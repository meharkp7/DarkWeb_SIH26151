import { useEffect, useSyncExternalStore } from 'react';

/** The five views of the Investigation Workspace. */
export type WorkspaceView = 'overview' | 'evidence' | 'network' | 'timeline' | 'assessment' | 'notes';

/**
 * Where the analyst currently is.
 *
 * The AEGIS Agent is a floating affordance rather than a page, so it has no
 * route of its own to read. Pages publish what they are showing here, and the
 * agent uses it to suggest questions that are actually answerable from the
 * screen in front of you. Without this it could only ever offer the same four
 * generic prompts everywhere, which is the thing that makes a copilot feel
 * bolted on rather than embedded.
 */
export interface AgentContext {
  /** Human-readable name of the current space, e.g. `Operation Nightfall`. */
  place: string;
  /** The workspace view on screen, when inside an investigation. */
  view?: WorkspaceView;
  /**
   * The case's id, when inside an investigation.
   *
   * Separate from `place` on purpose: the name is what the analyst reads and
   * what the grounding line shows, but the API needs the id to scope the
   * graph, hypothesis, timeline and assessment tools. Passing the name as
   * grounding text and omitting the id is what left every case-scoped
   * question — "compare the competing hypotheses" — answered from nothing.
   */
  caseId?: string;
}

const DEFAULT_CONTEXT: AgentContext = { place: 'Command Center' };

let current: AgentContext = DEFAULT_CONTEXT;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): AgentContext {
  return current;
}

/** Publish agent context for the lifetime of the calling component. */
export function usePublishAgentContext(context: AgentContext | null): void {
  const place = context?.place;
  const view = context?.view;
  // `caseId` is part of the published state, not decoration. Dropping it here
  // means every case-scoped question is answered from an unscoped context, and
  // the graph / hypothesis / timeline / assessment tools stay empty for the
  // whole console — the feature works in tests and never works in use.
  const caseId = context?.caseId;
  // Depend on the fields, not the object: call sites build a fresh literal
  // every render and an identity dep would thrash the store.
  useEffect(() => {
    current = place ? { place, view, caseId } : DEFAULT_CONTEXT;
    emit();
    return () => {
      // Only clear if nothing else has claimed the context in the meantime;
      // on a route change the next page's effect may already have run. The
      // guard compares `caseId` too, or navigating between two cases would
      // leave the first case's id published on the second.
      if (current.place === place && current.view === view && current.caseId === caseId) {
        current = DEFAULT_CONTEXT;
        emit();
      }
    };
  }, [place, view, caseId]);
}

export function useAgentContext(): AgentContext {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Set the context imperatively; used by the shell for non-case routes. */
export function setAgentContext(context: AgentContext): void {
  current = context;
  emit();
}

/**
 * Prompts worth asking from here. Deliberately view-specific: the point of
 * context is that the agent proposes the question you were about to type.
 */
const VIEW_SUGGESTIONS: Record<WorkspaceView, readonly string[]> = {
  overview: [
    'What changed in this investigation?',
    'What is the single strongest signal here?',
    'What is still unresolved?',
  ],
  evidence: [
    'Summarize the collected evidence',
    'Which evidence is weakest, and why?',
    'Which evidence contradicts the leading hypothesis?',
  ],
  network: [
    'Which actor sits at the centre of this?',
    'What is the shortest path between the two leading actors?',
    'Which links are weakest?',
  ],
  timeline: [
    'How did this investigation evolve?',
    'Summarize the last 24 hours',
    'When did the first activity appear?',
  ],
  assessment: [
    'Compare the competing hypotheses',
    'What evidence is driving this confidence?',
    'What does this assessment not prove?',
  ],
  notes: ['Summarize the analyst notes', 'What is still unresolved?'],
};

/**
 * Prompts worth asking from here, keyed by the section label the shell
 * actually renders.
 *
 * `AppShell.sectionLabel` produces these strings, so the keys are the app's
 * own vocabulary rather than a parallel list that drifts from it. Any section
 * missing here falls through to the generic pair below, which is the exact
 * "bolted-on copilot" failure this module exists to prevent.
 */
const SPACE_SUGGESTIONS: Record<string, readonly string[]> = {
  'Command Center': [
    'What changed recently?',
    'Which investigation needs attention?',
    'Explain the current queue pressure',
  ],
  Investigations: [
    'Which case needs attention?',
    'Show me the most overdue investigation',
    'Why is the top case prioritised?',
  ],
  Actors: [
    'Which actor is most active?',
    'What evidence links to this actor?',
    'Which actors are still uncorroborated?',
  ],
  Infrastructure: [
    'Which hidden services are exposed?',
    'Which correlation rests on a single channel?',
    'What does this misconfiguration not prove?',
  ],
  'Persona Linkage': [
    'Which persona link is weakest?',
    'Why is this linkage rejected?',
    'Which personas share writing style?',
  ],
  Collection: [
    'Which collection run failed?',
    'What sources are configured?',
    'What is the collection status?',
  ],
  'Threat Watch': ['What should I care about?', 'Show the newest critical alerts'],
  Reports: ['What reports exist for the last week?', 'Summarize the latest assessment'],
  Administration: [
    'Is the audit trail intact?',
    'What is the health of this deployment?',
  ],
};

const GENERIC_SUGGESTIONS: readonly string[] = [
  'What changed recently?',
  'Show me the latest activity',
];

export function agentSuggestions(context: AgentContext): readonly string[] {
  if (context.view !== undefined) return VIEW_SUGGESTIONS[context.view] ?? GENERIC_SUGGESTIONS;
  const direct = SPACE_SUGGESTIONS[context.place];
  if (direct !== undefined) return direct;
  // Pages publish a qualified place — `Infrastructure · findings`,
  // `Threat Watch · alerts` — so a whole-section fallback is tried before the
  // generic pair. An exact-match-only table meant five of the seven top-level
  // destinations silently got the generic prompts, which is the bolted-on
  // feeling this module exists to remove.
  const label = Object.keys(SPACE_SUGGESTIONS).find(
    (section) => context.place === section || context.place.startsWith(`${section} ·`),
  );
  // `label` is a key that came from this table, so the lookup cannot miss;
  // the fallback is only for the impossible case, and keeps the return typed.
  return (label !== undefined ? SPACE_SUGGESTIONS[label] : undefined) ?? GENERIC_SUGGESTIONS;
}

/** The one-line grounding note appended to every question sent to the API. */
export function agentGrounding(context: AgentContext): string | undefined {
  if (context.view) return `Current investigation: ${context.place} — viewing ${context.view}`;
  return `Current screen: ${context.place}`;
}
