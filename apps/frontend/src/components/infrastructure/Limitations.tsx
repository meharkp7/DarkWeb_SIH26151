import { useId, useState } from 'react';
import { leadFor } from '../../lib/explain';
import { cx } from '../../lib/format';

/**
 * The limitations of one finding or match, collapsible in a table and
 * expanded in full everywhere else.
 *
 * Rendered at the same visual weight as the finding it qualifies. A
 * misconfiguration shown without the benign alternative that produces it is
 * a false accusation with a confidence bar beside it, and collapsing the
 * caveat behind a count is how that happens in practice — so the count is
 * the collapsed form, the words are one click away, and the words are never
 * summarised on the way.
 */
export function Limitations({
  notes,
  compact = false,
  alwaysOpen = false,
  label = 'does not establish',
}: {
  readonly notes: readonly string[];
  readonly compact?: boolean;
  readonly alwaysOpen?: boolean;
  readonly label?: string;
}): JSX.Element {
  const [open, setOpen] = useState(alwaysOpen);
  const id = useId();

  if (notes.length === 0) {
    // Absence of caveats is itself a fact worth stating rather than rendering
    // as blank space that reads like "nothing to say here".
    return <span className="inf-muted inf-caption">no limitations recorded</span>;
  }

  const body = (
    <ul className="inf-limits__list" id={id}>
      {notes.map((note) => (
        <li className="inf-limits__note" key={note}>
          {note}
        </li>
      ))}
    </ul>
  );

  if (alwaysOpen) {
    return (
      <div className="inf-limits">
        <p className="inf-limits__head">{label}</p>
        <p className="inf-caption" style={{ marginBottom: 6 }}>
          {leadFor('infra.limitations', { count: notes.length })}
        </p>
        {body}
      </div>
    );
  }

  return (
    <div className={cx('inf-limits', compact && 'inf-limits--compact')}>
      <button
        type="button"
        className="inf-limits__toggle"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        {open
          ? 'hide what this does not show'
          : `${notes.length} ${notes.length === 1 ? 'limitation' : 'limitations'}`}
      </button>
      {open && body}
    </div>
  );
}
