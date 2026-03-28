/**
 * ToastOpenView — Toast POS-inspired Open View 点餐页面
 *
 * 布局规范:
 *   ┌─────────────────────────────────────────────────────────┐
 *   │ [Agent预警条 - 固定顶部]                                  │
 *   ├──────┬──────────────────────────────┬───────────────────┤
 *   │ 分类  │  [搜索栏 + 语音]              │  修饰面板          │
 *   │ 侧栏  │  [全部|常点|套餐|时令]          │  (选中菜品时显示)   │
 *   │      │  ┌────┐ ┌────┐ ┌────┐       │  ─────────────── │
 *   │ 10%  │  │色卡│ │色卡│ │色卡│        │  购物车            │
 *   │      │  └────┘ └────┘ └────┘       │       35%        │
 *   │      │         55%                  │                  │
 *   ├──────┴──────────────────────────────┴───────────────────┤
 *   │ [桌台] [会员] [挂单] [取单]                               │
 *   └─────────────────────────────────────────────────────────┘
 *
 * 规则 (store.md):
 *   - NO Ant Design — 仅自定义 TXTouch 组件
 *   - 所有点击区域 >= 48x48px
 *   - 最小字号 16px
 *   - 无 hover-only — 使用 :active + scale(0.97)
 *   - Agent 预警固定顶部
 *   - 品牌色 #FF6B35
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { TXAgentAlert } from '../touch/TXAgentAlert';
import { useOrderStore } from '../../store/orderStore';
import { fetchDishes, type DishItem } from '../../api/menuApi';
import { createOrder, addItem as apiAddItem } from '../../api/tradeApi';
import styles from './ToastOpenView.module.css';

// ── 分类色彩映射（Toast 风格色卡） ──
const CATEGORY_COLORS: Record<string, { bg: string; text: string }> = {
  '招牌菜': { bg: '#D32F2F', text: '#FFF' },
  '湘菜':   { bg: '#E65100', text: '#FFF' },
  '凉菜':   { bg: '#2E7D32', text: '#FFF' },
  '汤品':   { bg: '#1565C0', text: '#FFF' },
  '主食':   { bg: '#546E7A', text: '#FFF' },
  '饮品':   { bg: '#6A1B9A', text: '#FFF' },
  '小吃':   { bg: '#F57F17', text: '#FFF' },
  '素菜':   { bg: '#00838F', text: '#FFF' },
};

const DEFAULT_CATEGORY_COLOR = { bg: '#757575', text: '#FFF' };

// ── 修饰数据 ──
interface ModifierGroup {
  name: string;
  options: { label: string; priceFen: number }[];
  required: boolean;
  multiSelect: boolean;
}

const DISH_MODIFIERS: Record<string, ModifierGroup[]> = {
  'default': [
    {
      name: '辣度',
      options: [
        { label: '不辣', priceFen: 0 },
        { label: '微辣', priceFen: 0 },
        { label: '中辣', priceFen: 0 },
        { label: '特辣', priceFen: 0 },
      ],
      required: false,
      multiSelect: false,
    },
    {
      name: '做法',
      options: [
        { label: '标准', priceFen: 0 },
        { label: '少盐', priceFen: 0 },
        { label: '少油', priceFen: 0 },
      ],
      required: false,
      multiSelect: true,
    },
  ],
  '招牌菜': [
    {
      name: '辣度',
      options: [
        { label: '微辣', priceFen: 0 },
        { label: '中辣', priceFen: 0 },
        { label: '特辣', priceFen: 0 },
      ],
      required: true,
      multiSelect: false,
    },
    {
      name: '做法',
      options: [
        { label: '清蒸', priceFen: 0 },
        { label: '红烧', priceFen: 0 },
        { label: '干锅', priceFen: 200 },
      ],
      required: false,
      multiSelect: false,
    },
    {
      name: '加料',
      options: [
        { label: '加蛋', priceFen: 300 },
        { label: '加豆腐', priceFen: 200 },
        { label: '加粉丝', priceFen: 300 },
      ],
      required: false,
      multiSelect: true,
    },
  ],
};

// ── Mock 菜品（API 未就绪时降级） ──
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

const QUICK_TABS = ['全部', '常点', '套餐', '时令'] as const;

const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

// ── Agent 预警 demo 数据 ──
interface AgentAlertData {
  agentName: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  actionLabel?: string;
}

// ══════════════════════════════════════════
//  搜索栏组件
// ══════════════════════════════════════════
function SearchBar({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className={styles.searchBar}>
      <span className={styles.searchIcon} aria-hidden="true">&#128269;</span>
      <input
        className={styles.searchInput}
        type="text"
        placeholder="搜索菜品..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value && (
        <button
          className={`${styles.searchClear} tx-pressable`}
          onClick={() => onChange('')}
          aria-label="清除搜索"
        >
          &#10005;
        </button>
      )}
      <button
        className={`${styles.voiceBtn} tx-pressable`}
        aria-label="语音搜索"
        onClick={() => {
          /* 语音搜索占位 — 后续对接 Core ML Whisper */
        }}
      >
        &#127908;
      </button>
    </div>
  );
}

