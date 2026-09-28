export type UUID = string;

export type SourceType = 'public_web' | 'forum' | 'marketplace' | 'threat_feed' | 'analyst_submitted' | 'synthetic';
export type SourceTier = 'A' | 'B' | 'C' | 'D' | 'E';

export interface HealthResponse { readonly status: string; readonly service: string; }

export interface InvestigationCase {
  case_id: UUID;
  name: string;
  description: string | null;
  status: 'open' | 'active' | 'on_hold' | 'closed' | 'archived';
  tags?: string[];
  created_at: string | null;
  updated_at?: string | null;
}

export interface CaseSummary extends InvestigationCase {
  counts: { evidence: number; entities: number; relationships: number; assessments: number };
  last_activity: string | null;
}

export interface DashboardSnapshot {
  type: 'snapshot' | 'heartbeat';
  server_time: string;
  counts: { cases: number; evidence: number; entities: number; relationships: number; assessments: number };
  critical_alerts: number;
  activity: LiveActivity[];
  case_summaries?: CaseSummary[];
}

export interface LiveActivity {
  seq: number;
  occurred_at: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  case_id: string | null;
  payload: Record<string, unknown>;
}

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
export interface CaseCreate { name: string; description?: string | null; }
export interface SyntheticAnalysisRequest { seed: number; actor_count: number; min_score: number; }
export interface SyntheticHypothesis { hypothesis_id: string; source_actor_id: string; target_actor_id: string; raw_score: number; support_score: number; contradiction_score: number; final_score: number; status: string; evidence_count: number; explanations: string[]; }
export interface SyntheticAnalysisResponse { seed: number; actor_count: number; evidence_count: number; relationship_count: number; candidate_count: number; persisted_hypothesis_count: number; hypotheses: SyntheticHypothesis[]; }

export interface WorkspaceEntity { entity_id: string; type: string; surface_form: string; normalized_form: string; confidence: number; }
export interface WorkspaceRelationship { relationship_id: string; subject_entity_id: string; object_entity_id: string; type: string; confidence: number; first_seen: string; last_seen: string; evidence_ids: string[]; }
export interface WorkspaceAssessment { assessment_id: string; hypothesis_id: string; model_id: string; model_version: string; raw_score: number; calibrated_confidence: number | null; signals: Record<string, number>; explanations: string[]; limitations: string[]; supporting_evidence_ids: string[]; contradictory_evidence_ids: string[]; }
export interface WorkspaceEvidence { evidence_id: string; source_id: string; source_type: string; observed_at: string | null; collected_at: string; entity_type: string | null; reliability: number; independence_group: string; sha256: string; metadata: Record<string, unknown>; }
export interface CaseWorkspace { case: InvestigationCase; counts: Record<string, number>; evidence: WorkspaceEvidence[]; entities: WorkspaceEntity[]; relationships: WorkspaceRelationship[]; assessments: WorkspaceAssessment[]; activity: LiveActivity[]; }

export interface CopilotResponse {
  question: string; intent: string; rule: string; tools_run: string[]; evidence_ids: string[];
  flagged_evidence_ids: string[]; claims: Array<{ text: string; citations: string[]; status: string }>;
  unsupported_claims: Array<{ text: string; citations: string[]; status: string }>;
  dropped_claims: Array<{ text: string; citations: string[]; status: string }>;
  text: string;
}
