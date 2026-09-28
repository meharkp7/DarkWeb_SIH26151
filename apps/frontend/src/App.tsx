import { Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { CasesPage } from './pages/CasesPage';
import { CaseWorkspacePage } from './pages/CaseWorkspacePage';
import { EvidencePage } from './pages/EvidencePage';
import { ActorPage } from './pages/ActorPage';
import { TimelinePage } from './pages/TimelinePage';
import { GraphPage } from './pages/GraphPage';
import { AttributionPage } from './pages/AttributionPage';
import { HypothesesPage } from './pages/HypothesesPage';
import { SourcesPage } from './pages/SourcesPage';
import { ReportsPage } from './pages/ReportsPage';
import { NotFoundPage } from './pages/NotFoundPage';

/**
 * Route table for the Investigation UI (plan §23, screens in order).
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CasesPage />} />
        <Route path="cases/:caseId" element={<CaseWorkspacePage />} />
        <Route path="evidence" element={<EvidencePage />} />
        <Route path="actors/:actorId" element={<ActorPage />} />
        <Route path="timeline" element={<TimelinePage />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="attribution" element={<AttributionPage />} />
        <Route path="hypotheses" element={<HypothesesPage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
