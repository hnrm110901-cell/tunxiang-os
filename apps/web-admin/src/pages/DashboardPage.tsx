/**
 * 经营驾驶舱 — 商户首屏
 *
 * 调用 /api/v1/dashboard/summary 获取 KPI + 门店排名 + AI决策记录
 * API 失败时使用空状态，不降级到假数据
 */
import { useState, useEffect } from 'react';
import { txFetch, getTokenPayload } from '../api/client';

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
  good:      '#1890ff',
  warning:   '#faad14',
  critical:  '#ff4d4f',
  active:    '#52c41a',
  inactive:  '#faad14',
  unknown:   '#666',
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

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    txFetch<DashboardSummary>('/api/v1/dashboard/summary')
      .then((resp) => {
        if (!cancelled) setSummary(resp.data ?? null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'API Error');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  // ─── KPI 卡片数据 ───

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

      {error && (
        <div style={{
          background: '#2a1111', border: '1px solid #ff4d4f', borderRadius: 8,
          padding: '12px 16px', marginBottom: 16, color: '#ff4d4f', fontSize: 13,
        }}>
          数据加载失败：{error}
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
        {/* 左：门店排名 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
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
                      <span>{d.created_at ? new Date(d.created_at).toLocaleTimeString('zh-CN') : '--'}</span>
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
    </div>
  );
}
