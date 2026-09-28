from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.base import RequestResponseEndpoint

from aegis.api.analysis import run_synthetic_analysis
from aegis.api.deps import get_db, get_evidence_service
from aegis.api.security import SECURITY_HEADERS, RequestRateLimiter, request_guard
from aegis.db.session import engine
from aegis.evidence.service import EvidenceService
from aegis.observability import Metrics
from aegis.schemas.analysis import (
    SyntheticAnalysisRequest,
    SyntheticAnalysisResponse,
)
from aegis.schemas.evidence import (
    Evidence,
    EvidenceCreate,
    EvidenceProvenance,
    SourceCreate,
    SourceType,
)
from aegis.settings import settings

app = FastAPI(title=settings.app_name, version="0.2.0")
_api_limiter = RequestRateLimiter()
_guard = request_guard(_api_limiter, max_bytes=1_048_576)
_metrics = Metrics()


@app.middleware("http")
async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    _metrics.increment(f"api.status.{response.status_code}")
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
    return {"counters": snapshot.counters, "latencies_ms": snapshot.latencies_ms}


@app.get("/health/db")
def database_health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "service": "postgres"}


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
