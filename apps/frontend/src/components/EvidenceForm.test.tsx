import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EvidenceForm } from './EvidenceForm';
import { installFetch, jsonResponse } from '../test/mockFetch';

const CASE_ID = 'case_00000000000000000000000000000001';
const EVIDENCE_ID = 'ev_00000000000000000000000000000001';
const SHA256 = 'a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0';

/**
 * Fill the form with a complete, valid record.
 *
 * `fireEvent.change` rather than `userEvent.type`, and the reason is cost.
 * These are request-shape tests, and the six fields total ~163 characters.
 * `userEvent.type` re-renders the form on every keystroke and awaits a
 * `setTimeout(0)` between them, so the same assertion cost 633ms in
 * isolation and then timed out at vitest's 5s default under the full suite on
 * a 2-vCPU Linux runner — failing about two runs in three, and only on CI.
 * Being first in the file's order, it was also the test that paid for
 * everyone else's headroom.
 *
 * `change` fires the same handler a real edit does, so the value still has to
 * travel through the form's state to reach the POST body — which is the
 * entire point of these tests. Per-keystroke behaviour is not what is under
 * test, so simulating it bought nothing except the flake.
 */
async function fillEveryField(): Promise<void> {
  const fields: ReadonlyArray<readonly [RegExp, string]> = [
    [/Source ID/, 'src_00000000000000000000000000000001'],
    [/Raw artifact URI/, 's3://aegis/evidence/item.json'],
    [/SHA-256/, SHA256],
    [/Collector name/, 'synthetic'],
    [/Collector version/, '0.1.0'],
    [/Independence group/, 'platform:forum_alpha'],
  ];
  for (const [label, value] of fields) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
}

/**
 * Regression guard for the historic `case_id` bug: the form used to build its
 * create payload without `case_id`, so evidence ingested "from" a case landed
 * unassigned and never appeared in that case's workspace. Submitting with a
 * selected case must send `case_id` on the wire.
 */
describe('EvidenceForm', () => {
  it('includes case_id in the POST body when a case is selected', async () => {
    const user = userEvent.setup();
    const fetchMock = installFetch(async () =>
      jsonResponse({
        evidence_id: EVIDENCE_ID,
        case_id: CASE_ID,
        source_id: 'src_00000000000000000000000000000001',
        source_type: 'synthetic',
        observed_at: null,
        collected_at: '2026-09-29T12:00:00.000Z',
        entity_type: null,
        raw_artifact_uri: 's3://aegis/evidence/item.json',
        sha256: SHA256,
        collector_name: 'synthetic',
        collector_version: '0.1.0',
        source_reliability: 0.5,
        independence_group: 'platform:forum_alpha',
        metadata: {},
        artifact_id: null,
        created_at: '2026-09-29T12:00:00.000Z',
      }),
    );
    const onCreated = vi.fn();

    render(<EvidenceForm caseId={CASE_ID} onCreated={onCreated} />);
    await fillEveryField();

    await user.click(screen.getByRole('button', { name: 'Create evidence' }));

    // The success status only renders after the POST resolves — waiting for it
    // guarantees the request has been made without a custom waitFor timeout.
    expect(await screen.findByRole('status')).toHaveTextContent(`Evidence created: ${EVIDENCE_ID}`);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/evidence');
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.case_id).toBe(CASE_ID);
    expect(body.source_id).toBe('src_00000000000000000000000000000001');
    expect(body.sha256).toBe(SHA256);
    expect(body.source_reliability).toBe(0.5);
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ evidence_id: EVIDENCE_ID }));
  });

  it('sends case_id null for standalone (case-less) intake', async () => {
    const user = userEvent.setup();
    const fetchMock = installFetch(async () => jsonResponse({ evidence_id: EVIDENCE_ID }));

    render(<EvidenceForm caseId={null} onCreated={vi.fn()} />);
    expect(screen.queryByText(/Attaching to case/)).not.toBeInTheDocument();

    await fillEveryField();

    await user.click(screen.getByRole('button', { name: 'Create evidence' }));
    await screen.findByRole('status');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).toHaveProperty('case_id', null);
  });

  it('surfaces the server error detail when the POST is rejected', async () => {
    const user = userEvent.setup();
    installFetch(async () =>
      jsonResponse(
        { detail: 'sha256: Duplicate artifact already indexed' },
        { status: 409, statusText: 'Conflict' },
      ),
    );

    render(<EvidenceForm onCreated={vi.fn()} />);
    await fillEveryField();

    await user.click(screen.getByRole('button', { name: 'Create evidence' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('API 409 — sha256: Duplicate artifact already indexed');
  });
});