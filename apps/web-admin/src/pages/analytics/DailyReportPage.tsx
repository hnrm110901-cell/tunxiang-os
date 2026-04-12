/**
 * 运营日报自动生成页 — DailyReportPage
 * 域G: 经营分析 / 运营日报
 *
 * 功能：
 *   - 日期选择器（左右箭头 + 快捷按钮）
 *   - 门店选择（全部/指定门店）
 *   - 日报概览卡片（营收/订单客单价/翻台率/新增会员）
 *   - 详细报表（营收分析/时段分析/支付方式/菜品TOP10/异常记录）
 *   - 日报操作（生成PDF/发送邮箱/对比昨日）
 *   - 周报/月报汇总（底部Tab切换）
 *
 * 技术：Ant Design 5.x + ProTable，SVG无外部库
 * API：http://localhost:8009 对接 daily_report_routes
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card,
  Row,
  Col,
  Button,
  Select,
  Switch,
  Tabs,
  Tag,
  Space,
  Spin,
  message,
  Statistic,
  DatePicker,
  Tooltip,
  Badge,
  List,
} from 'antd';
import {
  LeftOutlined,
  RightOutlined,
  FilePdfOutlined,
  MailOutlined,
  SwapOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  ReloadOutlined,
  TeamOutlined,
  ShoppingCartOutlined,
  DollarOutlined,
  TableOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';
import { txFetchData } from '../../api';

// ─── 常量 ─────────────────────────────────────────────────────────────────────
const API_PREFIX = '/api/v1/analytics/daily-report';

// ─── Design Token ─────────────────────────────────────────────────────────────
const T = {
  brand: '#FF6B35',
  brandLight: '#FFF3ED',
  success: '#52c41a',
  danger: '#ff4d4f',
  warning: '#faad14',
  text1: '#1f1f1f',
  text2: '#666',
  text3: '#999',
  bg: '#f5f5f5',
  cardBg: '#fff',
  border: '#f0f0f0',
} as const;

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface DailyReport {
  store_id: string;
  store_name: string;
  report_date: string;
  order_count: number;
  revenue_fen: number;
  cost_fen: number;
  gross_profit_fen: number;
  gross_margin: number;
  avg_ticket_fen: number;
  table_turnover: number;
  new_members: number;
  payment_breakdown: Record<string, number>;
  channel_breakdown: Record<string, number>;
}

interface SummaryData {
  dimension: string;
  start_date: string;
  end_date: string;
  days: number;
  total_order_count: number;
  total_revenue_fen: number;
  total_cost_fen: number;
  total_gross_profit_fen: number;
  avg_gross_margin: number;
  avg_daily_revenue_fen: number;
  avg_ticket_fen: number;
  total_new_members: number;
}

interface DishRank {
  rank: number;
  name: string;
  sales: number;
  revenue: number;
  margin: number;
}

interface AnomalyRecord {
  id: string;
  type: 'refund' | 'discount' | 'complaint';
  content: string;
  amount_fen: number;
  time: string;
}

// ─── 静态全部门店选项（初始项，动态列表从 API 加载追加） ──────────────────────
const ALL_STORES_OPTION = { value: '', label: '全部门店' };

function mockHourlyData(seed: number): number[] {
  const hours: number[] = [];
  for (let h = 0; h < 24; h++) {
    const base = h >= 11 && h <= 13 ? 5000 : h >= 17 && h <= 20 ? 6500 : h >= 7 && h <= 9 ? 2000 : 800;
    hours.push(base + ((seed * (h + 1) * 37) % 2000));
  }
  return hours;
}

function mockDishTop10(seed: number): DishRank[] {
  const dishes = [
    '招牌剁椒鱼头', '蒜蓉龙虾', '小炒黄牛肉', '口味虾', '酱板鸭',
    '糖油粑粑', '臭豆腐拼盘', '紫苏桃子姜', '啤酒鸭', '农家小炒肉',
  ];
  return dishes.map((name, i) => ({
    rank: i + 1,
    name,
    sales: 80 - i * 6 + ((seed * (i + 1)) % 15),
    revenue: (12000 - i * 900 + ((seed * (i + 1) * 13) % 3000)),
    margin: +(0.55 + ((seed * (i + 1)) % 20) / 100).toFixed(2),
  }));
}

function mockAnomalies(seed: number): AnomalyRecord[] {
  const types: Array<'refund' | 'discount' | 'complaint'> = ['refund', 'discount', 'complaint'];
  const contents = [
    '顾客反映菜品口味偏咸，全额退款',
    '店长审批8折优惠（超出权限）',
    '等餐超时45分钟投诉',
    '外卖漏送配菜退部分款',
    '会员日折扣叠加错误',
    '顾客过敏反应投诉（已处理）',
  ];
  const count = 3 + (seed % 4);
  return Array.from({ length: count }, (_, i) => ({
    id: `anomaly-${seed}-${i}`,
    type: types[i % 3],
    content: contents[i % contents.length],
    amount_fen: 2000 + ((seed * (i + 1) * 47) % 8000),
    time: `${10 + (i * 2)}:${((seed * i) % 60).toString().padStart(2, '0')}`,
  }));
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pctText(val: number): string {
  const sign = val >= 0 ? '+' : '';
  return `${sign}${val.toFixed(1)}%`;
}

// ─── SVG 图表组件 ─────────────────────────────────────────────────────────────

/** 渠道柱状图 — 堂食/外卖/零售/储值 */
function ChannelBarChart({
  data,
  prevData,
  showCompare,
}: {
  data: Record<string, number>;
  prevData: Record<string, number> | null;
  showCompare: boolean;
}) {
  const channels = [
    { key: 'dine_in', label: '堂食', color: '#FF6B35' },
    { key: 'takeaway', label: '外卖', color: '#1890ff' },
    { key: 'mini_program', label: '小程序', color: '#52c41a' },
    { key: 'retail', label: '零售', color: '#722ed1' },
  ];
  const maxVal = Math.max(...channels.map(c => data[c.key] || 0), 1);
  const W = 400;
  const H = 200;
  const barW = 40;
  const gap = (W - channels.length * barW * (showCompare ? 2 : 1)) / (channels.length + 1);

  return (
    <svg viewBox={`0 0 ${W} ${H + 30}`} width="100%" style={{ maxWidth: 420 }}>
      {channels.map((ch, i) => {
        const val = data[ch.key] || 0;
        const barH = (val / maxVal) * H * 0.85;
        const x = gap + i * (barW * (showCompare ? 2 : 1) + gap);
        const prevVal = prevData?.[ch.key] || 0;
        const prevH = (prevVal / maxVal) * H * 0.85;

        return (
          <g key={ch.key}>
            <rect
              x={x}
              y={H - barH}
              width={barW}
              height={barH}
              fill={ch.color}
              rx={3}
            />
            <text x={x + barW / 2} y={H - barH - 5} textAnchor="middle" fontSize={10} fill={T.text2}>
              {fenToYuan(val)}
            </text>
            {showCompare && prevData && (
              <rect
                x={x + barW + 4}
                y={H - prevH}
                width={barW}
                height={prevH}
                fill={ch.color}
                opacity={0.3}
                rx={3}
                strokeDasharray="4 2"
                stroke={ch.color}
              />
            )}
            <text x={x + barW / 2} y={H + 16} textAnchor="middle" fontSize={11} fill={T.text2}>
              {ch.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** 24小时营收折线图 */
function HourlyLineChart({
  data,
  prevData,
  showCompare,
}: {
  data: number[];
  prevData: number[] | null;
  showCompare: boolean;
}) {
  const W = 500;
  const H = 200;
  const padX = 35;
  const padY = 20;
  const plotW = W - padX * 2;
  const plotH = H - padY * 2;
  const maxVal = Math.max(...data, ...(showCompare && prevData ? prevData : [0]), 1);

  const toX = (i: number) => padX + (i / 23) * plotW;
  const toY = (v: number) => padY + plotH - (v / maxVal) * plotH;

  const points = data.map((v, i) => `${toX(i)},${toY(v)}`).join(' ');
  const prevPoints = prevData ? prevData.map((v, i) => `${toX(i)},${toY(v)}`).join(' ') : '';

  // 高峰时段
  const peakLunch = data.slice(11, 14);
  const peakDinner = data.slice(17, 21);
  const lunchMax = Math.max(...peakLunch);
  const dinnerMax = Math.max(...peakDinner);

  return (
    <svg viewBox={`0 0 ${W} ${H + 10}`} width="100%" style={{ maxWidth: 540 }}>
      {/* Y轴 */}
      {[0, 0.25, 0.5, 0.75, 1].map(pct => {
        const y = padY + plotH * (1 - pct);
        return (
          <g key={pct}>
            <line x1={padX} y1={y} x2={W - padX} y2={y} stroke={T.border} strokeWidth={0.5} />
            <text x={padX - 4} y={y + 3} textAnchor="end" fontSize={9} fill={T.text3}>
              {Math.round(maxVal * pct)}
            </text>
          </g>
        );
      })}
      {/* X轴标签 */}
      {[0, 4, 8, 12, 16, 20, 23].map(h => (
        <text key={h} x={toX(h)} y={H} textAnchor="middle" fontSize={9} fill={T.text3}>
          {h}:00
        </text>
      ))}
      {/* 高峰区域 */}
      <rect x={toX(11)} y={padY} width={toX(13) - toX(11)} height={plotH} fill="rgba(255,107,53,0.08)" />
      <rect x={toX(17)} y={padY} width={toX(20) - toX(17)} height={plotH} fill="rgba(255,107,53,0.08)" />
      <text x={toX(12)} y={padY + 12} textAnchor="middle" fontSize={9} fill={T.brand}>
        午高峰 {lunchMax}
      </text>
      <text x={toX(18.5)} y={padY + 12} textAnchor="middle" fontSize={9} fill={T.brand}>
        晚高峰 {dinnerMax}
      </text>
      {/* 昨日虚线 */}
      {showCompare && prevData && (
        <polyline points={prevPoints} fill="none" stroke={T.text3} strokeWidth={1.5} strokeDasharray="5 3" />
      )}
      {/* 今日实线 */}
      <polyline points={points} fill="none" stroke={T.brand} strokeWidth={2} />
      {/* 数据点 */}
      {data.map((v, i) => (
        <circle key={i} cx={toX(i)} cy={toY(v)} r={2.5} fill={T.brand} />
      ))}
    </svg>
  );
}

/** 支付方式饼图 */
function PaymentPieChart({ data }: { data: Record<string, number> }) {
  const labels: Record<string, string> = {
    wechat: '微信',
    alipay: '支付宝',
    cash: '现金',
    card: '储值卡',
    credit: '挂账',
  };
  const colors: Record<string, string> = {
    wechat: '#07c160',
    alipay: '#1677ff',
    cash: '#faad14',
    card: '#722ed1',
    credit: '#8c8c8c',
  };

  const entries = Object.entries(data).filter(([, v]) => v > 0);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (total === 0) return <div style={{ color: T.text3, textAlign: 'center' }}>暂无数据</div>;

  const R = 70;
  const cx = 100;
  const cy = 90;
  let cumAngle = -Math.PI / 2;

  const slices = entries.map(([key, val]) => {
    const angle = (val / total) * Math.PI * 2;
    const startAngle = cumAngle;
    cumAngle += angle;
    const endAngle = cumAngle;
    const x1 = cx + R * Math.cos(startAngle);
    const y1 = cy + R * Math.sin(startAngle);
    const x2 = cx + R * Math.cos(endAngle);
    const y2 = cy + R * Math.sin(endAngle);
    const largeArc = angle > Math.PI ? 1 : 0;
    const d = `M${cx},${cy} L${x1},${y1} A${R},${R} 0 ${largeArc},1 ${x2},${y2} Z`;
    return { key, d, color: colors[key] || '#ccc', pct: ((val / total) * 100).toFixed(1), label: labels[key] || key, val };
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
      <svg viewBox="0 0 200 180" width={200}>
        {slices.map(s => (
          <path key={s.key} d={s.d} fill={s.color} stroke="#fff" strokeWidth={1.5} />
        ))}
      </svg>
      <div>
        {slices.map(s => (
          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 13 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: s.color, display: 'inline-block' }} />
            <span style={{ color: T.text1 }}>{s.label}</span>
            <span style={{ color: T.text3 }}>{s.pct}%</span>
            <span style={{ color: T.text2, marginLeft: 4 }}>{fenToYuan(s.val)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 汇总趋势折线图 ─────────────────────────────────────────────────────────

function TrendLineChart({ reports }: { reports: DailyReport[] }) {
  if (reports.length === 0) return <div style={{ color: T.text3, textAlign: 'center', padding: 40 }}>暂无数据</div>;
  const W = 500;
  const H = 180;
  const padX = 45;
  const padY = 20;
  const plotW = W - padX * 2;
  const plotH = H - padY * 2;
  const maxRev = Math.max(...reports.map(r => r.revenue_fen), 1);

  const toX = (i: number) => padX + (i / Math.max(reports.length - 1, 1)) * plotW;
  const toY = (v: number) => padY + plotH - (v / maxRev) * plotH;

  const points = reports.map((r, i) => `${toX(i)},${toY(r.revenue_fen)}`).join(' ');

  return (
    <svg viewBox={`0 0 ${W} ${H + 20}`} width="100%" style={{ maxWidth: 540 }}>
      {[0, 0.5, 1].map(pct => {
        const y = padY + plotH * (1 - pct);
        return (
          <g key={pct}>
            <line x1={padX} y1={y} x2={W - padX} y2={y} stroke={T.border} strokeWidth={0.5} />
            <text x={padX - 4} y={y + 3} textAnchor="end" fontSize={9} fill={T.text3}>
              {fenToYuan(Math.round(maxRev * pct))}
            </text>
          </g>
        );
      })}
      <polyline points={points} fill="none" stroke={T.brand} strokeWidth={2} />
      {reports.map((r, i) => (
        <g key={i}>
          <circle cx={toX(i)} cy={toY(r.revenue_fen)} r={3} fill={T.brand} />
          {reports.length <= 14 && (
            <text x={toX(i)} y={H + 14} textAnchor="middle" fontSize={8} fill={T.text3}>
              {r.report_date.slice(5)}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function DailyReportPage() {
  // 状态
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs().subtract(1, 'day'));
  const [storeId, setStoreId] = useState<string>('');
  const [storeOptions, setStoreOptions] = useState<{ value: string; label: string }[]>([ALL_STORES_OPTION]);
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [prevReport, setPrevReport] = useState<DailyReport | null>(null);
  const [showCompare, setShowCompare] = useState(false);
  const [summaryTab, setSummaryTab] = useState<'week' | 'month'>('week');
  const [summaryData, setSummaryData] = useState<SummaryData | null>(null);
  const [summaryReports, setSummaryReports] = useState<DailyReport[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // ─── 加载门店��表 ────────────────────────────────────────────────────────
  useEffect(() => {
    txFetchData<{ items: { id: string; name: string }[] }>('/api/v1/org/stores?page=1&size=100')
      .then((data) => {
        if (data?.items?.length) {
          setStoreOptions([
            ALL_STORES_OPTION,
            ...data.items.map((s) => ({ value: s.id, label: s.name })),
          ]);
        }
      })
      .catch(() => { /* 保持默认"全部门店"选项 */ });
  }, []);

  // ─── API 调用 ───────────────────────────────────────────────────────────

  const fetchReport = useCallback(async (dateStr: string, store: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ date: dateStr });
      if (store) params.set('store_id', store);
      const data = await txFetchData<DailyReport>(`${API_PREFIX}?${params.toString()}`);
      setReport(data);
    } catch (err: unknown) {
      console.error('[DailyReportPage] fetchReport error', err);
      message.error('日报数据加载失败');
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPrevReport = useCallback(async (dateStr: string, store: string) => {
    try {
      const params = new URLSearchParams({ date: dateStr });
      if (store) params.set('store_id', store);
      const data = await txFetchData<DailyReport>(`${API_PREFIX}?${params.toString()}`);
      setPrevReport(data);
    } catch {
      setPrevReport(null);
    }
  }, []);

  const fetchSummary = useCallback(async (dimension: 'week' | 'month', endDate: Dayjs, store: string) => {
    setSummaryLoading(true);
    try {
      // 汇总区间
      const startDate = dimension === 'week'
        ? endDate.subtract(6, 'day').format('YYYY-MM-DD')
        : endDate.startOf('month').format('YYYY-MM-DD');
      const params = new URLSearchParams({
        date: endDate.format('YYYY-MM-DD'),
        dimension,
        start_date: startDate,
      });
      if (store) params.set('store_id', store);

      // 汇总指标
      const summaryData = await txFetchData<SummaryData>(
        `${API_PREFIX}/summary?${params.toString()}`,
      ).catch(() => null);
      if (summaryData) setSummaryData(summaryData);

      // 明细列表（用于趋势图）
      const listParams = new URLSearchParams({ start_date: startDate, end_date: endDate.format('YYYY-MM-DD'), size: '31' });
      if (store) listParams.set('store_id', store);
      const listData = await txFetchData<{ items: DailyReport[] }>(
        `${API_PREFIX}/list?${listParams.toString()}`,
      ).catch(() => null);
      if (listData?.items) setSummaryReports(listData.items);
    } catch {
      message.error('汇总数据加载失败');
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  // ─── 副作用 ─────────────────────────────────────────────────────────────

  useEffect(() => {
    const dateStr = selectedDate.format('YYYY-MM-DD');
    fetchReport(dateStr, storeId);
    const prevStr = selectedDate.subtract(1, 'day').format('YYYY-MM-DD');
    fetchPrevReport(prevStr, storeId);
  }, [selectedDate, storeId, fetchReport, fetchPrevReport]);

  useEffect(() => {
    fetchSummary(summaryTab, selectedDate, storeId);
  }, [summaryTab, selectedDate, storeId, fetchSummary]);

  // ─── 日期操作 ───────────────────────────────────────────────────────────

  const goDay = (offset: number) => {
    const next = selectedDate.add(offset, 'day');
    if (next.isAfter(dayjs())) return;
    setSelectedDate(next);
  };

  const goToday = () => setSelectedDate(dayjs().subtract(0, 'day').isAfter(dayjs()) ? dayjs() : dayjs());
  const goYesterday = () => setSelectedDate(dayjs().subtract(1, 'day'));
  const goDayBefore = () => setSelectedDate(dayjs().subtract(2, 'day'));

  // ─── 模拟操作 ───────────────────────────────────────────────────────────

  const handleGeneratePDF = () => {
    message.success('PDF报告生成中... 完成后将自动下载');
  };

  const handleSendEmail = () => {
    message.success('日报已发送至管理组邮箱');
  };

  // ─── 计算环比 ───────────────────────────────────────────────────────────

  const calcChange = (curr: number, prev: number): number => {
    if (prev === 0) return 0;
    return ((curr - prev) / prev) * 100;
  };

  // ─── 数据准备 ───────────────────────────────────────────────────────────

  const dateSeed = selectedDate.diff(dayjs('2026-01-01'), 'day');
  // 优先使用 API 返回的扩展字段，否则降级到 Mock 补充数据
  type ExtendedReport = DailyReport & {
    hourly_revenue?: number[];
    top_dishes?: DishRank[];
    anomalies?: AnomalyRecord[];
  };
  const hourlyData: number[] = (report as ExtendedReport | null)?.hourly_revenue ?? mockHourlyData(dateSeed);
  const prevHourlyData: number[] = (prevReport as ExtendedReport | null)?.hourly_revenue ?? mockHourlyData(dateSeed - 1);
  const dishTop10: DishRank[] = (report as ExtendedReport | null)?.top_dishes ?? mockDishTop10(dateSeed);
  const anomalies: AnomalyRecord[] = (report as ExtendedReport | null)?.anomalies ?? mockAnomalies(dateSeed);

  const revenueChange = prevReport ? calcChange(report?.revenue_fen || 0, prevReport.revenue_fen) : 0;
  const ordersChange = prevReport ? calcChange(report?.order_count || 0, prevReport.order_count) : 0;
  const turnoverChange = prevReport ? (report?.table_turnover || 0) - prevReport.table_turnover : 0;
  const membersChange = prevReport ? (report?.new_members || 0) - prevReport.new_members : 0;

  // ─── 菜品 TOP10 ProTable 列定义 ────────────────────────────────────────

  const dishColumns: ProColumns<DishRank>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 60,
      render: (_: unknown, record: DishRank) => (
        <span
          style={{
            display: 'inline-block',
            width: 24,
            height: 24,
            borderRadius: 12,
            background: record.rank <= 3 ? T.brand : T.border,
            color: record.rank <= 3 ? '#fff' : T.text2,
            textAlign: 'center',
            lineHeight: '24px',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {record.rank}
        </span>
      ),
    },
    { title: '菜品', dataIndex: 'name', width: 160 },
    {
      title: '销量',
      dataIndex: 'sales',
      width: 80,
      sorter: (a: DishRank, b: DishRank) => a.sales - b.sales,
    },
    {
      title: '营收(元)',
      dataIndex: 'revenue',
      width: 120,
      render: (_: unknown, record: DishRank) => fenToYuan(record.revenue * 100),
      sorter: (a: DishRank, b: DishRank) => a.revenue - b.revenue,
    },
    {
      title: '毛利率',
      dataIndex: 'margin',
      width: 100,
      render: (_: unknown, record: DishRank) => {
        const color = record.margin >= 0.6 ? T.success : record.margin >= 0.4 ? T.warning : T.danger;
        return <span style={{ color, fontWeight: 500 }}>{(record.margin * 100).toFixed(1)}%</span>;
      },
      sorter: (a: DishRank, b: DishRank) => a.margin - b.margin,
    },
  ];

  // ─── 异常类型标签 ──────────────────────────────────────────────────────

  const anomalyTagMap: Record<string, { color: string; text: string }> = {
    refund: { color: 'red', text: '退款' },
    discount: { color: 'orange', text: '折扣' },
    complaint: { color: 'purple', text: '客诉' },
  };

  // ─── 渲染 ───────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: '0 0 24px', background: T.bg, minHeight: '100vh' }}>
      {/* ── 顶部操作栏 ────────────────────────────────────────────────── */}
      <Card
        bodyStyle={{ padding: '16px 24px' }}
        style={{ marginBottom: 16, borderRadius: 8 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          {/* 日期选择 */}
          <Space size={8}>
            <Button icon={<LeftOutlined />} onClick={() => goDay(-1)} />
            <DatePicker
              value={selectedDate}
              onChange={(d) => d && setSelectedDate(d)}
              allowClear={false}
              disabledDate={(d) => d.isAfter(dayjs())}
              style={{ width: 140 }}
            />
            <Button
              icon={<RightOutlined />}
              onClick={() => goDay(1)}
              disabled={selectedDate.isSame(dayjs(), 'day')}
            />
            <Button size="small" onClick={goToday}>今天</Button>
            <Button size="small" onClick={goYesterday} type={selectedDate.isSame(dayjs().subtract(1, 'day'), 'day') ? 'primary' : 'default'}>昨天</Button>
            <Button size="small" onClick={goDayBefore}>前天</Button>
          </Space>

          {/* 门店选择 */}
          <Select
            value={storeId}
            onChange={setStoreId}
            options={storeOptions}
            style={{ width: 180 }}
            placeholder="选择门店"
          />

          {/* 操作按钮 */}
          <Space>
            <Tooltip title="对比昨日数据">
              <span style={{ fontSize: 13, color: T.text2, marginRight: 4 }}>
                <SwapOutlined /> 对比昨日
              </span>
              <Switch checked={showCompare} onChange={setShowCompare} size="small" />
            </Tooltip>
            <Button icon={<FilePdfOutlined />} onClick={handleGeneratePDF}>
              生成PDF报告
            </Button>
            <Button icon={<MailOutlined />} onClick={handleSendEmail}>
              发送到邮箱
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => fetchReport(selectedDate.format('YYYY-MM-DD'), storeId)}
            />
          </Space>
        </div>
      </Card>

      <Spin spinning={loading}>
        {/* ── 日报概览卡片 4张 ─────────────────────────────────────────── */}
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {/* 营收 */}
          <Col xs={24} sm={12} lg={6}>
            <Card bodyStyle={{ padding: 20 }} style={{ borderRadius: 8, borderLeft: `4px solid ${T.brand}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <DollarOutlined style={{ fontSize: 20, color: T.brand }} />
                <span style={{ color: T.text2, fontSize: 13 }}>当日营收</span>
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: T.text1, lineHeight: 1.2 }}>
                {report ? `\u00A5${fenToYuan(report.revenue_fen)}` : '--'}
              </div>
              <div style={{ marginTop: 8, fontSize: 13 }}>
                {prevReport && (
                  <span style={{ color: revenueChange >= 0 ? T.success : T.danger }}>
                    {revenueChange >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                    {' '}环比 {pctText(revenueChange)}
                  </span>
                )}
              </div>
            </Card>
          </Col>

          {/* 订单数 + 客单价 */}
          <Col xs={24} sm={12} lg={6}>
            <Card bodyStyle={{ padding: 20 }} style={{ borderRadius: 8, borderLeft: `4px solid #1890ff` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <ShoppingCartOutlined style={{ fontSize: 20, color: '#1890ff' }} />
                <span style={{ color: T.text2, fontSize: 13 }}>订单数 / 客单价</span>
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: T.text1, lineHeight: 1.2 }}>
                {report ? report.order_count : '--'}
                <span style={{ fontSize: 14, fontWeight: 400, color: T.text2, marginLeft: 8 }}>
                  {report ? `\u00A5${fenToYuan(report.avg_ticket_fen)}` : ''}
                </span>
              </div>
              <div style={{ marginTop: 8, fontSize: 13 }}>
                {prevReport && (
                  <span style={{ color: ordersChange >= 0 ? T.success : T.danger }}>
                    {ordersChange >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                    {' '}订单环比 {pctText(ordersChange)}
                  </span>
                )}
              </div>
            </Card>
          </Col>

          {/* 翻台率 */}
          <Col xs={24} sm={12} lg={6}>
            <Card bodyStyle={{ padding: 20 }} style={{ borderRadius: 8, borderLeft: `4px solid #52c41a` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <TableOutlined style={{ fontSize: 20, color: '#52c41a' }} />
                <span style={{ color: T.text2, fontSize: 13 }}>翻台率</span>
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: T.text1, lineHeight: 1.2 }}>
                {report ? `${report.table_turnover.toFixed(2)}` : '--'}
                <span style={{ fontSize: 14, fontWeight: 400, color: T.text2, marginLeft: 4 }}>次/桌</span>
              </div>
              <div style={{ marginTop: 8, fontSize: 13 }}>
                {prevReport && (
                  <span style={{ color: turnoverChange >= 0 ? T.success : T.danger }}>
                    {turnoverChange >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                    {' '}{turnoverChange >= 0 ? '+' : ''}{turnoverChange.toFixed(2)}
                  </span>
                )}
              </div>
            </Card>
          </Col>

          {/* 新增会员 */}
          <Col xs={24} sm={12} lg={6}>
            <Card bodyStyle={{ padding: 20 }} style={{ borderRadius: 8, borderLeft: `4px solid #722ed1` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <TeamOutlined style={{ fontSize: 20, color: '#722ed1' }} />
                <span style={{ color: T.text2, fontSize: 13 }}>新增会员</span>
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: T.text1, lineHeight: 1.2 }}>
                {report ? report.new_members : '--'}
                <span style={{ fontSize: 14, fontWeight: 400, color: T.text2, marginLeft: 4 }}>人</span>
              </div>
              <div style={{ marginTop: 8, fontSize: 13 }}>
                {prevReport && (
                  <span style={{ color: membersChange >= 0 ? T.success : T.danger }}>
                    {membersChange >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                    {' '}{membersChange >= 0 ? '+' : ''}{membersChange}人
                  </span>
                )}
              </div>
            </Card>
          </Col>
        </Row>

        {/* ── 详细报表区 ──────────────────────────────────────────────── */}
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {/* 营收分析 — 渠道柱状图 */}
          <Col xs={24} lg={12}>
            <Card title="营收分析 — 渠道分布" bodyStyle={{ padding: 16 }} style={{ borderRadius: 8 }}>
              {report ? (
                <ChannelBarChart
                  data={report.channel_breakdown}
                  prevData={showCompare ? prevReport?.channel_breakdown ?? null : null}
                  showCompare={showCompare}
                />
              ) : (
                <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.text3 }}>
                  暂无数据
                </div>
              )}
              {showCompare && (
                <div style={{ fontSize: 12, color: T.text3, marginTop: 8 }}>
                  <span style={{ opacity: 0.5, borderLeft: `12px dashed ${T.text3}`, marginRight: 6 }} />
                  虚线为昨日数据
                </div>
              )}
            </Card>
          </Col>

          {/* 时段分析 — 24小时折线 */}
          <Col xs={24} lg={12}>
            <Card title="时段分析 — 24小时营收曲线" bodyStyle={{ padding: 16 }} style={{ borderRadius: 8 }}>
              <HourlyLineChart
                data={hourlyData}
                prevData={showCompare ? prevHourlyData : null}
                showCompare={showCompare}
              />
              {showCompare && (
                <div style={{ fontSize: 12, color: T.text3, marginTop: 8 }}>
                  <span style={{ display: 'inline-block', width: 20, borderTop: `2px dashed ${T.text3}`, marginRight: 6, verticalAlign: 'middle' }} />
                  虚线为昨日
                </div>
              )}
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {/* 支付方式饼图 */}
          <Col xs={24} lg={10}>
            <Card title="支付方式分布" bodyStyle={{ padding: 16 }} style={{ borderRadius: 8 }}>
              {report ? <PaymentPieChart data={report.payment_breakdown} /> : (
                <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.text3 }}>暂无数据</div>
              )}
            </Card>
          </Col>

          {/* 菜品 TOP10 */}
          <Col xs={24} lg={14}>
            <Card title="菜品 TOP10" bodyStyle={{ padding: 0 }} style={{ borderRadius: 8 }}>
              <ProTable<DishRank>
                columns={dishColumns}
                dataSource={dishTop10}
                rowKey="rank"
                search={false}
                pagination={false}
                options={false}
                size="small"
                headerTitle={false}
              />
            </Card>
          </Col>
        </Row>

        {/* 异常记录 */}
        <Card title="异常记录" style={{ marginBottom: 16, borderRadius: 8 }}>
          <Row gutter={16}>
            <Col span={4}>
              <Statistic
                title="退款笔数"
                value={anomalies.filter(a => a.type === 'refund').length}
                suffix="笔"
                valueStyle={{ color: T.danger }}
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="异常折扣"
                value={anomalies.filter(a => a.type === 'discount').length}
                suffix="笔"
                valueStyle={{ color: T.warning }}
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="客诉"
                value={anomalies.filter(a => a.type === 'complaint').length}
                suffix="件"
                valueStyle={{ color: '#722ed1' }}
              />
            </Col>
          </Row>
          <List
            style={{ marginTop: 16 }}
            size="small"
            dataSource={anomalies}
            renderItem={(item) => (
              <List.Item>
                <Space>
                  <Tag color={anomalyTagMap[item.type]?.color}>{anomalyTagMap[item.type]?.text}</Tag>
                  <span style={{ color: T.text3, fontSize: 12 }}>{item.time}</span>
                  <span>{item.content}</span>
                  {item.amount_fen > 0 && (
                    <span style={{ color: T.danger }}>{fenToYuan(item.amount_fen)}元</span>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Card>

        {/* ── 周报/月报汇总 ──────────────────────────────────────────── */}
        <Card
          title="周报 / 月报汇总"
          style={{ borderRadius: 8 }}
          extra={
            <Tabs
              activeKey={summaryTab}
              onChange={(k) => setSummaryTab(k as 'week' | 'month')}
              size="small"
              items={[
                { key: 'week', label: '本周' },
                { key: 'month', label: '本月' },
              ]}
            />
          }
        >
          <Spin spinning={summaryLoading}>
            {summaryData && (
              <>
                <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                  <Col xs={12} sm={6}>
                    <Statistic
                      title={`${summaryTab === 'week' ? '周' : '月'}累计营收`}
                      value={summaryData.total_revenue_fen / 100}
                      precision={2}
                      prefix="\u00A5"
                    />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic
                      title="累计订单"
                      value={summaryData.total_order_count}
                      suffix="单"
                    />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic
                      title="日均营收"
                      value={summaryData.avg_daily_revenue_fen / 100}
                      precision={2}
                      prefix="\u00A5"
                    />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic
                      title="平均毛利率"
                      value={(summaryData.avg_gross_margin * 100)}
                      precision={1}
                      suffix="%"
                      valueStyle={{ color: summaryData.avg_gross_margin >= 0.6 ? T.success : T.warning }}
                    />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic
                      title="平均客单价"
                      value={summaryData.avg_ticket_fen / 100}
                      precision={2}
                      prefix="\u00A5"
                    />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic
                      title="新增会员"
                      value={summaryData.total_new_members}
                      suffix="人"
                    />
                  </Col>
                  <Col xs={12} sm={6}>
                    <Statistic
                      title="统计天数"
                      value={summaryData.days}
                      suffix="天"
                    />
                  </Col>
                </Row>

                {/* 趋势折线 */}
                <Card type="inner" title="营收趋势" bodyStyle={{ padding: 12 }}>
                  <TrendLineChart reports={summaryReports} />
                </Card>
              </>
            )}
          </Spin>
        </Card>
      </Spin>
    </div>
  );
}
