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
  // Depend on the fields, not the object: call sites build a fresh literal
  // every render and an identity dep would thrash the store.
  useEffect(() => {
    current = place ? { place, view } : DEFAULT_CONTEXT;
    emit();
    return () => {
      // Only clear if nothing else has claimed the context in the meantime;
      // on a route change the next page's effect may already have run.
      if (current.place === place && current.view === view) {
        current = DEFAULT_CONTEXT;
        emit();
      }
    };
  }, [place, view]);
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
  'Threat Watch': ['What should I care about?', 'Show the newest critical alerts'],
  Reports: ['What reports exist for the last week?', 'Summarize the latest assessment'],
  Administration: [
    'Is the audit trail intact?',
    'What is the health of this deployment?',
  ],
};

export function agentSuggestions(context: AgentContext): readonly string[] {
  if (context.view) return VIEW_SUGGESTIONS[context.view];
  return SPACE_SUGGESTIONS[context.place] ?? ['What changed recently?', 'Show me the latest activity'];
}

/** The one-line grounding note appended to every question sent to the API. */
export function agentGrounding(context: AgentContext): string | undefined {
  if (context.view) return `Current investigation: ${context.place} — viewing ${context.view}`;
  return `Current screen: ${context.place}`;
}
