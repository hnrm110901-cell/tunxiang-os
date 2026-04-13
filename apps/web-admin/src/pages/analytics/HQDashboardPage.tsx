/**
 * HQDashboardPage — 集团经营驾驶舱大屏
 *
 * 终端：Admin（总部管理后台）
 * 域G：经营分析
 *
 * 布局（1440px 宽，适合大显示器 / 全屏投影）：
 *   顶栏 60px  — Logo + 门店选择 + 实时时钟 + 全屏按钮 + 30s倒计时
 *   主区上半   — 左(实时指标6卡) | 中(营收趋势SVG折线图) | 右(门店排行榜)
 *   主区下半   — 左(菜品热销TOP10水平进度条) | 右(Agent预警区)
 *
 * 技术：React + Ant Design inline style，ConfigProvider 主色 #FF6B35
 * 图表：纯 SVG（无 echarts/recharts/d3）
 * 刷新：30s 自动刷新所有数据
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ConfigProvider, Select, Spin, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import RealtimeDashboard from '../../components/RealtimeDashboard';
import { formatPrice } from '@tx-ds/utils';

// ─── Design Token（驾驶舱暗色） ────────────────────────────────────────────────
const T = {
  bg0: '#0d1117',
  bg1: '#1a1a2e',
  bg2: '#16213e',
  border: '#333',
  text1: '#e6e6e6',
  text2: '#999',
  brand: '#FF6B35',
  brandMuted: 'rgba(255,107,53,0.15)',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  gold: '#FFD700',
  silver: '#C0C0C0',
  bronze: '#CD7F32',
} as const;

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface HourlyPoint {
  hour: number;      // 8–22
  today: number;     // 元（非分）
  yesterday: number;
  lastWeek: number;
}

interface StoreRankRow {
  rank: number;
  store_id: string;
  store_name: string;
  revenue_fen: number;  // 分
  yoy_pct: number;      // 同比 %，正上升负下降
}

interface TopDish {
  name: string;
  count: number;
}

interface AlertItem {
  id: string;
  level: 'error' | 'warning' | 'info';
  message: string;
  ts: string;         // "HH:MM"
}

// ─── 注：MOCK 数据已移除，API 失败时使用空状态，不降级展示虚假数据 ────────────

// ─── 门店选项 ──────────────────────────────────────────────────────────────────
const STORE_OPTIONS = [
  { value: '', label: '全部门店' },
  { value: 'S1', label: '五一广场店' },
  { value: 'S2', label: '东塘店' },
  { value: 'S3', label: '河西万达店' },
];

// ─── 工具函数 ──────────────────────────────────────────────────────────────────
/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number) =>
  (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const pad = (n: number) => String(n).padStart(2, '0');

function nowHHMM() {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function getTenantId() {
  if (typeof window === 'undefined') return 'demo-tenant';
  return localStorage.getItem('tx_tenant_id') ?? 'demo-tenant';
}

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('tx_token') ?? '';
  return {
    'Content-Type': 'application/json',
    'X-Tenant-ID': getTenantId(),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

// ─── 子组件：实时时钟 ──────────────────────────────────────────────────────────
function RealtimeClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span style={{ fontVariantNumeric: 'tabular-nums', fontSize: 14, color: T.text2, letterSpacing: '0.04em' }}>
      {now.getFullYear()}-{pad(now.getMonth() + 1)}-{pad(now.getDate())}
      &nbsp;
      {pad(now.getHours())}:{pad(now.getMinutes())}:{pad(now.getSeconds())}
    </span>
  );
}

// ─── 子组件：30s 倒计时进度条 ─────────────────────────────────────────────────
interface CountdownBarProps { onTick: (remaining: number) => void; }
function CountdownBar({ onTick }: CountdownBarProps) {
  const [remaining, setRemaining] = useState(30);
  useEffect(() => {
    const t = setInterval(() => {
      setRemaining((prev) => {
        const next = prev <= 1 ? 30 : prev - 1;
        onTick(next);
        return next;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [onTick]);
  const pct = ((30 - remaining) / 30) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ fontSize: 11, color: T.text2, whiteSpace: 'nowrap' }}>
        {remaining}s 刷新
      </span>
      <div style={{ width: 60, height: 4, borderRadius: 2, background: T.border, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          background: T.brand,
          borderRadius: 2,
          transition: 'width 1s linear',
        }} />
      </div>
    </div>
  );
}

// ─── 子组件：营收趋势 SVG 折线图 ───────────────────────────────────────────────
interface RevenueTrendChartProps {
  data: HourlyPoint[];
  currentHour: number;
}
function RevenueTrendChart({ data, currentHour }: RevenueTrendChartProps) {
  const W = 760;
  const H = 200;
  const PAD = { top: 20, right: 60, bottom: 36, left: 64 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const hours = data.map((d) => d.hour);
  const allValues = data.flatMap((d) => [d.today, d.yesterday, d.lastWeek]);
  const maxV = Math.max(...allValues, 1);

  const xScale = (hour: number) =>
    PAD.left + ((hour - hours[0]) / (hours[hours.length - 1] - hours[0])) * chartW;

  const yScale = (val: number) =>
    PAD.top + chartH - (val / maxV) * chartH;

  const toPath = (key: 'today' | 'yesterday' | 'lastWeek') =>
    data
      .map((d, i) => `${i === 0 ? 'M' : 'L'}${xScale(d.hour).toFixed(1)},${yScale(d[key]).toFixed(1)}`)
      .join(' ');

  // 当前小时竖线 x
  const nowX = hours.includes(currentHour) ? xScale(currentHour) : null;

  // 今日最高点
  const maxToday = data.reduce((a, b) => (b.today > a.today ? b : a), data[0]);
  const maxTodayX = xScale(maxToday.hour);
  const maxTodayY = yScale(maxToday.today);

  // Y轴刻度
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((r) => ({
    val: maxV * r,
    y: PAD.top + chartH - r * chartH,
  }));

  const formatYLabel = (v: number) =>
    v >= 10000 ? `${(v / 10000).toFixed(1)}万` : `${Math.round(v)}`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      style={{ display: 'block', background: T.bg1, borderRadius: 8 }}
    >
      {/* 背景格线 */}
      {yTicks.map((t) => (
        <line
          key={t.val}
          x1={PAD.left} y1={t.y}
          x2={W - PAD.right} y2={t.y}
          stroke={T.border} strokeWidth="0.5" strokeDasharray="3,3"
        />
      ))}

      {/* Y轴标签 */}
      {yTicks.map((t) => (
        <text
          key={t.val}
          x={PAD.left - 6} y={t.y + 4}
          textAnchor="end" fontSize="9" fill={T.text2}
        >
          {formatYLabel(t.val)}
        </text>
      ))}

      {/* X轴标签（每隔2小时显示） */}
      {hours.filter((h) => h % 2 === 0).map((h) => (
        <text
          key={h}
          x={xScale(h)} y={H - 6}
          textAnchor="middle" fontSize="9" fill={T.text2}
        >
          {h}:00
        </text>
      ))}

      {/* 当前小时竖线 */}
      {nowX !== null && (
        <line
          x1={nowX} y1={PAD.top}
          x2={nowX} y2={PAD.top + chartH}
          stroke={T.brand} strokeWidth="1" strokeDasharray="4,3" opacity="0.7"
        />
      )}

      {/* 上周同日（灰虚线） */}
      <path d={toPath('lastWeek')} fill="none" stroke="#444" strokeWidth="1.5" strokeDasharray="5,3" />

      {/* 昨日（蓝灰实线） */}
      <path d={toPath('yesterday')} fill="none" stroke="#5580A0" strokeWidth="1.5" />

      {/* 今日面积渐变填充 */}
      <defs>
        <linearGradient id="todayGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={T.brand} stopOpacity="0.25" />
          <stop offset="100%" stopColor={T.brand} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path
        d={`${toPath('today')} L${xScale(hours[hours.length - 1])},${PAD.top + chartH} L${xScale(hours[0])},${PAD.top + chartH} Z`}
        fill="url(#todayGrad)"
      />
      {/* 今日折线（橙色，加粗） */}
      <path d={toPath('today')} fill="none" stroke={T.brand} strokeWidth="2.5" />

      {/* 今日数据点 */}
      {data.map((d) => (
        <circle
          key={d.hour}
          cx={xScale(d.hour)} cy={yScale(d.today)}
          r="3" fill={T.brand} stroke={T.bg1} strokeWidth="1.5"
        />
      ))}

      {/* 最高点标注 */}
      {maxToday.today > 0 && (
        <>
          <circle cx={maxTodayX} cy={maxTodayY} r="5" fill={T.brand} stroke="#fff" strokeWidth="1.5" />
          <text
            x={maxTodayX} y={maxTodayY - 10}
            textAnchor="middle" fontSize="10" fill={T.brand} fontWeight="700"
          >
            ¥{formatYLabel(maxToday.today)}
          </text>
        </>
      )}

      {/* 图例（右上角） */}
      {[
        { color: T.brand, label: '今日', dash: undefined },
        { color: '#5580A0', label: '昨日', dash: undefined },
        { color: '#444', label: '上周同日', dash: '5,3' },
      ].map((leg, i) => (
        <g key={leg.label} transform={`translate(${W - PAD.right - 4},${PAD.top + i * 16})`}>
          <line
            x1="0" y1="5" x2="18" y2="5"
            stroke={leg.color} strokeWidth="2"
            strokeDasharray={leg.dash}
          />
          <text x="22" y="9" fontSize="9" fill={T.text2}>{leg.label}</text>
        </g>
      ))}
    </svg>
  );
}

