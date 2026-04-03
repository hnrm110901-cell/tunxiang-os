/**
 * 多门店对比分析 — 总部端
 * 真实API接入版本
 *
 * Sections:
 *   1. 门店列表选择  → GET /api/v1/store-health/overview
 *   2. KPI对比表格   → POST /api/v1/analysis/store/comparison（并行多店）
 *   3. 营收趋势折线图 → GET /api/v1/analysis/store/{id}/revenue（并行多店，SVG手写）
 *   4. 核心指标条形对比 → 翻台率/客单价/毛利率/人效，SVG手写
 *   5. 门店健康评分排名 → GET /api/v1/store-health/overview
 *
 * 技术规范：
 *   - txFetch + Promise.allSettled 并行请求
 *   - 各Section独立错误处理，互不影响
 *   - 深色主题：bg #0d1e28，card #1a2a33
 *   - 纯手写SVG，不依赖任何图表库
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { txFetch } from '../../../api';

// ─────────────────────────────────────────────
// 类型定义
// ─────────────────────────────────────────────

type Period = 'day' | 'week' | 'month';

interface StoreOption {
  store_id: string;
  store_name: string;
  health_score: number;
  health_grade: string;
  status: string;
}

interface StoreHealthItem {
  store_id: string;
  store_name: string;
  status: string;
  health_score: number;
  health_grade: string;
  today_revenue_fen: number;
  revenue_rate: number;
  cost_rate: number;
  daily_review_completion: number;
  alerts: string[];
}

interface StoreHealthOverview {
  stores: StoreHealthItem[];
  summary: {
    total_stores: number;
    online_stores: number;
    avg_health_score: number;
    total_revenue_fen: number;
  };
  generated_at: string;
}

interface CompareRow {
  store_id: string;
  store_name: string;
  revenue_fen: number;
  avg_ticket_fen: number;
  margin_rate: number;
  turnover_rate: number;
  labor_efficiency: number; // 人效：元/人·天
  order_count: number;
}

interface RevenueTrendPoint {
  date: string;
  revenue_fen: number;
}

interface StoreRevenueSeries {
  store_id: string;
  store_name: string;
  points: RevenueTrendPoint[];
  color: string;
}

// ─────────────────────────────────────────────
// 常量
// ─────────────────────────────────────────────

const PERIOD_LABELS: Record<Period, string> = { day: '日', week: '周', month: '月' };
const PERIOD_TO_DAYS: Record<Period, number> = { day: 7, week: 28, month: 30 };

const STORE_COLORS = [
  '#FF6B2C', '#00C9A7', '#4A9EFF', '#FFB347', '#B97BFF',
  '#FF6B8A', '#36CFC9', '#FAAD14', '#73D13D', '#FF7875',
];

// 主题色
const BG_PAGE = '#0d1e28';
const BG_CARD = '#1a2a33';
const BG_CARD2 = '#112228';
const COLOR_TEXT = '#e0e8ef';
const COLOR_MUTED = '#6b8a9a';
const COLOR_BORDER = '#243542';
const COLOR_PRIMARY = '#FF6B2C';
const COLOR_SUCCESS = '#0F6E56';
const COLOR_WARNING = '#BA7517';
const COLOR_DANGER = '#A32D2D';

// ─────────────────────────────────────────────
// 工具函数
// ─────────────────────────────────────────────

const fmtYuan = (fen: number) =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

const fmtYuanFull = (fen: number) =>
  `¥${(fen / 100).toFixed(1)}`;

const marginColor = (m: number) =>
  m >= 45 ? COLOR_SUCCESS : m >= 38 ? COLOR_WARNING : COLOR_DANGER;

const healthColor = (score: number) =>
  score >= 80 ? COLOR_SUCCESS : score >= 60 ? COLOR_WARNING : COLOR_DANGER;

const gradeColor = (grade: string) => {
  if (grade === 'A') return COLOR_SUCCESS;
  if (grade === 'B') return '#4A9EFF';
  if (grade === 'C') return COLOR_WARNING;
  return COLOR_DANGER;
};

/** 取近N天日期字符串列表 */
function getDateRange(days: number): { startDate: string; endDate: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - days + 1);
  return {
    startDate: start.toISOString().slice(0, 10),
    endDate: end.toISOString().slice(0, 10),
  };
}

