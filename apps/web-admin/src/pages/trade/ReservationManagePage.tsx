/**
 * 预定管理页 — /hq/reservations
 * P1-02: 总部级预定台账、台型分配、爽约管理
 * API: GET  /api/v1/reservations?store_id=&date=&status=
 *      POST /api/v1/reservations
 *      PUT  /api/v1/reservations/{id}/status
 *      GET  /api/v1/reservations/stats
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { apiGet, apiPost } from '../../api/client';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

type ReservationStatus = 'pending' | 'confirmed' | 'arrived' | 'queuing' | 'seated' | 'completed' | 'cancelled' | 'no_show';
type ReservationType = 'regular' | 'banquet' | 'private_room' | 'outdoor' | 'vip';
type SourceChannel = 'meituan' | 'dianping' | 'wechat' | 'phone' | 'walkin';

interface ReservationItem {
  id: string;
  reservation_id: string;
  store_id: string;
  confirmation_code: string;
  customer_name: string;
  phone: string;
  type: ReservationType;
  date: string;
  time: string;
  estimated_end_time: string | null;
  party_size: number;
  room_name: string | null;
  table_no: string | null;
  special_requests: string | null;
  deposit_required: boolean;
  deposit_amount_fen: number;
  deposit_paid: boolean;
  consumer_id: string | null;
  source_channel: SourceChannel;
  status: ReservationStatus;
  confirmed_by: string | null;
  cancel_reason: string | null;
  cancel_fee_fen: number;
  no_show_recorded: boolean;
  arrived_at: string | null;
  seated_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
}

interface StoreOption { id: string; name: string; }

interface ReservationStats {
  total: number;
  pending: number;
  confirmed: number;
  arrived: number;
  seated: number;
  completed: number;
  cancelled: number;
  no_show: number;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<ReservationStatus, { label: string; color: string; bg: string }> = {
  pending:    { label: '待确认', color: '#BA7517', bg: 'rgba(186,117,23,0.10)' },
  confirmed:  { label: '已确认', color: '#185FA5', bg: 'rgba(24,95,165,0.10)' },
  arrived:    { label: '已到店', color: '#0F6E56', bg: 'rgba(15,110,86,0.10)' },
  queuing:    { label: '排队中', color: '#7C3AED', bg: 'rgba(124,58,237,0.10)' },
  seated:     { label: '已入座', color: '#0F6E56', bg: 'rgba(15,110,86,0.15)' },
  completed:  { label: '已完成', color: '#6B7280', bg: 'rgba(107,114,128,0.10)' },
  cancelled:  { label: '已取消', color: '#A32D2D', bg: 'rgba(163,45,45,0.10)' },
  no_show:    { label: '爽约',   color: '#A32D2D', bg: 'rgba(163,45,45,0.15)' },
};

const TYPE_LABELS: Record<ReservationType, string> = {
  regular: '普通', banquet: '宴席', private_room: '包间', outdoor: '露天', vip: 'VIP',
};

const SOURCE_LABELS: Record<SourceChannel, string> = {
  meituan: '美团', dianping: '大众点评', wechat: '微信', phone: '电话', walkin: '到店',
};

const FALLBACK_STORES: StoreOption[] = [
  { id: 'store-001', name: '徐记海鲜·芙蓉店' },
  { id: 'store-002', name: '徐记海鲜·梅溪湖店' },
  { id: 'store-003', name: '徐记海鲜·IFS店' },
];

const FALLBACK_RESERVATIONS: ReservationItem[] = [
  { id: '1', reservation_id: 'RSV-20260409001', store_id: 'store-001', confirmation_code: '836521', customer_name: '张先生', phone: '138****8001', type: 'private_room', date: '2026-04-09', time: '18:00', estimated_end_time: '20:00', party_size: 8, room_name: '湘江厅', table_no: null, special_requests: '需要儿童座椅，一位客人海鲜过敏', deposit_required: true, deposit_amount_fen: 50000, deposit_paid: true, consumer_id: 'M-1001', source_channel: 'phone', status: 'confirmed', confirmed_by: '李经理', cancel_reason: null, cancel_fee_fen: 0, no_show_recorded: false, arrived_at: null, seated_at: null, completed_at: null, cancelled_at: null, created_at: '2026-04-08T14:30:00Z' },
  { id: '2', reservation_id: 'RSV-20260409002', store_id: 'store-001', confirmation_code: '472913', customer_name: '王小姐', phone: '139****5002', type: 'regular', date: '2026-04-09', time: '12:00', estimated_end_time: '13:30', party_size: 4, room_name: null, table_no: 'A-05', special_requests: null, deposit_required: false, deposit_amount_fen: 0, deposit_paid: false, consumer_id: null, source_channel: 'meituan', status: 'arrived', confirmed_by: null, cancel_reason: null, cancel_fee_fen: 0, no_show_recorded: false, arrived_at: '2026-04-09T11:55:00Z', seated_at: null, completed_at: null, cancelled_at: null, created_at: '2026-04-09T08:00:00Z' },
  { id: '3', reservation_id: 'RSV-20260409003', store_id: 'store-001', confirmation_code: '195847', customer_name: '刘总', phone: '136****3003', type: 'vip', date: '2026-04-09', time: '18:30', estimated_end_time: '21:00', party_size: 12, room_name: '岳麓厅（大包）', table_no: null, special_requests: '商务宴请，需最好的包间，提前准备茶水', deposit_required: true, deposit_amount_fen: 100000, deposit_paid: true, consumer_id: 'M-VIP-088', source_channel: 'phone', status: 'pending', confirmed_by: null, cancel_reason: null, cancel_fee_fen: 0, no_show_recorded: false, arrived_at: null, seated_at: null, completed_at: null, cancelled_at: null, created_at: '2026-04-09T09:15:00Z' },
  { id: '4', reservation_id: 'RSV-20260408004', store_id: 'store-001', confirmation_code: '624780', customer_name: '陈女士', phone: '137****7004', type: 'regular', date: '2026-04-08', time: '19:00', estimated_end_time: null, party_size: 2, room_name: null, table_no: 'B-12', special_requests: null, deposit_required: false, deposit_amount_fen: 0, deposit_paid: false, consumer_id: null, source_channel: 'dianping', status: 'no_show', confirmed_by: null, cancel_reason: null, cancel_fee_fen: 0, no_show_recorded: true, arrived_at: null, seated_at: null, completed_at: null, cancelled_at: null, created_at: '2026-04-08T10:00:00Z' },
  { id: '5', reservation_id: 'RSV-20260409005', store_id: 'store-001', confirmation_code: '381046', customer_name: '赵先生', phone: '135****9005', type: 'banquet', date: '2026-04-10', time: '17:30', estimated_end_time: '21:00', party_size: 30, room_name: '星城宴会厅', table_no: null, special_requests: '生日宴，需要布置+蛋糕+LED屏祝福语', deposit_required: true, deposit_amount_fen: 200000, deposit_paid: false, consumer_id: 'M-2005', source_channel: 'wechat', status: 'pending', confirmed_by: null, cancel_reason: null, cancel_fee_fen: 0, no_show_recorded: false, arrived_at: null, seated_at: null, completed_at: null, cancelled_at: null, created_at: '2026-04-09T11:00:00Z' },
  { id: '6', reservation_id: 'RSV-20260409006', store_id: 'store-001', confirmation_code: '759213', customer_name: '黄先生', phone: '133****6006', type: 'regular', date: '2026-04-09', time: '11:30', estimated_end_time: '13:00', party_size: 6, room_name: null, table_no: 'C-08', special_requests: null, deposit_required: false, deposit_amount_fen: 0, deposit_paid: false, consumer_id: null, source_channel: 'walkin', status: 'seated', confirmed_by: null, cancel_reason: null, cancel_fee_fen: 0, no_show_recorded: false, arrived_at: '2026-04-09T11:25:00Z', seated_at: '2026-04-09T11:30:00Z', completed_at: null, cancelled_at: null, created_at: '2026-04-09T11:20:00Z' },
];

// ─── 辅助函数 ──────────────────────────────────────────────────────────────────

function formatFen(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

function getToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function ReservationManagePage() {
  // 筛选状态
  const [selectedStore, setSelectedStore] = useState('');
  const [selectedDate, setSelectedDate] = useState(getToday());
  const [selectedStatus, setSelectedStatus] = useState<ReservationStatus | ''>('');
  const [searchText, setSearchText] = useState('');

  // 数据
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [reservations, setReservations] = useState<ReservationItem[]>([]);
  const [stats, setStats] = useState<ReservationStats | null>(null);
  const [loading, setLoading] = useState(false);

  // 弹窗
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showDetailDrawer, setShowDetailDrawer] = useState(false);
  const [selectedReservation, setSelectedReservation] = useState<ReservationItem | null>(null);
  const [showActionModal, setShowActionModal] = useState(false);
  const [actionType, setActionType] = useState<string>('');

  // ─── 数据加载 ──────────────────────────────────────────────────────────────

  const loadStores = useCallback(async () => {
    try {
      const res = await apiGet<{ items: StoreOption[] }>('/api/v1/trade/stores');
      if (res.ok && res.data?.items?.length) { setStores(res.data.items); setSelectedStore(res.data.items[0].id); }
      else { setStores(FALLBACK_STORES); setSelectedStore(FALLBACK_STORES[0].id); }
    } catch { setStores(FALLBACK_STORES); setSelectedStore(FALLBACK_STORES[0].id); }
  }, []);

  const loadReservations = useCallback(async () => {
    if (!selectedStore) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ store_id: selectedStore, date: selectedDate, size: '200' });
      if (selectedStatus) params.set('status', selectedStatus);
      const res = await apiGet<{ items: ReservationItem[] }>(`/api/v1/reservations?${params}`);
      if (res.ok && res.data?.items) { setReservations(res.data.items); }
      else { setReservations(FALLBACK_RESERVATIONS); }
    } catch { setReservations(FALLBACK_RESERVATIONS); }
    setLoading(false);
  }, [selectedStore, selectedDate, selectedStatus]);

  const loadStats = useCallback(async () => {
    if (!selectedStore) return;
    try {
      const res = await apiGet<ReservationStats>(`/api/v1/reservations/stats?store_id=${selectedStore}&date=${selectedDate}`);
      if (res.ok && res.data) setStats(res.data);
      else setStats({ total: 6, pending: 2, confirmed: 1, arrived: 1, seated: 1, completed: 0, cancelled: 0, no_show: 1 });
    } catch { setStats({ total: 6, pending: 2, confirmed: 1, arrived: 1, seated: 1, completed: 0, cancelled: 0, no_show: 1 }); }
  }, [selectedStore, selectedDate]);

  useEffect(() => { loadStores(); }, [loadStores]);
  useEffect(() => { loadReservations(); loadStats(); }, [loadReservations, loadStats]);

  // ─── 操作 ──────────────────────────────────────────────────────────────────

  const handleStatusAction = async (reservationId: string, action: string, extra?: Record<string, unknown>) => {
    try {
      const res = await apiPost<null>(`/api/v1/reservations/${reservationId}/status`, { action, ...extra });
      if (res.ok) { loadReservations(); loadStats(); setShowActionModal(false); setShowDetailDrawer(false); }
    } catch { /* handled by apiPost */ }
  };

  const openAction = (reservation: ReservationItem, action: string) => {
    setSelectedReservation(reservation);
    setActionType(action);
    setShowActionModal(true);
  };

  // ─── 筛选 ──────────────────────────────────────────────────────────────────

  const filtered = useMemo(() => {
    if (!searchText.trim()) return reservations;
    const q = searchText.toLowerCase();
    return reservations.filter(r =>
      r.customer_name.toLowerCase().includes(q) ||
      r.phone.includes(q) ||
      r.reservation_id.toLowerCase().includes(q) ||
      r.confirmation_code.includes(q)
    );
  }, [reservations, searchText]);

  // ─── 渲染 ──────────────────────────────────────────────────────────────────

  const pageStyle: React.CSSProperties = { padding: '24px', maxWidth: 1400, margin: '0 auto' };
  const headerStyle: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 };
  const titleStyle: React.CSSProperties = { fontSize: 20, fontWeight: 600, color: '#1E2A3A' };
  const subtitleStyle: React.CSSProperties = { fontSize: 13, color: '#6B7280', marginTop: 4 };

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={headerStyle}>
        <div>
          <div style={titleStyle}>预定管理</div>
          <div style={subtitleStyle}>管理门店预定台账，确认/入座/爽约全流程</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setShowCreateModal(true)} style={{ padding: '8px 16px', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 500, fontSize: 14 }}>
            + 新建预定
          </button>
        </div>
      </div>

      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={selectedStore} onChange={e => setSelectedStore(e.target.value)} style={selectStyle}>
          {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)} style={{ ...selectStyle, width: 160 }} />
        <select value={selectedStatus} onChange={e => setSelectedStatus(e.target.value as ReservationStatus | '')} style={selectStyle}>
          <option value="">全部状态</option>
          {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <input placeholder="搜索姓名/手机/预定号" value={searchText} onChange={e => setSearchText(e.target.value)} style={{ ...selectStyle, width: 220 }} />
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
          <StatCard label="今日总预定" value={stats.total} color="#1E2A3A" />
          <StatCard label="待确认" value={stats.pending} color="#BA7517" />
          <StatCard label="已确认" value={stats.confirmed} color="#185FA5" />
          <StatCard label="已到店" value={stats.arrived} color="#0F6E56" />
          <StatCard label="已入座" value={stats.seated} color="#0F6E56" />
          <StatCard label="已完成" value={stats.completed} color="#6B7280" />
          <StatCard label="已取消" value={stats.cancelled} color="#A32D2D" />
          <StatCard label="爽约" value={stats.no_show} color="#A32D2D" />
        </div>
      )}

      {/* 预定列表 */}
      <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #E5E7EB', overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ background: '#F8F7F5' }}>
                {['预定号', '状态', '客户', '电话', '类型', '日期', '时间', '人数', '桌位/包间', '来源', '定金', '操作'].map(h => (
                  <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 500, color: '#6B7280', borderBottom: '1px solid #E5E7EB', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={12} style={{ padding: 40, textAlign: 'center', color: '#9CA3AF' }}>加载中...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={12} style={{ padding: 40, textAlign: 'center', color: '#9CA3AF' }}>暂无预定记录</td></tr>
              ) : filtered.map(r => {
                const sc = STATUS_CONFIG[r.status];
                return (
                  <tr key={r.id} style={{ borderBottom: '1px solid #F3F4F6', cursor: 'pointer' }}
                    onClick={() => { setSelectedReservation(r); setShowDetailDrawer(true); }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#FAFAF8')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >
                    <td style={cellStyle}>
                      <div style={{ fontWeight: 500 }}>{r.reservation_id}</div>
                      <div style={{ fontSize: 12, color: '#9CA3AF' }}>{r.confirmation_code}</div>
                    </td>
                    <td style={cellStyle}>
                      <span style={{ display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 12, fontWeight: 500, color: sc.color, background: sc.bg }}>{sc.label}</span>
                    </td>
                    <td style={cellStyle}>{r.customer_name}</td>
                    <td style={cellStyle}>{r.phone}</td>
                    <td style={cellStyle}>{TYPE_LABELS[r.type]}</td>
                    <td style={cellStyle}>{r.date}</td>
                    <td style={cellStyle}>{r.time}{r.estimated_end_time ? `~${r.estimated_end_time}` : ''}</td>
                    <td style={cellStyle}>{r.party_size}人</td>
                    <td style={cellStyle}>{r.room_name || r.table_no || '—'}</td>
                    <td style={cellStyle}>{SOURCE_LABELS[r.source_channel]}</td>
                    <td style={cellStyle}>
                      {r.deposit_required ? (
                        <span style={{ color: r.deposit_paid ? '#0F6E56' : '#BA7517' }}>
                          {formatFen(r.deposit_amount_fen)} {r.deposit_paid ? '✓' : '未付'}
                        </span>
                      ) : '—'}
                    </td>
                    <td style={cellStyle} onClick={e => e.stopPropagation()}>
                      <div style={{ display: 'flex', gap: 4 }}>
                        {r.status === 'pending' && (
                          <ActionBtn label="确认" color="#185FA5" onClick={() => openAction(r, 'confirm')} />
                        )}
                        {(r.status === 'confirmed' || r.status === 'arrived') && (
                          <ActionBtn label="入座" color="#0F6E56" onClick={() => openAction(r, 'seat')} />
                        )}
                        {r.status === 'pending' && (
                          <ActionBtn label="取消" color="#A32D2D" onClick={() => openAction(r, 'cancel')} />
                        )}
                        {r.status === 'confirmed' && (
                          <ActionBtn label="爽约" color="#A32D2D" onClick={() => openAction(r, 'no_show')} />
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 详情抽屉 */}
      {showDetailDrawer && selectedReservation && (
        <DetailDrawer
          reservation={selectedReservation}
          onClose={() => { setShowDetailDrawer(false); setSelectedReservation(null); }}
          onAction={(action) => openAction(selectedReservation, action)}
        />
      )}

      {/* 操作确认弹窗 */}
      {showActionModal && selectedReservation && (
        <ActionModal
          reservation={selectedReservation}
          action={actionType}
          onConfirm={(extra) => handleStatusAction(selectedReservation.id, actionType, extra)}
          onCancel={() => setShowActionModal(false)}
        />
      )}

      {/* 新建预定弹窗 */}
      {showCreateModal && (
        <CreateModal
          storeId={selectedStore}
          onSuccess={() => { setShowCreateModal(false); loadReservations(); loadStats(); }}
          onCancel={() => setShowCreateModal(false)}
        />
      )}
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

const selectStyle: React.CSSProperties = {
  padding: '7px 12px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 14, background: '#fff', color: '#374151', outline: 'none',
};

const cellStyle: React.CSSProperties = {
  padding: '10px 12px', whiteSpace: 'nowrap',
};

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #E5E7EB', padding: '14px 16px' }}>
      <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

function ActionBtn({ label, color, onClick }: { label: string; color: string; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{ padding: '3px 10px', fontSize: 12, border: `1px solid ${color}`, borderRadius: 4, background: 'transparent', color, cursor: 'pointer', fontWeight: 500 }}>
      {label}
    </button>
  );
}

function DetailDrawer({ reservation: r, onClose, onAction }: { reservation: ReservationItem; onClose: () => void; onAction: (action: string) => void }) {
  const sc = STATUS_CONFIG[r.status];
  const overlayStyle: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000, display: 'flex', justifyContent: 'flex-end' };
  const drawerStyle: React.CSSProperties = { width: 420, maxWidth: '90vw', background: '#fff', height: '100%', overflowY: 'auto', padding: 24, boxShadow: '-4px 0 12px rgba(0,0,0,0.08)' };
  const sectionStyle: React.CSSProperties = { marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid #F3F4F6' };
  const labelStyle: React.CSSProperties = { fontSize: 12, color: '#6B7280', marginBottom: 2 };
  const valueStyle: React.CSSProperties = { fontSize: 14, color: '#1E2A3A', fontWeight: 500 };

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={drawerStyle} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ fontSize: 18, fontWeight: 600 }}>预定详情</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#6B7280' }}>×</button>
        </div>

        {/* 状态 + 预定号 */}
        <div style={sectionStyle}>
          <span style={{ padding: '4px 12px', borderRadius: 6, fontSize: 14, fontWeight: 500, color: sc.color, background: sc.bg }}>{sc.label}</span>
          <div style={{ marginTop: 8, fontSize: 13, color: '#6B7280' }}>{r.reservation_id} · 确认码 {r.confirmation_code}</div>
        </div>

        {/* 客户信息 */}
        <div style={sectionStyle}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>客户信息</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px' }}>
            <div><div style={labelStyle}>姓名</div><div style={valueStyle}>{r.customer_name}</div></div>
            <div><div style={labelStyle}>电话</div><div style={valueStyle}>{r.phone}</div></div>
            <div><div style={labelStyle}>人数</div><div style={valueStyle}>{r.party_size}人</div></div>
            <div><div style={labelStyle}>类型</div><div style={valueStyle}>{TYPE_LABELS[r.type]}</div></div>
            {r.consumer_id && <div><div style={labelStyle}>会员ID</div><div style={valueStyle}>{r.consumer_id}</div></div>}
          </div>
        </div>

        {/* 预定信息 */}
        <div style={sectionStyle}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>预定信息</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px' }}>
            <div><div style={labelStyle}>日期</div><div style={valueStyle}>{r.date}</div></div>
            <div><div style={labelStyle}>时间</div><div style={valueStyle}>{r.time}{r.estimated_end_time ? ` ~ ${r.estimated_end_time}` : ''}</div></div>
            <div><div style={labelStyle}>桌位/包间</div><div style={valueStyle}>{r.room_name || r.table_no || '待分配'}</div></div>
            <div><div style={labelStyle}>来源</div><div style={valueStyle}>{SOURCE_LABELS[r.source_channel]}</div></div>
          </div>
          {r.special_requests && (
            <div style={{ marginTop: 8 }}>
              <div style={labelStyle}>特殊要求</div>
              <div style={{ ...valueStyle, fontWeight: 400, color: '#BA7517', padding: '6px 10px', background: 'rgba(186,117,23,0.06)', borderRadius: 6, marginTop: 4 }}>
                {r.special_requests}
              </div>
            </div>
          )}
        </div>

        {/* 定金 */}
        {r.deposit_required && (
          <div style={sectionStyle}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>定金</div>
            <div style={{ display: 'flex', gap: 16 }}>
              <div><div style={labelStyle}>金额</div><div style={valueStyle}>{formatFen(r.deposit_amount_fen)}</div></div>
              <div><div style={labelStyle}>状态</div><div style={{ ...valueStyle, color: r.deposit_paid ? '#0F6E56' : '#A32D2D' }}>{r.deposit_paid ? '已支付' : '未支付'}</div></div>
            </div>
          </div>
        )}

        {/* 时间线 */}
        <div style={sectionStyle}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>时间线</div>
          <TimelineItem label="创建" time={r.created_at} />
          {r.confirmed_by && <TimelineItem label={`确认（${r.confirmed_by}）`} time={null} />}
          {r.arrived_at && <TimelineItem label="到店" time={r.arrived_at} />}
          {r.seated_at && <TimelineItem label="入座" time={r.seated_at} />}
          {r.completed_at && <TimelineItem label="完成" time={r.completed_at} />}
          {r.cancelled_at && <TimelineItem label={`取消${r.cancel_reason ? ` — ${r.cancel_reason}` : ''}`} time={r.cancelled_at} />}
          {r.no_show_recorded && <TimelineItem label="爽约已记录" time={null} />}
        </div>

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {r.status === 'pending' && <ActionBtn label="确认预定" color="#185FA5" onClick={() => onAction('confirm')} />}
          {r.status === 'pending' && <ActionBtn label="取消预定" color="#A32D2D" onClick={() => onAction('cancel')} />}
          {(r.status === 'confirmed' || r.status === 'arrived') && <ActionBtn label="安排入座" color="#0F6E56" onClick={() => onAction('seat')} />}
          {r.status === 'confirmed' && <ActionBtn label="记录爽约" color="#A32D2D" onClick={() => onAction('no_show')} />}
          {r.status === 'seated' && <ActionBtn label="完成用餐" color="#0F6E56" onClick={() => onAction('complete')} />}
        </div>
      </div>
    </div>
  );
}

function TimelineItem({ label, time }: { label: string; time: string | null }) {
  const formatted = time ? new Date(time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#D1D5DB', flexShrink: 0 }} />
      <div style={{ fontSize: 13, color: '#374151' }}>{label}</div>
      {formatted && <div style={{ fontSize: 12, color: '#9CA3AF' }}>{formatted}</div>}
    </div>
  );
}

function ActionModal({ reservation: r, action, onConfirm, onCancel }: {
  reservation: ReservationItem; action: string;
  onConfirm: (extra?: Record<string, unknown>) => void; onCancel: () => void;
}) {
  const [tableNo, setTableNo] = useState(r.table_no || '');
  const [cancelReason, setCancelReason] = useState('');
  const [cancelFee, setCancelFee] = useState('0');

  const actionLabels: Record<string, string> = {
    confirm: '确认预定', seat: '安排入座', cancel: '取消预定', no_show: '记录爽约', complete: '完成用餐', arrive: '标记到店',
  };

  const handleSubmit = () => {
    const extra: Record<string, unknown> = {};
    if (action === 'seat') extra.table_no = tableNo;
    if (action === 'cancel') { extra.reason = cancelReason; extra.cancel_fee_fen = Math.round(parseFloat(cancelFee) * 100); }
    onConfirm(extra);
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onCancel}>
      <div style={{ background: '#fff', borderRadius: 12, padding: 24, width: 400, maxWidth: '90vw', boxShadow: '0 8px 24px rgba(0,0,0,0.12)' }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>{actionLabels[action] || action}</div>
        <div style={{ fontSize: 14, color: '#6B7280', marginBottom: 16 }}>
          {r.customer_name} · {r.party_size}人 · {r.date} {r.time}
        </div>

        {action === 'seat' && (
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 13, color: '#374151', marginBottom: 4 }}>分配桌号 *</label>
            <input value={tableNo} onChange={e => setTableNo(e.target.value)} placeholder="如: A-01, 湘江厅" style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
          </div>
        )}

        {action === 'cancel' && (
          <>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 13, color: '#374151', marginBottom: 4 }}>取消原因</label>
              <input value={cancelReason} onChange={e => setCancelReason(e.target.value)} placeholder="客户主动取消 / 门店满座..." style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 13, color: '#374151', marginBottom: 4 }}>取消费（元）</label>
              <input type="number" value={cancelFee} onChange={e => setCancelFee(e.target.value)} min="0" step="0.01" style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
            </div>
          </>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onCancel} style={{ padding: '8px 16px', border: '1px solid #D1D5DB', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 14 }}>取消</button>
          <button onClick={handleSubmit} style={{ padding: '8px 16px', border: 'none', borderRadius: 6, background: action === 'cancel' || action === 'no_show' ? '#A32D2D' : '#FF6B35', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 500 }}>
            {actionLabels[action]}
          </button>
        </div>
      </div>
    </div>
  );
}

