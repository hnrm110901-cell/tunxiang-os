import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { LangProvider } from '@/i18n/LangContext';
import ScanEntry from '@/pages/ScanEntry';
import DemoEntry from '@/pages/DemoEntry';
import TemplateRouter from '@/templates';
import DishDetail from '@/pages/DishDetail';
import Cart from '@/pages/Cart';
import Checkout from '@/pages/Checkout';
import OrderTrack from '@/pages/OrderTrack';
import PayResultPage from '@/pages/PayResultPage';
import FeedbackPage from '@/pages/FeedbackPage';
import QueuePreOrderPage from '@/pages/QueuePreOrderPage';

export default function App() {
  return (
    <LangProvider>
      <BrowserRouter>
        <Routes>
          {/* 扫码摄像头入口（原版） */}
          <Route path="/" element={<ScanEntry />} />
          {/* 演示入口：/m?store=xxx&table=A03&demo=true */}
          <Route path="/m" element={<DemoEntry />} />
          <Route path="/menu" element={<TemplateRouter />} />
          <Route path="/dish/:id" element={<DishDetail />} />
          <Route path="/cart" element={<Cart />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/order/:id/track" element={<OrderTrack />} />
          {/* 支付结果页：/pay/:orderId/result?status=success&amount=188 */}
          <Route path="/pay/:orderId/result" element={<PayResultPage />} />
          <Route path="/feedback/:orderId" element={<FeedbackPage />} />
          <Route path="/queue-preorder/:entryId" element={<QueuePreOrderPage />} />
        </Routes>
      </BrowserRouter>
    </LangProvider>
  );
}
