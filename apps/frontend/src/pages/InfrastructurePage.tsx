import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiUrl, authHeaders } from '../api/client';
import type {
  InfraFinding,
  InfraMatch,
  InfraObservation,
  InfraSummary,
} from '../api/types';
import { INFRA_FINDING_KINDS, INFRA_SEVERITIES } from '../api/types';
import { DataBlock } from '../components/DataBlock';
import { ErrorState, EmptyState, LoadingState } from '../components/States';
import { CorrelateRunner } from '../components/infrastructure/CorrelateRunner';
import { FindingsTable, sortFindings } from '../components/infrastructure/FindingsTable';
import type { FindingSortKey } from '../components/infrastructure/FindingsTable';
import { Limitations } from '../components/infrastructure/Limitations';
import { MatchesTable, sortMatches } from '../components/infrastructure/MatchesTable';
import type { MatchSortKey } from '../components/infrastructure/MatchesTable';
import {
  FeatureDigest,
  ObservationsTable,
  sortObservations,
} from '../components/infrastructure/ObservationsTable';
import type { ObservationSortKey } from '../components/infrastructure/ObservationsTable';
import { ChannelBars } from '../components/infrastructure/Primitives';
import { SummaryStrip, WeakShare } from '../components/infrastructure/SummaryStrip';
import { TimelineControl } from '../components/infrastructure/TimelineControl';
import { InspectorRail } from '../components/InspectorRail';
import type { InspectorRailProps, InspectorStatus } from '../components/InspectorRail';
import { useApi } from '../hooks/useApi';
import { leadFor } from '../lib/explain';
import { formatDateTime, formatPercent, shortId } from '../lib/format';
import { usePublishAgentContext } from '../components/agent-context';
import '../styles/infrastructure.css';

/*
 * Tor hidden-service misconfigurations and clearnet correlation.
 *
 * This is the problem statement's first capability: find the ways a hidden
 * service is exposed, and point at the clearnet infrastructure behind it.
 * Three registers, one timeline, and a governing rule that shapes every
 * column — a misconfiguration is never presented without the benign
 * alternative that produces it, and a correlation resting on one dimension
 * is never presented as one resting on several.
 *
 * Filters, tab, sort and selection all live in the address bar, so a view of
 * this capability can be linked, handed over or bookmarked. Nothing is
 * fetched and then filtered on the client except the column order, which
 * reorders the rows on screen; the row *count* a filter returns is part of
 * what is being read, so that comes from the API.
 */

const SEVERITY_TONE: Readonly<Record<string, InspectorStatus['tone']>> = {
  critical: 'danger',
  high: 'danger',
  medium: 'warn',
  low: 'ok',
  informational: 'muted',
};

const TABS = [
  { id: 'findings', label: 'Findings' },
  { id: 'matches', label: 'Matches' },
  { id: 'observations', label: 'Observations' },
] as const;

type TabId = (typeof TABS)[number]['id'];

function isTab(value: string | null): value is TabId {
  return value === 'findings' || value === 'matches' || value === 'observations';
}

function readSort<T extends string>(
  key: string | null,
  dir: string | null,
  allowed: readonly T[],
  fallback: { key: T; dir: 'asc' | 'desc' },
): { key: T; dir: 'asc' | 'desc' } {
  const sortKey = (key !== null && allowed.includes(key as T) ? key : fallback.key) as T;
  return { key: sortKey, dir: dir === 'asc' || dir === 'desc' ? dir : fallback.dir };
}

