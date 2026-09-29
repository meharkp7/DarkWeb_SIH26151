import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CaseExportMenu } from './CaseExportMenu';
import { setSessionToken } from '../api/client';
import type { CaseQueueEntry } from '../api/types';
import { installFetch, jsonResponse } from '../test/mockFetch';

/**
 * The export popover replaced the `/reports` page.
 *
 * These assertions pin the things that were easy to get wrong when the choice
 * moved inline: that the format list still matches what the export endpoint
 * actually accepts, that each format says what it contains rather than just
 * naming itself, that the popover behaves like a popover (Escape closes, focus
 * comes back to the trigger), and — most importantly — that a failed download
 * leaves the analyst in the popover instead of dismissing the thing they were
 * using and hiding the error.
 */

const CASE_A: CaseQueueEntry = {
  case_id: 'case-aaa',
  name: 'Alpha Breach',
  status: 'active',
  priority: 'high',
  severity: 'critical',
  tags: ['financial'],
  assigned_to: null,
  sla_due_at: null,
  sla_overdue: false,
  sla_state: 'none',
  queue_score: 62,
  queue_reason: 'High priority',
  reasons: [],
  counts: {
    evidence: 3, entities: 2, relationships: 1, assessments: 0,
    contradictions: 0, recent_evidence: 1,
  },
  last_activity: null,
  attribution: null,
} as unknown as CaseQueueEntry;

const CASE_B = { ...CASE_A, case_id: 'case-bbb', name: 'Beta Leak' } as CaseQueueEntry;

/** Formats the API accepts — mirrors the union on `api.reportExportUrl`. */
const SUPPORTED_FORMATS = [
  { value: 'pdf', name: /PDF briefing/ },
  { value: 'json', name: /JSON structured/ },
  { value: 'csv', name: /CSV ledger/ },
  { value: 'stix', name: /STIX 2\.1 exchange/ },
] as const;

function installCasesFetch(overrides: { readonly handler?: (input: unknown) => Promise<Response> | Response } = {}): void {
  if (overrides.handler !== undefined) {
    installFetch(overrides.handler);
    return;
  }
  installFetch(async (input) => {
    if (String(input).includes('/api/v1/dashboard/cases')) return jsonResponse([CASE_A, CASE_B]);
    throw new Error(`unexpected request: ${String(input)}`);
  });
}

function renderMenu(caseId = CASE_A.case_id) {
  setSessionToken('export-menu-token', Date.now() + 3_600_000);
  return render(<CaseExportMenu caseId={caseId} />);
}

