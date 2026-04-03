/**
 * 损益表（P&L）报告页
 * 功能: 门店/品牌 P&L 损益表 + 成本构成饼图（纯SVG）+ 成本分解TOP N + CSV导出
 * 调用 GET /api/v1/finance/pl/store  /api/v1/finance/cost/breakdown
 */
import { useState, useCallback } from 'react';
import { txFetch } from '../../../api';

// ---------- 类型定义 ----------

interface PLReport {
  store_id: string;
  period_start: string;
  period_end: string;
  revenue: {
    dine_in_fen: number;
    delivery_fen: number;
    other_fen: number;
    total_fen: number;
  };
  costs: {
    food_cost_fen: number;
    food_cost_rate: number;
    labor_cost_fen: number;
    rent_fen: number;
    utilities_fen: number;
    other_fen: number;
    total_fen: number;
  };
  gross_profit_fen: number;
  gross_margin_rate: number;
  net_profit_fen: number;
  net_margin_rate: number;
}

interface CostBreakdownItem {
  dish_name: string;
  food_cost_fen: number;
  sale_price_fen: number;
  cost_rate: number;
}

// ---------- 工具函数 ----------

/** 分 → 元，千分位，保留2位小数 */
function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** 百分比，保留1位小数 */
function pct(rate: number): string {
  return rate.toFixed(1) + '%';
}

/** 今天的 ISO 日期字符串 */
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** N天前的 ISO 日期字符串 */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** 本月第一天 */
function firstDayOfMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

/** 上月第一天 */
function firstDayOfLastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 10);
}

/** 上月最后一天 */
function lastDayOfLastMonth(): string {
  const d = new Date();
  d.setDate(0); // 当月第0天 = 上月最后一天
  return d.toISOString().slice(0, 10);
}

// ---------- SVG饼图 ----------

