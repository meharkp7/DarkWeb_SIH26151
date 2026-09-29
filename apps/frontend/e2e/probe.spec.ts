import { expect, signIn, test } from './fixtures';

/** Temporary probe: search term candidates drawn from graph entity labels. */
test('probe graph labels + search', async ({ page }) => {
  await signIn(page);
  await page.goto('/cases');
  const link = page.locator('a.inv-case-cell__name').first();
  await link.waitFor();
  const caseId = decodeURIComponent((await link.getAttribute('href'))!.replace(/^\/cases\//, ''));

  await page.goto(`/cases/${caseId}?tab=network`);
  await page.locator('.inv-network__canvas').waitFor({ timeout: 20000 });
  const labels = await page.locator('.inv-node__label').evaluateAll((els) => els.map((e) => e.textContent ?? ''));
  console.log(`GRAPH nodes=${labels.length} labels=${JSON.stringify(labels.slice(0, 12))}`);

  // geometry
  const geo = await page.evaluate(() => {
    const svg = document.querySelector('.inv-network__canvas');
    if (svg === null) return 'no svg';
    const nodes = Array.from(document.querySelectorAll('.inv-node')).map((g) => {
      const card = g.querySelector('rect');
      const r = card!.getBoundingClientRect();
      return { label: g.getAttribute('aria-label')?.slice(0, 30), top: Math.round(r.top), bottom: Math.round(r.bottom) };
    });
    const svgRect = svg.getBoundingClientRect();
    return {
      svgHeight: Math.round(svgRect.height),
      viewBox: svg.getAttribute('viewBox'),
      nodeCount: nodes.length,
      minTop: Math.min(...nodes.map((n) => n.top)),
      maxBottom: Math.max(...nodes.map((n) => n.bottom)),
      svgTop: Math.round(svgRect.top),
      svgBottom: Math.round(svgRect.bottom),
      sample: nodes.slice(0, 4),
    };
  });
  console.log(`GRAPH GEO :: ${JSON.stringify(geo, null, 1)}`);

  for (const label of labels.slice(0, 4)) {
    const trimmed = (label ?? '').replace(/…$/, '');
    if (trimmed.length < 4) continue;
    const term = trimmed.slice(0, 8);
    await page.locator('.gsearch input').fill(term);
    await page.waitForTimeout(1700);
    const hits = await page.locator('.gsearch__hit').evaluateAll((els) => els.slice(0, 4).map((e) => ({
      badge: e.querySelector('.gsearch__badge')?.textContent,
      label: e.querySelector('.gsearch__label')?.textContent,
      case: e.querySelector('.gsearch__case')?.textContent ?? null,
    })));
    console.log(`TERM ${JSON.stringify(term)} :: count=${await page.locator('.gsearch__hit').count()} hits=${JSON.stringify(hits)}`);
    await page.keyboard.press('Escape');
  }
  expect(true).toBe(true);
});
