import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { PersonasPage } from './PersonasPage';
import type { PersonaLinkage, PersonaLinkageCounts } from '../api/types';
import { installFetch, jsonResponse } from '../test/mockFetch';

/**
 * These assertions are about the one distinction the surface is built around:
 * a model score and an analyst decision are different things, and a `proposed`
 * row must not be readable as a finding.
 */

function linkage(overrides: Partial<PersonaLinkage> & Pick<PersonaLinkage, 'linkage_id' | 'candidate_handle'>): PersonaLinkage {
  return {
    actor_id: 'actor-1',
    actor_handle: 'shadow_vend',
    method: 'stylometry',
    score: 0.42,
    status: 'proposed',
    aligned_features: ['punctuation_ratio', 'mean_word_length'],
    apart_features: ['uppercase_ratio'],
    contested_features: ['char_count', 'word_count', 'sentence_count', 'digit_ratio'],
    limitations: [
      'Stylometry reads only the text each side chose to publish.',
      'A translation moves these features with no change of author.',
    ],
    case_id: 'case-1',
    case_name: 'Night Market Escrow',
    adjudicated_by: null,
    adjudicated_by_name: null,
    adjudicated_at: null,
    rationale: null,
    created_at: '2026-09-01T09:00:00Z',
    metadata: {},
    analyst_recorded: false,
    ...overrides,
  };
}

const PROPOSAL = linkage({ linkage_id: 'link-1', candidate_handle: 'quiet_mule_77' });

const CONFIRMED = linkage({
  linkage_id: 'link-2',
  candidate_handle: 'silk_route_9',
  status: 'confirmed',
  score: 0.88,
  analyst_recorded: true,
  adjudicated_by: 'user-1',
  adjudicated_by_name: 'Rhea Singh',
  adjudicated_at: '2026-09-10T11:30:00Z',
  rationale: 'Shared vendor list and payment address.',
  created_at: '2026-08-12T08:00:00Z',
});

const REJECTED = linkage({
  linkage_id: 'link-3',
  candidate_handle: 'bot_relist',
  status: 'rejected',
  score: 0.91,
  analyst_recorded: true,
  adjudicated_by: 'user-2',
  adjudicated_by_name: 'Tereza Novak',
  adjudicated_at: '2026-09-02T14:00:00Z',
  rationale: 'Both handles are the same relisting bot.',
  created_at: '2026-08-20T08:00:00Z',
});

const SUMMARY: PersonaLinkageCounts = {
  total: 3,
  by_status: { proposed: 1, confirmed: 1, rejected: 1 },
  by_method: { stylometry: 3, behavioural: 0, infrastructure: 0, attribution: 0, manual: 0 },
  proposed: 1,
  confirmed: 1,
  rejected: 1,
  adjudicated: 2,
  confirmed_total: 1,
  rejected_total: 1,
  confirmed_low_score: 0,
  rejected_high_score: 1,
  score_threshold: 0.75,
  gap: null,
};

const TEAM = {
  members: [
    {
      user_id: 'user-1',
      email: 'r.singh@aegis.intel',
      display_name: 'Rhea Singh',
      role: 'analyst',
      permissions: [],
      is_active: true,
      last_login_at: null,
      assigned_cases: 1,
    },
  ],
  roles: ['analyst'],
};

interface StubOptions {
  readonly rows: readonly PersonaLinkage[];
  readonly summary?: PersonaLinkageCounts;
  /** Rows returned by the detail endpoint, keyed by linkage id. */
  readonly details?: Readonly<Record<string, PersonaLinkage>>;
  /** Omit the team roster, so the adjudication control reports it cannot load. */
  readonly withoutTeam?: boolean;
}

/**
 * Serves the three reads the page makes plus the adjudication write, and applies
 * the ruling to the served rows so the refetch the write triggers returns the
 * updated record. Without that, a page that updated its own state would pass.
 */
