import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchCategories, fetchDishes, searchDishes, fetchAiRecommendations } from '@/api/menuApi';
import type { Category, DishItem, AiRecommendation } from '@/api/menuApi';
import DishCard from '@/components/DishCard';
import CartBar from '@/components/CartBar';

// ─── 尝在一起演示 Mock 数据 ──────────────────────────────────────────────────

const MOCK_CATEGORIES: Category[] = [
  { id: 'signature', name: '招牌', icon: '⭐', sortOrder: 1 },
  { id: 'hunan',     name: '湘菜', icon: '🌶️', sortOrder: 2 },
  { id: 'cold',      name: '凉菜', icon: '🥗', sortOrder: 3 },
  { id: 'soup',      name: '汤羹', icon: '🍲', sortOrder: 4 },
  { id: 'staple',    name: '主食', icon: '🍚', sortOrder: 5 },
  { id: 'drinks',    name: '饮品', icon: '🥤', sortOrder: 6 },
];

function makeDish(id: string, name: string, catId: string, price: number, desc: string, tags: DishItem['tags'] = []): DishItem {
  return {
    id, name, categoryId: catId, description: desc, price,
    images: [], tags, allergens: [], customOptions: [], soldOut: false, sortOrder: 1,
  };
}

const MOCK_DISHES: DishItem[] = [
  makeDish('d001', '剁椒鱼头', 'signature', 88, '新鲜花鲢，酱料手工腌制48小时，鲜辣过瘾', [{ type: 'signature', label: '招牌' }, { type: 'spicy2', label: '中辣' }]),
  makeDish('d002', '口味虾', 'signature', 128, '青壳龙虾，秘制口味酱现炒，肉质Q弹', [{ type: 'signature', label: '招牌' }, { type: 'spicy3', label: '特辣' }]),
  makeDish('d003', '毛氏红烧肉', 'signature', 68, '五花肉精选，冰糖入味，软糯不腻', [{ type: 'signature', label: '招牌' }]),
  makeDish('d004', '农家小炒肉', 'hunan', 48, '土猪五花，搭配青椒爆炒，香辣鲜嫩', [{ type: 'spicy2', label: '中辣' }]),
  makeDish('d005', '湘西土匪鸭', 'hunan', 68, '麻辣干香，湘西传统做法', [{ type: 'spicy3', label: '特辣' }]),
  makeDish('d006', '剁椒蒸蛋', 'hunan', 28, '嫩豆腐配剁椒，口感滑嫩', [{ type: 'spicy1', label: '微辣' }]),
  makeDish('d007', '辣椒炒腊肉', 'hunan', 52, '自制腊肉，搭配新鲜辣椒，烟熏香浓', [{ type: 'spicy2', label: '中辣' }]),
  makeDish('d008', '擂辣椒', 'cold', 26, '传统手工擂制，鲜辣开胃', [{ type: 'spicy2', label: '中辣' }]),
  makeDish('d009', '酸辣蕨根粉', 'cold', 24, '手工蕨根粉，酸爽开胃', [{ type: 'spicy1', label: '微辣' }]),
  makeDish('d010', '皮蛋豆腐', 'cold', 22, '嫩豆腐配皮蛋，淋上特调酱汁', []),
  makeDish('d011', '猪肚鸡汤', 'soup', 58, '滋补老母鸡与猪肚慢炖4小时', []),
  makeDish('d012', '酸萝卜老鸭汤', 'soup', 52, '酸萝卜去腻，老鸭鲜甜', []),
  makeDish('d013', '剁椒蛋炒饭', 'staple', 22, '米饭粒粒分明，剁椒提香', [{ type: 'spicy1', label: '微辣' }]),
  makeDish('d014', '手工米粉', 'staple', 18, '湘式手工米粉，劲道爽滑', []),
  makeDish('d015', '冰镇梅子汤', 'drinks', 12, '酸甜开胃，解辣必备', []),
  makeDish('d016', '湘茶冷泡茶', 'drinks', 16, '本地茶农直供，清凉回甘', []),
];

