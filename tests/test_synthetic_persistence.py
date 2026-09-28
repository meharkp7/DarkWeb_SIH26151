from hashlib import sha256
from uuid import UUID, uuid4

from aegis.schemas.evidence import Evidence
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.persistence import SyntheticPersistenceService


class _FakeDb:
    """Session stand-in: only the transaction boundary is observable."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeEvidenceService:
    """EvidenceService double: records traffic, answers digest lookups."""

    def __init__(self, existing: dict[str, Evidence] | None = None) -> None:
        self.sources = []
        self.evidence = []
        self.db = _FakeDb()
        #: one entry per get_by_sha256_batch call (the batched prefetch)
        self.batch_calls: list[tuple[str, ...]] = []
        #: rows that predate this call (content-level reuse)
        self.existing: dict[str, Evidence] = dict(existing or {})
        #: commit kwarg observed on every create_evidence call
        self.commit_flags: list[bool] = []

    def create_source(self, payload, *, commit=True):
        source = type(
            "Source",
            (),
            {"source_id": UUID("00000000-0000-0000-0000-000000000001")},
        )()
        self.sources.append(payload)
        return source

    def create_evidence(self, payload, artifact_bytes=None, *, commit=True):
        self.commit_flags.append(commit)
        self.evidence.append((payload, artifact_bytes))
        record = Evidence(
            **payload.model_dump(),
            evidence_id=uuid4(),
        )
        # rows created earlier in the same process are visible to later
        # lookups, mirroring the real session's flushed state
        self.existing[payload.sha256] = record
        return record

    def get_by_sha256(self, sha256_value):
        return self.existing.get(sha256_value)

    def get_by_sha256_batch(self, sha256s):
        self.batch_calls.append(tuple(sha256s))
        return {digest: self.existing[digest] for digest in sha256s if digest in self.existing}


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


def test_persist_evidence_prefetches_every_digest_in_one_batch_query() -> None:
    """The content-digest idempotency check must not scale with row count."""
    actors = SyntheticActorGenerator(seed=26151).generate(3)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    assert len(evidence) > 1

    fake = FakeEvidenceService()
    service = SyntheticPersistenceService(fake)

    service.persist_evidence(service.create_source(), actors, evidence)

    assert len(fake.batch_calls) == 1, "one prefetch for the whole batch, not one per row"
    digests = set(fake.batch_calls[0])
    assert len(digests) == len(evidence)
    assert all(len(digest) == 64 for digest in digests)


def test_persist_evidence_reuses_rows_created_within_the_same_batch() -> None:
    """A digest repeated inside one batch resolves to the first row, exactly as
    a per-item get_by_sha256 would have after that row was committed."""
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    duplicate = evidence[0]

    fake = FakeEvidenceService()
    service = SyntheticPersistenceService(fake)

    records = service.persist_evidence(service.create_source(), actors, [duplicate, duplicate])

    assert len(fake.evidence) == 1, "second item must reuse the first, not insert again"
    assert records[0].evidence_id == records[1].evidence_id
    assert len(fake.batch_calls) == 1


def test_persist_evidence_reuses_preexisting_content_digest() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)
    item = evidence[0]
    actor = next(a for a in actors if a.actor_id == item.actor_id)
    digest = sha256(SyntheticPersistenceService._serialize_evidence(actor, item)).hexdigest()

    prior = Evidence(
        source_id=UUID("00000000-0000-0000-0000-000000000009"),
        source_type="synthetic",
        observed_at=item.observed_at,
        collected_at=item.observed_at,
        raw_artifact_uri=f"synthetic://evidence/{item.evidence_id}",
        sha256=digest,
        collector_name="prior",
        collector_version="0.1.0",
        source_reliability=1.0,
        independence_group="prior",
        evidence_id=UUID("00000000-0000-0000-0000-00000000000a"),
    )

    fake = FakeEvidenceService(existing={digest: prior})
    service = SyntheticPersistenceService(fake)

    records = service.persist_evidence(service.create_source(), actors, [item])

    assert records[0].evidence_id == prior.evidence_id
    assert fake.evidence == [], "preexisting content must be reused, not re-inserted"


def test_persist_evidence_flushes_without_committing() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)
    evidence, _ = SyntheticEvidenceGenerator(seed=26151).generate(actors)

    fake = FakeEvidenceService()
    service = SyntheticPersistenceService(fake)

    service.persist_evidence(service.create_source(), actors, evidence)

    assert fake.db.commits == 0, "the enclosing analysis transaction commits once"
    assert fake.commit_flags, "rows were inserted"
    assert set(fake.commit_flags) == {False}, "inserts must be flush-only (commit=False)"


def test_persist_evidence_with_no_items_still_returns_empty() -> None:
    actors = SyntheticActorGenerator(seed=26151).generate(2)

    fake = FakeEvidenceService()
    service = SyntheticPersistenceService(fake)

    records = service.persist_evidence(service.create_source(), actors, [])

    assert records == []
    assert fake.evidence == []
    assert fake.db.commits == 0