// ══════════════════════════════════════════
//  主组件
// ══════════════════════════════════════════
export function ToastOpenView() {
  const { tableNo = '?' } = useParams();
  const navigate = useNavigate();
  const store = useOrderStore();
  const { items, totalFen, discountFen, orderId, orderNo } = store;

  const [dishes, setDishes] = useState<DishItem[]>(MOCK_DISHES);
  const [activeCategory, setActiveCategory] = useState('全部');
  const [activeQuickTab, setActiveQuickTab] = useState<string>('全部');
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(false);

  // 修饰面板状态
  const [selectedDish, setSelectedDish] = useState<DishItem | null>(null);
  const [modifierSelections, setModifierSelections] = useState<Record<string, string[]>>({});

  // Agent 预警
  const [agentAlert, setAgentAlert] = useState<AgentAlertData | null>(null);

  // ── 加载菜品 + 自动开单 ──
  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchDishes(STORE_ID).then((d) => {
        if (d.length > 0) setDishes(d);
      }),
      !orderId && tableNo !== '?'
        ? createOrder(STORE_ID, tableNo)
            .then((res) => store.setOrder(res.order_id, res.order_no, tableNo))
            .catch((e: Error) => console.error('开单失败(离线模式):', e.message))
        : Promise.resolve(),
    ]).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 模拟 Agent 预警（折扣守护 demo） ──
  useEffect(() => {
    // 当购物车总额超过 20000 分(200 元)时展示 demo 预警
    if (totalFen > 20000 && !agentAlert) {
      setAgentAlert({
        agentName: '折扣守护',
        message: '当前订单金额较高，请确认菜品数量是否正确',
        severity: 'warning',
        actionLabel: '已确认',
      });
    }
  }, [totalFen, agentAlert]);

  // ── 构建分类列表 ──
  const categories = useMemo(() => {
    const catMap = new Map<string, number>();
    for (const d of dishes) {
      catMap.set(d.category, (catMap.get(d.category) || 0) + 1);
    }
    const all: { id: string; name: string; count: number }[] = [
      { id: '全部', name: '全部', count: dishes.length },
    ];
    for (const [name, count] of catMap) {
      all.push({ id: name, name, count });
    }
    return all;
  }, [dishes]);

  // ── 筛选菜品 ──
  const filteredDishes = useMemo(() => {
    let result = dishes;

    // 分类筛选
    if (activeCategory !== '全部') {
      result = result.filter((d) => d.category === activeCategory);
    }

    // 快捷 Tab 筛选（demo: 常点 = 招牌菜+湘菜, 套餐 = 无, 时令 = 凉菜+汤品）
    if (activeQuickTab === '常点') {
      result = result.filter((d) => ['招牌菜', '湘菜'].includes(d.category));
    } else if (activeQuickTab === '套餐') {
      // 套餐功能占位
      result = [];
    } else if (activeQuickTab === '时令') {
      result = result.filter((d) => ['凉菜', '汤品'].includes(d.category));
    }

    // 搜索
    if (searchText.trim()) {
      const keyword = searchText.trim().toLowerCase();
      result = result.filter(
        (d) =>
          d.name.toLowerCase().includes(keyword) ||
          d.category.toLowerCase().includes(keyword),
      );
    }

    // 沽清排在后面
    return result.sort(
      (a, b) => Number(a.isAvailable === false) - Number(b.isAvailable === false),
    );
  }, [dishes, activeCategory, activeQuickTab, searchText]);

  // ── 获取菜品已点数量 ──
  const getQuantity = useCallback(
    (dishId: string) => {
      return items.filter((i) => i.dishId === dishId).reduce((s, i) => s + i.quantity, 0);
    },
    [items],
  );

  // ── 获取菜品修饰组 ──
  const getModifiers = useCallback((dish: DishItem): ModifierGroup[] => {
    return DISH_MODIFIERS[dish.category] || DISH_MODIFIERS['default'];
  }, []);

  // ── 点击菜品 → 打开修饰面板 ──
  const handleDishTap = useCallback(
    (dish: DishItem) => {
      if (!dish.isAvailable) return;

      const modifiers = getModifiers(dish);
      const hasModifiers = modifiers.length > 0;

      if (hasModifiers) {
        // 初始化修饰选择
        const initial: Record<string, string[]> = {};
        for (const group of modifiers) {
          initial[group.name] = [];
        }
        setModifierSelections(initial);
        setSelectedDish(dish);
      } else {
        // 无修饰直接加入购物车
        addDishToCart(dish, '');
      }
    },
    [getModifiers], // eslint-disable-line react-hooks/exhaustive-deps
  );

  // ── 修饰选项切换 ──
  const handleModifierToggle = useCallback(
    (groupName: string, label: string, multiSelect: boolean) => {
      setModifierSelections((prev) => {
        const current = prev[groupName] || [];
        if (multiSelect) {
          // 多选：切换
          const next = current.includes(label)
            ? current.filter((l) => l !== label)
            : [...current, label];
          return { ...prev, [groupName]: next };
        } else {
          // 单选：替换（再次点击取消）
          const next = current.includes(label) ? [] : [label];
          return { ...prev, [groupName]: next };
        }
      });
    },
    [],
  );

  // ── 确认修饰 → 加入购物车 ──
  const handleModifierConfirm = useCallback(() => {
    if (!selectedDish) return;

    // 构建 notes 和附加价格
    const noteParts: string[] = [];
    let extraPriceFen = 0;

    const modifiers = getModifiers(selectedDish);
    for (const group of modifiers) {
      const selected = modifierSelections[group.name] || [];
      if (selected.length > 0) {
        noteParts.push(`${group.name}:${selected.join('/')}`);
        for (const opt of group.options) {
          if (selected.includes(opt.label)) {
            extraPriceFen += opt.priceFen;
          }
        }
      }
    }

    const notes = noteParts.join(' ');
    addDishToCart(selectedDish, notes, extraPriceFen);
    setSelectedDish(null);
    setModifierSelections({});
  }, [selectedDish, modifierSelections, getModifiers]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 跳过修饰 → 直接加入购物车 ──
  const handleModifierSkip = useCallback(() => {
    if (!selectedDish) return;
    addDishToCart(selectedDish, '');
    setSelectedDish(null);
    setModifierSelections({});
  }, [selectedDish]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 加入购物车 ──
  const addDishToCart = useCallback(
    (dish: DishItem, notes: string, extraPriceFen = 0) => {
      const unitPrice = dish.priceFen + extraPriceFen;

      // 如果没有 notes 且购物车里已有相同菜品（也无 notes），合并数量
      if (!notes) {
        const existing = items.find((i) => i.dishId === dish.id && !i.notes);
        if (existing) {
          store.updateQuantity(existing.id, existing.quantity + 1);
          if (orderId) {
            apiAddItem(orderId, dish.id, dish.name, 1, unitPrice).catch(() => {});
          }
          return;
        }
      }

      store.addItem({
        dishId: dish.id,
        name: dish.name,
        quantity: 1,
        priceFen: unitPrice,
        notes,
        kitchenStation: dish.kitchenStation,
      });

      if (orderId) {
        apiAddItem(orderId, dish.id, dish.name, 1, unitPrice).catch(() => {});
      }
    },
    [items, orderId, store],
  );

  // ── 购物车操作 ──
  const handleCartMinus = useCallback(
    (itemId: string, currentQty: number) => {
      if (currentQty > 1) {
        store.updateQuantity(itemId, currentQty - 1);
      } else {
        store.removeItem(itemId);
      }
    },
    [store],
  );

  const handleSettle = useCallback(() => {
    if (items.length > 0) {
      navigate(`/settle/${orderId || 'temp'}`);
    }
  }, [items, orderId, navigate]);

  const handleBack = useCallback(() => {
    store.clear();
    navigate('/tables');
  }, [store, navigate]);

  // ── 计算 ──
  const finalFen = totalFen - discountFen;
  const itemCount = items.reduce((s, i) => s + i.quantity, 0);

  return (
    <div className={styles.page}>
      {/* Agent 预警条 — 固定顶部 */}
      {agentAlert && (
        <TXAgentAlert
          agentName={agentAlert.agentName}
          message={agentAlert.message}
          severity={agentAlert.severity}
          onAction={agentAlert.actionLabel ? () => setAgentAlert(null) : undefined}
          actionLabel={agentAlert.actionLabel}
        />
      )}

      <div className={styles.body}>
        {/* ══ 左侧 — 分类导航 (10%) ══ */}
        <nav className={styles.categoryNav} aria-label="菜品分类">
          {categories.map((cat) => (
            <button
              key={cat.id}
              className={`${styles.categoryItem} ${
                activeCategory === cat.id ? styles.categoryItemActive : ''
              } tx-pressable`}
              onClick={() => {
                setActiveCategory(cat.id);
                setActiveQuickTab('全部'); // 切换分类时重置 quick tab
              }}
              aria-pressed={activeCategory === cat.id}
            >
              {cat.name}
              <span className={styles.categoryCount}>({cat.count})</span>
            </button>
          ))}
        </nav>

        {/* ══ 中间 — 菜品网格 (55%) ══ */}
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

          {/* 快捷 Tab 栏 */}
          <div className={styles.quickTabs}>
            {QUICK_TABS.map((tab) => (
              <button
                key={tab}
                className={`${styles.quickTab} ${
                  activeQuickTab === tab ? styles.quickTabActive : ''
                } tx-pressable`}
                onClick={() => setActiveQuickTab(tab)}
                aria-pressed={activeQuickTab === tab}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* 色彩菜品网格 */}
          <div className={styles.dishGrid}>
            {filteredDishes.map((dish) => {
              const colors = CATEGORY_COLORS[dish.category] || DEFAULT_CATEGORY_COLOR;
              const qty = getQuantity(dish.id);
              const isSelected = selectedDish?.id === dish.id;

              return (
                <button
                  key={dish.id}
                  className={`${styles.colorDishCard} ${
                    isSelected ? styles.colorDishCardSelected : ''
                  } tx-pressable`}
                  style={{
                    backgroundColor: colors.bg,
                    color: colors.text,
                    cursor: dish.isAvailable ? 'pointer' : 'not-allowed',
                    opacity: dish.isAvailable ? 1 : 0.4,
                  }}
                  onClick={() => handleDishTap(dish)}
                  disabled={!dish.isAvailable}
                  aria-label={`${dish.name} ${fen2yuan(dish.priceFen)}${
                    !dish.isAvailable ? ' 已沽清' : ''
                  }`}
                >
                  <span className={styles.colorDishName}>{dish.name}</span>
                  <span className={styles.colorDishPrice}>{fen2yuan(dish.priceFen)}</span>

                  {/* 已点数量角标 */}
                  {qty > 0 && (
                    <span className={styles.colorDishQty} aria-label={`已点${qty}份`}>
                      {qty}
                    </span>
                  )}

                  {/* 沽清遮罩 */}
                  {!dish.isAvailable && (
                    <div className={styles.soldOutOverlay}>
                      <span className={styles.soldOutText}>沽清</span>
                    </div>
                  )}
                </button>
              );
            })}

            {filteredDishes.length === 0 && (
              <div className={styles.noResult}>
                {activeQuickTab === '套餐' ? '套餐功能即将上线' : '未找到匹配菜品'}
              </div>
            )}
          </div>
        </main>

        {/* ══ 右侧 — 修饰面板 + 购物车 (35%) ══ */}
        <aside className={styles.rightPanel} aria-label="订单面板">
          {/* 修饰面板（选中菜品时显示） */}
          {selectedDish && (
            <div className={styles.modifierPanel}>
              <div className={styles.modifierHeader}>
                <span className={styles.modifierDishName}>{selectedDish.name}</span>
                <button
                  className={`${styles.modifierClose} tx-pressable`}
                  onClick={() => {
                    setSelectedDish(null);
                    setModifierSelections({});
                  }}
                  aria-label="关闭修饰面板"
                >
                  &#10005;
                </button>
              </div>

              <div className={styles.modifierBody}>
                {getModifiers(selectedDish).map((group) => (
                  <div key={group.name} className={styles.modifierGroup}>
                    <div className={styles.modifierGroupTitle}>
                      {group.name}
                      {group.required && (
                        <span className={styles.requiredBadge}>必选</span>
                      )}
                    </div>
                    <div className={styles.modifierOptions}>
                      {group.options.map((opt) => {
                        const isSelected = (
                          modifierSelections[group.name] || []
                        ).includes(opt.label);
                        return (
                          <button
                            key={opt.label}
                            className={`${styles.modifierOption} ${
                              isSelected ? styles.modifierOptionSelected : ''
                            } tx-pressable`}
                            onClick={() =>
                              handleModifierToggle(
                                group.name,
                                opt.label,
                                group.multiSelect,
                              )
                            }
                            aria-pressed={isSelected}
                          >
                            {opt.label}
                            {opt.priceFen > 0 && (
                              <span className={styles.modifierOptionExtra}>
                                +{fen2yuan(opt.priceFen)}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>

              <div className={styles.modifierFooter}>
                <button
                  className={`${styles.modifierSkip} tx-pressable`}
                  onClick={handleModifierSkip}
                >
                  跳过
                </button>
                <button
                  className={`${styles.modifierConfirm} tx-pressable`}
                  onClick={handleModifierConfirm}
                >
                  确认加入 {fen2yuan(selectedDish.priceFen)}
                </button>
              </div>
            </div>
          )}

          {/* 购物车 */}
          <div className={styles.cartSection}>
            <div className={styles.cartHeader}>
              <div className={styles.cartTableInfo}>
                <span className={styles.cartTableNo}>{tableNo}号桌</span>
                {orderNo && <span className={styles.cartOrderNo}>{orderNo}</span>}
              </div>
              <span className={styles.cartItemCount}>{itemCount}道菜</span>
            </div>

            <div className={styles.cartList}>
              {items.length === 0 && (
                <div className={styles.cartEmpty}>
                  <span className={styles.cartEmptyIcon} aria-hidden="true">&#128203;</span>
                  <span className={styles.cartEmptyText}>点击菜品加入订单</span>
                </div>
              )}
              {items.map((item) => (
                <div key={item.id} className={styles.cartItem}>
                  <div className={styles.cartItemInfo}>
                    <div className={styles.cartItemName}>{item.name}</div>
                    {item.notes && (
                      <div className={styles.cartItemNotes}>{item.notes}</div>
                    )}
                    <div className={styles.cartItemPrice}>
                      {fen2yuan(item.priceFen * item.quantity)}
                    </div>
                  </div>
                  <div className={styles.cartItemActions}>
                    <button
                      className={`${styles.qtyBtn} tx-pressable`}
                      onClick={() => handleCartMinus(item.id, item.quantity)}
                      aria-label={`减少 ${item.name}`}
                    >
                      &#8722;
                    </button>
                    <span className={styles.qty}>{item.quantity}</span>
                    <button
                      className={`${styles.qtyBtn} tx-pressable`}
                      onClick={() => store.updateQuantity(item.id, item.quantity + 1)}
                      aria-label={`增加 ${item.name}`}
                    >
                      +
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className={styles.cartFooter}>
              {discountFen > 0 && (
                <div className={styles.discountRow}>
                  <span>优惠</span>
                  <span className={styles.discountAmount}>
                    &#8722;{fen2yuan(discountFen)}
                  </span>
                </div>
              )}
              <div className={styles.totalRow}>
                <span className={styles.totalLabel}>应付</span>
                <span className={styles.totalAmount}>{fen2yuan(finalFen)}</span>
              </div>
              <div className={styles.cartActions}>
                <button
                  className={`${styles.btnSecondary} tx-pressable`}
                  onClick={handleBack}
                >
                  返回
                </button>
                <button
                  className={`${styles.btnPrimary} tx-pressable`}
                  onClick={handleSettle}
                  disabled={items.length === 0}
                >
                  结算
                </button>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* 底部快捷栏 */}
      <footer className={styles.bottomBar}>
        <button
          className={`${styles.quickBtn} tx-pressable`}
          onClick={() => navigate('/tables')}
        >
          桌台
        </button>
        <button className={`${styles.quickBtn} tx-pressable`}>会员</button>
        <button className={`${styles.quickBtn} tx-pressable`}>挂单</button>
        <button className={`${styles.quickBtn} tx-pressable`}>取单</button>
      </footer>
    </div>
  );
}
