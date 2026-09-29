import { useMemo, useState } from 'react';
import { apiUrl } from '../../api/client';
import type { CaseGraph, CaseGraphEdge, CaseGraphNode } from '../../api/types';
import { useApi } from '../../hooks/useApi';
import { formatDate, formatPercent, shortId } from '../../lib/format';
import { InspectorRail } from '../InspectorRail';
import type { InspectorFact } from '../InspectorRail';
import { EmptyState, ErrorState, LoadingState } from '../States';

export interface NetworkGraphProps {
  readonly caseId: string;
  readonly caseName: string;
}

type LayoutMode = 'columns' | 'hierarchy' | 'force';
type Recency = 'all' | '7' | '30' | '90' | '365';

const LAYOUTS: ReadonlyArray<{ id: LayoutMode; label: string }> = [
  { id: 'columns', label: 'Columns by entity type' },
  { id: 'hierarchy', label: 'Hierarchy from hub' },
  { id: 'force', label: 'Force (deterministic)' },
];

const RECENCY: ReadonlyArray<{ id: Recency; label: string }> = [
  { id: 'all', label: 'Any time' },
  { id: '7', label: 'Seen in last 7 d' },
  { id: '30', label: 'Seen in last 30 d' },
  { id: '90', label: 'Seen in last 90 d' },
  { id: '365', label: 'Seen in last 365 d' },
];

const W = 1120;
const H = 620;
const NODE_W = 168;
const NODE_H = 52;
const LANE_X = 16;
const LANE_W = 108;

/** Above this the force pass stops being readable; the note says so on screen. */
const MAX_NODES = 70;

const GRAPH_ENDPOINT = 'GET /api/v1/cases/{id}/graph';

const GRAPH_TABS = [
  { id: 'links', label: 'Links' },
  { id: 'window', label: 'Observation window' },
] as const;

function graphPath(caseId: string, nodeTypes: readonly string[], edgeTypes: readonly string[]): string {
  const query = new URLSearchParams();
  for (const value of nodeTypes) query.append('node_type', value);
  for (const value of edgeTypes) query.append('edge_type', value);
  return `/v1/cases/${encodeURIComponent(caseId)}/graph${query.toString() === '' ? '' : `?${query.toString()}`}`;
}

interface Point {
  x: number;
  y: number;
}

function orderTypes(counts: Readonly<Record<string, number>>): string[] {
  return Object.keys(counts).sort((left, right) => (counts[right] ?? 0) - (counts[left] ?? 0) || left.localeCompare(right));
}

function groupByType(nodes: readonly CaseGraphNode[]): Map<string, CaseGraphNode[]> {
  const groups = new Map<string, CaseGraphNode[]>();
  for (const node of nodes) {
    const bucket = groups.get(node.type);
    if (bucket === undefined) groups.set(node.type, [node]);
    else bucket.push(node);
  }
  return groups;
}

function columnLayout(nodes: readonly CaseGraphNode[]): Map<string, Point> {
  const groups = groupByType(nodes);
  const types = [...groups.keys()].sort();
  const points = new Map<string, Point>();
  const usable = W - LANE_X * 2;
  types.forEach((type, column) => {
    const list = [...(groups.get(type) ?? [])].sort(
      (left, right) => right.degree - left.degree || left.label.localeCompare(right.label),
    );
    const x = LANE_X + LANE_W + (usable - LANE_W) * (types.length === 1 ? 0.5 : column / (types.length - 1));
    const gap = Math.min(84, Math.max(46, (H - 60) / Math.max(1, list.length)));
    const start = H / 2 - ((list.length - 1) * gap) / 2;
    list.forEach((node, row) => points.set(node.entity_id, { x, y: start + row * gap }));
  });
  return points;
}

