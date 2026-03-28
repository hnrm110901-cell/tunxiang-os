import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { CashierPage } from './pages/CashierPage';
import { MenuOrderPage } from './components/menu/MenuOrderPage';
import { ToastOpenView } from './components/menu/ToastOpenView';
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

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<POSDashboardPage />} />
        <Route path="/tables" element={<TableMapPage />} />
        <Route path="/reservations" element={<ReservationPage />} />
        <Route path="/open-table/:tableNo" element={<OpenTablePage />} />
        <Route path="/menu/:tableNo" element={<MenuOrderPage />} />
        <Route path="/toast/:tableNo" element={<ToastOpenView />} />
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
      </Routes>
    </BrowserRouter>
  );
}

export default App;
