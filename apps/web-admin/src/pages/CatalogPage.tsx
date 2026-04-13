/**
 * CatalogPage — 菜品管理
 * 真实 API 接入 + 分类筛选 + 四象限视图 + 成本率 + 快速调价
 */
import { useEffect, useState, useRef, useCallback } from 'react';
import { txFetchData } from '../api';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型定义 ───────────────────────────────────────────────

interface Dish {
  id: string;
  name: string;
  category_id: string;
  category_name?: string;
  price_fen: number;
  cost_fen?: number;
  cost_rate?: number;        // 0.0–1.0
  stock_status: 'normal' | 'low' | 'out_of_stock';
  quadrant?: 'star' | 'cash_cow' | 'question' | 'dog';
  is_available: boolean;
  image_url?: string;
  monthly_new?: boolean;
}

interface DishCategory {
  id: string;
  name: string;
  dish_count: number;
}

interface DishListResp {
  items: Dish[];
  total: number;
  page: number;
  size: number;
}

interface SummaryStats {
  total: number;
  avgCostRate: number;
  outOfStock: number;
  monthlyNew: number;
}

// ─── 工具函数 ────────────────────────────────────────────────

/** @deprecated — use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return formatPrice(fen);
}

function costRateColor(rate?: number): string {
  if (rate === undefined || rate === null) return '#8899A6';
  if (rate > 0.5) return '#A32D2D';
  if (rate >= 0.3) return '#BA7517';
  return '#0F6E56';
}

function costRateAntColor(rate?: number): string {
  if (rate === undefined || rate === null) return '#8899A6';
  if (rate > 0.5) return '#A32D2D';
  if (rate >= 0.3) return '#BA7517';
  return '#0F6E56';
}

function stockBadge(status: Dish['stock_status']): { label: string; color: string; bg: string } {
  if (status === 'out_of_stock') return { label: '缺货', color: '#A32D2D', bg: '#3A1515' };
  if (status === 'low') return { label: '低库存', color: '#BA7517', bg: '#3A2A10' };
  return { label: '正常', color: '#0F6E56', bg: '#0E2A22' };
}

function quadrantMeta(q?: Dish['quadrant']): { label: string; emoji: string; color: string } {
  if (q === 'star') return { label: '明星菜品', emoji: '⭐', color: '#FF6B35' };
  if (q === 'cash_cow') return { label: '金牛菜品', emoji: '🐂', color: '#185FA5' };
  if (q === 'question') return { label: '问题菜品', emoji: '❓', color: '#BA7517' };
  if (q === 'dog') return { label: '瘦狗菜品', emoji: '🐕', color: '#5F5E5A' };
  return { label: '未分类', emoji: '—', color: '#5F5E5A' };
}

/** 若 API 未返回 quadrant，根据 cost_rate + is_available 本地估算 */
function inferQuadrant(dish: Dish): Dish['quadrant'] {
  if (dish.quadrant) return dish.quadrant;
  const highMargin = (dish.cost_rate ?? 0.5) < 0.4;
  const available = dish.is_available;
  if (highMargin && available) return 'star';
  if (!highMargin && available) return 'cash_cow';
  if (highMargin && !available) return 'question';
  return 'dog';
}

// ─── 样式常量（深色主题） ────────────────────────────────────

