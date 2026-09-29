export type UUID = string;

export type SourceType = 'public_web' | 'forum' | 'marketplace' | 'threat_feed' | 'analyst_submitted' | 'synthetic';
export type SourceTier = 'A' | 'B' | 'C' | 'D' | 'E';

export interface HealthResponse { readonly status: string; readonly service: string; }

// ---------------------------------------------------------------------------
// Case triage
// ---------------------------------------------------------------------------

export const CASE_STATUSES = ['open', 'active', 'on_hold', 'closed', 'archived'] as const;
export type CaseStatus = (typeof CASE_STATUSES)[number];

export const CASE_PRIORITIES = ['low', 'medium', 'high', 'critical'] as const;
export type CasePriority = (typeof CASE_PRIORITIES)[number];

export const CASE_SEVERITIES = ['informational', 'low', 'medium', 'high', 'critical'] as const;
export type CaseSeverity = (typeof CASE_SEVERITIES)[number];

export const SOURCE_TYPES: readonly SourceType[] = [
  'public_web',
  'forum',
  'marketplace',
  'threat_feed',
  'analyst_submitted',
  'synthetic',
];

export const SOURCE_TIERS: readonly SourceTier[] = ['A', 'B', 'C', 'D', 'E'];

/** Statuses that end active work — used to decide whether an SLA still runs. */
export const TERMINAL_CASE_STATUSES: readonly CaseStatus[] = ['closed', 'archived'];

