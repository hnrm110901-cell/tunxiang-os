/**
 * MenuEngineeringPage — 菜单工程分析页
 *
 * BCG矩阵变体，以销量×毛利率将菜品分为四象限：
 *   ⭐ 明星菜（高销量+高毛利）→ 绿色
 *   💰 金牛菜（低销量+高毛利）→ 蓝色
 *   🔥 犁头菜（高销量+低毛利）→ 橙色
 *   💀 瘦狗菜（低销量+低毛利）→ 灰/红色
 *
 * 数据接口：
 *   GET  /api/v1/menu/engineering-analysis?period=week
 *   PATCH /api/v1/dishes/{dish_id}  { status: 'soldout' }
 */
import { useState, useEffect, useCallback, useMemo } from 'react';

// ─── 类型 ───

type Quadrant = 'star' | 'cash_cow' | 'plowshare' | 'dog';
type Period = 'today' | 'week' | 'month';
type SortKey = 'sales_count' | 'gross_margin' | 'score';

interface DishItem {
  id: string;
  name: string;
  category: string;
  price: number;       // 分
  cost: number;        // 分
  gross_margin: number; // 0~1
  sales_count: number;
  quadrant: Quadrant;
}

interface Summary {
  star: number;
  cash_cow: number;
  plowshare: number;
  dog: number;
}

interface AnalysisData {
  dishes: DishItem[];
  summary: Summary;
}

// ─── 常量 ───

const API_BASE: string = (window as unknown as Record<string, unknown>).__STORE_API_BASE__ as string || '';
const STORE_ID: string = (window as unknown as Record<string, unknown>).__STORE_ID__ as string || '';
const TENANT_ID: string = (window as unknown as Record<string, unknown>).__TENANT_ID__ as string || '';

const PERIOD_LABELS: Record<Period, string> = {
  today: '今天',
  week:  '本周',
  month: '本月',
};

const QUADRANT_META: Record<Quadrant, {
  label: string;
  icon: string;
  color: string;
  bg: string;
  border: string;
  advice: string;
}> = {
  star: {
    label:  '明星菜',
    icon:   '⭐',
    color:  '#22C55E',
    bg:     '#052E16',
    border: '#166534',
    advice: '加大备货，保障供应稳定',
  },
  cash_cow: {
    label:  '金牛菜',
    icon:   '💰',
    color:  '#60A5FA',
    bg:     '#1E3A5F',
    border: '#2563EB',
    advice: '重点推荐，提升曝光度',
  },
  plowshare: {
    label:  '犁头菜',
    icon:   '🔥',
    color:  '#FB923C',
    bg:     '#431407',
    border: '#EA580C',
    advice: '优化食材采购，控制成本',
  },
  dog: {
    label:  '瘦狗菜',
    icon:   '💀',
    color:  '#9CA3AF',
    bg:     '#1F2937',
    border: '#4B5563',
    advice: '建议评估下架，释放运营资源',
  },
};

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function pct(v: number): string {
  return (v * 100).toFixed(1) + '%';
}

/** 综合评分 = 归一化销量 × 0.5 + 毛利率 × 0.5 */
function compositeScore(dish: DishItem, maxSales: number): number {
  const normSales = maxSales > 0 ? dish.sales_count / maxSales : 0;
  return normSales * 0.5 + dish.gross_margin * 0.5;
}

// ─── Mock 数据（API 不可用时使用） ───

