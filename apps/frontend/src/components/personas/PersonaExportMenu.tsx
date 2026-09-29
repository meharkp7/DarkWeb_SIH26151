/**
 * Export the register under the filters currently applied.
 *
 * A plain `<a download>` cannot set an `Authorization` header, so the export is
 * fetched with the session headers and saved as a blob — the same reasoning as
 * the case export menu. The JSON form carries the server's summary alongside
 * the rows, which is why it is the one worth handing to someone: a register
 * exported without its observed error rate invites the reader to assume the
 * model was right about every row in the file.
 */

import { useCallback, useState } from 'react';

import { api, authHeaders, formatApiError } from '../../api/client';
import type { PersonaFilters } from '../../api/types';

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoked on the next tick: Safari aborts a download whose object URL
  // disappears synchronously after the click.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export interface PersonaExportMenuProps {
  readonly filters: PersonaFilters | undefined;
  readonly disabled?: boolean;
  readonly rowCount: number;
}

export function PersonaExportMenu({ filters, disabled = false, rowCount }: PersonaExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<null | 'csv' | 'json'>(null);
  const [error, setError] = useState<string | null>(null);

  const download = useCallback(
    async (format: 'csv' | 'json') => {
      setBusy(format);
      setError(null);
      try {
        const response = await fetch(api.personaExportUrl(format, filters), {
          headers: authHeaders(),
        });
        if (!response.ok) throw new Error(`Export failed (${response.status})`);
        saveBlob(await response.blob(), `aegis-persona-linkages.${format}`);
        setOpen(false);
      } catch (caught) {
        setError(formatApiError(caught));
      } finally {
        setBusy(null);
      }
    },
    [filters],
  );

  return (
    <div className="per-export">
      <button
        type="button"
        className="per-btn"
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={disabled || busy !== null}
        onClick={() => setOpen((value) => !value)}
      >
        Export
      </button>
      {open ? (
        <div className="per-export__menu" role="menu">
          <p className="per-export__note">
            {formatCountRows(rowCount)} under the filters above.
          </p>
          <button
            type="button"
            role="menuitem"
            className="per-export__item"
            disabled={busy !== null}
            onClick={() => void download('json')}
          >
            {busy === 'json' ? 'Preparing…' : 'JSON — rows plus the observed error rate'}
          </button>
          <button
            type="button"
            role="menuitem"
            className="per-export__item"
            disabled={busy !== null}
            onClick={() => void download('csv')}
          >
            {busy === 'csv' ? 'Preparing…' : 'CSV — one row per linkage'}
          </button>
          {error ? (
            <p className="per-error" role="alert">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function formatCountRows(value: number): string {
  return `${value} ${value === 1 ? 'linkage' : 'linkages'}`;
}
