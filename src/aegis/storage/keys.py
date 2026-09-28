"""Object-name validation and the canonical evidence path layout.

Threat: object-name injection (``../../etc/passwd``, absolute paths, NUL
bytes, URL-encoded traversal) reaching a storage adapter. Every adapter
must build keys exclusively through this module.
"""

from __future__ import annotations

import re
from uuid import UUID

MAX_KEY_LENGTH = 1024

# Conservative allow-list: no spaces, no percent signs, no control chars.
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

#: Evidence package parts (spec §5/Phase 04).
PART_RAW = "raw"
PART_NORMALIZED = "normalized"
PART_METADATA = "metadata.json"
PARTS = (PART_RAW, PART_NORMALIZED, PART_METADATA)


class InvalidObjectKey(ValueError):
    """Raised when a key or key component fails validation."""


def validate_key(key: str) -> str:
    """Validate an object key and return it unchanged.

    Rejects: empty keys, traversal segments, absolute/relative paths,
    backslashes, control characters, and anything outside the allow-list.
    """
    if not key:
        raise InvalidObjectKey("object key must not be empty")
    if len(key) > MAX_KEY_LENGTH:
        raise InvalidObjectKey(f"object key exceeds {MAX_KEY_LENGTH} characters")
    if not _KEY_RE.match(key):
        raise InvalidObjectKey(f"object key contains disallowed characters: {key!r}")
    if "\\" in key:
        raise InvalidObjectKey("backslashes are not allowed in object keys")
    segments = key.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise InvalidObjectKey(f"path traversal or empty segment in key: {key!r}")
    if key.startswith("/"):
        raise InvalidObjectKey("absolute object keys are not allowed")
    return key


def validate_uuid_component(name: str, value: str) -> str:
    """Validate a UUID used as a path component (case or evidence id)."""
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidObjectKey(f"{name} must be a UUID: {value!r}") from exc
    if str(parsed) != value:
        raise InvalidObjectKey(f"{name} must be canonical lowercase UUID: {value!r}")
    return value


def evidence_package_key(
    *,
    year: int,
    month: int,
    case_id: str,
    evidence_id: str,
    part: str,
) -> str:
    """Build ``evidence/{year}/{month}/{case}/{evidence_id}/{part}``.

    Layout (Phase 04):

        evidence/{year}/{month}/{case}/{evidence_id}/
            raw
            normalized
            metadata.json
    """
    if not 1970 <= year <= 9999:
        raise InvalidObjectKey(f"invalid year component: {year}")
    if not 1 <= month <= 12:
        raise InvalidObjectKey(f"invalid month component: {month}")
    if part not in PARTS:
        raise InvalidObjectKey(f"unknown evidence package part: {part!r}")

    validate_uuid_component("case_id", case_id)
    validate_uuid_component("evidence_id", evidence_id)

    key = f"evidence/{year:04d}/{month:02d}/{case_id}/{evidence_id}/{part}"
    return validate_key(key)


def evidence_package_prefix(*, year: int, month: int, case_id: str, evidence_id: str) -> str:
    """Prefix covering an entire evidence package."""
    validate_uuid_component("case_id", case_id)
    validate_uuid_component("evidence_id", evidence_id)
    if not 1970 <= year <= 9999 or not 1 <= month <= 12:
        raise InvalidObjectKey(f"invalid timestamp components: {year}/{month}")
    prefix = f"evidence/{year:04d}/{month:02d}/{case_id}/{evidence_id}"
    return validate_key(prefix)
