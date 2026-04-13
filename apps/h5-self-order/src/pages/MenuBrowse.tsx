import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchCategories, fetchDishes, searchDishes, fetchAiRecommendations } from '@/api/menuApi';
import type { Category, AiRecommendation } from '@/api/menuApi';
import { DishGrid, CategoryNav, MenuSearch, CartPanel, SpecSheet } from '@tx-ds/biz';
import type { DishData, SpecGroup } from '@tx-ds/biz';
import { formatPrice } from '@tx-ds/utils';

// ─── Mock 分类数据（尝在一起演示） ──────────────────────────────────────────

const MOCK_CATEGORIES: Array<{ id: string; name: string; icon: string }> = [
  { id: 'signature', name: '招牌', icon: '⭐' },
  { id: 'hunan',     name: '湘菜', icon: '🌶️' },
  { id: 'cold',      name: '凉菜', icon: '🥗' },
  { id: 'soup',      name: '汤羹', icon: '🍲' },
  { id: 'staple',    name: '主食', icon: '🍚' },
  { id: 'drinks',    name: '饮品', icon: '🥤' },
];

function makeDish(
  id: string, name: string, category: string, priceFen: number,
  description: string, tags: DishData['tags'] = [], allergens: DishData['allergens'] = [],
): DishData {
  return { id, name, category, priceFen, description, tags, allergens, images: [], soldOut: false };
}

const MOCK_DISHES: DishData[] = [
  makeDish('d001', '剁椒鱼头', 'signature', 8800, '新鲜花鲢，酱料手工腌制48小时，鲜辣过瘾', [{ type: 'signature', label: '招牌' }, { type: 'spicy2', label: '中辣' }]),
  makeDish('d002', '口味虾', 'signature', 12800, '青壳龙虾，秘制口味酱现炒，肉质Q弹', [{ type: 'signature', label: '招牌' }, { type: 'spicy3', label: '特辣' }]),
  makeDish('d003', '毛氏红烧肉', 'signature', 6800, '五花肉精选，冰糖入味，软糯不腻', [{ type: 'signature', label: '招牌' }]),
  makeDish('d004', '农家小炒肉', 'hunan', 4800, '土猪五花，搭配青椒爆炒，香辣鲜嫩', [{ type: 'spicy2', label: '中辣' }]),
  makeDish('d005', '湘西土匪鸭', 'hunan', 6800, '麻辣干香，湘西传统做法', [{ type: 'spicy3', label: '特辣' }]),
  makeDish('d006', '剁椒蒸蛋', 'hunan', 2800, '嫩豆腐配剁椒，口感滑嫩', [{ type: 'spicy1', label: '微辣' }]),
  makeDish('d007', '辣椒炒腊肉', 'hunan', 5200, '自制腊肉，搭配新鲜辣椒，烟熏香浓', [{ type: 'spicy2', label: '中辣' }]),
  makeDish('d008', '擂辣椒', 'cold', 2600, '传统手工擂制，鲜辣开胃', [{ type: 'spicy2', label: '中辣' }]),
  makeDish('d009', '酸辣蕨根粉', 'cold', 2400, '手工蕨根粉，酸爽开胃', [{ type: 'spicy1', label: '微辣' }]),
  makeDish('d010', '皮蛋豆腐', 'cold', 2200, '嫩豆腐配皮蛋，淋上特调酱汁', [], [{ code: 'egg', name: '蛋' }]),
  makeDish('d011', '猪肚鸡汤', 'soup', 5800, '滋补老母鸡与猪肚慢炖4小时'),
  makeDish('d012', '酸萝卜老鸭汤', 'soup', 5200, '酸萝卜去腻，老鸭鲜甜'),
  makeDish('d013', '剁椒蛋炒饭', 'staple', 2200, '米饭粒粒分明，剁椒提香', [{ type: 'spicy1', label: '微辣' }]),
  makeDish('d014', '手工米粉', 'staple', 1800, '湘式手工米粉，劲道爽滑'),
  makeDish('d015', '冰镇梅子汤', 'drinks', 1200, '酸甜开胃，解辣必备'),
  makeDish('d016', '湘茶冷泡茶', 'drinks', 1600, '本地茶农直供，清凉回甘'),
];

// ─── Mock 规格组 ────────────────────────────────────────

const MOCK_SPEC_GROUPS: SpecGroup[] = [
  { id: 'spicy', name: '辣度', type: 'single', required: true, options: [
    { id: 's1', label: '不辣' },
    { id: 's2', label: '微辣' },
    { id: 's3', label: '中辣' },
    { id: 's4', label: '特辣' },
  ]},
  { id: 'side', name: '配菜', type: 'multi', required: false, options: [
    { id: 'sd1', label: '豆腐', extraPriceFen: 0 },
    { id: 'sd2', label: '粉丝', extraPriceFen: 0 },
    { id: 'sd3', label: '金针菇', extraPriceFen: 300 },
  ]},
];

