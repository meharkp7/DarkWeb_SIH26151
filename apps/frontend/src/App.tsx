import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { CommandCenterPage } from './pages/CommandCenterPage';
import { CasesPage } from './pages/CasesPage';
import { CaseWorkspacePage } from './pages/CaseWorkspacePage';
import { ReportsPage } from './pages/ReportsPage';
import { ThreatWatchPage } from './pages/ThreatWatchPage';

export default function App() {
  return <Routes><Route element={<AppShell />}><Route index element={<CommandCenterPage />} /><Route path="cases" element={<CasesPage />} /><Route path="cases/:caseId" element={<CaseWorkspacePage />} /><Route path="watch" element={<ThreatWatchPage />} /><Route path="reports" element={<ReportsPage />} /><Route path="evidence" element={<Navigate to="/cases" replace />} /><Route path="graph" element={<Navigate to="/cases" replace />} /><Route path="timeline" element={<Navigate to="/cases" replace />} /><Route path="attribution" element={<Navigate to="/cases" replace />} /><Route path="hypotheses" element={<Navigate to="/cases" replace />} /><Route path="actors/:actorId" element={<Navigate to="/cases" replace />} /><Route path="sources" element={<Navigate to="/cases" replace />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes>;
}
