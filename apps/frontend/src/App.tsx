import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { AdminPage } from './pages/AdminPage';
import { CaseWorkspacePage } from './pages/CaseWorkspacePage';
import { ActorProfilePage } from './pages/ActorProfilePage';
import { ActorsPage } from './pages/ActorsPage';
import { CasesPage } from './pages/CasesPage';
import { InfrastructurePage } from './pages/InfrastructurePage';
import { PersonasPage } from './pages/PersonasPage';
import { CommandCenterPage } from './pages/CommandCenterPage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ThreatWatchPage } from './pages/ThreatWatchPage';
import { useAuth } from './store/auth';

/**
 * The retired standalone screens.
 *
 * Evidence, Network, Timeline, Attribution, Hypotheses and Sources were each
 * a global route. Every one of them is meaningless without a case —
 * they are views *of* an investigation — so reaching them without one either
 * duplicated the workspace or silently invented a context. They now redirect
 * to the register, and the real views live in the workspace tabs.
 */
const CASE_SCOPED_RETIRED = [
  'graph',
  'evidence',
  'timeline',
  'attribution',
  'hypotheses',
  'sources',
] as const;

function SessionGate() {
  const { authenticated, busy } = useAuth();
  if (busy && !authenticated) {
    return (
      <main className="enterprise-auth enterprise-auth--v2" aria-busy="true">
        <section className="enterprise-auth__panel">
          <div className="enterprise-auth__panel-inner">
            <p className="auth-notice">Restoring analyst session…</p>
          </div>
        </section>
      </main>
    );
  }
  if (!authenticated) {
    return (
      <Routes>
        <Route
          path="*"
          element={<LoginPage />}
        />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CommandCenterPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:caseId" element={<CaseWorkspacePage />} />
        <Route path="actors" element={<ActorsPage />} />
        <Route path="actors/:actorId" element={<ActorProfilePage />} />
        <Route path="infrastructure" element={<InfrastructurePage />} />
        <Route path="personas" element={<PersonasPage />} />
        <Route path="threat-watch" element={<ThreatWatchPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="watch" element={<Navigate to="/threat-watch" replace />} />
        {CASE_SCOPED_RETIRED.map((path) => (
          <Route key={path} path={path} element={<Navigate to="/cases" replace />} />
        ))}
        {CASE_SCOPED_RETIRED.map((path) => (
          <Route
            key={`${path}-detail`}
            path={`${path}/:entityId`}
            element={<Navigate to="/cases" replace />}
          />
        ))}
        <Route path="settings" element={<Navigate to="/admin" replace />} />
        {/*
          `/reports` is retired for a different reason than the case-scoped
          screens above. Those were views *of* an investigation and needed one
          to mean anything. Reports was a standalone page for what is,
          functionally, a format choice and a download on a case — so export
          became a popover in the workspace and register headers, and the
          preview became a drawer. Old bookmarks land on the register, where the
          export control now lives.
        */}
        <Route path="reports/*" element={<Navigate to="/cases" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return <SessionGate />;
}
