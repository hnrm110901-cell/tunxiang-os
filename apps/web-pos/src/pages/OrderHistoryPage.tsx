/**
 * 历史订单查询页 — POS收银端
 * 功能：补打小票 / 处理退款 / 核对账目
 * 规范：纯内联CSS，禁止Ant Design，触控优化（最小48×48px）
 */
import { useState, useCallback, useEffect } from 'react';

/* ─────────── 类型定义 ─────────── */
type OrderStatus = 'paid' | 'refunded' | 'voided' | 'pending';
type DateRange = 'today' | 'yesterday' | 'week' | 'custom';
type RefundReason = 'customer_complaint' | 'wrong_order' | 'dish_issue' | 'other';

interface OrderItem {
  id: string;
  name: string;
  quantity: number;
  unitPrice: number;
  subtotal: number;
  spec?: string;
}

interface Discount {
  label: string;
  amount: number;
}

interface Order {
  id: string;
  orderNo: string;
  tableNo: string;
  guestCount: number;
  cashier: string;
  createdAt: string;
  paidAt?: string;
  status: OrderStatus;
  items: OrderItem[];
  discounts: Discount[];
  subtotal: number;
  discountTotal: number;
  actualAmount: number;
  paymentMethod: string;
  refundAmount?: number;
  refundReason?: string;
}

/* ─────────── Mock 数据 ─────────── */
const MOCK_ORDERS: Order[] = [
  {
    id: 'ord_001', orderNo: 'POS20260402001', tableNo: 'A3', guestCount: 4,
    cashier: '李收银', createdAt: '2026-04-02 11:32:15', paidAt: '2026-04-02 11:45:30',
    status: 'paid',
    items: [
      { id: 'i1', name: '剁椒鱼头', quantity: 1, unitPrice: 98, subtotal: 98 },
      { id: 'i2', name: '小炒肉', quantity: 2, unitPrice: 58, subtotal: 116 },
      { id: 'i3', name: '凉拌黄瓜', quantity: 1, unitPrice: 28, subtotal: 28 },
      { id: 'i4', name: '米饭', quantity: 4, unitPrice: 3, subtotal: 12 },
    ],
    discounts: [{ label: '会员9折', amount: -25.4 }],
    subtotal: 254, discountTotal: 25.4, actualAmount: 228.6,
    paymentMethod: '微信支付',
  },
  {
    id: 'ord_002', orderNo: 'POS20260402002', tableNo: 'B5', guestCount: 2,
    cashier: '王收银', createdAt: '2026-04-02 12:10:08', paidAt: '2026-04-02 12:25:00',
    status: 'refunded',
    items: [
      { id: 'i5', name: '口味虾', quantity: 1, unitPrice: 128, subtotal: 128 },
      { id: 'i6', name: '外婆鸡', quantity: 1, unitPrice: 68, subtotal: 68 },
    ],
    discounts: [],
    subtotal: 196, discountTotal: 0, actualAmount: 196,
    paymentMethod: '支付宝',
    refundAmount: 196, refundReason: '客诉',
  },
  {
    id: 'ord_003', orderNo: 'POS20260402003', tableNo: 'C2', guestCount: 6,
    cashier: '李收银', createdAt: '2026-04-02 13:05:22', paidAt: '2026-04-02 13:50:40',
    status: 'paid',
    items: [
      { id: 'i7', name: '红烧肉', quantity: 2, unitPrice: 68, subtotal: 136 },
      { id: 'i8', name: '酸菜鱼', quantity: 1, unitPrice: 88, subtotal: 88 },
      { id: 'i9', name: '清蒸鱼', quantity: 1, unitPrice: 118, subtotal: 118 },
      { id: 'i10', name: '米饭', quantity: 6, unitPrice: 3, subtotal: 18 },
      { id: 'i11', name: '可乐', quantity: 3, unitPrice: 8, subtotal: 24 },
    ],
    discounts: [{ label: '优惠券-30', amount: -30 }],
    subtotal: 384, discountTotal: 30, actualAmount: 354,
    paymentMethod: '现金',
  },
  {
    id: 'ord_004', orderNo: 'POS20260402004', tableNo: 'D1', guestCount: 1,
    cashier: '王收银', createdAt: '2026-04-02 14:20:00',
    status: 'voided',
    items: [
      { id: 'i12', name: '辣椒炒肉', quantity: 1, unitPrice: 52, subtotal: 52 },
    ],
    discounts: [],
    subtotal: 52, discountTotal: 0, actualAmount: 52,
    paymentMethod: '-',
  },
  {
    id: 'ord_005', orderNo: 'POS20260401001', tableNo: 'A1', guestCount: 3,
    cashier: '李收银', createdAt: '2026-04-01 18:30:00', paidAt: '2026-04-01 19:15:00',
    status: 'paid',
    items: [
      { id: 'i13', name: '剁椒鱼头', quantity: 1, unitPrice: 98, subtotal: 98 },
      { id: 'i14', name: '小炒肉', quantity: 1, unitPrice: 58, subtotal: 58 },
      { id: 'i15', name: '米饭', quantity: 3, unitPrice: 3, subtotal: 9 },
    ],
    discounts: [],
    subtotal: 165, discountTotal: 0, actualAmount: 165,
    paymentMethod: '微信支付',
  },
  {
    id: 'ord_006', orderNo: 'POS20260401002', tableNo: 'B2', guestCount: 2,
    cashier: '王收银', createdAt: '2026-04-01 19:00:00', paidAt: '2026-04-01 19:45:00',
    status: 'paid',
    items: [
      { id: 'i16', name: '口味虾', quantity: 1, unitPrice: 128, subtotal: 128 },
      { id: 'i17', name: '凉拌黄瓜', quantity: 2, unitPrice: 28, subtotal: 56 },
    ],
    discounts: [],
    subtotal: 184, discountTotal: 0, actualAmount: 184,
    paymentMethod: '支付宝',
  },
];

