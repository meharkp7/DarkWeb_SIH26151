import { describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentButton } from './AgentButton';
import { agentSuggestions, setAgentContext } from './agent-context';
import { installFetch, jsonResponse } from '../test/mockFetch';

function copilotResponse(overrides: Record<string, unknown> = {}) {
  return {
    question: 'q',
    context: null,
    intent: 'evidence_search',
    rule: 'default',
    tools_run: ['search_evidence'],
    evidence_ids: ['e1'],
    flagged_evidence_ids: [],
    claims: [{ text: 'A claim', citations: ['e1'], status: 'supported' }],
    unsupported_claims: [],
    dropped_claims: [],
    text: 'Findings:\nA claim',
    ...overrides,
  };
}

function stubCopilot(body: Record<string, unknown> = copilotResponse()) {
  const calls: string[] = [];
  const bodies: Record<string, unknown>[] = [];
  const mock = installFetch(async (input, init) => {
    const url = String(input);
    if (url.includes('/v1/copilot/query')) {
      calls.push(url);
      if (init?.body !== undefined) bodies.push(JSON.parse(String(init.body)));
      return jsonResponse(body);
    }
    if (url.includes('/v1/dashboard/summary')) return jsonResponse({ activity: [] });
    return jsonResponse({});
  });
  return { mock, calls, bodies };
}

describe('agent-context', () => {
  it('suggests by section, including the sections added after the table', () => {
    // Actors, Infrastructure, Persona Linkage and Collection were absent from
    // the table, so four of the seven top-level destinations silently got the
    // generic pair — the bolted-on feeling the module exists to remove.
    setAgentContext({ place: 'Actors' });
    expect(agentSuggestions({ place: 'Actors' })[0]).not.toBe('What changed recently?');

    setAgentContext({ place: 'Infrastructure' });
    expect(agentSuggestions({ place: 'Infrastructure' })[0]).toMatch(/hidden service/i);

    setAgentContext({ place: 'Persona Linkage' });
    expect(agentSuggestions({ place: 'Persona Linkage' })[0]).toMatch(/persona link/i);

    setAgentContext({ place: 'Collection' });
    expect(agentSuggestions({ place: 'Collection' })[0]).toMatch(/collection run/i);
  });

  it('matches a qualified place back to its section', () => {
    // Pages publish `Infrastructure · findings`, not `Infrastructure`.
    expect(agentSuggestions({ place: 'Infrastructure · findings' })[0]).toMatch(/hidden service/i);
  });

  it('falls back to a generic pair for a genuinely unknown section', () => {
    expect(agentSuggestions({ place: 'Somewhere New' })).toEqual([
      'What changed recently?',
      'Show me the latest activity',
    ]);
  });
});

