/**
 * Types mirroring the canonical backend schemas.
 *
 * Source of truth: `src/aegis/schemas/*.py` (Pydantic models) and the
 * FastAPI `response_model`s declared in `src/aegis/api/app.py`.
 * Timestamps are ISO-8601 strings as serialised by Pydantic.
 */

export type UUID = string;

/** Mirrors `aegis.schemas.evidence.SourceType`. */
export type SourceType =
  | 'public_web'
  | 'forum'
  | 'marketplace'
  | 'threat_feed'
  | 'analyst_submitted'
  | 'synthetic';

export const SOURCE_TYPES: readonly SourceType[] = [
  'public_web',
  'forum',
  'marketplace',
  'threat_feed',
  'analyst_submitted',
  'synthetic',
];

/** Mirrors `aegis.schemas.evidence.SourceTier` (docs/data-source-policy.md). */
export type SourceTier = 'A' | 'B' | 'C' | 'D' | 'E';

export const SOURCE_TIERS: readonly SourceTier[] = ['A', 'B', 'C', 'D', 'E'];

/** `GET /health`, `GET /health/db`. */
export interface HealthResponse {
  readonly status: string;
  readonly service: string;
}

/** Durable investigation workspace (`Case` backend schema). */
export interface InvestigationCase {
  case_id: UUID;
  name: string;
  description: string | null;
  status: 'open' | 'active' | 'on_hold' | 'closed' | 'archived';
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
}

/** Payload for `POST /api/v1/sources` (`SourceCreate`). */
export interface SourceCreate {
  source_type: SourceType;
  name: string;
  tier: SourceTier;
  reliability: number;
  independence_group?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Response of `POST /api/v1/sources`. The handler declares
 * `response_model=dict[str, object]` but returns these four keys
 * (see `create_source` in `src/aegis/api/app.py`).
 */
export interface CreatedSource {
  source_id: string;
  source_type: string;
  name: string;
  reliability: number;
}

/** Payload for `POST /api/v1/evidence` (`EvidenceCreate`). */
export interface EvidenceCreate {
  case_id?: UUID | null;
  source_id: UUID;
  source_type: SourceType;
  observed_at?: string | null;
  collected_at: string;
  entity_type?: string | null;
  entity_value_hash?: string | null;
  context_hash?: string | null;
  raw_artifact_uri: string;
  sha256: string;
  collector_name: string;
  collector_version: string;
  normalizer_version?: string | null;
  extraction_version?: string | null;
  source_reliability: number;
  independence_group: string;
  metadata?: Record<string, unknown>;
}

/** Immutable evidence record (`Evidence` response model). */
export interface Evidence extends EvidenceCreate {
  evidence_id: UUID;
  artifact_id: UUID | null;
  created_at: string | null;
}

/** `GET /api/v1/evidence/{id}/provenance` (`EvidenceProvenance`). */
export interface EvidenceProvenance {
  evidence_id: UUID;
  sha256: string;
  artifact_uri: string;
  parent_evidence_ids: UUID[];
  derivation_count: number;
}

/** Payload for `POST /api/v1/cases` once that endpoint ships (`CaseCreate`). */
export interface CaseCreate {
  name: string;
  description?: string | null;
}

/** Payload for `POST /api/v1/analysis/synthetic`. */
export interface SyntheticAnalysisRequest {
  seed: number;
  actor_count: number;
  min_score: number;
}

/**
 * One hypothesis entry of `SyntheticAnalysisResponse.hypotheses`.
 *
 * The backend types this field as `list[dict[str, object]]`; the keys are
 * documented in `run_synthetic_analysis` (`src/aegis/api/analysis.py`), so
 * `parseSyntheticAnalysisResponse` narrows the loose payload at runtime.
 */
export interface SyntheticHypothesis {
  hypothesis_id: string;
  source_actor_id: string;
  target_actor_id: string;
  raw_score: number;
  support_score: number;
  contradiction_score: number;
  final_score: number;
  status: string;
  evidence_count: number;
  explanations: string[];
}

/** `POST /api/v1/analysis/synthetic` (`SyntheticAnalysisResponse`). */
export interface SyntheticAnalysisResponse {
  seed: number;
  actor_count: number;
  evidence_count: number;
  relationship_count: number;
  candidate_count: number;
  persisted_hypothesis_count: number;
  hypotheses: SyntheticHypothesis[];
}
