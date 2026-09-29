import {
  collectPageProblems,
  expect,
  gotoSettled,
  OVERFLOW_TOLERANCE_PX,
  test,
  TOP_LEVEL_ROUTES,
  workspaceRoutes,
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
 * The console and the failed-request lists are read after `networkidle` on
 * every route. A smoke test that checked them on `/` alone would pass for the
 * same reason the unit suite did.
 */

/** Assert the route-level invariants, reporting every offender in one message. */
async function expectHealthyRoute(page: import('@playwright/test').Page, route: RouteUnderTest) {
  const problems = collectPageProblems(page);

  await gotoSettled(page, route.path);

  const heading = page.locator('h1');
  await expect(heading, `${route.path} must render an <h1>`).toBeVisible();
  expect(await heading.textContent(), `${route.path} heading text`).toMatch(route.heading);

  expect(problems.consoleErrors, `${route.path} console errors`).toEqual([]);
  expect(problems.failedRequests, `${route.path} failed /api/ responses`).toEqual([]);

  const overflow = await problems.overflow;
  expect(
    overflow.scrollWidth,
    `${route.path} overflows horizontally: ${overflow.scrollWidth} > ${overflow.clientWidth} + ${OVERFLOW_TOLERANCE_PX}; widest offenders ${JSON.stringify(overflow.offenders)}`,
  ).toBeLessThanOrEqual(overflow.clientWidth + OVERFLOW_TOLERANCE_PX);
}

test.describe('routes', () => {
  for (const route of TOP_LEVEL_ROUTES) {
    test(`${route.label} renders cleanly`, async ({ signedInPage: page }) => {
      await expectHealthyRoute(page, route);
    });
  }

  test('every case workspace tab renders cleanly', async ({ signedInPage: page }) => {
    for (const route of await workspaceRoutes(page)) {
      await expectHealthyRoute(page, route);
    }
  });

  /**
   * A tab that renders the case heading but leaves its panel empty is a route
   * that has stopped working while still passing the heading check above, so
   * the tabpanel is asserted by id — the same id the tab's `aria-controls`
   * points at, which keeps the assertion honest about what is on screen.
   */
  test('every case workspace tab renders its own panel', async ({ signedInPage: page }) => {
    const routes = await workspaceRoutes(page);

    for (const route of routes) {
      const tab = new URL(route.path, 'http://x').searchParams.get('tab') ?? 'overview';
      await gotoSettled(page, route.path);

      // `aria-controls` is the tab's own claim about which panel it shows, so
      // asserting the pair together catches a tab that selects nothing.
      const tabButton = page.locator(`#inv-tab-${tab}`);
      await expect(tabButton, `${route.path} tab button`).toHaveAttribute('aria-selected', 'true');
      await expect(tabButton, `${route.path} aria-controls`).toHaveAttribute('aria-controls', `inv-panel-${tab}`);
      await expect(page.locator(`#inv-panel-${tab}`), `${route.path} panel`).toBeVisible();
    }
  });
});
