import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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

const STORE_ID: string =
  (window as Record<string, unknown>).__STORE_ID__ as string || '';

/** 内层布局组件（必须在 BrowserRouter 内，InventoryAlertBanner 需要 useNavigate） */
function AppLayout() {
  return (
    <div style={{ minHeight: '100vh', background: '#111827' }}>
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
      </Routes>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppLayout />
    </BrowserRouter>
  );
}

export default App;