/** 菜单浏览页 — 左分类 + 右菜品列表 */
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

  const [categories, setCategories] = useState<Category[]>([]);
  const [activeCat, setActiveCat] = useState('');
  const [dishes, setDishes] = useState<DishItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<DishItem[] | null>(null);
  const [aiRecs, setAiRecs] = useState<AiRecommendation[]>([]);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // 加载分类和菜品
  useEffect(() => {
    if (!storeId) { navigate('/'); return; }

    fetchCategories(storeId).then((cats) => {
      setCategories(cats);
      if (cats.length > 0) setActiveCat(cats[0].id);
    }).catch(() => {
      // API 不可用时使用演示 mock 数据
      setCategories(MOCK_CATEGORIES);
      setActiveCat(MOCK_CATEGORIES[0].id);
    });

    fetchDishes(storeId).then(setDishes).catch(() => {
      // API 不可用时使用演示 mock 数据
      setDishes(MOCK_DISHES);
    });
  }, [storeId, navigate]);

  // AI推荐
  useEffect(() => {
    if (!storeId) return;
    const dishIds = cart.map((c) => c.dish.id);
    fetchAiRecommendations(storeId, dishIds).then(setAiRecs).catch(() => { /* ignore */ });
  }, [storeId, cart]);

  // 搜索防抖
  const handleSearch = useCallback((q: string) => {
    setSearchQuery(q);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!q.trim()) { setSearchResults(null); return; }
    searchTimerRef.current = setTimeout(async () => {
      try {
        const results = await searchDishes(storeId, q);
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      }
    }, 300);
  }, [storeId]);

  // 语音搜索
  const handleVoiceSearch = () => {
    if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) return;
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      handleSearch(transcript);
    };
    recognition.start();
  };

  const getQuantity = (dishId: string) =>
    cart.filter((c) => c.dish.id === dishId).reduce((sum, c) => sum + c.quantity, 0);

  const displayDishes = searchResults ?? dishes.filter((d) => !activeCat || d.categoryId === activeCat);

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100vh',
      background: 'var(--tx-bg-primary)',
    }}>
      {/* 顶部：门店 + 搜索栏 */}
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
          <button
            className="tx-pressable"
            onClick={() => navigate(-1)}
            style={{
              padding: '6px 14px', borderRadius: 'var(--tx-radius-full)',
              background: 'var(--tx-bg-tertiary)',
              color: 'var(--tx-text-secondary)', fontSize: 'var(--tx-font-sm)',
            }}
          >
            {t('back')}
          </button>
        </div>

        {/* 搜索栏 */}
        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center',
            background: 'var(--tx-bg-tertiary)', borderRadius: 'var(--tx-radius-md)',
            padding: '0 12px', height: 44,
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
              <circle cx="11" cy="11" r="7" stroke="#666" strokeWidth="2"/>
              <path d="M20 20l-3.5-3.5" stroke="#666" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder={t('search')}
              style={{
                flex: 1, height: '100%', marginLeft: 8,
                background: 'transparent', color: 'var(--tx-text-primary)',
                fontSize: 'var(--tx-font-sm)',
              }}
            />
          </div>
          <button
            className="tx-pressable"
            onClick={handleVoiceSearch}
            style={{
              width: 44, height: 44, borderRadius: 'var(--tx-radius-md)',
              background: 'var(--tx-bg-tertiary)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
            aria-label={t('voiceSearch')}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <rect x="9" y="2" width="6" height="12" rx="3" stroke="#A0A0A0" strokeWidth="2"/>
              <path d="M5 11a7 7 0 0014 0" stroke="#A0A0A0" strokeWidth="2" strokeLinecap="round"/>
              <path d="M12 18v4m-3 0h6" stroke="#A0A0A0" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          </button>
        </div>
      </div>

      {/* 主体：左分类 + 右菜品 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左侧分类导航 */}
        {!searchResults && (
          <div style={{
            width: 80, flexShrink: 0, overflowY: 'auto',
            background: 'var(--tx-bg-secondary)',
          }}>
            {categories.map((cat) => (
              <button
                key={cat.id}
                className="tx-pressable"
                onClick={() => setActiveCat(cat.id)}
                style={{
                  width: '100%', padding: '16px 8px',
                  textAlign: 'center', fontSize: 'var(--tx-font-xs)',
                  color: activeCat === cat.id ? 'var(--tx-brand)' : 'var(--tx-text-secondary)',
                  fontWeight: activeCat === cat.id ? 700 : 400,
                  background: activeCat === cat.id ? 'var(--tx-bg-primary)' : 'transparent',
                  borderLeft: activeCat === cat.id ? '3px solid var(--tx-brand)' : '3px solid transparent',
                  transition: 'all 0.2s',
                }}
              >
                {cat.icon && <div style={{ fontSize: 20, marginBottom: 4 }}>{cat.icon}</div>}
                {cat.name}
              </button>
            ))}
          </div>
        )}

        {/* 右侧菜品列表 */}
        <div style={{
          flex: 1, overflowY: 'auto', padding: '0 12px 120px 12px',
        }}>
          {/* AI推荐区 */}
          {aiRecs.length > 0 && !searchResults && (
            <div style={{ marginBottom: 16, marginTop: 12 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12,
              }}>
                <span style={{
                  padding: '2px 8px', borderRadius: 'var(--tx-radius-sm)',
                  background: 'rgba(59, 130, 246, 0.15)',
                  color: 'var(--tx-info)', fontSize: 'var(--tx-font-xs)', fontWeight: 600,
                }}>
                  AI
                </span>
                <span style={{ color: 'var(--tx-text-primary)', fontSize: 'var(--tx-font-sm)', fontWeight: 600 }}>
                  {t('aiRecommend')}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 8 }}>
                {aiRecs.map((rec) => (
                  <div
                    key={rec.dishId}
                    className="tx-pressable"
                    onClick={() => navigate(`/dish/${rec.dishId}`)}
                    style={{
                      minWidth: 140, padding: 10, borderRadius: 'var(--tx-radius-md)',
                      background: 'var(--tx-bg-card)', flexShrink: 0,
                    }}
                  >
                    <img
                      src={rec.dish.images[0] ?? ''}
                      alt={rec.dish.name}
                      loading="lazy"
                      style={{ width: '100%', height: 100, objectFit: 'cover', borderRadius: 8 }}
                    />
                    <div style={{
                      marginTop: 6, fontSize: 'var(--tx-font-sm)', fontWeight: 600,
                      color: 'var(--tx-text-primary)',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    }}>
                      {rec.dish.name}
                    </div>
                    <div style={{
                      fontSize: 'var(--tx-font-xs)', color: 'var(--tx-brand)', marginTop: 2,
                    }}>
                      {t('yuan')}{rec.dish.price}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 菜品列表 */}
          {displayDishes.map((dish) => (
            <DishCard
              key={dish.id}
              dish={dish}
              quantity={getQuantity(dish.id)}
              onAdd={() => addToCart(dish, 1, {})}
              onTap={() => navigate(`/dish/${dish.id}`)}
            />
          ))}

          {displayDishes.length === 0 && (
            <div style={{
              textAlign: 'center', padding: 48,
              color: 'var(--tx-text-tertiary)', fontSize: 'var(--tx-font-sm)',
            }}>
              {searchResults ? 'No results' : t('loading')}
            </div>
          )}
        </div>
      </div>

      {/* 底部购物车栏 */}
      <CartBar
        count={cartCount()}
        total={cartTotal()}
        onViewCart={() => navigate('/cart')}
        onCheckout={() => navigate('/checkout')}
      />
    </div>
  );
}
