/**
 * 积分流水 — 员工端 PWA
 * 路由: /me/points/history
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const T = {
  bg:       '#0B1A20',
  card:     '#112228',
  border:   '#1a2a33',
  text:     '#E0E0E0',
  muted:    '#64748b',
  primary:  '#FF6B35',
  success:  '#30D158',
  danger:   '#FF453A',
};

interface PointsRecord {
  id: string;
  date: string;
  type: string;
  direction: 'earn' | 'consume';
  amount: number;
  reason: string;
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

export function CrewPointsHistory() {
  const navigate = useNavigate();

  const [records, setRecords] = useState<PointsRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<PointsRecord[]>('/api/v1/points/history?employee_id=me');
      setRecords(data);
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
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>积分流水</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {!loading && records.length === 0 && (
        <div style={{ textAlign: 'center', color: T.muted, padding: 48, fontSize: 16 }}>暂无积分记录</div>
      )}

      {records.map(r => (
        <div key={r.id} style={{
          background: T.card, borderRadius: 12, padding: 14, marginBottom: 8,
          border: `1px solid ${T.border}`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{r.type}</div>
            <div style={{ fontSize: 13, color: T.muted, marginTop: 4 }}>{r.date} · {r.reason}</div>
          </div>
          <div style={{
            fontSize: 20, fontWeight: 700,
            color: r.direction === 'earn' ? T.success : T.danger,
          }}>
            {r.direction === 'earn' ? '+' : '-'}{r.amount}
          </div>
        </div>
      ))}
    </div>
  );
}

export default CrewPointsHistory;
