/**
 * 茶饮模板 — 选规格+加料+甜度+温度
 *
 * 流程：菜单浏览 → 点击饮品 → 弹出定制面板 → 确认加入购物车
 * 特色：多维度规格选择（必选+可选）、加料多选、底部定制弹层
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchCategories, fetchDishes } from '@/api/menuApi';
import type { Category, DishItem } from '@/api/menuApi';
import CartBar from '@/components/CartBar';

// ─── 茶饮专用类型 ─────────────────────────────────────────────────────────────

interface TeaSpecGroup {
  groupName: string;
  required: boolean;
  options: TeaSpecOption[];
}

interface TeaSpecOption {
  id: string;
  label: string;
  priceAdjust: number;  // 加价（元）
  default?: boolean;
}

interface TeaCustomState {
  dish: DishItem;
  selections: Record<string, string>;  // groupName -> selected option id
  toppings: string[];                   // 加料 option ids
  quantity: number;
}

// ─── 茶饮规格模板 ─────────────────────────────────────────────────────────────

const TEA_SPEC_GROUPS: TeaSpecGroup[] = [
  {
    groupName: '杯型',
    required: true,
    options: [
      { id: 'size-m', label: '中杯', priceAdjust: 0, default: true },
      { id: 'size-l', label: '大杯', priceAdjust: 3 },
      { id: 'size-xl', label: '超大杯', priceAdjust: 5 },
    ],
  },
  {
    groupName: '甜度',
    required: true,
    options: [
      { id: 'sugar-100', label: '全糖', priceAdjust: 0 },
      { id: 'sugar-70', label: '七分糖', priceAdjust: 0, default: true },
      { id: 'sugar-50', label: '半糖', priceAdjust: 0 },
      { id: 'sugar-30', label: '三分糖', priceAdjust: 0 },
      { id: 'sugar-0', label: '无糖', priceAdjust: 0 },
    ],
  },
  {
    groupName: '温度',
    required: true,
    options: [
      { id: 'temp-ice', label: '冰', priceAdjust: 0, default: true },
      { id: 'temp-less-ice', label: '少冰', priceAdjust: 0 },
      { id: 'temp-room', label: '常温', priceAdjust: 0 },
      { id: 'temp-warm', label: '温热', priceAdjust: 0 },
      { id: 'temp-hot', label: '热', priceAdjust: 0 },
    ],
  },
];

const TEA_TOPPINGS: TeaSpecGroup = {
  groupName: '加料',
  required: false,
  options: [
    { id: 'top-pearl', label: '珍珠', priceAdjust: 2 },
    { id: 'top-coconut', label: '椰果', priceAdjust: 2 },
    { id: 'top-pudding', label: '布丁', priceAdjust: 3 },
    { id: 'top-taro', label: '芋圆', priceAdjust: 3 },
    { id: 'top-aloe', label: '芦荟', priceAdjust: 2 },
    { id: 'top-red-bean', label: '红豆', priceAdjust: 2 },
    { id: 'top-cheese', label: '芝士奶盖', priceAdjust: 5 },
    { id: 'top-shot', label: '浓缩咖啡', priceAdjust: 4 },
  ],
};

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export default function TeaTemplate() {
  const navigate = useNavigate();
  const storeId = useOrderStore((s) => s.storeId);
  const storeName = useOrderStore((s) => s.storeName);
  const tableNo = useOrderStore((s) => s.tableNo);
  const cart = useOrderStore((s) => s.cart);
  const addToCart = useOrderStore((s) => s.addToCart);
  const cartCount = useOrderStore((s) => s.cartCount);
  const cartTotal = useOrderStore((s) => s.cartTotal);

  const [categories, setCategories] = useState<Category[]>([]);
  const [activeCat, setActiveCat] = useState('');
  const [dishes, setDishes] = useState<DishItem[]>([]);
  const [customizing, setCustomizing] = useState<TeaCustomState | null>(null);

  useEffect(() => {
    if (!storeId) { navigate('/'); return; }
    fetchCategories(storeId).then((cats) => {
      setCategories(cats);
      if (cats.length > 0) setActiveCat(cats[0].id);
    }).catch(() => { /* fallback */ });
    fetchDishes(storeId).then(setDishes).catch(() => { /* fallback */ });
  }, [storeId, navigate]);

  const getQuantity = useCallback(
    (dishId: string) => cart.filter((c) => c.dish.id === dishId).reduce((sum, c) => sum + c.quantity, 0),
    [cart],
  );

  const displayDishes = useMemo(
    () => dishes.filter((d) => !activeCat || d.categoryId === activeCat),
    [dishes, activeCat],
  );

  // ── 打开定制面板 ──

  const openCustomizer = useCallback((dish: DishItem) => {
    // 初始化默认选项
    const defaults: Record<string, string> = {};
    for (const group of TEA_SPEC_GROUPS) {
      const def = group.options.find((o) => o.default);
      if (def) defaults[group.groupName] = def.id;
      else if (group.options.length > 0) defaults[group.groupName] = group.options[0].id;
    }
    setCustomizing({ dish, selections: defaults, toppings: [], quantity: 1 });
  }, []);

  // ── 计算定制后价格 ──

  const customPrice = useMemo(() => {
    if (!customizing) return 0;
    let price = customizing.dish.price;
    // 规格加价
    for (const group of TEA_SPEC_GROUPS) {
      const selectedId = customizing.selections[group.groupName];
      const opt = group.options.find((o) => o.id === selectedId);
      if (opt) price += opt.priceAdjust;
    }
    // 加料加价
    for (const toppingId of customizing.toppings) {
      const opt = TEA_TOPPINGS.options.find((o) => o.id === toppingId);
      if (opt) price += opt.priceAdjust;
    }
    return price * customizing.quantity;
  }, [customizing]);

  // ── 确认加入购物车 ──

  const handleConfirmCustom = useCallback(() => {
    if (!customizing) return;
    // 将规格选择转换为 CustomOption 格式
    const customSelections: Record<string, string[]> = {};
    for (const [groupName, optId] of Object.entries(customizing.selections)) {
      customSelections[groupName] = [optId];
    }
    if (customizing.toppings.length > 0) {
      customSelections['加料'] = customizing.toppings;
    }
    addToCart(customizing.dish, customizing.quantity, customSelections);
    setCustomizing(null);
  }, [customizing, addToCart]);

  // ── 切换加料 ──

  const toggleTopping = useCallback((toppingId: string) => {
    if (!customizing) return;
    setCustomizing((prev) => {
      if (!prev) return prev;
      const has = prev.toppings.includes(toppingId);
      return {
        ...prev,
        toppings: has
          ? prev.toppings.filter((t) => t !== toppingId)
          : [...prev.toppings, toppingId],
      };
    });
  }, [customizing]);

  // ── 选择规格 ──

  const selectSpec = useCallback((groupName: string, optionId: string) => {
    setCustomizing((prev) => {
      if (!prev) return prev;
      return { ...prev, selections: { ...prev.selections, [groupName]: optionId } };
    });
  }, []);

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--tx-bg-primary, #fff)' }}>
      {/* ── 顶部 ── */}
      <div className="px-4 pt-3 pb-2 flex-shrink-0">
        <div className="flex justify-between items-center mb-2">
          <div>
            <div className="text-lg font-bold" style={{ color: 'var(--tx-text-primary, #2C2C2A)' }}>
              {storeName}
            </div>
            <div className="text-xs mt-0.5" style={{ color: 'var(--tx-text-tertiary, #B4B2A9)' }}>
              {tableNo ? `${tableNo} 号桌` : '自取'}
            </div>
          </div>
          <button
            className="active:scale-95 transition-transform"
            onClick={() => navigate(-1)}
            style={{
              padding: '8px 16px', borderRadius: 999,
              background: 'var(--tx-bg-tertiary, #F0EDE6)',
              color: 'var(--tx-text-secondary)', fontSize: 14,
              minHeight: 48,
            }}
          >
            返回
          </button>
        </div>
      </div>

      {/* ── 分类+菜品 ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左侧分类 */}
        <div
          className="flex-shrink-0 overflow-y-auto"
          style={{ width: 80, background: 'var(--tx-bg-secondary, #F8F7F5)', WebkitOverflowScrolling: 'touch' }}
        >
          {categories.map((cat) => (
            <button
              key={cat.id}
              className="w-full active:scale-95 transition-transform"
              onClick={() => setActiveCat(cat.id)}
              style={{
                padding: '16px 8px', textAlign: 'center', fontSize: 13,
                color: activeCat === cat.id ? 'var(--tx-brand, #FF6B35)' : 'var(--tx-text-secondary)',
                fontWeight: activeCat === cat.id ? 700 : 400,
                background: activeCat === cat.id ? 'var(--tx-bg-primary)' : 'transparent',
                borderLeft: activeCat === cat.id ? '3px solid var(--tx-brand)' : '3px solid transparent',
                minHeight: 48,
              }}
            >
              {cat.icon && <div className="text-lg mb-1">{cat.icon}</div>}
              {cat.name}
            </button>
          ))}
        </div>

        {/* 右侧饮品列表 */}
        <div className="flex-1 overflow-y-auto px-3 pb-32" style={{ WebkitOverflowScrolling: 'touch' }}>
          {displayDishes.map((dish) => {
            const qty = getQuantity(dish.id);
            return (
              <button
                key={dish.id}
                className="flex gap-3 py-3 w-full text-left active:bg-gray-50 transition-colors"
                style={{ borderBottom: '1px solid var(--tx-border, #E8E6E1)' }}
                onClick={() => !dish.soldOut && openCustomizer(dish)}
              >
                <div
                  className="flex-shrink-0 rounded-xl overflow-hidden relative"
                  style={{ width: 90, height: 90, background: 'var(--tx-bg-tertiary)' }}
                >
                  <img
                    src={dish.images[0] ?? ''}
                    alt={dish.name}
                    loading="lazy"
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                  {dish.soldOut && (
                    <div className="absolute inset-0 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.45)' }}>
                      <span className="text-white text-sm font-bold">售罄</span>
                    </div>
                  )}
                  {qty > 0 && (
                    <span
                      className="absolute top-1 right-1 w-5 h-5 rounded-full flex items-center justify-center text-white text-xs font-bold"
                      style={{ background: 'var(--tx-brand, #FF6B35)', fontSize: 11 }}
                    >
                      {qty}
                    </span>
                  )}
                </div>
                <div className="flex-1 min-w-0 flex flex-col justify-between py-0.5">
                  <div>
                    <div className="text-base font-semibold" style={{ color: 'var(--tx-text-primary)' }}>
                      {dish.name}
                    </div>
                    <div className="text-xs mt-1 line-clamp-2" style={{ color: 'var(--tx-text-tertiary)' }}>
                      {dish.description || '选规格/甜度/温度/加料'}
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-baseline gap-1">
                      <span className="text-base font-bold" style={{ color: 'var(--tx-brand, #FF6B35)' }}>
                        ¥{dish.price}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--tx-text-tertiary)' }}>起</span>
                    </div>
                    <span
                      className="text-xs px-3 py-1 rounded-full"
                      style={{
                        background: dish.soldOut ? 'var(--tx-bg-tertiary)' : 'var(--tx-brand-light, #FFF3ED)',
                        color: dish.soldOut ? 'var(--tx-text-tertiary)' : 'var(--tx-brand, #FF6B35)',
                        fontWeight: 600, minHeight: 48, display: 'flex', alignItems: 'center',
                      }}
                    >
                      {dish.soldOut ? '售罄' : '选规格'}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}

          {displayDishes.length === 0 && (
            <div className="text-center py-16 text-sm" style={{ color: 'var(--tx-text-tertiary)' }}>
              该分类暂无饮品
            </div>
          )}
        </div>
      </div>

      {/* ── 底部购物车 ── */}
      <CartBar
        count={cartCount()}
        total={cartTotal()}
        onViewCart={() => navigate('/cart')}
        onCheckout={() => navigate('/checkout')}
      />

      {/* ── 定制弹层（底部滑出） ── */}
      {customizing && (
        <>
          {/* 遮罩 */}
          <div
            className="fixed inset-0 z-40"
            style={{ background: 'rgba(0,0,0,0.4)' }}
            onClick={() => setCustomizing(null)}
          />

          {/* 弹层 */}
          <div
            className="fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl overflow-hidden"
            style={{
              background: 'var(--tx-bg-primary, #fff)',
              maxHeight: '85vh',
              animation: 'slideUp 300ms ease-out',
            }}
          >
            {/* 弹层头部 */}
            <div className="flex gap-4 p-4" style={{ borderBottom: '1px solid var(--tx-border, #E8E6E1)' }}>
              <div
                className="flex-shrink-0 rounded-xl overflow-hidden"
                style={{ width: 80, height: 80, background: 'var(--tx-bg-tertiary)' }}
              >
                <img
                  src={customizing.dish.images[0] ?? ''}
                  alt={customizing.dish.name}
                  className="w-full h-full object-cover"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              </div>
              <div className="flex-1">
                <div className="text-lg font-bold" style={{ color: 'var(--tx-text-primary)' }}>
                  {customizing.dish.name}
                </div>
                <div className="text-xl font-bold mt-1" style={{ color: 'var(--tx-brand, #FF6B35)' }}>
                  ¥{customPrice.toFixed(1)}
                </div>
              </div>
              <button
                className="self-start active:scale-90 transition-transform"
                onClick={() => setCustomizing(null)}
                style={{ minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path d="M18 6L6 18M6 6l12 12" stroke="#B4B2A9" strokeWidth="2.5" strokeLinecap="round"/>
                </svg>
              </button>
            </div>

            {/* 规格选择区 */}
            <div className="overflow-y-auto" style={{ maxHeight: 'calc(85vh - 200px)', WebkitOverflowScrolling: 'touch' }}>
              {/* 必选规格 */}
              {TEA_SPEC_GROUPS.map((group) => (
                <div key={group.groupName} className="px-4 py-3" style={{ borderBottom: '1px solid var(--tx-border, #E8E6E1)' }}>
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-sm font-semibold" style={{ color: 'var(--tx-text-primary)' }}>
                      {group.groupName}
                    </span>
                    {group.required && (
                      <span
                        className="text-xs px-1.5 py-0.5 rounded"
                        style={{ background: 'var(--tx-brand-light, #FFF3ED)', color: 'var(--tx-brand, #FF6B35)' }}
                      >
                        必选
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {group.options.map((opt) => {
                      const selected = customizing.selections[group.groupName] === opt.id;
                      return (
                        <button
                          key={opt.id}
                          className="active:scale-95 transition-transform"
                          onClick={() => selectSpec(group.groupName, opt.id)}
                          style={{
                            padding: '10px 16px', borderRadius: 999,
                            fontSize: 14,
                            fontWeight: selected ? 700 : 400,
                            background: selected ? 'var(--tx-brand, #FF6B35)' : 'var(--tx-bg-secondary, #F8F7F5)',
                            color: selected ? '#fff' : 'var(--tx-text-primary)',
                            border: 'none',
                            minHeight: 48,
                          }}
                        >
                          {opt.label}
                          {opt.priceAdjust > 0 && ` +¥${opt.priceAdjust}`}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}

              {/* 加料（多选） */}
              <div className="px-4 py-3" style={{ borderBottom: '1px solid var(--tx-border, #E8E6E1)' }}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-sm font-semibold" style={{ color: 'var(--tx-text-primary)' }}>
                    {TEA_TOPPINGS.groupName}
                  </span>
                  <span className="text-xs" style={{ color: 'var(--tx-text-tertiary)' }}>
                    可多选
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {TEA_TOPPINGS.options.map((opt) => {
                    const selected = customizing.toppings.includes(opt.id);
                    return (
                      <button
                        key={opt.id}
                        className="active:scale-95 transition-transform"
                        onClick={() => toggleTopping(opt.id)}
                        style={{
                          padding: '10px 16px', borderRadius: 999,
                          fontSize: 14,
                          fontWeight: selected ? 700 : 400,
                          background: selected ? 'var(--tx-brand, #FF6B35)' : 'var(--tx-bg-secondary, #F8F7F5)',
                          color: selected ? '#fff' : 'var(--tx-text-primary)',
                          border: 'none',
                          minHeight: 48,
                        }}
                      >
                        {opt.label} +¥{opt.priceAdjust}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* 底部：数量+确认 */}
            <div
              className="p-4 flex items-center gap-4"
              style={{ borderTop: '1px solid var(--tx-border, #E8E6E1)' }}
            >
              {/* 数量选择 */}
              <div className="flex items-center gap-3">
                <button
                  className="rounded-full flex items-center justify-center active:scale-90 transition-transform"
                  disabled={customizing.quantity <= 1}
                  onClick={() => setCustomizing((p) => p ? { ...p, quantity: Math.max(1, p.quantity - 1) } : p)}
                  style={{
                    width: 36, height: 36,
                    border: '1.5px solid var(--tx-border)',
                    color: customizing.quantity <= 1 ? 'var(--tx-text-tertiary)' : 'var(--tx-text-primary)',
                    opacity: customizing.quantity <= 1 ? 0.4 : 1,
                    minWidth: 48, minHeight: 48, padding: 0,
                  }}
                >
                  <span className="text-lg leading-none">-</span>
                </button>
                <span className="text-lg font-bold w-6 text-center" style={{ color: 'var(--tx-text-primary)' }}>
                  {customizing.quantity}
                </span>
                <button
                  className="rounded-full flex items-center justify-center active:scale-90 transition-transform"
                  onClick={() => setCustomizing((p) => p ? { ...p, quantity: p.quantity + 1 } : p)}
                  style={{
                    width: 36, height: 36,
                    background: 'var(--tx-brand, #FF6B35)', color: '#fff',
                    minWidth: 48, minHeight: 48, padding: 0,
                  }}
                >
                  <span className="text-lg leading-none">+</span>
                </button>
              </div>

              {/* 确认按钮 */}
              <button
                className="flex-1 active:scale-[0.97] transition-transform"
                onClick={handleConfirmCustom}
                style={{
                  height: 52, borderRadius: 12,
                  background: 'var(--tx-brand, #FF6B35)', color: '#fff',
                  fontSize: 16, fontWeight: 700,
                }}
              >
                加入购物车 · ¥{customPrice.toFixed(1)}
              </button>
            </div>
          </div>

          {/* 弹层动画 */}
          <style>{`
            @keyframes slideUp {
              from { transform: translateY(100%); }
              to { transform: translateY(0); }
            }
          `}</style>
        </>
      )}
    </div>
  );
}
