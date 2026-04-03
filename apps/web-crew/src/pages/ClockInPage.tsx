/**
 * 打卡全屏页 — 服务员/厨师手机PWA
 * 路由: /schedule-clock（全屏，hiddenPaths 中，无底部 TabBar）
 *
 * 设计：
 *  - 全屏深色背景 #0B1A20
 *  - 顶部：当前时间（大字）+ 日期
 *  - 中心：超大圆形打卡按钮（直径200px）
 *  - 按钮周围：当前状态描述
 *  - 成功：CSS圆形扩散动画
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ─────────────────────────────────────────
   Tokens
───────────────────────────────────────── */
const T = {
  bg:         '#0B1A20',
  card:       '#112228',
  border:     '#1a2a33',
  text:       '#E0E0E0',
  muted:      '#64748b',
  dim:        '#334155',
  primary:    '#FF6B35',
  primaryAct: '#E55A28',
  navy:       '#1E2A3A',
  success:    '#0F6E56',
  successBg:  '#0a2820',
  successTxt: '#30D158',
};

type ClockStatus = 'not_clocked' | 'clocked_in' | 'clocked_out';

interface TodayAttendance {
  status:     ClockStatus;
  clockInAt:  string | null;
  clockOutAt: string | null;
  totalHours: number | null;
}

/* ─────────────────────────────────────────
   工具
───────────────────────────────────────── */
const WEEKDAY_LABELS = ['日', '一', '二', '三', '四', '五', '六'];

function padZ(n: number) { return String(n).padStart(2, '0'); }

function formatHHMMSS(d: Date) {
  return `${padZ(d.getHours())}:${padZ(d.getMinutes())}:${padZ(d.getSeconds())}`;
}