// ─── 子组件：门店排行榜（Ant Design Table） ────────────────────────────────────
interface StoreRankingTableProps {
  data: StoreRankRow[];
}
function StoreRankingTable({ data }: StoreRankingTableProps) {
  const rankIcon = (rank: number) => {
    if (rank === 1) return <span style={{ color: T.gold, fontSize: 16 }}>🥇</span>;
    if (rank === 2) return <span style={{ color: T.silver, fontSize: 16 }}>🥈</span>;
    if (rank === 3) return <span style={{ color: T.bronze, fontSize: 16 }}>🥉</span>;
    return <span style={{ color: T.text2, fontSize: 13, fontWeight: 700 }}>{rank}</span>;
  };

  const columns: ColumnsType<StoreRankRow> = [
    {
      title: '排名', dataIndex: 'rank', width: 48,
      render: (r: number) => (
        <div style={{ textAlign: 'center' }}>{rankIcon(r)}</div>
      ),
    },
    {
      title: '门店', dataIndex: 'store_name',
      render: (name: string) => (
        <span style={{ color: T.text1, fontSize: 12 }}>{name}</span>
      ),
    },
    {
      title: '营收', dataIndex: 'revenue_fen',
      render: (v: number) => (
        <span style={{ color: T.brand, fontWeight: 700, fontSize: 13 }}>
          ¥{fenToYuan(v)}
        </span>
      ),
    },
    {
      title: '同比', dataIndex: 'yoy_pct',
      render: (pct: number) => {
        const up = pct >= 0;
        return (
          <Tag
            color={up ? 'success' : 'error'}
            style={{ fontSize: 11, padding: '1px 5px' }}
          >
            {up ? '↑' : '↓'} {Math.abs(pct).toFixed(1)}%
          </Tag>
        );
      },
    },
  ];

  return (
    <Table<StoreRankRow>
      dataSource={data}
      columns={columns}
      rowKey="store_id"
      size="small"
      pagination={false}
      style={{ background: 'transparent' }}
      className="hq-rank-table"
    />
  );
}

