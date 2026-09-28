import { useState } from 'react';
import type { FormEvent } from 'react';
import { api, formatApiError } from '../api/client';
import { SOURCE_TIERS, SOURCE_TYPES } from '../api/types';
import type { CreatedSource, SourceCreate, SourceTier, SourceType } from '../api/types';
import { Badge } from '../components/Badge';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { Sparkline } from '../components/Sparkline';
import { formatPercent, scoreTone, shortId } from '../lib/format';
import { useSession } from '../store/session';
import type { RegisteredSource } from '../store/session';

type Status =
  | { readonly kind: 'idle' }
  | { readonly kind: 'busy' }
  | { readonly kind: 'ok'; readonly message: string }
  | { readonly kind: 'error'; readonly message: string };

/**
 * Screen 9 — source reliability.
 *
 * `POST /api/v1/sources` is live; there is no `GET /api/v1/sources`, so the
 * reliability table lists sources registered in this session and says so.
 */
export function SourcesPage() {
  const { sources, rememberSource } = useSession();
  const [name, setName] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('synthetic');
  const [tier, setTier] = useState<SourceTier>('C');
  const [reliability, setReliability] = useState('0.5');
  const [group, setGroup] = useState('');
  const [status, setStatus] = useState<Status>({ kind: 'idle' });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    const reliabilityValue = Number(reliability);
    if (trimmedName === '') {
      setStatus({ kind: 'error', message: 'A source name is required.' });
      return;
    }
    if (!Number.isFinite(reliabilityValue) || reliabilityValue < 0 || reliabilityValue > 1) {
      setStatus({ kind: 'error', message: 'Reliability must be a number between 0 and 1.' });
      return;
    }

    const payload: SourceCreate = {
      source_type: sourceType,
      name: trimmedName,
      tier,
      reliability: reliabilityValue,
      metadata: {},
      ...(group.trim() === '' ? {} : { independence_group: group.trim() }),
    };

    setStatus({ kind: 'busy' });
    api
      .createSource(payload)
      .then((created: CreatedSource) => {
        rememberSource({ ...created, tier });
        setStatus({ kind: 'ok', message: `Source registered: ${created.source_id}` });
        setName('');
        setGroup('');
      })
      .catch((error: unknown) => {
        setStatus({ kind: 'error', message: formatApiError(error) });
      });
  };

  const columns: ReadonlyArray<Column<RegisteredSource>> = [
    { key: 'name', header: 'Name', render: (row) => row.name },
    {
      key: 'type',
      header: 'Type',
      render: (row) => <Badge tone="info">{row.source_type}</Badge>,
    },
    {
      key: 'tier',
      header: 'Tier',
      // Tier is not echoed by POST /api/v1/sources; show the submitted value.
      render: (row) => <Badge tone="neutral">tier {row.tier}</Badge>,
      width: '7%',
    },
    {
      key: 'reliability',
      header: 'Reliability',
      render: (row) => (
        <span className="reliability">
          <span className="bar bar--inline">
            <span
              className={`bar__fill bar__fill--${scoreTone(row.reliability)}`}
              style={{ width: `${Math.round(row.reliability * 100)}%` }}
            />
          </span>
          {formatPercent(row.reliability)}
        </span>
      ),
    },
    {
      key: 'id',
      header: 'Source ID',
      render: (row) => (
        <span className="mono" title={row.source_id}>
          {shortId(row.source_id, 12)}
        </span>
      ),
    },
  ];

  const reliabilitySeries = sources.map((source) => source.reliability);

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Source reliability</h1>
          <p className="page-sub">
            Register collection sources and track how much each is trusted. Registration is a live{' '}
            <code>POST /api/v1/sources</code>; listing needs <code>GET /api/v1/sources</code>, which
            does not exist yet, so the table is session-scoped.
          </p>
        </div>
      </header>

      <div className="grid-2">
        <Panel
          title="Register a source"
          description="Tier policy: A synthetic · B public research · C authorised · D analyst-submitted · E restricted."
        >
          <form className="form" onSubmit={handleSubmit}>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="src-name">Name (required)</label>
                <input
                  id="src-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="AEGIS Synthetic Generator"
                  maxLength={256}
                  autoComplete="off"
                />
              </div>
              <div className="field">
                <label htmlFor="src-type">Source type</label>
                <select
                  id="src-type"
                  value={sourceType}
                  onChange={(event) => setSourceType(event.target.value as SourceType)}
                >
                  {SOURCE_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="src-tier">Tier</label>
                <select
                  id="src-tier"
                  value={tier}
                  onChange={(event) => setTier(event.target.value as SourceTier)}
                >
                  {SOURCE_TIERS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="src-reliability">Reliability (0–1)</label>
                <input
                  id="src-reliability"
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={reliability}
                  onChange={(event) => setReliability(event.target.value)}
                />
              </div>
              <div className="field field--wide">
                <label htmlFor="src-group">Independence group (optional)</label>
                <input
                  id="src-group"
                  value={group}
                  onChange={(event) => setGroup(event.target.value)}
                  placeholder="derived from the name when omitted"
                  autoComplete="off"
                />
              </div>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn btn--primary" disabled={status.kind === 'busy'}>
                {status.kind === 'busy' ? 'Registering…' : 'Register source'}
              </button>
              <span className="hint">POST /api/v1/sources</span>
            </div>
            {status.kind === 'ok' && (
              <p className="status status--ok" role="status">
                {status.message}
              </p>
            )}
            {status.kind === 'error' && (
              <p className="status status--error" role="alert">
                {status.message}
              </p>
            )}
          </form>
        </Panel>

        <Panel
          title="Reliability trend"
          description="Sources in the order they were registered this session."
        >
          {sources.length === 0 ? (
            <EmptyState
              title="No sources registered"
              message="Register a source with the form to populate this chart and the table. Historical reliability cannot be listed because the API has no source-list route."
              endpoint="GET /api/v1/sources"
            />
          ) : (
            <>
              <Sparkline
                values={reliabilitySeries}
                label="Reliability of session-registered sources, in registration order"
              />
              <dl className="kv">
                <dt>Sources registered</dt>
                <dd>{sources.length}</dd>
                <dt>Mean reliability</dt>
                <dd>
                  {formatPercent(
                    reliabilitySeries.reduce((total, value) => total + value, 0) /
                      reliabilitySeries.length,
                  )}
                </dd>
              </dl>
            </>
          )}
        </Panel>
      </div>

      <Panel
        title="Registered sources"
        description="This browser session only — no list endpoint exists to re-read them."
      >
        <DataTable<RegisteredSource>
          columns={columns}
          rows={sources}
          rowKey={(row) => row.source_id}
          caption="Sources registered in this session"
          empty={
            <EmptyState
              title="No sources yet"
              message="POST /api/v1/sources returns source_id, type, name and reliability; those land here as soon as one is registered."
              endpoint="GET /api/v1/sources"
            />
          }
        />
        <p className="hint">
          The API response omits tier and independence group, so the tier column reflects the value
          submitted with the form.
        </p>
      </Panel>
    </div>
  );
}
