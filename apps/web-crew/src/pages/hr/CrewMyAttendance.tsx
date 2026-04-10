/**
 * 我的考勤 — 员工端 PWA
 * 路由: /me/attendance
 * API: GET /api/v1/attendance/records?employee_id=me
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

interface AttendanceSummary {
  attend_days: number;
  late_count: number;
  early_leave_count: number;
  absent_count: number;
}

interface AttendanceRecord {
  date: string;
  clock_in: string | null;
  clock_out: string | null;
  hours: number | null;
  status: 'normal' | 'late' | 'early_leave' | 'absent';
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

const statusConfig: Record<AttendanceRecord['status'], { label: string; color: string }> = {
  normal:      { label: '正常', color: T.success },
  late:        { label: '迟到', color: T.warning },
  early_leave: { label: '早退', color: '#FFD60A' },
  absent:      { label: '缺勤', color: T.danger },
};

function getCurrentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function CrewMyAttendance() {
  const navigate = useNavigate();

  const [month, setMonth] = useState(getCurrentMonth);
  const [summary, setSummary] = useState<AttendanceSummary>({ attend_days: 0, late_count: 0, early_leave_count: 0, absent_count: 0 });
  const [records, setRecords] = useState<AttendanceRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<{ summary: AttendanceSummary; records: AttendanceRecord[] }>(
        `/api/v1/attendance/records?employee_id=me&month=${month}`
      );
      setSummary(data.summary);
      setRecords(data.records);
    } catch { /* ignore */ }
    setLoading(false);
  }, [month]);

  useEffect(() => { void load(); }, [load]);

  function changeMonth(delta: number) {
    const [y, m] = month.split('-').map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  }

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的考勤</h1>
        <div style={{ width: 48 }} />
      </div>

      {/* 月选择器 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', background: T.card, borderRadius: 8, fontSize: 16 }}
          onClick={() => changeMonth(-1)}
        >←</div>
        <div style={{ fontSize: 18, fontWeight: 600 }}>{month}</div>
        <div
          style={{ minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', background: T.card, borderRadius: 8, fontSize: 16 }}
          onClick={() => changeMonth(1)}
        >→</div>
      </div>

      {/* 统计卡 */}
      <div style={{
        background: T.card, borderRadius: 12, padding: 16, marginBottom: 16,
        border: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-around',
      }}>
        {[
          { label: '出勤', value: summary.attend_days, color: T.success },
          { label: '迟到', value: summary.late_count, color: T.warning },
          { label: '早退', value: summary.early_leave_count, color: '#FFD60A' },
          { label: '缺勤', value: summary.absent_count, color: T.danger },
        ].map(item => (
          <div key={item.label} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: item.color }}>{item.value}</div>
            <div style={{ fontSize: 13, color: T.muted, marginTop: 4 }}>{item.label}</div>
          </div>
        ))}
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {/* 记录列表 */}
      {records.map(r => {
        const sc = statusConfig[r.status];
        return (
          <div key={r.date} style={{
            background: T.card, borderRadius: 12, padding: 14, marginBottom: 8,
            border: `1px solid ${T.border}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{r.date}</div>
              <span style={{
                fontSize: 12, padding: '3px 8px', borderRadius: 4,
                background: sc.color + '22', color: sc.color,
              }}>{sc.label}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 14, color: T.muted }}>
              <span>上班 {r.clock_in ?? '--:--'}</span>
              <span>下班 {r.clock_out ?? '--:--'}</span>
              <span>{r.hours != null ? `${r.hours}h` : '-'}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default CrewMyAttendance;
