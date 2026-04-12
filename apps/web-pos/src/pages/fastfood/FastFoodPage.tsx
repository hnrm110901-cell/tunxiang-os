/**
 * FastFoodPage — 快餐模式主入口 /fastfood
 *
 * 业态判断：storeType === 'fast_food' 时从主菜单自动跳转此页
 * 布局：左侧菜品宫格（4列，大图+价格+名称）| 右侧订单列表+结账
 *
 * 核心流程：
 *   1. 点菜品直接加入购物车（无需开台）
 *   2. 右侧显示当前订单 + 合计
 *   3. 结账 → POST /api/v1/fastfood/orders → 获取取餐号
 *   4. 取餐号大字弹出确认
 *
 * Store-POS 终端规范（TXTouch）：
 *   - 所有触控区域 ≥ 48×48px，关键操作 ≥ 72px
 *   - 最小字体 16px
 *   - 深色主题
 *   - 触控反馈：active:scale-95 + transition-transform 200ms
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDishes, fetchCategories, type DishItem } from '../../api/menuApi';
import { txFetch } from '../../api/index';

// ─── Design Tokens ───
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  success: '#0F6E56',
  warning: '#BA7517',
  info: '#185FA5',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
  dimText: '#6B7280',
};

// ─── Types ───
interface CartItem {
  dishId: string;
  name: string;
  priceFen: number;
  qty: number;
}

type DineMode = 'dine_in' | 'pack';

interface FastFoodOrderResult {
  fast_food_order_id: string;
  call_number: string;
  order_type: string;
  total_fen: number;
  status: string;
}

// ─── Mock data (offline/dev fallback) ───
const MOCK_CATEGORIES = ['热销', '快餐套餐', '主食', '小吃', '饮品'];
const MOCK_DISHES: DishItem[] = [
  { id: 'm01', name: '黄焖鸡米饭', priceFen: 2800, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'm02', name: '麻辣烫', priceFen: 2200, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'm03', name: '牛肉面', priceFen: 1800, category: '热销', kitchenStation: 'noodle', isAvailable: true },
  { id: 'm04', name: '蛋炒饭', priceFen: 1500, category: '主食', kitchenStation: 'hot', isAvailable: true },
  { id: 'm05', name: '猪脚饭', priceFen: 2200, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'm06', name: '盖浇饭（鱼香肉丝）', priceFen: 2000, category: '热销', kitchenStation: 'hot', isAvailable: true },
  { id: 'm07', name: '炒河粉', priceFen: 1600, category: '主食', kitchenStation: 'hot', isAvailable: true },
  { id: 'm08', name: '煎饺（6个）', priceFen: 1200, category: '小吃', kitchenStation: 'snack', isAvailable: true },
  { id: 'm09', name: '葱油拌面', priceFen: 1000, category: '主食', kitchenStation: 'noodle', isAvailable: true },
  { id: 'm10', name: '冰镇绿茶', priceFen: 800, category: '饮品', kitchenStation: 'drink', isAvailable: true },
  { id: 'm11', name: '豆浆', priceFen: 500, category: '饮品', kitchenStation: 'drink', isAvailable: true },
  { id: 'm12', name: '快餐A套（荤+素+汤）', priceFen: 2800, category: '快餐套餐', kitchenStation: 'hot', isAvailable: true },
];

const STORE_ID = (window as unknown as Record<string, unknown>).__STORE_ID__ as string || 'demo-store';

function fmtFen(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

export function FastFoodPage() {
  const navigate = useNavigate();

  const [categories, setCategories] = useState<string[]>(MOCK_CATEGORIES);
  const [dishes, setDishes] = useState<DishItem[]>(MOCK_DISHES);
  const [activeCategory, setActiveCategory] = useState<string>(MOCK_CATEGORIES[0]);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [dineMode, setDineMode] = useState<DineMode>('dine_in');
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [successCallNumber, setSuccessCallNumber] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // ─── Load menu data ───
  useEffect(() => {
    (async () => {
      try {
        const [cats, dishesList] = await Promise.all([
          fetchCategories(STORE_ID),
          fetchDishes(STORE_ID),
        ]);
        if (cats.length > 0) setCategories(cats);
        if (dishesList.length > 0) setDishes(dishesList);
        if (cats.length > 0) setActiveCategory(cats[0]);
      } catch {
        // keep mock data on error
      }
    })();
  }, []);

  const filteredDishes = dishes.filter(d => d.category === activeCategory && d.isAvailable);

  // ─── Cart operations ───
  const addToCart = useCallback((dish: DishItem) => {
    setCart(prev => {
      const existing = prev.find(i => i.dishId === dish.id);
      if (existing) {
        return prev.map(i => i.dishId === dish.id ? { ...i, qty: i.qty + 1 } : i);
      }
      return [...prev, { dishId: dish.id, name: dish.name, priceFen: dish.priceFen, qty: 1 }];
    });
  }, []);

  const removeFromCart = useCallback((dishId: string) => {
    setCart(prev => {
      const existing = prev.find(i => i.dishId === dishId);
      if (!existing) return prev;
      if (existing.qty <= 1) return prev.filter(i => i.dishId !== dishId);
      return prev.map(i => i.dishId === dishId ? { ...i, qty: i.qty - 1 } : i);
    });
  }, []);

  const clearCart = useCallback(() => setCart([]), []);

  const totalFen = cart.reduce((s, i) => s + i.priceFen * i.qty, 0);
  const totalItems = cart.reduce((s, i) => s + i.qty, 0);

  // ─── Checkout ───
  const handleCheckout = useCallback(async () => {
    if (cart.length === 0 || isSubmitting) return;
    setIsSubmitting(true);
    try {
      const result = await txFetch<FastFoodOrderResult>('/api/v1/fastfood/orders', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID,
          items: cart.map(i => ({
            dish_id: i.dishId,
            dish_name: i.name,
            qty: i.qty,
            unit_price_fen: i.priceFen,
          })),
          order_type: dineMode,
        }),
      });
      setSuccessCallNumber(result.call_number);
      setCart([]);
      setCheckoutOpen(false);
    } catch (err) {
      // show error inline — keep checkout open
      alert((err as Error).message || '下单失败，请重试');
    } finally {
      setIsSubmitting(false);
    }
  }, [cart, dineMode, isSubmitting]);

  // ─── Dismiss success screen ───
  const dismissSuccess = useCallback(() => {
    setSuccessCallNumber(null);
  }, []);

  return (
    <div style={{ display: 'flex', height: '100vh', background: C.bg, overflow: 'hidden' }}>

      {/* ── Left: Category + Dishes (65%) ── */}
      <div style={{ display: 'flex', flex: '0 0 65%', borderRight: `1px solid ${C.border}` }}>

        {/* Category sidebar */}
        <div style={{
          width: 96,
          background: C.card,
          borderRight: `1px solid ${C.border}`,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
          padding: '8px 0',
        }}>
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              style={{
                padding: '12px 8px',
                background: activeCategory === cat ? C.accent : 'transparent',
                color: activeCategory === cat ? C.white : C.text,
                border: 'none',
                cursor: 'pointer',
                fontSize: 14,
                fontWeight: activeCategory === cat ? 700 : 400,
                textAlign: 'center',
                lineHeight: 1.3,
                minHeight: 48,
                transition: 'background 200ms',
              }}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Dish grid (4 columns) */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 10,
          }}>
            {filteredDishes.map(dish => {
              const cartItem = cart.find(i => i.dishId === dish.id);
              return (
                <button
                  key={dish.id}
                  onClick={() => addToCart(dish)}
                  style={{
                    background: C.card,
                    border: cartItem ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                    borderRadius: 10,
                    padding: 0,
                    cursor: 'pointer',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column',
                    minHeight: 120,
                    transition: 'transform 200ms',
                    position: 'relative',
                  }}
                  onPointerDown={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                  onPointerUp={e => (e.currentTarget.style.transform = 'scale(1)')}
                  onPointerLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
                >
                  {/* Dish image placeholder */}
                  <div style={{
                    background: '#1A3A48',
                    height: 72,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 28,
                  }}>
                    🍱
                  </div>
                  <div style={{ padding: '6px 8px', flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                    <div style={{ color: C.text, fontSize: 13, fontWeight: 500, lineHeight: 1.3, marginBottom: 4 }}>
                      {dish.name}
                    </div>
                    <div style={{ color: C.accent, fontSize: 16, fontWeight: 700 }}>
                      {fmtFen(dish.priceFen)}
                    </div>
                  </div>
                  {/* Cart qty badge */}
                  {cartItem && (
                    <div style={{
                      position: 'absolute',
                      top: 6,
                      right: 6,
                      background: C.accent,
                      color: C.white,
                      borderRadius: '50%',
                      width: 22,
                      height: 22,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 12,
                      fontWeight: 700,
                    }}>
                      {cartItem.qty}
                    </div>
                  )}
                </button>
              );
            })}
            {filteredDishes.length === 0 && (
              <div style={{ gridColumn: '1 / -1', textAlign: 'center', color: C.dimText, padding: 40, fontSize: 16 }}>
                该分类暂无菜品
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Right: Order list + checkout (35%) ── */}
      <div style={{ flex: '0 0 35%', display: 'flex', flexDirection: 'column', background: C.card }}>

        {/* Header */}
        <div style={{
          padding: '12px 16px',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <span style={{ color: C.text, fontSize: 16, fontWeight: 700 }}>
            快餐收银
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => navigate('/fastfood/kds')}
              style={{ padding: '6px 12px', background: C.info, color: C.white, border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}
            >
              KDS
            </button>
            <button
              onClick={() => navigate('/fastfood/call-screen')}
              style={{ padding: '6px 12px', background: C.warning, color: C.white, border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}
            >
              叫号屏
            </button>
          </div>
        </div>

        {/* Dine mode toggle */}
        <div style={{ padding: '10px 16px', borderBottom: `1px solid ${C.border}`, display: 'flex', gap: 8 }}>
          {(['dine_in', 'pack'] as DineMode[]).map(mode => (
            <button
              key={mode}
              onClick={() => setDineMode(mode)}
              style={{
                flex: 1,
                padding: '10px 0',
                background: dineMode === mode ? C.accent : '#1A3A48',
                color: C.white,
                border: 'none',
                borderRadius: 8,
                fontSize: 15,
                fontWeight: dineMode === mode ? 700 : 400,
                cursor: 'pointer',
                transition: 'background 200ms',
                minHeight: 48,
              }}
            >
              {mode === 'dine_in' ? '堂食' : '打包'}
            </button>
          ))}
        </div>

        {/* Cart items */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {cart.length === 0 ? (
            <div style={{ textAlign: 'center', color: C.dimText, padding: 40, fontSize: 16 }}>
              点击左侧菜品添加
            </div>
          ) : (
            cart.map(item => (
              <div key={item.dishId} style={{
                display: 'flex',
                alignItems: 'center',
                padding: '10px 16px',
                borderBottom: `1px solid ${C.border}`,
                gap: 10,
              }}>
                <div style={{ flex: 1, color: C.text, fontSize: 15, fontWeight: 500 }}>{item.name}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    onClick={() => removeFromCart(item.dishId)}
                    style={{
                      width: 32, height: 32, background: '#1A3A48', color: C.text,
                      border: 'none', borderRadius: '50%', fontSize: 18, cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >−</button>
                  <span style={{ color: C.white, fontSize: 16, fontWeight: 700, minWidth: 24, textAlign: 'center' }}>
                    {item.qty}
                  </span>
                  <button
                    onClick={() => addToCart({ id: item.dishId, name: item.name, priceFen: item.priceFen, category: '', kitchenStation: '', isAvailable: true })}
                    style={{
                      width: 32, height: 32, background: C.accent, color: C.white,
                      border: 'none', borderRadius: '50%', fontSize: 18, cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >+</button>
                </div>
                <div style={{ color: C.accent, fontSize: 15, fontWeight: 700, minWidth: 60, textAlign: 'right' }}>
                  {fmtFen(item.priceFen * item.qty)}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer: total + checkout */}
        <div style={{ padding: 16, borderTop: `1px solid ${C.border}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={{ color: C.dimText, fontSize: 15 }}>共 {totalItems} 件</span>
            <span style={{ color: C.white, fontSize: 20, fontWeight: 700 }}>{fmtFen(totalFen)}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {cart.length > 0 && (
              <button
                onClick={clearCart}
                style={{
                  width: 56, height: 56, background: '#2A3A48', color: C.dimText,
                  border: 'none', borderRadius: 10, fontSize: 13, cursor: 'pointer',
                }}
              >
                清空
              </button>
            )}
            <button
              onClick={() => setCheckoutOpen(true)}
              disabled={cart.length === 0}
              style={{
                flex: 1,
                height: 56,
                background: cart.length > 0 ? C.accent : C.muted,
                color: C.white,
                border: 'none',
                borderRadius: 10,
                fontSize: 20,
                fontWeight: 700,
                cursor: cart.length > 0 ? 'pointer' : 'not-allowed',
                transition: 'background 200ms',
              }}
            >
              结账 {cart.length > 0 ? fmtFen(totalFen) : ''}
            </button>
          </div>
        </div>
      </div>

      {/* ── Checkout Confirm Modal ── */}
      {checkoutOpen && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }}>
          <div style={{
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 16, padding: 28, width: 360, maxWidth: '90vw',
          }}>
            <h2 style={{ color: C.white, fontSize: 20, margin: '0 0 20px', textAlign: 'center' }}>确认结账</h2>
            <div style={{ marginBottom: 16 }}>
              {cart.map(item => (
                <div key={item.dishId} style={{ display: 'flex', justifyContent: 'space-between', color: C.text, fontSize: 15, marginBottom: 8 }}>
                  <span>{item.name} × {item.qty}</span>
                  <span>{fmtFen(item.priceFen * item.qty)}</span>
                </div>
              ))}
              <div style={{ borderTop: `1px solid ${C.border}`, marginTop: 12, paddingTop: 12, display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: C.dimText, fontSize: 15 }}>合计</span>
                <span style={{ color: C.accent, fontSize: 22, fontWeight: 700 }}>{fmtFen(totalFen)}</span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={() => setCheckoutOpen(false)}
                style={{
                  flex: 1, height: 52, background: '#2A3A48', color: C.text,
                  border: 'none', borderRadius: 10, fontSize: 16, cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={handleCheckout}
                disabled={isSubmitting}
                style={{
                  flex: 2, height: 52,
                  background: isSubmitting ? C.muted : C.accent,
                  color: C.white, border: 'none', borderRadius: 10,
                  fontSize: 18, fontWeight: 700,
                  cursor: isSubmitting ? 'not-allowed' : 'pointer',
                }}
              >
                {isSubmitting ? '下单中...' : '确认下单'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Success: call number display ── */}
      {successCallNumber && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
        }}
          onClick={dismissSuccess}
        >
          <div style={{
            background: C.card, border: `2px solid ${C.accent}`,
            borderRadius: 20, padding: '40px 60px', textAlign: 'center',
          }}>
            <div style={{ color: C.dimText, fontSize: 18, marginBottom: 12 }}>下单成功！请记好取餐号</div>
            <div style={{ color: C.accent, fontSize: 80, fontWeight: 900, lineHeight: 1 }}>
              #{successCallNumber}
            </div>
            <div style={{ color: C.dimText, fontSize: 15, marginTop: 20 }}>点击任意处关闭</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default FastFoodPage;