/* ─────────── 设备工具 ─────────── */
const isAndroidPOS = (): boolean =>
  !!(window as unknown as Record<string, unknown>).TXBridge;

const getPosMachineUrl = (): string => {
  const w = window as unknown as Record<string, unknown>;
  if (isAndroidPOS() && typeof (w.TXBridge as Record<string, unknown>).getMacMiniUrl === 'function') {
    return String((w.TXBridge as Record<string, () => string>).getMacMiniUrl());
  }
  return 'http://192.168.1.100:8000';
};

const TENANT_ID: string =
  ((window as unknown as Record<string, unknown>).__TENANT_ID__ as string) || 'default';
const STORE_ID: string =
  ((window as unknown as Record<string, unknown>).__STORE_ID__ as string) || '';

/* ─────────── API ─────────── */
async function fetchOrders(params: {
  store_id: string;
  date?: string;
  date_from?: string;
  date_to?: string;
  page: number;
  size: number;
  status?: OrderStatus | 'all';
}): Promise<{ items: Order[]; total: number }> {
  try {
    const qs = new URLSearchParams({
      store_id: params.store_id,
      page: String(params.page),
      size: String(params.size),
    });
    if (params.date) qs.set('date', params.date);
    if (params.date_from) qs.set('date_from', params.date_from);
    if (params.date_to) qs.set('date_to', params.date_to);
    if (params.status && params.status !== 'all') qs.set('status', params.status);

    const res = await fetch(`/api/v1/trade/orders?${qs}`, {
      headers: { 'X-Tenant-ID': TENANT_ID },
    });
    if (!res.ok) throw new Error('API error');
    return res.json();
  } catch {
    // 降级 Mock
    let filtered = [...MOCK_ORDERS];
    if (params.status && params.status !== 'all') {
      filtered = filtered.filter(o => o.status === params.status);
    }
    const start = (params.page - 1) * params.size;
    return { items: filtered.slice(start, start + params.size), total: filtered.length };
  }
}

async function fetchOrderDetail(orderId: string): Promise<Order> {
  try {
    const res = await fetch(`/api/v1/trade/orders/${orderId}`, {
      headers: { 'X-Tenant-ID': TENANT_ID },
    });
    if (!res.ok) throw new Error('API error');
    return res.json();
  } catch {
    const found = MOCK_ORDERS.find(o => o.id === orderId);
    if (!found) throw new Error('Order not found');
    return found;
  }
}

async function requestRefund(
  orderId: string,
  amount: number,
  reason: string,
  remark: string,
): Promise<void> {
  const res = await fetch(`/api/v1/trade/orders/${orderId}/refund`, {
    method: 'POST',
    headers: { 'X-Tenant-ID': TENANT_ID, 'Content-Type': 'application/json' },
    body: JSON.stringify({ amount, reason, remark }),
  });
  if (!res.ok) throw new Error('退款失败');
}

async function printReceipt(order: Order): Promise<void> {
  const lines = [
    '================================',
    '         屯象OS收银小票         ',
    '================================',
    `订单号: ${order.orderNo}`,
    `桌台: ${order.tableNo}   人数: ${order.guestCount}人`,
    `时间: ${order.paidAt || order.createdAt}`,
    `收银: ${order.cashier}`,
    '--------------------------------',
    ...order.items.map(i => `${i.name.padEnd(8)} ×${i.quantity}  ¥${i.subtotal.toFixed(2)}`),
    '--------------------------------',
    `小计: ¥${order.subtotal.toFixed(2)}`,
    ...order.discounts.map(d => `${d.label}: -¥${Math.abs(d.amount).toFixed(2)}`),
    `实付: ¥${order.actualAmount.toFixed(2)}`,
    `支付: ${order.paymentMethod}`,
    '================================',
    '       感谢光临，欢迎再来！       ',
    '================================',
  ].join('\n');

  if (isAndroidPOS()) {
    (window as unknown as Record<string, Record<string, (s: string) => void>>).TXBridge.print(lines);
  } else {
    await fetch(`${getPosMachineUrl()}/api/device/print`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: lines, type: 'receipt' }),
    });
  }
}

