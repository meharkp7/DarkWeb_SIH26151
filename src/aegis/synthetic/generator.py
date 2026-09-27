import hashlib
import random
from collections.abc import Sequence

from aegis.synthetic.actor import SyntheticActor, SyntheticIdentity


class SyntheticActorGenerator:
    """Generate deterministic synthetic threat-actor profiles for testing."""

    _PERSONAS: tuple[str, ...] = (
        "broker",
        "developer",
        "operator",
        "seller",
        "researcher",
    )

    _LANGUAGES: tuple[str, ...] = (
        "en",
        "ru",
        "de",
        "fr",
        "es",
    )

    _TIMEZONES: tuple[str, ...] = (
        "UTC",
        "UTC+1",
        "UTC+2",
        "UTC+3",
        "UTC-5",
    )

    _PLATFORMS: tuple[str, ...] = (
        "forum_alpha",
        "market_beta",
        "paste_gamma",
        "chat_delta",
    )

    def __init__(self, seed: int = 26151) -> None:
        self.seed = seed

    def generate(self, count: int = 10) -> list[SyntheticActor]:
        if count < 1:
            raise ValueError("count must be greater than zero")

        rng = random.Random(self.seed)
        actors: list[SyntheticActor] = []

        for index in range(count):
            actor_id = f"actor-{index + 1:04d}"
            alias = f"synthetic_{self.seed}_{index + 1:04d}"

            platforms = self._sample_platforms(rng)
            identities = tuple(
                self._make_identity(actor_id, alias, platform) for platform in platforms
            )

            indicators = (
                self._stable_hash(f"{actor_id}:email"),
                self._stable_hash(f"{actor_id}:wallet"),
                self._stable_hash(f"{actor_id}:style"),
            )

            # Controlled synthetic benchmark links.
            # These create known positive relationships without changing
            # the candidate-link scoring logic.
            if index == 1:
                reference_id = "actor-0001"
                indicators = (
                    self._stable_hash(f"{reference_id}:email"),
                    self._stable_hash(f"{reference_id}:wallet"),
                    indicators[2],
                )
            elif index == 3:
                reference_id = "actor-0003"
                indicators = (
                    indicators[0],
                    indicators[1],
                    self._stable_hash(f"{reference_id}:style"),
                )

            actors.append(
                SyntheticActor(
                    actor_id=actor_id,
                    alias=alias,
                    persona=rng.choice(self._PERSONAS),
                    language=rng.choice(self._LANGUAGES),
                    timezone=rng.choice(self._TIMEZONES),
                    identities=identities,
                    indicators=indicators,
                )
            )

        return actors

    @staticmethod
    def _sample_platforms(rng: random.Random) -> Sequence[str]:
        count = rng.randint(2, 3)
        return rng.sample(SyntheticActorGenerator._PLATFORMS, count)

    @staticmethod
    def _make_identity(
        actor_id: str,
        alias: str,
        platform: str,
    ) -> SyntheticIdentity:
        handle_hash = hashlib.sha256(f"{actor_id}:{platform}".encode()).hexdigest()[:12]

        return SyntheticIdentity(
            platform=platform,
            handle=f"{alias}_{handle_hash}",
            identity_hash=hashlib.sha256(f"{platform}:{handle_hash}".encode()).hexdigest(),
        )

    @staticmethod
    def _stable_hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
