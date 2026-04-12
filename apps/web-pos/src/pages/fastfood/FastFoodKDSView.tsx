/**
 * FastFoodKDSView — 快餐 KDS 出餐视图 /fastfood/kds
 *
 * 按取餐号分组，每张卡片显示：
 *   - 取餐号（大字）
 *   - 菜品列表
 *   - 等待时长
 *   - 出餐按钮
 *
 * 出餐后：
 *   1. POST /api/v1/fastfood/orders/{id}/ready — 通知后端出餐完成
 *   2. 通过 localStorage event 推送叫号信号（降级方案，无需 WS）
 *   3. 同域部署时也可通过 /ws/calling-screen 推送（由后端处理）
 *
 * 轮询：每 8 秒刷新待出餐订单列表
 *
 * Store-POS 终端规范（TXTouch）：
 *   - 深色主题
 *   - 所有触控区域 ≥ 48px
 *   - 字体 ≥ 16px
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../../api/index';

// ─── Design Tokens ───
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  success: '#10B981',
  warning: '#F59E0B',
  danger: '#EF4444',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
  dimText: '#6B7280',
};

// ─── Types ───
interface FastFoodOrderItem {
  dish_id: string;
  dish_name: string;
  qty: number;
  unit_price_fen: number;
}

interface FastFoodOrder {
  fast_food_order_id: string;
  call_number: string;
  order_type: 'dine_in' | 'pack';
  status: 'pending' | 'preparing' | 'ready' | 'called' | 'completed';
  items: FastFoodOrderItem[];
  created_at: string;
  ready_at: string | null;
}

const ORDER_TYPE_LABEL: Record<string, string> = {
  dine_in: '堂食',
  pack: '打包',
  takeaway: '外带',
};

const ORDER_TYPE_COLOR: Record<string, string> = {
  dine_in: C.success,
  pack: C.warning,
  takeaway: C.accent,
};

const STORE_ID = (window as unknown as Record<string, unknown>).__STORE_ID__ as string || 'demo-store';

function elapsedLabel(createdAt: string): string {
  const diff = Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000);
  if (diff < 60) return `${diff}秒`;
  if (diff < 3600) return `${Math.floor(diff / 60)}分${diff % 60}秒`;
  return `${Math.floor(diff / 3600)}小时`;
}

function urgencyColor(createdAt: string): string {
  const diff = Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000);
  if (diff > 600) return C.danger;   // > 10 min
  if (diff > 300) return C.warning;  // > 5 min
  return C.success;
}

// ─── Mock data for offline/dev ───
const MOCK_ORDERS: FastFoodOrder[] = [
  {
    fast_food_order_id: 'mock-001',
    call_number: '001',
    order_type: 'dine_in',
    status: 'preparing',
    items: [
      { dish_id: 'm01', dish_name: '黄焖鸡米饭', qty: 1, unit_price_fen: 2800 },
      { dish_id: 'm10', dish_name: '冰镇绿茶', qty: 2, unit_price_fen: 800 },
    ],
    created_at: new Date(Date.now() - 180000).toISOString(),
    ready_at: null,
  },
  {
    fast_food_order_id: 'mock-002',
    call_number: '002',
    order_type: 'pack',
    status: 'preparing',
    items: [
      { dish_id: 'm03', dish_name: '牛肉面', qty: 1, unit_price_fen: 1800 },
    ],
    created_at: new Date(Date.now() - 90000).toISOString(),
    ready_at: null,
  },
];

export function FastFoodKDSView() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<FastFoodOrder[]>(MOCK_ORDERS);
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const [, forceUpdate] = useState(0); // timer-driven re-render for elapsed time
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── Tick every second to refresh elapsed times ───
  useEffect(() => {
    timerRef.current = setInterval(() => forceUpdate(n => n + 1), 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  // ─── Fetch pending orders ───
  const fetchOrders = useCallback(async () => {
    try {
      const result = await txFetch<{ items: FastFoodOrder[]; total: number }>(
        `/api/v1/fastfood/orders?store_id=${STORE_ID}&status=pending,preparing`
      );
      if (result.items) setOrders(result.items);
    } catch {
      // keep existing data on error (might be offline)
    }
  }, []);

  useEffect(() => {
    fetchOrders();
    pollRef.current = setInterval(fetchOrders, 8000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchOrders]);

  // ─── Mark as ready (出餐) ───
  const markReady = useCallback(async (order: FastFoodOrder) => {
    if (loadingIds.has(order.fast_food_order_id)) return;

    setLoadingIds(prev => new Set(prev).add(order.fast_food_order_id));
    try {
      await txFetch(`/api/v1/fastfood/orders/${order.fast_food_order_id}/ready`, {
        method: 'POST',
      });

      // Optimistic update: move to 'ready' state locally
      setOrders(prev => prev.map(o =>
        o.fast_food_order_id === order.fast_food_order_id
          ? { ...o, status: 'ready', ready_at: new Date().toISOString() }
          : o
      ));

      // Push localStorage event as fallback call-number signal
      // (CallNumberScreen listens via storage event as additional channel)
      try {
        window.localStorage.setItem(
          'tx_fastfood_call',
          JSON.stringify({ call_number: order.call_number, ts: Date.now() })
        );
      } catch {
        // localStorage might not be available
      }

      // Remove from list after 3 seconds
      setTimeout(() => {
        setOrders(prev => prev.filter(o => o.fast_food_order_id !== order.fast_food_order_id));
      }, 3000);
    } catch (err) {
      alert((err as Error).message || '出餐操作失败');
    } finally {
      setLoadingIds(prev => {
        const next = new Set(prev);
        next.delete(order.fast_food_order_id);
        return next;
      });
    }
  }, [loadingIds]);

  const pendingOrders = orders.filter(o => o.status === 'pending' || o.status === 'preparing');
  const readyOrders = orders.filter(o => o.status === 'ready');

  return (
    <div style={{ minHeight: '100vh', background: C.bg, display: 'flex', flexDirection: 'column' }}>

      {/* Header */}
      <div style={{
        padding: '12px 20px',
        background: C.card,
        borderBottom: `1px solid ${C.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ color: C.text, fontSize: 18, fontWeight: 700 }}>快餐 KDS</span>
          <span style={{
            background: C.accent,
            color: C.white,
            borderRadius: 20,
            padding: '2px 12px',
            fontSize: 14,
            fontWeight: 700,
          }}>
            待出餐 {pendingOrders.length}
          </span>
        </div>
        <button
          onClick={() => navigate('/fastfood')}
          style={{ padding: '8px 16px', background: '#1A3A48', color: C.text, border: 'none', borderRadius: 8, fontSize: 14, cursor: 'pointer' }}
        >
          返回收银
        </button>
      </div>

      <div style={{ flex: 1, padding: 16, display: 'flex', gap: 16, overflow: 'hidden' }}>

        {/* Pending / Preparing column */}
        <div style={{ flex: 3, display: 'flex', flexDirection: 'column', gap: 4, overflow: 'hidden' }}>
          <div style={{ color: C.muted, fontSize: 14, marginBottom: 8, fontWeight: 600 }}>
            制作中 ({pendingOrders.length})
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: 12,
            overflowY: 'auto',
            flex: 1,
            alignContent: 'start',
          }}>
            {pendingOrders.map(order => (
              <div
                key={order.fast_food_order_id}
                style={{
                  background: C.card,
                  border: `1px solid ${C.border}`,
                  borderRadius: 12,
                  padding: 16,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 10,
                }}
              >
                {/* Order header */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ color: C.accent, fontSize: 32, fontWeight: 900 }}>
                    #{order.call_number}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                    <div style={{
                      background: ORDER_TYPE_COLOR[order.order_type] || C.muted,
                      color: C.white,
                      borderRadius: 6,
                      padding: '2px 8px',
                      fontSize: 12,
                      fontWeight: 700,
                    }}>
                      {ORDER_TYPE_LABEL[order.order_type] || order.order_type}
                    </div>
                    <div style={{ color: urgencyColor(order.created_at), fontSize: 13, fontWeight: 600 }}>
                      {elapsedLabel(order.created_at)}
                    </div>
                  </div>
                </div>

                {/* Items */}
                <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {order.items.map((item, idx) => (
                    <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: C.text, fontSize: 14 }}>{item.dish_name}</span>
                      <span style={{
                        background: '#1A3A48',
                        color: C.white,
                        borderRadius: 4,
                        padding: '1px 8px',
                        fontSize: 14,
                        fontWeight: 700,
                        minWidth: 28,
                        textAlign: 'center',
                      }}>
                        ×{item.qty}
                      </span>
                    </div>
                  ))}
                </div>

                {/* Ready button */}
                <button
                  onClick={() => markReady(order)}
                  disabled={loadingIds.has(order.fast_food_order_id)}
                  style={{
                    height: 48,
                    background: loadingIds.has(order.fast_food_order_id) ? C.muted : C.success,
                    color: C.white,
                    border: 'none',
                    borderRadius: 8,
                    fontSize: 16,
                    fontWeight: 700,
                    cursor: loadingIds.has(order.fast_food_order_id) ? 'not-allowed' : 'pointer',
                    transition: 'background 200ms',
                    marginTop: 4,
                  }}
                  onPointerDown={e => { if (!loadingIds.has(order.fast_food_order_id)) e.currentTarget.style.transform = 'scale(0.97)'; }}
                  onPointerUp={e => (e.currentTarget.style.transform = 'scale(1)')}
                  onPointerLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
                >
                  {loadingIds.has(order.fast_food_order_id) ? '处理中...' : '出餐 ✓'}
                </button>
              </div>
            ))}

            {pendingOrders.length === 0 && (
              <div style={{ gridColumn: '1 / -1', textAlign: 'center', color: C.dimText, padding: 60, fontSize: 18 }}>
                暂无待出餐订单
              </div>
            )}
          </div>
        </div>

        {/* Ready (called) column */}
        {readyOrders.length > 0 && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, minWidth: 180 }}>
            <div style={{ color: C.muted, fontSize: 14, marginBottom: 8, fontWeight: 600 }}>
              已叫号 ({readyOrders.length})
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
              {readyOrders.map(order => (
                <div
                  key={order.fast_food_order_id}
                  style={{
                    background: C.card,
                    border: `1px solid ${C.border}`,
                    borderRadius: 10,
                    padding: '12px 16px',
                    opacity: 0.6,
                    textAlign: 'center',
                  }}
                >
                  <div style={{ color: C.success, fontSize: 28, fontWeight: 700 }}>
                    #{order.call_number}
                  </div>
                  <div style={{ color: C.muted, fontSize: 12, marginTop: 4 }}>已出餐</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default FastFoodKDSView;
