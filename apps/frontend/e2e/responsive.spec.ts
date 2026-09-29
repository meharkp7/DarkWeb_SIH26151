import { expect, firstCaseId, test } from './fixtures';

/**
 * Dense tables at laptop width.
 *
 * Bug 3 was a register that clipped its rightmost column with no indication it
 * was there. Nothing in the unit suite could see it: the table rendered, the
 * cells existed, every assertion on the data passed. The only observable was
 * that some of the cells were somewhere the analyst could not get to.
 *
 * The fix for it was a min-width on the table plus an `overflow-x: auto` shell
 * around it, which is a two-part change — and only one part is visible in a
 * screenshot. A table given a min-width inside a shell that still clips silently
 * reintroduces the same bug. So both halves are asserted here, on every dense
 * register, at 1280×800: the container must be able to scroll, and it must
 * actually have to.
 */

/** The width the registers are designed to be squeezed at. */
const LAPTOP = { width: 1280, height: 800 } as const;

interface TableProbe {
  readonly name: string;
  readonly tableWidth: number;
  readonly container: string | null;
  readonly containerOverflowX: string | null;
  readonly containerWidth: number;
}

/**
 * Measured in the page, walking up from each table to the nearest ancestor that
 * can actually scroll.
 *
 * The nearest scrolling ancestor is the only one that matters: an `overflow-x`
 * further up may be reachable, but a scrollbar rendered at the far edge of a
 * page section is not a scroll affordance for a table inside it.
 */
function probeTables(): TableProbe[] {
  const probes: TableProbe[] = [];
  for (const table of Array.from(document.querySelectorAll('table'))) {
    let scroller: HTMLElement | null = table.parentElement;
    while (scroller !== null && scroller !== document.body) {
      const overflowX = getComputedStyle(scroller).overflowX;
      if (overflowX === 'auto' || overflowX === 'scroll') break;
      scroller = scroller.parentElement;
    }
    probes.push({
      name: table.className || table.getAttribute('aria-label') || 'table',
      tableWidth: table.scrollWidth,
      container: scroller === document.body ? null : (scroller?.className ?? null),
      containerOverflowX: scroller === document.body ? null : (scroller ? getComputedStyle(scroller).overflowX : null),
      containerWidth: scroller?.clientWidth ?? 0,
    });
  }
  return probes;
}

test.describe('dense tables at 1280', () => {
  test.use({ viewport: LAPTOP });

  const REGISTERS = [
    { label: 'investigations', path: '/cases', table: 'table.inv-register' },
    { label: 'infrastructure', path: '/infrastructure', table: 'table.inf-table' },
    { label: 'personas', path: '/personas', table: 'table.per-table' },
    { label: 'collection', path: '/collection', table: 'table.col-table' },
  ] as const;

  for (const register of REGISTERS) {
    test(`${register.label} scrolls its overflow instead of clipping it`, async ({ signedInPage: page }) => {
      await page.goto(register.path);
      const table = page.locator(register.table).first();
      await expect(table, `${register.path} must render a dense table`).toBeVisible();

      const probes = await page.evaluate(probeTables);
      const mine = probes.find((probe) => probe.tableWidth > 0);
      if (mine === undefined) throw new Error(`${register.path}: no table was measured.`);

      // Half one: a container that can scroll. A table wider than its shell with
      // `overflow-x: visible` is the original defect wearing a different class.
      expect(
        mine.containerOverflowX,
        `${register.path}: no ancestor of ${mine.name} has overflow-x auto/scroll — the table cannot be scrolled to`,
      ).toMatch(/auto|scroll/);

      // Half two: the scroll is real. A container that can scroll but does not
      // need to is fine; a container that needs to and cannot is bug 3 again.
      expect(
        mine.tableWidth,
        `${register.path}: ${mine.name} is ${mine.tableWidth}px inside a ${mine.containerWidth}px container and is being clipped, not scrolled`,
      ).toBeGreaterThan(mine.containerWidth);
    });
  }

  test('the inspector rail overlays below its breakpoint rather than squeezing', async ({ signedInPage: page }) => {
    const caseId = await firstCaseId(page);
    await page.goto(`/cases?inspect=${caseId}`);
    const rail = page.locator('.insp-rail');
    await expect(rail).toBeVisible();

    // At the breakpoint itself the rail is a column: the register gives up
    // width, which is the intended trade.
    const wide = await page.evaluate(() => {
      const shell = document.querySelector('.insp-shell.has-rail');
      return shell === null ? null : getComputedStyle(shell).gridTemplateColumns;
    });
    expect(wide, 'the shell must adopt the two-column layout with the rail open').not.toBeNull();
    expect(wide!.trim().split(/\s+/).length, 'rail must be a second grid column at 1280').toBe(2);

    // One pixel below the breakpoint it must become an overlay. Asserted on the
    // rail's own computed position, because that is the property the CSS
    // actually changes — asserting a class name would only restate the source.
    await page.setViewportSize({ width: LAPTOP.width - 1, height: LAPTOP.height });
    await expect(rail).toBeVisible();
    expect(
      await rail.evaluate((node) => getComputedStyle(node).position),
      'below 1280 the rail must be fixed, overlaying the register',
    ).toBe('fixed');

    // And the register underneath must get its full width back rather than
    // being squeezed into a strip beside the rail.
    const narrow = await page.evaluate(() => {
      const shell = document.querySelector('.insp-shell.has-rail');
      const wrap = document.querySelector('.table-wrap');
      return {
        columns: shell === null ? null : getComputedStyle(shell).gridTemplateColumns,
        wrapWidth: wrap?.clientWidth ?? 0,
      };
    });
    expect(narrow.columns!.trim().split(/\s+/).length, 'rail must stop being a column below 1280').toBe(1);
    expect(narrow.wrapWidth, 'the register must regain its width when the rail overlays').toBeGreaterThan(LAPTOP.width / 2);
  });
});
