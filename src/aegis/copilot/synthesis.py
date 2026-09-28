"""Evidence-grounded, deterministic copilot synthesis.

An LLM adapter may propose claims later, but this reference synthesizer gives
the service a safe baseline: it creates claims only from platform-authored
evidence summaries and validates every citation before rendering.
"""

from __future__ import annotations

from aegis.copilot.citations import validate_citations
from aegis.copilot.containment import data_region, detect_indicators
from aegis.copilot.types import Answer, Claim, EvidenceItem, EvidencePack, ParsedIntent


def flag_pack(pack: EvidencePack) -> EvidencePack:
    """Attach injection indicators without changing evidence text or provenance."""
    return EvidencePack(
        tuple(
            EvidenceItem(
                item_id=item.item_id,
                tool=item.tool,
                kind=item.kind,
                summary=item.summary,
                data_text=item.data_text,
                provenance=item.provenance,
                flags=detect_indicators(item.data_text),
            )
            for item in pack.items
        )
    )


def synthesize(question: str, intent: ParsedIntent, pack: EvidencePack) -> Answer:
    """Create an answer that makes only cited findings and isolated data available."""
    safe_pack = flag_pack(pack)
    claims = tuple(
        Claim(item.summary, (item.item_id,), origin=f"tool:{item.tool.value}")
        for item in safe_pack.items
    )
    validation = validate_citations(claims, safe_pack)
    findings = "\n".join(
        f"- {claim.text} [{', '.join(claim.citations)}]" for claim in validation.supported_claims
    )
    if not findings:
        findings = "No evidence-backed findings were retrieved."
    data = "\n\n".join(data_region(item.data_text) for item in safe_pack.items)
    text = (
        f"Findings:\n{findings}\n\nUntrusted evidence follows:\n{data}"
        if data
        else f"Findings:\n{findings}"
    )
    return Answer(question, intent, safe_pack, validation, text)