function sectorPath(
  cx: number, cy: number, r: number,
  startAngle: number, endAngle: number,
): string {
  const toRad = (a: number) => (a - 90) * Math.PI / 180;
  const x1 = cx + r * Math.cos(toRad(startAngle));
  const y1 = cy + r * Math.sin(toRad(startAngle));
  const x2 = cx + r * Math.cos(toRad(endAngle));
  const y2 = cy + r * Math.sin(toRad(endAngle));
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${cx} ${cy} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`;
}

interface PieSlice {
  label: string;
  value: number;
  color: string;
}

function SVGPieChart({ slices, size = 160 }: { slices: PieSlice[]; size?: number }) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 8;
  const total = slices.reduce((s, sl) => s + sl.value, 0);
  if (total === 0) {
    return (
      <svg width={size} height={size}>
        <circle cx={cx} cy={cy} r={r} fill="#1a2a33" />
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle" fill="#999" fontSize="12">暂无数据</text>
      </svg>
    );
  }

  let startAngle = 0;
  const sectors = slices.map((sl) => {
    const angle = (sl.value / total) * 360;
    const endAngle = startAngle + angle;
    const path = sectorPath(cx, cy, r, startAngle, endAngle);
    startAngle = endAngle;
    return { ...sl, path };
  });

  return (
    <svg width={size} height={size} style={{ flexShrink: 0 }}>
      {sectors.map((s) => (
        <path key={s.label} d={s.path} fill={s.color} stroke="#0B1A20" strokeWidth={1.5} />
      ))}
      {/* 中心空洞 */}
      <circle cx={cx} cy={cy} r={r * 0.42} fill="#0B1A20" />
      <text x={cx} y={cy - 6} textAnchor="middle" fill="#ccc" fontSize="11">成本构成</text>
      <text x={cx} y={cy + 10} textAnchor="middle" fill="#fff" fontSize="12" fontWeight="bold">
        {pct(100)}
      </text>
    </svg>
  );
}

// ---------- Mock数据（后端未就绪时使用） ----------

const MOCK_PL: PLReport = {
  store_id: 'store_001',
  period_start: '2024-04-01',
  period_end: '2024-04-30',
  revenue: {
    dine_in_fen: 12850000,
    delivery_fen: 4520000,
    other_fen: 230000,
    total_fen: 17600000,
  },
  costs: {
    food_cost_fen: 5632000,
    food_cost_rate: 32.0,
    labor_cost_fen: 3520000,
    rent_fen: 1500000,
    utilities_fen: 420000,
    other_fen: 350000,
    total_fen: 11422000,
  },
  gross_profit_fen: 11968000,
  gross_margin_rate: 68.0,
  net_profit_fen: 6178000,
  net_margin_rate: 35.1,
};

const MOCK_BREAKDOWN: CostBreakdownItem[] = [
  { dish_name: '招牌红烧肉', food_cost_fen: 3200, sale_price_fen: 6800, cost_rate: 47.1 },
  { dish_name: '清蒸鲈鱼', food_cost_fen: 5800, sale_price_fen: 9800, cost_rate: 59.2 },
  { dish_name: '麻婆豆腐', food_cost_fen: 800, sale_price_fen: 3200, cost_rate: 25.0 },
  { dish_name: '剁椒鱼头', food_cost_fen: 6200, sale_price_fen: 12800, cost_rate: 48.4 },
  { dish_name: '农家小炒肉', food_cost_fen: 2400, sale_price_fen: 4200, cost_rate: 57.1 },
  { dish_name: '口水鸡', food_cost_fen: 2800, sale_price_fen: 5800, cost_rate: 48.3 },
  { dish_name: '蒜蓉炒芥兰', food_cost_fen: 600, sale_price_fen: 2800, cost_rate: 21.4 },
  { dish_name: '干锅花菜', food_cost_fen: 900, sale_price_fen: 3600, cost_rate: 25.0 },
  { dish_name: '东坡肘子', food_cost_fen: 8800, sale_price_fen: 15800, cost_rate: 55.7 },
  { dish_name: '水煮牛肉', food_cost_fen: 3600, sale_price_fen: 5800, cost_rate: 62.1 },
];

// ---------- 门店列表（mock） ----------

const STORE_OPTIONS = [
  { id: 'store_001', name: '芙蓉路店' },
  { id: 'store_002', name: '望城店' },
  { id: 'store_003', name: '开福店' },
  { id: 'store_004', name: '岳麓店' },
];

// ---------- 主组件 ----------

export function PLReportPage() {
  const [storeId, setStoreId] = useState('store_001');
  const [datePreset, setDatePreset] = useState('本月');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<PLReport>(MOCK_PL);
  const [breakdown, setBreakdown] = useState<CostBreakdownItem[]>(MOCK_BREAKDOWN);
  const [hasGenerated, setHasGenerated] = useState(true); // 默认展示mock数据

  // 计算实际日期范围
  const getDateRange = useCallback((): { start: string; end: string } => {
    switch (datePreset) {
      case '本周': return { start: daysAgo(6), end: today() };
      case '本月': return { start: firstDayOfMonth(), end: today() };
      case '上月': return { start: firstDayOfLastMonth(), end: lastDayOfLastMonth() };
      case '自定义': return { start: customStart || firstDayOfMonth(), end: customEnd || today() };
      default: return { start: firstDayOfMonth(), end: today() };
    }
  }, [datePreset, customStart, customEnd]);

  // 生成报告
  const handleGenerate = useCallback(async () => {
    setLoading(true);
    const { start, end } = getDateRange();
    try {
      const [pl, cb] = await Promise.all([
        txFetch<PLReport>(`/api/v1/finance/pl/store?store_id=${encodeURIComponent(storeId)}&start_date=${start}&end_date=${end}`),
        txFetch<{ items: CostBreakdownItem[] }>(`/api/v1/finance/cost/breakdown?store_id=${encodeURIComponent(storeId)}&start_date=${start}&end_date=${end}&top_n=10`),
      ]);
      setReport(pl);
      setBreakdown(cb.items ?? []);
    } catch {
      // 后端未就绪时继续展示mock数据
      setReport(MOCK_PL);
      setBreakdown(MOCK_BREAKDOWN);
    } finally {
      setLoading(false);
      setHasGenerated(true);
    }
  }, [storeId, getDateRange]);

  // CSV导出
  const exportCSV = useCallback(() => {
    const { start, end } = getDateRange();
    const storeName = STORE_OPTIONS.find((s) => s.id === storeId)?.name ?? storeId;
    const r = report;
    const headers = ['项目', '金额(元)', '占收入比例'];
    const rows: string[][] = [
      ['── 营业收入 ──', '', ''],
      ['堂食收入', fenToYuan(r.revenue.dine_in_fen), pct(r.revenue.dine_in_fen / r.revenue.total_fen * 100)],
      ['外卖收入', fenToYuan(r.revenue.delivery_fen), pct(r.revenue.delivery_fen / r.revenue.total_fen * 100)],
      ['其他收入', fenToYuan(r.revenue.other_fen), pct(r.revenue.other_fen / r.revenue.total_fen * 100)],
      ['营业收入合计', fenToYuan(r.revenue.total_fen), '100%'],
      ['', '', ''],
      ['── 营业成本 ──', '', ''],
      ['食材成本', fenToYuan(r.costs.food_cost_fen), pct(r.costs.food_cost_rate)],
      ['人工成本', fenToYuan(r.costs.labor_cost_fen), pct(r.costs.labor_cost_fen / r.revenue.total_fen * 100)],
      ['房租及摊销', fenToYuan(r.costs.rent_fen), pct(r.costs.rent_fen / r.revenue.total_fen * 100)],
      ['水电气', fenToYuan(r.costs.utilities_fen), pct(r.costs.utilities_fen / r.revenue.total_fen * 100)],
      ['其他费用', fenToYuan(r.costs.other_fen), pct(r.costs.other_fen / r.revenue.total_fen * 100)],
      ['营业成本合计', fenToYuan(r.costs.total_fen), pct(r.costs.total_fen / r.revenue.total_fen * 100)],
      ['', '', ''],
      ['毛利额', fenToYuan(r.gross_profit_fen), pct(r.gross_margin_rate)],
      ['净利润', fenToYuan(r.net_profit_fen), pct(r.net_margin_rate)],
    ];
    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `P&L报告_${storeName}_${start}_${end}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [report, storeId, getDateRange]);

  // 成本率颜色
  const costRateColor = (rate: number) => {
    if (rate > 50) return '#A32D2D';
    if (rate >= 30) return '#BA7517';
    return '#0F6E56';
  };

  const { start: periodStart, end: periodEnd } = getDateRange();

  // 饼图数据
  const pieSlices: PieSlice[] = report
    ? [
        { label: '食材成本', value: report.costs.food_cost_fen, color: '#FF6B2C' },
        { label: '人工成本', value: report.costs.labor_cost_fen, color: '#185FA5' },
        { label: '房租及摊销', value: report.costs.rent_fen, color: '#0F6E56' },
        { label: '水电气', value: report.costs.utilities_fen, color: '#BA7517' },
        { label: '其他费用', value: report.costs.other_fen, color: '#6B4EA8' },
      ]
    : [];

  const totalCost = report?.costs.total_fen || 1;

  // 指标卡片数据
  const kpiCards = report
    ? [
        {
          label: '营业收入',
          value: `¥${fenToYuan(report.revenue.total_fen)}`,
          sub: null as string | null,
          color: '#FF6B2C',
          trend: null as 'up' | 'down' | null,
        },
        {
          label: '食材成本',
          value: `¥${fenToYuan(report.costs.food_cost_fen)}`,
          sub: `成本率 ${pct(report.costs.food_cost_rate)}`,
          color: '#BA7517',
          trend: null,
        },
        {
          label: '毛利额',
          value: `¥${fenToYuan(report.gross_profit_fen)}`,
          sub: `毛利率 ${pct(report.gross_margin_rate)}`,
          color: '#0F6E56',
          trend: null,
        },
        {
          label: '运营费用',
          value: `¥${fenToYuan(report.costs.labor_cost_fen + report.costs.rent_fen + report.costs.utilities_fen + report.costs.other_fen)}`,
          sub: '含人工/租金/水电/其他',
          color: '#185FA5',
          trend: null,
        },
        {
          label: '净利润',
          value: `¥${fenToYuan(report.net_profit_fen)}`,
          sub: `净利率 ${pct(report.net_margin_rate)}`,
          color: report.net_profit_fen >= 0 ? '#0F6E56' : '#A32D2D',
          trend: (report.net_profit_fen >= 0 ? 'up' : 'down') as 'up' | 'down',
        },
      ]
    : [];

  // P&L 表格行定义
  type RowKind = 'section' | 'item' | 'subtotal' | 'profit' | 'net';
  interface PLRow {
    label: string;
    fen: number | null;
    rate: number | null;
    kind: RowKind;
    indent?: boolean;
  }

  const plRows: PLRow[] = report
    ? [
        { label: '营业收入', fen: null, rate: null, kind: 'section' },
        { label: '堂食收入', fen: report.revenue.dine_in_fen, rate: report.revenue.dine_in_fen / report.revenue.total_fen * 100, kind: 'item', indent: true },
        { label: '外卖收入', fen: report.revenue.delivery_fen, rate: report.revenue.delivery_fen / report.revenue.total_fen * 100, kind: 'item', indent: true },
        { label: '其他收入', fen: report.revenue.other_fen, rate: report.revenue.other_fen / report.revenue.total_fen * 100, kind: 'item', indent: true },
        { label: '营业收入合计', fen: report.revenue.total_fen, rate: 100, kind: 'subtotal' },
        { label: '营业成本', fen: null, rate: null, kind: 'section' },
        { label: '食材成本', fen: report.costs.food_cost_fen, rate: report.costs.food_cost_rate, kind: 'item', indent: true },
        { label: '人工成本', fen: report.costs.labor_cost_fen, rate: report.costs.labor_cost_fen / report.revenue.total_fen * 100, kind: 'item', indent: true },
        { label: '房租及摊销', fen: report.costs.rent_fen, rate: report.costs.rent_fen / report.revenue.total_fen * 100, kind: 'item', indent: true },
        { label: '水电气', fen: report.costs.utilities_fen, rate: report.costs.utilities_fen / report.revenue.total_fen * 100, kind: 'item', indent: true },
        { label: '其他费用', fen: report.costs.other_fen, rate: report.costs.other_fen / report.revenue.total_fen * 100, kind: 'item', indent: true },
        { label: '营业成本合计', fen: report.costs.total_fen, rate: report.costs.total_fen / report.revenue.total_fen * 100, kind: 'subtotal' },
        { label: '毛利润', fen: report.gross_profit_fen, rate: report.gross_margin_rate, kind: 'profit' },
        { label: '净利润', fen: report.net_profit_fen, rate: report.net_margin_rate, kind: 'net' },
      ]
    : [];

  return (
    <div style={{ color: '#e0e0e0', fontSize: 13 }}>
      {/* ── 页头 ── */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 20, flexWrap: 'wrap', gap: 12,
      }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#fff', fontWeight: 700 }}>
          💹 损益表（P&L）
        </h2>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* 门店选择 */}
          <select
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
            style={{
              padding: '6px 10px', borderRadius: 6, border: '1px solid #1a2a33',
              background: '#1a2a33', color: '#ccc', fontSize: 12, cursor: 'pointer',
            }}
          >
            {STORE_OPTIONS.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>

          {/* 日期预设 */}
          {['本周', '本月', '上月', '自定义'].map((d) => (
            <button
              key={d}
              onClick={() => setDatePreset(d)}
              style={{
                padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 600,
                background: datePreset === d ? '#FF6B2C' : '#1a2a33',
                color: datePreset === d ? '#fff' : '#999',
                transition: 'background .15s',
              }}
            >
              {d}
            </button>
          ))}

          {/* 自定义日期区间 */}
          {datePreset === '自定义' && (
            <>
              <input
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                style={{
                  padding: '5px 8px', borderRadius: 6, border: '1px solid #1a2a33',
                  background: '#1a2a33', color: '#ccc', fontSize: 12,
                }}
              />
              <span style={{ color: '#666' }}>—</span>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                style={{
                  padding: '5px 8px', borderRadius: 6, border: '1px solid #1a2a33',
                  background: '#1a2a33', color: '#ccc', fontSize: 12,
                }}
              />
            </>
          )}

          {/* 生成报告 */}
          <button
            onClick={handleGenerate}
            disabled={loading}
            style={{
              padding: '6px 18px', borderRadius: 6, border: 'none', cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: 12, fontWeight: 700,
              background: loading ? '#2a3a43' : '#FF6B2C',
              color: loading ? '#666' : '#fff',
              transition: 'background .15s',
            }}
          >
            {loading ? '生成中...' : '📊 生成报告'}
          </button>

          {/* 导出CSV */}
          {hasGenerated && (
            <button
              onClick={exportCSV}
              style={{
                padding: '6px 14px', borderRadius: 6, border: '1px solid #1a2a33',
                background: 'transparent', cursor: 'pointer',
                fontSize: 12, fontWeight: 600, color: '#0F6E56',
                transition: 'background .15s',
              }}
            >
              📥 导出 CSV
            </button>
          )}
        </div>
      </div>

      {!hasGenerated && (
        <div style={{
          background: '#112228', borderRadius: 8, padding: 48,
          textAlign: 'center', color: '#666',
        }}>
          请选择门店和日期范围，点击「📊 生成报告」查看损益表
        </div>
      )}

      {hasGenerated && report && (
        <>
          {/* ── Section 1: 关键指标汇总 ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 20 }}>
            {kpiCards.map((kpi) => (
              <div key={kpi.label} style={{
                background: '#112228', borderRadius: 8, padding: 16,
                borderLeft: `3px solid ${kpi.color}`,
              }}>
                <div style={{ fontSize: 11, color: '#999', marginBottom: 6 }}>{kpi.label}</div>
                <div style={{
                  fontSize: kpi.kind === 'net' ? 22 : 20,
                  fontWeight: 'bold', color: kpi.color,
                  lineHeight: 1.2,
                }}>
                  {kpi.trend === 'up' && <span style={{ fontSize: 14 }}>↑ </span>}
                  {kpi.trend === 'down' && <span style={{ fontSize: 14 }}>↓ </span>}
                  {kpi.value}
                </div>
                {kpi.sub && (
                  <div style={{ fontSize: 11, color: '#777', marginTop: 4 }}>{kpi.sub}</div>
                )}
              </div>
            ))}
          </div>

          {/* 报告期间标题 */}
          <div style={{
            background: '#0B1A20', borderRadius: 6, padding: '8px 16px',
            marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <span style={{ fontSize: 12, color: '#666' }}>报告期间</span>
            <span style={{ fontSize: 13, color: '#ccc', fontWeight: 600 }}>
              {periodStart} — {periodEnd}
            </span>
            <span style={{ fontSize: 11, color: '#666', marginLeft: 'auto' }}>
              门店：{STORE_OPTIONS.find((s) => s.id === storeId)?.name ?? storeId}
            </span>
          </div>

          {/* ── Section 2 + 3: P&L表格 + 饼图 并排 ── */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16, marginBottom: 16 }}>

            {/* P&L 标准格式表格 */}
            <div style={{ background: '#112228', borderRadius: 8, overflow: 'hidden' }}>
              <div style={{
                background: '#1a2a33', padding: '12px 20px',
                fontSize: 14, fontWeight: 700, color: '#fff', letterSpacing: '0.03em',
              }}>
                损益表
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <colgroup>
                  <col style={{ width: '50%' }} />
                  <col style={{ width: '30%' }} />
                  <col style={{ width: '20%' }} />
                </colgroup>
                <thead>
                  <tr style={{ background: '#0f1e25' }}>
                    <th style={{ padding: '8px 20px', textAlign: 'left', color: '#666', fontWeight: 600, fontSize: 11 }}>项目</th>
                    <th style={{ padding: '8px 16px', textAlign: 'right', color: '#666', fontWeight: 600, fontSize: 11 }}>金额</th>
                    <th style={{ padding: '8px 16px', textAlign: 'right', color: '#666', fontWeight: 600, fontSize: 11 }}>占比</th>
                  </tr>
                </thead>
                <tbody>
                  {plRows.map((row, i) => {
                    const isSectionRow = row.kind === 'section';
                    const isSubtotal = row.kind === 'subtotal';
                    const isProfit = row.kind === 'profit';
                    const isNet = row.kind === 'net';

                    let rowBg = 'transparent';
                    if (isSectionRow) rowBg = '#152530';
                    if (isSubtotal) rowBg = '#1a2c38';
                    if (isProfit) rowBg = '#152530';
                    if (isNet) rowBg = '#0f1e25';

                    let labelColor = '#ccc';
                    if (isSectionRow) labelColor = '#e0e0e0';
                    if (isSubtotal) labelColor = '#fff';
                    if (isProfit) labelColor = '#0F6E56';
                    if (isNet) {
                      labelColor = row.fen != null && row.fen >= 0 ? '#0F6E56' : '#A32D2D';
                    }

                    let fontWeight: 'bold' | 'normal' = 'normal';
                    if (isSectionRow || isSubtotal || isProfit || isNet) fontWeight = 'bold';

                    const amountColor = isNet
                      ? (row.fen != null && row.fen >= 0 ? '#0F6E56' : '#A32D2D')
                      : isProfit ? '#0F6E56'
                      : '#fff';

                    return (
                      <tr key={i} style={{
                        background: rowBg,
                        borderTop: (isSubtotal || isProfit || isNet) ? '1px solid #2a3a43' : '1px solid #162028',
                        borderBottom: isNet ? '2px solid #FF6B2C' : undefined,
                      }}>
                        <td style={{
                          padding: `${isSectionRow ? 10 : 8}px 20px`,
                          paddingLeft: row.indent ? 36 : 20,
                          color: labelColor,
                          fontWeight,
                          fontSize: isNet ? 14 : 13,
                        }}>
                          {isSectionRow && (
                            <span style={{
                              display: 'inline-block', width: 3, height: 12,
                              background: '#FF6B2C', borderRadius: 2,
                              marginRight: 8, verticalAlign: 'middle',
                            }} />
                          )}
                          {row.label}
                        </td>
                        <td style={{
                          padding: '8px 16px', textAlign: 'right',
                          color: amountColor, fontWeight, fontSize: isNet ? 15 : 13,
                        }}>
                          {row.fen != null ? `¥ ${fenToYuan(row.fen)}` : ''}
                        </td>
                        <td style={{
                          padding: '8px 16px', textAlign: 'right',
                          color: (isSubtotal || isProfit || isNet) ? '#aaa' : '#666',
                          fontSize: 12,
                        }}>
                          {row.rate != null ? pct(row.rate) : ''}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Section 3: 成本构成饼图 */}
            <div style={{ background: '#112228', borderRadius: 8, padding: 20, display: 'flex', flexDirection: 'column' }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 14, color: '#fff', fontWeight: 700 }}>成本构成</h3>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <SVGPieChart slices={pieSlices} size={160} />
              </div>
              {/* 图例 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
                {pieSlices.map((sl) => {
                  const percent = sl.value / totalCost * 100;
                  return (
                    <div key={sl.label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{
                        width: 10, height: 10, borderRadius: 2,
                        background: sl.color, flexShrink: 0,
                      }} />
                      <span style={{ fontSize: 12, color: '#ccc', flex: 1 }}>{sl.label}</span>
                      <span style={{ fontSize: 12, color: '#fff', fontWeight: 600 }}>
                        {pct(percent)}
                      </span>
                    </div>
                  );
                })}
              </div>
              {/* 成本合计 */}
              <div style={{
                marginTop: 14, paddingTop: 12,
                borderTop: '1px solid #1a2a33',
                display: 'flex', justifyContent: 'space-between',
                fontSize: 12,
              }}>
                <span style={{ color: '#999' }}>成本合计</span>
                <span style={{ color: '#fff', fontWeight: 700 }}>
                  ¥{fenToYuan(report.costs.total_fen)}
                </span>
              </div>
            </div>
          </div>

          {/* ── Section 4: 成本分解 TOP 10 ── */}
          <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 14, color: '#fff', fontWeight: 700 }}>
              成本分解 TOP 10 菜品
            </h3>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1a2a33' }}>
                  {['#', '菜品名', '食材成本', '售价', '成本率', '成本率'].map((h, i) => (
                    <th key={i} style={{
                      padding: '8px 10px',
                      textAlign: i === 0 ? 'center' : i <= 1 ? 'left' : 'right',
                      color: '#666', fontWeight: 600, fontSize: 11,
                    }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {breakdown.map((item, idx) => {
                  const barColor = costRateColor(item.cost_rate);
                  return (
                    <tr key={idx} style={{ borderTop: '1px solid #162028' }}>
                      <td style={{ padding: '10px', textAlign: 'center', color: '#555', fontWeight: 600 }}>
                        {idx + 1}
                      </td>
                      <td style={{ padding: '10px', color: '#ccc' }}>{item.dish_name}</td>
                      <td style={{ padding: '10px', textAlign: 'right', color: '#fff' }}>
                        ¥{fenToYuan(item.food_cost_fen)}
                      </td>
                      <td style={{ padding: '10px', textAlign: 'right', color: '#fff' }}>
                        ¥{fenToYuan(item.sale_price_fen)}
                      </td>
                      <td style={{ padding: '10px', textAlign: 'right' }}>
                        <span style={{
                          padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                          background: barColor + '22', color: barColor,
                        }}>
                          {pct(item.cost_rate)}
                        </span>
                      </td>
                      <td style={{ padding: '10px', minWidth: 100 }}>
                        <div style={{
                          height: 6, borderRadius: 3,
                          background: '#0B1A20', overflow: 'hidden',
                        }}>
                          <div style={{
                            width: `${Math.min(item.cost_rate, 100)}%`,
                            height: '100%', borderRadius: 3,
                            background: barColor,
                            transition: 'width 0.6s ease',
                          }} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div style={{ marginTop: 12, fontSize: 11, color: '#555', display: 'flex', gap: 16 }}>
              <span>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: '#0F6E56', marginRight: 4 }} />
                &lt; 30% 健康
              </span>
              <span>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: '#BA7517', marginRight: 4 }} />
                30%–50% 偏高
              </span>
              <span>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: '#A32D2D', marginRight: 4 }} />
                &gt; 50% 危险
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