const s = {
  container: {
    backgroundColor: '#0B1A20',
    color: '#E0E0E0',
    minHeight: '100vh',
    padding: '24px 32px',
    fontFamily: 'system-ui, -apple-system, "PingFang SC", sans-serif',
  } as React.CSSProperties,

  header: {
    fontSize: '24px',
    fontWeight: 700,
    color: '#FFFFFF',
    marginBottom: '4px',
  } as React.CSSProperties,

  subtitle: {
    fontSize: '14px',
    color: '#8899A6',
    marginBottom: '24px',
  } as React.CSSProperties,

  card: {
    backgroundColor: '#112B36',
    borderRadius: '12px',
    padding: '20px',
    border: '1px solid #1E3A47',
  } as React.CSSProperties,

  cardTitle: {
    fontSize: '15px',
    fontWeight: 600,
    color: '#4FC3F7',
    marginBottom: '4px',
  } as React.CSSProperties,

  cardValue: {
    fontSize: '28px',
    fontWeight: 700,
    color: '#FFFFFF',
    lineHeight: 1.2,
  } as React.CSSProperties,

  tabBtn: (active: boolean): React.CSSProperties => ({
    padding: '6px 16px',
    borderRadius: '6px',
    border: 'none',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: active ? 600 : 400,
    backgroundColor: active ? '#FF6B35' : '#1E3A47',
    color: active ? '#FFFFFF' : '#8899A6',
    transition: 'all 0.2s',
  }),

  input: {
    backgroundColor: '#1E3A47',
    border: '1px solid #2A4A5A',
    borderRadius: '6px',
    color: '#E0E0E0',
    padding: '7px 12px',
    fontSize: '13px',
    outline: 'none',
    width: '220px',
  } as React.CSSProperties,

  select: {
    backgroundColor: '#1E3A47',
    border: '1px solid #2A4A5A',
    borderRadius: '6px',
    color: '#E0E0E0',
    padding: '7px 12px',
    fontSize: '13px',
    outline: 'none',
    cursor: 'pointer',
  } as React.CSSProperties,

  btn: (variant: 'primary' | 'ghost' | 'danger' = 'primary'): React.CSSProperties => ({
    padding: '6px 14px',
    borderRadius: '6px',
    border: 'none',
    cursor: 'pointer',
    fontSize: '12px',
    fontWeight: 500,
    backgroundColor:
      variant === 'primary' ? '#FF6B35' :
      variant === 'danger' ? '#A32D2D' : '#1E3A47',
    color: '#FFFFFF',
    transition: 'opacity 0.2s',
  }),

  dishRow: {
    display: 'grid',
    gridTemplateColumns: '2fr 1fr 120px 100px 140px 80px 120px',
    alignItems: 'center',
    gap: '12px',
    padding: '12px 16px',
    borderBottom: '1px solid #1E3A47',
    fontSize: '13px',
  } as React.CSSProperties,

  skeletonRow: {
    height: '52px',
    borderRadius: '6px',
    backgroundColor: '#1A3040',
    marginBottom: '4px',
    animation: 'pulse 1.5s ease-in-out infinite',
  } as React.CSSProperties,

  badge: (color: string, bg: string): React.CSSProperties => ({
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: '10px',
    fontSize: '11px',
    fontWeight: 600,
    color,
    backgroundColor: bg,
    whiteSpace: 'nowrap' as const,
  }),

  progressBar: (pct: number, color: string): React.CSSProperties => ({
    width: '100%',
    height: '5px',
    borderRadius: '3px',
    backgroundColor: '#1E3A47',
    position: 'relative' as const,
    overflow: 'hidden',
  }),
};

// ─── 子组件：成本率进度条 ─────────────────────────────────────

function CostRateBar({ rate }: { rate?: number }) {
  const pct = rate !== undefined ? Math.min(rate * 100, 100) : null;
  const color = costRateAntColor(rate);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
        <span style={{ fontSize: '11px', color: '#8899A6' }}>成本率</span>
        <span style={{ fontSize: '11px', color, fontWeight: 600 }}>
          {pct !== null ? `${pct.toFixed(1)}%` : '—'}
        </span>
      </div>
      <div style={s.progressBar(pct ?? 0, color)}>
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            height: '100%',
            width: `${pct ?? 0}%`,
            backgroundColor: color,
            borderRadius: '3px',
            transition: 'width 0.4s ease',
          }}
        />
      </div>
    </div>
  );
}

// ─── 子组件：骨架屏 ───────────────────────────────────────────

function SkeletonRows({ count = 8 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} style={{ ...s.skeletonRow, opacity: 1 - i * 0.08 }} />
      ))}
    </>
  );
}

// ─── 子组件：四象限视图 ───────────────────────────────────────

