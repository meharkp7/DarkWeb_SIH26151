import { formatCount } from '../../lib/explain';

/**
 * One tick per identifier kind, so "six identifiers" reads as "two keys and a
 * wallet" at a glance.
 *
 * The glyphs are decorative and `aria-hidden`; the accessible name of the cell
 * is the count and the spelled-out kinds beside them. A screen reader should
 * hear "6 identifiers: 2 onion, 2 pgp, 1 wallet, 1 handle", not six identical
 * coloured boxes.
 */
export interface ActorKindGlyphsProps {
  readonly kinds: Readonly<Record<string, number>>;
}

export function ActorKindGlyphs({ kinds }: ActorKindGlyphsProps) {
  const present = Object.entries(kinds)
    .filter(([, count]) => count > 0)
    .sort(([left], [right]) => left.localeCompare(right));
  if (present.length === 0) return null;

  const total = present.reduce((sum, [, count]) => sum + count, 0);
  const spoken = present.map(([kind, count]) => `${count} ${kind}`).join(', ');

  return (
    <span className="act-kinds" aria-hidden="true">
      {present.map(([kind]) => (
        <i key={kind} className={`act-kinds__glyph act-kinds__glyph--${kind}`} title={kind} />
      ))}
      <span className="sr-only">{`${formatCount(total, 'identifier')}: ${spoken}`}</span>
    </span>
  );
}