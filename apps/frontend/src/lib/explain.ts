/**
 * Plain-language explanations for every figure the console puts on screen.
 *
 * A lead sentence here is a claim about how a number was produced, and it is
 * held to the same standard as the number: if the backend changed its window,
 * its denominator or its source, the sentence is wrong and has to be changed
 * with it. The sources of truth are `src/aegis/api/dashboard_analytics.py`,
 * `src/aegis/api/live.py` and `src/aegis/api/workspace.py`.
 *
 * Two things are deliberately absent from this file: adjectives and optimism.
 * "Corroborated across independent sources" is a claim; "rich" and "powerful"
 * are not, and an analyst who cannot check a sentence stops reading the ones
 * they could.
 */

const EM_DASH = '—';

/**
 * Where a figure came from, in terms of how much weight it can carry.
 *
 * - `assessment` — a model assessment with evidence cited behind it. Recorded
 *   because the citations exist and can be opened, not because the model is
 *   right.
 * - `model`      — a bare model output with nothing behind it on screen. An
 *   estimate, always.
 * - `analyst`    — a human disposition. Recorded, and attributable to whoever
 *   made it.
 * - `derived`    — arithmetic over rows in the store, recomputed on each read.
 */
export type EpistemicSource = 'assessment' | 'model' | 'analyst' | 'derived';

export type EpistemicKind = 'recorded' | 'estimate';

export interface EpistemicLabel {
  readonly label: string;
  readonly kind: EpistemicKind;
}

/**
 * How a figure should be described in words.
 *
 * `derived` is classed as `recorded` because it is deterministic arithmetic over
 * stored rows — a count of records collected in the last seven days is either
 * true of the database or the query is wrong, which is a different failure from
 * a model being wrong. The label still says "derived", because the figure was
 * computed by the API rather than written down by anyone.
 */
export function epistemicLabel(source: EpistemicSource): EpistemicLabel {
  switch (source) {
    case 'assessment':
      return { label: 'Recorded score', kind: 'recorded' };
    case 'model':
      return { label: 'Model estimate', kind: 'estimate' };
    case 'analyst':
      return { label: 'Analyst disposition', kind: 'recorded' };
    case 'derived':
      return { label: 'Derived from records', kind: 'recorded' };
  }
}

/** Every metric this module can explain. Kept open so a panel can name its own. */
export const METRICS = {
  evidenceVelocity: 'evidence.velocity',
  investigationPressure: 'investigation.pressure',
  attributionPosture: 'attribution.posture',
  priorityQueue: 'priority.queue',
  commandPosture: 'command.posture',
  activityFeed: 'activity.feed',
  platformCounts: 'platform.counts',
  signalMatrix: 'signal.matrix',
  evidenceLedger: 'evidence.ledger',
  caseTimeline: 'case.timeline',
  caseGraph: 'case.graph',
  hypothesisBoard: 'hypothesis.board',
  competingHypotheses: 'hypotheses.competing',
  evidenceProvenance: 'evidence.provenance',
  caseMetrics: 'case.metrics',
  actorRegistry: 'actor.registry',
  actorProfile: 'actor.profile',
  actorSummary: 'actor.summary',
  personaLinkageRegister: 'persona.linkage.register',
  personaLinkageSummary: 'persona.linkage.summary',
  personaLinkageDetail: 'persona.linkage.detail',
  infraSummary: 'infra.summary',
  infraFindings: 'infra.findings',
  infraMatches: 'infra.matches',
  infraObservations: 'infra.observations',
  infraBreakdown: 'infra.breakdown',
  infraLimitations: 'infra.limitations',
  infraTimeline: 'infra.timeline',
} as const;

export type MetricName = (typeof METRICS)[keyof typeof METRICS];

/**
 * Context a lead may interpolate. Every key is optional and every key is
 * checked before use: a lead that asserts "across 0 buckets" because the frame
 * was partial is worse than one that omits the count.
 *
 * - `total`   — investigations in the register.
 * - `buckets` — monthly buckets in the velocity series.
 * - `limit`   — rows behind a lead assessment list.
 * - `shown`   — rows a preview is actually rendering.
 * - `single`  — correlations carried by exactly one channel.
 * - `count`   — a count of things a lead is about, zero included.
 */
