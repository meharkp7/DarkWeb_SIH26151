import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from './ErrorBoundary';

/**
 * The boundary exists so a render failure stays a message instead of becoming
 * a blank page. These tests pin that it actually catches, that it recovers on
 * retry, and that it resets when the analyst navigates away.
 */

function Boom({ shouldThrow }: { shouldThrow: boolean }): JSX.Element {
  if (shouldThrow) throw new Error('workspace payload was malformed');
  return <p>recovered content</p>;
}

describe('ErrorBoundary', () => {
  it('shows a recoverable message instead of unmounting the app', async () => {
    // React logs the caught error; that is intentional, keep the output readable.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary label="Investigation failed to render.">
        <Boom shouldThrow />
      </ErrorBoundary>,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent('This view could not be displayed');
    expect(alert).toHaveTextContent('Investigation failed to render.');
    // The underlying reason has to be surfaced, or it is unactionable.
    expect(screen.getByText('workspace payload was malformed')).toBeInTheDocument();

    // The failure must be logged, not swallowed.
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it('actually re-attempts the child when retry is pressed', async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    // A dead "Try again" button would look identical to a working one while
    // rendering the same fallback, so count the child's render attempts: the
    // point of retry is that the subtree is mounted and tried again.
    let attempts = 0;
    function AlwaysFails(): JSX.Element {
      attempts += 1;
      throw new Error('still broken');
    }

    render(
      <ErrorBoundary label="Investigation failed to render.">
        <AlwaysFails />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    const before = attempts;
    expect(before).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(attempts).toBeGreaterThan(before);
    // And because the fault was real, it is still reported.
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('still broken')).toBeInTheDocument();
    spy.mockRestore();
  });

  it('keeps showing the message when retry does not actually fix anything', async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <ErrorBoundary label="Investigation failed to render.">
        <Boom shouldThrow />
      </ErrorBoundary>,
    );

    // A real failure is usually still real. The boundary must not pretend the
    // screen recovered, and must not loop.
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('workspace payload was malformed')).toBeInTheDocument();

    // The escape hatch has to stay available.
    expect(screen.getByRole('link', { name: 'Back to cases' })).toHaveAttribute('href', '/cases');
    spy.mockRestore();
  });

  it('clears a caught error when resetKey changes, as on navigation', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { rerender } = render(
      <ErrorBoundary resetKey="/cases/broken" label="Investigation failed to render.">
        <Boom shouldThrow />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();

    rerender(
      <ErrorBoundary resetKey="/cases/healthy" label="Investigation failed to render.">
        <Boom shouldThrow={false} />
      </ErrorBoundary>,
    );

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('recovered content')).toBeInTheDocument();
    spy.mockRestore();
  });
});
