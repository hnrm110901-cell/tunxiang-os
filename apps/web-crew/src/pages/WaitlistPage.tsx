/**
 * 等位管理页 — 等位叫号调度引擎
 *
 * 功能：登记等位 / 实时叫号 / VIP优先 / 过号降级 / 入座确认
 * 轮询：每15秒自动刷新队列
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { txFetch } from '../api/index';

// ─── 颜色系统 ──────────────────────────────────────────────────────────────

const C = {
  bg:      '#0B1A20',
  card:    '#112228',
  border:  '#1a2a33',
  accent:  '#FF6B35',
  gold:    '#facc15',
  silver:  '#94a3b8',
  green:   '#22c55e',
  orange:  '#f97316',
  danger:  '#ef4444',
  warning: '#eab308',
  muted:   '#64748b',
  text:    '#f1f5f9',
  subtext: '#94a3b8',
};

// ─── 类型 ──────────────────────────────────────────────────────────────────

interface WaitlistEntry {
  id:                 string;
  queue_no:           number;
  name:               string;
  phone:              string | null;
  party_size:         number;
  table_type:         string | null;
  priority:           number;
  status:             'waiting' | 'called' | 'seated' | 'cancelled' | 'expired';
  call_count:         number;
  estimated_wait_min: number | null;
  called_at:          string | null;
  seated_at:          string | null;
  expired_at:         string | null;
  created_at:         string;
}

interface WaitlistStats {
  waiting_count:    number;
  called_count:     number;
  avg_wait_min:     number;
  current_queue_no: number;
}

interface ListData {
  items: WaitlistEntry[];
  total: number;
}

// ─── 辅助函数 ──────────────────────────────────────────────────────────────

function priorityLabel(priority: number): { label: string; color: string } | null {
  if (priority >= 40) return { label: '黑金会员', color: C.text };
  if (priority >= 30) return { label: '金卡会员', color: C.gold };
  if (priority >= 20) return { label: '银卡会员', color: C.silver };
  if (priority >= 10) return { label: '普通会员', color: C.silver };
  if (priority === -10) return { label: '过号降级', color: C.danger };
  return null;
}

function statusBadgeColor(status: WaitlistEntry['status']): string {
  switch (status) {
    case 'waiting':   return C.orange;
    case 'called':    return C.accent;
    case 'seated':    return C.green;
    case 'cancelled': return C.muted;
    case 'expired':   return C.danger;
    default:          return C.muted;
  }
}

function callBtnColor(call_count: number): string {
  if (call_count === 0) return C.accent;
  if (call_count <= 2)  return C.warning;
  return C.danger;
}

function minutesAgo(isoStr: string): number {
  const dt = new Date(isoStr);
  return Math.floor((Date.now() - dt.getTime()) / 60000);
}

// ─── 子组件：统计头部 ──────────────────────────────────────────────────────

function StatsBar({ stats }: { stats: WaitlistStats | null }) {
  return (
    <div style={{
      display: 'flex', gap: 16, padding: '12px 16px',
      background: C.card, borderBottom: `1px solid ${C.border}`,
    }}>
      <Stat label="等待" value={stats ? `${stats.waiting_count}桌` : '—'} color={C.orange} />
      <Stat label="已叫号" value={stats ? `${stats.called_count}桌` : '—'} color={C.accent} />
      <Stat label="预计等待" value={stats ? `约${stats.avg_wait_min}分钟` : '—'} color={C.subtext} />
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ flex: 1, textAlign: 'center' }}>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>{label}</div>
    </div>
  );
}

// ─── 子组件：等位卡片 ──────────────────────────────────────────────────────

interface EntryCardProps {
  entry:    WaitlistEntry;
  onCall:   (id: string, channel?: string) => void;
  onSeat:   (id: string) => void;
  onCancel: (id: string) => void;
  loading:  boolean;
}

function EntryCard({ entry, onCall, onSeat, onCancel, loading }: EntryCardProps) {
  const vip = priorityLabel(entry.priority);
  const badgeColor = statusBadgeColor(entry.status);
  const isActive = entry.status === 'waiting' || entry.status === 'called';

  return (
    <div style={{
      background: C.card, borderRadius: 12, padding: 16, marginBottom: 10,
      border: `1px solid ${C.border}`,
      opacity: isActive ? 1 : 0.6,
    }}>
      {/* 顶行 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* 队列号 Badge */}
        <div style={{
          width: 48, height: 48, borderRadius: 24,
          background: badgeColor,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 18, color: '#fff',
          flexShrink: 0,
        }}>
          {entry.queue_no}
        </div>

        {/* 基本信息 */}
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 18, fontWeight: 600, color: C.text }}>
              {entry.name}
            </span>
            {entry.priority >= 30 && (
              <span style={{ fontSize: 18, color: C.gold }}>★</span>
            )}
          </div>
          <div style={{ fontSize: 15, color: C.subtext, marginTop: 2 }}>
            {entry.party_size}人
            {entry.table_type ? ` · ${entry.table_type}` : ''}
            {entry.estimated_wait_min != null
              ? ` · 预计${entry.estimated_wait_min}分钟`
              : ''}
          </div>
        </div>

        {/* 等待时间 */}
        <div style={{ textAlign: 'right', fontSize: 14, color: C.muted }}>
          <div>{minutesAgo(entry.created_at)}分钟前</div>
          <div style={{ fontSize: 13, color: C.subtext }}>登记</div>
        </div>
      </div>

      {/* VIP标签 + 叫号信息 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        {vip && (
          <span style={{
            fontSize: 13, padding: '2px 8px', borderRadius: 10,
            background: 'rgba(250,204,21,0.12)', color: vip.color,
            border: `1px solid ${vip.color}30`,
          }}>
            {vip.label}
          </span>
        )}
        {entry.call_count > 0 && entry.called_at && (
          <span style={{
            fontSize: 13, padding: '2px 8px', borderRadius: 10,
            background: 'rgba(239,68,68,0.12)', color: C.danger,
            border: `1px solid ${C.danger}30`,
          }}>
            已叫号 {entry.call_count} 次，{minutesAgo(entry.called_at)} 分钟前
          </span>
        )}
        {entry.status === 'expired' && (
          <span style={{
            fontSize: 13, padding: '2px 8px', borderRadius: 10,
            background: 'rgba(239,68,68,0.12)', color: C.danger,
          }}>
            已过号降级
          </span>
        )}
      </div>

      {/* 操作按钮 */}
      {isActive && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          {/* 叫号 */}
          <button
            disabled={loading}
            onClick={() => onCall(entry.id, entry.phone ? 'sms' : 'screen')}
            style={{
              flex: 1, minHeight: 44, borderRadius: 8,
              background: callBtnColor(entry.call_count),
              color: '#fff', border: 'none', fontSize: 16,
              fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
            }}
          >
            {entry.call_count === 0 ? '叫号' : `再叫 (${entry.call_count})`}
          </button>

          {/* 入座 */}
          <button
            disabled={loading}
            onClick={() => onSeat(entry.id)}
            style={{
              flex: 1, minHeight: 44, borderRadius: 8,
              background: C.green,
              color: '#fff', border: 'none', fontSize: 16,
              fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
            }}
          >
            入座
          </button>

          {/* 取消 */}
          <button
            disabled={loading}
            onClick={() => onCancel(entry.id)}
            style={{
              minWidth: 64, minHeight: 44, borderRadius: 8,
              background: 'transparent', border: `1px solid ${C.danger}`,
              color: C.danger, fontSize: 16, fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
            }}
          >
            取消
          </button>
        </div>
      )}
    </div>
  );
}

