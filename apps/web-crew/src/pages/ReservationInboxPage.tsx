/**
 * 预订收件箱 — 多渠道统一预订管理
 *
 * 功能：日期切换 / 渠道筛选 / 状态操作 / 预订→开台直通车
 * 实时：WebSocket 实时推送（新预订立即显示 + 提示音 + Toast）
 * 降级：WS 连接失败 5 次后自动切换为 30 秒轮询
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchReservations,
  confirmArrival,
  assignTable,
  cancelReservation,
  markNoShow,
  computeStats,
  triggerMockReservation,
} from '../api/reservationApi';
import type { Reservation, ReservationChannel, ReservationStatus } from '../api/reservationApi';
import { useReservationWS } from '../hooks/useReservationWS';
import type { ReservationWSMessage } from '../hooks/useReservationWS';

// ─── 设计 Token ───────────────────────────────────────────────────────────────

const C = {
  bg:       '#0B1A20',
  card:     '#112228',
  border:   '#1a2a33',
  accent:   '#FF6B35',
  green:    '#22c55e',
  danger:   '#ef4444',
  warning:  '#f97316',
  muted:    '#64748b',
  text:     '#f1f5f9',
  subtext:  '#94a3b8',
  // 渠道色
  meituan:  '#F5A623',
  dianping: '#E64545',
  wechat:   '#07C160',
  phone:    '#64748b',
  walkin:   '#64748b',
} as const;

// ─── Toast 接口 ───────────────────────────────────────────────────────────────

interface ToastInfo {
  id: number;
  source: string;
  customerName: string;
  partySize: number;
  time: string;
  tableType: string;
}

// ─── 提示音（Web Audio API） ──────────────────────────────────────────────────

function playNotificationSound(): void {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.15);
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.4);
  } catch {
    // 浏览器不支持 AudioContext 时静默忽略
  }
}

// ─── 渠道显示 ─────────────────────────────────────────────────────────────────

const CHANNEL_LABEL: Record<ReservationChannel, string> = {
  meituan:  '美团',
  dianping: '大众',
  wechat:   '微信',
  phone:    '电话',
  walkin:   '现场',
};

const CHANNEL_COLOR: Record<ReservationChannel, string> = {
  meituan:  C.meituan,
  dianping: C.dianping,
  wechat:   C.wechat,
  phone:    C.phone,
  walkin:   C.walkin,
};

// ─── 状态显示 ─────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<ReservationStatus, string> = {
  pending:   '待确认',
  confirmed: '已确认',
  arrived:   '已到店',
  seated:    '已入座',
  completed: '已完成',
  cancelled: '已取消',
  no_show:   '爽约',
};

function statusColor(s: ReservationStatus): string {
  switch (s) {
    case 'pending':   return C.warning;
    case 'confirmed': return C.green;
    case 'arrived':   return C.accent;
    case 'seated':    return C.accent;
    case 'no_show':   return C.danger;
    case 'cancelled': return C.muted;
    default:          return C.muted;
  }
}

// ─── 日期工具 ─────────────────────────────────────────────────────────────────

function formatDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function dateLabel(dateStr: string, todayStr: string): string {
  const diff = (new Date(dateStr).getTime() - new Date(todayStr).getTime()) / 86400000;
  if (diff === -1) return '昨天';
  if (diff === 0)  return '今天';
  if (diff === 1)  return '明天';
  if (diff === 2)  return '后天';
  // 04-05 格式
  return dateStr.slice(5);
}

function buildDateRange(): string[] {
  const today = new Date();
  return [-1, 0, 1, 2, 3, 4].map(offset => {
    const d = new Date(today);
    d.setDate(d.getDate() + offset);
    return formatDate(d);
  });
}

// ─── 渠道 Badge ───────────────────────────────────────────────────────────────

function ChannelBadge({ channel }: { channel: ReservationChannel }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 6,
      fontSize: 13,
      fontWeight: 700,
      background: CHANNEL_COLOR[channel],
      color: '#fff',
      flexShrink: 0,
    }}>
      {CHANNEL_LABEL[channel]}
    </span>
  );
}

// ─── 预订卡片 ─────────────────────────────────────────────────────────────────

interface CardProps {
  r: Reservation;
  onArrival: (id: string) => void;
  onAssign: (r: Reservation) => void;
  onCancel: (id: string) => void;
  onNoShow: (id: string) => void;
  actionLoading: boolean;
}

function ReservationCard({ r, onArrival, onAssign, onCancel, onNoShow, actionLoading }: CardProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  const phone = r.customer_phone || r.phone || '';
  const tableType = r.table_type || r.room_name || '大厅';
  const specialReq = r.special_request || r.special_requests || '';

  const isActive = r.status === 'pending' || r.status === 'confirmed' || r.status === 'arrived';

  return (
    <div style={{
      background: C.card,
      borderRadius: 12,
      padding: 16,
      marginBottom: 10,
      border: `1px solid ${C.border}`,
      opacity: isActive ? 1 : 0.65,
      position: 'relative',
    }}>
      {/* 顶行：渠道 + 时间 + 姓名 + 人数 + 桌型 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <ChannelBadge channel={r.source_channel} />
        <span style={{ fontSize: 18, fontWeight: 700, color: C.accent }}>
          {r.time}
        </span>
        <span style={{ fontSize: 18, fontWeight: 600, color: C.text }}>
          {r.customer_name}
        </span>
        <span style={{ fontSize: 16, color: C.subtext }}>
          {r.party_size}人 · {tableType}
        </span>
      </div>

      {/* 特殊需求 */}
      {specialReq && (
        <div style={{
          marginTop: 8, fontSize: 15, color: C.subtext,
          background: 'rgba(255,255,255,0.04)',
          borderRadius: 6, padding: '4px 10px',
        }}>
          {specialReq}
        </div>
      )}

      {/* 状态行 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
        <span style={{
          fontSize: 13, padding: '2px 8px', borderRadius: 10,
          background: `${statusColor(r.status)}22`,
          color: statusColor(r.status),
          border: `1px solid ${statusColor(r.status)}44`,
        }}>
          {STATUS_LABEL[r.status]}
        </span>
        {r.assigned_table && (
          <span style={{ fontSize: 13, color: C.muted }}>桌号 {r.assigned_table}</span>
        )}
      </div>

      {/* 分割线 */}
      {isActive && (
        <div style={{ height: 1, background: C.border, margin: '12px 0' }} />
      )}

      {/* 操作按钮 */}
      {isActive && (
        <div style={{ display: 'flex', gap: 8, position: 'relative' }}>
          {/* 确认到店 / 安排入座 */}
          {(r.status === 'pending' || r.status === 'confirmed') && (
            <button
              disabled={actionLoading}
              onClick={() => onArrival(r.reservation_id || r.id)}
              style={{
                flex: 1, minHeight: 48, borderRadius: 8,
                background: C.green, color: '#fff', border: 'none',
                fontSize: 16, fontWeight: 600,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
                opacity: actionLoading ? 0.7 : 1,
              }}
            >
              确认到店
            </button>
          )}

          {r.status === 'arrived' && (
            <button
              disabled={actionLoading}
              onClick={() => onAssign(r)}
              style={{
                flex: 1, minHeight: 48, borderRadius: 8,
                background: C.accent, color: '#fff', border: 'none',
                fontSize: 16, fontWeight: 600,
                cursor: actionLoading ? 'not-allowed' : 'pointer',
                opacity: actionLoading ? 0.7 : 1,
              }}
            >
              安排入座
            </button>
          )}

          {/* 联系顾客 */}
          {phone && (
            <button
              onClick={() => { window.location.href = `tel:${phone}`; }}
              style={{
                flex: 1, minHeight: 48, borderRadius: 8,
                background: 'transparent',
                border: `1px solid ${C.border}`,
                color: C.subtext, fontSize: 16, fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              联系顾客
            </button>
          )}

          {/* 更多菜单 */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setMenuOpen(v => !v)}
              style={{
                minWidth: 48, minHeight: 48, borderRadius: 8,
                background: 'transparent',
                border: `1px solid ${C.border}`,
                color: C.subtext, fontSize: 20, cursor: 'pointer',
              }}
            >
              ⋮
            </button>
            {menuOpen && (
              <>
                {/* 遮罩关闭 */}
                <div
                  onClick={() => setMenuOpen(false)}
                  style={{ position: 'fixed', inset: 0, zIndex: 200 }}
                />
                <div style={{
                  position: 'absolute', right: 0, bottom: 56,
                  background: C.card, border: `1px solid ${C.border}`,
                  borderRadius: 10, padding: '4px 0',
                  minWidth: 140, zIndex: 201, boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
                }}>
                  <MenuBtn
                    label="取消预订"
                    color={C.danger}
                    onClick={() => { setMenuOpen(false); onCancel(r.reservation_id || r.id); }}
                  />
                  <MenuBtn
                    label="标记爽约"
                    color={C.warning}
                    onClick={() => { setMenuOpen(false); onNoShow(r.reservation_id || r.id); }}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MenuBtn({ label, color, onClick }: { label: string; color: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'block', width: '100%', textAlign: 'left',
        padding: '12px 16px', background: 'none', border: 'none',
        color, fontSize: 16, cursor: 'pointer',
        minHeight: 48,
      }}
    >
      {label}
    </button>
  );
}

// ─── 桌台输入对话框 ───────────────────────────────────────────────────────────

interface AssignDialogProps {
  reservation: Reservation;
  onClose: () => void;
  onConfirm: (tableNo: string) => void;
  loading: boolean;
}

function AssignDialog({ reservation, onClose, onConfirm, loading }: AssignDialogProps) {
  const [tableNo, setTableNo] = useState('');

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 300 }}
      />
      <div style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        background: C.card, borderRadius: 16, padding: '24px 20px',
        zIndex: 301, width: '82%', maxWidth: 360,
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text, marginBottom: 6 }}>
          安排入座
        </div>
        <div style={{ fontSize: 14, color: C.muted, marginBottom: 16 }}>
          {reservation.customer_name} · {reservation.party_size}人
        </div>
        <input
          type="text"
          value={tableNo}
          onChange={e => setTableNo(e.target.value)}
          placeholder="输入桌台号，如 A01、B12"
          autoFocus
          style={{
            width: '100%', minHeight: 48, borderRadius: 10, padding: '0 14px',
            background: '#0d1e26', border: `1px solid #1e3040`,
            color: C.text, fontSize: 16, marginBottom: 16,
            boxSizing: 'border-box',
          }}
        />
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={onClose}
            style={{
              flex: 1, minHeight: 48, borderRadius: 10,
              background: 'transparent', border: `1px solid ${C.border}`,
              color: C.subtext, fontSize: 16, cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            disabled={loading || !tableNo.trim()}
            onClick={() => tableNo.trim() && onConfirm(tableNo.trim())}
            style={{
              flex: 1, minHeight: 48, borderRadius: 10,
              background: loading || !tableNo.trim() ? C.muted : C.accent,
              color: '#fff', border: 'none',
              fontSize: 16, fontWeight: 700,
              cursor: loading || !tableNo.trim() ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? '处理中...' : '确认并开台'}
          </button>
        </div>
      </div>
    </>
  );
}

// ─── 取消原因对话框 ───────────────────────────────────────────────────────────

interface CancelDialogProps {
  reservationId: string;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  loading: boolean;
}

function CancelDialog({ onClose, onConfirm, loading }: CancelDialogProps) {
  const [reason, setReason] = useState('');

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 300 }}
      />
      <div style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        background: C.card, borderRadius: 16, padding: '24px 20px',
        zIndex: 301, width: '82%', maxWidth: 360,
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text, marginBottom: 16 }}>
          取消预订原因
        </div>
        <textarea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="请输入取消原因..."
          rows={3}
          style={{
            width: '100%', borderRadius: 10, padding: '10px 14px',
            background: '#0d1e26', border: `1px solid #1e3040`,
            color: C.text, fontSize: 16, marginBottom: 16,
            boxSizing: 'border-box', resize: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={onClose}
            style={{
              flex: 1, minHeight: 48, borderRadius: 10,
              background: 'transparent', border: `1px solid ${C.border}`,
              color: C.subtext, fontSize: 16, cursor: 'pointer',
            }}
          >
            返回
          </button>
          <button
            disabled={loading || !reason.trim()}
            onClick={() => reason.trim() && onConfirm(reason.trim())}
            style={{
              flex: 1, minHeight: 48, borderRadius: 10,
              background: loading || !reason.trim() ? C.muted : C.danger,
              color: '#fff', border: 'none',
              fontSize: 16, fontWeight: 700,
              cursor: loading || !reason.trim() ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? '处理中...' : '确认取消'}
          </button>
        </div>
      </div>
    </>
  );
}

// ─── 新预订 Toast 通知 ────────────────────────────────────────────────────────

const SOURCE_LABEL: Record<string, string> = {
  meituan:  '美团',
  dianping: '大众点评',
  wechat:   '微信',
  phone:    '电话',
  walkin:   '现场',
};

interface NewReservationToastProps {
  toasts: ToastInfo[];
  onDismiss: (id: number) => void;
}

function NewReservationToastStack({ toasts, onDismiss }: NewReservationToastProps) {
  if (toasts.length === 0) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 60,
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: 1000,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      width: 'min(92vw, 360px)',
      pointerEvents: 'none',
    }}>
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastInfo; onDismiss: (id: number) => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // 触发滑入动画
    const showTimer = setTimeout(() => setVisible(true), 10);
    // 3 秒后滑出并移除
    const hideTimer = setTimeout(() => {
      setVisible(false);
      setTimeout(() => onDismiss(toast.id), 300);
    }, 3000);
    return () => {
      clearTimeout(showTimer);
      clearTimeout(hideTimer);
    };
  }, [toast.id, onDismiss]);

  return (
    <div
      style={{
        background: C.card,
        borderLeft: `4px solid ${C.accent}`,
        borderRadius: 10,
        padding: '12px 16px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
        transform: visible ? 'translateY(0)' : 'translateY(-16px)',
        opacity: visible ? 1 : 0,
        transition: 'transform 0.25s ease, opacity 0.25s ease',
        pointerEvents: 'auto',
        cursor: 'pointer',
        border: `1px solid ${C.border}`,
        borderLeftWidth: 4,
      }}
      onClick={() => {
        setVisible(false);
        setTimeout(() => onDismiss(toast.id), 300);
      }}
    >
      <div style={{
        fontSize: 13, fontWeight: 700, color: C.accent,
        marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span>新预订</span>
        <span style={{
          background: C.accent + '22', color: C.accent,
          border: `1px solid ${C.accent}44`,
          borderRadius: 4, padding: '0 6px', fontSize: 12,
        }}>
          {SOURCE_LABEL[toast.source] ?? toast.source}
        </span>
      </div>
      <div style={{ fontSize: 15, color: C.text, fontWeight: 600 }}>
        {toast.customerName}
        <span style={{ color: C.subtext, fontWeight: 400, marginLeft: 8 }}>
          {toast.partySize}人 · {toast.time} · {toast.tableType || '大厅'}
        </span>
      </div>
    </div>
  );
}

// ─── WS 连接状态指示点 ────────────────────────────────────────────────────────

function WSStatusDot({ connected }: { connected: boolean }) {
  return (
    <div
      title={connected ? 'WebSocket 已连接' : '断开重连中...'}
      style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: connected ? C.green : C.muted,
        flexShrink: 0,
        boxShadow: connected ? `0 0 6px ${C.green}` : 'none',
        transition: 'background 0.3s, box-shadow 0.3s',
      }}
    />
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function ReservationInboxPage() {
  const navigate = useNavigate();
  const storeId = (window as typeof window & { __STORE_ID__?: string }).__STORE_ID__ || 'store_001';

  const todayStr = formatDate(new Date());
  const dateRange = buildDateRange();

  const [selectedDate, setSelectedDate] = useState(todayStr);
  const [selectedChannel, setSelectedChannel] = useState<ReservationChannel | 'all'>('all');
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assignTarget, setAssignTarget] = useState<Reservation | null>(null);
  const [cancelTargetId, setCancelTargetId] = useState<string | null>(null);
  const [mockLoading, setMockLoading] = useState(false);

  // WS 状态
  const [wsConnected, setWsConnected] = useState(false);
  const [useFallbackPolling, setUseFallbackPolling] = useState(false);
  // Toast 队列
  const [toasts, setToasts] = useState<ToastInfo[]>([]);
  const toastCounterRef = useRef(0);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 数据加载 ──────────────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchReservations(storeId, { date: selectedDate });
      setReservations(result.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId, selectedDate]);

  // 初始加载
  useEffect(() => {
    loadData();
  }, [loadData]);

  // 降级轮询：WS 失败时启用，WS 恢复时停止
  useEffect(() => {
    if (!useFallbackPolling) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    timerRef.current = setInterval(loadData, 30000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [useFallbackPolling, loadData]);

  // ── WS 消息处理 ───────────────────────────────────────────────────────────

  const handleWsMessage = useCallback((msg: ReservationWSMessage) => {
    if (msg.type !== 'new_reservation') return;

    const raw = msg.reservation;
    // 简单适配：直接映射常用字段
    const newItem: Reservation = {
      id: (raw.id ?? raw.reservation_id ?? '') as string,
      reservation_id: (raw.reservation_id ?? '') as string,
      reservation_no: (raw.confirmation_code ?? raw.reservation_no) as string | undefined,
      source_channel: ((raw.source_channel as string) || 'phone') as ReservationChannel,
      platform_order_id: raw.platform_order_id as string | undefined,
      customer_name: (raw.customer_name ?? '') as string,
      customer_phone: (raw.phone ?? raw.customer_phone ?? '') as string,
      phone: raw.phone as string | undefined,
      party_size: (raw.party_size ?? 0) as number,
      date: (raw.date ?? '') as string,
      time: (raw.time ?? '') as string,
      table_type: (raw.room_name ?? raw.table_type) as string | undefined,
      room_name: raw.room_name as string | undefined,
      special_request: (raw.special_requests ?? raw.special_request) as string | undefined,
      special_requests: raw.special_requests as string | undefined,
      status: (raw.status ?? 'pending') as ReservationStatus,
      member_id: (raw.consumer_id ?? raw.member_id) as string | undefined,
      assigned_table: (raw.table_no ?? raw.assigned_table) as string | undefined,
      table_no: raw.table_no as string | undefined,
      created_at: (raw.created_at ?? '') as string,
    };

    // 仅当日期匹配当前选中日期时插入列表顶部
    if (newItem.date === selectedDate) {
      setReservations(prev => {
        // 防重复
        const exists = prev.some(r => r.id === newItem.id || r.reservation_id === newItem.reservation_id);
        if (exists) return prev;
        return [newItem, ...prev];
      });
    }

    // 提示音
    playNotificationSound();

    // Toast
    const toastId = ++toastCounterRef.current;
    const toast: ToastInfo = {
      id: toastId,
      source: msg.source,
      customerName: newItem.customer_name,
      partySize: newItem.party_size,
      time: newItem.time,
      tableType: newItem.table_type || newItem.room_name || '大厅',
    };
    setToasts(prev => [...prev, toast]);
  }, [selectedDate]);

  const dismissToast = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // ── WebSocket 实时推送 ────────────────────────────────────────────────────

  useReservationWS({
    storeId,
    onMessage: handleWsMessage,
    onStatusChange: setWsConnected,
    onFallback: () => setUseFallbackPolling(true),
    enabled: true,
  });

  // ── 渠道筛选 ──────────────────────────────────────────────────────────────

  const stats = computeStats(reservations);

  const filteredItems = reservations
    .filter(r => selectedChannel === 'all' || r.source_channel === selectedChannel)
    .sort((a, b) => a.time.localeCompare(b.time));

  const allChannels: ReservationChannel[] = ['meituan', 'dianping', 'wechat', 'phone', 'walkin'];
  const usedChannels = allChannels.filter(
    ch => (stats.by_channel[ch] ?? 0) > 0,
  );

  // ── 操作处理 ──────────────────────────────────────────────────────────────

  const handleArrival = async (id: string) => {
    setActionLoading(true);
    try {
      await confirmArrival(id);
      await loadData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '操作失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleAssignConfirm = async (tableNo: string) => {
    if (!assignTarget) return;
    setActionLoading(true);
    try {
      await assignTable(assignTarget.reservation_id || assignTarget.id, tableNo);
      setAssignTarget(null);
      await loadData();

      // 预订→开台直通车
      const reservationId = assignTarget.reservation_id || assignTarget.id;
      navigate(
        `/open-table?table=${encodeURIComponent(tableNo)}&guests=${assignTarget.party_size}&prefilled=true&reservation_id=${encodeURIComponent(reservationId)}&name=${encodeURIComponent(assignTarget.customer_name)}`,
      );
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '操作失败');
      setActionLoading(false);
    }
  };

  const handleCancelConfirm = async (reason: string) => {
    if (!cancelTargetId) return;
    setActionLoading(true);
    try {
      await cancelReservation(cancelTargetId, reason);
      setCancelTargetId(null);
      await loadData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '取消失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleNoShow = async (id: string) => {
    if (!window.confirm('确认标记该预订为爽约？')) return;
    setActionLoading(true);
    try {
      await markNoShow(id);
      await loadData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '操作失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleMockReservation = async () => {
    setMockLoading(true);
    try {
      await triggerMockReservation(storeId);
      await loadData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '生成失败');
    } finally {
      setMockLoading(false);
    }
  };

  // ── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.text, paddingBottom: 80 }}>

      {/* 新预订 Toast 通知（固定在顶部，叠加层） */}
      <NewReservationToastStack toasts={toasts} onDismiss={dismissToast} />

      {/* 顶栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', padding: '14px 16px 10px',
        background: C.card, borderBottom: `1px solid ${C.border}`,
        position: 'sticky', top: 0, zIndex: 20,
      }}>
        <div style={{
          flex: 1, fontSize: 22, fontWeight: 700, color: C.text,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          预订收件箱
          <WSStatusDot connected={wsConnected} />
        </div>
        <button
          onClick={handleMockReservation}
          disabled={mockLoading}
          style={{
            minHeight: 40, padding: '0 14px', borderRadius: 8,
            background: 'transparent', border: `1px solid ${C.border}`,
            color: C.muted, fontSize: 14, cursor: 'pointer',
          }}
        >
          {mockLoading ? '生成中...' : '+ Mock预订'}
        </button>
      </div>

      {/* 汇总条 */}
      <div style={{
        display: 'flex', gap: 0,
        background: C.card, borderBottom: `1px solid ${C.border}`,
        padding: '10px 16px',
        overflowX: 'auto',
      }}>
        {[
          { label: '今日预订', value: `${stats.total}桌`, color: C.text },
          { label: '已到店', value: `${stats.arrived}`, color: C.accent },
          { label: '待到', value: `${stats.pending_arrive}`, color: C.green },
          { label: '爽约', value: `${stats.no_show}`, color: C.danger },
        ].map((s, i) => (
          <div key={i} style={{
            flex: 1, textAlign: 'center', minWidth: 72,
            borderRight: i < 3 ? `1px solid ${C.border}` : 'none',
            padding: '0 8px',
          }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: s.color }}>{s.value}</div>
            <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* 日期选择器 */}
      <div style={{
        display: 'flex', gap: 8, padding: '12px 16px',
        overflowX: 'auto', background: C.bg,
        borderBottom: `1px solid ${C.border}`,
      }}>
        {dateRange.map(d => {
          const isToday = d === todayStr;
          const isSelected = d === selectedDate;
          return (
            <button
              key={d}
              onClick={() => setSelectedDate(d)}
              style={{
                flexShrink: 0,
                minHeight: 40, padding: '0 16px', borderRadius: 20,
                background: isSelected ? C.accent : (isToday ? 'rgba(255,107,53,0.12)' : 'transparent'),
                border: `1px solid ${isSelected ? C.accent : (isToday ? C.accent : C.border)}`,
                color: isSelected ? '#fff' : (isToday ? C.accent : C.subtext),
                fontSize: 15, fontWeight: isSelected ? 700 : 400,
                cursor: 'pointer',
              }}
            >
              {dateLabel(d, todayStr)}
            </button>
          );
        })}
      </div>

      {/* 渠道筛选 Tab */}
      <div style={{
        display: 'flex', gap: 8, padding: '10px 16px',
        overflowX: 'auto',
        borderBottom: `1px solid ${C.border}`,
      }}>
        {/* 全部 */}
        <button
          onClick={() => setSelectedChannel('all')}
          style={{
            flexShrink: 0, minHeight: 36, padding: '0 14px', borderRadius: 18,
            background: selectedChannel === 'all' ? C.accent : 'transparent',
            border: `1px solid ${selectedChannel === 'all' ? C.accent : C.border}`,
            color: selectedChannel === 'all' ? '#fff' : C.subtext,
            fontSize: 15, fontWeight: selectedChannel === 'all' ? 700 : 400,
            cursor: 'pointer',
          }}
        >
          全部 {reservations.length}
        </button>

        {usedChannels.map(ch => {
          const isActive = selectedChannel === ch;
          const count = stats.by_channel[ch] ?? 0;
          return (
            <button
              key={ch}
              onClick={() => setSelectedChannel(ch)}
              style={{
                flexShrink: 0, minHeight: 36, padding: '0 14px', borderRadius: 18,
                background: isActive ? CHANNEL_COLOR[ch] : 'transparent',
                border: `1px solid ${isActive ? CHANNEL_COLOR[ch] : C.border}`,
                color: isActive ? '#fff' : CHANNEL_COLOR[ch],
                fontSize: 15, fontWeight: isActive ? 700 : 400,
                cursor: 'pointer',
              }}
            >
              {CHANNEL_LABEL[ch]} {count}
            </button>
          );
        })}
      </div>

      {/* 内容区 */}
      <div style={{ padding: '12px 16px' }}>

        {/* 错误提示 */}
        {error && (
          <div style={{
            background: 'rgba(239,68,68,0.10)', border: `1px solid ${C.danger}`,
            borderRadius: 10, padding: '12px 16px', color: C.danger,
            marginBottom: 12, fontSize: 15,
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span style={{ flex: 1 }}>{error}</span>
            <button
              onClick={loadData}
              style={{
                color: C.danger, background: 'none',
                border: `1px solid ${C.danger}`, borderRadius: 6,
                padding: '2px 10px', cursor: 'pointer', fontSize: 14,
              }}
            >
              重试
            </button>
          </div>
        )}

        {/* 加载中 */}
        {loading && filteredItems.length === 0 && (
          <div style={{ textAlign: 'center', color: C.muted, padding: 48, fontSize: 16 }}>
            加载中...
          </div>
        )}

        {/* 空状态 */}
        {!loading && filteredItems.length === 0 && !error && (
          <div style={{ textAlign: 'center', color: C.muted, padding: 60, fontSize: 16 }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📅</div>
            <div>该日期暂无预订</div>
            <div style={{ fontSize: 14, marginTop: 8 }}>点击右上角 "+ Mock预订" 生成测试数据</div>
          </div>
        )}

        {/* 预订卡片列表 */}
        {filteredItems.map(r => (
          <ReservationCard
            key={r.reservation_id || r.id}
            r={r}
            onArrival={handleArrival}
            onAssign={setAssignTarget}
            onCancel={setCancelTargetId}
            onNoShow={handleNoShow}
            actionLoading={actionLoading}
          />
        ))}
      </div>

      {/* 刷新指示 */}
      {loading && filteredItems.length > 0 && (
        <div style={{
          position: 'fixed', top: 8, right: 12,
          fontSize: 12, color: C.muted, zIndex: 99,
        }}>
          刷新中...
        </div>
      )}

      {/* 降级轮询提示（WS 失败时显示） */}
      {useFallbackPolling && (
        <div style={{
          position: 'fixed', bottom: 90, left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(100,116,139,0.9)', borderRadius: 20,
          padding: '6px 16px', fontSize: 13, color: '#fff',
          zIndex: 99, whiteSpace: 'nowrap',
        }}>
          实时推送不可用，已切换为轮询模式
        </div>
      )}

      {/* 安排入座对话框 */}
      {assignTarget && (
        <AssignDialog
          reservation={assignTarget}
          onClose={() => setAssignTarget(null)}
          onConfirm={handleAssignConfirm}
          loading={actionLoading}
        />
      )}

      {/* 取消预订对话框 */}
      {cancelTargetId && (
        <CancelDialog
          reservationId={cancelTargetId}
          onClose={() => setCancelTargetId(null)}
          onConfirm={handleCancelConfirm}
          loading={actionLoading}
        />
      )}
    </div>
  );
}
