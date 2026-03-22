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

function App() {
  return (
    <BrowserRouter>
      <ShellHQ>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/store-health" element={<StoreHealthPage />} />
          <Route path="/agents" element={<AgentMonitorPage />} />
        </Routes>
      </ShellHQ>
    </BrowserRouter>
  );
}

export default App;
