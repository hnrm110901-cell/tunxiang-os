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
import { PeakAlertPage } from './pages/PeakAlertPage';
import { OrderStatusPage } from './pages/OrderStatusPage';
import { TableServedNotice } from './pages/TableServedNotice';
import { TableDetailPage } from './pages/TableDetailPage';
import TableSidePayPage from './pages/TableSidePayPage';
import { ServiceBellBadge } from './pages/ServiceBellBadge';
import { PatrolAutoCheckin } from './pages/PatrolAutoCheckin';
import { TableMapView } from './pages/TableMapView';
import { SeatSplitPage } from './pages/SeatSplitPage';
import { CrewStatsPage } from './pages/CrewStatsPage';
import { ManagerMobileApp } from './pages/ManagerMobileApp';
import { ReceivingPage } from './pages/ReceivingPage';
import { StocktakePage } from './pages/StocktakePage';
import { PurchaseApprovalPage } from './pages/PurchaseApprovalPage';
import { HandoverMobilePage } from './pages/HandoverMobilePage';
import { RouteOptimizePage } from './pages/RouteOptimizePage';
import { ShiftSchedulePage } from './pages/ShiftSchedulePage';
import DishRecognizePage from './pages/DishRecognizePage';
import { ShiftSummaryPage } from './pages/ShiftSummaryPage';
import SelfPayLinkPage from './pages/SelfPayLinkPage';

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
  const hiddenPaths = ['/open-table', '/order-full', '/rush', '/table-ops', '/member', '/complaint', '/service-confirm', '/peak-alert', '/order-status', '/table-detail', '/table-side-pay', '/seat-split', '/crew-stats', '/manager-app', '/receiving', '/stocktake', '/handover', '/route-optimize', '/shift-schedule', '/dish-recognize', '/shift-summary', '/self-pay-link'];
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
        {/* 传菜员全桌上齐通知（固定顶部横幅，WebSocket实时推送） */}
        <TableServedNotice />
        {/* 服务铃实时响应（固定右下角悬浮角标） */}
        <ServiceBellBadge storeId={(window as any).__STORE_ID__ || ''} />
        {/* 巡台自动签到（BLE感应，固定右下角，ServiceBellBadge上方） */}
        <PatrolAutoCheckin
          storeId={(window as any).__STORE_ID__ || ''}
          crewId={(window as any).__CREW_ID__ || ''}
        />
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
          <Route path="/peak-alert" element={<PeakAlertPage />} />
          <Route path="/order-status" element={<OrderStatusPage />} />
          <Route path="/table-detail" element={<TableDetailPage />} />
          <Route path="/table-side-pay" element={<TableSidePayPage />} />
          <Route path="/table-map" element={<TableMapView />} />
          <Route path="/seat-split" element={<SeatSplitPage />} />
          <Route path="/crew-stats" element={<CrewStatsPage />} />
          <Route path="/manager-app" element={<ManagerMobileApp />} />
          <Route path="/receiving" element={<ReceivingPage />} />
          <Route path="/stocktake" element={<StocktakePage />} />
          <Route path="/purchase-approval" element={<PurchaseApprovalPage />} />
          <Route path="/route-optimize" element={<RouteOptimizePage />} />
          <Route path="/handover" element={<HandoverMobilePage />} />
          <Route path="/shift-schedule" element={<ShiftSchedulePage />} />
          <Route path="/dish-recognize" element={<DishRecognizePage />} />
          <Route path="/shift-summary" element={<ShiftSummaryPage />} />
          <Route path="/self-pay-link" element={<SelfPayLinkPage />} />
        </Routes>
        <BottomTab />
      </div>
    </BrowserRouter>
  );
}
