/**
 * 排班打卡页面 — 服务员端 PWA
 * 路由: /shift-schedule
 * Tabs: 今日打卡 / 本周排班 / 换班申请
 */
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 颜色常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  text: '#E0E0E0',
  muted: '#64748b',
  primary: '#FF6B35',
  success: '#30D158',
  warning: '#FF9F0A',
  danger: '#FF453A',
  inactive: '#334155',
};

/* ---------- 类型定义 ---------- */
type CheckinStatus = 'not_clocked' | 'clocked_in' | 'clocked_out';

interface CheckinRecord {
  type: 'clock_in' | 'clock_out';
  time: string;
}

interface DaySchedule {
  date: string;       // 'MM-DD'
  weekday: string;    // '周一' 等
  shift: string;      // '早班' | '午班' | '晚班' | ''
  timeRange: string;  // '09:00-14:00'
  status: 'present' | 'absent' | 'pending' | 'today';
  isToday: boolean;
}

interface ShiftSwap {
  id: string;
  fromDate: string;
  toCrew: string;
  reason: string;
  status: 'pending' | 'approved' | 'rejected';
  createdAt: string;
}

/* ---------- Mock 数据 ---------- */
const MOCK_WEEK_SCHEDULE: DaySchedule[] = [
  { date: '03-25', weekday: '周二', shift: '午班', timeRange: '11:00-17:00', status: 'present', isToday: false },
  { date: '03-26', weekday: '周三', shift: '晚班', timeRange: '17:00-22:00', status: 'present', isToday: false },
  { date: '03-27', weekday: '周四', shift: '',     timeRange: '',             status: 'pending', isToday: false },
  { date: '03-28', weekday: '周五', shift: '早班', timeRange: '09:00-14:00', status: 'absent',  isToday: false },
  { date: '03-29', weekday: '周六', shift: '午班', timeRange: '11:00-17:00', status: 'present', isToday: false },
  { date: '03-30', weekday: '周日', shift: '晚班', timeRange: '17:00-22:00', status: 'present', isToday: false },
  { date: '03-31', weekday: '周一', shift: '午班', timeRange: '11:00-17:00', status: 'today',   isToday: true  },
];

const MOCK_SWAPS: ShiftSwap[] = [
  { id: 'sw-001', fromDate: '03-28', toCrew: '李四', reason: '家里有事', status: 'approved',  createdAt: '03-27 10:20' },
  { id: 'sw-002', fromDate: '04-02', toCrew: '王五', reason: '看病',     status: 'pending',  createdAt: '03-30 14:05' },
  { id: 'sw-003', fromDate: '03-20', toCrew: '赵六', reason: '约好了',   status: 'rejected', createdAt: '03-19 09:00' },
];

const MOCK_CREW_LIST = ['李四', '王五', '赵六', '孙七', '周八'];

