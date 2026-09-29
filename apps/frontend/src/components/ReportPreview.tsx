import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api, authHeaders, formatApiError } from '../api/client';
import { Drawer } from './Drawer';
import { ErrorState, LoadingState } from './States';
import { formatDateTime, shortId } from '../lib/format';

/**
 * Report preview, extracted from the retired `/reports` page.
 *
 * Previewing is inspection, not navigation, so this is a controlled drawer
 * rather than a route. The body is rendered from the same payload
 * `/reports/preview` produces for the JSON export, so what an analyst reads
 * here is what the exported artifact contains.
 */

/** Shape of one section claim — a string today, but claims carry citations. */
type Claim = { readonly text?: unknown } | string | null;

interface PreviewSection {
  readonly heading: string;
  readonly claims: readonly Claim[];
}

interface PreviewProvenance {
  readonly case_id?: unknown;
  readonly query?: unknown;
  readonly evidence_ids?: unknown;
  readonly model_versions?: unknown;
  readonly dataset_versions?: unknown;
  readonly generated_at?: unknown;
}

interface ReportPayload {
  readonly title?: unknown;
  readonly generated_by?: unknown;
  readonly sections?: unknown;
  readonly provenance?: unknown;
}

/** Canonical document order. A section absent from the payload renders as such. */
const SECTION_ORDER = [
  'Classification',
  'Case',
  'Executive Summary',
  'Key Findings',
  'Attribution Assessment',
  'Supporting Evidence',
  'Contradictions',
  'Timeline',
  'Network',
  'Limitations',
  'Methodology',
] as const;

