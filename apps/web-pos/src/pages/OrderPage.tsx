/**
 * 订单详情页 — 查看已下单的订单
 */
import { useParams, useNavigate } from 'react-router-dom';

export function OrderPage() {
  const { orderId } = useParams();
  const navigate = useNavigate();

  return (
    <div style={{ padding: 24, background: '#0B1A20', minHeight: '100vh', color: '#fff' }}>
      <h2>订单详情</h2>
      <p>订单ID: {orderId}</p>
      <p style={{ color: '#999' }}>TODO: 从 tx-trade API 加载订单数据</p>
      <button
        onClick={() => navigate('/tables')}
        style={{ padding: '8px 24px', background: '#333', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
      >
        返回桌台
      </button>
    </div>
  );
}
