import { ANALYST_EMAIL, ANALYST_PASSWORD, expect, signIn, test, waitForShell } from './fixtures';

/**
 * The session lifecycle.
 *
 * The store keeps its token in web storage and revalidates it with
 * `/v1/auth/me` on every mount, so "signed in" is a claim the app has to earn
 * from the API on each load rather than a flag it set once. These tests are the
 * boundaries of that claim: it is established, it survives a reload, and signing
 * out really removes it.
 */
test.describe('session', () => {
  test('signing in reveals the shell and identifies the analyst', async ({ page }) => {
    await page.goto('/cases');

    const email = page.getByLabel('Work email');
    await expect(email).toBeVisible();

    await email.fill(ANALYST_EMAIL);
    await page.getByLabel('Password').fill(ANALYST_PASSWORD);
    await page.getByRole('button', { name: /Enter secure workspace/i }).click();

    await waitForShell(page);
    // The shell only renders once `/v1/auth/me` has resolved, so a name other
    // than the placeholder is proof the session was revalidated rather than
    // merely accepted locally.
    await expect(page.locator('.analyst strong')).not.toHaveText('Analyst');
  });

  test('the session survives a reload', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    await expect(page.locator('table.inv-register')).toBeVisible();
    const before = await page.locator('.analyst strong').textContent();

    await page.reload();

    await waitForShell(page);
    expect(await page.locator('.analyst strong').textContent()).toBe(before);
    // A restore that failed would land on the sign-in form, and a shell that
    // merely re-rendered from a stale flag would pass the check above; the
    // register actually loading is what distinguishes the two.
    await expect(page.locator('table.inv-register')).toBeVisible();
    await expect(page.getByLabel('Work email')).toHaveCount(0);
  });

  test('signing out clears the session', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    await expect(page.locator('table.inv-register')).toBeVisible();

    await page.getByRole('button', { name: /^Sign out/ }).click();

    await expect(page.getByLabel('Work email')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Primary' })).toHaveCount(0);

    // A sign-out that only hid the shell would be undone by the next reload.
    await page.reload();
    await expect(page.getByLabel('Work email')).toBeVisible();
  });

  test('a wrong password is refused and leaves no session behind', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('Work email').fill(ANALYST_EMAIL);
    await page.getByLabel('Password').fill('not-the-password');
    await page.getByRole('button', { name: /Enter secure workspace/i }).click();

    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Primary' })).toHaveCount(0);
  });

  /**
   * `signIn` is the shared helper every other spec uses, so it carries the
   * assertion of what "signed in" means instead of trusting each caller to
   * check. Exercised here, a failure in the helper is reported as a session
   * problem rather than as a timeout in whichever spec happened to run first.
   */
  test('the shared sign-in helper reaches an authenticated shell', async ({ page }) => {
    await signIn(page);
    await expect(page.getByLabel('Work email')).toHaveCount(0);
  });
});