/* ─────────── 工具函数 ─────────── */
function getTodayStr(): string {
  return new Date().toISOString().split('T')[0];
}
function getYesterdayStr(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().split('T')[0];
}
function getWeekStartStr(): string {
  const d = new Date();
  const day = d.getDay() || 7;
  d.setDate(d.getDate() - day + 1);
  return d.toISOString().split('T')[0];
}

/* ─────────── 状态标签 ─────────── */
const STATUS_LABEL: Record<OrderStatus, string> = {
  paid: '已支付',
  refunded: '已退款',
  voided: '已作废',
  pending: '待支付',
};
const STATUS_BG: Record<OrderStatus, string> = {
  paid: '#0F6E56',
  refunded: '#BA7517',
  voided: '#A32D2D',
  pending: '#5F5E5A',
};

/* ─────────── Toast ─────────── */
interface ToastState {
  visible: boolean;
  msg: string;
  type: 'success' | 'error';
}

function Toast({ state }: { state: ToastState }) {
  if (!state.visible) return null;
  return (
    <div style={{
      position: 'fixed', top: 80, left: '50%', transform: 'translateX(-50%)',
      zIndex: 9999, padding: '14px 28px', borderRadius: 12, fontSize: 18, fontWeight: 600,
      background: state.type === 'success' ? '#0F6E56' : '#A32D2D',
      color: '#fff', boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
      animation: 'fadeInDown 0.25s ease',
      whiteSpace: 'nowrap',
    }}>
      {state.msg}
    </div>
  );
}

/* ─────────── 退款弹窗 ─────────── */
interface RefundModalProps {
  order: Order;
  onClose: () => void;
  onSuccess: () => void;
  showToast: (msg: string, type: 'success' | 'error') => void;
}

