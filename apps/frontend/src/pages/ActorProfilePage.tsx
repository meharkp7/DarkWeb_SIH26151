import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { ActorIdentifier, ActorProfile, ActorSummary } from '../api/types';
import { Badge } from '../components/Badge';
import type { Tone } from '../components/Badge';
import { DataBlock } from '../components/DataBlock';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { ActorConfidence } from '../components/actor/ActorConfidence';
import { MarketplaceTimeline } from '../components/actor/MarketplaceTimeline';
import { PersonaLinkageList } from '../components/actor/ActorPieces';
import { ActorScanMark } from '../components/actor/ActorScanMark';
import { useApi } from '../hooks/useApi';
import { formatDate, formatDateTime, formatPercent, shortId } from '../lib/format';
import { leadFor } from '../lib/explain';
// Colocated for the same reason as on `ActorsPage`: this page cannot be sure
// anyone wired its stylesheet into the entry point.
import '../styles/actors.css';

const STATUS_TONE: Record<string, Tone> = {
  active: 'ok',
  dormant: 'warn',
  rebranded: 'info',
  retired: 'neutral',
  unknown: 'neutral',
};

/**
 * One actor, resolved.
 *
 * Sections rather than tabs, because every one of them is derived from a
 * single profile payload and an analyst reading "which venues is this persona
 * still on" should not have to click to find out. What an analyst *cannot* do
 * here is confirm a linkage — a persona merge is an adjudicated act with an
 * author and a rationale behind it, and this screen only shows what has been
 * proposed and what has been ruled on.
 */
