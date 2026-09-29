import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { CaseWorkspacePage } from './pages/CaseWorkspacePage';
import { CasesPage } from './pages/CasesPage';
import { CommandCenterPage } from './pages/CommandCenterPage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ReportsPage } from './pages/ReportsPage';
import { SettingsPage } from './pages/SettingsPage';
import { ThreatWatchPage } from './pages/ThreatWatchPage';
import { useAuth } from './store/auth';

export default function App() {
  const { authenticated, busy } = useAuth();
  if (busy && !authenticated) {
    return (
      <main className="enterprise-auth enterprise-auth--v2" aria-busy="true">
        <section className="enterprise-auth__panel"><div className="enterprise-auth__panel-inner"><p className="auth-notice">Restoring analyst session…</p></div></section>
      </main>
    );
  }
  if (!authenticated) return <Routes><Route path="*" element={<LoginPage />} /></Routes>;
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CommandCenterPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:caseId" element={<CaseWorkspacePage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="threat-watch" element={<ThreatWatchPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="watch" element={<Navigate to="/threat-watch" replace />} />
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
