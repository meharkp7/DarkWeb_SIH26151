import { parseSyntheticAnalysisResponse } from './parse';
import type {
  CaseCreate, CaseHypothesis, CaseNote, CaseNoteCreate, CaseSummary, CaseUpdate, CaseWorkspace,
  CopilotResponse, CreatedSource, DashboardSnapshot, Evidence, EvidenceCreate, EvidenceProvenance,
  HealthResponse, InvestigationCase, LiveActivity, SourceCreate, SyntheticAnalysisRequest,
} from './types';

function stripTrailingSlash(value: string): string { return value.endsWith('/') ? value.replace(/\/+$/, '') : value; }
export const API_BASE = stripTrailingSlash(import.meta.env.VITE_API_BASE ?? '/api');
export const HEALTH_BASE = stripTrailingSlash(import.meta.env.VITE_HEALTH_URL ?? '/health');
export function apiUrl(path: string): string { return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`; }
export function healthUrl(path = ''): string { return path ? `${HEALTH_BASE}${path.startsWith('/') ? path : `/${path}`}` : HEALTH_BASE; }

const API_KEY_STORAGE = 'aegis.apiKey';
const SESSION_STORAGE = 'aegis.session';
export function getApiKey(): string | null { return localStorage.getItem(API_KEY_STORAGE); }
export function setApiKey(value: string): void { localStorage.setItem(API_KEY_STORAGE, value); }
export function clearApiKey(): void { localStorage.removeItem(API_KEY_STORAGE); }
export function getSessionToken(): string | null { return sessionStorage.getItem(SESSION_STORAGE) || localStorage.getItem(SESSION_STORAGE); }
export function setSessionToken(value: string, persist = false): void {
  clearSessionToken();
  if (persist) localStorage.setItem(SESSION_STORAGE, value);
  else sessionStorage.setItem(SESSION_STORAGE, value);
}
export function clearSessionToken(): void { sessionStorage.removeItem(SESSION_STORAGE); localStorage.removeItem(SESSION_STORAGE); }

type UnauthorizedReason = 'expired' | 'invalid';
let unauthorizedHandler: ((reason: UnauthorizedReason) => void) | null = null;
export function onUnauthorized(handler: ((reason: UnauthorizedReason) => void) | null): void {
  unauthorizedHandler = handler;
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
  if (response.status === 401 && !url.includes('/auth/login')) {
    unauthorizedHandler?.(getSessionToken() ? 'expired' : 'invalid');
  }
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
  caseSummaries: (signal?: AbortSignal) => getJson<CaseSummary[]>(apiUrl('/v1/dashboard/cases'), signal),
  listCases: (signal?: AbortSignal) => getJson<InvestigationCase[]>(apiUrl('/v1/cases'), signal),
  getCase: (id:string, signal?:AbortSignal) => getJson<InvestigationCase>(apiUrl(`/v1/cases/${encodeURIComponent(id)}`),signal),
  createCase: (payload:CaseCreate, signal?:AbortSignal) => postJson<InvestigationCase>(apiUrl('/v1/cases'),payload,signal),
  updateCase: (id:string,payload:CaseUpdate,signal?:AbortSignal) => patchJson<InvestigationCase>(apiUrl(`/v1/cases/${encodeURIComponent(id)}`),payload,signal),
  getWorkspace: (id:string,signal?:AbortSignal) => getJson<CaseWorkspace>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/workspace`),signal),
  caseActivity: (id:string,limit=50,signal?:AbortSignal) => getJson<LiveActivity[]>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/activity?limit=${limit}`),signal),
  caseHypotheses: (id:string,signal?:AbortSignal) => getJson<CaseHypothesis[]>(apiUrl(`/v1/cases/${encodeURIComponent(id)}/hypotheses`),signal),
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
