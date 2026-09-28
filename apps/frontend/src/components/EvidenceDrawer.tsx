import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiUrl } from '../api/client';
import type { Evidence, EvidenceProvenance } from '../api/types';
import { useApi } from '../hooks/useApi';
import { formatDateTime, formatPercent, scoreTone, shortId } from '../lib/format';
import { Badge } from './Badge';
import { Drawer } from './Drawer';
import { ErrorState, LoadingState } from './States';

export interface EvidenceDrawerProps {
  readonly evidenceId: string;
  readonly onClose: () => void;
  /** Called whenever a record is successfully read (keeps the session list fresh). */
  readonly onLoaded: (record: Evidence) => void;
  /** Open another evidence record in this drawer (provenance navigation). */
  readonly onOpenEvidence: (evidenceId: string) => void;
}

/**
 * Evidence detail drawer: `GET /api/v1/evidence/{id}` plus its provenance
 * graph from `GET /api/v1/evidence/{id}/provenance`.
 */
export function EvidenceDrawer({
  evidenceId,
  onClose,
  onLoaded,
  onOpenEvidence,
}: EvidenceDrawerProps) {
  const detail = useApi<Evidence>(apiUrl(`/v1/evidence/${encodeURIComponent(evidenceId)}`));
  const provenance = useApi<EvidenceProvenance>(
    apiUrl(`/v1/evidence/${encodeURIComponent(evidenceId)}/provenance`),
  );

  const loaded = detail.data;
  useEffect(() => {
    if (loaded !== null) onLoaded(loaded);
  }, [loaded, onLoaded]);

  return (
    <Drawer title={`Evidence ${shortId(evidenceId, 12)}`} onClose={onClose}>
      {detail.loading && <LoadingState label="Fetching evidence record…" />}
      {!detail.loading && detail.error !== null && (
        <ErrorState message={detail.error} onRetry={detail.reload} />
      )}
      {!detail.loading && detail.error === null && loaded !== null && (
        <>
          <dl className="kv">
            <dt>Evidence ID</dt>
            <dd className="mono">{loaded.evidence_id}</dd>
            <dt>SHA-256</dt>
            <dd className="mono mono--break">{loaded.sha256}</dd>
            <dt>Source</dt>
            <dd>
              <Badge tone="info">{loaded.source_type}</Badge>{' '}
              <span className="mono">{shortId(loaded.source_id, 12)}</span>
            </dd>
            <dt>Observed at</dt>
            <dd>{formatDateTime(loaded.observed_at)}</dd>
            <dt>Collected at</dt>
            <dd>{formatDateTime(loaded.collected_at)}</dd>
            <dt>Collector</dt>
            <dd>
              {loaded.collector_name} <span className="hint">v{loaded.collector_version}</span>
            </dd>
            <dt>Normalizer / extraction</dt>
            <dd>
              {loaded.normalizer_version ?? '—'} / {loaded.extraction_version ?? '—'}
            </dd>
            <dt>Source reliability</dt>
            <dd>
              <span className="bar bar--inline">
                <span
                  className={`bar__fill bar__fill--${scoreTone(loaded.source_reliability)}`}
                  style={{ width: `${Math.round(loaded.source_reliability * 100)}%` }}
                />
              </span>{' '}
              {formatPercent(loaded.source_reliability)}
            </dd>
            <dt>Independence group</dt>
            <dd>{loaded.independence_group}</dd>
            <dt>Entity type</dt>
            <dd>{loaded.entity_type ?? '—'}</dd>
            <dt>Raw artifact</dt>
            <dd className="mono mono--break">{loaded.raw_artifact_uri}</dd>
            <dt>Case</dt>
            <dd>
              {loaded.case_id ? (
                <Link to={`/cases/${encodeURIComponent(loaded.case_id)}`}>
                  {shortId(loaded.case_id, 12)}
                </Link>
              ) : (
                'unassigned'
              )}
            </dd>
            <dt>Created at</dt>
            <dd>{formatDateTime(loaded.created_at)}</dd>
            <dt>Metadata</dt>
            <dd>
              <pre className="code-block">{JSON.stringify(loaded.metadata ?? {}, null, 2)}</pre>
            </dd>
          </dl>

          <section className="drawer__section" aria-label="Provenance">
            <h3 className="drawer__section-title">Provenance &amp; derivation</h3>
            {provenance.loading && <LoadingState label="Fetching provenance…" />}
            {provenance.error !== null && !provenance.loading && (
              <ErrorState message={provenance.error} onRetry={provenance.reload} />
            )}
            {provenance.error === null && !provenance.loading && provenance.data !== null && (
              <dl className="kv">
                <dt>Artifact URI</dt>
                <dd className="mono mono--break">{provenance.data.artifact_uri}</dd>
                <dt>Derivations</dt>
                <dd>{provenance.data.derivation_count}</dd>
                <dt>Parent evidence</dt>
                <dd>
                  {provenance.data.parent_evidence_ids.length === 0 ? (
                    <span className="hint">None — this is a root record.</span>
                  ) : (
                    <ul className="plain-list">
                      {provenance.data.parent_evidence_ids.map((parentId) => (
                        <li key={parentId}>
                          <button
                            type="button"
                            className="link-button mono"
                            onClick={() => onOpenEvidence(parentId)}
                          >
                            {shortId(parentId, 12)}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
              </dl>
            )}
          </section>
        </>
      )}
      <p className="hint">
        Endpoints: <code>GET /api/v1/evidence/{'{id}'}</code> ·{' '}
        <code>GET /api/v1/evidence/{'{id}'}/provenance</code>
      </p>
    </Drawer>
  );
}
