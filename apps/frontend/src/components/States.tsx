import type { ReactNode } from 'react';

export interface EmptyStateProps {
  readonly title: string;
  readonly message: string;
  /** Endpoint that will (or should) back this panel. */
  readonly endpoint?: string;
  readonly children?: ReactNode;
}

/**
 * Honest placeholder for data the API does not expose yet.
 *
 * Never renders invented values: it states what is missing, why, and which
 * endpoint is planned to fill the panel.
 */
export function EmptyState({ title, message, endpoint, children }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <p className="empty-state__title">{title}</p>
      <p className="empty-state__msg">{message}</p>
      {endpoint !== undefined && (
        <p className="empty-state__endpoint">
          Not implemented yet: <code>{endpoint}</code>
        </p>
      )}
      {children !== undefined && <div className="empty-state__actions">{children}</div>}
    </div>
  );
}

export interface LoadingStateProps {
  readonly label?: string;
}

/** Accessible busy indicator (`role="status"`). */
export function LoadingState({ label = 'Loading…' }: LoadingStateProps) {
  return (
    <div className="loading-state" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export interface ErrorStateProps {
  readonly message: string;
  readonly onRetry?: () => void;
}

/** Accessible error block (`role="alert"`), optionally retryable. */
export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="error-state" role="alert">
      <p className="error-state__msg">{message}</p>
      {onRetry !== undefined && (
        <button type="button" className="btn btn--ghost" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
