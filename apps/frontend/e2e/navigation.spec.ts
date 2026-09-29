import type { Page } from '@playwright/test';
import {
  collectPageProblems,
  expect,
  firstCaseId,
  gotoSettled,
  OVERFLOW_TOLERANCE_PX,
  test,
  TOP_LEVEL_ROUTES,
  WORKSPACE_TABS,
  workspacePath,
  type RouteUnderTest,
} from './fixtures';

/**
 * Every route, checked for the three things a passing unit test cannot see.
 *
 * 113 vitest tests cover the reducers, the API client and the formatting, and
 * every one of them was green while the app threw on two routes, clipped a
 * register and never opened a socket. What those tests cannot do is load a
 * route in a browser and watch it. So the assertions below are deliberately
 * blunt and applied uniformly: the heading renders, the console stays clean, no
 * `/api/` request failed, and the document does not scroll sideways.
 *
 * The console and failed-request lists are read after `networkidle` on every
 * route. A smoke test that checked them on `/` alone would pass for the same
 * reason the unit suite did.
 *
 * One test per route rather than one test that walks them all: a tab that starts
 * failing must name itself in the report, not hide behind whichever tab happened
 * to be visited last.
 */

/**
 * React logs a console error once per render, and a duplicate-key warning
 * repeats on every re-render of the offending list — 146 copies of a 20-line
 * stack, which buries every other error on the route. The comparison is still
 * made against the full list, so nothing is let through; only the message is
 * summarised, because a failure report nobody can read is one nobody acts on.
 */
function summarise(errors: readonly string[]): string {
  const unique = [...new Set(errors.map((text) => text.split('\n')[0]?.trim() ?? ''))];
  return `${unique.length} distinct of ${errors.length}: ${JSON.stringify(unique, null, 2)}`;
}

/** Assert the route-level invariants, reporting every offender in one message. */
async function expectHealthyRoute(page: Page, route: RouteUnderTest) {
  const problems = collectPageProblems(page);

  await gotoSettled(page, route.path);

  const heading = page.locator('h1');
  await expect(heading, `${route.path} must render an <h1>`).toBeVisible();
  expect(await heading.textContent(), `${route.path} heading text`).toMatch(route.heading);

  expect(problems.consoleErrors, `${route.path} console errors: ${summarise(problems.consoleErrors)}`).toEqual([]);
  expect(problems.failedRequests, `${route.path} failed /api/ responses`).toEqual([]);

  const overflow = await problems.overflow;
  expect(
    overflow.scrollWidth,
    `${route.path} overflows horizontally: ${overflow.scrollWidth} > ${overflow.clientWidth} + ${OVERFLOW_TOLERANCE_PX}\n  offenders: ${overflow.offenders.join('\n  ')}`,
  ).toBeLessThanOrEqual(overflow.clientWidth + OVERFLOW_TOLERANCE_PX);
}

test.describe('routes', () => {
  for (const route of TOP_LEVEL_ROUTES) {
    test(`${route.label} renders cleanly`, async ({ signedInPage: page }) => {
      await expectHealthyRoute(page, route);
    });
  }
});

test.describe('case workspace', () => {
  for (const tab of WORKSPACE_TABS) {
    test(`the ${tab} tab renders cleanly`, async ({ signedInPage: page }) => {
      // Resolved from the register rather than hard-coded, so the spec follows
      // the seeded data instead of a case id a reseed would invalidate.
      const caseId = await firstCaseId(page);
      await expectHealthyRoute(page, {
        path: workspacePath(caseId, tab),
        heading: /\S/,
        label: `case workspace · ${tab}`,
      });
    });
  }

  /**
   * A tab that renders the case heading but leaves its panel empty is a route
   * that has stopped working while still passing the heading check above, so
   * the tabpanel is asserted by id — the same id the tab's `aria-controls`
   * points at, which keeps the assertion honest about what is on screen.
   */
  test('every tab renders its own panel', async ({ signedInPage: page }) => {
    const caseId = await firstCaseId(page);

    for (const tab of WORKSPACE_TABS) {
      const path = workspacePath(caseId, tab);
      await gotoSettled(page, path);

      // `aria-controls` is the tab's own claim about which panel it shows, so
      // asserting the pair together catches a tab that selects nothing.
      const tabButton = page.locator(`#inv-tab-${tab}`);
      await expect(tabButton, `${path} tab button`).toHaveAttribute('aria-selected', 'true');
      await expect(tabButton, `${path} aria-controls`).toHaveAttribute('aria-controls', `inv-panel-${tab}`);
      await expect(page.locator(`#inv-panel-${tab}`), `${path} panel`).toBeVisible();
    }
  });
});
