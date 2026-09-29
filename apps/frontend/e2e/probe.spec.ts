import { collectPageProblems, expect, signIn, test, waitForShell } from './fixtures';

/** Temporary probe: records what the app actually does, per route. */
test('probe', async ({ page }) => {
  const problems = collectPageProblems(page);
  await signIn(page);
  const caseId = await (async () => {
    await page.goto('/cases');
    const link = page.locator('a.inv-case-cell__name').first();
    await link.waitFor();
    return decodeURIComponent((await link.getAttribute('href'))!.replace(/^\/cases\//, ''));
  })();

  const routes = [
    '/',
    '/cases',
    '/actors',
    '/infrastructure',
    '/personas',
    '/threat-watch',
    '/admin',
    `/cases/${caseId}`,
    `/cases/${caseId}?tab=evidence`,
    `/cases/${caseId}?tab=network`,
    `/cases/${caseId}?tab=timeline`,
    `/cases/${caseId}?tab=assessment`,
    `/cases/${caseId}?tab=notes`,
  ];
  for (const route of routes) {
    problems.consoleErrors.length;
    await page.goto(route);
    await page.waitForTimeout(1500);
    const h1 = await page.locator('h1').first().textContent().catch(() => null);
    console.log(`ROUTE ${route} :: h1=${JSON.stringify(h1)}`);
    console.log(`  consoleErrors=${JSON.stringify(problems.consoleErrors)}`);
    console.log(`  failedRequests=${JSON.stringify(problems.failedRequests)}`);
    console.log(`  overflow=${JSON.stringify(await problems.overflow)}`);
  }

  // live chip
  await page.goto('/');
  await waitForShell(page);
  const chip = page.locator('.sidebar-live');
  console.log(`LIVE CHIP = ${JSON.stringify((await chip.textContent())?.trim())}`);
  const ws = await page.evaluate(
    () =>
      new Promise<string>((resolve) => {
        const s = new WebSocket(`ws://${location.host}/api/v1/live`, ['aegis', 'x']);
        s.onopen = () => resolve('open:' + s.readyState);
        s.onerror = () => resolve('error');
        setTimeout(() => resolve('timeout:' + s.readyState), 4000);
      }),
  );
  console.log(`RAW WS = ${ws}`);
  expect(true).toBe(true);
});