/** 有规格的菜品 ID（演示用） */
const DISHES_WITH_SPECS = new Set(['d001', 'd002', 'd004', 'd005']);

// ─── 菜单浏览页 ─────────────────────────────────────────

export default function MenuBrowse() {
  const { t } = useLang();
  const navigate = useNavigate();
  const storeId = useOrderStore((s) => s.storeId);
  const storeName = useOrderStore((s) => s.storeName);
  const tableNo = useOrderStore((s) => s.tableNo);
  const cart = useOrderStore((s) => s.cart);
  const addToCart = useOrderStore((s) => s.addToCart);
  const cartCount = useOrderStore((s) => s.cartCount);
  const cartTotal = useOrderStore((s) => s.cartTotal);

  const [categories, setCategories] = useState<Array<{ id: string; name: string; icon?: string }>>([]);
  const [activeCat, setActiveCat] = useState('');
  const [dishes, setDishes] = useState<DishData[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<DishData[] | null>(null);
  const [aiRecs, setAiRecs] = useState<AiRecommendation[]>([]);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // SpecSheet state
  const [specDish, setSpecDish] = useState<DishData | null>(null);

  // ─── 加载分类和菜品 ───
  useEffect(() => {
    if (!storeId) { navigate('/'); return; }

    fetchCategories(storeId).then((cats) => {
      const mapped = cats.map((c) => ({ id: c.id, name: c.name, icon: c.icon }));
      setCategories(mapped);
      if (mapped.length > 0) setActiveCat(mapped[0].id);
    }).catch(() => {
      setCategories(MOCK_CATEGORIES);
      setActiveCat(MOCK_CATEGORIES[0].id);
    });

    fetchDishes(storeId).then((items) => {
      // Adapt API DishItem → DishData (priceFen)
      const mapped: DishData[] = items.map((d) => ({
        id: d.id, name: d.name, category: d.categoryId,
        priceFen: Math.round(d.price * 100),
        description: d.description, images: d.images,
        tags: d.tags, allergens: d.allergens as DishData['allergens'],
        soldOut: d.soldOut,
      }));
      setDishes(mapped);
    }).catch(() => {
      setDishes(MOCK_DISHES);
    });
  }, [storeId, navigate]);

  // ─── AI 推荐 ───
  useEffect(() => {
    if (!storeId) return;
    const dishIds = cart.map((c) => c.dish.id);
    fetchAiRecommendations(storeId, dishIds).then(setAiRecs).catch(() => { /* ignore */ });
  }, [storeId, cart]);

  // ─── 搜索防抖 ───
  const handleSearch = useCallback((q: string) => {
    setSearchQuery(q);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!q.trim()) { setSearchResults(null); return; }
    searchTimerRef.current = setTimeout(async () => {
      try {
        const results = await searchDishes(storeId, q);
        const mapped: DishData[] = results.map((d) => ({
          id: d.id, name: d.name, category: d.categoryId,
          priceFen: Math.round(d.price * 100),
          description: d.description, images: d.images,
          tags: d.tags, allergens: d.allergens as DishData['allergens'],
          soldOut: d.soldOut,
        }));
        setSearchResults(mapped);
      } catch {
        setSearchResults([]);
      }
    }, 300);
  }, [storeId]);

  // ─── 菜品点击：有规格 → SpecSheet，无规格 → 直接加购 ───
  const handleDishTap = useCallback((dish: DishData) => {
    if (DISHES_WITH_SPECS.has(dish.id)) {
      setSpecDish(dish);
    } else {
      addToCart({ id: dish.id, name: dish.name, categoryId: dish.category, description: dish.description ?? '', price: dish.priceFen / 100, images: dish.images ?? [], tags: dish.tags ?? [], allergens: [], customOptions: [], soldOut: false, sortOrder: 1 }, 1, {});
    }
  }, [addToCart]);

  const handleSpecConfirm = useCallback((selections: Record<string, string[]>, quantity: number) => {
    if (!specDish) return;
    addToCart({ id: specDish.id, name: specDish.name, categoryId: specDish.category, description: specDish.description ?? '', price: specDish.priceFen / 100, images: specDish.images ?? [], tags: specDish.tags ?? [], allergens: [], customOptions: [], soldOut: false, sortOrder: 1 }, quantity, selections);
    setSpecDish(null);
  }, [specDish, addToCart]);

  /** 购物车数量映射：Record<dishId, quantity> */
  const dishQuantities = useMemo(() => {
    const rec: Record<string, number> = {};
    for (const c of cart) {
      rec[c.dish.id] = (rec[c.dish.id] ?? 0) + c.quantity;
    }
    return rec;
  }, [cart]);

  const displayDishes = useMemo(
    () => searchResults ?? dishes.filter((d) => !activeCat || d.category === activeCat),
    [searchResults, dishes, activeCat],
  );

  // ─── Cart items adapted for CartPanel ───
  const cartItems = useMemo(() =>
    cart.map((c) => ({
      id: `${c.dish.id}-${JSON.stringify(c.specs ?? {})}`,
      dishId: c.dish.id,
      name: c.dish.name,
      quantity: c.quantity,
      priceFen: Math.round(c.dish.price * 100),
    })),
  [cart]);

  const totalFen = useMemo(() => Math.round(cartTotal() * 100), [cartTotal]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--tx-bg-primary)' }}>
      {/* 顶部：门店信息 */}
      <div style={{ padding: '12px 16px', flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 'var(--tx-font-lg)', fontWeight: 700, color: 'var(--tx-text-primary)' }}>
              {storeName}
            </div>
            <div style={{ fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-tertiary)', marginTop: 2 }}>
              {t('tableNo')} {tableNo}
            </div>
          </div>
          <button className="tx-pressable" onClick={() => navigate(-1)} style={{ padding: '6px 14px', borderRadius: 'var(--tx-radius-full)', background: 'var(--tx-bg-tertiary)', color: 'var(--tx-text-secondary)', fontSize: 'var(--tx-font-sm)' }}>
            {t('back')}
          </button>
        </div>
      </div>

      {/* 主体：左分类 + 右内容 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左侧分类导航 */}
        {!searchResults && categories.length > 0 && (
          <CategoryNav
            categories={categories}
            activeId={activeCat}
            layout="sidebar"
            onSelect={setActiveCat}
          />
        )}

        {/* 右侧内容区 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px 120px 12px' }}>
          {/* 搜索框 */}
          <div style={{ padding: '8px 0' }}>
            <MenuSearch
              value={searchQuery}
              onChange={handleSearch}
              onVoiceResult={handleSearch}
              enableVoice
              placeholder={t('search')}
            />
          </div>

          {/* AI推荐区 */}
          {aiRecs.length > 0 && !searchResults && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                <span style={{ padding: '2px 8px', borderRadius: 'var(--tx-radius-sm)', background: 'rgba(59, 130, 246, 0.15)', color: 'var(--tx-info)', fontSize: 'var(--tx-font-xs)', fontWeight: 600 }}>AI</span>
                <span style={{ color: 'var(--tx-text-primary)', fontSize: 'var(--tx-font-sm)', fontWeight: 600 }}>{t('aiRecommend')}</span>
              </div>
              <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 8 }}>
                {aiRecs.map((rec) => (
                  <div key={rec.dishId} className="tx-pressable" onClick={() => navigate(`/dish/${rec.dishId}`)} style={{ minWidth: 140, padding: 10, borderRadius: 'var(--tx-radius-md)', background: 'var(--tx-bg-card)', flexShrink: 0 }}>
                    <img src={rec.dish.images[0] ?? ''} alt={rec.dish.name} loading="lazy" style={{ width: '100%', height: 100, objectFit: 'cover', borderRadius: 8 }} />
                    <div style={{ marginTop: 6, fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: 'var(--tx-text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{rec.dish.name}</div>
                    <div style={{ fontSize: 'var(--tx-font-xs)', color: 'var(--tx-brand)', marginTop: 2 }}>{formatPrice(Math.round(rec.dish.price * 100))}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 菜品列表 */}
          {displayDishes.length > 0 ? (
            <DishGrid
              dishes={displayDishes}
              variant="horizontal"
              quantities={dishQuantities}
              showTags
              showAllergens
              onAddDish={handleDishTap}
              onTapDish={handleDishTap}
            />
          ) : (
            <div style={{ textAlign: 'center', padding: 48, color: 'var(--tx-text-tertiary)', fontSize: 'var(--tx-font-sm)' }}>
              {searchResults ? 'No results' : t('loading')}
            </div>
          )}
        </div>
      </div>

      {/* 底部购物车栏 */}
      <CartPanel
        mode="bottom-bar"
        items={cartItems}
        totalFen={totalFen}
        onUpdateQuantity={() => {}}
        onRemoveItem={() => {}}
        onSettle={() => navigate('/checkout')}
      />

      {/* 规格选择面板 */}
      <SpecSheet
        visible={!!specDish}
        dishName={specDish?.name ?? ''}
        dishPriceFen={specDish?.priceFen ?? 0}
        dishImage={specDish?.images?.[0]}
        specGroups={MOCK_SPEC_GROUPS}
        onConfirm={handleSpecConfirm}
        onClose={() => setSpecDish(null)}
      />
    </div>
  );
}
