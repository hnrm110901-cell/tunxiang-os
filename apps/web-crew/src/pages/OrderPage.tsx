/**
 * 点菜页面（核心） — 分类导航 + AI推荐 + 菜品列表 + 购物车 + 更多操作 + 出餐追踪 + 快捷结账
 * 对标: 天财商龙移动收银台 + Toast Go 2 + Square KDS Mobile + AI Agent 增强
 *
 * 支持: 加菜/退菜/改数量/时价菜输入价格/称重菜输入重量/备注做法
 *       + 8个快捷操作 + AI推荐 + 出餐进度 + 扫码结账
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useMemo, useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

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

/* ---------- Mock 数据 ---------- */
const CATEGORIES = [
  { id: 'hot', name: '热菜' },
  { id: 'cold', name: '凉菜' },
  { id: 'soup', name: '汤品' },
  { id: 'seafood', name: '海鲜' },
  { id: 'staple', name: '主食' },
  { id: 'drink', name: '饮品' },
  { id: 'dessert', name: '甜品' },
];

interface MockDish {
  id: string;
  name: string;
  catId: string;
  priceFen: number;
  tags: string[];
  soldOut: boolean;
  isMarketPrice: boolean;
  isWeighed: boolean;
  specs: { name: string; options: string[] }[];
}

