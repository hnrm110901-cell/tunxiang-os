/**
 * 收银/点餐页面 — 对接 tx-trade API
 * 左侧菜品列表 + 右侧购物车
 *
 * 2026-04-02 新增：
 *   - 活鲜菜品（pricingMethod='weight'）点击 → LiveSeafoodOrderSheet
 *   - N选M套餐（comboType='flexible'）点击 → ComboSelectorSheet
 */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { createOrder, addItem as apiAddItem } from '../api/tradeApi';
import { fetchDishes, type DishItem } from '../api/menuApi';
import { LiveSeafoodOrderSheet } from '../components/LiveSeafoodOrderSheet';
import { ComboSelectorSheet } from '../components/ComboSelectorSheet';
import { SpecSelectorSheet } from '../components/SpecSelectorSheet';
import type { LiveSeafoodOrderSheetProps } from '../components/LiveSeafoodOrderSheet';
import type { ComboSelectorSheetProps } from '../components/ComboSelectorSheet';
import type { DishSpecification } from '../api/menuApi';

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
  /** 多规格（大份/中份/小份/半份） */
  specifications?: DishSpecification[];
  imageUrl?: string;
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
  // 多规格示例
  {
    id: 'sp1', name: '水煮鱼', priceFen: 6800, category: '热菜',
    kitchenStation: '热菜档', isAvailable: true, pricingMethod: 'normal',
    specifications: [
      { spec_id: 'sp1-l', name: '大份', price_fen: 8800 },
      { spec_id: 'sp1-m', name: '中份', price_fen: 6800 },
      { spec_id: 'sp1-s', name: '小份/半份', price_fen: 3800, is_half: true },
    ],
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

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

// ─── 组件 ─────────────────────────────────────────────────────────────────────

export function CashierPage() {
  const { tableNo } = useParams();
  const navigate = useNavigate();
  const store = useOrderStore();
  const { items, totalFen, discountFen, orderId } = store;
  const finalFen = totalFen - discountFen;
  const [loading, setLoading] = useState(false);
  const [dishes, setDishes] = useState<ExtendedDishItem[]>(FALLBACK_DISHES);

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

  // 多规格弹层状态
  const [specSheet, setSpecSheet] = useState<{
    visible: boolean;
    dish: ExtendedDishItem | null;
  }>({ visible: false, dish: null });

  // 加载菜品（API优先，失败回退 mock）+ 自动开单
  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchDishes(STORE_ID).then((d) => {
        // API菜品没有扩展字段，保持 fallback 中的活鲜/套餐 mock
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

  // ── 菜品点击路由 ────────────────────────────────────────────────────────────

  const handleDishPress = (dish: ExtendedDishItem) => {
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

    // 多规格菜品 → 规格选择弹层
    if (dish.specifications && dish.specifications.length > 0) {
      setSpecSheet({ visible: true, dish });
      return;
    }

    // 普通菜品 → 直接加入订单
    handleAddNormalDish(dish);
  };

  const handleAddNormalDish = async (dish: ExtendedDishItem) => {
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
  };

  // ── 活鲜确认回调 ─────────────────────────────────────────────────────────────

  const handleSeafoodConfirm: LiveSeafoodOrderSheetProps['onConfirm'] = (
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
  };

  // ── 套餐确认回调 ─────────────────────────────────────────────────────────────

  const handleComboConfirm: ComboSelectorSheetProps['onConfirm'] = (selections) => {
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
  };

  // ── 多规格确认回调 ───────────────────────────────────────────────────────────

  const handleSpecConfirm = (specId: string, specName: string, priceFen: number, quantity: number) => {
    const dish = specSheet.dish;
    if (!dish) return;

    const cartKey = `${dish.id}__${specId}`;
    const displayName = `${dish.name}（${specName}）`;

    const existing = items.find((i) => i.dishId === cartKey);
    if (existing) {
      store.updateQuantity(existing.id, existing.quantity + quantity);
    } else {
      store.addItem({
        dishId: cartKey,
        name: displayName,
        quantity,
        priceFen,
        notes: `规格:${specName}`,
        kitchenStation: dish.kitchenStation,
      });
    }

    if (orderId) {
      apiAddItem(orderId, dish.id, displayName, quantity, priceFen).catch(() => {});
    }
  };

  // ── 菜品分类颜色 ─────────────────────────────────────────────────────────────

  const categoryTagColor = (cat: string): string => {
    const map: Record<string, string> = {
      '活鲜': '#0F6E56',
      '套餐': '#1B5FA8',
      '热菜': '#8B4513',
      '凉菜': '#2E6B4A',
      '主食': '#6B5320',
      '饮品': '#4A3580',
    };
    return map[cat] ?? '#555';
  };

  const isDishSpecial = (d: ExtendedDishItem) =>
    d.pricingMethod === 'weight' || d.pricingMethod === 'count' || d.comboType === 'flexible' || (d.specifications && d.specifications.length > 0);

  // ── 渲染 ─────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff', fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif' }}>

      {/* ── 左侧 — 菜品区 ── */}
      <div style={{ flex: 1, padding: 16, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 20 }}>桌号: {tableNo}</h3>
          {loading && <span style={{ color: '#faad14', fontSize: 16 }}>开单中...</span>}
          {store.orderNo && <span style={{ color: '#52c41a', fontSize: 16 }}>{store.orderNo}</span>}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(148px, 1fr))', gap: 10 }}>
          {dishes.map((d) => {
            const inOrder = items.find((i) => i.dishId === d.id);
            const special = isDishSpecial(d);

            return (
              <div
                key={d.id}
                role="button"
                tabIndex={0}
                aria-label={d.name}
                onClick={() => handleDishPress(d)}
                onKeyDown={(e) => e.key === 'Enter' && handleDishPress(d)}
                style={{
                  position: 'relative',
                  padding: 14,
                  borderRadius: 10,
                  background: d.isAvailable ? '#1a2a33' : '#111c22',
                  cursor: d.isAvailable ? 'pointer' : 'not-allowed',
                  textAlign: 'center',
                  minHeight: 80,
                  border: inOrder ? '2px solid #FF6B35' : special ? '1.5px solid rgba(255,107,53,0.4)' : '1.5px solid transparent',
                  opacity: d.isAvailable ? 1 : 0.5,
                  transition: 'transform 200ms ease',
                  userSelect: 'none',
                  WebkitUserSelect: 'none',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 4,
                }}
              >
                {/* 菜品名 */}
                <div style={{ fontWeight: 'bold', fontSize: 17, color: '#fff', lineHeight: 1.3 }}>
                  {d.name}
                </div>

                {/* 价格 */}
                <div style={{ color: '#FF6B35', fontSize: 16, fontWeight: 600 }}>
                  {d.comboType === 'flexible' && d.comboPriceFen
                    ? fen2yuan(d.comboPriceFen)
                    : d.pricingMethod === 'weight' || d.pricingMethod === 'count'
                      ? `${fen2yuan(d.priceFen)}/${d.displayUnit ?? '份'}`
                      : fen2yuan(d.priceFen)}
                </div>

                {/* 分类标签 */}
                <div style={{
                  display: 'inline-block',
                  padding: '2px 8px',
                  borderRadius: 4,
                  background: categoryTagColor(d.category),
                  fontSize: 13,
                  color: '#fff',
                }}>
                  {d.category}
                </div>

                {/* 活鲜/套餐标记 */}
                {d.pricingMethod === 'weight' && (
                  <div style={{ fontSize: 12, color: '#52c41a', marginTop: 2 }}>⚖ 按重量</div>
                )}
                {d.comboType === 'flexible' && (
                  <div style={{ fontSize: 12, color: '#1890ff', marginTop: 2 }}>📋 套餐</div>
                )}
                {d.specifications && d.specifications.length > 0 && (
                  <div style={{ fontSize: 12, color: '#faad14', marginTop: 2 }}>多规格</div>
                )}
                {!d.isAvailable && (
                  <div style={{
                    position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)',
                    borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 16, color: '#aaa', fontWeight: 600,
                  }}>
                    已沽清
                  </div>
                )}

                {/* 已点角标 */}
                {inOrder && (
                  <div style={{
                    position: 'absolute', top: 6, right: 6,
                    width: 22, height: 22, borderRadius: '50%',
                    background: '#FF6B35', color: '#fff',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 13, fontWeight: 700, lineHeight: 1,
                  }}>
                    {inOrder.quantity}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── 右侧 — 购物车 ── */}
      <div style={{ width: 320, background: '#112228', padding: 16, display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 20 }}>当前订单</h3>
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
          {items.length === 0 && (
            <div style={{ color: '#666', textAlign: 'center', marginTop: 40, fontSize: 16 }}>
              点击菜品加入订单
            </div>
          )}
          {items.map((item) => (
            <div key={item.id} style={{ padding: '10px 0', borderBottom: '1px solid #1a2a33' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.3 }}>{item.name}</div>
                  {item.notes && (
                    <div style={{ fontSize: 14, color: '#999', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.notes}
                    </div>
                  )}
                  <div style={{ fontSize: 16, color: '#999', marginTop: 2 }}>
                    {fen2yuan(item.priceFen)} × {item.quantity}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                  <button
                    type="button"
                    onClick={() => item.quantity > 1 ? store.updateQuantity(item.id, item.quantity - 1) : store.removeItem(item.id)}
                    style={btnStyle}
                  >
                    -
                  </button>
                  <span style={{ fontSize: 18, fontWeight: 600, minWidth: 20, textAlign: 'center' }}>
                    {item.quantity}
                  </span>
                  <button
                    type="button"
                    onClick={() => store.updateQuantity(item.id, item.quantity + 1)}
                    style={btnStyle}
                  >
                    +
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ borderTop: '1px solid #333', paddingTop: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 22, fontWeight: 'bold', color: '#FF6B35' }}>
            <span>应付</span>
            <span>{fen2yuan(finalFen)}</span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button
            type="button"
            onClick={() => { store.clear(); navigate('/tables'); }}
            style={{ ...actionBtn, background: '#333' }}
          >
            返回
          </button>
          <button
            type="button"
            onClick={() => items.length > 0 && navigate(`/settle/${orderId ?? 'temp'}`)}
            disabled={items.length === 0}
            style={{ ...actionBtn, background: items.length > 0 ? '#FF6B35' : '#444' }}
          >
            结算
          </button>
        </div>
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

      {/* ── 多规格选择弹层 ── */}
      {specSheet.dish && specSheet.dish.specifications && specSheet.dish.specifications.length > 0 && (
        <SpecSelectorSheet
          visible={specSheet.visible}
          dish={{
            id:             specSheet.dish.id,
            name:           specSheet.dish.name,
            imageUrl:       specSheet.dish.imageUrl,
            priceFen:       specSheet.dish.priceFen,
            specifications: specSheet.dish.specifications,
          }}
          onConfirm={handleSpecConfirm}
          onClose={() => setSpecSheet({ visible: false, dish: null })}
        />
      )}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  width: 36,
  height: 36,
  border: 'none',
  borderRadius: 6,
  background: '#333',
  color: '#fff',
  cursor: 'pointer',
  fontSize: 18,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  flexShrink: 0,
};

const actionBtn: React.CSSProperties = {
  flex: 1,
  height: 56,
  border: 'none',
  borderRadius: 10,
  color: '#fff',
  fontSize: 18,
  fontWeight: 600,
  cursor: 'pointer',
  fontFamily: 'inherit',
};
