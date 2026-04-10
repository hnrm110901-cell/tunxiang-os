/**
 * 我的请假 — 员工端 PWA
 * 路由: /me/leave
 * API: GET /api/v1/leave-requests?employee_id=me
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
  warning:  '#FF9F0A',
  danger:   '#FF453A',
};

interface LeaveRecord {
  id: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
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

const statusConfig: Record<LeaveRecord['status'], { label: string; color: string }> = {
  pending:   { label: '待审批', color: T.warning },
  approved:  { label: '已通过', color: T.success },
  rejected:  { label: '已驳回', color: T.danger },
  cancelled: { label: '已取消', color: T.muted },
};

export function CrewMyLeave() {
  const navigate = useNavigate();

  const [records, setRecords] = useState<LeaveRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<LeaveRecord[]>('/api/v1/leave-requests?employee_id=me');
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
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的请假</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {!loading && records.length === 0 && (
        <div style={{ textAlign: 'center', color: T.muted, padding: 48, fontSize: 16 }}>暂无请假记录</div>
      )}

      {records.map(r => {
        const sc = statusConfig[r.status];
        return (
          <div key={r.id} style={{
            background: T.card, borderRadius: 12, padding: 16, marginBottom: 10,
            border: `1px solid ${T.border}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{r.leave_type}</div>
              <span style={{
                fontSize: 12, padding: '3px 8px', borderRadius: 4,
                background: sc.color + '22', color: sc.color,
              }}>{sc.label}</span>
            </div>
            <div style={{ fontSize: 14, color: T.muted, marginTop: 8 }}>
              {r.start_date} ~ {r.end_date}
            </div>
            {r.reason && (
              <div style={{ fontSize: 14, color: T.dim, marginTop: 4 }}>{r.reason}</div>
            )}
          </div>
        );
      })}

      {/* 新建请假 FAB */}
      <div
        style={{
          position: 'fixed', bottom: 80, right: 20,
          width: 56, height: 56, borderRadius: '50%',
          background: T.primary, color: '#fff', fontSize: 28,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', boxShadow: '0 4px 12px rgba(255,107,53,0.4)',
          zIndex: 50,
        }}
        onClick={() => navigate('/me/leave/new')}
      >+</div>
    </div>
  );
}

export default CrewMyLeave;
