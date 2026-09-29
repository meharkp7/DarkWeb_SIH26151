import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { ApiError, api, apiUrl, authHeaders, formatApiError } from '../api/client';
import type { CaseQueueEntry } from '../api/types';
import { useApi } from '../hooks/useApi';

/**
 * Inline export control for a case.
 *
 * Exporting is an action taken *on* an investigation, not a place to go, so
 * this is a popover anchored to a toolbar button rather than a route. The
 * download is fetched with `authHeaders` and saved as a Blob: a plain
 * `<a href download>` navigation cannot set an `Authorization` header, so it
 * would be refused by every route behind the API base.
 */

/** Formats the export route actually supports (see `api.reportExportUrl`). */
const FORMATS = [
  { key: 'pdf', label: 'PDF briefing', hint: 'Formatted analyst brief with evidence citations.' },
  { key: 'json', label: 'JSON structured', hint: 'Machine-readable evidence and provenance package.' },
  { key: 'csv', label: 'CSV ledger', hint: 'Flat evidence matrix, one row per cited claim.' },
  { key: 'stix', label: 'STIX 2.1 exchange', hint: 'Structured threat-intelligence bundle for sharing.' },
] as const;

type ExportFormat = (typeof FORMATS)[number]['key'];

const ALL_CASES = '__all__';

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
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

export interface CaseExportMenuProps {
  /** The case the menu was opened from; the selector defaults to it. */
  readonly caseId: string;
}

export function CaseExportMenu({ caseId }: CaseExportMenuProps) {
  const { data: cases } = useApi<CaseQueueEntry[]>(apiUrl('/v1/dashboard/cases'));
  const list = useMemo(() => cases ?? [], [cases]);

  const [open, setOpen] = useState(false);
  // An empty `caseId` means no single case is in focus (the register header),
  // so the selector starts on "All investigations" rather than on nothing.
  const [selected, setSelected] = useState<string>(caseId === '' ? ALL_CASES : caseId);
  const [format, setFormat] = useState<ExportFormat>('pdf');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const formatGroupRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);

  // The selector follows the case the menu was opened from unless the analyst
  // has deliberately chosen another (or "All").
  useEffect(() => {
    setSelected(caseId === '' ? ALL_CASES : caseId);
  }, [caseId]);

  const close = useCallback(() => setOpen(false), []);

  const openPanel = useCallback(() => {
    setError(null);
    setOpen(true);
  }, []);

  const onClose = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  // Move focus into the popover on open; restore it to the trigger on close.
  useEffect(() => {
    if (!open) return undefined;
    // Captured once: the trigger node cannot change while the popover is open,
    // and the cleanup below must return focus to the node that opened it.
    const trigger = triggerRef.current;
    const first = panelRef.current?.querySelector<HTMLElement>('select, button, input');
    first?.focus();
    return () => {
      trigger?.focus();
    };
  }, [open]);

  // Escape closes from anywhere; an outside pointer press closes too.
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
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

  // Hold Tab inside the popover while it is open.
  const onPanelKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'Tab') return;
      const panel = panelRef.current;
      if (panel === null) return;
      const focusables = Array.from(
        panel.querySelectorAll<HTMLElement>('button:not([disabled]), select:not([disabled]), input:not([disabled])'),
      ).filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    },
    [],
  );

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
    // Set state directly rather than dispatching a `change` event: React
    // controls these radios, so its own value tracker would ignore a
    // synthetic event and the arrow would move focus without moving selection.
    setFormat(target.value as ExportFormat);
    target.focus();
  }, []);

  const download = useCallback(async (format: ExportFormat, targetId: string, name: string) => {
    const response = await fetch(api.reportExportUrl(targetId, format), { headers: authHeaders() });
    if (!response.ok) {
      // The API explains refusals in `detail`; the status line alone ("Service
      // Unavailable") tells the analyst nothing about what to do next.
      let detail = response.statusText || 'Export failed';
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        /* keep the status text */
      }
      throw new ApiError(response.status, detail);
    }
    const blob = await response.blob();
    saveBlob(blob, `aegis-${slug(name) || targetId}.${format}`);
  }, []);

  const runExport = useCallback(async () => {
    // A ref, not just state: a second click can land before React re-renders
    // the disabled button, and two downloads of the same case is a bug.
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      if (selected === ALL_CASES) {
        if (list.length === 0) throw new Error('No investigations are available to export.');
        for (const entry of list) {
          await download(format, entry.case_id, entry.name);
        }
      } else {
        const entry = list.find((item) => item.case_id === selected);
        await download(format, selected, entry?.name ?? selected);
      }
      onClose();
    } catch (reason: unknown) {
      // The popover stays open on failure so the analyst can pick another
      // format or retry without reopening it.
      setError(formatApiError(reason));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [download, format, list, onClose, selected]);

  return (
    <div className="exp-menu">
      <button
        ref={triggerRef}
        type="button"
        className="exp-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="case-export-popover"
        onClick={open ? onClose : openPanel}
      >
        Export
        <span className="exp-trigger__chevron" aria-hidden="true">
          {open ? '▴' : '▾'}
        </span>
      </button>

      {open && (
        <div
          ref={panelRef}
          id="case-export-popover"
          className="exp-popover"
          role="dialog"
          aria-label="Export investigation report"
          onKeyDown={onPanelKeyDown}
        >
          <div className="exp-popover__field">
            <label className="exp-label" htmlFor="exp-case">
              Case
            </label>
            <select
              id="exp-case"
              className="exp-select"
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
            >
              <option value={ALL_CASES}>All investigations</option>
              {list.map((item) => (
                <option key={item.case_id} value={item.case_id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>

          <div
            ref={formatGroupRef}
            className="exp-formats"
            role="radiogroup"
            aria-label="Export format"
            onKeyDown={onFormatKeyDown}
          >
            {FORMATS.map((item) => (
              <label className="exp-format" key={item.key}>
                <input
                  type="radio"
                  name="exp-format"
                  value={item.key}
                  checked={format === item.key}
                  onChange={() => setFormat(item.key)}
                />
                <span className="exp-format__text">
                  <span className="exp-format__label">{item.label}</span>
                  <span className="exp-format__hint">{item.hint}</span>
                </span>
              </label>
            ))}
          </div>

          {error !== null && (
            <p className="exp-error" role="alert">
              {error}
            </p>
          )}

          <button
            type="button"
            className="exp-action"
            onClick={() => void runExport()}
            disabled={busy}
          >
            {busy ? 'Preparing…' : 'Export report'}
          </button>
        </div>
      )}
    </div>
  );
}
