import { expect, liveChip, signIn, test, trackSockets } from './fixtures';

/**
 * The live feed. This is the direct regression guard for bug 1.
 *
 * The failure it prevents had no observable symptom anywhere except the socket
 * itself. The Vite proxy forwarded HTTP only — `ws: true` was never set on
 * `/api` — so the handshake never completed. `useLive` seeds its snapshot from
 * REST and only *enhances* it with the socket, which made the failure almost
 * perfect: every figure on every screen was correct, every unit test passed, and
 * nothing logged an error, because the `connect` event never fired and so no
 * `onerror` ran either. The console simply stopped updating and the sidebar chip
 * sat on "Reconnecting".
 *
 * The assertions are ordered by how hard they are to fake. The chip is the
 * symptom; the socket reaching `readyState === 1` is the cause. Both are checked
 * on a cold load, because a socket that connects once and is then left alone
 * would pass a test that only looked at the steady state.
 */

/** The API polls its audit tail every 2s, so this is generous, not optimistic. */
const LIVE_TIMEOUT_MS = 15_000;

test.describe('live feed', () => {
  test('the sidebar chip reaches Live on a cold load', async ({ page }) => {
    // Instrumented before the first navigation: the socket is opened by the
    // shell's very first effect, so a probe installed afterwards would miss it.
    const probe = await trackSockets(page);
    await signIn(page);

    const chip = liveChip(page);
    // Anchored, and tolerant of the leading whitespace JSX leaves in the chip's
    // text content. A loose substring would be satisfied by nothing at all here
    // — "Reconnecting" is the state that must never pass, and a substring
    // match is exactly the kind of check that lets a stale label through.
    await expect(chip, 'live chip never left its connecting state').toHaveText(/^\s*Live\b/, {
      timeout: LIVE_TIMEOUT_MS,
    });
    // The dot is the state, the label is its text. Asserting the dot class as
    // well catches a chip whose label and indicator disagree, which is exactly
    // the shape a partial reconnection leaves behind.
    await expect(chip.locator('.live-dot')).toHaveClass(/live-dot--on/);

    // The chip is derived from `connected`, which is only set in the `connect`
    // handler, so reaching "Live" already implies a socket opened. The socket is
    // read directly anyway: the label is the app's own account of itself.
    const open = (await probe.live()).filter((socket) => socket.readyState === 1);
    expect(open.length, 'a /api/v1/live socket reached readyState 1').toBeGreaterThan(0);
  });

  test('a socket the page opens actually reaches readyState 1', async ({ page }) => {
    const probe = await trackSockets(page);
    await signIn(page);

    await expect
      .poll(
        async () => (await probe.live()).filter((socket) => socket.readyState === 1).length,
        {
          timeout: LIVE_TIMEOUT_MS,
          message: 'no WebSocket for /api/v1/live ever reached readyState 1 (OPEN)',
        },
      )
      .toBeGreaterThan(0);

    // OPEN is not the same as working. The API sends a snapshot on connect and
    // a heartbeat on every poll thereafter, so a socket that opens and then goes
    // quiet is a socket the analyst is again reading stale figures from.
    await expect
      .poll(
        async () => (await probe.live()).reduce((total, socket) => total + socket.messages, 0),
        { timeout: LIVE_TIMEOUT_MS, message: 'the live socket opened but delivered no frames' },
      )
      .toBeGreaterThan(0);
  });

  test('the socket URL is the proxied API path and carries no token', async ({ page }) => {
    const probe = await trackSockets(page);
    await signIn(page);

    await expect
      .poll(async () => (await probe.live()).filter((socket) => socket.readyState === 1).length, {
        timeout: LIVE_TIMEOUT_MS,
      })
      .toBeGreaterThan(0);

    const urls = (await probe.live()).map((socket) => socket.url);
    // Asserted positively rather than by exclusion: a suite that tried to
    // recognise "the app's socket" by pattern would also pass if the app opened
    // no socket at all, which is the bug.
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(url).toContain('/api/v1/live');
      // The credential travels in the `Sec-WebSocket-Protocol` subprotocol, not
      // in the query string. A token in the URL leaks into the proxy log, the
      // browser history and anything else that records request URLs.
      expect(url, 'the live socket URL must not carry an access token').not.toContain('access_token');
    }
  });

  test('the chip carries a server timestamp, not the no-data placeholder', async ({ page }) => {
    await signIn(page);

    const chip = liveChip(page);
    await expect(chip).toHaveText(/^\s*Live\b/, { timeout: LIVE_TIMEOUT_MS });
    // `—` is the placeholder for "no snapshot yet". A chip that reads "Live"
    // followed by a dash is claiming a connection it has received no data from,
    // which is the shape bug 1 produced.
    await expect(chip).not.toHaveText(/—/);
  });
});
