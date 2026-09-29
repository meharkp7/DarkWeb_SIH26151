import { Sparkline } from '../Sparkline';
import type { ActorActivitySeries } from '../../api/types';
import { formatDate } from '../../lib/format';
// Colocated: the cell is a primitive, and a primitive that renders unstyled
// because someone forgot a line in `main.tsx` is a broken register.
import '../../styles/quality.css';

const DAY_MS = 86_400_000;
const WEEK_MS = 7 * DAY_MS;

type Direction = 'rising' | 'falling' | 'level';

/**
 * Direction is carried by an arrow *and* a word.
 *
 * The arrow is what a dense register is actually scanned for; the word is what
 * keeps the state from being a hue, which is invisible to a screen reader and
 * to a colourblind analyst. Neither is decoration on its own — that is why
 * both are here.
 */
const GLYPH: Readonly<Record<Direction, string>> = {
  rising: '↗',
  falling: '↘',
  level: '→',
};

const WORD: Readonly<Record<Direction, string>> = {
  rising: 'rising',
  falling: 'falling',
  level: 'level',
};

const SPARK_WIDTH = 74;
const SPARK_HEIGHT = 20;

export interface ActorTrendCellProps {
  /** The series as the API returned it; `null` means nothing was recorded. */
  readonly series: ActorActivitySeries | null;
  readonly lastSeen: string | null;
  /** Named in the accessible description so the trend is attributable. */
  readonly handle: string;
  /** Injected by tests; the cell otherwise reads the wall clock. */
  readonly now?: number;
}

function sum(values: readonly number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

/**
 * Direction from the two halves of the window rather than from its endpoints.
 *
 * Comparing week 1 with week 12 calls a series that spiked and settled
 * "falling", which is the wrong word for it. Half against half answers the
 * question a register reader is actually asking — is this persona busier now
 * than it was — and it does not on the strength of two single buckets.
 */
export function trendDirection(weekly: readonly number[]): Direction {
  if (weekly.length < 2) return 'level';
  const midpoint = Math.floor(weekly.length / 2);
  const earlier = sum(weekly.slice(0, midpoint));
  const later = sum(weekly.slice(midpoint));
  if (later > earlier) return 'rising';
  if (later < earlier) return 'falling';
  return 'level';
}

/**
 * How long ago this actor was last observed, in words.
 *
 * "Never seen" and "seen 14 months ago" are different gaps with different
 * remedies, and a bare date in a neighbouring column makes an analyst do the
 * subtraction. A `last_seen` in the future is reported as the data error it is
 * rather than rounded to "today".
 */
export function recencyPhrase(lastSeen: string | null, now: number): string {
  if (lastSeen === null) return 'never seen';
  const at = new Date(lastSeen).getTime();
  if (!Number.isFinite(at)) return 'last seen not recorded';
  const days = Math.floor((now - at) / DAY_MS);
  if (days < 0) return 'last seen is in the future — clock or record is wrong';
  if (days === 0) return 'seen today';
  if (days === 1) return 'seen yesterday';
  if (days < 30) return `seen ${days} days ago`;
  const months = Math.round(days / 30);
  return months <= 1 ? 'seen over a month ago' : `seen about ${months} months ago`;
}

function periodLabel(start: string, weeks: number): string {
  const from = new Date(`${start}T00:00:00Z`);
  if (Number.isNaN(from.getTime())) return `the last ${weeks} weeks`;
  // The last bucket covers the six days after it opens, so the window ends a
  // day short of `weeks` full weeks after the start.
  const to = new Date(from.getTime() + weeks * WEEK_MS - DAY_MS);
  return `the ${weeks} weeks from ${formatDate(start)} to ${formatDate(to.toISOString())}`;
}

/**
 * One register cell: how often the actor was observed per week, and how long
 * ago it was last seen.
 *
 * The series is what the store holds — sightings, not evidence records — so the
 * cell says how many of them cite a ledger record rather than letting "34"
 * read as 34 pieces of evidence. The sparkline carries `role="img"` with a
 * full sentence rather than a caption, and the visible glyph, word and totals
 * beside it are hidden from assistive technology, so a screen-reader user hears
 * the claim once and completely.
 *
 * **A flat series and an all-zero series draw nothing.** A level line at the
 * bottom of a cell is the most misleading thing a register can contain: it
 * looks like a measurement and is indistinguishable from "we stopped looking".
 * Both render the words "No trend recorded"; the flat-with-volume case still
 * prints the total, so "nothing changed" is never confused with "nothing was
 * found".
 */
export function ActorTrendCell({ series, lastSeen, handle, now }: ActorTrendCellProps) {
  const at = now ?? Date.now();
  const recency = recencyPhrase(lastSeen, at);

  if (series === null || series.weekly.length === 0) {
    return (
      <span className="q-trend q-trend--none">
        <span className="q-trend__none">No trend recorded</span>
        <span className="q-trend__meta">{recency}</span>
      </span>
    );
  }

  const weekly = series.weekly;
  const total = sum(weekly);
  const direction = total === 0 ? 'level' : trendDirection(weekly);
  const peak = Math.max(...weekly);
  const period = periodLabel(series.start, weekly.length);
  const midpoint = Math.floor(weekly.length / 2);
  const meta = `${total} sightings in ${weekly.length}w · ${recency}`;

  // No SVG is drawn here, so nothing on screen is a restatement of the words
  // beside it: the totals are content here, not decoration, and stay readable.
  if (direction === 'level') {
    return (
      <span className="q-trend q-trend--none">
        <span className="q-trend__none">No trend recorded</span>
        <span className="q-trend__meta">
          {`${meta} · ${series.cited} cite a ledger record`}
        </span>
      </span>
    );
  }

  const label =
    `Sighting volume for ${handle} over ${period}: ${WORD[direction]}, ` +
    `${sum(weekly.slice(0, midpoint))} in the first half and ${sum(weekly.slice(midpoint))} ` +
    `in the second, peaking at ${peak} in a single week. ${total} sightings in total, of which ` +
    `${series.cited} cite a ledger record. ${recency}.`;

  return (
    <span className="q-trend" data-dir={direction}>
      <span className="q-trend__head" aria-hidden="true">
        <span className="q-trend__arrow">{GLYPH[direction]}</span>
        <span className="q-trend__word">{WORD[direction]}</span>
      </span>
      <Sparkline
        className="q-trend__spark"
        values={weekly}
        label={label}
        width={SPARK_WIDTH}
        height={SPARK_HEIGHT}
        formatValue={(value) => `${Math.round(value)} sighting${Math.round(value) === 1 ? '' : 's'}`}
      />
      <span className="q-trend__meta" aria-hidden="true">
        {`${meta} · ${series.cited} cited`}
      </span>
    </span>
  );
}
