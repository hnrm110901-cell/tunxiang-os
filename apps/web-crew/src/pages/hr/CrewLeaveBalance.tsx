/**
 * 假期余额 — 员工端 PWA
 * 路由: /me/leave/balance
 * API: GET /api/v1/leave-requests/balance
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
  warning:  '#FF9F0A',
};

interface LeaveBalanceItem {
  type: string;
  label: string;
  total: number;
  used: number;
  remaining: number;
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

const typeColors: Record<string, string> = {
  annual: T.success,
  personal: T.warning,
  sick: '#4A9EFF',
  comp: T.primary,
};

function CircleProgress({ used, total, color }: { used: number; total: number; color: string }) {
  const pct = total > 0 ? Math.min(used / total, 1) : 0;
  const r = 36;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - pct);

  return (
    <svg width={88} height={88} viewBox="0 0 88 88">
      <circle cx="44" cy="44" r={r} fill="none" stroke={T.border} strokeWidth="6" />
      <circle
        cx="44" cy="44" r={r} fill="none" stroke={color} strokeWidth="6"
        strokeDasharray={`${c}`} strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 44 44)"
      />
      <text x="44" y="40" textAnchor="middle" fill={T.text} fontSize="16" fontWeight="700">
        {total - used}
      </text>
      <text x="44" y="56" textAnchor="middle" fill={T.muted} fontSize="11">
        剩余
      </text>
    </svg>
  );
}

export function CrewLeaveBalance() {
  const navigate = useNavigate();

  const [items, setItems] = useState<LeaveBalanceItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<LeaveBalanceItem[]>('/api/v1/leave-requests/balance');
      setItems(data);
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
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>假期余额</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {items.map(item => {
          const color = typeColors[item.type] ?? T.primary;
          return (
            <div key={item.type} style={{
              background: T.card, borderRadius: 12, padding: 16,
              border: `1px solid ${T.border}`, textAlign: 'center',
            }}>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>{item.label}</div>
              <CircleProgress used={item.used} total={item.total} color={color} />
              <div style={{ fontSize: 13, color: T.muted, marginTop: 8 }}>
                已用 {item.used} / 总计 {item.total}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default CrewLeaveBalance;
