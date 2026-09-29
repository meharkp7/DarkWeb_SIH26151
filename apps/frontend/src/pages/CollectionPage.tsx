import { useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { DataBlock } from '../components/DataBlock';
import { ErrorState, LoadingState } from '../components/States';
import { TimeRangeNotice } from '../components/TimeRangeControl';
import { useApi } from '../hooks/useApi';
import { filterByTimeRange, useTimeRange } from '../store/TimeRange';
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
  const { from, to, isoFrom, isoTo, label: windowLabel, isActive } = useTimeRange();

  const status = useApi<CollectionStatus>(api.collectionStatusUrl());
  const sources = useApi<CollectionSource[]>(api.collectionSourcesUrl());
  /**
   * The run log is narrowed by the server. `GET /v1/collection/jobs` already
   * takes `since`/`until` and applies them to `started_at` in SQL, so the
   * window is a query here rather than a slice the browser makes afterwards.
   */
  const jobs = useApi<CollectionJob[]>(
    api.collectionJobsUrl({
      limit: 60,
      status: statusFilter || undefined,
      since: isoFrom,
      until: isoTo,
    }),
  );

  /**
   * The source register is not, and the page says so. `GET /v1/collection/sources`
   * takes no parameters at all, so the only way to bound it is in the browser,
   * over the sources already loaded — measured by *last scan*, the one date on
   * a source that means anything. A source nobody has ever scanned has no date
   * and is left out, counted, rather than being presented as if it were inside
   * the window.
   */
  const sourcesInWindow = useMemo(
    () => filterByTimeRange(sources.data ?? [], (source) => source.last_scanned_at, from, to),
    [sources.data, from, to],
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

          {/*
            The strip above and the coverage block below are read from
            `GET /v1/collection/status`, which takes no time bound and computes
            its own 24-hour figures. They are labelled as they are, and saying
            so here is what stops an analyst reading a 7-day window into a
            count that was never bounded by one.
          */}
          {isActive && (
            <p className="tr-notice">
              {`${windowLabel} — the four figures above and the coverage block below are not bounded by this window. They come from GET /v1/collection/status, which takes no time parameter and counts the last 24 hours on its own. The window applies to the source register and the run log below.`}
            </p>
          )}

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

      <div className="col-tabs" role="tablist" aria-label="Collection views">
        {TABS.map((item) => (
          <button
            key={item.id}
            id={`col-tab-${item.id}`}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            aria-controls={`col-panel-${item.id}`}
            // Roving tabindex: only the selected tab is in the tab order, so
            // a keyboard user reaches the panel rather than walking the strip.
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => setParam('tab', item.id === 'sources' ? null : item.id)}
            onKeyDown={(event) => {
              if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
              event.preventDefault();
              const from = TABS.findIndex((t) => t.id === item.id);
              const offset = event.key === 'ArrowRight' ? 1 : -1;
              // The modulo keeps it wrapping, so Left from the first tab
              // lands on the last rather than dead-ending.
              const next = TABS[(from + offset + TABS.length) % TABS.length];
              if (next === undefined) return;
              setParam('tab', next.id === 'sources' ? null : next.id);
              document.getElementById(`col-tab-${next.id}`)?.focus();
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'sources' ? (
        <div id="col-panel-sources" role="tabpanel" aria-labelledby="col-tab-sources">
        <DataBlock
          eyebrow="Register"
          title="Sources and their quality weighting"
          lead="Reliability is a property of the outlet, recorded when the source was registered. It is a weight on that source, not a measurement of any individual record, and it does not change from one collection to the next."
        >
          <TimeRangeNotice
            window={windowLabel}
            shown={sourcesInWindow.rows.length}
            total={sourcesInWindow.total}
            basis={`in the browser over the ${sourcesInWindow.total} loaded ${
              sourcesInWindow.total === 1 ? 'source' : 'sources'
            }, by last scan — GET /v1/collection/sources takes no parameters`}
            undated={sourcesInWindow.undated}
          />
          {sources.loading ? (
            <LoadingState label="Loading sources" />
          ) : sources.error !== null ? (
            <ErrorState message={sources.error} onRetry={sources.reload} />
          ) : (sourcesInWindow.total === 0) ? (
            <p className="hint">No sources are registered.</p>
          ) : sourcesInWindow.rows.length === 0 ? (
            <p className="hint">
              No registered source was last scanned inside {windowLabel}. A source nobody has ever
              scanned carries no date at all, so it cannot be shown to fall in a window — widen the
              window, or set it to all time, to see the whole register.
            </p>
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
                  {sourcesInWindow.rows.map((source) => (
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
        </div>
      ) : (
        <div id="col-panel-jobs" role="tabpanel" aria-labelledby="col-tab-jobs">
        <DataBlock
          eyebrow="History"
          title="Run log"
          lead="Every job the platform has run against a registered source, newest first. Failures are shown alongside successes; a run log containing only successful runs cannot tell an analyst which sources keep failing."
        >
          {/*
            The unfiltered total is deliberately absent rather than guessed.
            The window reached the server, so the only number available is the
            page that came back — and a page of 60 is not a register total.
            Saying "0 in window" beside a 2,000-run register would be a
            confident answer to a question nobody asked.
          */}
          <TimeRangeNotice
            window={windowLabel}
            shown={jobs.data?.length ?? 0}
            total={null}
            basis={`by the server, on GET /v1/collection/jobs, by the time a run started`}
            footnote="This log is paged at 60 runs, so the number above is a page of the register rather than the whole of it: runs before the page, and any that fall outside the window, are not counted here either way."
          />
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
              {isActive
                ? `No run was started inside ${windowLabel}. That is a fact about the window, not about the sources: widen it, or set it to all time, to see the rest of the log.`
                : 'No jobs match this filter.'}{' '}
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
        </div>
      )}
    </div>
  );
}
