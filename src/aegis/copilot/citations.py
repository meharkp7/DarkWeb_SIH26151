"""Citation validation: only evidence-pack records can support findings."""

from __future__ import annotations

from aegis.copilot.types import CitationValidation, Claim, ClaimStatus, EvidencePack, ValidatedClaim


def validate_citations(claims: tuple[Claim, ...], pack: EvidencePack) -> CitationValidation:
    """Partition claims into supported, unverified, and fabricated-citation groups."""
    supported: list[ValidatedClaim] = []
    unsupported: list[ValidatedClaim] = []
    dropped: list[ValidatedClaim] = []
    for claim in claims:
        if not claim.citations:
            unsupported.append(
                ValidatedClaim(claim, ClaimStatus.UNSUPPORTED, "claim has no citations")
            )
        elif all(citation in pack for citation in claim.citations):
            supported.append(ValidatedClaim(claim, ClaimStatus.SUPPORTED, "all citations resolve"))
        else:
            unknown = sorted(citation for citation in claim.citations if citation not in pack)
            dropped.append(
                ValidatedClaim(
                    claim, ClaimStatus.DROPPED, f"unknown citation ids: {', '.join(unknown)}"
                )
            )
    return CitationValidation(tuple(supported), tuple(unsupported), tuple(dropped))
