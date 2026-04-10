/**
 * 我的班表 — 员工端 PWA
 * 路由: /me/schedule
 *
 * 功能：本周班表7天卡片、当日高亮、周导航
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

interface DayShift {
  date: string;
  weekday: string;
  shift_name: string;
  time_range: string;
  position: string;
  has_shift: boolean;
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

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function getMondayOfWeek(offset: number): string {
  const now = new Date();
  const day = now.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  const mon = new Date(now);
  mon.setDate(now.getDate() + diff + offset * 7);
  return mon.toISOString().slice(0, 10);
}

function getWeekDates(monday: string): string[] {
  const dates: string[] = [];
  const base = new Date(monday);
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    dates.push(d.toISOString().slice(0, 10));
  }
  return dates;
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export function CrewMySchedule() {
  const navigate = useNavigate();
  const storeId = localStorage.getItem('storeId') ?? '';

  const [weekOffset, setWeekOffset] = useState(0);
  const [days, setDays] = useState<DayShift[]>([]);
  const [loading, setLoading] = useState(true);

  const monday = getMondayOfWeek(weekOffset);
  const today = todayStr();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<DayShift[]>(`/api/v1/schedules/week?store_id=${storeId}&start=${monday}`);
      setDays(data);
    } catch {
      // fallback: generate empty week
      const dates = getWeekDates(monday);
      setDays(dates.map(date => {
        const d = new Date(date);
        return {
          date,
          weekday: WEEKDAY_LABELS[d.getDay()],
          shift_name: '',
          time_range: '',
          position: '',
          has_shift: false,
        };
      }));
    }
    setLoading(false);
  }, [storeId, monday]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >
          ←
        </div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的班表</h1>
        <div style={{ width: 48 }} />
      </div>

      {/* 周导航 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{
            minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center',
            justifyContent: 'center', cursor: 'pointer', borderRadius: 8,
            background: T.card, fontSize: 16,
          }}
          onClick={() => setWeekOffset(w => w - 1)}
        >
          ← 上周
        </div>
        <div style={{ fontSize: 16, fontWeight: 600 }}>{monday} 起</div>
        <div
          style={{
            minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center',
            justifyContent: 'center', cursor: 'pointer', borderRadius: 8,
            background: T.card, fontSize: 16,
          }}
          onClick={() => setWeekOffset(w => w + 1)}
        >
          下周 →
        </div>
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {/* 班表列表 */}
      {days.map(day => {
        const isToday = day.date === today;
        return (
          <div key={day.date} style={{
            background: T.card, borderRadius: 12, padding: 16, marginBottom: 10,
            border: `1px solid ${isToday ? T.primary : T.border}`,
            borderLeft: `4px solid ${day.has_shift ? T.success : T.dim}`,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>
                {day.date.slice(5)} {day.weekday}
                {isToday && <span style={{ color: T.primary, marginLeft: 8, fontSize: 12 }}>今天</span>}
              </div>
              {day.has_shift ? (
                <div style={{ fontSize: 14, color: T.muted, marginTop: 4 }}>
                  {day.shift_name} · {day.time_range} · {day.position}
                </div>
              ) : (
                <div style={{ fontSize: 14, color: T.dim, marginTop: 4 }}>休息</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default CrewMySchedule;
