"""Deterministic entity extractors (Phase 07).

Each extractor turns text into :class:`EntityMatch` candidates with a
span, a normalized form, and a confidence grounded in validation:

======================  ==========  ==========================================
type                   confidence  basis
======================  ==========  ==========================================
url                    0.95        scheme parsed, host present
onion_service (v3)     0.98        SHA3-256 checksum verified
wallet_address         0.95        base58check / bech32 / EIP-55 verified
pgp_key (grouped)      0.95        canonical grouped fingerprint form
email_identifier       0.90        structure + TLD allow-list
domain                 0.90        TLD allow-list (0.95 with scheme/www)
pgp_key (raw)          0.80        40 hex chars, strict boundaries
handle                 0.85        @-prefixed, boundary constrained
wallet (eth structural) 0.80       no EIP-55 case to verify
onion_service (v2)     0.60        no checksum exists; flagged legacy
==========================  ==========================================

Extraction is intentionally conservative: a candidate that fails
validation is dropped, not downgraded.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from aegis.extraction import patterns
from aegis.ontology import EntityType


@dataclass(frozen=True)
class EntityMatch:
    """One extracted occurrence: type + span + normalized form."""

    entity_type: EntityType
    start: int
    end: int
    normalized_form: str
    confidence: float
    surface_form: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int, int]:
        """Dedup key: same type at the same span is the same match."""
        return (self.entity_type.value, self.start, self.end)


class BaseExtractor(ABC):
    """Contract every deterministic extractor implements."""

    name: str = "extractor"
    entity_types: frozenset[EntityType] = frozenset()

    @abstractmethod
    def extract(self, text: str) -> list[EntityMatch]:
        """Return validated matches found in *text* (sorted by span)."""


def _match(
    entity_type: EntityType,
    text: str,
    start: int,
    end: int,
    normalized: str,
    confidence: float,
    **metadata: Any,
) -> EntityMatch:
    return EntityMatch(
        entity_type=entity_type,
        start=start,
        end=end,
        surface_form=text[start:end],
        normalized_form=normalized,
        confidence=confidence,
        metadata=dict(metadata),
    )


class EmailExtractor(BaseExtractor):
    name = "email"
    entity_types = frozenset({EntityType.EMAIL_IDENTIFIER})

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        for match in patterns.EMAIL_RE.finditer(text):
            domain = match.group("domain") + "." + match.group("tld")
            if not patterns.domain_looks_like_host(domain, text[: match.start()]):
                continue
            matches.append(
                _match(
                    EntityType.EMAIL_IDENTIFIER,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_email(match.group(0)),
                    0.90,
                    domain=patterns.normalize_domain(domain),
                )
            )
        return matches


class OnionExtractor(BaseExtractor):
    name = "onion"
    entity_types = frozenset({EntityType.ONION_SERVICE})

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        for version, regex, confidence in (
            (3, patterns.ONION_V3_RE, 0.98),
            (2, patterns.ONION_V2_RE, 0.60),
        ):
            for match in regex.finditer(text):
                address = match.group("addr")
                if not patterns.is_valid_onion(address, version=version):
                    continue
                matches.append(
                    _match(
                        EntityType.ONION_SERVICE,
                        text,
                        match.start(),
                        match.end(),
                        patterns.normalize_onion(address),
                        confidence,
                        onion_version=version,
                        legacy=version == 2,
                    )
                )
        return matches


class UrlExtractor(BaseExtractor):
    name = "url"
    entity_types = frozenset({EntityType.URL})

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        for match in patterns.URL_RE.finditer(text):
            raw = match.group("url")
            # Span covers the URL proper; trailing sentence punctuation
            # belongs to the sentence, not the URL.
            trimmed = raw.rstrip(patterns.URL_TRAILING_PUNCTUATION)
            if not trimmed:
                continue
            normalized = patterns.normalize_url(trimmed)
            if normalized is None:
                continue
            end = match.start() + len(trimmed)
            matches.append(
                _match(
                    EntityType.URL,
                    text,
                    match.start(),
                    end,
                    normalized,
                    0.95,
                    host=patterns.url_domain(trimmed),
                )
            )
        return matches


class WalletExtractor(BaseExtractor):
    name = "wallet"
    entity_types = frozenset({EntityType.WALLET_ADDRESS})

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []

        for match in patterns.WALLET_BTC_BECH32_RE.finditer(text):
            address = match.group("addr")
            if not patterns.is_valid_btc_bech32(address):
                continue
            matches.append(
                _match(
                    EntityType.WALLET_ADDRESS,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_wallet(address),
                    0.95,
                    network_hint="bitcoin",
                    scheme="bech32",
                )
            )

        for match in patterns.WALLET_BTC_BASE58_RE.finditer(text):
            address = match.group("addr")
            if not patterns.is_valid_btc_base58(address):
                continue
            matches.append(
                _match(
                    EntityType.WALLET_ADDRESS,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_wallet(address),
                    0.95,
                    network_hint="bitcoin",
                    scheme="base58check",
                )
            )

        for match in patterns.WALLET_ETH_RE.finditer(text):
            address = match.group("addr")
            status = patterns.eth_checksum_status(address)
            if status == "invalid":
                continue
            confidence = 0.95 if status == "checksum" else 0.80
            matches.append(
                _match(
                    EntityType.WALLET_ADDRESS,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_wallet("0x" + address),
                    confidence,
                    network_hint="ethereum",
                    eip55=status,
                )
            )
        return matches


class PgpExtractor(BaseExtractor):
    name = "pgp"
    entity_types = frozenset({EntityType.PGP_KEY})

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        consumed: list[tuple[int, int]] = []

        for match in patterns.PGP_GROUPED_RE.finditer(text):
            fingerprint = match.group("fp")
            consumed.append((match.start(), match.end()))
            matches.append(
                _match(
                    EntityType.PGP_KEY,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_pgp(fingerprint),
                    0.95,
                    format="grouped",
                )
            )

        for match in patterns.PGP_RAW_RE.finditer(text):
            if any(start <= match.start() < end for start, end in consumed):
                continue
            fingerprint = match.group("fp")
            matches.append(
                _match(
                    EntityType.PGP_KEY,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_pgp(fingerprint),
                    0.80,
                    format="raw",
                )
            )
        return matches


class DomainExtractor(BaseExtractor):
    name = "domain"
    entity_types = frozenset({EntityType.DOMAIN})

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        for match in patterns.DOMAIN_RE.finditer(text):
            domain = match.group("domain")
            preceding = text[: match.start()]
            if not patterns.domain_looks_like_host(domain, preceding):
                continue
            context_trusted = preceding[-8:].lower().endswith(("://", "www.", "//"))
            matches.append(
                _match(
                    EntityType.DOMAIN,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_domain(domain),
                    0.95 if context_trusted else 0.90,
                    tld=match.group("tld").lower(),
                )
            )
        return matches


class HandleExtractor(BaseExtractor):
    name = "handle"
    entity_types = frozenset({EntityType.HANDLE})

    def extract(self, text: str) -> list[EntityMatch]:
        matches: list[EntityMatch] = []
        for match in patterns.HANDLE_RE.finditer(text):
            handle = match.group("handle")
            # "user@domain" must never harvest the domain as a handle:
            # the email extractor owns that span (boundary rules above
            # already block it, this is a final guard).
            preceding = text[: match.start()].rstrip()
            if preceding.endswith("@"):
                continue
            matches.append(
                _match(
                    EntityType.HANDLE,
                    text,
                    match.start(),
                    match.end(),
                    patterns.normalize_handle(handle),
                    0.85,
                )
            )
        return matches


#: Default deterministic extractor fleet, highest-priority first.
DEFAULT_EXTRACTORS: tuple[BaseExtractor, ...] = (
    UrlExtractor(),
    EmailExtractor(),
    OnionExtractor(),
    WalletExtractor(),
    PgpExtractor(),
    DomainExtractor(),
    HandleExtractor(),
)


def extract_all(
    text: str, extractors: Sequence[BaseExtractor] = DEFAULT_EXTRACTORS
) -> list[EntityMatch]:
    """Run extractors, drop duplicate (type, span) matches, sort by span."""
    seen: dict[tuple[str, int, int], EntityMatch] = {}
    for extractor in extractors:
        for candidate in extractor.extract(text):
            if candidate.key not in seen:
                seen[candidate.key] = candidate
    return sorted(seen.values(), key=lambda m: (m.start, m.end, m.entity_type.value))