/** 将revenue_analysis数据规整为趋势点列表 */
function normalizeRevenueTrend(rawData: unknown): RevenueTrendPoint[] {
  if (!rawData || typeof rawData !== 'object') return [];
  const d = rawData as Record<string, unknown>;
  // 尝试常见字段名
  const items =
    (d.daily_trend as RevenueTrendPoint[] | undefined) ||
    (d.items as RevenueTrendPoint[] | undefined) ||
    (d.trend as RevenueTrendPoint[] | undefined) ||
    [];
  if (!Array.isArray(items)) return [];
  return items.map((p: unknown) => {
    const point = p as Record<string, unknown>;
    return {
      date: String(point.date || point.day || ''),
      revenue_fen: Number(point.revenue_fen || point.revenue || 0),
    };
  }).filter((p) => p.date);
}

/** 将store_comparison数据规整为CompareRow */
function normalizeCompareRow(
  storeId: string,
  storeName: string,
  rawData: unknown,
): CompareRow {
  const fallback: CompareRow = {
    store_id: storeId,
    store_name: storeName,
    revenue_fen: 0,
    avg_ticket_fen: 0,
    margin_rate: 0,
    turnover_rate: 0,
    labor_efficiency: 0,
    order_count: 0,
  };
  if (!rawData || typeof rawData !== 'object') return fallback;
  const d = rawData as Record<string, unknown>;
  // 聚合端点可能直接返回指标字段或嵌套在metrics中
  const metrics = (d.metrics as Record<string, unknown>) || d;
  return {
    store_id: storeId,
    store_name: storeName,
    revenue_fen: Number(metrics.revenue_fen || metrics.revenue || d.revenue_fen || 0),
    avg_ticket_fen: Number(metrics.avg_ticket_fen || d.avg_ticket_fen || 0),
    margin_rate: Number(metrics.margin_rate || d.margin_rate || 0),
    turnover_rate: Number(metrics.turnover_rate || d.turnover_rate || 0),
    labor_efficiency: Number(metrics.labor_efficiency || d.labor_efficiency || 0),
    order_count: Number(metrics.order_count || d.order_count || 0),
  };
}

// ─────────────────────────────────────────────
// SVG 折线图组件
// ─────────────────────────────────────────────

interface LineChartProps {
  series: StoreRevenueSeries[];
  height?: number;
}

