/**
 * 点菜页面（核心） — 分类导航 + 菜品列表 + 购物车
 * 支持: 加菜/退菜/改数量/时价菜输入价格/称重菜输入重量/备注做法
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

/* ---------- 样式常量 ---------- */
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

/* ---------- 类型 ---------- */
interface CartItem {
  dishId: string;
  name: string;
  qty: number;
  priceFen: number;          // 单价(分)
  weight?: number;            // 称重菜(斤)
  spec?: string;              // 选中的做法
  note: string;               // 备注
}

/* ---------- 组件 ---------- */
export function OrderPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const tableNo = params.get('table') || '';
  const guests = params.get('guests') || '';

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

  const filteredDishes = useMemo(
    () => DISHES.filter(d => d.catId === activeCat),
    [activeCat],
  );

  const cartTotal = cart.reduce((sum, item) => {
    const unitPrice = item.priceFen;
    const weight = item.weight || 1;
    return sum + unitPrice * item.qty * weight;
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

  return (
    <div style={{ background: C.bg, minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 顶部: 桌号信息 */}
      <div style={{
        padding: '12px 16px', background: C.card,
        borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <span style={{ fontSize: 20, fontWeight: 700, color: C.white }}>
            {tableNo ? `${tableNo} 桌` : '点菜'}
          </span>
          {guests && <span style={{ fontSize: 16, color: C.muted, marginLeft: 8 }}>{guests}人</span>}
        </div>
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 48, minHeight: 48, borderRadius: 12,
            background: C.card, border: `1px solid ${C.border}`,
            color: C.muted, fontSize: 16, cursor: 'pointer',
          }}
        >
          返回
        </button>
      </div>

      {/* 分类横向滚动 */}
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

      {/* 菜品列表 */}
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
              {/* 菜品信息 */}
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
              {/* 已点数量角标 */}
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

      {/* 底部购物车栏 */}
      {cartCount > 0 && (
        <div style={{
          position: 'fixed', bottom: 56, left: 0, right: 0,
          padding: '10px 16px', background: C.card,
          borderTop: `1px solid ${C.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
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
              fontSize: 20, fontWeight: 700, position: 'relative',
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

      {/* 购物车展开面板 */}
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

      {/* 特殊菜弹窗(时价/称重/做法) */}
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

            {/* 时价菜: 输入价格 */}
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

            {/* 称重菜: 输入重量 */}
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

            {/* 做法选择 */}
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

            {/* 备注 */}
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

            {/* 确认按钮 */}
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
    </div>
  );
}
