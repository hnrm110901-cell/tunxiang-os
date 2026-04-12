/**
 * AddDishSheet — 加菜底部抽屉组件
 *
 * 功能：
 *  - 从屏幕底部滑入，高度 80vh
 *  - 顶部搜索栏（MenuSearch 共享组件）
 *  - 菜品分类 Tab（CategoryNav 共享组件）
 *  - 菜品列表（DishCard compact 共享组件）
 *  - 底部操作区（固定）：已选件数 + 合计 + 确认加菜按钮
 *
 * 2026-04-12 重构：使用 @tx-ds/biz 共享组件替换内联 UI
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { txFetch } from '../api/index';
import { DishCard, CategoryNav, MenuSearch } from '@tx-ds/biz';
import type { DishData } from '@tx-ds/biz';
import { formatPrice } from '@tx-ds/utils';

// ─── Props ───

export interface AddDishSheetProps {
  visible: boolean;
  onClose: () => void;
  orderId: string;
  storeId: string;
  onSuccess?: () => void;
}

// ─── API 类型 ───

interface DishCategory {
  category_id: string;
  category_name: string;
}

interface DishInfo {
  dish_id: string;
  dish_name: string;
  category_id: string;
  price_fen: number;
  image_url?: string;
  tags?: string[];
  sold_out: boolean;
  description?: string;
}

// ─── Mock 数据 ───

const MOCK_CATEGORIES: DishCategory[] = [
  { category_id: 'all', category_name: '全部' },
  { category_id: 'c1', category_name: '招牌热菜' },
  { category_id: 'c2', category_name: '海鲜水产' },
  { category_id: 'c3', category_name: '凉菜小吃' },
  { category_id: 'c4', category_name: '汤品' },
  { category_id: 'c5', category_name: '主食酒水' },
];

const MOCK_DISHES: DishInfo[] = [
  { dish_id: 'd1', dish_name: '剁椒鱼头', category_id: 'c1', price_fen: 9800, sold_out: false, tags: ['招牌'] },
  { dish_id: 'd2', dish_name: '小炒黄牛肉', category_id: 'c1', price_fen: 6800, sold_out: false },
  { dish_id: 'd3', dish_name: '红烧肉', category_id: 'c1', price_fen: 5800, sold_out: false, tags: ['热销'] },
  { dish_id: 'd4', dish_name: '酸菜鱼', category_id: 'c1', price_fen: 7800, sold_out: false, tags: ['新品'] },
  { dish_id: 'd5', dish_name: '波士顿龙虾', category_id: 'c2', price_fen: 28800, sold_out: false, tags: ['时价'] },
  { dish_id: 'd6', dish_name: '蒜蓉蒸虾', category_id: 'c2', price_fen: 8800, sold_out: false },
  { dish_id: 'd7', dish_name: '清蒸鱼', category_id: 'c2', price_fen: 12800, sold_out: true },
  { dish_id: 'd8', dish_name: '凉拌黄瓜', category_id: 'c3', price_fen: 1800, sold_out: false },
  { dish_id: 'd9', dish_name: '夫妻肺片', category_id: 'c3', price_fen: 3800, sold_out: false, tags: ['招牌'] },
  { dish_id: 'd10', dish_name: '老鸭汤', category_id: 'c4', price_fen: 4800, sold_out: false },
  { dish_id: 'd11', dish_name: '米饭', category_id: 'c5', price_fen: 200, sold_out: false },
  { dish_id: 'd12', dish_name: '啤酒', category_id: 'c5', price_fen: 1500, sold_out: false },
];

// ─── 数据转换：DishInfo → DishData ───

const TAG_TYPE_MAP: Record<string, string> = {
  '招牌': 'signature',
  '热销': 'signature',
  '新品': 'new',
  '时价': 'seasonal',
};

function toDishData(d: DishInfo): DishData {
  return {
    id: d.dish_id,
    name: d.dish_name,
    priceFen: d.price_fen,
    category: d.category_id,
    soldOut: d.sold_out,
    images: d.image_url ? [d.image_url] : undefined,
    description: d.description,
    tags: d.tags?.map((t) => ({ type: TAG_TYPE_MAP[t] ?? 'seasonal', label: t })),
  };
}

// ─── 主组件 ───

export function AddDishSheet({ visible, onClose, orderId, storeId, onSuccess }: AddDishSheetProps) {
  const [categories, setCategories] = useState<DishCategory[]>([]);
  const [dishes, setDishes] = useState<DishInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeCategory, setActiveCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [toastMsg, setToastMsg] = useState<{ text: string; type: 'success' | 'error'; show: boolean }>({
    text: '', type: 'success', show: false,
  });
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Toast 工具
  const showToast = useCallback((text: string, type: 'success' | 'error' = 'success') => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToastMsg({ text, type, show: true });
    toastTimer.current = setTimeout(() => {
      setToastMsg((prev) => ({ ...prev, show: false }));
    }, 2000);
  }, []);

  // 加载数据
  const loadData = useCallback(async () => {
    if (!visible) return;
    setLoading(true);
    try {
      const [catRes, dishRes] = await Promise.all([
        txFetch<{ items: DishCategory[] }>(
          `/api/v1/menu/categories?store_id=${encodeURIComponent(storeId)}`,
        ),
        txFetch<{ items: DishInfo[] }>(
          `/api/v1/menu/dishes?store_id=${encodeURIComponent(storeId)}&is_available=true`,
        ),
      ]);
      setCategories([{ category_id: 'all', category_name: '全部' }, ...catRes.items]);
      setDishes(dishRes.items);
    } catch {
      // 降级 Mock
      setCategories(MOCK_CATEGORIES);
      setDishes(MOCK_DISHES);
    } finally {
      setLoading(false);
    }
  }, [visible, storeId]);

  useEffect(() => {
    if (visible) {
      loadData();
      setQuantities({});
      setSearchQuery('');
      setActiveCategory('all');
    }
  }, [visible, loadData]);

  // 过滤菜品
  const filteredDishes = useMemo(() => {
    let result = dishes;
    if (activeCategory !== 'all') {
      result = result.filter((d) => d.category_id === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter((d) => d.dish_name.toLowerCase().includes(q));
    }
    return result;
  }, [dishes, activeCategory, searchQuery]);

  // 计算已选
  const selectedSummary = useMemo(() => {
    let count = 0;
    let totalFen = 0;
    for (const dish of dishes) {
      const qty = quantities[dish.dish_id] || 0;
      if (qty > 0) {
        count += qty;
        totalFen += qty * dish.price_fen;
      }
    }
    return { count, totalFen };
  }, [quantities, dishes]);

  // 修改数量（DishCard onAdd 每次 +1）
  const handleAddDish = useCallback((dishId: string) => {
    setQuantities((prev) => ({
      ...prev,
      [dishId]: (prev[dishId] || 0) + 1,
    }));
  }, []);

  // CategoryNav 分类数据转换
  const navCategories = useMemo(
    () => categories.map((c) => ({ id: c.category_id, name: c.category_name })),
    [categories],
  );

  // 确认加菜
  const handleConfirm = async () => {
    if (selectedSummary.count === 0) return;
    setSubmitting(true);
    try {
      const items = dishes
        .filter((d) => (quantities[d.dish_id] || 0) > 0)
        .map((d) => ({
          dish_id: d.dish_id,
          quantity: quantities[d.dish_id],
          remark: '',
        }));

      await txFetch(
        `/api/v1/trade/orders/${encodeURIComponent(orderId)}/items`,
        {
          method: 'POST',
          body: JSON.stringify({ items }),
        },
      );

      onSuccess?.();
      onClose();
    } catch {
      showToast('加菜失败，请重试', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  if (!visible) return null;

  return (
    <>
      <style>{`
        @keyframes addDishSlideUp {
          from { transform: translateY(100%); }
          to { transform: translateY(0); }
        }
      `}</style>

      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.65)',
          zIndex: 300,
        }}
      />

      {/* 抽屉主体 */}
      <div style={{
        position: 'fixed',
        bottom: 0, left: 0, right: 0,
        height: '80vh',
        background: 'var(--tx-card, #112228)',
        borderRadius: '16px 16px 0 0',
        zIndex: 301,
        display: 'flex',
        flexDirection: 'column',
        animation: 'addDishSlideUp 300ms ease-out',
        overflow: 'hidden',
      }}>

        {/* Toast */}
        <div style={{
          position: 'absolute',
          top: 64,
          left: '50%',
          transform: `translateX(-50%) translateY(${toastMsg.show ? '0' : '-60px'})`,
          transition: 'transform 280ms ease',
          background: toastMsg.type === 'success' ? '#0F6E56' : '#A32D2D',
          color: '#fff',
          padding: '10px 20px',
          borderRadius: 10,
          fontSize: 16,
          fontWeight: 600,
          zIndex: 10,
          whiteSpace: 'nowrap',
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          pointerEvents: 'none',
        }}>
          {toastMsg.text}
        </div>

        {/* ── 标题栏 ── */}
        <div style={{
          padding: '16px 20px 12px',
          borderBottom: '1px solid var(--tx-border, #1a2a33)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>加菜</span>
          <button
            onClick={onClose}
            type="button"
            style={{
              width: 36, height: 36,
              background: 'rgba(100,116,139,0.2)',
              border: 'none',
              borderRadius: '50%',
              color: '#e2e8f0',
              fontSize: 18,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            &#x2715;
          </button>
        </div>

        {/* ── 搜索栏 ── */}
        <div style={{ padding: '12px 16px 0', flexShrink: 0 }}>
          <MenuSearch
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="搜索菜品..."
          />
        </div>

        {/* ── 分类 Tab ── */}
        {!searchQuery && navCategories.length > 0 && (
          <div style={{ flexShrink: 0 }}>
            <CategoryNav
              categories={navCategories}
              activeId={activeCategory}
              layout="topbar"
              onSelect={setActiveCategory}
            />
          </div>
        )}

        {/* ── 菜品列表 ── */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '14px 16px',
          paddingBottom: selectedSummary.count > 0 ? '80px' : '14px',
        }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#64748b', fontSize: 16 }}>
              加载中...
            </div>
          ) : filteredDishes.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#64748b', fontSize: 16 }}>
              {searchQuery ? `未找到"${searchQuery}"相关菜品` : '该分类暂无菜品'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filteredDishes.map((dish) => {
                const qty = quantities[dish.dish_id] || 0;
                return (
                  <DishCard
                    key={dish.dish_id}
                    dish={toDishData(dish)}
                    variant="compact"
                    quantity={qty}
                    showTags
                    onAdd={() => handleAddDish(dish.dish_id)}
                    onTap={() => !dish.sold_out && handleAddDish(dish.dish_id)}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* ── 底部操作区 ── */}
        {selectedSummary.count > 0 && (
          <div style={{
            position: 'absolute',
            bottom: 0, left: 0, right: 0,
            background: 'var(--tx-card, #112228)',
            borderTop: '1px solid var(--tx-border, #1a2a33)',
            padding: '12px 16px',
            paddingBottom: 'calc(12px + env(safe-area-inset-bottom, 0px))',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            zIndex: 5,
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 16, color: '#94a3b8' }}>
                已选 <span style={{ color: '#FF6B35', fontWeight: 700 }}>{selectedSummary.count}</span> 件
              </div>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>
                合计 <span style={{ color: '#FF6B35' }}>{formatPrice(selectedSummary.totalFen)}</span>
              </div>
            </div>

            <button
              onClick={handleConfirm}
              disabled={submitting}
              type="button"
              style={{
                height: 52,
                padding: '0 28px',
                borderRadius: 14,
                background: submitting ? 'rgba(255,107,53,0.5)' : '#FF6B35',
                border: 'none',
                color: '#fff',
                fontSize: 18,
                fontWeight: 700,
                cursor: submitting ? 'default' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                whiteSpace: 'nowrap',
                boxShadow: submitting ? 'none' : '0 4px 12px rgba(255,107,53,0.33)',
              }}
            >
              {submitting ? '提交中...' : '确认加菜'}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