export function ActorProfilePage() {
  const { actorId } = useParams<{ actorId: string }>();
  const profile = useApi<ActorProfile>(api.getActorUrl(actorId ?? ''));
  const staleDays = useApi<ActorSummary>(api.actorSummaryUrl());

  const data = profile.data;
  const grouped = useMemo(() => data?.identifiers_by_kind ?? {}, [data]);
  const identifierKinds = useMemo(
    () => Object.entries(grouped).sort(([left], [right]) => left.localeCompare(right)),
    [grouped],
  );

  return (
    <div className="page-stack act-page">
      {profile.error !== null && <ErrorState message={profile.error} onRetry={profile.reload} />}
      {profile.loading && <LoadingState label="Loading actor profile…" />}

      {!profile.loading && profile.error !== null && (
        <EmptyState
          title="Actor not found"
          message="The registry has no actor with that identifier. It may have been removed, or the link may be stale."
          endpoint="GET /api/v1/actors/{actor_id}"
        />
      )}

      {!profile.loading && profile.error === null && data === null && (
        <EmptyState title="No profile" message="The API returned no profile for this actor." />
      )}

      {data !== null && (
        <>
          <header className="act-page__head">
            <div>
              <span className="eyebrow">
                <Link to="/actors">← Actor registry</Link>
              </span>
              <h1>{data.actor.handle}</h1>
              <p>
                {`${data.actor.category} · ${data.actor.status} · last seen ${formatDate(data.actor.last_seen)}`}
              </p>
              <p>
                <Badge tone={STATUS_TONE[data.actor.status] ?? 'neutral'}>{data.actor.status}</Badge>
              </p>
            </div>
          </header>

          {data.actor.notes !== null && data.actor.notes !== '' && (
            <DataBlock title="Analyst note" eyebrow="Record">
              <p className="hint">{data.actor.notes}</p>
            </DataBlock>
          )}

          <div className="act-profile__grid">
            <DataBlock title="Identifiers" eyebrow="Evidence" lead={leadFor('actor.profile')}>
              {identifierKinds.length === 0 ? (
                <p className="hint">
                  No identifier is on file for this actor. A registry row with no identifiers is a
                  claim nobody has yet cited anything for.
                </p>
              ) : (
                identifierKinds.map(([kind, rows]) => (
                  <section className="act-id-group" key={kind}>
                    <header className="act-id-group__head">
                      <span className="act-id-group__kind">{kind}</span>
                      <span className="hint">{`${rows.length} on file`}</span>
                    </header>
                    {rows.map((identifier) => (
                      <IdentifierRow identifier={identifier} />
                    ))}
                  </section>
                ))
              )}
            </DataBlock>

            <div className="page-stack">
              <DataBlock title="Overview" eyebrow="Record" dense>
                <dl className="act-facts">
                  <Fact label="Attribution confidence" value={<ActorConfidence confidence={data.actor.confidence} compact />} />
                  <Fact label="First seen" value={formatDate(data.actor.first_seen)} />
                  <Fact label="Last seen" value={formatDateTime(data.actor.last_seen)} />
                  <Fact
                    label="Last scan"
                    value={
                      <ActorScanMark
                        lastScanAt={data.actor.last_scan_at}
                        staleDays={staleDays.data?.stale_days ?? null}
                      />
                    }
                  />
                  <Fact label="Source" value={data.actor.source_name ?? 'no source recorded'} />
                  <Fact label="Identifiers" value={data.actor.identifier_count} mono />
                  <Fact label="Venue presences" value={data.actor.marketplace_count} mono />
                  <Fact label="Actor ID" value={shortId(data.actor.actor_id, 12)} mono />
                </dl>
              </DataBlock>

              <DataBlock title="Persona linkages" eyebrow="Proposals" dense>
                <PersonaLinkageList linkages={data.persona_linkages} />
              </DataBlock>
            </div>
          </div>

          <DataBlock
            title="Marketplace presence"
            eyebrow="Venues"
            lead="One row per venue, drawn on a shared time axis running to today. A bar that stops short of the right edge is a venue the persona has stopped trading on, which is a different fact from a venue that was never on."
          >
            <MarketplaceTimeline presences={data.marketplaces} />
          </DataBlock>

          <DataBlock
            title="Linked investigations"
            eyebrow="Cases"
            lead="Investigations that cite one of this actor's identifiers. Each is counted once per investigation however many identifiers it cites."
          >
            {data.linked_cases.length === 0 ? (
              <p className="hint">
                No investigation cites this actor yet. The actor is tracked across cases; that no
                case has picked one of its identifiers up is a statement about the investigations,
                not about the actor.
              </p>
            ) : (
              <ul className="act-linkage-list">
                {data.linked_cases.map((link) => (
                  <li className="act-linkage" key={link.case_id}>
                    <div className="act-linkage__head">
                      <Link to={`/cases/${encodeURIComponent(link.case_id)}`}>{link.name}</Link>
                      <Badge tone={STATUS_TONE[link.status] === undefined ? 'neutral' : 'info'}>
                        {link.status}
                      </Badge>
                      <span className="act-linkage__score">
                        {`${link.identifier_count} identifier${link.identifier_count === 1 ? '' : 's'}`}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </DataBlock>
        </>
      )}
    </div>
  );
}

function Fact({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <dt className="act-fact__label">{label}</dt>
      <dd
        className={mono === true ? 'act-fact__value mono' : 'act-fact__value'}
        style={{ margin: 0 }}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * One identifier with its own confidence, its independence group and the
 * investigation it was observed in.
 *
 * The independence group is shown because three handles on one onion service
 * are one source wearing three hats: without it on screen, a corroboration
 * count is a number nobody can discount.
 */
function IdentifierRow({ identifier }: { identifier: ActorIdentifier }) {
  return (
    <div className="act-id-row">
      <span className="act-id-row__value">{identifier.value}</span>
      <span className="act-id-row__meta">
        {identifier.confidence === null ? 'not assessed' : formatPercent(identifier.confidence)}
        {identifier.independence_group !== null && (
          <span title="Identifiers sharing this group are not independent observations">
            {' '}
            · shared with {identifier.independence_group}
          </span>
        )}
        {identifier.case_id !== null && (
          <>
            {' '}
            ·{' '}
            <Link to={`/cases/${encodeURIComponent(identifier.case_id)}`}>seen in a case</Link>
          </>
        )}
        <span className="act-id-row__value">
          {' '}
          {formatDate(identifier.first_seen)} → {formatDate(identifier.last_seen)}
        </span>
      </span>
    </div>
  );
}