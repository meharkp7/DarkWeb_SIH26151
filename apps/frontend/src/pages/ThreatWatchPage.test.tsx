import { describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ThreatWatchPage, severity } from './ThreatWatchPage';
import type { LiveActivity } from '../api/types';
import { installFetch, jsonResponse } from '../test/mockFetch';

function event(overrides: Partial<LiveActivity> & Pick<LiveActivity, 'seq' | 'action'>): LiveActivity {
  return {
    occurred_at: '2026-01-05T10:00:00Z',
    entity_type: null,
    entity_id: null,
    case_id: null,
    payload: {},
    ...overrides,
  };
}

const EVENTS: LiveActivity[] = [
  event({
    seq: 5,
    action: 'alert.critical',
    case_id: 'case-1',
    payload: { message: 'Hidden service exposed', case_name: 'Nightfall', severity: 'critical' },
  }),
  event({
    seq: 4,
    action: 'evidence.added',
    case_id: 'case-1',
    payload: { message: 'Screenshot archived', case_name: 'Nightfall', network: 'onion' },
  }),
  event({
    seq: 3,
    action: 'relationship.linked',
    case_id: 'case-2',
    payload: { message: 'Actor linked to service', case_name: 'Dawnbreak' },
  }),
  event({
    seq: 2,
    action: 'assessment.scored',
    payload: { message: 'Confidence revised' },
  }),
  event({
    seq: 1,
    // Deliberately outside every known prefix: it must land in "Other" rather
    // than being attributed to whichever team happened to be listed first.
    action: 'quantum.entangled',
    payload: { message: 'Unrecognised subsystem event' },
  }),
];

function stubApi(events: readonly LiveActivity[] = EVENTS) {
  return installFetch(async (input) => {
    const url = String(input);
    if (url.includes('/v1/threat-watch/events')) return jsonResponse(events);
    if (url.includes('/v1/dashboard/summary')) return jsonResponse({ activity: [] });
    return jsonResponse({});
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ThreatWatchPage />
    </MemoryRouter>,
  );
}

describe('severity', () => {
  it('prefers the recorded severity over the action name', () => {
    // A producer that sets `severity: "critical"` on a `threat.*` action has
    // said something more specific than the prefix rule can infer.
    expect(severity(event({ seq: 1, action: 'threat.something', payload: { severity: 'critical' } }))).toBe(
      'critical',
    );
  });

  it('falls back to the action prefix when no severity was recorded', () => {
    expect(severity(event({ seq: 1, action: 'alert.anything' }))).toBe('critical');
    expect(severity(event({ seq: 1, action: 'threat.anything' }))).toBe('elevated');
    expect(severity(event({ seq: 1, action: 'evidence.added' }))).toBe('normal');
  });
});

describe('ThreatWatchPage', () => {
  it('reads the durable stream through the shared API client', async () => {
    const fetchMock = stubApi();
    renderPage();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.includes('/v1/threat-watch/events'))).toBe(true);
  });

  it('lists recorded events rather than showing an empty stream', async () => {
    stubApi();
    renderPage();

    expect(await screen.findByText('Hidden service exposed')).toBeInTheDocument();
    expect(screen.getByText('Screenshot archived')).toBeInTheDocument();
  });

  it('counts elevated events separately from routine ones', async () => {
    stubApi();
    renderPage();

    await screen.findByText('Hidden service exposed');
    // `alert.critical` is the only critical; `relationship.linked` is routine,
    // so the elevated count must not silently include it. The strip must not
    // collapse the two.
    const critical = screen.getByRole('button', { name: /Critical/ });
    expect(within(critical).getByText('1')).toBeInTheDocument();
    const elevated = screen.getByRole('button', { name: /Elevated/ });
    expect(within(elevated).getByText('1')).toBeInTheDocument();
  });

  it('filters to a category from the address bar', async () => {
    stubApi();
    renderPage();

    await screen.findByText('Hidden service exposed');
    // Scoped to the category group: the event rows carry the same word in
    // their metadata, so an unscoped name matches both.
    const group = screen.getByRole('group', { name: 'Filter by category' });
    await userEvent.click(within(group).getByRole('button', { name: /Evidence/ }));

    // `evidence.*` only: the alert, the relationship and the assessment rows
    // must all be gone, and the unrecognised action must not be swept in.
    await waitFor(() => expect(screen.queryByText('Hidden service exposed')).not.toBeInTheDocument());
    expect(screen.getByText('Screenshot archived')).toBeInTheDocument();
    expect(screen.queryByText('Unrecognised subsystem event')).not.toBeInTheDocument();
  });

  it('files an action matching no known prefix under Other, not a named team', async () => {
    stubApi();
    renderPage();

    await screen.findByText('Unrecognised subsystem event');
    const group = screen.getByRole('group', { name: 'Filter by category' });
    await userEvent.click(within(group).getByRole('button', { name: /Other/ }));

    await waitFor(() => expect(screen.getByText('Unrecognised subsystem event')).toBeInTheDocument());
    expect(screen.queryByText('Hidden service exposed')).not.toBeInTheDocument();
  });

  it('opens a detail inspector naming the action, case and recorded payload', async () => {
    stubApi();
    renderPage();

    await userEvent.click(await screen.findByText('Hidden service exposed'));

    const rail = await screen.findByRole('complementary', { name: 'Hidden service exposed' });
    // The action appears as the rail subtitle and again as a fact; the fact is
    // the assertion that matters, so it is the one named here.
    expect(within(rail).getAllByText('alert.critical').length).toBeGreaterThan(0);
    expect(within(rail).getByText('Nightfall')).toBeInTheDocument();
    // The payload tab is what makes the event auditable rather than a headline.
    expect(within(rail).getByText('critical')).toBeInTheDocument();
  });

  it('flags an event that carried a prompt-injection indicator', async () => {
    stubApi([
      event({
        seq: 9,
        action: 'evidence.added',
        payload: { message: 'Untrusted content ingested', flagged: true },
      }),
    ]);
    renderPage();

    await userEvent.click(await screen.findByText('Untrusted content ingested'));

    const rail = await screen.findByRole('complementary');
    expect(within(rail).getByText(/prompt-injection indicator/)).toBeInTheDocument();
  });

  it('narrows the stream to one case from the selector', async () => {
    stubApi();
    renderPage();

    const selector = await screen.findByLabelText('Filter by case');
    await userEvent.selectOptions(selector, 'case-2');

    await waitFor(() => expect(screen.queryByText('Hidden service exposed')).not.toBeInTheDocument());
    expect(screen.getByText('Actor linked to service')).toBeInTheDocument();
  });

  it('says so when the recorded stream cannot be read', async () => {
    // Previously this failure was swallowed, so a misconfigured base URL looked
    // identical to a feed with no events in it.
    installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/v1/threat-watch/events')) return jsonResponse({}, { status: 404 });
      if (url.includes('/v1/dashboard/summary')) return jsonResponse({ activity: [] });
      return jsonResponse({});
    });
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be read/);
  });

  it('distinguishes a genuinely empty feed from a filter that matched nothing', async () => {
    stubApi([]);
    renderPage();

    expect(
      await screen.findByText(/No events have been recorded yet/),
    ).toBeInTheDocument();
  });

  it('does not issue a request the page has no need for', async () => {
    const fetchMock = stubApi();
    renderPage();

    await screen.findByText('Hidden service exposed');
    const watchCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).includes('/v1/threat-watch/events'),
    );
    // One durable read. Re-fetching on every render is what made this page
    // feel slow; the websocket carries the live edge instead.
    expect(watchCalls).toHaveLength(1);
  });
});
