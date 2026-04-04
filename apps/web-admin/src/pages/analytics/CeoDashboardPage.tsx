/**
 * CeoDashboardPage — CEO/品牌总经理 经营数据驾驶舱
 *
 * 终端：Admin（总部管理后台）
 * 域G：经营分析
 *
 * 布局（全屏暗色主题，适合投屏演示）：
 *   顶部品牌栏   — Logo位 + 品牌名 + 当前时间 + 数据截至时间
 *   核心KPI区    — 一行4张大卡（占顶部20%高度）
 *   中间区域     — 2x2网格（占60%高度）：营收趋势/门店TOP5/品类占比/满意度雷达
 *   底部区域     — 滚动新闻条 + 三条硬约束状态灯（占20%高度）
 *
 * 技术：React + ConfigProvider，主体纯 CSS-in-JS + SVG，暗色 #0d1117 背景
 * 图表：纯 SVG（无 echarts/recharts/d3）
 * 刷新：30s 自动刷新
 * 全屏：双击进入 document.requestFullscreen
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ConfigProvider } from 'antd';
import { apiGet } from '../../api/client';

// ─── Design Token（CEO驾驶舱暗色） ─────────────────────────────────────────────
const T = {
  bg0: '#0d1117',
  bg1: '#161b22',
  bg2: '#1c2333',
  bgCard: '#21262d',
  border: '#30363d',
  text1: '#e6edf3',
  text2: '#8b949e',
  text3: '#6e7681',
  brand: '#FF6B35',
  brandMuted: 'rgba(255,107,53,0.15)',
  brandGlow: 'rgba(255,107,53,0.3)',
  success: '#3fb950',
  successMuted: 'rgba(63,185,80,0.15)',
  warning: '#d29922',
  warningMuted: 'rgba(210,153,34,0.15)',
  danger: '#f85149',
  dangerMuted: 'rgba(248,81,73,0.15)',
  info: '#58a6ff',
  infoMuted: 'rgba(88,166,255,0.15)',
  purple: '#bc8cff',
  cyan: '#39d2c0',
} as const;

// BASE URL 通过 apiGet 注入，不再硬编码

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface KpiData {
  monthly_revenue: number;       // 元
  revenue_mom_pct: number;       // 环比 %
  total_stores: number;
  active_stores: number;
  gross_margin_pct: number;      // 毛利率 %
  total_members: number;
  new_members_month: number;
}

interface MonthlyRevenue {
  month: string;    // "2025-04"
  revenue: number;  // 元
  yoy: number;      // 同比 元
}

interface StoreRank {
  store_name: string;
  revenue: number;  // 元
}

interface CategoryShare {
  category: string;
  revenue: number;
  color: string;
}

interface SatisfactionData {
  food: number;       // 0-100
  service: number;
  environment: number;
  speed: number;
  price: number;
}

interface NewsEvent {
  id: string;
  type: 'success' | 'warning' | 'info';
  message: string;
  ts: string;
}

interface ConstraintStatus {
  margin: 'green' | 'yellow' | 'red';
  food_safety: 'green' | 'yellow' | 'red';
  delivery_speed: 'green' | 'yellow' | 'red';
}

// ─── Mock 数据 ─────────────────────────────────────────────────────────────────

function mockKpi(): KpiData {
  return {
    monthly_revenue: 3856000,
    revenue_mom_pct: 12.3,
    total_stores: 28,
    active_stores: 26,
    gross_margin_pct: 62.8,
    total_members: 185600,
    new_members_month: 4320,
  };
}

function mockMonthlyRevenue(): MonthlyRevenue[] {
  const months = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date();
    d.setMonth(d.getMonth() - i);
    const label = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const base = 2800000 + Math.random() * 1500000;
    months.push({ month: label, revenue: Math.round(base), yoy: Math.round(base * (0.8 + Math.random() * 0.3)) });
  }
  return months;
}

function mockStoreRanks(): StoreRank[] {
  return [
    { store_name: '万达广场店', revenue: 680000 },
    { store_name: '国金中心店', revenue: 620000 },
    { store_name: '德思勤店', revenue: 540000 },
    { store_name: '梅溪湖店', revenue: 485000 },
    { store_name: '河西王府井店', revenue: 430000 },
  ];
}

function mockCategoryShares(): CategoryShare[] {
  return [
    { category: '海鲜', revenue: 1200000, color: T.brand },
    { category: '炒菜', revenue: 900000, color: T.info },
    { category: '汤品', revenue: 600000, color: T.success },
    { category: '主食', revenue: 500000, color: T.warning },
    { category: '甜点', revenue: 356000, color: T.purple },
    { category: '饮品', revenue: 300000, color: T.cyan },
  ];
}

function mockSatisfaction(): SatisfactionData {
  return { food: 88, service: 82, environment: 90, speed: 75, price: 70 };
}

function mockNews(): NewsEvent[] {
  return [
    { id: '1', type: 'success', message: '🎉 梅溪湖店本月营收突破50万目标', ts: '14:30' },
    { id: '2', type: 'info', message: '📋 星沙新店装修进度85%，预计4月15日开业', ts: '13:10' },
    { id: '3', type: 'warning', message: '⚠️ 德思勤店午高峰出餐超时率达18%', ts: '12:45' },
    { id: '4', type: 'success', message: '🎉 本月新增会员4320人，超目标8%', ts: '11:00' },
    { id: '5', type: 'info', message: '📊 Q1经营分析报告已生成，待审阅', ts: '10:30' },
  ];
}

function mockConstraints(): ConstraintStatus {
  return { margin: 'green', food_safety: 'green', delivery_speed: 'green' };
}

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

function fmtMoney(v: number): string {
  if (v >= 10000) return (v / 10000).toFixed(1) + '万';
  return v.toLocaleString();
}

function fmtMoneyFull(v: number): string {
  return '¥' + v.toLocaleString('zh-CN', { minimumFractionDigits: 0 });
}

function fmtTime(d: Date): string {
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtDate(d: Date): string {
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

// ─── SVG 图表组件 ──────────────────────────────────────────────────────────────

/** 毛利率进度环 */
function GrossMarginRing({ pct, size = 90 }: { pct: number; size?: number }) {
  const r = (size - 12) / 2;
  const c = Math.PI * 2 * r;
  const offset = c * (1 - pct / 100);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={T.border} strokeWidth={8} />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke={T.success} strokeWidth={8} strokeLinecap="round"
        strokeDasharray={`${c}`} strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dashoffset 0.8s ease' }}
      />
      <text x={size / 2} y={size / 2 - 6} textAnchor="middle" fill={T.text1} fontSize={18} fontWeight={700}>
        {pct.toFixed(1)}%
      </text>
      <text x={size / 2} y={size / 2 + 14} textAnchor="middle" fill={T.text2} fontSize={11}>
        毛利率
      </text>
    </svg>
  );
}

