/**
 * The register, fetched with one filter set and a hand-triggered reload.
 *
 * Two behaviours `useApi` does not provide, and both are needed here:
 *
 * 1. **A reload after an adjudication.** The summary's observed-error pair is
 *    server-computed, so a local update of the row would leave the block beside
 *    it describing a view that no longer exists. `reload()` refetches both.
 * 2. **A ruling applied from the response, not from the click.** `applyServerRow`
 *    writes the row the server returned, so the register reflects the stored
 *    record the instant the response lands, and the refetch that follows can
 *    only confirm it.
 *
 * The effect is keyed on the serialised filter object rather than the object
 * itself, so a parent that rebuilds the filters on every render does not refetch
 * in a loop. Whether this is the first read is held in a ref for the same
 * reason — putting it in the dependency list would restart the effect on every
 * successful read.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api, formatApiError } from '../../api/client';
import type { PersonaFilters, PersonaLinkage, PersonaLinkageCounts } from '../../api/types';

export interface PersonaRegister {
  readonly rows: readonly PersonaLinkage[];
  readonly summary: PersonaLinkageCounts | null;
  /** True only before the first successful read, so a refetch does not flash. */
  readonly loading: boolean;
  readonly error: string | null;
  /** Write the server's own copy of a row, then refresh the counts. */
  readonly applyServerRow: (linkage: PersonaLinkage) => void;
  readonly reload: () => void;
}

export function usePersonaRegister(filters: PersonaFilters | undefined): PersonaRegister {
  const [rows, setRows] = useState<readonly PersonaLinkage[]>([]);
  const [summary, setSummary] = useState<PersonaLinkageCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [overrides, setOverrides] = useState<Record<string, PersonaLinkage>>({});
  const filterKey = JSON.stringify(filters ?? null);
  const lastFilterKey = useRef('');
  const everLoaded = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    const filterChanged = lastFilterKey.current !== filterKey;
    if (filterChanged) {
      lastFilterKey.current = filterKey;
      // Rulings recorded under the previous filters say nothing about this view.
      setOverrides({});
    }
    if (filterChanged || !everLoaded.current) setLoading(true);

    Promise.all([
      api.personaLinkages(filters, controller.signal),
      api.personaLinkageSummary(filters, controller.signal),
    ])
      .then(([list, counts]) => {
        if (cancelled) return;
        everLoaded.current = true;
        setRows(list);
        setSummary(counts);
        setLoading(false);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setLoading(false);
        setError(formatApiError(caught));
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // `filters` is deliberately absent: `filterKey` is its stable identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, nonce]);

  const visible = useMemo(
    () => rows.map((row) => overrides[row.linkage_id] ?? row),
    [overrides, rows],
  );

  const applyServerRow = useCallback((linkage: PersonaLinkage) => {
    setOverrides((previous) => ({ ...previous, [linkage.linkage_id]: linkage }));
    // The counts are the server's, and the pair in them has to move when a
    // ruling does.
    setNonce((value) => value + 1);
  }, []);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { rows: visible, summary, loading, error, applyServerRow, reload };
}