function SvgLineChart({ series, height = 240 }: LineChartProps) {
  const W = 780;
  const H = height;
  const PAD = { top: 16, right: 20, bottom: 40, left: 64 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  // 收集所有日期（取并集）
  const allDates = useMemo(() => {
    const dateSet = new Set<string>();
    series.forEach((s) => s.points.forEach((p) => dateSet.add(p.date)));
    return Array.from(dateSet).sort();
  }, [series]);

  const allValues = useMemo(() => {
    const vals: number[] = [];
    series.forEach((s) => s.points.forEach((p) => vals.push(p.revenue_fen)));
    return vals;
  }, [series]);

  if (allDates.length === 0 || allValues.length === 0) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: COLOR_MUTED, fontSize: 13 }}>
        暂无趋势数据
      </div>
    );
  }

  const maxVal = Math.max(...allValues) * 1.1 || 1;
  const minVal = 0;

  const xScale = (i: number) => (i / Math.max(allDates.length - 1, 1)) * chartW;
  const yScale = (v: number) => chartH - ((v - minVal) / (maxVal - minVal)) * chartH;

  // Y轴刻度
  const yTicks = 4;
  const yTickValues = Array.from({ length: yTicks + 1 }, (_, i) =>
    minVal + (maxVal - minVal) * (i / yTicks),
  );

  // X轴刻度（最多显示7个）
  const xTickStep = Math.max(1, Math.ceil(allDates.length / 7));
  const xTickIndices = allDates.reduce<number[]>((acc, _, i) => {
    if (i % xTickStep === 0 || i === allDates.length - 1) acc.push(i);
    return acc;
  }, []);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: '100%', height }}
      preserveAspectRatio="xMidYMid meet"
    >
      <g transform={`translate(${PAD.left},${PAD.top})`}>
        {/* 网格线 */}
        {yTickValues.map((v, i) => (
          <line
            key={i}
            x1={0} y1={yScale(v)}
            x2={chartW} y2={yScale(v)}
            stroke={COLOR_BORDER} strokeWidth={1} strokeDasharray="4,4"
          />
        ))}

        {/* Y轴刻度文字 */}
        {yTickValues.map((v, i) => (
          <text
            key={i}
            x={-8} y={yScale(v) + 4}
            textAnchor="end"
            fontSize={11}
            fill={COLOR_MUTED}
          >
            {v >= 10000 ? `${(v / 10000).toFixed(0)}万` : v >= 100 ? `${(v / 100).toFixed(0)}` : '0'}
          </text>
        ))}

        {/* X轴刻度文字 */}
        {xTickIndices.map((i) => (
          <text
            key={i}
            x={xScale(i)} y={chartH + 20}
            textAnchor="middle"
            fontSize={10}
            fill={COLOR_MUTED}
          >
            {allDates[i]?.slice(5) /* MM-DD */}
          </text>
        ))}

        {/* 各门店折线 */}
        {series.map((s) => {
          const pts = allDates.map((d) => {
            const found = s.points.find((p) => p.date === d);
            return found ? found.revenue_fen : null;
          });

          // 拼接path，跳过null点
          let path = '';
          let prevNull = true;
          pts.forEach((v, i) => {
            if (v === null) {
              prevNull = true;
              return;
            }
            const x = xScale(i);
            const y = yScale(v);
            if (prevNull) {
              path += `M ${x} ${y} `;
              prevNull = false;
            } else {
              path += `L ${x} ${y} `;
            }
          });

          // 面积填充
          let areaPath = path;
          const lastNonNull = pts.reduce<number>((acc, v, i) => (v !== null ? i : acc), -1);
          const firstNonNull = pts.findIndex((v) => v !== null);
          if (firstNonNull >= 0 && lastNonNull >= 0) {
            areaPath += `L ${xScale(lastNonNull)} ${chartH} L ${xScale(firstNonNull)} ${chartH} Z`;
          }

          return (
            <g key={s.store_id}>
              <path d={areaPath} fill={s.color} fillOpacity={0.08} stroke="none" />
              <path d={path} stroke={s.color} strokeWidth={2} fill="none" strokeLinejoin="round" />
              {/* 数据点 */}
              {pts.map((v, i) =>
                v !== null ? (
                  <circle
                    key={i}
                    cx={xScale(i)} cy={yScale(v)}
                    r={3} fill={s.color}
                  />
                ) : null,
              )}
            </g>
          );
        })}

        {/* 坐标轴 */}
        <line x1={0} y1={0} x2={0} y2={chartH} stroke={COLOR_BORDER} strokeWidth={1} />
        <line x1={0} y1={chartH} x2={chartW} y2={chartH} stroke={COLOR_BORDER} strokeWidth={1} />
      </g>
    </svg>
  );
}

// ─────────────────────────────────────────────
// SVG 条形对比图组件
// ─────────────────────────────────────────────

interface BarMetric {
  key: string;
  label: string;
  unit: string;
  getValue: (r: CompareRow) => number;
  colorFn?: (v: number) => string;
}

const BAR_METRICS: BarMetric[] = [
  {
    key: 'turnover',
    label: '翻台率',
    unit: '次/天',
    getValue: (r) => r.turnover_rate,
  },
  {
    key: 'avg_ticket',
    label: '客单价',
    unit: '元',
    getValue: (r) => r.avg_ticket_fen / 100,
  },
  {
    key: 'margin',
    label: '毛利率',
    unit: '%',
    getValue: (r) => r.margin_rate,
    colorFn: marginColor,
  },
  {
    key: 'labor',
    label: '人效',
    unit: '元/人',
    getValue: (r) => r.labor_efficiency,
  },
];

interface GroupedBarChartProps {
  rows: CompareRow[];
  storeColorMap: Record<string, string>;
}

