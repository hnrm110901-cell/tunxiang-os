/**
 * 快速收银页 — 外卖/打包场景，不需要开台
 * 左侧：菜品分类 + 菜品列表
 * 右侧：购物车 + 合计 + 收款按钮
 * 底部：扫码枪输入框（自动聚焦）
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDishes, fetchCategories, type DishItem } from '../api/menuApi';
import { createOrder, addItem, settleOrder, createPayment } from '../api/tradeApi';
import { printReceipt as bridgePrint, openCashBox } from '../bridge/TXBridge';
import { printReceipt as apiPrintReceipt } from '../api/tradeApi';

/* ─── 样式常量 ─── */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  green: '#0F6E56',
  blue: '#185FA5',
  red: '#A32D2D',
  yellow: '#BA7517',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
};

/* ─── Mock 菜品数据（离线/开发用） ─── */
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

/* ─── 工具函数 ─── */
const fen2yuan = (fen: number) => (fen / 100).toFixed(2);

/* ─── 购物车项 ─── */
interface CartItem {
  dish: DishItem;
  quantity: number;
}

/* ─── 组件 ─── */
export function QuickCashierPage() {
  const navigate = useNavigate();
  const scanInputRef = useRef<HTMLInputElement>(null);

  const [categories, setCategories] = useState<string[]>(MOCK_CATEGORIES);
  const [dishes, setDishes] = useState<DishItem[]>(MOCK_DISHES);
  const [activeCategory, setActiveCategory] = useState<string>(MOCK_CATEGORIES[0]);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [scanValue, setScanValue] = useState('');
  const [paying, setPaying] = useState(false);
  const [paySuccess, setPaySuccess] = useState(false);

  /** 加载菜品数据 */
  useEffect(() => {
    const load = async () => {
      const storeId = import.meta.env.VITE_STORE_ID || '';
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
  }, []);

  /** 自动聚焦扫码输入框 */
  useEffect(() => {
    const timer = setTimeout(() => scanInputRef.current?.focus(), 300);
    return () => clearTimeout(timer);
  }, [paySuccess]);

  /** 当前分类的菜品 */
  const filteredDishes = dishes.filter(d => d.category === activeCategory);

  /** 购物车操作 */
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
    setCart(prev => {
      return prev
        .map(c => c.dish.id === dishId ? { ...c, quantity: c.quantity + delta } : c)
        .filter(c => c.quantity > 0);
    });
  }, []);

  const clearCart = useCallback(() => setCart([]), []);

  /** 合计金额 */
  const totalFen = cart.reduce((s, c) => s + c.dish.priceFen * c.quantity, 0);
  const totalCount = cart.reduce((s, c) => s + c.quantity, 0);

  /** 扫码处理 */
  const handleScan = useCallback((code: string) => {
    if (!code.trim()) return;
    // 尝试匹配菜品条码
    const matched = dishes.find(d => d.id === code || d.name.includes(code));
    if (matched) {
      addToCart(matched);
    }
    setScanValue('');
  }, [dishes, addToCart]);

  /** 收款 */
  const handlePay = async (method: string) => {
    if (paying || cart.length === 0) return;
    setPaying(true);

    try {
      const storeId = import.meta.env.VITE_STORE_ID || '';

      // 1. 创建外卖/打包订单（table_no 用 TAKEOUT）
      const { order_id } = await createOrder(storeId, 'TAKEOUT');

      // 2. 逐个加菜
      for (const item of cart) {
        await addItem(order_id, item.dish.id, item.dish.name, item.quantity, item.dish.priceFen);
      }

      // 3. 创建支付
      await createPayment(order_id, method, totalFen);

      // 4. 结算
      await settleOrder(order_id);

      // 5. 打印
      try {
        const { content_base64 } = await apiPrintReceipt(order_id);
        await bridgePrint(content_base64);
      } catch {
        // 打印失败不阻断
      }

      // 6. 现金弹钱箱
      if (method === 'cash') {
        try { await openCashBox(); } catch { /* ignore */ }
      }

      setPaySuccess(true);
      setCart([]);
      setTimeout(() => setPaySuccess(false), 3000);
    } catch (err) {
      alert(`收款失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setPaying(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: C.bg, color: C.text }}>
      {/* ═══ 左侧：分类 + 菜品列表 ═══ */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: `1px solid ${C.border}` }}>
        {/* 顶部导航 */}
        <div style={{
          padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12,
          borderBottom: `1px solid ${C.border}`, flexShrink: 0,
        }}>
          <button
            onClick={() => navigate('/tables')}
            style={{
              minHeight: 48, minWidth: 48, padding: '8px 16px',
              background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
              color: C.text, fontSize: 16, cursor: 'pointer',
            }}
          >
            {'<'} 桌台
          </button>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: C.white }}>
            快速收银
          </h2>
          <span style={{ fontSize: 16, color: C.muted }}>外卖 / 打包 / 快餐</span>
        </div>

        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* 分类侧栏 */}
          <div style={{
            width: 100, overflowY: 'auto', WebkitOverflowScrolling: 'touch',
            background: C.card, flexShrink: 0,
          }}>
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                style={{
                  width: '100%', minHeight: 56, padding: '12px 8px',
                  background: activeCategory === cat ? C.bg : 'transparent',
                  border: 'none', borderLeft: activeCategory === cat ? `3px solid ${C.accent}` : '3px solid transparent',
                  color: activeCategory === cat ? C.accent : C.muted,
                  fontSize: 16, fontWeight: activeCategory === cat ? 700 : 400,
                  cursor: 'pointer', textAlign: 'center',
                }}
              >
                {cat}
              </button>
            ))}
          </div>

          {/* 菜品网格 */}
          <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: 12 }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
              gap: 10,
            }}>
              {filteredDishes.map(dish => {
                const inCart = cart.find(c => c.dish.id === dish.id);
                return (
                  <button
                    key={dish.id}
                    onClick={() => addToCart(dish)}
                    disabled={!dish.isAvailable}
                    style={{
                      padding: 12, borderRadius: 12, textAlign: 'center',
                      background: dish.isAvailable ? C.card : `${C.muted}22`,
                      border: inCart ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                      color: dish.isAvailable ? C.white : C.muted,
                      cursor: dish.isAvailable ? 'pointer' : 'not-allowed',
                      opacity: dish.isAvailable ? 1 : 0.5,
                      transition: 'transform 200ms ease',
                      position: 'relative',
                      minHeight: 100,
                      display: 'flex', flexDirection: 'column',
                      alignItems: 'center', justifyContent: 'center', gap: 6,
                    }}
                    onPointerDown={e => {
                      if (dish.isAvailable) (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
                    }}
                    onPointerUp={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
                    onPointerLeave={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
                  >
                    {/* 已点数量角标 */}
                    {inCart && (
                      <span style={{
                        position: 'absolute', top: -6, right: -6,
                        width: 24, height: 24, borderRadius: '50%',
                        background: C.accent, color: C.white,
                        fontSize: 16, fontWeight: 700,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {inCart.quantity}
                      </span>
                    )}

                    {/* 沽清遮罩 */}
                    {!dish.isAvailable && (
                      <span style={{
                        position: 'absolute', inset: 0, borderRadius: 12,
                        background: 'rgba(0,0,0,0.5)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 18, fontWeight: 700, color: C.red,
                      }}>
                        已沽清
                      </span>
                    )}

                    <div style={{ fontSize: 18, fontWeight: 600 }}>{dish.name}</div>
                    <div style={{ fontSize: 18, color: C.accent, fontWeight: 700 }}>
                      {fen2yuan(dish.priceFen)}
                    </div>
                  </button>
                );
              })}
              {filteredDishes.length === 0 && (
                <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: 40, color: C.muted, fontSize: 18 }}>
                  该分类暂无菜品
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 底部扫码栏 */}
        <div style={{
          padding: '12px 16px', borderTop: `1px solid ${C.border}`,
          display: 'flex', gap: 12, alignItems: 'center', flexShrink: 0,
        }}>
          <span style={{ fontSize: 18, color: C.muted, flexShrink: 0 }}>扫码:</span>
          <input
            ref={scanInputRef}
            value={scanValue}
            onChange={e => setScanValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                handleScan(scanValue);
              }
            }}
            placeholder="扫码枪自动输入 / 手动输入菜品编码"
            style={{
              flex: 1, minHeight: 48, padding: '0 16px',
              background: C.card, border: `1px solid ${C.border}`,
              borderRadius: 8, color: C.white, fontSize: 18,
              outline: 'none',
            }}
          />
        </div>
      </div>

      {/* ═══ 右侧：购物车 + 收款 ═══ */}
      <div style={{
        width: 360, display: 'flex', flexDirection: 'column',
        background: C.card, flexShrink: 0,
      }}>
        {/* 购物车标题 */}
        <div style={{
          padding: '12px 16px', borderBottom: `1px solid ${C.border}`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <h3 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: C.white }}>
            购物车
            {totalCount > 0 && (
              <span style={{
                marginLeft: 8, fontSize: 16, padding: '2px 8px',
                background: C.accent, borderRadius: 12,
              }}>
                {totalCount}
              </span>
            )}
          </h3>
          {cart.length > 0 && (
            <button
              onClick={clearCart}
              style={{
                minHeight: 48, padding: '8px 16px',
                background: 'transparent', border: `1px solid ${C.border}`,
                borderRadius: 8, color: C.muted, fontSize: 16, cursor: 'pointer',
              }}
            >
              清空
            </button>
          )}
        </div>

        {/* 购物车列表 */}
        <div style={{
          flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch',
          padding: '8px 0',
        }}>
          {cart.length === 0 && (
            <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 18 }}>
              {paySuccess ? '收款成功，等待下一单' : '点击菜品加入购物车'}
            </div>
          )}
          {cart.map(item => (
            <div
              key={item.dish.id}
              style={{
                padding: '10px 16px',
                borderBottom: `1px solid ${C.border}`,
                display: 'flex', alignItems: 'center', gap: 12,
              }}
            >
              {/* 菜名+单价 */}
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18, fontWeight: 600, color: C.white }}>{item.dish.name}</div>
                <div style={{ fontSize: 16, color: C.muted }}>{fen2yuan(item.dish.priceFen)}</div>
              </div>

              {/* 数量调节 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button
                  onClick={() => updateQuantity(item.dish.id, -1)}
                  style={{
                    width: 48, height: 48, borderRadius: 8,
                    background: C.bg, border: `1px solid ${C.border}`,
                    color: C.text, fontSize: 22, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  -
                </button>
                <span style={{ fontSize: 20, fontWeight: 700, minWidth: 32, textAlign: 'center', color: C.white }}>
                  {item.quantity}
                </span>
                <button
                  onClick={() => updateQuantity(item.dish.id, 1)}
                  style={{
                    width: 48, height: 48, borderRadius: 8,
                    background: C.accent, border: 'none',
                    color: C.white, fontSize: 22, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  +
                </button>
              </div>

              {/* 小计 */}
              <div style={{ fontSize: 18, fontWeight: 700, color: C.accent, minWidth: 64, textAlign: 'right' }}>
                {fen2yuan(item.dish.priceFen * item.quantity)}
              </div>
            </div>
          ))}
        </div>

        {/* 合计 + 收款按钮 */}
        <div style={{
          padding: 16, borderTop: `1px solid ${C.border}`,
          flexShrink: 0,
        }}>
          {/* 成功提示 */}
          {paySuccess && (
            <div style={{
              background: `${C.green}22`, border: `1px solid ${C.green}`,
              borderRadius: 8, padding: 12, marginBottom: 12,
              textAlign: 'center', fontSize: 18, fontWeight: 700, color: C.green,
            }}>
              收款成功
            </div>
          )}

          {/* 合计 */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
            marginBottom: 12,
          }}>
            <span style={{ fontSize: 18, color: C.muted }}>合计</span>
            <span style={{ fontSize: 28, fontWeight: 700, color: C.accent }}>
              ¥{fen2yuan(totalFen)}
            </span>
          </div>

          {/* 收款按钮组 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <button
              onClick={() => handlePay('wechat')}
              disabled={paying || cart.length === 0}
              style={{
                minHeight: 56, borderRadius: 12, border: 'none',
                background: paying ? C.muted : '#07C160',
                color: C.white, fontSize: 18, fontWeight: 700,
                cursor: paying || cart.length === 0 ? 'not-allowed' : 'pointer',
                opacity: cart.length === 0 ? 0.4 : 1,
              }}
            >
              {paying ? '处理中...' : '微信'}
            </button>
            <button
              onClick={() => handlePay('alipay')}
              disabled={paying || cart.length === 0}
              style={{
                minHeight: 56, borderRadius: 12, border: 'none',
                background: paying ? C.muted : '#1677FF',
                color: C.white, fontSize: 18, fontWeight: 700,
                cursor: paying || cart.length === 0 ? 'not-allowed' : 'pointer',
                opacity: cart.length === 0 ? 0.4 : 1,
              }}
            >
              {paying ? '处理中...' : '支付宝'}
            </button>
            <button
              onClick={() => handlePay('cash')}
              disabled={paying || cart.length === 0}
              style={{
                minHeight: 56, borderRadius: 12, border: 'none',
                background: paying ? C.muted : C.yellow,
                color: C.white, fontSize: 18, fontWeight: 700,
                cursor: paying || cart.length === 0 ? 'not-allowed' : 'pointer',
                opacity: cart.length === 0 ? 0.4 : 1,
              }}
            >
              {paying ? '处理中...' : '现金'}
            </button>
            <button
              onClick={() => handlePay('unionpay')}
              disabled={paying || cart.length === 0}
              style={{
                minHeight: 56, borderRadius: 12, border: 'none',
                background: paying ? C.muted : '#e6002d',
                color: C.white, fontSize: 18, fontWeight: 700,
                cursor: paying || cart.length === 0 ? 'not-allowed' : 'pointer',
                opacity: cart.length === 0 ? 0.4 : 1,
              }}
            >
              {paying ? '处理中...' : '银联'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