const MOCK_DATA: AnalysisData = {
  dishes: [
    { id: 'd01', name: '宫保鸡丁',   category: '热菜', price: 3800,  cost: 1200, gross_margin: 0.684, sales_count: 156, quadrant: 'star'      },
    { id: 'd02', name: '佛跳墙',     category: '热菜', price: 18800, cost: 8000, gross_margin: 0.574, sales_count: 18,  quadrant: 'cash_cow'  },
    { id: 'd03', name: '鱼香肉丝',   category: '热菜', price: 3200,  cost: 1500, gross_margin: 0.531, sales_count: 203, quadrant: 'star'      },
    { id: 'd04', name: '口水鸡',     category: '凉菜', price: 4800,  cost: 1800, gross_margin: 0.625, sales_count: 87,  quadrant: 'cash_cow'  },
    { id: 'd05', name: '夫妻肺片',   category: '凉菜', price: 4200,  cost: 1900, gross_margin: 0.548, sales_count: 122, quadrant: 'star'      },
    { id: 'd06', name: '凉拌黄瓜',   category: '凉菜', price: 1800,  cost: 400,  gross_margin: 0.778, sales_count: 280, quadrant: 'star'      },
    { id: 'd07', name: '小笼包',     category: '主食', price: 2200,  cost: 1100, gross_margin: 0.500, sales_count: 195, quadrant: 'plowshare' },
    { id: 'd08', name: '手工饺子',   category: '主食', price: 2800,  cost: 1500, gross_margin: 0.464, sales_count: 43,  quadrant: 'dog'       },
    { id: 'd09', name: '鲜榨橙汁',   category: '饮品', price: 1800,  cost: 300,  gross_margin: 0.833, sales_count: 65,  quadrant: 'cash_cow'  },
    { id: 'd10', name: '招牌老汤面', category: '主食', price: 2600,  cost: 900,  gross_margin: 0.654, sales_count: 31,  quadrant: 'dog'       },
  ],
  summary: { star: 4, cash_cow: 3, plowshare: 1, dog: 2 },
};

// ─── 子组件：象限分布饼图（纯 div 实现） ───

interface QuadrantChartProps {
  summary: Summary;
}

