/**
 * web-admin — 总部管理后台
 * 决策1: Shell-HQ 四栏布局
 * 决策2: Agent Console 右侧面板
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ShellHQ } from './shell/ShellHQ';
import { DashboardPage } from './pages/DashboardPage';
import { StoreHealthPage } from './pages/StoreHealthPage';
import { AgentMonitorPage } from './pages/AgentMonitorPage';
import { TradePage } from './pages/TradePage';
import { CatalogPage } from './pages/CatalogPage';
import { SupplyPage } from './pages/SupplyPage';
import { OperationsPage } from './pages/OperationsPage';
import { CrmPage } from './pages/CrmPage';
import { OrgPage } from './pages/OrgPage';
import { SystemPage } from './pages/SystemPage';

function App() {
  return (
    <BrowserRouter>
      <ShellHQ>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/store-health" element={<StoreHealthPage />} />
          <Route path="/agents" element={<AgentMonitorPage />} />
          <Route path="/trade" element={<TradePage />} />
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/supply" element={<SupplyPage />} />
          <Route path="/operations" element={<OperationsPage />} />
          <Route path="/crm" element={<CrmPage />} />
          <Route path="/org" element={<OrgPage />} />
          <Route path="/system" element={<SystemPage />} />
        </Routes>
      </ShellHQ>
    </BrowserRouter>
  );
}

export default App;
