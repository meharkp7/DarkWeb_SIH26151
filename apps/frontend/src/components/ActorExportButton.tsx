import { useCallback, useEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { ApiError, api, authHeaders, formatApiError } from '../api/client';
import type { ActorQuery } from '../api/types';

const FORMATS = [
  { key: 'csv', label: 'CSV ledger', hint: 'One row per actor, with identifier and venue counts.' },
  { key: 'json', label: 'JSON structured', hint: 'The full result set, with the filters and the totals that produced it.' },
  { key: 'stix', label: 'STIX 2.1 exchange', hint: 'One threat-actor object per row, for sharing.' },
] as const;

type ExportFormat = (typeof FORMATS)[number]['key'];

export interface ActorExportButtonProps {
  /**
   * The filters currently applied to the register.
   *
   * Passed in rather than read from the URL inside this component, because the
   * export must carry the *active* filters: a file that silently contains the
   * whole registry while the analyst was looking at twelve actors is worse than
   * no export at all.
   */
  readonly filters?: ActorQuery;
}

/**
 * Inline export control for the actor registry.
 *
 * The same popover pattern the case export menu uses — an action taken on a
 * result set rather than a page to navigate to — and the same reason the
 * download is fetched rather than linked: an `<a download>` cannot carry an
 * `Authorization` header, so it would be refused by every route behind the API
 * base.
 */
export function ActorExportButton({ filters }: ActorExportButtonProps) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>('csv');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const formatGroupRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);

  const close = useCallback(() => setOpen(false), []);
  const onClose = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const trigger = triggerRef.current;
    panelRef.current?.querySelector<HTMLElement>('input, button')?.focus();
    return () => {
      trigger?.focus();
    };
  }, [open]);

  // Escape closes from anywhere; an outside pointer press closes too.
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      onClose();
    };
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (target === null) return;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      close();
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousedown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('mousedown', onPointerDown);
    };
  }, [open, onClose, close]);

  const onPanelKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab') return;
    const panel = panelRef.current;
    if (panel === null) return;
    const stops = Array.from(
      panel.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])'),
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (stops.length === 0) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }, []);

  // Arrow keys move within the radio group, as a radio group should.
  const onFormatKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    const forward = event.key === 'ArrowDown' || event.key === 'ArrowRight';
    const backward = event.key === 'ArrowUp' || event.key === 'ArrowLeft';
    if (!forward && !backward) return;
    const group = formatGroupRef.current;
    if (group === null) return;
    const radios = Array.from(group.querySelectorAll<HTMLInputElement>('input[type="radio"]'));
    if (radios.length === 0) return;
    const current = radios.findIndex((radio) => radio === document.activeElement);
    const base = current === -1 ? 0 : current;
    const next = forward ? (base + 1) % radios.length : (base - 1 + radios.length) % radios.length;
    const target = radios[next];
    if (target === undefined) return;
    event.preventDefault();
    // State is set directly rather than by dispatching a change event: React
    // controls these radios, so its own value tracker would swallow a synthetic
    // event and the arrow would move focus without moving selection.
    setFormat(target.value as ExportFormat);
    target.focus();
  }, []);

  const runExport = useCallback(async () => {
    // A ref as well as state: a second click can land before React re-renders
    // the disabled button, and two downloads of the same file is a bug.
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(api.actorExportUrl(format, filters), { headers: authHeaders() });
      if (!response.ok) {
        let detail = response.statusText || 'Export failed';
        try {
          const body = (await response.json()) as { detail?: unknown };
          if (typeof body.detail === 'string') detail = body.detail;
        } catch {
          /* keep the status text */
        }
        throw new ApiError(response.status, detail);
      }
      saveBlob(await response.blob(), `aegis-actor-registry.${format}`);
      onClose();
    } catch (reason: unknown) {
      // The popover stays open on failure so a format can be changed or the
      // export retried without reopening it.
      setError(formatApiError(reason));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [filters, format, onClose]);

  return (
    <div className="act-exp">
      <button
        ref={triggerRef}
        type="button"
        className="act-exp__trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="actor-export-popover"
        onClick={open ? onClose : () => { setError(null); setOpen(true); }}
      >
        Export registry
        <span aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div
          ref={panelRef}
          id="actor-export-popover"
          className="act-exp__panel"
          role="dialog"
          aria-label="Export the actor registry"
          onKeyDown={onPanelKeyDown}
        >
          <p className="act-exp__label">Format</p>
          <div
            ref={formatGroupRef}
            className="act-exp__formats"
            role="radiogroup"
            aria-label="Export format"
            onKeyDown={onFormatKeyDown}
          >
            {FORMATS.map((item) => (
              <label className="act-exp__format" key={item.key}>
                <input
                  type="radio"
                  name="actor-export-format"
                  value={item.key}
                  checked={format === item.key}
                  onChange={() => setFormat(item.key)}
                />
                <span>
                  <span>{item.label}</span>
                  <span className="act-exp__hint">{item.hint}</span>
                </span>
              </label>
            ))}
          </div>
          <p className="act-exp__note">
            The export carries the filters currently applied to the register, not the whole registry.
          </p>
          {error !== null && (
            <p className="act-exp__error" role="alert">
              {error}
            </p>
          )}
          <button
            type="button"
            className="act-exp__action"
            onClick={() => void runExport()}
            disabled={busy}
          >
            {busy ? 'Preparing…' : 'Export result set'}
          </button>
        </div>
      )}
    </div>
  );
}

/** Save a fetched response as a file without ever exposing the token to a URL. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on the next tick: Safari aborts the download if the object URL
  // disappears synchronously after the click.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}