function hierarchyLayout(nodes: readonly CaseGraphNode[], edges: readonly CaseGraphEdge[]): Map<string, Point> {
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  const hub = [...nodes].sort(
    (left, right) =>
      (degree.get(right.entity_id) ?? 0) - (degree.get(left.entity_id) ?? 0) || left.label.localeCompare(right.label),
  )[0];
  const points = new Map<string, Point>();
  if (hub === undefined) return points;

  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
    adjacency.set(edge.target, [...(adjacency.get(edge.target) ?? []), edge.source]);
  }

  const seen = new Set<string>([hub.entity_id]);
  points.set(hub.entity_id, { x: W / 2, y: H / 2 });
  const queue: Array<{ id: string; depth: number }> = [{ id: hub.entity_id, depth: 0 }];
  const byDepth = new Map<number, string[]>();
  while (queue.length > 0) {
    const current = queue.shift();
    if (current === undefined) break;
    if (current.depth >= 3) continue;
    for (const next of [...(adjacency.get(current.id) ?? [])].sort()) {
      if (seen.has(next)) continue;
      seen.add(next);
      byDepth.set(current.depth + 1, [...(byDepth.get(current.depth + 1) ?? []), next]);
      queue.push({ id: next, depth: current.depth + 1 });
    }
  }
  // Anything the walk never reached still deserves a slot, or the graph
  // silently shrinks without saying so.
  for (const node of nodes) {
    if (!seen.has(node.entity_id)) byDepth.set(1, [...(byDepth.get(1) ?? []), node.entity_id]);
  }

  for (const [depth, ids] of byDepth) {
    const radius = 110 + depth * 130;
    ids.forEach((id, index) => {
      const angle = (2 * Math.PI * index) / Math.max(1, ids.length) - Math.PI / 2;
      points.set(id, {
        x: Math.min(W - NODE_W / 2, Math.max(NODE_W / 2, W / 2 + radius * Math.cos(angle))),
        y: Math.min(H - 40, Math.max(30, H / 2 + radius * Math.sin(angle) * 0.82)),
      });
    });
  }
  return points;
}

/**
 * Deterministic force relaxation.
 *
 * No physics library and no `Math.random`: the same graph always produces the
 * same picture, which matters when two analysts are looking at the same case.
 */
function forceLayout(nodes: readonly CaseGraphNode[], edges: readonly CaseGraphEdge[]): Map<string, Point> {
  const points = new Map<string, Point>();
  const index = new Map<string, number>();
  nodes.forEach((node, position) => {
    index.set(node.entity_id, position);
    // Seed on a phyllotaxis spiral — even spacing, no randomness, stable order.
    const angle = position * 2.399963;
    const radius = 26 * Math.sqrt(position);
    points.set(node.entity_id, { x: W / 2 + radius * Math.cos(angle), y: H / 2 + radius * Math.sin(angle) });
  });
  if (nodes.length < 2) return points;

  const links = edges
    .map((edge) => [index.get(edge.source), index.get(edge.target)] as const)
    .filter((pair): pair is readonly [number, number] => pair[0] !== undefined && pair[1] !== undefined);

  for (let step = 0; step < 160; step += 1) {
    const cooling = 1 - step / 160;
    const forces = new Map<string, { x: number; y: number }>();
    for (const node of nodes) forces.set(node.entity_id, { x: 0, y: 0 });
    for (let i = 0; i < nodes.length; i += 1) {
      const a = nodes[i];
      if (a === undefined) continue;
      const pa = points.get(a.entity_id);
      if (pa === undefined) continue;
      for (let j = i + 1; j < nodes.length; j += 1) {
        const b = nodes[j];
        if (b === undefined) continue;
        const pb = points.get(b.entity_id);
        if (pb === undefined) continue;
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) {
          dx = (i - j) * 0.5 + 0.5;
          dy = 0.5;
          dist = Math.hypot(dx, dy);
        }
        const push = (5200 / (dist * dist)) * cooling;
        const fa = forces.get(a.entity_id);
        const fb = forces.get(b.entity_id);
        if (fa !== undefined) {
          fa.x += (dx / dist) * push;
          fa.y += (dy / dist) * push;
        }
        if (fb !== undefined) {
          fb.x -= (dx / dist) * push;
          fb.y -= (dy / dist) * push;
        }
      }
    }
    for (const [source, target] of links) {
      const a = nodes[source];
      const b = nodes[target];
      if (a === undefined || b === undefined) continue;
      const pa = points.get(a.entity_id);
      const pb = points.get(b.entity_id);
      const fa = forces.get(a.entity_id);
      const fb = forces.get(b.entity_id);
      if (pa === undefined || pb === undefined || fa === undefined || fb === undefined) continue;
      const dx = pb.x - pa.x;
      const dy = pb.y - pa.y;
      const dist = Math.max(1, Math.hypot(dx, dy));
      const pull = ((dist - 150) / 150) * 0.5;
      fa.x += (dx / dist) * pull * 40;
      fa.y += (dy / dist) * pull * 40;
      fb.x -= (dx / dist) * pull * 40;
      fb.y -= (dy / dist) * pull * 40;
    }
    for (const node of nodes) {
      const point = points.get(node.entity_id);
      const force = forces.get(node.entity_id);
      if (point === undefined || force === undefined) continue;
      point.x = Math.min(W - NODE_W / 2, Math.max(NODE_W / 2, point.x + Math.max(-28, Math.min(28, force.x)) * cooling));
      point.y = Math.min(H - NODE_H / 2, Math.max(NODE_H / 2, point.y + Math.max(-28, Math.min(28, force.y)) * cooling));
    }
  }
  return points;
}