function SvgGroupedBar({ rows, storeColorMap }: GroupedBarChartProps) {
  if (rows.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: COLOR_MUTED, fontSize: 13 }}>
        请选择至少一个门店
      </div>
    );
  }

  const W = 760;
  const ROW_H = 88;
  const BAR_H = 14;
  const PAD_LEFT = 56;
  const PAD_RIGHT = 24;
  const LABEL_W = 72;
  const chartW = W - PAD_LEFT - PAD_RIGHT - LABEL_W;
  const totalH = BAR_METRICS.length * ROW_H + 24;

  return (
    <svg
      viewBox={`0 0 ${W} ${totalH}`}
      style={{ width: '100%', height: totalH }}
      preserveAspectRatio="xMidYMid meet"
    >
      {BAR_METRICS.map((metric, mi) => {
        const values = rows.map((r) => metric.getValue(r));
        const maxVal = Math.max(...values, 0.001);
        const yBase = mi * ROW_H + 32;
        const barSpacing = rows.length > 1 ? (BAR_H + 4) : 0;

        return (
          <g key={metric.key}>
            {/* 指标标题 */}
            <text
              x={PAD_LEFT}
              y={yBase - 14}
              fontSize={11}
              fill={COLOR_MUTED}
              fontWeight={600}
            >
              {metric.label}（{metric.unit}）
            </text>

            {rows.map((row, ri) => {
              const val = metric.getValue(row);
              const barLen = (val / maxVal) * chartW;
              const color = metric.colorFn ? metric.colorFn(val) : (storeColorMap[row.store_id] || COLOR_PRIMARY);
              const y = yBase + ri * (BAR_H + 4);

              return (
                <g key={row.store_id}>
                  {/* 背景轨道 */}
                  <rect
                    x={PAD_LEFT + LABEL_W}
                    y={y}
                    width={chartW}
                    height={BAR_H}
                    rx={4}
                    fill={COLOR_BORDER}
                  />
                  {/* 数据条 */}
                  <rect
                    x={PAD_LEFT + LABEL_W}
                    y={y}
                    width={Math.max(barLen, 0)}
                    height={BAR_H}
                    rx={4}
                    fill={color}
                    fillOpacity={0.85}
                  />
                  {/* 门店名 */}
                  <text
                    x={PAD_LEFT + LABEL_W - 6}
                    y={y + BAR_H - 3}
                    textAnchor="end"
                    fontSize={10}
                    fill={storeColorMap[row.store_id] || COLOR_TEXT}
                  >
                    {row.store_name.length > 4 ? row.store_name.slice(0, 4) + '…' : row.store_name}
                  </text>
                  {/* 数值 */}
                  <text
                    x={PAD_LEFT + LABEL_W + barLen + 6}
                    y={y + BAR_H - 3}
                    fontSize={10}
                    fill={color}
                    fontWeight={600}
                  >
                    {metric.key === 'avg_ticket' || metric.key === 'labor'
                      ? `¥${val.toFixed(0)}`
                      : metric.key === 'margin'
                      ? `${val.toFixed(1)}%`
                      : val.toFixed(2)}
                  </text>
                </g>
              );
            })}

            {/* 分割线 */}
            {mi < BAR_METRICS.length - 1 && (
              <line
                x1={PAD_LEFT}
                y1={yBase + rows.length * (BAR_H + 4) + 8}
                x2={W - PAD_RIGHT}
                y2={yBase + rows.length * (BAR_H + 4) + 8}
                stroke={COLOR_BORDER}
                strokeWidth={1}
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ─────────────────────────────────────────────
// 子组件：Section 容器
// ─────────────────────────────────────────────

interface SectionCardProps {
  title: string;
  loading?: boolean;
  error?: string | null;
  children: React.ReactNode;
  action?: React.ReactNode;
}

function SectionCard({ title, loading, error, children, action }: SectionCardProps) {
  return (
    <div style={{
      background: BG_CARD,
      borderRadius: 8,
      padding: '16px 20px',
      border: `1px solid ${COLOR_BORDER}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: COLOR_TEXT }}>{title}</span>
        {action}
      </div>
      {loading ? (
        <div style={{ padding: 32, textAlign: 'center', color: COLOR_MUTED, fontSize: 13 }}>
          <span style={{ opacity: 0.7 }}>加载中…</span>
        </div>
      ) : error ? (
        <div style={{
          padding: '10px 14px',
          background: `${COLOR_DANGER}18`,
          borderRadius: 6,
          fontSize: 12,
          color: '#e88',
          border: `1px solid ${COLOR_DANGER}40`,
        }}>
          {error}
        </div>
      ) : children}
    </div>
  );
}

// ─────────────────────────────────────────────
// 主组件
// ─────────────────────────────────────────────

export function MultiStoreComparePage() {
  // ── 状态 ──
  const [period, setPeriod] = useState<Period>('day');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);

  // 门店列表（来自健康概览）
  const [storeList, setStoreList] = useState<StoreOption[]>([]);
  const [storeListLoading, setStoreListLoading] = useState(true);
  const [storeListError, setStoreListError] = useState<string | null>(null);

  // KPI 对比表格
  const [compareRows, setCompareRows] = useState<CompareRow[]>([]);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  // 营收趋势
  const [trendSeries, setTrendSeries] = useState<StoreRevenueSeries[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);
  const [trendError, setTrendError] = useState<string | null>(null);

  // 门店健康评分排名
  const [healthList, setHealthList] = useState<StoreHealthItem[]>([]);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);

  // 用于防止过期响应覆盖最新状态
  const fetchGenRef = useRef(0);

  // ── 颜色映射（storeId → color） ──
  const storeColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    storeList.forEach((s, i) => {
      map[s.store_id] = STORE_COLORS[i % STORE_COLORS.length];
    });
    return map;
  }, [storeList]);

  // ── Section 1：加载门店列表 & 健康评分 ──
  useEffect(() => {
    setStoreListLoading(true);
    setHealthLoading(true);

    txFetch<StoreHealthOverview>('/api/v1/store-health/overview')
      .then((data) => {
        const stores = data.stores.map((s) => ({
          store_id: s.store_id,
          store_name: s.store_name,
          health_score: s.health_score,
          health_grade: s.health_grade,
          status: s.status,
        }));
        setStoreList(stores);
        // 默认选前3个门店
        if (stores.length > 0) {
          setSelectedIds(new Set(stores.slice(0, Math.min(3, stores.length)).map((s) => s.store_id)));
        }
        setHealthList(data.stores);
        setStoreListError(null);
        setHealthError(null);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '加载门店列表失败';
        setStoreListError(msg);
        setHealthError(msg);
      })
      .finally(() => {
        setStoreListLoading(false);
        setHealthLoading(false);
      });
  }, []);

  // ── Section 2 & 3 & 4：选中门店变化时并行拉取数据 ──
  useEffect(() => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) {
      setCompareRows([]);
      setTrendSeries([]);
      return;
    }

    const gen = ++fetchGenRef.current;
    const { startDate, endDate } = getDateRange(PERIOD_TO_DAYS[period]);

    setCompareLoading(true);
    setTrendLoading(true);
    setCompareError(null);
    setTrendError(null);

    // 构建每门店的请求
    const compareRequests = ids.map((storeId) => {
      // 优先用 /analysis/store/comparison POST 端点，传单个门店也能拿到汇总
      const body = {
        store_ids: [storeId],
        metrics: ['revenue', 'orders', 'avg_ticket', 'turnover'],
        start_date: startDate,
        end_date: endDate,
      };
      return txFetch<unknown>('/api/v1/analysis/store/comparison', {
        method: 'POST',
        body: JSON.stringify(body),
      });
    });

    const trendRequests = ids.map((storeId) =>
      txFetch<unknown>(
        `/api/v1/analysis/store/${encodeURIComponent(storeId)}/revenue?start_date=${startDate}&end_date=${endDate}`,
      ),
    );

    // 并行请求，各自独立处理失败
    Promise.allSettled([
      Promise.allSettled(compareRequests),
      Promise.allSettled(trendRequests),
    ]).then(([compareSettled, trendSettled]) => {
      if (gen !== fetchGenRef.current) return; // 已过期

      // 处理 KPI 对比
      if (compareSettled.status === 'fulfilled') {
        const results = compareSettled.value;
        const rows: CompareRow[] = [];
        let anyError = false;
        results.forEach((r, i) => {
          const storeId = ids[i];
          const storeName = storeList.find((s) => s.store_id === storeId)?.store_name || storeId;
          if (r.status === 'fulfilled') {
            rows.push(normalizeCompareRow(storeId, storeName, r.value));
          } else {
            anyError = true;
            rows.push({
              store_id: storeId,
              store_name: storeName,
              revenue_fen: 0, avg_ticket_fen: 0,
              margin_rate: 0, turnover_rate: 0,
              labor_efficiency: 0, order_count: 0,
            });
          }
        });
        setCompareRows(rows);
        setCompareError(anyError ? '部分门店数据加载失败，以 0 显示' : null);
      }
      setCompareLoading(false);

      // 处理营收趋势
      if (trendSettled.status === 'fulfilled') {
        const results = trendSettled.value;
        const series: StoreRevenueSeries[] = [];
        let anyError = false;
        results.forEach((r, i) => {
          const storeId = ids[i];
          const storeOpt = storeList.find((s) => s.store_id === storeId);
          const color = storeColorMap[storeId] || STORE_COLORS[i % STORE_COLORS.length];
          if (r.status === 'fulfilled') {
            series.push({
              store_id: storeId,
              store_name: storeOpt?.store_name || storeId,
              points: normalizeRevenueTrend(r.value),
              color,
            });
          } else {
            anyError = true;
            series.push({
              store_id: storeId,
              store_name: storeOpt?.store_name || storeId,
              points: [],
              color,
            });
          }
        });
        setTrendSeries(series);
        setTrendError(anyError ? '部分门店趋势数据加载失败' : null);
      }
      setTrendLoading(false);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds, period]);

  // ── 门店选择操作 ──
  const toggleStore = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(storeList.map((s) => s.store_id)));
  }, [storeList]);

  const clearAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  // ── 导出 Excel ──
  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const resp = await fetch('/api/v1/report/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          report_type: 'multi_store_compare',
          store_ids: Array.from(selectedIds),
          period,
          start_date: getDateRange(PERIOD_TO_DAYS[period]).startDate,
          end_date: getDateRange(PERIOD_TO_DAYS[period]).endDate,
        }),
      });
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `门店对比_${period}_${new Date().toISOString().slice(0, 10)}.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      // 静默处理导出失败
    } finally {
      setExporting(false);
    }
  }, [selectedIds, period]);

  // ── 参与对比的门店行（已选） ──
  const selectedCompareRows = useMemo(
    () => compareRows.filter((r) => selectedIds.has(r.store_id)),
    [compareRows, selectedIds],
  );

  // ── 健康评分排名（按score降序） ──
  const sortedHealthList = useMemo(
    () => [...healthList].sort((a, b) => b.health_score - a.health_score),
    [healthList],
  );

  // ─────────────────────────────────────────────
  // 渲染
  // ─────────────────────────────────────────────
  return (
    <div style={{ background: BG_PAGE, minHeight: '100vh', padding: '20px 24px', color: COLOR_TEXT, fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' }}>

      {/* ── 顶部标题行 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: COLOR_TEXT }}>多门店对比分析</h2>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: COLOR_MUTED }}>
            数据来源：实时门店经营数据 · 自动刷新
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* 周期切换 */}
          {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                padding: '5px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 600,
                background: period === p ? COLOR_PRIMARY : BG_CARD,
                color: period === p ? '#fff' : COLOR_MUTED,
                transition: 'all 0.15s',
              }}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
          <span style={{ width: 1, height: 20, background: COLOR_BORDER }} />
          <button
            onClick={handleExport}
            disabled={exporting || selectedIds.size === 0}
            style={{
              padding: '5px 16px', borderRadius: 6, border: `1px solid ${COLOR_PRIMARY}`,
              cursor: 'pointer', fontSize: 12, fontWeight: 600,
              background: 'transparent', color: COLOR_PRIMARY,
              opacity: (exporting || selectedIds.size === 0) ? 0.4 : 1,
            }}
          >
            {exporting ? '导出中…' : '导出 Excel'}
          </button>
        </div>
      </div>

      {/* ── 主体两列布局 ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16, alignItems: 'start' }}>

        {/* ── 左侧：门店多选面板 ── */}
        <div style={{ background: BG_CARD, borderRadius: 8, border: `1px solid ${COLOR_BORDER}`, overflow: 'hidden' }}>
          <div style={{
            padding: '12px 16px',
            borderBottom: `1px solid ${COLOR_BORDER}`,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>
              选择门店
              {!storeListLoading && (
                <span style={{ color: COLOR_MUTED, fontWeight: 400, marginLeft: 6, fontSize: 11 }}>
                  已选 {selectedIds.size}/{storeList.length}
                </span>
              )}
            </span>
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={selectAll}
                disabled={storeListLoading}
                style={{ background: 'none', border: 'none', color: COLOR_PRIMARY, cursor: 'pointer', fontSize: 11, padding: 0 }}
              >
                全选
              </button>
              <button
                onClick={clearAll}
                style={{ background: 'none', border: 'none', color: COLOR_MUTED, cursor: 'pointer', fontSize: 11, padding: 0 }}
              >
                清空
              </button>
            </div>
          </div>

          {storeListLoading ? (
            <div style={{ padding: 24, textAlign: 'center', color: COLOR_MUTED, fontSize: 12 }}>加载门店列表…</div>
          ) : storeListError ? (
            <div style={{ padding: 12, color: '#e88', fontSize: 12 }}>{storeListError}</div>
          ) : (
            <div style={{ maxHeight: 480, overflowY: 'auto', padding: '8px 0' }}>
              {storeList.map((s) => {
                const isSelected = selectedIds.has(s.store_id);
                const dotColor = s.status === 'online' ? COLOR_SUCCESS : COLOR_MUTED;
                return (
                  <label
                    key={s.store_id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '7px 16px', cursor: 'pointer',
                      background: isSelected ? `${COLOR_PRIMARY}12` : 'transparent',
                      borderLeft: `3px solid ${isSelected ? COLOR_PRIMARY : 'transparent'}`,
                      transition: 'background 0.12s',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleStore(s.store_id)}
                      style={{ accentColor: COLOR_PRIMARY, flexShrink: 0 }}
                    />
                    {/* 状态点 */}
                    <span style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: dotColor, flexShrink: 0,
                    }} />
                    <span style={{ fontSize: 13, color: isSelected ? COLOR_TEXT : COLOR_MUTED, flex: 1 }}>
                      {s.store_name}
                    </span>
                    {/* 健康评分 */}
                    <span style={{
                      fontSize: 11, fontWeight: 700,
                      color: gradeColor(s.health_grade),
                      background: `${gradeColor(s.health_grade)}18`,
                      padding: '1px 6px', borderRadius: 10,
                    }}>
                      {s.health_grade}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        {/* ── 右侧：各分析区块 ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* ── Section 2：KPI 对比表格 ── */}
          <SectionCard
            title="核心KPI对比"
            loading={compareLoading}
            error={compareError}
          >
            {selectedIds.size === 0 ? (
              <div style={{ padding: '24px 0', textAlign: 'center', color: COLOR_MUTED, fontSize: 13 }}>
                请在左侧选择至少一个门店
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ color: COLOR_MUTED, fontSize: 11 }}>
                      {['门店', '营收', '客单价', '订单量', '毛利率', '翻台率', '人效'].map((h) => (
                        <th key={h} style={{ padding: '6px 8px', textAlign: h === '门店' ? 'left' : 'right', fontWeight: 500, whiteSpace: 'nowrap' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {selectedCompareRows.map((r) => {
                      const dotColor = storeColorMap[r.store_id] || COLOR_TEXT;
                      return (
                        <tr key={r.store_id} style={{ borderTop: `1px solid ${COLOR_BORDER}` }}>
                          <td style={{ padding: '10px 8px', fontWeight: 600, whiteSpace: 'nowrap' }}>
                            <span style={{
                              display: 'inline-block', width: 8, height: 8,
                              borderRadius: '50%', background: dotColor,
                              marginRight: 6, verticalAlign: 'middle',
                            }} />
                            {r.store_name}
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                            {fmtYuan(r.revenue_fen)}
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                            {fmtYuanFull(r.avg_ticket_fen)}
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'right' }}>
                            {r.order_count.toLocaleString()}
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'right' }}>
                            <span style={{
                              padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                              background: `${marginColor(r.margin_rate)}20`,
                              color: marginColor(r.margin_rate),
                            }}>
                              {r.margin_rate > 0 ? `${r.margin_rate.toFixed(1)}%` : '—'}
                            </span>
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'right' }}>
                            {r.turnover_rate > 0 ? r.turnover_rate.toFixed(2) : '—'}
                          </td>
                          <td style={{ padding: '10px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                            {r.labor_efficiency > 0 ? `¥${r.labor_efficiency.toFixed(0)}` : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>

          {/* ── Section 3：营收趋势折线图 ── */}
          <SectionCard
            title={`营收趋势对比（近${PERIOD_TO_DAYS[period]}天）`}
            loading={trendLoading}
            error={trendError}
            action={
              trendSeries.length > 0 ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                  {trendSeries.map((s) => (
                    <span key={s.store_id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: COLOR_MUTED }}>
                      <span style={{ width: 16, height: 2, background: s.color, display: 'inline-block', borderRadius: 1 }} />
                      {s.store_name}
                    </span>
                  ))}
                </div>
              ) : undefined
            }
          >
            {selectedIds.size === 0 ? (
              <div style={{ padding: '24px 0', textAlign: 'center', color: COLOR_MUTED, fontSize: 13 }}>
                请先选择门店
              </div>
            ) : (
              <SvgLineChart series={trendSeries} height={240} />
            )}
          </SectionCard>

          {/* ── Section 4：核心指标条形对比 ── */}
          <SectionCard
            title="核心指标对比（翻台率 / 客单价 / 毛利率 / 人效）"
            loading={compareLoading}
          >
            <SvgGroupedBar rows={selectedCompareRows} storeColorMap={storeColorMap} />
          </SectionCard>
        </div>
      </div>

      {/* ── Section 5：门店健康评分排名（全宽） ── */}
      <div style={{ marginTop: 16 }}>
        <SectionCard
          title="门店健康评分排名"
          loading={healthLoading}
          error={healthError}
          action={
            <span style={{ fontSize: 11, color: COLOR_MUTED }}>
              综合评分 = 营收达成40% + 成本控制30% + 日清完成30%
            </span>
          }
        >
          {sortedHealthList.length === 0 && !healthLoading ? (
            <div style={{ padding: '16px 0', textAlign: 'center', color: COLOR_MUTED, fontSize: 13 }}>暂无数据</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
              {sortedHealthList.map((item, idx) => {
                const barW = `${Math.max(item.health_score, 0)}%`;
                const isSelected = selectedIds.has(item.store_id);
                return (
                  <div
                    key={item.store_id}
                    style={{
                      background: isSelected ? `${COLOR_PRIMARY}10` : BG_CARD2,
                      borderRadius: 6,
                      padding: '10px 12px',
                      border: `1px solid ${isSelected ? `${COLOR_PRIMARY}40` : COLOR_BORDER}`,
                      cursor: 'pointer',
                    }}
                    onClick={() => toggleStore(item.store_id)}
                  >
                    {/* 排名 + 门店名 + 等级 */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                      <span style={{
                        width: 20, height: 20, borderRadius: '50%',
                        background: idx < 3 ? COLOR_PRIMARY : COLOR_BORDER,
                        color: idx < 3 ? '#fff' : COLOR_MUTED,
                        fontSize: 10, fontWeight: 700,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                      }}>
                        {idx + 1}
                      </span>
                      <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: COLOR_TEXT, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.store_name}
                      </span>
                      <span style={{
                        fontSize: 12, fontWeight: 700,
                        color: gradeColor(item.health_grade),
                        background: `${gradeColor(item.health_grade)}20`,
                        padding: '1px 7px', borderRadius: 10,
                      }}>
                        {item.health_grade}
                      </span>
                    </div>

                    {/* 评分进度条 */}
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                        <span style={{ fontSize: 10, color: COLOR_MUTED }}>健康分</span>
                        <span style={{ fontSize: 12, fontWeight: 700, color: healthColor(item.health_score) }}>
                          {item.health_score < 0 ? '—' : item.health_score}
                        </span>
                      </div>
                      <div style={{ height: 4, borderRadius: 2, background: COLOR_BORDER, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%',
                          width: item.health_score >= 0 ? barW : '0%',
                          background: healthColor(item.health_score),
                          borderRadius: 2,
                          transition: 'width 0.4s ease',
                        }} />
                      </div>
                    </div>

                    {/* 营收 + 告警数 */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ color: COLOR_MUTED }}>
                        今日 {fmtYuan(item.today_revenue_fen)}
                      </span>
                      {item.alerts.length > 0 && (
                        <span style={{
                          color: COLOR_DANGER,
                          background: `${COLOR_DANGER}18`,
                          padding: '0 6px', borderRadius: 8,
                        }}>
                          {item.alerts.length} 项预警
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
