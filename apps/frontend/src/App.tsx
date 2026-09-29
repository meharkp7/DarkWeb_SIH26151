import { Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { ActorPage } from './pages/ActorPage';
import { AttributionPage } from './pages/AttributionPage';
import { CaseWorkspacePage } from './pages/CaseWorkspacePage';
import { CasesPage } from './pages/CasesPage';
import { CommandCenterPage } from './pages/CommandCenterPage';
import { EvidencePage } from './pages/EvidencePage';
import { GraphPage } from './pages/GraphPage';
import { HypothesesPage } from './pages/HypothesesPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ReportsPage } from './pages/ReportsPage';
import { SourcesPage } from './pages/SourcesPage';
import { ThreatWatchPage } from './pages/ThreatWatchPage';
import { TimelinePage } from './pages/TimelinePage';

/**
 * Every page under `pages/` is routed.
 *
 * These routes previously redirected to `/cases`, which left roughly 1,400
 * lines of built components (GraphView, EvidenceForm, EvidenceDrawer, the
 * actor profile, sources, timeline) unreachable from the UI. They are wired
 * back in here rather than deleted.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CommandCenterPage />} />

        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:caseId" element={<CaseWorkspacePage />} />

        <Route path="watch" element={<ThreatWatchPage />} />
        <Route path="reports" element={<ReportsPage />} />

        <Route path="graph" element={<GraphPage />} />
        <Route path="evidence" element={<EvidencePage />} />
        <Route path="timeline" element={<TimelinePage />} />
        <Route path="attribution" element={<AttributionPage />} />
        <Route path="hypotheses" element={<HypothesesPage />} />
        <Route path="actors/:actorId" element={<ActorPage />} />
        <Route path="sources" element={<SourcesPage />} />

        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
