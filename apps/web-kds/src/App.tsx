/**
 * KDS App — 路由入口
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { KDSBoardPage } from './pages/KDSBoardPage';
import { HistoryPage } from './pages/HistoryPage';
import { StatsPage } from './pages/StatsPage';
import { KDSConfigPage } from './pages/KDSConfigPage';
import { AlertsPage } from './pages/AlertsPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/board" replace />} />
        <Route path="/board" element={<KDSBoardPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/config" element={<KDSConfigPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
      </Routes>
    </BrowserRouter>
  );
}
