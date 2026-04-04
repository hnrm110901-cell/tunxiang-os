/**
 * StoreComparisonPage — 多门店对比分析页
 *
 * 终端：Admin（总部管理后台）
 * 域G：经营分析
 *
 * 功能：
 *   1. 顶部筛选栏：时间范围 + 门店多选(最多5家) + 指标选择
 *   2. 对比图表区：SVG 分组柱状图
 *   3. 趋势对比区：SVG 多折线图 + tooltip
 *   4. 排名表格：ProTable
 *   5. 洞察卡片：最佳门店 / 需关注 / 异常
 *
 * 技术：React + Ant Design 5.x + ProTable，纯 SVG 图表
 * API：tx-analytics :8009，try/catch 降级 Mock
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ConfigProvider, Select, DatePicker, Card, Space, Tag, Row, Col } from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';
import { apiGet } from '../../api/client';

const { RangePicker } = DatePicker;

// ─── 常量 ──────────────────────────────────────────────────────────────────────

// BASE URL 通过 apiGet 注入，不再硬编码

const STORE_COLORS = ['#FF6B35', '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6'] as const;

type MetricKey = 'revenue' | 'orders' | 'avg_spend' | 'turnover_rate' | 'gross_margin';

const METRIC_OPTIONS: { value: MetricKey; label: string; unit: string }[] = [
  { value: 'revenue', label: '营收', unit: '元' },
  { value: 'orders', label: '订单数', unit: '单' },
  { value: 'avg_spend', label: '客单价', unit: '元' },
  { value: 'turnover_rate', label: '翻台率', unit: '%' },
  { value: 'gross_margin', label: '毛利率', unit: '%' },
];

const QUICK_RANGES: { label: string; range: [Dayjs, Dayjs] }[] = [
  { label: '今日', range: [dayjs().startOf('day'), dayjs().endOf('day')] },
  { label: '本周', range: [dayjs().startOf('week'), dayjs().endOf('day')] },
  { label: '本月', range: [dayjs().startOf('month'), dayjs().endOf('day')] },
];

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface StoreOption {
  store_id: string;
  store_name: string;
}

interface ComparisonItem {
  store_id: string;
  store_name: string;
  value: number;
}

interface TrendPoint {
  date: string;
  value: number;
}

interface StoreTrend {
  store_id: string;
  store_name: string;
  points: TrendPoint[];
}

interface RankRow {
  rank: number;
  store_id: string;
  store_name: string;
  revenue: number;
  orders: number;
  avg_spend: number;
  turnover_rate: number;
  gross_margin: number;
  mom_change: number; // 环比 %
}

interface InsightCard {
  type: 'best' | 'attention' | 'anomaly';
  title: string;
  description: string;
}

// ─── 门店列表 fallback（API 失败时使用空列表，不硬编码） ──────────────────────

/** 以下 generate* 函数仅作 API 失败时的降级 fallback，不作主数据源 */
function generateFallbackComparison(storeIds: string[], metric: MetricKey, storeList: StoreOption[]): ComparisonItem[] {
  const ranges: Record<MetricKey, [number, number]> = {
    revenue: [180000, 420000],
    orders: [800, 2500],
    avg_spend: [68, 128],
    turnover_rate: [2.1, 4.8],
    gross_margin: [52, 72],
  };
  const [min, max] = ranges[metric];
  return storeIds.map((id) => {
    const store = storeList.find((s) => s.store_id === id);
    return {
      store_id: id,
      store_name: store?.store_name ?? id,
      value: Math.round((min + Math.random() * (max - min)) * 100) / 100,
    };
  });
}

function generateFallbackTrend(storeIds: string[], metric: MetricKey, days: number, storeList: StoreOption[]): StoreTrend[] {
  const ranges: Record<MetricKey, [number, number]> = {
    revenue: [5000, 18000],
    orders: [30, 120],
    avg_spend: [60, 130],
    turnover_rate: [1.8, 5.2],
    gross_margin: [48, 75],
  };
  const [min, max] = ranges[metric];
  return storeIds.map((id) => {
    const store = storeList.find((s) => s.store_id === id);
    const base = min + Math.random() * (max - min) * 0.6;
    const points: TrendPoint[] = [];
    for (let i = 0; i < days; i++) {
      points.push({
        date: dayjs().subtract(days - 1 - i, 'day').format('MM-DD'),
        value: Math.round((base + Math.random() * (max - min) * 0.4) * 100) / 100,
      });
    }
    return { store_id: id, store_name: store?.store_name ?? id, points };
  });
}

