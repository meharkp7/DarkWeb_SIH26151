import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BehaviouralShifts } from './BehaviouralShifts';
import type { TemporalRefusal, TemporalShift, TemporalShiftReport } from '../../api/types';
import { installFetch, jsonResponse } from '../../test/mockFetch';

/*
 * These tests pin the honesty rules of the panel, not its layout.
 *
 * Each one is a way this panel could be made to look better and be less true:
 * a unit-scale CUSUM alarm drawn against a 0-1 bar track, a refused window
 * presented as a subject that did not change, a caveat that only appears once
 * the finding has been read past, or a table that sorts by a number whose units
 * the detector's own documentation says cannot be compared. A refactor that
 * breaks one of these has made the register lie, and the failing test is the
 * warning.
 */

const LIMITATION_ONE =
  'A change is only emitted when the new value persists for min_persist following events.';
const LIMITATION_TWO = 'The score is 1.0 for every confirmed state change.';
const COMMON_ONE =
  'Every change point here is derived from one subject at the moment of the request.';

const LIMITATIONS: readonly string[] = [LIMITATION_ONE, LIMITATION_TWO];
const COMMON: readonly string[] = [COMMON_ONE];

function window(
  label: string,
  overrides: Partial<TemporalShift['before']> = {},
): TemporalShift['before'] {
  return {
    label,
    from_at: '2026-06-01T08:00:00Z',
    to_at: '2026-06-20T08:00:00Z',
    event_count: 20,
    values: ['post'],
    buckets: 20,
    mean_count: 2,
    evidence_ids: [`evidence-${label}-1`, `evidence-${label}-2`],
    ...overrides,
  };
}

function context(peak: number, boundaryAt: number): TemporalShift['context'] {
  return Array.from({ length: 9 }, (_, index) => ({
    at: `2026-06-${String(index + 1).padStart(2, '0')}T00:00:00Z`,
    value: `${index < boundaryAt ? 2 : peak} events`,
    count: index < boundaryAt ? 2 : peak,
    is_boundary: index === boundaryAt,
  }));
}

const STATE_SHIFT: TemporalShift = {
  change_id: 'cp-activity-0001',
  case_id: 'case-1',
  subject_id: 'entity-1',
  subject_kind: 'entity',
  subject_label: 'vendor-orbit',
  channel: 'marketplace',
  channel_label: 'marketplace',
  detector: 'state_change',
  detector_label: 'confirmed state change (persistence rule)',
  changed_at: '2026-06-21T09:00:00Z',
  sharpness: 1,
  sharpness_note: '1.0 means the new value persisted across the confirmation window.',
  direction: null,
  from_value: 'nightjar.market.example',
  to_value: 'quietpine.market.example',
  summary: 'marketplace changed: nightjar.market.example → quietpine.market.example',
  before: window('before', { values: ['nightjar.market.example'] }),
  after: window('after', { values: ['quietpine.market.example'], from_at: '2026-06-21T09:00:00Z' }),
  distribution_distance: null,
  context: context(9, 4),
  evidence_ids: ['evidence-a', 'evidence-b', 'evidence-c'],
  limitations: LIMITATIONS,
};

/** A CUSUM alarm: the score is in the detector's own units and is not 0-1. */
const ACTIVITY_SHIFT: TemporalShift = {
  ...STATE_SHIFT,
  change_id: 'cp-activity-0002',
  // A different date from the state change, so the sort has something to order.
  changed_at: '2026-06-15T09:00:00Z',
  subject_id: 'entity-9',
  subject_label: 'vendor-echo',
  channel: 'activity',
  channel_label: 'posting cadence',
  detector: 'cusum',
  detector_label: 'CUSUM over bucketed activity',
  sharpness: 812.5,
  sharpness_note: 'Cumulative excess of each bucket over reference + drift.',
  direction: 'increase',
  from_value: null,
  to_value: null,
  summary: 'posting cadence rose sharply — CUSUM alarmed in this bucket',
  before: window('before', { buckets: 20, mean_count: 2, values: [] }),
  after: window('after', { buckets: 20, mean_count: 11, values: [] }),
  distribution_distance: 0.94,
  context: context(12, 4),
  limitations: ['For CUSUM, changed_at is the start of the bucket where the detector fired.'],
};

