import type { InfraChannelScores, InfraSeverity } from '../../api/types';
import { cx, formatPercent } from '../../lib/format';

/*
 * Small presentational pieces shared by the three infrastructure tables.
 *
 * The rule every one of them obeys: a meaning that matters is carried by
 * text as well as by colour, length or position. Severity is a word. An
 * unobserved channel says "not observed". An unscored detector says
 * "unscored". A single-channel match says so in the row.
 */

// --- severity --------------------------------------------------------------

export function Severity({ value }: { readonly value: InfraSeverity }): JSX.Element {
  return <span className={cx('inf-sev', `inf-sev--${value}`)}>{value}</span>;
}

// --- confidence ------------------------------------------------------------

/**
 * A confidence bar, a number, and an epistemic badge.
 *
 * `value === null` means the detector is deliberately unscored. That is
 * rendered as the words "unscored" rather than as an empty bar at zero,
 * because zero reads as a score and "unscored" is what it is.
 */
export function Confidence({ value }: { readonly value: number | null }): JSX.Element {
  if (value === null) {
    return (
      <span className="inf-conf inf-conf--unscored" title="The platform does not score this detector">
        unscored
      </span>
    );
  }
  return (
    <span className="inf-conf">
      <span
        className="inf-conf__track"
        role="img"
        aria-label={`Confidence ${formatPercent(value)}`}
      >
        <span className="inf-conf__fill" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="inf-conf__value">{formatPercent(value)}</span>
    </span>
  );
}

// --- per-channel breakdown -------------------------------------------------

/** The order the library weights the channels in, and how they are labelled. */
const CHANNELS: ReadonlyArray<{ readonly key: keyof InfraChannelScores; readonly label: string }> = [
  { key: 'certificate', label: 'certificate' },
  { key: 'content', label: 'content' },
  { key: 'http', label: 'http' },
  { key: 'tls', label: 'tls' },
  { key: 'technology', label: 'tech' },
  { key: 'temporal', label: 'temporal' },
];

function isChannelScore(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * The per-channel scores as a small bar set.
 *
 * Three things this refuses to do, each of which would misrepresent the
 * data:
 *
 * - draw an unobserved channel as a zero-length bar, which would count a
 *   missing measurement as evidence against the correlation;
 * - omit a channel that was simply not captured, which would make the
 *   breakdown look like corroboration by silence;
 * - leave a decisive channel indistinguishable from a merely high one, when
 *   the difference between them is the difference between a weak finding and
 *   a strong one.
 */
export function ChannelBars({
  breakdown,
  strongestChannel,
}: {
  readonly breakdown: InfraChannelScores;
  readonly strongestChannel: string | null;
}): JSX.Element {
  const decisive = new Set(breakdown.decisive_channels);
  return (
    <div className="inf-channels">
      {CHANNELS.map(({ key, label }) => {
        const score = breakdown[key];
        const present = isChannelScore(score);
        const carried = decisive.has(label) || decisive.has(key);
        return (
          <div
            key={key}
            className={cx(
              'inf-channel',
              carried && 'inf-channel--decisive',
              !present && 'inf-channel--absent',
            )}
          >
            <span className="inf-channel__name">
              {carried ? `${label} •` : label}
              {carried && <span className="sr-only"> (decisive channel)</span>}
            </span>
            <span
              className="inf-channel__track"
              role="img"
              aria-label={
                present
                  ? `${label}: ${formatPercent(score)}${carried ? ', decisive' : ''}`
                  : `${label}: not observed on both sides`
              }
            >
              {present && (
                <span
                  className="inf-channel__fill"
                  style={{ width: `${Math.round(Math.min(1, Math.max(0, score)) * 100)}%` }}
                />
              )}
            </span>
            <span className="inf-channel__value">
              {present ? formatPercent(score) : 'n/o'}
            </span>
          </div>
        );
      })}
      {strongestChannel !== null && (
        <span className="inf-caption">
          strongest: <strong>{strongestChannel}</strong>
        </span>
      )}
    </div>
  );
}

// --- corroboration ---------------------------------------------------------

/**
 * Whether a match rests on one dimension or several.
 *
 * This is the honest headline for a correlation table and it is given its own
 * cell rather than being left to the reader to infer from the bar lengths. A
 * 0.92 carried entirely by a shared certificate fingerprint is not the same
 * finding as one corroborated across certificate, TLS and content, and the
 * two must not read alike.
 */
export function Corroboration({
  decisiveChannels,
}: {
  readonly decisiveChannels: readonly string[];
}): JSX.Element {
  if (decisiveChannels.length <= 1) {
    return (
      <span
        className="inf-weak"
        title="Every channel except one failed to reach its cutoff. One dimension is not corroboration."
      >
        single channel
      </span>
    );
  }
  return (
    <span
      className="inf-strong"
      title={`${decisiveChannels.length} channels cleared their own cutoff: ${decisiveChannels.join(', ')}`}
    >
      {decisiveChannels.length} channels
    </span>
  );
}

// --- key/value -------------------------------------------------------------

export function KeyValue({
  items,
}: {
  readonly items: ReadonlyArray<{ readonly key: string; readonly value: JSX.Element | string }>;
}): JSX.Element {
  return (
    <dl className="inf-kv">
      {items.map((item) => (
        <div className="inf-kv__row" key={item.key}>
          <dt className="inf-kv__key">{item.key}</dt>
          <dd className="inf-kv__value">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
