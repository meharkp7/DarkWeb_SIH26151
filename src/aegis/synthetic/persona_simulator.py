"""Controllable, synthetic-only adversarial persona migrations (Phase 20)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import IntEnum

from aegis.synthetic.actor import SyntheticActor, SyntheticIdentity


class MigrationLevel(IntEnum):
    """Severity ladder specified by the implementation plan."""

    L1_ALIAS = 1
    L2_ALIAS_VOCABULARY = 2
    L3_ALIAS_VOCABULARY_BEHAVIOR = 3
    L4_ALIAS_VOCABULARY_BEHAVIOR_MARKETPLACE = 4
    L5_MULTIMODAL = 5


@dataclass(frozen=True)
class PersonaMigration:
    actor_id: str
    level: MigrationLevel
    original: SyntheticActor
    migrated: SyntheticActor
    changed_modalities: tuple[str, ...]


class AdversarialPersonaSimulator:
    """Creates deterministic variants without modelling or targeting real people."""

    _PLATFORM_ROTATION = {
        "forum_alpha": "market_beta",
        "market_beta": "paste_gamma",
        "paste_gamma": "chat_delta",
        "chat_delta": "forum_alpha",
    }
    _LANGUAGE_ROTATION = {"en": "de", "ru": "fr", "de": "es", "fr": "en", "es": "ru"}
    _TIMEZONE_ROTATION = {
        "UTC": "UTC+3",
        "UTC+1": "UTC-5",
        "UTC+2": "UTC",
        "UTC+3": "UTC+1",
        "UTC-5": "UTC+2",
    }

    def migrate(self, actor: SyntheticActor, level: MigrationLevel) -> PersonaMigration:
        alias = f"migrated_{self._digest(actor.actor_id + ':alias')}"
        migrated = replace(actor, alias=alias)
        changed = ["alias"]
        if level >= MigrationLevel.L2_ALIAS_VOCABULARY:
            # Language is the synthetic corpus' vocabulary/style proxy.
            indicators = (*actor.indicators[:2], self._digest(f"{actor.actor_id}:vocabulary"))
            migrated = replace(
                migrated,
                language=self._LANGUAGE_ROTATION[actor.language],
                indicators=indicators,
            )
            changed.append("vocabulary")
        if level >= MigrationLevel.L3_ALIAS_VOCABULARY_BEHAVIOR:
            migrated = replace(migrated, timezone=self._TIMEZONE_ROTATION[actor.timezone])
            changed.append("behavior")
        if level >= MigrationLevel.L4_ALIAS_VOCABULARY_BEHAVIOR_MARKETPLACE:
            identities = tuple(
                SyntheticIdentity(
                    platform=self._PLATFORM_ROTATION[identity.platform],
                    handle=f"{alias}_{self._digest(identity.identity_hash)}",
                    identity_hash=self._digest(f"{alias}:{identity.identity_hash}"),
                )
                for identity in actor.identities
            )
            migrated = replace(migrated, identities=identities)
            changed.append("marketplace")
        if level >= MigrationLevel.L5_MULTIMODAL:
            migrated = replace(
                migrated,
                indicators=tuple(
                    self._digest(f"{actor.actor_id}:rotated:{indicator}")
                    for indicator in migrated.indicators
                ),
            )
            changed.extend(("identifiers", "infrastructure"))
        return PersonaMigration(actor.actor_id, level, actor, migrated, tuple(changed))

    def generate(
        self, actors: list[SyntheticActor], level: MigrationLevel
    ) -> list[PersonaMigration]:
        return [self.migrate(actor, level) for actor in actors]

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:12]
