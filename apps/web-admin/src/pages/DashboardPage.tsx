/**
 * 经营驾驶舱 — 商户首屏
 * 从 tx-analytics BFF 拉取真实数据：KPI + 门店健康 + 告警
 */
import { useState, useEffect } from 'react';
import { txFetch, getTokenPayload } from '../api/client';

const fen2yuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;

interface DailyReport {
  revenue_fen: number;
  order_count: number;
  avg_ticket_fen: number;
  guest_count: number;
  discount_total_fen: number;
  channel_breakdown: Record<string, number>;
}

interface StoreHealth {
  store_id: string;
  store_name: string;
  overall_score: number;
  revenue_score: number;
  turnover_score: number;
  cost_score: number;
  complaint_score: number;
  efficiency_score: number;
}

interface KPIAlert {
  metric: string;
  message: string;
  severity: string;
}
import { useEffect, useState } from 'react';
import { txFetch } from '../api';

// ─── 类型 ───

interface DashboardKPI {
  revenue_fen: number;
  order_count: number;
  avg_order_fen: number;
  cost_rate: number | null;
}

interface DashboardStore {
  store_id: string;
  store_name: string;
  today_revenue_fen: number;
  today_orders: number;
  status: string;
}

interface DashboardDecision {
  id: string;
  agent_id: string;
  action: string;
  decision_type: string | null;
  confidence: number | null;
  created_at: string | null;
}

interface DashboardSummary {
  kpi: DashboardKPI;
  stores: DashboardStore[];
  decisions: DashboardDecision[];
  generated_at: string;
}

// ─── 工具函数 ───

const fen2yuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN')}`;

const statusColor: Record<string, string> = {
  excellent: '#52c41a',
  good: '#1890ff',
  warning: '#faad14',
  critical: '#ff4d4f',
  active: '#52c41a',
  inactive: '#faad14',
  unknown: '#666',
};

// ─── 骨架占位 ───

function SkeletonCard() {
  return (
    <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
      <div style={{ height: 12, width: '40%', background: '#1a2a33', borderRadius: 4, marginBottom: 12 }} />
      <div style={{ height: 28, width: '60%', background: '#1a2a33', borderRadius: 4, marginBottom: 8 }} />
      <div style={{ height: 12, width: '30%', background: '#1a2a33', borderRadius: 4 }} />
    </div>
  );
}

function SkeletonRow() {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #1a2a33' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#1a2a33' }} />
        <div style={{ height: 14, width: 80, background: '#1a2a33', borderRadius: 4 }} />
      </div>
      <div style={{ height: 14, width: 60, background: '#1a2a33', borderRadius: 4 }} />
    </div>
  );
}

// ─── 主组件 ───