/** 营收趋势面积图（近12月 + 同比虚线） */
function RevenueTrendChart({ data }: { data: MonthlyRevenue[] }) {
  const W = 520, H = 220, PX = 40, PY = 20, PB = 30;
  const chartW = W - PX * 2, chartH = H - PY - PB;
  const allVals = data.flatMap(d => [d.revenue, d.yoy]);
  const maxV = Math.max(...allVals) * 1.1;
  const xStep = chartW / Math.max(data.length - 1, 1);

  const revenuePoints = data.map((d, i) => ({
    x: PX + i * xStep,
    y: PY + chartH - (d.revenue / maxV) * chartH,
  }));
  const yoyPoints = data.map((d, i) => ({
    x: PX + i * xStep,
    y: PY + chartH - (d.yoy / maxV) * chartH,
  }));

  const areaPath = `M${revenuePoints[0].x},${revenuePoints[0].y} ` +
    revenuePoints.slice(1).map(p => `L${p.x},${p.y}`).join(' ') +
    ` L${revenuePoints[revenuePoints.length - 1].x},${PY + chartH} L${revenuePoints[0].x},${PY + chartH} Z`;

  const linePath = revenuePoints.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
  const yoyPath = yoyPoints.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={T.brand} stopOpacity={0.4} />
          <stop offset="100%" stopColor={T.brand} stopOpacity={0.02} />
        </linearGradient>
      </defs>
      {/* grid lines */}
      {[0, 0.25, 0.5, 0.75, 1].map(f => {
        const y = PY + chartH - f * chartH;
        return (
          <g key={f}>
            <line x1={PX} y1={y} x2={PX + chartW} y2={y} stroke={T.border} strokeWidth={0.5} />
            <text x={PX - 4} y={y + 4} textAnchor="end" fill={T.text3} fontSize={9}>
              {fmtMoney(maxV * f)}
            </text>
          </g>
        );
      })}
      {/* area fill */}
      <path d={areaPath} fill="url(#areaGrad)" />
      {/* revenue line */}
      <path d={linePath} fill="none" stroke={T.brand} strokeWidth={2.5} />
      {/* yoy dashed line */}
      <path d={yoyPath} fill="none" stroke={T.text3} strokeWidth={1.5} strokeDasharray="6,4" />
      {/* x labels */}
      {data.map((d, i) => (
        i % 2 === 0 ? (
          <text key={d.month} x={PX + i * xStep} y={H - 6} textAnchor="middle" fill={T.text3} fontSize={9}>
            {d.month.slice(5)}月
          </text>
        ) : null
      ))}
      {/* legend */}
      <line x1={W - 140} y1={12} x2={W - 120} y2={12} stroke={T.brand} strokeWidth={2} />
      <text x={W - 116} y={16} fill={T.text2} fontSize={10}>本期</text>
      <line x1={W - 80} y1={12} x2={W - 60} y2={12} stroke={T.text3} strokeWidth={1.5} strokeDasharray="4,3" />
      <text x={W - 56} y={16} fill={T.text2} fontSize={10}>同比</text>
      {/* dots */}
      {revenuePoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill={T.brand} />
      ))}
    </svg>
  );
}

