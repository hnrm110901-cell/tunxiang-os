/**
 * 预订台账 — 今日预订时间线，按时段展示
 * 每个预订: 客户名/人数/包厢/特殊要求
 * 状态: 待到店/已到店/已入座/已取消
 */
import { useState, useEffect, useCallback } from 'react';
import {
  fetchReservations,
  createReservation,
  updateReservationStatus,
  type Reservation,
  type ReservationStatus,
  type CreateReservationPayload,
} from '../api/reservationApi';

const STORE_ID = import.meta.env.VITE_STORE_ID || 'default-store';

const STATUS_MAP: Record<ReservationStatus, { label: string; color: string; bg: string }> = {
  pending:   { label: '待到店', color: 'var(--tx-info)',    bg: '#EBF3FF' },
  arrived:   { label: '已到店', color: 'var(--tx-primary)', bg: 'var(--tx-primary-light)' },
  seated:    { label: '已入座', color: 'var(--tx-success)', bg: '#E8F5F0' },
  cancelled: { label: '已取消', color: 'var(--tx-text-3)',  bg: '#F0F0F0' },
  no_show:   { label: '未到店', color: 'var(--tx-danger)',  bg: '#FFF5F5' },
};

const TIME_SLOTS = ['11:00', '11:30', '12:00', '12:30', '13:00', '17:00', '17:30', '18:00', '18:30', '19:00', '19:30', '20:00'];