export interface InvestigationCase {
  case_id: UUID;
  name: string;
  description: string | null;
  status: CaseStatus;
  priority: CasePriority;
  severity: CaseSeverity;
  tags: string[];
  assigned_to: UUID | null;
  sla_due_at: string | null;
  closed_at: string | null;
  closure_reason: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * @deprecated Alias of {@link CaseQueueEntry}.
 *
 * This used to be a separate interface with a hand-guessed `counts` shape and
 * optional `queue_score`. Two shapes for one list is how a page ends up
 * rendering against a payload the API never sends, and every field ends up
 * defensively optional — which is where "the dashboard is blank" bugs come
 * from. The register and the priority queue read the same rows, so they are
 * one type.
 */
export type CaseSummary = CaseQueueEntry;

export interface CaseCreate {
  name: string;
  description?: string | null;
  priority?: CasePriority;
  severity?: CaseSeverity;
  tags?: string[];
  assigned_to?: UUID | null;
  sla_due_at?: string | null;
}

/**
 * Partial triage update. Every key is optional and only the supplied keys are
 * applied server-side, so omitting a field never clears it.
 *
 * `tags` replaces the whole list rather than merging — that keeps "remove the
 * last tag" expressible.
 */
export interface CaseUpdate {
  name?: string;
  description?: string | null;
  status?: CaseStatus;
  priority?: CasePriority;
  severity?: CaseSeverity;
  tags?: string[];
  assigned_to?: UUID | null;
  sla_due_at?: string | null;
  /** Required (in this or a prior update) whenever status becomes 'closed'. */
  closure_reason?: string | null;
}

export interface CaseNote {
  note_id: UUID;
  case_id: UUID;
  author_id: UUID | null;
  body: string;
  created_at: string | null;
}

export interface CaseNoteCreate {
  body: string;
  author_id?: UUID | null;
}

// ---------------------------------------------------------------------------
// Dashboard / live
// ---------------------------------------------------------------------------

export interface LiveActivity {
  seq: number;
  occurred_at: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  case_id: string | null;
  payload: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Sources / evidence
// ---------------------------------------------------------------------------

export interface SourceCreate {
  source_type: SourceType;
  name: string;
  tier: SourceTier;
  reliability: number;
  independence_group?: string;
  metadata?: Record<string, unknown>;
}
export interface CreatedSource { source_id: string; source_type: string; name: string; reliability: number; }

export interface EvidenceCreate {
  case_id?: UUID | null; source_id: UUID; source_type: SourceType; observed_at?: string | null; collected_at: string;
  entity_type?: string | null; entity_value_hash?: string | null; context_hash?: string | null; raw_artifact_uri: string;
  sha256: string; collector_name: string; collector_version: string; normalizer_version?: string | null;
  extraction_version?: string | null; source_reliability: number; independence_group: string; metadata?: Record<string, unknown>;
}
export interface Evidence extends EvidenceCreate { evidence_id: UUID; artifact_id: UUID | null; created_at: string | null; }
export interface EvidenceProvenance { evidence_id: UUID; sha256: string; artifact_uri: string; parent_evidence_ids: UUID[]; derivation_count: number; }

export interface SyntheticAnalysisRequest { seed: number; actor_count: number; min_score: number; }
export interface SyntheticHypothesis { hypothesis_id: string; source_actor_id: string; target_actor_id: string; raw_score: number; support_score: number; contradiction_score: number; final_score: number; status: string; evidence_count: number; explanations: string[]; }
export interface SyntheticAnalysisResponse { seed: number; actor_count: number; evidence_count: number; relationship_count: number; candidate_count: number; persisted_hypothesis_count: number; hypotheses: SyntheticHypothesis[]; }

// ---------------------------------------------------------------------------
// Case workspace
// ---------------------------------------------------------------------------

export interface WorkspaceEntity { entity_id: string; type: string; surface_form: string; normalized_form: string; confidence: number; }
export interface WorkspaceRelationship { relationship_id: string; subject_entity_id: string; object_entity_id: string; type: string; confidence: number; first_seen: string; last_seen: string; evidence_ids: string[]; }
export interface WorkspaceAssessment { assessment_id: string; hypothesis_id: string; model_id: string; model_version: string; raw_score: number; calibrated_confidence: number | null; signals: Record<string, number>; explanations: string[]; limitations: string[]; supporting_evidence_ids: string[]; contradictory_evidence_ids: string[]; }
export interface WorkspaceEvidence { evidence_id: string; source_id: string; source_type: string; observed_at: string | null; collected_at: string; entity_type: string | null; reliability: number; independence_group: string; sha256: string; metadata: Record<string, unknown>; }

/** The `case` block of `GET /cases/{id}/workspace` — a superset of InvestigationCase. */
export interface WorkspaceCase extends InvestigationCase {
  sla_overdue: boolean;
}

export interface CaseWorkspace {
  case: WorkspaceCase;
  counts: Record<string, number>;
  evidence: WorkspaceEvidence[];
  entities: WorkspaceEntity[];
  relationships: WorkspaceRelationship[];
  assessments: WorkspaceAssessment[];
  activity: LiveActivity[];
}

// ---------------------------------------------------------------------------
// Copilot
// ---------------------------------------------------------------------------

export interface CopilotResponse {
  question: string; intent: string; rule: string; tools_run: string[]; evidence_ids: string[];
  flagged_evidence_ids: string[]; claims: Array<{ text: string; citations: string[]; status: string }>;
  unsupported_claims: Array<{ text: string; citations: string[]; status: string }>;
  dropped_claims: Array<{ text: string; citations: string[]; status: string }>;
  text: string;
}

// ---------------------------------------------------------------------------
// Command Center analytics
//
// These mirror the Pydantic models in `src/aegis/schemas/analytics.py`. The
// backend previously returned untyped `dict`s for all of this, so the shapes
// were guesses; they are now declared on both sides and can be checked.
// ---------------------------------------------------------------------------

/** One named driver behind a case's queue position. */
export interface PriorityReason {
  readonly key: string;
  readonly label: string;
  readonly weight: number;
}

/** A deadline state, kept distinct from `sla_overdue`. */
export type SlaState = 'breached' | 'at_risk' | 'ok' | 'none';

/**
 * An investigations-register row and a priority-queue row.
 *
 * Deliberately one type for both: the register and the queue read the same
 * rows, and two shapes for one list is how the two views start disagreeing
 * about a case.
 */
export interface CaseQueueEntry {
  readonly case_id: UUID;
  readonly name: string;
  readonly status: CaseStatus;
  readonly priority: CasePriority;
  readonly severity: CaseSeverity;
  readonly tags: readonly string[];
  readonly assigned_to: UUID | null;
  readonly sla_due_at: string | null;
  readonly sla_overdue: boolean;
  readonly sla_state: SlaState;
  readonly queue_score: number;
  readonly queue_reason: string;
  /** Every contributor to `queue_score`, summing exactly to it. */
  readonly reasons: readonly PriorityReason[];
  readonly counts: {
    readonly evidence: number;
    readonly entities: number;
    readonly relationships: number;
    readonly assessments: number;
    readonly contradictions: number;
    readonly recent_evidence: number;
  };
  readonly last_activity: string | null;
  readonly attribution: number | null;
}

export interface CommandPosture {
  readonly active_investigations: number;
  readonly critical: number;
  readonly high: number;
  readonly sla_at_risk: number;
  readonly new_evidence: number;
  readonly unresolved_links: number;
  readonly total_investigations: number;
  readonly unassigned: number;
  readonly pressure_index: number;
}

export interface VelocityPoint {
  readonly label: string;
  readonly count: number;
  /** Signed change against the previous bucket; null on the first. */
  readonly delta: number | null;
}

export interface PressureIndicator {
  readonly key: string;
  readonly label: string;
  readonly score: number;
  /** The raw count the score was scaled from. */
  readonly observed: number;
  /** The count that would score 100. */
  readonly ceiling: number;
}

export interface AttributionPosture {
  readonly case_id: UUID;
  readonly case_name: string;
  readonly confidence: number;
  readonly supporting_signals: number;
  readonly modalities: number;
  readonly contradictions: number;
  readonly freshness: number;
  readonly explanations: readonly string[];
  readonly signals: Readonly<Record<string, number>>;
}

export interface PlatformCounts {
  readonly cases: number;
  readonly evidence: number;
  readonly entities: number;
  readonly relationships: number;
  readonly assessments: number;
}

export interface DashboardSnapshot {
  readonly type: 'snapshot';
  readonly server_time: string;
  readonly counts: PlatformCounts;
  readonly critical_alerts: number;
  readonly activity: readonly LiveActivity[];
  readonly case_summaries: readonly CaseQueueEntry[];
  readonly command_posture: CommandPosture;
  readonly evidence_velocity: readonly VelocityPoint[];
  readonly investigation_pressure: readonly PressureIndicator[];
  readonly attribution_posture: readonly AttributionPosture[];
}

/** A websocket frame that is not a snapshot. */
export interface LiveControlFrame {
  readonly type: 'heartbeat' | 'degraded';
  readonly server_time: string;
  readonly detail?: string;
}

// ---------------------------------------------------------------------------
// Investigation workspace analytics
// ---------------------------------------------------------------------------

export type Band = 'HIGH' | 'MEDIUM' | 'LOW';

export interface SignalBand {
  readonly modality: string;
  readonly support: Band;
  readonly contradict: Band;
  readonly support_value: number;
  readonly contradict_value: number;
  readonly freshness: number;
}

export interface CaseMetrics {
  readonly case_id: UUID;
  readonly evidence: number;
  readonly links: number;
  readonly entities: number;
  readonly sources: number;
  readonly attribution: number | null;
  readonly contradictions: number;
  readonly hypotheses: number;
  readonly independent_sources: number;
}

export type TimelineLayer = 'event' | 'actor' | 'infrastructure' | 'financial';

export interface TimelineEvent {
  readonly occurred_at: string;
  readonly title: string;
  readonly layer: TimelineLayer;
  readonly evidence_id: UUID | null;
  readonly confidence: number | null;
  readonly detail: string | null;
  readonly action: string | null;
  readonly case_id: UUID | null;
}

export interface CaseTimeline {
  readonly case_id: UUID;
  readonly events: readonly TimelineEvent[];
  readonly layers: readonly TimelineLayer[];
}

export interface CaseHypothesis {
  readonly hypothesis_id: UUID;
  readonly kind: string;
  readonly status: string;
  readonly subject_entity_id: UUID;
  readonly object_entity_id: UUID;
  readonly missing_evidence: readonly string[];
  readonly analyst_disposition: string | null;
  readonly calibrated_confidence: number | null;
  readonly raw_score: number | null;
  readonly signals: Readonly<Record<string, number>>;
  readonly supporting_evidence_ids: readonly UUID[];
  readonly contradictory_evidence_ids: readonly UUID[];
  /** Distinct independence groups — three feeds copying one press release are one source. */
  readonly independent_source_groups: number;
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

export interface CaseGraphNode {
  readonly entity_id: UUID;
  readonly type: string;
  readonly label: string;
  readonly normalized_form: string;
  readonly confidence: number;
  readonly first_seen: string | null;
  readonly last_seen: string | null;
  readonly degree: number;
  readonly modality: string | null;
  readonly evidence_count: number;
}

export interface CaseGraphEdge {
  readonly relationship_id: UUID;
  readonly source: UUID;
  readonly target: UUID;
  readonly type: string;
  readonly confidence: number;
  readonly first_seen: string;
  readonly last_seen: string;
  readonly evidence_ids: readonly UUID[];
}

export interface CaseGraph {
  readonly case_id: UUID;
  readonly nodes: readonly CaseGraphNode[];
  readonly edges: readonly CaseGraphEdge[];
  readonly edge_types: Readonly<Record<string, number>>;
  readonly node_types: Readonly<Record<string, number>>;
}

// ---------------------------------------------------------------------------
// Administration
// ---------------------------------------------------------------------------

export interface TeamMember {
  readonly user_id: UUID;
  readonly email: string;
  readonly display_name: string;
  readonly role: string;
  readonly permissions: readonly string[];
  readonly is_active: boolean;
  readonly last_login_at: string | null;
  readonly assigned_cases: number;
}

export interface TeamResponse {
  readonly members: readonly TeamMember[];
  readonly roles: readonly string[];
}

export interface AuditEntry {
  readonly seq: number;
  readonly occurred_at: string;
  readonly action: string;
  readonly actor: string | null;
  readonly entity_type: string | null;
  readonly entity_id: string | null;
  readonly case_id: UUID | null;
  readonly case_name: string | null;
  readonly payload: Readonly<Record<string, unknown>>;
  readonly entry_hash: string;
  readonly prev_hash: string | null;
}

export interface AuditTrailResponse {
  readonly entries: readonly AuditEntry[];
  readonly total: number;
  /** Recomputed from the chain, not asserted. */
  readonly chain_valid: boolean;
  readonly actions: readonly string[];
}

export interface SystemHealth {
  readonly api_status: string;
  readonly database_status: string;
  readonly environment: string;
  readonly auth_mode: string;
  readonly auth_session_ttl_s: number;
  readonly live_socket: string;
  readonly counts: PlatformCounts;
  readonly metrics: Readonly<Record<string, unknown>>;
  readonly chain_valid: boolean;
  readonly adapters: Readonly<Record<string, string>>;
}

export interface ModelRunSummary {
  readonly run_id: UUID;
  readonly model_id: string;
  readonly model_version: string;
  readonly dataset_version: string;
  readonly feature_version: string;
  readonly status: string;
  readonly seed: number;
  readonly started_at: string | null;
  readonly finished_at: string | null;
  readonly metrics: Readonly<Record<string, unknown>>;
}

export interface ModelRegistryResponse {
  readonly runs: readonly ModelRunSummary[];
  readonly total: number;
}
