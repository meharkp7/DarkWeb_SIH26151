import { useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { DataBlock } from '../components/DataBlock';
import { ErrorState, LoadingState } from '../components/States';
import { useApi } from '../hooks/useApi';
import { formatDateTime, formatPercent } from '../lib/format';
import type {
  CollectionJob,
  CollectionRunResult,
  CollectionSource,
  CollectionStatus,
} from '../api/types';
import '../styles/collection.css';

/**
 * The autonomous collection register — the problem statement's "shall work in
 * an autonomous mode, drawing on available sources of good quality and
 * reliability".
 *
 * The screen leads with the honest figure rather than the flattering one. A
 * source nobody has scanned is not a clean source, and a register of forty
 * sources that is really six outlets is not forty sources; both are stated
 * here rather than left for an analyst to notice.
 */

type Tab = 'sources' | 'jobs';

const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: 'sources', label: 'Source register' },
  { id: 'jobs', label: 'Run log' },
];

const JOB_STATUSES = ['completed', 'partial', 'failed', 'running'] as const;

/** Words, not colour. A status conveyed only by hue is invisible to a screen
 *  reader and to a colourblind analyst. */
function statusWord(status: string | null): string {
  if (status === null) return 'never run';
  return status;
}

function freshnessTone(source: CollectionSource): 'ok' | 'warn' | 'muted' {
  if (source.last_scanned_at === null) return 'muted';
  return source.record_count > 0 ? 'ok' : 'warn';
}

