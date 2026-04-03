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
import { DiscountRequestPage } from './pages/DiscountRequestPage';
import ScanPayPage from './pages/ScanPayPage';
import { StoredValueRechargePage } from './pages/StoredValueRechargePage';
import { PrinterSettingsPage } from './pages/PrinterSettingsPage';
import { WaitlistPage } from './pages/WaitlistPage';
import { ReservationInboxPage } from './pages/ReservationInboxPage';
import { DeliveryDashboardPage } from './pages/DeliveryDashboardPage';
import { MemberLevelConfigPage } from './pages/MemberLevelConfigPage';
import { GroupDashboardPage } from './pages/GroupDashboardPage';
import { StoreDetailPage } from './pages/StoreDetailPage';
import { LiveSeafoodOrderPage } from './pages/LiveSeafoodOrderPage';
import { DailySettlementPage } from './pages/DailySettlementPage';
import { ShiftHandoverPage } from './pages/ShiftHandoverPage';
import { IssueReportPage } from './pages/IssueReportPage';
import { MemberLookupPage } from './pages/MemberLookupPage';
import { MemberPointsPage } from './pages/MemberPointsPage';
import { PointsTransactionPage } from './pages/PointsTransactionPage';
import { ApprovalPage } from './pages/ApprovalPage';
import { ManagerDashboardPage } from './pages/ManagerDashboardPage';
import { UrgePage } from './pages/UrgePage';
import { SchedulePage } from './pages/SchedulePage';
import { ClockInPage } from './pages/ClockInPage';

const tabs = [
  { path: '/tables',   label: '桌台',   icon: 'T' },
  { path: '/order',    label: '点餐',   icon: 'O' },
  { path: '/active',   label: '进行中', icon: 'A' },
  { path: '/schedule', label: '排班',   icon: 'S' },
  { path: '/cruise',   label: '巡航',   icon: 'C' },
  { path: '/delivery', label: '外卖',   icon: 'D' },
  { path: '/profile',  label: '我的',   icon: 'P' },
];

function BottomTab() {
  const loc = useLocation();
  // 在全屏子页面中隐藏底栏
  const hiddenPaths = ['/open-table', '/order-full', '/rush', '/table-ops', '/member', '/complaint', '/service-confirm', '/peak-alert', '/order-status', '/table-detail', '/table-side-pay', '/seat-split', '/crew-stats', '/manager-app', '/receiving', '/stocktake', '/handover', '/route-optimize', '/shift-schedule', '/dish-recognize', '/shift-summary', '/self-pay-link', '/discount-request', '/scan-pay', '/stored-value-recharge', '/printer-settings', '/waitlist', '/member-level-config', '/group-dashboard', '/store-detail', '/live-seafood', '/reservations', '/daily-settlement', '/shift-handover', '/issue-report', '/member-lookup', '/member-points', '/member/', '/approvals', '/manager-dashboard', '/urge', '/schedule-clock'];
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
          <Route path="/delivery" element={<DeliveryDashboardPage />} />
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
          <Route path="/discount-request" element={<DiscountRequestPage />} />
          <Route path="/scan-pay" element={<ScanPayPage />} />
          <Route path="/stored-value-recharge" element={<StoredValueRechargePage />} />
          <Route path="/printer-settings" element={<PrinterSettingsPage />} />
          <Route path="/waitlist" element={<WaitlistPage />} />
          <Route path="/member-level-config" element={<MemberLevelConfigPage />} />
          <Route path="/group-dashboard" element={<GroupDashboardPage />} />
          <Route path="/store-detail" element={<StoreDetailPage />} />
          <Route path="/live-seafood" element={<LiveSeafoodOrderPage />} />
          <Route path="/reservations" element={<ReservationInboxPage />} />
          {/* 日清日结 E1-E8 */}
          <Route path="/daily-settlement" element={<DailySettlementPage />} />
          <Route path="/shift-handover" element={<ShiftHandoverPage />} />
          <Route path="/issue-report" element={<IssueReportPage />} />
          {/* 会员积分管理 */}
          <Route path="/member-lookup" element={<MemberLookupPage />} />
          <Route path="/member-points" element={<MemberPointsPage />} />
          <Route path="/member/:memberId/points" element={<PointsTransactionPage />} />
          {/* 审批处理 */}
          <Route path="/approvals" element={<ApprovalPage />} />
          {/* 店长实时经营看板 */}
          <Route path="/manager-dashboard" element={<ManagerDashboardPage />} />
          {/* 催菜/加菜流程 */}
          <Route path="/urge" element={<UrgePage />} />
          {/* 排班查看（Tab页） */}
          <Route path="/schedule" element={<SchedulePage />} />
          {/* 打卡全屏页 */}
          <Route path="/schedule-clock" element={<ClockInPage />} />
        </Routes>
        <BottomTab />
      </div>
    </BrowserRouter>
  );
}