export function InfrastructurePage(): JSX.Element {
  const [params, setParams] = useSearchParams();

  const tabParam = params.get('tab');
  const tab: TabId = isTab(tabParam) ? tabParam : 'findings';
  const from = params.get('from') ?? '';
  const until = params.get('until') ?? '';
  const caseId = params.get('case') ?? '';
  const kind = params.get('kind') ?? 'all';
  const severity = params.get('severity') ?? 'all';
  const subject = params.get('subject') ?? '';
  const network = params.get('network') ?? 'all';
  const inspect = params.get('inspect');

  const patch = useCallback(
    (next: Record<string, string | null>): void => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          for (const [key, value] of Object.entries(next)) {
            if (value === null || value === '') updated.delete(key);
            else updated.set(key, value);
          }
          return updated;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // The API takes dates, not datetimes: a day boundary is what an analyst
  // picks, and inventing a time of day on their behalf would silently
  // include or exclude a day of records.
  const sinceParam = from === '' ? undefined : `${from}T00:00:00Z`;
  const untilParam = until === '' ? undefined : `${until}T23:59:59Z`;

  // `view` is the workspace's own union, which this page is not part of, so
  // only the place is published.
  usePublishAgentContext({ place: `Infrastructure · ${tab}` });

  const filters = useMemo(
    () => ({
      caseId: caseId === '' ? undefined : caseId,
      since: sinceParam,
      until: untilParam,
    }),
    [caseId, sinceParam, untilParam],
  );

  const findingQuery = useMemo(() => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries({
      kind: kind === 'all' ? '' : kind,
      severity: severity === 'all' ? '' : severity,
      case_id: filters.caseId,
      subject: subject === '' ? '' : subject,
      network: network === 'all' ? '' : network,
      since: filters.since,
      until: filters.until,
    })) {
      if (value !== undefined && value !== '') query.set(key, value);
    }
    return query.toString();
  }, [kind, severity, filters, subject, network]);

  const matchQuery = useMemo(() => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries({
      case_id: filters.caseId,
      subject: subject === '' ? '' : subject,
      since: filters.since,
      until: filters.until,
    })) {
      if (value !== undefined && value !== '') query.set(key, value);
    }
    return query.toString();
  }, [filters, subject]);

  const observationQuery = useMemo(() => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries({
      case_id: filters.caseId,
      subject: subject === '' ? '' : subject,
      network: network === 'all' ? '' : network,
      since: filters.since,
      until: filters.until,
    })) {
      if (value !== undefined && value !== '') query.set(key, value);
    }
    return query.toString();
  }, [filters, subject, network]);

  const summaryQuery = useMemo(
    () =>
      new URLSearchParams(
        Object.entries({
          case_id: filters.caseId,
          since: filters.since,
          until: filters.until,
        }).filter(([, value]) => value !== undefined && value !== '') as [string, string][],
      ).toString(),
    [filters],
  );
  const summary = useApi<InfraSummary>(
    `/api/v1/infrastructure/summary${summaryQuery === '' ? '' : `?${summaryQuery}`}`,
  );

  const findings = useApi<InfraFinding[]>(`/api/v1/infrastructure/findings${findingQuery === '' ? '' : `?${findingQuery}`}`);
  const matches = useApi<InfraMatch[]>(`/api/v1/infrastructure/matches${matchQuery === '' ? '' : `?${matchQuery}`}`);
  const observations = useApi<InfraObservation[]>(`/api/v1/infrastructure/observations${observationQuery === '' ? '' : `?${observationQuery}`}`);

  // Only the active tab's data is rendered, but the counts on the other tabs
  // come from the summary so the tab strip is not a guess.
  const active = tab === 'findings' ? findings : tab === 'matches' ? matches : observations;

  const findingSort = readSort<FindingSortKey>(
    params.get('fsort'),
    params.get('fdir'),
    ['detected_at', 'severity', 'kind', 'confidence', 'subject'],
    { key: 'detected_at', dir: 'desc' },
  );
  const matchSort = readSort<MatchSortKey>(
    params.get('msort'),
    params.get('mdir'),
    ['overall', 'strongest', 'corroboration', 'detected_at'],
    { key: 'overall', dir: 'desc' },
  );
  const observationSort = readSort<ObservationSortKey>(
    params.get('osort'),
    params.get('odir'),
    ['observed_at', 'network', 'source', 'subject', 'relations'],
    { key: 'observed_at', dir: 'desc' },
  );

  const toggleSort = (
    prefix: 'f' | 'm' | 'o',
    current: { key: string; dir: 'asc' | 'desc' },
    key: string,
  ): void => {
    patch({
      [`${prefix}sort`]: current.key === key ? '' : key,
      [`${prefix}dir`]: current.key === key && current.dir === 'asc' ? 'desc' : 'asc',
    });
  };

  const selectedFinding =
    findings.data?.find((row) => row.finding_id === inspect) ?? null;
  const selectedMatch = matches.data?.find((row) => row.match_id === inspect) ?? null;
  const selectedObservation =
    observations.data?.find((row) => row.observation_id === inspect) ?? null;

  /*
   * The rail is derived from `?inspect=` rather than from local selection
   * state, so a link into a specific finding or correlation renders with the
   * rail already open. `InspectorRail` takes its props explicitly, the same
   * way the investigations register passes them.
   */
  const rail: InspectorRailProps | null = useMemo(() => {
    if (selectedFinding !== null) return findingRailProps(selectedFinding);
    if (selectedMatch !== null) return matchRailProps(selectedMatch);
    if (selectedObservation !== null) return observationRailProps(selectedObservation);
    return null;
  }, [selectedFinding, selectedMatch, selectedObservation]);

  const exportHref = (dataset: 'findings' | 'matches' | 'observations'): string =>
    apiUrl(
      `/v1/infrastructure/export?${new URLSearchParams(
        Object.entries({
          format: 'csv',
          dataset,
          kind: kind === 'all' ? '' : kind,
          severity: severity === 'all' ? '' : severity,
          case_id: filters.caseId,
          subject: subject === '' ? '' : subject,
          network: network === 'all' ? '' : network,
          since: filters.since,
          until: filters.until,
        }).filter(([, value]) => value !== undefined && value !== '') as [string, string][],
      )}`,
    );

  const rowsLabel =
    active.loading
      ? 'loading'
      : `${(active.data ?? []).length} row${(active.data ?? []).length === 1 ? '' : 's'}`;

  return (
    <div className="inf-page">
      <header className="inf-page__head">
        <div>
          <h1 className="inf-page__title">Infrastructure</h1>
          <p className="inf-page__sub">
            Misconfigurations in Tor hidden services, and the clearnet infrastructure that may sit
            behind them. Everything here is a candidate for analyst review: shared hosting, a CDN
            and a reused default banner each produce these signals legitimately, and every row
            carries what it does not establish.
          </p>
        </div>
        <div className="inf-page__actions">
          <a
            className="inf-btn"
            href={exportHref(tab === 'matches' ? 'matches' : tab === 'observations' ? 'observations' : 'findings')}
            onClick={async (event) => {
              // The export needs the credential, which lives in a header and
              // not in the URL. Fetch it with the header and hand the analyst
              // a file.
              event.preventDefault();
              const response = await fetch(
                exportHref(tab === 'matches' ? 'matches' : tab === 'observations' ? 'observations' : 'findings'),
                { headers: authHeaders() },
              );
              const blob = await response.blob();
              const url = URL.createObjectURL(blob);
              const anchor = document.createElement('a');
              anchor.href = url;
              anchor.download = `aegis-infrastructure-${tab}.csv`;
              anchor.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export CSV
          </a>
        </div>
      </header>

      <nav className="inf-tabs" role="tablist" aria-label="Infrastructure registers">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            id={`inf-tab-${entry.id}`}
            aria-selected={tab === entry.id}
            tabIndex={tab === entry.id ? 0 : -1}
            className="inf-tab"
            onClick={() => patch({ tab: entry.id === 'findings' ? null : entry.id, inspect: null })}
          >
            {entry.label}
            <span className="inf-tab__count">
              {summary.data === null
                ? ''
                : entry.id === 'findings'
                  ? summary.data.findings_total
                  : entry.id === 'matches'
                    ? summary.data.matches_total
                    : summary.data.observations_total}
            </span>
          </button>
        ))}
      </nav>

      <DataBlock
        title="Coverage"
        lead={leadFor('infra.summary', {
          single: summary.data?.single_channel_matches ?? null,
          total: summary.data?.matches_total ?? null,
        })}
      >
        {summary.error !== null ? (
          <ErrorState message={summary.error} onRetry={summary.reload} />
        ) : summary.loading ? (
          <LoadingState label="Reading counts…" />
        ) : summary.data === null ? (
          <EmptyState
            title="No summary returned"
            message="The summary endpoint returned nothing for these filters."
            endpoint="/api/v1/infrastructure/summary"
          />
        ) : (
          <>
            <SummaryStrip summary={summary.data} />
            {/* `WeakShare` already renders a <p>; wrapping it in another one
                makes the paragraph nest inside itself, which React flags as
                invalid DOM nesting and which a screen reader flattens into
                nonsense. The spacing belongs on the child, not a wrapper. */}
            <div style={{ marginTop: 10 }}>
              <WeakShare summary={summary.data} />
            </div>
          </>
        )}
      </DataBlock>

      <div className="inf-filters">
        <TimelineControl
          from={from}
          until={until}
          onChange={(next) => patch({ from: next.from === '' ? null : next.from, until: next.until === '' ? null : next.until })}
        />
        <div className="inf-field">
          <label className="inf-field__label" htmlFor="inf-subject">
            Subject contains
          </label>
          <input
            id="inf-subject"
            type="search"
            placeholder="onion address or domain"
            value={subject}
            onChange={(event) => patch({ subject: event.target.value === '' ? null : event.target.value })}
          />
        </div>
        <div className="inf-field">
          <label className="inf-field__label" htmlFor="inf-case">
            Case id
          </label>
          <input
            id="inf-case"
            type="search"
            placeholder="all investigations"
            value={caseId}
            onChange={(event) => patch({ case: event.target.value === '' ? null : event.target.value })}
          />
        </div>
        {tab === 'findings' && (
          <>
            <div className="inf-field">
              <label className="inf-field__label" htmlFor="inf-kind">
                Kind
              </label>
              <select id="inf-kind" value={kind} onChange={(event) => patch({ kind: event.target.value })}>
                <option value="all">All kinds</option>
                {INFRA_FINDING_KINDS.map((value) => (
                  <option key={value} value={value}>
                    {value.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </div>
            <div className="inf-field">
              <label className="inf-field__label" htmlFor="inf-severity">
                Severity
              </label>
              <select
                id="inf-severity"
                value={severity}
                onChange={(event) => patch({ severity: event.target.value })}
              >
                <option value="all">All severities</option>
                {INFRA_SEVERITIES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
          </>
        )}
        {tab !== 'findings' && (
          <div className="inf-field">
            <label className="inf-field__label" htmlFor="inf-network">
              Network
            </label>
            <select
              id="inf-network"
              value={network}
              onChange={(event) => patch({ network: event.target.value })}
            >
              <option value="all">Both networks</option>
              <option value="onion">Tor hidden services</option>
              <option value="clearnet">Clearnet hosts</option>
            </select>
          </div>
        )}
      </div>

      {tab === 'findings' && (
        <DataBlock
          title={`Misconfigurations · ${rowsLabel}`}
          lead={leadFor('infra.findings', {
            shown: (findings.data ?? []).length,
            total: summary.data?.findings_total ?? null,
          })}
        >
          {findings.error !== null ? (
            <ErrorState message={findings.error} onRetry={findings.reload} />
          ) : findings.loading ? (
            <LoadingState label="Loading findings…" />
          ) : (findings.data ?? []).length === 0 ? (
            <EmptyState
              title="No misconfigurations in this window"
              message="Nothing was filed for these filters. A narrow timeline excludes records that exist outside it; an empty result is not a clean service."
              endpoint="/api/v1/infrastructure/findings"
            />
          ) : (
            <FindingsTable
              rows={sortFindings(findings.data ?? [], findingSort)}
              sort={findingSort}
              onSort={(key) => toggleSort('f', findingSort, key)}
              selectedId={inspect}
              onSelect={(row) => patch({ inspect: row.finding_id })}
            />
          )}
        </DataBlock>
      )}

      {tab === 'matches' && (
        <DataBlock
          title={`Correlations · ${rowsLabel}`}
          lead={leadFor('infra.matches', {
            shown: (matches.data ?? []).length,
            total: summary.data?.matches_total ?? null,
          })}
        >
          <p className="inf-caption" style={{ marginBottom: 8 }}>
            {leadFor('infra.breakdown')}
          </p>
          {matches.error !== null ? (
            <ErrorState message={matches.error} onRetry={matches.reload} />
          ) : matches.loading ? (
            <LoadingState label="Loading correlations…" />
          ) : (matches.data ?? []).length === 0 ? (
            <EmptyState
              title="No candidate origin servers in this window"
              message="No stored observation pair cleared the thresholds the last run was scored under. That is an absence of matches, not an absence of shared infrastructure."
              endpoint="/api/v1/infrastructure/matches"
            />
          ) : (
            <MatchesTable
              rows={sortMatches(matches.data ?? [], matchSort)}
              sort={matchSort}
              onSort={(key) => toggleSort('m', matchSort, key)}
              selectedId={inspect}
              onSelect={(row) => patch({ inspect: row.match_id })}
            />
          )}
          <div style={{ marginTop: 12 }}>
            <CorrelateRunner caseId={caseId} onComplete={matches.reload} />
          </div>
        </DataBlock>
      )}

      {tab === 'observations' && (
        <DataBlock
          title={`Observations · ${rowsLabel}`}
          lead={leadFor('infra.observations', {
            shown: (observations.data ?? []).length,
            total: summary.data?.observations_total ?? null,
          })}
        >
          {observations.error !== null ? (
            <ErrorState message={observations.error} onRetry={observations.reload} />
          ) : observations.loading ? (
            <LoadingState label="Loading observations…" />
          ) : (observations.data ?? []).length === 0 ? (
            <EmptyState
              title="No observations in this window"
              message="Nothing was recorded for these filters. The timeline above may be narrower than the data."
              endpoint="/api/v1/infrastructure/observations"
            />
          ) : (
            <ObservationsTable
              rows={sortObservations(observations.data ?? [], observationSort)}
              sort={observationSort}
              onSort={(key) => toggleSort('o', observationSort, key)}
              selectedId={inspect}
              onSelect={(row) => patch({ inspect: row.observation_id })}
            />
          )}
        </DataBlock>
      )}

      <p className="inf-footnote">{leadFor('infra.timeline')}</p>

      {rail !== null && <InspectorRail {...rail} onClose={() => patch({ inspect: null })} />}
    </div>
  );
}

/*
 * Rail builders.
 *
 * `InspectorRail` renders facts, a status strip and optional tab panels, so
 * each of the three registers describes itself in that shape. The facts carry
 * the identifiers and the score; the tabs carry the long-form material — for
 * a finding, what it does not establish; for a match, the full breakdown; for
 * an observation, the whole extracted feature document.
 */

function findingRailProps(finding: InfraFinding): InspectorRailProps {
  const status: InspectorStatus[] = [
    { label: finding.severity, tone: SEVERITY_TONE[finding.severity] ?? 'muted' },
    finding.confidence === null
      ? { label: 'unscored', tone: 'muted' }
      : { label: `confidence ${formatPercent(finding.confidence)}`, tone: 'warn' },
  ];
  return {
    open: true,
    onClose: () => undefined,
    title: finding.kind_label,
    subtitle: finding.detail,
    status,
    facts: [
      { label: 'Subject', value: finding.subject, mono: true },
      { label: 'Network', value: finding.network },
      { label: 'Kind', value: finding.kind },
      { label: 'Severity', value: finding.severity },
      { label: 'Detected', value: formatDateTime(finding.detected_at) },
      { label: 'Observed', value: formatDateTime(finding.observed_at) },
      {
        label: 'Case',
        value: finding.case_id === null ? 'unattributed' : shortId(finding.case_id),
      },
    ],
    confidence:
      finding.confidence === null ? undefined : { value: finding.confidence, kind: 'recorded' },
    identifiers: [
      { kind: 'finding', value: finding.finding_id },
      { kind: 'observation', value: finding.observation_id },
    ].concat(finding.evidence_id === null ? [] : [{ kind: 'evidence', value: finding.evidence_id }]),
    tabs: [{ id: 'limitations', label: 'Limitations' }],
    activeTab: 'limitations',
    tabPanels: {
      limitations: <Limitations notes={finding.limitations} alwaysOpen label="Does not establish" />,
    },
  };
}

function matchRailProps(match: InfraMatch): InspectorRailProps {
  return {
    open: true,
    onClose: () => undefined,
    title: `${match.onion_subject.slice(0, 14)}… → ${match.clearnet_subject}`,
    subtitle: `overall ${formatPercent(match.overall)}, carried by ${match.strongest_channel ?? 'no named channel'}`,
    status: [
      match.single_channel
        ? { label: 'single channel', tone: 'warn' }
        : { label: `${match.breakdown.decisive_channels.length} channels`, tone: 'ok' },
      { label: 'candidate', tone: 'muted' },
    ],
    facts: [
      { label: 'Onion', value: match.onion_subject, mono: true },
      { label: 'Clearnet', value: match.clearnet_subject, mono: true },
      { label: 'Overall', value: formatPercent(match.overall) },
      { label: 'Strongest', value: match.strongest_channel ?? '—' },
      {
        label: 'Decisive',
        value:
          match.breakdown.decisive_channels.length === 0
            ? 'none'
            : match.breakdown.decisive_channels.join(', '),
      },
      { label: 'Recorded', value: formatDateTime(match.detected_at) },
      {
        label: 'Case',
        value: match.case_id === null ? 'unattributed' : shortId(match.case_id),
      },
    ],
    identifiers: [
      { kind: 'match', value: match.match_id },
      { kind: 'onion observation', value: match.onion_observation_id },
      { kind: 'clearnet observation', value: match.clearnet_observation_id },
    ],
    tabs: [
      { id: 'breakdown', label: 'Breakdown' },
      { id: 'limitations', label: 'Limitations' },
    ],
    activeTab: 'breakdown',
    tabPanels: {
      breakdown: (
        <>
          <ChannelBars breakdown={match.breakdown} strongestChannel={match.strongest_channel} />
          <p className="inf-footnote" style={{ marginTop: 8 }}>
            A channel marked • cleared its own cutoff. `n/o` means it was not observed on both
            sides, so it contributed nothing — that is missing data, not disagreement.
          </p>
        </>
      ),
      limitations: <Limitations notes={match.limitations} alwaysOpen label="Does not establish" />,
    },
  };
}

function observationRailProps(observation: InfraObservation): InspectorRailProps {
  return {
    open: true,
    onClose: () => undefined,
    title: observation.subject,
    subtitle: `${observation.network} · ${observation.source}`,
    status: [
      { label: observation.network, tone: observation.network === 'onion' ? 'warn' : 'muted' },
      {
        label: `${observation.finding_count} findings · ${observation.match_count} matches`,
        tone: 'muted',
      },
    ],
    facts: [
      { label: 'Subject', value: observation.subject, mono: true },
      { label: 'Network', value: observation.network },
      { label: 'Source', value: observation.source },
      { label: 'Observed', value: formatDateTime(observation.observed_at) },
      {
        label: 'Window end',
        value:
          observation.observed_until === null
            ? 'instant observation'
            : formatDateTime(observation.observed_until),
      },
    ],
    identifiers: [
      { kind: 'observation', value: observation.observation_id },
    ].concat(
      observation.evidence_id === null ? [] : [{ kind: 'evidence', value: observation.evidence_id }],
    ),
    tabs: [
      { id: 'features', label: 'Features' },
      { id: 'document', label: 'Raw document' },
    ],
    activeTab: 'features',
    tabPanels: {
      features: <FeatureDigest features={observation.features} />,
      document: (
        <pre className="inf-features">{JSON.stringify(observation.features, null, 2)}</pre>
      ),
    },
  };
}

export default InfrastructurePage;
