from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from aegis.db.session import SessionLocal
from aegis.evidence.artifacts import ArtifactStore
from aegis.evidence.service import EvidenceService
from aegis.settings import settings


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_evidence_service(
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceService:
    return EvidenceService(
        db,
        ArtifactStore(settings.evidence_storage_path),
    )