function generateFallbackRanking(storeIds: string[], storeList: StoreOption[]): RankRow[] {
  return storeIds
    .map((id) => {
      const store = storeList.find((s) => s.store_id === id);
      return {
        rank: 0,
        store_id: id,
        store_name: store?.store_name ?? id,
        revenue: Math.round(180000 + Math.random() * 240000),
        orders: Math.round(800 + Math.random() * 1700),
        avg_spend: Math.round((68 + Math.random() * 60) * 100) / 100,
        turnover_rate: Math.round((2.1 + Math.random() * 2.7) * 10) / 10,
        gross_margin: Math.round((52 + Math.random() * 20) * 10) / 10,
        mom_change: Math.round((-15 + Math.random() * 30) * 10) / 10,
      };
    })
    .sort((a, b) => b.revenue - a.revenue)
    .map((row, i) => ({ ...row, rank: i + 1 }));
}

function generateMockInsights(ranking: RankRow[]): InsightCard[] {
  if (ranking.length === 0) return [];
  const best = ranking[0];
  const worst = ranking[ranking.length - 1];
  const avgSpend = ranking.reduce((s, r) => s + r.avg_spend, 0) / ranking.length;
  const anomaly = ranking.find((r) => r.avg_spend < avgSpend * 0.7);

  const cards: InsightCard[] = [
    {
      type: 'best',
      title: '最佳门店',
      description: `${best.store_name} 本月营收最高 ${(best.revenue / 10000).toFixed(1)}万，环比 ${best.mom_change >= 0 ? '+' : ''}${best.mom_change}%`,
    },
    {
      type: 'attention',
      title: '需关注',
      description: `${worst.store_name} 翻台率 ${worst.turnover_rate}，在所选门店中排名末位，建议关注`,
    },
  ];

  if (anomaly) {
    cards.push({
      type: 'anomaly',
      title: '异常',
      description: `${anomaly.store_name} 客单价 ${anomaly.avg_spend}元，低于平均值 ${avgSpend.toFixed(0)}元 的70%`,
    });
  }

  return cards;
}

// ─── SVG 分组柱状图 ───────────────────────────────────────────────────────────

interface BarChartProps {
  data: ComparisonItem[];
  metric: MetricKey;
  unit: string;
}