// ─── 子组件：登记等位 Sheet ────────────────────────────────────────────────

const TABLE_TYPES = ['普通桌', '4人桌', '6人桌', '包厢'];
const PARTY_SIZES = [1, 2, 3, 4, 5, 6];

interface RegisterSheetProps {
  onClose:    () => void;
  onSubmit:   (form: RegisterForm) => void;
  loading:    boolean;
}

interface RegisterForm {
  name:       string;
  phone:      string;
  party_size: number;
  table_type: string;
}

function RegisterSheet({ onClose, onSubmit, loading }: RegisterSheetProps) {
  const [form, setForm] = useState<RegisterForm>({
    name:       '',
    phone:      '',
    party_size: 2,
    table_type: '普通桌',
  });

  const handleSubmit = () => {
    if (!form.name.trim()) {
      alert('请输入顾客姓名');
      return;
    }
    onSubmit(form);
  };

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          zIndex: 100,
        }}
      />
      {/* Sheet */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: C.card, borderRadius: '16px 16px 0 0',
        padding: '20px 16px 32px',
        zIndex: 101,
        maxHeight: '85vh', overflowY: 'auto',
      }}>
        {/* 标题栏 */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ flex: 1, fontSize: 20, fontWeight: 700, color: C.text }}>
            登记等位
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: C.muted,
              fontSize: 24, cursor: 'pointer', padding: '4px 8px',
            }}
          >
            ✕
          </button>
        </div>

        {/* 姓名 */}
        <Label text="顾客姓名" required />
        <input
          type="text"
          value={form.name}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          placeholder="如：王先生 / 张小姐"
          style={inputStyle}
        />

        {/* 手机号 */}
        <Label text="手机号（选填，用于短信通知）" />
        <input
          type="tel"
          value={form.phone}
          onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
          placeholder="13x xxxx xxxx"
          style={inputStyle}
        />

        {/* 人数 */}
        <Label text="就餐人数" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 16 }}>
          {PARTY_SIZES.map(n => (
            <button
              key={n}
              onClick={() => setForm(f => ({ ...f, party_size: n }))}
              style={{
                minHeight: 48, borderRadius: 8, fontSize: 17, fontWeight: 600,
                background: form.party_size === n ? C.accent : C.bg,
                color: form.party_size === n ? '#fff' : C.subtext,
                border: `1px solid ${form.party_size === n ? C.accent : C.border}`,
                cursor: 'pointer',
              }}
            >
              {n === 6 ? '6+' : `${n}人`}
            </button>
          ))}
        </div>

        {/* 桌型偏好 */}
        <Label text="桌型偏好" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 24 }}>
          {TABLE_TYPES.map(t => (
            <button
              key={t}
              onClick={() => setForm(f => ({ ...f, table_type: t }))}
              style={{
                minHeight: 48, borderRadius: 8, fontSize: 16, fontWeight: 600,
                background: form.table_type === t ? C.accent : C.bg,
                color: form.table_type === t ? '#fff' : C.subtext,
                border: `1px solid ${form.table_type === t ? C.accent : C.border}`,
                cursor: 'pointer',
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* 确认按钮 */}
        <button
          onClick={handleSubmit}
          disabled={loading}
          style={{
            width: '100%', minHeight: 52, borderRadius: 12,
            background: loading ? C.muted : C.accent,
            color: '#fff', border: 'none',
            fontSize: 18, fontWeight: 700,
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? '登记中...' : '确认登记'}
        </button>
      </div>
    </>
  );
}

const inputStyle: React.CSSProperties = {
  width: '100%', minHeight: 48, borderRadius: 10, padding: '0 14px',
  background: '#0d1e26', border: `1px solid #1e3040`,
  color: '#f1f5f9', fontSize: 16, marginBottom: 14,
  boxSizing: 'border-box',
};

function Label({ text, required }: { text: string; required?: boolean }) {
  return (
    <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>
      {text}
      {required && <span style={{ color: C.danger, marginLeft: 4 }}>*</span>}
    </div>
  );
}

// ─── 子组件：入座确认对话框 ────────────────────────────────────────────────

interface SeatDialogProps {
  entryId:  string;
  onClose:  () => void;
  onSeat:   (entryId: string, tableNo: string) => void;
  loading:  boolean;
}

function SeatDialog({ entryId, onClose, onSeat, loading }: SeatDialogProps) {
  const [tableNo, setTableNo] = useState('');

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 200 }}
      />
      <div style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        background: C.card, borderRadius: 16, padding: 24,
        zIndex: 201, width: '80%', maxWidth: 360,
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text, marginBottom: 16 }}>
          请输入桌台号
        </div>
        <input
          type="text"
          value={tableNo}
          onChange={e => setTableNo(e.target.value)}
          placeholder="如：A01、B12"
          autoFocus
          style={{ ...inputStyle, marginBottom: 20 }}
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
            onClick={() => tableNo.trim() && onSeat(entryId, tableNo.trim())}
            disabled={loading || !tableNo.trim()}
            style={{
              flex: 1, minHeight: 48, borderRadius: 10,
              background: loading ? C.muted : C.green,
              color: '#fff', border: 'none',
              fontSize: 16, fontWeight: 700,
              cursor: loading || !tableNo.trim() ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? '处理中...' : '确认入座'}
          </button>
        </div>
      </div>
    </>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────

export function WaitlistPage() {
  const [searchParams] = useSearchParams();
  const storeId = searchParams.get('store_id') || (window as any).__STORE_ID__ || '';

  const [entries, setEntries]       = useState<WaitlistEntry[]>([]);
  const [stats, setStats]           = useState<WaitlistStats | null>(null);
  const [loading, setLoading]       = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const [seatTarget, setSeatTarget] = useState<string | null>(null);
  const [error, setError]           = useState<string | null>(null);

  // ── 数据获取 ──────────────────────────────────────────────────────────

  const fetchData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const [listData, statsData] = await Promise.all([
        txFetch<ListData>(`/api/v1/waitlist?store_id=${encodeURIComponent(storeId)}&status=waiting`),
        txFetch<WaitlistStats>(`/api/v1/waitlist/stats?store_id=${encodeURIComponent(storeId)}`),
      ]);
      setEntries(listData.items);
      setStats(statsData);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  // 初始加载 + 15秒轮询
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchData();
    timerRef.current = setInterval(fetchData, 15000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchData]);

  // ── 操作处理 ──────────────────────────────────────────────────────────

  const handleCall = async (entryId: string, channel = 'screen') => {
    setActionLoading(true);
    try {
      await txFetch(`/api/v1/waitlist/${encodeURIComponent(entryId)}/call`, {
        method: 'POST',
        body: JSON.stringify({ operator_id: 'crew', channel }),
      });
      await fetchData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '叫号失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleSeat = async (entryId: string, tableNo: string) => {
    setActionLoading(true);
    try {
      await txFetch(`/api/v1/waitlist/${encodeURIComponent(entryId)}/seat`, {
        method: 'POST',
        body: JSON.stringify({ table_no: tableNo, operator_id: 'crew' }),
      });
      setSeatTarget(null);
      await fetchData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '入座处理失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancel = async (entryId: string) => {
    if (!window.confirm('确认取消该等位？')) return;
    setActionLoading(true);
    try {
      await txFetch(`/api/v1/waitlist/${encodeURIComponent(entryId)}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason: '前台取消' }),
      });
      await fetchData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '取消失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRegister = async (form: RegisterForm) => {
    setActionLoading(true);
    try {
      await txFetch('/api/v1/waitlist', {
        method: 'POST',
        body: JSON.stringify({
          store_id:   storeId,
          name:       form.name,
          phone:      form.phone || null,
          party_size: form.party_size,
          table_type: form.table_type,
        }),
      });
      setShowRegister(false);
      await fetchData();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '登记失败');
    } finally {
      setActionLoading(false);
    }
  };

  // ── 渲染 ──────────────────────────────────────────────────────────────

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.text, paddingBottom: 80 }}>
      {/* 顶栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', padding: '14px 16px 10px',
        background: C.card, borderBottom: `1px solid ${C.border}`,
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ flex: 1, fontSize: 22, fontWeight: 700, color: C.text }}>
          等位管理
        </div>
        <button
          onClick={() => setShowRegister(true)}
          style={{
            minHeight: 48, paddingLeft: 20, paddingRight: 20,
            borderRadius: 10, background: C.accent,
            color: '#fff', border: 'none',
            fontSize: 16, fontWeight: 700, cursor: 'pointer',
          }}
        >
          + 登记等位
        </button>
      </div>

      {/* 统计摘要 */}
      <StatsBar stats={stats} />

      {/* 内容区 */}
      <div style={{ padding: '12px 16px' }}>
        {/* 加载/错误状态 */}
        {error && (
          <div style={{
            background: 'rgba(239,68,68,0.1)', border: `1px solid ${C.danger}`,
            borderRadius: 10, padding: '12px 16px', color: C.danger,
            marginBottom: 12, fontSize: 15,
          }}>
            {error}
            <button
              onClick={fetchData}
              style={{
                marginLeft: 12, color: C.danger, background: 'none',
                border: `1px solid ${C.danger}`, borderRadius: 6,
                padding: '2px 10px', cursor: 'pointer', fontSize: 14,
              }}
            >
              重试
            </button>
          </div>
        )}

        {loading && entries.length === 0 && (
          <div style={{ textAlign: 'center', color: C.muted, padding: 40, fontSize: 16 }}>
            加载中...
          </div>
        )}

        {!loading && entries.length === 0 && !error && (
          <div style={{
            textAlign: 'center', color: C.muted, padding: 60,
            fontSize: 16,
          }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🎉</div>
            <div>暂无等位顾客</div>
            <div style={{ fontSize: 14, marginTop: 8 }}>点击右上角按钮登记新等位</div>
          </div>
        )}

        {/* 等位列表 */}
        {entries.map(entry => (
          <EntryCard
            key={entry.id}
            entry={entry}
            onCall={handleCall}
            onSeat={(id) => setSeatTarget(id)}
            onCancel={handleCancel}
            loading={actionLoading}
          />
        ))}
      </div>

      {/* 轮询指示 */}
      {loading && entries.length > 0 && (
        <div style={{
          position: 'fixed', top: 8, right: 12,
          fontSize: 12, color: C.muted, zIndex: 99,
        }}>
          刷新中...
        </div>
      )}

      {/* 登记等位 Sheet */}
      {showRegister && (
        <RegisterSheet
          onClose={() => setShowRegister(false)}
          onSubmit={handleRegister}
          loading={actionLoading}
        />
      )}

      {/* 入座确认对话框 */}
      {seatTarget && (
        <SeatDialog
          entryId={seatTarget}
          onClose={() => setSeatTarget(null)}
          onSeat={handleSeat}
          loading={actionLoading}
        />
      )}
    </div>
  );
}