export interface LeadContext {
  readonly total?: number | null;
  readonly buckets?: number | null;
  readonly limit?: number | null;
  readonly shown?: number | null;
  readonly single?: number | null;
  readonly count?: number | null;
}

/** The context with every key resolved, so no lead can print "undefined". */
interface ResolvedContext {
  readonly total: number | null;
  readonly buckets: number | null;
  readonly limit: number | null;
  readonly shown: number | null;
  readonly single: number | null;
  readonly count: number | null;
}

/** A positive finite number, or null — the only context values worth printing. */
function positive(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * A count that may legitimately be zero.
 *
 * `positive()` maps 0 to null because a zero *total* usually means the frame
 * was partial. That is the wrong reading for a count of weak findings: "none
 * of these correlations rests on a single channel" is a real and reassuring
 * result, and rendering it as an em dash would lose it.
 */
function countable(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function readContext(context: Record<string, unknown> | undefined): ResolvedContext {
  const source = context ?? {};
  return {
    total: positive(source['total']),
    buckets: positive(source['buckets']),
    limit: positive(source['limit']),
    shown: positive(source['shown']),
    single: countable(source['single']),
    count: countable(source['count']),
  };
}

type LeadBuilder = (context: ResolvedContext) => string;

const LEADS: Readonly<Record<MetricName, LeadBuilder>> = {
  'evidence.velocity': ({ buckets }) =>
    `Evidence records per calendar month, counted by the date they were collected, in ${
      buckets === null ? 'monthly buckets' : `${buckets} monthly bucket${buckets === 1 ? '' : 's'}`
    } ending with the current month. A month with nothing collected is drawn as zero rather than left out, because "we collected nothing" is an answer and a missing point is not. The bar beneath each point is the signed change against the month before it; the first bucket has no earlier month, so it has no change to show.`,

  'investigation.pressure': () =>
    'Five platform-wide indicators, each scored 0–100 by dividing a recorded count by a fixed ceiling. The count and its ceiling are printed beside every score, so any figure here can be checked by hand. The headline index is the mean of the five, not a total. The windows differ: evidence and relationship growth count the last 7 days, novel infrastructure and contradictions are all-time, and SLA exposure counts investigations due within 12 hours that are not closed or archived.',

  'attribution.posture': ({ limit }) =>
    `The leading assessment for ${
      limit === null
        ? 'each investigation shown here, drawn from those that are not closed or archived'
        : `up to ${limit} investigations that are not closed or archived`
    }: the highest calibrated confidence available, or the raw model score where nothing has been calibrated. The percentage is a hypothesis under review, not a finding. Supporting signals counts the evidence cited behind it, modalities the distinct signal types, contradictions the citations that argue against it, and freshness the strongest single signal — which is not the age of the evidence.`,

  'priority.queue': ({ total }) =>
    `${
      total === null ? 'Every investigation in the register' : `All ${total} investigations in the register`
    }, ranked by the queue score the server computes. The score is the sum of signed contributions — priority, severity, deadline state, unresolved contradictions, evidence collected in the last 7 days, resolved links, and whether an analyst is assigned — capped at 100, so a saturated row's contributions will not add up to its score. Closed and archived investigations score 0. Open a row to see what produced its position.`,

  'command.posture': ({ total }) =>
    `Live counts across ${
      total === null ? 'the register' : `the ${total} investigations in the register`
    }. Active means status open or active. Critical and high count the priority field. SLA at risk counts investigations already past their deadline or due within the next 12 hours. New evidence counts records collected in the last 7 days. Unresolved contradictions counts assessments carrying at least one contradictory citation. Each tile opens the register filtered to that condition.`,

  'activity.feed': ({ shown }) =>
    `The most recent writes to the audit ledger, newest first.${
      shown === null ? '' : ` The ${shown} most recent are listed here;`
    } each entry records that the platform performed an action — a case created, evidence ingested, a link resolved — and carries no judgement about whether that action was right.`,

  'platform.counts': () =>
    'All-time totals held by the platform at the moment of this snapshot, with nothing filtered: every case, evidence record, entity, relationship and assessment in the store. Critical alerts counts audit entries recorded as critical over the same all-time period; it is a count of events that have happened, not a list of alerts still open.',

  'signal.matrix': () =>
    'Support, contradiction and freshness for each modality in this case, averaged over every assessment recorded here. A modality with no recorded signal is shown at a neutral 0.55 rather than at zero, so an absence is not read as a weak lead. Contradiction is 12% of the average number of contradictory citations per assessment, capped at 0.85. Bands: HIGH from 0.72, MEDIUM from 0.48, LOW below that.',

  'evidence.ledger': () =>
    'Every evidence record attached to this case, newest collection first, with the source it came from, the reliability recorded against that source, and the independence group it belongs to. Reliability is a property of the source, not a measurement of this record. Independence groups are what stop three feeds copying one press release from reading as three sources.',

  'case.timeline': () =>
    'Everything the platform recorded against this case, newest first, in four lanes: what happened, who it involved, the infrastructure it touched, and the money. Up to 80 audit entries and 30 evidence records are merged and ordered by when they occurred, so the lanes are interleaved by time rather than listed separately.',

  'case.graph': () =>
    "Entities in this case as nodes, and the relationships between them as edges. An edge is drawn only when both of its endpoints are entities belonging to this case, so a link reaching outside the case is absent here rather than shown as a node nothing can describe. Nodes are ordered by degree, so the most connected entities come first. An edge's confidence is the model's, and the evidence behind it is what makes it checkable.",

  'hypothesis.board': () =>
    'Every hypothesis raised in this case, highest calibrated confidence first. The confidence belongs to the best assessment attached to that hypothesis and is absent where nothing has been calibrated; the raw score is the uncalibrated model output of the same assessment, and the two are not interchangeable. Independent source groups counts the distinct groups behind the supporting links, not the number of citations.',

  'hypotheses.competing': () =>
    "This case's hypotheses as a matrix: one row per hypothesis, one column per modality, each cell the model's signal value for that pairing. A cell with no recorded signal is left empty rather than drawn as zero, so a modality nobody has measured is not read as a disconfirmed one. Confidence sits beside the number of supporting and contradictory citations and the number of independent source groups behind them, because the same percentage carried by one source and by four is not the same claim.",

  'evidence.provenance': () =>
    'Where one evidence record came from: its SHA-256 digest, the artifact URI it was ingested from, and the parent records it was derived from. The derivation count is the number of parents on file, so a count of zero means no parent is recorded — which is not the same as the record being original, only that nobody recorded the derivation.',

  'case.metrics': () =>
    'Counts for this case alone: evidence records, resolved relationships, entities, distinct sources, contradictory citations, hypotheses, and distinct independence groups. Attribution is the highest calibrated confidence among this case\'s assessments, and it is absent when nothing here has been assessed — which means missing, not zero.',

  'actor.registry': ({ total, shown }) =>
    `The cross-case actor registry: one row per tracked actor${
      total === null ? '' : `, ${total} in total`
    }, of which ${shown === null ? 'this view' : `${shown}`} are shown. The identifier and marketplace counts are counts of stored rows, grouped in the database rather than counted per row. Attribution confidence is the recorded score or absent — an actor nobody has assessed reads as "not assessed", never as zero, and a confidence filter excludes those actors rather than ranking them last. Last scan is when the actor was last re-scanned, which is a different fact from last seen: an actor can be observed daily and scanned monthly. Links counts distinct investigations citing one of this actor's identifiers, so one investigation cited twice is one link.${total !== null && shown !== null && shown < total ? ` This view is filtered: ${shown} of ${total} actors match.` : ''}`,

  'actor.profile': () =>
    "One actor, resolved into its parts. Identifiers are grouped by kind, and each carries its own confidence or the absence of one, the independence group it belongs to, and the investigation it was observed in — three identifiers sharing an independence group are one source wearing three hats, not three corroborations. Marketplace presences are windows: a first-seen and a last-seen per venue, so a persona that has left a venue is visible as one rather than as absent. Persona linkages are proposals to merge a candidate handle into this actor; a linkage is only a finding once an analyst has ruled on it, and the model's score is kept separate from that ruling so a rejection stays visible as a rejection.",

  'actor.summary': () =>
    'Registry-wide counts, recomputed on each read with nothing filtered: every actor, by status, by category and by identifier kind. Stale counts actors whose last scan is older than the stated threshold, including those never scanned at all, because an actor nobody has looked at is the back of the backlog rather than an exemption from it. Unassessed counts actors carrying no attribution score — the population a confidence filter excludes, stated here so the exclusion is visible rather than silent.',

  'persona.linkage.register': ({ total, shown }) =>
    `Every proposal to merge a candidate handle into a tracked actor${
      total === null ? '' : `, ${total} on file`
    }${shown === null || total === null || shown === total ? '' : `, ${shown} shown by the current filters`}. The score is the model's own output for the pair and is never changed by a decision; the status is an analyst's ruling and exists in a separate column. A proposal nobody has ruled on is a hypothesis, and it is drawn as one. The aligned, apart and contested columns count named features, and the three partition the vocabulary between them: a feature measured on one side only, or measured inside the band where neither agreement nor disagreement can be claimed, is contested rather than quietly counted as support. Filters, the sort and the row under inspection all live in the address bar, so a view of this register can be linked or handed over. Adjudicated names the analyst and the date, or an em dash when nobody has ruled.`,

  'persona.linkage.summary': () =>
    'Counts over exactly the linkages the register beside it is showing. The two figures worth reading are the confirmations the scorer ranked below the stated threshold and the rejections it ranked at or above it. Those are the model\'s false-negative and false-positive rates as analysts have actually observed them, counted from the decisions rather than reported by the thing being measured, which is the only version of the number that can be checked. When nothing here has been adjudicated the block says so instead of printing a clean 0% over an empty denominator, because a scorer nobody has ever overruled has not been tested.',

  'infra.summary': ({ single, total }) =>
    `Counts over exactly the records the current filters return. The figure worth reading first is the ${formatCount(
      single,
      'match',
      'matches',
    )} whose score rests on a single channel: a correlation carried by one dimension is a weak finding, and a total that hid this would let it be read as a strong one.${
      typeof single === 'number' && typeof total === 'number'
        ? ` ${formatCount(total - single, 'match', 'matches')} are corroborated on more than one.`
        : ''
    } A shared fingerprint is counted as unscored rather than folded into a confidence average, because the platform declines to put a number on common control. Distinct onion services and clearnet hosts are counted separately from observations, since a service observed twice is one service.`,

  'infra.findings': ({ shown, total }) =>
    `Misconfigurations observed in Tor hidden services${
      total === null ? '' : `, ${total} matching the current filters`
    }${shown === null || total === null || shown === total ? '' : `, ${shown} shown`}. Each row carries its address, so a finding is actionable without a second lookup. Confidence is the detector's own score for how sure it is that the condition was present, not a probability that it means anything: an unscored detector reads as unscored and is excluded by a confidence filter rather than counted as zero. The limitations column is not a footnote — a status page, a clearnet certificate, a default banner and a shared fingerprint are each produced routinely by shared hosting, a CDN or a single scanner, and a finding rendered without that alternative is a false accusation with a bar next to it.`,

  'infra.matches': ({ shown, total }) =>
    `Candidate origin servers: hidden services paired with a clearnet host${
      total === null ? '' : `, ${total} above the stated thresholds`
    }${shown === null || total === null || shown === total ? '' : `, ${shown} shown`}. Overall is a weighted mean over the channels that were actually observable on both sides, not over a fixed denominator — a channel nobody measured is missing, not a zero. The bars are the per-channel scores, and the strongest channel is named rather than left for the reader to infer. A match whose score rests on one channel says so in the row: a 0.92 carried entirely by a shared certificate fingerprint is a weaker finding than the same score corroborated across certificate, TLS and content, and the two must not read alike.`,

  'infra.observations': ({ shown, total }) =>
    `The stored observations the correlations were computed from${
      total === null ? '' : `, ${total} in range`
    }${shown === null || total === null || shown === total ? '' : `, ${shown} shown`}. Each one holds the metadata that was actually captured — TLS version, cipher and client fingerprint, HTTP response shape, certificate identity, technology list, and the content fingerprint derived from the body — because a correlation is only as checkable as the features beside it.`,

  'infra.breakdown': () =>
    'One bar per channel, in the weight the score gave it. A channel with no bar was not observed on both sides and contributed nothing; it is left blank rather than drawn at zero, because a client that renders a missing measurement as 0 turns absent data into evidence against the correlation. Channels marked decisive are the ones that cleared their own cutoff — the certificate, content and HTTP cutoffs come from the rule this run was scored under, and the two commodity channels need to be near-identical to count. Temporal is never decisive: every observation has a time range, so counting it would give almost every pair a second voice, including two services with nothing in common that happened to be online at the same time.',

  'infra.limitations': ({ count }) =>
    `What this ${count === 1 ? 'finding does' : 'findings do'} not establish — ${formatCount(
      count,
      'note',
      'notes',
    )}, in the words of the detector that produced ${count === 1 ? 'it' : 'them'}. These are not hedges added after the fact. Shared hosting, a CDN terminating TLS, a migration between hosts and one scanner reused across a range all produce the same signals, and a register that showed only the detections would be counting coincidence as infrastructure.`,

  'infra.timeline': () =>
    'The window every figure on this page is drawn from. Findings are bounded by when they were detected, observations by when they were observed and matches by when the correlation was recorded, and the controls are in the address bar so a view of this timeline can be linked or handed over. An empty result inside a narrow window means nothing was recorded in that window — it does not mean the service was clean.',

  'persona.linkage.detail': () =>
    'One linkage. The three feature lists are named, not counted: which features agree, which disagree, and which could not be decided either way. Contested is not a synonym for weak support — it holds everything the analysis could not separate, including features measured on only one side and features the similarity function scores as perfect agreement only because both sides were zero. The limitations are what this analysis cannot see, generated by the scorer that produced the number: what a text sample leaves no trace of, what a behavioural profile cannot distinguish from a shared schedule, and which of the recorded metrics are not the model\'s output at all. Where no trained pairwise verifier was applied, the record says so rather than presenting a probability no model produced.',
};

/**
 * Said when a panel has no explanation registered for it. The point of the
 * fallback is that an unexplained figure announces itself rather than passing
 * as a self-evident one.
 */
const UNDOCUMENTED =
  'No basis has been documented for this figure. Treat it as an unlabelled number and check it against the endpoint that produced it.';

/**
 * The lead sentence for a named metric.
 *
 * Never returns an empty string: a block with no lead is exactly the failure
 * this module exists to remove.
 */
export function leadFor(metric: string, context?: Record<string, unknown>): string {
  const builder = (LEADS as Readonly<Record<string, LeadBuilder | undefined>>)[metric];
  if (builder === undefined) return UNDOCUMENTED;
  return builder(readContext(context));
}

/**
 * A count with its noun, or an em dash when the value was not returned.
 *
 * "0 links" and "not recorded" are different facts, and rendering an absent
 * count as 0 collapses them into a false one. A missing value is a statement
 * about the system, not about the case.
 */
export function formatCount(n: number | null | undefined, noun: string, plural?: string): string {
  if (typeof n !== 'number' || !Number.isFinite(n)) return EM_DASH;
  const word = Math.abs(n) === 1 ? noun : (plural ?? `${noun}s`);
  return `${n.toLocaleString('en-GB')} ${word}`;
}

/** Any optional value, formatted — or an em dash when it is absent. */
export function formatOptional<T>(
  value: T | null | undefined,
  formatter?: (value: T) => string,
): string {
  if (value === null || value === undefined) return EM_DASH;
  if (typeof value === 'string' && value.trim() === '') return EM_DASH;
  if (typeof value === 'number' && !Number.isFinite(value)) return EM_DASH;
  return formatter === undefined ? String(value) : formatter(value);
}
