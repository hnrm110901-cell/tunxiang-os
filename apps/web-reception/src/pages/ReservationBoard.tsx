/**
 * 预订台账 — 今日预订时间线，按时段展示
 * 每个预订: 客户名/人数/包厢/特殊要求
 * 状态: 待到店/已到店/已入座/已取消
 */
import { useState } from 'react';
import { AIInsightsPanel } from '../components/AIInsightsPanel';

type ReservationStatus = 'pending' | 'arrived' | 'seated' | 'cancelled';

interface Reservation {
  id: string;
  customerName: string;
  phone: string;
  guestCount: number;
  timeSlot: string;       // "11:30"
  roomOrTable: string;    // 包厢/桌号
  specialRequests: string;
  status: ReservationStatus;
  isVip: boolean;
  reservationCode: string;
}

const STATUS_MAP: Record<ReservationStatus, { label: string; color: string; bg: string }> = {
  pending:   { label: '待到店', color: 'var(--tx-info)',    bg: '#EBF3FF' },
  arrived:   { label: '已到店', color: 'var(--tx-primary)', bg: 'var(--tx-primary-light)' },
  seated:    { label: '已入座', color: 'var(--tx-success)', bg: '#E8F5F0' },
  cancelled: { label: '已取消', color: 'var(--tx-text-3)',  bg: '#F0F0F0' },
};

const TIME_SLOTS = ['11:00', '11:30', '12:00', '12:30', '13:00', '17:00', '17:30', '18:00', '18:30', '19:00', '19:30', '20:00'];

// 模拟数据
const MOCK_RESERVATIONS: Reservation[] = [
  { id: 'R001', customerName: '张总', phone: '138****6789', guestCount: 8, timeSlot: '11:30', roomOrTable: '牡丹厅', specialRequests: '忌辣、准备茅台2瓶', status: 'pending', isVip: true, reservationCode: 'YD20260327001' },
  { id: 'R002', customerName: '李女士', phone: '139****1234', guestCount: 4, timeSlot: '11:30', roomOrTable: 'A3桌', specialRequests: '儿童椅1把', status: 'arrived', isVip: false, reservationCode: 'YD20260327002' },
  { id: 'R003', customerName: '王经理', phone: '136****5678', guestCount: 10, timeSlot: '12:00', roomOrTable: '芙蓉厅', specialRequests: '商务接待、提前摆台', status: 'pending', isVip: true, reservationCode: 'YD20260327003' },
  { id: 'R004', customerName: '刘先生', phone: '158****4321', guestCount: 2, timeSlot: '12:00', roomOrTable: 'B5桌', specialRequests: '', status: 'seated', isVip: false, reservationCode: 'YD20260327004' },
  { id: 'R005', customerName: '赵女士', phone: '177****8765', guestCount: 6, timeSlot: '17:30', roomOrTable: '梅花厅', specialRequests: '生日聚会、准备蛋糕位', status: 'pending', isVip: false, reservationCode: 'YD20260327005' },
  { id: 'R006', customerName: '陈总', phone: '135****9999', guestCount: 12, timeSlot: '18:00', roomOrTable: '国宾厅', specialRequests: '忌海鲜、高端宴请', status: 'pending', isVip: true, reservationCode: 'YD20260327006' },
  { id: 'R007', customerName: '孙先生', phone: '150****3456', guestCount: 3, timeSlot: '18:30', roomOrTable: 'C2桌', specialRequests: '靠窗位', status: 'cancelled', isVip: false, reservationCode: 'YD20260327007' },
  { id: 'R008', customerName: '周女士', phone: '188****7777', guestCount: 5, timeSlot: '19:00', roomOrTable: '兰花厅', specialRequests: '家庭聚餐', status: 'pending', isVip: false, reservationCode: 'YD20260327008' },
];

export function ReservationBoard() {
  const [statusFilter, setStatusFilter] = useState<ReservationStatus | 'all'>('all');
  const [periodFilter, setPeriodFilter] = useState<'lunch' | 'dinner' | 'all'>('all');

  const filtered = MOCK_RESERVATIONS.filter(r => {
    if (statusFilter !== 'all' && r.status !== statusFilter) return false;
    if (periodFilter === 'lunch') {
      const hour = parseInt(r.timeSlot.split(':')[0]);
      if (hour >= 17) return false;
    }
    if (periodFilter === 'dinner') {
      const hour = parseInt(r.timeSlot.split(':')[0]);
      if (hour < 17) return false;
    }
    return true;
  });

  // 按时间段分组
  const grouped = TIME_SLOTS.reduce<Record<string, Reservation[]>>((acc, slot) => {
    const items = filtered.filter(r => r.timeSlot === slot);
    if (items.length > 0) acc[slot] = items;
    return acc;
  }, {});

  const counts = {
    total: MOCK_RESERVATIONS.length,
    pending: MOCK_RESERVATIONS.filter(r => r.status === 'pending').length,
    arrived: MOCK_RESERVATIONS.filter(r => r.status === 'arrived').length,
    seated: MOCK_RESERVATIONS.filter(r => r.status === 'seated').length,
    totalGuests: MOCK_RESERVATIONS.filter(r => r.status !== 'cancelled').reduce((s, r) => s + r.guestCount, 0),
  };

  return (
    <div style={{ padding: 24 }}>
      {/* AI 预订洞察面板 (SevenRooms + Anolla 对标) */}
      <AIInsightsPanel />

      {/* 顶部标题 + 统计 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 32, fontWeight: 800 }}>今日预订台账</h1>
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
                {items.length}桌 / {items.reduce((s, r) => s + r.guestCount, 0)}人
              </span>
            </div>

            {/* 预订卡片 */}
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {items.map(r => (
                <ReservationCard key={r.id} reservation={r} />
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
    </div>
  );
}

function ReservationCard({ reservation: r }: { reservation: Reservation }) {
  const st = STATUS_MAP[r.status];

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
      {r.isVip && (
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
        <span style={{ fontSize: 24, fontWeight: 700 }}>{r.customerName}</span>
        <span style={{ fontSize: 20, color: 'var(--tx-text-2)' }}>{r.guestCount}人</span>
      </div>

      {/* 包厢/桌号 */}
      <div style={{ fontSize: 20, fontWeight: 600, color: 'var(--tx-primary)', marginBottom: 8 }}>
        {r.roomOrTable}
      </div>

      {/* 手机号 + 预订号 */}
      <div style={{ fontSize: 16, color: 'var(--tx-text-3)', marginBottom: 8 }}>
        {r.phone} | {r.reservationCode}
      </div>

      {/* 特殊要求 */}
      {r.specialRequests && (
        <div style={{
          fontSize: 18,
          color: 'var(--tx-danger)',
          background: '#FFF5F5',
          padding: '6px 10px',
          borderRadius: 6,
          marginBottom: 12,
        }}>
          {r.specialRequests}
        </div>
      )}

      {/* 状态标签 */}
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
