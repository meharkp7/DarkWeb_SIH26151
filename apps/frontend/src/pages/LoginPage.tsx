import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useAuth } from '../store/auth';

const cases = [
  { id: 'NF-042', name: 'Operation Nightfall', score: 94, tone: 'critical' },
  { id: 'BI-017', name: 'Black Ice', score: 86, tone: 'high' },
  { id: 'CM-031', name: 'Copper Trace', score: 78, tone: 'watch' },
];

export function LoginPage() {
  const { signIn, busy, error, sessionNotice } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);

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
          <div className="auth-board-head"><span>ACTIVE INVESTIGATION QUEUE</span><b>03 PRIORITY CASES</b></div>
          <div className="auth-queue-lines">
            {cases.map((item, index) => (
              <div className="auth-queue-line" key={item.id}>
                <span className="auth-queue-rank">0{index + 1}</span>
                <span className={`auth-queue-dot ${item.tone}`} />
                <div><strong>{item.id} / {item.name}</strong><small>{index === 0 ? 'Attribution assessment · SLA exception' : index === 1 ? 'Infrastructure correlation · active' : 'Financial linkage · monitoring'}</small></div>
                <b>{item.score}%</b>
              </div>
            ))}
          </div>
          <div className="auth-board-foot"><span>Evidence ledger</span><strong>3,250+</strong><span>Relationships</span><strong>1,600+</strong><span>Assessments</span><strong>300</strong></div>
        </div>

        <div className="auth-network-figure">
          <div className="auth-network-title"><span>RELATIONSHIP SIGNAL MAP</span><small>LIVE / SYNTHETIC DEMONSTRATION CORPUS</small></div>
          <svg viewBox="0 0 760 270" preserveAspectRatio="none">
            <g className="auth-links"><path d="M80 210 C170 180 170 72 280 105 S430 215 520 145 S650 78 720 42"/><path d="M80 210 C180 220 230 240 350 195 S510 100 620 130 S680 170 720 210"/><path d="M280 105 C350 45 420 50 520 145"/></g>
            <g className="auth-nodes"><circle cx="80" cy="210" r="9"/><circle cx="280" cy="105" r="7"/><circle cx="350" cy="195" r="6"/><circle cx="520" cy="145" r="10"/><circle cx="620" cy="130" r="6"/><circle cx="720" cy="42" r="8"/><circle cx="720" cy="210" r="6"/></g>
            <g className="auth-node-labels"><text x="64" y="237">ACTOR</text><text x="257" y="84">HANDLE</text><text x="495" y="126">WALLET</text><text x="694" y="24">INFRA</text></g>
          </svg>
        </div>

        <div className="auth-command-foot"><span>Evidence → Entity → Relationship → Assessment</span><span>All records synthetic for demonstration</span></div>
      </section>

      <section className="enterprise-auth__panel">
        <div className="enterprise-auth__panel-inner">
          <div className="enterprise-panel-meta"><span className="eyebrow">Corporate analyst access</span><span className="secure-badge">● SECURE SESSION</span></div>
          <div className="enterprise-auth__copy">
            <h1>Sign in to your<br /><em>analyst workspace.</em></h1>
            <p>Authorized personnel only. Investigation activity is attributable to the authenticated analyst and recorded in the audit ledger.</p>
          </div>
          <form onSubmit={submit} className="enterprise-form">
            <label htmlFor="corporate-email">Work email</label>
            <input id="corporate-email" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="analyst@organization.com" autoFocus />
            <label htmlFor="corporate-password">Password</label>
            <input id="corporate-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" />
            <div className="enterprise-form__options"><label className="remember"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> <span>Remember this device</span></label><button type="button" className="quiet-link">Forgot password?</button></div>
            {sessionNotice && <p className="auth-notice">{sessionNotice}</p>}
            {error && <p className="auth-error">{error}</p>}
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