const QUADRANTS: Array<{ key: Dish['quadrant']; label: string; emoji: string; desc: string; borderColor: string }> = [
  { key: 'star',      label: '明星菜品', emoji: '⭐', desc: '高销量 · 高利润', borderColor: '#FF6B35' },
  { key: 'cash_cow',  label: '金牛菜品', emoji: '🐂', desc: '高销量 · 低利润', borderColor: '#185FA5' },
  { key: 'question',  label: '问题菜品', emoji: '❓', desc: '低销量 · 高利润', borderColor: '#BA7517' },
  { key: 'dog',       label: '瘦狗菜品', emoji: '🐕', desc: '低销量 · 低利润', borderColor: '#5F5E5A' },
];

function QuadrantView({ dishes }: { dishes: Dish[] }) {
  const byQ = (key: Dish['quadrant']) =>
    dishes.filter((d) => inferQuadrant(d) === key);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginTop: '16px' }}>
      {QUADRANTS.map(({ key, label, emoji, desc, borderColor }) => {
        const items = byQ(key);
        const shown = items.slice(0, 5);
        const more = items.length - 5;
        return (
          <div
            key={key}
            style={{
              ...s.card,
              borderLeft: `3px solid ${borderColor}`,
              padding: '16px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <span style={{ fontSize: '18px' }}>{emoji}</span>
              <div>
                <div style={{ fontSize: '14px', fontWeight: 600, color: '#FFFFFF' }}>{label}</div>
                <div style={{ fontSize: '11px', color: '#8899A6' }}>{desc}</div>
              </div>
              <div style={{ marginLeft: 'auto', ...s.badge(borderColor, borderColor + '22') }}>
                {items.length} 道
              </div>
            </div>
            {items.length === 0 ? (
              <div style={{ color: '#5F5E5A', fontSize: '12px', padding: '8px 0' }}>暂无菜品</div>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {shown.map((d) => (
                  <li
                    key={d.id}
                    style={{
                      padding: '5px 0',
                      fontSize: '13px',
                      color: '#C8D8E0',
                      borderBottom: '1px solid #1E3A47',
                      display: 'flex',
                      justifyContent: 'space-between',
                    }}
                  >
                    <span>{d.name}</span>
                    <span style={{ color: '#8899A6' }}>¥{fenToYuan(d.price_fen)}</span>
                  </li>
                ))}
                {more > 0 && (
                  <li style={{ padding: '5px 0', fontSize: '12px', color: '#5F5E5A' }}>
                    等 {more} 项…
                  </li>
                )}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── 子组件：内联调价表单 ────────────────────────────────────

function InlinePriceEditor({
  dish,
  onConfirm,
  onCancel,
}: {
  dish: Dish;
  onConfirm: (newPriceFen: number) => Promise<void>;
  onCancel: () => void;
}) {
  const [val, setVal] = useState(fenToYuan(dish.price_fen));
  const [saving, setSaving] = useState(false);

  async function handleConfirm() {
    const yuan = parseFloat(val);
    if (isNaN(yuan) || yuan <= 0) return;
    setSaving(true);
    try {
      await onConfirm(Math.round(yuan * 100));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
      <span style={{ color: '#8899A6', fontSize: '12px' }}>¥</span>
      <input
        type="number"
        min="0"
        step="0.01"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleConfirm()}
        style={{ ...s.input, width: '80px', padding: '4px 8px' }}
        autoFocus
      />
      <button style={s.btn('primary')} onClick={handleConfirm} disabled={saving}>
        {saving ? '…' : '确认'}
      </button>
      <button style={s.btn('ghost')} onClick={onCancel}>取消</button>
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────

export function CatalogPage() {
  const [view, setView] = useState<'list' | 'quadrant'>('list');
  const [dishes, setDishes] = useState<Dish[]>([]);
  const [categories, setCategories] = useState<DishCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<SummaryStats>({ total: 0, avgCostRate: 0, outOfStock: 0, monthlyNew: 0 });
  const [editingPriceId, setEditingPriceId] = useState<string | null>(null);
  const [editingDetailId, setEditingDetailId] = useState<string | null>(null);
  const PAGE_SIZE = 20;

  // ─── 门店选择（暂用第一门店，后续可扩展） ───
  const [storeId] = useState('default');

  // ─── 获取分类 ───
  useEffect(() => {
    txFetchData<{ categories: DishCategory[] }>(`/api/v1/menu/categories?store_id=${encodeURIComponent(storeId)}`)
      .then((data) => setCategories(data.categories ?? []))
      .catch(() => setCategories([]));
  }, [storeId]);

  // ─── 获取菜品列表 ───
  const fetchDishes = useCallback(async () => {
    setLoading(true);
    try {
      const catParam = selectedCategory !== 'all' ? `&category_id=${encodeURIComponent(selectedCategory)}` : '';
      const searchParam = search ? `&name=${encodeURIComponent(search)}` : '';
      const data = await txFetchData<DishListResp>(
        `/api/v1/menu/dishes?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${PAGE_SIZE}${catParam}${searchParam}`,
      );
      const items = data.items ?? [];
      setDishes(items);
      setTotal(data.total ?? 0);

      // 汇总统计
      const outOfStock = items.filter((d) => d.stock_status === 'out_of_stock').length;
      const monthlyNew = items.filter((d) => d.monthly_new).length;
      const withCostRate = items.filter((d) => d.cost_rate !== undefined);
      const avgCostRate = withCostRate.length
        ? withCostRate.reduce((s, d) => s + (d.cost_rate ?? 0), 0) / withCostRate.length
        : 0;
      setStats({ total: data.total ?? 0, avgCostRate, outOfStock, monthlyNew });
    } catch {
      setDishes([]);
    } finally {
      setLoading(false);
    }
  }, [storeId, page, selectedCategory, search]);

  useEffect(() => {
    fetchDishes();
  }, [fetchDishes]);

  // ─── 搜索防抖 ───
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function handleSearchChange(v: string) {
    setSearch(v);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      setPage(1);
    }, 350);
  }

  // ─── 快速调价（乐观更新） ───
  async function handlePriceUpdate(dishId: string, newPriceFen: number) {
    // 乐观更新本地状态
    setDishes((prev) =>
      prev.map((d) => (d.id === dishId ? { ...d, price_fen: newPriceFen } : d)),
    );
    setEditingPriceId(null);
    try {
      await txFetchData(`/api/v1/menu/dishes/${encodeURIComponent(dishId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ price_fen: newPriceFen }),
      });
    } catch {
      // 回滚
      fetchDishes();
    }
  }

  // ─── 编辑详情保存（可用状态切换） ───
  async function handleToggleAvailability(dish: Dish) {
    const next = !dish.is_available;
    setDishes((prev) =>
      prev.map((d) => (d.id === dish.id ? { ...d, is_available: next } : d)),
    );
    try {
      await txFetchData(`/api/v1/menu/dishes/${encodeURIComponent(dish.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_available: next }),
      });
    } catch {
      fetchDishes();
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  // ─── 渲染汇总卡片 ───
  function renderSummaryCards() {
    const cards = [
      {
        title: '总菜品数',
        value: stats.total,
        suffix: '道',
        color: '#4FC3F7',
      },
      {
        title: '平均成本率',
        value: stats.avgCostRate > 0 ? (stats.avgCostRate * 100).toFixed(1) : '—',
        suffix: stats.avgCostRate > 0 ? '%' : '',
        color: costRateColor(stats.avgCostRate),
      },
      {
        title: '缺货菜品',
        value: stats.outOfStock,
        suffix: '道',
        color: stats.outOfStock > 0 ? '#A32D2D' : '#0F6E56',
        alert: stats.outOfStock > 0,
      },
      {
        title: '本月新增',
        value: stats.monthlyNew,
        suffix: '道',
        color: '#FF6B35',
      },
    ];

    return (
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '16px',
          marginBottom: '24px',
        }}
      >
        {cards.map((c) => (
          <div
            key={c.title}
            style={{
              ...s.card,
              borderTop: c.alert ? '2px solid #A32D2D' : '2px solid transparent',
            }}
          >
            <div style={s.cardTitle}>{c.title}</div>
            <div style={{ ...s.cardValue, color: c.color }}>
              {c.value}
              <span style={{ fontSize: '14px', marginLeft: '4px', color: '#8899A6' }}>
                {c.suffix}
              </span>
            </div>
            {c.alert && (
              <div style={{ fontSize: '11px', color: '#A32D2D', marginTop: '4px' }}>
                ⚠ 需要补货
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  // ─── 渲染列表头 ───
  function renderListHeader() {
    return (
      <div
        style={{
          ...s.dishRow,
          padding: '8px 16px',
          borderBottom: '2px solid #1E3A47',
          color: '#8899A6',
          fontSize: '12px',
          fontWeight: 600,
        }}
      >
        <span>菜品名称</span>
        <span>分类</span>
        <span>售价</span>
        <span>成本率</span>
        <span>库存状态</span>
        <span>四象限</span>
        <span>操作</span>
      </div>
    );
  }

  // ─── 渲染单行菜品 ───
  function renderDishRow(dish: Dish) {
    const stock = stockBadge(dish.stock_status);
    const qMeta = quadrantMeta(inferQuadrant(dish));
    const isEditingPrice = editingPriceId === dish.id;
    const isEditingDetail = editingDetailId === dish.id;

    return (
      <div key={dish.id}>
        <div
          style={{
            ...s.dishRow,
            backgroundColor: isEditingDetail ? '#162F3C' : 'transparent',
            transition: 'background-color 0.2s',
          }}
        >
          {/* 菜品名 */}
          <div>
            <div style={{ fontWeight: 500, color: dish.is_available ? '#E0E0E0' : '#5F5E5A' }}>
              {dish.name}
              {!dish.is_available && (
                <span
                  style={{
                    marginLeft: '6px',
                    fontSize: '10px',
                    color: '#5F5E5A',
                    backgroundColor: '#1E3A47',
                    padding: '1px 5px',
                    borderRadius: '3px',
                  }}
                >
                  已下架
                </span>
              )}
            </div>
          </div>

          {/* 分类 */}
          <div style={{ color: '#8899A6', fontSize: '12px' }}>
            {dish.category_name || '—'}
          </div>

          {/* 售价 */}
          <div style={{ color: '#FFFFFF', fontWeight: 600 }}>
            ¥{fenToYuan(dish.price_fen)}
          </div>

          {/* 成本率进度条 */}
          <div style={{ width: '100%' }}>
            <CostRateBar rate={dish.cost_rate} />
          </div>

          {/* 库存状态 */}
          <div>
            <span style={s.badge(stock.color, stock.bg)}>{stock.label}</span>
          </div>

          {/* 四象限标签 */}
          <div>
            <span
              style={s.badge(qMeta.color, qMeta.color + '22')}
              title={qMeta.label}
            >
              {qMeta.emoji} {qMeta.label.replace('菜品', '')}
            </span>
          </div>

          {/* 操作 */}
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' as const }}>
            <button
              style={s.btn('ghost')}
              onClick={() => setEditingDetailId(isEditingDetail ? null : dish.id)}
            >
              {isEditingDetail ? '收起' : '编辑'}
            </button>
            <button
              style={s.btn('primary')}
              onClick={() => setEditingPriceId(isEditingPrice ? null : dish.id)}
            >
              调价
            </button>
          </div>
        </div>

        {/* 展开：快速调价 */}
        {isEditingPrice && (
          <div
            style={{
              backgroundColor: '#0D2530',
              padding: '12px 16px',
              borderBottom: '1px solid #1E3A47',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
            }}
          >
            <span style={{ fontSize: '12px', color: '#8899A6' }}>
              「{dish.name}」新售价：
            </span>
            <InlinePriceEditor
              dish={dish}
              onConfirm={(p) => handlePriceUpdate(dish.id, p)}
              onCancel={() => setEditingPriceId(null)}
            />
          </div>
        )}

        {/* 展开：编辑表单（状态切换） */}
        {isEditingDetail && (
          <div
            style={{
              backgroundColor: '#0D2530',
              padding: '14px 16px',
              borderBottom: '1px solid #1E3A47',
              display: 'flex',
              gap: '20px',
              alignItems: 'center',
              flexWrap: 'wrap' as const,
            }}
          >
            <div style={{ fontSize: '12px', color: '#8899A6' }}>
              快捷操作：「{dish.name}」
            </div>
            <button
              style={s.btn(dish.is_available ? 'danger' : 'primary')}
              onClick={() => handleToggleAvailability(dish)}
            >
              {dish.is_available ? '下架菜品' : '上架菜品'}
            </button>
            <div style={{ fontSize: '11px', color: '#5F5E5A' }}>
              菜品ID: {dish.id}
            </div>
            {dish.cost_fen !== undefined && (
              <div style={{ fontSize: '12px', color: '#8899A6' }}>
                BOM成本：
                <span style={{ color: '#E0E0E0' }}>¥{fenToYuan(dish.cost_fen)}</span>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // ─── 渲染分页 ───
  function renderPagination() {
    if (totalPages <= 1) return null;
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '12px',
          padding: '16px',
          borderTop: '1px solid #1E3A47',
        }}
      >
        <button
          style={s.btn('ghost')}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
        >
          ← 上一页
        </button>
        <span style={{ fontSize: '13px', color: '#8899A6' }}>
          第 <span style={{ color: '#4FC3F7', fontWeight: 600 }}>{page}</span> / {totalPages} 页
          （共 {total} 道菜）
        </span>
        <button
          style={s.btn('ghost')}
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={page >= totalPages}
        >
          下一页 →
        </button>
      </div>
    );
  }

  // ─── JSX ─────────────────────────────────────────────────

  return (
    <div style={s.container}>
      {/* ── 头部 ── */}
      <h1 style={s.header}>菜品管理</h1>
      <p style={s.subtitle}>菜品档案 / 分类管理 / BOM成本 / 四象限分析 / 快速调价</p>

      {/* ── 汇总卡片 ── */}
      {renderSummaryCards()}

      {/* ── 工具栏 ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          marginBottom: '16px',
          flexWrap: 'wrap' as const,
        }}
      >
        {/* 视图切换 */}
        <button style={s.tabBtn(view === 'list')} onClick={() => setView('list')}>
          列表视图
        </button>
        <button style={s.tabBtn(view === 'quadrant')} onClick={() => setView('quadrant')}>
          四象限视图
        </button>

        <div style={{ flex: 1 }} />

        {/* 搜索 */}
        <input
          type="text"
          placeholder="搜索菜品名称…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
          style={s.input}
        />

        {/* 分类筛选 */}
        <select
          value={selectedCategory}
          onChange={(e) => {
            setSelectedCategory(e.target.value);
            setPage(1);
          }}
          style={s.select}
        >
          <option value="all">全部分类</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}（{c.dish_count}）
            </option>
          ))}
        </select>
      </div>

      {/* ── 内容区 ── */}
      <div style={s.card}>
        {view === 'list' ? (
          <>
            {renderListHeader()}
            {loading ? (
              <div style={{ padding: '12px' }}>
                <SkeletonRows count={8} />
              </div>
            ) : dishes.length === 0 ? (
              <div
                style={{
                  padding: '48px',
                  textAlign: 'center' as const,
                  color: '#5F5E5A',
                  fontSize: '14px',
                }}
              >
                {search ? `未找到包含「${search}」的菜品` : '暂无菜品数据'}
              </div>
            ) : (
              dishes.map(renderDishRow)
            )}
            {renderPagination()}
          </>
        ) : (
          <>
            <div style={{ padding: '4px 0 0 0', color: '#8899A6', fontSize: '13px' }}>
              共 {total} 道菜品，按销量/利润分类展示
            </div>
            {loading ? (
              <div style={{ padding: '12px' }}>
                <SkeletonRows count={4} />
              </div>
            ) : (
              <QuadrantView dishes={dishes} />
            )}
          </>
        )}
      </div>

      {/* ── CSS 动画 (骨架屏脉冲) ── */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
