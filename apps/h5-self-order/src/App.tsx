import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { LangProvider } from '@/i18n/LangContext';
import ScanEntry from '@/pages/ScanEntry';
import MenuBrowse from '@/pages/MenuBrowse';
import DishDetail from '@/pages/DishDetail';
import Cart from '@/pages/Cart';
import Checkout from '@/pages/Checkout';
import OrderTrack from '@/pages/OrderTrack';
import FeedbackPage from '@/pages/FeedbackPage';
import QueuePreOrderPage from '@/pages/QueuePreOrderPage';

export default function App() {
  return (
    <LangProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ScanEntry />} />
          <Route path="/menu" element={<MenuBrowse />} />
          <Route path="/dish/:id" element={<DishDetail />} />
          <Route path="/cart" element={<Cart />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/order/:id/track" element={<OrderTrack />} />
          <Route path="/feedback/:orderId" element={<FeedbackPage />} />
          <Route path="/queue-preorder/:entryId" element={<QueuePreOrderPage />} />
        </Routes>
      </BrowserRouter>
    </LangProvider>
  );
}
