import { useId } from 'react';
import type { ReactNode } from 'react';
import { cx } from '../lib/format';
// Colocated rather than imported in main.tsx: the block is a primitive, and a
// primitive that only renders correctly when someone remembers to wire a
// stylesheet into the entry point is not one.
import '../styles/datablock.css';

export interface DataBlockProps {
  /** What the block is. Used as the accessible name of the section. */
  readonly title: string;
  /**
   * The sentence the analyst reads before the numbers: what is shown, over what
   * window, against what denominator. Omit only when there is nothing true to
   * say — never to save space.
   */
  readonly lead?: string;
  /** A claim about the block as a whole, not a category label. */
  readonly eyebrow?: string;
  /** Right-aligned controls in the block header. */
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  /** Drops the outer padding, for a block placed inside another block. */
  readonly dense?: boolean;
  readonly className?: string;
  /**
   * Heading level for the title. Pages pass 2; a block nested inside another
   * block passes 3 so the document outline does not skip a level.
   */
  readonly headingLevel?: 2 | 3;
}

/**
 * The wrapper every data panel sits in.
 *
 * The ordering is the whole point: eyebrow, then title, then the lead, then the
 * data. An analyst who reads nothing else still learns what the block is, what
 * its figures mean, and how they were produced — before any number can be
 * mistaken for something else.
 */
export function DataBlock({
  title,
  lead,
  eyebrow,
  actions,
  children,
  dense = false,
  className,
  headingLevel = 2,
}: DataBlockProps) {
  const titleId = useId();
  const Heading = headingLevel === 3 ? 'h3' : 'h2';
  return (
    <section
      className={cx('db', dense && 'db--dense', className)}
      aria-labelledby={titleId}
    >
      <div className="db__head">
        <div className="db__headings">
          {eyebrow !== undefined && eyebrow !== '' && (
            <p className="db__eyebrow">{eyebrow}</p>
          )}
          <Heading className="db__title" id={titleId}>
            {title}
          </Heading>
          {lead !== undefined && lead !== '' && <p className="db__lead">{lead}</p>}
        </div>
        {actions !== undefined && <div className="db__actions">{actions}</div>}
      </div>
      <div className="db__body">{children}</div>
    </section>
  );
}
