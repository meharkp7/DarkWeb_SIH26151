import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { CaseWorkspacePage } from './pages/CaseWorkspacePage';
import { CasesPage } from './pages/CasesPage';
import { CommandCenterPage } from './pages/CommandCenterPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import { ThreatWatchPage } from './pages/ThreatWatchPage';

/**
 * Five primary spaces, and nothing else.
 *
 *   Command Center  what is happening right now
 *   Cases           the investigation index
 *   Investigation   one case, five views (Overview/Evidence/Network/Timeline/Assessment)
 *   Reports         output, not another analysis screen
 *   Threat Watch    what changed that I should care about
 *
 * Everything case-scoped lives inside the workspace, so the former global
 * analysis pages (/graph, /evidence, /timeline, /attribution, /hypotheses,
 * /sources, /actors/:id) are no longer top-level destinations — they were
 * the same information sliced a second time, reachable without a case
 * context, which is not how an investigator works. They redirect to /cases
 * rather than 404ing so old links and bookmarks still land somewhere sane.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CommandCenterPage />} />

        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:caseId" element={<CaseWorkspacePage />} />

        <Route path="reports" element={<ReportsPage />} />
        <Route path="threat-watch" element={<ThreatWatchPage />} />
        <Route path="settings" element={<SettingsPage />} />

        {/* Canonical path is /threat-watch; /watch was the old name. */}
        <Route path="watch" element={<Navigate to="/threat-watch" replace />} />

        {/*
          Retired global analysis surfaces. These components still exist and
          remain reachable from inside the workspace; only their old
          standalone entry points are gone.
        */}
        <Route path="graph" element={<Navigate to="/cases" replace />} />
        <Route path="evidence" element={<Navigate to="/cases" replace />} />
        <Route path="timeline" element={<Navigate to="/cases" replace />} />
        <Route path="attribution" element={<Navigate to="/cases" replace />} />
        <Route path="hypotheses" element={<Navigate to="/cases" replace />} />
        <Route path="sources" element={<Navigate to="/cases" replace />} />
        <Route path="actors/:actorId" element={<Navigate to="/cases" replace />} />

        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
