/**
 * 服务员端 PWA — 手机点餐/加菜/催菜/桌台状态
 */
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { TablesView } from './pages/TablesView';
import { QuickOrderView } from './pages/QuickOrderView';
import { ActiveOrdersView } from './pages/ActiveOrdersView';
import { DailyCruisePage } from './pages/DailyCruisePage';
import { ReviewPage } from './pages/ReviewPage';
import { ProfilePage } from './pages/ProfilePage';

const tabs = [
  { path: '/tables', label: '桌台', icon: '🪑' },
  { path: '/order', label: '点餐', icon: '📋' },
  { path: '/active', label: '进行中', icon: '🔥' },
  { path: '/cruise', label: '巡航', icon: '🚀' },
  { path: '/review', label: '复盘', icon: '📊' },
  { path: '/profile', label: '我的', icon: '👤' },
];

function BottomTab() {
  const loc = useLocation();
  return (
    <nav style={{
      position: 'fixed', bottom: 0, left: 0, right: 0, display: 'flex',
      background: '#112228', borderTop: '1px solid #1a2a33', padding: '8px 0',
    }}>
      {tabs.map(t => (
        <Link key={t.path} to={t.path} style={{
          flex: 1, textAlign: 'center', textDecoration: 'none', fontSize: 12,
          color: loc.pathname === t.path ? '#FF6B2C' : '#666',
        }}>
          <div style={{ fontSize: 20 }}>{t.icon}</div>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#fff', paddingBottom: 64 }}>
        <Routes>
          <Route path="/" element={<Navigate to="/tables" replace />} />
          <Route path="/tables" element={<TablesView />} />
          <Route path="/order" element={<QuickOrderView />} />
          <Route path="/active" element={<ActiveOrdersView />} />
          <Route path="/cruise" element={<DailyCruisePage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Routes>
        <BottomTab />
      </div>
    </BrowserRouter>
  );
}
