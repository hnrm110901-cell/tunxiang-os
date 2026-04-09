/**
 * 快餐模板 — 图片+价格网格，一键下单
 *
 * 流程：菜品网格 → 一键加入 → 底栏结算
 * 特色：大图网格、单手快速操作、热门标签、套餐推荐置顶
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchCategories, fetchDishes } from '@/api/menuApi';
import type { Category, DishItem } from '@/api/menuApi';
import CartBar from '@/components/CartBar';

// ─── 快餐专用类型 ─────────────────────────────────────────────────────────────

type QuickTab = 'recommend' | string;  // 'recommend' 为推荐tab，其余为分类id

interface ComboMeal {
  id: string;
  name: string;
  image: string;
  originalPrice: number;
  comboPrice: number;
  items: string[];
  tag: string;
}

// ─── Mock 数据 ─────────────────────────────────────────────────────────────────

const MOCK_COMBOS: ComboMeal[] = [
  { id: 'combo-01', name: '超值午餐A', image: '/images/quick/combo-a.jpg', originalPrice: 42, comboPrice: 29.9, items: ['香辣鸡腿饭', '例汤', '小菜'], tag: '热销' },
  { id: 'combo-02', name: '营养套餐B', image: '/images/quick/combo-b.jpg', originalPrice: 48, comboPrice: 35.9, items: ['红烧排骨饭', '饮品', '水果'], tag: '新品' },
  { id: 'combo-03', name: '轻食套餐C', image: '/images/quick/combo-c.jpg', originalPrice: 38, comboPrice: 25.9, items: ['鸡胸肉沙拉', '全麦面包', '果汁'], tag: '健康' },
];

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export default function QuickServiceTemplate() {
  const navigate = useNavigate();
  const storeId = useOrderStore((s) => s.storeId);
  const storeName = useOrderStore((s) => s.storeName);
  const tableNo = useOrderStore((s) => s.tableNo);
  const cart = useOrderStore((s) => s.cart);
  const addToCart = useOrderStore((s) => s.addToCart);
  const cartCount = useOrderStore((s) => s.cartCount);
  const cartTotal = useOrderStore((s) => s.cartTotal);

  const [categories, setCategories] = useState<Category[]>([]);
  const [activeTab, setActiveTab] = useState<QuickTab>('recommend');
  const [dishes, setDishes] = useState<DishItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    if (!storeId) { navigate('/'); return; }
    fetchCategories(storeId).then((cats) => {
      setCategories(cats);
    }).catch(() => { /* fallback */ });
    fetchDishes(storeId).then(setDishes).catch(() => { /* fallback */ });
  }, [storeId, navigate]);

  const getQuantity = useCallback(
    (dishId: string) => cart.filter((c) => c.dish.id === dishId).reduce((sum, c) => sum + c.quantity, 0),
    [cart],
  );

  // 按分类过滤 + 搜索过滤
  const displayDishes = useMemo(() => {
    let filtered = dishes;
    if (activeTab !== 'recommend') {
      filtered = filtered.filter((d) => d.categoryId === activeTab);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      filtered = filtered.filter((d) => d.name.toLowerCase().includes(q));
    }
    return filtered;
  }, [dishes, activeTab, searchQuery]);

  // 套餐加入购物车
  const handleAddCombo = useCallback((combo: ComboMeal) => {
    const comboDish: DishItem = {
      id: combo.id,
      name: combo.name,
      categoryId: 'combo',
      description: combo.items.join(' + '),
      price: combo.comboPrice,
      images: [combo.image],
      tags: [],
      allergens: [],
      customOptions: [],
      soldOut: false,
      sortOrder: 0,
    };
    addToCart(comboDish, 1, {});
  }, [addToCart]);

  const allTabs: { id: QuickTab; label: string }[] = [
    { id: 'recommend', label: '推荐' },
    ...categories.map((c) => ({ id: c.id, label: c.name })),
  ];

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--tx-bg-primary, #fff)' }}>
      {/* ── 顶部栏 ── */}
      <div className="px-4 pt-3 pb-2 flex-shrink-0">
        <div className="flex justify-between items-center mb-3">
          <div>
            <div className="text-lg font-bold" style={{ color: 'var(--tx-text-primary, #2C2C2A)' }}>
              {storeName}
            </div>
            <div className="text-xs mt-0.5" style={{ color: 'var(--tx-text-tertiary, #B4B2A9)' }}>
              {tableNo ? `${tableNo} 号桌` : '快餐自取'}
            </div>
          </div>
          <button
            className="active:scale-95 transition-transform"
            onClick={() => navigate(-1)}
            style={{
              padding: '8px 16px', borderRadius: '999px',
              background: 'var(--tx-bg-tertiary, #F0EDE6)',
              color: 'var(--tx-text-secondary)', fontSize: 14,
              minHeight: 48,
            }}
          >
            返回
          </button>
        </div>

        {/* 搜索栏 */}
        <div
          className="flex items-center rounded-xl px-3"
          style={{ height: 44, background: 'var(--tx-bg-tertiary, #F0EDE6)' }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="flex-shrink-0">
            <circle cx="11" cy="11" r="7" stroke="#B4B2A9" strokeWidth="2"/>
            <path d="M20 20l-3.5-3.5" stroke="#B4B2A9" strokeWidth="2" strokeLinecap="round"/>
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索菜品"
            className="flex-1 ml-2 bg-transparent text-sm"
            style={{ color: 'var(--tx-text-primary)', height: '100%' }}
          />
          {searchQuery && (
            <button
              className="active:scale-90 transition-transform"
              onClick={() => setSearchQuery('')}
              style={{ minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M18 6L6 18M6 6l12 12" stroke="#B4B2A9" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </button>
          )}
        </div>

        {/* 分类Tab横向滚动 */}
        <div
          className="flex gap-2 mt-3 overflow-x-auto pb-1"
          style={{ WebkitOverflowScrolling: 'touch', scrollbarWidth: 'none' }}
        >
          {allTabs.map((tab) => (
            <button
              key={tab.id}
              className="flex-shrink-0 active:scale-95 transition-transform"
              onClick={() => { setActiveTab(tab.id); setSearchQuery(''); }}
              style={{
                padding: '8px 16px', borderRadius: 999,
                fontSize: 14, fontWeight: activeTab === tab.id ? 700 : 400,
                background: activeTab === tab.id ? 'var(--tx-brand, #FF6B35)' : 'var(--tx-bg-secondary, #F8F7F5)',
                color: activeTab === tab.id ? '#fff' : 'var(--tx-text-secondary)',
                minHeight: 48,
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── 内容区 ── */}
      <div className="flex-1 overflow-y-auto px-4 pb-32" style={{ WebkitOverflowScrolling: 'touch' }}>
        {/* 套餐推荐（仅推荐Tab显示） */}
        {activeTab === 'recommend' && !searchQuery && (
          <div className="mb-4">
            <div className="text-base font-bold mb-3" style={{ color: 'var(--tx-text-primary)' }}>
              超值套餐
            </div>
            <div
              className="flex gap-3 overflow-x-auto pb-2"
              style={{ WebkitOverflowScrolling: 'touch', scrollbarWidth: 'none' }}
            >
              {MOCK_COMBOS.map((combo) => (
                <div
                  key={combo.id}
                  className="flex-shrink-0 rounded-xl overflow-hidden"
                  style={{
                    width: 200, background: 'var(--tx-bg-card, #fff)',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
                  }}
                >
                  <div className="relative" style={{ height: 120, background: 'var(--tx-bg-tertiary)' }}>
                    <img
                      src={combo.image}
                      alt={combo.name}
                      loading="lazy"
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                    <span
                      className="absolute top-2 left-2 text-xs px-2 py-0.5 rounded-full text-white"
                      style={{ background: 'var(--tx-brand, #FF6B35)' }}
                    >
                      {combo.tag}
                    </span>
                  </div>
                  <div className="p-3">
                    <div className="text-sm font-semibold truncate" style={{ color: 'var(--tx-text-primary)' }}>
                      {combo.name}
                    </div>
                    <div className="text-xs mt-1 truncate" style={{ color: 'var(--tx-text-tertiary)' }}>
                      {combo.items.join(' + ')}
                    </div>
                    <div className="flex items-center justify-between mt-2">
                      <div className="flex items-baseline gap-1">
                        <span className="text-base font-bold" style={{ color: 'var(--tx-brand, #FF6B35)' }}>
                          ¥{combo.comboPrice}
                        </span>
                        <span className="text-xs line-through" style={{ color: 'var(--tx-text-tertiary)' }}>
                          ¥{combo.originalPrice}
                        </span>
                      </div>
                      <button
                        className="rounded-full flex items-center justify-center active:scale-90 transition-transform"
                        onClick={() => handleAddCombo(combo)}
                        style={{
                          width: 32, height: 32,
                          background: 'var(--tx-brand, #FF6B35)', color: '#fff',
                          minWidth: 48, minHeight: 48, padding: 0,
                        }}
                      >
                        <span className="text-lg leading-none">+</span>
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 菜品网格 — 两列大图 */}
        <div className="grid grid-cols-2 gap-3">
          {displayDishes.map((dish) => {
            const qty = getQuantity(dish.id);
            return (
              <div
                key={dish.id}
                className="rounded-xl overflow-hidden relative"
                style={{
                  background: 'var(--tx-bg-card, #fff)',
                  boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
                  opacity: dish.soldOut ? 0.5 : 1,
                }}
              >
                {/* 菜品图片 */}
                <div
                  className="relative"
                  style={{ height: 130, background: 'var(--tx-bg-tertiary, #F0EDE6)' }}
                >
                  <img
                    src={dish.images[0] ?? ''}
                    alt={dish.name}
                    loading="lazy"
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                  {dish.soldOut && (
                    <div
                      className="absolute inset-0 flex items-center justify-center"
                      style={{ background: 'rgba(0,0,0,0.45)' }}
                    >
                      <span className="text-white text-base font-bold">已售罄</span>
                    </div>
                  )}
                  {qty > 0 && !dish.soldOut && (
                    <span
                      className="absolute top-2 right-2 w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-bold"
                      style={{ background: 'var(--tx-brand, #FF6B35)' }}
                    >
                      {qty}
                    </span>
                  )}
                  {/* 标签 */}
                  {dish.tags.length > 0 && (
                    <span
                      className="absolute top-2 left-2 text-xs px-2 py-0.5 rounded-full text-white"
                      style={{ background: 'var(--tx-brand, #FF6B35)' }}
                    >
                      {dish.tags[0].label}
                    </span>
                  )}
                </div>

                {/* 菜品信息 + 加购按钮 */}
                <div className="p-2.5">
                  <div
                    className="text-sm font-semibold truncate"
                    style={{ color: 'var(--tx-text-primary, #2C2C2A)' }}
                  >
                    {dish.name}
                  </div>
                  {dish.description && (
                    <div
                      className="text-xs mt-0.5 truncate"
                      style={{ color: 'var(--tx-text-tertiary, #B4B2A9)' }}
                    >
                      {dish.description}
                    </div>
                  )}
                  <div className="flex items-center justify-between mt-2">
                    <div className="flex items-baseline gap-1">
                      <span className="text-base font-bold" style={{ color: 'var(--tx-brand, #FF6B35)' }}>
                        ¥{dish.price}
                      </span>
                      {dish.memberPrice != null && dish.memberPrice < dish.price && (
                        <span className="text-xs" style={{ color: 'var(--tx-text-tertiary)' }}>
                          会员¥{dish.memberPrice}
                        </span>
                      )}
                    </div>
                    <button
                      className="rounded-full flex items-center justify-center active:scale-90 transition-transform"
                      disabled={dish.soldOut}
                      onClick={() => addToCart(dish, 1, {})}
                      style={{
                        width: 32, height: 32,
                        background: dish.soldOut ? 'var(--tx-bg-tertiary)' : 'var(--tx-brand, #FF6B35)',
                        color: dish.soldOut ? 'var(--tx-text-tertiary)' : '#fff',
                        minWidth: 48, minHeight: 48, padding: 0,
                      }}
                    >
                      <span className="text-lg leading-none">+</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {displayDishes.length === 0 && (
          <div className="text-center py-16 text-sm" style={{ color: 'var(--tx-text-tertiary)' }}>
            {searchQuery ? '未找到匹配菜品' : '暂无菜品'}
          </div>
        )}
      </div>

      {/* ── 底部购物车 ── */}
      <CartBar
        count={cartCount()}
        total={cartTotal()}
        onViewCart={() => navigate('/cart')}
        onCheckout={() => navigate('/checkout')}
      />
    </div>
  );
}