/** 门店TOP5水平柱状图 */
function StoreTop5Chart({ data }: { data: StoreRank[] }) {
  const W = 520, H = 220, PL = 100, PR = 60, PY = 16;
  const barH = 28, gap = 10;
  const maxV = Math.max(...data.map(d => d.revenue));
  const barAreaW = W - PL - PR;

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
      {data.map((d, i) => {
        const y = PY + i * (barH + gap);
        const barW = (d.revenue / maxV) * barAreaW;
        const colors = [T.brand, T.info, T.success, T.warning, T.purple];
        return (
          <g key={d.store_name}>
            <text x={PL - 8} y={y + barH / 2 + 4} textAnchor="end" fill={T.text2} fontSize={12}>
              {d.store_name}
            </text>
            <rect x={PL} y={y} width={barW} height={barH} rx={4} fill={colors[i]} opacity={0.85}
              style={{ transition: 'width 0.6s ease' }} />
            <text x={PL + barW + 8} y={y + barH / 2 + 4} fill={T.text1} fontSize={12} fontWeight={600}>
              {fmtMoney(d.revenue)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** 品类营收占比环形图 */
function CategoryDonutChart({ data }: { data: CategoryShare[] }) {
  const size = 220, cx = size / 2, cy = size / 2, R = 80, r = 50;
  const total = data.reduce((s, d) => s + d.revenue, 0);
  let cumAngle = -Math.PI / 2;

  const arcs = data.map(d => {
    const angle = (d.revenue / total) * Math.PI * 2;
    const startAngle = cumAngle;
    cumAngle += angle;
    const endAngle = cumAngle;
    const largeArc = angle > Math.PI ? 1 : 0;
    const x1o = cx + R * Math.cos(startAngle), y1o = cy + R * Math.sin(startAngle);
    const x2o = cx + R * Math.cos(endAngle), y2o = cy + R * Math.sin(endAngle);
    const x1i = cx + r * Math.cos(endAngle), y1i = cy + r * Math.sin(endAngle);
    const x2i = cx + r * Math.cos(startAngle), y2i = cy + r * Math.sin(startAngle);
    const path = `M${x1o},${y1o} A${R},${R} 0 ${largeArc} 1 ${x2o},${y2o} L${x1i},${y1i} A${r},${r} 0 ${largeArc} 0 ${x2i},${y2i} Z`;
    return { ...d, path, pct: ((d.revenue / total) * 100).toFixed(1) };
  });

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${size + 140} ${size}`} preserveAspectRatio="xMidYMid meet">
      {arcs.map(a => (
        <path key={a.category} d={a.path} fill={a.color} opacity={0.9} />
      ))}
      <text x={cx} y={cy - 4} textAnchor="middle" fill={T.text1} fontSize={14} fontWeight={700}>
        ¥{fmtMoney(total)}
      </text>
      <text x={cx} y={cy + 14} textAnchor="middle" fill={T.text3} fontSize={10}>
        总营收
      </text>
      {/* legend */}
      {arcs.map((a, i) => (
        <g key={a.category}>
          <rect x={size + 8} y={20 + i * 28} width={12} height={12} rx={2} fill={a.color} />
          <text x={size + 26} y={20 + i * 28 + 11} fill={T.text2} fontSize={11}>
            {a.category} {a.pct}%
          </text>
        </g>
      ))}
    </svg>
  );
}

/** 客户满意度雷达图（5维 polygon） */
function SatisfactionRadar({ data }: { data: SatisfactionData }) {
  const size = 220, cx = size / 2, cy = size / 2, R = 80;
  const dims: { key: keyof SatisfactionData; label: string }[] = [
    { key: 'food', label: '菜品' },
    { key: 'service', label: '服务' },
    { key: 'environment', label: '环境' },
    { key: 'speed', label: '速度' },
    { key: 'price', label: '价格' },
  ];
  const n = dims.length;
  const angleStep = (Math.PI * 2) / n;

  function polarXY(value: number, idx: number): [number, number] {
    const angle = -Math.PI / 2 + idx * angleStep;
    const r = (value / 100) * R;
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
  }

  const gridLevels = [20, 40, 60, 80, 100];
  const dataPoints = dims.map((d, i) => polarXY(data[d.key], i));
  const dataPath = dataPoints.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ') + ' Z';

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${size} ${size}`} preserveAspectRatio="xMidYMid meet">
      {/* grid polygons */}
      {gridLevels.map(lv => {
        const pts = dims.map((_, i) => polarXY(lv, i)).map(([x, y]) => `${x},${y}`).join(' ');
        return <polygon key={lv} points={pts} fill="none" stroke={T.border} strokeWidth={0.8} />;
      })}
      {/* axis lines */}
      {dims.map((_, i) => {
        const [x, y] = polarXY(100, i);
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke={T.border} strokeWidth={0.5} />;
      })}
      {/* data polygon */}
      <polygon points={dataPoints.map(([x, y]) => `${x},${y}`).join(' ')}
        fill={T.brandMuted} stroke={T.brand} strokeWidth={2} />
      {/* dots + labels */}
      {dims.map((d, i) => {
        const [x, y] = polarXY(data[d.key], i);
        const [lx, ly] = polarXY(115, i);
        return (
          <g key={d.key}>
            <circle cx={x} cy={y} r={4} fill={T.brand} />
            <text x={lx} y={ly + 4} textAnchor="middle" fill={T.text2} fontSize={11}>
              {d.label}
            </text>
            <text x={lx} y={ly + 18} textAnchor="middle" fill={T.text1} fontSize={10} fontWeight={600}>
              {data[d.key]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ─── 状态灯颜色映射 ──────────────────────────────────────────────────────────
function statusColor(s: 'green' | 'yellow' | 'red'): string {
  if (s === 'green') return T.success;
  if (s === 'yellow') return T.warning;
  return T.danger;
}

function statusEmoji(s: 'green' | 'yellow' | 'red'): string {
  if (s === 'green') return '\uD83D\uDFE2';
  if (s === 'yellow') return '\uD83D\uDFE1';
  return '\uD83D\uDD34';
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function CeoDashboardPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(new Date());
  const [dataTime, setDataTime] = useState(new Date());
  const [countdown, setCountdown] = useState(30);

  const [kpi, setKpi] = useState<KpiData>(mockKpi);
  const [revenueData, setRevenueData] = useState<MonthlyRevenue[]>(mockMonthlyRevenue);
  const [storeRanks, setStoreRanks] = useState<StoreRank[]>(mockStoreRanks);
  const [categories, setCategories] = useState<CategoryShare[]>(mockCategoryShares);
  const [satisfaction, setSatisfaction] = useState<SatisfactionData>(mockSatisfaction);
  const [news, setNews] = useState<NewsEvent[]>(mockNews);
  const [constraints, setConstraints] = useState<ConstraintStatus>(mockConstraints);
  const [newsOffset, setNewsOffset] = useState(0);

  // ─── 数据加载 ──────────────────────────────────────────────────────────────
  const loadData = useCallback(async () => {
    try {
      const [kpiData, revData, storeData, catData, satData, newsData, conData] = await Promise.all([
        apiGet<KpiData>('/api/v1/analytics/ceo/kpi').catch(() => null),
        apiGet<MonthlyRevenue[]>('/api/v1/analytics/ceo/revenue-trend').catch(() => null),
        apiGet<StoreRank[]>('/api/v1/analytics/ceo/store-ranks').catch(() => null),
        apiGet<CategoryShare[]>('/api/v1/analytics/ceo/category-shares').catch(() => null),
        apiGet<SatisfactionData>('/api/v1/analytics/ceo/satisfaction').catch(() => null),
        apiGet<NewsEvent[]>('/api/v1/analytics/ceo/news').catch(() => null),
        apiGet<ConstraintStatus>('/api/v1/analytics/ceo/constraints').catch(() => null),
      ]);

      if (kpiData) setKpi(kpiData);
      if (revData) setRevenueData(revData);
      if (storeData) setStoreRanks(storeData);
      if (catData) setCategories(catData);
      if (satData) setSatisfaction(satData);
      if (newsData) setNews(newsData);
      if (conData) setConstraints(conData);
      setDataTime(new Date());
    } catch (_e: unknown) {
      // API不可用，继续使用 Mock 数据
    }
  }, []);

  // ─── 时钟 + 自动刷新 ──────────────────────────────────────────────────────
  useEffect(() => {
    loadData();
    const clockTimer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(clockTimer);
  }, [loadData]);

  useEffect(() => {
    const refreshTimer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          loadData();
          return 30;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(refreshTimer);
  }, [loadData]);

  // ─── 新闻滚动 ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (news.length === 0) return;
    const scrollTimer = setInterval(() => {
      setNewsOffset(prev => (prev + 1) % news.length);
    }, 4000);
    return () => clearInterval(scrollTimer);
  }, [news.length]);

  // ─── 双击全屏 ──────────────────────────────────────────────────────────────
  const handleDoubleClick = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {/* ignore */});
    } else {
      el.requestFullscreen().catch(() => {/* ignore */});
    }
  }, []);

  // ─── KPI 卡片渲染 ──────────────────────────────────────────────────────────
  const kpiCards: Array<{ title: string; content: React.ReactNode }> = [
    {
      title: '本月总营收',
      content: (
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 800, color: T.text1, lineHeight: 1.2 }}>
            {fmtMoneyFull(kpi.monthly_revenue)}
          </div>
          <div style={{
            fontSize: 14, marginTop: 6,
            color: kpi.revenue_mom_pct >= 0 ? T.success : T.danger,
            fontWeight: 600,
          }}>
            {kpi.revenue_mom_pct >= 0 ? '▲' : '▼'} {Math.abs(kpi.revenue_mom_pct).toFixed(1)}% 环比
          </div>
        </div>
      ),
    },
    {
      title: '门店总数 / 营业中',
      content: (
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 800, color: T.text1, lineHeight: 1.2 }}>
            <span>{kpi.total_stores}</span>
            <span style={{ fontSize: 18, color: T.text3, margin: '0 6px' }}>/</span>
            <span style={{ color: T.success }}>{kpi.active_stores}</span>
          </div>
          <div style={{ fontSize: 12, color: T.text2, marginTop: 6 }}>
            营业率 {((kpi.active_stores / kpi.total_stores) * 100).toFixed(0)}%
          </div>
        </div>
      ),
    },
    {
      title: '全品牌毛利率',
      content: (
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <GrossMarginRing pct={kpi.gross_margin_pct} size={90} />
        </div>
      ),
    },
    {
      title: '会员总数',
      content: (
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 800, color: T.text1, lineHeight: 1.2 }}>
            {(kpi.total_members / 10000).toFixed(1)}<span style={{ fontSize: 16, color: T.text2 }}>万</span>
          </div>
          <div style={{ fontSize: 13, color: T.info, marginTop: 6, fontWeight: 600 }}>
            +{kpi.new_members_month.toLocaleString()} 本月新增
          </div>
        </div>
      ),
    },
  ];

  // ─── 样式常量 ─────────────────────────────────────────────────────────────
  const cardStyle: React.CSSProperties = {
    background: T.bgCard,
    borderRadius: 12,
    border: `1px solid ${T.border}`,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
  };

  const sectionTitleStyle: React.CSSProperties = {
    fontSize: 13,
    color: T.text2,
    fontWeight: 600,
    marginBottom: 12,
    letterSpacing: 1,
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div
        ref={containerRef}
        onDoubleClick={handleDoubleClick}
        style={{
          width: '100%',
          height: '100vh',
          background: T.bg0,
          color: T.text1,
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          userSelect: 'none',
        }}
      >
        {/* ─── 顶部品牌栏 ───────────────────────────────────────────────────── */}
        <div style={{
          height: 56,
          minHeight: 56,
          background: T.bg1,
          borderBottom: `1px solid ${T.border}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 24px',
          justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {/* Logo 占位 */}
            <div style={{
              width: 36, height: 36, borderRadius: 8,
              background: `linear-gradient(135deg, ${T.brand}, #ff9966)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 18, fontWeight: 900, color: '#fff',
            }}>
              TX
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: T.text1 }}>屯象OS</div>
              <div style={{ fontSize: 10, color: T.text3, marginTop: -2 }}>CEO 经营驾驶舱</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 20, fontWeight: 600, color: T.text1, fontVariantNumeric: 'tabular-nums' }}>
                {fmtTime(now)}
              </div>
              <div style={{ fontSize: 11, color: T.text3 }}>{fmtDate(now)}</div>
            </div>
            <div style={{
              background: T.bgCard, borderRadius: 8, padding: '4px 12px',
              border: `1px solid ${T.border}`,
            }}>
              <div style={{ fontSize: 10, color: T.text3 }}>数据截至</div>
              <div style={{ fontSize: 12, color: T.text2, fontVariantNumeric: 'tabular-nums' }}>
                {fmtTime(dataTime)}
              </div>
            </div>
            <div style={{
              width: 32, height: 32, borderRadius: '50%',
              background: T.brandMuted, display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 12, fontWeight: 700, color: T.brand, fontVariantNumeric: 'tabular-nums',
            }}>
              {countdown}
            </div>
          </div>
        </div>

        {/* ─── 核心KPI区（20%） ─────────────────────────────────────────────── */}
        <div style={{
          flex: '0 0 20%',
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 16,
          padding: '16px 24px',
        }}>
          {kpiCards.map(card => (
            <div key={card.title} style={{
              ...cardStyle,
              justifyContent: 'center',
              alignItems: 'center',
            }}>
              <div style={{ fontSize: 12, color: T.text3, marginBottom: 10, fontWeight: 600, letterSpacing: 1 }}>
                {card.title}
              </div>
              {card.content}
            </div>
          ))}
        </div>

        {/* ─── 中间区域（60%）2x2 网格 ──────────────────────────────────────── */}
        <div style={{
          flex: '0 0 60%',
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gridTemplateRows: '1fr 1fr',
          gap: 16,
          padding: '0 24px',
        }}>
          {/* 左上：营收趋势 */}
          <div style={cardStyle}>
            <div style={sectionTitleStyle}>营收趋势（近12月）</div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <RevenueTrendChart data={revenueData} />
            </div>
          </div>

          {/* 右上：门店TOP5 */}
          <div style={cardStyle}>
            <div style={sectionTitleStyle}>门店营收 TOP5</div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <StoreTop5Chart data={storeRanks} />
            </div>
          </div>

          {/* 左下：品类占比 */}
          <div style={cardStyle}>
            <div style={sectionTitleStyle}>品类营收占比</div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <CategoryDonutChart data={categories} />
            </div>
          </div>

          {/* 右下：满意度雷达 */}
          <div style={cardStyle}>
            <div style={sectionTitleStyle}>客户满意度（5维）</div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <SatisfactionRadar data={satisfaction} />
            </div>
          </div>
        </div>

        {/* ─── 底部区域（20%） ─────────────────────────────────────────────── */}
        <div style={{
          flex: '0 0 auto',
          padding: '12px 24px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}>
          {/* 滚动新闻条 */}
          <div style={{
            ...cardStyle,
            flexDirection: 'row',
            alignItems: 'center',
            padding: '10px 20px',
            overflow: 'hidden',
            height: 48,
          }}>
            <div style={{
              fontSize: 11, color: T.brand, fontWeight: 700,
              marginRight: 16, whiteSpace: 'nowrap',
              background: T.brandMuted, padding: '2px 8px', borderRadius: 4,
            }}>
              经营快讯
            </div>
            <div style={{
              flex: 1, overflow: 'hidden', position: 'relative', height: 24,
            }}>
              {news.map((item, i) => (
                <div
                  key={item.id}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    opacity: i === newsOffset ? 1 : 0,
                    transform: `translateY(${i === newsOffset ? 0 : 20}px)`,
                    transition: 'opacity 0.5s, transform 0.5s',
                    fontSize: 13,
                    color: item.type === 'warning' ? T.warning : item.type === 'success' ? T.success : T.text2,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  <span style={{ color: T.text3, marginRight: 8 }}>{item.ts}</span>
                  {item.message}
                </div>
              ))}
            </div>
          </div>

          {/* 三条硬约束状态灯 */}
          <div style={{
            display: 'flex', gap: 16, justifyContent: 'center',
          }}>
            {([
              { key: 'margin' as const, label: '毛利', icon: statusEmoji(constraints.margin) },
              { key: 'food_safety' as const, label: '食安', icon: statusEmoji(constraints.food_safety) },
              { key: 'delivery_speed' as const, label: '出餐', icon: statusEmoji(constraints.delivery_speed) },
            ]).map(item => (
              <div key={item.key} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                background: T.bgCard, borderRadius: 8, padding: '8px 20px',
                border: `1px solid ${T.border}`,
              }}>
                <span style={{ fontSize: 16 }}>{item.icon}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.text2 }}>{item.label}</span>
                <div style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: statusColor(constraints[item.key]),
                  boxShadow: `0 0 8px ${statusColor(constraints[item.key])}`,
                }} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
}

export default CeoDashboardPage;
