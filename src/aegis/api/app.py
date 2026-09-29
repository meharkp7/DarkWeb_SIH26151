import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.middleware.base import RequestResponseEndpoint

from aegis.api.actor_links import router as actor_links_router
from aegis.api.actors import router as actors_router
from aegis.api.admin import router as admin_router
from aegis.api.analysis import run_synthetic_analysis
from aegis.api.auth import router as auth_router
from aegis.api.auth import validate_access_token
from aegis.api.collection import router as collection_router
from aegis.api.copilot import router as copilot_router
from aegis.api.deps import get_db, get_evidence_service
from aegis.api.infrastructure import router as infrastructure_router
from aegis.api.live import router as live_router
from aegis.api.personas import router as personas_router
from aegis.api.reports import router as reports_router
from aegis.api.search import router as search_router
from aegis.api.security import SECURITY_HEADERS, RequestRateLimiter, request_guard
from aegis.api.workspace import router as workspace_router
from aegis.db.audit import AuditService
from aegis.db.models import CaseRecord
from aegis.db.session import assert_postgres, engine
from aegis.evidence.search_index import EvidenceSearchIndexer
from aegis.evidence.service import EvidenceService
from aegis.observability import registry as _metrics
from aegis.schemas.analysis import (
    SyntheticAnalysisRequest,
    SyntheticAnalysisResponse,
)
from aegis.schemas.evidence import (
    Case,
    CaseCreate,
    CasePriority,
    CaseSeverity,
    CaseStatus,
    CaseUpdate,
    Evidence,
    EvidenceCreate,
    EvidenceProvenance,
    SourceCreate,
    SourceType,
)
from aegis.search.opensearch import OpenSearchAdapter
from aegis.settings import settings

app = FastAPI(title=settings.app_name, version="0.3.0")
app.include_router(auth_router)
_api_limiter = RequestRateLimiter()
_guard = request_guard(_api_limiter, max_bytes=1_048_576)

#: Paths reachable without the deployment-level API key. Unchanged from the
#: original inline set — extracted only so the middleware line fits in 100
#: columns. Do not widen without a deliberate access-control decision.
_PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/health/db",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/v1/auth/login",
    }
)


@app.on_event("startup")
def _verify_database() -> None:
    """Refuse to serve against a database that cannot support the platform.

    The audit chain takes a Postgres advisory lock, several analytics queries
    use DISTINCT ON and window functions, and the metadata columns are JSONB
    with containment queries. On another engine those fail at call time, deep
    inside a write, with an error that names a data structure rather than the
    cause — so the check happens here, once, and says what is wrong.
    """
    try:
        assert_postgres()
    except RuntimeError:
        logger.exception("Refusing to start: the configured database is not usable")
        raise


logger = logging.getLogger(__name__)

_cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        # Required for the split deployment: the console is served from Vercel
        # and calls this API on Render, so every request is cross-origin and
        # carries `credentials: "include"` alongside its Authorization header.
        #
        # Safe here because the allowlist is explicit. Credentials with a
        # wildcard origin is the dangerous combination, and Starlette rejects
        # it anyway — the origins have to be named, which is the property that
        # makes this safe rather than a blanket "allow everything".
        allow_credentials=True,
        # GET/POST cover the read + ingest surface, PATCH covers case triage.
        # OPTIONS is required for the preflight that a cross-origin request
        # with an Authorization header triggers; Starlette handles it, but the
        # verb has to be permitted for the preflight to be answered.
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Authorization", "X-AEGIS-API-Key"],
        # The console polls the health endpoint, and a cached 401 from a
        # preflight failure is indistinguishable from an expired session.
        expose_headers=["Retry-After"],
        max_age=600,
    )


