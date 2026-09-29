import { expect, firstCaseId, signIn, test } from './fixtures';

/**
 * The investigations register: selection, navigation, and the round trip.
 *
 * The register is the app's densest screen and the one place two behaviours are
 * easy to confuse. Clicking a row is a *selection* — it fills the rail and
 * rewrites the query string, and the analyst stays on the register. Clicking the
 * case name is a *navigation*. Both are reachable from the same click target, so
 * a regression that wired the row to the link (or the link to nothing) would
 * still leave a register that looks right in a screenshot.
 */

const rail = '.insp-rail';

test.describe('investigations register', () => {
  test('clicking a row selects it, fills the rail, and does not navigate', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    await expect(page.locator('table.inv-register')).toBeVisible();
    const pathBefore = new URL(page.url()).pathname;

    const row = page.locator('table.inv-register tbody tr[aria-selected]').first();
    const name = await row.locator('a.inv-case-cell__name').textContent();

    // Clicked on a cell that is not the link, which is the distinction under
    // test: the row handler and the link handler occupy the same visual target.
    await row.locator('td').nth(3).click();

    await expect(page.locator(rail)).toBeVisible();
    await expect(page.locator(`${rail}__title`)).toHaveText(name ?? '');
    // The rail must actually carry facts, not merely open: an empty rail with
    // the right title is what a selection that lost its payload looks like.
    await expect(page.locator(`${rail} .insp-facts__row`)).not.toHaveCount(0);
    await expect(row).toHaveAttribute('aria-selected', 'true');

    expect(new URL(page.url()).pathname).toBe(pathBefore);
  });

  test('the selection is written to the query string', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const row = page.locator('table.inv-register tbody tr[aria-selected]').first();
    const link = row.locator('a.inv-case-cell__name');
    const caseId = decodeURIComponent((await link.getAttribute('href'))!.replace(/^\/cases\//, ''));

    await row.locator('td').nth(3).click();

    // `?inspect=` is what makes a selection shareable and survives a reload.
    await expect.poll(() => new URL(page.url()).searchParams.get('inspect')).toBe(caseId);
  });

  test('the case name link navigates to the workspace', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const link = page.locator('table.inv-register a.inv-case-cell__name').first();
    const name = await link.textContent();
    const caseId = decodeURIComponent((await link.getAttribute('href'))!.replace(/^\/cases\//, ''));

    await link.click();

    await expect(page).toHaveURL(new RegExp(`/cases/${caseId}$`));
    // The workspace `<h1>` is the case name, so this distinguishes arriving at
    // the workspace from landing on a route that merely shares the path.
    await expect(page.locator('h1')).toHaveText(name ?? '');
  });

  test('a ?inspect= URL round-trips into an open rail', async ({ signedInPage: page }) => {
    // Read the name from the register rather than hard-coding it, so the
    // assertion is about the URL restoring the selection and not about a case
    // called something in particular.
    const caseId = await firstCaseId(page);
    const expected = (await page.locator(`a.inv-case-cell__name[href="/cases/${caseId}"]`).first().textContent()) ?? '';

    await page.goto(`/cases?inspect=${caseId}`);

    await expect(page.locator(rail)).toBeVisible();
    await expect(page.locator(`${rail}__title`)).toHaveText(expected ?? '');
    await expect(page.locator(`${rail} .insp-facts__row`)).not.toHaveCount(0);
    // The rail is a named landmark and the heading is its accessible name, so
    // the rail is reachable as one unit rather than as loose controls.
    await expect(page.getByRole('complementary', { name: expected ?? '' })).toBeVisible();
  });

  test('Escape closes the rail and returns focus to the row', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const row = page.locator('table.inv-register tbody tr[aria-selected]').first();
    await row.locator('td').nth(3).click();
    await expect(page.locator(rail)).toBeVisible();

    // Focus lands inside the rail on open, so the analyst is reading the thing
    // that just appeared rather than the row they clicked.
    await expect(page.locator(`${rail}__title`)).toBeFocused();

    await page.keyboard.press('Escape');

    await expect(page.locator(rail)).toHaveCount(0);
    // Focus restoration is the part that is easy to drop: without it a keyboard
    // analyst is dropped at the top of the document and has to re-tab to the
    // register they were working in.
    await expect(row).toBeFocused();
    await expect.poll(() => new URL(page.url()).searchParams.get('inspect')).toBeNull();
  });

  test('a keyboard user can select a row with Enter', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const row = page.locator('table.inv-register tbody tr[aria-selected]').first();
    await row.focus();
    await page.keyboard.press('Enter');

    await expect(page.locator(rail)).toBeVisible();
    // A row that is both focusable and activatable is the whole point of
    // `tabIndex` + `role="button"` on a `<tr>`.
    expect(new URL(page.url()).pathname).toBe('/cases');
  });
});

/**
 * The register is reachable without a session, so a sign-out that failed would
 * leave it rendering for an anonymous analyst. Asserted through the real gate
 * rather than by inspecting storage, because the storage is not what the
 * security of the screen rests on.
 */
test.describe('register access', () => {
  test('the register is not reachable without a session', async ({ page }) => {
    await signIn(page);
    await page.goto('/cases');
    await expect(page.locator('table.inv-register')).toBeVisible();

    await page.getByRole('button', { name: /^Sign out/ }).click();
    await expect(page.getByLabel('Work email')).toBeVisible();

    await page.goto('/cases');
    await expect(page.locator('table.inv-register')).toHaveCount(0);
  });
});
