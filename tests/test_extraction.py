"""Phase 07 entity extraction tests: exact extraction and false-positive
cases for every deterministic extractor, plus domain NER and pipeline
provenance.
"""

from __future__ import annotations

import base64
import hashlib
from uuid import uuid4

import pytest

from aegis.extraction import (
    ExtractionPipeline,
    PlatformMentionExtractor,
    RoleCueAliasExtractor,
)
from aegis.extraction.extractors import EntityMatch, extract_all
from aegis.ontology import EntityType
from aegis.schemas.entity import Entity

# Verified fixtures (checksum-valid / spec vectors)
BTC_BECH32 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
BTC_BASE58 = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
ETH_EIP55 = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
ETH_BAD_CASE = "0x5aaeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
PGP_GROUPED = "ABCD EF01 2345 6789 ABCD EF01 2345 6789 ABCD EF01"
PGP_RAW = "abcdef0123456789abcdef0123456789abcdef01"
SHA256_BLOB = "d" * 64


def _make_onion_v3() -> str:
    """Construct a checksum-valid v3 address from the Tor spec."""
    public_key = bytes(range(32))
    version = b"\x03"
    checksum = hashlib.sha3_256(b".onion checksum" + public_key + version).digest()[:2]
    encoded = base64.b32encode(public_key + checksum + version).decode("ascii")
    return encoded.lower() + ".onion"


ONION_V3 = _make_onion_v3()
ONION_V2 = "expyuzz4wqqyqhjn.onion"


def _pipeline() -> ExtractionPipeline:
    return ExtractionPipeline()


def _types(matches: list[EntityMatch]) -> set[EntityType]:
    return {match.entity_type for match in matches}


# ------------------------------------------------------ exact extraction


def test_email_extraction() -> None:
    text = "Escrow questions? Mail vendor.alpha+3@sub.example.org now."
    matches = _pipeline().extract_matches(text)
    emails = [m for m in matches if m.entity_type == EntityType.EMAIL_IDENTIFIER]
    assert len(emails) == 1
    match = emails[0]
    assert match.normalized_form == "vendor.alpha+3@sub.example.org"
    assert match.metadata["domain"] == "sub.example.org"
    assert text[match.start : match.end] == "vendor.alpha+3@sub.example.org"
    assert match.confidence == 0.90


def test_handle_extraction() -> None:
    text = "ping @Ghost_Broker and @alice2 about the order"
    matches = _pipeline().extract_matches(text)
    handles = [m for m in matches if m.entity_type == EntityType.HANDLE]
    assert [h.normalized_form for h in handles] == ["ghost_broker", "alice2"]
    for handle in handles:
        assert text[handle.start] == "@"


def test_email_domain_is_not_harvested_as_handle() -> None:
    matches = _pipeline().extract_matches("write to someone@example.com today")
    assert _types(matches) >= {EntityType.EMAIL_IDENTIFIER, EntityType.DOMAIN}
    assert EntityType.HANDLE not in _types(matches)


def test_pgp_grouped_and_raw_extraction() -> None:
    pipeline = _pipeline()
    grouped = pipeline.extract_matches(f"My key: {PGP_GROUPED} or contact me")
    pgp_grouped = [m for m in grouped if m.entity_type == EntityType.PGP_KEY]
    assert len(pgp_grouped) == 1
    assert pgp_grouped[0].normalized_form == PGP_GROUPED.replace(" ", "").lower()
    assert pgp_grouped[0].confidence == 0.95
    assert pgp_grouped[0].metadata["format"] == "grouped"

    raw = pipeline.extract_matches(f"fingerprint {PGP_RAW} listed")
    pgp_raw = [m for m in raw if m.entity_type == EntityType.PGP_KEY]
    assert len(pgp_raw) == 1
    assert pgp_raw[0].confidence == 0.80
    assert pgp_raw[0].metadata["format"] == "raw"


def test_wallet_extraction_all_schemes() -> None:
    text = f"send to {BTC_BECH32} or {BTC_BASE58}; erc20 ref {ETH_EIP55}"
    matches = _pipeline().extract_matches(text)
    wallets = [m for m in matches if m.entity_type == EntityType.WALLET_ADDRESS]
    normalized = {w.normalized_form for w in wallets}
    assert normalized == {BTC_BECH32.lower(), BTC_BASE58, ETH_EIP55.lower()}

    by_norm = {w.normalized_form: w for w in wallets}
    assert by_norm[BTC_BECH32.lower()].metadata["scheme"] == "bech32"
    assert by_norm[BTC_BASE58].metadata["scheme"] == "base58check"
    eth = by_norm[ETH_EIP55.lower()]
    assert eth.metadata["eip55"] == "checksum"
    assert eth.confidence == 0.95


def test_onion_extraction_v3_and_legacy_v2() -> None:
    text = f"mirror at {ONION_V3} and old link {ONION_V2}"
    matches = _pipeline().extract_matches(text)
    onions = [m for m in matches if m.entity_type == EntityType.ONION_SERVICE]
    assert len(onions) == 2
    by_norm = {o.normalized_form: o for o in onions}
    v3 = by_norm[ONION_V3]
    v2 = by_norm[ONION_V2]
    assert v3.confidence == 0.98 and v3.metadata["onion_version"] == 3
    assert v2.confidence == 0.60 and v2.metadata["legacy"] is True


