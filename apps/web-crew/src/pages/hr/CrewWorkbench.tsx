/**
 * 我的工作台 — 员工端 PWA
 * 路由: /me
 *
 * 功能：今日班次、打卡状态、待处理事项、积分变动、证照提醒
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ─────────────────────────────────────────
   Tokens
───────────────────────────────────────── */
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

/* ─────────────────────────────────────────
   Types
───────────────────────────────────────── */
interface TodayShift {
  shift_name: string;
  time_range: string;
  position: string;
  start_time: string;
}

interface PendingItem {
  id: string;
  type: 'swap' | 'leave';
  title: string;
  created_at: string;
}

interface PointsSummary {
  today_earned: number;
  balance: number;
}

interface ComplianceAlert {
  id: string;
  cert_name: string;
  expires_at: string;
  days_left: number;
}

type ClockStatus = 'not_clocked' | 'clocked_in' | 'clocked_out';

/* ─────────────────────────────────────────
   API helpers
───────────────────────────────────────── */
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

/* ─────────────────────────────────────────
   工具
───────────────────────────────────────── */
function formatCountdown(startIso: string): string {
  const diff = new Date(startIso).getTime() - Date.now();
  if (diff <= 0) return '已开始';
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  return `${h}小时${m}分钟后`;
}

/* ─────────────────────────────────────────
   主页面
───────────────────────────────────────── */
export function CrewWorkbench() {
  const navigate = useNavigate();
  const storeId = localStorage.getItem('storeId') ?? '';

  const [shift, setShift] = useState<TodayShift | null>(null);
  const [clockStatus, setClockStatus] = useState<ClockStatus>('not_clocked');
  const [pending, setPending] = useState<PendingItem[]>([]);
  const [points, setPoints] = useState<PointsSummary>({ today_earned: 0, balance: 0 });
  const [alerts, setAlerts] = useState<ComplianceAlert[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, att, p, pt, al] = await Promise.allSettled([
        apiGet<TodayShift | null>(`/api/v1/schedules/today?store_id=${storeId}`),
        apiGet<{ status: ClockStatus }>(`/api/v1/attendance/today?store_id=${storeId}`),
        apiGet<PendingItem[]>('/api/v1/hr/pending-items'),
        apiGet<PointsSummary>('/api/v1/points/summary'),
        apiGet<ComplianceAlert[]>('/api/v1/compliance/alerts'),
      ]);
      if (s.status === 'fulfilled') setShift(s.value);
      if (att.status === 'fulfilled') setClockStatus(att.value.status);
      if (p.status === 'fulfilled') setPending(p.value);
      if (pt.status === 'fulfilled') setPoints(pt.value);
      if (al.status === 'fulfilled') setAlerts(al.value);
    } catch { /* ignore */ }
    setLoading(false);
  }, [storeId]);

  useEffect(() => { void load(); }, [load]);

  const clockLabel: Record<ClockStatus, string> = {
    not_clocked: '未打卡',
    clocked_in: '已上班',
    clocked_out: '已下班',
  };
  const clockColor: Record<ClockStatus, string> = {
    not_clocked: T.muted,
    clocked_in: T.success,
    clocked_out: T.primary,
  };

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 16 }}>我的工作台</h1>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {/* 今日班次 */}
      <div style={{
        background: T.card, borderRadius: 12, padding: 16, marginBottom: 12,
        border: `1px solid ${T.border}`,
      }}>
        <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>今日班次</div>
        {shift ? (
          <>
            <div style={{ fontSize: 18, fontWeight: 600 }}>{shift.shift_name}</div>
            <div style={{ fontSize: 16, color: T.muted, marginTop: 4 }}>{shift.time_range} · {shift.position}</div>
            <div style={{ fontSize: 14, color: T.primary, marginTop: 8 }}>{formatCountdown(shift.start_time)}</div>
          </>
        ) : (
          <div style={{ fontSize: 16, color: T.muted }}>今日无班次</div>
        )}
      </div>

      {/* 打卡状态 */}
      <div
        style={{
          background: T.card, borderRadius: 12, padding: 16, marginBottom: 12,
          border: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 12,
          cursor: 'pointer', minHeight: 48,
        }}
        onClick={() => navigate('/schedule-clock')}
      >
        <div style={{
          width: 14, height: 14, borderRadius: '50%',
          background: clockColor[clockStatus],
        }} />
        <div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{clockLabel[clockStatus]}</div>
          <div style={{ fontSize: 14, color: T.muted }}>点击进入打卡</div>
        </div>
      </div>

      {/* 待处理事项 */}
      {pending.length > 0 && (
        <div style={{
          background: T.card, borderRadius: 12, padding: 16, marginBottom: 12,
          border: `1px solid ${T.border}`,
        }}>
          <div style={{ fontSize: 14, color: T.muted, marginBottom: 8 }}>待处理 ({pending.length})</div>
          {pending.map(item => (
            <div key={item.id} style={{
              padding: '10px 0', borderBottom: `1px solid ${T.border}`,
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              minHeight: 48,
            }}>
              <div>
                <span style={{
                  fontSize: 12, padding: '2px 6px', borderRadius: 4,
                  background: item.type === 'swap' ? '#1a2a33' : '#1f1208',
                  color: item.type === 'swap' ? T.warning : T.primary,
                  marginRight: 8,
                }}>{item.type === 'swap' ? '调班' : '请假'}</span>
                <span style={{ fontSize: 16 }}>{item.title}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 积分变动 */}
      <div style={{
        background: T.card, borderRadius: 12, padding: 16, marginBottom: 12,
        border: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', cursor: 'pointer', minHeight: 48,
      }} onClick={() => navigate('/me/points')}>
        <div>
          <div style={{ fontSize: 14, color: T.muted }}>积分</div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{points.balance}</div>
        </div>
        <div style={{
          fontSize: 14, color: T.success,
          background: '#0a2820', padding: '4px 10px', borderRadius: 8,
        }}>
          +{points.today_earned} 今日
        </div>
      </div>

      {/* 证照提醒 */}
      {alerts.length > 0 && alerts.map(a => (
        <div key={a.id} style={{
          background: '#2a1215', borderRadius: 12, padding: 16, marginBottom: 12,
          border: `1px solid ${T.danger}40`,
        }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: T.danger }}>
            {a.cert_name} 即将到期
          </div>
          <div style={{ fontSize: 14, color: T.muted, marginTop: 4 }}>
            到期日：{a.expires_at} · 剩余 {a.days_left} 天
          </div>
        </div>
      ))}
    </div>
  );
}

export default CrewWorkbench;
