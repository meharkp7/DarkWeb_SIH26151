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
      // ⌘K belongs to the navigation palette now. Two surfaces claiming the
      // same shortcut means the analyst can never be sure which one they are
      // about to get, so the agent takes ⌘J instead — adjacent, unused, and
      // still reachable without a mouse.
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'j') {
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
      // The case id travels as scope; the name travels as grounding text.
      // Sending only the name left the graph, hypothesis, timeline and
      // assessment tools unpopulated, so the questions the agent itself
      // suggests were the ones it could not answer.
      setAnswer(
        await api.copilot(grounding ? `${q}\nContext: ${grounding}` : q, 10, context.caseId),
      );
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
        aria-label="Ask the AEGIS Agent (Command-J)"
      >
        <span className="agent-orb__spark">✦</span>
        <span className="agent-orb__label">Ask AEGIS</span>
        <kbd>⌘J</kbd>
      </button>
      {open && (
        <div
          className="agent-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <section
            className="agent-panel"
            role="dialog"
            aria-modal="true"
            aria-label="AEGIS Agent"
            onKeyDown={(e) => {
              if (e.key !== 'Tab') return;
              const focusable = e.currentTarget.querySelectorAll<HTMLElement>(
                'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
              );
              const first = focusable[0];
              const last = focusable[focusable.length - 1];
              if (first === undefined || last === undefined) return;
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
              }
            }}
          >
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
