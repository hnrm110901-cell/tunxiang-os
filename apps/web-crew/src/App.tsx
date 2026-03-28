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
import { OpenTablePage } from './pages/OpenTablePage';
import { OrderPage } from './pages/OrderPage';
import { RushPage } from './pages/RushPage';
import { TableOpsPage } from './pages/TableOpsPage';
import { MemberPage } from './pages/MemberPage';
import { ComplaintPage } from './pages/ComplaintPage';
import { ServiceConfirmPage } from './pages/ServiceConfirmPage';

const tabs = [
  { path: '/tables', label: '桌台', icon: 'T' },
  { path: '/order', label: '点餐', icon: 'O' },
  { path: '/active', label: '进行中', icon: 'A' },
  { path: '/cruise', label: '巡航', icon: 'C' },
  { path: '/review', label: '复盘', icon: 'R' },
  { path: '/profile', label: '我的', icon: 'P' },
];

function BottomTab() {
  const loc = useLocation();
  // 在全屏子页面中隐藏底栏
  const hiddenPaths = ['/open-table', '/order-full', '/rush', '/table-ops', '/member', '/complaint', '/service-confirm'];
  const shouldHide = hiddenPaths.some(p => loc.pathname.startsWith(p));
  if (shouldHide) return null;

  return (
    <nav style={{
      position: 'fixed', bottom: 0, left: 0, right: 0, display: 'flex',
      background: '#112228', borderTop: '1px solid #1a2a33', padding: '8px 0',
      zIndex: 50,
    }}>
      {tabs.map(t => {
        const isActive = loc.pathname === t.path;
        return (
          <Link key={t.path} to={t.path} style={{
            flex: 1, textAlign: 'center', textDecoration: 'none',
            fontSize: 16, color: isActive ? '#FF6B2C' : '#64748b',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            gap: 2, minHeight: 48, justifyContent: 'center',
          }}>
            <span style={{
              width: 28, height: 28, borderRadius: 6,
              background: isActive ? 'rgba(255,107,44,0.15)' : 'transparent',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16, fontWeight: 700,
            }}>
              {t.icon}
            </span>
            <span style={{ fontSize: 16 }}>{t.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#fff', paddingBottom: 64 }}>
        <Routes>
          <Route path="/" element={<Navigate to="/tables" replace />} />
          {/* 主Tab页 */}
          <Route path="/tables" element={<TablesView />} />
          <Route path="/order" element={<QuickOrderView />} />
          <Route path="/active" element={<ActiveOrdersView />} />
          <Route path="/cruise" element={<DailyCruisePage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          {/* 功能子页面 */}
          <Route path="/open-table" element={<OpenTablePage />} />
          <Route path="/order-full" element={<OrderPage />} />
          <Route path="/rush" element={<RushPage />} />
          <Route path="/table-ops" element={<TableOpsPage />} />
          <Route path="/member" element={<MemberPage />} />
          <Route path="/complaint" element={<ComplaintPage />} />
          <Route path="/service-confirm" element={<ServiceConfirmPage />} />
        </Routes>
        <BottomTab />
      </div>
    </BrowserRouter>
  );
}
