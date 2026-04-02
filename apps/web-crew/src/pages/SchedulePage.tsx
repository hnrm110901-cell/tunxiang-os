/**
 * 员工个人排班查看页 — 服务员/厨师手机PWA
 * 路由: /schedule（底部 TabBar 可见）
 *
 * 布局：
 *   顶部  — 本周排班7天横向滚动
 *   中部  — 本周汇总（排班天数 + 预计总工时）
 *   打卡区 — 上班打卡 / 下班打卡 / 今日已完成
 *   底部  — 最近7天考勤记录（localStorage缓存）
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ─────────────────────────────────────────
   Design Tokens (与全局一致)
───────────────────────────────────────── */
const T = {
  bg:       '#0B1A20',
  card:     '#112228',
  cardAlt:  '#0f1e26',
  border:   '#1a2a33',
  text:     '#E0E0E0',
  muted:    '#64748b',
  dim:      '#334155',
  primary:  '#FF6B35',        // 主色 上班打卡按钮
  primaryAct: '#E55A28',
  navy:     '#1E2A3A',        // 下班打卡按钮底色
  success:  '#0F6E56',        // 已完成绿色
  successBg: '#0a2820',
  successTxt: '#30D158',
  warning:  '#BA7517',
};

/* ─────────────────────────────────────────
   类型
───────────────────────────────────────── */
interface DaySchedule {
  date:       string;   // 'YYYY-MM-DD'
  label:      string;   // '周一' 等
  dayNum:     number;   // 日期数字
  hasShift:   boolean;
  startTime:  string;   // '09:00'
  endTime:    string;   // '18:00'
  hours:      number;   // 预计工时（小时）
}

type ClockStatus = 'not_clocked' | 'clocked_in' | 'clocked_out';

interface TodayAttendance {
  status:     ClockStatus;
  clockInAt:  string | null;   // ISO string
  clockOutAt: string | null;
  totalHours: number | null;   // 已完成工时（小时）
}

interface AttendanceRecord {
  date:       string;   // 'YYYY-MM-DD'
  dayLabel:   string;
  clockIn:    string | null;   // 'HH:MM'
  clockOut:   string | null;
  hours:      string | null;   // '8.0h'
}

/* ─────────────────────────────────────────
   工具函数
───────────────────────────────────────── */
function getWeekDates(weekStart: string): string[] {
  const dates: string[] = [];
  const base = new Date(weekStart);
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    dates.push(d.toISOString().slice(0, 10));
  }
  return dates;
}

function getMondayOfCurrentWeek(): string {
  const now = new Date();
  const day = now.getDay();
  const diff = day === 0 ? -6 : 1 - day;  // 周一为起点
  const mon = new Date(now);
  mon.setDate(now.getDate() + diff);
  return mon.toISOString().slice(0, 10);
}

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function hhmm(isoOrHHMM: string | null): string {
  if (!isoOrHHMM) return '--:--';
  if (isoOrHHMM.includes('T')) {
    const d = new Date(isoOrHHMM);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  return isoOrHHMM.slice(0, 5);
}

function diffSeconds(from: string): number {
  return Math.floor((Date.now() - new Date(from).getTime()) / 1000);
}

function formatDuration(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

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

async function apiGet<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: buildHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json() as { ok: boolean; data: T };
  if (!json.ok) throw new Error('API error');
  return json.data;
}

async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json() as { ok: boolean; data: T };
  if (!json.ok) throw new Error('API error');
  return json.data;
}

/* ─────────────────────────────────────────
   Toast 组件
───────────────────────────────────────── */
interface ToastProps {
  msg:   string;
  type?: 'success' | 'error';
}
function Toast({ msg, type = 'success' }: ToastProps) {
  const bg = type === 'error' ? '#3a1010' : '#0a2820';
  const border = type === 'error' ? '#7a2020' : '#1a5a40';
  const color  = type === 'error' ? '#ff6b6b' : T.successTxt;
  return (
    <div style={{
      position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
      background: bg, color, border: `1px solid ${border}`,
      borderRadius: 12, padding: '12px 24px',
      fontSize: 16, fontWeight: 600,
      zIndex: 999, boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
      whiteSpace: 'nowrap', maxWidth: '90vw',
      animation: 'fadeInDown 0.2s ease',
    }}>
      {msg}
    </div>
  );
}

