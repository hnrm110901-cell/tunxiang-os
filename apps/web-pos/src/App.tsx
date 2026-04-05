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
import { DiscountAuditPage } from './pages/DiscountAuditPage';
import { LiveMenuEditorPage } from './pages/LiveMenuEditorPage';
import { MenuEngineeringPage } from './pages/MenuEngineeringPage';
import { MenuBoardControlPage } from './pages/MenuBoardControlPage';
import { MemberPage } from './pages/MemberPage';
import { RefundPage } from './pages/RefundPage';
import { LiveSeafoodPage } from './pages/LiveSeafoodPage';
import { ReceivingPage } from './pages/ReceivingPage';
import { BanquetPage } from './pages/BanquetPage';
import { DepositPage } from './pages/DepositPage';
import { LoginPage } from './pages/LoginPage';
import { AuthGuard } from './components/AuthGuard';
import { useAuthStore } from './store/authStore';

const STORE_ID: string =
  (window as Record<string, unknown>).__STORE_ID__ as string || '';

/** 员工信息栏 — 登录后显示在页面顶部 */
function EmployeeBar() {
  const { employee, logout } = useAuthStore();
  if (!employee) return null;

  return (
    <div
      style={{
        background: '#0B1A20',
        borderBottom: '1px solid #1E3A45',
        padding: '6px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontSize: '13px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span style={{ color: '#6B8A99' }}>当班</span>
        <span style={{ color: '#E0E7EB', fontWeight: 600 }}>{employee.name}</span>
        <span
          style={{
            background: '#1E3A45',
            color: '#FF6B2C',
            padding: '2px 8px',
            borderRadius: '4px',
            fontSize: '11px',
            fontWeight: 500,
          }}
        >
          {employee.role}
        </span>
      </div>
      <button
        onClick={logout}
        style={{
          background: 'transparent',
          border: '1px solid #1E3A45',
          color: '#6B8A99',
          padding: '4px 12px',
          borderRadius: '6px',
          fontSize: '12px',
          cursor: 'pointer',
        }}
      >
        退出登录
      </button>
    </div>
  );
}

/** 内层布局组件（必须在 BrowserRouter 内，InventoryAlertBanner 需要 useNavigate） */
function AppLayout() {
  return (
    <Routes>
      {/* 登录页 — 不受 AuthGuard 保护 */}
      <Route path="/login" element={<LoginPage />} />

      {/* 所有业务路由 — 需要登录 */}
      <Route
        path="/*"
        element={
          <AuthGuard>
            <div style={{ minHeight: '100vh', background: '#111827' }}>
              {/* 员工信息栏 */}
              <EmployeeBar />
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
                <Route path="/discount-audit" element={<DiscountAuditPage />} />
                <Route path="/live-menu" element={<LiveMenuEditorPage />} />
                <Route path="/menu-engineering" element={<MenuEngineeringPage />} />
                <Route path="/menu-board-control" element={<MenuBoardControlPage />} />
                <Route path="/members" element={<MemberPage />} />
                <Route path="/refund" element={<RefundPage />} />
                <Route path="/live-seafood" element={<LiveSeafoodPage />} />
                <Route path="/receiving" element={<ReceivingPage />} />
                <Route path="/banquet" element={<BanquetPage />} />
                <Route path="/deposits" element={<DepositPage />} />
              </Routes>
            </div>
          </AuthGuard>
        }
      />
    </Routes>
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
