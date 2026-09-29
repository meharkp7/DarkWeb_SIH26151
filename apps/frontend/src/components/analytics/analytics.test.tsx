import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AttributionPanel } from './AttributionPanel';
import { PressurePanel } from './PressurePanel';
import { VelocityChart } from './VelocityChart';
import { CommandCenterPage } from '../../pages/CommandCenterPage';
import { clearSessionToken, setSessionToken } from '../../api/client';
import type { AttributionPosture, DashboardSnapshot, PressureIndicator, VelocityPoint } from '../../api/types';
import { AuthProvider } from '../../store/auth';
import { installFetch, jsonResponse } from '../../test/mockFetch';

/**
 * The Command Center's own regression tests.
 *
 * Two things are worth pinning here. First, the velocity chart is hand-rolled
 * geometry over data that can legitimately be degenerate — one bucket, all
 * zeros, a non-finite count — and a NaN in a path `d` silently deletes the
 * shape in every browser rather than throwing. Second, the priority queue's
 * expand control is a real `<button>` inside a row that is itself navigable,
 * which is the one interaction on the page that can break both ways.
 */

const FULL: readonly VelocityPoint[] = [
  { label: 'Jun 2026', count: 120, delta: null },
  { label: 'Jul 2026', count: 315, delta: 195 },
  { label: 'Aug 2026', count: 90, delta: -225 },
];
const SINGLE: readonly VelocityPoint[] = [{ label: 'Sep 2026', count: 0, delta: null }];
const ALL_ZERO: readonly VelocityPoint[] = [
  { label: 'Jan', count: 0, delta: 0 },
  { label: 'Feb', count: 0, delta: 0 },
];
const NON_FINITE = [
  { label: 'Jan', count: Number.NaN, delta: null },
] as unknown as readonly VelocityPoint[];

function pathData(): string[] {
  return Array.from(document.querySelectorAll('path')).map((node) => node.getAttribute('d') ?? '');
}

describe('VelocityChart', () => {
  it('draws a finite path for a full, single, all-zero and non-finite series', () => {
    for (const points of [FULL, SINGLE, ALL_ZERO, NON_FINITE]) {
      const { container, unmount } = render(<VelocityChart points={points} />);
      for (const d of pathData()) expect(d).not.toMatch(/NaN|Infinity|undefined/);
      expect(container.querySelector('svg')).not.toBeNull();
      expect(container.querySelector('title')).not.toBeNull();
      expect(container.querySelector('desc')).not.toBeNull();
      unmount();
    }
  });

  it('renders nothing for an empty series so the caller owns the empty state', () => {
    const { container } = render(<VelocityChart points={[]} />);
    expect(container.innerHTML).toBe('');
  });

  it('states the count and the signed delta on every point', () => {
    const { container } = render(<VelocityChart points={FULL} />);
    const titles = Array.from(container.querySelectorAll('title')).map((node) => node.textContent ?? '');
    expect(titles).toContain('Jun 2026: 120 collected, change —');
    expect(titles).toContain('Jul 2026: 315 collected, change +195');
    expect(titles).toContain('Aug 2026: 90 collected, change -225');
  });
});

const PRESSURE: readonly PressureIndicator[] = [
  { key: 'evidence_velocity', label: 'Evidence velocity', score: 35, observed: 315, ceiling: 900 },
  { key: 'sla_exposure', label: 'SLA exposure', score: 100, observed: 8, ceiling: 8 },
];

const ATTRIBUTION: readonly AttributionPosture[] = [
  {
    case_id: 'case-1',
    case_name: 'Alpha',
    confidence: 0.8123,
    supporting_signals: 4,
    modalities: 2,
    contradictions: 1,
    freshness: 0.4,
    explanations: ['Two independent feeds agree.'],
    signals: { behavioral: 0.7, financial: 0.1 },
  },
];

describe('PressurePanel', () => {
  it('shows the raw fraction beside every scaled score, not the score alone', () => {
    const { container } = render(<PressurePanel indicators={PRESSURE} pressureIndex={68} />);
    expect(container.textContent).toContain('315 / 900');
    expect(container.textContent).toContain('8 / 8');
    expect(container.textContent).toContain('68');
    expect(container.querySelectorAll('[role="progressbar"]')).toHaveLength(PRESSURE.length);
  });

  it('reports an absent index rather than substituting one', () => {
    const { container } = render(<PressurePanel indicators={PRESSURE} />);
    expect(container.textContent).toContain('did not return a platform pressure index');
  });
});

