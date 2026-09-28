"""Versioned base contract for every canonical AEGIS schema.

Rules enforced here:

* ``extra="forbid"`` — payloads with unknown fields are rejected.
* ``schema_version`` — every payload carries an explicit version.
* Backwards-compatible upgrades — older versions are migrated to the
  current version through per-model ``MIGRATIONS``; unknown versions are
  rejected instead of being silently coerced.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

Payload = dict[str, Any]
Migration = Callable[[Payload], Payload]


class CanonicalModel(BaseModel):
    """Base class for all canonical AEGIS schemas."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=True,
    )

    #: Declared by subclasses; the version this class currently speaks.
    CURRENT_VERSION: ClassVar[str] = "1.0"

    #: Maps an older ``schema_version`` to a function producing the next payload.
    MIGRATIONS: ClassVar[Mapping[str, Migration]] = {}

    schema_version: str = Field(
        default="",
        min_length=1,
        max_length=16,
        description="Semantic schema version of this payload (e.g. '1.0'). "
        "Injected as CURRENT_VERSION when absent.",
    )

    @classmethod
    def upgrade(cls, payload: Payload) -> Payload:
        """Migrate *payload* forward until it reaches ``CURRENT_VERSION``."""
        working = dict(payload)
        seen: set[str] = set()
        while (version := str(working.get("schema_version", cls.CURRENT_VERSION))) != (
            cls.CURRENT_VERSION
        ):
            if version in seen:
                raise ValueError(f"{cls.__name__}: cyclic schema migration at {version}")
            seen.add(version)
            migration = cls.MIGRATIONS.get(version)
            if migration is None:
                raise ValueError(
                    f"{cls.__name__}: unsupported schema_version {version!r}; "
                    f"supported: {sorted({cls.CURRENT_VERSION, *cls.MIGRATIONS.keys()})}"
                )
            working = migration(working)
        working["schema_version"] = cls.CURRENT_VERSION
        return working

    @model_validator(mode="before")
    @classmethod
    def _apply_upgrade(cls, data: Any) -> Any:
        if isinstance(data, dict):
            payload: Payload = dict(data)
            payload.setdefault("schema_version", cls.CURRENT_VERSION)
            return cls.upgrade(payload)
        return data

    @classmethod
    def example(cls) -> CanonicalModel:
        """Return a valid instance; used by the schema validation gate."""
        raise NotImplementedError(f"{cls.__name__} must implement example()")


def rename_field(payload: Payload, old: str, new: str) -> Payload:
    """Copy *payload* with field *old* renamed to *new*, dropping the old key.

    Used by ``MIGRATIONS`` implementations so renamed keys never leak through
    ``extra="forbid"`` validation.
    """
    out = dict(payload)
    value = out.pop(old, None)
    if value is not None:
        out[new] = value
    return out


def migrate(
    payload: Payload,
    target: str,
    *,
    renames: tuple[tuple[str, str], ...] = (),
    drops: tuple[str, ...] = (),
    defaults: Mapping[str, Any] | None = None,
) -> Payload:
    """Standard migration primitive: rename/drop/default fields and stamp *target*.

    Every ``MIGRATIONS`` entry must stamp the next version so ``upgrade()``
    terminates; using this helper guarantees that.
    """
    out = dict(payload)
    for old, new in renames:
        value = out.pop(old, None)
        if value is not None:
            out[new] = value
    for key in drops:
        out.pop(key, None)
    for key, value in (defaults or {}).items():
        out.setdefault(key, value)
    out["schema_version"] = target
    return out
