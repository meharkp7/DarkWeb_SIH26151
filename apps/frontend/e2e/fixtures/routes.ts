/**
 * Every route the suite treats as a destination.
 *
 * Held here rather than inside `navigation.spec.ts` so the route list, the tab
 * list and the case-workspace path builder cannot drift apart. A duplicated tab
 * list is the kind of thing that stays correct for a week and then quietly stops
 * covering the tab that was added last.
 */

export type RouteUnderTest = {
  /** Path relative to the base URL. */
  readonly path: string;
  /** The `<h1>` the route must render, as the DOM reports it. */
  readonly heading: RegExp;
  /** Short label used in the test name. */
  readonly label: string;
};

/**
 * Top-level destinations.
 *
 * Headings are matched rather than compared for equality because several pages
 * compose their `<h1>` from markup — `Threat <i>Watch.</i>` — and the command
 * centre greets the analyst by name and by time of day. The patterns pin the
 * identifying part of the heading, which is what a regression would change.
 */
export const TOP_LEVEL_ROUTES: readonly RouteUnderTest[] = [
  { path: '/', heading: /Good (morning|afternoon|evening), \S/, label: 'command center' },
  { path: '/cases', heading: /^Investigations$/, label: 'investigations register' },
  { path: '/actors', heading: /^Actors$/, label: 'actors' },
  { path: '/infrastructure', heading: /^Infrastructure$/, label: 'infrastructure' },
  { path: '/personas', heading: /^Persona linkage$/, label: 'persona linkage' },
  { path: '/collection', heading: /^Collection\.$/, label: 'collection' },
  { path: '/threat-watch', heading: /^Threat Watch\.$/, label: 'threat watch' },
  { path: '/admin', heading: /^Administration$/, label: 'administration' },
];

/** The case workspace's six tabs, in the order they are declared. */
export const WORKSPACE_TABS = [
  'overview',
  'evidence',
  'network',
  'timeline',
  'assessment',
  'notes',
] as const;

export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];

/**
 * The path for one tab of one case.
 *
 * `overview` is the default view and takes no query parameter, which is what
 * makes a missing `?tab=overview` load rather than fall through to a tab that
 * does not exist.
 */
export function workspacePath(caseId: string, tab: WorkspaceTab): string {
  return tab === 'overview' ? `/cases/${caseId}` : `/cases/${caseId}?tab=${tab}`;
}
