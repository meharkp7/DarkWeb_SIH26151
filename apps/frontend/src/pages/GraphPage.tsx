import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { GraphView } from '../components/GraphView';
import type { GraphEdge, GraphNode } from '../components/GraphView';
import { EmptyState } from '../components/States';
import { Panel } from '../components/Panel';
import { Badge } from '../components/Badge';
import { formatPercent } from '../lib/format';
import { useSession } from '../store/session';

/**
 * Screen 6 — relationship graph.
 *
 * No graph endpoint exists, so the view lays out the actors found in session
 * analysis hypotheses (`POST /api/v1/analysis/synthetic`) as a deterministic
 * circle graph. Nodes open their actor profile.
 */
export function GraphPage() {
  const navigate = useNavigate();
  const { analysis } = useSession();

  const nodes = useMemo<GraphNode[]>(() => {
    if (analysis === null) return [];
    const ids: string[] = [];
    for (const hypothesis of analysis.hypotheses) {
      for (const actor of [hypothesis.source_actor_id, hypothesis.target_actor_id]) {
        if (actor !== '' && !ids.includes(actor)) ids.push(actor);
      }
    }
    return ids.map((id, index) => ({ id, label: `A${index + 1}` }));
  }, [analysis]);

  const edges = useMemo<GraphEdge[]>(() => {
    if (analysis === null) return [];
    return analysis.hypotheses
      .filter(
        (hypothesis) => hypothesis.source_actor_id !== '' && hypothesis.target_actor_id !== '',
      )
      .map((hypothesis) => ({
        source: hypothesis.source_actor_id,
        target: hypothesis.target_actor_id,
        label: formatPercent(hypothesis.final_score),
        tone: hypothesis.contradiction_score > hypothesis.support_score ? ('danger' as const) : ('ok' as const),
      }));
  }, [analysis]);

  const selectNode = (id: string) => navigate(`/actors/${encodeURIComponent(id)}`);

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Graph</h1>
          <p className="page-sub">
            Actors and their attribution links. The API serves no graph route yet, so this lays out
            session analysis hypotheses — edge captions are final scores from the model run.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/hypotheses">
            {analysis === null ? 'Run an analysis' : 'Re-run analysis'}
          </Link>
        </div>
      </header>

      <Panel
        title="Actor relationships"
        description="Circle layout — deterministic, keyboard reachable, every node opens its profile."
        actions={
          <div className="legend">
            <span className="legend__item">
              <span className="legend__swatch legend__swatch--ok" aria-hidden="true" /> support-led
            </span>
            <span className="legend__item">
              <span className="legend__swatch legend__swatch--danger" aria-hidden="true" />{' '}
              contradiction-led
            </span>
          </div>
        }
      >
        {nodes.length === 0 || edges.length === 0 ? (
          <EmptyState
            title="Nothing to lay out"
            message="No graph data: neither a graph endpoint nor a session analysis run exists yet. Run the synthetic analysis to produce actors and hypothesis edges."
            endpoint="GET /api/v1/graph"
          >
            <Link className="btn btn--primary" to="/hypotheses">
              Run synthetic analysis
            </Link>
          </EmptyState>
        ) : (
          <>
            <GraphView
              nodes={nodes}
              edges={edges}
              label="Actor relationship graph from session hypotheses"
              onSelectNode={selectNode}
            />
            <p className="hint">
              <Badge tone="info">{nodes.length}</Badge> actors ·{' '}
              <Badge tone="info">{edges.length}</Badge> hypothesis edges · caption = final score.
            </p>
          </>
        )}
      </Panel>
    </div>
  );
}
