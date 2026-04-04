/**
 * 订单详情页 — 查看已下单的订单详情
 * 从 tx-trade API 加载订单数据，展示订单信息、菜品明细、价格汇总
 */
import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getOrder, printReceipt as apiPrintReceipt } from '../api/tradeApi';
import { printReceipt as bridgePrint } from '../bridge/TXBridge';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface OrderItemData {
  item_id: string;
  dish_id: string;
  dish_name: string;
  quantity: number;
  unit_price_fen: number;
  subtotal_fen: number;
  notes?: string;
}

interface OrderData {
  order_id: string;
  order_no: string;
  table_no: string;
  order_type: 'dine_in' | 'takeout' | 'pickup';
  status: 'pending' | 'confirmed' | 'cooking' | 'completed' | 'settled' | 'cancelled';
  items: OrderItemData[];
  total_amount_fen: number;
  discount_amount_fen: number;
  final_amount_fen: number;
  created_at: string;
  updated_at?: string;
  customer_count?: number;
  remark?: string;
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const ORDER_TYPE_LABEL: Record<string, string> = {
  dine_in: '堂食',
  takeout: '外卖',
  pickup: '自取',
};

const STATUS_CONFIG: Record<string, { label: string; bg: string; color: string }> = {
  pending:   { label: '待确认', bg: 'rgba(250,173,20,0.15)', color: '#faad14' },
  confirmed: { label: '已确认', bg: 'rgba(24,144,255,0.15)', color: '#1890ff' },
  cooking:   { label: '制作中', bg: 'rgba(250,140,22,0.15)', color: '#fa8c16' },
  completed: { label: '已完成', bg: 'rgba(82,196,26,0.15)', color: '#52c41a' },
  settled:   { label: '已结算', bg: 'rgba(82,196,26,0.15)', color: '#52c41a' },
  cancelled: { label: '已取消', bg: 'rgba(255,77,79,0.15)', color: '#ff4d4f' },
};

const formatTime = (iso: string): string => {
  try {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return iso;
  }
};

// ─── 组件 ─────────────────────────────────────────────────────────────────────

export function OrderPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();