describe('CaseExportMenu', () => {
  it('opens on click and reports its expanded state', async () => {
    const user = userEvent.setup();
    installCasesFetch();
    renderMenu();

    const trigger = screen.getByRole('button', { name: /Export/ });
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('dialog', { name: 'Export investigation report' })).not.toBeInTheDocument();

    await user.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('dialog', { name: 'Export investigation report' })).toBeInTheDocument();
  });

  it('lists every format the export endpoint accepts, and no others', async () => {
    const user = userEvent.setup();
    installCasesFetch();
    renderMenu();
    await user.click(screen.getByRole('button', { name: /Export/ }));

    const group = screen.getByRole('radiogroup', { name: 'Export format' });
    const radios = within(group).getAllByRole('radio');

    // The list is derived from the route's format union, so a format added or
    // dropped on the API shows up here as a failure rather than as a 422.
    expect(radios).toHaveLength(SUPPORTED_FORMATS.length);
    expect(radios.map((radio) => (radio as HTMLInputElement).value).sort()).toEqual(
      SUPPORTED_FORMATS.map((format) => format.value).sort(),
    );

    for (const format of SUPPORTED_FORMATS) {
      expect(within(group).getByRole('radio', { name: format.name })).toBeInTheDocument();
    }
  });

  it('describes what each format contains rather than only naming it', async () => {
    const user = userEvent.setup();
    installCasesFetch();
    renderMenu();
    await user.click(screen.getByRole('button', { name: /Export/ }));

    const group = screen.getByRole('radiogroup', { name: 'Export format' });
    for (const hint of [
      'Formatted analyst brief with evidence citations.',
      'Machine-readable evidence and provenance package.',
      'Flat evidence matrix, one row per cited claim.',
      'Structured threat-intelligence bundle for sharing.',
    ]) {
      expect(within(group).getByText(hint)).toBeInTheDocument();
    }
  });

  it('defaults the case selector to the case the menu was opened from', async () => {
    const user = userEvent.setup();
    installCasesFetch();
    renderMenu(CASE_B.case_id);
    await user.click(screen.getByRole('button', { name: /Export/ }));

    const select = screen.getByLabelText('Case') as HTMLSelectElement;
    await waitFor(() => {
      expect(within(select).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)).toEqual([
        '__all__',
        CASE_A.case_id,
        CASE_B.case_id,
      ]);
    });
    expect(select.value).toBe(CASE_B.case_id);
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const user = userEvent.setup();
    installCasesFetch();
    renderMenu();

    const trigger = screen.getByRole('button', { name: /Export/ });
    await user.click(trigger);
    expect(screen.getByRole('dialog', { name: 'Export investigation report' })).toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: 'Export investigation report' })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    // Focus must not be dropped at the document root: the analyst has to be
    // able to carry on tabbing from where they were.
    expect(trigger).toHaveFocus();
  });

  it('keeps the popover open and shows the error when the download fails', async () => {
    const user = userEvent.setup();
    installCasesFetch({
      handler: async (input) => {
        const url = String(input);
        if (url.includes('/api/v1/dashboard/cases')) return jsonResponse([CASE_A, CASE_B]);
        if (url.includes('/reports/export')) {
          return jsonResponse({ detail: 'report builder unavailable' }, { status: 503, statusText: 'Service Unavailable' });
        }
        throw new Error(`unexpected request: ${url}`);
      },
    });
    renderMenu();
    await user.click(screen.getByRole('button', { name: /Export/ }));

    await user.click(screen.getByRole('button', { name: 'Export report' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('API 503 — report builder unavailable');
    // The whole point: dismissing the popover would hide the error behind a
    // button the analyst has to find and re-open.
    expect(screen.getByRole('dialog', { name: 'Export investigation report' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export report' })).toBeEnabled();
  });

  it('does not fire a second download while one is in flight', async () => {
    const user = userEvent.setup();
    // A promise the test resolves by hand, so the export stays in flight long
    // enough for the second click to land while the button is disabled.
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetchMock = installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/dashboard/cases')) return jsonResponse([CASE_A, CASE_B]);
      if (url.includes('/reports/export')) {
        await gate;
        return { ok: true, status: 200, blob: async () => new Blob(['{}']) } as unknown as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    renderMenu();
    await user.click(screen.getByRole('button', { name: /Export/ }));

    const action = screen.getByRole('button', { name: 'Export report' });
    await user.click(action);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preparing…' })).toBeDisabled();
    });

    const exportCalls = () =>
      fetchMock.mock.calls.filter((call) => String(call[0]).includes('/reports/export')).length;
    expect(exportCalls()).toBe(1);

    // A second click on the now-disabled control must not queue a second
    // download: two identical files in the downloads folder is a real bug.
    await user.click(screen.getByRole('button', { name: 'Preparing…' }));
    expect(exportCalls()).toBe(1);

    release();
  });

  it('exports the selected case as a file and closes on success', async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });

    const fetchMock = installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/api/v1/dashboard/cases')) return jsonResponse([CASE_A, CASE_B]);
      if (url.includes('/reports/export')) {
        return { ok: true, status: 200, blob: async () => new Blob(['report']) } as unknown as Response;
      }
      throw new Error(`unexpected request: ${url}`);
    });
    renderMenu();
    await user.click(screen.getByRole('button', { name: /Export/ }));

    const group = screen.getByRole('radiogroup', { name: 'Export format' });
    await user.click(within(group).getByRole('radio', { name: /CSV ledger/ }));
    await user.click(screen.getByRole('button', { name: 'Export report' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Export investigation report' })).not.toBeInTheDocument();
    });

    const exportCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/reports/export'));
    expect(exportCall).toBeDefined();
    // The API needs an Authorization header, which a plain link navigation
    // cannot set — the request must be a credentialed fetch.
    const init = (exportCall as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer export-menu-token');
    expect(String((exportCall as [string, RequestInit])[0])).toContain('format=csv');
    expect(createObjectURL).toHaveBeenCalled();
  });
});
