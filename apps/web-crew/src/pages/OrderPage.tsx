/**
 * 点菜页面（核心） — 分类导航 + AI推荐 + 菜品列表 + 购物车 + 更多操作 + 出餐追踪 + 快捷结账
 * 对标: 天财商龙移动收银台 + Toast Go 2 + Square KDS Mobile + AI Agent 增强
 *
 * 支持: 加菜/退菜/改数量/时价菜输入价格/称重菜输入重量/备注做法
 *       + 8个快捷操作 + AI推荐 + 出餐进度 + 扫码结账
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { fetchDishCategories, fetchDishes, addItemsToOrder } from '../api/index';
import type { DishCategory, DishInfo } from '../api/index';
import { WeighDishSheet } from './WeighDishSheet';
import { ComboSelectionSheet } from './ComboSelectionSheet';
import { fetchComboDetail } from '../api/comboApi';
import type { ComboDetail, ComboSelection } from '../api/comboApi';

/* ---------- API 工具函数 ---------- */
const API_BASE = (): string =>
  (typeof window !== 'undefined' && (window as unknown as Record<string, string>).__TX_API_BASE__) || '';

const TENANT_ID = (): string =>
  (typeof window !== 'undefined' && (window as unknown as Record<string, string>).__TENANT_ID__) || '';

async function txFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE()}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID(),
      ...(options.headers || {}),
    },
  });
  const json = await res.json();
  if (!res.ok || json.ok === false) {
    throw new Error(json.error?.message || json.detail || `HTTP ${res.status}`);
  }
  return json.data ?? json;
}

/* ---------- Toast 类型 ---------- */
interface ToastMsg {
  id: number;
  text: string;
  color: string; // green | red
}

/* ---------- 样式常量(Design Token) ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  accentActive: '#E55A28',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
  warning: '#BA7517',
  info: '#185FA5',
};

/* ---------- Mock AI 推荐 & KDS(保持 mock，待后续接真实 API) ---------- */

/* Mock AI 推荐 */
const MOCK_AI_RECS = [
  { id: 'd3', name: '红烧肉', priceFen: 5800, reason: '本桌常点', tag: '回头客推荐' },
  { id: 'd1', name: '剁椒鱼头', priceFen: 8800, reason: '今日必点TOP1', tag: '招牌热销' },
  { id: 'd12', name: '杨枝甘露', priceFen: 2800, reason: '甜品搭配率82%', tag: 'AI搭配' },
  { id: 'd5', name: '蒜蓉蒸虾', priceFen: 12800, reason: '新品好评率95%', tag: '新品推荐' },
];

/* Mock 出餐进度 */
const MOCK_KDS_STATUS = [
  { taskId: 'k1', dishName: '剁椒鱼头', qty: 1, status: 'done' as const, isOvertime: false, rushCount: 0 },
  { taskId: 'k2', dishName: '小炒黄牛肉', qty: 1, status: 'cooking' as const, isOvertime: false, rushCount: 0 },
  { taskId: 'k3', dishName: '红烧肉', qty: 2, status: 'pending' as const, isOvertime: false, rushCount: 0 },
  { taskId: 'k4', dishName: '凉拌黄瓜', qty: 1, status: 'pending' as const, isOvertime: true, rushCount: 1 },
];

/* ---------- 类型 ---------- */
interface CartItem {
  dishId: string;
  name: string;
  qty: number;
  priceFen: number;
  weight?: number;
  spec?: string;
  note: string;
}

type ModalType =
  | 'none'
  | 'more-ops'        // 更多操作菜单
  | 'edit-table'      // 修改开台
  | 'verify-coupon'   // 聚合验券
  | 'copy-dishes'     // 复制菜品
  | 'sold-out-mgmt'   // 沽清管理
  | 'daily-limit'     // 限量设置
  | 'change-waiter'   // 修改点菜员
  | 'kds-status'      // 出餐进度
  | 'checkout'        // 快捷结账
  | 'pre-bill'        // 埋单
  | 'fire-kitchen'    // 起菜
  | 'mark-served'     // 上菜/划菜
  | 'price-override'  // 菜品变价
  | 'item-transfer'   // 单品转台
  | 'verify-receipt'  // 核对单据
  | 'print-receipt'   // 打印客单
  | 'kitchen-msg'     // 后厨通知
  | 'pay-transfer';   // 转账

