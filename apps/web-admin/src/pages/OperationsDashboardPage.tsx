/**
 * 经营驾驶舱（P&L版）— OperationsDashboardPage
 * 域G: 经营分析 / 经营驾驶舱
 *
 * 功能区块：
 *   1. 顶部筛选栏（日期 + 门店 + 刷新）
 *   2. 4个关键指标卡片（营收/毛利率/订单数/翻台率）
 *   3. 30天营收趋势折线图（实际 vs 目标）
 *   4. 各渠道营收饼图 + 明细表
 *   5. 门店P&L对比表（多店）
 *   6. 日清日结E1-E8完成状态
 *
 * API:
 *   GET /api/v1/finance/pnl/calculate
 *   GET /api/v1/finance/pnl/trend
 *   GET /api/v1/finance/pnl/compare
 *   GET /api/v1/ops/daily-summary
 *   GET /api/v1/ops/settlement/checklist
 *   GET /api/v1/analytics/dashboard
 */
import { useState, useEffect, useCallback } from 'react';
import { TxLineChart } from '../components/charts';
import { TxPieChart } from '../components/charts';
import { txFetch } from '../api';

// ─── 颜色常量（Design Token） ───
const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  cardBg: '#112228',
  innerBg: '#0B1A20',
  border: '#1a2a33',
  text: '#fff',
  textSub: '#ccc',
  textMuted: '#999',
  textDim: '#666',
};

// ─── 工具函数 ───
const today = () => new Date().toISOString().slice(0, 10);
const fmt10k = (v: number) => `${(v / 10000).toFixed(2)}万`;
const fmtPct = (v: number) => `${v.toFixed(1)}%`;
const marginColor = (m: number): string =>
  m >= 45 ? C.success : m >= 35 ? C.warning : C.danger;

// ─── 类型定义 ───

interface PnlData {
  revenue_fen: number;
  cost_fen: number;
  gross_profit_fen: number;
  gross_margin: number; // 0–100
}

interface TrendPoint {
  date: string;
  revenue_fen: number;
  target_fen: number;
}

interface DailySummary {
  order_count: number;
  table_turnover: number;
  channel_breakdown: ChannelItem[];
}

interface ChannelItem {
  name: string;
  amount_fen: number;
  ratio: number;   // 0–100
  mom: number;     // 月环比 %
  color?: string;
}

interface StorePnl {
  store_id: string;
  store_name: string;
  revenue_fen: number;
  cost_fen: number;
  gross_profit_fen: number;
  gross_margin: number; // 0–100
  rank: number;
}

interface ChecklistStore {
  store_id: string;
  store_name: string;
  completed: number;   // 0–8
  items: ChecklistItem[];
}

interface ChecklistItem {
  code: string; // E1–E8
  name: string;
  done: boolean;
}

interface Store {
  store_id: string;
  store_name: string;
}

// ─── Mock 数据已移除，所有数据通过 API 加载 ───

const EMPTY_PNL: PnlData = { revenue_fen: 0, cost_fen: 0, gross_profit_fen: 0, gross_margin: 0 };
const EMPTY_SUMMARY: DailySummary = { order_count: 0, table_turnover: 0, channel_breakdown: [] };

// ─── 子组件：指标卡片 ───

interface KpiCardProps {
  label: string;
  value: string;
  sub: string;
  trendValue: number;    // 正=涨，负=跌
  trendLabel: string;
  accentColor: string;
  warn?: boolean;        // 低于阈值时橙色警告边框
}

function KpiCard({ label, value, sub, trendValue, trendLabel, accentColor, warn }: KpiCardProps) {
  const up = trendValue >= 0;
  const trendColor = up ? C.success : C.danger;
  const borderColor = warn ? C.warning : accentColor;
  return (
    <div style={{
      background: C.cardBg,
      borderRadius: 8,
      padding: 20,
      borderLeft: `3px solid ${borderColor}`,
      minWidth: 0,
    }}>
      <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 'bold', color: warn ? C.warning : C.text }}>{value}</div>
      <div style={{ fontSize: 12, color: C.textDim, marginBottom: 6 }}>{sub}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: trendColor }}>
        <span>{up ? '▲' : '▼'}</span>
        <span>{Math.abs(trendValue).toFixed(1)}% {trendLabel}</span>
      </div>
    </div>
  );
}

// ─── 子组件：渠道明细行 ───
interface ChannelRowProps {
  item: ChannelItem;
}