def test_domain_extraction_and_context_confidence() -> None:
    pipeline = _pipeline()
    bare = pipeline.extract_matches("go to example.com for the mirror")
    domains = [m for m in bare if m.entity_type == EntityType.DOMAIN]
    assert [d.normalized_form for d in domains] == ["example.com"]
    assert domains[0].confidence == 0.90

    secured = pipeline.extract_matches("hosted at https://mirror.example.net/login")
    secured_domains = [m for m in secured if m.entity_type == EntityType.DOMAIN]
    assert secured_domains and secured_domains[0].confidence == 0.95
    # scheme context allows non-allowlisted TLDs too
    niche = pipeline.extract_matches("see https://sub.examplenewtld/x")
    niche_domains = {m.normalized_form for m in niche if m.entity_type == EntityType.DOMAIN}
    assert "sub.examplenewtld" in niche_domains
    # ...but the same unknown TLD bare, without context, is not a host
    bare_niche = pipeline.extract_matches("look at sub.examplenewtld directly")
    assert not [m for m in bare_niche if m.entity_type == EntityType.DOMAIN]


def test_url_extraction_span_and_normalization() -> None:
    text = "See https://ExAmPle.com/Path?q=1#section now."
    matches = _pipeline().extract_matches(text)
    urls = [m for m in matches if m.entity_type == EntityType.URL]
    assert len(urls) == 1
    url = urls[0]
    # span excludes trailing sentence period
    assert text[url.start : url.end] == "https://ExAmPle.com/Path?q=1#section"
    # fragment dropped, scheme/host lowercased, path case preserved
    assert url.normalized_form == "https://example.com/Path?q=1"
    assert url.metadata["host"] == "example.com"

    www = _pipeline().extract_matches("mirror: www.Example.org/deals.")
    www_urls = [m for m in www if m.entity_type == EntityType.URL]
    assert www_urls and www_urls[0].normalized_form == "http://www.example.org/deals"


# -------------------------------------------------------- false positives


def test_sha256_blob_is_not_pgp_or_wallet() -> None:
    matches = _pipeline().extract_matches(f"sha256 = {SHA256_BLOB} pinned above")
    assert EntityType.PGP_KEY not in _types(matches)
    assert EntityType.WALLET_ADDRESS not in _types(matches)
    # a contiguous 40-hex slice must not be harvested either
    assert SHA256_BLOB[:40] not in {
        m.normalized_form for m in matches if m.entity_type == EntityType.PGP_KEY
    }


def test_eth_address_is_not_a_pgp_fingerprint() -> None:
    matches = _pipeline().extract_matches(f"verify sig {ETH_EIP55} please")
    types = _types(matches)
    assert EntityType.WALLET_ADDRESS in types
    assert EntityType.PGP_KEY not in types


def test_checksum_failures_are_dropped() -> None:
    tampered_bech32 = BTC_BECH32[:-1] + ("5" if BTC_BECH32[-1] != "5" else "4")
    tampered_base58 = BTC_BASE58[:-1] + ("3" if BTC_BASE58[-1] != "3" else "2")
    flipped = ("a" if ONION_V3[10] != "a" else "b") + ONION_V3[11:]
    tampered_onion = ONION_V3[:10] + flipped

    text = f"{tampered_bech32} {tampered_base58} {ETH_BAD_CASE} {tampered_onion}"
    matches = _pipeline().extract_matches(text)
    assert EntityType.WALLET_ADDRESS not in _types(matches)
    assert EntityType.ONION_SERVICE not in _types(matches)


def test_filenames_are_not_domains() -> None:
    text = "attached report.pdf, notes.txt, module.js and data.json"
    matches = _pipeline().extract_matches(text)
    assert EntityType.DOMAIN not in _types(matches)
    assert EntityType.URL not in _types(matches)


def test_partial_or_forged_onion_rejected() -> None:
    short = ONION_V3[:40] + ".onion"  # wrong length: no regex match
    # right length, but first base32 char flipped -> SHA3 checksum fails
    forged = ("b" if ONION_V3[0] != "b" else "c") + ONION_V3[1:]
    assert forged != ONION_V3
    matches = _pipeline().extract_matches(f"link {short} and {forged}")
    onions = [m for m in matches if m.entity_type == EntityType.ONION_SERVICE]
    # neither the truncated nor the checksum-forged address is extracted
    assert onions == []


def test_short_and_bogus_handles_rejected() -> None:
    matches = _pipeline().extract_matches("@a is too short; email user@host for info")
    assert EntityType.HANDLE not in _types(matches)
    assert EntityType.EMAIL_IDENTIFIER not in _types(matches)


def test_ip_addresses_and_dates_are_not_extracted() -> None:
    matches = _pipeline().extract_matches("on 2026-01-15 at 192.168.10.55 port 8443")
    assert EntityType.DOMAIN not in _types(matches)
    assert EntityType.WALLET_ADDRESS not in _types(matches)