function installApi({ rows, summary = SUMMARY, details, withoutTeam = false }: StubOptions) {
  const served = rows.map((row) => ({ ...row }));
  const requests: string[] = [];

  installFetch(async (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : String(input);
    requests.push(url);
    const path = url.split('?')[0] ?? url;
    const method = init?.method ?? 'GET';

    if (path.endsWith('/v1/admin/team')) {
      if (withoutTeam) return jsonResponse({ detail: 'forbidden' }, { status: 403 });
      return jsonResponse(TEAM);
    }
    if (path.endsWith('/v1/personas/linkages/summary')) return jsonResponse(summary);
    if (path.endsWith('/v1/personas/linkages')) {
      return jsonResponse(
        method === 'POST'
          ? { ...PROPOSAL, linkage_id: 'link-new' }
          : served,
      );
    }
    const detailMatch = /\/v1\/personas\/linkages\/([^/]+)(\/adjudicate)?$/.exec(path);
    if (detailMatch) {
      const id = detailMatch[1] ?? '';
      if (detailMatch[2]) {
        const payload = JSON.parse(String(init?.body ?? '{}')) as {
          status: 'confirmed' | 'rejected';
          analyst_id: string;
          rationale: string;
        };
        const target = served.find((row) => row.linkage_id === id);
        if (!target) return jsonResponse({ detail: 'Persona linkage not found' }, { status: 404 });
        const analyst = TEAM.members.find((member) => member.user_id === payload.analyst_id);
        const stored: PersonaLinkage = {
          ...target,
          status: payload.status,
          analyst_recorded: true,
          adjudicated_by: payload.analyst_id,
          adjudicated_by_name: analyst?.display_name ?? 'Unknown',
          adjudicated_at: '2026-09-29T12:00:00Z',
          rationale: payload.rationale,
        };
        const index = served.indexOf(target);
        served[index] = stored;
        return jsonResponse({
          linkage: stored,
          previous_status: target.status,
          previous_rationale: null,
          previous_adjudicator: null,
          audit_seq: 9001,
        });
      }
      const base = served.find((row) => row.linkage_id === id) ?? PROPOSAL;
      return jsonResponse({
        ...(details?.[id] ?? base),
        feature_agreement: {
          punctuation_ratio: 0.98,
          mean_word_length: 0.93,
          uppercase_ratio: 0.41,
          char_count: 1,
          word_count: 1,
          sentence_count: 1,
          digit_ratio: 1,
        },
        scorer: 'aegis.stylometry.features.stylometric_similarity',
      });
    }
    return jsonResponse({ detail: `unstubbed ${url}` }, { status: 404 });
  });

  return { requests, served };
}

function renderPage(entry = '/personas') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <PersonasPage />
    </MemoryRouter>,
  );
}

async function awaitRegister() {
  await screen.findByRole('button', { name: /quiet_mule_77/ });
}

