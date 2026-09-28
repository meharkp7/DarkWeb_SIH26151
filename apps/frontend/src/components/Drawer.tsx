import { useId, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';

export interface DrawerProps {
  readonly title: string;
  readonly onClose: () => void;
  readonly children: ReactNode;
  readonly footer?: ReactNode;
}

/**
 * Right-hand detail drawer with dialog semantics:
 * `role="dialog"`, `aria-modal`, Escape to close, focus moved in on open
 * and restored on close.
 */
export function Drawer({ title, onClose, children, footer }: DrawerProps) {
  const titleId = useId();
  const containerRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previous = document.activeElement;
    containerRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={containerRef}
        tabIndex={-1}
      >
        <header className="drawer__head">
          <h2 className="drawer__title" id={titleId}>
            {title}
          </h2>
          <button type="button" className="btn btn--icon" onClick={onClose} aria-label="Close panel">
            <span aria-hidden="true">✕</span>
          </button>
        </header>
        <div className="drawer__body">{children}</div>
        {footer !== undefined && <footer className="drawer__foot">{footer}</footer>}
      </aside>
    </>
  );
}