# ------------------------------------------------------------------- NER


def test_platform_suffix_grammar() -> None:
    pipeline = _pipeline()
    matches = pipeline.extract_matches("listed on Acme market and discussed on Delta forum")
    marketplaces = [m for m in matches if m.entity_type == EntityType.MARKETPLACE]
    forums = [m for m in matches if m.entity_type == EntityType.FORUM]
    assert [m.normalized_form for m in marketplaces] == ["acme market"]
    assert [f.normalized_form for f in forums] == ["delta forum"]


def test_platform_gazetteer_lookup() -> None:
    matches = _pipeline().extract_matches("cross-posted to forum_alpha daily")
    forums = [m for m in matches if m.entity_type == EntityType.FORUM]
    assert forums and forums[0].normalized_form == "forum_alpha"
    assert forums[0].metadata["cue"] == "gazetteer"


def test_prose_market_mention_not_a_platform() -> None:
    matches = _pipeline().extract_matches("the goods traded on the black market for weeks")
    assert EntityType.MARKETPLACE not in _types(matches)


def test_role_cue_alias_extraction() -> None:
    matches = _pipeline().extract_matches("vendor ghostbroker replied quickly")
    aliases = [m for m in matches if m.entity_type == EntityType.ALIAS]
    assert len(aliases) == 1
    alias = aliases[0]
    assert alias.normalized_form == "ghostbroker"
    assert alias.metadata["role"] == "vendor"
    assert alias.surface_form == "ghostbroker"
    assert alias.confidence == 0.65


def test_role_cue_followed_by_prose_is_not_an_alias() -> None:
    matches = _pipeline().extract_matches("the vendor shipped the package today")
    assert EntityType.ALIAS not in _types(matches)


def test_ner_extractors_can_run_standalone() -> None:
    text = "vendor ghostbroker on Delta forum"
    platform = PlatformMentionExtractor().extract(text)
    alias = RoleCueAliasExtractor().extract(text)
    assert {m.entity_type for m in platform} == {EntityType.FORUM}
    assert {m.entity_type for m in alias} == {EntityType.ALIAS}


# --------------------------------------------------------------- pipeline


def test_pipeline_emits_canonical_entities_with_span_provenance() -> None:
    text = (
        "Contact @ghostbroker or vendor@example.com; key "
        f"{PGP_GROUPED}; wallet {BTC_BASE58}; site example.com"
    )
    evidence_id = uuid4()
    case_id = uuid4()
    result = ExtractionPipeline(include_ner=False).extract(
        text, evidence_id=evidence_id, case_id=case_id, field_name="body"
    )

    assert result.entities
    # spans sorted and provably aligned with the source text
    starts = [entity.span.start for entity in result.entities if entity.span]
    assert starts == sorted(starts)
    for entity in result.entities:
        assert isinstance(entity, Entity)
        Entity.model_validate(entity.model_dump())  # canonical schema gate
        assert entity.span is not None
        assert text[entity.span.start : entity.span.end] == entity.surface_form
        assert entity.evidence_id == evidence_id
        assert entity.case_id == case_id
        assert 0.0 <= entity.confidence <= 1.0

    types = _types(result.matches)
    assert {
        EntityType.HANDLE,
        EntityType.EMAIL_IDENTIFIER,
        EntityType.PGP_KEY,
        EntityType.WALLET_ADDRESS,
        EntityType.DOMAIN,
    } <= types

    # one entity per (type, span) — no duplicates
    keys = [
        (entity.entity_type, entity.span.start, entity.span.end)
        for entity in result.entities
        if entity.span
    ]
    assert len(keys) == len(set(keys))


def test_pipeline_can_disable_ner() -> None:
    text = "vendor ghostbroker on Delta forum"
    with_ner = ExtractionPipeline().extract(text, evidence_id=uuid4())
    without_ner = ExtractionPipeline(include_ner=False).extract(text, evidence_id=uuid4())
    assert EntityType.ALIAS in {e.entity_type for e in with_ner.entities}
    assert EntityType.ALIAS not in {e.entity_type for e in without_ner.entities}
    assert EntityType.FORUM not in {e.entity_type for e in without_ner.entities}


def test_pipeline_rejects_out_of_bounds_spans() -> None:
    class _BadExtractor:
        name = "bad"

        def extract(self, text: str) -> list[EntityMatch]:  # noqa: ARG002
            return [
                EntityMatch(
                    entity_type=EntityType.HANDLE,
                    start=0,
                    end=10_000,
                    normalized_form="boom",
                    confidence=1.0,
                    surface_form="",
                )
            ]

    pipeline = ExtractionPipeline([_BadExtractor()])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="outside text"):
        pipeline.extract("short", evidence_id=uuid4())


def test_extract_all_deduplicates_and_sorts() -> None:
    text = f"mail a@example.com and visit example.com with {PGP_RAW}"
    matches = extract_all(text)
    keys = [m.key for m in matches]
    assert len(keys) == len(set(keys))
    assert [m.start for m in matches] == sorted(m.start for m in matches)
