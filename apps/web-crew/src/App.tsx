/**
 * 服务员端 PWA — 手机点餐/加菜/催菜/桌台状态
 */
import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { getStoreToken } from './api/index';
import { CrewLoginPage } from './pages/CrewLoginPage';
import { TXAgentAlert, type TXAgentAlertProps } from '@tx/touch';
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
// ─── Sprint 0-8: 员工端人力页面 ────────────────────────────────────────────────
import { CrewWorkbenchPage } from './pages/hr/CrewWorkbenchPage';
import { CrewMySchedulePage } from './pages/hr/CrewMySchedulePage';
import { CrewSwapRequestPage } from './pages/hr/CrewSwapRequestPage';
import { CrewOpenShiftsPage } from './pages/hr/CrewOpenShiftsPage';
import { CrewMyAttendancePage } from './pages/hr/CrewMyAttendancePage';
import { CrewAttendanceExceptionsPage } from './pages/hr/CrewAttendanceExceptionsPage';
import { CrewMyLeavePage } from './pages/hr/CrewMyLeavePage';
import { CrewLeaveNewPage } from './pages/hr/CrewLeaveNewPage';
import { CrewLeaveBalancePage } from './pages/hr/CrewLeaveBalancePage';
import { CrewMyPerformancePage } from './pages/hr/CrewMyPerformancePage';
import { CrewMyPointsPage } from './pages/hr/CrewMyPointsPage';
import { CrewPointsHistoryPage } from './pages/hr/CrewPointsHistoryPage';
import { CrewMyPayrollPage } from './pages/hr/CrewMyPayrollPage';
import { CrewMyGrowthPage } from './pages/hr/CrewMyGrowthPage';
import { CrewMyCompliancePage } from './pages/hr/CrewMyCompliancePage';
// ─── Phase 3: 店长工作台 ─────────────────────────────────────────────────────
import { OpeningChecklistPage } from './pages/manager/OpeningChecklistPage';
import { ClosingChecklistPage } from './pages/manager/ClosingChecklistPage';
import { DailyBriefPage } from './pages/manager/DailyBriefPage';
import { StoreLivePage } from './pages/manager/StoreLivePage';
import { StoreIncidentsCenterPage } from './pages/manager/StoreIncidentsCenterPage';
import { PatrolExecutionPage } from './pages/manager/PatrolExecutionPage';
// ─── 模块3.3: 供应链移动端 ────────────────────────────────────────────────────
import { MobilePurchasePage } from './pages/supply/MobilePurchasePage';
import { MobileStocktakePage } from './pages/supply/MobileStocktakePage';

// ─── Agent 预警数据结构（后续接 WebSocket 推送，暂用 mock 空数组）───────────
interface AgentAlert extends TXAgentAlertProps {
  id: string;
}

// ─── Tab 图标（Unicode emoji / 文字符号）────────────────────────────────────
const tabs = [
  { path: '/tables',   label: '桌台',   icon: '🏠' },
  { path: '/order',    label: '点餐',   icon: '📋' },
  { path: '/active',   label: '进行中', icon: '⚡' },
  { path: '/schedule', label: '排班',   icon: '📅' },
  { path: '/cruise',   label: '巡航',   icon: '🚶' },
  { path: '/delivery', label: '外卖',   icon: '🛵' },
  { path: '/profile',  label: '我的',   icon: '👤' },
];

/**
 * BottomTab — 底部导航栏（固定，高度56px，图标触控区48×48px）
 * 单手拇指可达，7个Tab，不超出屏幕宽度
 */
