import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api, apiUrl, authHeaders, formatApiError } from '../api/client';
import type { CaseQueueEntry } from '../api/types';
import { Badge } from '../components/Badge';
import { ErrorState, LoadingState } from '../components/States';
import { useApi } from '../hooks/useApi';
import { formatDateTime, shortId } from '../lib/format';

/**
 * Report preview and export.
 *
 * The preview is rendered from the same payload `/reports/preview` produces
 * for the JSON export, so what an analyst reads here is what the exported
 * artifact contains. Exports cannot be plain links: every route behind the API
 * base needs an `Authorization` header, and a browser navigation cannot set
 * one, so each export is fetched with `authHeaders` and saved as a blob.
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

interface ReportPreview {
  readonly title?: unknown;
  readonly generated_by?: unknown;
  readonly sections?: unknown;
  readonly provenance?: unknown;
}

const FORMATS = [
  { key: 'pdf', label: 'Executive PDF', icon: '◈', desc: 'Designed analyst brief with evidence citations.' },
  { key: 'json', label: 'Evidence JSON', icon: '□', desc: 'Machine-readable evidence and provenance package.' },
  { key: 'csv', label: 'CSV matrix', icon: '▤', desc: 'Flat evidence matrix for analysis.' },
  { key: 'stix', label: 'STIX bundle', icon: '◇', desc: 'Structured threat-intelligence export.' },
] as const;

type ExportFormat = (typeof FORMATS)[number]['key'];

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

function sectionsOf(payload: ReportPreview | null): readonly PreviewSection[] {
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

function provenanceOf(payload: ReportPreview | null): PreviewProvenance | null {
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

function ReportDocument({ payload, caseId }: { readonly payload: ReportPreview; readonly caseId: string }) {
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

async function fetchPreview(caseId: string, signal: AbortSignal): Promise<ReportPreview> {
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
  return payload as ReportPreview;
}

/** Save a fetched response as a file without ever exposing the token to a URL. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on the next tick: Safari aborts the download if the object URL
  // disappears synchronously after the click.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ReportsPage() {
  const { data: cases, loading: casesLoading, error: casesError, reload: reloadCases } =
    useApi<CaseQueueEntry[]>(apiUrl('/v1/dashboard/cases'));
  const list: readonly CaseQueueEntry[] = useMemo(() => cases ?? [], [cases]);

  const [selected, setSelected] = useState<string>('');
  const active = useMemo(
    () => list.find((item) => item.case_id === selected) ?? list[0] ?? null,
    [list, selected],
  );

  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [downloading, setDownloading] = useState<ExportFormat | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const caseId = active?.case_id ?? null;

  const loadPreview = useCallback(
    (id: string, signal: AbortSignal) => {
      setPreviewLoading(true);
      setPreviewError(null);
      setPreview(null);
      void fetchPreview(id, signal)
        .then((payload) => {
          if (!signal.aborted) setPreview(payload);
        })
        .catch((reason: unknown) => {
          if (signal.aborted) return;
          setPreviewError(formatApiError(reason));
        })
        .finally(() => {
          if (!signal.aborted) setPreviewLoading(false);
        });
    },
    [],
  );

  useEffect(() => {
    if (caseId === null) {
      setPreview(null);
      setPreviewError(null);
      return undefined;
    }
    const controller = new AbortController();
    loadPreview(caseId, controller.signal);
    return () => controller.abort();
  }, [caseId, loadPreview]);

  const download = useCallback(
    async (format: ExportFormat) => {
      if (caseId === null) return;
      setDownloading(format);
      setDownloadError(null);
      try {
        const response = await fetch(api.reportExportUrl(caseId, format), { headers: authHeaders() });
        if (!response.ok) throw new ApiError(response.status, response.statusText || 'Export failed');
        const blob = await response.blob();
        const name = slug(active?.name ?? caseId) || caseId;
        saveBlob(blob, `aegis-${name}.${format}`);
      } catch (reason) {
        setDownloadError(formatApiError(reason));
      } finally {
        setDownloading(null);
      }
    },
    [active, caseId],
  );

  return (
    <div className="page-stack rep-page">
      <header className="hero-head">
        <div>
          <span className="eyebrow">Investigation output</span>
          <h1>Reports</h1>
          <p>Turn a case workspace into an auditable evidence package.</p>
        </div>
      </header>

      <div className="report-select">
        <div>
          <span className="eyebrow">Case</span>
          <label className="rep-visually-hidden" htmlFor="rep-case">
            Case to report on
          </label>
          <select
            id="rep-case"
            value={active?.case_id ?? ''}
            disabled={list.length === 0}
            onChange={(event) => setSelected(event.target.value)}
          >
            {list.map((item) => (
              <option key={item.case_id} value={item.case_id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        {active && (
          <span>
            {active.counts.evidence} evidence · {active.counts.assessments} assessments
          </span>
        )}
      </div>

      {casesLoading && list.length === 0 && <LoadingState label="Loading investigations…" />}
      {casesError !== null && <ErrorState message={casesError} onRetry={reloadCases} />}
      {!casesLoading && casesError === null && list.length === 0 && (
        <p className="rep-unavailable">No investigations are available to report on.</p>
      )}

      {active !== null && (
        <>
          <section className="report-grid rep-exports" aria-label="Export formats">
            {FORMATS.map((format) => (
              <article className="report-card" key={format.key}>
                <div className="report-icon" aria-hidden="true">
                  {format.icon}
                </div>
                <div>
                  <h2>{format.label}</h2>
                  <p>{format.desc}</p>
                </div>
                <button
                  type="button"
                  className="button button--dark"
                  onClick={() => void download(format.key)}
                  disabled={downloading !== null}
                >
                  {downloading === format.key ? 'Preparing…' : 'Export'}
                  <span className="rep-visually-hidden"> {format.label}</span>
                </button>
              </article>
            ))}
          </section>

          {downloadError !== null && <ErrorState message={downloadError} />}

          <section className="rep-preview" aria-label="Report preview" aria-busy={previewLoading}>
            <div className="rep-preview__head">
              <div>
                <span className="eyebrow">Preview</span>
                <h2 className="rep-preview__title">Rendered report</h2>
              </div>
              {active && <Badge tone="info">{active.status.replace('_', ' ')}</Badge>}
            </div>

            {previewLoading && <LoadingState label="Building report preview…" />}
            {previewError !== null && (
              <ErrorState message={previewError} onRetry={() => caseId !== null && loadPreview(caseId, new AbortController().signal)} />
            )}
            {preview !== null && !previewLoading && <ReportDocument payload={preview} caseId={active?.case_id ?? ''} />}
            {!previewLoading && previewError === null && preview === null && (
              <p className="rep-unavailable">No preview is available for this case.</p>
            )}
          </section>

          <p className="report-footnote">
            Exports are generated from the persisted case state. No report claims are created outside cited
            evidence. Printing this page reproduces the preview layout.
          </p>
        </>
      )}
    </div>
  );
}