function RefundModal({ order, onClose, onSuccess, showToast }: RefundModalProps) {
  const [amount, setAmount] = useState<string>(String(order.actualAmount.toFixed(2)));
  const [reason, setReason] = useState<RefundReason>('customer_complaint');
  const [remark, setRemark] = useState('');
  const [loading, setLoading] = useState(false);
  const [showReasonPicker, setShowReasonPicker] = useState(false);

  const reasonOptions: { value: RefundReason; label: string }[] = [
    { value: 'customer_complaint', label: '客诉' },
    { value: 'wrong_order', label: '点错菜' },
    { value: 'dish_issue', label: '菜品问题' },
    { value: 'other', label: '其他' },
  ];

  const handleConfirm = async () => {
    const amtNum = parseFloat(amount);
    if (isNaN(amtNum) || amtNum <= 0) {
      showToast('退款金额无效', 'error');
      return;
    }
    if (amtNum > order.actualAmount) {
      showToast(`退款金额不能超过实付金额 ¥${order.actualAmount.toFixed(2)}`, 'error');
      return;
    }
    setLoading(true);
    try {
      await requestRefund(order.id, amtNum, reason, remark);
      showToast('退款申请已提交', 'success');
      onSuccess();
    } catch {
      showToast('退款申请失败，请重试', 'error');
    } finally {
      setLoading(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box', padding: '12px 16px',
    fontSize: 18, borderRadius: 12, border: '2px solid #E8E6E1',
    background: '#F8F7F5', color: '#2C2C2A', outline: 'none',
    fontFamily: 'inherit',
  };

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 8000,
        }}
      />
      {/* Modal */}
      <div style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 'min(480px, 90vw)', zIndex: 8001,
        background: '#fff', borderRadius: 20, padding: 32,
        boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 28 }}>
          <h2 style={{ margin: 0, fontSize: 24, color: '#2C2C2A', fontWeight: 700 }}>申请退款</h2>
          <button
            onClick={onClose}
            style={{
              width: 48, height: 48, border: 'none', borderRadius: 12,
              background: '#F0EDE6', color: '#5F5E5A', fontSize: 20,
              cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >✕</button>
        </div>

        {/* 订单信息 */}
        <div style={{
          background: '#F8F7F5', borderRadius: 12, padding: '16px 20px',
          marginBottom: 24, fontSize: 16, color: '#5F5E5A', lineHeight: '1.8',
        }}>
          <span>订单号：{order.orderNo}</span><br />
          <span>桌台：{order.tableNo} &nbsp;|&nbsp; 实付：</span>
          <span style={{ color: '#FF6B35', fontWeight: 700, fontSize: 20 }}>
            ¥{order.actualAmount.toFixed(2)}
          </span>
        </div>

        {/* 退款金额 */}
        <label style={{ display: 'block', fontSize: 18, color: '#2C2C2A', fontWeight: 600, marginBottom: 8 }}>
          退款金额
        </label>
        <div style={{ position: 'relative', marginBottom: 20 }}>
          <span style={{
            position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)',
            fontSize: 20, color: '#5F5E5A', pointerEvents: 'none',
          }}>¥</span>
          <input
            type="number"
            value={amount}
            onChange={e => setAmount(e.target.value)}
            min={0.01}
            max={order.actualAmount}
            step={0.01}
            style={{ ...inputStyle, paddingLeft: 36 }}
          />
        </div>

        {/* 退款原因 */}
        <label style={{ display: 'block', fontSize: 18, color: '#2C2C2A', fontWeight: 600, marginBottom: 8 }}>
          退款原因
        </label>
        <button
          onClick={() => setShowReasonPicker(true)}
          style={{
            width: '100%', padding: '12px 16px', fontSize: 18,
            borderRadius: 12, border: '2px solid #E8E6E1',
            background: '#F8F7F5', color: '#2C2C2A',
            textAlign: 'left', cursor: 'pointer', marginBottom: 20,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            minHeight: 48, fontFamily: 'inherit',
          }}
        >
          <span>{reasonOptions.find(r => r.value === reason)?.label ?? '选择原因'}</span>
          <span style={{ color: '#B4B2A9' }}>▼</span>
        </button>

        {/* 备注 */}
        <label style={{ display: 'block', fontSize: 18, color: '#2C2C2A', fontWeight: 600, marginBottom: 8 }}>
          备注（可选）
        </label>
        <input
          type="text"
          value={remark}
          onChange={e => setRemark(e.target.value)}
          placeholder="补充说明..."
          style={{ ...inputStyle, marginBottom: 28 }}
        />

        {/* 确认按钮 */}
        <button
          onClick={handleConfirm}
          disabled={loading}
          style={{
            width: '100%', height: 60, borderRadius: 12, border: 'none',
            background: loading ? '#B4B2A9' : '#A32D2D',
            color: '#fff', fontSize: 20, fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer',
            transition: 'transform 0.2s ease',
          }}
          onPointerDown={e => { if (!loading) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
          onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
        >
          {loading ? '提交中...' : '确认退款'}
        </button>
      </div>

      {/* 原因选择器（底部弹层） */}
      {showReasonPicker && (
        <>
          <div
            onClick={() => setShowReasonPicker(false)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 9000 }}
          />
          <div style={{
            position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 9001,
            background: '#fff', borderRadius: '20px 20px 0 0',
            padding: '24px 20px',
            animation: 'slideUp 0.3s ease-out',
          }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A', marginBottom: 20, textAlign: 'center' }}>
              选择退款原因
            </div>
            {reasonOptions.map(opt => (
              <button
                key={opt.value}
                onClick={() => { setReason(opt.value); setShowReasonPicker(false); }}
                style={{
                  width: '100%', height: 60, marginBottom: 12, borderRadius: 12,
                  border: `2px solid ${reason === opt.value ? '#FF6B35' : '#E8E6E1'}`,
                  background: reason === opt.value ? '#FFF3ED' : '#F8F7F5',
                  color: reason === opt.value ? '#FF6B35' : '#2C2C2A',
                  fontSize: 18, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
                  transition: 'transform 0.2s ease',
                }}
                onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
                onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </>
  );
}

/* ─────────── 订单详情底部抽屉 ─────────── */
interface OrderDrawerProps {
  order: Order | null;
  onClose: () => void;
  onPrint: (order: Order) => void;
  onRefund: (order: Order) => void;
}

function OrderDrawer({ order, onClose, onPrint, onRefund }: OrderDrawerProps) {
  if (!order) return null;

  const drawerStyle: React.CSSProperties = {
    position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 7000,
    height: '70vh', background: '#fff', borderRadius: '20px 20px 0 0',
    boxShadow: '0 -8px 24px rgba(0,0,0,0.15)',
    display: 'flex', flexDirection: 'column',
    animation: 'slideUp 0.3s ease-out',
  };

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 6999,
        }}
      />

      <div style={drawerStyle}>
        {/* 拖拽把手 */}
        <div style={{ display: 'flex', justifyContent: 'center', padding: '16px 0 8px' }}>
          <div style={{ width: 48, height: 5, borderRadius: 3, background: '#E8E6E1' }} />
        </div>

        {/* 头部 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '8px 24px 16px', borderBottom: '1px solid #E8E6E1',
          flexShrink: 0,
        }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A' }}>
              订单详情
            </div>
            <div style={{ fontSize: 16, color: '#5F5E5A', marginTop: 4 }}>
              {order.orderNo}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{
              padding: '6px 16px', borderRadius: 20, fontSize: 16, fontWeight: 600,
              background: STATUS_BG[order.status], color: '#fff',
            }}>
              {STATUS_LABEL[order.status]}
            </span>
            <button
              onClick={onClose}
              style={{
                width: 48, height: 48, border: 'none', borderRadius: 12,
                background: '#F0EDE6', color: '#5F5E5A', fontSize: 20, cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >✕</button>
          </div>
        </div>

        {/* 内容（可滚动） */}
        <div style={{
          flex: 1, overflowY: 'auto', padding: '20px 24px',
          WebkitOverflowScrolling: 'touch',
        } as React.CSSProperties}>

          {/* 基本信息 */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr',
            gap: '8px 24px', background: '#F8F7F5', borderRadius: 12,
            padding: '16px 20px', marginBottom: 20, fontSize: 16,
          }}>
            {[
              { label: '下单时间', value: order.createdAt },
              { label: '桌台', value: order.tableNo },
              { label: '人数', value: `${order.guestCount} 人` },
              { label: '收银员', value: order.cashier },
              ...(order.paidAt ? [{ label: '支付时间', value: order.paidAt }] : []),
            ].map(row => (
              <div key={row.label}>
                <div style={{ color: '#B4B2A9', fontSize: 14, marginBottom: 2 }}>{row.label}</div>
                <div style={{ color: '#2C2C2A', fontWeight: 500 }}>{row.value}</div>
              </div>
            ))}
          </div>

          {/* 菜品明细 */}
          <div style={{ marginBottom: 20 }}>
            <h3 style={{ margin: '0 0 12px', fontSize: 18, color: '#2C2C2A', fontWeight: 700 }}>
              菜品明细
            </h3>
            {/* 表头 */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 56px 80px 80px',
              padding: '8px 0', borderBottom: '2px solid #E8E6E1',
              fontSize: 14, color: '#B4B2A9', fontWeight: 600,
            }}>
              <span>菜品</span><span style={{ textAlign: 'center' }}>数量</span>
              <span style={{ textAlign: 'right' }}>单价</span>
              <span style={{ textAlign: 'right' }}>小计</span>
            </div>
            {order.items.map(item => (
              <div key={item.id} style={{
                display: 'grid', gridTemplateColumns: '1fr 56px 80px 80px',
                padding: '12px 0', borderBottom: '1px solid #F0EDE6',
                fontSize: 16, color: '#2C2C2A', alignItems: 'center',
              }}>
                <div>
                  <div>{item.name}</div>
                  {item.spec && <div style={{ fontSize: 14, color: '#B4B2A9' }}>{item.spec}</div>}
                </div>
                <div style={{ textAlign: 'center', color: '#5F5E5A' }}>×{item.quantity}</div>
                <div style={{ textAlign: 'right', color: '#5F5E5A' }}>¥{item.unitPrice.toFixed(2)}</div>
                <div style={{ textAlign: 'right', fontWeight: 600 }}>¥{item.subtotal.toFixed(2)}</div>
              </div>
            ))}
          </div>

          {/* 优惠明细 */}
          {order.discounts.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <h3 style={{ margin: '0 0 12px', fontSize: 18, color: '#2C2C2A', fontWeight: 700 }}>
                优惠明细
              </h3>
              {order.discounts.map((d, idx) => (
                <div key={idx} style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '10px 0', borderBottom: '1px solid #F0EDE6',
                  fontSize: 16,
                }}>
                  <span style={{ color: '#5F5E5A' }}>{d.label}</span>
                  <span style={{ color: '#BA7517', fontWeight: 600 }}>
                    -¥{Math.abs(d.amount).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 支付金额汇总 */}
          <div style={{
            background: '#F8F7F5', borderRadius: 12, padding: '16px 20px', marginBottom: 20,
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              fontSize: 16, color: '#5F5E5A', marginBottom: 8,
            }}>
              <span>小计</span><span>¥{order.subtotal.toFixed(2)}</span>
            </div>
            {order.discountTotal > 0 && (
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                fontSize: 16, color: '#BA7517', marginBottom: 8,
              }}>
                <span>优惠</span><span>-¥{order.discountTotal.toFixed(2)}</span>
              </div>
            )}
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', paddingTop: 12, borderTop: '1px solid #E8E6E1',
            }}>
              <span style={{ fontSize: 18, color: '#2C2C2A', fontWeight: 600 }}>
                {order.paymentMethod} 实付
              </span>
              <span style={{ fontSize: 32, fontWeight: 800, color: '#FF6B35' }}>
                ¥{order.actualAmount.toFixed(2)}
              </span>
            </div>
            {order.refundAmount !== undefined && (
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                fontSize: 16, color: '#A32D2D', marginTop: 8,
              }}>
                <span>已退款</span><span>-¥{order.refundAmount.toFixed(2)}</span>
              </div>
            )}
          </div>
        </div>

        {/* 底部操作按钮 */}
        {order.status === 'paid' && (
          <div style={{
            padding: '16px 24px 32px', borderTop: '1px solid #E8E6E1',
            display: 'flex', gap: 12, flexShrink: 0,
          }}>
            <button
              onClick={() => onPrint(order)}
              style={{
                flex: 1, height: 60, borderRadius: 12, border: '2px solid #FF6B35',
                background: '#FFF3ED', color: '#FF6B35', fontSize: 18, fontWeight: 700,
                cursor: 'pointer', transition: 'transform 0.2s ease', fontFamily: 'inherit',
              }}
              onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
              onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            >
              补打小票
            </button>
            <button
              onClick={() => onRefund(order)}
              style={{
                flex: 1, height: 60, borderRadius: 12, border: 'none',
                background: '#A32D2D', color: '#fff', fontSize: 18, fontWeight: 700,
                cursor: 'pointer', transition: 'transform 0.2s ease', fontFamily: 'inherit',
              }}
              onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
              onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            >
              申请退款
            </button>
          </div>
        )}
        {(order.status === 'refunded' || order.status === 'voided') && (
          <div style={{
            padding: '16px 24px 32px', borderTop: '1px solid #E8E6E1',
            flexShrink: 0,
          }}>
            <button
              onClick={onClose}
              style={{
                width: '100%', height: 60, borderRadius: 12, border: '2px solid #E8E6E1',
                background: '#F8F7F5', color: '#5F5E5A', fontSize: 18, fontWeight: 700,
                cursor: 'pointer', transition: 'transform 0.2s ease', fontFamily: 'inherit',
              }}
              onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
              onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            >
              关闭
            </button>
          </div>
        )}
      </div>
    </>
  );
}

