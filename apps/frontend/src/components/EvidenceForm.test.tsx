import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EvidenceForm } from './EvidenceForm';
import { installFetch, jsonResponse } from '../test/mockFetch';

const CASE_ID = 'case_00000000000000000000000000000001';
const EVIDENCE_ID = 'ev_00000000000000000000000000000001';
const SHA256 = 'a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0';

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
    await user.type(screen.getByLabelText(/Source ID/), 'src_00000000000000000000000000000001');
    await user.type(screen.getByLabelText(/Raw artifact URI/), 's3://aegis/evidence/item.json');
    await user.type(screen.getByLabelText(/SHA-256/), SHA256);
    await user.type(screen.getByLabelText(/Collector name/), 'synthetic');
    await user.type(screen.getByLabelText(/Collector version/), '0.1.0');
    await user.type(screen.getByLabelText(/Independence group/), 'platform:forum_alpha');

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

    await user.type(screen.getByLabelText(/Source ID/), 'src_00000000000000000000000000000001');
    await user.type(screen.getByLabelText(/Raw artifact URI/), 's3://aegis/evidence/item.json');
    await user.type(screen.getByLabelText(/SHA-256/), SHA256);
    await user.type(screen.getByLabelText(/Collector name/), 'synthetic');
    await user.type(screen.getByLabelText(/Collector version/), '0.1.0');
    await user.type(screen.getByLabelText(/Independence group/), 'platform:forum_alpha');

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
    await user.type(screen.getByLabelText(/Source ID/), 'src_00000000000000000000000000000001');
    await user.type(screen.getByLabelText(/Raw artifact URI/), 's3://aegis/evidence/item.json');
    await user.type(screen.getByLabelText(/SHA-256/), SHA256);
    await user.type(screen.getByLabelText(/Collector name/), 'synthetic');
    await user.type(screen.getByLabelText(/Collector version/), '0.1.0');
    await user.type(screen.getByLabelText(/Independence group/), 'platform:forum_alpha');

    await user.click(screen.getByRole('button', { name: 'Create evidence' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('API 409 — sha256: Duplicate artifact already indexed');
  });
});