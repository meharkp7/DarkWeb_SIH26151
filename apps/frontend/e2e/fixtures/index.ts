import { expect, test as base } from '@playwright/test';
import type { Page } from '@playwright/test';
import { ANALYST_EMAIL, ANALYST_PASSWORD } from './environment';

export { API_ORIGIN, ANALYST_EMAIL } from './environment';
export { collectPageProblems, OVERFLOW_TOLERANCE_PX } from './problems';
export type { OverflowReport, PageProblems } from './problems';

/** Where the sign-in form lives; every unauthenticated route renders it. */
export const SIGN_IN_SUBMIT = 'button:has-text("Enter secure workspace")';

/**
 * Sign in through the real form.
 *
 * Deliberately not a token injected into storage: the auth store reads its
 * envelope on mount, restores the session with `/v1/auth/me` and only then
 * reveals the shell. A pre-seeded token would skip exactly the code path the
 * suite is here to cover, and would go on passing if that path regressed.
 */
export async function signIn(page: Page): Promise<void> {
  await page.goto('/');
  const email = page.getByLabel('Work email');
  await expect(email).toBeVisible();
  await email.fill(ANALYST_EMAIL);
  await page.getByLabel('Password').fill(ANALYST_PASSWORD);
  await page.getByRole('button', { name: /Enter secure workspace/i }).click();
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
}

/**
 * Wait until the shell has rendered its chrome rather than its content.
 *
 * The live chip and the nav both live in `AppShell`, so they appear together;
 * a test that waits for one has waited for the shell.
 */
export async function waitForShell(page: Page): Promise<void> {
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
}

/** Resolve an investigation id from the register, so no case id is hard-coded. */
export async function firstCaseId(page: Page): Promise<string> {
  await page.goto('/cases');
  const link = page.locator('a.inv-case-cell__name').first();
  await expect(link).toBeVisible();
  const href = await link.getAttribute('href');
  if (href === null) throw new Error('Register row link carried no href.');
  return decodeURIComponent(href.replace(/^\/cases\//, ''));
}

type Fixtures = {
  /** A page already through the sign-in form and holding a live session. */
  signedInPage: Page;
};

export const test = base.extend<Fixtures>({
  signedInPage: async ({ page }, use) => {
    await signIn(page);
    await use(page);
  },
});

export { expect };