describe('AgentButton', () => {
  it('sends the case id and the screen as separate fields, never in the question', async () => {
    setAgentContext({ place: 'Operation Nightfall', view: 'assessment', caseId: 'case-1' });
    const { bodies } = stubCopilot();

    render(<AgentButton />);
    await userEvent.click(screen.getByRole('button', { name: /Ask the AEGIS Agent/ }));
    await userEvent.type(screen.getByPlaceholderText(/Ask about this investigation/), 'What changed?');
    await userEvent.click(screen.getByRole('button', { name: '↑' }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      question: 'What changed?',
      case_id: 'case-1',
      context: 'Current investigation: Operation Nightfall — viewing assessment',
    });
    // The grounding must not be concatenated onto the question: the router
    // matches on substrings, so "assessment" in the suffix captured every
    // question typed on that tab.
    expect((bodies[0] as { question: string }).question).not.toContain('Context:');
  });

  it('omits the case id outside an investigation', async () => {
    setAgentContext({ place: 'Command Center' });
    const { bodies } = stubCopilot();

    render(<AgentButton />);
    await userEvent.click(screen.getByRole('button', { name: /Ask the AEGIS Agent/ }));
    await userEvent.type(screen.getByPlaceholderText(/Ask about this investigation/), 'What changed?');
    await userEvent.click(screen.getByRole('button', { name: '↑' }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).not.toHaveProperty('case_id');
    expect(bodies[0]).toMatchObject({ context: 'Current screen: Command Center' });
  });

  it('surfaces the containment verdict instead of discarding it', async () => {
    // The injection screen runs on every answer and used to be returned and
    // then never read, so a quarantined citation was indistinguishable from
    // one that was never checked.
    setAgentContext({ place: 'Command Center' });
    stubCopilot(
      copilotResponse({
        flagged_evidence_ids: ['e1'],
        unsupported_claims: [{ text: 'An unsupported claim', citations: [], status: 'unsupported', reason: 'no citation' }],
      }),
    );

    render(<AgentButton />);
    await userEvent.click(screen.getByRole('button', { name: /Ask the AEGIS Agent/ }));
    await userEvent.click(screen.getByRole('button', { name: /What changed recently\?/ }));

    expect(await screen.findByText(/prompt-injection indicator/)).toBeInTheDocument();
    expect(screen.getByText(/An unsupported claim/)).toBeInTheDocument();
  });

  it('says nothing about containment when nothing was flagged', async () => {
    setAgentContext({ place: 'Command Center' });
    stubCopilot();

    render(<AgentButton />);
    await userEvent.click(screen.getByRole('button', { name: /Ask the AEGIS Agent/ }));
    await userEvent.click(screen.getByRole('button', { name: /What changed recently\?/ }));

    expect(await screen.findByText(/Findings:/)).toBeInTheDocument();
    expect(screen.queryByText(/prompt-injection indicator/)).not.toBeInTheDocument();
  });

  it('renders the generated report as a document, not as answer prose', async () => {
    // `generate_report` used to appear in the tool breadcrumb with nothing
    // behind it, so the console showed a tool that had not run.
    setAgentContext({ place: 'Command Center' });
    stubCopilot(
      copilotResponse({
        tools_run: ['search_evidence', 'generate_report'],
        report: {
          title: 'create a report',
          sections: [
            { heading: 'Evidence retrieved', claims: ['A claim'] },
            { heading: 'Timeline', claims: ['A handle appeared', 'Another handle appeared'] },
          ],
          evidence_ids: ['e1', 'e2'],
          generated_by: 'aegis.copilot',
        },
      }),
    );

    render(<AgentButton />);
    await userEvent.click(screen.getByRole('button', { name: /Ask the AEGIS Agent/ }));
    await userEvent.click(screen.getByRole('button', { name: /What changed recently\?/ }));

    const report = await screen.findByRole('region', { name: 'Report' });
    expect(within(report).getByText('Evidence retrieved')).toBeInTheDocument();
    expect(within(report).getByText('A handle appeared')).toBeInTheDocument();
    // The section headings are what make it a brief rather than a list.
    expect(within(report).getByText('Timeline')).toBeInTheDocument();
  });

  it('renders no report block when nothing was validated', async () => {
    setAgentContext({ place: 'Command Center' });
    stubCopilot(copilotResponse({ report: null }));

    render(<AgentButton />);
    await userEvent.click(screen.getByRole('button', { name: /Ask the AEGIS Agent/ }));
    await userEvent.click(screen.getByRole('button', { name: /What changed recently\?/ }));

    expect(await screen.findByText(/Findings:/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Report' })).not.toBeInTheDocument();
  });

  it('does not announce a stage the request has not reached', async () => {
    // The previous progress indicator advanced on a 900ms timer regardless of
    // the request, so it said "Validating citations" before anything had run.
    setAgentContext({ place: 'Command Center' });
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/v1/copilot/query')) {
        await gate;
        return jsonResponse(copilotResponse());
      }
      if (url.includes('/v1/dashboard/summary')) return jsonResponse({ activity: [] });
      return jsonResponse({});
    });

    render(<AgentButton />);
    await userEvent.click(screen.getByRole('button', { name: /Ask the AEGIS Agent/ }));
    await userEvent.click(screen.getByRole('button', { name: /What changed recently\?/ }));

    // Mid-request, only the first stage may be claimed.
    expect(await screen.findByText('Reading the investigation')).toBeInTheDocument();
    expect(screen.queryByText('Validating citations')).not.toBeInTheDocument();
    release?.();
    await waitFor(() => expect(screen.getByText(/Findings:/)).toBeInTheDocument());
  });
});
