import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<POSDashboardPage />} />
        <Route path="/tables" element={<TableMapPage />} />
        <Route path="/reservations" element={<ReservationPage />} />
        <Route path="/open-table/:tableNo" element={<OpenTablePage />} />
        <Route path="/cashier/:tableNo" element={<CashierPage />} />
        <Route path="/order/:orderId" element={<OrderPage />} />
        <Route path="/settle/:orderId" element={<SettlePage />} />
        <Route path="/shift" element={<ShiftPage />} />
        <Route path="/exceptions" element={<ExceptionPage />} />
        <Route path="/queue" element={<QueuePage />} />
        <Route path="/settings" element={<POSSettingsPage />} />
        <Route path="/reports" element={<POSReportsPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
