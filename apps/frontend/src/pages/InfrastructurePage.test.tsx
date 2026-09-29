import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { InfrastructurePage } from './InfrastructurePage';
import type { InfraFinding, InfraMatch, InfraObservation, InfraSummary } from '../api/types';
import { installFetch, jsonResponse } from '../test/mockFetch';

/*
 * These tests exist to pin the honesty rules, not the layout.
 *
 * Each one asserts a way this page could be made to look better and be less
 * true: a shared fingerprint scored as if it were a probability, an unobserved
 * channel drawn at zero, a single-dimension correlation reading like a
 * corroborated one, or a finding whose caveats are one click and a half away.
 * A refactor that breaks one of these has made the register lie, and the
 * failing test is the warning.
 */

const SCORED: InfraFinding = {
  finding_id: 'f-scored',
  observation_id: 'o-1',
  case_id: 'case-1',
  subject: 'k3x7mq2zp4nt6vh8c5rd9bwg3lyfj2u5oqt7vxa4zncmwe6krsbhju3pdg.onion',
  network: 'onion',
  kind: 'clearnet_certificate',
  kind_label: 'Clearnet-tied certificate',
  severity: 'high',
  detail: 'The certificate served by the hidden service carries a clearnet SAN.',
  limitations: [
    'A mirror operator holds the domain legitimately; this shows control of the name, not common control of the host.',
  ],
  confidence: 0.85,
  detected_at: '2026-09-20T10:00:00Z',
  observed_at: '2026-09-19T10:00:00Z',
  evidence_id: 'e-1',
  metadata: {},
};

// The row the unscored behaviour is about. A shared fingerprint gets no
// number, because the number would be read as a probability of common
// control and it is not one.
const UNSCORED: InfraFinding = {
  ...SCORED,
  finding_id: 'f-unscored',
  kind: 'shared_fingerprint',
  kind_label: 'Shared fingerprint',
  severity: 'high',
  confidence: null,
  limitations: [
    'An identical certificate is what shared hosting, a CDN terminating TLS, and a migration between hosts all look like.',
  ],
};

const FINDINGS: InfraFinding[] = [SCORED, UNSCORED];

function match(overrides: Partial<InfraMatch> & Pick<InfraMatch, 'match_id' | 'single_channel'>): InfraMatch {
  return {
    case_id: 'case-1',
    onion_observation_id: 'o-1',
    clearnet_observation_id: 'o-2',
    onion_subject: 'k3x7mq2zp4nt6vh8c5rd9bwg3lyfj2u5oqt7vxa4zncmwe6krsbhju3pdg.onion',
    clearnet_subject: 'quiet-relay.example',
    overall: 0.62,
    breakdown: {
      certificate: 0.55,
      content: null,
      technology: 0.3,
      http: 0.71,
      tls: 0.44,
      temporal: 0.8,
      available_channels: ['certificate', 'technology', 'http', 'tls', 'temporal'],
      decisive_channels: ['http'],
    },
    strongest_channel: 'http',
    limitations: ['Shared infrastructure does not establish common control, ownership or operation.'],
    sources: [],
    evidence_ids: [],
    detected_at: '2026-09-21T10:00:00Z',
    metadata: {},
    ...overrides,
  };
}

// A high score carried entirely by one channel: the same finding shape as the
// corroborated one, and not the same finding.
const SINGLE_CHANNEL = match({
  match_id: 'm-single',
  single_channel: true,
  overall: 0.92,
  breakdown: {
    certificate: 1,
    // Never captured on the clearnet side, so it was not scored — which is a
    // different fact from having been scored and found to disagree.
    content: null,
    technology: 0,
    http: 0.24,
    tls: 0.13,
    temporal: 0.33,
    available_channels: ['certificate', 'technology', 'http', 'tls', 'temporal'],
    decisive_channels: ['certificate'],
  },
  strongest_channel: 'certificate',
});