const DISHES: MockDish[] = [
  { id: 'd1', name: '剁椒鱼头', catId: 'hot', priceFen: 8800, tags: ['招牌', '辣'], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [{ name: '做法', options: ['红剁椒', '黄剁椒', '双色'] }] },
  { id: 'd2', name: '小炒黄牛肉', catId: 'hot', priceFen: 6800, tags: ['辣'], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [{ name: '辣度', options: ['微辣', '中辣', '特辣'] }] },
  { id: 'd3', name: '红烧肉', catId: 'hot', priceFen: 5800, tags: ['招牌'], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd4', name: '酸菜鱼', catId: 'hot', priceFen: 7800, tags: [], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [{ name: '鱼种', options: ['草鱼', '黑鱼'] }] },
  { id: 'd5', name: '蒜蓉蒸虾', catId: 'seafood', priceFen: 12800, tags: ['新品'], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd6', name: '波士顿龙虾', catId: 'seafood', priceFen: 0, tags: ['时价'], soldOut: false, isMarketPrice: true, isWeighed: true, specs: [{ name: '做法', options: ['蒜蓉蒸', '芝士焗', '上汤'] }] },
  { id: 'd7', name: '凉拌黄瓜', catId: 'cold', priceFen: 1800, tags: [], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd8', name: '口味虾', catId: 'hot', priceFen: 12800, tags: ['招牌', '辣'], soldOut: true, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd9', name: '老鸭汤', catId: 'soup', priceFen: 4800, tags: [], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd10', name: '米饭', catId: 'staple', priceFen: 300, tags: [], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd11', name: '酸梅汤', catId: 'drink', priceFen: 800, tags: [], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd12', name: '杨枝甘露', catId: 'dessert', priceFen: 2800, tags: ['新品'], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] },
  { id: 'd13', name: '活鱼(称重)', catId: 'seafood', priceFen: 9800, tags: ['称重'], soldOut: false, isMarketPrice: false, isWeighed: true, specs: [{ name: '做法', options: ['清蒸', '红烧', '水煮'] }] },
];

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
  | 'checkout';       // 快捷结账

/* ---------- 组件 ---------- */
export function OrderPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const tableNo = params.get('table') || '';
  const guests = params.get('guests') || '';
  const orderId = params.get('order_id') || 'mock-order-001';

  const [activeCat, setActiveCat] = useState(CATEGORIES[0].id);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [showCart, setShowCart] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 弹窗: 时价/称重/做法
  const [editingDish, setEditingDish] = useState<MockDish | null>(null);
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

  // 复制菜品
  const [sourceOrderId, setSourceOrderId] = useState('');

  // 沽清管理 (mock)
  const [dishAvailability, setDishAvailability] = useState<Record<string, boolean>>(() => {
    const map: Record<string, boolean> = {};
    DISHES.forEach(d => { map[d.id] = !d.soldOut; });
    return map;
  });

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

  const filteredDishes = useMemo(
    () => DISHES.filter(d => d.catId === activeCat),
    [activeCat],
  );

  const cartTotal = cart.reduce((sum, item) => {
    const weight = item.weight || 1;
    return sum + item.priceFen * item.qty * weight;
  }, 0);

  const cartCount = cart.reduce((sum, i) => sum + i.qty, 0);

  /* 添加到购物车（普通菜直接加，特殊菜弹窗） */
  const handleDishPress = (dish: MockDish) => {
    if (dish.soldOut) return;
    if (dish.isMarketPrice || dish.isWeighed || dish.specs.length > 0) {
      setEditingDish(dish);
      setEditPrice(dish.isMarketPrice ? '' : String(dish.priceFen / 100));
      setEditWeight(dish.isWeighed ? '' : '1');
      setEditSpec(dish.specs.length > 0 ? dish.specs[0].options[0] : '');
      setEditNote('');
      return;
    }
    addToCartSimple(dish);
  };

  const addToCartSimple = (dish: MockDish) => {
    setCart(prev => {
      const existing = prev.find(i => i.dishId === dish.id && !i.spec);
      if (existing) {
        return prev.map(i => i.dishId === dish.id && !i.spec ? { ...i, qty: i.qty + 1 } : i);
      }
      return [...prev, { dishId: dish.id, name: dish.name, qty: 1, priceFen: dish.priceFen, note: '' }];
    });
  };

  const confirmEditDish = () => {
    if (!editingDish) return;
    const priceFen = editingDish.isMarketPrice
      ? Math.round(parseFloat(editPrice || '0') * 100)
      : editingDish.priceFen;
    const weight = editingDish.isWeighed ? parseFloat(editWeight || '1') : undefined;

    setCart(prev => [
      ...prev,
      {
        dishId: editingDish.id,
        name: editingDish.name,
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
    setTimeout(() => {
      setSubmitting(false);
      setCart([]);
      setShowCart(false);
      navigate('/active');
    }, 800);
  };

  const cartItemQty = (dishId: string): number =>
    cart.filter(i => i.dishId === dishId).reduce((s, i) => s + i.qty, 0);

  /* AI推荐: 一键加入 */
  const addAIRecToCart = useCallback((rec: typeof MOCK_AI_RECS[0]) => {
    const dish = DISHES.find(d => d.id === rec.id);
    if (dish) handleDishPress(dish);
    else addToCartSimple({ id: rec.id, name: rec.name, catId: '', priceFen: rec.priceFen, tags: [], soldOut: false, isMarketPrice: false, isWeighed: false, specs: [] });
  }, []);

  /* 更多操作菜单项 */
  const MORE_OPS = [
    { key: 'edit-table' as ModalType, label: '修改开台', desc: '修改人数/服务员', icon: 'E' },
    { key: 'verify-coupon' as ModalType, label: '聚合验券', desc: '美团/抖音/点评', icon: 'V' },
    { key: 'copy-dishes' as ModalType, label: '复制菜品', desc: '从历史订单复制', icon: 'C' },
    { key: 'transfer' as ModalType, label: '换台', desc: '当前桌转移', icon: 'T' },
    { key: 'sold-out-mgmt' as ModalType, label: '沽清管理', desc: '标记售罄/恢复', icon: 'S' },
    { key: 'daily-limit' as ModalType, label: '限量设置', desc: '每日限量配置', icon: 'L' },
    { key: 'change-waiter' as ModalType, label: '修改点菜员', desc: '更换服务员', icon: 'W' },
    { key: 'refresh' as ModalType, label: '刷新状态', desc: '同步沽清/限量', icon: 'R' },
  ];

  const handleMoreOpsSelect = (key: ModalType | string) => {
    if (key === 'transfer') {
      setActiveModal('none');
      navigate('/table-ops');
      return;
    }
    if (key === 'refresh') {
      setActiveModal('none');
      // TODO: 实际调用 refreshDishStatus API
      alert('菜品状态已刷新');
      return;
    }
    setActiveModal(key as ModalType);
  };

  /* 结账处理 */
  const handleCheckout = (method: string) => {
    setCheckoutProcessing(true);
    setTimeout(() => {
      setCheckoutProcessing(false);
      setCheckoutDone(true);
    }, 1200);
  };

  /* 催菜 */
  const handleRushTask = (taskId: string) => {
    // TODO: 调用 rushKdsTask API
    alert(`已催菜: ${taskId}`);
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
            WebkitOverflowScrolling: 'touch' as string,
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
            WebkitOverflowScrolling: 'touch',
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
        WebkitOverflowScrolling: 'touch',
        padding: '8px 12px', background: C.card,
        borderBottom: `1px solid ${C.border}`,
      }}>
        {CATEGORIES.map(cat => (
          <button
            key={cat.id}
            onClick={() => setActiveCat(cat.id)}
            style={{
              minWidth: 64, minHeight: 48, padding: '8px 14px',
              borderRadius: 8, border: 'none',
              background: activeCat === cat.id ? C.accent : 'transparent',
              color: activeCat === cat.id ? C.white : C.text,
              fontSize: 16, fontWeight: activeCat === cat.id ? 700 : 400,
              cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
            }}
          >
            {cat.name}
          </button>
        ))}
      </div>

      {/* ===== 菜品列表 ===== */}
      <div style={{
        flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as string,
        padding: '12px', paddingBottom: cart.length > 0 ? 140 : 80,
      }}>
        {filteredDishes.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
            该分类暂无菜品
          </div>
        )}
        {filteredDishes.map(dish => {
          const qty = cartItemQty(dish.id);
          return (
            <button
              key={dish.id}
              onClick={() => handleDishPress(dish)}
              disabled={dish.soldOut}
              style={{
                display: 'flex', alignItems: 'center', width: '100%',
                padding: 14, marginBottom: 8, borderRadius: 12,
                background: C.card, border: `1px solid ${C.border}`,
                cursor: dish.soldOut ? 'not-allowed' : 'pointer',
                opacity: dish.soldOut ? 0.4 : 1,
                textAlign: 'left', position: 'relative',
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 18, fontWeight: 600, color: C.white }}>{dish.name}</span>
                  {dish.tags.map(tag => (
                    <span key={tag} style={{
                      fontSize: 16, padding: '1px 6px', borderRadius: 4,
                      background: tag === '招牌' ? `${C.accent}22` : tag === '新品' ? `${C.green}22` : tag === '辣' ? `${C.danger}22` : `${C.warning}22`,
                      color: tag === '招牌' ? C.accent : tag === '新品' ? C.green : tag === '辣' ? '#ff4d4f' : C.warning,
                    }}>
                      {tag}
                    </span>
                  ))}
                  {dish.soldOut && (
                    <span style={{ fontSize: 16, color: C.danger, fontWeight: 700 }}>已沽清</span>
                  )}
                </div>
                <div style={{ fontSize: 16, color: C.accent, fontWeight: 700, marginTop: 4 }}>
                  {dish.isMarketPrice ? '时价' : `\u00A5${(dish.priceFen / 100).toFixed(0)}`}
                  {dish.isWeighed && <span style={{ fontSize: 16, color: C.muted, fontWeight: 400 }}>/斤</span>}
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
              WebkitOverflowScrolling: 'touch' as string,
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
            {cart.map((item, idx) => (
              <div key={`${item.dishId}-${idx}`} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '12px 0', borderBottom: `1px solid ${C.border}`,
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 16, color: C.white }}>{item.name}</div>
                  <div style={{ fontSize: 16, color: C.muted }}>
                    {'\u00A5'}{(item.priceFen / 100).toFixed(0)}
                    {item.weight ? ` \u00D7 ${item.weight}斤` : ''}
                    {item.spec ? ` / ${item.spec}` : ''}
                    {item.note ? ` / ${item.note}` : ''}
                  </div>
                </div>
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
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ===== 特殊菜弹窗(时价/称重/做法) ===== */}
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
              {editingDish.name}
            </h3>

            {editingDish.isMarketPrice && (
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

            {editingDish.isWeighed && (
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

            {editingDish.specs.map(spec => (
              <div key={spec.name} style={{ marginBottom: 16 }}>
                <label style={{ fontSize: 16, color: C.text, display: 'block', marginBottom: 8 }}>
                  {spec.name}
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

      {/* ===== A. 更多操作弹出菜单(8个快捷操作) ===== */}
      {renderOverlay(activeModal === 'more-ops', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            更多操作
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {MORE_OPS.map(op => (
              <button
                key={op.key}
                onClick={() => handleMoreOpsSelect(op.key)}
                style={{
                  minHeight: 72, padding: 14, borderRadius: 12,
                  background: C.card, border: `1px solid ${C.border}`,
                  cursor: 'pointer', textAlign: 'left',
                  display: 'flex', alignItems: 'center', gap: 12,
                }}
              >
                <span style={{
                  width: 44, height: 44, borderRadius: 10,
                  background: `${C.accent}22`, color: C.accent,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 18, fontWeight: 700, flexShrink: 0,
                }}>
                  {op.icon}
                </span>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 600, color: C.white }}>{op.label}</div>
                  <div style={{ fontSize: 16, color: C.muted }}>{op.desc}</div>
                </div>
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
              // TODO: 调用 updateTableInfo API
              setActiveModal('none');
              alert(`已修改: 人数=${editGuestCount}, 服务员=${editWaiterId || '未变'}`);
            }}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: C.accent, color: C.white, border: 'none',
              fontSize: 18, fontWeight: 700, cursor: 'pointer',
            }}
          >
            确认修改
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
                if (!couponCode.trim()) return;
                // TODO: 调用 verifyPlatformCoupon API
                setCouponResult('验券成功: 美团50元代100元券, 优惠50元');
              }}
              style={{
                flex: 1, minHeight: 56, borderRadius: 12,
                background: C.accent, color: C.white, border: 'none',
                fontSize: 16, fontWeight: 700, cursor: 'pointer',
              }}
            >
              验证
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
      {renderOverlay(activeModal === 'copy-dishes', () => setActiveModal('none'), (
        <>
          <h3 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
            复制菜品
          </h3>
          <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
            从历史订单一键复制菜品到当前订单
          </div>
          <div style={{ marginBottom: 16 }}>
            <input
              type="text"
              value={sourceOrderId}
              onChange={e => setSourceOrderId(e.target.value)}
              placeholder="输入源订单号"
              style={{
                width: '100%', padding: 14, fontSize: 18,
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 12, color: C.white, boxSizing: 'border-box',
              }}
            />
          </div>
          <button
            onClick={() => {
              if (!sourceOrderId.trim()) return;
              // TODO: 调用 copyDishesFromOrder API
              setActiveModal('none');
              alert(`已从订单 ${sourceOrderId} 复制菜品`);
            }}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: C.accent, color: C.white, border: 'none',
              fontSize: 18, fontWeight: 700, cursor: 'pointer',
            }}
          >
            复制到当前订单
          </button>
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
            {DISHES.map(dish => {
              const available = dishAvailability[dish.id] ?? true;
              return (
                <button
                  key={dish.id}
                  onClick={() => {
                    setDishAvailability(prev => ({ ...prev, [dish.id]: !prev[dish.id] }));
                    // TODO: 调用 setDishAvailability API
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: 14, borderRadius: 12,
                    background: C.card, border: `1px solid ${C.border}`,
                    cursor: 'pointer', opacity: available ? 1 : 0.5,
                  }}
                >
                  <span style={{ fontSize: 16, color: C.white }}>{dish.name}</span>
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
              {DISHES.filter(d => !d.soldOut).map(dish => (
                <button
                  key={dish.id}
                  onClick={() => setLimitDishId(dish.id)}
                  style={{
                    minHeight: 48, padding: '8px 14px', borderRadius: 8,
                    background: limitDishId === dish.id ? `${C.accent}22` : C.card,
                    border: limitDishId === dish.id ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                    color: limitDishId === dish.id ? C.accent : C.text,
                    fontSize: 16, cursor: 'pointer',
                  }}
                >
                  {dish.name}
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
                  // TODO: 调用 setDishDailyLimit API
                  setActiveModal('none');
                  const dish = DISHES.find(d => d.id === limitDishId);
                  alert(`${dish?.name || limitDishId} 每日限量设为 ${limitValue || '不限'}`);
                }}
                style={{
                  width: '100%', minHeight: 56, borderRadius: 12,
                  background: C.accent, color: C.white, border: 'none',
                  fontSize: 18, fontWeight: 700, cursor: 'pointer',
                }}
              >
                确认设置
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
              if (!newWaiterId.trim()) return;
              // TODO: 调用 updateOrderWaiter API
              setActiveModal('none');
              alert(`点菜员已更换为: ${newWaiterId}`);
            }}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: C.accent, color: C.white, border: 'none',
              fontSize: 18, fontWeight: 700, cursor: 'pointer',
            }}
          >
            确认更换
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
                    style={{
                      minWidth: 64, minHeight: 48, borderRadius: 10,
                      background: item.isOvertime ? C.danger : `${C.warning}22`,
                      border: item.isOvertime ? 'none' : `1px solid ${C.warning}`,
                      color: item.isOvertime ? C.white : C.warning,
                      fontSize: 16, fontWeight: 700, cursor: 'pointer',
                    }}
                  >
                    催菜
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
