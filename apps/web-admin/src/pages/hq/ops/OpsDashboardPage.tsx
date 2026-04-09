/**
 * 经营驾驶舱 -- 实时经营总览（增强版）
 * 顶部4个KPI卡片 | 中间营收趋势（按小时+对比昨日）
 * 左下门店排名（可切换维度）| 右下AI决策推荐TOP3
 * 30秒自动轮询
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { Alert, Button } from 'antd';
import { TxLineChart } from '../../../components/charts';
import { txFetch } from '../../../api';

// ---------- 类型定义 ----------
interface OverviewKPI {
  label: string;
  value: number;
  formatted: string;
  trend_percent: number;
  trend_up: boolean;
}

interface StoreRankItem {
  rank: number;
  store_id: string;
  store_name: string;
  revenue_fen: number;
  order_count: number;
  turnover_rate: number;
  health_score: number;
}

interface DecisionSuggestion {
  decision_id: string;
  agent_id: string;
  title: string;
  description: string;
  priority: string;
  confidence: number;
}

interface HourlyTrend {
  today: number[];
  yesterday: number[];
}

// ---------- 门店排名维度 ----------
type RankDimension = 'revenue' | 'avg_ticket' | 'turnover';
const RANK_LABELS: Record<RankDimension, string> = {
  revenue: '营收',
  avg_ticket: '客单价',
  turnover: '翻台率',
};

// ---------- 工具 ----------
const scoreColor = (s: number) => s >= 80 ? '#0F6E56' : s >= 60 ? '#BA7517' : '#A32D2D';
const priorityColor: Record<string, string> = { critical: '#A32D2D', warning: '#BA7517', info: '#185FA5' };
const priorityLabel: Record<string, string> = { critical: '紧急', warning: '建议', info: '洞察' };

const POLL_INTERVAL = 30_000;

// ---------- 组件 ----------
export function OpsDashboardPage() {
  const [dateRange, setDateRange] = useState<'today' | 'week' | 'month'>('today');
  const [kpis, setKpis] = useState<OverviewKPI[]>([]);
  const [stores, setStores] = useState<StoreRankItem[]>([]);
  const [decisions, setDecisions] = useState<DecisionSuggestion[]>([]);
  const [hourlyTrend, setHourlyTrend] = useState<HourlyTrend>({ today: Array(13).fill(0), yesterday: Array(13).fill(0) });
  const [rankDimension, setRankDimension] = useState<RankDimension>('revenue');
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  // 数据拉取
  const loadData = useCallback(async () => {
    setLoading(true);
    const period = dateRange === 'today' ? 'day' : dateRange === 'week' ? 'week' : 'month';
    try {
      const [kpiRes, alertsRes, agentRes, rankRes, trendRes] = await Promise.allSettled([
        txFetch<{ items: OverviewKPI[] }>(`/api/v1/ops/dashboard/kpi?period=${period}`),
        txFetch<{ items: StoreRankItem[] }>(`/api/v1/ops/dashboard/store-ranking?period=${period}`),
        txFetch<{ items: DecisionSuggestion[] }>('/api/v1/brain/decisions/recent?limit=10'),
        txFetch<{ items: StoreRankItem[] }>(`/api/v1/analytics/alerts?status=active&level=critical&period=${period}`),
        txFetch<HourlyTrend>('/api/v1/ops/dashboard/hourly-trend'),
      ]);
      if (kpiRes.status === 'fulfilled') setKpis(kpiRes.value.data?.items ?? []);
      if (alertsRes.status === 'fulfilled') setStores(alertsRes.value.data?.items ?? []);
      if (agentRes.status === 'fulfilled') setDecisions(agentRes.value.data?.items ?? []);
      if (rankRes.status === 'fulfilled') setStores(rankRes.value.data?.items ?? []);
      if (trendRes.status === 'fulfilled' && trendRes.value.data) setHourlyTrend(trendRes.value.data);
    } catch {
      // 保持空数据
    }
    setLoading(false);
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
  const todaySlice = hourlyTrend.today.length >= 13 ? hourlyTrend.today.slice(0, 13) : hourlyTrend.today;
  const yesterdaySlice = hourlyTrend.yesterday.length >= 13 ? hourlyTrend.yesterday.slice(0, 13) : hourlyTrend.yesterday;

  const dateLabels: Record<string, string> = { today: '今日', week: '本周', month: '本月' };

  return (
    <div>
      {/* AI 预警条 */}
      <Alert
        type="warning"
        showIcon
        banner
        message="🤖 tx-ops 运营指挥官：福田中心店午市翻台率低于目标 23%，建议立即查看并调整排班"
        action={<Button size="small" type="primary" style={{ background: '#FF6B35', border: 'none' }}>查看建议</Button>}
        style={{ marginBottom: 16 }}
        closable
      />
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
