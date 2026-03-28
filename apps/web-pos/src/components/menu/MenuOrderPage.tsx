/**
 * MenuOrderPage — POS 点餐主页面
 *
 * 布局规范 (store.md):
 *   ┌─────────────────────────────────────────────────────┐
 *   │ [Agent预警条 - 固定顶部]                              │
 *   ├──────┬──────────────────────────────┬───────────────┤
 *   │ 分类  │        菜品网格               │   购物车      │
 *   │ 侧栏  │  ┌────┐ ┌────┐ ┌────┐      │   ┌────────┐ │
 *   │      │  │菜品 │ │菜品 │ │菜品 │      │   │订单行   │ │
 *   │ 10%  │  └────┘ └────┘ └────┘      │   │...      │ │
 *   │      │         55%                  │   │  35%    │ │
 *   ├──────┴──────────────────────────────┴───────────────┤
 *   │ [桌台信息] [会员信息] [挂单] [取单]                    │
 *   └─────────────────────────────────────────────────────┘
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { TXCategoryNav, type CategoryItem } from '../touch/TXCategoryNav';
import { TXDishCard } from '../touch/TXDishCard';
import { TXCartPanel } from '../touch/TXCartPanel';
import { TXAgentAlert } from '../touch/TXAgentAlert';
import { useOrderStore } from '../../store/orderStore';
import { fetchDishes, fetchCategories, type DishItem } from '../../api/menuApi';
import { createOrder, addItem as apiAddItem } from '../../api/tradeApi';
import styles from './MenuOrderPage.module.css';

// ── Mock 数据（API 未就绪时的降级） ──
const MOCK_DISHES: DishItem[] = [
  { id: 'd1', name: '招牌剁椒鱼头', priceFen: 12800, category: '招牌菜', kitchenStation: '热菜档', isAvailable: true },
  { id: 'd2', name: '小炒黄牛肉', priceFen: 6800, category: '湘菜', kitchenStation: '热菜档', isAvailable: true },
  { id: 'd3', name: '茶油土鸡汤', priceFen: 8800, category: '汤品', kitchenStation: '汤档', isAvailable: true },
  { id: 'd4', name: '口味虾', priceFen: 12800, category: '招牌菜', kitchenStation: '热菜档', isAvailable: true },
  { id: 'd5', name: '农家小炒肉', priceFen: 4200, category: '湘菜', kitchenStation: '热菜档', isAvailable: true },
  { id: 'd6', name: '凉拌黄瓜', priceFen: 1800, category: '凉菜', kitchenStation: '凉菜档', isAvailable: true },
  { id: 'd7', name: '酸辣土豆丝', priceFen: 2200, category: '湘菜', kitchenStation: '热菜档', isAvailable: true },
  { id: 'd8', name: '辣椒炒肉', priceFen: 3800, category: '湘菜', kitchenStation: '热菜档', isAvailable: true },
  { id: 'd9', name: '蒜蓉西兰花', priceFen: 2600, category: '素菜', kitchenStation: '热菜档', isAvailable: true },
  { id: 'd10', name: '紫苏桃子姜', priceFen: 1600, category: '凉菜', kitchenStation: '凉菜档', isAvailable: true },
  { id: 'd11', name: '米饭', priceFen: 300, category: '主食', kitchenStation: 'default', isAvailable: true },
  { id: 'd12', name: '酸梅汤', priceFen: 800, category: '饮品', kitchenStation: 'default', isAvailable: true },
  { id: 'd13', name: '鲜榨橙汁', priceFen: 1800, category: '饮品', kitchenStation: 'default', isAvailable: true },
  { id: 'd14', name: '糖油粑粑', priceFen: 1200, category: '小吃', kitchenStation: '面点档', isAvailable: true },
  { id: 'd15', name: '臭豆腐', priceFen: 1500, category: '小吃', kitchenStation: '面点档', isAvailable: false },
  { id: 'd16', name: '外婆菜炒蛋', priceFen: 2800, category: '湘菜', kitchenStation: '热菜档', isAvailable: true },
];

const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

// ── 搜索栏组件 ──
function SearchBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className={styles.searchBar}>
      <span className={styles.searchIcon}>🔍</span>
      <input
        className={styles.searchInput}
        type="text"
        placeholder="搜索菜品..."
        value={value}
        onChange={e => onChange(e.target.value)}
      />
      {value && (
        <button className={`${styles.searchClear} tx-pressable`} onClick={() => onChange('')}>
          ✕
        </button>
      )}
    </div>
  );
}

export function MenuOrderPage() {
  const { tableNo = '?' } = useParams();
  const navigate = useNavigate();
  const store = useOrderStore();
  const { items, totalFen, discountFen, orderId, orderNo } = store;

  const [dishes, setDishes] = useState<DishItem[]>(MOCK_DISHES);
  const [activeCategory, setActiveCategory] = useState('全部');
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(false);

  // 加载菜品 + 自动开单
  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchDishes(STORE_ID).then(d => { if (d.length > 0) setDishes(d); }),
      !orderId && tableNo !== '?'
        ? createOrder(STORE_ID, tableNo)
            .then(res => store.setOrder(res.order_id, res.order_no, tableNo))
            .catch(e => console.error('开单失败(离线模式):', e))
        : Promise.resolve(),
    ]).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 构建分类列表
  const categories: CategoryItem[] = useMemo(() => {
    const catMap = new Map<string, number>();
    for (const d of dishes) {
      catMap.set(d.category, (catMap.get(d.category) || 0) + 1);
    }
    const all: CategoryItem[] = [{ id: '全部', name: '全部', count: dishes.length }];
    for (const [name, count] of catMap) {
      all.push({ id: name, name, count });
    }
    return all;
  }, [dishes]);

  // 筛选菜品
  const filteredDishes = useMemo(() => {
    let result = dishes;
    if (activeCategory !== '全部') {
      result = result.filter(d => d.category === activeCategory);
    }
    if (searchText.trim()) {
      const keyword = searchText.trim().toLowerCase();
      result = result.filter(d =>
        d.name.toLowerCase().includes(keyword) ||
        d.category.toLowerCase().includes(keyword)
      );
    }
    // 沽清菜品排在后面
    return result.sort((a, b) => Number(a.isAvailable === false) - Number(b.isAvailable === false));
  }, [dishes, activeCategory, searchText]);

  // 获取菜品已点数量
  const getQuantity = useCallback((dishId: string) => {
    const item = items.find(i => i.dishId === dishId);
    return item ? item.quantity : 0;
  }, [items]);

  // 点菜
  const handleAddDish = useCallback((dish: DishItem) => {
    const existing = items.find(i => i.dishId === dish.id);
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
    // 异步同步到后端
    if (orderId) {
      apiAddItem(orderId, dish.id, dish.name, 1, dish.priceFen).catch(() => {});
    }
  }, [items, orderId, store]);

  const handleSettle = useCallback(() => {
    if (items.length > 0) {
      navigate(`/settle/${orderId || 'temp'}`);
    }
  }, [items, orderId, navigate]);

  const handleBack = useCallback(() => {
    store.clear();
    navigate('/tables');
  }, [store, navigate]);

  return (
    <div className={styles.page}>
      {/* Agent 预警条（示例） */}
      {/* <TXAgentAlert agentName="折扣守护" message="检测到异常折扣..." severity="warning" /> */}

      <div className={styles.body}>
        {/* 左侧 — 分类导航 */}
        <TXCategoryNav
          categories={categories}
          activeId={activeCategory}
          onSelect={setActiveCategory}
        />

        {/* 中间 — 菜品网格 */}
        <main className={styles.menuArea}>
          {/* 顶部: 桌号 + 搜索 + 状态 */}
          <header className={styles.menuHeader}>
            <div className={styles.menuHeaderLeft}>
              <span className={styles.tableBadge}>{tableNo}号桌</span>
              {loading && <span className={styles.loadingHint}>加载中...</span>}
              {orderNo && <span className={styles.orderBadge}>{orderNo}</span>}
            </div>
            <SearchBar value={searchText} onChange={setSearchText} />
          </header>

          {/* 菜品网格 */}
          <div className={styles.dishGrid}>
            {filteredDishes.map(dish => (
              <TXDishCard
                key={dish.id}
                name={dish.name}
                price={dish.priceFen}
                tags={
                  dish.category === '招牌菜' ? ['招牌'] :
                  !dish.isAvailable ? [] :
                  undefined
                }
                soldOut={!dish.isAvailable}
                quantity={getQuantity(dish.id)}
                onPress={() => handleAddDish(dish)}
              />
            ))}
            {filteredDishes.length === 0 && (
              <div className={styles.noResult}>未找到匹配菜品</div>
            )}
          </div>
        </main>

        {/* 右侧 — 购物车 */}
        <TXCartPanel
          tableNo={tableNo}
          orderNo={orderNo}
          items={items}
          totalFen={totalFen}
          discountFen={discountFen}
          onUpdateQuantity={store.updateQuantity}
          onRemoveItem={store.removeItem}
          onSettle={handleSettle}
          onBack={handleBack}
        />
      </div>

      {/* 底部快捷栏 */}
      <footer className={styles.bottomBar}>
        <button className={`${styles.quickBtn} tx-pressable`} onClick={() => navigate('/tables')}>
          桌台
        </button>
        <button className={`${styles.quickBtn} tx-pressable`}>
          会员
        </button>
        <button className={`${styles.quickBtn} tx-pressable`}>
          挂单
        </button>
        <button className={`${styles.quickBtn} tx-pressable`}>
          取单
        </button>
      </footer>
    </div>
  );
}