/* ─────────── 主页组件 ─────────── */
export function OrderHistoryPage() {
  /* ── 搜索状态 ── */
  const [dateRange, setDateRange] = useState<DateRange>('today');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [statusFilter, setStatusFilter] = useState<OrderStatus | 'all'>('all');
  const [keyword, setKeyword] = useState('');

  /* ── 列表状态 ── */
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const PAGE_SIZE = 20;

  /* ── 详情抽屉 ── */
  const [drawerOrder, setDrawerOrder] = useState<Order | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  /* ── 退款弹窗 ── */
  const [refundOrder, setRefundOrder] = useState<Order | null>(null);

  /* ── Toast ── */
  const [toast, setToast] = useState<ToastState>({ visible: false, msg: '', type: 'success' });
  const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ visible: true, msg, type });
    setTimeout(() => setToast(prev => ({ ...prev, visible: false })), 2500);
  }, []);

  /* ── 加载订单 ── */
  const loadOrders = useCallback(async (resetPage?: boolean) => {
    setLoading(true);
    const p = resetPage ? 1 : page;
    try {
      const dateParams: Record<string, string> = {};
      if (dateRange === 'today') dateParams.date = getTodayStr();
      else if (dateRange === 'yesterday') dateParams.date = getYesterdayStr();
      else if (dateRange === 'week') {
        dateParams.date_from = getWeekStartStr();
        dateParams.date_to = getTodayStr();
      } else if (dateRange === 'custom') {
        if (customFrom) dateParams.date_from = customFrom;
        if (customTo) dateParams.date_to = customTo;
      }

      const result = await fetchOrders({
        store_id: STORE_ID,
        ...dateParams,
        page: p,
        size: PAGE_SIZE,
        status: statusFilter,
      });

      const filtered = keyword
        ? result.items.filter(o =>
          o.tableNo.includes(keyword) ||
          String(o.actualAmount).includes(keyword) ||
          o.orderNo.includes(keyword),
        )
        : result.items;

      if (resetPage) {
        setOrders(filtered);
        setPage(2);
      } else {
        setOrders(prev => [...prev, ...filtered]);
        setPage(prev => prev + 1);
      }
      setTotal(result.total);
      setHasMore(p * PAGE_SIZE < result.total);
    } finally {
      setLoading(false);
    }
  }, [dateRange, statusFilter, keyword, page, customFrom, customTo]);

  /* ── 初始加载 & 筛选变化时重载 ── */
  useEffect(() => {
    loadOrders(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange, statusFilter]);

  /* ── 点击行展开详情 ── */
  const openDetail = async (order: Order) => {
    setDetailLoading(true);
    setDrawerOrder(order); // 先用列表数据展示
    try {
      const detail = await fetchOrderDetail(order.id);
      setDrawerOrder(detail);
    } catch {
      // 使用已有数据
    } finally {
      setDetailLoading(false);
    }
  };

  /* ── 补打小票 ── */
  const handlePrint = async (order: Order) => {
    try {
      await printReceipt(order);
      showToast('已发送打印', 'success');
    } catch {
      showToast('打印失败，请重试', 'error');
    }
  };

  /* ── 退款成功 ── */
  const handleRefundSuccess = () => {
    setRefundOrder(null);
    setDrawerOrder(null);
    loadOrders(true);
  };

  /* ────── 样式常量 ────── */
  const searchBg = '#1E2A3A';
  const dateButtonStyle = (active: boolean): React.CSSProperties => ({
    height: 44, padding: '0 20px', borderRadius: 8, border: 'none',
    background: active ? '#FF6B35' : '#2C3E50',
    color: active ? '#fff' : '#B4B2A9',
    fontSize: 16, fontWeight: active ? 700 : 400,
    cursor: 'pointer', transition: 'transform 0.2s ease',
    whiteSpace: 'nowrap', minWidth: 72,
    fontFamily: 'inherit',
  });

  const statusTabStyle = (active: boolean): React.CSSProperties => ({
    height: 44, padding: '0 16px', borderRadius: 8, border: 'none',
    background: active ? '#FF6B35' : 'transparent',
    color: active ? '#fff' : '#B4B2A9',
    fontSize: 16, fontWeight: active ? 700 : 400,
    cursor: 'pointer', transition: 'transform 0.2s ease',
    whiteSpace: 'nowrap',
    fontFamily: 'inherit',
  });

  return (
    <div style={{
      minHeight: '100vh',
      background: '#F8F7F5',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      display: 'flex', flexDirection: 'column',
    }}>
      {/* ────── keyframes ────── */}
      <style>{`
        @keyframes slideUp {
          from { transform: translateY(100%); }
          to { transform: translateY(0); }
        }
        @keyframes fadeInDown {
          from { opacity: 0; transform: translate(-50%, -20px); }
          to { opacity: 1; transform: translate(-50%, 0); }
        }
      `}</style>

      <Toast state={toast} />

      {/* ────── 顶部搜索栏 ────── */}
      <div style={{
        background: searchBg, flexShrink: 0,
        padding: '12px 20px', display: 'flex', flexDirection: 'column', gap: 12,
      }}>
        {/* 标题行 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <h1 style={{ margin: 0, fontSize: 22, color: '#fff', fontWeight: 700 }}>
            历史订单
          </h1>
          <span style={{ fontSize: 16, color: '#B4B2A9' }}>
            共 {total} 条
          </span>
        </div>

        {/* 日期选择 */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {(['today', 'yesterday', 'week', 'custom'] as DateRange[]).map(r => (
            <button
              key={r}
              onClick={() => setDateRange(r)}
              style={dateButtonStyle(dateRange === r)}
              onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
              onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            >
              {{ today: '今日', yesterday: '昨日', week: '本周', custom: '自定义' }[r]}
            </button>
          ))}
          {dateRange === 'custom' && (
            <>
              <input
                type="date"
                value={customFrom}
                onChange={e => setCustomFrom(e.target.value)}
                style={{
                  height: 44, padding: '0 12px', borderRadius: 8,
                  border: 'none', background: '#2C3E50', color: '#E0E0E0',
                  fontSize: 16, fontFamily: 'inherit',
                }}
              />
              <span style={{ color: '#B4B2A9', fontSize: 16 }}>至</span>
              <input
                type="date"
                value={customTo}
                onChange={e => setCustomTo(e.target.value)}
                style={{
                  height: 44, padding: '0 12px', borderRadius: 8,
                  border: 'none', background: '#2C3E50', color: '#E0E0E0',
                  fontSize: 16, fontFamily: 'inherit',
                }}
              />
              <button
                onClick={() => loadOrders(true)}
                style={{
                  height: 44, padding: '0 20px', borderRadius: 8, border: 'none',
                  background: '#FF6B35', color: '#fff', fontSize: 16, fontWeight: 700,
                  cursor: 'pointer', fontFamily: 'inherit',
                }}
              >
                查询
              </button>
            </>
          )}
        </div>

        {/* 状态筛选 + 搜索框 */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{
            display: 'flex', background: '#2C3E50', borderRadius: 8, padding: 4,
          }}>
            {(['all', 'paid', 'refunded', 'voided'] as const).map(s => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                style={statusTabStyle(statusFilter === s)}
                onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
                onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              >
                {{ all: '全部', paid: '已支付', refunded: '已退款', voided: '已作废' }[s]}
              </button>
            ))}
          </div>

          <div style={{ flex: 1, minWidth: 200, position: 'relative' }}>
            <span style={{
              position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)',
              color: '#B4B2A9', fontSize: 18, pointerEvents: 'none',
            }}>🔍</span>
            <input
              type="text"
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') loadOrders(true); }}
              placeholder="桌号 / 金额 / 订单号"
              style={{
                width: '100%', height: 44, boxSizing: 'border-box',
                paddingLeft: 44, paddingRight: 16, borderRadius: 8,
                border: 'none', background: '#2C3E50',
                color: '#E0E0E0', fontSize: 16, fontFamily: 'inherit',
                outline: 'none',
              }}
            />
          </div>

          <button
            onClick={() => loadOrders(true)}
            style={{
              height: 44, padding: '0 24px', borderRadius: 8, border: 'none',
              background: '#FF6B35', color: '#fff', fontSize: 16, fontWeight: 700,
              cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'inherit',
              transition: 'transform 0.2s ease',
            }}
            onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
            onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          >
            搜索
          </button>
        </div>
      </div>

      {/* ────── 列表区域 ────── */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '12px 16px',
        WebkitOverflowScrolling: 'touch',
      } as React.CSSProperties}>

        {loading && orders.length === 0 && (
          <div style={{
            textAlign: 'center', padding: '60px 0', color: '#B4B2A9', fontSize: 18,
          }}>
            加载中...
          </div>
        )}

        {!loading && orders.length === 0 && (
          <div style={{
            textAlign: 'center', padding: '60px 0', color: '#B4B2A9', fontSize: 18,
          }}>
            暂无订单数据
          </div>
        )}

        {orders.map(order => (
          <div
            key={order.id}
            onClick={() => openDetail(order)}
            style={{
              height: 72, background: '#fff', borderRadius: 12,
              marginBottom: 8, padding: '0 16px',
              display: 'flex', alignItems: 'center', gap: 12,
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
              cursor: 'pointer', transition: 'transform 0.15s ease',
              userSelect: 'none',
            }}
            onPointerDown={e => { (e.currentTarget as HTMLDivElement).style.transform = 'scale(0.99)'; }}
            onPointerUp={e => { (e.currentTarget as HTMLDivElement).style.transform = 'scale(1)'; }}
            onPointerCancel={e => { (e.currentTarget as HTMLDivElement).style.transform = 'scale(1)'; }}
          >
            {/* 时间 */}
            <div style={{ width: 90, flexShrink: 0 }}>
              <div style={{ fontSize: 16, color: '#2C2C2A', fontWeight: 500 }}>
                {(order.paidAt || order.createdAt).slice(11, 16)}
              </div>
              <div style={{ fontSize: 14, color: '#B4B2A9', marginTop: 2 }}>
                {(order.paidAt || order.createdAt).slice(5, 10)}
              </div>
            </div>

            {/* 桌号 */}
            <div style={{
              width: 56, height: 48, background: '#F0EDE6', borderRadius: 8,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <span style={{ fontSize: 18, fontWeight: 700, color: '#2C2C2A' }}>
                {order.tableNo}
              </span>
            </div>

            {/* 金额 */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 24, fontWeight: 800, color: '#FF6B35' }}>
                ¥{order.actualAmount.toFixed(2)}
              </div>
              <div style={{ fontSize: 14, color: '#B4B2A9', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {order.items.map(i => i.name).join('、')}
              </div>
            </div>

            {/* 状态标签 */}
            <div style={{ flexShrink: 0 }}>
              <span style={{
                padding: '6px 12px', borderRadius: 20, fontSize: 14, fontWeight: 600,
                background: STATUS_BG[order.status], color: '#fff',
                whiteSpace: 'nowrap',
              }}>
                {STATUS_LABEL[order.status]}
              </span>
            </div>

            {/* 操作按钮区 */}
            <div
              style={{ display: 'flex', gap: 8, flexShrink: 0 }}
              onClick={e => e.stopPropagation()}
            >
              {order.status === 'paid' && (
                <>
                  <button
                    onClick={() => handlePrint(order)}
                    style={{
                      minWidth: 80, height: 48, padding: '0 12px', borderRadius: 8,
                      border: '2px solid #FF6B35', background: '#FFF3ED',
                      color: '#FF6B35', fontSize: 15, fontWeight: 600,
                      cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'inherit',
                      transition: 'transform 0.2s ease',
                    }}
                    onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
                    onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                    onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                  >
                    补打
                  </button>
                  <button
                    onClick={() => setRefundOrder(order)}
                    style={{
                      minWidth: 80, height: 48, padding: '0 12px', borderRadius: 8,
                      border: 'none', background: '#A32D2D',
                      color: '#fff', fontSize: 15, fontWeight: 600,
                      cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'inherit',
                      transition: 'transform 0.2s ease',
                    }}
                    onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
                    onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                    onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                  >
                    退款
                  </button>
                </>
              )}
              {(order.status === 'refunded' || order.status === 'voided') && (
                <button
                  onClick={() => openDetail(order)}
                  style={{
                    minWidth: 80, height: 48, padding: '0 12px', borderRadius: 8,
                    border: '2px solid #E8E6E1', background: '#F8F7F5',
                    color: '#5F5E5A', fontSize: 15, fontWeight: 600,
                    cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'inherit',
                    transition: 'transform 0.2s ease',
                  }}
                  onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
                  onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                  onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                >
                  详情
                </button>
              )}
            </div>
          </div>
        ))}

        {/* 加载更多 */}
        {orders.length > 0 && (
          <div style={{ textAlign: 'center', padding: '20px 0 40px' }}>
            {hasMore ? (
              <button
                onClick={() => loadOrders()}
                disabled={loading}
                style={{
                  height: 52, padding: '0 48px', borderRadius: 12,
                  border: '2px solid #E8E6E1', background: loading ? '#F0EDE6' : '#fff',
                  color: loading ? '#B4B2A9' : '#5F5E5A', fontSize: 17, fontWeight: 600,
                  cursor: loading ? 'not-allowed' : 'pointer', fontFamily: 'inherit',
                  transition: 'transform 0.2s ease',
                }}
                onPointerDown={e => { if (!loading) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
                onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                onPointerCancel={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              >
                {loading ? '加载中...' : `加载更多（已显示 ${orders.length}/${total}）`}
              </button>
            ) : (
              <span style={{ color: '#B4B2A9', fontSize: 16 }}>
                已显示全部 {total} 条订单
              </span>
            )}
          </div>
        )}
      </div>

      {/* ────── 详情抽屉加载占位 ────── */}
      {detailLoading && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          height: '70vh', background: '#fff', borderRadius: '20px 20px 0 0',
          zIndex: 7000, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 20, color: '#B4B2A9',
        }}>
          加载中...
        </div>
      )}

      {/* ────── 订单详情抽屉 ────── */}
      {!detailLoading && drawerOrder && (
        <OrderDrawer
          order={drawerOrder}
          onClose={() => setDrawerOrder(null)}
          onPrint={handlePrint}
          onRefund={o => { setRefundOrder(o); setDrawerOrder(null); }}
        />
      )}

      {/* ────── 退款弹窗 ────── */}
      {refundOrder && (
        <RefundModal
          order={refundOrder}
          onClose={() => setRefundOrder(null)}
          onSuccess={handleRefundSuccess}
          showToast={showToast}
        />
      )}
    </div>
  );
}
