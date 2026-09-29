/**
 * Adjudication: an analyst rules a proposed linkage confirmed or rejected.
 *
 * This is the boundary between an estimate and a finding, so the control is
 * built to make an unattributed decision impossible:
 *
 * - the **decision** is a radio pair with the consequence spelled out, not two
 *   buttons that could be pressed without reading either;
 * - the **rationale** is required, and the submit stays disabled without it — the
 *   server refuses a blank one too, this just says so before the round trip;
 * - the **analyst** is picked from the real account roster rather than typed as
 *   an id, because a ruling nobody owns is not a finding.
 *
 * Nothing is applied optimistically. `onRuled` is called with the server's own
 * copy of the row after the response arrives, and the caller's state is updated
 * from that — never from what the click implied. A reversal says so, and warns
 * before it happens: the new ruling **replaces** the old one, and the history
 * lives in the audit trail rather than in a column that could hold two rulings
 * at once.
 */

import { useCallback, useMemo, useState } from 'react';

import { api, formatApiError } from '../../api/client';
import { useApi } from '../../hooks/useApi';
import type { AdjudicationResponse, PersonaLinkage, TeamResponse } from '../../api/types';
import { LinkageStatusPill } from './LinkageStatusPill';

export interface AdjudicationControlProps {
  readonly linkage: PersonaLinkage;
  /** Called with the server's stored row once the ruling is recorded. */
  readonly onRuled: (response: AdjudicationResponse) => void;
  /** Dense row expansion rather than the inspector rail. */
  readonly terse?: boolean;
}

type Decision = 'confirmed' | 'rejected';

const DECISIONS: readonly { value: Decision; label: string; gloss: string }[] = [
  {
    value: 'confirmed',
    label: 'Confirm — this handle is this actor',
    gloss: 'Record as the same person. A confirmation is a finding; the model score is kept beside it, not replaced by it.',
  },
  {
    value: 'rejected',
    label: 'Reject — not the same person',
    gloss: 'Record as different people. A rejection stays on file, including the high score that produced it.',
  },
];

export function AdjudicationControl({ linkage, onRuled, terse = false }: AdjudicationControlProps) {
  const { data: team, error: teamError } = useApi<TeamResponse>(api.teamUrl());
  const members = useMemo(
    () => (team?.members ?? []).filter((member) => member.is_active),
    [team],
  );

  const [decision, setDecision] = useState<Decision | null>(null);
  const [rationale, setRationale] = useState('');
  const [analystId, setAnalystId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AdjudicationResponse | null>(null);

  const effectiveAnalyst = analystId || (members[0]?.user_id ?? '');
  const canSubmit =
    decision !== null && rationale.trim().length > 0 && effectiveAnalyst.length > 0 && !busy;

  const isReversal =
    linkage.status !== 'proposed' && decision !== null && decision !== linkage.status;

  const submit = useCallback(async () => {
    if (decision === null || !canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.adjudicatePersonaLinkage(linkage.linkage_id, {
        status: decision,
        analyst_id: effectiveAnalyst,
        rationale: rationale.trim(),
      });
      // Success is only what the server says it is. The caller's row comes from
      // this response, not from the click.
      setResult(response);
      onRuled(response);
    } catch (caught) {
      setError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  }, [canSubmit, decision, effectiveAnalyst, linkage.linkage_id, onRuled, rationale]);

  return (
    <div className={`per-adjudicate${terse ? ' per-adjudicate--terse' : ''}`}>
      {linkage.status === 'proposed' ? (
        <p className="per-adjudicate__state">
          <LinkageStatusPill status="proposed" />
          <span>
            Nobody has ruled on this. Until an analyst does, the score is a hypothesis and must not
            be reported as a linkage.
          </span>
        </p>
      ) : (
        <p className="per-adjudicate__state">
          <LinkageStatusPill status={linkage.status} />
          <span>
            Ruled {linkage.adjudicated_at ? formatWhen(linkage.adjudicated_at) : 'at an unrecorded time'}{' '}
            by {linkage.adjudicated_by_name ?? 'an unrecorded analyst'}
            {linkage.rationale ? `: “${linkage.rationale}”` : ''}
          </span>
        </p>
      )}

      {teamError ? (
        <p className="per-error" role="alert">
          Could not load the analyst roster: {teamError}. A ruling needs a named analyst, so it
          cannot be recorded until the roster loads.
        </p>
      ) : null}

      <fieldset className="per-adjudicate__choice" disabled={busy}>
        <legend className="per-adjudicate__legend">Ruling</legend>
        {DECISIONS.map((option) => (
          <label className="per-adjudicate__option" key={option.value}>
            <input
              type="radio"
              name={`per-decision-${linkage.linkage_id}`}
              value={option.value}
              checked={decision === option.value}
              onChange={() => {
                setDecision(option.value);
                setResult(null);
              }}
            />
            <span className="per-adjudicate__optionlabel">
              {option.label}
              <span className="per-adjudicate__gloss">{option.gloss}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <label className="per-field">
        <span className="per-field__label">
          Rationale <span className="per-field__req">required</span>
        </span>
        <textarea
          className="per-field__input"
          value={rationale}
          rows={3}
          placeholder="Why this ruling, on what evidence. A decision with no stated reason is indistinguishable from a model output."
          onChange={(event) => {
            setRationale(event.target.value);
            setResult(null);
          }}
        />
      </label>

      <label className="per-field">
        <span className="per-field__label">Deciding analyst</span>
        {members.length === 0 && !teamError ? (
          <span className="per-field__hint">Loading the account roster…</span>
        ) : (
          <select
            className="per-field__input"
            value={effectiveAnalyst}
            onChange={(event) => setAnalystId(event.target.value)}
          >
            {members.map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {member.display_name} — {member.role.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        )}
      </label>

      {isReversal ? (
        <p className="per-adjudicate__warning" role="status">
          This replaces the current ruling rather than adding to it. The row will read
          {' '}
          <strong>{decision}</strong> and the earlier decision stays only in the audit trail.
        </p>
      ) : null}

      {error ? (
        <p className="per-error" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <p className="per-adjudicate__done" role="status">
          Ruling recorded by the server.{' '}
          {result.previous_status && result.previous_status !== result.linkage.status
            ? `Reversed from ${result.previous_status}. `
            : ''}
          This row now reads {result.linkage.status}
          {result.linkage.adjudicated_by_name ? `, attributed to ${result.linkage.adjudicated_by_name}` : ''}
          {` (audit entry #${result.audit_seq}).`}
        </p>
      ) : null}

      <button
        type="button"
        className="per-btn per-btn--primary"
        disabled={!canSubmit}
        onClick={submit}
      >
        {busy ? 'Recording…' : 'Record ruling'}
      </button>
    </div>
  );
}

function formatWhen(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'at an unrecorded time';
  return `on ${date.toISOString().slice(0, 10)}`;
}