/* ---------- 工具函数 ---------- */
function formatTime(d: Date): string {
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

function formatDate(d: Date): string {
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day   = String(d.getDate()).padStart(2, '0');
  return `${month}-${day}`;
}

function swapStatusLabel(s: ShiftSwap['status']): string {
  if (s === 'pending')  return '待审批';
  if (s === 'approved') return '已通过';
  return '已拒绝';
}

function swapStatusColor(s: ShiftSwap['status']): string {
  if (s === 'pending')  return C.warning;
  if (s === 'approved') return C.success;
  return C.danger;
}

/* ---------- Tab 1 — 今日打卡 ---------- */
function CheckinTab() {
  const [now, setNow]             = useState(new Date());
  const [status, setStatus]       = useState<CheckinStatus>('not_clocked');
  const [records, setRecords]     = useState<CheckinRecord[]>([]);
  const [gpsReady, setGpsReady]   = useState(false);
  const [gpsError, setGpsError]   = useState('');
  const [loading, setLoading]     = useState(false);
  const [toast, setToast]         = useState('');
  const posRef = useRef<GeolocationPosition | null>(null);

  // 每秒刷新时间
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // 请求 GPS
  useEffect(() => {
    if (!navigator.geolocation) {
      setGpsError('设备不支持GPS');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        posRef.current = pos;
        setGpsReady(true);
        setGpsError('');
      },
      (err) => {
        setGpsError(`GPS获取失败: ${err.message}`);
        setGpsReady(false);
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }, []);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }

  async function handleCheckin(type: 'clock_in' | 'clock_out') {
    setLoading(true);
    try {
      const body: Record<string, unknown> = { type };
      if (posRef.current) {
        body.lat = posRef.current.coords.latitude;
        body.lng = posRef.current.coords.longitude;
      }
      const deviceId = (window as Record<string, unknown>).__DEVICE_ID__ as string | undefined;
      if (deviceId) body.device_id = deviceId;

      await fetch('/api/v1/crew/checkin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const timeStr = formatTime(new Date());
      setRecords(prev => [...prev, { type, time: timeStr }]);
      setStatus(type === 'clock_in' ? 'clocked_in' : 'clocked_out');
      showToast(type === 'clock_in' ? `上班打卡成功 ${timeStr}` : `下班打卡成功 ${timeStr}`);
    } catch {
      showToast('打卡请求失败，请重试');
    } finally {
      setLoading(false);
    }
  }

  const statusConfig: Record<CheckinStatus, { label: string; color: string; bg: string }> = {
    not_clocked: { label: '未打卡',  color: C.muted,   bg: '#1a2a33' },
    clocked_in:  { label: '已上班',  color: C.success, bg: '#0d2d1a' },
    clocked_out: { label: '已下班',  color: C.primary, bg: '#1f1208' },
  };
  const sc = statusConfig[status];

  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  const dateStr = `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 周${weekdays[now.getDay()]}`;

  return (
    <div style={{ padding: '16px 16px 0' }}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', top: 72, left: '50%', transform: 'translateX(-50%)',
          background: '#1e2e38', color: '#fff', borderRadius: 10,
          padding: '10px 20px', fontSize: 15, zIndex: 200,
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
          border: `1px solid ${C.border}`,
        }}>
          {toast}
        </div>
      )}

      {/* 大时钟 */}
      <div style={{
        background: C.card, borderRadius: 16, padding: '24px 20px',
        border: `1px solid ${C.border}`, textAlign: 'center', marginBottom: 16,
      }}>
        <div style={{ fontSize: 48, fontWeight: 800, color: '#fff', letterSpacing: 2, lineHeight: 1.1 }}>
          {formatTime(now)}
        </div>
        <div style={{ fontSize: 16, color: C.muted, marginTop: 6 }}>{dateStr}</div>
      </div>

      {/* 当班状态卡片 */}
      <div style={{
        background: sc.bg, borderRadius: 16, padding: '16px 20px',
        border: `1px solid ${C.border}`, marginBottom: 16,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 4 }}>当班状态</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: sc.color }}>{sc.label}</div>
        </div>
        {/* GPS 状态 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 10, height: 10, borderRadius: '50%',
            background: gpsReady ? C.success : C.danger,
            boxShadow: gpsReady ? `0 0 6px ${C.success}` : `0 0 6px ${C.danger}`,
          }} />
          <span style={{ fontSize: 13, color: gpsReady ? C.success : C.danger }}>
            {gpsReady ? 'GPS已就绪' : (gpsError || 'GPS定位中...')}
          </span>
        </div>
      </div>

      {/* 打卡按钮 */}
      {status === 'not_clocked' && (
        <button
          onClick={() => handleCheckin('clock_in')}
          disabled={loading}
          style={{
            width: '100%', minHeight: 64, borderRadius: 16, fontSize: 20, fontWeight: 700,
            border: 'none', cursor: loading ? 'not-allowed' : 'pointer',
            background: loading ? C.inactive : C.primary,
            color: '#fff', marginBottom: 16,
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? '打卡中...' : '上班打卡'}
        </button>
      )}
      {status === 'clocked_in' && (
        <button
          onClick={() => handleCheckin('clock_out')}
          disabled={loading}
          style={{
            width: '100%', minHeight: 64, borderRadius: 16, fontSize: 20, fontWeight: 700,
            border: 'none', cursor: loading ? 'not-allowed' : 'pointer',
            background: loading ? C.inactive : '#1a4a5a',
            color: '#fff', marginBottom: 16,
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? '打卡中...' : '下班打卡'}
        </button>
      )}
      {status === 'clocked_out' && (
        <div style={{
          textAlign: 'center', padding: '20px 0', fontSize: 16,
          color: C.muted, marginBottom: 16,
        }}>
          今日打卡已完成
        </div>
      )}

      {/* 今日打卡记录 */}
      <h3 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 10px' }}>
        今日记录
      </h3>
      <div style={{
        background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
        overflow: 'hidden',
      }}>
        {records.length === 0 ? (
          <div style={{ padding: '20px 16px', fontSize: 15, color: C.muted, textAlign: 'center' }}>
            暂无打卡记录
          </div>
        ) : (
          records.map((r, i) => (
            <div
              key={i}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '14px 16px', minHeight: 52,
                borderBottom: i < records.length - 1 ? `1px solid ${C.border}` : 'none',
              }}
            >
              <span style={{ fontSize: 16, color: r.type === 'clock_in' ? C.success : C.primary }}>
                {r.type === 'clock_in' ? '上班' : '下班'}
              </span>
              <span style={{ fontSize: 18, fontWeight: 600, color: '#fff' }}>{r.time}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ---------- Tab 2 — 本周排班 ---------- */
function ScheduleTab() {
  const [schedule, setSchedule] = useState<DaySchedule[]>(MOCK_WEEK_SCHEDULE);
  const [selectedIdx, setSelectedIdx] = useState(
    MOCK_WEEK_SCHEDULE.findIndex(d => d.isToday) ?? 0,
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // 实际调用: GET /api/v1/crew/schedule?week=current
    // setSchedule(apiData)
    void schedule; // suppress lint: using mock
  }, []);

  const selected = schedule[selectedIdx];

  function statusIcon(s: DaySchedule['status']): string {
    if (s === 'present') return '✓';
    if (s === 'absent')  return '✗';
    if (s === 'today')   return '●';
    return '○';
  }

  function statusColor(s: DaySchedule['status']): string {
    if (s === 'present') return C.success;
    if (s === 'absent')  return C.danger;
    if (s === 'today')   return C.primary;
    return C.muted;
  }

  const shiftColors: Record<string, string> = {
    '早班': '#2563eb',
    '午班': '#7c3aed',
    '晚班': '#b45309',
  };

  return (
    <div style={{ padding: '16px 0 0' }}>
      {/* 横向日历 */}
      <div
        ref={scrollRef}
        style={{
          display: 'flex', gap: 8, overflowX: 'auto', padding: '0 16px 12px',
          scrollbarWidth: 'none',
        }}
      >
        {schedule.map((day, idx) => (
          <button
            key={day.date}
            onClick={() => setSelectedIdx(idx)}
            style={{
              flexShrink: 0, width: 64, minHeight: 80,
              borderRadius: 14,
              border: `2px solid ${selectedIdx === idx ? C.primary : C.border}`,
              background: day.isToday
                ? (selectedIdx === idx ? `${C.primary}22` : '#1a2e38')
                : (selectedIdx === idx ? `${C.primary}11` : C.card),
              cursor: 'pointer',
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 4,
              padding: '8px 0',
            }}
          >
            <div style={{ fontSize: 13, color: day.isToday ? C.primary : C.muted }}>
              {day.weekday}
            </div>
            <div style={{ fontSize: 17, fontWeight: 700, color: day.isToday ? C.primary : '#fff' }}>
              {day.date.slice(3)}
            </div>
            <div style={{
              fontSize: 16, fontWeight: 700,
              color: statusColor(day.status),
            }}>
              {statusIcon(day.status)}
            </div>
          </button>
        ))}
      </div>

      {/* 选中日详情 */}
      <div style={{ padding: '0 16px' }}>
        <div style={{
          background: C.card, borderRadius: 16, padding: '20px',
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 16, color: C.muted, marginBottom: 12 }}>
            {selected.date} {selected.weekday}
            {selected.isToday && (
              <span style={{
                marginLeft: 8, fontSize: 13, color: C.primary,
                border: `1px solid ${C.primary}`, borderRadius: 4, padding: '1px 6px',
              }}>
                今天
              </span>
            )}
          </div>

          {selected.shift ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <div style={{
                  padding: '6px 14px', borderRadius: 20, fontSize: 16, fontWeight: 700,
                  background: `${shiftColors[selected.shift] ?? C.primary}33`,
                  color: shiftColors[selected.shift] ?? C.primary,
                  border: `1px solid ${shiftColors[selected.shift] ?? C.primary}55`,
                }}>
                  {selected.shift}
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#fff' }}>
                  {selected.timeRange}
                </div>
              </div>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <div style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: statusColor(selected.status),
                }} />
                <span style={{ fontSize: 16, color: statusColor(selected.status) }}>
                  {selected.status === 'present' && '已到岗'}
                  {selected.status === 'absent'  && '缺勤'}
                  {selected.status === 'today'   && '今天在班'}
                  {selected.status === 'pending' && '待排班'}
                </span>
              </div>
            </>
          ) : (
            <div style={{ fontSize: 16, color: C.muted, padding: '8px 0' }}>
              该日暂无排班
            </div>
          )}
        </div>

        {/* 本周出勤统计 */}
        <h3 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '20px 0 10px' }}>
          本周出勤
        </h3>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10,
        }}>
          {[
            { label: '应到班', value: schedule.filter(d => d.shift).length, color: C.text },
            { label: '已到岗', value: schedule.filter(d => d.status === 'present' || d.status === 'today').length, color: C.success },
            { label: '缺勤',   value: schedule.filter(d => d.status === 'absent').length,  color: C.danger },
          ].map(item => (
            <div key={item.label} style={{
              background: C.card, borderRadius: 12, padding: '14px 10px',
              border: `1px solid ${C.border}`, textAlign: 'center',
            }}>
              <div style={{ fontSize: 24, fontWeight: 800, color: item.color, marginBottom: 4 }}>
                {item.value}
              </div>
              <div style={{ fontSize: 13, color: C.muted }}>{item.label}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- Tab 3 — 换班申请 ---------- */
function ShiftSwapTab() {
  const [swaps, setSwaps]             = useState<ShiftSwap[]>(MOCK_SWAPS);
  const [showModal, setShowModal]     = useState(false);
  const [fromDate, setFromDate]       = useState('');
  const [toCrew, setToCrew]           = useState('');
  const [reason, setReason]           = useState('');
  const [submitting, setSubmitting]   = useState(false);
  const [toast, setToast]             = useState('');

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }

  async function handleSubmit() {
    if (!fromDate || !toCrew) {
      showToast('请选择日期和接班同事');
      return;
    }
    setSubmitting(true);
    try {
      await fetch('/api/v1/crew/shift-swap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_date: fromDate, to_crew_id: toCrew, reason }),
      });
      const newSwap: ShiftSwap = {
        id: `sw-${Date.now()}`,
        fromDate,
        toCrew,
        reason,
        status: 'pending',
        createdAt: formatDate(new Date()) + ' ' + formatTime(new Date()).slice(0, 5),
      };
      setSwaps(prev => [newSwap, ...prev]);
      setShowModal(false);
      setFromDate('');
      setToCrew('');
      setReason('');
      showToast('换班申请已提交');
    } catch {
      showToast('提交失败，请重试');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ padding: '16px 16px 0' }}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', top: 72, left: '50%', transform: 'translateX(-50%)',
          background: '#1e2e38', color: '#fff', borderRadius: 10,
          padding: '10px 20px', fontSize: 15, zIndex: 200,
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
          border: `1px solid ${C.border}`,
        }}>
          {toast}
        </div>
      )}

      {/* 发起换班 */}
      <button
        onClick={() => setShowModal(true)}
        style={{
          width: '100%', minHeight: 56, borderRadius: 14, fontSize: 18, fontWeight: 700,
          border: 'none', cursor: 'pointer', background: C.primary, color: '#fff',
          marginBottom: 20,
        }}
      >
        + 发起换班申请
      </button>

      {/* 申请列表 */}
      <h3 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 10px' }}>
        我的申请
      </h3>
      <div style={{
        background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
        overflow: 'hidden',
      }}>
        {swaps.length === 0 ? (
          <div style={{ padding: '24px 16px', fontSize: 15, color: C.muted, textAlign: 'center' }}>
            暂无换班申请
          </div>
        ) : (
          swaps.map((swap, i) => (
            <div
              key={swap.id}
              style={{
                padding: '16px', minHeight: 72,
                borderBottom: i < swaps.length - 1 ? `1px solid ${C.border}` : 'none',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 17, fontWeight: 700, color: '#fff' }}>
                  {swap.fromDate} 换给 {swap.toCrew}
                </span>
                <span style={{
                  fontSize: 13, fontWeight: 600, color: swapStatusColor(swap.status),
                  border: `1px solid ${swapStatusColor(swap.status)}`,
                  borderRadius: 6, padding: '2px 8px',
                }}>
                  {swapStatusLabel(swap.status)}
                </span>
              </div>
              {swap.reason && (
                <div style={{ fontSize: 14, color: C.muted, marginBottom: 4 }}>
                  原因：{swap.reason}
                </div>
              )}
              <div style={{ fontSize: 13, color: C.inactive }}>
                申请时间：{swap.createdAt}
              </div>
            </div>
          ))
        )}
      </div>

      {/* 底部弹出模态框 */}
      {showModal && (
        <div
          onClick={() => setShowModal(false)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 100,
            display: 'flex', alignItems: 'flex-end',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              width: '100%', background: '#112228',
              borderRadius: '20px 20px 0 0',
              border: `1px solid ${C.border}`,
              padding: '24px 20px 40px',
            }}
          >
            <div style={{ fontSize: 18, fontWeight: 700, color: '#fff', marginBottom: 20, textAlign: 'center' }}>
              发起换班申请
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 15, color: C.muted, display: 'block', marginBottom: 6 }}>
                换班日期
              </label>
              <input
                type="date"
                value={fromDate}
                onChange={e => setFromDate(e.target.value)}
                style={{
                  width: '100%', minHeight: 52, borderRadius: 12, fontSize: 16,
                  background: '#0B1A20', color: '#fff',
                  border: `1px solid ${C.border}`, padding: '0 14px',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 15, color: C.muted, display: 'block', marginBottom: 6 }}>
                接班同事
              </label>
              <select
                value={toCrew}
                onChange={e => setToCrew(e.target.value)}
                style={{
                  width: '100%', minHeight: 52, borderRadius: 12, fontSize: 16,
                  background: '#0B1A20', color: toCrew ? '#fff' : C.muted,
                  border: `1px solid ${C.border}`, padding: '0 14px',
                  boxSizing: 'border-box',
                }}
              >
                <option value="" disabled>请选择同事</option>
                {MOCK_CREW_LIST.map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>

            <div style={{ marginBottom: 24 }}>
              <label style={{ fontSize: 15, color: C.muted, display: 'block', marginBottom: 6 }}>
                换班原因（选填）
              </label>
              <textarea
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="填写换班原因..."
                rows={3}
                style={{
                  width: '100%', borderRadius: 12, fontSize: 16,
                  background: '#0B1A20', color: '#fff',
                  border: `1px solid ${C.border}`, padding: '12px 14px',
                  boxSizing: 'border-box', resize: 'none',
                  lineHeight: 1.5,
                }}
              />
            </div>

            <button
              onClick={handleSubmit}
              disabled={submitting}
              style={{
                width: '100%', minHeight: 56, borderRadius: 14, fontSize: 18, fontWeight: 700,
                border: 'none', cursor: submitting ? 'not-allowed' : 'pointer',
                background: submitting ? C.inactive : C.primary,
                color: '#fff', opacity: submitting ? 0.7 : 1,
              }}
            >
              {submitting ? '提交中...' : '确认提交'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- 主组件 ---------- */
type TabKey = 'checkin' | 'schedule' | 'swap';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'checkin',  label: '今日打卡' },
  { key: 'schedule', label: '本周排班' },
  { key: 'swap',     label: '换班申请' },
];

