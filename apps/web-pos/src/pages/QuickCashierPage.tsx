/**
 * QuickCashierPage — 快餐收银界面（触控优化，安卓POS机使用）
 *
 * 竖屏/横屏自适应布局：
 *   顶部：门店模式标识 + 叫号屏入口 + 当前时间
 *   主区：左侧菜品分类 + 菜品卡片网格（4列）
 *   右侧购物车：菜品列表 + 合计 + 订单类型 + 结账弹窗
 *
 * 结账弹窗：
 *   显示取餐号（自动获取）+ 支付方式选择
 *   现金：输入实收金额，显示找零
 *   支付后：显示取餐号大字 + 自动打印小票
 *
 * Store-POS 终端规范（tx-ui 技能）：
 *   - 禁用 Ant Design，所有组件手写触控优化
 *   - 所有点击区域 ≥ 48×48px，关键操作 ≥ 72px
 *   - 最小字体 16px（绝对底线）
 *   - 触控反馈：按下 scale(0.97) + 200ms transition
 *   - 无 hover，用 :active/onPointerDown 替代
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDishes, fetchCategories, type DishItem } from '../api/menuApi';
import { printReceipt as bridgePrint, openCashBox } from '../bridge/TXBridge';

// ─── Design Tokens（与 CallingScreenPage 一致） ───
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
  dimText: '#6B7280',
};

// ─── 常量 ───
const ORDER_TYPES = [
  { value: 'dine_in', label: '堂食', color: C.success },
  { value: 'takeaway', label: '外带', color: C.info },
  { value: 'pack', label: '打包', color: C.warning },
] as const;

type OrderType = 'dine_in' | 'takeaway' | 'pack';

// ─── Mock 数据（离线/开发用） ───
const MOCK_CATEGORIES = ['热销', '主食', '小吃', '粉面', '饮品', '套餐', '凉菜', '甜品'];

const MOCK_DISHES: DishItem[] = [
  { id: 'd01', name: '剁椒鱼头', priceFen: 8800, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'd02', name: '毛氏红烧肉', priceFen: 5800, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'd03', name: '辣椒炒肉', priceFen: 3800, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'd04', name: '蒜蓉大虾', priceFen: 6800, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'd05', name: '白米饭', priceFen: 300, category: '主食', kitchenStation: 'staple', isAvailable: true },
  { id: 'd06', name: '蛋炒饭', priceFen: 1800, category: '主食', kitchenStation: 'staple', isAvailable: true },
  { id: 'd07', name: '酸辣粉', priceFen: 1500, category: '粉面', kitchenStation: 'noodle', isAvailable: true },
  { id: 'd08', name: '牛肉面', priceFen: 2200, category: '粉面', kitchenStation: 'noodle', isAvailable: true },
  { id: 'd09', name: '臭豆腐', priceFen: 1200, category: '小吃', kitchenStation: 'cold', isAvailable: true },
  { id: 'd10', name: '糖油粑粑', priceFen: 800, category: '小吃', kitchenStation: 'cold', isAvailable: true },
  { id: 'd11', name: '可乐', priceFen: 500, category: '饮品', kitchenStation: 'bar', isAvailable: true },
  { id: 'd12', name: '雪碧', priceFen: 500, category: '饮品', kitchenStation: 'bar', isAvailable: true },
  { id: 'd13', name: '凉拌黄瓜', priceFen: 1200, category: '凉菜', kitchenStation: 'cold', isAvailable: true },
  { id: 'd14', name: '口水鸡', priceFen: 2800, category: '凉菜', kitchenStation: 'cold', isAvailable: true },
  { id: 'd15', name: '招牌套餐A', priceFen: 3980, category: '套餐', kitchenStation: 'hot', isAvailable: true },
  { id: 'd16', name: '双人套餐B', priceFen: 6880, category: '套餐', kitchenStation: 'hot', isAvailable: true },
  { id: 'd17', name: '芒果布丁', priceFen: 1500, category: '甜品', kitchenStation: 'bar', isAvailable: true },
  { id: 'd18', name: '冰淇淋', priceFen: 1200, category: '甜品', kitchenStation: 'bar', isAvailable: false },
];

// ─── 工具函数 ───

const fen2yuan = (fen: number) => (fen / 100).toFixed(2);

function getBase(): string {
  return (window as unknown as Record<string, unknown>).__API_BASE__ as string || '';
}

function getTenantId(): string {
  return (
    (window as unknown as Record<string, unknown>).__TENANT_ID__ as string
    || localStorage.getItem('tenant_id')
    || ''
  );
}

function getStoreId(): string {
  return (
    (window as unknown as Record<string, unknown>).__STORE_ID__ as string
    || localStorage.getItem('store_id')
    || import.meta.env.VITE_STORE_ID
    || ''
  );
}

function formatClock(): string {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, '0');
  const m = String(now.getMinutes()).padStart(2, '0');
  const s = String(now.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

// ─── 快餐 API ───

interface QuickOrderResult {
  quick_order_id: string;
  call_number: string;
  order_type: string;
  total_fen: number;
  status: string;
}

async function apiCreateQuickOrder(
  storeId: string,
  items: { dish_id: string; dish_name: string; qty: number; unit_price_fen: number }[],
  orderType: OrderType,
): Promise<QuickOrderResult> {
  const resp = await fetch(`${getBase()}/api/v1/quick-cashier/order`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
    },
    body: JSON.stringify({ store_id: storeId, items, order_type: orderType }),
  });
  const json: unknown = await resp.json();
  if (!resp.ok) {
    const err = (json as Record<string, unknown>)?.error as Record<string, string>;
    throw new Error(err?.message ?? `HTTP ${resp.status}`);
  }
  return (json as { data: QuickOrderResult }).data;
}

interface QuickPayResult {
  call_number: string;
  change_fen: number | null;
  paid_at: string;
}

async function apiQuickPay(
  quickOrderId: string,
  method: string,
  amountFen: number,
  cashReceivedFen?: number,
): Promise<QuickPayResult> {
  const resp = await fetch(`${getBase()}/api/v1/quick-cashier/order/${encodeURIComponent(quickOrderId)}/pay`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
    },
    body: JSON.stringify({
      method,
      amount_fen: amountFen,
      cash_received_fen: cashReceivedFen ?? null,
    }),
  });
  const json: unknown = await resp.json();
  if (!resp.ok) {
    const err = (json as Record<string, unknown>)?.error as Record<string, string>;
    throw new Error(err?.message ?? `HTTP ${resp.status}`);
  }
  return (json as { data: QuickPayResult }).data;
}

// ─── 购物车类型 ───

interface CartItem {
  dish: DishItem;
  quantity: number;
}

// ─── 支付弹窗状态 ───

type PayStep = 'select_method' | 'cash_input' | 'success';

interface PayModalState {
  open: boolean;
  step: PayStep;
  callNumber: string;
  quickOrderId: string;
  changeFen: number | null;
  cashInputStr: string;
  processing: boolean;
  errorMsg: string;
}

const INIT_PAY_MODAL: PayModalState = {
  open: false,
  step: 'select_method',
  callNumber: '',
  quickOrderId: '',
  changeFen: null,
  cashInputStr: '',
  processing: false,
  errorMsg: '',
};

// ─── 触控按钮组件 ───

function TxBtn({
  label,
  bgColor,
  disabled = false,
  loading = false,
  fullWidth = false,
  size = 'normal',
  onPress,
}: {
  label: string;
  bgColor: string;
  disabled?: boolean;
  loading?: boolean;
  fullWidth?: boolean;
  size?: 'normal' | 'large';
  onPress: () => void;
}) {
  const height = size === 'large' ? 72 : 56;
  return (
    <button
      onClick={onPress}
      disabled={disabled || loading}
      style={{
        minHeight: height,
        width: fullWidth ? '100%' : undefined,
        padding: '0 20px',
        background: disabled || loading ? C.muted : bgColor,
        border: 'none',
        borderRadius: 12,
        color: C.white,
        fontSize: size === 'large' ? 22 : 18,
        fontWeight: 700,
        cursor: disabled || loading ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        transition: 'transform 200ms ease',
      }}
      onPointerDown={e => {
        if (!disabled && !loading) {
          (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
        }
      }}
      onPointerUp={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
      onPointerLeave={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
    >
      {loading ? '处理中...' : label}
    </button>
  );
}

// ─── 支付弹窗 ───

function PayModal({
  modal,
  totalFen,
  orderType,
  onClose,
  onPayMethod,
  onCashConfirm,
  onCashInputChange,
}: {
  modal: PayModalState;
  totalFen: number;
  orderType: OrderType;
  onClose: () => void;
  onPayMethod: (method: string) => void;
  onCashConfirm: () => void;
  onCashInputChange: (val: string) => void;
}) {
  if (!modal.open) return null;

  const cashReceivedFen = Math.round(parseFloat(modal.cashInputStr || '0') * 100);
  const changeFen = cashReceivedFen > 0 ? cashReceivedFen - totalFen : null;
  const cashEnough = cashReceivedFen >= totalFen;

  const orderTypeLabel = ORDER_TYPES.find(t => t.value === orderType)?.label ?? orderType;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: 20,
      }}
      onClick={e => {
        if (e.target === e.currentTarget && modal.step !== 'success') onClose();
      }}
    >
      <div
        style={{
          background: '#0F2530',
          border: `1px solid ${C.border}`,
          borderRadius: 20,
          padding: 32,
          width: '100%',
          maxWidth: 480,
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}
      >
        {/* ── 成功界面 ── */}
        {modal.step === 'success' && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 22, color: C.success, marginBottom: 12, fontWeight: 700 }}>
              支付成功
            </div>
            <div style={{ fontSize: 18, color: C.dimText, marginBottom: 24 }}>
              {orderTypeLabel} · 取餐号
            </div>
            <div
              style={{
                fontSize: 96,
                fontWeight: 900,
                color: C.accent,
                fontFamily: 'JetBrains Mono, monospace',
                letterSpacing: 8,
                lineHeight: 1,
                marginBottom: 20,
              }}
            >
              {modal.callNumber}
            </div>
            {modal.changeFen !== null && modal.changeFen > 0 && (
              <div
                style={{
                  fontSize: 22,
                  color: C.warning,
                  marginBottom: 20,
                  fontWeight: 700,
                }}
              >
                找零 ¥{fen2yuan(modal.changeFen)}
              </div>
            )}
            <TxBtn
              label="完成"
              bgColor={C.success}
              fullWidth
              size="large"
              onPress={onClose}
            />
          </div>
        )}

        {/* ── 现金输入界面 ── */}
        {modal.step === 'cash_input' && (
          <div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 24,
              }}
            >
              <span style={{ fontSize: 22, fontWeight: 800, color: C.white }}>
                现金收款
              </span>
              <button
                onClick={onClose}
                style={{
                  minHeight: 48,
                  minWidth: 48,
                  background: 'transparent',
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  color: C.muted,
                  fontSize: 18,
                  cursor: 'pointer',
                }}
              >
                ✕
              </button>
            </div>

            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 18, color: C.dimText, marginBottom: 8 }}>
                应收金额
              </div>
              <div style={{ fontSize: 44, fontWeight: 800, color: C.accent }}>
                ¥{fen2yuan(totalFen)}
              </div>
            </div>

            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 18, color: C.dimText, marginBottom: 8 }}>
                实收金额
              </div>
              <input
                type="number"
                min="0"
                step="0.01"
                value={modal.cashInputStr}
                onChange={e => onCashInputChange(e.target.value)}
                placeholder="输入收到的金额"
                autoFocus
                style={{
                  width: '100%',
                  minHeight: 64,
                  padding: '0 16px',
                  background: C.card,
                  border: `2px solid ${cashEnough ? C.success : C.border}`,
                  borderRadius: 10,
                  color: C.white,
                  fontSize: 28,
                  fontWeight: 700,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            {cashReceivedFen > 0 && (
              <div
                style={{
                  marginBottom: 20,
                  padding: 16,
                  background: cashEnough ? `${C.success}18` : `${C.danger}18`,
                  border: `1px solid ${cashEnough ? C.success : C.danger}`,
                  borderRadius: 10,
                  textAlign: 'center',
                }}
              >
                {cashEnough ? (
                  <span style={{ fontSize: 22, color: C.success, fontWeight: 700 }}>
                    找零 ¥{fen2yuan(changeFen ?? 0)}
                  </span>
                ) : (
                  <span style={{ fontSize: 20, color: C.danger }}>
                    金额不足，还差 ¥{fen2yuan(totalFen - cashReceivedFen)}
                  </span>
                )}
              </div>
            )}

            {modal.errorMsg && (
              <div
                style={{
                  marginBottom: 16,
                  color: C.danger,
                  fontSize: 16,
                  textAlign: 'center',
                }}
              >
                {modal.errorMsg}
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <TxBtn
                label="返回"
                bgColor={C.muted}
                onPress={() => onCashInputChange('')}
              />
              <div style={{ flex: 1 }}>
                <TxBtn
                  label="确认收款"
                  bgColor={C.accent}
                  disabled={!cashEnough || modal.processing}
                  loading={modal.processing}
                  fullWidth
                  size="large"
                  onPress={onCashConfirm}
                />
              </div>
            </div>
          </div>
        )}

        {/* ── 支付方式选择界面 ── */}
        {modal.step === 'select_method' && (
          <div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 24,
              }}
            >
              <span style={{ fontSize: 22, fontWeight: 800, color: C.white }}>
                选择支付方式
              </span>
              <button
                onClick={onClose}
                style={{
                  minHeight: 48,
                  minWidth: 48,
                  background: 'transparent',
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  color: C.muted,
                  fontSize: 18,
                  cursor: 'pointer',
                }}
              >
                ✕
              </button>
            </div>

            {/* 订单类型 + 金额 */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 24,
                padding: 16,
                background: C.card,
                borderRadius: 12,
              }}
            >
              <div>
                <div style={{ fontSize: 18, color: C.dimText }}>
                  {orderTypeLabel}
                </div>
                <div style={{ fontSize: 16, color: C.dimText, marginTop: 4 }}>
                  取餐号将在支付后显示
                </div>
              </div>
              <div style={{ fontSize: 44, fontWeight: 800, color: C.accent }}>
                ¥{fen2yuan(totalFen)}
              </div>
            </div>

            {modal.errorMsg && (
              <div
                style={{
                  marginBottom: 16,
                  color: C.danger,
                  fontSize: 16,
                  textAlign: 'center',
                }}
              >
                {modal.errorMsg}
              </div>
            )}

            {/* 支付方式大按钮 */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 12,
              }}
            >
              <TxButton2
                icon="💚"
                label="微信支付"
                bgColor="#07C160"
                loading={modal.processing}
                onPress={() => onPayMethod('wechat')}
              />
              <TxButton2
                icon="💙"
                label="支付宝"
                bgColor="#1677FF"
                loading={modal.processing}
                onPress={() => onPayMethod('alipay')}
              />
              <TxButton2
                icon="💴"
                label="现金"
                bgColor={C.warning}
                loading={modal.processing}
                onPress={() => onPayMethod('cash')}
              />
              <TxButton2
                icon="💳"
                label="银联"
                bgColor="#e6002d"
                loading={modal.processing}
                onPress={() => onPayMethod('unionpay')}
              />
              <div style={{ gridColumn: '1 / -1' }}>
                <TxButton2
                  icon="👤"
                  label="会员卡"
                  bgColor={C.info}
                  loading={modal.processing}
                  onPress={() => onPayMethod('member_balance')}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TxButton2({
  icon,
  label,
  bgColor,
  loading,
  onPress,
}: {
  icon: string;
  label: string;
  bgColor: string;
  loading: boolean;
  onPress: () => void;
}) {
  return (
    <button
      onClick={onPress}
      disabled={loading}
      style={{
        minHeight: 72,
        padding: '0 16px',
        background: loading ? C.muted : bgColor,
        border: 'none',
        borderRadius: 12,
        color: C.white,
        fontSize: 20,
        fontWeight: 700,
        cursor: loading ? 'not-allowed' : 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        transition: 'transform 200ms ease',
        width: '100%',
      }}
      onPointerDown={e => {
        if (!loading) (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
      }}
      onPointerUp={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
      onPointerLeave={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
    >
      <span>{icon}</span>
      <span>{loading ? '处理中...' : label}</span>
    </button>
  );
}

// ─── 主组件 ───

export function QuickCashierPage() {
  const navigate = useNavigate();
  const scanInputRef = useRef<HTMLInputElement>(null);
  const storeId = getStoreId();

  // ── 菜品数据 ──
  const [categories, setCategories] = useState<string[]>(MOCK_CATEGORIES);
  const [dishes, setDishes] = useState<DishItem[]>(MOCK_DISHES);
  const [activeCategory, setActiveCategory] = useState<string>(MOCK_CATEGORIES[0]);

  // ── 购物车 ──
  const [cart, setCart] = useState<CartItem[]>([]);
  const [orderType, setOrderType] = useState<OrderType>('dine_in');

  // ── 扫码 ──
  const [scanValue, setScanValue] = useState('');

  // ── 当前时间 ──
  const [clock, setClock] = useState(formatClock());

  // ── 支付弹窗 ──
  const [payModal, setPayModal] = useState<PayModalState>(INIT_PAY_MODAL);

  // ── 每秒更新时钟 ──
  useEffect(() => {
    const timer = setInterval(() => setClock(formatClock()), 1000);
    return () => clearInterval(timer);
  }, []);

  // ── 加载菜品数据 ──
  useEffect(() => {
    const load = async () => {
      try {
        const [cats, ds] = await Promise.all([
          fetchCategories(storeId),
          fetchDishes(storeId),
        ]);
        if (cats.length > 0) setCategories(cats);
        if (ds.length > 0) setDishes(ds);
        if (cats.length > 0) setActiveCategory(cats[0]);
      } catch {
        // 离线模式使用 mock
      }
    };
    load();
  }, [storeId]);

  // ── 支付后自动聚焦扫码框 ──
  useEffect(() => {
    if (!payModal.open) {
      const timer = setTimeout(() => scanInputRef.current?.focus(), 300);
      return () => clearTimeout(timer);
    }
  }, [payModal.open]);

  // ── 购物车操作 ──
  const addToCart = useCallback((dish: DishItem) => {
    if (!dish.isAvailable) return;
    setCart(prev => {
      const existing = prev.find(c => c.dish.id === dish.id);
      if (existing) {
        return prev.map(c => c.dish.id === dish.id ? { ...c, quantity: c.quantity + 1 } : c);
      }
      return [...prev, { dish, quantity: 1 }];
    });
  }, []);

  const updateQuantity = useCallback((dishId: string, delta: number) => {
    setCart(prev =>
      prev
        .map(c => c.dish.id === dishId ? { ...c, quantity: c.quantity + delta } : c)
        .filter(c => c.quantity > 0),
    );
  }, []);

  const clearCart = useCallback(() => setCart([]), []);

  // ── 计算合计 ──
  const totalFen = cart.reduce((s, c) => s + c.dish.priceFen * c.quantity, 0);
  const totalCount = cart.reduce((s, c) => s + c.quantity, 0);

  // ── 扫码处理 ──
  const handleScan = useCallback((code: string) => {
    if (!code.trim()) return;
    const matched = dishes.find(d => d.id === code || d.name.includes(code));
    if (matched) addToCart(matched);
    setScanValue('');
  }, [dishes, addToCart]);

  // ── 打开支付弹窗 ──
  const handleOpenPay = useCallback(async () => {
    if (cart.length === 0) return;

    // 先创建快餐订单，获取取餐号
    setPayModal({ ...INIT_PAY_MODAL, open: true, processing: true });
    try {
      const items = cart.map(c => ({
        dish_id: c.dish.id,
        dish_name: c.dish.name,
        qty: c.quantity,
        unit_price_fen: c.dish.priceFen,
      }));
      const result = await apiCreateQuickOrder(storeId, items, orderType);
      setPayModal(prev => ({
        ...prev,
        step: 'select_method',
        callNumber: result.call_number,
        quickOrderId: result.quick_order_id,
        processing: false,
      }));
    } catch (err) {
      setPayModal(prev => ({
        ...prev,
        processing: false,
        errorMsg: err instanceof Error ? err.message : '创建订单失败',
      }));
    }
  }, [cart, storeId, orderType]);

  // ── 支付方式选择 ──
  const handlePayMethod = useCallback(async (method: string) => {
    if (method === 'cash') {
      setPayModal(prev => ({ ...prev, step: 'cash_input', errorMsg: '' }));
      return;
    }
    // 其他方式直接支付
    setPayModal(prev => ({ ...prev, processing: true, errorMsg: '' }));
    try {
      const result = await apiQuickPay(payModal.quickOrderId, method, totalFen);
      // 打印小票（静默失败）
      _tryPrint(payModal.quickOrderId);
      setPayModal(prev => ({
        ...prev,
        step: 'success',
        callNumber: result.call_number,
        processing: false,
      }));
      setCart([]);
    } catch (err) {
      setPayModal(prev => ({
        ...prev,
        processing: false,
        errorMsg: err instanceof Error ? err.message : '支付失败，请重试',
      }));
    }
  }, [payModal.quickOrderId, totalFen]);

  // ── 现金支付确认 ──
  const handleCashConfirm = useCallback(async () => {
    const cashReceivedFen = Math.round(parseFloat(payModal.cashInputStr || '0') * 100);
    if (cashReceivedFen < totalFen) return;

    setPayModal(prev => ({ ...prev, processing: true, errorMsg: '' }));
    try {
      const result = await apiQuickPay(
        payModal.quickOrderId,
        'cash',
        totalFen,
        cashReceivedFen,
      );
      // 打印小票 + 开钱箱（静默失败）
      _tryPrint(payModal.quickOrderId);
      try { await openCashBox(); } catch { /* ignore */ }

      setPayModal(prev => ({
        ...prev,
        step: 'success',
        callNumber: result.call_number,
        changeFen: result.change_fen,
        processing: false,
      }));
      setCart([]);
    } catch (err) {
      setPayModal(prev => ({
        ...prev,
        processing: false,
        errorMsg: err instanceof Error ? err.message : '支付失败，请重试',
      }));
    }
  }, [payModal.quickOrderId, payModal.cashInputStr, totalFen]);

  // ── 关闭弹窗 ──
  const handleCloseModal = useCallback(() => {
    setPayModal(INIT_PAY_MODAL);
  }, []);

  // ── 当前分类菜品 ──
  const filteredDishes = dishes.filter(d => d.category === activeCategory);

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        background: C.bg,
        color: C.text,
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        flexDirection: 'column',
      }}
    >
      {/* ── 顶栏 ── */}
      <header
        style={{
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          borderBottom: `1px solid ${C.border}`,
          flexShrink: 0,
          background: C.card,
          minHeight: 60,
        }}
      >
        <button
          onClick={() => navigate('/dashboard')}
          style={{
            minHeight: 48,
            minWidth: 48,
            padding: '8px 14px',
            background: 'transparent',
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            color: C.text,
            fontSize: 16,
            cursor: 'pointer',
          }}
          onPointerDown={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
          }}
          onPointerUp={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
          onPointerLeave={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
        >
          ← 主页
        </button>

        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: C.white }}>
          快餐模式
        </h1>

        <span
          style={{
            fontSize: 16,
            padding: '4px 10px',
            background: `${C.accent}22`,
            border: `1px solid ${C.accent}`,
            borderRadius: 6,
            color: C.accent,
            fontWeight: 600,
          }}
        >
          Quick Cashier
        </span>

        {/* 叫号屏入口 */}
        <button
          onClick={() => navigate('/calling-screen')}
          style={{
            minHeight: 48,
            padding: '8px 16px',
            background: `${C.success}18`,
            border: `1px solid ${C.success}`,
            borderRadius: 8,
            color: C.success,
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
          }}
          onPointerDown={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
          }}
          onPointerUp={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
          onPointerLeave={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
        >
          叫号管理
        </button>

        <div style={{ marginLeft: 'auto', fontSize: 18, color: C.dimText, fontFamily: 'monospace' }}>
          {clock}
        </div>
      </header>

      {/* ── 主内容（左右分屏） ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* ═══ 左侧：分类 + 菜品网格 ═══ */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            borderRight: `1px solid ${C.border}`,
            overflow: 'hidden',
          }}
        >
          {/* 分类 Tab（横向滚动） */}
          <div
            style={{
              display: 'flex',
              gap: 0,
              borderBottom: `1px solid ${C.border}`,
              flexShrink: 0,
              overflowX: 'auto',
              WebkitOverflowScrolling: 'touch',
              background: C.card,
            }}
          >
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                style={{
                  flexShrink: 0,
                  minHeight: 52,
                  padding: '0 20px',
                  background: 'transparent',
                  border: 'none',
                  borderBottom: activeCategory === cat ? `3px solid ${C.accent}` : '3px solid transparent',
                  color: activeCategory === cat ? C.accent : C.muted,
                  fontSize: 18,
                  fontWeight: activeCategory === cat ? 700 : 400,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                  transition: 'color 150ms ease',
                }}
              >
                {cat}
              </button>
            ))}
          </div>

          {/* 菜品网格 */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
              padding: 12,
            }}
          >
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
                gap: 10,
              }}
            >
              {filteredDishes.map(dish => {
                const inCart = cart.find(c => c.dish.id === dish.id);
                return (
                  <button
                    key={dish.id}
                    onClick={() => addToCart(dish)}
                    disabled={!dish.isAvailable}
                    style={{
                      padding: '14px 10px',
                      borderRadius: 12,
                      textAlign: 'center',
                      background: dish.isAvailable ? C.card : `${C.muted}18`,
                      border: inCart ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                      color: dish.isAvailable ? C.white : C.muted,
                      cursor: dish.isAvailable ? 'pointer' : 'not-allowed',
                      opacity: dish.isAvailable ? 1 : 0.5,
                      transition: 'transform 200ms ease',
                      position: 'relative',
                      minHeight: 100,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 6,
                    }}
                    onPointerDown={e => {
                      if (dish.isAvailable) {
                        (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
                      }
                    }}
                    onPointerUp={e => {
                      (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
                    }}
                    onPointerLeave={e => {
                      (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
                    }}
                  >
                    {/* 已点角标 */}
                    {inCart && (
                      <span
                        style={{
                          position: 'absolute',
                          top: -6,
                          right: -6,
                          width: 26,
                          height: 26,
                          borderRadius: '50%',
                          background: C.accent,
                          color: C.white,
                          fontSize: 16,
                          fontWeight: 700,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        {inCart.quantity}
                      </span>
                    )}

                    {/* 沽清遮罩 */}
                    {!dish.isAvailable && (
                      <span
                        style={{
                          position: 'absolute',
                          inset: 0,
                          borderRadius: 12,
                          background: 'rgba(0,0,0,0.55)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 18,
                          fontWeight: 700,
                          color: C.danger,
                        }}
                      >
                        已沽清
                      </span>
                    )}

                    <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.3 }}>
                      {dish.name}
                    </div>
                    <div style={{ fontSize: 18, color: C.accent, fontWeight: 700 }}>
                      ¥{fen2yuan(dish.priceFen)}
                    </div>
                  </button>
                );
              })}
              {filteredDishes.length === 0 && (
                <div
                  style={{
                    gridColumn: '1/-1',
                    textAlign: 'center',
                    padding: 40,
                    color: C.muted,
                    fontSize: 18,
                  }}
                >
                  该分类暂无菜品
                </div>
              )}
            </div>
          </div>

          {/* 扫码栏 */}
          <div
            style={{
              padding: '10px 16px',
              borderTop: `1px solid ${C.border}`,
              display: 'flex',
              gap: 10,
              alignItems: 'center',
              flexShrink: 0,
              background: C.card,
            }}
          >
            <span style={{ fontSize: 18, color: C.muted, flexShrink: 0 }}>扫码:</span>
            <input
              ref={scanInputRef}
              value={scanValue}
              onChange={e => setScanValue(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') handleScan(scanValue);
              }}
              placeholder="扫码枪自动输入 / 手动输入菜品编码"
              style={{
                flex: 1,
                minHeight: 48,
                padding: '0 16px',
                background: C.bg,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                color: C.white,
                fontSize: 18,
                outline: 'none',
              }}
            />
          </div>
        </div>

        {/* ═══ 右侧：购物车 ═══ */}
        <div
          style={{
            width: 340,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            background: C.card,
          }}
        >
          {/* 购物车标题 */}
          <div
            style={{
              padding: '12px 16px',
              borderBottom: `1px solid ${C.border}`,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexShrink: 0,
            }}
          >
            <h3 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: C.white }}>
              购物车
              {totalCount > 0 && (
                <span
                  style={{
                    marginLeft: 8,
                    fontSize: 16,
                    padding: '2px 8px',
                    background: C.accent,
                    borderRadius: 12,
                  }}
                >
                  {totalCount}
                </span>
              )}
            </h3>
            {cart.length > 0 && (
              <button
                onClick={clearCart}
                style={{
                  minHeight: 48,
                  padding: '8px 14px',
                  background: 'transparent',
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  color: C.muted,
                  fontSize: 16,
                  cursor: 'pointer',
                }}
              >
                清空
              </button>
            )}
          </div>

          {/* 购物车列表 */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
              padding: '8px 0',
            }}
          >
            {cart.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 18 }}>
                点击菜品加入购物车
              </div>
            ) : (
              cart.map(item => (
                <div
                  key={item.dish.id}
                  style={{
                    padding: '10px 16px',
                    borderBottom: `1px solid ${C.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 18, fontWeight: 600, color: C.white }}>
                      {item.dish.name}
                    </div>
                    <div style={{ fontSize: 16, color: C.muted }}>
                      ¥{fen2yuan(item.dish.priceFen)}
                    </div>
                  </div>

                  {/* 数量调节 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button
                      onClick={() => updateQuantity(item.dish.id, -1)}
                      style={{
                        width: 48,
                        height: 48,
                        borderRadius: 8,
                        background: C.bg,
                        border: `1px solid ${C.border}`,
                        color: C.text,
                        fontSize: 22,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      -
                    </button>
                    <span
                      style={{
                        fontSize: 20,
                        fontWeight: 700,
                        minWidth: 28,
                        textAlign: 'center',
                        color: C.white,
                      }}
                    >
                      {item.quantity}
                    </span>
                    <button
                      onClick={() => updateQuantity(item.dish.id, 1)}
                      style={{
                        width: 48,
                        height: 48,
                        borderRadius: 8,
                        background: C.accent,
                        border: 'none',
                        color: C.white,
                        fontSize: 22,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      +
                    </button>
                  </div>

                  {/* 小计 */}
                  <div
                    style={{
                      fontSize: 18,
                      fontWeight: 700,
                      color: C.accent,
                      minWidth: 60,
                      textAlign: 'right',
                    }}
                  >
                    ¥{fen2yuan(item.dish.priceFen * item.quantity)}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 底部：订单类型 + 合计 + 结账 */}
          <div
            style={{
              padding: '14px 16px',
              borderTop: `1px solid ${C.border}`,
              flexShrink: 0,
            }}
          >
            {/* 订单类型选择 */}
            <div
              style={{
                display: 'flex',
                gap: 8,
                marginBottom: 14,
              }}
            >
              {ORDER_TYPES.map(t => (
                <button
                  key={t.value}
                  onClick={() => setOrderType(t.value)}
                  style={{
                    flex: 1,
                    minHeight: 48,
                    border: orderType === t.value ? `2px solid ${t.color}` : `1px solid ${C.border}`,
                    borderRadius: 8,
                    background: orderType === t.value ? `${t.color}22` : 'transparent',
                    color: orderType === t.value ? t.color : C.muted,
                    fontSize: 17,
                    fontWeight: orderType === t.value ? 700 : 400,
                    cursor: 'pointer',
                    transition: 'all 150ms ease',
                  }}
                  onPointerDown={e => {
                    (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
                  }}
                  onPointerUp={e => {
                    (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
                  }}
                  onPointerLeave={e => {
                    (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
                  }}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* 合计 */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: 14,
              }}
            >
              <span style={{ fontSize: 18, color: C.muted }}>合计</span>
              <span style={{ fontSize: 32, fontWeight: 800, color: C.accent }}>
                ¥{fen2yuan(totalFen)}
              </span>
            </div>

            {/* 结账按钮 */}
            <TxBtn
              label={cart.length === 0 ? '请选择菜品' : '结账'}
              bgColor={C.accent}
              disabled={cart.length === 0}
              fullWidth
              size="large"
              onPress={handleOpenPay}
            />
          </div>
        </div>
      </div>

      {/* ── 支付弹窗 ── */}
      <PayModal
        modal={payModal}
        totalFen={totalFen}
        orderType={orderType}
        onClose={handleCloseModal}
        onPayMethod={handlePayMethod}
        onCashConfirm={handleCashConfirm}
        onCashInputChange={val =>
          setPayModal(prev => ({ ...prev, cashInputStr: val }))
        }
      />
    </div>
  );
}

// ─── 工具：静默打印 ───

async function _tryPrint(quickOrderId: string): Promise<void> {
  try {
    const resp = await fetch(`${getBase()}/api/v1/trade/orders/${encodeURIComponent(quickOrderId)}/print/receipt`, {
      method: 'POST',
      headers: { 'X-Tenant-ID': getTenantId() },
    });
    if (resp.ok) {
      const json: unknown = await resp.json();
      const b64 = (json as { data: { content_base64?: string } }).data?.content_base64;
      if (b64) await bridgePrint(b64);
    }
  } catch {
    // 打印失败不影响主流程
  }
}
