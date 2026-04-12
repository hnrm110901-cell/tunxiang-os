/**
 * 收银/点餐页面 — 对接 tx-trade API
 * 左侧菜品列表 + 右侧购物车
 *
 * 2026-04-02 新增：
 *   - 活鲜菜品（pricingMethod='weight'）点击 → LiveSeafoodOrderSheet
 *   - N选M套餐（comboType='flexible'）点击 → ComboSelectorSheet
 *
 * 2026-04-12 重构：使用 @tx-ds/biz 共享组件替换内联 UI
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { createOrder, addItem as apiAddItem } from '../api/tradeApi';
import { fetchDishes, type DishItem } from '../api/menuApi';
import { DishCard, CategoryNav, MenuSearch, CartPanel } from '@tx-ds/biz';
import type { DishData, CartItem } from '@tx-ds/biz';
import { formatPrice } from '@tx-ds/utils';
import { LiveSeafoodOrderSheet } from '../components/LiveSeafoodOrderSheet';
import { ComboSelectorSheet } from '../components/ComboSelectorSheet';
import type { LiveSeafoodOrderSheetProps } from '../components/LiveSeafoodOrderSheet';
import type { ComboSelectorSheetProps } from '../components/ComboSelectorSheet';

// ─── 扩展菜品类型（增加活鲜/套餐字段）────────────────────────────────────────

interface ExtendedDishItem extends DishItem {
  /** 'normal' | 'weight' = 按重量计费（活鲜）| 'count' = 按件计费 */
  pricingMethod: 'normal' | 'weight' | 'count';
  /** 仅 pricingMethod='weight'/'count' 时有效 */
  weightUnit?: 'jin' | 'liang' | 'kg' | 'g';
  displayUnit?: string;
  minOrderQty?: number;
  tankZoneName?: string;
  /** 'flexible' = N选M套餐 */
  comboType?: 'fixed' | 'flexible';
  comboPriceFen?: number;
  originalPriceFen?: number;
  comboGroups?: ComboSelectorSheetProps['combo']['groups'];
}

// ─── 扩展 fallback 菜品数据 ───────────────────────────────────────────────────

const FALLBACK_DISHES: ExtendedDishItem[] = [
  {
    id: 'd1', name: '剁椒鱼头', priceFen: 8800, category: '热菜',
    kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal',
  },
  {
    id: 'd2', name: '农家小炒肉', priceFen: 4200, category: '热菜',
    kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal',
  },
  {
    id: 'd3', name: '凉拌黄瓜', priceFen: 900, category: '凉菜',
    kitchenStation: '凉菜档', isAvailable: true, pricingMethod: 'normal',
  },
  {
    id: 'd4', name: '口味虾', priceFen: 12800, category: '热菜',
    kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal',
  },
  {
    id: 'd5', name: '米饭', priceFen: 300, category: '主食',
    kitchenStation: 'default', isAvailable: true, pricingMethod: 'normal',
  },
  {
    id: 'd6', name: '酸梅汤', priceFen: 800, category: '饮品',
    kitchenStation: 'default', isAvailable: true, pricingMethod: 'normal',
  },
  // 活鲜示例
  {
    id: 'ls1', name: '鲈鱼（活）', priceFen: 5800, category: '活鲜',
    kitchenStation: '活鲜档', isAvailable: true,
    pricingMethod: 'weight',
    weightUnit: 'jin',
    displayUnit: '斤',
    minOrderQty: 0.5,
    tankZoneName: 'A区3号缸',
  },
  {
    id: 'ls2', name: '基围虾（活）', priceFen: 9800, category: '活鲜',
    kitchenStation: '活鲜档', isAvailable: true,
    pricingMethod: 'weight',
    weightUnit: 'jin',
    displayUnit: '斤',
    minOrderQty: 1,
    tankZoneName: 'B区1号缸',
  },
  // N选M套餐示例
  {
    id: 'cb1', name: '家庭欢乐套餐', priceFen: 19800, category: '套餐',
    kitchenStation: 'default', isAvailable: true,
    pricingMethod: 'normal',
    comboType: 'flexible',
    comboPriceFen: 19800,
    originalPriceFen: 23800,
    comboGroups: [
      {
        id: 'cg1',
        groupName: '主菜',
        minSelect: 2,
        maxSelect: 2,
        isRequired: true,
        items: [
          { id: 'ci1', dishId: 'd1', dishName: '剁椒鱼头', quantity: 1, extraPriceFen: 0 },
          { id: 'ci2', dishId: 'd2', dishName: '农家小炒肉', quantity: 1, extraPriceFen: 0 },
          { id: 'ci3', dishId: 'd4', dishName: '口味虾', quantity: 1, extraPriceFen: 2000 },
        ],
      },
      {
        id: 'cg2',
        groupName: '凉菜',
        minSelect: 1,
        maxSelect: 1,
        isRequired: true,
        items: [
          { id: 'ci4', dishId: 'd3', dishName: '凉拌黄瓜', quantity: 1, extraPriceFen: 0 },
          { id: 'ci5', dishId: 'd3', dishName: '夫妻肺片', quantity: 1, extraPriceFen: 500 },
        ],
      },
      {
        id: 'cg3',
        groupName: '饮品',
        minSelect: 0,
        maxSelect: 2,
        isRequired: false,
        items: [
          { id: 'ci6', dishId: 'd6', dishName: '酸梅汤', quantity: 1, extraPriceFen: 0 },
          { id: 'ci7', dishId: 'd6', dishName: '鲜榨橙汁', quantity: 1, extraPriceFen: 300 },
        ],
      },
    ],
  },
];

