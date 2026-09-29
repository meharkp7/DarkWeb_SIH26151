import { useEffect, useState } from 'react';
import { api, formatApiError } from '../api/client';
import type { CopilotResponse } from '../api/types';
import { agentGrounding, agentSuggestions, useAgentContext } from './agent-context';

/** The agent works in visible stages rather than a single opaque spinner. */
const STAGES = ['Reading the investigation', 'Searching evidence', 'Checking relationships', 'Validating citations'] as const;

export function AgentButton() {
  const context = useAgentContext();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(0);
  const [answer, setAnswer] = useState<CopilotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const suggestions = agentSuggestions(context);
  const grounding = agentGrounding(context);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === 'Escape') setOpen(false);
    };
    const openHandler = () => setOpen(true);
    window.addEventListener('keydown', handler);
    window.addEventListener('aegis:open-agent', openHandler);
    return () => {
      window.removeEventListener('keydown', handler);
      window.removeEventListener('aegis:open-agent', openHandler);
    };
  }, []);

  // A stale answer from the previous screen is worse than no answer: it reads
  // as though it is about whatever is on screen now.
  useEffect(() => {
    setAnswer(null);
    setError(null);
  }, [context.place, context.view]);

  useEffect(() => {
    if (!busy) return;
    setStage(0);
    const timer = window.setInterval(() => {
      setStage((s) => Math.min(s + 1, STAGES.length - 1));
    }, 900);
    return () => window.clearInterval(timer);
  }, [busy]);

  const ask = async (value = question) => {
    const q = value.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api.copilot(grounding ? `${q}\nContext: ${grounding}` : q));
      setQuestion('');
    } catch (reason) {
      setError(formatApiError(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        className={`agent-orb ${open ? 'agent-orb--open' : ''}`}
        onClick={() => setOpen(true)}
        aria-label="Ask AEGIS"
      >
        <span className="agent-orb__spark">✦</span>
        <span className="agent-orb__label">Ask AEGIS</span>
        <kbd>⌘K</kbd>
      </button>
      {open && (
        <div
          className="agent-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <section className="agent-panel" role="dialog" aria-modal="true" aria-label="AEGIS Agent">
            <header className="agent-panel__head">
              <div>
                <div className="agent-kicker">
                  <span className="agent-live-dot" /> AEGIS Agent
                </div>
                <h2>Investigate, don’t navigate.</h2>
                {grounding && <p className="agent-scope">{grounding}</p>}
              </div>
              <button className="icon-button" onClick={() => setOpen(false)} aria-label="Close">
                ×
              </button>
            </header>
            <div className="agent-suggestions">
              {suggestions.map((item) => (
                <button key={item} onClick={() => void ask(item)} disabled={busy}>
                  {item}
                  <span>↗</span>
                </button>
              ))}
            </div>
            {busy && (
              <div className="agent-thinking">
                <span className="thinking-dot" /> {STAGES[stage]}
              </div>
            )}
            {error && <div className="inline-error">{error}</div>}
            {answer && (
              <div className="agent-answer">
                <div className="agent-answer__meta">
                  {answer.intent} · {answer.tools_run.join(' · ')}
                </div>
                <p>{answer.text}</p>
                <div className="agent-answer__links">
                  <span>{answer.evidence_ids.length} evidence references</span>
                  <span>{answer.claims.length} supported claims</span>
                </div>
              </div>
            )}
            <form
              className="agent-input"
              onSubmit={(e) => {
                e.preventDefault();
                void ask();
              }}
            >
              <input
                autoFocus
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask about this investigation…"
              />
              <button type="submit" disabled={!question.trim() || busy}>
                {busy ? '…' : '↑'}
              </button>
            </form>
          </section>
        </div>
      )}
    </>
  );
}
