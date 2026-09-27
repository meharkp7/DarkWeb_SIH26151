from dataclasses import dataclass, replace

from aegis.synthetic.evidence import SyntheticEvidence


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    source_actor_id: str
    target_actor_id: str
    evidence: tuple[SyntheticEvidence, ...]
    expected_match: bool


class ScenarioBuilder:
    """Create deterministic evidence variations for evaluation."""

    def build(self, evidence: list[SyntheticEvidence]) -> list[ScenarioResult]:
        actor_ids = sorted({item.actor_id for item in evidence})

        if len(actor_ids) < 4:
            raise ValueError("Scenario evaluation requires at least four actors")

        results = [
            self._clean_strong(evidence, actor_ids[0], actor_ids[1]),
            self._clean_weak(evidence, actor_ids[2], actor_ids[3]),
            self._contradictory(evidence, actor_ids[0], actor_ids[2]),
            self._noisy_match(evidence, actor_ids[1], actor_ids[3]),
            self._no_match(evidence, actor_ids[0], actor_ids[3]),
        ]

        return results

    @staticmethod
    def _pair_evidence(
        evidence: list[SyntheticEvidence],
        source_id: str,
        target_id: str,
    ) -> list[SyntheticEvidence]:
        return [item for item in evidence if item.actor_id in {source_id, target_id}]

    def _clean_strong(
        self,
        evidence: list[SyntheticEvidence],
        source_id: str,
        target_id: str,
    ) -> ScenarioResult:
        """Existing controlled pair with multiple shared indicators."""
        relevant = self._pair_evidence(evidence, source_id, target_id)

        return ScenarioResult(
            name="clean_strong",
            source_actor_id=source_id,
            target_actor_id=target_id,
            evidence=tuple(relevant),
            expected_match=True,
        )

    def _clean_weak(
        self,
        evidence: list[SyntheticEvidence],
        source_id: str,
        target_id: str,
    ) -> ScenarioResult:
        """Existing controlled pair with only one shared indicator."""
        relevant = self._pair_evidence(evidence, source_id, target_id)

        return ScenarioResult(
            name="clean_weak",
            source_actor_id=source_id,
            target_actor_id=target_id,
            evidence=tuple(relevant),
            expected_match=True,
        )

    def _contradictory(
        self,
        evidence: list[SyntheticEvidence],
        source_id: str,
        target_id: str,
    ) -> ScenarioResult:
        """
        Inject one matching indicator while retaining conflicting
        contextual evidence.
        """
        relevant = self._pair_evidence(evidence, source_id, target_id)

        source_wallet = next(
            item
            for item in relevant
            if item.actor_id == source_id and item.evidence_type == "wallet"
        )

        mutated = [
            replace(
                item,
                value=source_wallet.value,
            )
            if item.actor_id == target_id and item.evidence_type == "wallet"
            else item
            for item in relevant
        ]

        return ScenarioResult(
            name="contradictory",
            source_actor_id=source_id,
            target_actor_id=target_id,
            evidence=tuple(mutated),
            expected_match=False,
        )

    def _noisy_match(
        self,
        evidence: list[SyntheticEvidence],
        source_id: str,
        target_id: str,
    ) -> ScenarioResult:
        """Inject one low-confidence accidental indicator overlap."""
        relevant = self._pair_evidence(evidence, source_id, target_id)

        source_wallet = next(
            item
            for item in relevant
            if item.actor_id == source_id and item.evidence_type == "wallet"
        )

        mutated = [
            replace(
                item,
                value=source_wallet.value,
                confidence=0.35,
            )
            if item.actor_id == target_id and item.evidence_type == "wallet"
            else item
            for item in relevant
        ]

        return ScenarioResult(
            name="noisy_match",
            source_actor_id=source_id,
            target_actor_id=target_id,
            evidence=tuple(mutated),
            expected_match=False,
        )

    def _no_match(
        self,
        evidence: list[SyntheticEvidence],
        source_id: str,
        target_id: str,
    ) -> ScenarioResult:
        """Pair with no intentionally shared indicators."""
        relevant = self._pair_evidence(evidence, source_id, target_id)

        return ScenarioResult(
            name="no_match",
            source_actor_id=source_id,
            target_actor_id=target_id,
            evidence=tuple(relevant),
            expected_match=False,
        )