function formatDateFull(d: Date) {
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 周${WEEKDAY_LABELS[d.getDay()]}`;
}

function hhmm(iso: string | null): string {
  if (!iso) return '--:--';
  const d = iso.includes('T') ? new Date(iso) : null;
  if (d) return `${padZ(d.getHours())}:${padZ(d.getMinutes())}`;
  return iso.slice(0, 5);
}

function diffSeconds(fromIso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(fromIso).getTime()) / 1000));
}

function formatDuration(secs: number): string {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `${padZ(h)}:${padZ(m)}:${padZ(s)}`;
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

/* ─────────────────────────────────────────
   成功扩散动画覆盖层
───────────────────────────────────────── */
function RippleOverlay({ color }: { color: string }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, display: 'flex',
      alignItems: 'center', justifyContent: 'center',
      pointerEvents: 'none', zIndex: 50,
    }}>
      {[0, 150, 300].map(delay => (
        <div key={delay} style={{
          position: 'absolute',
          width: 200, height: 200,
          borderRadius: '50%',
          border: `3px solid ${color}`,
          animation: `rippleOut 0.9s ${delay}ms ease-out forwards`,
          opacity: 0,
        }} />
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────
   主页面
───────────────────────────────────────── */
export function ClockInPage() {
  const navigate  = useNavigate();
  const storeId    = localStorage.getItem('storeId')    ?? '';
  const employeeId = localStorage.getItem('employeeId') ?? '';

  /* ── 时钟 ── */
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  /* ── 打卡状态 ── */
  const [att, setAtt] = useState<TodayAttendance>({
    status: 'not_clocked', clockInAt: null, clockOutAt: null, totalHours: null,
  });
  const [loading, setLoading] = useState(true);

  /* ── 计时器 ── */
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── 操作 ── */
  const [actionLoading, setActionLoading] = useState(false);
  const [rippleColor,   setRippleColor]   = useState('');
  const [showRipple,    setShowRipple]    = useState(false);

  /* ── Toast ── */
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  function showToast(msg: string, type: 'success' | 'error' = 'success') {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2800);
  }

  /* ── 加载今日考勤 ── */
  const loadAtt = useCallback(async () => {
    setLoading(true);
    try {
      type ApiToday = {
        status: ClockStatus;
        clock_in_at:  string | null;
        clock_out_at: string | null;
        total_hours:  number | null;
      };
      const data = await apiGet<ApiToday>(`/api/v1/attendance/today?store_id=${storeId}`);
      setAtt({
        status:     data.status,
        clockInAt:  data.clock_in_at,
        clockOutAt: data.clock_out_at,
        totalHours: data.total_hours,
      });
    } catch {
      // 降级读缓存
      const cached = localStorage.getItem('todayAttendance');
      if (cached) {
        try { setAtt(JSON.parse(cached) as TodayAttendance); } catch { /* ignore */ }
      }
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => { void loadAtt(); }, [loadAtt]);

  /* ── 计时器 ── */
  useEffect(() => {
    if (att.status === 'clocked_in' && att.clockInAt) {
      setElapsed(diffSeconds(att.clockInAt));
      timerRef.current = setInterval(() => {
        setElapsed(diffSeconds(att.clockInAt!));
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
      setElapsed(0);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [att]);

  /* ── 打卡 ── */
  async function handleClock() {
    if (att.status === 'clocked_out') return;
    const type  = att.status === 'not_clocked' ? 'in' : 'out';
    const label = type === 'in' ? '上班打卡' : '下班打卡';
    const timeStr = formatHHMMSS(new Date());

    const confirmed = window.confirm(`确认${label}？\n当前时间：${timeStr}`);
    if (!confirmed) return;

    setActionLoading(true);
    try {
      const url = type === 'in'
        ? '/api/v1/attendance/clock-in'
        : '/api/v1/attendance/clock-out';
      type ClockResp = { clock_in_at?: string; clock_out_at?: string; total_hours?: number };
      const resp = await apiPost<ClockResp>(url, {
        store_id: storeId, employee_id: employeeId,
      });

      const color = type === 'in' ? T.primary : T.successTxt;
      setRippleColor(color);
      setShowRipple(true);
      setTimeout(() => setShowRipple(false), 1000);

      const newAtt: TodayAttendance = type === 'in'
        ? { status: 'clocked_in',  clockInAt: resp.clock_in_at ?? new Date().toISOString(), clockOutAt: null, totalHours: null }
        : { status: 'clocked_out', clockInAt: att.clockInAt, clockOutAt: resp.clock_out_at ?? new Date().toISOString(), totalHours: resp.total_hours ?? null };

      setAtt(newAtt);
      localStorage.setItem('todayAttendance', JSON.stringify(newAtt));
      showToast(`${label}成功 ${timeStr.slice(0, 5)}`);
    } catch {
      showToast(`${label}失败，请重试`, 'error');
    } finally {
      setActionLoading(false);
    }
  }

  /* ─── 大按钮配置 ─── */
  const btnConfig: Record<ClockStatus, {
    label:    string;
    subLabel: string;
    btnColor: string;
    glow:     string;
    textColor: string;
    border:   string;
    disabled: boolean;
  }> = {
    not_clocked: {
      label:    '上班打卡',
      subLabel: '点击开始今天的班次',
      btnColor: T.primary,
      glow:     `${T.primary}44`,
      textColor: '#fff',
      border:   'none',
      disabled: false,
    },
    clocked_in: {
      label:    '下班打卡',
      subLabel: `已上班 ${formatDuration(elapsed)}`,
      btnColor: T.navy,
      glow:     `${T.primary}33`,
      textColor: '#fff',
      border:   `3px solid ${T.primary}`,
      disabled: false,
    },
    clocked_out: {
      label:    '已完成',
      subLabel: `今日工时 ${att.totalHours != null ? att.totalHours.toFixed(1) + 'h' : '--'}`,
      btnColor: T.success,
      glow:     `${T.successTxt}33`,
      textColor: '#fff',
      border:   'none',
      disabled: true,
    },
  };

  const cfg = loading
    ? { label: '…', subLabel: '加载中', btnColor: T.dim, glow: 'transparent', textColor: T.muted, border: 'none', disabled: true }
    : btnConfig[att.status];

  return (
    <div style={{
      background: T.bg, minHeight: '100vh', color: T.text,
      display: 'flex', flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
    }}>
      {/* keyframes */}
      <style>{`
        @keyframes rippleOut {
          0%   { transform: scale(1); opacity: 0.8; }
          100% { transform: scale(4); opacity: 0; }
        }
        @keyframes fadeInDown {
          from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
          to   { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
        @keyframes pulseGlow {
          0%, 100% { box-shadow: 0 0 30px var(--glow); }
          50%       { box-shadow: 0 0 60px var(--glow); }
        }
        .clock-circle:active:not([disabled]) {
          transform: scale(0.94) !important;
        }
      `}</style>

      {showRipple && <RippleOverlay color={rippleColor} />}

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)',
          background: toast.type === 'error' ? '#3a1010' : T.successBg,
          color: toast.type === 'error' ? '#ff6b6b' : T.successTxt,
          border: `1px solid ${toast.type === 'error' ? '#7a2020' : T.success}`,
          borderRadius: 12, padding: '12px 24px',
          fontSize: 16, fontWeight: 600, zIndex: 999,
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
          animation: 'fadeInDown 0.2s ease',
          whiteSpace: 'nowrap',
        }}>
          {toast.msg}
        </div>
      )}

      {/* ── 顶部导航栏 ── */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '16px 16px 12px',
        borderBottom: `1px solid ${T.border}`,
      }}>
        <button
          onClick={() => navigate('/schedule')}
          style={{
            background: 'none', border: 'none', color: T.text,
            fontSize: 18, cursor: 'pointer',
            minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            borderRadius: 10,
          }}
        >
          ←
        </button>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#fff', marginLeft: 8 }}>
          打卡
        </span>
      </div>

      {/* ── 当前时间（大字） ── */}
      <div style={{ textAlign: 'center', padding: '32px 16px 0' }}>
        <div style={{
          fontSize: 56, fontWeight: 800, letterSpacing: 2,
          color: '#fff', lineHeight: 1.1,
          fontVariantNumeric: 'tabular-nums',
        }}>
          {formatHHMMSS(now)}
        </div>
        <div style={{ fontSize: 16, color: T.muted, marginTop: 8 }}>
          {formatDateFull(now)}
        </div>
      </div>

      {/* ── 上班/下班时间显示（已打卡时） ── */}
      {!loading && (att.status === 'clocked_in' || att.status === 'clocked_out') && (
        <div style={{
          display: 'flex', justifyContent: 'center', gap: 36,
          padding: '20px 16px 0',
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: T.muted }}>上班打卡</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: T.successTxt }}>
              {hhmm(att.clockInAt)}
            </div>
          </div>
          {att.status === 'clocked_out' && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 13, color: T.muted }}>下班打卡</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#fff' }}>
                {hhmm(att.clockOutAt)}
              </div>
            </div>
          )}
          {att.status === 'clocked_in' && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 13, color: T.muted }}>已上班</div>
              <div style={{
                fontSize: 20, fontWeight: 800, color: T.primary,
                fontVariantNumeric: 'tabular-nums',
              }}>
                {formatDuration(elapsed)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── 中心超大打卡按钮 ── */}
      <div style={{
        flex: 1, display: 'flex',
        flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        padding: '24px 16px',
        gap: 24,
      }}>
        {/* 提示文字 */}
        <div style={{ fontSize: 16, color: T.muted, textAlign: 'center' }}>
          {cfg.subLabel}
        </div>

        {/* 超大圆形按钮 */}
        <button
          className="clock-circle"
          onClick={handleClock}
          disabled={cfg.disabled || actionLoading}
          style={{
            width: 200, height: 200, borderRadius: '50%',
            background: actionLoading ? T.dim : cfg.btnColor,
            border: cfg.border || 'none',
            color: cfg.textColor,
            fontSize: 24, fontWeight: 800,
            cursor: cfg.disabled || actionLoading ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'transform 0.2s, box-shadow 0.2s',
            boxShadow: cfg.disabled || actionLoading
              ? 'none'
              : `0 0 40px ${cfg.glow}, 0 0 0 0 ${cfg.glow}`,
            opacity: actionLoading ? 0.7 : 1,
            ['--glow' as string]: cfg.glow,
            animation: !cfg.disabled && !actionLoading
              ? 'pulseGlow 2.5s ease-in-out infinite'
              : 'none',
          } as React.CSSProperties}
        >
          {actionLoading ? '…' : cfg.label}
        </button>
      </div>

      {/* ── 今日已完成：工时总结 ── */}
      {!loading && att.status === 'clocked_out' && (
        <div style={{
          margin: '0 16px 24px',
          background: T.successBg, borderRadius: 14,
          border: `1px solid ${T.success}`, padding: '16px 20px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 16, color: T.successTxt, fontWeight: 700, marginBottom: 6 }}>
            今日出勤完成
          </div>
          {att.totalHours != null && (
            <div style={{ fontSize: 28, fontWeight: 800, color: '#fff' }}>
              共 <span style={{ color: T.primary }}>{att.totalHours.toFixed(1)}</span> 小时
            </div>
          )}
        </div>
      )}
    </div>
  );
}