function BottomTab() {
  const loc = useLocation();
  // 在全屏子页面中隐藏底栏
  const hiddenPaths = [
    '/open-table', '/order-full', '/rush', '/table-ops', '/member', '/complaint',
    '/service-confirm', '/peak-alert', '/order-status', '/table-detail', '/table-side-pay',
    '/seat-split', '/crew-stats', '/manager-app', '/receiving', '/stocktake', '/handover',
    '/route-optimize', '/shift-schedule', '/dish-recognize', '/shift-summary', '/self-pay-link',
    '/discount-request', '/scan-pay', '/stored-value-recharge', '/printer-settings', '/waitlist',
    '/member-level-config', '/group-dashboard', '/store-detail', '/live-seafood', '/reservations',
    '/daily-settlement', '/shift-handover', '/issue-report', '/member-lookup', '/member-points',
    '/member/', '/approvals', '/manager-dashboard', '/manager/', '/urge', '/schedule-clock',
    '/me', '/store/', '/supply/',
  ];
  const shouldHide = hiddenPaths.some(p => loc.pathname.startsWith(p));
  if (shouldHide) return null;

  return (
    <nav
      role="tablist"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        display: 'flex',
        background: '#112228',
        borderTop: '1px solid #1a2a33',
        // 56px 内容区 + iOS safe area
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        zIndex: 50,
        WebkitTapHighlightColor: 'transparent',
      }}
    >
      {tabs.map(t => {
        const isActive = loc.pathname === t.path || loc.pathname.startsWith(t.path + '/');
        return (
          <Link
            key={t.path}
            to={t.path}
            role="tab"
            aria-selected={isActive}
            style={{
              flex: 1,
              textAlign: 'center',
              textDecoration: 'none',
              color: isActive ? 'var(--tx-primary, #FF6B35)' : '#64748b',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              // 总高度56px（图标24px + gap4px + 文字16px + padding各4px = 52px → min 56px）
              minHeight: 56,
              paddingTop: 6,
              paddingBottom: 6,
              gap: 2,
            }}
          >
            {/* 图标触控区 ≥ 48×48px */}
            <span
              style={{
                width: 48,
                height: 28,
                borderRadius: 8,
                background: isActive ? 'rgba(255,107,53,0.15)' : 'transparent',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 20,
                lineHeight: 1,
              }}
            >
              {t.icon}
            </span>
            <span style={{ fontSize: 16, fontWeight: isActive ? 600 : 400, lineHeight: 1 }}>
              {t.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(() => !!getStoreToken());
  // Agent 预警条状态（暂用空数组，后续接 WebSocket 推送替换为 useState）
  const agentAlerts: AgentAlert[] = [];

  if (!isLoggedIn) {
    return <CrewLoginPage onLogin={() => setIsLoggedIn(true)} />;
  }

  return (
    <BrowserRouter>
      <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#fff', paddingBottom: 64 }}>
        {/* Agent 预警条（有预警时显示在最顶部，高度动态，推送来源：折扣守护/出餐调度等） */}
        {agentAlerts.length > 0 && (
          <TXAgentAlert
            agentName={agentAlerts[0].agentName}
            message={agentAlerts[0].message}
            severity={agentAlerts[0].severity}
            onAction={agentAlerts[0].onAction}
            actionLabel={agentAlerts[0].actionLabel}
          />
        )}
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
          {/* ─── Phase 3: 店长工作台 ─── */}
          <Route path="/manager/opening-checklist" element={<OpeningChecklistPage />} />
          <Route path="/manager/closing-checklist" element={<ClosingChecklistPage />} />
          <Route path="/manager/daily-brief" element={<DailyBriefPage />} />
          <Route path="/manager/store-live" element={<StoreLivePage />} />
          <Route path="/manager/incidents" element={<StoreIncidentsCenterPage />} />
          <Route path="/manager/patrol" element={<PatrolExecutionPage />} />
          {/* ─── 模块3.3: 供应链移动端 ─── */}
          <Route path="/supply/purchase" element={<MobilePurchasePage />} />
          <Route path="/supply/stocktake" element={<MobileStocktakePage />} />
          {/* 催菜/加菜流程 */}
          <Route path="/urge" element={<UrgePage />} />
          {/* 排班查看（Tab页） */}
          <Route path="/schedule" element={<SchedulePage />} />
          {/* 打卡全屏页 */}
          <Route path="/schedule-clock" element={<ClockInPage />} />
          {/* ─── Sprint 0-8: 员工端人力页面 ─── */}
          <Route path="/me" element={<CrewWorkbenchPage />} />
          <Route path="/me/schedule" element={<CrewMySchedulePage />} />
          <Route path="/me/schedule/swap" element={<CrewSwapRequestPage />} />
          <Route path="/me/schedule/open-shifts" element={<CrewOpenShiftsPage />} />
          <Route path="/me/attendance" element={<CrewMyAttendancePage />} />
          <Route path="/me/attendance/exceptions" element={<CrewAttendanceExceptionsPage />} />
          <Route path="/me/leave" element={<CrewMyLeavePage />} />
          <Route path="/me/leave/new" element={<CrewLeaveNewPage />} />
          <Route path="/me/leave/balance" element={<CrewLeaveBalancePage />} />
          <Route path="/me/performance" element={<CrewMyPerformancePage />} />
          <Route path="/me/points" element={<CrewMyPointsPage />} />
          <Route path="/me/points/history" element={<CrewPointsHistoryPage />} />
          <Route path="/me/payroll" element={<CrewMyPayrollPage />} />
          <Route path="/me/growth" element={<CrewMyGrowthPage />} />
          <Route path="/me/compliance" element={<CrewMyCompliancePage />} />
        </Routes>
        <BottomTab />
      </div>
    </BrowserRouter>
  );
}
