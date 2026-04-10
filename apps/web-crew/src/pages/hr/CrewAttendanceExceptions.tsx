/**
 * 异常申诉 — 员工端 PWA
 * 路由: /me/attendance/exceptions
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
  warning:  '#FF9F0A',
  danger:   '#FF453A',
};

interface ExceptionRecord {
  id: string;
  date: string;
  type: string;
  description: string;
  appeal_status: 'none' | 'pending' | 'approved' | 'rejected';
  appeal_reason: string | null;
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

const appealStatusConfig: Record<ExceptionRecord['appeal_status'], { label: string; color: string }> = {
  none:     { label: '未申诉', color: T.muted },
  pending:  { label: '待审核', color: T.warning },
  approved: { label: '已通过', color: T.success },
  rejected: { label: '已驳回', color: T.danger },
};

export function CrewAttendanceExceptions() {
  const navigate = useNavigate();

  const [records, setRecords] = useState<ExceptionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [appealId, setAppealId] = useState<string | null>(null);
  const [appealReason, setAppealReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<ExceptionRecord[]>('/api/v1/attendance/exceptions?employee_id=me');
      setRecords(data);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }

  async function handleAppeal() {
    if (!appealId || !appealReason.trim()) { showToast('请填写申诉原因'); return; }
    setSubmitting(true);
    try {
      await apiPost('/api/v1/attendance/appeal', {
        exception_id: appealId,
        reason: appealReason.trim(),
      });
      showToast('申诉已提交');
      setRecords(prev => prev.map(r =>
        r.id === appealId ? { ...r, appeal_status: 'pending' as const, appeal_reason: appealReason.trim() } : r
      ));
      setAppealId(null);
      setAppealReason('');
    } catch {
      showToast('提交失败');
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
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>异常申诉</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {!loading && records.length === 0 && (
        <div style={{ textAlign: 'center', color: T.muted, padding: 48, fontSize: 16 }}>暂无异常记录</div>
      )}

      {records.map(r => {
        const sc = appealStatusConfig[r.appeal_status];
        return (
          <div key={r.id} style={{
            background: T.card, borderRadius: 12, padding: 16, marginBottom: 10,
            border: `1px solid ${T.border}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{r.date}</div>
                <div style={{ fontSize: 14, color: T.muted, marginTop: 4 }}>{r.type} — {r.description}</div>
              </div>
              <span style={{
                fontSize: 12, padding: '3px 8px', borderRadius: 4,
                background: sc.color + '22', color: sc.color,
              }}>{sc.label}</span>
            </div>
            {r.appeal_reason && (
              <div style={{ fontSize: 14, color: T.muted, marginTop: 8, padding: '8px 12px', background: T.bg, borderRadius: 8 }}>
                申诉原因：{r.appeal_reason}
              </div>
            )}
            {r.appeal_status === 'none' && (
              <div
                style={{
                  marginTop: 12, background: T.primary, color: '#fff', fontSize: 16,
                  fontWeight: 600, textAlign: 'center', borderRadius: 8, height: 48,
                  lineHeight: '48px', cursor: 'pointer',
                }}
                onClick={() => { setAppealId(r.id); setAppealReason(''); }}
              >发起申诉</div>
            )}
          </div>
        );
      })}

      {/* 申诉弹窗 */}
      {appealId && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
        }}>
          <div style={{ background: T.card, borderRadius: 12, padding: 24, width: '85%', maxWidth: 360 }}>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>填写申诉原因</div>
            <textarea
              value={appealReason}
              onChange={e => setAppealReason(e.target.value)}
              placeholder="请描述异常原因..."
              style={{
                width: '100%', minHeight: 100, background: T.bg, color: T.text,
                border: `1px solid ${T.border}`, borderRadius: 8, padding: 12,
                fontSize: 16, resize: 'vertical', boxSizing: 'border-box',
              }}
            />
            <div style={{ fontSize: 14, color: T.muted, marginTop: 8, marginBottom: 16 }}>
              上传凭证功能即将开放
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <div
                style={{
                  flex: 1, height: 48, lineHeight: '48px', textAlign: 'center',
                  borderRadius: 8, background: T.dim, color: T.text, cursor: 'pointer', fontSize: 16,
                }}
                onClick={() => setAppealId(null)}
              >取消</div>
              <div
                style={{
                  flex: 1, height: 48, lineHeight: '48px', textAlign: 'center',
                  borderRadius: 8, background: T.primary, color: '#fff', cursor: 'pointer',
                  fontSize: 16, opacity: submitting ? 0.6 : 1,
                }}
                onClick={() => !submitting && void handleAppeal()}
              >{submitting ? '提交中...' : '提交'}</div>
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

export default CrewAttendanceExceptions;
