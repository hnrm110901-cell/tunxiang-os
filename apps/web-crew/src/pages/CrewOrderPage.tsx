/**
 * CrewOrderPage - 服务员桌旁点餐页
 * 桌号选择 + 分类Tab + 菜品列表 + 购物车 + 下单确认
 */
import { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { CategoryNav, DishCard } from '@tx-ds/biz';
import type { DishData } from '@tx-ds/biz';
import { formatPrice } from '@tx-ds/utils';

/* ---------- 类型 ---------- */
interface DishItem {
  id: string;
  name: string;
  price: number;
  category: string;
  image: string;
  tags: string[];        // 推荐/新品/招牌
}

interface CartItem {
  dish: DishItem;
  qty: number;
  remark: string;
  practice: string;      // 做法
  isRecommended: boolean; // 服务员推荐标记
}

/* ---------- mock 数据 ---------- */
const TABLES = [
  { id: 'A1', open: true },  { id: 'A2', open: false }, { id: 'A3', open: true },
  { id: 'B1', open: true },  { id: 'B2', open: false }, { id: 'B3', open: true },
  { id: 'C1', open: true },  { id: 'C2', open: true },  { id: 'C3', open: false },
  { id: 'D1', open: false }, { id: 'D2', open: true },  { id: 'D3', open: true },
];

const CATEGORIES = ['热销', '凉菜', '热菜', '汤品', '主食', '饮品', '甜品'];

const DISHES: DishItem[] = [
  { id: 'd1',  name: '剁椒鱼头',     price: 88,  category: '热销', image: '', tags: ['招牌'] },
  { id: 'd2',  name: '红烧肉',       price: 58,  category: '热销', image: '', tags: ['推荐'] },
  { id: 'd3',  name: '蒜蓉西兰花',   price: 28,  category: '热菜', image: '', tags: [] },
  { id: 'd4',  name: '酸辣土豆丝',   price: 22,  category: '凉菜', image: '', tags: [] },
  { id: 'd5',  name: '皮蛋豆腐',     price: 18,  category: '凉菜', image: '', tags: [] },
  { id: 'd6',  name: '番茄蛋汤',     price: 16,  category: '汤品', image: '', tags: [] },
  { id: 'd7',  name: '鸡汤',         price: 48,  category: '汤品', image: '', tags: ['推荐'] },
  { id: 'd8',  name: '蛋炒饭',       price: 15,  category: '主食', image: '', tags: [] },
  { id: 'd9',  name: '酸梅汤',       price: 12,  category: '饮品', image: '', tags: [] },
  { id: 'd10', name: '芒果布丁',     price: 18,  category: '甜品', image: '', tags: ['新品'] },
  { id: 'd11', name: '水煮牛肉',     price: 68,  category: '热菜', image: '', tags: ['招牌'] },
  { id: 'd12', name: '麻婆豆腐',     price: 32,  category: '热菜', image: '', tags: [] },
  { id: 'd13', name: '米饭',         price: 3,   category: '主食', image: '', tags: [] },
  { id: 'd14', name: '可乐',         price: 8,   category: '饮品', image: '', tags: [] },
];

const PRACTICES: Record<string, string[]> = {
  '剁椒鱼头': ['微辣', '中辣', '特辣'],
  '红烧肉': ['少糖', '正常', '多糖'],
  '水煮牛肉': ['微辣', '中辣', '特辣', '变态辣'],
  '麻婆豆腐': ['微辣', '中辣'],
};

/* ---------- 组件 ---------- */
export function CrewOrderPage() {
  const nav = useNavigate();

  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState(CATEGORIES[0]);
  const [cart, setCart] = useState<Map<string, CartItem>>(new Map());
  const [showConfirm, setShowConfirm] = useState(false);
  const [showPractice, setShowPractice] = useState<string | null>(null); // dishId
  const [remarkDishId, setRemarkDishId] = useState<string | null>(null);
  const [remarkText, setRemarkText] = useState('');

  const filteredDishes = useMemo(
    () => DISHES.filter(d => d.category === activeCategory),
    [activeCategory],
  );

  const totalQty = useMemo(() => {
    let q = 0;
    cart.forEach(c => { q += c.qty; });
    return q;
  }, [cart]);

  const totalPrice = useMemo(() => {
    let p = 0;
    cart.forEach(c => { p += c.dish.price * c.qty; });
    return p;
  }, [cart]);

  const vibrate = useCallback(() => { try { navigator.vibrate(50); } catch (_e) { /* noop */ } }, []);

  // Map DishItem → DishData for shared component
  const toDishData = useCallback((d: DishItem): DishData => ({
    id: d.id,
    name: d.name,
    priceFen: d.price * 100,  // mock data is in yuan, shared component expects fen
    image: d.image,
    tags: d.tags,
    soldOut: false,
  }), []);

  const navCategories = useMemo(
    () => CATEGORIES.map(c => ({ id: c, name: c })),
    [],
  );

  const addToCart = (dish: DishItem) => {
    vibrate();
    setCart(prev => {
      const next = new Map(prev);
      const existing = next.get(dish.id);
      if (existing) {
        next.set(dish.id, { ...existing, qty: existing.qty + 1 });
      } else {
        next.set(dish.id, { dish, qty: 1, remark: '', practice: '', isRecommended: false });
      }
      return next;
    });
  };

  const removeFromCart = (dishId: string) => {
    vibrate();
    setCart(prev => {
      const next = new Map(prev);
      const existing = next.get(dishId);
      if (existing && existing.qty > 1) {
        next.set(dishId, { ...existing, qty: existing.qty - 1 });
      } else {
        next.delete(dishId);
      }
      return next;
    });
  };

  const setPractice = (dishId: string, practice: string) => {
    setCart(prev => {
      const next = new Map(prev);
      const existing = next.get(dishId);
      if (existing) {
        next.set(dishId, { ...existing, practice });
      }
      return next;
    });
    setShowPractice(null);
  };

  const saveRemark = () => {
    if (!remarkDishId) return;
    setCart(prev => {
      const next = new Map(prev);
      const existing = next.get(remarkDishId);
      if (existing) {
        next.set(remarkDishId, { ...existing, remark: remarkText });
      }
      return next;
    });
    setRemarkDishId(null);
    setRemarkText('');
  };

  const toggleRecommend = (dishId: string) => {
    vibrate();
    setCart(prev => {
      const next = new Map(prev);
      const existing = next.get(dishId);
      if (existing) {
        next.set(dishId, { ...existing, isRecommended: !existing.isRecommended });
      }
      return next;
    });
  };

  const handleSubmit = () => {
    vibrate();
    // TODO: 调用 API 提交订单
    setCart(new Map());
    setShowConfirm(false);
    nav('/active');
  };

  /* --- 桌号选择（未选桌时全屏显示） --- */
  if (!selectedTable) {
    return (
      <div style={{ padding: '16px 12px', maxWidth: 480, margin: '0 auto' }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: 16,
        }}>
          <button
            onClick={() => { vibrate(); nav(-1); }}
            style={{
              background: 'none', border: 'none', color: '#94a3b8', fontSize: 16,
              cursor: 'pointer', minWidth: 48, minHeight: 48,
              display: 'flex', alignItems: 'center',
            }}
          >
            &lt; 返回
          </button>
          <span style={{ fontSize: 20, fontWeight: 700 }}>选择桌号</span>
          <div style={{ width: 48 }} />
        </div>
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 10,
        }}>
          {TABLES.map(t => (
            <button
              key={t.id}
              onClick={() => { vibrate(); if (t.open) setSelectedTable(t.id); }}
              style={{
                background: t.open ? '#112228' : '#0d1f26',
                border: t.open ? '2px solid #FF6B35' : '2px solid #1a2a33',
                borderRadius: 12, padding: 16, cursor: t.open ? 'pointer' : 'default',
                opacity: t.open ? 1 : 0.4, minHeight: 64,
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                justifyContent: 'center', gap: 4,
              }}
            >
              <span style={{ fontSize: 22, fontWeight: 700, color: t.open ? '#FF6B35' : '#475569' }}>
                {t.id}
              </span>
              <span style={{ fontSize: 14, color: t.open ? '#94a3b8' : '#334155' }}>
                {t.open ? '已开台' : '空闲'}
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  /* --- 主点餐界面 --- */
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      {/* 顶部栏 */}
      <div style={{
        background: '#112228', padding: '12px 14px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <button
          onClick={() => { vibrate(); setSelectedTable(null); }}
          style={{
            background: 'none', border: 'none', color: '#94a3b8', fontSize: 16,
            cursor: 'pointer', minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center',
          }}
        >
          &lt; 换桌
        </button>
        <span style={{ fontSize: 20, fontWeight: 700 }}>
          <span style={{ color: '#FF6B35' }}>{selectedTable}</span> 桌点餐
        </span>
        <div style={{ width: 48 }} />
      </div>

      {/* 内容区：左分类 + 右菜品 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左侧分类 — 共享 CategoryNav 组件 */}
        <CategoryNav
          categories={navCategories}
          activeId={activeCategory}
          onSelect={(id) => { vibrate(); setActiveCategory(id); }}
          direction="vertical"
        />

        {/* 右侧菜品列表 — 共享 DishCard 组件 + 服务员专属操作 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px' }}>
          {filteredDishes.map(dish => {
            const inCart = cart.get(dish.id);
            const qty = inCart?.qty ?? 0;
            return (
              <div key={dish.id} style={{ marginBottom: 8 }}>
                <DishCard
                  dish={toDishData(dish)}
                  variant="horizontal"
                  qty={qty}
                  onAdd={() => addToCart(dish)}
                  onMinus={() => removeFromCart(dish.id)}
                />
                {/* 服务员专属：做法/备注/推荐 操作行 */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6, marginTop: 4,
                  paddingLeft: 74, flexWrap: 'wrap',
                }}>
                  {PRACTICES[dish.name] && (
                    <button
                      onClick={() => { vibrate(); if (qty > 0) setShowPractice(dish.id); else { addToCart(dish); setShowPractice(dish.id); } }}
                      style={{
                        background: '#1a2a33', border: 'none', borderRadius: 6, padding: '4px 8px',
                        color: inCart?.practice ? '#FF6B35' : '#94a3b8', fontSize: 14,
                        cursor: 'pointer', minHeight: 32,
                      }}
                    >
                      {inCart?.practice || '做法'}
                    </button>
                  )}
                  <button
                    onClick={() => { vibrate(); if (qty > 0) { setRemarkDishId(dish.id); setRemarkText(inCart?.remark ?? ''); } else { addToCart(dish); setRemarkDishId(dish.id); setRemarkText(''); } }}
                    style={{
                      background: '#1a2a33', border: 'none', borderRadius: 6, padding: '4px 8px',
                      color: inCart?.remark ? '#FF6B35' : '#94a3b8', fontSize: 14,
                      cursor: 'pointer', minHeight: 32,
                    }}
                  >
                    {inCart?.remark ? '已备注' : '备注'}
                  </button>
                  {qty > 0 && (
                    <button
                      onClick={() => toggleRecommend(dish.id)}
                      style={{
                        background: inCart?.isRecommended ? '#FF6B3533' : '#1a2a33',
                        border: 'none', borderRadius: 6, padding: '4px 8px',
                        color: inCart?.isRecommended ? '#FF6B35' : '#94a3b8',
                        fontSize: 14, cursor: 'pointer', minHeight: 32,
                      }}
                    >
                      {inCart?.isRecommended ? '已推荐' : '推荐'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {filteredDishes.length === 0 && (
            <div style={{ padding: 32, textAlign: 'center', color: '#475569', fontSize: 16 }}>
              该分类暂无菜品
            </div>
          )}
        </div>
      </div>

      {/* 底部购物车栏 */}
      {totalQty > 0 && (
        <div style={{
          background: '#112228', borderTop: '1px solid #1a2a33', padding: '10px 14px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <div>
            <span style={{ fontSize: 16, color: '#94a3b8' }}>已选 </span>
            <span style={{ fontSize: 20, fontWeight: 700, color: '#FF6B35' }}>{totalQty}</span>
            <span style={{ fontSize: 16, color: '#94a3b8' }}> 件</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: '#FF6B35' }}>{formatPrice(totalPrice * 100)}</span>
            <button
              onClick={() => { vibrate(); setShowConfirm(true); }}
              style={{
                background: '#FF6B35', border: 'none', borderRadius: 10,
                color: '#fff', fontSize: 18, fontWeight: 700,
                padding: '12px 28px', cursor: 'pointer',
                minWidth: 48, minHeight: 48,
              }}
            >
              下单
            </button>
          </div>
        </div>
      )}

      {/* 做法选择弹窗 */}
      {showPractice && (() => {
        const item = cart.get(showPractice);
        const dishName = item?.dish.name ?? '';
        const opts = PRACTICES[dishName] ?? [];
        return (
          <div
            onClick={() => setShowPractice(null)}
            style={{
              position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
              display: 'flex', alignItems: 'flex-end', justifyContent: 'center', zIndex: 100,
            }}
          >
            <div
              onClick={e => e.stopPropagation()}
              style={{
                background: '#112228', borderRadius: '16px 16px 0 0', padding: '20px 16px 32px',
                width: '100%', maxWidth: 480,
              }}
            >
              <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 14 }}>{dishName} - 做法选择</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {opts.map(p => (
                  <button
                    key={p}
                    onClick={() => setPractice(showPractice, p)}
                    style={{
                      background: item?.practice === p ? '#FF6B35' : '#1a2a33',
                      border: 'none', borderRadius: 8, padding: '12px 20px',
                      color: item?.practice === p ? '#fff' : '#e2e8f0',
                      fontSize: 16, fontWeight: 600, cursor: 'pointer',
                      minWidth: 48, minHeight: 48,
                    }}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </div>
        );
      })()}

      {/* 备注弹窗 */}
      {remarkDishId && (
        <div
          onClick={() => { setRemarkDishId(null); setRemarkText(''); }}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'flex-end', justifyContent: 'center', zIndex: 100,
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#112228', borderRadius: '16px 16px 0 0', padding: '20px 16px 32px',
              width: '100%', maxWidth: 480,
            }}
          >
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 14 }}>添加备注</div>
            <textarea
              value={remarkText}
              onChange={e => setRemarkText(e.target.value)}
              placeholder="如：不要香菜、少油少盐..."
              style={{
                width: '100%', background: '#0B1A20', border: '1px solid #1a2a33',
                borderRadius: 8, padding: 12, color: '#e2e8f0', fontSize: 16,
                resize: 'none', height: 80, outline: 'none', boxSizing: 'border-box',
              }}
            />
            <button
              onClick={saveRemark}
              style={{
                width: '100%', background: '#FF6B35', border: 'none', borderRadius: 10,
                color: '#fff', fontSize: 18, fontWeight: 700, padding: '14px 0',
                marginTop: 12, cursor: 'pointer', minHeight: 48,
              }}
            >
              确定
            </button>
          </div>
        </div>
      )}

      {/* 下单确认弹窗 */}
      {showConfirm && (
        <div
          onClick={() => setShowConfirm(false)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#112228', borderRadius: 16, padding: '20px 16px',
              width: 'calc(100% - 32px)', maxWidth: 420, maxHeight: '80vh',
              display: 'flex', flexDirection: 'column',
            }}
          >
            <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 14, textAlign: 'center' }}>
              确认下单 - {selectedTable}桌
            </div>
            <div style={{ flex: 1, overflowY: 'auto', marginBottom: 14 }}>
              {Array.from(cart.values()).map(item => (
                <div key={item.dish.id} style={{
                  display: 'flex', justifyContent: 'space-between', padding: '8px 0',
                  borderBottom: '1px solid #1a2a33', alignItems: 'center',
                }}>
                  <div>
                    <div style={{ fontSize: 16 }}>
                      {item.dish.name}
                      {item.isRecommended && (
                        <span style={{ fontSize: 12, color: '#FF6B35', marginLeft: 6 }}>[推荐]</span>
                      )}
                    </div>
                    {item.practice && (
                      <div style={{ fontSize: 14, color: '#94a3b8' }}>做法: {item.practice}</div>
                    )}
                    {item.remark && (
                      <div style={{ fontSize: 14, color: '#94a3b8' }}>备注: {item.remark}</div>
                    )}
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontSize: 16, color: '#FF6B35' }}>x{item.qty}</div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{formatPrice(item.dish.price * item.qty * 100)}</div>
                  </div>
                </div>
              ))}
            </div>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '12px 0 8px', borderTop: '1px solid #1a2a33',
            }}>
              <span style={{ fontSize: 16, color: '#94a3b8' }}>共 {totalQty} 件</span>
              <span style={{ fontSize: 24, fontWeight: 700, color: '#FF6B35' }}>{formatPrice(totalPrice * 100)}</span>
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
              <button
                onClick={() => setShowConfirm(false)}
                style={{
                  flex: 1, background: '#1a2a33', border: 'none', borderRadius: 10,
                  color: '#94a3b8', fontSize: 18, fontWeight: 600, padding: '14px 0',
                  cursor: 'pointer', minHeight: 48,
                }}
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                style={{
                  flex: 1, background: '#FF6B35', border: 'none', borderRadius: 10,
                  color: '#fff', fontSize: 18, fontWeight: 700, padding: '14px 0',
                  cursor: 'pointer', minHeight: 48,
                }}
              >
                确认下单
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