function recencyCutoff(days: Recency): number | null {
  if (days === 'all') return null;
  return Date.now() - Number(days) * 86_400_000;
}

function withinRecency(node: CaseGraphNode, cutoff: number | null): boolean {
  if (cutoff === null) return true;
  const seen = Date.parse(node.last_seen ?? node.first_seen ?? '');
  if (Number.isNaN(seen)) return true;
  return seen >= cutoff;
}

function endpoints(a: Point, b: Point) {
  const direction = b.x >= a.x ? 1 : -1;
  return {
    x1: a.x + (direction * NODE_W) / 2,
    y1: a.y,
    x2: b.x - (direction * NODE_W) / 2,
    y2: b.y,
  };
}

function clip(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}

/**
 * Case network.
 *
 * Entity-type and edge-type filters are pushed to the API so the counts the
 * analyst reads are the server's counts; recency is a browser-side control
 * because the graph endpoint has no time parameter, and the header says which
 * is which.
 */
export function NetworkGraph({ caseId, caseName }: NetworkGraphProps) {
  const [layout, setLayout] = useState<LayoutMode>('columns');
  const [nodeTypes, setNodeTypes] = useState<readonly string[]>([]);
  const [edgeTypes, setEdgeTypes] = useState<readonly string[]>([]);
  const [recency, setRecency] = useState<Recency>('all');
  const [selected, setSelected] = useState<string | null>(null);
  const [railTab, setRailTab] = useState<string>('links');

  const unfiltered = useApi<CaseGraph>(apiUrl(`/v1/cases/${encodeURIComponent(caseId)}/graph`));
  const filteredUrl = useMemo(() => {
    if (nodeTypes.length === 0 && edgeTypes.length === 0) return null;
    return apiUrl(graphPath(caseId, nodeTypes, edgeTypes));
  }, [caseId, nodeTypes, edgeTypes]);
  const filtered = useApi<CaseGraph>(filteredUrl);

  const resource = filteredUrl === null ? unfiltered : filtered;
  const graph = resource.data;

  const typeOptions = useMemo(() => {
    const source = graph ?? unfiltered.data;
    return {
      nodes: orderTypes(source?.node_types ?? {}),
      edges: orderTypes(source?.edge_types ?? {}),
    };
  }, [graph, unfiltered.data]);

  const visible = useMemo(() => {
    if (graph === null || graph === undefined) return { nodes: [] as CaseGraphNode[], edges: [] as CaseGraphEdge[], dropped: 0 };
    const cutoff = recencyCutoff(recency);
    const fresh = graph.nodes.filter((node) => withinRecency(node, cutoff));
    const allowed = new Set(fresh.map((node) => node.entity_id));
    const edges = graph.edges.filter((edge) => allowed.has(edge.source) && allowed.has(edge.target));
    // Highest-degree first: the entities a case turns on are the ones an
    // analyst opens the network to look at.
    const nodes = [...fresh].sort((left, right) => right.degree - left.degree || left.label.localeCompare(right.label));
    return { nodes: nodes.slice(0, MAX_NODES), edges: edges.slice(0, 220), dropped: nodes.length - Math.min(nodes.length, MAX_NODES) };
  }, [graph, recency]);

  const positions = useMemo(() => {
    if (visible.nodes.length === 0) return new Map<string, Point>();
    if (layout === 'hierarchy') return hierarchyLayout(visible.nodes, visible.edges);
    if (layout === 'force') return forceLayout(visible.nodes, visible.edges);
    return columnLayout(visible.nodes);
  }, [visible, layout]);

  const selectedNode = visible.nodes.find((node) => node.entity_id === selected) ?? null;

  const nodeEdges = useMemo(() => {
    if (selectedNode === null) return [] as CaseGraphEdge[];
    return visible.edges
      .filter((edge) => edge.source === selectedNode.entity_id || edge.target === selectedNode.entity_id)
      .slice(0, 12);
  }, [selectedNode, visible.edges]);

  const selectedFacts: InspectorFact[] =
    selectedNode === null
      ? []
      : [
          { label: 'Entity type', value: selectedNode.type.replaceAll('_', ' ') },
          { label: 'Degree', value: selectedNode.degree, mono: true },
          { label: 'Evidence', value: selectedNode.evidence_count, mono: true },
          { label: 'Modality', value: selectedNode.modality === null ? '—' : selectedNode.modality.replaceAll('_', ' ') },
        ];

  const connected = useMemo(() => {
    if (selected === null) return new Set<string>();
    const set = new Set<string>();
    for (const edge of visible.edges) {
      if (edge.source === selected) set.add(edge.target);
      if (edge.target === selected) set.add(edge.source);
    }
    return set;
  }, [selected, visible.edges]);

  const toggle = (value: string, current: readonly string[]) =>
    current.includes(value) ? current.filter((item) => item !== value) : [...current, value];

  return (
    <div className="panel">
      <div className="panel__head">
        <div className="panel__headings">
          <h2 className="panel__title">Entity network</h2>
          <p className="panel__desc">
            {caseName} — nodes are entities, edges are observed relationships. Every edge
            carries the evidence behind it; open the inspector before treating a link as attribution.
          </p>
        </div>
        <div className="panel__actions">
          <span className="surface-meta">
            {visible.nodes.length} node{visible.nodes.length === 1 ? '' : 's'} · {visible.edges.length}{' '}
            link{visible.edges.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      <div className="inv-network__controls">
        <label className="sr-only" htmlFor="inv-graph-layout">
          Graph layout
        </label>
        <select
          id="inv-graph-layout"
          className="inv-select"
          value={layout}
          onChange={(event) => setLayout(event.target.value as LayoutMode)}
        >
          {LAYOUTS.map((item) => (
            <option key={item.id} value={item.id}>
              Layout: {item.label}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="inv-graph-recency">
          Recency window
        </label>
        <select
          id="inv-graph-recency"
          className="inv-select"
          value={recency}
          onChange={(event) => setRecency(event.target.value as Recency)}
        >
          {RECENCY.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
        <span className="inv-ledger-filters" style={{ border: 0, padding: 0, gap: 6 }}>
          <span className="hint" id="inv-node-type-label">
            Entity types
          </span>
          {typeOptions.nodes.map((type) => (
            <button
              key={type}
              type="button"
              className="inv-toggle"
              aria-pressed={nodeTypes.includes(type)}
              onClick={() => setNodeTypes((current) => toggle(type, current))}
            >
              {type.replaceAll('_', ' ')}
            </button>
          ))}
        </span>
        <span className="inv-ledger-filters" style={{ border: 0, padding: 0, gap: 6 }}>
          <span className="hint">Edge types</span>
          {typeOptions.edges.map((type) => (
            <button
              key={type}
              type="button"
              className="inv-toggle"
              aria-pressed={edgeTypes.includes(type)}
              onClick={() => setEdgeTypes((current) => toggle(type, current))}
            >
              {type.replaceAll('_', ' ')}
            </button>
          ))}
        </span>
      </div>

      <div className="panel__body">
        {resource.loading && <LoadingState label="Building entity graph…" />}
        {resource.error !== null && <ErrorState message={resource.error} onRetry={resource.reload} />}
        {!resource.loading && resource.error === null && visible.nodes.length === 0 && (
          <EmptyState
            title="No entities"
            message="No entity has been resolved for this investigation, or every entity was excluded by the current filters."
            endpoint={GRAPH_ENDPOINT}
          />
        )}
        {!resource.loading && resource.error === null && visible.nodes.length > 0 && (
          <div className={selectedNode === null ? 'insp-shell' : 'insp-shell has-rail'}>
            <div>
              <svg
                className="inv-network__canvas"
                viewBox={`0 0 ${W} ${H}`}
                role="img"
                aria-label={`Entity relationship graph for ${caseName}: ${visible.nodes.length} entities and ${visible.edges.length} relationships`}
              >
                <defs>
                  <marker
                    id="inv-graph-arrow"
                    viewBox="0 0 10 10"
                    refX="9"
                    refY="5"
                    markerWidth="5"
                    markerHeight="5"
                    orient="auto"
                  >
                    <path d="M0 0L10 5L0 10z" fill="#6c7370" />
                  </marker>
                </defs>
                {visible.edges.map((edge) => {
                  const a = positions.get(edge.source);
                  const b = positions.get(edge.target);
                  if (a === undefined || b === undefined) return null;
                  const p = endpoints(a, b);
                  const active = selected === edge.source || selected === edge.target;
                  return (
                    <line
                      key={edge.relationship_id}
                      className={[
                        'inv-edge',
                        active ? 'is-active' : '',
                        edge.confidence < 0.5 ? 'is-weak' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      x1={p.x1}
                      y1={p.y1}
                      x2={p.x2}
                      y2={p.y2}
                      markerEnd="url(#inv-graph-arrow)"
                    >
                      <title>{`${edge.type} · confidence ${formatPercent(edge.confidence)} · ${edge.evidence_ids.length} backing record(s)`}</title>
                    </line>
                  );
                })}
                {visible.nodes.map((node) => {
                  const point = positions.get(node.entity_id);
                  if (point === undefined) return null;
                  const isSelected = selected === node.entity_id;
                  const dim = selected !== null && !isSelected && !connected.has(node.entity_id);
                  return (
                    <g
                      key={node.entity_id}
                      className={['inv-node', isSelected ? 'is-selected' : '', dim ? 'is-dim' : '']
                        .filter(Boolean)
                        .join(' ')}
                      transform={`translate(${point.x - NODE_W / 2},${point.y - NODE_H / 2})`}
                      role="button"
                      tabIndex={0}
                      aria-pressed={isSelected}
                      aria-label={`${node.label}, ${node.type.replaceAll('_', ' ')}, degree ${node.degree}`}
                      onClick={() => setSelected(isSelected ? null : node.entity_id)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          setSelected(isSelected ? null : node.entity_id);
                        }
                      }}
                    >
                      <rect width={NODE_W} height={NODE_H} rx="7" className="inv-node__card" />
                      <rect width={4} height={NODE_H} rx="2" className="inv-node__rail" />
                      <text x="14" y="16" className="inv-node__type">
                        {node.type.replaceAll('_', ' ')}
                      </text>
                      <text x="14" y="32" className="inv-node__label">
                        {clip(node.label, 22)}
                      </text>
                      <text x="14" y="45" className="inv-node__meta">
                        {`deg ${node.degree} · ${node.evidence_count} ev · ${formatPercent(node.confidence)}`}
                      </text>
                    </g>
                  );
                })}
              </svg>
              {visible.dropped > 0 && (
                <p className="hint">
                  {visible.dropped} further entit{visible.dropped === 1 ? 'y is' : 'ies are'} not
                  drawn — the network is capped at {MAX_NODES} nodes so the picture stays readable.
                  Narrow the entity-type filter to see the rest.
                </p>
              )}
              <p className="hint">
                Recency is applied in the browser ({recency === 'all' ? 'no window' : `last ${recency} days`});
                entity and edge type filters are applied by the API.
              </p>
            </div>

            <InspectorRail
              open={selectedNode !== null}
              onClose={() => setSelected(null)}
              title={selectedNode?.label ?? 'Entity'}
              subtitle={selectedNode === null ? undefined : selectedNode.type.replaceAll('_', ' ')}
              empty="Select an entity in the graph to read its observation window, degree and corroborating evidence count."
              status={
                selectedNode === null
                  ? undefined
                  : [
                      { label: selectedNode.type.replaceAll('_', ' '), tone: 'muted' as const },
                      {
                        label: `${selectedNode.evidence_count} evidence record${selectedNode.evidence_count === 1 ? '' : 's'}`,
                        tone: selectedNode.evidence_count > 0 ? ('ok' as const) : ('muted' as const),
                      },
                    ]
              }
              confidence={
                selectedNode === null ? undefined : { value: selectedNode.confidence, kind: 'estimate' as const }
              }
              facts={selectedFacts}
              identifiers={selectedNode === null ? undefined : [{ kind: 'entity_id', value: selectedNode.entity_id }]}
              summary={
                selectedNode === null || selectedNode.modality === null
                  ? undefined
                  : `Modality ${selectedNode.modality.replaceAll('_', ' ')}`
              }
              tabs={GRAPH_TABS}
              activeTab={railTab}
              onTabChange={setRailTab}
              tabPanels={{
                links: (
                  <ul className="insp-panel-list">
                    {nodeEdges.map((edge) => {
                      const peer = edge.source === selectedNode?.entity_id ? edge.target : edge.source;
                      const other = visible.nodes.find((node) => node.entity_id === peer);
                      return (
                        <li key={edge.relationship_id}>
                          <button
                            type="button"
                            className="insp-panel-list__row insp-panel-list__row--button"
                            onClick={() => setSelected(peer)}
                          >
                            <span>{`${edge.type} → ${other?.label ?? shortId(peer, 12)}`}</span>
                            <span className="insp-panel-list__meta">
                              {`${formatPercent(edge.confidence)} · ${edge.evidence_ids.length} ev`}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                    {nodeEdges.length === 0 && <li className="hint">No relationships in the current view.</li>}
                  </ul>
                ),
                window: (
                  <dl className="insp-facts">
                    <div className="insp-facts__row">
                      <dt className="insp-facts__label">First seen</dt>
                      <dd className="insp-facts__value">{formatDate(selectedNode?.first_seen)}</dd>
                    </div>
                    <div className="insp-facts__row">
                      <dt className="insp-facts__label">Last seen</dt>
                      <dd className="insp-facts__value">{formatDate(selectedNode?.last_seen)}</dd>
                    </div>
                    <div className="insp-facts__row">
                      <dt className="insp-facts__label">Degree</dt>
                      <dd className="insp-facts__value insp-facts__value--mono">{selectedNode?.degree ?? 0}</dd>
                    </div>
                    <div className="insp-facts__row">
                      <dt className="insp-facts__label">Normalized</dt>
                      <dd className="insp-facts__value insp-facts__value--mono">
                        {shortId(selectedNode?.normalized_form ?? '', 20)}
                      </dd>
                    </div>
                  </dl>
                ),
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