function ChannelRow({ item }: ChannelRowProps) {
  const up = item.mom >= 0;
  return (
    <tr style={{ borderTop: `1px solid ${C.border}` }}>
      <td style={{ padding: '10px 8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: item.color || C.primary, flexShrink: 0, display: 'inline-block' }} />
          <span style={{ fontSize: 13, color: C.textSub }}>{item.name}</span>
        </div>
      </td>
      <td style={{ padding: '10px 8px', textAlign: 'right', color: C.text, fontWeight: 600, fontSize: 13 }}>
        ¥{(item.amount_fen / 100).toLocaleString()}
      </td>
      <td style={{ padding: '10px 8px', textAlign: 'right', color: C.textMuted, fontSize: 12 }}>
        {item.ratio.toFixed(1)}%
      </td>
      <td style={{ padding: '10px 8px', textAlign: 'right', fontSize: 12, color: up ? C.success : C.danger }}>
        {up ? '+' : ''}{item.mom.toFixed(1)}%
      </td>
    </tr>
  );
}

// ─── 子组件：P&L表格行 ───
interface PnlRowProps {
  row: StorePnl;
}

function PnlRow({ row }: PnlRowProps) {
  const mc = marginColor(row.gross_margin);
  const isLow = row.gross_margin < 35;
  return (
    <tr style={{ borderTop: `1px solid ${C.border}` }}>
      <td style={{ padding: '10px 8px', fontWeight: 'bold', color: row.rank <= 3 ? C.primary : C.textDim, textAlign: 'center' }}>
        {row.rank}
      </td>
      <td style={{ padding: '10px 8px', color: C.textSub, fontSize: 13 }}>{row.store_name}</td>
      <td style={{ padding: '10px 8px', textAlign: 'right', color: C.text, fontSize: 13 }}>
        ¥{(row.revenue_fen / 100).toLocaleString()}
      </td>
      <td style={{ padding: '10px 8px', textAlign: 'right', color: C.textMuted, fontSize: 13 }}>
        ¥{(row.cost_fen / 100).toLocaleString()}
      </td>
      <td style={{ padding: '10px 8px', textAlign: 'right', color: C.text, fontWeight: 600, fontSize: 13 }}>
        ¥{(row.gross_profit_fen / 100).toLocaleString()}
      </td>
      <td style={{ padding: '10px 8px', textAlign: 'right' }}>
        <span style={{
          padding: '2px 10px',
          borderRadius: 10,
          fontSize: 11,
          fontWeight: 700,
          background: `${mc}20`,
          color: mc,
          border: isLow ? `1px solid ${C.danger}` : 'none',
        }}>
          {fmtPct(row.gross_margin)}
        </span>
      </td>
    </tr>
  );
}

// ─── 子组件：日清日结卡片 ───
interface ChecklistCardProps {
  store: ChecklistStore;
}

function ChecklistCard({ store }: ChecklistCardProps) {
  const [expanded, setExpanded] = useState(false);
  const pct = (store.completed / 8) * 100;
  const barColor = pct === 100 ? C.success : pct >= 50 ? C.primary : C.danger;
  return (
    <div style={{ background: C.innerBg, borderRadius: 8, padding: 14, cursor: 'pointer' }} onClick={() => setExpanded(!expanded)}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: C.textSub, fontWeight: 600 }}>{store.store_name}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: store.completed < 8 ? C.danger : C.success, fontWeight: 700 }}>
            {store.completed}/8
            {store.completed < 8 && (
              <span style={{
                marginLeft: 6,
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: C.danger,
                display: 'inline-block',
                verticalAlign: 'middle',
              }} />
            )}
          </span>
          <span style={{ fontSize: 11, color: C.textDim }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>
      {/* 进度条 */}
      <div style={{ height: 6, borderRadius: 3, background: C.border, overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${pct}%`,
          borderRadius: 3,
          background: barColor,
          transition: 'width 0.4s ease',
        }} />
      </div>
      {/* 展开明细 */}
      {expanded && (
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
          {store.items.map((item) => (
            <div key={item.code} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 11,
              color: item.done ? C.success : C.danger,
            }}>
              <span>{item.done ? '✓' : '✗'}</span>
              <span>{item.code}</span>
              <span style={{ color: C.textDim, fontSize: 10 }}>{item.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ───

export function OperationsDashboardPage() {
  const [selectedDate, setSelectedDate] = useState(today());
  const [selectedStores, setSelectedStores] = useState<string[]>([]);  // 空=全部
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(new Date());

  // 数据 state（初始为空，由 API 填充）
  const [pnl, setPnl] = useState<PnlData>(EMPTY_PNL);
  const [yesterdayPnl, setYesterdayPnl] = useState<PnlData>(EMPTY_PNL);
  const [summary, setSummary] = useState<DailySummary>(EMPTY_SUMMARY);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [storePnl, setStorePnl] = useState<StorePnl[]>([]);
  const [checklist, setChecklist] = useState<ChecklistStore[]>([]);
  const [stores, setStores] = useState<Store[]>([]);
  const [sortByMargin, setSortByMargin] = useState(false);

  // 数据加载
  const loadData = useCallback(async () => {
    setLoading(true);
    const storeParam = selectedStores.length > 0 ? selectedStores[0] : 's1';

    // 昨日日期（用于对比）
    const d = new Date(selectedDate);
    d.setDate(d.getDate() - 1);
    const yesterday = d.toISOString().slice(0, 10);

    try {
      const [storesRes, pnlRes, yPnlRes, summaryRes, trendRes, compareRes, checklistRes] = await Promise.allSettled([
        txFetch<{ items: Store[] }>('/api/v1/trade/stores/realtime-status'),
        txFetch<PnlData>(`/api/v1/finance/pnl/calculate?store_id=${storeParam}&date=${selectedDate}`),
        txFetch<PnlData>(`/api/v1/finance/pnl/calculate?store_id=${storeParam}&date=${yesterday}`),
        txFetch<DailySummary>(`/api/v1/ops/daily-summary?store_id=${storeParam}&date=${selectedDate}`),
        txFetch<{ items: TrendPoint[] }>(`/api/v1/finance/pnl/trend?store_id=${storeParam}&days=30`),
        txFetch<{ items: StorePnl[] }>(`/api/v1/ops/dashboard`),
        txFetch<{ items: ChecklistStore[] }>(`/api/v1/ops/settlement/checklist?date=${selectedDate}`),
      ]);

      if (storesRes.status === 'fulfilled' && storesRes.value.data?.items) setStores(storesRes.value.data.items);
      if (pnlRes.status === 'fulfilled' && pnlRes.value.data) setPnl(pnlRes.value.data);
      if (yPnlRes.status === 'fulfilled' && yPnlRes.value.data) setYesterdayPnl(yPnlRes.value.data);
      if (summaryRes.status === 'fulfilled' && summaryRes.value.data) setSummary(summaryRes.value.data);
      if (trendRes.status === 'fulfilled' && trendRes.value.data?.items) setTrend(trendRes.value.data.items);
      if (compareRes.status === 'fulfilled' && compareRes.value.data?.items) setStorePnl(compareRes.value.data.items);
      if (checklistRes.status === 'fulfilled' && checklistRes.value.data?.items) setChecklist(checklistRes.value.data.items);
    } catch {
      // 保持空数据
    }

    setLastRefresh(new Date());
    setLoading(false);
  }, [selectedDate, selectedStores]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 门店 P&L 排序
  const sortedStorePnl = [...storePnl].sort((a, b) =>
    sortByMargin ? b.gross_margin - a.gross_margin : a.rank - b.rank,
  ).map((s, i) => ({ ...s, rank: i + 1 }));

  // 营收趋势图数据
  const trendLabels = trend.map((p) => p.date.slice(5)); // MM-DD
  const trendActual = trend.map((p) => p.revenue_fen / 100);
  const trendTarget = trend.map((p) => p.target_fen / 100);

  // 渠道饼图数据
  const pieData = summary.channel_breakdown.map((c) => ({
    name: c.name,
    value: c.amount_fen,
    color: c.color,
  }));

  // 昨日对比
  const revenueTrend = yesterdayPnl.revenue_fen > 0
    ? ((pnl.revenue_fen - yesterdayPnl.revenue_fen) / yesterdayPnl.revenue_fen) * 100
    : 0;
  const marginTarget = 45;
  const marginDiff = pnl.gross_margin - marginTarget;
  // 订单环比：yesterdayPnl 暂无 order_count，用 0 表示
  const orderTrend = 0;
  // turnover 环比暂用 0，后续可从 API 返回
  const turnoverTrend = 0;

  // 门店选择器（受控）
  const allStores = stores;
  const storeLabel = selectedStores.length === 0
    ? '全部门店'
    : selectedStores.map((id) => allStores.find(s => s.store_id === id)?.store_name || id).join('、');

  const handleStoreToggle = (storeId: string) => {
    setSelectedStores((prev) =>
      prev.includes(storeId) ? prev.filter((s) => s !== storeId) : [...prev, storeId],
    );
  };

  return (
    <div style={{ padding: 24, minWidth: 1024 }}>
      {/* ── 标题行 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ margin: 0, color: C.text, fontSize: 20 }}>经营驾驶舱</h2>
          <span style={{
            fontSize: 11, color: C.textDim, background: C.innerBg,
            padding: '2px 8px', borderRadius: 4, border: `1px solid ${C.border}`,
          }}>
            P&L 版 · {lastRefresh.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })} 更新
          </span>
          {loading && (
            <span style={{ fontSize: 11, color: C.primary }}>加载中...</span>
          )}
        </div>
        <button
          onClick={loadData}
          style={{
            padding: '6px 16px', borderRadius: 6, border: 'none',
            background: C.primary, color: '#fff', cursor: 'pointer',
            fontSize: 12, fontWeight: 600,
          }}
        >
          一键刷新
        </button>
      </div>

      {/* ── 筛选栏 ── */}
      <div style={{
        background: C.cardBg, borderRadius: 8, padding: '12px 16px',
        marginBottom: 20, display: 'flex', alignItems: 'center', gap: 20,
        flexWrap: 'wrap',
      }}>
        {/* 日期选择 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: C.textMuted }}>日期</span>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            style={{
              background: C.innerBg, border: `1px solid ${C.border}`,
              borderRadius: 4, padding: '4px 10px', color: C.textSub,
              fontSize: 12, cursor: 'pointer',
            }}
          />
        </div>

        {/* 门店选择 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: C.textMuted }}>门店</span>
          <div style={{ position: 'relative' }}>
            <div style={{
              background: C.innerBg, border: `1px solid ${C.border}`,
              borderRadius: 4, padding: '4px 10px', color: C.textSub,
              fontSize: 12, minWidth: 120,
            }}>
              {storeLabel}
            </div>
          </div>
          {/* 门店多选按钮组 */}
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              onClick={() => setSelectedStores([])}
              style={{
                padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                fontSize: 11, fontWeight: 600,
                background: selectedStores.length === 0 ? C.primary : C.innerBg,
                color: selectedStores.length === 0 ? '#fff' : C.textMuted,
              }}
            >
              全部
            </button>
            {allStores.map((s) => (
              <button
                key={s.store_id}
                onClick={() => handleStoreToggle(s.store_id)}
                style={{
                  padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                  fontSize: 11, fontWeight: 600,
                  background: selectedStores.includes(s.store_id) ? C.primary : C.innerBg,
                  color: selectedStores.includes(s.store_id) ? '#fff' : C.textMuted,
                }}
              >
                {s.store_name}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── 1. 关键指标卡片行（4个）── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20 }}>
        <KpiCard
          label="今日营收"
          value={fmt10k(pnl.revenue_fen)}
          sub="万元"
          trendValue={revenueTrend}
          trendLabel="较昨日"
          accentColor={C.primary}
        />
        <KpiCard
          label="毛利率"
          value={fmtPct(pnl.gross_margin)}
          sub={`目标 ${marginTarget}%`}
          trendValue={marginDiff}
          trendLabel={`vs 目标 ${marginTarget}%`}
          accentColor={marginColor(pnl.gross_margin)}
          warn={pnl.gross_margin < 40}
        />
        <KpiCard
          label="今日订单数"
          value={`${summary.order_count}`}
          sub="单"
          trendValue={orderTrend}
          trendLabel="较昨日"
          accentColor={C.info}
        />
        <KpiCard
          label="翻台率"
          value={`${summary.table_turnover.toFixed(1)}`}
          sub="次/天"
          trendValue={turnoverTrend}
          trendLabel="较上周同期"
          accentColor={C.success}
        />
      </div>

      {/* ── 2. 营收趋势图（30天）── */}
      <div style={{ background: C.cardBg, borderRadius: 8, padding: 20, marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16, color: C.text }}>近30天营收趋势</h3>
          <span style={{ fontSize: 11, color: C.textDim }}>实际营收 vs 目标营收</span>
        </div>
        <TxLineChart
          data={{
            labels: trendLabels,
            datasets: [
              { name: '实际营收', values: trendActual, color: C.primary },
              { name: '目标营收', values: trendTarget, color: C.info },
            ],
          }}
          height={260}
          showArea
          unit="元"
        />
      </div>

      {/* ── 3. 渠道营收饼图 + 明细表 ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        {/* 饼图 */}
        <div style={{ background: C.cardBg, borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16, color: C.text }}>各渠道营收分布</h3>
          <TxPieChart
            data={pieData}
            size={160}
            donut
            unit="元"
            title="今日"
          />
        </div>

        {/* 明细表 */}
        <div style={{ background: C.cardBg, borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16, color: C.text }}>渠道明细</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ padding: '8px', textAlign: 'left', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>渠道</th>
                <th style={{ padding: '8px', textAlign: 'right', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>金额</th>
                <th style={{ padding: '8px', textAlign: 'right', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>占比</th>
                <th style={{ padding: '8px', textAlign: 'right', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>月环比</th>
              </tr>
            </thead>
            <tbody>
              {summary.channel_breakdown.map((item) => (
                <ChannelRow key={item.name} item={item} />
              ))}
            </tbody>
          </table>
          {/* 合计行 */}
          <div style={{
            marginTop: 12, paddingTop: 12, borderTop: `1px solid ${C.border}`,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span style={{ fontSize: 12, color: C.textMuted, fontWeight: 600 }}>合计</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: C.primary }}>
              ¥{(pnl.revenue_fen / 100).toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      {/* ── 4. 门店P&L对比表 ── */}
      <div style={{ background: C.cardBg, borderRadius: 8, padding: 20, marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16, color: C.text }}>门店 P&L 对比</h3>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: C.textMuted }}>排序：</span>
            <button
              onClick={() => setSortByMargin(false)}
              style={{
                padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                fontSize: 11, fontWeight: 600,
                background: !sortByMargin ? C.primary : C.innerBg,
                color: !sortByMargin ? '#fff' : C.textMuted,
              }}
            >
              默认
            </button>
            <button
              onClick={() => setSortByMargin(true)}
              style={{
                padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                fontSize: 11, fontWeight: 600,
                background: sortByMargin ? C.primary : C.innerBg,
                color: sortByMargin ? '#fff' : C.textMuted,
              }}
            >
              毛利率↓
            </button>
          </div>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ padding: '8px', textAlign: 'center', fontSize: 11, color: C.textMuted, fontWeight: 600, width: 40 }}>#</th>
              <th style={{ padding: '8px', textAlign: 'left', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>门店</th>
              <th style={{ padding: '8px', textAlign: 'right', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>营收</th>
              <th style={{ padding: '8px', textAlign: 'right', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>成本</th>
              <th style={{ padding: '8px', textAlign: 'right', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>毛利</th>
              <th style={{ padding: '8px', textAlign: 'right', fontSize: 11, color: C.textMuted, fontWeight: 600 }}>毛利率</th>
            </tr>
          </thead>
          <tbody>
            {sortedStorePnl.map((row) => (
              <PnlRow key={row.store_id} row={row} />
            ))}
          </tbody>
        </table>

        {/* 说明：低于35%红色警告 */}
        <div style={{ marginTop: 12, fontSize: 11, color: C.textDim }}>
          <span style={{ color: C.danger, marginRight: 4 }}>●</span>毛利率 &lt; 35% 红色警告边框
          <span style={{ color: C.warning, margin: '0 4px 0 12px' }}>●</span>35%–45% 橙色提示
          <span style={{ color: C.success, margin: '0 4px 0 12px' }}>●</span>≥ 45% 绿色健康
        </div>
      </div>

      {/* ── 5. 日清日结 E1-E8 完成状态 ── */}
      <div style={{ background: C.cardBg, borderRadius: 8, padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16, color: C.text }}>日清日结完成状态（E1-E8）</h3>
          <div style={{ display: 'flex', gap: 12, fontSize: 12, color: C.textMuted, alignItems: 'center' }}>
            <span>
              全完成：
              <span style={{ color: C.success, fontWeight: 700, marginLeft: 4 }}>
                {checklist.filter((s) => s.completed === 8).length}/{checklist.length}
              </span>
              家门店
            </span>
            <span>
              未完成项：
              <span style={{ color: C.danger, fontWeight: 700, marginLeft: 4 }}>
                {checklist.reduce((sum, s) => sum + (8 - s.completed), 0)}
              </span>
              项
            </span>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {checklist.map((store) => (
            <ChecklistCard key={store.store_id} store={store} />
          ))}
        </div>

        {/* E1-E8 说明 */}
        <div style={{
          marginTop: 16, padding: 12, background: C.innerBg, borderRadius: 6,
          display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6,
        }}>
          {E_NAMES.map((name, idx) => (
            <div key={`E${idx + 1}`} style={{ fontSize: 11, color: C.textDim }}>
              <span style={{ color: C.textMuted, fontWeight: 600 }}>E{idx + 1}</span>
              {' '}{name}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
