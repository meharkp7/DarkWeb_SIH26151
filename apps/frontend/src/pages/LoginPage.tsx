import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useAuth } from '../store/auth';

/**
 * What the sign-in screen shows in place of live figures.
 *
 * This panel is rendered before the analyst has a credential, so it cannot
 * read the ledger — and a previous version filled the gap with invented case
 * IDs, invented confidence scores and invented record counts. That is worse
 * than an empty panel: "Operation Nightfall" is a real case in the seeded
 * dataset, so the screen was asserting a 94% attribution that no assessment
 * had ever produced. A fabricated number on an unauthenticated screen is the
 * one place it is guaranteed to be believed.
 *
 * So the board states what the platform does rather than how much data it
 * currently holds. Every figure on the other side of this gate is read from
 * the API.
 */
const CAPABILITIES = [
  {
    id: 'ATTRIBUTION',
    name: 'Evidence-linked attribution',
    detail: 'Hypotheses carry citations, contradictions and a stated limit',
    tone: 'critical',
  },
  {
    id: 'PROVENANCE',
    name: 'Immutable evidence ledger',
    detail: 'Hash-chained audit trail, full derivation chain per record',
    tone: 'high',
  },
  {
    id: 'CONTEXT',
    name: 'Case-scoped relationship graph',
    detail: 'Every edge resolves to the evidence that established it',
    tone: 'watch',
  },
] as const;

export function LoginPage() {
  const { signIn, busy, error, sessionNotice, sessionState } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);

  const describedBy = error !== null ? 'auth-error' : sessionNotice !== null ? 'auth-notice' : undefined;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void signIn(email, password, remember);
  };

  return (
    <main className="enterprise-auth enterprise-auth--v2">
      <section className="auth-command-view" aria-hidden="true">
        <div className="auth-command-top">
          <div className="auth-logo-lockup"><span>◇</span><div><strong>AEGIS</strong><small>INTELLIGENCE GROUP</small></div></div>
          <span className="auth-classification">CONTROLLED / ANALYST ACCESS</span>
        </div>

        <div className="auth-command-copy">
          <span className="eyebrow">Intelligence operations platform</span>
          <h2>One workspace for<br /><em>evidence-led decisions.</em></h2>
          <p>Investigations, evidence provenance, relationship analysis and attribution assessments in one controlled operating environment.</p>
        </div>

        <div className="auth-command-board">
          <div className="auth-board-head"><span>PLATFORM CAPABILITIES</span><b>NO FIGURES SHOWN PRE-AUTH</b></div>
          <div className="auth-queue-lines">
            {CAPABILITIES.map((item, index) => (
              <div className="auth-queue-line" key={item.id}>
                <span className="auth-queue-rank">0{index + 1}</span>
                <span className={`auth-queue-dot ${item.tone}`} />
                <div><strong>{item.id} / {item.name}</strong><small>{item.detail}</small></div>
              </div>
            ))}
          </div>
          <div className="auth-board-foot"><span>Ledger</span><strong>Verified on request</strong><span>Attribution</span><strong>Hypotheses, not verdicts</strong></div>
        </div>

        <div className="auth-network-figure">
          <div className="auth-network-title"><span>RELATIONSHIP MODEL</span><small>ILLUSTRATIVE SCHEMA / NOT A LIVE VIEW</small></div>
          <svg viewBox="0 0 760 270" preserveAspectRatio="none">
            <g className="auth-links"><path d="M80 210 C170 180 170 72 280 105 S430 215 520 145 S650 78 720 42"/><path d="M80 210 C180 220 230 240 350 195 S510 100 620 130 S680 170 720 210"/><path d="M280 105 C350 45 420 50 520 145"/></g>
            <g className="auth-nodes"><circle cx="80" cy="210" r="9"/><circle cx="280" cy="105" r="7"/><circle cx="350" cy="195" r="6"/><circle cx="520" cy="145" r="10"/><circle cx="620" cy="130" r="6"/><circle cx="720" cy="42" r="8"/><circle cx="720" cy="210" r="6"/></g>
            <g className="auth-node-labels"><text x="64" y="237">ACTOR</text><text x="257" y="84">HANDLE</text><text x="495" y="126">WALLET</text><text x="694" y="24">INFRA</text></g>
          </svg>
        </div>

        <div className="auth-command-foot"><span>Evidence → Entity → Relationship → Assessment</span><span>Attribution output is a hypothesis for analyst review</span></div>
      </section>

      <section className="enterprise-auth__panel">
        <div className="enterprise-auth__panel-inner">
          <div className="enterprise-panel-meta"><span className="eyebrow">Corporate analyst access</span><span className="secure-badge">● SECURE SESSION</span></div>
          <div className="enterprise-auth__copy">
            <h1>Sign in to your<br /><em>analyst workspace.</em></h1>
            <p>Authorized personnel only. Investigation activity is attributable to the authenticated analyst and recorded in the audit ledger.</p>
          </div>
          <form onSubmit={submit} className="enterprise-form" noValidate>
            <label htmlFor="corporate-email">Work email</label>
            <input
              id="corporate-email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="analyst@organization.com"
              autoFocus
              required
              aria-invalid={error !== null}
              aria-describedby={describedBy}
            />
            <label htmlFor="corporate-password">Password</label>
            <input
              id="corporate-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter your password"
              required
              aria-invalid={error !== null}
              aria-describedby={describedBy}
            />
            <div className="enterprise-form__options">
              <label className="remember">
                <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
                <span>Remember this device</span>
              </label>
              {/* Deliberately not a button. A control labelled "Forgot
                  password?" that goes nowhere is worse than no control: it
                  tells an analyst a recovery path exists and then swallows the
                  click. Password recovery is an administrator action. */}
              <span className="quiet-link">Credentials are issued by your administrator</span>
            </div>
            {/* Both notices are live regions: an expired session or a rejected
                password is the one thing on this page the analyst must not
                miss because it rendered above the fold on a wide monitor. */}
            {sessionNotice ? <p className="auth-notice" id="auth-notice" role="alert">{sessionNotice}</p> : null}
            {error ? <p className="auth-error" id="auth-error" role="alert">{error}</p> : null}
            {sessionState === 'authenticating' ? (
              <p className="auth-notice" role="status">Authenticating…</p>
            ) : null}
            <button className="enterprise-submit" type="submit" disabled={busy}>{busy ? 'Authenticating…' : 'Enter secure workspace'} <span>↗</span></button>
          </form>
          <div className="auth-policy"><span>Session controls</span><span>Audit logging</span><span>Role-based access</span></div>
          <footer className="enterprise-auth__foot"><span>AEGIS CONTROLLED ENVIRONMENT</span><span>AUTHENTICATED ACCESS REQUIRED</span></footer>
        </div>
      </section>
    </main>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { authenticated } = useAuth();
  return authenticated ? children : null;
}
