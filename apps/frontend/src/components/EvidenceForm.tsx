import { useState } from 'react';
import type { FormEvent } from 'react';
import { api, formatApiError } from '../api/client';
import { SOURCE_TYPES } from '../api/types';
import type { Evidence, EvidenceCreate, SourceType } from '../api/types';

export interface EvidenceFormProps {
  /** Called with the record returned by `POST /api/v1/evidence`. */
  readonly onCreated: (record: Evidence) => void;
}

type Status =
  | { readonly kind: 'idle' }
  | { readonly kind: 'busy' }
  | { readonly kind: 'ok'; readonly message: string }
  | { readonly kind: 'error'; readonly message: string };

const SHA256_PATTERN = /^[a-fA-F0-9]{64}$/;

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

/** Default `collected_at` value: now, to the minute, in local time. */
function nowLocalInput(): string {
  const now = new Date();
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}`
  );
}

/**
 * Ingest form for `POST /api/v1/evidence` (live endpoint).
 * Mirrors the required fields of `EvidenceCreate` in
 * `src/aegis/schemas/evidence.py`.
 */
export function EvidenceForm({ onCreated }: EvidenceFormProps) {
  const [sourceId, setSourceId] = useState('');
  const [sourceType, setSourceType] = useState<SourceType>('synthetic');
  const [observedAt, setObservedAt] = useState('');
  const [collectedAt, setCollectedAt] = useState(nowLocalInput);
  const [entityType, setEntityType] = useState('');
  const [rawUri, setRawUri] = useState('');
  const [sha256, setSha256] = useState('');
  const [collectorName, setCollectorName] = useState('');
  const [collectorVersion, setCollectorVersion] = useState('');
  const [reliability, setReliability] = useState('0.5');
  const [independenceGroup, setIndependenceGroup] = useState('');
  const [status, setStatus] = useState<Status>({ kind: 'idle' });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmed = {
      sourceId: sourceId.trim(),
      rawUri: rawUri.trim(),
      sha256: sha256.trim(),
      collectorName: collectorName.trim(),
      collectorVersion: collectorVersion.trim(),
      independenceGroup: independenceGroup.trim(),
    };
    const reliabilityValue = Number(reliability);

    if (
      trimmed.sourceId === '' ||
      trimmed.rawUri === '' ||
      trimmed.collectorName === '' ||
      trimmed.collectorVersion === '' ||
      trimmed.independenceGroup === '' ||
      collectedAt === ''
    ) {
      setStatus({ kind: 'error', message: 'All required fields must be filled in.' });
      return;
    }
    if (!SHA256_PATTERN.test(trimmed.sha256)) {
      setStatus({ kind: 'error', message: 'sha256 must be exactly 64 hexadecimal characters.' });
      return;
    }
    if (!Number.isFinite(reliabilityValue) || reliabilityValue < 0 || reliabilityValue > 1) {
      setStatus({ kind: 'error', message: 'Source reliability must be between 0 and 1.' });
      return;
    }

    const payload: EvidenceCreate = {
      source_id: trimmed.sourceId,
      source_type: sourceType,
      observed_at: observedAt === '' ? null : new Date(observedAt).toISOString(),
      collected_at: new Date(collectedAt).toISOString(),
      entity_type: entityType.trim() === '' ? null : entityType.trim(),
      raw_artifact_uri: trimmed.rawUri,
      sha256: trimmed.sha256.toLowerCase(),
      collector_name: trimmed.collectorName,
      collector_version: trimmed.collectorVersion,
      source_reliability: reliabilityValue,
      independence_group: trimmed.independenceGroup,
      metadata: {},
    };

    setStatus({ kind: 'busy' });
    api
      .createEvidence(payload)
      .then((record) => {
        onCreated(record);
        setStatus({ kind: 'ok', message: `Evidence created: ${record.evidence_id}` });
      })
      .catch((error: unknown) => {
        setStatus({ kind: 'error', message: formatApiError(error) });
      });
  };

  return (
    <form className="form" onSubmit={handleSubmit}>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="ev-source-id">Source ID (required)</label>
          <input
            id="ev-source-id"
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
            placeholder="UUID from POST /api/v1/sources"
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="ev-source-type">Source type</label>
          <select
            id="ev-source-type"
            value={sourceType}
            onChange={(event) => setSourceType(event.target.value as SourceType)}
          >
            {SOURCE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="ev-observed">Observed at (optional)</label>
          <input
            id="ev-observed"
            type="datetime-local"
            value={observedAt}
            onChange={(event) => setObservedAt(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="ev-collected">Collected at (required)</label>
          <input
            id="ev-collected"
            type="datetime-local"
            value={collectedAt}
            onChange={(event) => setCollectedAt(event.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="ev-entity-type">Entity type (optional)</label>
          <input
            id="ev-entity-type"
            value={entityType}
            onChange={(event) => setEntityType(event.target.value)}
            placeholder="handle / wallet / domain"
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="ev-uri">Raw artifact URI (required)</label>
          <input
            id="ev-uri"
            value={rawUri}
            onChange={(event) => setRawUri(event.target.value)}
            placeholder="s3://aegis/evidence/…"
            autoComplete="off"
          />
        </div>
        <div className="field field--wide">
          <label htmlFor="ev-sha256">SHA-256 (required, 64 hex chars)</label>
          <input
            id="ev-sha256"
            value={sha256}
            onChange={(event) => setSha256(event.target.value)}
            placeholder="a-f0-9 × 64"
            spellCheck={false}
            autoComplete="off"
            className="mono"
          />
        </div>
        <div className="field">
          <label htmlFor="ev-collector">Collector name (required)</label>
          <input
            id="ev-collector"
            value={collectorName}
            onChange={(event) => setCollectorName(event.target.value)}
            placeholder="synthetic"
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="ev-collector-version">Collector version (required)</label>
          <input
            id="ev-collector-version"
            value={collectorVersion}
            onChange={(event) => setCollectorVersion(event.target.value)}
            placeholder="0.1.0"
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="ev-reliability">Source reliability (0–1)</label>
          <input
            id="ev-reliability"
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={reliability}
            onChange={(event) => setReliability(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="ev-independence">Independence group (required)</label>
          <input
            id="ev-independence"
            value={independenceGroup}
            onChange={(event) => setIndependenceGroup(event.target.value)}
            placeholder="platform:forum_alpha"
            autoComplete="off"
          />
        </div>
      </div>

      <div className="form-actions">
        <button type="submit" className="btn btn--primary" disabled={status.kind === 'busy'}>
          {status.kind === 'busy' ? 'Creating…' : 'Create evidence'}
        </button>
        <span className="hint">POST /api/v1/evidence</span>
      </div>

      {status.kind === 'ok' && (
        <p className="status status--ok" role="status">
          {status.message}
        </p>
      )}
      {status.kind === 'error' && (
        <p className="status status--error" role="alert">
          {status.message}
        </p>
      )}
    </form>
  );
}
