import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchCategories, fetchDishes, searchDishes, fetchAiRecommendations } from '@/api/menuApi';
import type { Category, DishItem, AiRecommendation } from '@/api/menuApi';
import DishCard from '@/components/DishCard';
import CartBar from '@/components/CartBar';

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
    }).catch(() => { /* mock fallback */ });

    fetchDishes(storeId).then(setDishes).catch(() => { /* mock fallback */ });
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
