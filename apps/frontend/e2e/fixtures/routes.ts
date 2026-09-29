/**
 * Every route the suite treats as a destination.
 *
 * Held here rather than inside `navigation.spec.ts` because the register, the
 * case workspace and the export specs need the same case-workspace tab list, and
 * a tab list duplicated across two files drifts the moment a tab is added.
 */

import type { Page } from '@playwright/test';
import { firstCaseId } from './index';

/** The six tabs of a case workspace, in the order the tabs are declared. */
export const WORKSPACE_TABS = [
  'overview',
  'evidence',
  'network',
  'timeline',
  'assessment',
  'notes',
] as const;

export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];

export interface RouteUnderTest {
  /** Path relative to the base URL. */
  readonly path: string;
  /** The `<h1>` the route must render, exactly as the DOM reports it. */
  readonly heading: RegExp;
  /** Short label used in the test name. */
  readonly label: string;
}

/**
 * Top-level destinations.
 *
 * Headings are matched rather than compared for equality because several pages
 * compose their `<h1>` from markup — `Threat <i>Watch.</i>` — and the command
 * centre greets the analyst by name and time of day. The patterns pin the
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

/**
 * The case workspace, once per tab.
 *
 * The heading is the case name, so it cannot be known until a case is resolved
 * from the register; the pattern therefore matches "some non-empty name" and the
 * tab itself is asserted separately by the spec through the tabpanel's id.
 */
export async function workspaceRoutes(page: Page, caseId?: string): Promise<readonly RouteUnderTest[]> {
  const id = caseId ?? (await firstCaseId(page));
  return WORKSPACE_TABS.map((tab) => ({
    path: tab === 'overview' ? `/cases/${id}` : `/cases/${id}?tab=${tab}`,
    heading: /\S/,
    label: `case workspace · ${tab}`,
  }));
}
