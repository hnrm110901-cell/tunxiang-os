/**
 * 我的积分 — 员工端 PWA
 * 路由: /me/points
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const T = {
  bg:       '#0B1A20',
  card:     '#112228',
  border:   '#1a2a33',
  text:     '#E0E0E0',
  muted:    '#64748b',
  dim:      '#334155',
  primary:  '#FF6B35',
  success:  '#30D158',
  danger:   '#FF453A',
};

interface PointsOverview {
  balance: number;
  month_earned: number;
  month_consumed: number;
  rank: number;
  total_employees: number;
}

function buildHeaders(): HeadersInit {
  const tenantId = localStorage.getItem('tenantId') ?? '';
  return {
    'Content-Type': 'application/json',
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
  };
}

async function apiGet<R>(url: string): Promise<R> {
  const res = await fetch(url, { headers: buildHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json() as { ok: boolean; data: R };
  if (!json.ok) throw new Error('API error');
  return json.data;
}

export function CrewMyPoints() {
  const navigate = useNavigate();

  const [data, setData] = useState<PointsOverview | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet<PointsOverview>('/api/v1/points/overview');
      setData(d);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的积分</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {data && (
        <>
          {/* 余额大数字 */}
          <div style={{
            background: T.card, borderRadius: 12, padding: 24, marginBottom: 16,
            border: `1px solid ${T.border}`, textAlign: 'center',
          }}>
            <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>积分余额</div>
            <div style={{ fontSize: 48, fontWeight: 800, color: T.primary }}>{data.balance}</div>
          </div>

          {/* 本月统计 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
            <div style={{
              background: T.card, borderRadius: 12, padding: 16,
              border: `1px solid ${T.border}`, textAlign: 'center',
            }}>
              <div style={{ fontSize: 13, color: T.muted }}>本月获取</div>
              <div style={{ fontSize: 28, fontWeight: 700, color: T.success, marginTop: 4 }}>+{data.month_earned}</div>
            </div>
            <div style={{
              background: T.card, borderRadius: 12, padding: 16,
              border: `1px solid ${T.border}`, textAlign: 'center',
            }}>
              <div style={{ fontSize: 13, color: T.muted }}>本月消耗</div>
              <div style={{ fontSize: 28, fontWeight: 700, color: T.danger, marginTop: 4 }}>-{data.month_consumed}</div>
            </div>
          </div>

          {/* 排名 */}
          <div style={{
            background: T.card, borderRadius: 12, padding: 16, marginBottom: 16,
            border: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between',
            alignItems: 'center', minHeight: 48,
          }}>
            <div style={{ fontSize: 16 }}>门店排名</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: T.primary }}>
              第 {data.rank} 名
              <span style={{ fontSize: 14, color: T.muted, fontWeight: 400 }}> / {data.total_employees}人</span>
            </div>
          </div>

          {/* 查看积分流水 */}
          <div
            style={{
              background: T.card, borderRadius: 12, padding: 16,
              border: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', cursor: 'pointer', minHeight: 48,
            }}
            onClick={() => navigate('/me/points/history')}
          >
            <div style={{ fontSize: 16 }}>积分流水</div>
            <div style={{ fontSize: 16, color: T.muted }}>→</div>
          </div>
        </>
      )}
    </div>
  );
}

export default CrewMyPoints;
