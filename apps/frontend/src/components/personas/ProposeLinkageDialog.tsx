/**
 * Propose a linkage, and have the platform score it.
 *
 * The form has no score field, and that is the point: the score is computed from
 * the two text samples by the platform's stylometry, and a caller-supplied one
 * is refused by the API. So the analyst's job here is to supply evidence —
 * a handle and enough of each side's writing — and read back what the model
 * says about it.
 *
 * The word count under each sample is there to make the refusal legible before
 * it happens. A sample under the platform's minimum is not scored at all: the
 * endpoint answers 422 with the count it measured and the threshold it needs,
 * and that answer is shown verbatim rather than swallowed, because "the analysis
 * could not run" and "the analysis found nothing" must never look the same.
 *
 * Reached from an actor profile, so the actor is the one in the address bar. The
 * behavioural method is not offered here: it needs an event sample rather than
 * two text areas, and a form that pretends to collect one would be worse than
 * not offering it.
 */

import { useCallback, useMemo, useState } from 'react';

import { api, formatApiError } from '../../api/client';
import type { PersonaLinkageDetail } from '../../api/types';
import { LinkageScoreBar } from './LinkageScoreBar';
import { LinkageStatusPill } from './LinkageStatusPill';

/** Mirrors the server's minimum so the hint is available before submitting. */
const MIN_WORDS = 120;

function countWords(value: string): number {
  return value.split(/\s+/).filter((token) => token.length > 0).length;
}

export interface ProposeLinkageDialogProps {
  readonly actorId: string;
  readonly caseId?: string | null;
  readonly onCreated: (linkage: PersonaLinkageDetail) => void;
  readonly onClose: () => void;
}

export function ProposeLinkageDialog({
  actorId,
  caseId = null,
  onCreated,
  onClose,
}: ProposeLinkageDialogProps) {
  const [handle, setHandle] = useState('');
  const [actorSample, setActorSample] = useState('');
  const [candidateSample, setCandidateSample] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<PersonaLinkageDetail | null>(null);

  const actorWords = useMemo(() => countWords(actorSample), [actorSample]);
  const candidateWords = useMemo(() => countWords(candidateSample), [candidateSample]);
  const tooShort = actorWords < MIN_WORDS || candidateWords < MIN_WORDS;
  const canSubmit = handle.trim().length > 0 && !tooShort && !busy;

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const linkage = await api.proposePersonaLinkage({
        actor_id: actorId,
        candidate_handle: handle.trim(),
        method: 'stylometry',
        case_id: caseId,
        actor_sample: actorSample,
        candidate_sample: candidateSample,
      });
      setCreated(linkage);
      onCreated(linkage);
    } catch (caught) {
      setError(formatApiError(caught));
    } finally {
      setBusy(false);
    }
  }, [actorId, canSubmit, caseId, candidateSample, handle, actorSample, onCreated]);

  return (
    <div className="per-modal" role="dialog" aria-modal="true" aria-label="Propose a persona linkage">
      <div className="per-modal__panel">
        <h3 className="per-modal__title">Propose a persona linkage</h3>
        <p className="per-modal__lead">
          The score is computed here, from the two text samples, by the platform&rsquo;s stylometry.
          There is no field for it, and a request carrying one is refused. What you get back is a{' '}
          <strong>proposal</strong>: a hypothesis until an analyst rules on it.
        </p>

        <label className="per-field">
          <span className="per-field__label">Candidate handle</span>
          <input
            className="per-field__input"
            value={handle}
            onChange={(event) => setHandle(event.target.value)}
            placeholder="the handle to be linked to this actor"
          />
        </label>

        <label className="per-field">
          <span className="per-field__label">
            Known actor&rsquo;s text <span className="per-field__count">{actorWords} words</span>
          </span>
          <textarea
            className="per-field__input"
            rows={5}
            value={actorSample}
            onChange={(event) => setActorSample(event.target.value)}
            placeholder="Posts already attributed to this actor."
          />
        </label>

        <label className="per-field">
          <span className="per-field__label">
            Candidate&rsquo;s text <span className="per-field__count">{candidateWords} words</span>
          </span>
          <textarea
            className="per-field__input"
            rows={5}
            value={candidateSample}
            onChange={(event) => setCandidateSample(event.target.value)}
            placeholder="Posts collected from the candidate handle."
          />
        </label>

        {tooShort ? (
          <p className="per-modal__hint">
            Each side needs at least {MIN_WORDS} words before the ratio features are stable. Below
            that the platform refuses rather than returning a number — a short sample is not weak
            evidence, it is no evidence.
          </p>
        ) : null}

        {error ? (
          <p className="per-error" role="alert">
            {error}
          </p>
        ) : null}

        {created ? (
          <div className="per-modal__result">
            <p>
              <LinkageStatusPill status={created.status} /> Proposed and recorded as{' '}
              <code>{created.linkage_id}</code>.
            </p>
            <LinkageScoreBar score={created.score} linkage={created} />
            <p className="per-modal__hint">
              {created.contested_features.length} of the{' '}
              {created.aligned_features.length + created.apart_features.length + created.contested_features.length}{' '}
              measured features came back contested, and {created.limitations.length} limitations are
              on file. Adjudicate it from the register row.
            </p>
          </div>
        ) : null}

        <div className="per-modal__actions">
          <button type="button" className="per-btn" onClick={onClose}>
            {created ? 'Close' : 'Cancel'}
          </button>
          <button
            type="button"
            className="per-btn per-btn--primary"
            disabled={!canSubmit}
            onClick={submit}
          >
            {busy ? 'Scoring…' : 'Propose linkage'}
          </button>
        </div>
      </div>
    </div>
  );
}
