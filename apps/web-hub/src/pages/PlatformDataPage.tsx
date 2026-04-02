/**
 * 平台数据（GET /api/v1/hub/platform/stats）
 */
import { useEffect, useState } from 'react';
import { hubGet } from '../api/hubApi';

const s = {
  page: { color: '#E0E0E0' } as React.CSSProperties,
  title: { fontSize: 22, fontWeight: 700, color: '#FFFFFF', marginBottom: 20 } as React.CSSProperties,
  cards: { display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  card: {
    flex: '1 1 200px', background: '#0D2129', borderRadius: 10, padding: '18px 20px',
    border: '1px solid #1A3540',
  } as React.CSSProperties,
  cardLabel: { fontSize: 12, color: '#6B8A97', marginBottom: 6 } as React.CSSProperties,
  cardValue: { fontSize: 28, fontWeight: 700, color: '#FF6B2C' } as React.CSSProperties,
  row: { display: 'flex', gap: 24, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  section: {
    flex: '1 1 320px', background: '#0D2129', borderRadius: 10, padding: 20,
    border: '1px solid #1A3540',
  } as React.CSSProperties,
  sectionTitle: { fontSize: 14, fontWeight: 600, color: '#FFFFFF', marginBottom: 16 } as React.CSSProperties,
  toolbar: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } as React.CSSProperties,
  btnSec: {
    background: 'transparent', color: '#FF6B2C', border: '1px solid #FF6B2C', borderRadius: 6,
    padding: '6px 14px', fontSize: 12, cursor: 'pointer', marginLeft: 6,
  } as React.CSSProperties,
  table: { width: '100%', borderCollapse: 'collapse' as const, fontSize: 13 } as React.CSSProperties,
  th: {
    textAlign: 'left' as const, padding: '10px 12px', borderBottom: '1px solid #1A3540',
    color: '#6B8A97', fontWeight: 600, fontSize: 12,
  } as React.CSSProperties,
  td: { padding: '10px 12px', borderBottom: '1px solid #112A33' } as React.CSSProperties,
  err: { color: '#EF4444', fontSize: 13, marginBottom: 12 } as React.CSSProperties,
};

type HubPlatformStats = {
  total_merchants: number;
  total_stores: number;
  active_stores_today: number;
  total_orders_today: number;
  gmv_today_yuan: number;
  agent_calls_today: number;
  avg_response_ms: number;
};

export function PlatformDataPage() {
  const [stats, setStats] = useState<HubPlatformStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    hubGet<HubPlatformStats>('/platform/stats')
      .then((d) => {
        if (!cancelled) {
          setStats(d);
          setErr(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message || '加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const gmvWan = stats ? stats.gmv_today_yuan / 10000 : 0;

  return (
    <div style={s.page}>
      <div style={s.title}>平台数据</div>
      {err && <div style={s.err}>{err}</div>}
      {loading && <div style={{ color: '#6B8A97', marginBottom: 16 }}>加载中…</div>}
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>商户总数</div><div style={s.cardValue}>{stats?.total_merchants ?? '—'}</div></div>
        <div style={s.card}><div style={s.cardLabel}>门店总数</div><div style={{ ...s.cardValue, color: '#3B82F6' }}>{stats?.total_stores ?? '—'}</div></div>
        <div style={s.card}><div style={s.cardLabel}>今日GMV</div><div style={{ ...s.cardValue, color: '#22C55E' }}>{stats ? `${gmvWan.toFixed(1)}万` : '—'}</div></div>
        <div style={s.card}><div style={s.cardLabel}>今日订单</div><div style={{ ...s.cardValue, color: '#A855F7' }}>{stats?.total_orders_today?.toLocaleString() ?? '—'}</div></div>
      </div>

      <div style={s.row}>
        <div style={s.section}>
          <div style={s.sectionTitle}>今日运营</div>
          <div style={{ fontSize: 13, color: '#8BA5B2', lineHeight: 2.0 }}>
            <div>在营门店（今日）：<strong style={{ color: '#FFFFFF' }}>{stats?.active_stores_today ?? '—'}</strong></div>
            <div>Agent 调用次数：<strong style={{ color: '#FFFFFF' }}>{stats?.agent_calls_today?.toLocaleString() ?? '—'}</strong></div>
            <div>接口平均响应：<strong style={{ color: '#FFFFFF' }}>{stats?.avg_response_ms ?? '—'} ms</strong></div>
          </div>
        </div>
        <div style={s.section}>
          <div style={s.sectionTitle}>说明</div>
          <div style={{ fontSize: 13, color: '#8BA5B2', lineHeight: 2.0 }}>
            数据来自网关 Hub 演示接口；后续可替换为真实数仓汇总。
          </div>
        </div>
      </div>

      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>平台汇总指标</div>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>指标</th>
            <th style={s.th}>数值</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={s.td}>今日 GMV（元）</td>
            <td style={s.td}>{stats?.gmv_today_yuan?.toLocaleString() ?? '—'}</td>
            <td style={s.td}><button type="button" style={s.btnSec}>查看详情</button></td>
          </tr>
          <tr>
            <td style={s.td}>今日订单数</td>
            <td style={s.td}>{stats?.total_orders_today?.toLocaleString() ?? '—'}</td>
            <td style={s.td}><button type="button" style={s.btnSec}>查看详情</button></td>
          </tr>
          <tr>
            <td style={s.td}>Agent 调用</td>
            <td style={s.td}>{stats?.agent_calls_today?.toLocaleString() ?? '—'}</td>
            <td style={s.td}><button type="button" style={s.btnSec}>查看详情</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
