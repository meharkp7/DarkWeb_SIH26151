import { useEffect, useState } from 'react';
import { api, formatApiError } from '../api/client';
import type { CopilotResponse } from '../api/types';

export function AgentButton({ context }: { context?: string }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<CopilotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setOpen(true); }
      if (event.key === 'Escape') setOpen(false);
    };
    const openHandler = () => setOpen(true);
    window.addEventListener('keydown', handler);
    window.addEventListener('aegis:open-agent', openHandler);
    return () => { window.removeEventListener('keydown', handler); window.removeEventListener('aegis:open-agent', openHandler); };
  }, []);

  const ask = async (value = question) => {
    const q = value.trim();
    if (!q || busy) return;
    setBusy(true); setError(null);
    try { setAnswer(await api.copilot(context ? `${q}\nContext: ${context}` : q)); setQuestion(''); }
    catch (reason) { setError(formatApiError(reason)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <button className={`agent-orb ${open ? 'agent-orb--open' : ''}`} onClick={() => setOpen(true)} aria-label="Ask AEGIS">
        <span className="agent-orb__spark">✦</span><span className="agent-orb__label">Ask AEGIS</span><kbd>⌘K</kbd>
      </button>
      {open && (
        <div className="agent-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
          <section className="agent-panel" role="dialog" aria-modal="true" aria-label="AEGIS Agent">
            <header className="agent-panel__head">
              <div><div className="agent-kicker"><span className="agent-live-dot" /> AEGIS Agent</div><h2>Investigate, don’t navigate.</h2></div>
              <button className="icon-button" onClick={() => setOpen(false)} aria-label="Close">×</button>
            </header>
            <div className="agent-suggestions">
              {['Summarize this case', 'Show the strongest connections', 'What changed recently?', 'Explain the attribution signals'].map((item) => (
                <button key={item} onClick={() => void ask(item)}>{item}<span>↗</span></button>
              ))}
            </div>
            {busy && <div className="agent-thinking"><span className="thinking-dot" /> Searching evidence <span>·</span> checking relationships <span>·</span> validating citations</div>}
            {error && <div className="inline-error">{error}</div>}
            {answer && <div className="agent-answer"><div className="agent-answer__meta">{answer.intent} · {answer.tools_run.join(' · ')}</div><p>{answer.text}</p><div className="agent-answer__links"><span>{answer.evidence_ids.length} evidence references</span><span>{answer.claims.length} supported claims</span></div></div>}
            <form className="agent-input" onSubmit={(e) => { e.preventDefault(); void ask(); }}>
              <input autoFocus value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about this investigation…" />
              <button type="submit" disabled={!question.trim() || busy}>{busy ? '…' : '↑'}</button>
            </form>
          </section>
        </div>
      )}
    </>
  );
}