@app.middleware("http")
async def api_key_auth(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Optional deployment-level API-key gate. Disabled by default for local development."""
    if request.url.path not in _PUBLIC_PATHS:
        supplied = request.headers.get("X-AEGIS-API-Key")
        bearer = request.headers.get("Authorization", "")
        token = bearer.removeprefix("Bearer ").strip() if bearer.startswith("Bearer ") else ""
        api_ok = bool(
            settings.enable_api_key_auth and settings.api_key and supplied == settings.api_key
        )
        session_ok = bool(token and validate_access_token(token) is not None)
        if not api_ok and not session_ok:
            return Response(status_code=401, content="authentication required")
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    started = perf_counter()
    response = await call_next(request)
    _metrics.increment(f"api.status.{response.status_code}")
    _metrics.observe_latency("api.request", (perf_counter() - started) * 1000.0)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/metrics")
def metrics() -> dict[str, object]:
    """Operational snapshot; deploy behind operator authentication in production."""
    snapshot = _metrics.snapshot()
    return {
        "counters": snapshot.counters,
        "latencies_ms": snapshot.latencies_ms,
        "histograms_ms": snapshot.histograms_ms,
        "gauges": snapshot.gauges,
        "ml": snapshot.ml,
    }


@app.get("/health/db")
def database_health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "service": "postgres"}


def _case_schema(record: CaseRecord) -> Case:
    return Case(
        case_id=record.case_id,
        name=record.name,
        description=record.description,
        status=CaseStatus(record.status),
        priority=CasePriority(record.priority),
        severity=CaseSeverity(record.severity),
        tags=tuple(record.tags or ()),
        assigned_to=record.assigned_to,
        sla_due_at=record.sla_due_at,
        closed_at=record.closed_at,
        closure_reason=record.closure_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@app.get("/api/v1/cases", response_model=list[Case])
def list_cases(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Case]:
    records = db.scalars(
        select(CaseRecord).order_by(CaseRecord.created_at.desc()).limit(limit)
    ).all()
    return [_case_schema(record) for record in records]


@app.post("/api/v1/cases", response_model=Case, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(_guard)],
) -> Case:
    record = CaseRecord(
        name=payload.name,
        description=payload.description,
        priority=payload.priority.value,
        severity=payload.severity.value,
        tags=list(payload.tags),
        assigned_to=payload.assigned_to,
        sla_due_at=payload.sla_due_at,
    )
    db.add(record)
    db.flush()
    AuditService(db).record(
        "case.created",
        case_id=record.case_id,
        entity_type="case",
        entity_id=str(record.case_id),
        payload={"name": record.name, "priority": record.priority},
    )
    db.commit()
    db.refresh(record)
    return _case_schema(record)


@app.get("/api/v1/cases/{case_id}", response_model=Case)
def get_case(case_id: UUID, db: Annotated[Session, Depends(get_db)]) -> Case:
    record = db.get(CaseRecord, case_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return _case_schema(record)


@app.patch("/api/v1/cases/{case_id}", response_model=Case)
def update_case(
    case_id: UUID,
    payload: CaseUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(_guard)],
) -> Case:
    """Partial triage update.

    Only keys actually present in the request body are applied, so omitting a
    field never clears it. ``tags`` replaces the whole list rather than
    merging, which keeps "remove the last tag" expressible.

    Closing a case requires a closure reason — supplied now, or already
    stored from a previous close. The same rule is enforced independently by
    the ``ck_cases_closure_reason`` CHECK constraint, so no code path can
    produce a reasonless closed case.
    """
    record = db.get(CaseRecord, case_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    changes = payload.supplied()
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No updatable fields supplied",
        )

    previous_status = record.status

    if "name" in changes and payload.name is not None:
        record.name = payload.name
    if "description" in changes:
        record.description = payload.description
    if "priority" in changes and payload.priority is not None:
        record.priority = payload.priority.value
    if "severity" in changes and payload.severity is not None:
        record.severity = payload.severity.value
    if "tags" in changes and payload.tags is not None:
        record.tags = list(payload.tags)
    if "assigned_to" in changes:
        record.assigned_to = payload.assigned_to
    if "sla_due_at" in changes:
        record.sla_due_at = payload.sla_due_at
    if "closure_reason" in changes:
        record.closure_reason = payload.closure_reason

    if "status" in changes and payload.status is not None:
        new_status = payload.status.value
        if new_status != previous_status:
            if new_status == "closed":
                reason = payload.closure_reason or record.closure_reason
                if reason is None or not reason.strip():
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="closure_reason is required to close a case",
                    )
                record.closure_reason = reason
                record.closed_at = datetime.now(UTC)
            else:
                # Re-opening clears the closure record so a later close has to
                # state a fresh reason rather than inheriting a stale one.
                record.closed_at = None
                record.closure_reason = None
        record.status = new_status

    AuditService(db).record(
        "case.updated",
        case_id=record.case_id,
        entity_type="case",
        entity_id=str(record.case_id),
        payload={
            "changed": sorted(changes),
            "from_status": previous_status,
            "to_status": record.status,
        },
    )
    db.commit()
    db.refresh(record)
    return _case_schema(record)


@app.post("/api/v1/sources", response_model=dict[str, object], status_code=status.HTTP_201_CREATED)
def create_source(
    payload: SourceCreate,
    service: Annotated[EvidenceService, Depends(get_evidence_service)],
    _: Annotated[None, Depends(_guard)],
) -> dict[str, object]:
    source = service.create_source(payload)
    return {
        "source_id": str(source.source_id),
        "source_type": source.source_type,
        "name": source.name,
        "reliability": source.reliability,
    }


@app.post("/api/v1/evidence", response_model=Evidence, status_code=status.HTTP_201_CREATED)
def create_evidence(
    payload: EvidenceCreate,
    service: Annotated[EvidenceService, Depends(get_evidence_service)],
    _: Annotated[None, Depends(_guard)],
) -> Evidence:
    try:
        record = service.create_evidence(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    search = OpenSearchAdapter(
        settings.opensearch_url,
        index_prefix=settings.opensearch_index_prefix,
        http_auth=(
            (settings.opensearch_username, settings.opensearch_password)
            if settings.opensearch_username is not None and settings.opensearch_password is not None
            else None
        ),
    )
    EvidenceSearchIndexer(search).index(record)

    return Evidence(
        **payload.model_dump(),
        evidence_id=record.evidence_id,
        artifact_id=record.artifact_id,
        created_at=record.created_at,
    )


@app.get("/api/v1/evidence/{evidence_id}", response_model=Evidence)
def get_evidence(
    evidence_id: UUID,
    service: Annotated[EvidenceService, Depends(get_evidence_service)],
) -> Evidence:
    record = service.get(evidence_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    return Evidence(
        case_id=record.case_id,
        source_id=record.source_id,
        source_type=SourceType(record.source_type),
        observed_at=record.observed_at,
        collected_at=record.collected_at,
        entity_type=record.entity_type,
        entity_value_hash=record.entity_value_hash,
        context_hash=record.context_hash,
        raw_artifact_uri=record.raw_artifact_uri,
        sha256=record.sha256,
        collector_name=record.collector_name,
        collector_version=record.collector_version,
        normalizer_version=record.normalizer_version,
        extraction_version=record.extraction_version,
        source_reliability=record.source_reliability,
        independence_group=record.independence_group,
        metadata=record.metadata_json,
        evidence_id=record.evidence_id,
        artifact_id=record.artifact_id,
        created_at=record.created_at,
    )


@app.get("/api/v1/evidence/{evidence_id}/provenance", response_model=EvidenceProvenance)
def get_provenance(
    evidence_id: UUID,
    service: Annotated[EvidenceService, Depends(get_evidence_service)],
) -> EvidenceProvenance:
    try:
        return service.provenance(evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.post(
    "/api/v1/analysis/synthetic",
    response_model=SyntheticAnalysisResponse,
)
def synthetic_analysis(
    payload: SyntheticAnalysisRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(_guard)],
) -> SyntheticAnalysisResponse:
    return run_synthetic_analysis(payload, db)


app.include_router(copilot_router)
app.include_router(reports_router)
app.include_router(live_router)
app.include_router(workspace_router)
app.include_router(admin_router)
# BEFORE the actor router, not after. FastAPI matches in registration order,
# so `/actors/{actor_id}` swallows `/actors/graph` and `/actors/links` if it
# is registered first — and a path parameter that fails to parse as a UUID
# yields 422, not the 200 the link endpoints are supposed to return.
app.include_router(actor_links_router)
app.include_router(actors_router)
app.include_router(search_router)
app.include_router(infrastructure_router)
app.include_router(personas_router)
app.include_router(collection_router)