export function CollectionPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get('tab') === 'jobs' ? 'jobs' : 'sources') as Tab;
  const statusFilter = params.get('status') ?? '';

  const status = useApi<CollectionStatus>(api.collectionStatusUrl());
  const sources = useApi<CollectionSource[]>(api.collectionSourcesUrl());
  const jobs = useApi<CollectionJob[]>(
    api.collectionJobsUrl({ limit: 60, status: statusFilter || undefined }),
  );

  const [run, setRun] = useState<CollectionRunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const setParam = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(params);
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const triggerRun = useCallback(async () => {
    setRunning(true);
    setRunError(null);
    try {
      const result = await api.runCollection({ job_type: 'COLLECT' });
      setRun(result);
      // The run log changed, so both panels are now stale.
      jobs.reload();
      status.reload();
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : 'The run could not be started.');
    } finally {
      setRunning(false);
    }
  }, [jobs, status]);

  const headline = useMemo(() => {
    if (!status.data) return null;
    return [
      { label: 'Sources registered', value: status.data.sources_total },
      { label: 'Scanned in the last 24h', value: status.data.jobs_last_24h_total },
      { label: 'Records collected, 24h', value: status.data.records_last_24h },
      {
        label: 'Never scanned',
        value: status.data.sources_never_scanned,
        // Deliberately the same red as a failure: a source nobody has looked
        // at is a gap in coverage, not a neutral fact.
        tone: status.data.sources_never_scanned > 0 ? 'bad' : 'good',
      },
    ] as const;
  }, [status.data]);

  return (
    <div className="col-page">
      <header className="col-hero">
        <div>
          <span className="eyebrow">SOURCE REGISTER · AUTONOMOUS MODE</span>
          <h1>Collection.</h1>
          <p>
            What the platform collects, from where, and how much to trust the source rather than the
            individual record. A run that found nothing and a run that never looked are both shown.
          </p>
        </div>
        <div className="col-hero__actions">
          <button
            type="button"
            className="col-run"
            onClick={() => void triggerRun()}
            disabled={running}
            aria-busy={running}
          >
            {running ? 'Collecting…' : 'Run collection now'}
          </button>
          <small className="col-hero__hint">
            Executes the platform's own orchestrator over the configured collectors.
          </small>
        </div>
      </header>

      {runError ? <ErrorState message={`Collection run failed — ${runError}`} /> : null}

      {run ? (
        <section className="col-run-result" aria-live="polite">
          <p className="col-run-result__head">
            <b>{run.collection_mode}</b>
            {run.synthetic ? <span className="col-tag col-tag--warn">synthetic corpus</span> : null}
          </p>
          <p className="col-run-result__note">{run.mode_note}</p>
          <ul className="col-run-result__stats">
            <li>
              <b>{run.duration_seconds.toFixed(1)}s</b>
              <span>duration</span>
            </li>
            <li>
              <b>{run.ingested}</b>
              <span>records ingested</span>
            </li>
            <li>
              <b>{run.error_count}</b>
              <span>collector errors</span>
            </li>
            <li>
              <b>{run.outcomes.length}</b>
              <span>collectors run</span>
            </li>
          </ul>
          {run.limitations.length > 0 ? (
            <details className="col-run-result__limits">
              <summary>What this run does not establish ({run.limitations.length})</summary>
              <ul>
                {run.limitations.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
      ) : null}

      {status.loading ? (
        <LoadingState label="Loading collection status" />
      ) : status.error !== null ? (
        <ErrorState message={status.error} onRetry={status.reload} />
      ) : status.data ? (
        <>
          <section className="col-strip">
            {headline?.map((item) => (
              <div key={item.label} className="col-strip__cell">
                <b>{item.value}</b>
                <span>{item.label}</span>
              </div>
            ))}
          </section>

          <DataBlock
            eyebrow="Coverage"
            title="What the register actually contains"
            lead={status.data.reliability_basis}
          >
            <dl className="col-facts">
              <div>
                <dt>Independence groups</dt>
                <dd>{status.data.independence_groups}</dd>
              </div>
              <div>
                <dt>Mean reliability, contributing sources</dt>
                <dd>
                  {status.data.mean_contributing_reliability === null
                    ? '—'
                    : formatPercent(status.data.mean_contributing_reliability)}
                </dd>
              </div>
              <div>
                <dt>Dominant independence group</dt>
                <dd>
                  {status.data.dominant_independence_group ?? '—'}
                  {status.data.dominant_independence_group_size > 1 ? (
                    <span className="col-facts__note">
                      {' '}
                      {status.data.dominant_independence_group_size} of{' '}
                      {status.data.sources_total} sources share it, so they are
                      not independent observations
                    </span>
                  ) : null}
                </dd>
              </div>
              <div>
                <dt>Sources never scanned</dt>
                <dd>
                  {status.data.sources_never_scanned} of {status.data.sources_total}
                  {status.data.sources_never_scanned > 0 ? (
                    <span className="col-facts__note">
                      {' '}
                      a source nobody has looked at is a gap in coverage, not a
                      source with nothing to report
                    </span>
                  ) : null}
                </dd>
              </div>
            </dl>
            {status.data.limitations.length > 0 ? (
              <ul className="col-limitations">
                {status.data.limitations.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : null}
          </DataBlock>
        </>
      ) : null}

      <nav className="col-tabs" aria-label="Collection views">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setParam('tab', item.id === 'sources' ? null : item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'sources' ? (
        <DataBlock
          eyebrow="Register"
          title="Sources and their quality weighting"
          lead="Reliability is a property of the outlet, recorded when the source was registered. It is a weight on that source, not a measurement of any individual record, and it does not change from one collection to the next."
        >
          {sources.loading ? (
            <LoadingState label="Loading sources" />
          ) : sources.error !== null ? (
            <ErrorState message={sources.error} onRetry={sources.reload} />
          ) : (sources.data?.length ?? 0) === 0 ? (
            <p className="hint">No sources are registered.</p>
          ) : (
            <div className="table-wrap">
              <table className="col-table" aria-label="Source register">
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Type</th>
                    <th scope="col">Reliability</th>
                    <th scope="col">Independence</th>
                    <th scope="col">Records</th>
                    <th scope="col">Runs</th>
                    <th scope="col">Last scan</th>
                    <th scope="col">Last status</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.data?.map((source) => (
                    <tr key={source.source_id}>
                      <th scope="row">{source.name}</th>
                      <td className="mono">{source.source_type}</td>
                      <td>
                        <span className="col-bar" aria-hidden="true">
                          <i
                            style={{ width: `${Math.round(source.reliability * 100)}%` }}
                            data-tone={freshnessTone(source)}
                          />
                        </span>
                        <span className="col-num">{formatPercent(source.reliability)}</span>
                      </td>
                      <td>
                        {source.independence_group ?? '—'}
                        {source.independence_group_size > 1 ? (
                          <small className="col-warn">
                            {' '}
                            ×{source.independence_group_size} not independent
                          </small>
                        ) : null}
                      </td>
                      <td className="col-num">{source.record_count.toLocaleString()}</td>
                      <td className="col-num">{source.job_count}</td>
                      <td>
                        {source.last_scanned_at ? formatDateTime(source.last_scanned_at) : '—'}
                      </td>
                      <td>
                        <span className="col-status" data-status={statusWord(source.last_status)}>
                          {statusWord(source.last_status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataBlock>
      ) : (
        <DataBlock
          eyebrow="History"
          title="Run log"
          lead="Every job the platform has run against a registered source, newest first. Failures are shown alongside successes; a run log containing only successful runs cannot tell an analyst which sources keep failing."
        >
          <div className="col-filters" role="search" aria-label="Filter the run log">
            <button
              type="button"
              className={statusFilter === '' ? 'is-active' : ''}
              aria-pressed={statusFilter === ''}
              onClick={() => setParam('status', null)}
            >
              all
            </button>
            {JOB_STATUSES.map((value) => (
              <button
                key={value}
                type="button"
                className={statusFilter === value ? 'is-active' : ''}
                aria-pressed={statusFilter === value}
                onClick={() => setParam('status', value)}
              >
                {value}
              </button>
            ))}
          </div>
          {jobs.loading ? (
            <LoadingState label="Loading run log" />
          ) : jobs.error !== null ? (
            <ErrorState message={jobs.error} onRetry={jobs.reload} />
          ) : (jobs.data?.length ?? 0) === 0 ? (
            <p className="hint">
              No jobs match this filter.{' '}
              <Link to="/actors" className="link-button">
                Review the source register
              </Link>
            </p>
          ) : (
            <div className="table-wrap">
              <table className="col-table" aria-label="Collection run log">
                <thead>
                  <tr>
                    <th scope="col">Started</th>
                    <th scope="col">Source</th>
                    <th scope="col">Collector</th>
                    <th scope="col">Status</th>
                    <th scope="col">Candidates</th>
                    <th scope="col">Records</th>
                    <th scope="col">Errors</th>
                    <th scope="col">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.data?.map((job) => (
                    <tr key={job.job_id}>
                      <th scope="row">
                        {job.started_at ? formatDateTime(job.started_at) : '—'}
                      </th>
                      <td>{job.source_name ?? '—'}</td>
                      <td className="mono">
                        {job.collector_name}
                        <small> v{job.collector_version}</small>
                      </td>
                      <td>
                        <span className="col-status" data-status={job.status}>
                          {job.status}
                        </span>
                        {job.error_samples.length > 0 ? (
                          <small className="col-warn"> {job.error_samples.length} recorded</small>
                        ) : null}
                      </td>
                      <td className="col-num">{job.candidates.toLocaleString()}</td>
                      <td className="col-num">{job.records.toLocaleString()}</td>
                      <td className="col-num">{job.errors}</td>
                      <td className="col-num">{job.duration_seconds}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataBlock>
      )}
    </div>
  );
}
