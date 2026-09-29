import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Sparkline } from '../Sparkline';
import { ActorTrendCell, recencyPhrase, trendDirection } from '../actor/ActorTrendCell';
import { SourceReliabilityStrip } from './SourceReliabilityStrip';
import type { ActorActivitySeries, CollectionStatus } from '../../api/types';
import { installFetch, jsonResponse } from '../../test/mockFetch';

/** A fixed "now" so recency phrases are assertions rather than a race. */
const NOW = Date.parse('2026-09-29T12:00:00Z');

function series(values: number[]): { points: string; allFinite: boolean } {
  const { container } = render(
    <Sparkline values={values} label="test series" width={100} height={30} />,
  );
  const points = container.querySelector('polyline')?.getAttribute('points') ?? '';
  return {
    points,
    allFinite: points
      .split(' ')
      .filter(Boolean)
      .every((pair) => pair.split(',').every((n) => Number.isFinite(Number(n)))),
  };
}

function activity(weekly: number[], cited = 0): ActorActivitySeries {
  return { weekly, start: '2026-07-06', cited };
}

const RISING = [1, 1, 0, 2, 1, 0, 4, 5, 6, 7, 8, 9];

describe('Sparkline geometry', () => {
  // The three shapes a registry series actually takes. None of them may
  // produce a `NaN` coordinate: a polyline with NaN in it renders as nothing at
  // all while still occupying the cell, which reads as a broken chart rather
  // than as an absent one.
  it('draws an all-zero series as a level line, not a broken path', () => {
    const { points, allFinite } = series([0, 0, 0, 0, 0, 0]);
    expect(points).not.toContain('NaN');
    expect(allFinite).toBe(true);
    // Every point on the baseline: the divisor falls back to 1, so the series
    // is drawn rather than collapsing to a division by zero.
    const ys = points.split(' ').map((pair) => Number(pair.split(',')[1]));
    expect(new Set(ys).size).toBe(1);
  });

  it('draws a decreasing series as decreasing, not mirrored', () => {
    const { points, allFinite } = series([5, 4, 3, 2, 1]);
    expect(allFinite).toBe(true);
    const ys = points.split(' ').map((pair) => Number(pair.split(',')[1]));
    // y grows downward in SVG, so a falling series has growing y.
    expect(ys[0]).toBeLessThan(ys[ys.length - 1] as number);
  });

  it('draws a single point without dividing by zero', () => {
    const { container } = render(<Sparkline values={[7]} label="one point" width={60} height={20} />);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(container.querySelector('polyline')).toBeNull();
    expect(container.querySelector('circle')?.getAttribute('cy')).not.toBeNaN();
  });

  it('renders nothing at all for an empty or non-finite series', () => {
    const { container } = render(
      <span>
        <Sparkline values={[]} label="empty" />
        <Sparkline values={[1, Number.NaN, 3]} label="not a number" />
      </span>,
    );
    expect(container.querySelector('svg')).toBeNull();
  });
});

