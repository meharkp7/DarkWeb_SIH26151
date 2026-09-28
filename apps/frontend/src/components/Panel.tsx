import type { ReactNode } from 'react';

export interface PanelProps {
  readonly title: string;
  /** Short explanation rendered under the title. */
  readonly description?: string;
  /** Right-aligned controls in the panel header. */
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  /** Heading level for the panel title (pages use h1, panels h2 by default). */
  readonly headingLevel?: 2 | 3;
}

/** Elevated section with a titled header — the main content container. */
export function Panel({ title, description, actions, children, headingLevel = 2 }: PanelProps) {
  const Heading = headingLevel === 3 ? 'h3' : 'h2';
  return (
    <section className="panel" aria-label={title}>
      <div className="panel__head">
        <div className="panel__headings">
          <Heading className="panel__title">{title}</Heading>
          {description !== undefined && <p className="panel__desc">{description}</p>}
        </div>
        {actions !== undefined && <div className="panel__actions">{actions}</div>}
      </div>
      <div className="panel__body">{children}</div>
    </section>
  );
}
