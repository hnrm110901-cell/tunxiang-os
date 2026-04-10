/**
 * 调班申请 — 员工端 PWA
 * 路由: /me/schedule/swap
 * API: POST /api/v1/schedules/swap
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
  primaryAct: '#E55A28',
  success:  '#30D158',
};

interface MyShift {
  id: string;
  date: string;
  shift_name: string;
  time_range: string;
}

interface Colleague {
  id: string;
  name: string;
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

export function CrewSwapRequest() {
  const navigate = useNavigate();
  const storeId = localStorage.getItem('storeId') ?? '';

  const [shifts, setShifts] = useState<MyShift[]>([]);
  const [colleagues, setColleagues] = useState<Colleague[]>([]);
  const [selectedShift, setSelectedShift] = useState('');
  const [selectedTarget, setSelectedTarget] = useState('');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState('');

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.allSettled([
        apiGet<MyShift[]>(`/api/v1/schedules/my-shifts?store_id=${storeId}`),
        apiGet<Colleague[]>(`/api/v1/employees/colleagues?store_id=${storeId}`),
      ]);
      if (s.status === 'fulfilled') setShifts(s.value);
      if (c.status === 'fulfilled') setColleagues(c.value);
    } catch { /* ignore */ }
  }, [storeId]);

  useEffect(() => { void load(); }, [load]);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }

  async function handleSubmit() {
    if (!selectedShift) { showToast('请选择班次'); return; }
    if (!reason.trim()) { showToast('请填写原因'); return; }
    setSubmitting(true);
    try {
      await apiPost('/api/v1/schedules/swap', {
        shift_id: selectedShift,
        target_employee_id: selectedTarget || null,
        reason: reason.trim(),
      });
      showToast('调班申请已提交');
      setTimeout(() => navigate(-1), 1200);
    } catch {
      showToast('提交失败，请重试');
    }
    setSubmitting(false);
  }

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>调班申请</h1>
        <div style={{ width: 48 }} />
      </div>

      {/* 选择班次 */}
      <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>选择要调的班次</div>
      <div style={{ marginBottom: 16 }}>
        {shifts.map(s => (
          <div
            key={s.id}
            style={{
              background: selectedShift === s.id ? T.primary + '22' : T.card,
              border: `1px solid ${selectedShift === s.id ? T.primary : T.border}`,
              borderRadius: 12, padding: 14, marginBottom: 8, cursor: 'pointer',
              minHeight: 48, display: 'flex', alignItems: 'center',
            }}
            onClick={() => setSelectedShift(s.id)}
          >
            <div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{s.date} {s.shift_name}</div>
              <div style={{ fontSize: 14, color: T.muted }}>{s.time_range}</div>
            </div>
          </div>
        ))}
        {shifts.length === 0 && (
          <div style={{ color: T.muted, textAlign: 'center', padding: 24, fontSize: 16 }}>暂无可调班次</div>
        )}
      </div>

      {/* 选择调换对象 */}
      <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>调换对象（可选）</div>
      <div style={{ marginBottom: 16 }}>
        <div
          style={{
            background: selectedTarget === '' ? T.primary + '22' : T.card,
            border: `1px solid ${selectedTarget === '' ? T.primary : T.border}`,
            borderRadius: 12, padding: 14, marginBottom: 8, cursor: 'pointer',
            minHeight: 48, display: 'flex', alignItems: 'center', fontSize: 16,
          }}
          onClick={() => setSelectedTarget('')}
        >
          空班（不指定对象）
        </div>
        {colleagues.map(c => (
          <div
            key={c.id}
            style={{
              background: selectedTarget === c.id ? T.primary + '22' : T.card,
              border: `1px solid ${selectedTarget === c.id ? T.primary : T.border}`,
              borderRadius: 12, padding: 14, marginBottom: 8, cursor: 'pointer',
              minHeight: 48, display: 'flex', alignItems: 'center', fontSize: 16,
            }}
            onClick={() => setSelectedTarget(c.id)}
          >
            {c.name}
          </div>
        ))}
      </div>

      {/* 原因 */}
      <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>调班原因</div>
      <textarea
        value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder="请输入调班原因..."
        style={{
          width: '100%', minHeight: 100, background: T.card, color: T.text,
          border: `1px solid ${T.border}`, borderRadius: 12, padding: 14,
          fontSize: 16, resize: 'vertical', boxSizing: 'border-box',
        }}
      />

      {/* 提交 */}
      <div
        style={{
          marginTop: 24, background: submitting ? T.primaryAct : T.primary,
          color: '#fff', fontSize: 18, fontWeight: 700, textAlign: 'center',
          borderRadius: 12, height: 72, lineHeight: '72px', cursor: submitting ? 'default' : 'pointer',
          opacity: submitting ? 0.6 : 1,
        }}
        onClick={submitting ? undefined : handleSubmit}
      >
        {submitting ? '提交中...' : '提交调班申请'}
      </div>

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: 100, left: '50%', transform: 'translateX(-50%)',
          background: '#333', color: '#fff', padding: '10px 24px', borderRadius: 8,
          fontSize: 16, zIndex: 100,
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}

export default CrewSwapRequest;
