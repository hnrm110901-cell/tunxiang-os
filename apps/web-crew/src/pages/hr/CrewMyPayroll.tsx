/**
 * 我的工资单 — 员工端 PWA
 * 路由: /me/payroll
 * API: GET /api/v1/payslips?employee_id=me
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
};

interface PayslipSummary {
  id: string;
  month: string;
  gross: number;
  net: number;
  status: 'pending' | 'paid' | 'confirmed';
}

interface PayslipDetail {
  base_salary: number;
  performance_bonus: number;
  allowance: number;
  social_insurance: number;
  housing_fund: number;
  tax: number;
  net: number;
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

function formatYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

const statusConfig: Record<PayslipSummary['status'], { label: string; color: string }> = {
  pending:   { label: '待发放', color: T.warning },
  paid:      { label: '已发放', color: T.success },
  confirmed: { label: '已确认', color: T.muted },
};

export function CrewMyPayroll() {
  const navigate = useNavigate();

  const [slips, setSlips] = useState<PayslipSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PayslipDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [toast, setToast] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<PayslipSummary[]>('/api/v1/payslips?employee_id=me');
      setSlips(data);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }

  async function toggleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(id);
    setDetailLoading(true);
    try {
      const d = await apiGet<PayslipDetail>(`/api/v1/payslips/${id}`);
      setDetail(d);
    } catch {
      setDetail(null);
    }
    setDetailLoading(false);
  }

  async function handleConfirm(id: string) {
    try {
      await apiPost(`/api/v1/payslips/${id}/confirm`, {});
      showToast('已确认');
      setSlips(prev => prev.map(s => s.id === id ? { ...s, status: 'confirmed' as const } : s));
    } catch {
      showToast('确认失败');
    }
  }

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的工资单</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {!loading && slips.length === 0 && (
        <div style={{ textAlign: 'center', color: T.muted, padding: 48, fontSize: 16 }}>暂无工资单</div>
      )}

      {slips.map(s => {
        const sc = statusConfig[s.status];
        const expanded = expandedId === s.id;
        return (
          <div key={s.id} style={{
            background: T.card, borderRadius: 12, marginBottom: 10,
            border: `1px solid ${T.border}`, overflow: 'hidden',
          }}>
            <div
              style={{
                padding: 16, cursor: 'pointer', display: 'flex',
                justifyContent: 'space-between', alignItems: 'center', minHeight: 48,
              }}
              onClick={() => void toggleExpand(s.id)}
            >
              <div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{s.month}</div>
                <div style={{ fontSize: 14, color: T.muted, marginTop: 4 }}>
                  应发 {formatYuan(s.gross)} · 实发 {formatYuan(s.net)}
                </div>
              </div>
              <span style={{
                fontSize: 12, padding: '3px 8px', borderRadius: 4,
                background: sc.color + '22', color: sc.color,
              }}>{sc.label}</span>
            </div>

            {expanded && (
              <div style={{ padding: '0 16px 16px', borderTop: `1px solid ${T.border}` }}>
                {detailLoading ? (
                  <div style={{ textAlign: 'center', color: T.muted, padding: 16 }}>加载中...</div>
                ) : detail ? (
                  <div style={{ paddingTop: 12 }}>
                    {[
                      { label: '基本工资', value: detail.base_salary, positive: true },
                      { label: '绩效奖金', value: detail.performance_bonus, positive: true },
                      { label: '补贴', value: detail.allowance, positive: true },
                      { label: '社保', value: detail.social_insurance, positive: false },
                      { label: '公积金', value: detail.housing_fund, positive: false },
                      { label: '个税', value: detail.tax, positive: false },
                    ].map(item => (
                      <div key={item.label} style={{
                        display: 'flex', justifyContent: 'space-between',
                        padding: '6px 0', fontSize: 14,
                      }}>
                        <span style={{ color: T.muted }}>{item.label}</span>
                        <span style={{ color: item.positive ? T.success : T.muted }}>
                          {item.positive ? '+' : '-'}{formatYuan(item.value)}
                        </span>
                      </div>
                    ))}
                    <div style={{
                      display: 'flex', justifyContent: 'space-between',
                      padding: '10px 0 0', fontSize: 16, fontWeight: 700,
                      borderTop: `1px solid ${T.border}`, marginTop: 6,
                    }}>
                      <span>实发</span>
                      <span style={{ color: T.primary }}>{formatYuan(detail.net)}</span>
                    </div>

                    {s.status === 'paid' && (
                      <div
                        style={{
                          marginTop: 12, background: T.primary, color: '#fff', fontSize: 16,
                          fontWeight: 600, textAlign: 'center', borderRadius: 8, height: 48,
                          lineHeight: '48px', cursor: 'pointer',
                        }}
                        onClick={() => void handleConfirm(s.id)}
                      >确认已阅</div>
                    )}
                  </div>
                ) : (
                  <div style={{ textAlign: 'center', color: T.muted, padding: 16 }}>加载失败</div>
                )}
              </div>
            )}
          </div>
        );
      })}

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

export default CrewMyPayroll;
