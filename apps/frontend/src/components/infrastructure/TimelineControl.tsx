import type { ChangeEvent } from 'react';

const WINDOWS: ReadonlyArray<{ readonly label: string; readonly days: number }> = [
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 90 days', days: 90 },
  { label: 'Last 365 days', days: 365 },
  { label: 'All time', days: 0 },
];

function isoDay(offsetDays: number): string {
  const date = new Date();
  date.setDate(date.getDate() - offsetDays);
  return date.toISOString().slice(0, 10);
}

/**
 * The global timeline control, present on all three tabs.
 *
 * The problem statement requires querying across a chosen window, so this is
 * persistent chrome rather than a per-tab control. It drives `from`/`until`
 * in the address bar, which means a particular window can be linked or
 * handed over as a URL instead of retyped.
 *
 * The presets are a convenience over the two date inputs, never a replacement
 * for them: picking "Last 30 days" writes the same two parameters an analyst
 * would have written by hand.
 */
export function TimelineControl({
  from,
  until,
  onChange,
}: {
  readonly from: string;
  readonly until: string;
  readonly onChange: (next: { from: string; until: string }) => void;
}): JSX.Element {
  const activePreset = WINDOWS.find((window) => {
    if (window.days === 0) return from === '' && until === '';
    return until === '' && from === isoDay(window.days);
  });

  const applyPreset = (event: ChangeEvent<HTMLSelectElement>): void => {
    const days = Number(event.target.value);
    onChange(days === 0 ? { from: '', until: '' } : { from: isoDay(days), until: '' });
  };

  return (
    <div className="inf-timeline">
      <span className="inf-timeline__label" id="inf-timeline-label">
        Timeline
      </span>
      <div className="inf-field">
        <label className="inf-field__label" htmlFor="inf-timeline-preset">
          Window
        </label>
        <select
          id="inf-timeline-preset"
          value={activePreset === undefined ? 'custom' : String(activePreset.days)}
          onChange={applyPreset}
        >
          {activePreset === undefined && <option value="custom">Custom range</option>}
          {WINDOWS.map((window) => (
            <option key={window.label} value={String(window.days)}>
              {window.label}
            </option>
          ))}
        </select>
      </div>
      <div className="inf-field">
        <label className="inf-field__label" htmlFor="inf-timeline-from">
          From
        </label>
        <input
          id="inf-timeline-from"
          type="date"
          value={from}
          onChange={(event) => onChange({ from: event.target.value, until })}
        />
      </div>
      <div className="inf-field">
        <label className="inf-field__label" htmlFor="inf-timeline-until">
          Until
        </label>
        <input
          id="inf-timeline-until"
          type="date"
          value={until}
          onChange={(event) => onChange({ from, until: event.target.value })}
        />
      </div>
      {(from !== '' || until !== '') && (
        <button
          type="button"
          className="inf-btn"
          onClick={() => onChange({ from: '', until: '' })}
        >
          Clear window
        </button>
      )}
    </div>
  );
}