/* ---------- 组件 ---------- */
export function OrderPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const tableNo = params.get('table') || '';
  const guests = params.get('guests') || '';
  const orderId = params.get('order_id') || 'mock-order-001';

  const storeId = (window as unknown as Record<string, string>).__STORE_ID__ || 'store_001';

  const [categories, setCategories] = useState<DishCategory[]>([]);
  const [dishes, setDishes] = useState<DishInfo[]>([]);
  const [menuLoading, setMenuLoading] = useState(false);

  const [activeCat, setActiveCat] = useState<string | null>(null);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [showCart, setShowCart] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 称重菜弹层
  const [weighDish, setWeighDish] = useState<DishInfo | null>(null);

  // 套餐N选M弹层
  const [comboSheet, setComboSheet] = useState<ComboDetail | null>(null);

  // 弹窗: 时价/称重/做法
  const [editingDish, setEditingDish] = useState<DishInfo | null>(null);
  const [editPrice, setEditPrice] = useState('');
  const [editWeight, setEditWeight] = useState('');
  const [editSpec, setEditSpec] = useState('');
  const [editNote, setEditNote] = useState('');

  // 更多操作 & 功能弹窗
  const [activeModal, setActiveModal] = useState<ModalType>('none');

  // AI 推荐面板
  const [aiExpanded, setAiExpanded] = useState(true);

  // 修改开台表单
  const [editGuestCount, setEditGuestCount] = useState(guests);
  const [editWaiterId, setEditWaiterId] = useState('');

  // 聚合验券
  const [couponCode, setCouponCode] = useState('');
  const [couponResult, setCouponResult] = useState<string | null>(null);

  // 复制菜品（sourceOrderId 用于记录已复制来源，暂不展示）
  const [_sourceOrderId, setSourceOrderId] = useState('');

  // 沽清管理
  const [dishAvailability, setDishAvailability] = useState<Record<string, boolean>>({});

  // 限量设置
  const [limitDishId, setLimitDishId] = useState('');
  const [limitValue, setLimitValue] = useState('');

  // 修改点菜员
  const [newWaiterId, setNewWaiterId] = useState('');

  // 出餐进度
  const [kdsItems] = useState(MOCK_KDS_STATUS);

  // 结账
  const [checkoutProcessing, setCheckoutProcessing] = useState(false);
  const [checkoutDone, setCheckoutDone] = useState(false);

  // 埋单（preBillData 待结账面板接入）
  const [_preBillData, setPreBillData] = useState<{
    items: { item_name: string; quantity: number; unit_price_fen: number; subtotal_fen: number; is_gift: boolean }[];
    subtotal_fen: number; discount_fen: number; service_charge_fen: number; total_fen: number;
  } | null>(null);

  // 后厨通知
  const [_kitchenMsg, setKitchenMsg] = useState('');
  const [_kitchenMsgSent, setKitchenMsgSent] = useState(false);

  /* ---------- Toast ---------- */
  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  const toastIdRef = useRef(0);
  const showToast = useCallback((text: string, color: string, durationMs = 2000) => {
    const id = ++toastIdRef.current;
    setToasts(prev => [...prev, { id, text, color }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), durationMs);
  }, []);
  const toastOk = useCallback((text: string) => showToast(text, C.green, 2000), [showToast]);
  const toastErr = useCallback((text: string) => showToast(text, '#ef4444', 3000), [showToast]);

  /* ---------- 操作 loading 状态 ---------- */
  const [refreshingDish, setRefreshingDish] = useState(false);
  const [rushingTaskId, setRushingTaskId] = useState<string | null>(null);
  const [updatingTable, setUpdatingTable] = useState(false);
  const [verifyingCoupon, setVerifyingCoupon] = useState(false);
  const [copyingDishes, setCopyingDishes] = useState(false);
  const [historyOrders, setHistoryOrders] = useState<
    { id: string; items: { dish_id: string; dish_name: string; qty: number; price_fen: number }[] }[]
  >([]);
  const [togglingDishId, setTogglingDishId] = useState<string | null>(null);
  const [settingLimit, setSettingLimit] = useState(false);
  const [updatingWaiter, setUpdatingWaiter] = useState(false);

  /* ---------- 加载菜品分类 ---------- */
  useEffect(() => {
    fetchDishCategories(storeId)
      .then(res => {
        setCategories(res.items);
        if (res.items.length > 0) {
          setActiveCat(res.items[0].category_id);
        }
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '加载分类失败';
        toastErr(`加载分类失败: ${msg}`);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId]);

  /* ---------- 切换分类时加载菜品 ---------- */
  useEffect(() => {
    if (!activeCat) return;
    setMenuLoading(true);
    fetchDishes(storeId, activeCat)
      .then(res => {
        setDishes(res.items);
        // 同步沽清状态
        setDishAvailability(prev => {
          const map = { ...prev };
          res.items.forEach(d => { map[d.dish_id] = !d.sold_out; });
          return map;
        });
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '加载菜品失败';
        toastErr(`加载菜品失败: ${msg}`);
      })
      .finally(() => setMenuLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, activeCat]);

  const cartTotal = cart.reduce((sum, item) => {
    const weight = item.weight || 1;
    return sum + item.priceFen * item.qty * weight;
  }, 0);

  const cartCount = cart.reduce((sum, i) => sum + i.qty, 0);

  /* 添加到购物车（普通菜直接加，特殊菜弹窗） */
  const handleDishPress = (dish: DishInfo) => {
    if (dish.sold_out) return;
    // 套餐菜：弹出N选M选择面板
    if (dish.is_combo && dish.combo_id) {
      fetchComboDetail(dish.combo_id)
        .then(detail => setComboSheet(detail))
        .catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : '加载套餐失败';
          toastErr(`加载套餐失败: ${msg}`);
        });
      return;
    }
    // 称重菜：弹出专用称重面板
    if (dish.is_weighed) {
      setWeighDish(dish);
      return;
    }
    const specs = dish.specs || [];
    if (dish.is_market_price || specs.length > 0) {
      setEditingDish(dish);
      setEditPrice(dish.is_market_price ? '' : String(dish.price_fen / 100));
      setEditWeight('1');
      setEditSpec(specs.length > 0 ? specs[0].options[0] : '');
      setEditNote('');
      return;
    }
    addToCartSimple(dish);
  };

  const addToCartSimple = (dish: DishInfo) => {
    setCart(prev => {
      const existing = prev.find(i => i.dishId === dish.dish_id && !i.spec);
      if (existing) {
        return prev.map(i => i.dishId === dish.dish_id && !i.spec ? { ...i, qty: i.qty + 1 } : i);
      }
      return [...prev, { dishId: dish.dish_id, name: dish.dish_name, qty: 1, priceFen: dish.price_fen, note: '' }];
    });
  };

  /** 通用加入购物车（供套餐确认回调使用） */
  const addToCart = useCallback((item: {
    dish_id: string;
    dish_name: string;
    quantity: number;
    unit_price_fen: number;
    special_notes?: string;
  }) => {
    setCart(prev => [
      ...prev,
      {
        dishId: item.dish_id,
        name: item.dish_name,
        qty: item.quantity,
        priceFen: item.unit_price_fen,
        note: item.special_notes || '',
      },
    ]);
  }, []);

  const confirmEditDish = () => {
    if (!editingDish) return;
    const priceFen = editingDish.is_market_price
      ? Math.round(parseFloat(editPrice || '0') * 100)
      : editingDish.price_fen;
    const weight = editingDish.is_weighed ? parseFloat(editWeight || '1') : undefined;

    setCart(prev => [
      ...prev,
      {
        dishId: editingDish.dish_id,
        name: editingDish.dish_name,
        qty: 1,
        priceFen: priceFen,
        weight,
        spec: editSpec || undefined,
        note: editNote,
      },
    ]);
    setEditingDish(null);
  };

  const updateQty = (index: number, delta: number) => {
    setCart(prev => {
      const next = [...prev];
      next[index] = { ...next[index], qty: next[index].qty + delta };
      if (next[index].qty <= 0) next.splice(index, 1);
      return next;
    });
  };

  const handleSubmit = () => {
    if (cart.length === 0) return;
    setSubmitting(true);
    const items = cart.map(i => ({
      dish_id: i.dishId,
      dish_name: i.name,
      quantity: i.qty,
      unit_price_fen: i.priceFen,
      special_notes: [i.spec, i.note].filter(Boolean).join(' / ') || undefined,
    }));
    addItemsToOrder(orderId, items)
      .then(() => {
        setCart([]);
        setShowCart(false);
        navigate('/active');
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '提交失败';
        toastErr(`提交失败: ${msg}`);
      })
      .finally(() => setSubmitting(false));
  };

  const cartItemQty = (dishId: string): number =>
    cart.filter(i => i.dishId === dishId).reduce((s, i) => s + i.qty, 0);

  /* AI推荐: 一键加入 */
  const addAIRecToCart = useCallback((rec: typeof MOCK_AI_RECS[0]) => {
    const dish = dishes.find(d => d.dish_id === rec.id);
    if (dish) {
      handleDishPress(dish);
    } else {
      // 菜品未在当前分类，构造临时 DishInfo 直接加购
      addToCartSimple({
        dish_id: rec.id, dish_name: rec.name, category_id: '',
        price_fen: rec.priceFen, sold_out: false,
        is_market_price: false, is_weighed: false,
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dishes]);

  /* 更多操作菜单项 — 5x5 网格，对标天财商龙 */
  const MORE_OPS: { key: string; label: string; icon: string; color?: string }[] = [
    // Row 1
    { key: '_add-item', label: '加单', icon: '+' },
    { key: 'checkout', label: '结算', icon: '$', color: C.green },
    { key: 'pre-bill', label: '埋单', icon: 'B' },
    { key: 'fire-kitchen', label: '起菜', icon: 'F', color: C.warning },
    { key: 'mark-served', label: '上菜', icon: 'S', color: C.green },
    // Row 2
    { key: 'sold-out-mgmt', label: '停菜', icon: 'X', color: C.danger },
    { key: 'price-override', label: '菜品变价', icon: 'P' },
    { key: '_weigh', label: '称重', icon: 'W' },
    { key: '_gift', label: '赠单', icon: 'G' },
    { key: '_return', label: '退单', icon: 'R', color: C.danger },
    // Row 3
    { key: '_rush', label: '催单', icon: '!' , color: C.warning },
    { key: 'edit-table', label: '修改开台', icon: 'E' },
    { key: 'item-transfer', label: '单品转台', icon: 'T' },
    { key: '_table-transfer', label: '换台', icon: 'H' },
    { key: '_close-table', label: '关台', icon: 'C' },
    // Row 4
    { key: 'verify-receipt', label: '核对单据', icon: 'V' },
    { key: 'print-receipt', label: '打印客单', icon: 'L' },
    { key: 'verify-coupon', label: '验证会员', icon: 'M' },
    { key: 'kitchen-msg', label: '后厨通知', icon: 'K', color: C.info },
    { key: 'pay-transfer', label: '转账', icon: 'Z' },
    // Row 5
    { key: '_merge', label: '并账', icon: 'J' },
    { key: 'sold-out-mgmt', label: '沽清管理', icon: 'Q' },
    { key: 'daily-limit', label: '限量设置', icon: 'D' },
    { key: 'change-waiter', label: '修改点菜员', icon: 'W' },
    { key: '_refresh', label: '刷新状态', icon: 'R' },
  ];

  const handleMoreOpsSelect = (key: string) => {
    // 快捷跳转类(前缀 _ 表示不走弹窗)
    if (key === '_add-item') { setActiveModal('none'); setShowCart(true); return; }
    if (key === '_table-transfer') { setActiveModal('none'); navigate('/table-ops'); return; }
    if (key === '_close-table') { setActiveModal('none'); navigate('/table-ops?action=close'); return; }
    if (key === '_merge') { setActiveModal('none'); navigate('/table-ops?action=merge'); return; }
    if (key === '_rush') { setActiveModal('none'); alert('已催单'); return; }
    if (key === '_weigh') { setActiveModal('none'); alert('请将菜品放上电子秤'); return; }
    if (key === '_gift') { setActiveModal('none'); alert('请在购物车中标记赠送'); return; }
    if (key === '_return') { setActiveModal('none'); navigate(`/return?order_id=${orderId}`); return; }
    if (key === '_refresh') {
      setActiveModal('none');
      if (refreshingDish) return;
      setRefreshingDish(true);
      const storeId = params.get('store_id') || '';
      txFetch<{ id: string; is_available: boolean }[]>(
        `/api/v1/dishes?store_id=${encodeURIComponent(storeId)}&status=available`,
      )
        .then(data => {
          // 将远端可用状态同步到本地
          const map: Record<string, boolean> = {};
          if (Array.isArray(data)) {
            data.forEach(d => { map[d.id] = d.is_available; });
          }
          setDishAvailability(prev => ({ ...prev, ...map }));
          toastOk('菜品状态已刷新');
        })
        .catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : '刷新失败';
          toastErr(`刷新失败: ${msg}`);
        })
        .finally(() => setRefreshingDish(false));
      return;
    }
    // 埋单加载数据
    if (key === 'pre-bill') {
      setPreBillData({
        items: cart.map(i => ({
          item_name: i.name, quantity: i.qty,
          unit_price_fen: i.priceFen,
          subtotal_fen: i.priceFen * i.qty * (i.weight || 1),
          is_gift: false,
        })),
        subtotal_fen: cartTotal, discount_fen: 0,
        service_charge_fen: 0, total_fen: cartTotal,
      });
    }
    // 后厨通知重置
    if (key === 'kitchen-msg') { setKitchenMsg(''); setKitchenMsgSent(false); }
    setActiveModal(key as ModalType);
  };

  /* 结账处理 */
  const handleCheckout = (_method: string) => {
    setCheckoutProcessing(true);
    setTimeout(() => {
      setCheckoutProcessing(false);
      setCheckoutDone(true);
    }, 1200);
  };

  /* 催菜 */
  const handleRushTask = (taskId: string) => {
    if (rushingTaskId) return;
    setRushingTaskId(taskId);
    txFetch(`/api/v1/orders/${encodeURIComponent(orderId)}/rush-items`, {
      method: 'POST',
      body: JSON.stringify({ item_ids: [taskId] }),
    })
      .then(() => {
        toastOk('已催菜，后厨收到加急通知');
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '催菜失败';
        toastErr(`催菜失败: ${msg}`);
      })
      .finally(() => setRushingTaskId(null));
  };

  const kdsStatusColor = (status: string, isOvertime: boolean) => {
    if (isOvertime) return C.danger;
    if (status === 'done') return C.green;
    if (status === 'cooking') return C.warning;
    return C.muted;
  };

  const kdsStatusText = (status: string, isOvertime: boolean) => {
    if (isOvertime) return '超时';
    if (status === 'done') return '已出餐';
    if (status === 'cooking') return '制作中';
    return '待制作';
  };

  /* 底部弹层通用遮罩 */
  const renderOverlay = (visible: boolean, onClose: () => void, children: React.ReactNode) => {
    if (!visible) return null;
    return (
      <div
        style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.6)', zIndex: 300,
          display: 'flex', alignItems: 'flex-end',
        }}
        onClick={onClose}
      >
        <div
          style={{
            width: '100%', background: C.bg, borderRadius: '16px 16px 0 0',
            padding: '20px 16px 32px', maxHeight: '80vh', overflowY: 'auto',
            WebkitOverflowScrolling: 'touch' as any,
          }}
          onClick={e => e.stopPropagation()}
        >
          {children}
        </div>
      </div>
    );
  };

  return (
    <div style={{ background: C.bg, minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ===== 顶部: 桌号信息 + 更多操作 + 出餐进度 + 结账 ===== */}
      <div style={{
        padding: '12px 16px', background: C.card,
        borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => navigate(-1)}
            style={{
              minWidth: 48, minHeight: 48, borderRadius: 12,
              background: C.card, border: `1px solid ${C.border}`,
              color: C.muted, fontSize: 16, cursor: 'pointer',
            }}
          >
            {'<'}
          </button>
          <div>
            <span style={{ fontSize: 20, fontWeight: 700, color: C.white }}>
              {tableNo ? `${tableNo} 桌` : '点菜'}
            </span>
            {guests && <span style={{ fontSize: 16, color: C.muted, marginLeft: 8 }}>{guests}人</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {/* 出餐进度按钮 */}
          <button
            onClick={() => setActiveModal('kds-status')}
            style={{
              minWidth: 48, minHeight: 48, borderRadius: 12,
              background: C.card, border: `1px solid ${C.border}`,
              color: C.green, fontSize: 16, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
            title="出餐进度"
          >
            KDS
          </button>
          {/* 结账按钮 */}
          <button
            onClick={() => setActiveModal('checkout')}
            style={{
              minWidth: 48, minHeight: 48, borderRadius: 12,
              background: C.green, border: 'none',
              color: C.white, fontSize: 16, fontWeight: 700, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            $$
          </button>
          {/* 更多操作按钮 */}
          <button
            onClick={() => setActiveModal('more-ops')}
            style={{
              minWidth: 48, minHeight: 48, borderRadius: 12,
              background: C.card, border: `1px solid ${C.border}`,
              color: C.text, fontSize: 20, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            ...
          </button>
        </div>
      </div>

      {/* ===== B. AI 智能推荐面板(可折叠) ===== */}
      <div style={{
        background: `${C.info}15`, borderBottom: `1px solid ${C.border}`,
      }}>
        <button
          onClick={() => setAiExpanded(!aiExpanded)}
          style={{
            width: '100%', padding: '10px 16px',
            background: 'transparent', border: 'none', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 700, color: C.info }}>
            AI 智能推荐
          </span>
          <span style={{ fontSize: 16, color: C.muted }}>
            {aiExpanded ? '收起' : '展开'}
          </span>
        </button>
        {aiExpanded && (
          <div style={{
            display: 'flex', gap: 10, overflowX: 'auto',
            WebkitOverflowScrolling: 'touch' as any,
            padding: '0 12px 12px',
          }}>
            {MOCK_AI_RECS.map(rec => (
              <button
                key={rec.id}
                onClick={() => addAIRecToCart(rec)}
                style={{
                  minWidth: 130, flexShrink: 0, padding: 12, borderRadius: 12,
                  background: C.card, border: `1px solid ${C.border}`,
                  cursor: 'pointer', textAlign: 'left',
                }}
              >
                <span style={{
                  display: 'inline-block', fontSize: 16, padding: '2px 6px',
                  borderRadius: 4, background: `${C.info}22`, color: C.info,
                  marginBottom: 6,
                }}>
                  {rec.tag}
                </span>
                <div style={{ fontSize: 16, fontWeight: 600, color: C.white, marginBottom: 4 }}>
                  {rec.name}
                </div>
                <div style={{ fontSize: 16, color: C.muted, marginBottom: 4 }}>
                  {rec.reason}
                </div>
                <div style={{ fontSize: 16, fontWeight: 700, color: C.accent }}>
                  {'\u00A5'}{(rec.priceFen / 100).toFixed(0)}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ===== 分类横向滚动 ===== */}
      <div style={{
        display: 'flex', gap: 0, overflowX: 'auto',
        WebkitOverflowScrolling: 'touch' as any,
        padding: '8px 12px', background: C.card,
        borderBottom: `1px solid ${C.border}`,
      }}>
        {/* 🐟 活鲜 — 特殊入口，navigate 到活鲜点单页 */}
        <button
          onClick={() => navigate(`/live-seafood?order_id=${encodeURIComponent(orderId)}&table=${encodeURIComponent(tableNo)}`)}
          style={{
            minWidth: 72, minHeight: 48, padding: '8px 14px',
            borderRadius: 8, border: 'none',
            background: `${C.accent}22`,
            color: C.accent,
            fontSize: 16, fontWeight: 700,
            cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
          }}
        >
          {'\uD83D\uDC1F'} 活鲜
        </button>
        {categories.map(cat => (
          <button
            key={cat.category_id}
            onClick={() => setActiveCat(cat.category_id)}
            style={{
              minWidth: 64, minHeight: 48, padding: '8px 14px',
              borderRadius: 8, border: 'none',
              background: activeCat === cat.category_id ? C.accent : 'transparent',
              color: activeCat === cat.category_id ? C.white : C.text,
              fontSize: 16, fontWeight: activeCat === cat.category_id ? 700 : 400,
              cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
            }}
          >
            {cat.category_name}
          </button>
        ))}
      </div>

      {/* ===== 菜品列表 ===== */}
      <div style={{
        flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as any,
        padding: '12px', paddingBottom: cart.length > 0 ? 140 : 80,
      }}>
        {menuLoading && (
          <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
            加载中...
          </div>
        )}
        {!menuLoading && dishes.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
            该分类暂无菜品
          </div>
        )}
        {dishes.map(dish => {
          const qty = cartItemQty(dish.dish_id);
          const tags = dish.tags || [];
          return (
            <button
              key={dish.dish_id}
              onClick={() => handleDishPress(dish)}
              disabled={dish.sold_out}
              style={{
                display: 'flex', alignItems: 'center', width: '100%',
                padding: 14, marginBottom: 8, borderRadius: 12,
                background: C.card, border: `1px solid ${C.border}`,
                cursor: dish.sold_out ? 'not-allowed' : 'pointer',
                opacity: dish.sold_out ? 0.4 : 1,
                textAlign: 'left', position: 'relative',
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 18, fontWeight: 600, color: C.white }}>{dish.dish_name}</span>
                  {dish.is_weighed && (
                    <span style={{
                      fontSize: 14, padding: '1px 6px', borderRadius: 4,
                      background: `${C.accent}22`, color: C.accent,
                      fontWeight: 700, letterSpacing: 0.5,
                    }}>
                      称重
                    </span>
                  )}
                  {tags.map(tag => (
                    <span key={tag} style={{
                      fontSize: 16, padding: '1px 6px', borderRadius: 4,
                      background: tag === '招牌' ? `${C.accent}22` : tag === '新品' ? `${C.green}22` : tag === '辣' ? `${C.danger}22` : `${C.warning}22`,
                      color: tag === '招牌' ? C.accent : tag === '新品' ? C.green : tag === '辣' ? '#ff4d4f' : C.warning,
                    }}>
                      {tag}
                    </span>
                  ))}
                  {dish.sold_out && (
                    <span style={{ fontSize: 16, color: C.danger, fontWeight: 700 }}>已沽清</span>
                  )}
                </div>
                <div style={{ fontSize: 16, color: C.accent, fontWeight: 700, marginTop: 4 }}>
                  {dish.is_market_price ? '时价' : `\u00A5${(dish.price_fen / 100).toFixed(0)}`}
                  {dish.is_weighed && <span style={{ fontSize: 16, color: C.muted, fontWeight: 400 }}>/斤</span>}
                </div>
              </div>
              {qty > 0 && (
                <span style={{
                  minWidth: 28, height: 28, borderRadius: 14,
                  background: C.accent, color: C.white,
                  fontSize: 16, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  marginLeft: 8,
                }}>
                  {qty}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* ===== 底部购物车栏 ===== */}
      {cartCount > 0 && (
        <div style={{
          position: 'fixed', bottom: 56, left: 0, right: 0,
          padding: '10px 16px', background: C.card,
          borderTop: `1px solid ${C.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          zIndex: 50,
        }}>
          <button
            onClick={() => setShowCart(!showCart)}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
            }}
          >
            <span style={{
              width: 48, height: 48, borderRadius: 24,
              background: C.accent, color: C.white,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 20, fontWeight: 700,
            }}>
              {cartCount}
            </span>
            <span style={{ fontSize: 20, fontWeight: 700, color: C.accent }}>
              {'\u00A5'}{(cartTotal / 100).toFixed(0)}
            </span>
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            style={{
              minHeight: 48, padding: '0 24px', borderRadius: 12,
              background: submitting ? C.muted : C.accent,
              color: C.white, border: 'none', fontSize: 18, fontWeight: 700,
              cursor: submitting ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? '提交中...' : '下单'}
          </button>
        </div>
      )}

      {/* ===== 购物车展开面板 ===== */}
      {showCart && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.6)', zIndex: 100,
          }}
          onClick={() => setShowCart(false)}
        >
          <div
            style={{
              position: 'absolute', bottom: 56 + 68, left: 0, right: 0,
              maxHeight: '60vh', overflowY: 'auto',
              WebkitOverflowScrolling: 'touch' as any,
              background: C.bg, borderRadius: '16px 16px 0 0',
              padding: '16px 12px',
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ fontSize: 18, fontWeight: 700, color: C.white }}>已选菜品</span>
              <button
                onClick={() => { setCart([]); setShowCart(false); }}
                style={{
                  minHeight: 48, padding: '8px 12px', borderRadius: 8,
                  background: 'transparent', border: `1px solid ${C.danger}`,
                  color: C.danger, fontSize: 16, cursor: 'pointer',
                }}
              >
                清空
              </button>
            </div>
            {cart.map((item, idx) => {
              // 称重菜：note 里含有 "xkg" 标记（由 WeighDishSheet 的 onConfirm 写入）
              const isWeighedItem = !!item.note && /[0-9.]+kg/.test(item.note);
              // 套餐项：note 里含有 " | " 分隔的选择记录（如"主菜: 清蒸鲈鱼 | 主食: 炒饭"）
              const isComboItem = !!item.note && item.note.includes(' | ');
              return (
                <div key={`${item.dishId}-${idx}`} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 0', borderBottom: `1px solid ${C.border}`,
                }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 16, color: C.white }}>
                      {item.name}
                      {isWeighedItem && (
                        <span style={{
                          fontSize: 14, color: C.muted,
                          marginLeft: 6, fontWeight: 400,
                        }}>
                          · {item.note}
                        </span>
                      )}
                    </div>
                    {/* 套餐选择明细 — 小字分行显示 */}
                    {isComboItem && (
                      <div style={{ fontSize: 14, color: C.muted, marginTop: 2, lineHeight: 1.6 }}>
                        {item.note.split(' | ').map((seg, si) => (
                          <span key={si} style={{ display: 'block' }}>
                            {seg}
                          </span>
                        ))}
                      </div>
                    )}
                    <div style={{ fontSize: 16, color: C.muted }}>
                      {isWeighedItem
                        ? /* 称重菜：显示总价 */
                          `\u00A5${(item.priceFen / 100).toFixed(2)}`
                        : isComboItem
                          ? /* 套餐：显示合计价 */
                            `套餐合计 \u00A5${(item.priceFen / 100).toFixed(2)}`
                          : /* 普通菜：显示单价 × 数量 */
                            `\u00A5${(item.priceFen / 100).toFixed(0)}${item.spec ? ` / ${item.spec}` : ''}${item.note && !isComboItem ? ` / ${item.note}` : ''}`
                      }
                    </div>
                  </div>
                  {/* 称重菜不显示 +/- 按钮，只显示删除 */}
                  {isWeighedItem ? (
                    <button
                      onClick={() => updateQty(idx, -item.qty)}
                      style={{
                        width: 48, height: 48, borderRadius: 12,
                        background: C.card, border: `1px solid ${C.border}`,
                        color: '#ef4444', fontSize: 18, cursor: 'pointer',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                      title="移除"
                    >
                      ✕
                    </button>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <button
                        onClick={() => updateQty(idx, -1)}
                        style={{
                          width: 48, height: 48, borderRadius: 12,
                          background: C.card, border: `1px solid ${C.border}`,
                          color: C.white, fontSize: 20, cursor: 'pointer',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}
                      >
                        -
                      </button>
                      <span style={{ fontSize: 20, fontWeight: 700, color: C.white, minWidth: 24, textAlign: 'center' }}>
                        {item.qty}
                      </span>
                      <button
                        onClick={() => updateQty(idx, 1)}
                        style={{
                          width: 48, height: 48, borderRadius: 12,
                          background: C.card, border: `1px solid ${C.border}`,
                          color: C.white, fontSize: 20, cursor: 'pointer',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}
                      >
                        +
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ===== 称重菜弹层 ===== */}
      {weighDish && (
        <WeighDishSheet
          dish={weighDish}
          onConfirm={(weightKg, totalFen) => {
            setCart(prev => [
              ...prev,
              {
                dishId: weighDish.dish_id,
                name: weighDish.dish_name,
                qty: 1,
                priceFen: totalFen,        // 存储的是总价（分）
                weight: undefined,
                spec: undefined,
                note: `${weightKg.toFixed(3)}kg`,
              },
            ]);
            setWeighDish(null);
            showToast(`已加入：${weighDish.dish_name} ${weightKg.toFixed(3)}kg ¥${(totalFen / 100).toFixed(2)}`, C.green, 2500);
          }}
          onClose={() => setWeighDish(null)}
        />
      )}

      {/* ===== 套餐N选M弹层 ===== */}
      {comboSheet && (
        <ComboSelectionSheet
          combo={comboSheet}
          onConfirm={(selections: ComboSelection[], totalFen: number) => {
            addToCart({
              dish_id: comboSheet.combo_id,
              dish_name: comboSheet.combo_name,
              quantity: 1,
              unit_price_fen: totalFen,
              special_notes: selections.map(s =>
                `${s.group_name}: ${s.selected_items.map(i => i.dish_name).join('/')}`
              ).join(' | '),
            });
            showToast(`已加入：${comboSheet.combo_name} ¥${(totalFen / 100).toFixed(2)}`, C.green, 2500);
            setComboSheet(null);
          }}
          onClose={() => setComboSheet(null)}
        />
      )}

      {/* ===== 特殊菜弹窗(时价/做法) ===== */}
      {editingDish && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.6)', zIndex: 200,
            display: 'flex', alignItems: 'flex-end',
          }}
          onClick={() => setEditingDish(null)}
        >
          <div
            style={{
              width: '100%', background: C.bg, borderRadius: '16px 16px 0 0',
              padding: '20px 16px 32px',
            }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
              {editingDish.dish_name}
            </h3>

            {editingDish.is_market_price && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
                  价格(元)
                </label>
                <input
                  type="number"
                  inputMode="decimal"
                  value={editPrice}
                  onChange={e => setEditPrice(e.target.value)}
                  placeholder="输入时价"
                  style={{
                    width: '100%', padding: 14, fontSize: 20, fontWeight: 700,
                    background: C.card, border: `1px solid ${C.border}`,
                    borderRadius: 12, color: C.accent,
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            )}

            {editingDish.is_weighed && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
                  重量(斤)
                </label>
                <input
                  type="number"
                  inputMode="decimal"
                  value={editWeight}
                  onChange={e => setEditWeight(e.target.value)}
                  placeholder="输入重量"
                  style={{
                    width: '100%', padding: 14, fontSize: 20, fontWeight: 700,
                    background: C.card, border: `1px solid ${C.border}`,
                    borderRadius: 12, color: C.white,
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            )}

            {(editingDish.specs || []).map(spec => (
              <div key={spec.spec_name} style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
                  {spec.spec_name}
                </label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {spec.options.map(opt => (
                    <button
                      key={opt}
                      onClick={() => setEditSpec(opt)}
                      style={{
                        minHeight: 48, padding: '10px 16px', borderRadius: 8,
                        background: editSpec === opt ? `${C.accent}22` : C.card,
                        border: editSpec === opt ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                        color: editSpec === opt ? C.accent : C.text,
                        fontSize: 16, cursor: 'pointer',
                      }}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              </div>
            ))}

            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
                备注
              </label>
              <input
                type="text"
                value={editNote}
                onChange={e => setEditNote(e.target.value)}
                placeholder="如: 少盐、不要香菜"
                style={{
                  width: '100%', padding: 14, fontSize: 16,
                  background: C.card, border: `1px solid ${C.border}`,
                  borderRadius: 12, color: C.white,
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <button
              onClick={confirmEditDish}
              style={{
                width: '100%', minHeight: 56, borderRadius: 12,
                background: C.accent, color: C.white, border: 'none',
                fontSize: 18, fontWeight: 700, cursor: 'pointer',
              }}
            >
              加入购物车
            </button>
          </div>
        </div>
      )}

      {/* ===== A. 更多操作弹出菜单(5x5网格，对标天财) ===== */}
      {renderOverlay(activeModal === 'more-ops', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 12px' }}>
            操作面板
          </h3>
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8,
          }}>
            {MORE_OPS.map((op, idx) => (
              <button
                key={`${op.key}-${idx}`}
                onClick={() => handleMoreOpsSelect(op.key)}
                style={{
                  minHeight: 56, padding: '8px 4px', borderRadius: 10,
                  background: C.card, border: `1px solid ${C.border}`,
                  cursor: 'pointer',
                  display: 'flex', flexDirection: 'column',
                  alignItems: 'center', justifyContent: 'center', gap: 4,
                }}
              >
                <span style={{
                  width: 32, height: 32, borderRadius: 8,
                  background: `${op.color || C.accent}22`,
                  color: op.color || C.accent,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 16, fontWeight: 700, flexShrink: 0,
                }}>
                  {op.icon}
                </span>
                <span style={{ fontSize: 16, fontWeight: 600, color: C.white, textAlign: 'center', lineHeight: '1.2' }}>
                  {op.label}
                </span>
              </button>
            ))}
          </div>
        </>
      ))}

      {/* ===== A1. 修改开台弹窗 ===== */}
      {renderOverlay(activeModal === 'edit-table', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            修改开台信息
          </h3>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
              就餐人数
            </label>
            <input
              type="number"
              inputMode="numeric"
              value={editGuestCount}
              onChange={e => setEditGuestCount(e.target.value)}
              placeholder="输入人数"
              style={{
                width: '100%', padding: 14, fontSize: 20, fontWeight: 700,
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 12, color: C.white, boxSizing: 'border-box',
              }}
            />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
              服务员ID (可选)
            </label>
            <input
              type="text"
              value={editWaiterId}
              onChange={e => setEditWaiterId(e.target.value)}
              placeholder="输入服务员工号"
              style={{
                width: '100%', padding: 14, fontSize: 16,
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 12, color: C.white, boxSizing: 'border-box',
              }}
            />
          </div>
          <button
            onClick={() => {
              if (updatingTable) return;
              setUpdatingTable(true);
              const body: Record<string, unknown> = {
                guest_count: parseInt(editGuestCount, 10) || 0,
              };
              if (editWaiterId.trim()) body.table_remark = editWaiterId.trim();
              txFetch(`/api/v1/orders/${encodeURIComponent(orderId)}`, {
                method: 'PATCH',
                body: JSON.stringify(body),
              })
                .then(() => {
                  setActiveModal('none');
                  toastOk(`开台信息已更新: ${editGuestCount}人`);
                })
                .catch((err: unknown) => {
                  const msg = err instanceof Error ? err.message : '更新失败';
                  toastErr(`更新失败: ${msg}`);
                })
                .finally(() => setUpdatingTable(false));
            }}
            disabled={updatingTable}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: updatingTable ? C.muted : C.accent, color: C.white, border: 'none',
              fontSize: 18, fontWeight: 700, cursor: updatingTable ? 'not-allowed' : 'pointer',
            }}
          >
            {updatingTable ? '保存中...' : '确认修改'}
          </button>
        </>
      ))}

      {/* ===== A2. 聚合验券弹窗 ===== */}
      {renderOverlay(activeModal === 'verify-coupon', () => { setActiveModal('none'); setCouponResult(null); }, (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            聚合验券
          </h3>
          <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
            支持美团、抖音、大众点评团购券核销
          </div>
          <div style={{ marginBottom: 16 }}>
            <input
              type="text"
              value={couponCode}
              onChange={e => setCouponCode(e.target.value)}
              placeholder="输入或扫描券码"
              style={{
                width: '100%', padding: 14, fontSize: 18,
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 12, color: C.white, boxSizing: 'border-box',
              }}
            />
          </div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <button
              onClick={() => {
                // TODO: 调用手机摄像头扫码
                alert('扫码功能需要安卓原生桥接');
              }}
              style={{
                flex: 1, minHeight: 56, borderRadius: 12,
                background: C.card, border: `1px solid ${C.border}`,
                color: C.text, fontSize: 16, cursor: 'pointer',
              }}
            >
              扫一扫
            </button>
            <button
              onClick={() => {
                if (!couponCode.trim() || verifyingCoupon) return;
                setVerifyingCoupon(true);
                // 平台从 couponCode 前缀猜测（实际可让服务员选择）
                const platform = couponCode.startsWith('MT') ? 'meituan'
                  : couponCode.startsWith('DY') ? 'douyin' : 'universal';
                txFetch<{ discount_fen: number; description: string }>(
                  '/api/v1/coupons/verify',
                  {
                    method: 'POST',
                    body: JSON.stringify({ code: couponCode.trim(), platform, order_id: orderId }),
                  },
                )
                  .then(data => {
                    const yuan = (data.discount_fen / 100).toFixed(0);
                    setCouponResult(`验券成功: ${data.description}，优惠 ¥${yuan}`);
                    toastOk(`券已核销，优惠 ¥${yuan}`);
                  })
                  .catch((err: unknown) => {
                    const msg = err instanceof Error ? err.message : '验券失败';
                    setCouponResult(null);
                    toastErr(`验券失败: ${msg}`);
                  })
                  .finally(() => setVerifyingCoupon(false));
              }}
              disabled={verifyingCoupon}
              style={{
                flex: 1, minHeight: 56, borderRadius: 12,
                background: verifyingCoupon ? C.muted : C.accent, color: C.white, border: 'none',
                fontSize: 16, fontWeight: 700, cursor: verifyingCoupon ? 'not-allowed' : 'pointer',
              }}
            >
              {verifyingCoupon ? '验证中...' : '验证'}
            </button>
          </div>
          {couponResult && (
            <div style={{
              padding: 14, borderRadius: 12,
              background: `${C.green}22`, border: `1px solid ${C.green}`,
            }}>
              <div style={{ fontSize: 16, color: C.green, fontWeight: 600 }}>{couponResult}</div>
            </div>
          )}
        </>
      ))}

      {/* ===== A3. 复制菜品弹窗 ===== */}
      {renderOverlay(activeModal === 'copy-dishes', () => { setActiveModal('none'); setHistoryOrders([]); setSourceOrderId(''); }, (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            复制菜品
          </h3>
          <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
            从同桌历史订单一键复制菜品到当前订单
          </div>

          {/* 第一步：查询历史订单 */}
          {historyOrders.length === 0 && (
            <button
              onClick={() => {
                if (copyingDishes) return;
                setCopyingDishes(true);
                txFetch<{ items: typeof historyOrders }>(
                  `/api/v1/orders?table_no=${encodeURIComponent(tableNo)}&status=active&limit=5`,
                )
                  .then(data => {
                    const orders = Array.isArray(data) ? data : (data as { items: typeof historyOrders }).items ?? [];
                    if (orders.length === 0) {
                      toastErr('未找到同桌历史订单');
                    } else {
                      setHistoryOrders(orders as typeof historyOrders);
                    }
                  })
                  .catch((err: unknown) => {
                    const msg = err instanceof Error ? err.message : '查询失败';
                    toastErr(`查询失败: ${msg}`);
                  })
                  .finally(() => setCopyingDishes(false));
              }}
              disabled={copyingDishes}
              style={{
                width: '100%', minHeight: 56, borderRadius: 12,
                background: copyingDishes ? C.muted : C.info, color: C.white, border: 'none',
                fontSize: 18, fontWeight: 700, cursor: copyingDishes ? 'not-allowed' : 'pointer',
                marginBottom: 12,
              }}
            >
              {copyingDishes ? '查询中...' : '查询同桌历史订单'}
            </button>
          )}

          {/* 第二步：选择订单并复制 */}
          {historyOrders.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {historyOrders.map(order => (
                <button
                  key={order.id}
                  onClick={() => {
                    if (copyingDishes) return;
                    setCopyingDishes(true);
                    // 将历史订单菜品加入购物车
                    const newItems: CartItem[] = order.items.map(i => ({
                      dishId: i.dish_id,
                      name: i.dish_name,
                      qty: i.qty,
                      priceFen: i.price_fen,
                      note: '',
                    }));
                    setCart(prev => {
                      const merged = [...prev];
                      newItems.forEach(ni => {
                        const exist = merged.find(x => x.dishId === ni.dishId && !x.spec);
                        if (exist) exist.qty += ni.qty;
                        else merged.push(ni);
                      });
                      return merged;
                    });
                    setCopyingDishes(false);
                    setHistoryOrders([]);
                    setSourceOrderId(order.id);
                    setActiveModal('none');
                    toastOk(`已复制 ${order.items.length} 道菜品到购物车`);
                  }}
                  style={{
                    padding: 14, borderRadius: 12,
                    background: C.card, border: `1px solid ${C.border}`,
                    cursor: 'pointer', textAlign: 'left',
                  }}
                >
                  <div style={{ fontSize: 16, fontWeight: 700, color: C.white, marginBottom: 4 }}>
                    订单 {order.id}
                  </div>
                  <div style={{ fontSize: 16, color: C.muted }}>
                    {order.items.map(i => `${i.dish_name}x${i.qty}`).join(' / ')}
                  </div>
                </button>
              ))}
              <button
                onClick={() => setHistoryOrders([])}
                style={{
                  minHeight: 48, borderRadius: 12,
                  background: 'transparent', border: `1px solid ${C.border}`,
                  color: C.muted, fontSize: 16, cursor: 'pointer',
                }}
              >
                重新查询
              </button>
            </div>
          )}
        </>
      ))}

      {/* ===== A5. 沽清管理弹窗 ===== */}
      {renderOverlay(activeModal === 'sold-out-mgmt', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            沽清管理
          </h3>
          <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
            点击切换菜品售罄/上架状态
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {dishes.map(dish => {
              const available = dishAvailability[dish.dish_id] ?? !dish.sold_out;
              return (
                <button
                  key={dish.dish_id}
                  disabled={togglingDishId === dish.dish_id}
                  onClick={() => {
                    if (togglingDishId) return;
                    const newVal = !dishAvailability[dish.dish_id];
                    // 乐观更新
                    setDishAvailability(prev => ({ ...prev, [dish.dish_id]: newVal }));
                    setTogglingDishId(dish.dish_id);
                    txFetch(`/api/v1/dishes/${encodeURIComponent(dish.dish_id)}/availability`, {
                      method: 'PATCH',
                      body: JSON.stringify({ is_available: newVal }),
                    })
                      .then(() => {
                        toastOk(newVal ? `${dish.dish_name} 已恢复在售` : `${dish.dish_name} 已沽清`);
                      })
                      .catch((err: unknown) => {
                        // 回滚
                        setDishAvailability(prev => ({ ...prev, [dish.dish_id]: !newVal }));
                        const msg = err instanceof Error ? err.message : '操作失败';
                        toastErr(`操作失败: ${msg}`);
                      })
                      .finally(() => setTogglingDishId(null));
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: 14, borderRadius: 12,
                    background: C.card, border: `1px solid ${C.border}`,
                    cursor: togglingDishId === dish.dish_id ? 'not-allowed' : 'pointer',
                    opacity: (available ? 1 : 0.5) * (togglingDishId === dish.dish_id ? 0.6 : 1),
                  }}
                >
                  <span style={{ fontSize: 16, color: C.white }}>{dish.dish_name}</span>
                  <span style={{
                    fontSize: 16, fontWeight: 700, padding: '4px 12px', borderRadius: 8,
                    background: available ? `${C.green}22` : `${C.danger}22`,
                    color: available ? C.green : C.danger,
                  }}>
                    {available ? '在售' : '已沽清'}
                  </span>
                </button>
              );
            })}
          </div>
        </>
      ))}

      {/* ===== A6. 限量设置弹窗 ===== */}
      {renderOverlay(activeModal === 'daily-limit', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            限量设置
          </h3>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
              选择菜品
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
              {dishes.filter(d => !d.sold_out).map(dish => (
                <button
                  key={dish.dish_id}
                  onClick={() => setLimitDishId(dish.dish_id)}
                  style={{
                    minHeight: 48, padding: '8px 14px', borderRadius: 8,
                    background: limitDishId === dish.dish_id ? `${C.accent}22` : C.card,
                    border: limitDishId === dish.dish_id ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                    color: limitDishId === dish.dish_id ? C.accent : C.text,
                    fontSize: 16, cursor: 'pointer',
                  }}
                >
                  {dish.dish_name}
                </button>
              ))}
            </div>
          </div>
          {limitDishId && (
            <>
              <div style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
                  每日限量数 (0=不限)
                </label>
                <input
                  type="number"
                  inputMode="numeric"
                  value={limitValue}
                  onChange={e => setLimitValue(e.target.value)}
                  placeholder="输入限量数"
                  style={{
                    width: '100%', padding: 14, fontSize: 20, fontWeight: 700,
                    background: C.card, border: `1px solid ${C.border}`,
                    borderRadius: 12, color: C.white, boxSizing: 'border-box',
                  }}
                />
              </div>
              <button
                onClick={() => {
                  if (settingLimit || !limitDishId) return;
                  const dailyLimit = parseInt(limitValue, 10) || 0;
                  setSettingLimit(true);
                  txFetch(`/api/v1/dishes/${encodeURIComponent(limitDishId)}/daily-limit`, {
                    method: 'PATCH',
                    body: JSON.stringify({ daily_limit: dailyLimit }),
                  })
                    .then(() => {
                      setActiveModal('none');
                      const dish = dishes.find(d => d.dish_id === limitDishId);
                      const label = dailyLimit === 0 ? '不限' : `${dailyLimit}份`;
                      toastOk(`${dish?.dish_name || limitDishId} 每日限量已设为 ${label}`);
                      setLimitDishId('');
                      setLimitValue('');
                    })
                    .catch((err: unknown) => {
                      const msg = err instanceof Error ? err.message : '设置失败';
                      toastErr(`设置失败: ${msg}`);
                    })
                    .finally(() => setSettingLimit(false));
                }}
                disabled={settingLimit}
                style={{
                  width: '100%', minHeight: 56, borderRadius: 12,
                  background: settingLimit ? C.muted : C.accent, color: C.white, border: 'none',
                  fontSize: 18, fontWeight: 700, cursor: settingLimit ? 'not-allowed' : 'pointer',
                }}
              >
                {settingLimit ? '保存中...' : '确认设置'}
              </button>
            </>
          )}
        </>
      ))}

      {/* ===== A7. 修改点菜员弹窗 ===== */}
      {renderOverlay(activeModal === 'change-waiter', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            修改点菜员
          </h3>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
              新服务员工号
            </label>
            <input
              type="text"
              value={newWaiterId}
              onChange={e => setNewWaiterId(e.target.value)}
              placeholder="输入服务员工号或姓名"
              style={{
                width: '100%', padding: 14, fontSize: 18,
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 12, color: C.white, boxSizing: 'border-box',
              }}
            />
          </div>
          <button
            onClick={() => {
              if (!newWaiterId.trim() || updatingWaiter) return;
              setUpdatingWaiter(true);
              txFetch(`/api/v1/orders/${encodeURIComponent(orderId)}/waiter`, {
                method: 'PATCH',
                body: JSON.stringify({ waiter_id: newWaiterId.trim(), waiter_name: newWaiterId.trim() }),
              })
                .then(() => {
                  setActiveModal('none');
                  toastOk(`点菜员已更换为: ${newWaiterId}`);
                  setNewWaiterId('');
                })
                .catch((err: unknown) => {
                  const msg = err instanceof Error ? err.message : '更新失败';
                  toastErr(`更新失败: ${msg}`);
                })
                .finally(() => setUpdatingWaiter(false));
            }}
            disabled={updatingWaiter}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: updatingWaiter ? C.muted : C.accent, color: C.white, border: 'none',
              fontSize: 18, fontWeight: 700, cursor: updatingWaiter ? 'not-allowed' : 'pointer',
            }}
          >
            {updatingWaiter ? '更新中...' : '确认更换'}
          </button>
        </>
      ))}

      {/* ===== C. 出餐进度追踪弹窗 ===== */}
      {renderOverlay(activeModal === 'kds-status', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            出餐进度
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {kdsItems.map(item => (
              <div
                key={item.taskId}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: 14, borderRadius: 12,
                  background: C.card,
                  borderLeft: `4px solid ${kdsStatusColor(item.status, item.isOvertime)}`,
                }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 18, fontWeight: 600, color: C.white }}>
                    {item.dishName} x{item.qty}
                  </div>
                  <div style={{
                    fontSize: 16, fontWeight: 700, marginTop: 4,
                    color: kdsStatusColor(item.status, item.isOvertime),
                  }}>
                    {kdsStatusText(item.status, item.isOvertime)}
                    {item.rushCount > 0 && (
                      <span style={{ marginLeft: 8, color: C.warning }}>
                        (已催{item.rushCount}次)
                      </span>
                    )}
                  </div>
                </div>
                {item.status !== 'done' && (
                  <button
                    onClick={() => handleRushTask(item.taskId)}
                    disabled={rushingTaskId === item.taskId}
                    style={{
                      minWidth: 64, minHeight: 48, borderRadius: 10,
                      background: rushingTaskId === item.taskId ? C.muted : item.isOvertime ? C.danger : `${C.warning}22`,
                      border: item.isOvertime ? 'none' : `1px solid ${C.warning}`,
                      color: item.isOvertime ? C.white : C.warning,
                      fontSize: 16, fontWeight: 700,
                      cursor: rushingTaskId === item.taskId ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {rushingTaskId === item.taskId ? '催...' : '催菜'}
                  </button>
                )}
              </div>
            ))}
          </div>
          <div style={{
            marginTop: 16, padding: 12, borderRadius: 12,
            background: `${C.info}15`, textAlign: 'center',
          }}>
            <span style={{ fontSize: 16, color: C.info }}>
              已出 {kdsItems.filter(i => i.status === 'done').length} / {kdsItems.length} 道
            </span>
          </div>
        </>
      ))}

      {/* ===== Toast 通知层 ===== */}
      <div style={{
        position: 'fixed', top: 16, left: '50%', transform: 'translateX(-50%)',
        zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8,
        pointerEvents: 'none', minWidth: 240, maxWidth: '90vw',
      }}>
        {toasts.map(t => (
          <div
            key={t.id}
            style={{
              padding: '12px 20px', borderRadius: 12,
              background: t.color === C.green ? '#14532d' : '#450a0a',
              border: `1px solid ${t.color}`,
              color: t.color, fontSize: 16, fontWeight: 600,
              textAlign: 'center', boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
            }}
          >
            {t.text}
          </div>
        ))}
      </div>

      {/* ===== D. 快捷结账弹窗 ===== */}
      {renderOverlay(activeModal === 'checkout', () => { if (!checkoutProcessing) { setActiveModal('none'); setCheckoutDone(false); } }, (
        <>
          {!checkoutDone ? (
            <>
              <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
                快捷结账
              </h3>
              {/* 金额信息 */}
              <div style={{
                padding: 20, borderRadius: 12, background: C.card,
                marginBottom: 16, textAlign: 'center',
              }}>
                <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>应收金额</div>
                <div style={{ fontSize: 36, fontWeight: 700, color: C.accent }}>
                  {'\u00A5'}{(cartTotal / 100).toFixed(2)}
                </div>
                {cartCount > 0 && (
                  <div style={{ fontSize: 16, color: C.muted, marginTop: 4 }}>
                    共 {cartCount} 件菜品
                  </div>
                )}
              </div>

              {/* 支付方式 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
                <button
                  onClick={() => handleCheckout('scan_qr')}
                  disabled={checkoutProcessing}
                  style={{
                    minHeight: 72, borderRadius: 12,
                    background: '#07C160', border: 'none',
                    color: C.white, fontSize: 18, fontWeight: 700,
                    cursor: checkoutProcessing ? 'not-allowed' : 'pointer',
                    opacity: checkoutProcessing ? 0.6 : 1,
                  }}
                >
                  扫码支付
                </button>
                <button
                  onClick={() => handleCheckout('cash')}
                  disabled={checkoutProcessing}
                  style={{
                    minHeight: 72, borderRadius: 12,
                    background: C.accent, border: 'none',
                    color: C.white, fontSize: 18, fontWeight: 700,
                    cursor: checkoutProcessing ? 'not-allowed' : 'pointer',
                    opacity: checkoutProcessing ? 0.6 : 1,
                  }}
                >
                  现金
                </button>
                <button
                  onClick={() => handleCheckout('card')}
                  disabled={checkoutProcessing}
                  style={{
                    minHeight: 72, borderRadius: 12,
                    background: C.info, border: 'none',
                    color: C.white, fontSize: 18, fontWeight: 700,
                    cursor: checkoutProcessing ? 'not-allowed' : 'pointer',
                    opacity: checkoutProcessing ? 0.6 : 1,
                  }}
                >
                  银联刷卡
                </button>
                <button
                  onClick={() => handleCheckout('credit')}
                  disabled={checkoutProcessing}
                  style={{
                    minHeight: 72, borderRadius: 12,
                    background: C.card, border: `1px solid ${C.border}`,
                    color: C.text, fontSize: 18, fontWeight: 700,
                    cursor: checkoutProcessing ? 'not-allowed' : 'pointer',
                    opacity: checkoutProcessing ? 0.6 : 1,
                  }}
                >
                  企业挂账
                </button>
              </div>

              {checkoutProcessing && (
                <div style={{ textAlign: 'center', padding: 20 }}>
                  <div style={{ fontSize: 18, color: C.muted }}>处理中...</div>
                </div>
              )}
            </>
          ) : (
            /* 结账成功 */
            <div style={{ textAlign: 'center', padding: 20 }}>
              <div style={{
                width: 64, height: 64, borderRadius: 32,
                background: `${C.green}22`, color: C.green,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 32, fontWeight: 700, margin: '0 auto 16px',
              }}>
                OK
              </div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.green, marginBottom: 8 }}>
                结账成功
              </div>
              <div style={{ fontSize: 24, fontWeight: 700, color: C.white, marginBottom: 4 }}>
                {'\u00A5'}{(cartTotal / 100).toFixed(2)}
              </div>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 20 }}>
                {tableNo ? `${tableNo} 桌` : ''} {guests ? `${guests}人` : ''}
              </div>
              <button
                onClick={() => {
                  setActiveModal('none');
                  setCheckoutDone(false);
                  setCart([]);
                  navigate('/active');
                }}
                style={{
                  width: '100%', minHeight: 56, borderRadius: 12,
                  background: C.accent, color: C.white, border: 'none',
                  fontSize: 18, fontWeight: 700, cursor: 'pointer',
                }}
              >
                返回
              </button>
            </div>
          )}
        </>
      ))}
    </div>
  );
}
