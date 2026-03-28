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

export function DashboardPage() {
  const payload = getTokenPayload();
  const merchantName = payload?.merchant_name || '商户';

  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [stores, setStores] = useState<StoreHealth[]>([]);
  const [alerts, setAlerts] = useState<KPIAlert[]>([]);
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
