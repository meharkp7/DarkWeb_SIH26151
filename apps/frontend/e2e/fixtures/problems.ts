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

  const describe = (element: Element): string => {
    const classes =
      typeof element.className === 'string' ? element.className.trim().split(/\s+/).slice(0, 2) : [];
    return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}${
      classes.length > 0 ? `.${classes.join('.')}` : ''
    } right=${Math.round(element.getBoundingClientRect().right)}`;
  };

  // Only elements that actually widen the document are reported. A wide table
  // inside an `overflow-x: auto` container is working as designed and is not a
  // document-level overflow, so any element with a scrollable ancestor is
  // excluded from the diagnosis.
  const offenders: string[] = [];
  for (const element of Array.from(document.body.querySelectorAll<HTMLElement>('*'))) {
    const box = element.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) continue;
    if (box.right <= clientWidth + tolerance) continue;
    let ancestor: HTMLElement | null = element.parentElement;
    let insideScroller = false;
    while (ancestor !== null && ancestor !== document.body) {
      const overflowX = getComputedStyle(ancestor).overflowX;
      if (overflowX === 'auto' || overflowX === 'scroll' || overflowX === 'hidden') {
        insideScroller = true;
        break;
      }
      ancestor = ancestor.parentElement;
    }
    if (!insideScroller) offenders.push(describe(element));
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
