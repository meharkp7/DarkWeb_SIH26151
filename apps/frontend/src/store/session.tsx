import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { CreatedSource, Evidence, SourceTier, SyntheticAnalysisResponse } from '../api/types';

/** A source registered this session, plus the tier submitted with it. */
export interface RegisteredSource extends CreatedSource {
  /** The API response does not echo the tier, so we remember what was sent. */
  readonly tier: SourceTier;
}


/**
 * Client-side session store.
 *
 * The backend exposes no list endpoints yet (`GET /api/v1/evidence`,
 * `GET /api/v1/cases`, `GET /api/v1/sources` do not exist), so records the
 * analyst creates or fetches during this browser session are kept here so the
 * evidence table, timeline, graph and report draft can render real data.
 * Everything is labelled "this session" in the UI — nothing is persisted.
 */
export interface SessionStore {
  readonly evidence: Evidence[];
  readonly rememberEvidence: (record: Evidence) => void;
  readonly sources: RegisteredSource[];
  readonly rememberSource: (source: RegisteredSource) => void;
  readonly analysis: SyntheticAnalysisResponse | null;
  readonly setAnalysis: (analysis: SyntheticAnalysisResponse) => void;
}

const SessionContext = createContext<SessionStore | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [sources, setSources] = useState<RegisteredSource[]>([]);
  const [analysis, setAnalysis] = useState<SyntheticAnalysisResponse | null>(null);

  const rememberEvidence = useCallback((record: Evidence) => {
    setEvidence((current) => {
      const withoutDuplicate = current.filter(
        (item) => item.evidence_id !== record.evidence_id,
      );
      return [record, ...withoutDuplicate];
    });
  }, []);

  const rememberSource = useCallback((source: RegisteredSource) => {
    setSources((current) => {
      const withoutDuplicate = current.filter((item) => item.source_id !== source.source_id);
      return [...withoutDuplicate, source];
    });
  }, []);

  const value = useMemo<SessionStore>(
    () => ({ evidence, rememberEvidence, sources, rememberSource, analysis, setAnalysis }),
    [evidence, rememberEvidence, sources, rememberSource, analysis],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionStore {
  const store = useContext(SessionContext);
  if (store === null) {
    throw new Error('useSession must be used inside <SessionProvider>.');
  }
  return store;
}
