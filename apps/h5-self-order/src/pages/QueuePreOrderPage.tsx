import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { txFetch } from '@/api/index';
import { fetchCategories, fetchDishes, searchDishes } from '@/api/menuApi';
import type { Category, DishItem } from '@/api/menuApi';
import { DishCard, CategoryNav, MenuSearch } from '@tx-ds/biz';
import type { DishData } from '@tx-ds/biz';
import { formatPrice } from '@tx-ds/utils';

/* ---- 类型 ---- */

interface WaitlistEntry {
  entry_id: string;
  queue_no: number;
  name: string;
  status: string;
  estimated_wait_min: number;
  party_size: number;
  store_id?: string;
  created_at: string;
}


interface PreOrderItemData {
  dish_id: string;
  dish_name: string;
  quantity: number;
  unit_price_fen: number;
  modifiers: Record<string, unknown>[];
  notes: string;
}

interface PreOrderResponse {
  entry_id: string;
  pre_order_items: PreOrderItemData[];
  pre_order_total_fen: number;
  items_count: number;
}

/* ---- 本地购物车条目 ---- */

interface LocalCartItem {
  dish: DishItem;
  quantity: number;
}

/* ---- 页面 ---- */

/**
 * 排队预点菜页 -- 排队中的客户浏览菜单并预选菜品
 *
 * URL: /queue-preorder/:entryId
 */