describe('PersonasPage', () => {
  it('shows the three feature lists as counts and the decision as a separate column', async () => {
    installApi({ rows: [PROPOSAL, CONFIRMED, REJECTED] });
    renderPage();

    await awaitRegister();
    const table = screen.getByRole('table');
    const header = within(table).getAllByRole('columnheader').map((cell) => cell.textContent);
    expect(header.join(' ')).toMatch(/Candidate/);
    expect(header.join(' ')).toMatch(/Actor/);
    expect(header.join(' ')).toMatch(/Method/);
    expect(header.join(' ')).toMatch(/Score/);
    expect(header.join(' ')).toMatch(/Status/);
    expect(header.join(' ')).toMatch(/Aligned/);
    expect(header.join(' ')).toMatch(/Apart/);
    expect(header.join(' ')).toMatch(/Contested/);
    expect(header.join(' ')).toMatch(/Adjudicated/);
    expect(header.join(' ')).toMatch(/Case/);

    const proposalRow = screen.getByRole('button', { name: /quiet_mule_77/ }).closest('tr');
    expect(within(proposalRow!).getByText('proposed')).toBeInTheDocument();
    // 2 aligned, 1 apart, 4 contested — the counts are the server's.
    const cells = within(proposalRow!).getAllByRole('cell');
    expect(cells[5]).toHaveTextContent('2');
    expect(cells[6]).toHaveTextContent('1');
    expect(cells[7]).toHaveTextContent('4');
    // Nobody has ruled, so the adjudicator cell is an em dash, not a name.
    expect(cells[8]).toHaveTextContent('—');

    const confirmedRow = screen.getByRole('button', { name: /silk_route_9/ }).closest('tr');
    expect(within(confirmedRow!).getByText('confirmed')).toBeInTheDocument();
    expect(within(confirmedRow!).getByText('Rhea Singh')).toBeInTheDocument();
  });

  it('never lets a proposal read as a finding', async () => {
    installApi({ rows: [PROPOSAL, CONFIRMED] });
    renderPage();
    await awaitRegister();

    // The word, the mark and the shape: a proposal is dashed with a hollow "?"...
    const proposalRow = screen.getByRole('button', { name: /quiet_mule_77/ }).closest('tr')!;
    const proposalPill = within(proposalRow).getByText('proposed').closest('.per-status')!;
    expect(proposalPill.className).toContain('per-status--proposed');
    expect(proposalPill.querySelector('.per-status__mark')?.textContent).toBe('?');
    const confirmedRow = screen.getByRole('button', { name: /silk_route_9/ }).closest('tr')!;
    const confirmedPill = within(confirmedRow).getByText('confirmed').closest('.per-status')!;
    expect(confirmedPill.querySelector('.per-status__mark')?.textContent).toBe('✓');

    // ...and its score says so in words, not only in colour.
    expect(screen.getAllByText(/not reviewed/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Rhea Singh confirmed it/).length).toBeGreaterThan(0);
  });

  it('leads with the observed error rate, against a stated threshold', async () => {
    installApi({ rows: [PROPOSAL, CONFIRMED, REJECTED] });
    renderPage();
    await awaitRegister();

    expect(screen.getByText(/against the 0\.75 line/)).toBeInTheDocument();
    // One rejection the scorer ranked high: the model's false positives, counted
    // from the decision rather than reported by the scorer.
    const falsePositives = screen.getByText(/Rejected despite a high score/).closest('li')!;
    expect(falsePositives).toHaveTextContent('1 of 1');
    expect(falsePositives).toHaveTextContent('false positives');
    // Zero confirmations below the line, over a denominator of one — not a
    // headline rate over nothing.
    const falseNegatives = screen.getByText(/Confirmed despite a low score/).closest('li')!;
    expect(falseNegatives).toHaveTextContent('0 of 1');
  });

  it('shows the feature names and the full limitations when a row is expanded', async () => {
    installApi({ rows: [PROPOSAL] });
    renderPage();
    await awaitRegister();

    await userEvent.click(screen.getByRole('button', { name: /quiet_mule_77/ }));

    // Scoped to the row's own expansion: the inspector rail shows the same
    // component for the same record, and both must agree.
    await waitFor(() =>
      expect(document.querySelector<HTMLElement>('.per-table__expansion')).not.toBeNull(),
    );
    const scope = document.querySelector<HTMLElement>('.per-table__expansion')!;

    const aligned = within(scope).getByRole('region', { name: 'Aligned features' });
    expect(within(aligned).getByText('punctuation_ratio')).toBeInTheDocument();
    expect(within(aligned).getByText('mean_word_length')).toBeInTheDocument();

    const apart = within(scope).getByRole('region', { name: 'Apart features' });
    expect(within(apart).getByText('uppercase_ratio')).toBeInTheDocument();

    const contested = within(scope).getByRole('region', { name: 'Contested features' });
    expect(within(contested).getByText('digit_ratio')).toBeInTheDocument();

    // Limitations in full, not summarised: both lines, verbatim.
    expect(
      within(scope).getByText('Stylometry reads only the text each side chose to publish.'),
    ).toBeInTheDocument();
    expect(
      within(scope).getByText('A translation moves these features with no change of author.'),
    ).toBeInTheDocument();
  });

  it('requires a rationale, then takes the row from the server response', async () => {
    const { served } = installApi({ rows: [PROPOSAL] });
    renderPage();
    await awaitRegister();

    await userEvent.click(screen.getByRole('button', { name: /quiet_mule_77/ }));
    // Scoped to the expanded row: the rail renders the same control for the
    // same record, and one of them is enough to drive.
    await waitFor(() =>
      expect(document.querySelector<HTMLElement>('.per-table__expansion')).not.toBeNull(),
    );
    const scope = document.querySelector<HTMLElement>('.per-table__expansion')!;
    const record = within(scope).getByRole('button', { name: 'Record ruling' });
    // No decision and no rationale: nothing to record.
    expect(record).toBeDisabled();

    await userEvent.click(within(scope).getByRole('radio', { name: /Confirm/ }));
    // A decision alone is still not enough — a ruling with no stated reason is
    // indistinguishable from a model output.
    expect(record).toBeDisabled();

    await userEvent.type(
      within(scope).getByPlaceholderText(/A decision with no stated reason/),
      'Same vendor list, same payment address, and the PGP key is reused.',
    );
    expect(record).toBeEnabled();

    await userEvent.click(record);

    // The row now reads confirmed, attributed to the analyst the server named.
    await waitFor(() => {
      const cell = screen.getByRole('button', { name: /quiet_mule_77/ }).closest('tr')!;
      expect(within(cell).getByText('confirmed')).toBeInTheDocument();
      expect(within(cell).getByText('Rhea Singh')).toBeInTheDocument();
    });
    // And the change came from the server's copy, not from local optimism.
    expect(served[0]?.status).toBe('confirmed');
    expect(served[0]?.rationale).toContain('PGP key');
  });

  it('drives the timeline from the address bar', async () => {
    const { requests } = installApi({ rows: [PROPOSAL] });
    renderPage('/personas?from=2026-08-01&until=2026-09-01&status=proposed');
    await awaitRegister();

    // The window went to the server as `since`/`until` on the proposal date, and
    // the same filter set was applied to the summary beside it.
    const linkageRequest = requests.find((url) => url.includes('/v1/personas/linkages?'));
    expect(linkageRequest).toContain('since=2026-08-01');
    expect(linkageRequest).toContain('until=2026-09-01T23%3A59%3A59Z');
    expect(linkageRequest).toContain('status=proposed');
    const summaryRequest = requests.find((url) => url.includes('/linkages/summary?'));
    expect(summaryRequest).toContain('since=2026-08-01');

    // A date change rewrites the URL rather than the component's state.
    await userEvent.clear(screen.getByLabelText(/Proposed from/));
    await userEvent.type(screen.getByLabelText(/Proposed from/), '2026-08-05');
    await waitFor(() => {
      expect(
        requests.some((url) => url.includes('since=2026-08-05')),
      ).toBe(true);
    });
  });

  it('surfaces the refusal when a sample is too short to score', async () => {
    installFetch(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : String(input);
      const path = url.split('?')[0] ?? url;
      const method = init?.method ?? 'GET';
      if (path.endsWith('/v1/admin/team')) return jsonResponse(TEAM);
      if (path.endsWith('/v1/personas/linkages/summary')) return jsonResponse(SUMMARY);
      if (path.endsWith('/v1/personas/linkages')) {
        if (method === 'POST') {
          return jsonResponse(
            {
              detail:
                'The candidate text sample has 3 words. Stylometric analysis needs at least 120 words per side before function-word, punctuation and entropy features are stable, so no score was computed.',
            },
            { status: 422 },
          );
        }
        return jsonResponse([PROPOSAL]);
      }
      return jsonResponse({ detail: `unstubbed ${url}` }, { status: 404 });
    });
    renderPage('/personas?actor=actor-1');
    await awaitRegister();

    await userEvent.click(screen.getByRole('button', { name: 'Propose linkage' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByPlaceholderText(/handle to be linked/), 'new_handle');
    await userEvent.type(within(dialog).getByPlaceholderText(/Posts already attributed/), 'one two three');
    await userEvent.type(within(dialog).getByPlaceholderText(/Posts collected from the candidate/), 'four five six');

    // The form refuses the submission locally, because three words is not a sample.
    expect(within(dialog).getByRole('button', { name: 'Propose linkage' })).toBeDisabled();
    expect(within(dialog).getByText(/Each side needs at least 120 words/)).toBeInTheDocument();

    // And the server's own refusal, when it is asked, is shown rather than
    // swallowed — "could not be analysed" must not look like "found nothing".
    //
    // Set the long samples with `fireEvent.change`, not 1800 keystrokes.
    // `userEvent.type` re-renders the component per character, and this
    // dialog sits inside a 629-line page, so `'lorem '.repeat(150)` on each
    // side is 1800 full re-renders to express one fact: the field holds at
    // least 120 words. It cost 2.8s on a laptop and 5.0s on a 2-vCPU Linux
    // runner, which is 8ms over vitest's 5s default — green locally, red on
    // CI, and indistinguishable from a real regression in the log.
    //
    // `fireEvent.change` is also the more honest simulation: nobody types 150
    // words, they paste them. The short realistic typing above stays on
    // `userEvent`, because per-keystroke behaviour is what that part is
    // testing.
    fireEvent.change(within(dialog).getByPlaceholderText(/Posts already attributed/), {
      target: { value: 'lorem '.repeat(150) },
    });
    fireEvent.change(within(dialog).getByPlaceholderText(/Posts collected from the candidate/), {
      target: { value: 'ipsum '.repeat(150) },
    });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Propose linkage' }));
    expect(await within(dialog).findByText(/no score was computed/)).toBeInTheDocument();
  });
});
