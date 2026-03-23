/**
 * web-hub — 屯象科技内部运维管理商家后台
 * 橙色主题 #FF6B2C + 深色背景 #0B1A20
 */
import { BrowserRouter, Routes, Route, Navigate, NavLink, useLocation } from 'react-router-dom';
import { MerchantsPage } from './pages/MerchantsPage';
import { StoresPage } from './pages/StoresPage';
import { TemplatesPage } from './pages/TemplatesPage';
import { AdaptersPage } from './pages/AdaptersPage';
import { AgentMonitorPage } from './pages/AgentMonitorPage';
import { BillingPage } from './pages/BillingPage';
import { TicketsPage } from './pages/TicketsPage';
import { DeploymentPage } from './pages/DeploymentPage';
import { PlatformDataPage } from './pages/PlatformDataPage';

const NAV_ITEMS = [
  { path: '/merchants', label: '商户管理', icon: '🏢' },
  { path: '/stores', label: '门店总览', icon: '🏪' },
  { path: '/templates', label: '模板配置', icon: '📋' },
  { path: '/adapters', label: 'Adapter监控', icon: '🔌' },
  { path: '/agents', label: 'Agent监控', icon: '🤖' },
  { path: '/billing', label: '计费账单', icon: '💰' },
  { path: '/tickets', label: '工单中心', icon: '🎫' },
  { path: '/deployment', label: '部署管理', icon: '🖥' },
  { path: '/platform', label: '平台数据', icon: '📊' },
];

const styles = {
  container: {
    display: 'flex',
    height: '100vh',
    background: '#0B1A20',
    color: '#E0E0E0',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    margin: 0,
  } as React.CSSProperties,
  sidebar: {
    width: 220,
    minWidth: 220,
    background: '#0D2129',
    borderRight: '1px solid #1A3540',
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  } as React.CSSProperties,
  logo: {
    padding: '20px 16px',
    borderBottom: '1px solid #1A3540',
    textAlign: 'center' as const,
  } as React.CSSProperties,
  logoTitle: {
    fontSize: 16,
    fontWeight: 700,
    color: '#FF6B2C',
    margin: 0,
  } as React.CSSProperties,
  logoSub: {
    fontSize: 11,
    color: '#6B8A97',
    marginTop: 4,
  } as React.CSSProperties,
  nav: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '8px 0',
  } as React.CSSProperties,
  navItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 16px',
    fontSize: 14,
    color: '#8BA5B2',
    textDecoration: 'none',
    borderLeft: '3px solid transparent',
    transition: 'all 0.2s',
  } as React.CSSProperties,
  navItemActive: {
    color: '#FF6B2C',
    background: 'rgba(255,107,44,0.08)',
    borderLeftColor: '#FF6B2C',
  } as React.CSSProperties,
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  } as React.CSSProperties,
  topBar: {
    height: 52,
    minHeight: 52,
    background: '#0D2129',
    borderBottom: '1px solid #1A3540',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 24px',
  } as React.CSSProperties,
  topTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: '#E0E0E0',
  } as React.CSSProperties,
  topRight: {
    fontSize: 12,
    color: '#6B8A97',
  } as React.CSSProperties,
  content: {
    flex: 1,
    overflow: 'auto',
    padding: 24,
  } as React.CSSProperties,
};

function Sidebar() {
  return (
    <div style={styles.sidebar}>
      <div style={styles.logo}>
        <div style={styles.logoTitle}>屯象OS</div>
        <div style={styles.logoSub}>运维中心</div>
      </div>
      <nav style={styles.nav}>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            style={({ isActive }) => ({
              ...styles.navItem,
              ...(isActive ? styles.navItemActive : {}),
            })}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function TopBar() {
  const location = useLocation();
  const current = NAV_ITEMS.find((n) => location.pathname.startsWith(n.path));
  return (
    <div style={styles.topBar}>
      <div style={styles.topTitle}>
        屯象OS · 运维中心 {current ? `— ${current.label}` : ''}
      </div>
      <div style={styles.topRight}>运维管理员</div>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div style={styles.container}>
        <Sidebar />
        <div style={styles.main}>
          <TopBar />
          <div style={styles.content}>
            <Routes>
              <Route path="/" element={<Navigate to="/merchants" replace />} />
              <Route path="/merchants" element={<MerchantsPage />} />
              <Route path="/stores" element={<StoresPage />} />
              <Route path="/templates" element={<TemplatesPage />} />
              <Route path="/adapters" element={<AdaptersPage />} />
              <Route path="/agents" element={<AgentMonitorPage />} />
              <Route path="/billing" element={<BillingPage />} />
              <Route path="/tickets" element={<TicketsPage />} />
              <Route path="/deployment" element={<DeploymentPage />} />
              <Route path="/platform" element={<PlatformDataPage />} />
            </Routes>
          </div>
        </div>
      </div>
    </BrowserRouter>
  );
}

export default App;
