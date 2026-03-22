import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { DashboardPage } from './pages/DashboardPage';
import { StoreHealthPage } from './pages/StoreHealthPage';
import { AgentMonitorPage } from './pages/AgentMonitorPage';

const NAV_ITEMS = [
  { path: '/dashboard', label: '经营驾驶舱' },
  { path: '/store-health', label: '门店健康' },
  { path: '/agents', label: 'Agent 监控' },
];

function SideNav() {
  const location = useLocation();
  return (
    <nav style={{ width: 200, background: '#0B1A20', borderRight: '1px solid #1a2a33', padding: '16px 0' }}>
      <div style={{ padding: '8px 16px', marginBottom: 16 }}>
        <span style={{ fontSize: 18, fontWeight: 'bold', color: '#FF6B2C' }}>屯象OS</span>
        <span style={{ fontSize: 12, color: '#666', marginLeft: 8 }}>V3.0</span>
      </div>
      {NAV_ITEMS.map((item) => (
        <Link key={item.path} to={item.path}
          style={{
            display: 'block', padding: '10px 16px', color: location.pathname === item.path ? '#FF6B2C' : '#999',
            textDecoration: 'none', background: location.pathname === item.path ? '#112228' : 'transparent',
            borderLeft: location.pathname === item.path ? '3px solid #FF6B2C' : '3px solid transparent',
            fontSize: 14,
          }}>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
        <SideNav />
        <main style={{ flex: 1, overflowY: 'auto' }}>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/store-health" element={<StoreHealthPage />} />
            <Route path="/agents" element={<AgentMonitorPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
