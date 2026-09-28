"""Run a complete, database-free synthetic investigation rehearsal."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from aegis.copilot.types import Claim, Report, ReportSection
from aegis.reporting.export import ReportProvenance, export_csv, export_json, export_stix_bundle
from aegis.synthetic.calibration import ConfidenceCalibrator
from aegis.synthetic.candidate_links import CandidateLinkEngine
from aegis.synthetic.contradiction import ContradictionDetector
from aegis.synthetic.evidence_generator import SyntheticEvidenceGenerator
from aegis.synthetic.generator import SyntheticActorGenerator
from aegis.synthetic.graph import EvidenceGraphBuilder
from aegis.synthetic.hypothesis import AttributionHypothesisBuilder


def rehearse(seed: int, actor_count: int) -> dict[str, object]:
    if actor_count < 4:
        raise ValueError("actor_count must be at least 4")
    started = perf_counter()
    timings: dict[str, float] = {}

    stage = perf_counter()
    actors = SyntheticActorGenerator(seed=seed).generate(actor_count)
    evidence, relationships = SyntheticEvidenceGenerator(seed=seed).generate(actors)
    timings["collection_and_normalization_ms"] = round((perf_counter() - stage) * 1000, 3)
    time_to_first_evidence_ms = (perf_counter() - started) * 1000

    stage = perf_counter()
    graph = EvidenceGraphBuilder().build(evidence, relationships)
    timings["graph_build_ms"] = round((perf_counter() - stage) * 1000, 3)

    stage = perf_counter()
    candidates = CandidateLinkEngine().generate(evidence, min_score=0.0)
    timings["candidate_generation_ms"] = round((perf_counter() - stage) * 1000, 3)
    time_to_candidate_ms = (perf_counter() - started) * 1000

    stage = perf_counter()
    calibrator = ConfidenceCalibrator()
    contradiction_detector = ContradictionDetector()
    hypothesis_builder = AttributionHypothesisBuilder()
    hypotheses = []
    for candidate in candidates:
        calibrated = calibrator.calibrate(candidate, evidence)
        contradiction = contradiction_detector.analyze(candidate, evidence)
        hypotheses.append(hypothesis_builder.build(calibrated, contradiction, evidence))
    timings["fusion_and_assessment_ms"] = round((perf_counter() - stage) * 1000, 3)
    time_to_assessment_ms = (perf_counter() - started) * 1000

    claims = tuple(
        Claim(
            text=(
                f"Synthetic candidate {hypothesis.source_actor_id} ↔ "
                f"{hypothesis.target_actor_id} has final score {hypothesis.final_score:.3f}; "
                "analyst review is required."
            ),
            citations=tuple(item.evidence_id for item in hypothesis.evidence),
            origin="synthetic-rehearsal",
        )
        for hypothesis in hypotheses
        if hypothesis.evidence
    )
    cited_evidence_ids = tuple(
        dict.fromkeys(citation for claim in claims for citation in claim.citations)
    )
    report = Report(
        title=f"AEGIS synthetic rehearsal seed {seed}",
        sections=(ReportSection("Attribution hypotheses for analyst review", claims),),
        evidence_ids=cited_evidence_ids,
        generated_by="phase-28-synthetic-rehearsal",
    )
    provenance = ReportProvenance(
        case_id=f"synthetic-case-{seed}",
        query="Rehearse synthetic cross-platform candidate attribution",
        evidence_ids=cited_evidence_ids,
        model_versions=("synthetic-candidate-0.1", "contradiction-fusion-0.1"),
        dataset_versions=(f"synthetic-seed-{seed}",),
        generated_at=datetime.now(UTC),
    )
    timings["report_generation_ms"] = round((perf_counter() - stage) * 1000, 3)
    return {
        "seed": seed,
        "actor_count": len(actors),
        "evidence_count": len(evidence),
        "graph_node_count": len(graph.nodes),
        "graph_edge_count": len(graph.edges),
        "candidate_count": len(candidates),
        "assessment_count": len(hypotheses),
        "time_to_first_evidence_ms": round(time_to_first_evidence_ms, 3),
        "time_to_candidate_ms": round(time_to_candidate_ms, 3),
        "time_to_assessment_ms": round(time_to_assessment_ms, 3),
        "total_processing_ms": round((perf_counter() - started) * 1000, 3),
        "stage_timings_ms": timings,
        "report_json": json.loads(export_json(report, provenance)),
        "report_csv": export_csv(report, provenance),
        "report_stix": export_stix_bundle(report, provenance),
        "limitations": [
            "Synthetic-only rehearsal; metrics do not estimate field performance.",
            "All candidate findings require analyst review.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=26151)
    parser.add_argument("--actors", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path("artifacts/rehearsal/phase28.json"))
    args = parser.parse_args()
    try:
        result = rehearse(args.seed, args.actors)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"rehearsal artifact written to {args.output}")
    print(
        "actors={actor_count} evidence={evidence_count} candidates={candidate_count} "
        "assessments={assessment_count} total_ms={total_processing_ms}".format(**result)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
