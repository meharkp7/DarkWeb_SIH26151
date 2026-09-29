import { expect, signIn, test, trackSockets } from './fixtures';

/**
 * A hand-driven survey of the app, kept deliberately rough.
 *
 * This is not a spec and asserts nothing: it signs in, visits every route and
 * every case tab, and prints the console errors, failed requests, heading and
 * document-overflow measurement for each. It exists so a human can re-derive the
 * ground truth the assertions in the other files are written against — a failing
 * assertion names what broke, this names what everything currently does.
 *
 * Run it alone with:
 *   npx playwright test probe --project=desktop
 */
test('survey every route', async ({ page }) => {
  const probe = await trackSockets(page);
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('response', (response) => {
    if (response.url().includes('/api/') && response.status() >= 400) {
      failedRequests.push(`${response.status()} ${response.url()}`);
    }
  });

  await signIn(page);

  await page.goto('/cases');
  const caseLink = page.locator('table.inv-register a.inv-case-cell__name').first();
  await caseLink.waitFor();
  const caseId = decodeURIComponent((await caseLink.getAttribute('href'))!.replace(/^\/cases\//, ''));

  const routes = [
    '/',
    '/cases',
    '/actors',
    '/infrastructure',
    '/personas',
    '/collection',
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
    consoleErrors.length = 0;
    failedRequests.length = 0;
    await page.goto(route);
    await page.waitForLoadState('networkidle').catch(() => undefined);
    const heading = await page.locator('h1').first().textContent();
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    console.log(
      `ROUTE ${route} :: h1=${JSON.stringify(heading)} overflow=${JSON.stringify(overflow)}\n` +
        `  consoleErrors=${JSON.stringify(consoleErrors)}\n  failedRequests=${JSON.stringify(failedRequests)}`,
    );
  }

  const sockets = await probe.read();
  console.log(`SOCKETS :: ${JSON.stringify(sockets)}`);
  console.log(`LIVE CHIP :: ${JSON.stringify(await page.locator('.sidebar-live').textContent())}`);

  expect(true).toBe(true);
});
