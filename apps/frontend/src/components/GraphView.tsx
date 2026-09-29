import { useMemo, useState } from 'react';
import { cx, shortId } from '../lib/format';

export interface GraphNode { readonly id: string; readonly label: string; readonly type?: string; readonly confidence?: number; }
export interface GraphEdge { readonly source: string; readonly target: string; readonly label: string; readonly tone: 'ok' | 'danger'; readonly confidence?: number; }
export interface GraphViewProps { readonly nodes: readonly GraphNode[]; readonly edges: readonly GraphEdge[]; readonly label: string; readonly onSelectNode: (id: string) => void; }

type Point = { x: number; y: number };
const W = 1180;
const H = 650;
const NODE_W = 178;
const NODE_H = 58;
const ORDER = ['actor', 'account', 'identity', 'domain', 'infrastructure', 'wallet', 'source'];

function typeLabel(type: string): string { return type.replaceAll('_', ' '); }
function layout(nodes: readonly GraphNode[]): Map<string, Point> {
  const groups = new Map<string, GraphNode[]>();
  for (const node of nodes) { const type = node.type ?? 'entity'; groups.set(type, [...(groups.get(type) ?? []), node]); }
  const ordered = [...groups.entries()].sort((a, b) => (ORDER.indexOf(a[0]) - ORDER.indexOf(b[0])) || a[0].localeCompare(b[0]));
  const cols = Math.max(1, ordered.length);
  const points = new Map<string, Point>();
  ordered.forEach(([type, list], col) => {
    const x = 120 + col * ((W - 240) / Math.max(1, cols - 1));
    const gap = Math.min(110, Math.max(78, (H - 150) / Math.max(1, list.length)));
    const start = H / 2 - ((list.length - 1) * gap) / 2;
    list.forEach((node, row) => points.set(node.id, { x, y: start + row * gap }));
  });
  return points;
}

function edgeEndpoints(a: Point, b: Point): { x1: number; y1: number; x2: number; y2: number } {
  const direction = b.x >= a.x ? 1 : -1;
  return { x1: a.x + direction * NODE_W / 2, y1: a.y, x2: b.x - direction * NODE_W / 2, y2: b.y };
}

export function GraphView({ nodes, edges, label, onSelectNode }: GraphViewProps) {
  const [selected, setSelected] = useState<string | null>(nodes[0]?.id ?? null);
  const positions = useMemo(() => layout(nodes), [nodes]);
  if (!nodes.length) return null;
  const selectedNode = nodes.find((node) => node.id === selected);
  const connected = new Set(edges.filter((edge) => edge.source === selected || edge.target === selected).flatMap((edge) => [edge.source, edge.target]));
  const colorClass = (type: string) => `entity-${type.replaceAll('_', '-')}`;

  return <div className="semantic-graph semantic-graph--intelligence">
    <div className="semantic-graph__head"><div><span className="eyebrow">Attribution relationship model</span><h3>{label}</h3><p>Relationships are rendered as traceable analytical links, not decorative topology.</p></div><div className="semantic-graph__legend"><span><i className="g-key g-key--actor" />Actor</span><span><i className="g-key g-key--entity" />Entity</span><span><i className="g-key g-key--contradiction" />Contradiction</span><b>{nodes.length} entities · {edges.length} relationships</b></div></div>
    <svg className="semantic-graph__svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      <defs><pattern id="aegis-grid-v4" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M36 0H0V36" fill="none" stroke="rgba(255,255,255,.035)" strokeWidth="1" /></pattern><marker id="aegis-arrow-v4" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#747c79" /></marker></defs>
      <rect width={W} height={H} fill="url(#aegis-grid-v4)" />
      {edges.map((edge, index) => { const a = positions.get(edge.source); const b = positions.get(edge.target); if (!a || !b) return null; const active = selected === edge.source || selected === edge.target; const p = edgeEndpoints(a, b); const midX = (p.x1 + p.x2) / 2; const midY = (p.y1 + p.y2) / 2; return <g key={`${edge.source}-${edge.target}-${index}`} className={cx('semantic-edge', active ? 'is-active' : '', edge.tone === 'danger' ? 'is-contradictory' : '')}><line x1={p.x1} y1={p.y1} x2={p.x2} y2={p.y2} markerEnd="url(#aegis-arrow-v4)" /><rect x={midX - 45} y={midY - 11} width="90" height="20" rx="4" /><text x={midX} y={midY + 3} textAnchor="middle">{active ? edge.label : `${Math.round((edge.confidence ?? 0) * 100)}%`}</text></g>; })}
      {nodes.map((node) => { const p = positions.get(node.id)!; const type = node.type ?? 'entity'; const active = selected === node.id; const related = selected === null || connected.has(node.id); return <g key={node.id} className={cx('semantic-node', colorClass(type), active ? 'is-selected' : '', related ? '' : 'is-dim')} transform={`translate(${p.x - NODE_W / 2},${p.y - NODE_H / 2})`} onClick={() => { setSelected(node.id); onSelectNode(node.id); }} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(node.id); onSelectNode(node.id); } }}>
        <rect width={NODE_W} height={NODE_H} rx="8" className="semantic-node__card" />
        <rect width="4" height={NODE_H} rx="2" className="semantic-node__rail" />
        <text x="16" y="17" className="semantic-node__type">{typeLabel(type).toUpperCase()}</text>
        <text x="16" y="35" className="semantic-node__label">{node.label.slice(0, 24)}</text>
        <text x={NODE_W - 13} y="17" textAnchor="end" className="semantic-node__confidence">{node.confidence === undefined ? '—' : `${Math.round(node.confidence * 100)}%`}</text>
        <text x="16" y="49" className="semantic-node__id">{shortId(node.id, 12)}</text>
      </g>; })}
    </svg>
    <aside className="semantic-graph__inspector">{selectedNode ? <><span className="eyebrow">Selected entity</span><strong>{selectedNode.label}</strong><span className="semantic-inspector-type">{typeLabel(selectedNode.type ?? 'entity')}</span><dl><dt>Entity identifier</dt><dd className="mono">{shortId(selectedNode.id, 20)}</dd><dt>Analytical confidence</dt><dd>{selectedNode.confidence === undefined ? '—' : `${Math.round(selectedNode.confidence * 100)}%`}</dd><dt>Observed relationships</dt><dd>{edges.filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id).length}</dd><dt>Interpretation</dt><dd>Open the supporting evidence before treating this relationship as attribution.</dd></dl></> : <span className="hint">Select an entity.</span>}</aside>
  </div>;
}