export function ReservationBoard() {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<ReservationStatus | 'all'>('all');
  const [periodFilter, setPeriodFilter] = useState<'lunch' | 'dinner' | 'all'>('all');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const loadReservations = useCallback(async () => {
    try {
      setError(null);
      const result = await fetchReservations(STORE_ID);
      setReservations(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载预订数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadReservations();
  }, [loadReservations]);

  const handleStatusChange = async (reservationId: string, newStatus: ReservationStatus) => {
    try {
      setActionLoading(reservationId);
      await updateReservationStatus(reservationId, newStatus);
      await loadReservations();
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新状态失败');
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreate = async (payload: CreateReservationPayload) => {
    try {
      setActionLoading('create');
      await createReservation(payload);
      setShowCreateForm(false);
      await loadReservations();
    } catch (err) {
      setError(err instanceof Error ? err.message : '新增预订失败');
    } finally {
      setActionLoading(null);
    }
  };

  const filtered = reservations.filter(r => {
    if (statusFilter !== 'all' && r.status !== statusFilter) return false;
    if (periodFilter === 'lunch') {
      const hour = parseInt(r.time_slot.split(':')[0]);
      if (hour >= 17) return false;
    }
    if (periodFilter === 'dinner') {
      const hour = parseInt(r.time_slot.split(':')[0]);
      if (hour < 17) return false;
    }
    return true;
  });

  // 按时间段分组
  const grouped = TIME_SLOTS.reduce<Record<string, Reservation[]>>((acc, slot) => {
    const items = filtered.filter(r => r.time_slot === slot);
    if (items.length > 0) acc[slot] = items;
    return acc;
  }, {});

  const counts = {
    total: reservations.length,
    pending: reservations.filter(r => r.status === 'pending').length,
    arrived: reservations.filter(r => r.status === 'arrived').length,
    seated: reservations.filter(r => r.status === 'seated').length,
    totalGuests: reservations.filter(r => r.status !== 'cancelled').reduce((s, r) => s + r.guest_count, 0),
  };

  if (loading) {
    return (
      <div style={{ padding: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div style={{ fontSize: 22, color: 'var(--tx-text-3)' }}>加载预订数据中...</div>
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      {/* 错误提示 */}
      {error && (
        <div style={{
          background: '#FFF5F5', border: '1px solid var(--tx-danger)', borderRadius: 'var(--tx-radius-sm)',
          padding: '12px 20px', marginBottom: 16, color: 'var(--tx-danger)', fontSize: 18,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>{error}</span>
          <button onClick={() => setError(null)} style={{
            border: 'none', background: 'transparent', color: 'var(--tx-danger)',
            fontSize: 18, cursor: 'pointer', fontWeight: 700,
          }}>关闭</button>
        </div>
      )}

      {/* 顶部标题 + 统计 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <h1 style={{ fontSize: 32, fontWeight: 800 }}>今日预订台账</h1>
          <button
            onClick={() => setShowCreateForm(true)}
            style={{
              minWidth: 100, minHeight: 48, borderRadius: 'var(--tx-radius-sm)',
              border: 'none', background: 'var(--tx-primary)', color: '#fff',
              fontSize: 18, fontWeight: 700, cursor: 'pointer',
            }}
          >
            新增预订
          </button>
        </div>
        <div style={{ display: 'flex', gap: 20 }}>
          <StatBadge label="总预订" value={counts.total} color="var(--tx-text-1)" />
          <StatBadge label="待到店" value={counts.pending} color="var(--tx-info)" />
          <StatBadge label="已到店" value={counts.arrived} color="var(--tx-primary)" />
          <StatBadge label="已入座" value={counts.seated} color="var(--tx-success)" />
          <StatBadge label="总人数" value={counts.totalGuests} color="var(--tx-text-2)" />
        </div>
      </div>

      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        {/* 餐段筛选 */}
        {(['all', 'lunch', 'dinner'] as const).map(p => (
          <button
            key={p}
            onClick={() => setPeriodFilter(p)}
            style={{
              minWidth: 80,
              minHeight: 48,
              borderRadius: 'var(--tx-radius-sm)',
              border: '2px solid',
              borderColor: periodFilter === p ? 'var(--tx-primary)' : 'var(--tx-border)',
              background: periodFilter === p ? 'var(--tx-primary-light)' : '#fff',
              color: periodFilter === p ? 'var(--tx-primary)' : 'var(--tx-text-2)',
              fontSize: 18,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 200ms',
              padding: '0 16px',
            }}
          >
            {{ all: '全部', lunch: '午餐', dinner: '晚餐' }[p]}
          </button>
        ))}

        <div style={{ width: 1, background: 'var(--tx-border)', margin: '0 8px' }} />

        {/* 状态筛选 */}
        {(['all', 'pending', 'arrived', 'seated', 'cancelled'] as const).map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            style={{
              minWidth: 72,
              minHeight: 48,
              borderRadius: 'var(--tx-radius-sm)',
              border: '2px solid',
              borderColor: statusFilter === s ? 'var(--tx-primary)' : 'var(--tx-border)',
              background: statusFilter === s ? 'var(--tx-primary-light)' : '#fff',
              color: statusFilter === s ? 'var(--tx-primary)' : 'var(--tx-text-2)',
              fontSize: 18,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 200ms',
              padding: '0 16px',
            }}
          >
            {s === 'all' ? '全部状态' : STATUS_MAP[s].label}
          </button>
        ))}
      </div>

      {/* 时间线 */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 24,
        overflowY: 'auto',
        maxHeight: 'calc(100vh - 200px)',
        WebkitOverflowScrolling: 'touch',
        paddingBottom: 40,
      }}>
        {Object.entries(grouped).map(([slot, items]) => (
          <div key={slot}>
            {/* 时段标头 */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginBottom: 12,
            }}>
              <div style={{
                fontSize: 24,
                fontWeight: 800,
                color: 'var(--tx-primary)',
                minWidth: 70,
              }}>
                {slot}
              </div>
              <div style={{
                height: 2,
                flex: 1,
                background: 'var(--tx-border)',
              }} />
              <span style={{ fontSize: 18, color: 'var(--tx-text-3)' }}>
                {items.length}桌 / {items.reduce((s, r) => s + r.guest_count, 0)}人
              </span>
            </div>

            {/* 预订卡片 */}
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {items.map(r => (
                <ReservationCard
                  key={r.reservation_id}
                  reservation={r}
                  onStatusChange={handleStatusChange}
                  actionLoading={actionLoading}
                />
              ))}
            </div>
          </div>
        ))}

        {Object.keys(grouped).length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: 80,
            fontSize: 20,
            color: 'var(--tx-text-3)',
          }}>
            暂无匹配的预订记录
          </div>
        )}
      </div>

      {/* 新增预订弹窗 */}
      {showCreateForm && (
        <CreateReservationModal
          onClose={() => setShowCreateForm(false)}
          onSubmit={handleCreate}
          isLoading={actionLoading === 'create'}
        />
      )}
    </div>
  );
}

function ReservationCard({
  reservation: r,
  onStatusChange,
  actionLoading,
}: {
  reservation: Reservation;
  onStatusChange: (id: string, status: ReservationStatus) => void;
  actionLoading: string | null;
}) {
  const st = STATUS_MAP[r.status] || STATUS_MAP.pending;
  const isLoading = actionLoading === r.reservation_id;

  return (
    <div style={{
      background: '#fff',
      borderRadius: 'var(--tx-radius-md)',
      boxShadow: 'var(--tx-shadow-sm)',
      padding: 20,
      minWidth: 280,
      maxWidth: 360,
      flex: '1 1 280px',
      borderLeft: `4px solid ${st.color}`,
      opacity: r.status === 'cancelled' ? 0.5 : 1,
      position: 'relative',
    }}>
      {/* VIP标识 */}
      {r.is_vip && (
        <div style={{
          position: 'absolute',
          top: 12,
          right: 12,
          background: '#FFD700',
          color: '#6B4E00',
          fontSize: 16,
          fontWeight: 800,
          padding: '2px 10px',
          borderRadius: 6,
        }}>
          VIP
        </div>
      )}

      {/* 客户名 + 人数 */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 24, fontWeight: 700 }}>{r.customer_name}</span>
        <span style={{ fontSize: 20, color: 'var(--tx-text-2)' }}>{r.guest_count}人</span>
      </div>

      {/* 包厢/桌号 */}
      <div style={{ fontSize: 20, fontWeight: 600, color: 'var(--tx-primary)', marginBottom: 8 }}>
        {r.room_or_table}
      </div>

      {/* 手机号 + 预订号 */}
      <div style={{ fontSize: 16, color: 'var(--tx-text-3)', marginBottom: 8 }}>
        {r.phone} | {r.reservation_code}
      </div>

      {/* 特殊要求 */}
      {r.special_requests && (
        <div style={{
          fontSize: 18,
          color: 'var(--tx-danger)',
          background: '#FFF5F5',
          padding: '6px 10px',
          borderRadius: 6,
          marginBottom: 12,
        }}>
          {r.special_requests}
        </div>
      )}

      {/* 状态标签 + 操作按钮 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{
          display: 'inline-block',
          fontSize: 18,
          fontWeight: 700,
          color: st.color,
          background: st.bg,
          padding: '4px 16px',
          borderRadius: 6,
        }}>
          {st.label}
        </div>

        {/* 状态操作按钮 */}
        {r.status === 'pending' && (
          <>
            <button
              disabled={isLoading}
              onClick={() => onStatusChange(r.reservation_id, 'arrived')}
              style={{
                fontSize: 16, fontWeight: 700, padding: '4px 12px', borderRadius: 6,
                border: 'none', background: 'var(--tx-primary)', color: '#fff',
                cursor: isLoading ? 'not-allowed' : 'pointer', opacity: isLoading ? 0.6 : 1,
              }}
            >
              {isLoading ? '...' : '确认到店'}
            </button>
            <button
              disabled={isLoading}
              onClick={() => onStatusChange(r.reservation_id, 'cancelled')}
              style={{
                fontSize: 16, fontWeight: 700, padding: '4px 12px', borderRadius: 6,
                border: '1px solid var(--tx-border)', background: '#fff', color: 'var(--tx-text-2)',
                cursor: isLoading ? 'not-allowed' : 'pointer', opacity: isLoading ? 0.6 : 1,
              }}
            >
              {isLoading ? '...' : '取消'}
            </button>
          </>
        )}
        {r.status === 'arrived' && (
          <button
            disabled={isLoading}
            onClick={() => onStatusChange(r.reservation_id, 'seated')}
            style={{
              fontSize: 16, fontWeight: 700, padding: '4px 12px', borderRadius: 6,
              border: 'none', background: 'var(--tx-success)', color: '#fff',
              cursor: isLoading ? 'not-allowed' : 'pointer', opacity: isLoading ? 0.6 : 1,
            }}
          >
            {isLoading ? '...' : '确认入座'}
          </button>
        )}
      </div>
    </div>
  );
}

function CreateReservationModal({
  onClose,
  onSubmit,
  isLoading,
}: {
  onClose: () => void;
  onSubmit: (payload: CreateReservationPayload) => void;
  isLoading: boolean;
}) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [guestCount, setGuestCount] = useState(2);
  const [timeSlot, setTimeSlot] = useState('12:00');
  const [roomOrTable, setRoomOrTable] = useState('');
  const [specialRequests, setSpecialRequests] = useState('');

  const handleSubmit = () => {
    if (!name.trim() || !phone.trim()) return;
    onSubmit({
      store_id: STORE_ID,
      customer_name: name.trim(),
      phone: phone.trim(),
      guest_count: guestCount,
      time_slot: timeSlot,
      room_or_table: roomOrTable.trim(),
      special_requests: specialRequests.trim() || undefined,
    });
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
    }}>
      <div style={{
        background: '#fff', borderRadius: 'var(--tx-radius-lg)',
        padding: 32, width: 480, boxShadow: 'var(--tx-shadow-md)',
      }}>
        <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 24 }}>新增预订</h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FormField label="客户称呼" value={name} onChange={setName} placeholder="客户姓名" />
          <FormField label="手机号" value={phone} onChange={setPhone} placeholder="手机号码" />
          <div>
            <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>人数</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button onClick={() => setGuestCount(Math.max(1, guestCount - 1))} style={stepBtnStyle}>-</button>
              <span style={{ fontSize: 24, fontWeight: 800, minWidth: 32, textAlign: 'center' }}>{guestCount}</span>
              <button onClick={() => setGuestCount(guestCount + 1)} style={stepBtnStyle}>+</button>
            </div>
          </div>
          <div>
            <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>时段</div>
            <select
              value={timeSlot}
              onChange={e => setTimeSlot(e.target.value)}
              style={{
                width: '100%', height: 48, borderRadius: 'var(--tx-radius-md)',
                border: '2px solid var(--tx-border)', padding: '0 12px', fontSize: 18, outline: 'none',
              }}
            >
              {TIME_SLOTS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <FormField label="桌台/包厢" value={roomOrTable} onChange={setRoomOrTable} placeholder="如：牡丹厅 / A3桌" />
          <FormField label="特殊要求" value={specialRequests} onChange={setSpecialRequests} placeholder="忌口、特殊布置等（选填）" />
        </div>

        <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
          <button onClick={onClose} style={{
            flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
            border: '2px solid var(--tx-border)', background: '#fff',
            fontSize: 20, fontWeight: 700, cursor: 'pointer', color: 'var(--tx-text-2)',
          }}>取消</button>
          <button onClick={handleSubmit} disabled={isLoading} style={{
            flex: 1, height: 56, borderRadius: 'var(--tx-radius-md)',
            border: 'none', background: 'var(--tx-primary)', color: '#fff',
            fontSize: 20, fontWeight: 700, cursor: isLoading ? 'not-allowed' : 'pointer',
            opacity: isLoading ? 0.6 : 1,
          }}>{isLoading ? '提交中...' : '确认创建'}</button>
        </div>
      </div>
    </div>
  );
}

const stepBtnStyle: React.CSSProperties = {
  width: 48, height: 48, borderRadius: 'var(--tx-radius-md)',
  border: '2px solid var(--tx-border)', background: '#fff',
  fontSize: 22, fontWeight: 700, cursor: 'pointer',
};

function FormField({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder: string;
}) {
  return (
    <div>
      <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>{label}</div>
      <input
        value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        style={{
          width: '100%', height: 48, borderRadius: 'var(--tx-radius-md)',
          border: '2px solid var(--tx-border)', padding: '0 16px', fontSize: 18, outline: 'none',
        }}
      />
    </div>
  );
}

function StatBadge({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 28, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 16, color: 'var(--tx-text-3)' }}>{label}</div>
    </div>
  );
}
