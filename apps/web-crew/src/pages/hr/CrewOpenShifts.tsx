/**
 * 可接班次 — 员工端 PWA
 * 路由: /me/schedule/open-shifts
 * API: GET /api/v1/schedules/gaps?store_id=&status=open
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

interface OpenShift {
  id: string;
  date: string;
  time_range: string;
  position: string;
  urgency: 'critical' | 'urgent' | 'normal';
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

async function apiPost<R>(url: string, body: unknown): Promise<R> {
  const res = await fetch(url, {
    method: 'POST', headers: buildHeaders(), body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json() as { ok: boolean; data: R };
  if (!json.ok) throw new Error('API error');
  return json.data;
}

const urgencyConfig: Record<OpenShift['urgency'], { label: string; color: string; bg: string }> = {
  critical: { label: '紧急', color: T.danger, bg: '#2a1215' },
  urgent:   { label: '较急', color: T.warning, bg: '#1f1a08' },
  normal:   { label: '普通', color: '#4A9EFF', bg: '#0a1a2a' },
};

export function CrewOpenShifts() {
  const navigate = useNavigate();
  const storeId = localStorage.getItem('storeId') ?? '';

  const [shifts, setShifts] = useState<OpenShift[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);
  const [toast, setToast] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<OpenShift[]>(`/api/v1/schedules/gaps?store_id=${storeId}&status=open`);
      setShifts(data);
    } catch { /* ignore */ }
    setLoading(false);
  }, [storeId]);

  useEffect(() => { void load(); }, [load]);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }

  async function handleClaim(id: string) {
    setClaiming(true);
    try {
      await apiPost('/api/v1/schedules/claim', { gap_id: id });
      showToast('认领成功');
      setShifts(prev => prev.filter(s => s.id !== id));
    } catch {
      showToast('认领失败，请重试');
    }
    setClaiming(false);
    setConfirmId(null);
  }

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>可接班次</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {!loading && shifts.length === 0 && (
        <div style={{ textAlign: 'center', color: T.muted, padding: 48, fontSize: 16 }}>暂无可接班次</div>
      )}

      {shifts.map(s => {
        const uc = urgencyConfig[s.urgency];
        return (
          <div key={s.id} style={{
            background: T.card, borderRadius: 12, padding: 16, marginBottom: 10,
            border: `1px solid ${T.border}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{s.date}</div>
                <div style={{ fontSize: 14, color: T.muted, marginTop: 4 }}>{s.time_range} · {s.position}</div>
              </div>
              <span style={{
                fontSize: 12, padding: '4px 10px', borderRadius: 6,
                background: uc.bg, color: uc.color,
              }}>{uc.label}</span>
            </div>
            <div
              style={{
                marginTop: 12, background: T.primary, color: '#fff', fontSize: 16,
                fontWeight: 600, textAlign: 'center', borderRadius: 8, height: 48,
                lineHeight: '48px', cursor: 'pointer',
              }}
              onClick={() => setConfirmId(s.id)}
            >
              认领
            </div>
          </div>
        );
      })}

      {/* 确认弹窗 */}
      {confirmId && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }}>
          <div style={{
            background: T.card, borderRadius: 12, padding: 24, width: '80%', maxWidth: 320,
          }}>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 16, textAlign: 'center' }}>确认认领？</div>
            <div style={{ fontSize: 16, color: T.muted, marginBottom: 24, textAlign: 'center' }}>
              认领后将自动排入您的班表
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <div
                style={{
                  flex: 1, height: 48, lineHeight: '48px', textAlign: 'center',
                  borderRadius: 8, background: T.dim, color: T.text, cursor: 'pointer', fontSize: 16,
                }}
                onClick={() => setConfirmId(null)}
              >取消</div>
              <div
                style={{
                  flex: 1, height: 48, lineHeight: '48px', textAlign: 'center',
                  borderRadius: 8, background: T.primary, color: '#fff', cursor: 'pointer',
                  fontSize: 16, opacity: claiming ? 0.6 : 1,
                }}
                onClick={() => !claiming && void handleClaim(confirmId)}
              >{claiming ? '认领中...' : '确认'}</div>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div style={{
          position: 'fixed', bottom: 100, left: '50%', transform: 'translateX(-50%)',
          background: '#333', color: '#fff', padding: '10px 24px', borderRadius: 8,
          fontSize: 16, zIndex: 100,
        }}>{toast}</div>
      )}
    </div>
  );
}

export default CrewOpenShifts;
