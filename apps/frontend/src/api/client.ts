import { parseSyntheticAnalysisResponse } from './parse';
import type {
  CreatedSource,
  CaseCreate,
  Evidence,
  EvidenceCreate,
  EvidenceProvenance,
  HealthResponse,
  InvestigationCase,
  SourceCreate,
  SyntheticAnalysisRequest,
  SyntheticAnalysisResponse,
} from './types';

/**
 * Typed fetch wrappers for the endpoints that actually exist today.
 *
 * Current backend surface (grep `@app.(get|post)` in `src/aegis/api/app.py`):
 *   GET  /health
 *   GET  /health/db
 *   POST /api/v1/sources
 *   POST /api/v1/evidence
 *   GET  /api/v1/evidence/{evidence_id}
 *   GET  /api/v1/evidence/{evidence_id}/provenance
 *   POST /api/v1/analysis/synthetic
 *
 * Nothing else is called: screens whose endpoints are not implemented yet
 * render an explicit "not available via API" state instead of guessing.
 */

function stripTrailingSlash(value: string): string {
  return value.endsWith('/') ? value.replace(/\/+$/, '') : value;
}

/** Base for `/api/v1/*` routes. Override with `VITE_API_BASE`. */
export const API_BASE = stripTrailingSlash(import.meta.env.VITE_API_BASE ?? '/api');

/** Base for health probes (`/health`, `/health/db`). Override with `VITE_HEALTH_URL`. */
export const HEALTH_BASE = stripTrailingSlash(import.meta.env.VITE_HEALTH_URL ?? '/health');

/** Build an absolute app-relative URL for an API path such as `/v1/evidence`. */
export function apiUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE}${suffix}`;
}

/** Build an absolute app-relative URL for a health path such as `` or `/db`. */
export function healthUrl(path = ''): string {
  if (path === '') return HEALTH_BASE;
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${HEALTH_BASE}${suffix}`;
}

/** Error carrying the HTTP status and the backend's `detail` message. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API request failed (${status}): ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

interface FastApiErrorDetail {
  readonly detail?: unknown;
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail = response.statusText || 'Request failed';
  try {
    const body = (await response.json()) as FastApiErrorDetail;
    if (typeof body.detail === 'string') {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      // FastAPI validation errors: [{ loc, msg, type }, ...]
      detail = body.detail
        .map((item: unknown) => {
          const entry = item as { loc?: unknown; msg?: unknown };
          const location = Array.isArray(entry.loc) ? entry.loc.join('.') : 'payload';
          return typeof entry.msg === 'string' ? `${location}: ${entry.msg}` : location;
        })
        .join('; ');
    }
  } catch {
    // Non-JSON body (proxy/HTML error page) — keep the status text.
  }
  return new ApiError(response.status, detail);
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) throw await toApiError(response);
  // Responses are shaped by FastAPI `response_model`s; no client-side schema
  // validation library is used, so the JSON is asserted to the mirrored type.
  return (await response.json()) as T;
}

const JSON_HEADERS = { Accept: 'application/json' } as const;

/** GET a JSON resource. */
export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { method: 'GET', headers: JSON_HEADERS, signal });
  return parseResponse<T>(response);
}

/** POST a JSON body. */
export async function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { ...JSON_HEADERS, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  return parseResponse<T>(response);
}

/** Render any thrown value as a short, user-facing message. */
export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) return `API ${error.status} — ${error.detail}`;
  if (error instanceof TypeError) {
    return 'Cannot reach the AEGIS API. Is the backend running (uvicorn aegis.api.app:app)?';
  }
  if (error instanceof Error) return error.message;
  return 'Unexpected error while contacting the API.';
}

/** Typed calls for the endpoints served by `src/aegis/api/app.py`. */
export const api = {
  health: (signal?: AbortSignal): Promise<HealthResponse> =>
    getJson<HealthResponse>(healthUrl(), signal),

  databaseHealth: (signal?: AbortSignal): Promise<HealthResponse> =>
    getJson<HealthResponse>(healthUrl('/db'), signal),

  listCases: (signal?: AbortSignal): Promise<InvestigationCase[]> =>
    getJson<InvestigationCase[]>(apiUrl('/v1/cases'), signal),

  getCase: (id: string, signal?: AbortSignal): Promise<InvestigationCase> =>
    getJson<InvestigationCase>(apiUrl(`/v1/cases/${encodeURIComponent(id)}`), signal),

  createCase: (payload: CaseCreate): Promise<InvestigationCase> =>
    postJson<InvestigationCase>(apiUrl('/v1/cases'), payload),

  createSource: (payload: SourceCreate): Promise<CreatedSource> =>
    postJson<CreatedSource>(apiUrl('/v1/sources'), payload),

  createEvidence: (payload: EvidenceCreate): Promise<Evidence> =>
    postJson<Evidence>(apiUrl('/v1/evidence'), payload),

  getEvidence: (id: string, signal?: AbortSignal): Promise<Evidence> =>
    getJson<Evidence>(apiUrl(`/v1/evidence/${encodeURIComponent(id)}`), signal),

  getEvidenceProvenance: (id: string, signal?: AbortSignal): Promise<EvidenceProvenance> =>
    getJson<EvidenceProvenance>(
      apiUrl(`/v1/evidence/${encodeURIComponent(id)}/provenance`),
      signal,
    ),

  runSyntheticAnalysis: async (
    payload: SyntheticAnalysisRequest,
  ): Promise<SyntheticAnalysisResponse> => {
    const raw = await postJson<unknown>(apiUrl('/v1/analysis/synthetic'), payload);
    return parseSyntheticAnalysisResponse(raw);
  },
};