function GroupBarChart({ data, metric, unit }: BarChartProps) {
  const width = 700;
  const height = 360;
  const padLeft = 70;
  const padRight = 30;
  const padTop = 30;
  const padBottom = 60;

  if (data.length === 0) {
    return (
      <svg width={width} height={height}>
        <text x={width / 2} y={height / 2} textAnchor="middle" fill="#999" fontSize={14}>
          请选择门店
        </text>
      </svg>
    );
  }

  const maxVal = Math.max(...data.map((d) => d.value), 1);
  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;
  const barW = Math.min(50, chartW / data.length * 0.6);
  const gap = (chartW - barW * data.length) / (data.length + 1);

  // Y-axis ticks
  const tickCount = 5;
  const yTicks = Array.from({ length: tickCount + 1 }, (_, i) =>
    Math.round((maxVal / tickCount) * i * 100) / 100
  );

  return (
    <svg width={width} height={height} style={{ display: 'block', margin: '0 auto' }}>
      {/* Y axis grid lines */}
      {yTicks.map((tick, i) => {
        const y = padTop + chartH - (tick / maxVal) * chartH;
        return (
          <g key={`ytick-${i}`}>
            <line x1={padLeft} y1={y} x2={width - padRight} y2={y} stroke="#e8e8e8" strokeDasharray="3,3" />
            <text x={padLeft - 8} y={y + 4} textAnchor="end" fill="#999" fontSize={11}>
              {metric === 'revenue' ? `${(tick / 10000).toFixed(1)}万` : tick.toFixed(1)}
            </text>
          </g>
        );
      })}

      {/* Bars */}
      {data.map((item, i) => {
        const x = padLeft + gap * (i + 1) + barW * i;
        const barH = (item.value / maxVal) * chartH;
        const y = padTop + chartH - barH;
        const color = STORE_COLORS[i % STORE_COLORS.length];
        return (
          <g key={item.store_id}>
            <rect x={x} y={y} width={barW} height={barH} fill={color} rx={3} />
            <text x={x + barW / 2} y={y - 6} textAnchor="middle" fill={color} fontSize={11} fontWeight={600}>
              {metric === 'revenue' ? `${(item.value / 10000).toFixed(1)}万` : item.value.toFixed(1)}{unit === '元' ? '' : unit}
            </text>
            <text
              x={x + barW / 2}
              y={padTop + chartH + 16}
              textAnchor="middle"
              fill="#666"
              fontSize={11}
              transform={`rotate(-15, ${x + barW / 2}, ${padTop + chartH + 16})`}
            >
              {item.store_name.length > 6 ? item.store_name.slice(0, 6) + '..' : item.store_name}
            </text>
          </g>
        );
      })}

      {/* Y axis label */}
      <text x={12} y={padTop + chartH / 2} textAnchor="middle" fill="#999" fontSize={11} transform={`rotate(-90, 12, ${padTop + chartH / 2})`}>
        {METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? ''} ({unit})
      </text>

      {/* Legend */}
      {data.map((item, i) => (
        <g key={`legend-${i}`} transform={`translate(${width - padRight - 120}, ${padTop + i * 18})`}>
          <rect width={10} height={10} fill={STORE_COLORS[i % STORE_COLORS.length]} rx={2} />
          <text x={14} y={9} fill="#666" fontSize={11}>
            {item.store_name.length > 8 ? item.store_name.slice(0, 8) + '..' : item.store_name}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ─── SVG 多折线趋势图 ─────────────────────────────────────────────────────────

interface TrendChartProps {
  trends: StoreTrend[];
  metric: MetricKey;
  unit: string;
}

function TrendLineChart({ trends, metric, unit }: TrendChartProps) {
  const width = 700;
  const height = 360;
  const padLeft = 70;
  const padRight = 30;
  const padTop = 30;
  const padBottom = 50;

  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    storeName: string;
    date: string;
    value: number;
  } | null>(null);

  if (trends.length === 0 || trends[0].points.length === 0) {
    return (
      <svg width={width} height={height}>
        <text x={width / 2} y={height / 2} textAnchor="middle" fill="#999" fontSize={14}>
          请选择门店
        </text>
      </svg>
    );
  }

  const allValues = trends.flatMap((t) => t.points.map((p) => p.value));
  const maxVal = Math.max(...allValues, 1);
  const minVal = Math.min(...allValues, 0);
  const range = maxVal - minVal || 1;

  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;
  const dates = trends[0].points.map((p) => p.date);
  const stepX = chartW / Math.max(dates.length - 1, 1);

  const toX = (i: number) => padLeft + i * stepX;
  const toY = (v: number) => padTop + chartH - ((v - minVal) / range) * chartH;

  // Y ticks
  const tickCount = 5;
  const yTicks = Array.from({ length: tickCount + 1 }, (_, i) =>
    Math.round((minVal + (range / tickCount) * i) * 100) / 100
  );

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <svg width={width} height={height} style={{ display: 'block', margin: '0 auto' }}>
        {/* Y grid */}
        {yTicks.map((tick, i) => {
          const y = toY(tick);
          return (
            <g key={`ytick-${i}`}>
              <line x1={padLeft} y1={y} x2={width - padRight} y2={y} stroke="#e8e8e8" strokeDasharray="3,3" />
              <text x={padLeft - 8} y={y + 4} textAnchor="end" fill="#999" fontSize={11}>
                {metric === 'revenue' ? `${(tick / 10000).toFixed(1)}万` : tick.toFixed(1)}
              </text>
            </g>
          );
        })}

        {/* X axis labels */}
        {dates.map((d, i) => {
          // Only show every Nth label if too many
          const showEvery = dates.length > 15 ? 3 : dates.length > 7 ? 2 : 1;
          if (i % showEvery !== 0 && i !== dates.length - 1) return null;
          return (
            <text key={`x-${i}`} x={toX(i)} y={height - 8} textAnchor="middle" fill="#999" fontSize={10}>
              {d}
            </text>
          );
        })}

        {/* Lines + hover circles */}
        {trends.map((trend, tIdx) => {
          const color = STORE_COLORS[tIdx % STORE_COLORS.length];
          const pathD = trend.points
            .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(i)} ${toY(p.value)}`)
            .join(' ');
          return (
            <g key={trend.store_id}>
              <path d={pathD} fill="none" stroke={color} strokeWidth={2} />
              {trend.points.map((p, i) => (
                <circle
                  key={`dot-${i}`}
                  cx={toX(i)}
                  cy={toY(p.value)}
                  r={4}
                  fill={color}
                  stroke="#fff"
                  strokeWidth={1.5}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={() =>
                    setTooltip({ x: toX(i), y: toY(p.value), storeName: trend.store_name, date: p.date, value: p.value })
                  }
                  onMouseLeave={() => setTooltip(null)}
                />
              ))}
            </g>
          );
        })}

        {/* Legend */}
        {trends.map((trend, i) => (
          <g key={`legend-${i}`} transform={`translate(${width - padRight - 120}, ${padTop + i * 18})`}>
            <rect width={10} height={10} fill={STORE_COLORS[i % STORE_COLORS.length]} rx={2} />
            <text x={14} y={9} fill="#666" fontSize={11}>
              {trend.store_name.length > 8 ? trend.store_name.slice(0, 8) + '..' : trend.store_name}
            </text>
          </g>
        ))}

        {/* Y axis label */}
        <text x={12} y={padTop + chartH / 2} textAnchor="middle" fill="#999" fontSize={11} transform={`rotate(-90, 12, ${padTop + chartH / 2})`}>
          {METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? ''} ({unit})
        </text>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          style={{
            position: 'absolute',
            left: tooltip.x + 12,
            top: tooltip.y - 40,
            background: 'rgba(0,0,0,0.82)',
            color: '#fff',
            padding: '6px 12px',
            borderRadius: 6,
            fontSize: 12,
            lineHeight: '18px',
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
            zIndex: 10,
          }}
        >
          <div style={{ fontWeight: 600 }}>{tooltip.storeName}</div>
          <div>
            {tooltip.date}：{metric === 'revenue' ? `${(tooltip.value / 10000).toFixed(2)}万` : tooltip.value.toFixed(1)}
            {unit === '元' ? '元' : unit}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 洞察卡片组件 ─────────────────────────────────────────────────────────────

function InsightCards({ cards }: { cards: InsightCard[] }) {
  const styleMap: Record<InsightCard['type'], { bg: string; border: string; icon: string }> = {
    best: { bg: '#FFFBE6', border: '#FFD700', icon: '🏆' },
    attention: { bg: '#FFF7E6', border: '#F59E0B', icon: '⚠️' },
    anomaly: { bg: '#FFF1F0', border: '#FF4D4F', icon: '🔴' },
  };

  if (cards.length === 0) return null;

  return (
    <Row gutter={16}>
      {cards.map((card, i) => {
        const s = styleMap[card.type];
        return (
          <Col key={i} span={8}>
            <div
              style={{
                background: s.bg,
                border: `1px solid ${s.border}`,
                borderRadius: 8,
                padding: '16px 20px',
                minHeight: 90,
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 6 }}>
                {s.icon} {card.title}
              </div>
              <div style={{ color: '#333', fontSize: 13, lineHeight: '20px' }}>
                {card.description}
              </div>
            </div>
          </Col>
        );
      })}
    </Row>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function StoreComparisonPage() {
  // 筛选状态
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().startOf('month'),
    dayjs().endOf('day'),
  ]);
  const [selectedStoreIds, setSelectedStoreIds] = useState<string[]>([]);
  const [metric, setMetric] = useState<MetricKey>('revenue');

  // 数据状态
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [comparison, setComparison] = useState<ComparisonItem[]>([]);
  const [trends, setTrends] = useState<StoreTrend[]>([]);
  const [ranking, setRanking] = useState<RankRow[]>([]);
  const [insights, setInsights] = useState<InsightCard[]>([]);
  const [loading, setLoading] = useState(false);

  const metricUnit = METRIC_OPTIONS.find((m) => m.value === metric)?.unit ?? '';

  // 加载门店列表（首次挂载时）
  useEffect(() => {
    apiGet<StoreOption[]>('/api/v1/org/stores?status=active')
      .then((data) => {
        setStores(data);
        // 默认选前三家
        if (selectedStoreIds.length === 0 && data.length > 0) {
          setSelectedStoreIds(data.slice(0, 3).map((s) => s.store_id));
        }
      })
      .catch(() => {
        // API 失败时保持空列表，用户手动输入
        setStores([]);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 加载对比数据
  const fetchData = useCallback(async () => {
    if (selectedStoreIds.length === 0) {
      setComparison([]);
      setTrends([]);
      setRanking([]);
      setInsights([]);
      return;
    }

    setLoading(true);
    const idsParam = selectedStoreIds.join(',');
    const start = dateRange[0].format('YYYY-MM-DD');
    const end = dateRange[1].format('YYYY-MM-DD');
    const days = dateRange[1].diff(dateRange[0], 'day') + 1;

    try {
      const [compData, trendData, rankData] = await Promise.all([
        apiGet<ComparisonItem[]>(
          `/api/v1/analytics/store-comparison?store_ids=${idsParam}&metric=${metric}&start=${start}&end=${end}`
        ).catch(() => null),
        apiGet<StoreTrend[]>(
          `/api/v1/analytics/store-trend?store_ids=${idsParam}&metric=${metric}&start=${start}&end=${end}`
        ).catch(() => null),
        apiGet<RankRow[]>(
          `/api/v1/analytics/realtime/store-comparison?store_ids=${idsParam}&start=${start}&end=${end}`
        ).catch(() => null),
      ]);

      setComparison(compData ?? generateFallbackComparison(selectedStoreIds, metric, stores));
      setTrends(trendData ?? generateFallbackTrend(selectedStoreIds, metric, Math.min(days, 30), stores));

      const resolvedRank = rankData ?? generateFallbackRanking(selectedStoreIds, stores);
      setRanking(resolvedRank);
      setInsights(generateMockInsights(resolvedRank));
    } catch (_err: unknown) {
      // API 全部失败时使用 fallback
      const fbComp = generateFallbackComparison(selectedStoreIds, metric, stores);
      const fbTrend = generateFallbackTrend(selectedStoreIds, metric, Math.min(days, 30), stores);
      const fbRank = generateFallbackRanking(selectedStoreIds, stores);
      setComparison(fbComp);
      setTrends(fbTrend);
      setRanking(fbRank);
      setInsights(generateMockInsights(fbRank));
    }

    setLoading(false);
  }, [selectedStoreIds, metric, dateRange, stores]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ProTable 列定义
  const columns: ProColumns<RankRow>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 60,
      align: 'center',
      render: (_: unknown, row: RankRow) => {
        const bgMap: Record<number, string> = { 1: '#FFD700', 2: '#FFECD2', 3: '#FFECD2' };
        return (
          <span
            style={{
              display: 'inline-block',
              width: 24,
              height: 24,
              lineHeight: '24px',
              borderRadius: 12,
              textAlign: 'center',
              fontWeight: 700,
              fontSize: 13,
              background: bgMap[row.rank] ?? '#f5f5f5',
              color: row.rank === 1 ? '#8B6508' : '#666',
            }}
          >
            {row.rank}
          </span>
        );
      },
    },
    {
      title: '门店名',
      dataIndex: 'store_name',
      width: 140,
      ellipsis: true,
    },
    {
      title: '营收(元)',
      dataIndex: 'revenue',
      width: 110,
      align: 'right',
      sorter: (a: RankRow, b: RankRow) => a.revenue - b.revenue,
      render: (_: unknown, row: RankRow) => row.revenue.toLocaleString(),
    },
    {
      title: '订单数',
      dataIndex: 'orders',
      width: 90,
      align: 'right',
      sorter: (a: RankRow, b: RankRow) => a.orders - b.orders,
    },
    {
      title: '客单价',
      dataIndex: 'avg_spend',
      width: 90,
      align: 'right',
      sorter: (a: RankRow, b: RankRow) => a.avg_spend - b.avg_spend,
      render: (_: unknown, row: RankRow) => `${row.avg_spend.toFixed(1)}`,
    },
    {
      title: '翻台率',
      dataIndex: 'turnover_rate',
      width: 80,
      align: 'right',
      sorter: (a: RankRow, b: RankRow) => a.turnover_rate - b.turnover_rate,
      render: (_: unknown, row: RankRow) => `${row.turnover_rate}%`,
    },
    {
      title: '毛利率',
      dataIndex: 'gross_margin',
      width: 80,
      align: 'right',
      sorter: (a: RankRow, b: RankRow) => a.gross_margin - b.gross_margin,
      render: (_: unknown, row: RankRow) => `${row.gross_margin}%`,
    },
    {
      title: '环比增长',
      dataIndex: 'mom_change',
      width: 100,
      align: 'right',
      sorter: (a: RankRow, b: RankRow) => a.mom_change - b.mom_change,
      render: (_: unknown, row: RankRow) => (
        <span style={{ color: row.mom_change >= 0 ? '#10B981' : '#EF4444', fontWeight: 600 }}>
          {row.mom_change >= 0 ? `+${row.mom_change}%` : `${row.mom_change}%`}
          {row.mom_change >= 0 ? ' ↑' : ' ↓'}
        </span>
      ),
    },
  ];

  // 排名行样式
  const rowClassName = (record: RankRow) => {
    if (record.rank === 1) return 'rank-gold';
    if (record.rank <= 3) return 'rank-orange';
    return '';
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 页面标题 */}
        <h2 style={{ margin: '0 0 20px', fontSize: 22, fontWeight: 600 }}>
          多门店对比分析
        </h2>

        {/* 顶部筛选栏 */}
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap size={16}>
            {/* 快捷时间 */}
            {QUICK_RANGES.map((q) => (
              <Tag
                key={q.label}
                style={{
                  cursor: 'pointer',
                  borderColor:
                    dateRange[0].isSame(q.range[0], 'day') && dateRange[1].isSame(q.range[1], 'day')
                      ? '#FF6B35'
                      : undefined,
                  color:
                    dateRange[0].isSame(q.range[0], 'day') && dateRange[1].isSame(q.range[1], 'day')
                      ? '#FF6B35'
                      : undefined,
                }}
                onClick={() => setDateRange(q.range)}
              >
                {q.label}
              </Tag>
            ))}

            {/* 自定义日期 */}
            <RangePicker
              size="small"
              value={dateRange}
              onChange={(vals) => {
                if (vals && vals[0] && vals[1]) {
                  setDateRange([vals[0], vals[1]]);
                }
              }}
              allowClear={false}
            />

            {/* 门店多选 */}
            <Select
              mode="multiple"
              size="small"
              style={{ minWidth: 320 }}
              placeholder="选择门店（最多5家）"
              value={selectedStoreIds}
              maxCount={5}
              onChange={(vals: string[]) => setSelectedStoreIds(vals)}
              options={stores.map((s) => ({ value: s.store_id, label: s.store_name }))}
            />

            {/* 指标选择 */}
            <Select
              size="small"
              style={{ width: 120 }}
              value={metric}
              onChange={(val: MetricKey) => setMetric(val)}
              options={METRIC_OPTIONS.map((m) => ({ value: m.value, label: m.label }))}
            />
          </Space>
        </Card>

        {/* 对比图表区 + 趋势对比区 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <Card
              title={`${METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? ''} 门店对比`}
              size="small"
              loading={loading}
            >
              <GroupBarChart data={comparison} metric={metric} unit={metricUnit} />
            </Card>
          </Col>
          <Col span={12}>
            <Card
              title={`${METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? ''} 趋势对比`}
              size="small"
              loading={loading}
            >
              <TrendLineChart trends={trends} metric={metric} unit={metricUnit} />
            </Card>
          </Col>
        </Row>

        {/* 排名表格 */}
        <Card title="门店排名" size="small" style={{ marginBottom: 16 }}>
          <style>{`
            .rank-gold td { background: #FFFBE6 !important; }
            .rank-orange td { background: #FFF7E6 !important; }
          `}</style>
          <ProTable<RankRow>
            columns={columns}
            dataSource={ranking}
            rowKey="store_id"
            search={false}
            toolBarRender={false}
            pagination={false}
            loading={loading}
            rowClassName={rowClassName}
            size="small"
          />
        </Card>

        {/* 洞察卡片 */}
        <Card title="经营洞察" size="small">
          <InsightCards cards={insights} />
        </Card>
      </div>
    </ConfigProvider>
  );
}

export default StoreComparisonPage;
