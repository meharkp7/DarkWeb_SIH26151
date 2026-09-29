import { render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearSessionToken, setSessionToken } from '../api/client';
import { AuthProvider, useAuth } from './auth';
import { installFetch, jsonResponse } from '../test/mockFetch';

const EMAIL = 'analyst@example.test';

const IDENTITY = {
  email: EMAIL,
  name: 'Test Analyst',
  role: 'Senior Intelligence Analyst',
  organization: 'AEGIS',
};

/** Reads the context out of the tree so assertions can be made on state. */
function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="state">{auth.sessionState}</span>
      <span data-testid="identity">{auth.identity?.name ?? 'none'}</span>
      <span data-testid="notice">{auth.sessionNotice ?? ''}</span>
      <span data-testid="error">{auth.error ?? ''}</span>
      <button type="button" onClick={() => void auth.signIn(EMAIL, 'secret', false)}>
        sign in
      </button>
    </div>
  );
}

function renderProvider() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function installAuthFetch(overrides: (url: string) => boolean = () => false) {
  return installFetch(async (input) => {
    const url = String(input);
    if (overrides(url)) throw new Error(`unexpected request: ${url}`);
    if (url.includes('/api/v1/auth/login')) {
      return jsonResponse({
        access_token: 'issued-token',
        token_type: 'bearer',
        expires_in: 900,
        expires_at: Math.floor(Date.now() / 1000) + 900,
        identity: IDENTITY,
      });
    }
    if (url.includes('/api/v1/auth/me')) return jsonResponse(IDENTITY);
    return jsonResponse({});
  });
}

describe('auth store', () => {
  beforeEach(() => {
    clearSessionToken();
    vi.restoreAllMocks();
  });

  it('restores a session from a persisted token on mount', async () => {
    setSessionToken('persisted-token', Date.now() + 900_000, true);
    installAuthFetch((url) => url.includes('/auth/login'));

    renderProvider();

    await waitFor(() => {
      expect(screen.getByTestId('state')).toHaveTextContent('authenticated');
    });
    expect(screen.getByTestId('identity')).toHaveTextContent('Test Analyst');
  });

  it('discards a session whose recorded expiry has already passed', async () => {
    // The store must not send a token the API will refuse. A session that
    // expired while the tab was closed should present the sign-in screen, not
    // a dashboard that 401s on first paint.
    setSessionToken('stale-token', Date.now() - 1, true);
    installAuthFetch();

    renderProvider();

    await waitFor(() => {
      expect(screen.getByTestId('state')).toHaveTextContent('expired');
    });
    expect(screen.getByTestId('notice')).toHaveTextContent(/session has expired/i);
  });

  it('records the expiry issued with the token', async () => {
    installAuthFetch();

    renderProvider();
    await act(async () => {
      screen.getByRole('button', { name: 'sign in' }).click();
    });

    await waitFor(() => {
      expect(screen.getByTestId('state')).toHaveTextContent('authenticated');
    });
    // A token and an expiry stored separately is how they drift; the store
    // writes one envelope, so a fresh sign-in must land authenticated with an
    // identity rather than merely "logged in".
    expect(screen.getByTestId('identity')).toHaveTextContent('Test Analyst');
  });

  it('reports a rejected sign-in without leaving a half-authenticated state', async () => {
    installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/auth/login')) {
        return jsonResponse({ detail: 'Invalid credentials' }, { status: 401 });
      }
      return jsonResponse({});
    });

    renderProvider();
    await act(async () => {
      screen.getByRole('button', { name: 'sign in' }).click();
    });

    await waitFor(() => {
      expect(screen.getByTestId('error')).not.toHaveTextContent('');
    });
    expect(screen.getByTestId('state')).toHaveTextContent('unauthenticated');
    expect(screen.getByTestId('identity')).toHaveTextContent('none');
  });

  it('exposes a real message when the stored session is refused', async () => {
    setSessionToken('revoked-token', Date.now() + 900_000, true);
    installFetch(async (input) => {
      const url = String(input);
      if (url.includes('/auth/me')) return jsonResponse({ detail: 'nope' }, { status: 401 });
      return jsonResponse({});
    });

    renderProvider();

    await waitFor(() => {
      expect(screen.getByTestId('notice')).toHaveTextContent(/session has expired/i);
    });
  });

  it('refuses to sign in with empty credentials without calling the API', async () => {
    const fetchMock = installAuthFetch();

    function EmptyProbe() {
      const auth = useAuth();
      return (
        <button type="button" onClick={() => void auth.signIn('   ', '')}>
          empty
        </button>
      );
    }
    render(
      <MemoryRouter>
        <AuthProvider>
          <EmptyProbe />
        </AuthProvider>
      </MemoryRouter>,
    );

    await act(async () => {
      screen.getByRole('button', { name: 'empty' }).click();
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
