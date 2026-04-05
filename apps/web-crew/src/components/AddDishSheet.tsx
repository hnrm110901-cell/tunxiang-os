/**
 * AddDishSheet — 加菜底部抽屉组件
 *
 * 功能：
 *  - 从屏幕底部滑入，高度 80vh
 *  - 顶部搜索栏
 *  - 菜品分类 Tab（水平滚动）
 *  - 菜品网格（每行2列）：图片占位 + 菜名 + 价格 + 加减控件
 *  - 底部操作区（固定）：已选件数 + 合计 + 确认加菜按钮
 *
 * 设计规范：
 *  - 纯内联CSS，禁止 Ant Design
 *  - 所有点击区域 ≥ 48×48px
 *  - TypeScript strict
 *  - API 失败降级 Toast，不阻断操作
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { txFetch } from '../api/index';

// ─── Design Tokens ───
const T = {
  bg: '#0B1A20',
  card: '#112228',
  cardAlt: '#1E2A3A',
  border: '#1a2a33',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  success: '#0F6E56',
  danger: '#A32D2D',
  text: '#e2e8f0',
  textSecondary: '#94a3b8',
  muted: '#64748b',
  white: '#ffffff',
  placeholder: '#B4B2A9',
} as const;

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

// ─── (Mock data removed — API is the sole data source) ───

// ─── 工具函数 ───

function formatPrice(fen: number): string {
  return `¥${(fen / 100).toFixed(0)}`;
}

// ─── 子组件：搜索栏 ───

interface SearchBarProps {
  value: string;
  onChange: (v: string) => void;
}

function SearchBar({ value, onChange }: SearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div style={{
      position: 'relative',
      margin: '0 16px',
    }}>
      <span style={{
        position: 'absolute',
        left: 12,
        top: '50%',
        transform: 'translateY(-50%)',
        fontSize: 16,
        color: T.muted,
        pointerEvents: 'none',
      }}>🔍</span>
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="搜索菜品..."
        style={{
          width: '100%',
          height: 44,
          boxSizing: 'border-box',
          background: T.cardAlt,
          border: `1px solid ${T.border}`,
          borderRadius: 10,
          padding: '0 12px 0 36px',
          fontSize: 16,
          color: T.text,
          outline: 'none',
          caretColor: T.accent,
        }}
      />
      {value && (
        <button
          onClick={() => onChange('')}
          style={{
            position: 'absolute',
            right: 8,
            top: '50%',
            transform: 'translateY(-50%)',
            width: 28, height: 28,
            background: T.muted,
            border: 'none',
            borderRadius: '50%',
            color: T.bg,
            fontSize: 14,
            cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >✕</button>
      )}
    </div>
  );
}

// ─── 子组件：分类 Tab ───

interface CategoryTabProps {
  categories: DishCategory[];
  active: string;
  onSelect: (id: string) => void;
}

function CategoryTab({ categories, active, onSelect }: CategoryTabProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // 自动滚动到激活 Tab
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const activeEl = container.querySelector(`[data-cat="${active}"]`) as HTMLElement;
    if (activeEl) {
      const containerRect = container.getBoundingClientRect();
      const elRect = activeEl.getBoundingClientRect();
      if (elRect.left < containerRect.left || elRect.right > containerRect.right) {
        activeEl.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
      }
    }
  }, [active]);

  return (
    <div
      ref={scrollRef}
      style={{
        display: 'flex',
        overflowX: 'auto',
        WebkitOverflowScrolling: 'touch',
        scrollbarWidth: 'none',
        gap: 4,
        padding: '10px 16px 0',
        borderBottom: `1px solid ${T.border}`,
      }}
    >
      <style>{`
        div::-webkit-scrollbar { display: none; }
      `}</style>
      {categories.map(cat => {
        const isActive = cat.category_id === active;
        return (
          <button
            key={cat.category_id}
            data-cat={cat.category_id}
            onClick={() => onSelect(cat.category_id)}
            style={{
              flexShrink: 0,
              height: 40,
              padding: '0 14px',
              borderRadius: '8px 8px 0 0',
              background: isActive ? T.accent : 'transparent',
              border: 'none',
              color: isActive ? T.white : T.muted,
              fontSize: 16,
              fontWeight: isActive ? 600 : 400,
              cursor: 'pointer',
              transition: 'all 200ms',
              whiteSpace: 'nowrap',
              marginBottom: isActive ? 0 : 0,
              borderBottom: isActive ? `2px solid ${T.accent}` : '2px solid transparent',
            }}
          >
            {cat.category_name}
          </button>
        );
      })}
    </div>
  );
}

// ─── 子组件：数量控件 ───

interface QtyControlProps {
  qty: number;
  soldOut: boolean;
  onChange: (newQty: number) => void;
}

function QtyControl({ qty, soldOut, onChange }: QtyControlProps) {
  if (soldOut) {
    return (
      <div style={{
        height: 32,
        padding: '0 10px',
        background: `${T.muted}22`,
        borderRadius: 8,
        fontSize: 16,
        color: T.muted,
        display: 'flex', alignItems: 'center',
      }}>
        已沽清
      </div>
    );
  }

  if (qty === 0) {
    return (
      <button
        onClick={() => onChange(1)}
        style={{
          width: 36, height: 36,
          borderRadius: 10,
          background: T.accent,
          border: 'none',
          color: T.white,
          fontSize: 22,
          fontWeight: 700,
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'transform 200ms',
        }}
        onPointerDown={e => { e.currentTarget.style.transform = 'scale(0.9)'; }}
        onPointerUp={e => { e.currentTarget.style.transform = 'scale(1)'; }}
        onPointerLeave={e => { e.currentTarget.style.transform = 'scale(1)'; }}
      >
        +
      </button>
    );
  }

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
    }}>
      <button
        onClick={() => onChange(Math.max(0, qty - 1))}
        style={{
          width: 32, height: 32,
          borderRadius: 8,
          background: `${T.muted}33`,
          border: `1px solid ${T.border}`,
          color: T.text,
          fontSize: 20,
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'transform 200ms',
        }}
        onPointerDown={e => { e.currentTarget.style.transform = 'scale(0.9)'; }}
        onPointerUp={e => { e.currentTarget.style.transform = 'scale(1)'; }}
        onPointerLeave={e => { e.currentTarget.style.transform = 'scale(1)'; }}
      >
        −
      </button>
      <span style={{ fontSize: 18, fontWeight: 700, color: T.accent, minWidth: 20, textAlign: 'center' }}>
        {qty}
      </span>
      <button
        onClick={() => onChange(qty + 1)}
        style={{
          width: 32, height: 32,
          borderRadius: 8,
          background: T.accent,
          border: 'none',
          color: T.white,
          fontSize: 20,
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'transform 200ms',
        }}
        onPointerDown={e => { e.currentTarget.style.transform = 'scale(0.9)'; }}
        onPointerUp={e => { e.currentTarget.style.transform = 'scale(1)'; }}
        onPointerLeave={e => { e.currentTarget.style.transform = 'scale(1)'; }}
      >
        +
      </button>
    </div>
  );
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
      setToastMsg(prev => ({ ...prev, show: false }));
    }, 2000);
  }, []);

  // 加载数据
  const loadData = useCallback(async () => {
    if (!visible) return;
    setLoading(true);
    try {
      const [catRes, dishRes] = await Promise.all([
        txFetch<{ items: DishCategory[] }>(
          `/api/v1/menu/categories?store_id=${encodeURIComponent(storeId)}`
        ),
        txFetch<{ items: DishInfo[] }>(
          `/api/v1/menu/dishes?store_id=${encodeURIComponent(storeId)}&is_available=true`
        ),
      ]);
      setCategories([{ category_id: 'all', category_name: '全部' }, ...catRes.items]);
      setDishes(dishRes.items);
    } catch {
      // API 失败：设空数组 + 提示用户
      setCategories([{ category_id: 'all', category_name: '全部' }]);
      setDishes([]);
      showToast('加载菜品失败，请重试', 'error');
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
      result = result.filter(d => d.category_id === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(d => d.dish_name.toLowerCase().includes(q));
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

  // 修改数量
  const handleQtyChange = useCallback((dishId: string, newQty: number) => {
    setQuantities(prev => {
      if (newQty === 0) {
        const next = { ...prev };
        delete next[dishId];
        return next;
      }
      return { ...prev, [dishId]: newQty };
    });
  }, []);

  // 确认加菜
  const handleConfirm = async () => {
    if (selectedSummary.count === 0) return;
    setSubmitting(true);
    try {
      const items = dishes
        .filter(d => (quantities[d.dish_id] || 0) > 0)
        .map(d => ({
          dish_id: d.dish_id,
          quantity: quantities[d.dish_id],
          remark: '',
        }));

      await txFetch(
        `/api/v1/trade/orders/${encodeURIComponent(orderId)}/items`,
        {
          method: 'POST',
          body: JSON.stringify({ items }),
        }
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

  // 卡片宽度：(屏幕 - 容器padding 32px - gap 12px) / 2
  // 使用 calc 动态计算

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
        background: T.card,
        borderRadius: '16px 16px 0 0',
        zIndex: 301,
        display: 'flex',
        flexDirection: 'column',
        animation: 'addDishSlideUp 300ms ease-out',
        overflow: 'hidden',
      }}>

        {/* Toast（内嵌在弹层中） */}
        <div style={{
          position: 'absolute',
          top: 64,
          left: '50%',
          transform: `translateX(-50%) translateY(${toastMsg.show ? '0' : '-60px'})`,
          transition: 'transform 280ms ease',
          background: toastMsg.type === 'success' ? T.success : T.danger,
          color: T.white,
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
          borderBottom: `1px solid ${T.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: T.white }}>加菜</span>
          <button
            onClick={onClose}
            style={{
              width: 36, height: 36,
              background: `${T.muted}33`,
              border: 'none',
              borderRadius: '50%',
              color: T.text,
              fontSize: 18,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >✕</button>
        </div>

        {/* ── 搜索栏 ── */}
        <div style={{ paddingTop: 12, paddingBottom: 0, flexShrink: 0 }}>
          <SearchBar value={searchQuery} onChange={setSearchQuery} />
        </div>

        {/* ── 分类 Tab ── */}
        {!searchQuery && (
          <div style={{ flexShrink: 0 }}>
            <CategoryTab
              categories={categories}
              active={activeCategory}
              onSelect={setActiveCategory}
            />
          </div>
        )}

        {/* ── 菜品网格 ── */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '14px 16px',
          // 底部留出操作区高度
          paddingBottom: selectedSummary.count > 0 ? '80px' : '14px',
        }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: T.muted, fontSize: 16 }}>
              加载中...
            </div>
          ) : filteredDishes.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: T.muted, fontSize: 16 }}>
              {searchQuery ? `未找到"${searchQuery}"相关菜品` : '该分类暂无菜品'}
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 12,
            }}>
              {filteredDishes.map(dish => {
                const qty = quantities[dish.dish_id] || 0;
                const isSelected = qty > 0;
                return (
                  <div
                    key={dish.dish_id}
                    style={{
                      background: T.cardAlt,
                      borderRadius: 12,
                      overflow: 'hidden',
                      border: isSelected
                        ? `2px solid ${T.accent}`
                        : `1px solid ${T.border}`,
                      opacity: dish.sold_out ? 0.6 : 1,
                      transition: 'border-color 200ms',
                    }}
                  >
                    {/* 菜品图片占位 */}
                    <div style={{
                      width: '100%',
                      aspectRatio: '4/3',
                      background: `linear-gradient(135deg, #1a2a33 0%, #0B1A20 100%)`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      position: 'relative',
                      overflow: 'hidden',
                    }}>
                      {dish.image_url ? (
                        <img
                          src={dish.image_url}
                          alt={dish.dish_name}
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        />
                      ) : (
                        <span style={{ fontSize: 36 }}>🍽</span>
                      )}

                      {/* 标签 */}
                      {dish.tags && dish.tags.length > 0 && !dish.sold_out && (
                        <div style={{
                          position: 'absolute',
                          top: 6, left: 6,
                          background: T.accent,
                          color: T.white,
                          fontSize: 12,
                          padding: '2px 6px',
                          borderRadius: 4,
                          fontWeight: 600,
                        }}>
                          {dish.tags[0]}
                        </div>
                      )}

                      {/* 沽清遮罩 */}
                      {dish.sold_out && (
                        <div style={{
                          position: 'absolute', inset: 0,
                          background: 'rgba(0,0,0,0.55)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                          <span style={{
                            background: T.danger,
                            color: T.white,
                            fontSize: 14,
                            fontWeight: 700,
                            padding: '4px 10px',
                            borderRadius: 6,
                          }}>
                            已沽清
                          </span>
                        </div>
                      )}

                      {/* 已选数量角标 */}
                      {isSelected && (
                        <div style={{
                          position: 'absolute',
                          top: 6, right: 6,
                          width: 22, height: 22,
                          borderRadius: '50%',
                          background: T.accent,
                          color: T.white,
                          fontSize: 13,
                          fontWeight: 700,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                          {qty}
                        </div>
                      )}
                    </div>

                    {/* 菜品信息 */}
                    <div style={{ padding: '10px 10px 12px' }}>
                      <div style={{
                        fontSize: 16,
                        fontWeight: 600,
                        color: T.white,
                        marginBottom: 4,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {dish.dish_name}
                      </div>
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}>
                        <span style={{
                          fontSize: 16,
                          fontWeight: 700,
                          color: T.accent,
                        }}>
                          {formatPrice(dish.price_fen)}
                        </span>
                        <QtyControl
                          qty={qty}
                          soldOut={dish.sold_out}
                          onChange={newQty => handleQtyChange(dish.dish_id, newQty)}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── 底部操作区（固定，仅有选中时显示） ── */}
        {selectedSummary.count > 0 && (
          <div style={{
            position: 'absolute',
            bottom: 0, left: 0, right: 0,
            background: T.card,
            borderTop: `1px solid ${T.border}`,
            padding: '12px 16px',
            paddingBottom: 'calc(12px + env(safe-area-inset-bottom, 0px))',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            zIndex: 5,
          }}>
            {/* 已选摘要 */}
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 16, color: T.textSecondary }}>
                已选 <span style={{ color: T.accent, fontWeight: 700 }}>{selectedSummary.count}</span> 件
              </div>
              <div style={{ fontSize: 18, fontWeight: 700, color: T.white }}>
                合计 <span style={{ color: T.accent }}>{formatPrice(selectedSummary.totalFen)}</span>
              </div>
            </div>

            {/* 确认加菜 */}
            <button
              onClick={handleConfirm}
              disabled={submitting}
              style={{
                height: 52,
                padding: '0 28px',
                borderRadius: 14,
                background: submitting ? `${T.accent}88` : T.accent,
                border: 'none',
                color: T.white,
                fontSize: 18,
                fontWeight: 700,
                cursor: submitting ? 'default' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                transition: 'transform 200ms, background 200ms',
                boxShadow: submitting ? 'none' : `0 4px 12px ${T.accent}55`,
                whiteSpace: 'nowrap',
              }}
              onPointerDown={e => { if (!submitting) { e.currentTarget.style.transform = 'scale(0.97)'; e.currentTarget.style.background = T.accentActive; } }}
              onPointerUp={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.background = submitting ? `${T.accent}88` : T.accent; }}
              onPointerLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.background = submitting ? `${T.accent}88` : T.accent; }}
            >
              {submitting ? '提交中...' : '确认加菜'}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