describe('AttributionPanel', () => {
  it('shows the evidence behind the confidence, and links to the case', () => {
    const { container } = render(
      <MemoryRouter>
        <AttributionPanel rows={ATTRIBUTION} />
      </MemoryRouter>,
    );
    expect(container.textContent).toContain('81.2%');
    expect(container.textContent).toContain('behavioral');
    expect(container.textContent).toContain('Two independent feeds agree.');
    expect(screen.getByRole('link', { name: 'Alpha' })).toHaveAttribute('href', '/cases/case-1');
  });

  it('says so when nothing has been assessed', () => {
    const { container } = render(<AttributionPanel rows={[]} />);
    expect(container.textContent).toContain('No assessment has been produced yet');
  });
});

const SNAPSHOT = {
  type: 'snapshot',
  server_time: '2026-09-29T12:00:00Z',
  counts: { cases: 2, evidence: 900, entities: 40, relationships: 12, assessments: 5 },
  critical_alerts: 2,
  activity: [
    {
      seq: 9,
      occurred_at: '2026-09-29T11:59:00Z',
      action: 'evidence.collected',
      entity_type: 'evidence',
      entity_id: 'ev-1',
      case_id: 'case-1',
      payload: { message: 'Feed ingested 12 new records' },
    },
  ],
  case_summaries: [
    {
      case_id: 'case-1',
      name: 'Alpha',
      status: 'active',
      priority: 'critical',
      severity: 'critical',
      tags: [],
      assigned_to: null,
      sla_due_at: '2026-09-29T20:00:00Z',
      sla_overdue: false,
      sla_state: 'at_risk',
      // Deliberately below the sum of its reasons, which is what the API's
      // 100-point cap produces — the row has to say so rather than assert a
      // reconciliation that did not happen.
      queue_score: 97,
      queue_reason: 'Critical priority',
      reasons: [
        { key: 'priority', label: 'Critical priority', weight: 40 },
        { key: 'evidence_velocity', label: '40 evidence in 7 days', weight: 20 },
        { key: 'unassigned', label: 'No analyst assigned', weight: 6 },
      ],
      counts: {
        evidence: 315,
        entities: 9,
        relationships: 12,
        assessments: 2,
        contradictions: 1,
        recent_evidence: 40,
      },
      last_activity: '2026-09-29T11:59:00Z',
      attribution: 0.81,
    },
    {
      case_id: 'case-2',
      name: 'Bravo',
      status: 'open',
      priority: 'medium',
      severity: 'low',
      tags: [],
      assigned_to: 'user-2',
      sla_due_at: null,
      sla_overdue: false,
      sla_state: 'none',
      queue_score: 25,
      queue_reason: 'Medium priority',
      reasons: [{ key: 'priority', label: 'Medium priority', weight: 25 }],
      counts: {
        evidence: 4,
        entities: 1,
        relationships: 0,
        assessments: 0,
        contradictions: 0,
        recent_evidence: 0,
      },
      last_activity: null,
      attribution: null,
    },
  ],
  command_posture: {
    active_investigations: 2,
    critical: 1,
    high: 0,
    sla_at_risk: 1,
    new_evidence: 315,
    unresolved_links: 1,
    total_investigations: 2,
    unassigned: 1,
    pressure_index: 68,
  },
  evidence_velocity: FULL,
  investigation_pressure: PRESSURE,
  attribution_posture: ATTRIBUTION,
} as unknown as DashboardSnapshot;

describe('CommandCenterPage', () => {
  async function renderPage(): Promise<void> {
    installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/auth/me')) {
        return jsonResponse({
          email: 'analyst@example.test',
          name: 'Test Analyst',
          role: 'analyst',
          organization: 'AEGIS',
        });
      }
      if (url.includes('/api/v1/dashboard/summary')) return jsonResponse(SNAPSHOT);
      throw new Error(`App route test received an unexpected request: ${url}`);
    });
    clearSessionToken();
    setSessionToken('command-center-token', Date.now() + 3_600_000);
    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <CommandCenterPage />
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  it('makes every posture tile a link that carries its denominator', async () => {
    await renderPage();

    const sla = await screen.findByRole('link', { name: /SLA at risk or breached/ });
    expect(sla).toHaveAttribute('href', '/cases?sla=at_risk');
    expect(sla.textContent).toContain('due within 12 hours');
    expect(screen.getByRole('link', { name: /^Active investigations/ })).toHaveAttribute(
      'href',
      '/cases?status=active',
    );
  });

  it('ranks the queue by score and expands a row without navigating', async () => {
    await renderPage();

    await screen.findAllByRole('link', { name: 'Alpha' });
    const rows = screen.getAllByRole('button', { name: 'Why' });
    const first = rows[0] as HTMLElement;
    expect(first).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(first);

    expect(screen.getByRole('button', { name: 'Hide reasons' })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('No analyst assigned')).toBeInTheDocument();
    // The published score is capped at 100, so the contributions are reported
    // as a total rather than claimed to reconcile.
    expect(screen.getByText(/signed contributions total/)).toBeInTheDocument();
  });
});