// The same 0.92, corroborated on three channels.
const CORROBORATED = match({
  match_id: 'm-corroborated',
  single_channel: false,
  overall: 0.92,
  breakdown: {
    certificate: 1,
    content: 0.93,
    technology: 1,
    http: 1,
    tls: 1,
    temporal: 1,
    available_channels: ['certificate', 'content', 'technology', 'http', 'tls', 'temporal'],
    decisive_channels: ['certificate', 'content', 'http'],
  },
  strongest_channel: 'certificate',
});

const MATCHES: InfraMatch[] = [SINGLE_CHANNEL, CORROBORATED];

const OBSERVATIONS: InfraObservation[] = [
  {
    observation_id: 'o-1',
    subject: 'quiet-relay.example',
    network: 'clearnet',
    source: 'synthetic-collector',
    observed_at: '2026-09-19T10:00:00Z',
    observed_until: '2026-09-19T18:00:00Z',
    case_id: 'case-1',
    evidence_id: 'e-1',
    features: {
      schema_version: 'aegis-infrastructure/1',
      observation: {
        tls: { version: 'TLSv1.3', cipher_suite: 'TLS_AES_256_GCM_SHA384', alpn: ['h2'], ja3: 'abc123' },
        http: { status_code: 200, server: 'nginx/1.24.0', content_type: 'text/html' },
        certificate: { subject: 'CN=quiet-relay.example', issuer: 'C=Example', fingerprint_sha256: 'ff' },
        technologies: ['nginx:1.24.0'],
      },
      content: { sha256: 'abc', simhash: 42 },
      technology_keys: ['nginx:1.24.0'],
    },
    finding_count: 2,
    match_count: 1,
  },
];

const SUMMARY: InfraSummary = {
  findings_total: 2,
  findings_by_kind: {
    exposed_status_page: 0,
    clearnet_certificate: 1,
    default_banner: 0,
    descriptor_inconsistency: 0,
    shared_fingerprint: 1,
  },
  findings_by_severity: { critical: 0, high: 2, medium: 0, low: 0, informational: 0 },
  findings_unscored: 1,
  observations_total: 1,
  onion_services: 1,
  clearnet_hosts: 1,
  matches_total: 2,
  single_channel_matches: 1,
  matches_by_strongest_channel: { certificate: 1, http: 1 },
  earliest_observation: '2026-09-19T10:00:00Z',
  latest_observation: '2026-09-19T18:00:00Z',
};

function installInfraFetch(): { urls: string[] } {
  const urls: string[] = [];
  installFetch(async (input) => {
    const url = String(input);
    urls.push(url);
    if (url.includes('/v1/infrastructure/summary')) return jsonResponse(SUMMARY);
    if (url.includes('/v1/infrastructure/findings')) return jsonResponse(FINDINGS);
    if (url.includes('/v1/infrastructure/matches')) return jsonResponse(MATCHES);
    if (url.includes('/v1/infrastructure/observations')) return jsonResponse(OBSERVATIONS);
    throw new Error(`Unexpected request: ${url}`);
  });
  return { urls };
}

function renderPage(initialEntry = '/infrastructure'): void {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <InfrastructurePage />
    </MemoryRouter>,
  );
}

