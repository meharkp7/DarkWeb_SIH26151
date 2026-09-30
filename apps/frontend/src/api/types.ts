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

export interface CopilotClaim {
  text: string;
  citations: string[];
  status: string;
  /** Which tool produced the claim, and what was dropped, when it was. */
  origin?: string;
  reason?: string | null;
}

export interface CopilotReport {
  title: string;
  sections: ReadonlyArray<{ heading: string; claims: string[] }>;
  evidence_ids: string[];
  generated_by: string;
}

export interface CopilotResponse {
  question: string;
  /** The screen the question was asked from, as the API received it. */
  context?: string | null;
  intent: string; rule: string; tools_run: string[]; evidence_ids: string[];
  flagged_evidence_ids: string[]; claims: CopilotClaim[];
  unsupported_claims: CopilotClaim[]; dropped_claims: CopilotClaim[];
  text: string;
  /**
   * A brief built only from citation-validated claims. `null` when nothing
   * survived validation, which is a different state from a report with no
   * sections — see the backend `CopilotReport` docstring.
   */
  report?: CopilotReport | null;
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

// ---------------------------------------------------------------------------
// Global search
// ---------------------------------------------------------------------------

export type SearchKind =
  | 'case'
  | 'entity'
  | 'evidence'
  | 'hypothesis'
  | 'source'
  | 'relationship';

export interface SearchHit {
  readonly kind: SearchKind;
  readonly id: UUID;
  readonly label: string;
  readonly detail: string | null;
  /** Present on everything case-scoped, so a hit is actionable without a second lookup. */
  readonly case_id: UUID | null;
  readonly case_name: string | null;
  readonly occurred_at: string | null;
  readonly score: number | null;
}

export interface SearchResponse {
  readonly query: string;
  readonly hits: readonly SearchHit[];
  /** Per-kind totals, not just what was returned. */
  readonly counts: Readonly<Partial<Record<SearchKind, number>>>;
  readonly truncated: Readonly<Partial<Record<SearchKind, boolean>>>;
}

// ---------------------------------------------------------------------------
// Actor registry
//
// The mirror of `src/aegis/schemas/actors.py`. Every field the problem
// statement names is on every row, and `confidence` is nullable because
// "not assessed" and "assessed at zero" are different facts — the UI must be
// able to tell them apart rather than rendering both as a 0%.
// ---------------------------------------------------------------------------

/** Identifier kinds the registry stores. */
export type ActorIdentifierKind =
  | 'handle'
  | 'pgp'
  | 'wallet'
  | 'onion'
  | 'clearnet'
  | 'jabber'
  | (string & {});

export interface ActorRegistryRow {
  readonly actor_id: UUID;
  readonly handle: string;
  readonly category: string;
  readonly status: string;
  /** `null` means *not assessed* — not zero. */
  readonly confidence: number | null;
  readonly first_seen: string | null;
  readonly last_seen: string | null;
  readonly last_scan_at: string | null;
  readonly source_id: UUID | null;
  readonly source_name: string | null;
  readonly identifier_count: number;
  readonly marketplace_count: number;
  /** Distinct investigations citing one of this actor's identifiers. */
  readonly case_link_count: number;
  readonly identifier_kinds: Readonly<Record<string, number>>;
  readonly notes: string | null;
  /**
   * Recorded sighting volume per week, or `null` when the platform has nothing
   * to plot for this actor. `null` is deliberately not an empty list and not a
   * run of zeros: a chart drawn from either would be a chart of nothing.
   */
  readonly activity: ActorActivitySeries | null;
}

/**
 * What the register's trend cell plots.
 *
 * These are *sightings*, not evidence records: the store holds one row per time
 * an actor was observed, and `cited` is how many of those were backed by a
 * ledger record. "34 records about this actor" and "34 times this actor was
 * seen" are different claims, and only the first is evidence — so the count of
 * the second travels with the series rather than being left to be assumed.
 */
export interface ActorActivitySeries {
  readonly weekly: readonly number[];
  /** ISO date the first bucket covers, so the period is named, not assumed. */
  readonly start: string;
  /** Sightings in the window that cite an evidence record. */
  readonly cited: number;
}

export interface ActorIdentifier {
  readonly identifier_id: UUID;
  readonly kind: string;
  readonly value: string;
  readonly independence_group: string | null;
  readonly confidence: number | null;
  readonly first_seen: string | null;
  readonly last_seen: string | null;
  readonly source_id: UUID | null;
  readonly source_name: string | null;
  readonly case_id: UUID | null;
}

export interface ActorMarketplacePresence {
  readonly presence_id: UUID;
  readonly marketplace: string;
  readonly role: string | null;
  readonly first_seen: string | null;
  readonly last_seen: string | null;
  readonly listing_count: number | null;
  readonly source_id: UUID | null;
  readonly source_name: string | null;
}

export interface PersonaLinkageSummary {
  readonly linkage_id: UUID;
  readonly candidate_handle: string;
  readonly method: string;
  /** The model's score, never overwritten by the analyst's ruling. */
  readonly score: number;
  readonly status: 'proposed' | 'confirmed' | 'rejected' | (string & {});
  readonly aligned_features: readonly string[];
  readonly apart_features: readonly string[];
  readonly contested_features: readonly string[];
  readonly limitations: readonly string[];
  readonly case_id: UUID | null;
  readonly adjudicated_by: UUID | null;
  readonly adjudicated_at: string | null;
  readonly rationale: string | null;
}

export interface ActorCaseLink {
  readonly case_id: UUID;
  readonly name: string;
  readonly status: string;
  readonly identifier_count: number;
}

export interface ActorProfile {
  readonly actor: ActorRegistryRow;
  readonly identifiers_by_kind: Readonly<Record<string, readonly ActorIdentifier[]>>;
  readonly marketplaces: readonly ActorMarketplacePresence[];
  /** Empty means "no linkage rows on file", not "no linkage exists". */
  readonly persona_linkages: readonly PersonaLinkageSummary[];
  readonly linked_cases: readonly ActorCaseLink[];
}

export interface ActorCategoryCount {
  readonly category: string;
  readonly count: number;
}

export interface ActorStatusCount {
  readonly status: string;
  readonly count: number;
}

export interface ActorIdentifierKindCount {
  readonly kind: string;
  readonly count: number;
}

export interface ActorSummary {
  readonly total: number;
  readonly by_status: readonly ActorStatusCount[];
  readonly by_category: readonly ActorCategoryCount[];
  readonly identifier_kinds: readonly ActorIdentifierKindCount[];
  readonly identifiers: number;
  readonly marketplaces: number;
  /** Threshold, not lookback: "no scan in N days". A larger N is laxer. */
  readonly stale_days: number;
  readonly stale: number;
  /** Actors carrying no attribution score — what `min_confidence` excludes. */
  readonly unassessed: number;
}

/** The filter set both the list route and the export accept. */
export interface ActorQuery {
  readonly q?: string;
  readonly category?: string;
  readonly status?: string;
  readonly min_confidence?: number;
  readonly source_id?: string;
  readonly sort?: string;
  readonly dir?: 'asc' | 'desc';
}

// ---------------------------------------------------------------------------
// Tor hidden-service infrastructure
//
// These mirror the Pydantic models in `src/aegis/api/infrastructure.py`.
// ---------------------------------------------------------------------------

/** The five misconfiguration classes the detector files, in display order. */
export const INFRA_FINDING_KINDS = [
  'exposed_status_page',
  'clearnet_certificate',
  'default_banner',
  'descriptor_inconsistency',
  'shared_fingerprint',
] as const;
export type InfraFindingKind = (typeof INFRA_FINDING_KINDS)[number];

export const INFRA_FINDING_KIND_LABELS: Readonly<Record<InfraFindingKind, string>> = {
  exposed_status_page: 'Exposed status page',
  clearnet_certificate: 'Clearnet-tied certificate',
  default_banner: 'Default service banner',
  descriptor_inconsistency: 'Descriptor inconsistency',
  shared_fingerprint: 'Shared fingerprint',
};

export const INFRA_SEVERITIES = [
  'critical',
  'high',
  'medium',
  'low',
  'informational',
] as const;
export type InfraSeverity = (typeof INFRA_SEVERITIES)[number];

export type InfraNetwork = 'onion' | 'clearnet';

/**
 * A misconfiguration in one hidden service.
 *
 * `limitations` is not decoration: shared hosting, a CDN and a reused default
 * banner all produce these signals legitimately, so a finding rendered without
 * its alternative reading is a false accusation with a confidence bar on it.
 * `confidence` is nullable — an unscored detector must read as unscored, not
 * as zero.
 */
export interface InfraFinding {
  readonly finding_id: UUID;
  readonly observation_id: UUID;
  readonly case_id: UUID | null;
  readonly subject: string;
  readonly network: InfraNetwork;
  readonly kind: InfraFindingKind;
  readonly kind_label: string;
  readonly severity: InfraSeverity;
  readonly detail: string;
  readonly limitations: readonly string[];
  readonly confidence: number | null;
  readonly detected_at: string;
  readonly observed_at: string;
  readonly evidence_id: UUID | null;
  readonly metadata: Readonly<Record<string, unknown>>;
}

/** The per-channel scores behind one correlation, exactly as stored. */
export interface InfraChannelScores {
  readonly certificate: number | null;
  readonly content: number | null;
  readonly technology: number | null;
  readonly http: number | null;
  readonly tls: number | null;
  readonly temporal: number;
  /** Channels that contributed to `overall`. A null channel is *absent*, not zero. */
  readonly available_channels: readonly string[];
  /**
   * Channels clearing their own decisive cutoff, strongest first. One entry
   * here means the whole score rests on a single dimension.
   */
  readonly decisive_channels: readonly string[];
}

export interface InfraMatch {
  readonly match_id: UUID;
  readonly case_id: UUID | null;
  readonly onion_observation_id: UUID;
  readonly clearnet_observation_id: UUID;
  readonly onion_subject: string;
  readonly clearnet_subject: string;
  readonly overall: number;
  readonly breakdown: InfraChannelScores;
  /** The channel that carried the candidate, named. */
  readonly strongest_channel: string | null;
  /** True when `decisive_channels` holds at most one entry. */
  readonly single_channel: boolean;
  readonly limitations: readonly string[];
  readonly sources: readonly string[];
  readonly evidence_ids: readonly string[];
  readonly detected_at: string;
  readonly metadata: Readonly<Record<string, unknown>>;
}

/** The stored `features_json` document, with its derived half intact. */
export interface InfraFeaturesDocument {
  readonly schema_version: string;
  readonly observation: Readonly<Record<string, unknown>>;
  readonly content: { readonly sha256: string; readonly simhash: number } | null;
  readonly technology_keys: readonly string[];
}

export interface InfraObservation {
  readonly observation_id: UUID;
  readonly subject: string;
  readonly network: InfraNetwork;
  readonly source: string;
  readonly observed_at: string;
  readonly observed_until: string | null;
  readonly case_id: UUID | null;
  readonly evidence_id: UUID | null;
  readonly features: Readonly<Record<string, unknown>>;
  readonly finding_count: number;
  readonly match_count: number;
}

export interface InfraSummary {
  readonly findings_total: number;
  readonly findings_by_kind: Readonly<Record<string, number>>;
  readonly findings_by_severity: Readonly<Record<string, number>>;
  /** Findings the platform declines to score, counted rather than averaged in. */
  readonly findings_unscored: number;
  readonly observations_total: number;
  readonly onion_services: number;
  readonly clearnet_hosts: number;
  readonly matches_total: number;
  /**
   * The headline: matches whose score is carried by exactly one channel. A
   * correlation resting on a single dimension is a weak finding, and a total
   * that hides this lets it be read as a strong one.
   */
  readonly single_channel_matches: number;
  readonly matches_by_strongest_channel: Readonly<Record<string, number>>;
  readonly earliest_observation: string | null;
  readonly latest_observation: string | null;
}

/** The decision rule for a correlation run. Every field is required by the API. */
export interface InfraThresholdInput {
  readonly min_similarity: number;
  readonly min_certificate: number;
  readonly min_content: number;
  readonly min_http: number;
  readonly min_temporal_overlap: number;
  readonly require_temporal_overlap: boolean;
}

export interface InfraSkippedObservation {
  readonly observation_id: UUID;
  readonly subject: string;
  readonly reason: string;
}

export interface InfraCorrelateRequest {
  readonly case_id: UUID;
  readonly thresholds: InfraThresholdInput;
  readonly observation_ids?: readonly UUID[];
  readonly networks?: readonly InfraNetwork[];
  readonly since?: string | null;
  readonly until?: string | null;
  readonly limit?: number | null;
}

export interface InfraCorrelateResponse {
  readonly case_id: UUID;
  readonly thresholds: InfraThresholdInput;
  readonly observations_considered: number;
  readonly pairs_evaluated: number;
  readonly candidates: number;
  readonly same_network_candidates: number;
  readonly created: readonly InfraMatch[];
  readonly existing: readonly InfraMatch[];
  readonly skipped_observations: readonly InfraSkippedObservation[];
  /** The correlation's own limitations, verbatim and deduplicated. */
  readonly limitations: readonly string[];
  readonly correlated_at: string;
}

export interface InfraListFilters {
  readonly kind?: string;
  readonly severity?: string;
  readonly caseId?: string;
  readonly subject?: string;
  readonly network?: InfraNetwork;
  readonly since?: string;
  readonly until?: string;
  readonly minConfidence?: number;
  readonly strongestChannel?: string;
  readonly minOverall?: number;
  readonly limit?: number;
}

// ---------------------------------------------------------------------------
// Persona linkage
// ---------------------------------------------------------------------------

/**
 * The three states a linkage can be in.
 *
 * `proposed` is a hypothesis nobody has ruled on; only `confirmed` is a finding.
 * The distinction is load-bearing, so it is a closed union rather than a string.
 */
export const PERSONA_LINKAGE_STATUSES = ['proposed', 'confirmed', 'rejected'] as const;
export type PersonaLinkageStatus = (typeof PERSONA_LINKAGE_STATUSES)[number];

export const PERSONA_LINKAGE_METHODS = [
  'stylometry',
  'behavioural',
  'infrastructure',
  'attribution',
  'manual',
] as const;
export type PersonaLinkageMethod = (typeof PERSONA_LINKAGE_METHODS)[number];

/** The methods the API will score from a supplied sample. */
export const PERSONA_SCORABLE_METHODS = ['stylometry', 'behavioural'] as const;
export type PersonaScorableMethod = (typeof PERSONA_SCORABLE_METHODS)[number];

/** Human labels: the raw method names are not what an analyst reads. */
export const PERSONA_METHOD_LABELS: Readonly<Record<PersonaLinkageMethod, string>> = {
  stylometry: 'Stylometry',
  behavioural: 'Behavioural',
  infrastructure: 'Infrastructure',
  attribution: 'Attribution',
  manual: 'Manual',
};

export interface PersonaLinkage {
  readonly linkage_id: UUID;
  readonly actor_id: UUID;
  /** Resolved server-side so the register never shows a bare actor UUID. */
  readonly actor_handle: string;
  readonly candidate_handle: string;
  readonly method: PersonaLinkageMethod;
  /** The model's output. An adjudication never changes it. */
  readonly score: number;
  readonly status: PersonaLinkageStatus;
  readonly aligned_features: readonly string[];
  readonly apart_features: readonly string[];
  readonly contested_features: readonly string[];
  readonly limitations: readonly string[];
  readonly case_id: UUID | null;
  readonly case_name: string | null;
  readonly adjudicated_by: UUID | null;
  readonly adjudicated_by_name: string | null;
  readonly adjudicated_at: string | null;
  readonly rationale: string | null;
  readonly created_at: string;
  readonly metadata: Readonly<Record<string, unknown>>;
  /** True only once a human ruled. Gates whether the score may be called a finding. */
  readonly analyst_recorded: boolean;
}

export interface PersonaLinkageDetail extends PersonaLinkage {
  /** Feature name -> agreement, the terms the three-way split was made from. */
  readonly feature_agreement: Readonly<Record<string, number>>;
  /** The function that produced `score`, named. */
  readonly scorer: string | null;
}

/**
 * Counts across the linkage register, for one filter set.
 *
 * Named `…Counts` rather than `…Summary` because the actor profile's linkage
 * panel already declares a `PersonaLinkageSummary` for a single row: two
 * interfaces with one name merge in TypeScript, which would require both
 * shapes at once and break the endpoint that returns only this one.
 */
export interface PersonaLinkageCounts {
  readonly total: number;
  readonly by_status: Readonly<Record<string, number>>;
  readonly by_method: Readonly<Record<string, number>>;
  readonly proposed: number;
  readonly confirmed: number;
  readonly rejected: number;
  readonly adjudicated: number;
  readonly confirmed_total: number;
  readonly rejected_total: number;
  /** Confirmations the scorer ranked below the threshold: observed false negatives. */
  readonly confirmed_low_score: number;
  /** Rejections the scorer ranked at or above it: observed false positives. */
  readonly rejected_high_score: number;
  /** Returned so the comparison is labelled rather than implied. */
  readonly score_threshold: number;
  /** Set when nothing here has been adjudicated, rather than reporting a clean 0%. */
  readonly gap: string | null;
}

export interface AdjudicationResponse {
  /** The stored row as the server now holds it, not as the client hoped. */
  readonly linkage: PersonaLinkage;
  readonly previous_status: string | null;
  readonly previous_rationale: string | null;
  readonly previous_adjudicator: string | null;
  readonly audit_seq: number;
}

/** Filters shared by the list, the summary and the export, so they cannot disagree. */
export interface PersonaFilters {
  readonly status?: PersonaLinkageStatus | null;
  readonly method?: PersonaLinkageMethod | null;
  readonly actor_id?: string | null;
  readonly min_score?: number | null;
  readonly from?: string | null;
  readonly until?: string | null;
}

// ---------------------------------------------------------------------------
// Autonomous collection
// ---------------------------------------------------------------------------

/** One registered source, with the quality basis the PS asks to be visible. */
export interface CollectionSource {
  readonly source_id: UUID;
  readonly source_type: string;
  readonly name: string;
  /** A weight on the outlet, not a measurement of any record it produced. */
  readonly reliability: number;
  readonly reliability_basis: string;
  readonly independence_group: string | null;
  /** How many sources share this group. >1 means they are not independent. */
  readonly independence_group_size: number;
  readonly independence_note: string | null;
  readonly record_count: number;
  readonly job_count: number;
  readonly last_scanned_at: string | null;
  readonly last_status: string | null;
  readonly synthetic: boolean;
}

export interface CollectionJob {
  readonly job_id: UUID;
  readonly source_id: UUID;
  readonly source_name: string | null;
  readonly source_type: string | null;
  readonly collector_name: string;
  readonly collector_version: string;
  readonly status: string;
  readonly candidates: number;
  readonly records: number;
  readonly errors: number;
  readonly error_samples: readonly string[];
  readonly duration_seconds: number;
  readonly independence_group: string | null;
  readonly reliability: number | null;
  readonly synthetic: boolean;
  readonly started_at: string | null;
  readonly finished_at: string | null;
}

export interface CollectionStatus {
  readonly generated_at: string;
  readonly sources_total: number;
  readonly sources_healthy: number;
  readonly sources_stale: number;
  /** Sources nobody has looked at. Not the same as a source with nothing. */
  readonly sources_never_scanned: number;
  readonly stale_after_days: number;
  readonly jobs_last_24h: Readonly<Record<string, number>>;
  readonly jobs_last_24h_total: number;
  readonly records_last_24h: number;
  readonly contributing_sources: number;
  readonly mean_contributing_reliability: number | null;
  /**
   * Mean over *every* registered source. Returned beside the contributing mean
   * because the gap between the two is the finding: a register whose average
   * collapses once non-contributing sources are included has a coverage gap,
   * not weak evidence.
   */
  readonly mean_registered_reliability: number | null;
  readonly independence_groups: number;
  readonly dominant_independence_group: string | null;
  readonly dominant_independence_group_size: number;
  /** Grouped server-side; the band names and edges are the API's, not ours. */
  readonly reliability_bands: readonly SourceReliabilityBand[];
  readonly reliability_basis: string;
  readonly limitations: readonly string[];
}

/** One reliability band and what it has actually produced. */
export interface SourceReliabilityBand {
  readonly band: string;
  /** The weight at and above which a source falls in this band. */
  readonly min_reliability: number;
  readonly sources: number;
  /** Those of them that produced a record or a completed/partial run. */
  readonly contributing_sources: number;
  /** Evidence rows stored against the band's sources, all-time. */
  readonly records: number;
}

export interface CollectionRunRequest {
  readonly job_type?: 'DISCOVER' | 'COLLECT' | 'DIFF' | 'REPROCESS' | 'REASSESS' | 'REVALIDATE';
  readonly case_id?: UUID;
  readonly seed_terms?: readonly string[];
  readonly platforms?: readonly string[];
  readonly limit?: number;
}

export interface CollectionRunOutcome {
  readonly collector: string | null;
  readonly status: string;
  readonly candidates: number;
  readonly records: number | null;
  readonly errors: readonly string[];
}

export interface CollectionRunResult {
  readonly collection_mode: string;
  /** True when the run used the in-process synthetic corpus, not a network collector. */
  readonly synthetic: boolean;
  readonly mode_note: string;
  readonly duration_seconds: number;
  readonly error_count: number;
  readonly ingested: number;
  readonly job_ids: readonly UUID[];
  readonly outcomes: readonly CollectionRunOutcome[];
  readonly notes: readonly string[];
  readonly limitations: readonly string[];
  readonly audit_seq: number;
  readonly started_at: string;
  readonly finished_at: string;
}

// ---------------------------------------------------------------------------
// Behavioural change detection
//
// The shapes `aegis.timeline`'s detectors produce, as the API renders them.
// `sharpness` is always the detector's own score and never a probability;
// `limitations` travels on every row rather than only on the envelope, because
// a caveat that can be collapsed away from the finding it qualifies is the
// caveat most likely to be missed.
// ---------------------------------------------------------------------------

export interface TemporalRefusal {
  readonly subject_id: string;
  readonly subject_kind: string;
  readonly subject_label: string | null;
  readonly channel: string;
  readonly rule: string;
  readonly reason: string;
  readonly observed: number;
  readonly required: number;
  readonly unit: string;
}

export interface EvidenceWindow {
  readonly label: string;
  readonly from_at: string | null;
  readonly to_at: string | null;
  readonly event_count: number;
  readonly values: readonly string[];
  readonly buckets: number;
  readonly mean_count: number | null;
  readonly evidence_ids: readonly string[];
}

export interface ContextPoint {
  readonly at: string;
  readonly value: string;
  /** Bucket count on the activity channel; null on a categorical one. */
  readonly count: number | null;
  readonly is_boundary: boolean;
}

export interface TemporalShift {
  readonly change_id: string;
  readonly case_id: UUID | null;
  readonly subject_id: string;
  readonly subject_kind: string;
  readonly subject_label: string | null;
  readonly channel: string;
  readonly channel_label: string;
  readonly detector: string;
  readonly detector_label: string;
  readonly changed_at: string;
  /** The detector's own score, in that detector's own units. Never a probability. */
  readonly sharpness: number;
  readonly sharpness_note: string;
  readonly direction: string | null;
  readonly from_value: string | null;
  readonly to_value: string | null;
  readonly summary: string;
  readonly before: EvidenceWindow;
  readonly after: EvidenceWindow;
  /** The library's own KS distance across the split, 0-1, or null. */
  readonly distribution_distance: number | null;
  readonly context: readonly ContextPoint[];
  readonly evidence_ids: readonly string[];
  readonly limitations: readonly string[];
}

export interface TemporalShiftReport {
  readonly case_id: UUID;
  readonly generated_at: string;
  readonly method: string;
  readonly bucket: string;
  readonly min_persist: number;
  readonly subjects: number;
  readonly observations: number;
  readonly window_start: string | null;
  readonly window_end: string | null;
  readonly shifts: readonly TemporalShift[];
  readonly refusals: readonly TemporalRefusal[];
  /** Stated on every read, including an empty one. */
  readonly basis: string;
  readonly limitations: readonly string[];
}

export interface TemporalBoundary {
  readonly index: number;
  readonly at: string;
  readonly gain: number;
  readonly mean_before: number;
  readonly mean_after: number;
}

export interface TemporalRegime {
  readonly index: number;
  readonly first_bucket: string;
  readonly last_bucket: string;
  readonly buckets: number;
  readonly mean: number;
  readonly peak: number;
  readonly total: number;
}

export interface SubjectSegmentation {
  readonly subject_id: string;
  readonly subject_kind: string;
  readonly subject_label: string | null;
  readonly channel: string;
  readonly gain_function: string;
  readonly min_size: number;
  readonly min_gain: number;
  readonly buckets: number;
  readonly window_start: string | null;
  readonly window_end: string | null;
  readonly boundaries: readonly TemporalBoundary[];
  readonly regimes: readonly TemporalRegime[];
  readonly limitations: readonly string[];
}

export interface TemporalSegmentationReport {
  readonly case_id: UUID;
  readonly generated_at: string;
  readonly gain: string;
  readonly min_size: number;
  readonly min_gain: number;
  readonly bucket: string;
  readonly series: readonly SubjectSegmentation[];
  readonly refusals: readonly TemporalRefusal[];
  readonly basis: string;
  readonly limitations: readonly string[];
}

export interface ActorPresence {
  readonly marketplace: string;
  readonly role: string | null;
  readonly first_seen: string | null;
  readonly last_seen: string | null;
  readonly listing_count: number | null;
}

export interface ActorTransitionReport {
  readonly actor_id: UUID;
  readonly handle: string;
  readonly generated_at: string;
  readonly min_persist: number;
  readonly marketplaces: readonly string[];
  readonly presence: readonly ActorPresence[];
  readonly window_start: string | null;
  readonly window_end: string | null;
  readonly transitions: readonly TemporalShift[];
  readonly refusals: readonly TemporalRefusal[];
  readonly basis: string;
  readonly limitations: readonly string[];
}

export interface BehaviourPoint {
  readonly at: string;
  readonly events: number;
  readonly magnitude: number;
}

export interface AlgorithmBandwidth {
  readonly algorithm: string;
  readonly min_points: number;
  readonly note: string;
}

export interface Bandwidth {
  readonly cusum: AlgorithmBandwidth;
  readonly ks: AlgorithmBandwidth;
  readonly binary_segmentation: AlgorithmBandwidth;
}

export interface ActorBehaviourReport {
  readonly actor_id: UUID;
  readonly handle: string;
  readonly generated_at: string;
  readonly channel: string;
  readonly bucket: string;
  readonly points: readonly BehaviourPoint[];
  readonly buckets: number;
  readonly observations: number;
  readonly window_start: string | null;
  readonly window_end: string | null;
  readonly mean: number | null;
  readonly standard_deviation: number | null;
  readonly peak: number | null;
  readonly silent_buckets: number;
  readonly analysable: boolean;
  readonly refusal: TemporalRefusal | null;
  readonly bandwidth: Bandwidth;
  readonly limitations: readonly string[];
}