const REFUSAL: TemporalRefusal = {
  subject_id: 'entity-2',
  subject_kind: 'entity',
  subject_label: 'entity-short',
  channel: 'activity',
  rule: 'max(2 * min_size, 4) buckets',
  reason:
    '3 bucket(s) of activity are stored and the detector needs max(2 × 3, 4) = 6. A distribution distance or a split gain over that many points is a number rather than a change, so no score was computed and this subject is reported as unanalysed rather than unchanged.',
  observed: 3,
  required: 6,
  unit: 'buckets',
};

function report(overrides: Partial<TemporalShiftReport> = {}): TemporalShiftReport {
  return {
    case_id: 'case-1',
    generated_at: '2026-06-22T00:00:00Z',
    method: 'binary_segmentation',
    bucket: '86400',
    min_persist: 2,
    subjects: 3,
    observations: 480,
    window_start: '2026-06-01T00:00:00Z',
    window_end: '2026-06-21T00:00:00Z',
    shifts: [STATE_SHIFT, ACTIVITY_SHIFT],
    refusals: [],
    basis: '2 change point(s) detected in 480 stored observations across 3 subject series.',
    limitations: [...LIMITATIONS, ...COMMON],
    ...overrides,
  };
}

/** The first evidence-expander on the page, typed. */
async function firstEvidenceToggle(): Promise<HTMLButtonElement> {
  const found = await screen.findAllByRole('button', { name: /evidence/i });
  const button = found[0];
  if (button === undefined) throw new Error('no evidence toggle rendered');
  return button as HTMLButtonElement;
}

/** The shift rows, excluding the expanded detail row that follows one of them. */
function shiftRows(table: HTMLElement): HTMLElement[] {
  return Array.from(table.querySelectorAll('tbody tr:not(.bs-detail)')) as HTMLElement[];
}

function serve(body: TemporalShiftReport): void {
  installFetch(() => jsonResponse(body));
}

