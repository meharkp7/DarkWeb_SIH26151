import type { Page, Response } from '@playwright/test';

/**
 * Page-level problem collection.
 *
 * Every route in `navigation.spec.ts` is asserted for the same three things, so
 * the collection is a single helper returning a live view: the arrays fill as
 * the page runs, and a test reads them after the route has settled.
 *
 * "Live view" rather than a snapshot, deliberately. A console error emitted
 * during a slow sub-request would be missed by a snapshot taken too early, and
 * a snapshot taken too late would attribute an error to the wrong navigation.
 */

/** Layout is allowed to differ by a pixel; anything more is a real overflow. */
export const OVERFLOW_TOLERANCE_PX = 2;

export interface OverflowReport {
  /** `document.documentElement.scrollWidth <= clientWidth + tolerance`. */
  readonly overflowing: boolean;
  readonly scrollWidth: number;
  readonly clientWidth: number;
  readonly tolerance: number;
  /** Elements that widen the document, widest first. */
  readonly offenders: readonly string[];
}

export interface PageProblems {
  /** Console errors and uncaught page errors, as readable one-liners. */
  readonly consoleErrors: readonly string[];
  /** `/api/` and `/health` requests that failed at the network or HTTP layer. */
  readonly failedRequests: readonly string[];
  /**
   * A promise rather than a value: reading the scroll geometry needs an
   * evaluate in the page, and it must happen when the assertion runs, after the
   * route has settled — not when the listener was attached.
   */
  readonly overflow: Promise<OverflowReport>;
}

/** Only the app's own API surface counts; Vite's HMR and module requests do not. */
const API_PATH = /\/api\/|\/health/;

function describeRequest(response: Response): string {
  return `${response.status()} ${response.request().method()} ${response.url()}`;
}

/** Runs in the page: the document's own scroll geometry. */
const MEASURE_OVERFLOW = ([tolerance]: readonly [number]): OverflowReport => {
  const root = document.documentElement;
  const clientWidth = root.clientWidth;
  const overflowing = root.scrollWidth > clientWidth + tolerance;
  if (!overflowing) {
    return { overflowing: false, scrollWidth: root.scrollWidth, clientWidth, tolerance, offenders: [] };
  }

  // A short text snippet is included because the class name is often not the
  // identifying thing: eight identical `.sr-only` spans say far less than one
  // line naming the label each of them is standing in for.
  const describe = (element: Element): string => {
    const classes =
      typeof element.className === 'string' ? element.className.trim().split(/\s+/).slice(0, 2) : [];
    const text = (element.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}${
      classes.length > 0 ? `.${classes.join('.')}` : ''
    } right=${Math.round(element.getBoundingClientRect().right)}${text === '' ? '' : ` "${text}"`}`;
  };

  // Only elements that actually widen the document are reported, and the rule
  // for "can this element be wider than the document" is not the same for every
  // element.
  //
  // A static, relative or sticky element is always laid out inside its parent's
  // box, so any ancestor with `overflow-x` clipped or scrolled contains it. An
  // absolutely or fixed positioned element is laid out against its nearest
  // *positioned* ancestor, and only a positioned ancestor can clip it: a static
  // `overflow-x: auto` wrapper sitting between the element and its containing
  // block is skipped entirely, because the element escapes it. Treating both
  // alike finds the wrong element — a sticky table header inside a working
  // scroller looks like an offender while the absolutely positioned 1px
  // `.sr-only` label that actually widens the document does not.
  const CLIPS = new Set(['auto', 'scroll', 'hidden', 'clip']);

  const offenders: string[] = [];
  for (const element of Array.from(document.body.querySelectorAll<HTMLElement>('*'))) {
    const box = element.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) continue;
    if (box.right <= clientWidth + tolerance) continue;

    const position = getComputedStyle(element).position;
    const outOfFlow = position === 'absolute' || position === 'fixed';

    let ancestor: HTMLElement | null = element.parentElement;
    let contained = false;
    while (ancestor !== null && ancestor !== document.body) {
      const style = getComputedStyle(ancestor);
      const clips = CLIPS.has(style.overflowX);
      const positioned = style.position !== 'static' && style.position !== '';
      if (outOfFlow) {
        // The nearest positioned ancestor is the containing block, and only
        // ancestors at or below it can clip. A `positioned` ancestor here with no
        // clipping ends the search: everything above it is irrelevant.
        if (positioned) {
          contained = clips;
          break;
        }
      } else if (clips) {
        contained = true;
        break;
      }
      ancestor = ancestor.parentElement;
    }
    if (!contained) offenders.push(describe(element));
  }

  return {
    overflowing: true,
    scrollWidth: root.scrollWidth,
    clientWidth,
    tolerance,
    offenders: offenders.slice(0, 8),
  };
};

/**
 * Start recording console errors, uncaught exceptions and failed API calls on
 * `page`.
 *
 * Attach this *before* navigating: the first paint of a route is where React
 * reports its errors, and a listener registered afterwards has already missed
 * the evidence.
 */
export function collectPageProblems(page: Page): PageProblems {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];

  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const location = message.location();
    const at = location.url === '' ? '' : ` (${location.url}:${location.lineNumber})`;
    consoleErrors.push(`${message.text()}${at}`);
  });

  // A render that throws never reaches `console.error`; it surfaces here.
  page.on('pageerror', (error) => {
    consoleErrors.push(`Uncaught: ${error.message}`);
  });

  page.on('response', (response) => {
    if (response.status() < 400) return;
    if (!API_PATH.test(response.url())) return;
    failedRequests.push(describeRequest(response));
  });

  page.on('requestfailed', (request) => {
    if (!API_PATH.test(request.url())) return;
    const errorText = request.failure()?.errorText ?? 'unknown error';
    // An aborted request is a deliberate cancellation — the global search
    // aborts its in-flight lookup on every keystroke — not a failure. Counting
    // it would make the "no failed requests" assertion unusable rather than
    // meaningful.
    if (errorText === 'net::ERR_ABORTED') return;
    failedRequests.push(`${errorText} ${request.method()} ${request.url()}`);
  });

  return {
    get consoleErrors() {
      return [...consoleErrors];
    },
    get failedRequests() {
      return [...failedRequests];
    },
    get overflow() {
      return page.evaluate(MEASURE_OVERFLOW, [OVERFLOW_TOLERANCE_PX] as const);
    },
  };
}
