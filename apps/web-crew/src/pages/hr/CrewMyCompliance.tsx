/**
 * 我的证照 — 员工端 PWA
 * 路由: /me/compliance
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

interface CertItem {
  id: string;
  cert_name: string;
  cert_type: 'health' | 'food_safety' | 'contract' | 'other';
  status: 'valid' | 'expiring_soon' | 'expired';
  expires_at: string;
  days_left: number;
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

const statusConfig: Record<CertItem['status'], { label: string; color: string; bg: string }> = {
  valid:         { label: '有效',     color: T.success, bg: '#0a2820' },
  expiring_soon: { label: '即将到期', color: T.warning, bg: '#1f1a08' },
  expired:       { label: '已过期',   color: T.danger,  bg: '#2a1215' },
};

const typeLabels: Record<CertItem['cert_type'], string> = {
  health:      '健康证',
  food_safety: '食品安全证',
  contract:    '劳动合同',
  other:       '其他证照',
};

export function CrewMyCompliance() {
  const navigate = useNavigate();

  const [certs, setCerts] = useState<CertItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<CertItem[]>('/api/v1/compliance/my-certs');
      setCerts(data);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  // 即将到期和已过期的排前面
  const sorted = [...certs].sort((a, b) => {
    const order: Record<string, number> = { expired: 0, expiring_soon: 1, valid: 2 };
    return (order[a.status] ?? 3) - (order[b.status] ?? 3);
  });

  const alertCerts = sorted.filter(c => c.status === 'expiring_soon' || c.status === 'expired');

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的证照</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {/* 警告 Alert */}
      {alertCerts.length > 0 && (
        <div style={{
          background: '#2a1215', borderRadius: 12, padding: 14, marginBottom: 16,
          border: `1px solid ${T.danger}40`,
        }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: T.danger, marginBottom: 8 }}>
            证照提醒
          </div>
          {alertCerts.map(c => (
            <div key={c.id} style={{ fontSize: 14, color: T.text, marginBottom: 4 }}>
              {c.cert_name} — {c.status === 'expired' ? '已过期' : `剩余 ${c.days_left} 天`}
            </div>
          ))}
        </div>
      )}

      {/* 证照列表 */}
      {sorted.map(c => {
        const sc = statusConfig[c.status];
        return (
          <div key={c.id} style={{
            background: T.card, borderRadius: 12, padding: 16, marginBottom: 10,
            border: `1px solid ${T.border}`,
            borderLeft: `4px solid ${sc.color}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{c.cert_name}</div>
                <div style={{ fontSize: 13, color: T.muted, marginTop: 4 }}>{typeLabels[c.cert_type]}</div>
              </div>
              <span style={{
                fontSize: 12, padding: '4px 10px', borderRadius: 6,
                background: sc.bg, color: sc.color,
              }}>{sc.label}</span>
            </div>
            <div style={{ fontSize: 14, color: T.muted, marginTop: 8 }}>
              到期日：{c.expires_at}
              {c.status !== 'expired' && (
                <span style={{ marginLeft: 8, color: c.days_left <= 30 ? T.danger : T.muted }}>
                  (剩余 {c.days_left} 天)
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default CrewMyCompliance;
