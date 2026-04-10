/**
 * 请假申请 — 员工端 PWA
 * 路由: /me/leave/new
 * API: POST /api/v1/leave-requests
 */
import { useState } from 'react';
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

const LEAVE_TYPES = [
  { key: 'annual',   label: '年假',   icon: '🏖' },
  { key: 'personal', label: '事假',   icon: '📋' },
  { key: 'sick',     label: '病假',   icon: '🏥' },
  { key: 'comp',     label: '调休',   icon: '🔄' },
];

function buildHeaders(): HeadersInit {
  const tenantId = localStorage.getItem('tenantId') ?? '';
  return {
    'Content-Type': 'application/json',
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
  };
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

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export function CrewLeaveNew() {
  const navigate = useNavigate();

  const [leaveType, setLeaveType] = useState('');
  const [startDate, setStartDate] = useState(todayStr);
  const [endDate, setEndDate] = useState(todayStr);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState('');

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }

  async function handleSubmit() {
    if (!leaveType) { showToast('请选择请假类型'); return; }
    if (!startDate || !endDate) { showToast('请选择日期'); return; }
    if (endDate < startDate) { showToast('结束日期不能早于开始日期'); return; }

    setSubmitting(true);
    try {
      await apiPost('/api/v1/leave-requests', {
        leave_type: leaveType,
        start_date: startDate,
        end_date: endDate,
        reason: reason.trim(),
      });
      showToast('请假申请已提交');
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
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>请假申请</h1>
        <div style={{ width: 48 }} />
      </div>

      {/* 请假类型 */}
      <div style={{ fontSize: 14, color: T.muted, marginBottom: 10 }}>请假类型</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 20 }}>
        {LEAVE_TYPES.map(lt => (
          <div
            key={lt.key}
            style={{
              background: leaveType === lt.key ? T.primary + '22' : T.card,
              border: `2px solid ${leaveType === lt.key ? T.primary : T.border}`,
              borderRadius: 12, padding: 16, textAlign: 'center', cursor: 'pointer',
              minHeight: 48,
            }}
            onClick={() => setLeaveType(lt.key)}
          >
            <div style={{ fontSize: 24, marginBottom: 4 }}>{lt.icon}</div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{lt.label}</div>
          </div>
        ))}
      </div>

      {/* 日期选择 */}
      <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>开始日期</div>
      <input
        type="date"
        value={startDate}
        onChange={e => setStartDate(e.target.value)}
        style={{
          width: '100%', height: 48, background: T.card, color: T.text,
          border: `1px solid ${T.border}`, borderRadius: 12, padding: '0 14px',
          fontSize: 16, boxSizing: 'border-box', marginBottom: 12,
          colorScheme: 'dark',
        }}
      />

      <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>结束日期</div>
      <input
        type="date"
        value={endDate}
        onChange={e => setEndDate(e.target.value)}
        style={{
          width: '100%', height: 48, background: T.card, color: T.text,
          border: `1px solid ${T.border}`, borderRadius: 12, padding: '0 14px',
          fontSize: 16, boxSizing: 'border-box', marginBottom: 16,
          colorScheme: 'dark',
        }}
      />

      {/* 原因 */}
      <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>请假原因</div>
      <textarea
        value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder="请输入请假原因（可选）..."
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
        {submitting ? '提交中...' : '提交请假申请'}
      </div>

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

export default CrewLeaveNew;
