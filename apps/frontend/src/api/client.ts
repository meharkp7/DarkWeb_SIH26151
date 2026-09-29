import { parseSyntheticAnalysisResponse } from './parse';
import type {
  AuditTrailResponse, CaseCreate, CaseGraph, CaseHypothesis, CaseMetrics,
  CaseNote, CaseNoteCreate, CaseQueueEntry, CaseTimeline, CaseUpdate, CaseWorkspace, CommandPosture,
  CopilotResponse, CreatedSource, DashboardSnapshot, Evidence, EvidenceCreate, EvidenceProvenance,
  HealthResponse, InvestigationCase, LiveActivity, ModelRegistryResponse, SearchResponse,
  SignalBand, SourceCreate, SyntheticAnalysisRequest, SystemHealth, TeamResponse,
} from './types';

function stripTrailingSlash(value: string): string { return value.endsWith('/') ? value.replace(/\/+$/, '') : value; }
export const API_BASE = stripTrailingSlash(import.meta.env.VITE_API_BASE ?? '/api');
export const HEALTH_BASE = stripTrailingSlash(import.meta.env.VITE_HEALTH_URL ?? '/health');
export function apiUrl(path: string): string { return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`; }
export function healthUrl(path = ''): string { return path ? `${HEALTH_BASE}${path.startsWith('/') ? path : `/${path}`}` : HEALTH_BASE; }

const API_KEY_STORAGE = 'aegis.apiKey';
const SESSION_STORAGE = 'aegis.session';
/**
 * Refresh a token this long before it actually expires. A short skew means a
 * request issued in the last few seconds of a session still carries a token the
 * API will accept, instead of racing the expiry and producing a spurious 401.
 */
const EXPIRY_SKEW_MS = 30_000;

export function getApiKey(): string | null { return localStorage.getItem(API_KEY_STORAGE); }
export function setApiKey(value: string): void { localStorage.setItem(API_KEY_STORAGE, value); }
export function clearApiKey(): void { localStorage.removeItem(API_KEY_STORAGE); }

/**
 * A session is stored as one JSON envelope so the token and its expiry can
 * never drift apart. Older builds wrote the bare token string; that shape is
 * still read so an in-flight tab upgrade does not sign the analyst out.
 */
interface StoredSession { readonly token: string; readonly expiresAt: number }

function readStoredSession(): StoredSession | null {
  for (const store of [sessionStorage, localStorage]) {
    const raw = store.getItem(SESSION_STORAGE);
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw) as Partial<StoredSession> | null;
      if (
        parsed !== null && typeof parsed === 'object' &&
        typeof parsed.token === 'string' &&
        typeof parsed.expiresAt === 'number'
      ) return { token: parsed.token, expiresAt: parsed.expiresAt };
    } catch { /* not our envelope — fall through to the legacy shape */ }
    return { token: raw, expiresAt: 0 };
  }
  return null;
}

/**
 * The stored session if it is still usable, otherwise null.
 *
 * Deliberately does NOT clear storage. A getter that mutates is a getter that
 * destroys evidence other code needs: the auth store has to be able to tell
 * "never signed in" from "signed in, and the session has since run out", and
 * a cleared token makes those identical. Expiry is enforced here; removal is
 * the caller's decision.
 */
export function getSession(): StoredSession | null {
  const stored = readStoredSession();
  if (!stored) return null;
  if (stored.expiresAt !== 0 && stored.expiresAt - EXPIRY_SKEW_MS <= Date.now()) {
    return null;
  }
  return stored;
}
/**
 * The stored session *without* checking its expiry.
 *
 * Callers use this to tell "never signed in" apart from "signed in, and the
 * session has since run out". The distinction is the whole point of the
 * re-auth notice: an analyst who lands on a bare sign-in form after a quiet
 * timeout needs to be told what happened, not left to guess.
 */
export function peekSession(): StoredSession | null { return readStoredSession(); }
export function getSessionToken(): string | null { return getSession()?.token ?? null; }
export function getSessionExpiry(): number | null { return getSession()?.expiresAt ?? null; }
export function setSessionToken(token: string, expiresAt: number, persist = false): void {
  clearSessionToken();
  const payload = JSON.stringify({ token, expiresAt } satisfies StoredSession);
  if (persist) localStorage.setItem(SESSION_STORAGE, payload);
  else sessionStorage.setItem(SESSION_STORAGE, payload);
}
export function clearSessionToken(): void { sessionStorage.removeItem(SESSION_STORAGE); localStorage.removeItem(SESSION_STORAGE); }

type UnauthorizedReason = 'expired' | 'invalid';
type UnauthorizedHandler = (reason: UnauthorizedReason) => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;
let handledToken: string | null = null;
export function onUnauthorized(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

/**
 * Report a 401 at most once per credential.
 *
 * A command center opens several requests at once, so one expired session
 * produces a burst of 401s. Without the latch the auth store is torn down and
 * rebuilt for each of them, which is what turns a single expiry into a
 * redirect loop. The latch is keyed on the token, so a fresh sign-in re-arms it.
 *
 * The token is read raw rather than through {@link getSessionToken}: a request
 * that was refused *because* it expired must still be reported as an expiry,
 * not as a missing credential.
 */
function reportUnauthorized(): void {
  const token = readStoredSession()?.token ?? null;
  if (token !== null && token === handledToken) return;
  handledToken = token;
  unauthorizedHandler?.(token ? 'expired' : 'invalid');
}

export class ApiError extends Error {
  readonly status: number; readonly detail: string;
  constructor(status: number, detail: string) { super(`API request failed (${status}): ${detail}`); this.name = 'ApiError'; this.status = status; this.detail = detail; }
}
async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || 'Request failed';
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') detail = body.detail;
    else if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: unknown };
      if (typeof first.msg === 'string') detail = first.msg;
    }
  } catch { /* keep status text */ }
  return new ApiError(response.status, detail);
}
async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}
export function authHeaders(contentType?: string): Record<string, string> {
  const token = getSessionToken();
  const key = getApiKey();
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (contentType) headers['Content-Type'] = contentType;
  if (token) headers.Authorization = `Bearer ${token}`;
  else if (key) headers['X-AEGIS-API-Key'] = key;
  return headers;
}
const baseHeaders = (): Record<string, string> => authHeaders();
async function send<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (response.status === 401 && !url.includes('/auth/login')) reportUnauthorized();
  return parseResponse<T>(response);
}
export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> { return send<T>(url, { headers: baseHeaders(), signal }); }
export async function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> { return send<T>(url, { method:'POST', headers:authHeaders('application/json'), body:JSON.stringify(body), signal }); }
export async function patchJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> { return send<T>(url, { method:'PATCH', headers:authHeaders('application/json'), body:JSON.stringify(body), signal }); }
export function formatApiError(error: unknown): string { if (error instanceof ApiError) return `API ${error.status} — ${error.detail}`; if (error instanceof TypeError) return 'Cannot reach the AEGIS API.'; if (error instanceof Error) return error.message; return 'Unexpected API error.'; }

export const api = {
  login: (email: string, password: string) => postJson<{ access_token: string; token_type: string; expires_at: number; identity: { email: string; name: string; role: string; organization: string } }>(apiUrl('/v1/auth/login'), { email, password }),
  authMe: (signal?: AbortSignal) => getJson<{ email: string; name: string; role: string; organization: string }>(apiUrl('/v1/auth/me'), signal),
  health: (signal?: AbortSignal) => getJson<HealthResponse>(healthUrl(), signal),
  databaseHealth: (signal?: AbortSignal) => getJson<HealthResponse>(healthUrl('/db'), signal),
  dashboard: (signal?: AbortSignal) => getJson<DashboardSnapshot>(apiUrl('/v1/dashboard/summary'), signal),
  activity: (limit=40, signal?: AbortSignal) => getJson<LiveActivity[]>(apiUrl(`/v1/dashboard/activity?limit=${limit}`), signal),
  caseSummaries: (signal?: AbortSignal) => getJson<CaseQueueEntry[]>(apiUrl('/v1/dashboard/cases'), signal),
  commandPosture: (signal?: AbortSignal) => getJson<CommandPosture>(apiUrl('/v1/dashboard/summary'), signal),
  // The snapshot is the only carrier of these three series, so they are read
  // off it rather than fetched three more times.
  evidenceVelocity: (signal?: AbortSignal) =>
    getJson<DashboardSnapshot>(apiUrl('/v1/dashboard/summary'), signal)
      .then((snapshot) => snapshot.evidence_velocity),
  investigationPressure: (signal?: AbortSignal) =>
    getJson<DashboardSnapshot>(apiUrl('/v1/dashboard/summary'), signal)
      .then((snapshot) => snapshot.investigation_pressure),
  attributionPosture: (signal?: AbortSignal) =>
    getJson<DashboardSnapshot>(apiUrl('/v1/dashboard/summary'), signal)
      .then((snapshot) => snapshot.attribution_posture),
  listCases: (signal?: AbortSignal) => getJson<InvestigationCase[]>(apiUrl('/v1/cases'), signal),
  getCase: (id:string, signal?:AbortSignal) => getJson<InvestigationCase>(apiUrl(`/v1/cases/${encodeURIComponent(id)}`),signal),
  createCase: (payload:CaseCreate, signal?:AbortSignal) => postJson<InvestigationCase>(apiUrl('/v1/cases'),payload,signal),
  updateCase: (id:string,payload:CaseUpdate,signal?:AbortSignal) => patchJson<InvestigationCase>(apiUrl(`/v1/cases/${encodeURIComponent(id)}`),payload,signal),
  getWorkspace: (id:string,signal?:AbortSignal) => getJson<CaseWorkspace>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/workspace`),signal),
  caseActivity: (id:string,limit=50,signal?:AbortSignal) => getJson<LiveActivity[]>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/activity?limit=${limit}`),signal),
  caseHypotheses: (id:string,signal?:AbortSignal) => getJson<CaseHypothesis[]>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/hypotheses`),signal),
  caseMetrics: (id:string,signal?:AbortSignal) => getJson<CaseMetrics>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/metrics`),signal),
  caseSignals: (id:string,signal?:AbortSignal) => getJson<SignalBand[]>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/signals`),signal),
  caseTimeline: (id:string,signal?:AbortSignal) => getJson<CaseTimeline>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/timeline`),signal),
  caseGraph: (id:string,params?:{edge_type?:string[];node_type?:string[]},signal?:AbortSignal) => {
    const query = new URLSearchParams();
    for (const key of ['edge_type', 'node_type'] as const) {
      for (const value of params?.[key] ?? []) query.append(key, value);
    }
    const suffix = query.toString() ? `?${query}` : '';
    return getJson<CaseGraph>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/graph${suffix}`), signal);
  },
  /**
   * Cross-case search. Debounce the caller's side; this has no cache and the
   * backend applies a minimum term length rather than scanning for a
   * one-character prefix.
   */
  search: (q: string, signal?:AbortSignal) => {
    const query = new URLSearchParams({ q });
    return getJson<SearchResponse>(apiUrl(`/v1/search?${query}`), signal);
  },
  team: (signal?:AbortSignal) => getJson<TeamResponse>(apiUrl('/v1/admin/team'),signal),
  auditTrail: (params?:{limit?:number;offset?:number;action?:string;case_id?:string},signal?:AbortSignal) => {
    const query = new URLSearchParams();
    if (params?.limit !== undefined) query.set('limit', String(params.limit));
    if (params?.offset !== undefined) query.set('offset', String(params.offset));
    if (params?.action) query.set('action', params.action);
    if (params?.case_id) query.set('case_id', params.case_id);
    const suffix = query.toString() ? `?${query}` : '';
    return getJson<AuditTrailResponse>(apiUrl(`/v1/admin/audit${suffix}`), signal);
  },
  systemHealth: (signal?:AbortSignal) => getJson<SystemHealth>(apiUrl('/v1/admin/system'),signal),
  modelRegistry: (signal?:AbortSignal) => getJson<ModelRegistryResponse>(apiUrl('/v1/models'),signal),
  listNotes: (id:string,signal?:AbortSignal) => getJson<CaseNote[]>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/notes`),signal),
  createNote: (id:string,payload:CaseNoteCreate,signal?:AbortSignal) => postJson<CaseNote>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/notes`),payload,signal),
  reportExportUrl: (id:string,format:'json'|'csv'|'stix'|'pdf') => apiUrl(`/v1/cases/${encodeURIComponent(id)}/reports/export?format=${format}`),
  reportPreviewUrl: (id:string) => apiUrl(`/v1/cases/${encodeURIComponent(id)}/reports/preview`),
  createSource: (payload:SourceCreate) => postJson<CreatedSource>(apiUrl('/v1/sources'),payload),
  createEvidence: (payload:EvidenceCreate) => postJson<Evidence>(apiUrl('/v1/evidence'),payload),
  getEvidence: (id:string,signal?:AbortSignal) => getJson<Evidence>(apiUrl(`/v1/evidence/${encodeURIComponent(id)}`),signal),
  getEvidenceProvenance: (id:string,signal?:AbortSignal) => getJson<EvidenceProvenance>(apiUrl(`/v1/evidence/${encodeURIComponent(id)}/provenance`),signal),
  runSyntheticAnalysis: async (payload:SyntheticAnalysisRequest) => parseSyntheticAnalysisResponse(await postJson<unknown>(apiUrl('/v1/analysis/synthetic'),payload)),
  copilot: (question:string,limit=10) => postJson<CopilotResponse>(apiUrl('/v1/copilot/query'),{question,limit}),
};

export function liveUrl(): string { const base = new URL(apiUrl('/v1/live'),window.location.href); base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'; const token = getSessionToken() || getApiKey(); if (token) base.searchParams.set('access_token', token); return base.toString(); }
