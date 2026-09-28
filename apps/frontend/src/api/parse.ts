import type {
  SyntheticAnalysisResponse,
  SyntheticHypothesis,
} from './types';

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function asHypothesis(value: unknown): SyntheticHypothesis | null {
  const record = asRecord(value);
  if (record === null) return null;
  const hypothesisId = asString(record['hypothesis_id']);
  if (hypothesisId === '') return null;
  return {
    hypothesis_id: hypothesisId,
    source_actor_id: asString(record['source_actor_id']),
    target_actor_id: asString(record['target_actor_id']),
    raw_score: asNumber(record['raw_score']),
    support_score: asNumber(record['support_score']),
    contradiction_score: asNumber(record['contradiction_score']),
    final_score: asNumber(record['final_score']),
    status: asString(record['status']),
    evidence_count: asNumber(record['evidence_count']),
    explanations: asStringList(record['explanations']),
  };
}

/**
 * Narrow the `POST /api/v1/analysis/synthetic` payload.
 *
 * The endpoint declares `hypotheses: list[dict[str, object]]`, so the wire
 * shape is intentionally loose; entries without a `hypothesis_id` are dropped
 * rather than rendered with fabricated values.
 */
export function parseSyntheticAnalysisResponse(raw: unknown): SyntheticAnalysisResponse {
  const record = asRecord(raw);
  if (record === null) {
    throw new Error('Unexpected analysis payload: expected a JSON object.');
  }
  const rawHypotheses = record['hypotheses'];
  const hypotheses = Array.isArray(rawHypotheses)
    ? rawHypotheses
        .map(asHypothesis)
        .filter((item): item is SyntheticHypothesis => item !== null)
    : [];
  return {
    seed: asNumber(record['seed']),
    actor_count: asNumber(record['actor_count']),
    evidence_count: asNumber(record['evidence_count']),
    relationship_count: asNumber(record['relationship_count']),
    candidate_count: asNumber(record['candidate_count']),
    persisted_hypothesis_count: asNumber(record['persisted_hypothesis_count']),
    hypotheses,
  };
}
