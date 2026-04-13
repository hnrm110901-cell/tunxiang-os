/**
 * 三栏点餐页 — /order/:orderId
 * P0-07: 左栏分类 | 中栏菜品网格 | 右栏购物车+下单
 *
 * 布局比例: 10% 分类 | 55% 菜品 | 35% 购物车
 * 遵循 TXTouch 规范: 最小触控48px, 字体>=16px, 暗色主题, 无Ant Design
 *
 * API: GET  /api/v1/menu/dishes?store_id=
 *      GET  /api/v1/menu/categories?store_id=
 *      POST /api/v1/trade/orders/{id}/items
 *      POST /api/v1/trade/orders/{id}/actions/submit
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { createOrder, addItem as apiAddItem, removeItem as apiRemoveItem, getOrder } from '../api/tradeApi';
import { fetchDishes, fetchCategories, type DishItem } from '../api/menuApi';
import { LiveSeafoodOrderSheet } from '../components/LiveSeafoodOrderSheet';
import { ComboSelectorSheet } from '../components/ComboSelectorSheet';
import DishRecommendBanner from '../components/DishRecommendBanner';
import type { LiveSeafoodOrderSheetProps } from '../components/LiveSeafoodOrderSheet';
import type { ComboSelectorSheetProps } from '../components/ComboSelectorSheet';
import { formatPrice } from '@tx-ds/utils';

// ─── 扩展类型 ──────────────────────────────────────────────────────────────────

interface ExtendedDishItem extends DishItem {
  pricingMethod: 'normal' | 'weight' | 'count';
  weightUnit?: 'jin' | 'liang' | 'kg' | 'g';
  displayUnit?: string;
  minOrderQty?: number;
  tankZoneName?: string;
  comboType?: 'fixed' | 'flexible';
  comboPriceFen?: number;
  originalPriceFen?: number;
  comboGroups?: ComboSelectorSheetProps['combo']['groups'];
  spicy?: number; // 辣度 0-3
  tags?: string[];
}

// ─── Fallback 菜品 ──────────────────────────────────────────────────────────────

const FALLBACK_CATEGORIES = ['招牌菜', '热菜', '凉菜', '活鲜', '汤羹', '主食', '饮品', '套餐'];

const FALLBACK_DISHES: ExtendedDishItem[] = [
  { id: 'd01', name: '剁椒鱼头', priceFen: 8800, category: '招牌菜', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal', spicy: 2, tags: ['招牌'] },
  { id: 'd02', name: '农家小炒肉', priceFen: 4200, category: '热菜', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal', spicy: 1 },
  { id: 'd03', name: '口味虾', priceFen: 12800, category: '招牌菜', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal', spicy: 3, tags: ['招牌', '季节'] },
  { id: 'd04', name: '辣椒炒肉', priceFen: 3800, category: '热菜', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal', spicy: 2 },
  { id: 'd05', name: '红烧肉', priceFen: 5800, category: '热菜', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd06', name: '蒜蓉粉丝蒸扇贝', priceFen: 6800, category: '热菜', kitchenStation: '蒸菜档', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd07', name: '凉拌黄瓜', priceFen: 900, category: '凉菜', kitchenStation: '凉菜档', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd08', name: '夫妻肺片', priceFen: 3200, category: '凉菜', kitchenStation: '凉菜档', isAvailable: true, pricingMethod: 'normal', spicy: 2 },
  { id: 'd09', name: '皮蛋豆腐', priceFen: 1800, category: '凉菜', kitchenStation: '凉菜档', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd10', name: '鲈鱼（活）', priceFen: 5800, category: '活鲜', kitchenStation: '活鲜档', isAvailable: true, pricingMethod: 'weight', weightUnit: 'jin', displayUnit: '斤', minOrderQty: 0.5, tankZoneName: 'A区3号缸' },
  { id: 'd11', name: '基围虾（活）', priceFen: 9800, category: '活鲜', kitchenStation: '活鲜档', isAvailable: true, pricingMethod: 'weight', weightUnit: 'jin', displayUnit: '斤', minOrderQty: 1, tankZoneName: 'B区1号缸' },
  { id: 'd12', name: '皮皮虾', priceFen: 8800, category: '活鲜', kitchenStation: '活鲜档', isAvailable: false, pricingMethod: 'weight', weightUnit: 'jin', displayUnit: '斤' },
  { id: 'd13', name: '番茄蛋汤', priceFen: 1200, category: '汤羹', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd14', name: '酸菜鱼汤', priceFen: 4800, category: '汤羹', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal', spicy: 1 },
  { id: 'd15', name: '米饭', priceFen: 300, category: '主食', kitchenStation: 'default', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd16', name: '蛋炒饭', priceFen: 1800, category: '主食', kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd17', name: '酸梅汤', priceFen: 800, category: '饮品', kitchenStation: 'default', isAvailable: true, pricingMethod: 'normal' },
  { id: 'd18', name: '鲜榨橙汁', priceFen: 1500, category: '饮品', kitchenStation: 'default', isAvailable: true, pricingMethod: 'normal' },
  {
    id: 'cb1', name: '家庭欢乐套餐', priceFen: 19800, category: '套餐', kitchenStation: 'default', isAvailable: true,
    pricingMethod: 'normal', comboType: 'flexible', comboPriceFen: 19800, originalPriceFen: 23800,
    comboGroups: [
      { id: 'cg1', groupName: '主菜（选2）', minSelect: 2, maxSelect: 2, isRequired: true, items: [
        { id: 'ci1', dishId: 'd01', dishName: '剁椒鱼头', quantity: 1, extraPriceFen: 0 },
        { id: 'ci2', dishId: 'd02', dishName: '农家小炒肉', quantity: 1, extraPriceFen: 0 },
        { id: 'ci3', dishId: 'd03', dishName: '口味虾', quantity: 1, extraPriceFen: 2000 },
      ]},
      { id: 'cg2', groupName: '凉菜（选1）', minSelect: 1, maxSelect: 1, isRequired: true, items: [
        { id: 'ci4', dishId: 'd07', dishName: '凉拌黄瓜', quantity: 1, extraPriceFen: 0 },
        { id: 'ci5', dishId: 'd08', dishName: '夫妻肺片', quantity: 1, extraPriceFen: 500 },
      ]},
      { id: 'cg3', groupName: '饮品（选0-2）', minSelect: 0, maxSelect: 2, isRequired: false, items: [
        { id: 'ci6', dishId: 'd17', dishName: '酸梅汤', quantity: 1, extraPriceFen: 0 },
        { id: 'ci7', dishId: 'd18', dishName: '鲜榨橙汁', quantity: 1, extraPriceFen: 300 },
      ]},
    ],
  },
];

// ─── 辅助 ──────────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

const SPICY_ICONS = ['', '🌶', '🌶🌶', '🌶🌶🌶'];

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function OrderPage() {
  const { orderId: routeOrderId } = useParams();
  const navigate = useNavigate();
  const store = useOrderStore();
  const { items, totalFen, discountFen, orderId } = store;
  const finalFen = totalFen - discountFen;

  // 数据状态
  const [loading, setLoading] = useState(false);
  const [dishes, setDishes] = useState<ExtendedDishItem[]>(FALLBACK_DISHES);
  const [categories, setCategories] = useState<string[]>(FALLBACK_CATEGORIES);
  const [activeCategory, setActiveCategory] = useState<string>('全部');
  const [searchText, setSearchText] = useState('');
  const [tableNo, setTableNo] = useState(store.tableNo || '');
  const [showRecommend, setShowRecommend] = useState(true);

  // 弹层
  const [seafoodSheet, setSeafoodSheet] = useState<{ visible: boolean; dish: ExtendedDishItem | null }>({ visible: false, dish: null });
  const [comboSheet, setComboSheet] = useState<{ visible: boolean; dish: ExtendedDishItem | null }>({ visible: false, dish: null });
  const [showNoteModal, setShowNoteModal] = useState<string | null>(null);
  const [noteText, setNoteText] = useState('');

  // ─── 初始化 ────────────────────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true);

    Promise.all([
      fetchDishes(STORE_ID).then(d => {
        if (d.length > 0) {
          const extended: ExtendedDishItem[] = d.map(item => ({ ...item, pricingMethod: 'normal' as const }));
          setDishes([...extended, ...FALLBACK_DISHES.filter(fd => fd.pricingMethod === 'weight' || fd.comboType === 'flexible')]);
        }
      }),
      fetchCategories(STORE_ID).then(c => {
        if (c.length > 0) setCategories(c);
      }),
      routeOrderId && routeOrderId !== 'new'
        ? getOrder(routeOrderId).then((order: Record<string, unknown>) => {
            store.setOrder(routeOrderId, (order.order_no as string) || '', (order.table_no as string) || '');
            setTableNo((order.table_no as string) || '');
          }).catch(() => {})
        : Promise.resolve(),
    ]).finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── 分类筛选 ──────────────────────────────────────────────────────────────

  const filteredDishes = useMemo(() => {
    let result = dishes;
    if (activeCategory !== '全部') {
      result = result.filter(d => d.category === activeCategory);
    }
    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      result = result.filter(d => d.name.toLowerCase().includes(q));
    }
    return result;
  }, [dishes, activeCategory, searchText]);

  const dishCountByCategory = useMemo(() => {
    const counts: Record<string, number> = { '全部': dishes.length };
    for (const d of dishes) {
      counts[d.category] = (counts[d.category] || 0) + 1;
    }
    return counts;
  }, [dishes]);

  // ─── 菜品操作 ──────────────────────────────────────────────────────────────

  const handleDishPress = useCallback((dish: ExtendedDishItem) => {
    if (!dish.isAvailable) return;

    if (dish.pricingMethod === 'weight' || dish.pricingMethod === 'count') {
      setSeafoodSheet({ visible: true, dish });
      return;
    }

    if (dish.comboType === 'flexible' && dish.comboGroups) {
      setComboSheet({ visible: true, dish });
      return;
    }

    addNormalDish(dish);
  }, [items, orderId]); // eslint-disable-line react-hooks/exhaustive-deps

  const addNormalDish = async (dish: ExtendedDishItem) => {
    const existing = items.find(i => i.dishId === dish.id);
    if (existing) {
      store.updateQuantity(existing.id, existing.quantity + 1);
    } else {
      store.addItem({
        dishId: dish.id, name: dish.name, quantity: 1,
        priceFen: dish.priceFen, notes: '', kitchenStation: dish.kitchenStation,
      });
    }
    if (orderId) {
      apiAddItem(orderId, dish.id, dish.name, 1, dish.priceFen).catch(() => {});
    }
  };

  const handleSeafoodConfirm: LiveSeafoodOrderSheetProps['onConfirm'] = (weighRecordId, qty, amountFen) => {
    const dish = seafoodSheet.dish;
    if (!dish) return;
    store.addItem({
      dishId: dish.id, name: `${dish.name}（${qty.toFixed(2)}${dish.displayUnit ?? ''}）`,
      quantity: 1, priceFen: amountFen, notes: `称重记录:${weighRecordId}`, kitchenStation: dish.kitchenStation,
    });
    if (orderId) apiAddItem(orderId, dish.id, dish.name, qty, dish.priceFen).catch(() => {});
  };

  const handleComboConfirm: ComboSelectorSheetProps['onConfirm'] = (selections) => {
    const dish = comboSheet.dish;
    if (!dish) return;
    const selectedNames = selections
      .flatMap(s => {
        const group = dish.comboGroups?.find(g => g.id === s.groupId);
        return (group?.items ?? []).filter(item => s.itemIds.includes(item.id)).map(item => item.dishName);
      }).join('、');
    store.addItem({
      dishId: dish.id, name: dish.name, quantity: 1,
      priceFen: dish.comboPriceFen ?? dish.priceFen,
      notes: selectedNames ? `已选：${selectedNames}` : '', kitchenStation: dish.kitchenStation,
    });
    if (orderId) apiAddItem(orderId, dish.id, dish.name, 1, dish.comboPriceFen ?? dish.priceFen).catch(() => {});
  };

  // ─── 购物车操作 ────────────────────────────────────────────────────────────

  const handleQtyChange = (itemId: string, delta: number) => {
    const item = items.find(i => i.id === itemId);
    if (!item) return;
    const newQty = item.quantity + delta;
    if (newQty <= 0) {
      store.removeItem(itemId);
      if (orderId) apiRemoveItem(orderId, itemId).catch(() => {});
    } else {
      store.updateQuantity(itemId, newQty);
    }
  };

  const handleSubmitOrder = async () => {
    if (items.length === 0) return;
    let activeOrderId = orderId;
    if (!activeOrderId && tableNo) {
      try {
        const res = await createOrder(STORE_ID, tableNo);
        store.setOrder(res.order_id, res.order_no, tableNo);
        activeOrderId = res.order_id;
        for (const item of items) {
          await apiAddItem(activeOrderId, item.dishId, item.name, item.quantity, item.priceFen).catch(() => {});
        }
      } catch {
        // 离线模式: 直接跳转结算
      }
    }
    navigate(`/settle/${activeOrderId ?? 'temp'}`);
  };

  const handleHoldOrder = () => {
    navigate('/tables');
  };

  // ─── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={{
      display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
    }}>

      {/* ═══ 左栏: 分类导航 (10%) ═══ */}
      <div style={{
        width: 110, minWidth: 110, background: '#081418',
        display: 'flex', flexDirection: 'column',
        borderRight: '1px solid #1a2a33',
        overflowY: 'auto', WebkitOverflowScrolling: 'touch' as never,
      }}>
        <button
          type="button"
          onClick={() => navigate('/tables')}
          style={{
            padding: '14px 8px', background: 'transparent', border: 'none', borderBottom: '1px solid #1a2a33',
            color: '#9CA3AF', fontSize: 14, cursor: 'pointer', textAlign: 'center', minHeight: 48,
          }}
        >
          ← 桌台
        </button>

        <CategoryBtn label="全部" count={dishCountByCategory['全部'] || 0} active={activeCategory === '全部'} onClick={() => setActiveCategory('全部')} />
        {categories.map(cat => (
          <CategoryBtn key={cat} label={cat} count={dishCountByCategory[cat] || 0} active={activeCategory === cat} onClick={() => setActiveCategory(cat)} />
        ))}
      </div>

      {/* ═══ 中栏: 菜品网格 (55%) ═══ */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* 顶部栏 */}
        <div style={{
          padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderBottom: '1px solid #1a2a33', gap: 12,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18, fontWeight: 600 }}>
              {tableNo ? `${tableNo}号桌` : '点餐'}
            </span>
            {store.orderNo && (
              <span style={{ fontSize: 14, color: '#52c41a', background: 'rgba(82,196,26,0.1)', padding: '2px 8px', borderRadius: 4 }}>
                {store.orderNo}
              </span>
            )}
            {loading && <span style={{ color: '#faad14', fontSize: 14 }}>加载中...</span>}
          </div>
          <div style={{ position: 'relative', width: 220 }}>
            <input
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              placeholder="搜索菜品..."
              style={{
                width: '100%', padding: '8px 12px 8px 32px', background: '#112228',
                border: '1px solid #1a2a33', borderRadius: 8, color: '#fff', fontSize: 14,
                outline: 'none', boxSizing: 'border-box',
              }}
            />
            <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#6B7280', fontSize: 14, pointerEvents: 'none' }}>🔍</span>
          </div>
        </div>

        {/* AI推荐 */}
        {showRecommend && tableNo && (
          <div style={{ padding: '8px 16px 0' }}>
            <DishRecommendBanner tableNo={tableNo} onDismiss={() => setShowRecommend(false)} />
          </div>
        )}

        {/* 菜品网格 */}
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as never, padding: 16 }}>
          {filteredDishes.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#6B7280', paddingTop: 60, fontSize: 16 }}>
              {searchText ? '没有找到匹配的菜品' : '该分类暂无菜品'}
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
              {filteredDishes.map(d => {
                const inOrder = items.find(i => i.dishId === d.id);
                const isSpecial = d.pricingMethod === 'weight' || d.pricingMethod === 'count' || d.comboType === 'flexible';

                return (
                  <div
                    key={d.id}
                    role="button"
                    tabIndex={0}
                    aria-label={d.name}
                    onClick={() => handleDishPress(d)}
                    onKeyDown={e => e.key === 'Enter' && handleDishPress(d)}
                    style={{
                      position: 'relative', padding: 14, borderRadius: 10,
                      background: d.isAvailable ? '#1a2a33' : '#111c22',
                      cursor: d.isAvailable ? 'pointer' : 'not-allowed',
                      textAlign: 'center', minHeight: 100,
                      border: inOrder ? '2px solid #FF6B35' : isSpecial ? '1.5px solid rgba(255,107,53,0.3)' : '1.5px solid transparent',
                      opacity: d.isAvailable ? 1 : 0.45,
                      transition: 'transform 150ms ease, border-color 150ms ease',
                      userSelect: 'none', WebkitUserSelect: 'none' as never,
                      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4,
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: 17, color: '#fff', lineHeight: 1.3 }}>{d.name}</div>
                    {d.spicy && d.spicy > 0 && <div style={{ fontSize: 12 }}>{SPICY_ICONS[d.spicy]}</div>}
                    <div style={{ color: '#FF6B35', fontSize: 16, fontWeight: 600 }}>
                      {d.comboType === 'flexible' && d.comboPriceFen
                        ? fen2yuan(d.comboPriceFen)
                        : d.pricingMethod === 'weight' || d.pricingMethod === 'count'
                          ? `${fen2yuan(d.priceFen)}/${d.displayUnit ?? '份'}`
                          : fen2yuan(d.priceFen)}
                    </div>
                    {d.pricingMethod === 'weight' && <div style={{ fontSize: 12, color: '#52c41a' }}>⚖ 按重量</div>}
                    {d.comboType === 'flexible' && <div style={{ fontSize: 12, color: '#1890ff' }}>📋 套餐</div>}
                    {d.tags?.includes('招牌') && <div style={{ fontSize: 11, color: '#FF6B35', background: 'rgba(255,107,53,0.15)', padding: '1px 6px', borderRadius: 3 }}>招牌</div>}
                    {!d.isAvailable && (
                      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, color: '#aaa', fontWeight: 600 }}>
                        已沽清
                      </div>
                    )}
                    {inOrder && (
                      <div style={{ position: 'absolute', top: 6, right: 6, width: 24, height: 24, borderRadius: '50%', background: '#FF6B35', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700 }}>
                        {inOrder.quantity}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ═══ 右栏: 购物车 + 下单 (35%) ═══ */}
      <div style={{
        width: 340, minWidth: 300, background: '#112228',
        display: 'flex', flexDirection: 'column', borderLeft: '1px solid #1a2a33',
      }}>
        {/* 头部 */}
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #1a2a33', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 18, fontWeight: 600 }}>
            当前订单
            {items.length > 0 && <span style={{ fontSize: 14, color: '#9CA3AF', fontWeight: 400, marginLeft: 6 }}>{items.reduce((s, i) => s + i.quantity, 0)}道</span>}
          </span>
          {items.length > 0 && (
            <button type="button" onClick={() => store.clear()} style={{ padding: '4px 10px', background: 'transparent', border: '1px solid #A32D2D', borderRadius: 6, color: '#A32D2D', fontSize: 13, cursor: 'pointer', minHeight: 32, minWidth: 48 }}>
              清空
            </button>
          )}
        </div>

        {/* 列表 */}
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as never, padding: '0 16px' }}>
          {items.length === 0 ? (
            <div style={{ color: '#6B7280', textAlign: 'center', paddingTop: 60, fontSize: 16 }}>点击左侧菜品加入订单</div>
          ) : items.map(item => (
            <div key={item.id} style={{ padding: '12px 0', borderBottom: '1px solid #1a2a33' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.3 }}>{item.name}</div>
                  {item.notes && <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.notes}</div>}
                  <div style={{ fontSize: 14, color: '#FF6B35', marginTop: 3, fontWeight: 500 }}>{fen2yuan(item.priceFen * item.quantity)}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                  <button type="button" onClick={() => handleQtyChange(item.id, -1)} style={qtyBtnStyle}>−</button>
                  <span style={{ fontSize: 18, fontWeight: 600, minWidth: 24, textAlign: 'center' }}>{item.quantity}</span>
                  <button type="button" onClick={() => handleQtyChange(item.id, +1)} style={qtyBtnStyle}>+</button>
                </div>
              </div>
              <button
                type="button"
                onClick={() => { setShowNoteModal(item.id); setNoteText(item.notes); }}
                style={{ marginTop: 4, padding: '2px 8px', background: 'transparent', border: '1px solid #333', borderRadius: 4, color: '#6B7280', fontSize: 12, cursor: 'pointer' }}
              >
                {item.notes ? '改备注' : '+ 备注'}
              </button>
            </div>
          ))}
        </div>

        {/* 合计 + 操作 */}
        <div style={{ borderTop: '1px solid #333', padding: 16 }}>
          {discountFen > 0 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, color: '#52c41a', marginBottom: 8 }}>
              <span>优惠</span><span>-{fen2yuan(discountFen)}</span>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 22, fontWeight: 700, color: '#FF6B35', marginBottom: 14 }}>
            <span>合计</span><span>{fen2yuan(finalFen)}</span>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button type="button" onClick={handleHoldOrder} style={{ flex: 1, padding: '14px 0', background: '#1a2a33', color: '#fff', border: '1px solid #333', borderRadius: 8, fontSize: 16, fontWeight: 500, cursor: 'pointer', minHeight: 52 }}>
              挂单
            </button>
            <button type="button" onClick={handleSubmitOrder} disabled={items.length === 0} style={{ flex: 2, padding: '14px 0', background: items.length > 0 ? '#FF6B35' : '#444', color: '#fff', border: 'none', borderRadius: 8, fontSize: 18, fontWeight: 600, cursor: items.length > 0 ? 'pointer' : 'not-allowed', minHeight: 52 }}>
              下单结算
            </button>
          </div>
        </div>
      </div>

      {/* ═══ 弹层 ═══ */}

      {seafoodSheet.dish && (
        <LiveSeafoodOrderSheet
          visible={seafoodSheet.visible}
          dish={{
            id: seafoodSheet.dish.id, name: seafoodSheet.dish.name,
            pricingMethod: (seafoodSheet.dish.pricingMethod === 'weight' || seafoodSheet.dish.pricingMethod === 'count') ? seafoodSheet.dish.pricingMethod : 'weight',
            pricePerUnitFen: seafoodSheet.dish.priceFen, weightUnit: seafoodSheet.dish.weightUnit ?? 'jin',
            displayUnit: seafoodSheet.dish.displayUnit ?? '斤', minOrderQty: seafoodSheet.dish.minOrderQty ?? 0.5,
            tankZoneName: seafoodSheet.dish.tankZoneName,
          }}
          storeId={STORE_ID} orderId={orderId ?? undefined}
          onConfirm={handleSeafoodConfirm} onClose={() => setSeafoodSheet({ visible: false, dish: null })}
        />
      )}

      {comboSheet.dish && comboSheet.dish.comboGroups && (
        <ComboSelectorSheet
          visible={comboSheet.visible}
          combo={{
            id: comboSheet.dish.id, comboName: comboSheet.dish.name,
            comboPriceFen: comboSheet.dish.comboPriceFen ?? comboSheet.dish.priceFen,
            originalPriceFen: comboSheet.dish.originalPriceFen ?? 0, groups: comboSheet.dish.comboGroups,
          }}
          onConfirm={handleComboConfirm} onClose={() => setComboSheet({ visible: false, dish: null })}
        />
      )}

      {/* 备注弹窗 */}
      {showNoteModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowNoteModal(null)}>
          <div style={{ background: '#1a2a33', borderRadius: 12, padding: 20, width: 360, maxWidth: '90vw' }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>菜品备注</div>
            <textarea
              value={noteText} onChange={e => setNoteText(e.target.value)}
              placeholder="如：少盐、不要辣、加辣..." rows={3}
              style={{ width: '100%', padding: 10, background: '#112228', border: '1px solid #333', borderRadius: 8, color: '#fff', fontSize: 16, resize: 'vertical', boxSizing: 'border-box', outline: 'none' }}
            />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
              {['少盐', '少油', '不辣', '微辣', '加辣', '不要葱', '不要姜', '不要蒜', '打包'].map(tag => (
                <button key={tag} type="button" onClick={() => setNoteText(prev => prev ? `${prev}，${tag}` : tag)}
                  style={{ padding: '6px 12px', background: '#112228', border: '1px solid #333', borderRadius: 6, color: '#ccc', fontSize: 14, cursor: 'pointer', minHeight: 36 }}>
                  {tag}
                </button>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
              <button type="button" onClick={() => setShowNoteModal(null)} style={{ flex: 1, padding: '10px 0', background: '#333', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 48 }}>取消</button>
              <button type="button" onClick={() => {
                const item = items.find(i => i.id === showNoteModal);
                if (item) { store.removeItem(showNoteModal); const { id: _unused, ...rest } = item; store.addItem({ ...rest, notes: noteText }); }
                setShowNoteModal(null);
              }} style={{ flex: 1, padding: '10px 0', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, fontWeight: 500, cursor: 'pointer', minHeight: 48 }}>确定</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function CategoryBtn({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{
      padding: '14px 8px', background: active ? 'rgba(255,107,53,0.15)' : 'transparent',
      border: 'none', borderLeft: active ? '3px solid #FF6B35' : '3px solid transparent',
      color: active ? '#FF6B35' : '#ccc', fontSize: 15, fontWeight: active ? 600 : 400,
      cursor: 'pointer', textAlign: 'center', minHeight: 48, transition: 'background 150ms, color 150ms',
    }}>
      <div>{label}</div>
      <div style={{ fontSize: 12, color: active ? '#FF6B35' : '#6B7280', marginTop: 2 }}>{count}</div>
    </button>
  );
}

const qtyBtnStyle: React.CSSProperties = {
  width: 36, height: 36, borderRadius: '50%', border: '1px solid #555',
  background: 'transparent', color: '#fff', fontSize: 20, fontWeight: 600,
  cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', minWidth: 36,
};
