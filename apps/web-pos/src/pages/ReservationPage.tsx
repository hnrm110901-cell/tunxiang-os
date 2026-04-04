/**
 * 预订排队台账 — 双栏布局
 * 左：预订列表（按时段分组） 右：详情/新建
 */
import { useState, useEffect, useCallback } from 'react';

// ─── API helpers ───

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '';

interface Reservation {
  id: string;
  customer_name: string;
  phone: string;
  guest_count: number;
  time_slot: string;
  room_or_table: string;
  special_requests: string;
  status: string;
}

interface ReservationListResult {
  items: Reservation[];
  total: number;
}

async function txFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options.headers as Record<string, string> || {}),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

async function fetchReservations(): Promise<ReservationListResult> {
  return txFetch<ReservationListResult>(`/api/v1/reservations?store_id=${encodeURIComponent(STORE_ID)}`);
}

async function createReservation(body: {
  store_id: string;
  customer_name: string;
  phone: string;
  guest_count: number;
  time_slot: string;
  room_or_table: string;
  special_requests: string;
}): Promise<Reservation> {
  return txFetch<Reservation>('/api/v1/reservations', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

async function updateReservationStatus(id: string, status: string): Promise<void> {
  return txFetch<void>(`/api/v1/reservations/${encodeURIComponent(id)}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
}

// ─── Status config ───

const statusMap: Record<string, { label: string; color: string }> = {
  pending: { label: '待确认', color: '#faad14' },
  confirmed: { label: '已确认', color: '#52c41a' },
  seated: { label: '已就座', color: '#1890ff' },
  cancelled: { label: '已取消', color: '#ff4d4f' },
  no_show: { label: '爽约', color: '#999' },
};

// ─── Creation form ───

interface CreateFormProps {
  onSubmit: (data: {
    customer_name: string;
    phone: string;
    guest_count: number;
    time_slot: string;
    room_or_table: string;
    special_requests: string;
  }) => void;
  onCancel: () => void;
  submitting: boolean;
}

function CreateForm({ onSubmit, onCancel, submitting }: CreateFormProps) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [guests, setGuests] = useState(2);
  const [timeSlot, setTimeSlot] = useState('');
  const [table, setTable] = useState('');
  const [notes, setNotes] = useState('');

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '8px 10px', background: '#0B1A20', color: '#fff',
    border: '1px solid #1a2a33', borderRadius: 6, marginBottom: 10, boxSizing: 'border-box',
  };
  const labelStyle: React.CSSProperties = { fontSize: 12, color: '#999', marginBottom: 4, display: 'block' };

  const handleSubmit = () => {
    if (!name.trim() || !phone.trim() || !timeSlot.trim()) return;
    onSubmit({ customer_name: name.trim(), phone: phone.trim(), guest_count: guests, time_slot: timeSlot.trim(), room_or_table: table.trim(), special_requests: notes.trim() });
  };

  return (
    <div>
      <h4 style={{ margin: '0 0 12px' }}>新增预订</h4>
      <label style={labelStyle}>姓名 *</label>
      <input style={inputStyle} value={name} onChange={e => setName(e.target.value)} placeholder="客人姓名" />
      <label style={labelStyle}>手机 *</label>
      <input style={inputStyle} value={phone} onChange={e => setPhone(e.target.value)} placeholder="手机号" />
      <label style={labelStyle}>人数</label>
      <input style={inputStyle} type="number" min={1} value={guests} onChange={e => setGuests(Number(e.target.value) || 1)} />
      <label style={labelStyle}>时段 *</label>
      <input style={inputStyle} value={timeSlot} onChange={e => setTimeSlot(e.target.value)} placeholder="如 18:00" />
      <label style={labelStyle}>桌号/包间</label>
      <input style={inputStyle} value={table} onChange={e => setTable(e.target.value)} placeholder="可选" />
      <label style={labelStyle}>备注</label>
      <input style={inputStyle} value={notes} onChange={e => setNotes(e.target.value)} placeholder="特殊要求" />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button
          disabled={submitting || !name.trim() || !phone.trim() || !timeSlot.trim()}
          onClick={handleSubmit}
          style={{ flex: 1, padding: 8, background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', opacity: submitting ? 0.6 : 1 }}
        >
          {submitting ? '提交中...' : '确认创建'}
        </button>
        <button onClick={onCancel} style={{ flex: 1, padding: 8, background: '#333', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
          取消
        </button>
      </div>
    </div>
  );
}

// ─── Main page ───

export function ReservationPage() {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const loadReservations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchReservations();
      setReservations(result.items);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '加载预订列表失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadReservations();
  }, [loadReservations]);

  const handleCreate = async (data: {
    customer_name: string;
    phone: string;
    guest_count: number;
    time_slot: string;
    room_or_table: string;
    special_requests: string;
  }) => {
    setSubmitting(true);
    try {
      await createReservation({ store_id: STORE_ID, ...data });
      setShowCreate(false);
      await loadReservations();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '创建预订失败';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleStatusUpdate = async (id: string, status: string) => {
    setActionLoading(id);
    try {
      await updateReservationStatus(id, status);
      await loadReservations();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '更新状态失败';
      setError(message);
    } finally {
      setActionLoading(null);
    }
  };

  const lunchItems = reservations.filter(r => {
    const hour = parseInt(r.time_slot, 10);
    return !isNaN(hour) && hour < 15;
  });
  const dinnerItems = reservations.filter(r => {
    const hour = parseInt(r.time_slot, 10);
    return isNaN(hour) || hour >= 15;
  });

  const selectedReservation = reservations.find(x => x.id === selected);

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左：预订列表 */}
      <div style={{ flex: 1, padding: 16, overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>预订台账</h3>
          <button
            onClick={() => { setShowCreate(true); setSelected(null); }}
            style={{ padding: '6px 16px', background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}
          >
            + 新增预订
          </button>
        </div>

        {error && (
          <div style={{ padding: '8px 12px', marginBottom: 10, background: '#ff4d4f22', color: '#ff4d4f', borderRadius: 6, fontSize: 13 }}>
            {error}
            <button onClick={loadReservations} style={{ marginLeft: 12, background: 'none', border: 'none', color: '#ff4d4f', textDecoration: 'underline', cursor: 'pointer', fontSize: 13 }}>重试</button>
          </div>
        )}

        {loading ? (
          <div style={{ color: '#666', textAlign: 'center', marginTop: 40 }}>加载中...</div>
        ) : reservations.length === 0 && !error ? (
          <div style={{ color: '#666', textAlign: 'center', marginTop: 40 }}>暂无预订</div>
        ) : (
          <>
            {/* 午市 */}
            <div style={{ fontSize: 11, color: '#999', padding: '8px 0 4px', borderBottom: '1px solid #1a2a33' }}>午市 (11:00-14:00)</div>
            {lunchItems.length === 0 ? (
              <div style={{ color: '#444', fontSize: 12, padding: '10px 8px' }}>暂无午市预订</div>
            ) : (
              lunchItems.map(r => (
                <ReservationRow key={r.id} r={r} selected={selected === r.id} onSelect={() => { setSelected(r.id); setShowCreate(false); }} />
              ))
            )}

            {/* 晚市 */}
            <div style={{ fontSize: 11, color: '#999', padding: '12px 0 4px', borderBottom: '1px solid #1a2a33' }}>晚市 (17:00-21:00)</div>
            {dinnerItems.length === 0 ? (
              <div style={{ color: '#444', fontSize: 12, padding: '10px 8px' }}>暂无晚市预订</div>
            ) : (
              dinnerItems.map(r => (
                <ReservationRow key={r.id} r={r} selected={selected === r.id} onSelect={() => { setSelected(r.id); setShowCreate(false); }} />
              ))
            )}
          </>
        )}
      </div>

      {/* 右：详情/新建 */}
      <div style={{ width: 320, background: '#112228', padding: 16, borderLeft: '1px solid #1a2a33' }}>
        {showCreate ? (
          <CreateForm onSubmit={handleCreate} onCancel={() => setShowCreate(false)} submitting={submitting} />
        ) : selectedReservation ? (
          <div>
            <h4 style={{ margin: '0 0 12px' }}>预订详情</h4>
            {(() => {
              const r = selectedReservation;
              const s = statusMap[r.status] || { label: r.status, color: '#999' };
              const isActioning = actionLoading === r.id;
              return (
                <div>
                  <div style={{ fontSize: 20, fontWeight: 'bold', marginBottom: 8 }}>{r.customer_name}</div>
                  <div style={{ color: '#999', marginBottom: 4 }}>{r.phone}</div>
                  <div style={{ marginBottom: 4 }}>{r.guest_count} 人 · {r.time_slot} · {r.room_or_table || '待分桌'}</div>
                  {r.special_requests && (
                    <div style={{ color: '#999', fontSize: 12, marginBottom: 4 }}>备注: {r.special_requests}</div>
                  )}
                  <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, background: s.color + '22', color: s.color }}>{s.label}</span>
                  {(r.status === 'pending' || r.status === 'confirmed') && (
                    <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                      {r.status === 'pending' && (
                        <button
                          disabled={isActioning}
                          onClick={() => handleStatusUpdate(r.id, 'confirmed')}
                          style={{ flex: 1, padding: 8, background: '#52c41a', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', opacity: isActioning ? 0.6 : 1 }}
                        >
                          {isActioning ? '处理中...' : '确认'}
                        </button>
                      )}
                      <button
                        disabled={isActioning}
                        onClick={() => handleStatusUpdate(r.id, 'cancelled')}
                        style={{ flex: 1, padding: 8, background: '#333', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', opacity: isActioning ? 0.6 : 1 }}
                      >
                        {isActioning ? '处理中...' : '取消'}
                      </button>
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        ) : (
          <div style={{ color: '#666', textAlign: 'center', marginTop: 40 }}>选择预订查看详情</div>
        )}
      </div>
    </div>
  );
}

function ReservationRow({ r, selected, onSelect }: { r: Reservation; selected: boolean; onSelect: () => void }) {
  const s = statusMap[r.status] || { label: r.status, color: '#999' };
  return (
    <div onClick={onSelect} style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '10px 8px', cursor: 'pointer', borderRadius: 6,
      background: selected ? '#1a2a33' : 'transparent',
      borderBottom: '1px solid #112228',
    }}>
      <div>
        <div style={{ fontWeight: 'bold' }}>{r.customer_name} <span style={{ fontWeight: 'normal', color: '#999' }}>({r.guest_count}人)</span></div>
        <div style={{ fontSize: 12, color: '#666' }}>{r.time_slot} · {r.room_or_table || '待分桌'}</div>
      </div>
      <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 10, background: s.color + '22', color: s.color }}>{s.label}</span>
    </div>
  );
}