function text(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() === '' ? null : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function claimText(claim: Claim): string | null {
  if (typeof claim === 'string') return text(claim);
  if (claim !== null && typeof claim === 'object') return text(claim.text);
  return null;
}

function sectionsOf(payload: ReportPayload | null): readonly PreviewSection[] {
  if (payload === null || !Array.isArray(payload.sections)) return [];
  const sections: PreviewSection[] = [];
  for (const entry of payload.sections) {
    if (entry === null || typeof entry !== 'object') continue;
    const heading = text((entry as { heading?: unknown }).heading);
    if (heading === null) continue;
    const raw = (entry as { claims?: unknown }).claims;
    sections.push({ heading, claims: Array.isArray(raw) ? (raw as readonly Claim[]) : [] });
  }
  return sections;
}

/** Case-insensitive heading match, so `Executive Summary` == `executive summary`. */
function findSection(sections: readonly PreviewSection[], heading: string): PreviewSection | null {
  const wanted = heading.toLowerCase();
  return sections.find((section) => section.heading.toLowerCase() === wanted) ?? null;
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

function provenanceOf(payload: ReportPayload | null): PreviewProvenance | null {
  if (payload === null) return null;
  const value = payload.provenance;
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as PreviewProvenance;
}

function idList(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === 'string');
}

function SectionBlock({
  heading,
  body,
  emptyNote,
}: {
  readonly heading: string;
  readonly body: readonly string[];
  readonly emptyNote: string;
}) {
  return (
    <section className="rep-section" id={`rep-${slug(heading)}`}>
      <h3 className="rep-section__title">{heading}</h3>
      {body.length === 0 ? (
        // "Not available" is a statement about the data, not an error: the
        // report builder only emits sections the case state supports.
        <p className="rep-unavailable">Not available — {emptyNote}</p>
      ) : (
        <ul className="rep-list">
          {body.map((line, index) => (
            <li key={`${heading}-${index}`}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ReportDocument({ payload, caseId }: { readonly payload: ReportPayload; readonly caseId: string }) {
  const sections = useMemo(() => sectionsOf(payload), [payload]);
  const provenance = useMemo(() => provenanceOf(payload), [payload]);
  const evidenceIds = useMemo(() => idList(provenance?.evidence_ids), [provenance]);
  const modelVersions = useMemo(() => idList(provenance?.model_versions), [provenance]);
  const datasetVersions = useMemo(() => idList(provenance?.dataset_versions), [provenance]);

  const claimsOf = (section: PreviewSection | null): readonly string[] =>
    section === null ? [] : section.claims.map(claimText).filter((entry): entry is string => entry !== null);

  const caseLines: readonly string[] = (() => {
    const lines: string[] = [];
    const caseIdLine = text(provenance?.case_id);
    if (caseIdLine !== null) lines.push(`Case identifier: ${caseIdLine}`);
    lines.push(`Case reference: ${caseId}`);
    const query = text(provenance?.query);
    if (query !== null) lines.push(`Report query: ${query}`);
    return lines;
  })();

  // Rendered after the canonical sections so a newer builder that adds a
  // section is still shown rather than silently dropped.
  const known = new Set(SECTION_ORDER.map((value) => value.toLowerCase()));
  known.add('evidence matrix');
  const extras = sections.filter((section) => !known.has(section.heading.toLowerCase()));

  // Each canonical section names the payload section it is read from and why it
  // is empty when it is — an empty report is a statement about the case, not a
  // rendering failure.
  const body: Record<string, { readonly lines: readonly string[]; readonly note: string }> = {
    Classification: { lines: claimsOf(findSection(sections, 'Classification')), note: 'the case carries no classification' },
    Case: { lines: caseLines, note: 'no case provenance was returned' },
    'Executive Summary': { lines: claimsOf(findSection(sections, 'Executive Summary')), note: 'no executive summary claims were generated' },
    'Key Findings': { lines: claimsOf(findSection(sections, 'Key Findings')), note: 'no findings were recorded' },
    'Attribution Assessment': { lines: claimsOf(findSection(sections, 'Attribution Assessment')), note: 'no attribution assessments exist for this case' },
    'Supporting Evidence': {
      lines: claimsOf(findSection(sections, 'Supporting Evidence') ?? findSection(sections, 'Evidence Matrix')),
      note: 'no evidence is linked to this case',
    },
    Contradictions: { lines: claimsOf(findSection(sections, 'Contradictions')), note: 'no contradictions were recorded' },
    Timeline: { lines: claimsOf(findSection(sections, 'Timeline')), note: 'the case has no timeline events' },
    Network: { lines: claimsOf(findSection(sections, 'Network')), note: 'no network relationships were recorded' },
    Limitations: { lines: claimsOf(findSection(sections, 'Limitations')), note: 'the builder declared no limitations' },
    Methodology: { lines: claimsOf(findSection(sections, 'Methodology')), note: 'no methodology block was generated' },
  };

  return (
    <article className="rep-doc">
      <header className="rep-doc__head">
        <p className="eyebrow">AEGIS investigation report</p>
        <h2 className="rep-doc__title">{text(payload.title) ?? `Report — ${caseId}`}</h2>
        <p className="rep-doc__meta">
          <span>
            Generated by <span className="mono">{text(payload.generated_by) ?? 'unknown generator'}</span>
          </span>
          <span>{formatDateTime(text(provenance?.generated_at))}</span>
        </p>
      </header>

      {SECTION_ORDER.map((heading) => {
        const entry = body[heading];
        return (
          <SectionBlock
            key={heading}
            heading={heading}
            body={entry?.lines ?? []}
            emptyNote={entry?.note ?? 'no content was generated'}
          />
        );
      })}

      {extras.map((section) => (
        <SectionBlock key={section.heading} heading={section.heading} body={claimsOf(section)} emptyNote="no claims" />
      ))}

      <section className="rep-section" id="rep-provenance">
        <h3 className="rep-section__title">Provenance</h3>
        <div className="rep-provenance">
          <div>
            <b>Evidence records</b>
            <span>{evidenceIds.length === 0 ? 'None cited' : evidenceIds.map((id) => shortId(id)).join(', ')}</span>
          </div>
          <div>
            <b>Model versions</b>
            <span>{modelVersions.length === 0 ? 'None used' : modelVersions.join(', ')}</span>
          </div>
          <div>
            <b>Dataset versions</b>
            <span>{datasetVersions.length === 0 ? 'None referenced' : datasetVersions.join(', ')}</span>
          </div>
        </div>
      </section>
    </article>
  );
}

async function fetchPreview(caseId: string, signal: AbortSignal): Promise<ReportPayload> {
  const response = await fetch(api.reportPreviewUrl(caseId), { headers: authHeaders(), signal });
  if (!response.ok) {
    let detail = response.statusText || 'Report preview failed';
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* keep the status text */
    }
    throw new ApiError(response.status, detail);
  }
  const payload: unknown = await response.json();
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('Report preview payload is not a JSON object.');
  }
  return payload as ReportPayload;
}

export interface ReportPreviewProps {
  readonly caseId: string;
  readonly onClose: () => void;
}

/**
 * Controlled report preview drawer.
 *
 * Fetches the case's preview with `authHeaders` on open and whenever the case
 * changes, aborting the in-flight request on teardown. Renders loading, error
 * and empty states honestly; an absent or empty section inside the document
 * says so rather than rendering nothing.
 */
export function ReportPreview({ caseId, onClose }: ReportPreviewProps) {
  const [payload, setPayload] = useState<ReportPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(
    (signal: AbortSignal) => {
      if (caseId === '') return;
      setLoading(true);
      setError(null);
      setPayload(null);
      void fetchPreview(caseId, signal)
        .then((result) => {
          if (!signal.aborted) setPayload(result);
        })
        .catch((reason: unknown) => {
          if (signal.aborted) return;
          setError(formatApiError(reason));
        })
        .finally(() => {
          if (!signal.aborted) setLoading(false);
        });
    },
    [caseId],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load, nonce]);

  const retry = useCallback(() => setNonce((value) => value + 1), []);
  const isEmpty = payload !== null && sectionsOf(payload).length === 0;

  return (
    <Drawer title="Report preview" onClose={onClose}>
      {loading && <LoadingState label="Building report preview…" />}
      {error !== null && <ErrorState message={error} onRetry={retry} />}
      {payload !== null && !loading && error === null && !isEmpty && (
        <ReportDocument payload={payload} caseId={caseId} />
      )}
      {!loading && error === null && (payload === null || isEmpty) && (
        <p className="rep-unavailable">No preview is available for this case.</p>
      )}
    </Drawer>
  );
}