const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

// ─── 数据转换 ─────────────────────────────────────────────────────────────────

/** ExtendedDishItem → DishData（共享组件接口） */
function toDishData(d: ExtendedDishItem): DishData {
  const tags: DishData['tags'] = [];
  if (d.pricingMethod === 'weight') tags.push({ type: 'seasonal', label: '按重量' });
  if (d.comboType === 'flexible') tags.push({ type: 'new', label: '套餐' });
  return {
    id: d.id,
    name: d.name,
    priceFen: d.comboType === 'flexible' && d.comboPriceFen ? d.comboPriceFen : d.priceFen,
    category: d.category,
    soldOut: !d.isAvailable,
    pricingMethod: d.pricingMethod,
    comboType: d.comboType,
    kitchenStation: d.kitchenStation,
    tags,
  };
}

// ─── 组件 ─────────────────────────────────────────────────────────────────────

export function CashierPage() {
  const { tableNo } = useParams();
  const navigate = useNavigate();
  const store = useOrderStore();
  const { items, totalFen, discountFen, orderId } = store;
  const [loading, setLoading] = useState(false);
  const [dishes, setDishes] = useState<ExtendedDishItem[]>(FALLBACK_DISHES);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');

  // 活鲜弹层状态
  const [seafoodSheet, setSeafoodSheet] = useState<{
    visible: boolean;
    dish: ExtendedDishItem | null;
  }>({ visible: false, dish: null });

  // 套餐弹层状态
  const [comboSheet, setComboSheet] = useState<{
    visible: boolean;
    dish: ExtendedDishItem | null;
  }>({ visible: false, dish: null });

  // 加载菜品（API优先，失败回退 mock）+ 自动开单
  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchDishes(STORE_ID).then((d) => {
        if (d.length > 0) {
          const extended: ExtendedDishItem[] = d.map((item) => ({ ...item, pricingMethod: 'normal' as const }));
          setDishes(extended);
        }
      }),
      !orderId && tableNo
        ? createOrder(STORE_ID, tableNo)
            .then((res) => store.setOrder(res.order_id, res.order_no, tableNo))
            .catch((e) => console.error('开单失败(离线模式):', e))
        : Promise.resolve(),
    ]).finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 分类列表 ────────────────────────────────────────────────────────────────

  const categories = useMemo(() => {
    const catSet = new Set(dishes.map((d) => d.category));
    return [
      { id: 'all', name: '全部' },
      ...Array.from(catSet).map((c) => ({ id: c, name: c })),
    ];
  }, [dishes]);

  // ── 菜品过滤（分类 + 搜索） ─────────────────────────────────────────────────

  const filteredDishes = useMemo(() => {
    let result = dishes;
    if (activeCategory !== 'all') {
      result = result.filter((d) => d.category === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter((d) => d.name.toLowerCase().includes(q));
    }
    return result;
  }, [dishes, activeCategory, searchQuery]);

  // ── 菜品点击路由 ────────────────────────────────────────────────────────────

  const handleDishPress = useCallback((dish: ExtendedDishItem) => {
    if (!dish.isAvailable) return;

    // 活鲜菜品 → 称重弹层
    if (dish.pricingMethod === 'weight' || dish.pricingMethod === 'count') {
      setSeafoodSheet({ visible: true, dish });
      return;
    }

    // N选M套餐 → 套餐选择弹层
    if (dish.comboType === 'flexible' && dish.comboGroups) {
      setComboSheet({ visible: true, dish });
      return;
    }

    // 普通菜品 → 直接加入订单
    handleAddNormalDish(dish);
  }, [items, orderId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAddNormalDish = useCallback(async (dish: ExtendedDishItem) => {
    const existing = items.find((i) => i.dishId === dish.id);
    if (existing) {
      store.updateQuantity(existing.id, existing.quantity + 1);
    } else {
      store.addItem({
        dishId: dish.id,
        name: dish.name,
        quantity: 1,
        priceFen: dish.priceFen,
        notes: '',
        kitchenStation: dish.kitchenStation,
      });
    }
    if (orderId) {
      apiAddItem(orderId, dish.id, dish.name, 1, dish.priceFen).catch(() => {});
    }
  }, [items, orderId, store]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 活鲜确认回调 ─────────────────────────────────────────────────────────────

  const handleSeafoodConfirm: LiveSeafoodOrderSheetProps['onConfirm'] = useCallback((
    weighRecordId,
    qty,
    amountFen,
  ) => {
    const dish = seafoodSheet.dish;
    if (!dish) return;

    store.addItem({
      dishId: dish.id,
      name: `${dish.name}（${qty.toFixed(2)}${dish.displayUnit ?? ''}）`,
      quantity: 1,
      priceFen: amountFen,
      notes: `称重记录:${weighRecordId}`,
      kitchenStation: dish.kitchenStation,
    });

    if (orderId) {
      apiAddItem(orderId, dish.id, dish.name, qty, dish.priceFen).catch(() => {});
    }
  }, [seafoodSheet.dish, orderId, store]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 套餐确认回调 ─────────────────────────────────────────────────────────────

  const handleComboConfirm: ComboSelectorSheetProps['onConfirm'] = useCallback((selections) => {
    const dish = comboSheet.dish;
    if (!dish) return;

    const selectedNames = selections
      .flatMap((s) => {
        const group = dish.comboGroups?.find((g) => g.id === s.groupId);
        return (group?.items ?? [])
          .filter((item) => s.itemIds.includes(item.id))
          .map((item) => item.dishName);
      })
      .join('、');

    store.addItem({
      dishId: dish.id,
      name: dish.name,
      quantity: 1,
      priceFen: dish.comboPriceFen ?? dish.priceFen,
      notes: selectedNames ? `已选：${selectedNames}` : '',
      kitchenStation: dish.kitchenStation,
    });

    if (orderId) {
      apiAddItem(
        orderId,
        dish.id,
        dish.name,
        1,
        dish.comboPriceFen ?? dish.priceFen,
      ).catch(() => {});
    }
  }, [comboSheet.dish, orderId, store]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── orderStore items → CartItem 映射 ─────────────────────────────────────────

  const cartItems: CartItem[] = useMemo(
    () => items.map((i) => ({
      id: i.id,
      dishId: i.dishId,
      name: i.name,
      quantity: i.quantity,
      priceFen: i.priceFen,
      notes: i.notes,
      kitchenStation: i.kitchenStation,
    })),
    [items],
  );

  // ── 辅助函数 ─────────────────────────────────────────────────────────────────

  const getQuantityForDish = useCallback(
    (dishId: string) => {
      const item = items.find((i) => i.dishId === dishId);
      return item?.quantity ?? 0;
    },
    [items],
  );

  // ── 渲染 ─────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--tx-bg, #0B1A20)', color: '#fff', fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif' }}>

      {/* ── 顶部：搜索 + 桌号信息 ── */}
      <div style={{ padding: '12px 16px 0', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <MenuSearch
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="搜索菜品..."
            enableVoice
          />
        </div>
        <div style={{ flexShrink: 0, textAlign: 'right' }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>桌号: {tableNo}</div>
          {loading && <span style={{ color: '#faad14', fontSize: 13 }}>开单中...</span>}
          {store.orderNo && <span style={{ color: '#52c41a', fontSize: 13 }}>{store.orderNo}</span>}
        </div>
      </div>

      {/* ── 分类导航 ── */}
      {!searchQuery && (
        <div style={{ flexShrink: 0 }}>
          <CategoryNav
            categories={categories}
            activeId={activeCategory}
            layout="topbar"
            onSelect={setActiveCategory}
          />
        </div>
      )}

      {/* ── 主体：菜品网格 + 侧边购物车 ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* 菜品网格 */}
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(148px, 1fr))', gap: 10 }}>
            {filteredDishes.map((d) => (
              <DishCard
                key={d.id}
                dish={toDishData(d)}
                variant="grid"
                quantity={getQuantityForDish(d.id)}
                showImage={false}
                onAdd={() => handleDishPress(d)}
                onTap={() => handleDishPress(d)}
              />
            ))}
          </div>
          {filteredDishes.length === 0 && (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#64748b', fontSize: 16 }}>
              {searchQuery ? `未找到"${searchQuery}"相关菜品` : '该分类暂无菜品'}
            </div>
          )}
        </div>

        {/* 右侧购物车 */}
        <CartPanel
          mode="sidebar"
          items={cartItems}
          totalFen={totalFen}
          discountFen={discountFen}
          tableNo={tableNo}
          onUpdateQuantity={(itemId, qty) => store.updateQuantity(itemId, qty)}
          onRemoveItem={(itemId) => store.removeItem(itemId)}
          onClear={() => store.clear()}
          onSettle={() => items.length > 0 && navigate(`/settle/${orderId ?? 'temp'}`)}
        />
      </div>

      {/* ── 活鲜称重弹层 ── */}
      {seafoodSheet.dish && (
        <LiveSeafoodOrderSheet
          visible={seafoodSheet.visible}
          dish={{
            id:               seafoodSheet.dish.id,
            name:             seafoodSheet.dish.name,
            pricingMethod:    (seafoodSheet.dish.pricingMethod === 'weight' || seafoodSheet.dish.pricingMethod === 'count')
                                ? seafoodSheet.dish.pricingMethod
                                : 'weight',
            pricePerUnitFen:  seafoodSheet.dish.priceFen,
            weightUnit:       seafoodSheet.dish.weightUnit ?? 'jin',
            displayUnit:      seafoodSheet.dish.displayUnit ?? '斤',
            minOrderQty:      seafoodSheet.dish.minOrderQty ?? 0.5,
            tankZoneName:     seafoodSheet.dish.tankZoneName,
          }}
          storeId={STORE_ID}
          orderId={orderId ?? undefined}
          onConfirm={handleSeafoodConfirm}
          onClose={() => setSeafoodSheet({ visible: false, dish: null })}
        />
      )}

      {/* ── 套餐选择弹层 ── */}
      {comboSheet.dish && comboSheet.dish.comboGroups && (
        <ComboSelectorSheet
          visible={comboSheet.visible}
          combo={{
            id:              comboSheet.dish.id,
            comboName:       comboSheet.dish.name,
            comboPriceFen:   comboSheet.dish.comboPriceFen ?? comboSheet.dish.priceFen,
            originalPriceFen: comboSheet.dish.originalPriceFen ?? comboSheet.dish.priceFen,
            groups:          comboSheet.dish.comboGroups,
          }}
          onConfirm={handleComboConfirm}
          onClose={() => setComboSheet({ visible: false, dish: null })}
        />
      )}
    </div>
  );
}
