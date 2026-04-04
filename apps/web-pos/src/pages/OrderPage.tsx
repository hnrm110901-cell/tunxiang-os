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
      <div className="tx-page">
        <div className="flex flex-col items-center justify-center h-screen gap-4">
          <div className="w-10 h-10 border-[3px] border-tx-border border-t-tx-accent rounded-full animate-spin" />
          <span className="text-tx-muted text-[17px]">加载订单中...</span>
        </div>
      </div>
    );
  }

  // ── 错误状态 ──

  if (error || !order) {
    return (
      <div className="tx-page">
        <div className="flex flex-col items-center justify-center h-screen gap-4">
          <div className="text-5xl">!</div>
          <span className="text-tx-danger text-lg">{error || '订单不存在'}</span>
          <div className="flex gap-3 mt-2">
            <button
              type="button"
              onClick={loadOrder}
              className="px-6 py-2.5 border-none rounded-tx-sm text-base cursor-pointer font-tx bg-tx-border text-white"
            >
              重试
            </button>
            <button
              type="button"
              onClick={() => navigate('/tables')}
              className="px-6 py-2.5 border-none rounded-tx-sm text-base cursor-pointer font-tx bg-[#333] text-tx-text-3"
            >
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
    <div className="tx-page">
      <div className="max-w-[800px] mx-auto p-5">

        {/* ── 顶部导航栏 ── */}
        <div className="flex justify-between items-center mb-5">
          <button
            type="button"
            onClick={() => navigate('/tables')}
            className="bg-transparent border-none text-tx-muted text-base cursor-pointer py-2 font-tx"
          >
            &larr; 返回桌台
          </button>
          <span className="text-tx-muted text-sm">{formatTime(order.created_at)}</span>
        </div>

        {/* ── 订单头部卡片 ── */}
        <div className="tx-card">
          <div className="flex justify-between items-start flex-wrap gap-3">
            <div>
              <div className="text-[22px] font-bold text-white mb-1.5">
                {order.order_no}
              </div>
              <div className="flex gap-3 items-center flex-wrap">
                {/* 桌号 */}
                <span className="tx-tag bg-tx-accent-light text-tx-accent">桌 {order.table_no}</span>
                {/* 订单类型 */}
                <span className="tx-tag bg-[rgba(24,144,255,0.15)] text-tx-blue">
                  {ORDER_TYPE_LABEL[order.order_type] || order.order_type}
                </span>
                {/* 人数 */}
                {order.customer_count != null && order.customer_count > 0 && (
                  <span className="tx-tag bg-[rgba(82,196,26,0.15)] text-tx-green">
                    {order.customer_count}人
                  </span>
                )}
              </div>
            </div>
            {/* 状态徽章 */}
            <div
              className="px-4 py-1.5 rounded-[20px] text-[15px] font-semibold whitespace-nowrap"
              style={{ background: statusCfg.bg, color: statusCfg.color }}
            >
              {statusCfg.label}
            </div>
          </div>

          {order.remark && (
            <div className="mt-3 px-3 py-2 rounded-md bg-[rgba(250,173,20,0.1)] text-tx-warning text-sm">
              备注: {order.remark}
            </div>
          )}
        </div>

        {/* ── 菜品明细 ── */}
        <div className="tx-card mt-3">
          <div className="text-[17px] font-semibold mb-3 text-tx-muted">
            菜品明细 ({order.items?.length || 0})
          </div>

          {(!order.items || order.items.length === 0) ? (
            <div className="text-tx-text-4 text-center py-5">暂无菜品</div>
          ) : (
            <div>
              {/* 表头 */}
              <div className="flex py-2 border-b border-tx-border text-tx-muted text-sm">
                <div className="flex-1">菜品</div>
                <div className="w-[60px] text-center">数量</div>
                <div className="w-[90px] text-right">单价</div>
                <div className="w-[90px] text-right">小计</div>
              </div>

              {/* 菜品行 */}
              {order.items.map((item) => (
                <div key={item.item_id} className="flex items-start py-3 border-b border-tx-border">
                  <div className="flex-1 min-w-0">
                    <div className="text-base font-medium text-white">{item.dish_name}</div>
                    {item.notes && (
                      <div className="text-[13px] text-tx-warning mt-1">{item.notes}</div>
                    )}
                  </div>
                  <div className="w-[60px] text-center text-base text-tx-text-2">
                    x{item.quantity}
                  </div>
                  <div className="w-[90px] text-right text-[15px] text-tx-text-3">
                    {fen2yuan(item.unit_price_fen)}
                  </div>
                  <div className="w-[90px] text-right text-base font-semibold text-white">
                    {fen2yuan(item.subtotal_fen || item.unit_price_fen * item.quantity)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── 价格汇总 ── */}
        <div className="tx-card mt-3">
          <div className="flex flex-col gap-2.5">
            <div className="flex justify-between text-base text-tx-text-2">
              <span>菜品合计</span>
              <span>{fen2yuan(order.total_amount_fen)}</span>
            </div>

            {order.discount_amount_fen > 0 && (
              <div className="flex justify-between text-base text-tx-accent">
                <span>优惠</span>
                <span>-{fen2yuan(order.discount_amount_fen)}</span>
              </div>
            )}

            <div className="border-t border-tx-border pt-3 flex justify-between text-[22px] font-bold">
              <span className="text-white">应付金额</span>
              <span className="text-tx-accent">{fen2yuan(order.final_amount_fen)}</span>
            </div>
          </div>
        </div>

        {/* ── 操作按钮 ── */}
        <div className="grid grid-cols-2 gap-2.5 mt-5">
          {/* 加菜 */}
          <button
            type="button"
            onClick={() => navigate(`/cashier/${order.table_no}`)}
            disabled={!isActive}
            className={`py-4 rounded-[10px] text-lg font-semibold font-tx ${
              isActive
                ? 'bg-tx-border text-white border-[1.5px] border-tx-accent cursor-pointer'
                : 'bg-[#111c22] text-tx-text-4 border-[1.5px] border-[#333] cursor-not-allowed'
            }`}
          >
            加菜
          </button>

          {/* 结账 */}
          <button
            type="button"
            onClick={() => navigate(`/settle/${orderId}`)}
            disabled={!isActive}
            className={`py-4 rounded-[10px] text-lg font-semibold font-tx border-none ${
              isActive
                ? 'bg-tx-accent text-white cursor-pointer'
                : 'bg-[#444] text-white cursor-not-allowed'
            }`}
          >
            结账
          </button>

          {/* 打印 */}
          <button
            type="button"
            onClick={handlePrint}
            disabled={printing}
            className={`py-4 rounded-[10px] text-lg font-semibold font-tx border-[1.5px] border-[#333] bg-tx-border ${
              printing
                ? 'text-tx-text-4 cursor-not-allowed'
                : 'text-white cursor-pointer'
            }`}
          >
            {printing ? '打印中...' : '打印小票'}
          </button>

          {/* 返回桌台 */}
          <button
            type="button"
            onClick={() => navigate('/tables')}
            className="py-4 rounded-[10px] text-lg font-semibold font-tx bg-tx-border text-tx-muted border-[1.5px] border-[#333] cursor-pointer"
          >
            返回桌台
          </button>
        </div>
      </div>
    </div>
  );
}
