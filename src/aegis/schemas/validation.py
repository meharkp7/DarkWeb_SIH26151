"""Schema validation gate used by CI (``scripts/validate_schemas.py``).

For every canonical schema this suite asserts that a valid example
serializes, round-trips through JSON, rejects unknown fields, rejects
missing required fields, and rejects unsupported schema versions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from aegis.schemas.base import CanonicalModel


@dataclass(frozen=True)
class ValidationResult:
    name: str
    ok: bool
    detail: str


def _dump(instance: BaseModel) -> dict[str, Any]:
    return instance.model_dump(mode="python")


def run_schema_validation_suite(name: str, schema: type[CanonicalModel]) -> ValidationResult:
    checks: list[str] = []
    try:
        # 1. valid example constructs
        example = schema.example()
        checks.append("example")

        # 2. python round-trip
        payload = _dump(example)
        rehydrated = schema.model_validate(payload)
        if rehydrated != example:
            return ValidationResult(name, False, "python round-trip mismatch")
        checks.append("round-trip")

        # 3. JSON round-trip
        json_payload = example.model_dump_json()
        from_json = schema.model_validate_json(json_payload)
        if from_json != example:
            return ValidationResult(name, False, "json round-trip mismatch")
        checks.append("json")

        # 4. schema version stamped and current
        if example.schema_version != schema.CURRENT_VERSION:
            return ValidationResult(
                name, False, f"schema_version {example.schema_version} != {schema.CURRENT_VERSION}"
            )
        checks.append("version")

        # 5. unknown field rejected
        try:
            schema.model_validate({**payload, "unexpected_field": "x"})
        except ValidationError:
            checks.append("extra-forbidden")
        else:
            return ValidationResult(name, False, "unknown field was accepted")

        # 6. missing required field rejected
        required = [
            field
            for field, info in schema.model_fields.items()
            if info.is_required() and field != "schema_version"
        ]
        if required:
            trimmed = dict(payload)
            trimmed.pop(required[0])
            try:
                schema.model_validate(trimmed)
            except ValidationError:
                checks.append("required")
            else:
                return ValidationResult(name, False, f"missing {required[0]} was accepted")

        # 7. unsupported historical version rejected
        try:
            schema.upgrade({"schema_version": "0.0-not-a-version"})
        except ValueError:
            checks.append("version-guard")
        else:
            if schema.MIGRATIONS:
                return ValidationResult(name, False, "unsupported version was accepted")

    except NotImplementedError as exc:
        return ValidationResult(name, False, str(exc))
    except Exception as exc:  # noqa: BLE001 - the gate must report, not crash
        return ValidationResult(name, False, f"{type(exc).__name__}: {exc}")

    return ValidationResult(name, True, ", ".join(checks))