describe('BehaviouralShifts', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the report basis and both changes', async () => {
    serve(report());
    render(<BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />);

    expect(
      await screen.findByText(/2 change point\(s\) detected in 480 stored observations/),
    ).toBeTruthy();
    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(within(table).getByText('vendor-orbit')).toBeTruthy();
    expect(within(table).getByText('vendor-echo')).toBeTruthy();
    expect(
      within(table).getAllByText(/marketplace changed: nightjar/).length,
    ).toBeGreaterThan(0);
  });

  it('says what the panel does not show without the reader expanding a row', async () => {
    serve(report());
    render(<BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />);

    const heading = await screen.findByText('What these numbers do not show');
    expect(heading).toBeTruthy();
    // Rendered on the page, not behind the first click: a caveat that only
    // appears after the finding has been read past is a caveat most people miss.
    expect(screen.getByText(LIMITATION_ONE)).toBeTruthy();
    expect(screen.getByText(COMMON_ONE)).toBeTruthy();
  });

  it('shows evidence on both sides of the boundary when a row is opened', async () => {
    const user = userEvent.setup();
    serve(report());
    render(<BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />);

    const toggle = await firstEvidenceToggle();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await user.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');

    const panel = screen.getByText('Evidence either side').closest('div')!;
    expect(within(panel).getByText('Before')).toBeTruthy();
    expect(within(panel).getByText('From the change')).toBeTruthy();
    expect(within(panel).getByText(/nightjar\.market\.example/)).toBeTruthy();
    expect(within(panel).getByText(/quietpine\.market\.example/)).toBeTruthy();
    // The row's own limitations sit in the same panel as its evidence, at the
    // same visual weight, rather than in a separate list further down.
    expect(within(panel).getByText(LIMITATION_TWO)).toBeTruthy();
  });

  it('draws a sharpness bar only where the score has a 0-1 scale', async () => {
    serve(report());
    const { container } = render(
      <BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />,
    );
    await screen.findByRole('table');

    const imgs = within(container).getAllByRole('img', { name: /Sharpness/ });
    // Only the confirmed state change: 1.0 on a 0-1 track means the persistence
    // rule was satisfied, which is exactly what a full bar is allowed to say.
    expect(imgs).toHaveLength(1);
    expect(imgs[0]?.getAttribute('aria-label')).toContain('confirmed');
    // The CUSUM alarm is unit-scale and unbounded. A bar beside it would invite
    // the one comparison its units forbid, so there is none, and the cell says so.
    expect(
      screen.getAllByText(/cumulative excess — not comparable across run lengths/).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('812.50')).toBeTruthy();
  });

  it('names both sides of a change, so the chart is readable without colour', async () => {
    const user = userEvent.setup();
    serve(report());
    const { container } = render(
      <BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />,
    );
    await user.click(await firstEvidenceToggle());

    expect(screen.getByText('before the change')).toBeTruthy();
    expect(screen.getByText('from the change')).toBeTruthy();
    const svg = container.querySelector('svg')!;
    expect(svg.getAttribute('aria-label')).toMatch(/change is marked at/);
    // The boundary is captioned in the drawing as well as dashed.
    expect(svg.textContent).toContain('change');
  });

  it('lists a refused window with its counts instead of showing a blank', async () => {
    serve(report({ shifts: [], refusals: [REFUSAL] }));
    render(<BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />);

    expect(await screen.findByText('not assessed')).toBeTruthy();
    expect(screen.getByText('3 / 6 buckets')).toBeTruthy();
    expect(screen.getByText(/rule: max\(2 \* min_size, 4\) buckets/)).toBeTruthy();
    // And the panel refuses to read the empty table as a clean result.
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByText(/Nothing was scored, and nothing was found/)).toBeTruthy();
  });

  it('sorts by date with aria-sort, and says which way', async () => {
    const user = userEvent.setup();
    serve(report());
    const { container } = render(
      <BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />,
    );
    const table = await screen.findByRole('table');
    const headers = within(table).getAllByRole('columnheader');
    const when = headers[0]!;
    expect(when.getAttribute('aria-sort')).toBe('descending');

    // Most recent first by default, and the row order matches. Expanded detail
    // is its own <tr>, so only the shift rows are compared.
    const first = shiftRows(table)[0];
    // Day only: `formatDateTime` renders in the reader's own zone, and this
    // test is about which row sorts first, not about a timezone.
    if (first === undefined) throw new Error('no shift rows rendered');
    expect(within(first).getByText(/^21 Jun 2026,/)).toBeTruthy();

    await user.click(within(when).getByRole('button', { name: /when/i }));
    expect(container.querySelector('th[aria-sort="ascending"]')).not.toBeNull();
    const reversed = shiftRows(table)[0];
    if (reversed === undefined) throw new Error('no shift rows rendered');
    expect(within(reversed).queryByText(/^21 Jun 2026,/)).toBeNull();
    expect(within(reversed).getByText(/^15 Jun 2026,/)).toBeTruthy();
  });

  it('refuses to answer when the API says there is no stored history', async () => {
    serve(
      report({
        shifts: [],
        refusals: [],
        basis:
          'Case case-1 has no stored timeline, no evidence records and no audit entries, so no behavioural claim can be supported.',
      }),
    );
    render(<BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />);

    expect(await screen.findByText('No stored history to analyse')).toBeTruthy();
    expect(
      screen.getAllByText(/no behavioural claim can be supported/).length,
    ).toBeGreaterThan(0);
  });

  it('surfaces an API error rather than rendering an empty panel', async () => {
    installFetch(() => jsonResponse({ detail: 'Case not found' }, { status: 404 }));
    render(<BehaviouralShifts caseId="case-1" onSelectEvidence={() => {}} />);

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: /retry/i })).toBeTruthy();
  });
});
