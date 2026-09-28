import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '../components/Badge';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { useSession } from '../store/session';

interface ReportSection {
  readonly key: string;
  readonly label: string;
  readonly planSection: string;
}

const SECTIONS: readonly ReportSection[] = [
  { key: 'overview', label: 'Executive summary', planSection: 'Phase 24' },
  { key: 'evidence', label: 'Evidence inventory', planSection: 'Phase 24' },
  { key: 'timeline', label: 'Timeline of activity', planSection: 'Phase 23' },
  { key: 'graph', label: 'Relationship graph', planSection: 'Phase 23' },
  { key: 'hypotheses', label: 'Hypothesis comparison', planSection: 'Phase 23' },
  { key: 'attribution', label: 'Attribution assessment', planSection: 'Phase 23' },
  { key: 'sources', label: 'Source reliability', planSection: 'Phase 11' },
  { key: 'limitations', label: 'Limitations & contradictions', planSection: 'Phase 24' },
];

type SectionState = Record<string, boolean>;

function initialState(): SectionState {
  const state: SectionState = {};
  for (const section of SECTIONS) state[section.key] = true;
  return state;
}

/**
 * Screen 10 — report builder.
 *
 * Builds a client-side markdown draft from real session data and documents
 * the backend endpoint that will perform server-side export. No reporting
 * route exists in `src/aegis/api/app.py`, so the export action is an honest
 * stub — it never claims a download happened.
 */
export function ReportsPage() {
  const { evidence, sources, analysis } = useSession();
  const [selected, setSelected] = useState<SectionState>(initialState);
  const [status, setStatus] = useState<string | null>(null);

  const counts: Record<string, string> = useMemo(
    () => ({
      overview: 'case data pending API',
      evidence: `${evidence.length} record${evidence.length === 1 ? '' : 's'}`,
      timeline: `${evidence.length} event${evidence.length === 1 ? '' : 's'} derived`,
      graph:
        analysis === null ? 'no run' : `${analysis.hypotheses.length} hypothesis edges`,
      hypotheses: analysis === null ? 'no run' : `${analysis.hypotheses.length} returned`,
      attribution: analysis === null ? 'no run' : `seed ${analysis.seed}`,
      sources: `${sources.length} registered`,
      limitations: analysis === null ? 'no run' : 'contradictions pending API',
    }),
    [evidence.length, sources.length, analysis],
  );

  const draft = useMemo(() => {
    const lines: string[] = [
      '# AEGIS investigation report — draft',
      '',
      '_Client-side draft: assembled in the browser from this session’s data._',
      '',
    ];
    for (const section of SECTIONS) {
      if (!selected[section.key]) continue;
      lines.push(`## ${section.label}`);
      lines.push(`- Status: ${counts[section.key] ?? 'unknown'}`);
      if (section.key === 'overview') {
        lines.push('- Case metadata: not available (GET /api/v1/cases not implemented).');
      }
      if (section.key === 'evidence' && evidence.length > 0) {
        for (const record of evidence.slice(0, 5)) {
          lines.push(`- \`${record.sha256.slice(0, 16)}…\` ${record.raw_artifact_uri}`);
        }
        if (evidence.length > 5) lines.push(`- …and ${evidence.length - 5} more.`);
      }
      if (section.key === 'hypotheses' && analysis !== null) {
        for (const hypothesis of analysis.hypotheses.slice(0, 5)) {
          lines.push(
            `- ${hypothesis.source_actor_id.slice(0, 8)} → ${hypothesis.target_actor_id.slice(0, 8)}: final ${(Math.round(hypothesis.final_score * 1000) / 10).toFixed(1)}% (support ${(Math.round(hypothesis.support_score * 1000) / 10).toFixed(1)}%, contradiction ${(Math.round(hypothesis.contradiction_score * 1000) / 10).toFixed(1)}%)`,
          );
        }
        if (analysis.hypotheses.length > 5) {
          lines.push(`- …and ${analysis.hypotheses.length - 5} more.`);
        }
      }
      if (section.key === 'sources' && sources.length > 0) {
        for (const source of sources.slice(0, 5)) {
          lines.push(`- ${source.name} (${source.source_type}): ${Math.round(source.reliability * 100)}%`);
        }
      }
      lines.push('');
    }
    const last = lines[lines.length - 1];
    if (last === '') lines.pop();
    return lines.join('\n');
  }, [selected, counts, evidence, analysis, sources]);

  const selectedCount = SECTIONS.filter((section) => selected[section.key]).length;

  const handleToggle = (key: string, checked: boolean) => {
    setSelected((current) => ({ ...current, [key]: checked }));
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(draft);
      setStatus('Draft copied to the clipboard.');
    } catch {
      setStatus('Clipboard access was refused — select the preview text and copy manually.');
    }
  };

  const handleExport = () => {
    setStatus(
      'Server export is not implemented. Planned endpoint: POST /api/v1/reports/export ' +
        '({ case_id, sections, format }) — no reporting route exists in src/aegis/api/app.py yet.',
    );
  };

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Report builder</h1>
          <p className="page-sub">
            Choose sections, preview the draft (built from real session data), then export once the
            reporting endpoint ships.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/evidence">
            Evidence
          </Link>
          <Link className="btn" to="/hypotheses">
            Hypotheses
          </Link>
        </div>
      </header>

      <div className="grid-2">
        <Panel
          title="Sections"
          description={`${selectedCount} of ${SECTIONS.length} selected`}
        >
          <ul className="checklist">
            {SECTIONS.map((section) => (
              <li key={section.key} className="checklist__item">
                <input
                  type="checkbox"
                  id={`report-${section.key}`}
                  checked={selected[section.key] === true}
                  onChange={(event) => handleToggle(section.key, event.target.checked)}
                />
                <label htmlFor={`report-${section.key}`}>{section.label}</label>
                <Badge tone="neutral">{counts[section.key] ?? '—'}</Badge>
              </li>
            ))}
          </ul>
          <p className="hint">
            Counts are session facts; anything the API does not serve is labelled rather than
            filled in.
          </p>
        </Panel>

        <Panel title="Export" description="Server-side rendering is a Phase 24 concern.">
          <dl className="kv">
            <dt>Planned endpoint</dt>
            <dd className="mono mono--break">POST /api/v1/reports/export</dd>
            <dt>Planned payload</dt>
            <dd className="mono">
              {'{ case_id, sections[], format: "md" | "pdf" | "json" }'}
            </dd>
            <dt>Current status</dt>
            <dd>
              <Badge tone="warn">not implemented</Badge>
            </dd>
            <dt>Schema</dt>
            <dd className="hint">no Report schema in src/aegis/schemas/ yet</dd>
          </dl>
          <div className="form-actions">
            <button type="button" className="btn btn--primary" onClick={handleExport}>
              Export report
            </button>
            <button type="button" className="btn" onClick={handleCopy}>
              Copy draft
            </button>
          </div>
          {status !== null && (
            <p className="status status--info" role="status">
              {status}
            </p>
          )}
        </Panel>
      </div>

      <Panel title="Draft preview" description="Markdown assembled client-side.">
        {selectedCount === 0 ? (
          <EmptyState
            title="No sections selected"
            message="Tick at least one section to build the draft."
          />
        ) : (
          <pre className="code-block code-block--tall">{draft}</pre>
        )}
      </Panel>
    </div>
  );
}
