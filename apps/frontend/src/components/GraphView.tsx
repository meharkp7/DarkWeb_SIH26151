import { cx, shortId } from '../lib/format';

export interface GraphNode {
  readonly id: string;
  /** Short display label. */
  readonly label: string;
}

export interface GraphEdge {
  readonly source: string;
  readonly target: string;
  /** Edge caption, e.g. a final score. */
  readonly label: string;
  /** `ok` when support dominates, `danger` when contradiction dominates. */
  readonly tone: 'ok' | 'danger';
}

export interface GraphViewProps {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly label: string;
  /** Called when a node is activated (click or Enter). */
  readonly onSelectNode: (id: string) => void;
}

const CHART_WIDTH = 880;
const CHART_HEIGHT = 560;
const CENTER_X = CHART_WIDTH / 2;
const CENTER_Y = CHART_HEIGHT / 2 - 10;
const RADIUS = 210;
const NODE_RADIUS = 24;

interface Point {
  readonly x: number;
  readonly y: number;
}

/**
 * Deterministic circle-layout relationship graph in inline SVG.
 * Nodes link to `/actors/:id`; edges render score captions and contradiction
 * styling (dashed red when the contradiction score beats support).
 */
export function GraphView({ nodes, edges, label, onSelectNode }: GraphViewProps) {
  if (nodes.length === 0) return null;

  const positions = new Map<string, Point>();
  nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / nodes.length;
    const x = nodes.length === 1 ? CENTER_X : CENTER_X + RADIUS * Math.cos(angle);
    const y = nodes.length === 1 ? CENTER_Y : CENTER_Y + RADIUS * Math.sin(angle);
    positions.set(node.id, { x, y });
  });

  const positionedEdges = edges.flatMap((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (source === undefined || target === undefined) return [];
    return [{ ...edge, source, target }];
  });

  return (
    <svg
      className="graph-svg"
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      <defs>
        <marker
          id="graph-arrow"
          viewBox="0 0 8 8"
          refX="7"
          refY="4"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path className="graph-svg__arrow" d="M0,0 L8,4 L0,8 z" />
        </marker>
      </defs>

      {positionedEdges.map((edge, index) => (
        <g key={`${edge.source.x}-${edge.target.x}-${index}-${edge.label}`}>
          <line
            className={cx('graph-svg__edge', `graph-svg__edge--${edge.tone}`)}
            x1={edge.source.x}
            y1={edge.source.y}
            x2={edge.target.x}
            y2={edge.target.y}
            markerEnd="url(#graph-arrow)"
          >
            <title>{edge.label}</title>
          </line>
          <text
            className="graph-svg__edge-label"
            x={(edge.source.x + edge.target.x) / 2}
            y={(edge.source.y + edge.target.y) / 2 - 6}
            textAnchor="middle"
          >
            {edge.label}
          </text>
        </g>
      ))}

      {nodes.map((node) => {
        const point = positions.get(node.id);
        if (point === undefined) return null;
        const href = `/actors/${encodeURIComponent(node.id)}`;
        return (
          <a
            key={node.id}
            href={href}
            className="graph-svg__node-link"
            aria-label={`Open actor profile ${node.label}`}
            onClick={(event) => {
              event.preventDefault();
              onSelectNode(node.id);
            }}
          >
            <circle
              className="graph-svg__node"
              cx={point.x}
              cy={point.y}
              r={NODE_RADIUS}
            >
              <title>{node.id}</title>
            </circle>
            <text className="graph-svg__node-label" x={point.x} y={point.y + 4} textAnchor="middle">
              {node.label}
            </text>
            <text
              className="graph-svg__node-id"
              x={point.x}
              y={point.y + NODE_RADIUS + 16}
              textAnchor="middle"
            >
              {shortId(node.id, 10)}
            </text>
          </a>
        );
      })}
    </svg>
  );
}
