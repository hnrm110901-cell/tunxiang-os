import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { getStoreToken } from './api/index';
import { PosLoginPage } from './pages/PosLoginPage';
import { InventoryAlertBanner } from './pages/InventoryAlertBanner';
import { CashierPage } from './pages/CashierPage';
import { OrderPage } from './pages/OrderPage';
import { SettlePage } from './pages/SettlePage';
import { ShiftPage } from './pages/ShiftPage';
import { TableMapPage } from './pages/TableMapPage';
import { ReservationPage } from './pages/ReservationPage';
import { OpenTablePage } from './pages/OpenTablePage';
import { ExceptionPage } from './pages/ExceptionPage';
import { POSDashboardPage } from './pages/POSDashboardPage';
import { QueuePage } from './pages/QueuePage';
import { POSSettingsPage } from './pages/POSSettingsPage';
import { POSReportsPage } from './pages/POSReportsPage';
import { CreditPayPage } from './pages/CreditPayPage';
import { ReverseSettlePage } from './pages/ReverseSettlePage';
import { SplitPayPage } from './pages/SplitPayPage';
import { TaxInvoicePage } from './pages/TaxInvoicePage';
import { HandoverPage } from './pages/HandoverPage';
import { QuickCashierPage } from './pages/QuickCashierPage';
import { WineStoragePosPage } from './pages/WineStoragePosPage';
import { DepositPosPage } from './pages/DepositPosPage';
import { CallingScreenPage } from './pages/CallingScreenPage';
import { DiscountAuditPage } from './pages/DiscountAuditPage';
import { LiveMenuEditorPage } from './pages/LiveMenuEditorPage';
import { MenuEngineeringPage } from './pages/MenuEngineeringPage';
import { MenuBoardControlPage } from './pages/MenuBoardControlPage';
import { BarCounterPage } from './pages/BarCounterPage';
import { QuickShiftReportPage } from './pages/QuickShiftReportPage';
import FoodCourtPage from './pages/FoodCourtPage';  // TC-P2-12 智慧商街档口收银
import { OmniChannelOrders } from './pages/OmniChannelOrders';  // 外卖聚合接单
import { TrainingModePage } from './pages/TrainingModePage';
import { TrainingModeBanner } from './components/TrainingModeBanner';
import { useTrainingMode } from './hooks/useTrainingMode';
import { FastFoodPage } from './pages/fastfood/FastFoodPage';
import { CallNumberScreen } from './pages/fastfood/CallNumberScreen';
import { FastFoodKDSView } from './pages/fastfood/FastFoodKDSView';
import { PrintManagerPage } from './pages/PrintManagerPage';  // 模块4.2 打印管理可视化中心
import { BanquetDepositPage } from './pages/BanquetDepositPage';  // 模块4.1 宴会定金管理

const STORE_ID: string =
  (window as unknown as Record<string, unknown>).__STORE_ID__ as string || '';

/** 内层布局组件（必须在 BrowserRouter 内，InventoryAlertBanner 需要 useNavigate） */
function AppLayout() {
  const { isTrainingMode, currentScenario, startedAt, exitTrainingMode } = useTrainingMode();

  return (
    <div style={{ minHeight: '100vh', background: '#111827' }}>
      {/* 训练模式橙色横幅 — 训练模式激活时固定在顶部 */}
      {isTrainingMode && (
        <TrainingModeBanner
          scenarioLabel={currentScenario?.label ?? null}
          startedAt={startedAt}
          onExit={exitTrainingMode}
        />
      )}
      {/* 全局库存预警横幅 — 每60秒轮询，有预警才显示 */}
      <InventoryAlertBanner storeId={STORE_ID} />

      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<POSDashboardPage />} />
        <Route path="/tables" element={<TableMapPage />} />
        <Route path="/reservations" element={<ReservationPage />} />
        <Route path="/open-table/:tableNo" element={<OpenTablePage />} />
        <Route path="/cashier/:tableNo" element={<CashierPage />} />
        <Route path="/order/:orderId" element={<OrderPage />} />
        <Route path="/settle/:orderId" element={<SettlePage />} />
        <Route path="/credit-pay/:orderId" element={<CreditPayPage />} />
        <Route path="/reverse-settle" element={<ReverseSettlePage />} />
        <Route path="/split-pay/:orderId" element={<SplitPayPage />} />
        <Route path="/tax-invoice/:orderId" element={<TaxInvoicePage />} />
        <Route path="/shift" element={<ShiftPage />} />
        <Route path="/exceptions" element={<ExceptionPage />} />
        <Route path="/queue" element={<QueuePage />} />
        <Route path="/settings" element={<POSSettingsPage />} />
        <Route path="/reports" element={<POSReportsPage />} />
        <Route path="/handover" element={<HandoverPage />} />
        <Route path="/quick-cashier" element={<QuickCashierPage />} />
        {/* ─── Phase1: 存酒 / 押金 门店操作端 ─── */}
        <Route path="/wine-storage" element={<WineStoragePosPage />} />
        <Route path="/deposits" element={<DepositPosPage />} />
        {/* ─── Phase4: 快餐叫号屏 ─── */}
        <Route path="/calling-screen" element={<CallingScreenPage />} />
        <Route path="/discount-audit" element={<DiscountAuditPage />} />
        <Route path="/live-menu" element={<LiveMenuEditorPage />} />
        <Route path="/menu-engineering" element={<MenuEngineeringPage />} />
        <Route path="/menu-board-control" element={<MenuBoardControlPage />} />
        {/* ─── TC-P0-02: 吧台盘点 ─── */}
        <Route path="/bar-counter" element={<BarCounterPage />} />
        {/* ─── TC-P1-10: 快餐结班报表 ─── */}
        <Route path="/quick/shift-report" element={<QuickShiftReportPage />} />
        {/* ─── TC-P2-12: 美食广场档口收银 ─── */}
        <Route path="/food-court" element={<FoodCourtPage />} />
        {/* ─── Phase 2B: 外卖聚合接单 ─── */}
        <Route path="/delivery" element={<OmniChannelOrders />} />
        {/* ─── 训练/演示模式入口 ─── */}
        <Route path="/training" element={<TrainingModePage />} />
        {/* ─── 模块3.1: 快餐平行流程 ─── */}
        <Route path="/fastfood" element={<FastFoodPage />} />
        <Route path="/fastfood/call-screen" element={<CallNumberScreen />} />
        <Route path="/fastfood/kds" element={<FastFoodKDSView />} />
        {/* ─── 模块4.1: 宴会定金管理 ─── */}
        <Route path="/banquet-deposit" element={<BanquetDepositPage />} />
        {/* ─── 模块4.2: 打印管理可视化中心 ─── */}
        <Route path="/print-manager" element={<PrintManagerPage />} />
      </Routes>
    </div>
  );
}

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(() => !!getStoreToken());

  if (!isLoggedIn) {
    return <PosLoginPage onLogin={() => setIsLoggedIn(true)} />;
  }

  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  );
}

export default App;
