from uuid import UUID

from aegis.schemas.evidence import Evidence
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.persistence import SyntheticPersistenceService


class FakeEvidenceService:
    def __init__(self) -> None:
        self.sources = []
        self.evidence = []

    def create_source(self, payload):
        source = type(
            "Source",
            (),
            {"source_id": UUID("00000000-0000-0000-0000-000000000001")},
        )()
        self.sources.append(payload)
        return source

    def create_evidence(self, payload, artifact_bytes=None):
        self.evidence.append((payload, artifact_bytes))
        return Evidence(
            **payload.model_dump(),
            evidence_id=UUID("00000000-0000-0000-0000-000000000002"),
        )

    def get_by_sha256(self, sha256):
        for payload, _ in self.evidence:
            if payload.sha256 == sha256:
                return Evidence(
                    **payload.model_dump(),
                    evidence_id=UUID("00000000-0000-0000-0000-000000000002"),
                )
        return None


def test_create_source_uses_synthetic_type() -> None:
    fake = FakeEvidenceService()
    service = SyntheticPersistenceService(fake)

    source_id = service.create_source()

    assert source_id == UUID("00000000-0000-0000-0000-000000000001")
    assert fake.sources[0].name == "AEGIS Synthetic Generator"


def test_persist_evidence_uses_existing_evidence_layer() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    fake = FakeEvidenceService()
    service = SyntheticPersistenceService(fake)

    source_id = service.create_source()
    records = service.persist_evidence(source_id, actors, evidence)

    assert len(records) == len(evidence)
    assert len(fake.evidence) == len(evidence)

    payload, artifact = fake.evidence[0]

    assert payload.source_id == source_id
    assert payload.source_type.value == "synthetic"
    assert payload.metadata["synthetic"] is True
    assert artifact is not None
    assert len(payload.sha256) == 64