function renderRouted(initialEntry: string): void {
  function Probe() {
    const location = useLocation();
    return <span data-testid="location">{location.pathname + location.search}</span>;
  }
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/infrastructure"
          element={
            <>
              <InfrastructurePage />
              <Probe />
            </>
          }
        />
        <Route path="*" element={<p>Other</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('InfrastructurePage', () => {
  it('serves an unscored detector as "unscored" rather than as 0%', async () => {
    installInfraFetch();
    renderPage();

    const row = await screen.findByText('Shared fingerprint');
    const cells = row.closest('tr') as HTMLElement;
    expect(within(cells).getByText('unscored')).toBeInTheDocument();
    // A zero-width bar beside "0.0%" would read as a measured score of zero,
    // which says the opposite of what an unscored detector means.
    expect(within(cells).queryByText('0.0%')).not.toBeInTheDocument();
  });

  it('shows the limitations on the row, not only in a detail view', async () => {
    installInfraFetch();
    renderPage();

    await screen.findByText('Shared fingerprint');
    const toggle = screen.getAllByRole('button', { name: /1 limitation/ })[0]!;
    expect(toggle).toBeInTheDocument();
    // The count is the collapsed form; the words are the actual caveat and
    // have to be reachable without leaving the register.
    await userEvent.click(toggle);
    expect(
      screen.getByText(/shared hosting, a CDN terminating TLS/i),
    ).toBeInTheDocument();
  });

  it('labels a single-channel match as such, at the same weight as its score', async () => {
    installInfraFetch();
    renderPage('/infrastructure?tab=matches');

    // Both rows score 92% on purpose: the same number, two different
    // findings, and the label is the only thing that tells them apart.
    const scores = await screen.findAllByText('92%');
    expect(scores).toHaveLength(2);

    const single = (await screen.findByText('single channel')).closest('tr') as HTMLElement;
    expect(within(single).getByText('92%')).toBeInTheDocument();
    // Named twice on the row — the strongest-channel column and the decisive
    // channel bar — which is itself the point: the channel is named, not inferred.
    expect(within(single).getAllByText('certificate').length).toBeGreaterThanOrEqual(2);

    // The corroborated 92% must not be labelled the same way.
    const corroborated = screen.getByText('3 channels');
    expect(corroborated.className).toContain('inf-strong');
    const corroboratedRow = corroborated.closest('tr') as HTMLElement;
    expect(within(corroboratedRow).queryByText('single channel')).not.toBeInTheDocument();
  });

  it('draws an unobserved channel as not-observed, never as zero', async () => {
    installInfraFetch();
    renderPage('/infrastructure?tab=matches');

    const bars = await screen.findByLabelText('content: not observed on both sides');
    expect(bars).toBeInTheDocument();
    expect(screen.getByText('n/o')).toBeInTheDocument();
    // A rendered 0.0% for content would assert the two pages were measured
    // and found to differ. They were never measured.
    expect(screen.queryByLabelText('content: 0.0%')).not.toBeInTheDocument();
  });

  it('puts the single-channel share in the summary rather than only the total', async () => {
    installInfraFetch();
    renderPage();

    const tile = (await screen.findByText('single-channel')).closest('div') as HTMLElement;
    expect(within(tile).getByText('1')).toBeInTheDocument();
    expect(within(tile).getByText(/corroborated/)).toBeInTheDocument();
    expect(screen.getByText(/of correlations in this window rest on a single channel/)).toBeInTheDocument();
  });

  it('sends the timeline window to the API rather than slicing on the client', async () => {
    const { urls } = installInfraFetch();
    renderPage('/infrastructure?from=2026-01-01&until=2026-02-01&kind=default_banner');

    await screen.findByText('Shared fingerprint');
    const findingsCall = urls.find((url) => url.includes('/v1/infrastructure/findings'));
    expect(findingsCall).toBeDefined();
    expect(findingsCall).toContain('since=2026-01-01');
    expect(findingsCall).toContain('until=2026-02-01');
    expect(findingsCall).toContain('kind=default_banner');
  });

  it('writes the tab, filters and selection into the address bar', async () => {
    installInfraFetch();
    renderRouted('/infrastructure');

    await userEvent.click(await screen.findByRole('tab', { name: /Matches/ }));
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('tab=matches');
    });

    const single = (await screen.findByText('single channel')).closest('tr') as HTMLElement;
    await userEvent.click(single);
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('inspect=m-single');
    });
  });

  it('refuses to offer a correlation run without a case to attribute it to', async () => {
    installInfraFetch();
    renderPage('/infrastructure?tab=matches');

    expect(
      await screen.findByText(/A correlation writes match rows/),
    ).toBeInTheDocument();
    // The threshold inputs are not offered at all, because there is nothing
    // to run them against.
    expect(screen.queryByLabelText('Min overall')).not.toBeInTheDocument();
  });

  it('requires the analyst to state the thresholds before a run', async () => {
    installInfraFetch();
    renderPage('/infrastructure?tab=matches&case=case-1');

    // Every cutoff is an explicit input, not a hidden default.
    for (const label of ['Min overall', 'Min certificate', 'Min content', 'Min HTTP']) {
      expect(await screen.findByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByLabelText('Min overall')).toHaveValue(0.42);
  });
});