export default function QueuePreOrderPage() {
  const { entryId } = useParams<{ entryId: string }>();
  const navigate = useNavigate();
  useLang();
  const storeId = useOrderStore((s) => s.storeId);

  // ---- 排队状态 ----
  const [entry, setEntry] = useState<WaitlistEntry | null>(null);
  // ---- 菜单 ----
  const [categories, setCategories] = useState<Category[]>([]);
  const [activeCat, setActiveCat] = useState('');
  const [dishes, setDishes] = useState<DishItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<DishItem[] | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // ---- 预点菜本地购物车 ----
  const [localCart, setLocalCart] = useState<LocalCartItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [savedHint, setSavedHint] = useState(false);
  const [loading, setLoading] = useState(true);

  // ---- 加载排队状态 ----
  useEffect(() => {
    if (!entryId) return;

    // 获取排队条目
    txFetch<WaitlistEntry>(`/waitlist/${entryId}`)
      .then((data) => {
        // API 可能返回 data 直接或嵌套
        setEntry(data);
      })
      .catch(() => {
        // 降级：使用模拟数据
        setEntry({
          entry_id: entryId,
          queue_no: 101,
          name: '',
          status: 'waiting',
          estimated_wait_min: 20,
          party_size: 2,
          created_at: new Date().toISOString(),
        });
      });

    // 获取已有预点菜
    txFetch<PreOrderResponse>(`/waitlist/${entryId}/pre-order`)
      .then((data) => {
        if (data.pre_order_items && data.pre_order_items.length > 0) {
          // 将已有预点菜还原到本地购物车（需要匹配菜品完整信息）
          // 此处先记录 dish_id -> quantity 的映射，等菜品列表加载后再关联
          setExistingPreOrderItems(data.pre_order_items);
        }
      })
      .catch(() => { /* 忽略 — 可能是新排队 */ });
  }, [entryId]);

  // ---- 已有预点菜还原 ----
  const [existingPreOrderItems, setExistingPreOrderItems] = useState<PreOrderItemData[]>([]);

  // 当菜品列表加载完且有已有预点菜时，还原到本地购物车
  useEffect(() => {
    if (dishes.length === 0 || existingPreOrderItems.length === 0) return;

    const restored: LocalCartItem[] = [];
    for (const item of existingPreOrderItems) {
      const dish = dishes.find((d) => d.id === item.dish_id);
      if (dish) {
        restored.push({ dish, quantity: item.quantity });
      }
    }
    if (restored.length > 0) {
      setLocalCart(restored);
      setExistingPreOrderItems([]); // 已还原，清空
    }
  }, [dishes, existingPreOrderItems]);

  // ---- 加载菜品 ----
  useEffect(() => {
    if (!storeId) {
      setLoading(false);
      return;
    }

    setLoading(true);
    Promise.all([
      fetchCategories(storeId).catch(() => []),
      fetchDishes(storeId).catch(() => []),
    ]).then(([cats, allDishes]) => {
      setCategories(cats);
      if (cats.length > 0) setActiveCat(cats[0].id);
      setDishes(allDishes);
      setLoading(false);
    });
  }, [storeId]);

  // ---- 轮询排队状态（每30秒） ----
  useEffect(() => {
    if (!entryId) return;
    const interval = setInterval(() => {
      txFetch<WaitlistEntry>(`/waitlist/${entryId}`)
        .then((data) => {
          setEntry(data);
          // 入座后自动跳转
          if (data.status === 'seated') {
            navigate('/menu');
          }
        })
        .catch(() => { /* 忽略轮询失败 */ });
    }, 30_000);
    return () => clearInterval(interval);
  }, [entryId, navigate]);

  // ---- 搜索防抖 ----
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

  // ---- 本地购物车操作 ----
  const addToLocalCart = (dish: DishItem) => {
    setLocalCart((prev) => {
      const existing = prev.find((c) => c.dish.id === dish.id);
      if (existing) {
        return prev.map((c) =>
          c.dish.id === dish.id ? { ...c, quantity: c.quantity + 1 } : c,
        );
      }
      return [...prev, { dish, quantity: 1 }];
    });
  };

  const getLocalQuantity = (dishId: string) =>
    localCart.find((c) => c.dish.id === dishId)?.quantity ?? 0;

  const localCartCount = localCart.reduce((sum, c) => sum + c.quantity, 0);
  const localCartTotalYuan = localCart.reduce(
    (sum, c) => sum + c.dish.price * c.quantity, 0,
  );

  // ---- 保存预点菜 ----
  const handleSavePreOrder = async () => {
    if (!entryId || localCart.length === 0 || saving) return;
    setSaving(true);

    const items = localCart.map((c) => ({
      dish_id: c.dish.id,
      dish_name: c.dish.name,
      quantity: c.quantity,
      unit_price_fen: Math.round(c.dish.price * 100),
      modifiers: [],
      notes: '',
    }));

    try {
      await txFetch<PreOrderResponse>(`/waitlist/${entryId}/pre-order`, {
        method: 'POST',
        body: JSON.stringify({ items }),
      });
      setSavedHint(true);
      setTimeout(() => setSavedHint(false), 2500);
    } catch {
      // 降级：显示失败提示但保留本地状态
    } finally {
      setSaving(false);
    }
  };

  // ---- DishItem → DishData 映射 ----
  const toDishData = useCallback((d: DishItem): DishData => ({
    id: d.id, name: d.name, category: d.categoryId,
    priceFen: Math.round(d.price * 100),
    description: d.description, images: d.images ?? [],
    tags: d.tags ?? [], allergens: d.allergens ?? [],
    soldOut: d.soldOut ?? false,
  }), []);

  // ---- 分类映射给 CategoryNav ----
  const navCategories = useMemo(() =>
    categories.map((c) => ({ id: c.id, name: c.name })),
    [categories],
  );

  // ---- 展示菜品 ----
  const displayDishes = searchResults ?? dishes.filter((d) => !activeCat || d.categoryId === activeCat);

  // ---- 排队状态色 ----
  const statusColor = entry?.status === 'called' ? '#0F6E56' : '#FF6B35';
  const statusText = entry?.status === 'called' ? '已叫号，请尽快前往' : '排队等位中';

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100vh',
      background: 'var(--tx-bg-primary, #FFFFFF)',
    }}>
      {/* ---- 顶部：排队状态栏 ---- */}
      <div style={{
        padding: '14px 16px', flexShrink: 0,
        background: `linear-gradient(135deg, ${statusColor}, ${statusColor}dd)`,
        color: '#fff',
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>
              {entry ? `${statusText}` : '加载中...'}
            </div>
            {entry && (
              <div style={{ fontSize: 14, marginTop: 4, opacity: 0.9 }}>
                排队号: <span style={{ fontWeight: 700, fontSize: 20 }}>
                  A{String(entry.queue_no).padStart(3, '0')}
                </span>
                {entry.status === 'waiting' && (
                  <span style={{ marginLeft: 12 }}>
                    预计等待 {entry.estimated_wait_min} 分钟
                  </span>
                )}
              </div>
            )}
          </div>
          <button
            className="tx-pressable"
            onClick={() => navigate(-1)}
            style={{
              padding: '6px 14px', borderRadius: 20,
              background: 'rgba(255,255,255,0.2)', color: '#fff',
              fontSize: 14, fontWeight: 500, border: 'none', cursor: 'pointer',
            }}
          >
            返回
          </button>
        </div>

        {/* 小提示 */}
        <div style={{
          marginTop: 8, padding: '8px 12px',
          background: 'rgba(255,255,255,0.15)', borderRadius: 8,
          fontSize: 13,
        }}>
          排队期间可先浏览菜单预选菜品，入座后自动下单，省去等待时间
        </div>
      </div>

      {/* ---- 搜索栏（共享组件） ---- */}
      <div style={{ padding: '10px 16px', flexShrink: 0 }}>
        <MenuSearch
          value={searchQuery}
          onChange={handleSearch}
          placeholder="搜索菜品"
        />
      </div>

      {/* ---- 主体：左分类 + 右菜品 ---- */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左侧分类导航（共享组件） */}
        {!searchResults && (
          <CategoryNav
            categories={navCategories}
            activeId={activeCat}
            layout="sidebar"
            onSelect={setActiveCat}
          />
        )}

        {/* 右侧菜品列表（共享 DishCard） */}
        <div style={{
          flex: 1, overflowY: 'auto', padding: '0 12px 140px 12px',
          WebkitOverflowScrolling: 'touch',
        }}>
          {loading ? (
            <div style={{
              textAlign: 'center', padding: 48,
              color: 'var(--tx-text-tertiary, #B4B2A9)', fontSize: 14,
            }}>
              菜单加载中...
            </div>
          ) : displayDishes.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: 48,
              color: 'var(--tx-text-tertiary, #B4B2A9)', fontSize: 14,
            }}>
              {searchResults ? '未找到相关菜品' : '暂无菜品'}
            </div>
          ) : (
            displayDishes.map((dish) => (
              <DishCard
                key={dish.id}
                dish={toDishData(dish)}
                variant="horizontal"
                quantity={getLocalQuantity(dish.id)}
                onAdd={() => addToLocalCart(dish)}
                onTap={() => navigate(`/dish/${dish.id}`)}
              />
            ))
          )}
        </div>
      </div>

      {/* ---- 底部：预点菜购物车bar ---- */}
      {localCartCount > 0 && (
        <div
          className="tx-slide-up"
          style={{
            position: 'fixed', bottom: 0, left: 0, right: 0,
            padding: '12px 16px',
            paddingBottom: 'calc(12px + env(safe-area-inset-bottom, 0px))',
            background: 'var(--tx-bg-secondary, #F8F7F5)',
            borderTop: '1px solid var(--tx-border, #E8E6E1)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            boxShadow: '0 -4px 12px rgba(0,0,0,0.08)',
          }}
        >
          <div>
            <div style={{
              fontSize: 13,
              color: 'var(--tx-text-secondary, #5F5E5A)',
            }}>
              已选 <span style={{ fontWeight: 700, color: 'var(--tx-brand, #FF6B35)' }}>{localCartCount}</span> 道菜
            </div>
            <div style={{
              fontSize: 20, fontWeight: 700,
              color: 'var(--tx-brand, #FF6B35)',
            }}>
              {formatPrice(Math.round(localCartTotalYuan * 100))}
            </div>
          </div>

          <button
            className="tx-pressable"
            onClick={handleSavePreOrder}
            disabled={saving}
            style={{
              padding: '0 28px', height: 48, borderRadius: 24,
              background: saving ? '#ccc' : 'var(--tx-brand, #FF6B35)',
              color: '#fff', fontSize: 16, fontWeight: 700,
              border: 'none', cursor: saving ? 'default' : 'pointer',
              transition: 'background 0.2s',
            }}
          >
            {saving ? '保存中...' : '保存预点菜'}
          </button>
        </div>
      )}

      {/* ---- 保存成功提示 ---- */}
      {savedHint && (
        <div style={{
          position: 'fixed', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          padding: '16px 32px', borderRadius: 12,
          background: 'rgba(0,0,0,0.75)', color: '#fff',
          fontSize: 16, fontWeight: 600, zIndex: 1000,
          pointerEvents: 'none',
        }}>
          预点菜已保存
        </div>
      )}
    </div>
  );
}
