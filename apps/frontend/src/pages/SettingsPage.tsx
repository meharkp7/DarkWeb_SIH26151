import { healthUrl } from '../api/client';
import type { HealthResponse } from '../api/types';
import { Panel } from '../components/Panel';
import { useApi } from '../hooks/useApi';

/**
 * Deployment and connection status.
 *
 * Settings is the one non-analysis space in the app, so it earns its place by
 * telling the operator what they are actually connected to. Everything here is
 * read from the live API rather than build-time constants, because the usual
 * failure this catches is "the UI is pointed at the wrong backend" — which a
 * hardcoded version string would happily hide.
 */

type Probe = {
  readonly name: string;
  /** Displayed to the operator; the request goes through the health base. */
  readonly endpoint: string;
  /** Path appended to the health base. */
  readonly path: string;
};

const PROBES: readonly Probe[] = [
  { name: 'API', endpoint: '/health', path: '' },
  { name: 'Database', endpoint: '/health/db', path: '/db' },
];

function ProbeRow({ probe }: { probe: Probe }) {
  const { data, error, loading } = useApi<HealthResponse>(healthUrl(probe.path));

  return (
    <div className="setting-row">
      <div className="setting-row__label">
        <strong>{probe.name}</strong>
        <code>{probe.endpoint}</code>
      </div>
      <div className="setting-row__state">
        {loading && <span className="pill">Checking…</span>}
        {!loading && error && (
          <span className="pill pill--critical" title={error}>
            Unreachable
          </span>
        )}
        {!loading && !error && data && (
          <span className="pill pill--ok" title={data.service}>
            {data.status}
          </span>
        )}
      </div>
    </div>
  );
}

export function SettingsPage() {
  const base = healthUrl();

  return (
    <div className="page-stack">
      <header className="hero-head">
        <div>
          <span className="eyebrow">Deployment</span>
          <h1>Settings</h1>
          <p>Where this workspace is pointed, and whether it is answering.</p>
        </div>
      </header>
      <Panel title="Connection" description="Probed live against the API this window is configured to use.">
        <div className="settings-list">
          <div className="setting-row">
            <div className="setting-row__label">
              <strong>API base</strong>
              <code>{base}</code>
            </div>
            <div className="setting-row__state">
              <span className="pill">{import.meta.env.MODE}</span>
            </div>
          </div>
          {PROBES.map((probe) => (
            <ProbeRow key={probe.name} probe={probe} />
          ))}
        </div>
      </Panel>

      <Panel title="Data handling" description="What AEGIS stores and what it refuses to do.">
        <ul className="settings-notes">
          <li>All evidence is synthetic or authorized. AEGIS is a training and analysis surface, not a collection tool.</li>
          <li>Evidence writes are chained and hashed; the ledger verifies on read, so tampering is detectable rather than assumed away.</li>
          <li>Exports are generated locally from the API. Nothing leaves the machine from this interface.</li>
        </ul>
      </Panel>

      <Panel title="Troubleshooting" description="The three failures that account for most of this.">
        <ul className="settings-notes">
          <li>
            <strong>Everything says Unreachable.</strong> The API is not running, or the frontend proxy target is wrong. Check{' '}
            <code>VITE_PROXY_TARGET</code>.
          </li>
          <li>
            <strong>API is up, Database is down.</strong> Point <code>AEGIS_DATABASE_URL</code> at a migrated PostgreSQL instance and run{' '}
            <code>make migrate</code>.
          </li>
          <li>
            <strong>Sidebar says Reconnecting.</strong> The live feed is a WebSocket on <code>/api/v1/live</code>; it is
            independent of the HTTP data and the app is fully usable without it.
          </li>
        </ul>
      </Panel>
    </div>
  );
}
