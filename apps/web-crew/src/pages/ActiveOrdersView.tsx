/**
 * 进行中订单 — 催菜/加菜入口
 * 接入 fetchActiveOrders + rushOrder 真实 API
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchActiveOrders, rushOrder, type ActiveOrder } from '../api/index';

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  muted: '#5F5E5A',
  text: '#E2EAE8',
  white: '#FFFFFF',
};

function elapsedColor(min: number): string {
  if (min > 30) return C.danger;
  if (min > 15) return C.warning;
  return C.green;
}

function elapsedLabel(min: number): string {
  if (min >= 60) return `${Math.floor(min / 60)}h${min % 60}m`;
  return `${min}分钟`;
}

export function ActiveOrdersView() {
  const navigate = useNavigate();
  const storeId = (window as any).__STORE_ID__ || 'store_001';

  const [orders, setOrders] = useState<ActiveOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [rushingIds, setRushingIds] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    fetchActiveOrders(storeId)
      .then(res => setOrders(res.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [storeId]);

  useEffect(() => {
    load();
    // 每30秒刷新一次
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [load]);

  const handleRush = async (order: ActiveOrder) => {
    if (rushingIds.has(order.order_id)) return;
    setRushingIds(prev => new Set(prev).add(order.order_id));
    try {
      await rushOrder(order.order_id);
    } catch {
      // 静默失败
    } finally {
      setRushingIds(prev => { const s = new Set(prev); s.delete(order.order_id); return s; });
    }
  };

  const handleAddDish = (order: ActiveOrder) => {
    navigate(`/order-full?table=${encodeURIComponent(order.table_no)}&order_id=${encodeURIComponent(order.order_id)}`);
  };

  const handleGoDetail = (order: ActiveOrder) => {
    navigate(`/table-detail?table=${encodeURIComponent(order.table_no)}&order_id=${encodeURIComponent(order.order_id)}`);
  };

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: C.white }}>进行中订单</h3>
        <button
          onClick={load}
          style={{
            minHeight: 40, padding: '0 14px', borderRadius: 8,
            background: 'transparent', border: `1px solid ${C.border}`,
            color: C.muted, fontSize: 16, cursor: 'pointer',
          }}
        >
          刷新
        </button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 48, color: C.muted, fontSize: 16 }}>加载中...</div>
      ) : orders.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 48, color: C.muted, fontSize: 16 }}>暂无进行中订单</div>
      ) : (
        orders.map(order => {
          const elapsedMin = Math.floor(
            (Date.now() - new Date(order.created_at).getTime()) / 60000
          );
          const color = elapsedColor(elapsedMin);
          const isRushing = rushingIds.has(order.order_id);

          return (
            <div
              key={order.order_id}
              onClick={() => handleGoDetail(order)}
              style={{
                padding: 16, marginBottom: 10, borderRadius: 12, background: C.card,
                borderLeft: `4px solid ${color}`, cursor: 'pointer',
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 20, fontWeight: 700, color: C.white }}>
                  {order.table_no} 桌
                </span>
                <span style={{ fontSize: 18, color, fontWeight: 600 }}>
                  {elapsedLabel(elapsedMin)}
                </span>
              </div>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 12 }}>
                {order.item_count} 道菜 · ¥{(order.total_fen / 100).toFixed(0)}
              </div>
              <div style={{ display: 'flex', gap: 10 }} onClick={e => e.stopPropagation()}>
                <button
                  onClick={() => handleRush(order)}
                  disabled={isRushing}
                  style={{
                    flex: 1, minHeight: 48, borderRadius: 10,
                    background: isRushing ? `${C.muted}22` : `${C.danger}22`,
                    color: isRushing ? C.muted : C.danger,
                    border: `1px solid ${isRushing ? C.border : C.danger}`,
                    fontSize: 16, fontWeight: 600, cursor: isRushing ? 'not-allowed' : 'pointer',
                    transition: 'transform .15s',
                  }}
                >
                  {isRushing ? '催菜中...' : '⚡ 催菜'}
                </button>
                <button
                  onClick={() => handleAddDish(order)}
                  style={{
                    flex: 1, minHeight: 48, borderRadius: 10,
                    background: `${C.accent}22`, color: C.accent,
                    border: `1px solid ${C.accent}`,
                    fontSize: 16, fontWeight: 600, cursor: 'pointer',
                    transition: 'transform .15s',
                  }}
                >
                  ➕ 加菜
                </button>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
