import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { CashierPage } from './pages/CashierPage';
import { OrderPage } from './pages/OrderPage';
import { SettlePage } from './pages/SettlePage';
import { ShiftPage } from './pages/ShiftPage';
import { TableMapPage } from './pages/TableMapPage';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/tables" replace />} />
        <Route path="/tables" element={<TableMapPage />} />
        <Route path="/cashier/:tableNo" element={<CashierPage />} />
        <Route path="/order/:orderId" element={<OrderPage />} />
        <Route path="/settle/:orderId" element={<SettlePage />} />
        <Route path="/shift" element={<ShiftPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
