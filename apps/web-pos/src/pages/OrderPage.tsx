/**
 * 订单详情页 — 查看已下单的订单
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import DishRecommendBanner from '../components/DishRecommendBanner';

export function OrderPage() {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const [showRecommend, setShowRecommend] = useState(true);

  return (
    <div style={{ padding: 24, background: '#0B1A20', minHeight: '100vh', color: '#fff' }}>
      <h2>订单详情</h2>

      {/* AI 个性化推荐横幅 */}
      {showRecommend && (
        <DishRecommendBanner
          tableNo={undefined}
          onDismiss={() => setShowRecommend(false)}
        />
      )}

      <p>订单ID: {orderId}</p>
      <p style={{ color: '#999' }}>TODO: 从 tx-trade API 加载订单数据</p>

      {/* 沽清菜品示例（供应链卫士） */}
      <div
        style={{
          opacity: 0.5,
          background: '#112228',
          borderRadius: 8,
          padding: '10px 14px',
          marginTop: 12,
        }}
      >
        <span style={{ color: '#fff', fontSize: 14 }}>皮皮虾（沽清）</span>
        <div
          style={{
            fontSize: 12,
            color: '#FF6B35',
            marginTop: 4,
            cursor: 'pointer',
          }}
        >
          供应链卫士：已沽清 · 替代：椒盐濑尿虾↗
        </div>
      </div>
      <button
        onClick={() => navigate('/tables')}
        style={{ padding: '8px 24px', background: '#333', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
      >
        返回桌台
      </button>
    </div>
  );
}
