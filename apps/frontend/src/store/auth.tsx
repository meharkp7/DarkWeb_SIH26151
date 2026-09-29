import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api, clearSessionToken, getSessionToken, onUnauthorized, setSessionToken } from '../api/client';

export interface Identity {
  readonly email: string;
  readonly name: string;
  readonly role: string;
  readonly organization: string;
}

interface AuthContextValue {
  readonly authenticated: boolean;
  readonly busy: boolean;
  readonly error: string | null;
  readonly identity: Identity | null;
  readonly signIn: (email: string, password: string, remember?: boolean) => Promise<boolean>;
  readonly sessionNotice: string | null;
  readonly signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [busy, setBusy] = useState(() => Boolean(getSessionToken()));
  const [error, setError] = useState<string | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  const expireSession = useCallback((message: string) => {
    clearSessionToken();
    setAuthenticated(false);
    setIdentity(null);
    setSessionNotice(message);
  }, []);

  useEffect(() => {
    onUnauthorized((reason) => {
      expireSession(
        reason === 'expired'
          ? 'Your analyst session has expired. Sign in again.'
          : 'Authentication is required to access AEGIS.',
      );
    });
    return () => onUnauthorized(null);
  }, [expireSession]);

  useEffect(() => {
    const token = getSessionToken();
    if (!token) return;
    setBusy(true);
    void api.authMe()
      .then((profile) => {
        setIdentity(profile);
        setAuthenticated(true);
      })
      .catch(() => expireSession('Your analyst session has expired. Sign in again.'))
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
      setSessionToken(result.access_token, remember);
      setIdentity(result.identity);
      setAuthenticated(true);
      return true;
    } catch {
      clearSessionToken();
      setAuthenticated(false);
      setIdentity(null);
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
    setError(null);
  }, []);

  const value = useMemo(
    () => ({ authenticated, busy, error, identity, sessionNotice, signIn, signOut }),
    [authenticated, busy, error, identity, sessionNotice, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.');
  return value;
}
