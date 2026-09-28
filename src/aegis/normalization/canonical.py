"""Canonical text encoding and metadata normalization (Phase 06).

Pipeline position 1–2: ``raw -> canonical encoding -> metadata
normalization -> exact hash``.

Canonical encoding is deliberately conservative: it removes encoding
noise (Unicode compatibility forms, zero-width characters, HTML markup,
collapsible whitespace) so that trivially re-rendered copies hash
identically, while preserving the analyst-visible wording.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

CANONICAL_VERSION = "0.1.0"

_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")
_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]{1,500}>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)

#: Metadata keys dropped before hashing: collection-time noise must not
#: change whether two fetches are "the same" observation.
VOLATILE_METADATA_KEYS = frozenset(
    {
        "fetched_at",
        "collected_at",
        "request_id",
        "trace_id",
        "duration_ms",
        "retry_count",
        "http_status",
        "etag",
        "last_modified",
    }
)


def strip_html(text: str) -> str:
    """Remove script/style blocks and tags, decode entities."""
    without_blocks = _SCRIPT.sub(" ", text)
    without_tags = _TAG.sub(" ", without_blocks)
    return html.unescape(without_tags)


def canonical_text(text: str, *, html_input: bool = False) -> str:
    """Encoding-stable canonical form of *text*.

    Steps: optional HTML strip → NFKC → remove zero-width characters →
    collapse whitespace → strip. Case is preserved.
    """
    value = strip_html(text) if html_input or "<" in text and ">" in text else text
    value = unicodedata.normalize("NFKC", value)
    value = _ZERO_WIDTH.sub("", value)
    value = _WS.sub(" ", value)
    return value.strip()


def normalized_text(text: str, *, html_input: bool = False) -> str:
    """Case-folded canonical form used for exact-copy detection."""
    return canonical_text(text, html_input=html_input).casefold()


def normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Stable metadata: volatile keys removed, values trimmed/sorted.

    Returns a JSON-round-trippable dict with deterministic key order so
    two fetches of the same observation produce identical bytes.
    """

    def _clean(value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return {
                key: _clean(item)
                for key, item in sorted(value.items())
                if key not in VOLATILE_METADATA_KEYS
            }
        if isinstance(value, (list, tuple)):
            return [_clean(item) for item in value]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)

    return {
        key: _clean(value)
        for key, value in sorted(metadata.items())
        if key not in VOLATILE_METADATA_KEYS
    }
