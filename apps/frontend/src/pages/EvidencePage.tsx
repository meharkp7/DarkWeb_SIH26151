import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EvidenceDrawer } from '../components/EvidenceDrawer';
import { EvidenceForm } from '../components/EvidenceForm';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { Badge } from '../components/Badge';
import type { Evidence } from '../api/types';
import { formatDateTime, formatPercent, scoreTone, shortId } from '../lib/format';
import { useSession } from '../store/session';

/**
 * Screen 3 — evidence explorer.
 *
 * Live endpoints: `POST /api/v1/evidence`, `GET /api/v1/evidence/{id}`,
 * `GET /api/v1/evidence/{id}/provenance`. There is no collection endpoint,
 * so the table shows records fetched or created in this session and says so.
 */
export function EvidencePage() {
  const { evidence, rememberEvidence } = useSession();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lookupId, setLookupId] = useState('');

  const handleLookup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = lookupId.trim();
    if (trimmed !== '') setSelectedId(trimmed);
  };

  const columns: ReadonlyArray<Column<Evidence>> = [
    {
      key: 'sha256',
      header: 'SHA-256',
      render: (row) => (
        <span className="mono" title={row.sha256}>
          {shortId(row.sha256, 16)}
        </span>
      ),
      width: '15%',
    },
    {
      key: 'source',
      header: 'Source',
      render: (row) => (
        <>
          <Badge tone="info">{row.source_type}</Badge>{' '}
          <span className="mono">{shortId(row.source_id, 8)}</span>
        </>
      ),
    },
    {
      key: 'observed',
      header: 'Observed at',
      render: (row) => formatDateTime(row.observed_at ?? row.collected_at),
    },
    {
      key: 'collector',
      header: 'Collector',
      render: (row) => (
        <>
          {row.collector_name} <span className="hint">v{row.collector_version}</span>
        </>
      ),
    },
    {
      key: 'reliability',
      header: 'Reliability',
      align: 'end',
      render: (row) => (
        <span className={scoreTone(row.source_reliability) === 'danger' ? 'text-danger' : undefined}>
          {formatPercent(row.source_reliability)}
        </span>
      ),
    },
    {
      key: 'case',
      header: 'Case',
      render: (row) =>
        row.case_id ? (
          <Link to={`/cases/${encodeURIComponent(row.case_id)}`}>{shortId(row.case_id, 8)}</Link>
        ) : (
          <span className="hint">—</span>
        ),
    },
    {
      key: 'actions',
      header: '',
      align: 'end',
      render: (row) => (
        <button
          type="button"
          className="btn btn--ghost btn--small"
          onClick={() => setSelectedId(row.evidence_id)}
        >
          Inspect
        </button>
      ),
    },
  ];

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Evidence explorer</h1>
          <p className="page-sub">
            Immutable, hash-identified records with provenance. The API serves evidence{' '}
            <strong>by ID only</strong> — there is no <code>GET /api/v1/evidence</code> collection
            endpoint yet, so the table lists what this session fetched or created.
          </p>
        </div>
        <div className="page-actions">
          <span className="hint">POST · GET by ID · provenance — all live</span>
        </div>
      </header>

      <Panel
        title="Evidence records"
        description="This browser session only — reloading clears it because no list endpoint exists."
        actions={
          <form className="inline-form inline-form--compact" onSubmit={handleLookup}>
            <div className="field">
              <label htmlFor="evidence-lookup">Fetch by evidence ID</label>
              <input
                id="evidence-lookup"
                value={lookupId}
                onChange={(event) => setLookupId(event.target.value)}
                placeholder="evidence UUID"
                autoComplete="off"
                className="mono"
              />
            </div>
            <button type="submit" className="btn">
              Load
            </button>
          </form>
        }
      >
        <DataTable<Evidence>
          columns={columns}
          rows={evidence}
          rowKey={(row) => row.evidence_id}
          caption="Evidence records held in this session"
          empty={
            <EmptyState
              title="No evidence loaded yet"
              message="Fetch a record by its ID or ingest one with the form below. The records then appear here with full provenance."
              endpoint="GET /api/v1/evidence"
            />
          }
        />
      </Panel>

      <div className="grid-2">
        <Panel
          title="Ingest evidence"
          description="POST /api/v1/evidence — creates an immutable record and returns its ID."
        >
          <EvidenceForm onCreated={rememberEvidence} />
        </Panel>

        <Panel
          title="Read paths"
          description="The exact endpoints this screen calls."
        >
          <dl className="kv">
            <dt>Fetch record</dt>
            <dd className="mono">GET /api/v1/evidence/{'{id}'}</dd>
            <dt>Provenance</dt>
            <dd className="mono">GET /api/v1/evidence/{'{id}'}/provenance</dd>
            <dt>Ingest</dt>
            <dd className="mono">POST /api/v1/evidence</dd>
            <dt>Register source</dt>
            <dd className="mono">POST /api/v1/sources</dd>
            <dt>List collection</dt>
            <dd>
              <span className="mono text-warn">not implemented</span>{' '}
              <span className="hint">(GET /api/v1/evidence)</span>
            </dd>
          </dl>
          <p className="hint">
            Parent records in the provenance view are clickable — they open in this drawer and
            refresh the session list.
          </p>
        </Panel>
      </div>

      {selectedId !== null && (
        <EvidenceDrawer
          evidenceId={selectedId}
          onClose={() => setSelectedId(null)}
          onLoaded={rememberEvidence}
          onOpenEvidence={setSelectedId}
        />
      )}
    </div>
  );
}
