import type { Tone } from '../components/Badge';

const DATE_TIME = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const DATE_ONLY = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

const CLOCK = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const EM_DASH = '—';

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Human-readable timestamp, or an em dash when the value is absent. */
export function formatDateTime(value: string | null | undefined): string {
  const date = parse(value);
  return date === null ? EM_DASH : DATE_TIME.format(date);
}

/** Date-only timestamp, or an em dash when the value is absent. */
export function formatDate(value: string | null | undefined): string {
  const date = parse(value);
  return date === null ? EM_DASH : DATE_ONLY.format(date);
}

/** `HH:MM:SS` clock used for "last checked" labels. */
export function formatClock(date: Date): string {
  return CLOCK.format(date);
}

/** Shorten a UUID for dense tables while keeping it copyable in full elsewhere. */
export function shortId(id: string, length = 8): string {
  if (id.length <= length) return id;
  return `${id.slice(0, length)}…`;
}

/** 0–1 score as a percentage string, e.g. `0.8431 → 84.3%`. */
export function formatPercent(value: number): string {
  const clamped = Math.min(1, Math.max(0, value));
  return `${Math.round(clamped * 1000) / 10}%`;
}

/** Visual tone for a 0–1 score: green ≥ 0.75, amber ≥ 0.5, red below. */
export function scoreTone(value: number): Tone {
  if (value >= 0.75) return 'ok';
  if (value >= 0.5) return 'warn';
  return 'danger';
}

/** Join class names, skipping falsy entries. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part)).join(' ');
}
