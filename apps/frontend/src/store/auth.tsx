import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  api, clearSessionToken, getSession, getSessionExpiry, onUnauthorized, peekSession, setSessionToken,
} from '../api/client';

export interface Identity {
  readonly email: string;
  readonly name: string;
  readonly role: string;
  readonly organization: string;
}

type SessionState = 'unauthenticated' | 'authenticating' | 'authenticated' | 'expired';

interface AuthContextValue {
  readonly authenticated: boolean;
  readonly busy: boolean;
  readonly error: string | null;
  readonly identity: Identity | null;
  readonly signIn: (email: string, password: string, remember?: boolean) => Promise<boolean>;
  readonly sessionNotice: string | null;
  readonly signOut: () => void;
  /** Drives the "session ends in mm:ss" readout and the re-auth countdown. */
  readonly sessionExpiresAt: number | null;
  readonly sessionState: SessionState;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const EXPIRY_NOTICE = 'Your analyst session has expired. Sign in again.';
const MISSING_CREDENTIALS = 'Authentication is required to access AEGIS.';

/** How often the countdown re-renders while a session is live. */
const COUNTDOWN_INTERVAL_MS = 1_000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [busy, setBusy] = useState(() => Boolean(getSession()));
  const [error, setError] = useState<string | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  const [sessionExpiresAt, setSessionExpiresAt] = useState<number | null>(getSessionExpiry);
  // Re-render once a second so the remaining-session readout stays accurate.
  const [, setTick] = useState(0);

  const expireSession = useCallback((message: string) => {
    clearSessionToken();
    setAuthenticated(false);
    setIdentity(null);
    setSessionExpiresAt(null);
    setSessionNotice(message);
  }, []);

  useEffect(() => {
    onUnauthorized((reason) => {
      expireSession(reason === 'expired' ? EXPIRY_NOTICE : MISSING_CREDENTIALS);
    });
    return () => onUnauthorized(null);
  }, [expireSession]);

  useEffect(() => {
    if (sessionExpiresAt === null) return;
    const timer = window.setInterval(() => setTick((value) => value + 1), COUNTDOWN_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [sessionExpiresAt]);

  useEffect(() => {
    // Read the raw envelope first: `getSession()` clears an expired token, and
    // that would make "the session ran out" indistinguishable from "never
    // signed in" — leaving the analyst on a blank form with no explanation.
    const stored = peekSession();
    const session = getSession();
    if (!session) {
      // `getSession()` only reports; removal happens here, where we know
      // whether an expired token or no token at all was found.
      if (stored !== null) expireSession(EXPIRY_NOTICE);
      return;
    }
    setBusy(true);
    void api.authMe()
      .then((profile) => {
        setIdentity(profile);
        setSessionExpiresAt(session.expiresAt === 0 ? null : session.expiresAt);
        setAuthenticated(true);
      })
      .catch(() => expireSession(EXPIRY_NOTICE))
      .finally(() => setBusy(false));
  }, [expireSession]);

  const signIn = useCallback(async (email: string, password: string, remember = false) => {
    const trimmed = email.trim();
    if (!trimmed || !password) {
      setError('Enter your corporate email and password.');
      return false;
    }
    setBusy(true);
    setError(null);
    setSessionNotice(null);
    try {
      const result = await api.login(trimmed, password);
      setSessionToken(result.access_token, result.expires_at * 1000, remember);
      setSessionExpiresAt(result.expires_at * 1000);
      setIdentity(result.identity);
      setAuthenticated(true);
      return true;
    } catch {
      clearSessionToken();
      setAuthenticated(false);
      setIdentity(null);
      setSessionExpiresAt(null);
      setError('Sign-in failed. Verify your corporate credentials or contact your administrator.');
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const signOut = useCallback(() => {
    clearSessionToken();
    setAuthenticated(false);
    setIdentity(null);
    setSessionExpiresAt(null);
    setError(null);
  }, []);

  const sessionState: SessionState = busy
    ? 'authenticating'
    : authenticated ? 'authenticated' : sessionNotice ? 'expired' : 'unauthenticated';

  const value = useMemo(
    () => ({ authenticated, busy, error, identity, sessionNotice, signIn, signOut, sessionExpiresAt, sessionState }),
    [authenticated, busy, error, identity, sessionNotice, signIn, signOut, sessionExpiresAt, sessionState],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.');
  return value;
}
