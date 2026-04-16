/**
 * P&L 利润报表页面
 * 域E：财务结算 — 月度损益可视化
 *
 * 功能：
 *   1. 顶部筛选栏（年份 + 月份 + 对比月份）
 *   2. 月度汇总指标卡片（营收/食材成本/人力成本/毛利）
 *   3. 每日趋势折线图（纯SVG，无第三方图表库）
 *   4. 多月对比 ProTable
 *   5. 预算执行情况（纯CSS进度条）
 *
 * API:
 *   GET /api/v1/finance/pnl/monthly-summary?store_id=&year=&month=
 *   GET /api/v1/finance/pnl/daily?store_id=&year=&month=
 *   GET /api/v1/finance/pnl/compare?store_id=&year=&months=1,2,...
 *   GET /api/v1/finance/budget/execution?store_id=&year=&month=
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Select,
  Button,
  Statistic,
  Row,
  Col,
  Space,
  Tag,
  Spin,
  Alert,
  Progress,
  ConfigProvider,
  Typography,
  Divider,
} from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  ReloadOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { txFetchData, getTenantId, getToken } from '../../api';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;

// ─── 主题 ────────────────────────────────────────────────────────────────────

const TX_THEME = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
};

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface MonthlySummary {
  period: string;
  store_id: string;
  _is_mock?: boolean;
  revenue: {
    dine_in_fen: number;
    takeaway_fen: number;
    retail_fen: number;
    total_fen: number;
  };
  cogs: {
    food_cost_fen: number;
    labor_cost_fen: number;
    total_fen: number;
  };
  gross_profit_fen: number;
  gross_margin_rate: number;
  operating_expenses_fen: number;
  net_profit_fen: number;
  net_margin_rate: number;
  avg_daily_revenue_fen: number;
  best_day: { date: string | null; revenue_fen: number };
  worst_day: { date: string | null; revenue_fen: number };
}

interface DailyItem {
  date: string;
  net_revenue_fen: number;
  food_cost_fen: number | null;
  labor_cost_fen: number | null;
  gross_profit_fen: number | null;
  gross_margin_pct: number | null;
  orders_count: number;
}

interface CompareItem {
  period: string;
  _is_mock?: boolean;
  revenue: { total_fen: number };
  cogs: { food_cost_fen: number; labor_cost_fen: number; total_fen: number };
  gross_profit_fen: number;
  gross_margin_rate: number;
  operating_expenses_fen: number;
  net_profit_fen: number;
  net_margin_rate: number;
}

interface BudgetExecution {
  period: string;
  _is_mock?: boolean;
  has_budget: boolean;
  budget: {
    revenue_target_fen: number;
    cost_budget_fen: number;
    labor_budget_fen: number;
  };
  actual: {
    revenue_fen: number;
    food_cost_fen: number;
    labor_cost_fen: number;
  };
  variance: {
    revenue_over_budget: boolean;
    cost_over_budget: boolean;
    labor_over_budget: boolean;
  };
  execution_rate: number;
  execution_status: 'on_track' | 'below_target' | 'critical';
}

// ─── Demo 门店 ID（从 localStorage 或 fallback）─────────────────────────────

const DEMO_STORE_ID = '00000000-0000-0000-0000-000000000001';

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function fenToWan(fen: number): string {
  return ((fen / 100) / 10000).toFixed(2);
}

function pctDisplay(rate: number): string {
  return (rate * 100).toFixed(1) + '%';
}

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('tx_token') || '';
  const tenantId = localStorage.getItem('tx_tenant_id') || 'demo-tenant';
  return {
    'Content-Type': 'application/json',
    'X-Tenant-ID': tenantId,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

// ─── 年份 / 月份选项 ──────────────────────────────────────────────────────────

const currentYear = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: 5 }, (_, i) => ({
  value: currentYear - i,
  label: `${currentYear - i}年`,
}));
const MONTH_OPTIONS = Array.from({ length: 12 }, (_, i) => ({
  value: i + 1,
  label: `${i + 1}月`,
}));

// ─── 子组件：纯SVG折线图 ──────────────────────────────────────────────────────

interface LineChartProps {
  data: DailyItem[];
  loading: boolean;
}

function DailyTrendChart({ data, loading }: LineChartProps) {
  if (loading) {
    return (
      <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (!data.length) {
    return (
      <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#B4B2A9' }}>
        暂无每日数据
      </div>
    );
  }

  const WIDTH = 800;
  const HEIGHT = 300;
  const PAD_L = 60;
  const PAD_R = 20;
  const PAD_T = 20;
  const PAD_B = 40;
  const CHART_W = WIDTH - PAD_L - PAD_R;
  const CHART_H = HEIGHT - PAD_T - PAD_B;

  const maxRev = Math.max(...data.map((d) => d.net_revenue_fen), 1);
  const maxProfit = Math.max(...data.map((d) => d.gross_profit_fen ?? 0), 1);
  const maxFood = Math.max(...data.map((d) => d.food_cost_fen ?? 0), 1);
  const globalMax = Math.max(maxRev, maxProfit, maxFood, 1);

  const toX = (i: number) =>
    PAD_L + (data.length <= 1 ? CHART_W / 2 : (i / (data.length - 1)) * CHART_W);
  const toY = (val: number) => PAD_T + CHART_H - (val / globalMax) * CHART_H;

  const revPoints = data.map((d, i) => `${toX(i)},${toY(d.net_revenue_fen)}`).join(' ');
  const foodPoints = data
    .map((d, i) => `${toX(i)},${toY(d.food_cost_fen ?? 0)}`)
    .join(' ');
  const profitPoints = data
    .map((d, i) => `${toX(i)},${toY(d.gross_profit_fen ?? 0)}`)
    .join(' ');

  // Y轴刻度（4档）
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((r) => ({
    y: PAD_T + CHART_H - r * CHART_H,
    label: `¥${((globalMax * r) / 100).toFixed(0)}`,
  }));

  // X轴刻度（每5天一个标签）
  const xTicks = data
    .map((d, i) => ({ i, label: d.date.slice(8) }))
    .filter((_, i) => i % 5 === 0 || i === data.length - 1);

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ width: '100%', minWidth: 600 }}>
        {/* 网格线 */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD_L} y1={t.y} x2={WIDTH - PAD_R} y2={t.y}
              stroke="#E8E6E1" strokeWidth="1"
            />
            <text x={PAD_L - 6} y={t.y + 4} textAnchor="end" fontSize="11" fill="#B4B2A9">
              {t.label}
            </text>
          </g>
        ))}

        {/* X轴标签 */}
        {xTicks.map((t) => (
          <text
            key={t.i}
            x={toX(t.i)} y={HEIGHT - 8}
            textAnchor="middle" fontSize="11" fill="#B4B2A9"
          >
            {t.label}日
          </text>
        ))}

        {/* 营收折线（橙色）*/}
        <polyline
          points={revPoints}
          fill="none"
          stroke="#FF6B35"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />

        {/* 食材成本折线（蓝色）*/}
        <polyline
          points={foodPoints}
          fill="none"
          stroke="#185FA5"
          strokeWidth="2"
          strokeLinejoin="round"
        />

        {/* 毛利折线（绿色）*/}
        <polyline
          points={profitPoints}
          fill="none"
          stroke="#0F6E56"
          strokeWidth="2"
          strokeLinejoin="round"
        />

        {/* 数据点（带tooltip）*/}
        {data.map((d, i) => (
          <g key={i}>
            <circle
              cx={toX(i)} cy={toY(d.net_revenue_fen)}
              r="4" fill="#FF6B35"
              style={{ cursor: 'pointer' }}
            >
              <title>
                {d.date}{'\n'}
                营收：¥{fenToYuan(d.net_revenue_fen)}{'\n'}
                食材：¥{fenToYuan(d.food_cost_fen ?? 0)}{'\n'}
                毛利：¥{fenToYuan(d.gross_profit_fen ?? 0)}{'\n'}
                订单：{d.orders_count}单
              </title>
            </circle>
            {d.gross_profit_fen !== null && (
              <circle
                cx={toX(i)} cy={toY(d.gross_profit_fen)}
                r="3" fill="#0F6E56"
                style={{ cursor: 'pointer' }}
              >
                <title>
                  {d.date}{'\n'}
                  毛利：¥{fenToYuan(d.gross_profit_fen)}
                </title>
              </circle>
            )}
          </g>
        ))}

        {/* 图例 */}
        <g transform={`translate(${PAD_L}, ${PAD_T - 5})`}>
          <rect x="0" y="-8" width="12" height="3" fill="#FF6B35" rx="1" />
          <text x="16" y="0" fontSize="11" fill="#5F5E5A">营收</text>
          <rect x="52" y="-8" width="12" height="3" fill="#185FA5" rx="1" />
          <text x="68" y="0" fontSize="11" fill="#5F5E5A">食材成本</text>
          <rect x="124" y="-8" width="12" height="3" fill="#0F6E56" rx="1" />
          <text x="140" y="0" fontSize="11" fill="#5F5E5A">毛利</text>
        </g>
      </svg>
    </div>
  );
}

