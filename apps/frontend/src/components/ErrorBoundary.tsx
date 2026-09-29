import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  readonly children: ReactNode;
  /** Shown instead of the default panel; lets the shell stay visible. */
  readonly label?: string;
  /** Changing this value clears a caught error, for retry affordances. */
  readonly resetKey?: string;
}

interface State {
  readonly error: Error | null;
}

/**
 * Contains a render failure to the subtree that caused it.
 *
 * Without this, any throw during render unmounts the entire React tree and the
 * operator is left staring at a blank page with no indication of what broke or
 * whether the API is even reachable. On a screen someone uses to make
 * attribution calls, silently losing the workspace is worse than an explicit
 * "this view failed, here is why" — and it is a routine class of failure here,
 * since a malformed API payload surfaces as a render error.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidUpdate(previous: Props): void {
    // Navigating away from a broken screen should clear the error, otherwise
    // the failure follows the analyst into a route that works fine.
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Left on the console rather than swallowed: the boundary exists to keep
    // the UI usable, not to make the failure invisible.
    console.error('AEGIS view failed to render', error, info.componentStack);
  }

  private readonly retry = (): void => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="boundary" role="alert">
        <div className="boundary__head">
          <span className="boundary__mark">!</span>
          <div>
            <strong>This view could not be displayed</strong>
            <p>{this.props.label ?? 'The data for this screen could not be rendered.'}</p>
          </div>
        </div>
        <pre className="boundary__detail">{error.message}</pre>
        <div className="boundary__actions">
          <button className="button" onClick={this.retry}>
            Try again
          </button>
          <a className="button button--dark" href="/cases">
            Back to cases
          </a>
        </div>
      </div>
    );
  }
}
