/**
 * 经营驾驶舱 — 品牌总部大屏（1920×1080 全屏优先）
 * 域G: 经营分析
 *
 * 布局: CSS Grid 全屏
 * 图表: 纯CSS/SVG（禁止echarts/d3/recharts）
 * 刷新: 30秒自动刷新
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { Select, DatePicker, Spin } from 'antd';
import dayjs, { Dayjs } from 'dayjs';
import { useNavigate } from 'react-router-dom';

// ─── 类型定义 ────────────────────────────────────────────────────
interface OverviewData {
  total_revenue: number;
  revenue_change: number;     // 环比变化 %
  total_orders: number;
  orders_change: number;
  avg_turnover_rate: number;  // 翻台率 %
  turnover_change: number;
  avg_spend_per_customer: number; // 客单价
  spend_change: number;
  online_stores: number;
  total_stores: number;
}

interface StoreRanking {
  store_id: string;
  store_name: string;
  revenue: number;
}

interface CategorySales {
  category: string;
  amount: number;
  percentage: number;
}

interface Alert {
  id: string;
  level: 'critical' | 'warn' | 'info';
  store_name: string;
  content: string;
  created_at: string;
}

// ─── 空状态常量（仅用于类型安全的空数组/对象，不用于渲染） ────────────────────
const EMPTY_OVERVIEW: OverviewData = {
  total_revenue: 0,
  revenue_change: 0,
  total_orders: 0,
  orders_change: 0,
  avg_turnover_rate: 0,
  turnover_change: 0,
  avg_spend_per_customer: 0,
  spend_change: 0,
  online_stores: 0,
  total_stores: 0,
};

// 品牌列表
const BRAND_OPTIONS = [
  { value: 'all', label: '全部品牌' },
  { value: 'brand_1', label: '尝在一起' },
  { value: 'brand_2', label: '最黔线' },
  { value: 'brand_3', label: '尚宫厨' },
];

// 图表颜色序列
const CHART_COLORS = ['#FF6B35', '#0F6E56', '#1B6DAB', '#8B6914', '#6B3A8B'];

// ─── 工具函数 ─────────────────────────────────────────────────────
function formatRevenue(val: number): string {
  return (val / 10000).toFixed(2);
}

function formatChange(val: number): { label: string; up: boolean } {
  const abs = Math.abs(val).toFixed(1);
  return { label: `${abs}%`, up: val >= 0 };
}

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('tx_token');
  const tenantId = localStorage.getItem('tx_tenant_id') || '';
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
  };
}

// ─── 子组件：实时时钟 ─────────────────────────────────────────────
function RealtimeClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    <span style={{
      fontVariantNumeric: 'tabular-nums',
      fontSize: 15,
      color: '#B0B8C0',
      letterSpacing: '0.04em',
    }}>
      {now.getFullYear()}-{pad(now.getMonth() + 1)}-{pad(now.getDate())}
      &nbsp;
      {pad(now.getHours())}:{pad(now.getMinutes())}:{pad(now.getSeconds())}
    </span>
  );
}

// ─── 子组件：KPI 指标卡 ───────────────────────────────────────────
interface KPICardProps {
  title: string;
  value: string;
  unit?: string;
  change?: number;
  extra?: string; // 额外说明（在线门店用）
}

function KPICard({ title, value, unit, change, extra }: KPICardProps) {
  const ch = change != null ? formatChange(change) : null;
  return (
    <div style={{
      background: '#1E2A3A',
      borderRadius: 8,
      padding: '18px 20px',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      minHeight: 100,
      border: '1px solid rgba(255,255,255,0.06)',
    }}>
      <div style={{ fontSize: 13, color: '#B0B8C0', marginBottom: 8 }}>{title}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span style={{
          fontSize: 32,
          fontWeight: 700,
          color: '#FF6B35',
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1,
        }}>
          {value}
        </span>
        {unit && <span style={{ fontSize: 14, color: '#B0B8C0' }}>{unit}</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
        {ch && (
          <span style={{
            fontSize: 12,
            color: ch.up ? '#0F6E56' : '#A32D2D',
            display: 'flex',
            alignItems: 'center',
            gap: 2,
          }}>
            <span style={{ fontSize: 14 }}>{ch.up ? '↑' : '↓'}</span>
            {ch.label}
          </span>
        )}
        {extra && <span style={{ fontSize: 12, color: '#B0B8C0' }}>{extra}</span>}
      </div>
    </div>
  );
}

// ─── 子组件：门店营收排行（纯CSS柱状图）───────────────────────────
interface StoreRankingChartProps {
  data: StoreRanking[];
}

function StoreRankingChart({ data }: StoreRankingChartProps) {
  const navigate = useNavigate();
  const maxRevenue = data.length > 0 ? Math.max(...data.map((s) => s.revenue)) : 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {data.map((store, idx) => {
        const pct = (store.revenue / maxRevenue) * 100;
        const isChamp = idx === 0;
        return (
          <div
            key={store.store_id}
            onClick={() => navigate(`/analytics/store-detail?store_id=${store.store_id}`)}
            style={{
              display: 'grid',
              gridTemplateColumns: '120px 1fr 90px',
              alignItems: 'center',
              gap: 10,
              cursor: 'pointer',
              padding: '4px 6px',
              borderRadius: 4,
              transition: 'background 0.15s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.04)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            {/* 排名 + 门店名 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                fontSize: 11,
                width: 18,
                height: 18,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: 3,
                background: isChamp ? '#FF6B35' : '#1E2A3A',
                color: isChamp ? '#fff' : '#B0B8C0',
                fontWeight: 700,
                flexShrink: 0,
              }}>
                {idx + 1}
              </span>
              <span style={{
                fontSize: 12,
                color: '#E0E0E0',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                maxWidth: 86,
              }}>
                {store.store_name.length > 8 ? store.store_name.slice(0, 8) : store.store_name}
              </span>
            </div>

            {/* 进度条 */}
            <div style={{
              height: 16,
              background: 'rgba(255,255,255,0.06)',
              borderRadius: 3,
              overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${pct}%`,
                background: isChamp
                  ? 'linear-gradient(90deg, #FF6B35, #FF8555)'
                  : '#374151',
                borderRadius: 3,
                transition: 'width 0.6s ease',
              }} />
            </div>

            {/* 金额 */}
            <div style={{
              fontSize: 12,
              color: isChamp ? '#FF6B35' : '#B0B8C0',
              textAlign: 'right',
              fontVariantNumeric: 'tabular-nums',
              fontWeight: isChamp ? 700 : 400,
            }}>
              ¥{store.revenue.toLocaleString()}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 子组件：品类销售占比（SVG 环形图）────────────────────────────
interface CategoryPieChartProps {
  data: CategorySales[];
}

function CategoryPieChart({ data }: CategoryPieChartProps) {
  const size = 160;
  const cx = size / 2;
  const cy = size / 2;
  const r = 58;
  const strokeWidth = 22;
  const circumference = 2 * Math.PI * r;

  // 计算每个分段的 stroke-dasharray / stroke-dashoffset
  let offset = 0;
  const segments = data.map((item, idx) => {
    const dash = (item.percentage / 100) * circumference;
    const gap = circumference - dash;
    const segment = { ...item, dash, gap, offset, color: CHART_COLORS[idx] };
    offset += dash;
    return segment;
  });

  const topCategory = data[0];

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
      {/* SVG 环形图 */}
      <div style={{ position: 'relative', flexShrink: 0 }}>
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
          {/* 背景圆 */}
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={strokeWidth}
          />
          {segments.map((seg) => (
            <circle
              key={seg.category}
              cx={cx} cy={cy} r={r}
              fill="none"
              stroke={seg.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${seg.dash} ${seg.gap}`}
              strokeDashoffset={-seg.offset}
              strokeLinecap="round"
            />
          ))}
        </svg>
        {/* 中心文字 */}
        {topCategory && (
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
            pointerEvents: 'none',
          }}>
            <div style={{ fontSize: 11, color: '#B0B8C0', whiteSpace: 'nowrap' }}>最高</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#FF6B35', whiteSpace: 'nowrap' }}>
              {topCategory.category}
            </div>
            <div style={{ fontSize: 12, color: '#E0E0E0' }}>{topCategory.percentage}%</div>
          </div>
        )}
      </div>

      {/* 图例 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1 }}>
        {data.map((item, idx) => (
          <div key={item.category} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              width: 10,
              height: 10,
              borderRadius: 2,
              background: CHART_COLORS[idx],
              flexShrink: 0,
            }} />
            <span style={{ fontSize: 12, color: '#E0E0E0', flex: 1 }}>{item.category}</span>
            <span style={{
              fontSize: 12,
              color: '#B0B8C0',
              fontVariantNumeric: 'tabular-nums',
              marginLeft: 'auto',
            }}>
              {item.percentage}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 子组件：AI 预警列表 ──────────────────────────────────────────
interface AlertListProps {
  alerts: Alert[];
}

function AlertList({ alerts }: AlertListProps) {
  const levelColor: Record<Alert['level'], string> = {
    critical: '#A32D2D',
    warn: '#BA7517',
    info: 'transparent',
  };
  const levelBg: Record<Alert['level'], string> = {
    critical: 'rgba(163,45,45,0.15)',
    warn: 'rgba(186,117,23,0.12)',
    info: 'transparent',
  };
  const levelIcon: Record<Alert['level'], string> = {
    critical: '🔴',
    warn: '🟡',
    info: '🟢',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {alerts.map((alert) => (
        <div
          key={alert.id}
          style={{
            background: levelBg[alert.level],
            borderLeft: `3px solid ${levelColor[alert.level]}`,
            borderRadius: '0 6px 6px 0',
            padding: '8px 10px',
            animation: alert.level === 'critical' ? 'pulse 1.5s infinite' : 'none',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
            <span style={{ fontSize: 12 }}>{levelIcon[alert.level]}</span>
            <span style={{
              fontSize: 12,
              fontWeight: 600,
              color: '#E0E0E0',
              flex: 1,
            }}>
              {alert.store_name}
            </span>
            <span style={{ fontSize: 10, color: '#B0B8C0' }}>{alert.created_at}</span>
          </div>
          <div style={{ fontSize: 11, color: '#B0B8C0', lineHeight: 1.5, paddingLeft: 18 }}>
            {alert.content}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────
export function AnalyticsDashboardPage() {
  const [selectedBrand, setSelectedBrand] = useState<string>('all');
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [overview, setOverview] = useState<OverviewData>(EMPTY_OVERVIEW);
  const [ranking, setRanking] = useState<StoreRanking[]>([]);
  const [categorySales, setCategorySales] = useState<CategorySales[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());

  const containerRef = useRef<HTMLDivElement>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const dateStr = selectedDate.format('YYYY-MM-DD');
    const headers = getAuthHeaders();

    // 并发请求，失败时保留空状态
    const [overviewRes, rankingRes, categoryRes, alertsRes] = await Promise.allSettled([
      fetch(`/api/v1/analytics/overview?date=${dateStr}&brand_id=${selectedBrand}`, { headers }),
      fetch(`/api/v1/analytics/store-ranking?date=${dateStr}&limit=10`, { headers }),
      fetch(`/api/v1/analytics/category-sales?date=${dateStr}`, { headers }),
      fetch('/api/v1/brain/alerts', { headers }),
    ]);

    if (overviewRes.status === 'fulfilled' && overviewRes.value.ok) {
      try {
        const json = await overviewRes.value.json();
        if (json?.ok && json.data) setOverview(json.data);
        else setOverview(EMPTY_OVERVIEW);
      } catch { setOverview(EMPTY_OVERVIEW); }
    } else {
      setOverview(EMPTY_OVERVIEW);
    }

    if (rankingRes.status === 'fulfilled' && rankingRes.value.ok) {
      try {
        const json = await rankingRes.value.json();
        if (json?.ok && Array.isArray(json.data)) setRanking(json.data);
        else setRanking([]);
      } catch { setRanking([]); }
    } else {
      setRanking([]);
    }

    if (categoryRes.status === 'fulfilled' && categoryRes.value.ok) {
      try {
        const json = await categoryRes.value.json();
        if (json?.ok && Array.isArray(json.data)) setCategorySales(json.data);
        else setCategorySales([]);
      } catch { setCategorySales([]); }
    } else {
      setCategorySales([]);
    }

    if (alertsRes.status === 'fulfilled' && alertsRes.value.ok) {
      try {
        const json = await alertsRes.value.json();
        if (json?.ok && Array.isArray(json.data)) setAlerts(json.data);
        else setAlerts([]);
      } catch { setAlerts([]); }
    } else {
      setAlerts([]);
    }

    setLastRefreshed(new Date());
    setLoading(false);
  }, [selectedBrand, selectedDate]);

  // 初始加载
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 30秒自动刷新
  useEffect(() => {
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // 全屏切换
  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen?.();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.();
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  return (
    <>
      {/* 全局样式注入 */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
        .dashboard-scroll::-webkit-scrollbar {
          width: 4px;
        }
        .dashboard-scroll::-webkit-scrollbar-track {
          background: transparent;
        }
        .dashboard-scroll::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.15);
          border-radius: 2px;
        }
      `}</style>

      <Spin spinning={loading} tip="加载中..." style={{ color: '#FF6B35' }}>
      <div
        ref={containerRef}
        style={{
          display: 'grid',
          gridTemplateRows: '64px 120px 1fr',
          gridTemplateColumns: '1fr 320px',
          height: '100%',
          minHeight: '100vh',
          background: '#0B1A20',
          color: '#E0E0E0',
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
          overflow: 'hidden',
        }}
      >
        {/* ──────── 顶部导航栏 ──────── */}
        <div style={{
          gridColumn: '1 / -1',
          gridRow: '1',
          display: 'flex',
          alignItems: 'center',
          padding: '0 24px',
          background: '#0B1A20',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          gap: 16,
        }}>
          {/* Logo + 标题 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 16 }}>
            <div style={{
              width: 32, height: 32,
              background: '#FF6B35',
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 900,
              fontSize: 14,
              color: '#fff',
            }}>
              屯
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#E0E0E0', lineHeight: 1.2 }}>屯象OS</div>
              <div style={{ fontSize: 11, color: '#B0B8C0', lineHeight: 1.2 }}>经营驾驶舱</div>
            </div>
          </div>

          {/* 分隔线 */}
          <div style={{ width: 1, height: 28, background: 'rgba(255,255,255,0.1)' }} />

          {/* 品牌选择 */}
          <Select
            value={selectedBrand}
            onChange={setSelectedBrand}
            options={BRAND_OPTIONS}
            style={{ width: 140 }}
            styles={{
              popup: {
                root: { background: '#1E2A3A' }
              }
            }}
          />

          {/* 日期选择 */}
          <DatePicker
            value={selectedDate}
            onChange={(d) => d && setSelectedDate(d)}
            allowClear={false}
            style={{ width: 140 }}
          />

          {/* 刷新指示 */}
          <span style={{ fontSize: 11, color: '#B0B8C0' }}>
            上次刷新: {lastRefreshed.getHours().toString().padStart(2, '0')}:
            {lastRefreshed.getMinutes().toString().padStart(2, '0')}:
            {lastRefreshed.getSeconds().toString().padStart(2, '0')}
          </span>

          {/* 右侧：时钟 + 全屏 */}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16 }}>
            <RealtimeClock />
            <button
              onClick={toggleFullscreen}
              title={isFullscreen ? '退出全屏' : '全屏'}
              style={{
                background: 'rgba(255,255,255,0.08)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 6,
                color: '#B0B8C0',
                cursor: 'pointer',
                padding: '4px 10px',
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              {isFullscreen ? '⛶' : '⛶'} {isFullscreen ? '退出全屏' : '全屏'}
            </button>
          </div>
        </div>

        {/* ──────── KPI 横排（5个指标卡）──────── */}
        <div style={{
          gridColumn: '1 / -1',
          gridRow: '2',
          display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)',
          gap: 12,
          padding: '12px 24px',
          alignItems: 'stretch',
        }}>
          <KPICard
            title="今日总营收"
            value={formatRevenue(overview.total_revenue)}
            unit="万元"
            change={overview.revenue_change}
          />
          <KPICard
            title="今日订单数"
            value={overview.total_orders.toLocaleString()}
            unit="单"
            change={overview.orders_change}
          />
          <KPICard
            title="平均翻台率"
            value={overview.avg_turnover_rate.toFixed(1)}
            unit="次/天"
            change={overview.turnover_change}
          />
          <KPICard
            title="平均客单价"
            value={`¥${overview.avg_spend_per_customer.toFixed(0)}`}
            change={overview.spend_change}
          />
          <KPICard
            title="在线门店"
            value={`${overview.online_stores}/${overview.total_stores}`}
            unit="家"
            extra={`${Math.round((overview.online_stores / overview.total_stores) * 100)}% 在线率`}
          />
        </div>

        {/* ──────── 主图表区（左侧）──────── */}
        <div style={{
          gridColumn: '1',
          gridRow: '3',
          display: 'grid',
          gridTemplateRows: '1fr 1fr',
          gap: 12,
          padding: '0 12px 16px 24px',
          overflow: 'hidden',
        }}>
          {/* 门店营收排行 */}
          <div style={{
            background: '#1E2A3A',
            borderRadius: 8,
            padding: '16px 20px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            border: '1px solid rgba(255,255,255,0.06)',
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 12,
            }}>
              <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#E0E0E0' }}>
                门店营收排行
              </h3>
              <span style={{ fontSize: 11, color: '#B0B8C0' }}>
                今日 TOP {ranking.length}
              </span>
            </div>
            <div
              className="dashboard-scroll"
              style={{ flex: 1, overflow: 'auto' }}
            >
              <StoreRankingChart data={ranking} />
            </div>
          </div>

          {/* 品类销售占比 */}
          <div style={{
            background: '#1E2A3A',
            borderRadius: 8,
            padding: '16px 20px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            border: '1px solid rgba(255,255,255,0.06)',
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 12,
            }}>
              <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#E0E0E0' }}>
                品类销售占比
              </h3>
              <span style={{ fontSize: 11, color: '#B0B8C0' }}>今日</span>
            </div>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
              <CategoryPieChart data={categorySales} />
            </div>
          </div>
        </div>

        {/* ──────── AI 预警中心（右侧）──────── */}
        <div style={{
          gridColumn: '2',
          gridRow: '3',
          background: '#1E2A3A',
          borderRadius: 8,
          margin: '0 24px 16px 0',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          border: '1px solid rgba(255,255,255,0.06)',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 12,
            flexShrink: 0,
          }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#E0E0E0' }}>
              AI 预警中心
            </h3>
            {/* 预警数量徽章 */}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              {alerts.filter((a) => a.level === 'critical').length > 0 && (
                <span style={{
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 10,
                  background: 'rgba(163,45,45,0.3)',
                  color: '#ff6b6b',
                  animation: 'pulse 1.5s infinite',
                }}>
                  {alerts.filter((a) => a.level === 'critical').length} 严重
                </span>
              )}
              {alerts.filter((a) => a.level === 'warn').length > 0 && (
                <span style={{
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 10,
                  background: 'rgba(186,117,23,0.25)',
                  color: '#f0a040',
                }}>
                  {alerts.filter((a) => a.level === 'warn').length} 警告
                </span>
              )}
            </div>
          </div>

          {/* 预警列表可滚动 */}
          <div
            className="dashboard-scroll"
            style={{ flex: 1, overflow: 'auto' }}
          >
            <AlertList alerts={alerts} />
          </div>
        </div>
      </div>
      </Spin>
    </>
  );
}