/* ─────────────────────────────────────────
   主页面
───────────────────────────────────────── */
export function SchedulePage() {
  const navigate = useNavigate();
  const storeId    = localStorage.getItem('storeId')    ?? '';
  const employeeId = localStorage.getItem('employeeId') ?? '';

  /* ── 排班数据 ── */
  const weekStart = getMondayOfCurrentWeek();
  const [weekDays, setWeekDays]     = useState<DaySchedule[]>([]);
  const [selectedDate, setSelectedDate] = useState<string>(todayStr());
  const [scheduleLoading, setScheduleLoading] = useState(true);
  const [scheduleError,   setScheduleError]   = useState('');

  /* ── 今日考勤状态 ── */
  const [todayAtt,    setTodayAtt]    = useState<TodayAttendance>({
    status: 'not_clocked', clockInAt: null, clockOutAt: null, totalHours: null,
  });
  const [attLoading, setAttLoading] = useState(true);

  /* ── 已上班时长计时器 ── */
  const [elapsedSecs, setElapsedSecs] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── 最近考勤记录 ── */
  const [records, setRecords] = useState<AttendanceRecord[]>([]);

  /* ── 打卡操作状态 ── */
  const [clockLoading, setClockLoading] = useState(false);

  /* ── Toast ── */
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  function showToast(msg: string, type: 'success' | 'error' = 'success') {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2800);
  }

  /* ── 加载排班 ── */
  const loadSchedule = useCallback(async () => {
    setScheduleLoading(true);
    setScheduleError('');
    try {
      type ApiShift = { date: string; start_time: string; end_time: string; hours: number };
      const data = await apiGet<{ shifts: ApiShift[] }>(
        `/api/v1/schedules/week?store_id=${storeId}&week_start=${weekStart}`
      );
      const shiftMap = new Map<string, ApiShift>();
      (data.shifts ?? []).forEach((s: ApiShift) => shiftMap.set(s.date, s));

      const days: DaySchedule[] = getWeekDates(weekStart).map(date => {
        const d   = new Date(date);
        const s   = shiftMap.get(date);
        return {
          date,
          label:     WEEKDAY_LABELS[d.getDay()],
          dayNum:    d.getDate(),
          hasShift:  !!s,
          startTime: s?.start_time ?? '',
          endTime:   s?.end_time   ?? '',
          hours:     s?.hours      ?? 0,
        };
      });
      setWeekDays(days);
    } catch {
      setScheduleError('排班加载失败');
      // 降级：生成空的7天框架，不阻断查看
      const days: DaySchedule[] = getWeekDates(weekStart).map(date => {
        const d = new Date(date);
        return {
          date, label: WEEKDAY_LABELS[d.getDay()], dayNum: d.getDate(),
          hasShift: false, startTime: '', endTime: '', hours: 0,
        };
      });
      setWeekDays(days);
    } finally {
      setScheduleLoading(false);
    }
  }, [storeId, weekStart]);

  /* ── 加载今日考勤 ── */
  const loadTodayAtt = useCallback(async () => {
    setAttLoading(true);
    try {
      type ApiToday = {
        status: ClockStatus;
        clock_in_at:  string | null;
        clock_out_at: string | null;
        total_hours:  number | null;
      };
      const data = await apiGet<ApiToday>(`/api/v1/attendance/today?store_id=${storeId}`);
      setTodayAtt({
        status:     data.status,
        clockInAt:  data.clock_in_at,
        clockOutAt: data.clock_out_at,
        totalHours: data.total_hours,
      });
    } catch {
      // 降级：读取 localStorage 缓存的打卡状态
      const cached = localStorage.getItem('todayAttendance');
      if (cached) {
        try {
          const parsed = JSON.parse(cached) as TodayAttendance;
          setTodayAtt(parsed);
        } catch { /* ignore */ }
      }
    } finally {
      setAttLoading(false);
    }
  }, [storeId]);

  /* ── 加载考勤记录（localStorage缓存） ── */
  const loadRecords = useCallback(async () => {
    // 先尝试从 localStorage 读取缓存
    const cacheKey  = `attendanceRecords_${employeeId}`;
    const cacheTime = `attendanceRecordsTime_${employeeId}`;
    const now = Date.now();
    const lastFetch = parseInt(localStorage.getItem(cacheTime) ?? '0', 10);
    const CACHE_TTL = 5 * 60 * 1000; // 5分钟

    if (now - lastFetch < CACHE_TTL) {
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        try {
          setRecords(JSON.parse(cached) as AttendanceRecord[]);
          return;
        } catch { /* fallthrough to API */ }
      }
    }

    try {
      type ApiRecord = {
        date: string;
        clock_in:   string | null;
        clock_out:  string | null;
        hours:      number | null;
      };
      const data = await apiGet<{ records: ApiRecord[] }>(
        `/api/v1/attendance/today?store_id=${storeId}`
      );
      const mapped: AttendanceRecord[] = (data.records ?? []).slice(0, 7).map((r: ApiRecord) => {
        const d = new Date(r.date);
        return {
          date:     r.date,
          dayLabel: `${WEEKDAY_LABELS[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`,
          clockIn:  r.clock_in  ? hhmm(r.clock_in)  : null,
          clockOut: r.clock_out ? hhmm(r.clock_out) : null,
          hours:    r.hours != null ? `${r.hours.toFixed(1)}h` : null,
        };
      });
      setRecords(mapped);
      localStorage.setItem(cacheKey, JSON.stringify(mapped));
      localStorage.setItem(cacheTime, String(now));
    } catch { /* 无法加载记录，静默失败 */ }
  }, [employeeId, storeId]);

  /* ── 初始化：并行请求 ── */
  useEffect(() => {
    void loadSchedule();
    void loadTodayAtt();
    void loadRecords();
  }, [loadSchedule, loadTodayAtt, loadRecords]);

  /* ── 计时器：已上班时长 ── */
  useEffect(() => {
    if (todayAtt.status === 'clocked_in' && todayAtt.clockInAt) {
      setElapsedSecs(diffSeconds(todayAtt.clockInAt));
      timerRef.current = setInterval(() => {
        setElapsedSecs(diffSeconds(todayAtt.clockInAt!));
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
      setElapsedSecs(0);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [todayAtt]);

  /* ── 打卡操作 ── */
  async function handleClock(type: 'in' | 'out') {
    const label   = type === 'in' ? '上班打卡' : '下班打卡';
    const nowTime = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    const confirmed = window.confirm(`确认${label}？\n当前时间：${nowTime}`);
    if (!confirmed) return;

    setClockLoading(true);
    try {
      const url = type === 'in'
        ? '/api/v1/attendance/clock-in'
        : '/api/v1/attendance/clock-out';
      type ClockResp = { clock_in_at?: string; clock_out_at?: string; total_hours?: number };
      const resp = await apiPost<ClockResp>(url, {
        store_id:    storeId,
        employee_id: employeeId,
      });

      const newAtt: TodayAttendance = type === 'in'
        ? {
            status:     'clocked_in',
            clockInAt:  resp.clock_in_at ?? new Date().toISOString(),
            clockOutAt: null,
            totalHours: null,
          }
        : {
            status:     'clocked_out',
            clockInAt:  todayAtt.clockInAt,
            clockOutAt: resp.clock_out_at ?? new Date().toISOString(),
            totalHours: resp.total_hours ?? null,
          };

      setTodayAtt(newAtt);
      localStorage.setItem('todayAttendance', JSON.stringify(newAtt));
      showToast(`${label}成功 ${nowTime}`);

      // 刷新记录缓存
      const cacheKey  = `attendanceRecords_${employeeId}`;
      const cacheTime = `attendanceRecordsTime_${employeeId}`;
      localStorage.removeItem(cacheKey);
      localStorage.removeItem(cacheTime);
      setTimeout(() => { void loadRecords(); }, 500);
    } catch {
      showToast(`${label}失败，请重试`, 'error');
    } finally {
      setClockLoading(false);
    }
  }

  /* ── 选中日班次详情 ── */
  const selectedDay = weekDays.find(d => d.date === selectedDate);

  /* ── 本周汇总 ── */
  const totalShiftDays = weekDays.filter(d => d.hasShift).length;
  const totalHours     = weekDays.reduce((sum, d) => sum + d.hours, 0);

  /* ─────────────────────────────────────────
     渲染
  ───────────────────────────────────────── */
  return (
    <div style={{
      background: T.bg, minHeight: '100vh', color: T.text,
      paddingBottom: 80,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
    }}>
      {/* keyframes */}
      <style>{`
        @keyframes fadeInDown {
          from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
          to   { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
        @keyframes pulseRing {
          0%   { box-shadow: 0 0 0 0 rgba(15,110,86,0.5); }
          70%  { box-shadow: 0 0 0 16px rgba(15,110,86,0); }
          100% { box-shadow: 0 0 0 0 rgba(15,110,86,0); }
        }
        .day-card:active { transform: scale(0.95); }
        .clock-btn:active { transform: scale(0.97); }
        .record-row:active { background: #0f2028 !important; }
      `}</style>

      {toast && <Toast msg={toast.msg} type={toast.type} />}

      {/* ══ 顶部标题 ══ */}
      <div style={{
        padding: '16px 16px 12px',
        borderBottom: `1px solid ${T.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 20, fontWeight: 800, color: '#fff' }}>排班</span>
        <button
          onClick={() => navigate('/schedule-clock')}
          style={{
            background: T.primary, border: 'none', borderRadius: 10,
            color: '#fff', fontSize: 16, fontWeight: 700,
            padding: '8px 18px', minHeight: 40, minWidth: 80,
            cursor: 'pointer',
          }}
        >
          打卡
        </button>
      </div>

      {/* ══ 本周排班 7天横向滚动 ══ */}
      <section style={{ padding: '16px 0 8px' }}>
        <div style={{
          paddingLeft: 16, fontSize: 16, fontWeight: 600, color: T.muted,
          marginBottom: 10,
        }}>
          本周排班
          {scheduleError && (
            <span style={{ fontSize: 14, color: T.warning, marginLeft: 8 }}>
              · {scheduleError}
            </span>
          )}
        </div>

        {scheduleLoading ? (
          <div style={{
            display: 'flex', gap: 8, padding: '0 16px',
            overflowX: 'hidden',
          }}>
            {[...Array(7)].map((_, i) => (
              <div key={i} style={{
                flexShrink: 0, width: 60, height: 80,
                borderRadius: 14, background: T.card,
                border: `1px solid ${T.border}`,
                opacity: 0.5,
              }} />
            ))}
          </div>
        ) : (
          <div style={{
            display: 'flex', gap: 8,
            overflowX: 'auto', padding: '0 16px 4px',
            scrollbarWidth: 'none',
            WebkitOverflowScrolling: 'touch',
          } as React.CSSProperties}>
            {weekDays.map(day => {
              const isToday    = day.date === todayStr();
              const isSelected = day.date === selectedDate;
              return (
                <button
                  key={day.date}
                  className="day-card"
                  onClick={() => setSelectedDate(day.date)}
                  style={{
                    flexShrink: 0, width: 60, height: 80,
                    borderRadius: 14,
                    border: `2px solid ${isSelected ? T.primary : T.border}`,
                    background: isToday
                      ? (isSelected ? T.primary : `${T.primary}22`)
                      : (isSelected ? `${T.primary}18` : T.card),
                    cursor: 'pointer', padding: 0,
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center', gap: 2,
                    transition: 'transform 0.15s',
                    position: 'relative',
                  }}
                >
                  {/* 星期 */}
                  <span style={{
                    fontSize: 12, color: isToday ? (isSelected ? '#fff' : T.primary) : T.muted,
                    lineHeight: 1,
                  }}>
                    {day.label.replace('周', '')}
                  </span>

                  {/* 日期数字 — 今天用圆形橙色背景 */}
                  {isToday ? (
                    <div style={{
                      width: 30, height: 30, borderRadius: '50%',
                      background: isSelected ? 'rgba(255,255,255,0.25)' : T.primary,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 17, fontWeight: 800,
                      color: '#fff',
                    }}>
                      {day.dayNum}
                    </div>
                  ) : (
                    <span style={{
                      fontSize: 22, fontWeight: 800,
                      color: isSelected ? T.primary : '#fff',
                      lineHeight: 1,
                    }}>
                      {day.dayNum}
                    </span>
                  )}

                  {/* 班次时间 or 休 */}
                  {day.hasShift ? (
                    <span style={{
                      fontSize: 10, color: isSelected ? T.primary : T.primary,
                      fontWeight: 600, lineHeight: 1,
                    }}>
                      {day.startTime}-{day.endTime}
                    </span>
                  ) : (
                    <span style={{ fontSize: 16, color: T.dim, fontWeight: 700 }}>
                      休
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* 选中日班次详情 */}
        {selectedDay && (
          <div style={{
            margin: '12px 16px 0',
            background: T.card, borderRadius: 14,
            border: `1px solid ${T.border}`, padding: '14px 16px',
          }}>
            <div style={{ fontSize: 14, color: T.muted, marginBottom: 6 }}>
              {selectedDay.date} {selectedDay.label}
              {selectedDay.date === todayStr() && (
                <span style={{
                  marginLeft: 8, fontSize: 12, color: T.primary,
                  border: `1px solid ${T.primary}`, borderRadius: 4,
                  padding: '1px 6px',
                }}>
                  今天
                </span>
              )}
            </div>
            {selectedDay.hasShift ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 22, fontWeight: 800, color: '#fff' }}>
                  {selectedDay.startTime}–{selectedDay.endTime}
                </span>
                <span style={{
                  fontSize: 14, color: T.primary,
                  background: `${T.primary}18`, borderRadius: 8,
                  padding: '3px 10px', fontWeight: 600,
                }}>
                  {selectedDay.hours}h
                </span>
              </div>
            ) : (
              <div style={{ fontSize: 17, color: T.muted }}>今日休息</div>
            )}
          </div>
        )}
      </section>

      {/* ══ 本周汇总 ══ */}
      <section style={{ padding: '16px 16px 0' }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: T.muted, marginBottom: 10 }}>
          本周汇总
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          {[
            { label: '排班天数', value: totalShiftDays, unit: '天', color: '#fff' },
            { label: '预计工时', value: totalHours.toFixed(1), unit: 'h', color: T.primary },
          ].map(item => (
            <div key={item.label} style={{
              flex: 1, background: T.card, borderRadius: 14,
              border: `1px solid ${T.border}`, padding: '16px 16px 14px',
              display: 'flex', flexDirection: 'column', gap: 4,
            }}>
              <div style={{ fontSize: 14, color: T.muted }}>{item.label}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <span style={{ fontSize: 28, fontWeight: 800, color: item.color }}>
                  {item.value}
                </span>
                <span style={{ fontSize: 16, color: T.muted }}>{item.unit}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ══ 打卡区 ══ */}
      <section style={{ padding: '20px 16px 0' }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: T.muted, marginBottom: 12 }}>
          今日打卡
        </div>

        {attLoading ? (
          <div style={{
            background: T.card, borderRadius: 16, padding: '32px',
            border: `1px solid ${T.border}`, textAlign: 'center',
            fontSize: 16, color: T.muted,
          }}>
            加载中…
          </div>
        ) : (
          <div style={{
            background: T.card, borderRadius: 16,
            border: `1px solid ${T.border}`, padding: '20px 16px',
          }}>

            {/* 未打卡上班 */}
            {todayAtt.status === 'not_clocked' && (
              <>
                <div style={{ fontSize: 16, color: T.muted, marginBottom: 16, textAlign: 'center' }}>
                  尚未打卡，请开始您的班次
                </div>
                <button
                  className="clock-btn"
                  onClick={() => handleClock('in')}
                  disabled={clockLoading}
                  style={{
                    width: '100%', height: 72, borderRadius: 36,
                    background: clockLoading ? T.dim : T.primary,
                    border: 'none', color: '#fff',
                    fontSize: 22, fontWeight: 800,
                    cursor: clockLoading ? 'not-allowed' : 'pointer',
                    transition: 'transform 0.2s, background 0.15s',
                    boxShadow: clockLoading ? 'none' : `0 4px 20px ${T.primary}55`,
                    opacity: clockLoading ? 0.7 : 1,
                  }}
                >
                  {clockLoading ? '打卡中…' : '上班打卡'}
                </button>
              </>
            )}

            {/* 已打卡上班，未下班 */}
            {todayAtt.status === 'clocked_in' && (
              <>
                {/* 上班信息 */}
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'center', marginBottom: 12,
                }}>
                  <div>
                    <div style={{ fontSize: 14, color: T.muted }}>上班时间</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: T.successTxt }}>
                      {hhmm(todayAtt.clockInAt)}
                    </div>
                  </div>
                  {/* 已上班时长 */}
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 14, color: T.muted }}>已上班</div>
                    <div style={{
                      fontSize: 20, fontWeight: 800,
                      color: T.primary, fontVariantNumeric: 'tabular-nums',
                    }}>
                      {formatDuration(elapsedSecs)}
                    </div>
                  </div>
                </div>

                {/* 下班打卡按钮 */}
                <button
                  className="clock-btn"
                  onClick={() => handleClock('out')}
                  disabled={clockLoading}
                  style={{
                    width: '100%', height: 72, borderRadius: 36,
                    background: clockLoading ? T.dim : T.navy,
                    border: `2px solid ${T.primary}`,
                    color: '#fff', fontSize: 22, fontWeight: 800,
                    cursor: clockLoading ? 'not-allowed' : 'pointer',
                    transition: 'transform 0.2s',
                    opacity: clockLoading ? 0.7 : 1,
                  }}
                >
                  {clockLoading ? '打卡中…' : '下班打卡'}
                </button>
              </>
            )}

            {/* 已打卡下班 */}
            {todayAtt.status === 'clocked_out' && (
              <div style={{ textAlign: 'center', padding: '8px 0' }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  background: T.successBg, borderRadius: 12,
                  border: `1px solid ${T.success}`,
                  padding: '10px 20px', marginBottom: 14,
                }}>
                  <span style={{ fontSize: 18 }}>✓</span>
                  <span style={{ fontSize: 17, fontWeight: 700, color: T.successTxt }}>
                    今日已完成
                  </span>
                </div>

                <div style={{
                  display: 'flex', justifyContent: 'center', gap: 32,
                  marginTop: 4,
                }}>
                  <div>
                    <div style={{ fontSize: 13, color: T.muted }}>上班</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>
                      {hhmm(todayAtt.clockInAt)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 13, color: T.muted }}>下班</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>
                      {hhmm(todayAtt.clockOutAt)}
                    </div>
                  </div>
                  {todayAtt.totalHours != null && (
                    <div>
                      <div style={{ fontSize: 13, color: T.muted }}>工时</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: T.primary }}>
                        {todayAtt.totalHours.toFixed(1)}h
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ══ 最近7天考勤记录 ══ */}
      <section style={{ padding: '20px 16px 0' }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: T.muted, marginBottom: 10 }}>
          最近考勤
        </div>

        <div style={{
          background: T.card, borderRadius: 14,
          border: `1px solid ${T.border}`, overflow: 'hidden',
        }}>
          {/* 表头 */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr',
            padding: '10px 16px', borderBottom: `1px solid ${T.border}`,
            background: T.cardAlt,
          }}>
            {['日期', '上班', '下班', '工时'].map(h => (
              <div key={h} style={{ fontSize: 13, color: T.muted, textAlign: 'center' }}>{h}</div>
            ))}
          </div>

          {records.length === 0 ? (
            <div style={{
              padding: '24px 16px', fontSize: 16, color: T.muted, textAlign: 'center',
            }}>
              暂无考勤记录
            </div>
          ) : (
            records.map((r, i) => (
              <div
                key={r.date}
                className="record-row"
                style={{
                  display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr',
                  padding: '13px 16px', minHeight: 52,
                  borderBottom: i < records.length - 1 ? `1px solid ${T.border}` : 'none',
                  transition: 'background 0.1s',
                }}
              >
                <div style={{ fontSize: 14, color: T.muted, textAlign: 'center' }}>
                  {r.dayLabel}
                </div>
                <div style={{
                  fontSize: 15, fontWeight: 600, textAlign: 'center',
                  color: r.clockIn ? T.successTxt : T.dim,
                }}>
                  {r.clockIn ?? '--:--'}
                </div>
                <div style={{
                  fontSize: 15, fontWeight: 600, textAlign: 'center',
                  color: r.clockOut ? '#fff' : T.dim,
                }}>
                  {r.clockOut ?? '--:--'}
                </div>
                <div style={{
                  fontSize: 15, fontWeight: 700, textAlign: 'center',
                  color: r.hours ? T.primary : T.dim,
                }}>
                  {r.hours ?? '--'}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
