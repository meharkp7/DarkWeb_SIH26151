"""Validate that every canonical schema serializes, rejects bad input, and round-trips.

Run by CI as the schema-validation gate:
    PYTHONPATH=src uv run python scripts/validate_schemas.py
"""

from __future__ import annotations

import sys

from aegis.schemas import CANONICAL_SCHEMAS
from aegis.schemas.validation import run_schema_validation_suite


def main() -> int:
    failures: list[str] = []

    for name, schema in sorted(CANONICAL_SCHEMAS.items()):
        result = run_schema_validation_suite(name, schema)
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {name:<28} {result.detail}")
        if not result.ok:
            failures.append(name)

    print(f"\n{len(CANONICAL_SCHEMAS) - len(failures)}/{len(CANONICAL_SCHEMAS)} schemas valid")
    if failures:
        print(f"failed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