// ─── 子组件：预算执行进度条 ───────────────────────────────────────────────────

interface BudgetRowProps {
  label: string;
  targetFen: number;
  actualFen: number;
  overBudget: boolean;
}

function BudgetRow({ label, targetFen, actualFen, overBudget }: BudgetRowProps) {
  const rate = targetFen > 0 ? Math.min((actualFen / targetFen) * 100, 150) : 0;
  const displayRate = targetFen > 0 ? ((actualFen / targetFen) * 100).toFixed(1) : '0.0';
  const barColor = overBudget ? '#A32D2D' : rate >= 90 ? '#0F6E56' : '#BA7517';

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <Text style={{ fontSize: 13, color: '#5F5E5A' }}>{label}</Text>
        <Space size={16}>
          <Text style={{ fontSize: 12, color: '#B4B2A9' }}>
            目标：¥{fenToWan(targetFen)}万
          </Text>
          <Text style={{ fontSize: 12, color: '#2C2C2A', fontWeight: 600 }}>
            实际：¥{fenToWan(actualFen)}万
          </Text>
          <Text
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: overBudget ? '#A32D2D' : rate >= 90 ? '#0F6E56' : '#BA7517',
            }}
          >
            {displayRate}%
          </Text>
        </Space>
      </div>
      <div
        style={{
          height: 8,
          background: '#F0EDE6',
          borderRadius: 4,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${Math.min(rate, 100)}%`,
            background: barColor,
            borderRadius: 4,
            transition: 'width 0.6s ease',
          }}
        />
      </div>
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export default function PnLReportPage() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [loading, setLoading] = useState(false);

  const [summary, setSummary] = useState<MonthlySummary | null>(null);
  const [dailyItems, setDailyItems] = useState<DailyItem[]>([]);
  const [compareItems, setCompareItems] = useState<CompareItem[]>([]);
  const [budgetExec, setBudgetExec] = useState<BudgetExecution | null>(null);
  const [dailyLoading, setDailyLoading] = useState(false);

  // 获取近6个月的月份列表
  const getRecentMonths = useCallback(() => {
    const months: number[] = [];
    for (let i = 5; i >= 0; i--) {
      const d = new Date(year, month - 1 - i, 1);
      if (d.getFullYear() === year) {
        months.push(d.getMonth() + 1);
      }
    }
    // 确保当前月在列表中
    if (!months.includes(month)) months.push(month);
    return months;
  }, [year, month]);

  // 获取门店 ID（从 localStorage 或使用 demo）
  const getStoreId = () => {
    try {
      const raw = localStorage.getItem('tx_user');
      if (raw) {
        const u = JSON.parse(raw);
        if (u.store_id) return u.store_id;
      }
    } catch { /* ignore */ }
    return DEMO_STORE_ID;
  };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setDailyLoading(true);
    const storeId = getStoreId();
    const start = `${year}-${String(month).padStart(2, '0')}-01`;
    const endDay = new Date(year, month, 0).getDate();
    const end = `${year}-${String(month).padStart(2, '0')}-${String(endDay).padStart(2, '0')}`;
    const recentMonths = getRecentMonths();

    // 1. P&L 报表（月度汇总 + 每日明细）
    try {
      const data = await txFetchData<MonthlySummary & { daily_items?: DailyItem[] }>(
        `/api/v1/analytics/pl-report?store_id=${storeId}&start=${start}&end=${end}`,
      );
      setSummary(data);
      if (data.daily_items) {
        setDailyItems(data.daily_items);
      }
    } catch {
      setSummary(null);
      setDailyItems([]);
    } finally {
      setDailyLoading(false);
    }

    // 2. 多月对比
    try {
      const compareStart = `${year}-${String(Math.min(...recentMonths)).padStart(2, '0')}-01`;
      const data = await txFetchData<{ items: CompareItem[] }>(
        `/api/v1/analytics/pl-report?store_id=${storeId}&start=${compareStart}&end=${end}&groupBy=month`,
      );
      if (data.items) {
        setCompareItems(data.items);
      } else {
        setCompareItems([]);
      }
    } catch {
      setCompareItems([]);
    }

    // 3. 预算执行
    try {
      const data = await txFetchData<BudgetExecution>(
        `/api/v1/analytics/pl-report/budget?store_id=${storeId}&year=${year}&month=${month}`,
      );
      setBudgetExec(data);
    } catch {
      setBudgetExec(null);
    }

    setLoading(false);
  }, [year, month, getRecentMonths]);

  // CSV 导出（触发浏览器下载）
  const handleExportCSV = useCallback(async () => {
    const storeId = getStoreId();
    const start = `${year}-${String(month).padStart(2, '0')}-01`;
    const endDay = new Date(year, month, 0).getDate();
    const end = `${year}-${String(month).padStart(2, '0')}-${String(endDay).padStart(2, '0')}`;
    try {
      const token = getToken();
      const tenantId = getTenantId();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      if (tenantId) headers['X-Tenant-ID'] = tenantId;
      const url = `/api/v1/analytics/pl-report/export?format=csv&store_id=${storeId}&start=${start}&end=${end}`;
      const res = await fetch(url, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `pl-report-${year}-${month}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href);
    } catch (err) {
      console.error('[PnLReportPage] export error', err);
    }
  }, [year, month]);

  useEffect(() => {
    fetchAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 对比表格列定义
  const compareColumns: ProColumns<CompareItem>[] = [
    {
      title: '月份',
      dataIndex: 'period',
      width: 90,
      render: (val) => <Text strong>{String(val)}</Text>,
    },
    {
      title: '营收（万）',
      dataIndex: ['revenue', 'total_fen'],
      width: 110,
      render: (_, r) => (
        <Text style={{ color: '#FF6B35', fontWeight: 600 }}>
          ¥{fenToWan(r.revenue.total_fen)}
        </Text>
      ),
    },
    {
      title: '食材成本（万）',
      dataIndex: ['cogs', 'food_cost_fen'],
      width: 120,
      render: (_, r) => `¥${fenToWan(r.cogs.food_cost_fen)}`,
    },
    {
      title: '食材占比',
      dataIndex: 'food_pct',
      width: 100,
      render: (_, r) => {
        const pct = r.revenue.total_fen > 0 ? r.cogs.food_cost_fen / r.revenue.total_fen : 0;
        return (
          <Tag color={pct > 0.4 ? 'red' : pct > 0.32 ? 'orange' : 'green'}>
            {pctDisplay(pct)}
          </Tag>
        );
      },
    },
    {
      title: '人力成本（万）',
      dataIndex: ['cogs', 'labor_cost_fen'],
      width: 120,
      render: (_, r) => `¥${fenToWan(r.cogs.labor_cost_fen)}`,
    },
    {
      title: '人力占比',
      dataIndex: 'labor_pct',
      width: 100,
      render: (_, r) => {
        const pct = r.revenue.total_fen > 0 ? r.cogs.labor_cost_fen / r.revenue.total_fen : 0;
        return (
          <Tag color={pct > 0.35 ? 'red' : pct > 0.28 ? 'orange' : 'green'}>
            {pctDisplay(pct)}
          </Tag>
        );
      },
    },
    {
      title: '毛利（万）',
      dataIndex: 'gross_profit_fen',
      width: 110,
      render: (_, r) => (
        <Text
          style={{ color: r.gross_profit_fen < 0 ? '#A32D2D' : '#0F6E56', fontWeight: 600 }}
        >
          ¥{fenToWan(r.gross_profit_fen)}
        </Text>
      ),
    },
    {
      title: '毛利率',
      dataIndex: 'gross_margin_rate',
      width: 90,
      render: (_, r) => {
        const pct = r.gross_margin_rate * 100;
        let color: 'red' | 'orange' | 'green' = 'green';
        if (pct < 30) color = 'red';
        else if (pct < 50) color = 'orange';
        return <Tag color={color}>{pct.toFixed(1)}%</Tag>;
      },
    },
  ];

  // 毛利率颜色
  const grossMarginColor =
    summary && summary.gross_margin_rate * 100 < 30
      ? '#A32D2D'
      : '#0F6E56';

  return (
    <ConfigProvider theme={TX_THEME}>
      <div style={{ padding: '0 0 32px 0' }}>

        {/* ── 页头 ─────────────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
            P&amp;L 利润报表
          </Title>
          <Text style={{ color: '#B4B2A9', fontSize: 12 }}>
            月度损益汇总 · 每日趋势 · 多月对比 · 预算执行
          </Text>
        </div>

        {/* ── 筛选栏 ────────────────────────────────────────── */}
        <Card
          size="small"
          style={{ marginBottom: 16, background: '#F8F7F5' }}
          bodyStyle={{ padding: '12px 16px' }}
        >
          <Space wrap>
            <Text style={{ color: '#5F5E5A', fontSize: 13 }}>年份</Text>
            <Select
              value={year}
              onChange={setYear}
              options={YEAR_OPTIONS}
              style={{ width: 110 }}
            />
            <Text style={{ color: '#5F5E5A', fontSize: 13 }}>月份</Text>
            <Select
              value={month}
              onChange={setMonth}
              options={MONTH_OPTIONS}
              style={{ width: 90 }}
            />
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={fetchAll}
              loading={loading}
            >
              查询
            </Button>
            <Button
              icon={<DownloadOutlined />}
              onClick={handleExportCSV}
            >
              导出 CSV
            </Button>
          </Space>
        </Card>

        {/* ── 月度汇总指标卡片 ───────────────────────────────── */}
        <Spin spinning={loading}>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            {/* 营收卡片 */}
            <Col xs={24} sm={12} lg={6}>
              <Card size="small" style={{ height: '100%' }}>
                <Statistic
                  title="月度营收"
                  value={summary ? (summary.revenue.total_fen / 100 / 10000) : 0}
                  precision={2}
                  prefix="¥"
                  suffix="万"
                  valueStyle={{ color: '#FF6B35', fontWeight: 700 }}
                />
                <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Tag color="blue" style={{ fontSize: 11 }}>
                    堂食 ¥{summary ? fenToWan(summary.revenue.dine_in_fen) : '0.00'}万
                  </Tag>
                  <Tag color="cyan" style={{ fontSize: 11 }}>
                    外卖 ¥{summary ? fenToWan(summary.revenue.takeaway_fen) : '0.00'}万
                  </Tag>
                </div>
                {summary && (
                  <div style={{ marginTop: 6, fontSize: 12, color: '#B4B2A9' }}>
                    日均 ¥{fenToWan(summary.avg_daily_revenue_fen)}万
                  </div>
                )}
              </Card>
            </Col>

            {/* 食材成本卡片 */}
            <Col xs={24} sm={12} lg={6}>
              <Card size="small" style={{ height: '100%' }}>
                <Statistic
                  title="食材成本"
                  value={summary ? (summary.cogs.food_cost_fen / 100 / 10000) : 0}
                  precision={2}
                  prefix="¥"
                  suffix="万"
                  valueStyle={{ color: '#185FA5', fontWeight: 700 }}
                />
                {summary && summary.revenue.total_fen > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Tag
                      color={
                        summary.cogs.food_cost_fen / summary.revenue.total_fen > 0.4
                          ? 'red'
                          : 'green'
                      }
                    >
                      占营收{' '}
                      {pctDisplay(summary.cogs.food_cost_fen / summary.revenue.total_fen)}
                    </Tag>
                  </div>
                )}
              </Card>
            </Col>

            {/* 人力成本卡片 */}
            <Col xs={24} sm={12} lg={6}>
              <Card size="small" style={{ height: '100%' }}>
                <Statistic
                  title="人力成本"
                  value={summary ? (summary.cogs.labor_cost_fen / 100 / 10000) : 0}
                  precision={2}
                  prefix="¥"
                  suffix="万"
                  valueStyle={{ color: '#BA7517', fontWeight: 700 }}
                />
                {summary && summary.revenue.total_fen > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Tag
                      color={
                        summary.cogs.labor_cost_fen / summary.revenue.total_fen > 0.35
                          ? 'red'
                          : 'orange'
                      }
                    >
                      占营收{' '}
                      {pctDisplay(summary.cogs.labor_cost_fen / summary.revenue.total_fen)}
                    </Tag>
                  </div>
                )}
              </Card>
            </Col>

            {/* 毛利卡片 */}
            <Col xs={24} sm={12} lg={6}>
              <Card
                size="small"
                style={{
                  height: '100%',
                  borderColor:
                    summary && summary.gross_margin_rate * 100 < 30 ? '#A32D2D' : undefined,
                }}
              >
                <Statistic
                  title="毛利"
                  value={summary ? (summary.gross_profit_fen / 100 / 10000) : 0}
                  precision={2}
                  prefix="¥"
                  suffix="万"
                  valueStyle={{ color: grossMarginColor, fontWeight: 700 }}
                />
                {summary && (
                  <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Tag
                      color={
                        summary.gross_margin_rate * 100 < 30
                          ? 'red'
                          : summary.gross_margin_rate * 100 < 50
                          ? 'orange'
                          : 'green'
                      }
                      style={{ fontWeight: 600 }}
                    >
                      毛利率 {pctDisplay(summary.gross_margin_rate)}
                    </Tag>
                    {summary.gross_margin_rate * 100 >= 50 ? (
                      <ArrowUpOutlined style={{ color: '#0F6E56' }} />
                    ) : (
                      <ArrowDownOutlined style={{ color: '#A32D2D' }} />
                    )}
                  </div>
                )}
                {summary && summary.gross_margin_rate * 100 < 30 && (
                  <div style={{ marginTop: 4, fontSize: 11, color: '#A32D2D' }}>
                    ⚠ 毛利率低于30%，请关注成本控制
                  </div>
                )}
              </Card>
            </Col>
          </Row>
        </Spin>

        {/* ── 每日趋势折线图 ─────────────────────────────────── */}
        <Card
          title="每日营收 · 成本 · 毛利趋势"
          size="small"
          style={{ marginBottom: 16 }}
          extra={
            <Text style={{ fontSize: 12, color: '#B4B2A9' }}>
              {year}年{month}月
            </Text>
          }
        >
          <DailyTrendChart data={dailyItems} loading={dailyLoading} />
        </Card>

        {/* ── 多月对比 ProTable ──────────────────────────────── */}
        <Card
          title="多月 P&amp;L 对比"
          size="small"
          style={{ marginBottom: 16 }}
          extra={
            <Text style={{ fontSize: 12, color: '#B4B2A9' }}>
              近6个月
            </Text>
          }
        >
          <ProTable<CompareItem>
            columns={compareColumns}
            dataSource={compareItems}
            rowKey="period"
            search={false}
            toolBarRender={false}
            pagination={false}
            size="small"
            loading={loading}
            scroll={{ x: 800 }}
            rowClassName={(record) => {
              const m = parseInt(record.period.split('-')[1], 10);
              return m === month ? 'ant-table-row-selected' : '';
            }}
          />
        </Card>

        {/* ── 预算执行情况 ─────────────────────────────────────── */}
        <Card
          title="预算执行情况"
          size="small"
          extra={
            budgetExec && (
              <Tag
                color={
                  budgetExec.execution_status === 'on_track'
                    ? 'green'
                    : budgetExec.execution_status === 'below_target'
                    ? 'orange'
                    : 'red'
                }
              >
                {budgetExec.execution_status === 'on_track'
                  ? '达标'
                  : budgetExec.execution_status === 'below_target'
                  ? '未达标'
                  : '严重偏差'}
              </Tag>
            )
          }
        >
          <Spin spinning={loading}>
            {budgetExec ? (
              budgetExec.has_budget ? (
                <div style={{ padding: '4px 0' }}>
                  {/* 营收执行率 */}
                  <BudgetRow
                    label="营收目标完成率"
                    targetFen={budgetExec.budget.revenue_target_fen}
                    actualFen={budgetExec.actual.revenue_fen}
                    overBudget={false}
                  />
                  <Divider style={{ margin: '8px 0' }} />
                  {/* 食材成本控制 */}
                  <BudgetRow
                    label="食材成本控制（超预算为红）"
                    targetFen={budgetExec.budget.cost_budget_fen}
                    actualFen={budgetExec.actual.food_cost_fen}
                    overBudget={budgetExec.variance.cost_over_budget}
                  />
                  <Divider style={{ margin: '8px 0' }} />
                  {/* 人力成本控制 */}
                  <BudgetRow
                    label="人力成本控制（超预算为红）"
                    targetFen={budgetExec.budget.labor_budget_fen}
                    actualFen={budgetExec.actual.labor_cost_fen}
                    overBudget={budgetExec.variance.labor_over_budget}
                  />

                  {/* 综合执行率 */}
                  <div
                    style={{
                      marginTop: 16,
                      padding: '12px 16px',
                      background: '#F8F7F5',
                      borderRadius: 6,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 16,
                    }}
                  >
                    <Text style={{ fontSize: 13, color: '#5F5E5A' }}>综合营收执行率</Text>
                    <Progress
                      percent={Math.round(budgetExec.execution_rate * 100)}
                      strokeColor={
                        budgetExec.execution_rate >= 0.95
                          ? '#0F6E56'
                          : budgetExec.execution_rate >= 0.80
                          ? '#BA7517'
                          : '#A32D2D'
                      }
                      style={{ flex: 1 }}
                      size="small"
                    />
                  </div>
                </div>
              ) : (
                <div
                  style={{
                    padding: '24px 0',
                    textAlign: 'center',
                    color: '#B4B2A9',
                  }}
                >
                  本月暂无预算计划，请前往预算管理页面设置
                </div>
              )
            ) : (
              <div
                style={{ padding: '24px 0', textAlign: 'center', color: '#B4B2A9' }}
              >
                加载中…
              </div>
            )}
          </Spin>
        </Card>

      </div>
    </ConfigProvider>
  );
}