export function DashboardPage() {
  const payload = getTokenPayload();
  const merchantName = payload?.merchant_name || '商户';

  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [stores, setStores] = useState<StoreHealth[]>([]);
  const [alerts, setAlerts] = useState<KPIAlert[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadDashboard() {
      setLoading(true);
      setError(null);

      try {
        const healthResp = await txFetch<{ scores: StoreHealth[] }>('/api/v1/analytics/stores/health?store_id=all');
        if (!cancelled && healthResp.data?.scores) {
          setStores(healthResp.data.scores);
        }
      } catch (e) {
        if (!cancelled) setStores([]);
      }

      try {
        const reportResp = await txFetch<{ report: DailyReport }>('/api/v1/analytics/reports/daily?store_id=all&date=today');
        if (!cancelled && reportResp.data?.report) {
          setReport(reportResp.data.report);
        }
      } catch (e) {
        if (!cancelled) setReport(null);
      }

      try {
        const alertResp = await txFetch<{ alerts: KPIAlert[] }>('/api/v1/analytics/kpi/alerts?store_id=all');
        if (!cancelled && alertResp.data?.alerts) {
          setAlerts(alertResp.data.alerts);
        }
      } catch (e) {
        if (!cancelled) setAlerts([]);
      }

      if (!cancelled) setLoading(false);
    }

    loadDashboard();
    return () => { cancelled = true; };
  }, []);

  const kpiCards = [
    { label: '今日营收', value: report ? fen2yuan(report.revenue_fen) : '--', color: '#FF6B2C' },
    { label: '订单数', value: report ? `${report.order_count} 单` : '--', color: '#1890ff' },
    { label: '客单价', value: report ? fen2yuan(report.avg_ticket_fen) : '--', color: '#722ed1' },
    { label: '客流', value: report ? `${report.guest_count} 人` : '--', color: '#52c41a' },
  ];

  const scoreColor = (score: number) => {
    if (score >= 80) return '#52c41a';
    if (score >= 60) return '#1890ff';
    if (score >= 40) return '#faad14';
    return '#ff4d4f';
  };

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: '#999', paddingTop: 120 }}>
        <div style={{ fontSize: 18, marginBottom: 8 }}>加载中...</div>
        <div style={{ fontSize: 13 }}>正在获取 {merchantName} 的经营数据</div>
      </div>
    );
  }
    setLoading(true);
    setError(null);

    txFetch<DashboardSummary>('/api/v1/dashboard/summary')
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'API Error');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  // ─── KPI 卡片数据（真实 API → 展示结构）

  const kpiCards = summary
    ? [
        {
          label: '今日营收',
          value: fen2yuan(summary.kpi.revenue_fen),
          sub: `${summary.kpi.order_count.toLocaleString('zh-CN')} 单`,
          color: '#FF6B2C',
        },
        {
          label: '成本率',
          value: summary.kpi.cost_rate != null ? `${(summary.kpi.cost_rate * 100).toFixed(1)}%` : '--',
          sub: '今日综合',
          color: '#52c41a',
        },
        {
          label: '今日订单',
          value: summary.kpi.order_count > 0 ? summary.kpi.order_count.toLocaleString('zh-CN') : '--',
          sub: '笔',
          color: '#1890ff',
        },
        {
          label: '客单价',
          value: summary.kpi.avg_order_fen > 0 ? fen2yuan(summary.kpi.avg_order_fen) : '--',
          sub: '今日均值',
          color: '#722ed1',
        },
      ]
    : null;

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 4, fontSize: 20 }}>{merchantName} · 经营驾驶舱</h2>
      <p style={{ marginTop: 0, marginBottom: 20, fontSize: 12, color: '#666' }}>
        {new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}
      </p>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {kpiCards.map((kpi) => (
          <div key={kpi.label} style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            <div style={{ fontSize: 12, color: '#999' }}>{kpi.label}</div>
            <div style={{ fontSize: 28, fontWeight: 'bold', color: kpi.color, margin: '4px 0' }}>{kpi.value}</div>
          </div>
        ))}
      {error && (
        <div style={{
          background: '#2a1111', border: '1px solid #ff4d4f', borderRadius: 8,
          padding: '12px 16px', marginBottom: 16, color: '#ff4d4f', fontSize: 13,
        }}>
          数据加载失败：{error}，当前显示降级占位
        </div>
      )}

      {/* KPI 卡片行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {loading
          ? Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
          : (kpiCards ?? []).map((kpi) => (
              <div key={kpi.label} style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
                <div style={{ fontSize: 12, color: '#999' }}>{kpi.label}</div>
                <div style={{ fontSize: 28, fontWeight: 'bold', color: kpi.color, margin: '4px 0' }}>
                  {kpi.value}
                </div>
                <div style={{ fontSize: 12, color: '#666' }}>{kpi.sub}</div>
              </div>
            ))
        }
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 左：门店健康 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>门店健康度</h3>
          {stores.length > 0 ? stores.map((store, i) => (
            <div key={store.store_id || i} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 0', borderBottom: i < stores.length - 1 ? '1px solid #1a2a33' : 'none',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{
                  width: 32, height: 32, borderRadius: '50%',
                  background: scoreColor(store.overall_score), color: '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 13, fontWeight: 'bold',
                }}>{store.overall_score}</span>
                <div>
                  <div style={{ fontSize: 14 }}>{store.store_name}</div>
                  <div style={{ fontSize: 11, color: '#666' }}>
                    营收{store.revenue_score} · 翻台{store.turnover_score} · 成本{store.cost_score}
                  </div>
                </div>
              </div>
            </div>
          )) : (
            <div style={{ color: '#666', fontSize: 13, padding: 20, textAlign: 'center' }}>
              暂无门店数据，请先运行数据同步
            </div>
          )}
        </div>

        {/* 右：告警 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>经营告警</h3>
          {alerts.length > 0 ? alerts.map((alert, i) => (
            <div key={i} style={{
              padding: 12, marginBottom: 8, borderRadius: 8, background: '#0B1A20',
              border: `1px solid ${alert.severity === 'critical' ? '#ff4d4f' : alert.severity === 'warning' ? '#faad14' : '#1a2a33'}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: alert.severity === 'critical' ? '#ff4d4f' : '#faad14',
                }} />
                <span style={{ fontSize: 14 }}>{alert.message}</span>
              </div>
              <div style={{ fontSize: 11, color: '#666', marginTop: 4, paddingLeft: 16 }}>
                指标: {alert.metric}
              </div>
            </div>
          )) : (
            <div style={{ color: '#52c41a', fontSize: 13, padding: 20, textAlign: 'center' }}>
              当前无告警，经营状态良好
            </div>
          <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>门店健康度排名</h3>
          {loading
            ? Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)
            : summary && summary.stores.length > 0
              ? summary.stores.map((store, i) => (
                  <div key={store.store_id} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 0',
                    borderBottom: i < summary.stores.length - 1 ? '1px solid #1a2a33' : 'none',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{
                        width: 28, height: 28, borderRadius: '50%',
                        background: statusColor[store.status] ?? '#666',
                        color: '#fff',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 12, fontWeight: 'bold',
                      }}>{i + 1}</span>
                      <div>
                        <div style={{ fontSize: 14 }}>{store.store_name}</div>
                        <div style={{ fontSize: 11, color: '#666' }}>{store.today_orders} 单</div>
                      </div>
                    </div>
                    <div style={{ fontSize: 14, color: '#999' }}>{fen2yuan(store.today_revenue_fen)}</div>
                  </div>
                ))
              : (
                  <div style={{ color: '#666', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                    暂无门店数据
                  </div>
                )
          }
        </div>

        {/* 右：AI 决策日志 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>近期 AI 决策记录</h3>
          {loading
            ? Array.from({ length: 3 }).map((_, i) => (
                <div key={i} style={{
                  padding: 12, marginBottom: 8, borderRadius: 8, background: '#0B1A20',
                  border: '1px solid #1a2a33',
                }}>
                  <div style={{ height: 14, width: '70%', background: '#1a2a33', borderRadius: 4, marginBottom: 8 }} />
                  <div style={{ height: 11, width: '40%', background: '#1a2a33', borderRadius: 4 }} />
                </div>
              ))
            : summary && summary.decisions.length > 0
              ? summary.decisions.map((d, idx) => (
                  <div key={d.id} style={{
                    padding: 12, marginBottom: 8, borderRadius: 8, background: '#0B1A20',
                    border: '1px solid #1a2a33',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{
                          width: 24, height: 24, borderRadius: '50%', background: '#FF6B2C',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 12, fontWeight: 'bold',
                        }}>#{idx + 1}</span>
                        <span style={{ fontSize: 14 }}>{d.action}</span>
                      </div>
                      {d.confidence != null && (
                        <span style={{ color: '#52c41a', fontWeight: 'bold', fontSize: 13 }}>
                          {(d.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: '#666' }}>
                      <span>Agent: {d.agent_id}</span>
                      <span>置信度: {d.confidence != null ? `${(d.confidence * 100).toFixed(0)}%` : '--'}</span>
                    </div>
                  </div>
                ))
              : (
                  <div style={{ color: '#666', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                    暂无决策记录
                  </div>
                )
          }
          {summary && summary.decisions.length > 0 && (
            <div style={{ textAlign: 'center', marginTop: 12 }}>
              <span style={{ color: '#999', fontSize: 12 }}>
                更新于 {summary.generated_at ? new Date(summary.generated_at).toLocaleTimeString('zh-CN') : '--'}
              </span>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div style={{ marginTop: 16, padding: 12, background: 'rgba(255,77,79,0.1)', borderRadius: 8, color: '#ff4d4f', fontSize: 13 }}>
          {error}
        </div>
      )}
    </div>
  );
}