export function ShiftSchedulePage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>('checkin');

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.text, paddingBottom: 80 }}>
      {/* 顶部导航 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 16px 0', borderBottom: `1px solid ${C.border}`,
        position: 'sticky', top: 0, background: C.bg, zIndex: 10,
      }}>
        <button
          onClick={() => navigate('/profile')}
          style={{
            background: 'none', border: 'none', color: C.text, fontSize: 18,
            cursor: 'pointer', padding: '4px 8px 4px 0', minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center',
          }}
        >
          ←
        </button>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>排班打卡</span>
        <div style={{ width: 48 }} />
      </div>

      {/* Tab 切换栏 */}
      <div style={{
        display: 'flex', borderBottom: `1px solid ${C.border}`,
        position: 'sticky', top: 56, background: C.bg, zIndex: 9,
      }}>
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            style={{
              flex: 1, minHeight: 48, fontSize: 16, fontWeight: activeTab === t.key ? 700 : 400,
              background: 'none', border: 'none', cursor: 'pointer',
              color: activeTab === t.key ? C.primary : C.muted,
              borderBottom: activeTab === t.key ? `2px solid ${C.primary}` : '2px solid transparent',
              transition: 'color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      {activeTab === 'checkin'  && <CheckinTab />}
      {activeTab === 'schedule' && <ScheduleTab />}
      {activeTab === 'swap'     && <ShiftSwapTab />}
    </div>
  );
}
