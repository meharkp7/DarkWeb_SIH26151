import { expect, firstCaseId, test } from './fixtures';

/**
 * The global search box.
 *
 * Two behaviours with opposite failure modes, so both are asserted:
 *
 *  - A long enough term must find things, and each hit must say which case it
 *    belongs to. An entity label on its own is an identifier with no context;
 *    the case name is what makes a hit actionable.
 *  - A term below the minimum length must not reach the API at all. The hint is
 *    a promise, and a promise the client breaks is worse than no promise: the
 *    analyst waits for results that were never going to arrive.
 */

const MIN_TERM = 3;

/**
 * A term guaranteed to be in the index.
 *
 * Taken from the case workspace's own network graph rather than hard-coded, so
 * the spec follows the seeded dataset instead of asserting against a fixture
 * that a reseed would quietly invalidate.
 */
async function indexedTerm(page: import('@playwright/test').Page): Promise<string> {
  const caseId = await firstCaseId(page);
  await page.goto(`/cases/${caseId}?tab=network`);
  const label = page.locator('.inv-node__label').first();
  await expect(label, 'the case network must render nodes to search for').toBeVisible();
  const text = ((await label.textContent()) ?? '').replace(/…$/, '').trim();
  if (text.length < MIN_TERM) {
    throw new Error(`Network node label ${JSON.stringify(text)} is too short to search for.`);
  }
  return text;
}

test.describe('global search', () => {
  test('finds an entity and shows the case it belongs to', async ({ signedInPage: page }) => {
    const term = await indexedTerm(page);

    const input = page.getByRole('combobox', { name: 'Search across the platform' });
    await input.fill(term);

    const hits = page.locator('.gsearch__hit');
    await expect(hits.first(), `no search hit for ${JSON.stringify(term)}`).toBeVisible();

    // The badge is the record type; the case name is the context. Both are
    // asserted on the first hit, because a hit that renders a label with no case
    // is indistinguishable from one that failed to resolve its case.
    const first = hits.first();
    await expect(first.locator('.gsearch__badge')).not.toBeEmpty();
    await expect(first.locator('.gsearch__case')).not.toBeEmpty();

    // Every hit that claims a case must show a non-empty one, not an empty span
    // that occupies the space an analyst reads.
    const caseTexts = await page.locator('.gsearch__hit .gsearch__case').allTextContents();
    expect(caseTexts.length).toBeGreaterThan(0);
    for (const text of caseTexts) expect(text.trim()).not.toBe('');
  });

  test('a term below the minimum length shows the hint and issues no request', async ({ signedInPage: page }) => {
    // Registered before typing: a request listener attached afterwards would
    // miss the very request this test exists to prove does not happen.
    const searches: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/v1/search')) searches.push(request.url());
    });

    const input = page.getByRole('combobox', { name: 'Search across the platform' });
    await input.fill('ab');

    await expect(page.locator('.gsearch__hint')).toHaveText(`${MIN_TERM}+ characters`);
    // The results panel is not rendered at all below the minimum, which is what
    // makes "no results" and "not enough to search" distinguishable.
    await expect(page.locator('.gsearch__panel')).toHaveCount(0);
    await page.waitForTimeout(750);
    expect(searches, 'a below-minimum term must not reach /v1/search').toEqual([]);
  });

  test('the hint clears once the term is long enough to search', async ({ signedInPage: page }) => {
    const term = await indexedTerm(page);
    const input = page.getByRole('combobox', { name: 'Search across the platform' });

    await input.fill('ab');
    await expect(page.locator('.gsearch__hint')).toBeVisible();

    await input.fill(term);
    // Asserted as absent rather than "not visible": the hint is unmounted when
    // the term becomes searchable, and a lingering element would overlay the
    // first row of results.
    await expect(page.locator('.gsearch__hint')).toHaveCount(0);
    await expect(page.locator('.gsearch__hit').first()).toBeVisible();
  });
});