describe('ActorTrendCell', () => {
  it('says so rather than drawing a line when the API returned no series', () => {
    render(
      <ActorTrendCell series={null} lastSeen="2026-09-20T00:00:00Z" handle="h" now={NOW} />,
    );
    expect(screen.getByText('No trend recorded')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('draws nothing for an all-zero series', () => {
    render(
      <ActorTrendCell
        series={activity([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])}
        lastSeen="2026-09-20T00:00:00Z"
        handle="h"
        now={NOW}
      />,
    );
    expect(screen.getByText('No trend recorded')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('draws nothing for a flat series, and still prints its volume', () => {
    render(
      <ActorTrendCell
        series={activity(new Array(12).fill(3), 3)}
        lastSeen="2026-09-20T00:00:00Z"
        handle="h"
        now={NOW}
      />,
    );
    expect(screen.getByText('No trend recorded')).toBeInTheDocument();
    // The total distinguishes "nothing changed" from "nothing was found".
    expect(screen.getByText(/36 sightings in 12w/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('names the period, the direction and the peak for a rising series', () => {
    render(
      <ActorTrendCell
        series={activity(RISING, 4)}
        lastSeen="2026-09-20T00:00:00Z"
        handle="amberlight1supply"
        now={NOW}
      />,
    );
    const label = screen.getByRole('img').getAttribute('aria-label') ?? '';
    expect(label).toContain('amberlight1supply');
    // The period is named from the window the API reported, not asserted as
    // "the last 12 weeks" by the client.
    expect(label).toMatch(/12 weeks from 06 Jul 2026 to 27 Sep\w* 2026/);
    expect(label).toContain('rising');
    expect(label).toContain('peaking at 9');
  });

  it('says sightings are not evidence records, and reports the ledger-backed count', () => {
    render(
      <ActorTrendCell
        series={activity(RISING, 4)}
        lastSeen="2026-09-20T00:00:00Z"
        handle="h"
        now={NOW}
      />,
    );
    const label = screen.getByRole('img').getAttribute('aria-label') ?? '';
    // "44 sightings" read as "44 records" is the false claim this cell exists
    // to prevent, so the ledger-backed subset is named in the description.
    expect(label).toContain('sightings in total');
    expect(label).toContain('4 cite a ledger record');
  });

  it('carries the direction as a word and an arrow, not as a hue alone', () => {
    const { container } = render(
      <ActorTrendCell
        series={activity(RISING)}
        lastSeen="2026-09-20T00:00:00Z"
        handle="h"
        now={NOW}
      />,
    );
    expect(screen.getByText('rising')).toBeInTheDocument();
    expect(container.querySelector('.q-trend__arrow')?.textContent).toBe('↗');
  });

  it('reports a future last-seen as the data error it is', () => {
    expect(recencyPhrase('2026-10-01T00:00:00Z', NOW)).toContain('in the future');
    expect(recencyPhrase(null, NOW)).toBe('never seen');
    expect(recencyPhrase('2026-09-29T00:00:00Z', NOW)).toBe('seen today');
  });

  it('splits the window in half rather than reading its endpoints', () => {
    // Rose, then fell back to where it started. Endpoint comparison would call
    // this flat; half-against-half calls it what it is.
    expect(trendDirection([10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 10])).toBe('level');
    expect(trendDirection([1, 1, 1, 1, 1, 1, 9, 9, 9, 9, 9, 9])).toBe('rising');
    expect(trendDirection([9, 9, 9, 9, 9, 9, 1, 1, 1, 1, 1, 1])).toBe('falling');
  });
});

const STATUS: CollectionStatus = {
  generated_at: '2026-09-29T12:00:00Z',
  sources_total: 6,
  sources_healthy: 4,
  sources_stale: 1,
  sources_never_scanned: 1,
  stale_after_days: 7,
  jobs_last_24h: { completed: 3 },
  jobs_last_24h_total: 3,
  records_last_24h: 12,
  contributing_sources: 4,
  mean_contributing_reliability: 0.71,
  mean_registered_reliability: 0.55,
  independence_groups: 3,
  dominant_independence_group: 'group-alpha',
  dominant_independence_group_size: 4,
  reliability_bands: [
    { band: 'high', min_reliability: 0.7, sources: 2, contributing_sources: 2, records: 900 },
    { band: 'medium', min_reliability: 0.4, sources: 2, contributing_sources: 1, records: 80 },
    { band: 'low', min_reliability: 0, sources: 2, contributing_sources: 1, records: 20 },
  ],
  reliability_basis: 'Reliability is recorded against the source when it was registered.',
  limitations: [],
};

describe('SourceReliabilityStrip', () => {
  it('shows records per band, not just a source count', async () => {
    installFetch(async (input) => {
      if (String(input).includes('/v1/collection/status')) return jsonResponse(STATUS);
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    render(<SourceReliabilityStrip />);

    const bands = await screen.findByRole('list', { name: /reliability band/i });
    const text = bands.textContent ?? '';
    // The record count, not the source count, is the figure that says how much
    // weight is behind a band — 2 sources holding 900 records and 2 sources
    // holding 20 are not the same fact.
    expect(text).toContain('2 sources · 900 records');
    expect(text).toContain('2 sources · 80 records');
    expect(text).toContain('2 sources · 20 records');
    expect(text).toContain('2 of them have produced any');
    expect(text).toContain('1 of them has produced any');
  });

  it('says plainly that the source count overstates the independent observations', async () => {
    installFetch(async () => jsonResponse(STATUS));
    render(<SourceReliabilityStrip />);

    const note = await screen.findByText(/6 registered sources span 3 independence groups/);
    expect(note.textContent).toContain('3 fewer independent observations');
    expect(note.textContent).toContain('The largest group holds 4 of the 6 sources');
  });

  it('separates the mean over contributors from the mean over the register', async () => {
    installFetch(async () => jsonResponse(STATUS));
    render(<SourceReliabilityStrip />);

    expect(await screen.findByText('71%')).toBeInTheDocument();
    expect(screen.getByText('55%')).toBeInTheDocument();
  });

  it('does not claim a source count is an observation count when the groups match', async () => {
    installFetch(async () =>
      jsonResponse({ ...STATUS, independence_groups: 6, dominant_independence_group_size: 1 }),
    );
    render(<SourceReliabilityStrip />);

    expect(await screen.findByText(/Every source sits in a group of its own/)).toBeInTheDocument();
  });

  it('shows nothing about reliability when no source is registered', async () => {
    installFetch(async () => jsonResponse({ ...STATUS, sources_total: 0, reliability_bands: [] }));
    render(<SourceReliabilityStrip />);

    expect(await screen.findByText('No sources registered')).toBeInTheDocument();
  });
});
