from dataclasses import dataclass


@dataclass(frozen=True)
class SyntheticIdentity:
    platform: str
    handle: str
    identity_hash: str


@dataclass(frozen=True)
class SyntheticActor:
    actor_id: str
    alias: str
    persona: str
    language: str
    timezone: str
    identities: tuple[SyntheticIdentity, ...]
    indicators: tuple[str, ...]