// ─── 子组件：菜品热销 TOP10 ───────────────────────────────────────────────────
interface TopDishesProps {
  data: TopDish[];
}
function TopDishes({ data }: TopDishesProps) {
  const maxCount = data.length > 0 ? Math.max(...data.map((d) => d.count)) : 1;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      {data.map((dish, idx) => {
        const pct = (dish.count / maxCount) * 100;
        const isTop3 = idx < 3;
        return (
          <div key={dish.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* 序号 */}
            <span style={{
              width: 18, height: 18, borderRadius: 4, flexShrink: 0,
              background: isTop3 ? T.brand : T.bg2,
              color: isTop3 ? '#fff' : T.text2,
              fontSize: 10, fontWeight: 700,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {idx + 1}
            </span>
            {/* 菜名 */}
            <span style={{
              width: 80, fontSize: 12, color: T.text1,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              flexShrink: 0,
            }}>
              {dish.name}
            </span>
            {/* 进度条 */}
            <div style={{
              flex: 1, height: 12, borderRadius: 6,
              background: 'rgba(255,255,255,0.06)', overflow: 'hidden',
            }}>
              <div style={{
                width: `${pct}%`, height: '100%', borderRadius: 6,
                background: isTop3
                  ? `linear-gradient(90deg, ${T.brand}, #FF8555)`
                  : '#374151',
                transition: 'width 0.6s ease',
              }} />
            </div>
            {/* 销量 */}
            <span style={{
              width: 34, fontSize: 11, color: isTop3 ? T.brand : T.text2,
              textAlign: 'right', fontVariantNumeric: 'tabular-nums',
              fontWeight: isTop3 ? 700 : 400, flexShrink: 0,
            }}>
              {dish.count}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── 子组件：Agent 预警区 ──────────────────────────────────────────────────────
interface AlertPanelProps {
  alerts: AlertItem[];
  isNewAlert: (id: string) => boolean;
}
function AlertPanel({ alerts, isNewAlert }: AlertPanelProps) {
  if (alerts.length === 0) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: T.success, fontSize: 14,
      }}>
        当前运营正常
      </div>
    );
  }

  const levelStyle: Record<AlertItem['level'], { bg: string; border: string; icon: string }> = {
    error:   { bg: 'rgba(163,45,45,0.18)',  border: '#A32D2D', icon: '🚨' },
    warning: { bg: 'rgba(186,117,23,0.15)', border: '#BA7517', icon: '⚠️' },
    info:    { bg: 'rgba(24,95,165,0.15)',  border: '#185FA5', icon: 'ℹ️' },
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', flex: 1 }}>
      {alerts.map((a) => {
        const s = levelStyle[a.level];
        const isNew = isNewAlert(a.id);
        return (
          <div
            key={a.id}
            style={{
              background: s.bg,
              borderLeft: `3px solid ${s.border}`,
              borderRadius: '0 6px 6px 0',
              padding: '8px 10px',
              animation: isNew ? 'hq-fadein 0.5s ease' : undefined,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{ fontSize: 12 }}>{s.icon}</span>
              <span style={{ flex: 1, fontSize: 11, color: T.text1, lineHeight: 1.5 }}>
                {a.message}
              </span>
              <span style={{ fontSize: 10, color: T.text2, whiteSpace: 'nowrap', marginLeft: 4 }}>
                {a.ts}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 卡片容器 ──────────────────────────────────────────────────────────────────
function Card({
  title, extra, children, style,
}: {
  title: string; extra?: React.ReactNode;
  children: React.ReactNode; style?: React.CSSProperties;
}) {
  return (
    <div style={{
      background: T.bg1, borderRadius: 8, padding: '14px 16px',
      border: `1px solid ${T.border}`, display: 'flex', flexDirection: 'column',
      overflow: 'hidden', ...style,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 12, flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: T.text1 }}>{title}</span>
        {extra && <span style={{ fontSize: 11, color: T.text2 }}>{extra}</span>}
      </div>
      <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
        {children}
      </div>
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function HQDashboardPage() {
  const containerRef = useRef<HTMLDivElement>(null);

  const [selectedStore, setSelectedStore] = useState<string>('');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [asOf, setAsOf] = useState(nowHHMM());

  // 数据状态
  const [hourlyData, setHourlyData]   = useState<HourlyPoint[]>([]);
  const [rankingData, setRankingData] = useState<StoreRankRow[]>([]);
  const [topDishes, setTopDishes]     = useState<TopDish[]>([]);
  const [alerts, setAlerts]           = useState<AlertItem[]>([]);
  const [newAlertIds, setNewAlertIds] = useState<Set<string>>(new Set());
  const [dataLoading, setDataLoading] = useState(true);

  const currentHour = new Date().getHours();

  // ── 数据获取 ──
  const fetchAll = useCallback(async () => {
    setDataLoading(true);
    const headers = getAuthHeaders();
    const today = new Date().toISOString().slice(0, 10);
    const storeParam = selectedStore ? `&store_id=${selectedStore}` : '';

    const [kpiRes, compareRes, alertRes] = await Promise.allSettled([
      fetch(`/api/v1/analytics/hq/kpi?date=${today}${storeParam}`, { headers }),
      fetch(`/api/v1/analytics/hq/store-comparison?date=${today}`, { headers }),
      fetch(`/api/v1/analytics/alerts?level=critical&status=active${storeParam}`, { headers }),
    ]);

    if (kpiRes.status === 'fulfilled' && kpiRes.value.ok) {
      try {
        const j = await kpiRes.value.json();
        if (j?.ok) {
          if (Array.isArray(j.data?.hourly_trend)) setHourlyData(j.data.hourly_trend as HourlyPoint[]);
          else setHourlyData([]);
          if (Array.isArray(j.data?.top_dishes)) setTopDishes(j.data.top_dishes as TopDish[]);
          else setTopDishes([]);
        }
      } catch { setHourlyData([]); setTopDishes([]); }
    } else {
      setHourlyData([]); setTopDishes([]);
    }

    if (compareRes.status === 'fulfilled' && compareRes.value.ok) {
      try {
        const j = await compareRes.value.json();
        if (j?.ok && Array.isArray(j.data)) setRankingData(j.data as StoreRankRow[]);
        else if (j?.ok && Array.isArray(j.data?.stores)) setRankingData(j.data.stores as StoreRankRow[]);
        else setRankingData([]);
      } catch { setRankingData([]); }
    } else {
      setRankingData([]);
    }

    if (alertRes.status === 'fulfilled' && alertRes.value.ok) {
      try {
        const j = await alertRes.value.json();
        if (j?.ok && Array.isArray(j.data)) {
          const incoming = j.data as AlertItem[];
          // 找到新预警 id（渐入动画）
          setAlerts((prev) => {
            const prevIds = new Set(prev.map((a) => a.id));
            const freshIds = incoming.filter((a) => !prevIds.has(a.id)).map((a) => a.id);
            if (freshIds.length > 0) {
              setNewAlertIds(new Set(freshIds));
              setTimeout(() => setNewAlertIds(new Set()), 2000);
            }
            return incoming;
          });
        } else {
          setAlerts([]);
        }
      } catch { setAlerts([]); }
    } else {
      setAlerts([]);
    }
    setDataLoading(false);

    setAsOf(nowHHMM());
  }, [selectedStore]);

  // 初始 + 门店切换时加载
  useEffect(() => { void fetchAll(); }, [fetchAll]);

  // 全屏切换
  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  };
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  // 倒计时回调（remaining=30 时触发刷新）
  const handleTick = useCallback((remaining: number) => {
    if (remaining === 30) void fetchAll();
  }, [fetchAll]);

  return (
    <ConfigProvider theme={{
      token: { colorPrimary: '#FF6B35', colorSuccess: '#0F6E56', colorWarning: '#BA7517', colorError: '#A32D2D' },
    }}>
      {/* 全局样式注入 */}
      <style>{`
        @keyframes hq-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.55; }
        }
        @keyframes hq-fadein {
          from { opacity: 0; transform: translateY(-6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        /* 排行榜暗色 Table 覆写 */
        .hq-rank-table .ant-table,
        .hq-rank-table .ant-table-thead > tr > th,
        .hq-rank-table .ant-table-tbody > tr > td,
        .hq-rank-table .ant-table-tbody > tr.ant-table-row:hover > td {
          background: transparent !important;
          color: ${T.text1};
          border-color: ${T.border} !important;
        }
        .hq-rank-table .ant-table-thead > tr > th {
          color: ${T.text2} !important;
          font-size: 11px;
        }
        .hq-rank-table .ant-table-tbody > tr > td {
          padding: 6px 8px;
        }
        .hq-dash-scroll::-webkit-scrollbar { width: 3px; }
        .hq-dash-scroll::-webkit-scrollbar-track { background: transparent; }
        .hq-dash-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 2px; }
      `}</style>

      <Spin spinning={dataLoading} tip="加载中..." style={{ color: '#FF6B35' }}>
      <div
        ref={containerRef}
        style={{
          minHeight: '100vh',
          background: T.bg0,
          color: T.text1,
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* ════════════════ 顶栏 60px ════════════════ */}
        <header style={{
          height: 60, flexShrink: 0,
          display: 'flex', alignItems: 'center', gap: 16,
          padding: '0 24px',
          background: T.bg1,
          borderBottom: `1px solid ${T.border}`,
        }}>
          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 8 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 6,
              background: T.brand,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 900, fontSize: 14, color: '#fff',
            }}>
              屯
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: T.brand, lineHeight: 1.2 }}>屯象OS</div>
              <div style={{ fontSize: 11, color: T.text2, lineHeight: 1.2 }}>集团驾驶舱</div>
            </div>
          </div>

          <div style={{ width: 1, height: 28, background: T.border }} />

          {/* 门店选择 */}
          <Select
            value={selectedStore || ''}
            onChange={(v) => setSelectedStore(v as string)}
            options={STORE_OPTIONS}
            style={{ width: 150 }}
            placeholder="全部门店"
          />

          {/* 数据截至 */}
          <span style={{ fontSize: 12, color: T.text2 }}>
            数据截至: <span style={{ color: T.text1, fontVariantNumeric: 'tabular-nums' }}>{asOf}</span>
          </span>

          {/* 右侧区域 */}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16 }}>
            <RealtimeClock />
            <CountdownBar onTick={handleTick} />
            <button
              onClick={toggleFullscreen}
              title={isFullscreen ? '退出全屏' : '进入全屏'}
              style={{
                background: 'rgba(255,255,255,0.08)',
                border: `1px solid ${T.border}`,
                borderRadius: 6, color: T.text2, cursor: 'pointer',
                padding: '4px 12px', fontSize: 12,
                display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              {isFullscreen ? '⛶ 退出全屏' : '⛶ 全屏'}
            </button>
          </div>
        </header>

        {/* ════════════════ 主内容区 ════════════════ */}
        <div style={{
          flex: 1, overflow: 'auto',
          display: 'grid',
          gridTemplateRows: '1fr 1fr',
          gridTemplateColumns: '300px 1fr 280px',
          gap: 12,
          padding: '12px 16px 16px',
          minHeight: 0,
        }}
          className="hq-dash-scroll"
        >
          {/* ── 左上：实时指标（RealtimeDashboard 组件）── */}
          <div style={{
            gridRow: '1', gridColumn: '1',
            background: T.bg1, borderRadius: 8,
            border: `1px solid ${T.border}`,
            padding: '14px 12px',
            overflow: 'hidden',
          }}>
            <div style={{
              fontSize: 13, fontWeight: 600, color: T.text1, marginBottom: 12,
            }}>
              实时经营指标
            </div>
            <div style={{
              /* 在暗色背景里嵌入 RealtimeDashboard，需要覆写其内部白色字 */
            }}>
              <style>{`
                /* RealtimeDashboard 暗色适配 */
                .hq-rt-wrap .ant-statistic-card { background: ${T.bg2} !important; border-color: ${T.border} !important; }
                .hq-rt-wrap .ant-statistic-content-value { color: ${T.text1}; }
                .hq-rt-wrap .ant-typography { color: ${T.text2} !important; }
                .hq-rt-wrap .ant-statistic-card-meta-title { color: ${T.text2} !important; }
              `}</style>
              <div className="hq-rt-wrap">
                <RealtimeDashboard storeId={selectedStore || undefined} compact={false} />
              </div>
            </div>
          </div>

          {/* ── 中上：营收趋势折线图 ── */}
          <Card
            title="今日营收趋势"
            extra={`今日 vs 昨日 vs 上周同日`}
            style={{ gridRow: '1', gridColumn: '2' }}
          >
            <RevenueTrendChart data={hourlyData} currentHour={currentHour} />
          </Card>

          {/* ── 右上：门店排行榜 ── */}
          <Card
            title="门店营收排行"
            extra={`今日 TOP ${rankingData.length}`}
            style={{ gridRow: '1', gridColumn: '3', overflowY: 'auto' }}
          >
            <StoreRankingTable data={rankingData} />
          </Card>

          {/* ── 左下：菜品热销 TOP10 ── */}
          <Card
            title="菜品热销 TOP10"
            extra="今日销量"
            style={{ gridRow: '2', gridColumn: '1' }}
          >
            <TopDishes data={topDishes} />
          </Card>

          {/* ── 中下 + 右下：Agent 预警区（跨2列）── */}
          <div style={{
            gridRow: '2', gridColumn: '2 / 4',
            background: T.bg1, borderRadius: 8,
            border: `1px solid ${T.border}`,
            padding: '14px 16px',
            display: 'flex', flexDirection: 'column',
            overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: 12, flexShrink: 0,
            }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: T.text1 }}>
                Agent 预警中心
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                {alerts.filter((a) => a.level === 'error').length > 0 && (
                  <span style={{
                    fontSize: 10, padding: '2px 7px', borderRadius: 10,
                    background: 'rgba(163,45,45,0.3)', color: '#ff6b6b',
                    animation: 'hq-pulse 1.5s infinite',
                  }}>
                    {alerts.filter((a) => a.level === 'error').length} 严重
                  </span>
                )}
                {alerts.filter((a) => a.level === 'warning').length > 0 && (
                  <span style={{
                    fontSize: 10, padding: '2px 7px', borderRadius: 10,
                    background: 'rgba(186,117,23,0.25)', color: '#f0a040',
                  }}>
                    {alerts.filter((a) => a.level === 'warning').length} 警告
                  </span>
                )}
                {alerts.length === 0 && (
                  <span style={{ fontSize: 11, color: T.success }}>全部正常</span>
                )}
              </div>
            </div>
            <div className="hq-dash-scroll" style={{ flex: 1, overflowY: 'auto' }}>
              <AlertPanel
                alerts={alerts}
                isNewAlert={(id) => newAlertIds.has(id)}
              />
            </div>
          </div>
        </div>
      </div>
      </Spin>
    </ConfigProvider>
  );
}

export default HQDashboardPage;
