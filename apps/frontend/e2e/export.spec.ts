import { expect, test } from './fixtures';

/**
 * The export popover.
 *
 * The formats are the whole point of the control and each carries a one-line
 * description of what it produces. A menu that lists four bare words leaves the
 * analyst choosing between file extensions, and the only way to find out which
 * one keeps the evidence citations is to run the export and open the file.
 *
 * The failure path is asserted as carefully as the success path. An export that
 * fails must keep the menu open and say why: closing the menu on failure throws
 * away the analyst's format choice and their context, and a silent dismissal
 * reads as success.
 */

const FORMATS = [
  { label: 'PDF briefing', hint: 'Formatted analyst brief with evidence citations.' },
  { label: 'JSON structured', hint: 'Machine-readable evidence and provenance package.' },
  { label: 'CSV ledger', hint: 'Flat evidence matrix, one row per cited claim.' },
  { label: 'STIX 2.1 exchange', hint: 'Structured threat-intelligence bundle for sharing.' },
];

/** Matched as a predicate so the query string cannot defeat the glob. */
const EXPORT_PATTERN = (url: URL) => url.pathname.endsWith('/reports/export');

/**
 * Failure is induced by refusing the request at the network layer.
 *
 * The alternative — deleting the case, revoking a permission, or reaching for a
 * mock of the app's own client — would each change application state to test a
 * UI decision. A refused response is the same event from the component's point
 * of view, and it is the only way to reach this path without a defect.
 */
function refuseExport(page: import('@playwright/test').Page): void {
  page.route(EXPORT_PATTERN, (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"export service unavailable"}' }),
  );
}

test.describe('export popover', () => {
  test('opens on the case workspace and lists all four formats with descriptions', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const link = page.locator('table.inv-register a.inv-case-cell__name').first();
    await expect(link).toBeVisible();
    const caseId = decodeURIComponent((await link.getAttribute('href'))!.replace(/^\/cases\//, ''));
    await page.goto(`/cases/${caseId}`);

    const trigger = page.locator('.exp-trigger');
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();

    const popover = page.locator('.exp-popover');
    await expect(popover).toBeVisible();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');

    await expect(page.locator('.exp-format')).toHaveCount(FORMATS.length);
    for (const [index, format] of FORMATS.entries()) {
      const option = page.locator('.exp-format').nth(index);
      // Both halves asserted per format: a label without a description is the
      // exact regression the format list exists to prevent.
      await expect(option.locator('.exp-format__label')).toHaveText(format.label);
      await expect(option.locator('.exp-format__hint')).toHaveText(format.hint);
    }
  });

  test('Escape closes the popover and returns focus to the trigger', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const link = page.locator('table.inv-register a.inv-case-cell__name').first();
    await expect(link).toBeVisible();
    await link.click();
    await expect(page.locator('.exp-trigger')).toBeVisible();

    const trigger = page.locator('.exp-trigger');
    await trigger.click();
    await expect(page.locator('.exp-popover')).toBeVisible();

    await page.keyboard.press('Escape');

    await expect(page.locator('.exp-popover')).toHaveCount(0);
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    // Focus goes back to the control that opened the menu, not to the document.
    // A keyboard analyst who cannot get back to the trigger has to tab the whole
    // header again, and most will assume the menu is simply gone for good.
    await expect(trigger).toBeFocused();
  });

  test('a failed export keeps the popover open and reports the error', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const link = page.locator('table.inv-register a.inv-case-cell__name').first();
    await expect(link).toBeVisible();
    await link.click();

    const trigger = page.locator('.exp-trigger');
    await trigger.click();
    await expect(page.locator('.exp-popover')).toBeVisible();

    refuseExport(page);
    await page.locator('.exp-go').click();

    // Open, with a visible reason. Both halves matter: a menu that closes on
    // failure looks identical to a menu that was dismissed, and a menu that
    // stays open with no message leaves the analyst waiting for a file.
    await expect(page.locator('.exp-popover')).toBeVisible();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const error = page.locator('.exp-error');
    await expect(error).toBeVisible();
    await expect(error).toContainText('503');

    // Focus stays inside the open menu, on the control that failed, so a retry
    // is one keystroke away rather than a hunt through the header.
    await expect(page.locator('.exp-go')).toBeFocused();
  });

  test('a failed export can be retried from the same open popover', async ({ signedInPage: page }) => {
    await page.goto('/cases');
    const link = page.locator('table.inv-register a.inv-case-cell__name').first();
    await expect(link).toBeVisible();
    await link.click();

    await page.locator('.exp-trigger').click();
    await expect(page.locator('.exp-popover')).toBeVisible();

    refuseExport(page);
    await page.locator('.exp-go').click();
    await expect(page.locator('.exp-error')).toBeVisible();

    // With the route unblocked, a second attempt from the still-open menu has
    // to work — the format choice survived the failure.
    await page.unroute(EXPORT_PATTERN);
    const download = page.waitForEvent('download');
    await page.locator('.exp-go').click();
    await download;

    await expect(page.locator('.exp-popover')).toHaveCount(0);
  });
});