  const [order, setOrder] = useState<OrderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);

  // ── 加载订单数据 ──

  const loadOrder = useCallback(async () => {
    if (!orderId) {
      setError('缺少订单ID');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const data = await getOrder(orderId);
      setOrder(data as unknown as OrderData);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载订单失败');
    } finally {
      setLoading(false);
    }
  }, [orderId]);

  useEffect(() => {
    loadOrder();
  }, [loadOrder]);

  // ── 打印小票 ──

  const handlePrint = async () => {
    if (!orderId || printing) return;
    setPrinting(true);

    try {
      const { content_base64 } = await apiPrintReceipt(orderId);
      await bridgePrint(content_base64);
    } catch (err) {
      alert(`打印失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setPrinting(false);
    }
  };

  // ── 加载状态 ──

  if (loading) {
    return (
      <div style={pageStyle}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: 16 }}>
          <div style={spinnerStyle} />
          <span style={{ color: '#8A94A4', fontSize: 17 }}>加载订单中...</span>
        </div>
      </div>
    );
  }

  // ── 错误状态 ──

  if (error || !order) {
    return (
      <div style={pageStyle}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: 16 }}>
          <div style={{ fontSize: 48 }}>!</div>
          <span style={{ color: '#ff4d4f', fontSize: 18 }}>{error || '订单不存在'}</span>
          <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
            <button type="button" onClick={loadOrder} style={{ ...btnBase, background: '#1a2a33', color: '#fff' }}>
              重试
            </button>
            <button type="button" onClick={() => navigate('/tables')} style={{ ...btnBase, background: '#333', color: '#999' }}>
              返回桌台
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── 订单数据 ──

  const statusCfg = STATUS_CONFIG[order.status] || STATUS_CONFIG.pending;
  const isActive = order.status === 'pending' || order.status === 'confirmed' || order.status === 'cooking';

  return (
    <div style={pageStyle}>
      <div style={{ maxWidth: 800, margin: '0 auto', padding: 20 }}>

        {/* ── 顶部导航栏 ── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <button
            type="button"
            onClick={() => navigate('/tables')}
            style={{ background: 'none', border: 'none', color: '#8A94A4', fontSize: 16, cursor: 'pointer', padding: '8px 0', fontFamily: 'inherit' }}
          >
            &larr; 返回桌台
          </button>
          <span style={{ color: '#8A94A4', fontSize: 14 }}>{formatTime(order.created_at)}</span>
        </div>

        {/* ── 订单头部卡片 ── */}
        <div style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#fff', marginBottom: 6 }}>
                {order.order_no}
              </div>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                {/* 桌号 */}
                <span style={tagStyle}>桌 {order.table_no}</span>
                {/* 订单类型 */}
                <span style={{ ...tagStyle, background: 'rgba(24,144,255,0.15)', color: '#1890ff' }}>
                  {ORDER_TYPE_LABEL[order.order_type] || order.order_type}
                </span>
                {/* 人数 */}
                {order.customer_count != null && order.customer_count > 0 && (
                  <span style={{ ...tagStyle, background: 'rgba(82,196,26,0.15)', color: '#52c41a' }}>
                    {order.customer_count}人
                  </span>
                )}
              </div>
            </div>
            {/* 状态徽章 */}
            <div style={{
              padding: '6px 16px',
              borderRadius: 20,
              background: statusCfg.bg,
              color: statusCfg.color,
              fontSize: 15,
              fontWeight: 600,
              whiteSpace: 'nowrap',
            }}>
              {statusCfg.label}
            </div>
          </div>

          {order.remark && (
            <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 6, background: 'rgba(250,173,20,0.1)', color: '#faad14', fontSize: 14 }}>
              备注: {order.remark}
            </div>
          )}
        </div>

        {/* ── 菜品明细 ── */}
        <div style={{ ...cardStyle, marginTop: 12 }}>
          <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 12, color: '#8A94A4' }}>
            菜品明细 ({order.items?.length || 0})
          </div>

          {(!order.items || order.items.length === 0) ? (
            <div style={{ color: '#555', textAlign: 'center', padding: '20px 0' }}>暂无菜品</div>
          ) : (
            <div>
              {/* 表头 */}
              <div style={{ display: 'flex', padding: '8px 0', borderBottom: '1px solid #1a2a33', color: '#8A94A4', fontSize: 14 }}>
                <div style={{ flex: 1 }}>菜品</div>
                <div style={{ width: 60, textAlign: 'center' }}>数量</div>
                <div style={{ width: 90, textAlign: 'right' }}>单价</div>
                <div style={{ width: 90, textAlign: 'right' }}>小计</div>
              </div>

              {/* 菜品行 */}
              {order.items.map((item) => (
                <div key={item.item_id} style={{ display: 'flex', alignItems: 'flex-start', padding: '12px 0', borderBottom: '1px solid #1a2a33' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 16, fontWeight: 500, color: '#fff' }}>{item.dish_name}</div>
                    {item.notes && (
                      <div style={{ fontSize: 13, color: '#faad14', marginTop: 4 }}>{item.notes}</div>
                    )}
                  </div>
                  <div style={{ width: 60, textAlign: 'center', fontSize: 16, color: '#ccc' }}>
                    x{item.quantity}
                  </div>
                  <div style={{ width: 90, textAlign: 'right', fontSize: 15, color: '#999' }}>
                    {fen2yuan(item.unit_price_fen)}
                  </div>
                  <div style={{ width: 90, textAlign: 'right', fontSize: 16, fontWeight: 600, color: '#fff' }}>
                    {fen2yuan(item.subtotal_fen || item.unit_price_fen * item.quantity)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── 价格汇总 ── */}
        <div style={{ ...cardStyle, marginTop: 12 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: '#ccc' }}>
              <span>菜品合计</span>
              <span>{fen2yuan(order.total_amount_fen)}</span>
            </div>

            {order.discount_amount_fen > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: '#FF6B2C' }}>
                <span>优惠</span>
                <span>-{fen2yuan(order.discount_amount_fen)}</span>
              </div>
            )}

            <div style={{ borderTop: '1px solid #1a2a33', paddingTop: 12, display: 'flex', justifyContent: 'space-between', fontSize: 22, fontWeight: 700 }}>
              <span style={{ color: '#fff' }}>应付金额</span>
              <span style={{ color: '#FF6B2C' }}>{fen2yuan(order.final_amount_fen)}</span>
            </div>
          </div>
        </div>

        {/* ── 操作按钮 ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 20 }}>
          {/* 加菜 */}
          <button
            type="button"
            onClick={() => navigate(`/cashier/${order.table_no}`)}
            disabled={!isActive}
            style={{
              ...actionBtnStyle,
              background: isActive ? '#1a2a33' : '#111c22',
              color: isActive ? '#fff' : '#555',
              border: isActive ? '1.5px solid #FF6B2C' : '1.5px solid #333',
              cursor: isActive ? 'pointer' : 'not-allowed',
            }}
          >
            加菜
          </button>

          {/* 结账 */}
          <button
            type="button"
            onClick={() => navigate(`/settle/${orderId}`)}
            disabled={!isActive}
            style={{
              ...actionBtnStyle,
              background: isActive ? '#FF6B2C' : '#444',
              color: '#fff',
              border: 'none',
              cursor: isActive ? 'pointer' : 'not-allowed',
            }}
          >
            结账
          </button>

          {/* 打印 */}
          <button
            type="button"
            onClick={handlePrint}
            disabled={printing}
            style={{
              ...actionBtnStyle,
              background: '#1a2a33',
              color: printing ? '#666' : '#fff',
              border: '1.5px solid #333',
              cursor: printing ? 'not-allowed' : 'pointer',
            }}
          >
            {printing ? '打印中...' : '打印小票'}
          </button>

          {/* 返回桌台 */}
          <button
            type="button"
            onClick={() => navigate('/tables')}
            style={{
              ...actionBtnStyle,
              background: '#1a2a33',
              color: '#8A94A4',
              border: '1.5px solid #333',
              cursor: 'pointer',
            }}
          >
            返回桌台
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 样式常量 ─────────────────────────────────────────────────────────────────

const pageStyle: React.CSSProperties = {
  background: '#0B1A20',
  minHeight: '100vh',
  color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
};

const cardStyle: React.CSSProperties = {
  background: '#112228',
  borderRadius: 12,
  padding: 20,
};

const tagStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderRadius: 6,
  background: 'rgba(255,107,44,0.15)',
  color: '#FF6B2C',
  fontSize: 14,
  fontWeight: 600,
};

const btnBase: React.CSSProperties = {
  padding: '10px 24px',
  border: 'none',
  borderRadius: 8,
  fontSize: 16,
  cursor: 'pointer',
  fontFamily: 'inherit',
};

const actionBtnStyle: React.CSSProperties = {
  padding: '16px 0',
  borderRadius: 10,
  fontSize: 18,
  fontWeight: 600,
  fontFamily: 'inherit',
};

const spinnerStyle: React.CSSProperties = {
  width: 40,
  height: 40,
  border: '3px solid #1a2a33',
  borderTop: '3px solid #FF6B2C',
  borderRadius: '50%',
  animation: 'spin 0.8s linear infinite',
};

// Inject spinner keyframes
if (typeof document !== 'undefined' && !document.getElementById('tx-spinner-keyframes')) {
  const style = document.createElement('style');
  style.id = 'tx-spinner-keyframes';
  style.textContent = '@keyframes spin { to { transform: rotate(360deg); } }';
  document.head.appendChild(style);
}
