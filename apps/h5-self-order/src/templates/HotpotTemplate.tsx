/**
 * 火锅模板 — 先选锅底，再选菜品
 *
 * 流程：锅底选择 → 菜品分类浏览 → 购物车
 * 特色：锅底必选校验、鸳鸯锅双选、菜品按涮煮时间标注
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrderStore } from '@/store/useOrderStore';
import type { DishItem } from '@/api/menuApi';
import CartBar from '@/components/CartBar';

// ─── 火锅专用类型 ─────────────────────────────────────────────────────────────

interface SoupBase {
  id: string;
  name: string;
  image: string;
  price: number;
  spicyLevel: 0 | 1 | 2 | 3;
  tags: string[];
  description: string;
}

interface HotpotDish extends DishItem {
  cookTimeSeconds: number;   // 建议涮煮时间
  cookTimeLabel: string;     // 如 "15秒" "3分钟"
  isSignature: boolean;
}

type HotpotStep = 'soup' | 'dishes';

// ─── Mock 数据 ─────────────────────────────────────────────────────────────────

const MOCK_SOUP_BASES: SoupBase[] = [
  { id: 'sb-01', name: '牛油麻辣锅', image: '/images/hotpot/mala.jpg', price: 68, spicyLevel: 3, tags: ['招牌', '重辣'], description: '精选天然牛油，重庆老火锅味道' },
  { id: 'sb-02', name: '番茄锅底', image: '/images/hotpot/tomato.jpg', price: 48, spicyLevel: 0, tags: ['不辣', '鲜美'], description: '新鲜番茄慢熬4小时' },
  { id: 'sb-03', name: '菌汤锅底', image: '/images/hotpot/mushroom.jpg', price: 58, spicyLevel: 0, tags: ['养生', '鲜香'], description: '松茸+牛肝菌+竹荪' },
  { id: 'sb-04', name: '清油麻辣锅', image: '/images/hotpot/qingyou.jpg', price: 58, spicyLevel: 2, tags: ['中辣', '清爽'], description: '植物油底，辣而不燥' },
  { id: 'sb-05', name: '鸳鸯锅（可选两种）', image: '/images/hotpot/yuanyang.jpg', price: 88, spicyLevel: 0, tags: ['热销', '双拼'], description: '左右双格，各选一种锅底' },
];

const MOCK_CATEGORIES = [
  { id: 'cat-meat', name: '鲜切肉类', icon: '' },
  { id: 'cat-ball', name: '丸滑类', icon: '' },
  { id: 'cat-veg', name: '时蔬类', icon: '' },
  { id: 'cat-tofu', name: '豆制品', icon: '' },
  { id: 'cat-seafood', name: '海鲜类', icon: '' },
  { id: 'cat-noodle', name: '主食面点', icon: '' },
  { id: 'cat-drink', name: '饮品', icon: '' },
  { id: 'cat-sauce', name: '蘸料', icon: '' },
];

// ─── 辅助函数 ──────────────────────────────────────────────────────────────────

function spicyDots(level: 0 | 1 | 2 | 3): string {
  if (level === 0) return '不辣';
  return Array(level).fill('🌶').join('');
}

function cookTimeBadgeColor(seconds: number): string {
  if (seconds <= 15) return 'var(--tx-success, #0F6E56)';
  if (seconds <= 60) return 'var(--tx-warning, #BA7517)';
  return 'var(--tx-danger, #A32D2D)';
}

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export default function HotpotTemplate() {
  const navigate = useNavigate();
  const storeId = useOrderStore((s) => s.storeId);
  const storeName = useOrderStore((s) => s.storeName);
  const tableNo = useOrderStore((s) => s.tableNo);
  const cart = useOrderStore((s) => s.cart);
  const addToCart = useOrderStore((s) => s.addToCart);
  const cartCount = useOrderStore((s) => s.cartCount);
  const cartTotal = useOrderStore((s) => s.cartTotal);

  const [step, setStep] = useState<HotpotStep>('soup');
  const [selectedSoups, setSelectedSoups] = useState<SoupBase[]>([]);
  const [isYuanyang, setIsYuanyang] = useState(false);
  const [activeCat, setActiveCat] = useState(MOCK_CATEGORIES[0].id);
  const [dishes, setDishes] = useState<HotpotDish[]>([]);

  // 生产环境从API加载
  useEffect(() => {
    if (!storeId) { navigate('/'); return; }
    // Mock: 生成火锅菜品
    const mockDishes: HotpotDish[] = MOCK_CATEGORIES.flatMap((cat) =>
      Array.from({ length: 5 }, (_, i) => ({
        id: `${cat.id}-${i}`,
        name: `${cat.name}${i + 1}号`,
        categoryId: cat.id,
        description: '新鲜食材每日配送',
        price: 18 + Math.floor(Math.random() * 40),
        images: [`/images/hotpot/${cat.id}-${i}.jpg`],
        tags: [],
        allergens: [],
        customOptions: [],
        soldOut: false,
        sortOrder: i,
        cookTimeSeconds: [8, 15, 30, 60, 120, 180][Math.floor(Math.random() * 6)],
        cookTimeLabel: '',
        isSignature: Math.random() > 0.7,
      })),
    );
    mockDishes.forEach((d) => {
      d.cookTimeLabel = d.cookTimeSeconds < 60
        ? `${d.cookTimeSeconds}秒`
        : `${Math.round(d.cookTimeSeconds / 60)}分钟`;
    });
    setDishes(mockDishes);
  }, [storeId, navigate]);

  // ── 锅底选择逻辑 ──

  const handleSelectSoup = useCallback((soup: SoupBase) => {
    if (soup.id === 'sb-05') {
      // 鸳鸯锅：需选两种
      setIsYuanyang(true);
      setSelectedSoups([soup]);
      return;
    }
    if (isYuanyang && selectedSoups.length === 1 && selectedSoups[0].id === 'sb-05') {
      // 鸳鸯锅的第二个选择
      setSelectedSoups((prev) => [...prev, soup]);
      return;
    }
    setIsYuanyang(false);
    setSelectedSoups([soup]);
  }, [isYuanyang, selectedSoups]);

  const canProceedToDishes = isYuanyang
    ? selectedSoups.length === 2
    : selectedSoups.length === 1;

  const handleConfirmSoup = useCallback(() => {
    if (!canProceedToDishes) return;
    // 把锅底加入购物车
    for (const soup of selectedSoups) {
      const soupAsDish: DishItem = {
        id: soup.id,
        name: soup.name,
        categoryId: 'soup-base',
        description: soup.description,
        price: soup.price,
        images: [soup.image],
        tags: [],
        allergens: [],
        customOptions: [],
        soldOut: false,
        sortOrder: 0,
      };
      addToCart(soupAsDish, 1, {});
    }
    setStep('dishes');
  }, [canProceedToDishes, selectedSoups, addToCart]);

  const getQuantity = (dishId: string) =>
    cart.filter((c) => c.dish.id === dishId).reduce((sum, c) => sum + c.quantity, 0);

  const filteredDishes = dishes.filter((d) => d.categoryId === activeCat);

  // ── 渲染：锅底选择步骤 ──

  if (step === 'soup') {
    return (
      <div className="flex flex-col h-screen" style={{ background: 'var(--tx-bg-primary, #fff)' }}>
        {/* 头部 */}
        <div className="px-4 pt-3 pb-2 flex-shrink-0">
          <div className="flex justify-between items-center mb-2">
            <div>
              <div className="text-lg font-bold" style={{ color: 'var(--tx-text-primary, #2C2C2A)' }}>
                {storeName}
              </div>
              <div className="text-xs mt-0.5" style={{ color: 'var(--tx-text-tertiary, #B4B2A9)' }}>
                {tableNo} 号桌
              </div>
            </div>
            <button
              className="active:scale-95 transition-transform"
              onClick={() => navigate(-1)}
              style={{
                padding: '8px 16px', borderRadius: '999px',
                background: 'var(--tx-bg-tertiary, #F0EDE6)',
                color: 'var(--tx-text-secondary, #5F5E5A)', fontSize: 14,
                minHeight: 48, minWidth: 48,
              }}
            >
              返回
            </button>
          </div>

          {/* 步骤提示 */}
          <div className="flex items-center gap-2 py-3">
            <div className="flex items-center gap-1.5">
              <span
                className="w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-bold"
                style={{ background: 'var(--tx-brand, #FF6B35)' }}
              >
                1
              </span>
              <span className="text-sm font-semibold" style={{ color: 'var(--tx-text-primary, #2C2C2A)' }}>
                选锅底
              </span>
            </div>
            <div className="flex-1 h-px" style={{ background: 'var(--tx-border, #E8E6E1)' }} />
            <div className="flex items-center gap-1.5 opacity-40">
              <span
                className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                style={{ background: 'var(--tx-bg-tertiary, #F0EDE6)', color: 'var(--tx-text-tertiary)' }}
              >
                2
              </span>
              <span className="text-sm" style={{ color: 'var(--tx-text-tertiary)' }}>
                选菜品
              </span>
            </div>
          </div>

          {isYuanyang && selectedSoups.length === 1 && (
            <div
              className="text-sm py-2 px-3 rounded-lg mb-2"
              style={{ background: 'var(--tx-brand-light, #FFF3ED)', color: 'var(--tx-brand, #FF6B35)' }}
            >
              鸳鸯锅已选左侧，请再选一种作为右侧锅底
            </div>
          )}
        </div>

        {/* 锅底列表 */}
        <div className="flex-1 overflow-y-auto px-4 pb-32" style={{ WebkitOverflowScrolling: 'touch' }}>
          {MOCK_SOUP_BASES.map((soup) => {
            const selected = selectedSoups.some((s) => s.id === soup.id);
            return (
              <button
                key={soup.id}
                className="w-full text-left mb-3 active:scale-[0.98] transition-transform"
                onClick={() => handleSelectSoup(soup)}
                style={{
                  display: 'flex', gap: 12, padding: 12,
                  borderRadius: 12,
                  background: 'var(--tx-bg-card, #fff)',
                  border: selected
                    ? '2px solid var(--tx-brand, #FF6B35)'
                    : '2px solid var(--tx-border, #E8E6E1)',
                  boxShadow: selected ? '0 2px 8px rgba(255,107,53,0.15)' : '0 1px 2px rgba(0,0,0,0.05)',
                  minHeight: 56,
                }}
              >
                <div
                  className="flex-shrink-0 rounded-lg overflow-hidden"
                  style={{ width: 80, height: 80, background: 'var(--tx-bg-tertiary, #F0EDE6)' }}
                >
                  <img
                    src={soup.image}
                    alt={soup.name}
                    loading="lazy"
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between">
                    <div className="text-base font-bold" style={{ color: 'var(--tx-text-primary)' }}>
                      {soup.name}
                    </div>
                    {selected && (
                      <span
                        className="text-xs px-2 py-0.5 rounded-full text-white flex-shrink-0"
                        style={{ background: 'var(--tx-brand, #FF6B35)' }}
                      >
                        已选
                      </span>
                    )}
                  </div>
                  <div className="text-xs mt-1" style={{ color: 'var(--tx-text-secondary)' }}>
                    {soup.description}
                  </div>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-sm font-bold" style={{ color: 'var(--tx-brand, #FF6B35)' }}>
                      ¥{soup.price}
                    </span>
                    <span className="text-xs" style={{ color: 'var(--tx-text-tertiary)' }}>
                      {spicyDots(soup.spicyLevel)}
                    </span>
                    {soup.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-xs px-1.5 py-0.5 rounded"
                        style={{ background: 'var(--tx-brand-light, #FFF3ED)', color: 'var(--tx-brand)' }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* 确认锅底 */}
        <div className="fixed bottom-0 left-0 right-0 p-4" style={{ background: 'var(--tx-bg-primary, #fff)' }}>
          <button
            className="w-full active:scale-[0.97] transition-transform"
            disabled={!canProceedToDishes}
            onClick={handleConfirmSoup}
            style={{
              height: 56, borderRadius: 12,
              background: canProceedToDishes ? 'var(--tx-brand, #FF6B35)' : 'var(--tx-bg-tertiary, #E8E6E1)',
              color: canProceedToDishes ? '#fff' : 'var(--tx-text-tertiary)',
              fontSize: 18, fontWeight: 700,
              opacity: canProceedToDishes ? 1 : 0.6,
            }}
          >
            {canProceedToDishes
              ? `确认锅底 · ¥${selectedSoups.reduce((s, b) => s + b.price, 0)} → 选菜品`
              : '请选择锅底'}
          </button>
        </div>
      </div>
    );
  }

  // ── 渲染：菜品选择步骤 ──

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--tx-bg-primary, #fff)' }}>
      {/* 头部 */}
      <div className="px-4 pt-3 pb-2 flex-shrink-0">
        <div className="flex justify-between items-center">
          <div>
            <div className="text-lg font-bold" style={{ color: 'var(--tx-text-primary)' }}>
              {storeName}
            </div>
            <div className="text-xs mt-0.5" style={{ color: 'var(--tx-text-tertiary)' }}>
              锅底: {selectedSoups.map((s) => s.name).join(' + ')}
            </div>
          </div>
          <button
            className="active:scale-95 transition-transform"
            onClick={() => setStep('soup')}
            style={{
              padding: '8px 16px', borderRadius: '999px',
              background: 'var(--tx-bg-tertiary)', color: 'var(--tx-text-secondary)',
              fontSize: 14, minHeight: 48,
            }}
          >
            换锅底
          </button>
        </div>
      </div>

      {/* 左分类 + 右菜品 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 分类 */}
        <div className="flex-shrink-0 overflow-y-auto" style={{ width: 80, background: 'var(--tx-bg-secondary, #F8F7F5)', WebkitOverflowScrolling: 'touch' }}>
          {MOCK_CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              className="w-full active:scale-95 transition-transform"
              onClick={() => setActiveCat(cat.id)}
              style={{
                padding: '16px 8px', textAlign: 'center',
                fontSize: 13,
                color: activeCat === cat.id ? 'var(--tx-brand, #FF6B35)' : 'var(--tx-text-secondary)',
                fontWeight: activeCat === cat.id ? 700 : 400,
                background: activeCat === cat.id ? 'var(--tx-bg-primary, #fff)' : 'transparent',
                borderLeft: activeCat === cat.id ? '3px solid var(--tx-brand)' : '3px solid transparent',
                minHeight: 48,
              }}
            >
              {cat.icon && <div className="text-lg mb-1">{cat.icon}</div>}
              {cat.name}
            </button>
          ))}
        </div>

        {/* 菜品列表 */}
        <div className="flex-1 overflow-y-auto px-3 pb-32" style={{ WebkitOverflowScrolling: 'touch' }}>
          {filteredDishes.map((dish) => {
            const qty = getQuantity(dish.id);
            return (
              <div
                key={dish.id}
                className="flex gap-3 py-3"
                style={{ borderBottom: '1px solid var(--tx-border, #E8E6E1)' }}
              >
                <div
                  className="flex-shrink-0 rounded-lg overflow-hidden relative"
                  style={{ width: 80, height: 80, background: 'var(--tx-bg-tertiary)' }}
                >
                  <img
                    src={dish.images[0]}
                    alt={dish.name}
                    loading="lazy"
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                  {/* 涮煮时间标记 */}
                  <span
                    className="absolute bottom-0 right-0 text-xs text-white px-1.5 py-0.5 rounded-tl-md"
                    style={{ background: cookTimeBadgeColor(dish.cookTimeSeconds), fontSize: 11 }}
                  >
                    {dish.cookTimeLabel}
                  </span>
                </div>
                <div className="flex-1 min-w-0 flex flex-col justify-between">
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-base font-semibold truncate" style={{ color: 'var(--tx-text-primary)' }}>
                        {dish.name}
                      </span>
                      {dish.isSignature && (
                        <span
                          className="text-xs px-1 py-0.5 rounded flex-shrink-0"
                          style={{ background: 'var(--tx-brand-light, #FFF3ED)', color: 'var(--tx-brand)' }}
                        >
                          招牌
                        </span>
                      )}
                    </div>
                    <div className="text-xs mt-1 truncate" style={{ color: 'var(--tx-text-tertiary)' }}>
                      {dish.description}
                    </div>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-base font-bold" style={{ color: 'var(--tx-brand, #FF6B35)' }}>
                      ¥{dish.price}
                    </span>
                    {/* 加减按钮 */}
                    <div className="flex items-center gap-2">
                      {qty > 0 && (
                        <>
                          <button
                            className="rounded-full flex items-center justify-center active:scale-90 transition-transform"
                            style={{
                              width: 32, height: 32,
                              border: '1px solid var(--tx-border)',
                              color: 'var(--tx-text-secondary)',
                              minWidth: 48, minHeight: 48,
                              padding: 0,
                            }}
                            onClick={() => {
                              const cartKey = cart.find((c) => c.dish.id === dish.id)?.cartKey;
                              if (cartKey) useOrderStore.getState().updateQuantity(cartKey, qty - 1);
                            }}
                          >
                            <span className="text-lg leading-none">-</span>
                          </button>
                          <span className="text-base font-semibold w-6 text-center" style={{ color: 'var(--tx-text-primary)' }}>
                            {qty}
                          </span>
                        </>
                      )}
                      <button
                        className="rounded-full flex items-center justify-center active:scale-90 transition-transform"
                        style={{
                          width: 32, height: 32,
                          background: dish.soldOut ? 'var(--tx-bg-tertiary)' : 'var(--tx-brand, #FF6B35)',
                          color: dish.soldOut ? 'var(--tx-text-tertiary)' : '#fff',
                          minWidth: 48, minHeight: 48,
                          padding: 0,
                          opacity: dish.soldOut ? 0.4 : 1,
                        }}
                        disabled={dish.soldOut}
                        onClick={() => addToCart(dish, 1, {})}
                      >
                        <span className="text-lg leading-none">+</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}

          {filteredDishes.length === 0 && (
            <div className="text-center py-12 text-sm" style={{ color: 'var(--tx-text-tertiary)' }}>
              该分类暂无菜品
            </div>
          )}
        </div>
      </div>

      {/* 底部购物车 */}
      <CartBar
        count={cartCount()}
        total={cartTotal()}
        onViewCart={() => navigate('/cart')}
        onCheckout={() => navigate('/checkout')}
      />
    </div>
  );
}
