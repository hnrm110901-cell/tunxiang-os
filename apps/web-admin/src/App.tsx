/**
 * web-admin — 总部管理后台
 * 路由已按产品域拆分到 src/routes/*.tsx
 */
import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getToken, clearAuth, isTokenExpired } from './api/client';
import { ShellHQ } from './shell/ShellHQ';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { DailyPlanPage } from './pages/DailyPlanPage';
import { SystemPage } from './pages/SystemPage';
import { PayrollPage } from './pages/PayrollPage';
// ─── 按域路由 ─────────────────────────────────────────────────────────────────
import { growthRoutes } from './routes/hq-growth';
import { opsRoutes } from './routes/hq-ops';
import { analyticsRoutes } from './routes/hq-analytics';
import { agentRoutes } from './routes/hq-agent';
import { supplyRoutes } from './routes/hq-supply';
import { hrRoutes } from './routes/hq-hr';
import { tradeRoutes } from './routes/hq-trade';
import { menuRoutes } from './routes/hq-menu';
import { storeRoutes } from './routes/hq-store';
import { mobileRoutes } from './routes/mobile';

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    const token = getToken();
    if (!token || isTokenExpired()) { clearAuth(); return false; }
    return true;
  });

  const handleLogout = () => {
    const token = getToken();
    if (token) {
      fetch('/api/v1/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    }
    clearAuth();
    setIsLoggedIn(false);
  };

  if (!isLoggedIn) { return <LoginPage onLogin={() => setIsLoggedIn(true)} />; }

  return (
    <BrowserRouter>
      <ShellHQ onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/daily-plan" element={<DailyPlanPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/payroll" element={<PayrollPage />} />
          {/* ═══ 按域路由组 ═══ */}
          {growthRoutes}
          {opsRoutes}
          {analyticsRoutes}
          {agentRoutes}
          {supplyRoutes}
          {hrRoutes}
          {tradeRoutes}
          {menuRoutes}
          {storeRoutes}
          {mobileRoutes}
        </Routes>
      </ShellHQ>
    </BrowserRouter>
  );
}

export default App;