function QuadrantChart({ summary }: QuadrantChartProps) {
  const total = summary.star + summary.cash_cow + summary.plowshare + summary.dog;
  if (total === 0) return null;

  const segments: { key: Quadrant; count: number }[] = [
    { key: 'star',      count: summary.star      },
    { key: 'cash_cow',  count: summary.cash_cow  },
    { key: 'plowshare', count: summary.plowshare },
    { key: 'dog',       count: summary.dog       },
  ];

  // 用水平条形图代替饼图（纯 div，无 SVG 依赖）
  return (
    <div
      style={{
        background: '#1F2937',
        border: '1px solid #374151',
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
      }}
    >
      <div style={{ color: '#9CA3AF', fontSize: 14, marginBottom: 12 }}>象限分布（共 {total} 个菜品）</div>

      {/* 复合进度条 */}
      <div style={{ display: 'flex', height: 28, borderRadius: 6, overflow: 'hidden', marginBottom: 12 }}>
        {segments.map(({ key, count }) => {
          const w = (count / total) * 100;
          if (w === 0) return null;
          const meta = QUADRANT_META[key];
          return (
            <div
              key={key}
              title={`${meta.icon}${meta.label}: ${count} 项`}
              style={{
                width: `${w}%`,
                background: meta.color,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 12,
                color: '#111827',
                fontWeight: 700,
                transition: 'width 0.4s ease',
                overflow: 'hidden',
                whiteSpace: 'nowrap',
              }}
            >
              {w >= 12 ? count : ''}
            </div>
          );
        })}
      </div>

      {/* 图例 */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {segments.map(({ key, count }) => {
          const meta = QUADRANT_META[key];
          const ratio = Math.round((count / total) * 100);
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  background: meta.color,
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 13, color: '#D1D5DB' }}>
                {meta.icon}{meta.label}
                <span style={{ color: '#6B7280', marginLeft: 4 }}>{count}（{ratio}%）</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── 子组件：象限卡片（TOP5）───

interface QuadrantCardProps {
  quadrant: Quadrant;
  dishes: DishItem[];
  onSoldout: (dishId: string, dishName: string) => void;
  soldoutIds: Set<string>;
}

function QuadrantCard({ quadrant, dishes, onSoldout, soldoutIds }: QuadrantCardProps) {
  const meta = QUADRANT_META[quadrant];
  const top5 = dishes
    .filter(d => d.quadrant === quadrant)
    .sort((a, b) => b.sales_count - a.sales_count)
    .slice(0, 5);

  return (
    <div
      style={{
        background: meta.bg,
        border: `1px solid ${meta.border}`,
        borderRadius: 12,
        padding: 14,
      }}
    >
      {/* 卡片标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
        <span style={{ fontSize: 18 }}>{meta.icon}</span>
        <span style={{ color: meta.color, fontWeight: 700, fontSize: 15 }}>{meta.label}</span>
      </div>

      {/* TOP5 列表 */}
      {top5.length === 0 ? (
        <div style={{ color: '#6B7280', fontSize: 13 }}>暂无菜品</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {top5.map((d, idx) => (
            <div
              key={d.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <span style={{ color: '#6B7280', fontSize: 12, width: 16, textAlign: 'right', flexShrink: 0 }}>
                {idx + 1}
              </span>
              <span
                style={{
                  flex: 1,
                  color: '#F9FAFB',
                  fontSize: 14,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {d.name}
              </span>
              <span style={{ color: '#9CA3AF', fontSize: 12, flexShrink: 0 }}>
                {d.sales_count}份
              </span>
              <span style={{ color: meta.color, fontSize: 12, flexShrink: 0 }}>
                {pct(d.gross_margin)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 操作建议 */}
      <div
        style={{
          marginTop: 10,
          padding: '8px 10px',
          background: '#111827',
          borderRadius: 8,
          fontSize: 12,
          color: '#9CA3AF',
        }}
      >
        AI建议：{meta.advice}
      </div>

      {/* 瘦狗菜：下架按钮 */}
      {quadrant === 'dog' && top5.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          {top5.map(d => (
            <button
              key={d.id}
              disabled={soldoutIds.has(d.id)}
              onClick={() => onSoldout(d.id, d.name)}
              style={{
                height: 48,
                width: '100%',
                background: soldoutIds.has(d.id) ? '#374151' : '#7F1D1D',
                color: soldoutIds.has(d.id) ? '#6B7280' : '#FCA5A5',
                border: `1px solid ${soldoutIds.has(d.id) ? '#4B5563' : '#EF4444'}`,
                borderRadius: 8,
                cursor: soldoutIds.has(d.id) ? 'not-allowed' : 'pointer',
                fontSize: 13,
                fontWeight: 600,
                textAlign: 'left',
                padding: '0 12px',
              }}
            >
              {soldoutIds.has(d.id) ? `✓ 已下架：${d.name}` : `下架：${d.name}`}
            </button>
          ))}
        </div>
      )}

      {/* 明星菜：备货建议 */}
      {quadrant === 'star' && top5.length > 0 && (
        <div
          style={{
            marginTop: 8,
            padding: '10px 12px',
            background: '#052E16',
            border: '1px solid #166534',
            borderRadius: 8,
            fontSize: 13,
            color: '#86EFAC',
          }}
        >
          备货建议：{top5.map(d => d.name).join('、')} 需增加备货量约 20%
        </div>
      )}
    </div>
  );
}

// ─── 子组件：菜品行 ───

interface DishRowProps {
  dish: DishItem;
  rank: number;
  onSoldout: (dishId: string, dishName: string) => void;
  isSoldout: boolean;
}

function DishRow({ dish, rank, onSoldout, isSoldout }: DishRowProps) {
  const meta = QUADRANT_META[dish.quadrant];
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '12px 16px',
        gap: 10,
        borderBottom: '1px solid #1F2937',
        minHeight: 56,
      }}
    >
      {/* 排名 */}
      <span
        style={{
          color: rank <= 3 ? '#FF6B35' : '#6B7280',
          fontSize: 14,
          fontWeight: 700,
          width: 22,
          textAlign: 'right',
          flexShrink: 0,
        }}
      >
        {rank}
      </span>

      {/* 菜品名 + 象限 badge */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            color: '#F9FAFB',
            fontSize: 16,
            fontWeight: 600,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {dish.name}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
          <span
            style={{
              fontSize: 11,
              color: meta.color,
              background: meta.bg,
              border: `1px solid ${meta.border}`,
              borderRadius: 4,
              padding: '1px 6px',
              whiteSpace: 'nowrap',
            }}
          >
            {meta.icon}{meta.label}
          </span>
          <span style={{ fontSize: 12, color: '#6B7280' }}>{dish.category}</span>
        </div>
      </div>

      {/* 价格/成本/毛利 */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', flexShrink: 0, gap: 1 }}>
        <span style={{ color: '#FF6B35', fontSize: 14, fontWeight: 700 }}>
          ¥{fenToYuan(dish.price)}
        </span>
        <span style={{ color: '#6B7280', fontSize: 12 }}>
          成本¥{fenToYuan(dish.cost)}
        </span>
        <span style={{ color: meta.color, fontSize: 13, fontWeight: 600 }}>
          {pct(dish.gross_margin)}
        </span>
      </div>

      {/* 销量 */}
      <div style={{ textAlign: 'right', flexShrink: 0, width: 48 }}>
        <div style={{ color: '#F9FAFB', fontSize: 15, fontWeight: 700 }}>{dish.sales_count}</div>
        <div style={{ color: '#6B7280', fontSize: 11 }}>份</div>
      </div>

      {/* 下架按钮（仅瘦狗菜显示） */}
      {dish.quadrant === 'dog' && (
        <button
          disabled={isSoldout}
          onClick={() => onSoldout(dish.id, dish.name)}
          style={{
            height: 48,
            padding: '0 10px',
            background: isSoldout ? '#374151' : '#7F1D1D',
            color: isSoldout ? '#6B7280' : '#FCA5A5',
            border: `1px solid ${isSoldout ? '#4B5563' : '#EF4444'}`,
            borderRadius: 8,
            cursor: isSoldout ? 'not-allowed' : 'pointer',
            fontSize: 12,
            fontWeight: 600,
            flexShrink: 0,
            whiteSpace: 'nowrap',
          }}
        >
          {isSoldout ? '已下架' : '下架'}
        </button>
      )}
    </div>
  );
}

// ─── 主页面 ───

export function MenuEngineeringPage() {
  const [period, setPeriod]     = useState<Period>('week');
  const [category, setCategory] = useState('');
  const [sortKey, setSortKey]   = useState<SortKey>('sales_count');
  const [data, setData]         = useState<AnalysisData>(MOCK_DATA);
  const [loading, setLoading]   = useState(false);
  const [soldoutIds, setSoldoutIds] = useState<Set<string>>(new Set());
  const [toast, setToast]       = useState('');

  // ─── 派生：分类列表 ───
  const categories = useMemo(() => {
    const cats = Array.from(new Set(data.dishes.map(d => d.category).filter(Boolean)));
    return ['全部', ...cats];
  }, [data.dishes]);

  // ─── 拉取数据 ───
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ period });
      if (STORE_ID)  params.set('store_id', STORE_ID);
      if (category && category !== '全部') params.set('category', category);

      const headers: Record<string, string> = {};
      if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;

      const url = `${API_BASE}/api/v1/menu/engineering-analysis?${params.toString()}`;
      const resp = await fetch(url, { headers });
      if (!resp.ok) { setData(MOCK_DATA); return; }
      const json = await resp.json() as { ok: boolean; data: AnalysisData };
      if (json.ok && json.data) {
        setData(json.data);
      } else {
        setData(MOCK_DATA);
      }
    } catch {
      setData(MOCK_DATA);
    } finally {
      setLoading(false);
    }
  }, [period, category]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ─── 下架菜品 ───
  const handleSoldout = useCallback(async (dishId: string, dishName: string) => {
    if (soldoutIds.has(dishId)) return;

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;

      if (API_BASE) {
        const resp = await fetch(`${API_BASE}/api/v1/dishes/${dishId}`, {
          method:  'PATCH',
          headers,
          body:    JSON.stringify({ status: 'soldout' }),
        });
        const json = await resp.json() as { ok: boolean };
        if (!json.ok) {
          setToast(`下架失败：${dishName}`);
          setTimeout(() => setToast(''), 3000);
          return;
        }
      }
    } catch {
      // API 不可用时，乐观更新
    }

    setSoldoutIds(prev => new Set([...prev, dishId]));
    setToast(`已下架：${dishName}`);
    setTimeout(() => setToast(''), 3000);
  }, [soldoutIds]);

  // ─── 排序后的菜品列表 ───
  const maxSales = useMemo(
    () => Math.max(...data.dishes.map(d => d.sales_count), 1),
    [data.dishes]
  );

  const filteredDishes = useMemo(() => {
    let list = [...data.dishes];
    if (category && category !== '全部') {
      list = list.filter(d => d.category === category);
    }
    switch (sortKey) {
      case 'sales_count':  list.sort((a, b) => b.sales_count  - a.sales_count);  break;
      case 'gross_margin': list.sort((a, b) => b.gross_margin - a.gross_margin); break;
      case 'score':
        list.sort((a, b) => compositeScore(b, maxSales) - compositeScore(a, maxSales));
        break;
    }
    return list;
  }, [data.dishes, category, sortKey, maxSales]);

  const SORT_TABS: { key: SortKey; label: string }[] = [
    { key: 'sales_count',  label: '销量' },
    { key: 'gross_margin', label: '毛利率' },
    { key: 'score',        label: '综合评分' },
  ];

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#111827',
        color: '#F9FAFB',
        fontFamily: 'system-ui, sans-serif',
      }}
    >
      {/* ─── 顶部标题栏 ─── */}
      <div
        style={{
          display:         'flex',
          alignItems:      'center',
          justifyContent:  'space-between',
          padding:         '16px 16px 12px',
          borderBottom:    '1px solid #1F2937',
          position:        'sticky',
          top:             0,
          background:      '#111827',
          zIndex:          10,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>菜单工程分析</h1>
        {loading && (
          <span style={{ color: '#FF6B35', fontSize: 13 }}>加载中...</span>
        )}
      </div>

      {/* ─── 筛选栏 ─── */}
      <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {/* 时间筛选 */}
        <div style={{ display: 'flex', gap: 8 }}>
          {(Object.keys(PERIOD_LABELS) as Period[]).map(p => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                height:     48,
                padding:    '0 18px',
                borderRadius: 24,
                border:     'none',
                cursor:     'pointer',
                fontSize:   15,
                fontWeight: period === p ? 700 : 400,
                background: period === p ? '#FF6B35' : '#1F2937',
                color:      period === p ? '#fff'    : '#9CA3AF',
                flexShrink: 0,
              }}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>

        {/* 分类筛选 */}
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setCategory(cat === '全部' ? '' : cat)}
              style={{
                height:     40,
                padding:    '0 14px',
                borderRadius: 20,
                border:     'none',
                cursor:     'pointer',
                fontSize:   13,
                fontWeight: (category === cat || (cat === '全部' && !category)) ? 700 : 400,
                background: (category === cat || (cat === '全部' && !category)) ? '#374151' : '#1F2937',
                color:      (category === cat || (cat === '全部' && !category)) ? '#F9FAFB' : '#9CA3AF',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: '0 16px 16px' }}>
        {/* ─── 象限分布饼图 ─── */}
        <QuadrantChart summary={data.summary} />

        {/* ─── 四象限卡片 ─── */}
        <div
          style={{
            display:             'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap:                 12,
            marginBottom:        20,
          }}
        >
          {(['star', 'cash_cow', 'plowshare', 'dog'] as Quadrant[]).map(q => (
            <QuadrantCard
              key={q}
              quadrant={q}
              dishes={data.dishes}
              onSoldout={handleSoldout}
              soldoutIds={soldoutIds}
            />
          ))}
        </div>
      </div>

      {/* ─── 全部菜品排序列表 ─── */}
      <div>
        {/* 排序切换 + 表头 */}
        <div
          style={{
            padding:          '10px 16px',
            display:          'flex',
            alignItems:       'center',
            justifyContent:   'space-between',
            borderTop:        '1px solid #1F2937',
            borderBottom:     '1px solid #1F2937',
            position:         'sticky',
            top:              56,
            background:       '#111827',
            zIndex:           9,
          }}
        >
          <span style={{ color: '#9CA3AF', fontSize: 14 }}>
            全部菜品（{filteredDishes.length}）
          </span>
          <div style={{ display: 'flex', gap: 6 }}>
            {SORT_TABS.map(tab => (
              <button
                key={tab.key}
                onClick={() => setSortKey(tab.key)}
                style={{
                  height:       40,
                  padding:      '0 12px',
                  borderRadius: 8,
                  border:       'none',
                  cursor:       'pointer',
                  fontSize:     13,
                  fontWeight:   sortKey === tab.key ? 700 : 400,
                  background:   sortKey === tab.key ? '#FF6B35' : '#1F2937',
                  color:        sortKey === tab.key ? '#fff'    : '#9CA3AF',
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* 菜品行 */}
        {filteredDishes.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#6B7280', padding: 40, fontSize: 15 }}>
            暂无菜品数据
          </div>
        ) : (
          filteredDishes.map((dish, idx) => (
            <DishRow
              key={dish.id}
              dish={dish}
              rank={idx + 1}
              onSoldout={handleSoldout}
              isSoldout={soldoutIds.has(dish.id)}
            />
          ))
        )}
      </div>

      {/* ─── Toast 提示 ─── */}
      {toast && (
        <div
          style={{
            position:     'fixed',
            bottom:       32,
            left:         '50%',
            transform:    'translateX(-50%)',
            background:   '#1F2937',
            border:       '1px solid #374151',
            borderRadius: 10,
            padding:      '12px 20px',
            color:        '#F9FAFB',
            fontSize:     15,
            fontWeight:   600,
            zIndex:       100,
            whiteSpace:   'nowrap',
            boxShadow:    '0 4px 20px rgba(0,0,0,0.5)',
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
