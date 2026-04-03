/**
 * 经营驾驶舱 -- 实时经营总览（增强版）
 * 顶部4个KPI卡片 | 中间营收趋势（按小时+对比昨日）
 * 左下门店排名（可切换维度）| 右下AI决策推荐TOP3
 * 30秒自动轮询
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { TxLineChart } from '../../../components/charts';
import {
  fetchDashboardOverview,
  fetchStoreRanking,
  fetchTop3Decisions,
} from '../../../api';
import type { OverviewKPI, StoreRankItem } from '../../../api/dashboardApi';
import type { DecisionSuggestion } from '../../../api';

// ---------- 门店排名维度 ----------
type RankDimension = 'revenue' | 'avg_ticket' | 'turnover';
const RANK_LABELS: Record<RankDimension, string> = {
  revenue: '营收',
  avg_ticket: '客单价',
  turnover: '翻台率',
};

// ---------- Mock fallback ----------
const MOCK_KPI: OverviewKPI[] = [
  { label: '今日营收', value: 2856000, formatted: '\u00A528,560', trend_percent: 12.3, trend_up: true },
  { label: '订单数', value: 426, formatted: '426', trend_percent: 8.1, trend_up: true },
  { label: '客单价', value: 6700, formatted: '\u00A567.0', trend_percent: 3.2, trend_up: true },
  { label: '翻台率', value: 2.8, formatted: '2.8', trend_percent: -7.1, trend_up: false },
];

const MOCK_HOURLY_TODAY = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1200, 2800, 5600, 12800, 18500, 19200, 20100, 21000, 23400, 26000, 27800, 28560, 0, 0, 0];
const MOCK_HOURLY_YESTERDAY = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1000, 2400, 4800, 11200, 16200, 17000, 17800, 18500, 20100, 22800, 24200, 25420, 0, 0, 0];

const MOCK_STORES: StoreRankItem[] = [
  { rank: 1, store_id: 's1', store_name: '芙蓉路店', revenue_fen: 8560000, order_count: 128, turnover_rate: 3.2, health_score: 92 },
  { rank: 2, store_id: 's2', store_name: '岳麓店', revenue_fen: 6400000, order_count: 96, turnover_rate: 2.8, health_score: 78 },
  { rank: 3, store_id: 's3', store_name: '星沙店', revenue_fen: 5200000, order_count: 78, turnover_rate: 2.4, health_score: 65 },
  { rank: 4, store_id: 's4', store_name: '河西店', revenue_fen: 3800000, order_count: 57, turnover_rate: 1.9, health_score: 45 },
  { rank: 5, store_id: 's5', store_name: '开福店', revenue_fen: 3420000, order_count: 51, turnover_rate: 2.1, health_score: 58 },
];

const MOCK_DECISIONS: DecisionSuggestion[] = [
  {
    decision_id: 'd1', agent_id: 'discount-guard', title: '河西店折扣异常',
    description: '河西店午市折扣率达38%，超过安全阈值30%。建议暂停"午市满100减40"活动，改为满150减30。',
    priority: 'critical', confidence: 0.92,
  },
  {
    decision_id: 'd2', agent_id: 'inventory-alert', title: '鲈鱼备货不足',
    description: '岳麓店鲈鱼库存仅剩2份，预计今日需求12份。建议紧急补货或标记临时沽清。',
    priority: 'warning', confidence: 0.87,
  },
  {
    decision_id: 'd3', agent_id: 'smart-menu', title: '推荐上架新品',
    description: '根据近7天客户搜索数据，"酸菜鱼"搜索量上升46%，建议芙蓉路店/岳麓店上架试销。',
    priority: 'info', confidence: 0.78,
  },
];

// ---------- 工具 ----------
const scoreColor = (s: number) => s >= 80 ? '#0F6E56' : s >= 60 ? '#BA7517' : '#A32D2D';
const priorityColor: Record<string, string> = { critical: '#A32D2D', warning: '#BA7517', info: '#185FA5' };
const priorityLabel: Record<string, string> = { critical: '紧急', warning: '建议', info: '洞察' };

const POLL_INTERVAL = 30_000;

// ---------- 组件 ----------
export function OpsDashboardPage() {
  const [dateRange, setDateRange] = useState<'today' | 'week' | 'month'>('today');
  const [kpis, setKpis] = useState<OverviewKPI[]>(MOCK_KPI);
  const [stores, setStores] = useState<StoreRankItem[]>(MOCK_STORES);
  const [decisions, setDecisions] = useState<DecisionSuggestion[]>(MOCK_DECISIONS);
  const [rankDimension, setRankDimension] = useState<RankDimension>('revenue');
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  // 数据拉取
  const loadData = useCallback(async () => {
    try {
      const [overviewRes, storeRes, decRes] = await Promise.allSettled([
        fetchDashboardOverview(),
        fetchStoreRanking(dateRange === 'today' ? 'day' : dateRange === 'week' ? 'week' : 'month'),
        fetchTop3Decisions('all'),
      ]);
      if (overviewRes.status === 'fulfilled') setKpis(overviewRes.value.items);
      if (storeRes.status === 'fulfilled') setStores(storeRes.value.items);
      if (decRes.status === 'fulfilled') setDecisions(decRes.value);
    } catch {
      // keep mock data on failure
    }
    setLastRefresh(new Date());
  }, [dateRange]);

  // 30秒轮询
  useEffect(() => {
    loadData();
    timerRef.current = setInterval(loadData, POLL_INTERVAL);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loadData]);

  // 门店排序
  const sortedStores = [...stores].sort((a, b) => {
    if (rankDimension === 'revenue') return b.revenue_fen - a.revenue_fen;
    if (rankDimension === 'avg_ticket') return (b.revenue_fen / (b.order_count || 1)) - (a.revenue_fen / (a.order_count || 1));
    return b.turnover_rate - a.turnover_rate;
  }).map((s, i) => ({ ...s, rank: i + 1 }));

  // 小时标签 09:00-21:00
  const hourLabels = Array.from({ length: 13 }, (_, i) => `${(i + 9).toString().padStart(2, '0')}:00`);
  const todaySlice = MOCK_HOURLY_TODAY.slice(9, 22);
  const yesterdaySlice = MOCK_HOURLY_YESTERDAY.slice(9, 22);

  const dateLabels: Record<string, string> = { today: '今日', week: '本周', month: '本月' };

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ margin: 0 }}>经营驾驶舱</h2>
          <span style={{ fontSize: 11, color: '#666', background: '#1a2a33', padding: '2px 8px', borderRadius: 4 }}>
            {lastRefresh.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })} 更新
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['today', 'week', 'month'] as const).map((d) => (
            <button key={d} onClick={() => setDateRange(d)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: dateRange === d ? '#FF6B2C' : '#1a2a33',
              color: dateRange === d ? '#fff' : '#999',
            }}>
              {dateLabels[d]}
            </button>
          ))}
        </div>
      </div>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {kpis.map((kpi) => (
          <div key={kpi.label} style={{
            background: '#112228', borderRadius: 8, padding: 20,
            borderLeft: '3px solid #FF6B2C',
          }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
            <div style={{ fontSize: 28, fontWeight: 'bold', color: '#fff' }}>{kpi.formatted}</div>
            <div style={{
              fontSize: 12, marginTop: 4, display: 'flex', alignItems: 'center', gap: 4,
              color: kpi.trend_up ? '#0F6E56' : '#A32D2D',
            }}>
              <span style={{ fontSize: 14 }}>{kpi.trend_up ? '\u2191' : '\u2193'}</span>
              {Math.abs(kpi.trend_percent).toFixed(1)}% 较昨日同期
            </div>
          </div>
        ))}
      </div>

      {/* 营收趋势（按小时对比昨日） */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>营收趋势（今日 vs 昨日同期）</h3>
        <TxLineChart
          data={{
            labels: hourLabels,
            datasets: [
              { name: '今日', values: todaySlice, color: '#FF6B2C' },
              { name: '昨日', values: yesterdaySlice, color: '#185FA5' },
            ],
          }}
          height={280}
          showArea
          unit="元"
        />
      </div>

      {/* 下半区：门店排名 + AI决策推荐 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 门店排名 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>门店排名</h3>
            <div style={{ display: 'flex', gap: 6 }}>
              {(Object.keys(RANK_LABELS) as RankDimension[]).map((dim) => (
                <button key={dim} onClick={() => setRankDimension(dim)} style={{
                  padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                  fontSize: 11, fontWeight: 600,
                  background: rankDimension === dim ? '#FF6B2C' : '#0B1A20',
                  color: rankDimension === dim ? '#fff' : '#999',
                }}>
                  {RANK_LABELS[dim]}
                </button>
              ))}
            </div>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                <th style={{ padding: '8px 4px' }}>#</th>
                <th style={{ padding: '8px 4px' }}>门店</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>
                  {rankDimension === 'revenue' ? '营收' : rankDimension === 'avg_ticket' ? '客单价' : '翻台率'}
                </th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>单量</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>评分</th>
              </tr>
            </thead>
            <tbody>
              {sortedStores.map((s) => {
                const dimValue = rankDimension === 'revenue'
                  ? `\u00A5${(s.revenue_fen / 100).toLocaleString()}`
                  : rankDimension === 'avg_ticket'
                    ? `\u00A5${(s.revenue_fen / (s.order_count || 1) / 100).toFixed(1)}`
                    : s.turnover_rate.toFixed(1);
                return (
                  <tr key={s.store_id} style={{ borderTop: '1px solid #1a2a33' }}>
                    <td style={{ padding: '10px 4px', fontWeight: 'bold', color: s.rank <= 3 ? '#FF6B2C' : '#666' }}>{s.rank}</td>
                    <td style={{ padding: '10px 4px' }}>{s.store_name}</td>
                    <td style={{ padding: '10px 4px', textAlign: 'right', fontWeight: 600 }}>{dimValue}</td>
                    <td style={{ padding: '10px 4px', textAlign: 'right', color: '#999' }}>{s.order_count}</td>
                    <td style={{ padding: '10px 4px', textAlign: 'right' }}>
                      <span style={{
                        padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                        background: `${scoreColor(s.health_score)}20`, color: scoreColor(s.health_score),
                      }}>{s.health_score}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* AI 决策推荐 TOP3 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>
              AI 决策推荐
              <span style={{ fontSize: 11, color: '#185FA5', marginLeft: 8 }}>TOP 3</span>
            </h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {decisions.map((d, idx) => {
              const pColor = priorityColor[d.priority] || '#185FA5';
              return (
                <div key={d.decision_id} style={{
                  padding: 16, borderRadius: 8, background: '#0B1A20',
                  borderLeft: `3px solid ${pColor}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{
                        fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 700,
                        background: `${pColor}20`, color: pColor,
                      }}>
                        {priorityLabel[d.priority] || d.priority}
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{d.title}</span>
                    </div>
                    <span style={{ fontSize: 10, color: '#666' }}>
                      置信度 {(d.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: '#999', lineHeight: 1.6 }}>{d.description}</div>
                  <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                    <button style={{
                      padding: '4px 12px', borderRadius: 4, border: 'none', cursor: 'pointer',
                      fontSize: 11, fontWeight: 600, background: pColor, color: '#fff',
                    }}>
                      采纳执行
                    </button>
                    <button style={{
                      padding: '4px 12px', borderRadius: 4, border: '1px solid #2a3a43',
                      cursor: 'pointer', fontSize: 11, fontWeight: 600, background: 'transparent', color: '#999',
                    }}>
                      稍后处理
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