function CreateModal({ storeId, onSuccess, onCancel }: { storeId: string; onSuccess: () => void; onCancel: () => void }) {
  const [form, setForm] = useState({
    customer_name: '', phone: '', party_size: 2, type: 'regular' as ReservationType,
    date: getToday(), time: '18:00', room_name: '', special_requests: '',
    deposit_required: false, deposit_amount_fen: 0, source_channel: 'phone' as SourceChannel,
  });
  const [submitting, setSubmitting] = useState(false);

  const update = (key: string, value: unknown) => setForm(prev => ({ ...prev, [key]: value }));

  const handleSubmit = async () => {
    if (!form.customer_name || !form.phone) return;
    setSubmitting(true);
    try {
      const res = await apiPost<null>('/api/v1/reservations', { ...form, store_id: storeId });
      if (res.ok) onSuccess();
    } catch { /* handled */ }
    setSubmitting(false);
  };

  const fieldStyle: React.CSSProperties = { marginBottom: 12 };
  const lbl: React.CSSProperties = { display: 'block', fontSize: 13, color: '#374151', marginBottom: 4 };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onCancel}>
      <div style={{ background: '#fff', borderRadius: 12, padding: 24, width: 480, maxWidth: '90vw', maxHeight: '85vh', overflowY: 'auto', boxShadow: '0 8px 24px rgba(0,0,0,0.12)' }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 20 }}>新建预定</div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
          <div style={fieldStyle}>
            <label style={lbl}>客户姓名 *</label>
            <input value={form.customer_name} onChange={e => update('customer_name', e.target.value)} style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
          </div>
          <div style={fieldStyle}>
            <label style={lbl}>手机号 *</label>
            <input value={form.phone} onChange={e => update('phone', e.target.value)} style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
          </div>
          <div style={fieldStyle}>
            <label style={lbl}>日期</label>
            <input type="date" value={form.date} onChange={e => update('date', e.target.value)} style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
          </div>
          <div style={fieldStyle}>
            <label style={lbl}>时间</label>
            <input type="time" value={form.time} onChange={e => update('time', e.target.value)} style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
          </div>
          <div style={fieldStyle}>
            <label style={lbl}>人数</label>
            <input type="number" value={form.party_size} onChange={e => update('party_size', parseInt(e.target.value) || 1)} min={1} style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
          </div>
          <div style={fieldStyle}>
            <label style={lbl}>预定类型</label>
            <select value={form.type} onChange={e => update('type', e.target.value)} style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }}>
              {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div style={fieldStyle}>
            <label style={lbl}>来源渠道</label>
            <select value={form.source_channel} onChange={e => update('source_channel', e.target.value)} style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }}>
              {Object.entries(SOURCE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <div style={fieldStyle}>
            <label style={lbl}>包间名称</label>
            <input value={form.room_name} onChange={e => update('room_name', e.target.value)} placeholder="如: 湘江厅" style={{ ...selectStyle, width: '100%', boxSizing: 'border-box' }} />
          </div>
        </div>

        <div style={fieldStyle}>
          <label style={lbl}>特殊要求</label>
          <textarea value={form.special_requests} onChange={e => update('special_requests', e.target.value)} rows={2} placeholder="过敏信息、布置要求等..." style={{ ...selectStyle, width: '100%', boxSizing: 'border-box', resize: 'vertical' }} />
        </div>

        <div style={{ ...fieldStyle, display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={form.deposit_required} onChange={e => update('deposit_required', e.target.checked)} id="deposit-check" />
          <label htmlFor="deposit-check" style={{ fontSize: 13, color: '#374151' }}>需要定金</label>
          {form.deposit_required && (
            <input type="number" value={form.deposit_amount_fen / 100} onChange={e => update('deposit_amount_fen', Math.round(parseFloat(e.target.value || '0') * 100))} min={0} step={1} placeholder="金额（元）" style={{ ...selectStyle, width: 120, marginLeft: 8 }} />
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button onClick={onCancel} style={{ padding: '8px 16px', border: '1px solid #D1D5DB', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 14 }}>取消</button>
          <button onClick={handleSubmit} disabled={submitting} style={{ padding: '8px 16px', border: 'none', borderRadius: 6, background: '#FF6B35', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 500, opacity: submitting ? 0.6 : 1 }}>
            {submitting ? '提交中...' : '创建预定'}
          </button>
        </div>
      </div>
    </div>
  );
}
