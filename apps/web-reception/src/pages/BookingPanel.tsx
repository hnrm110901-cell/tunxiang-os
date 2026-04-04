/**
 * 预约管理面板 — 前台工作人员平板横屏专用
 * 左侧50%：今日预约时间轴（11:00~21:00，每30分钟一格）
 * 右侧50%：预约详情 + 操作 + 新建预约表单
 * 状态色：待确认=橙 / 已确认=蓝 / 已到店=绿 / 已取消=灰 / 爽约=红
 * 10s自动刷新
 */
import { useState, useEffect, useCallback } from 'react';

// ─── 类型 ───

type BookingStatus = 'pending' | 'confirmed' | 'arrived' | 'cancelled' | 'noshow';

interface Booking {
  id: string;
  customerName: string;
  phone: string;
  guestCount: number;
  date: string;         // YYYY-MM-DD
  timeSlot: string;     // HH:mm
  roomType: 'hall' | 'private';
  roomName: string;
  remark: string;
  status: BookingStatus;
}

interface NewBookingForm {
  customerName: string;
  phone: string;
  guestCount: string;
  date: string;
  timeSlot: string;
  roomType: 'hall' | 'private';
  roomName: string;
  remark: string;
}

// ─── 颜色常量（深色主题）───

const C = {
  bg1: '#0B1A20',
  bg2: '#112228',
  bg3: '#1A3038',
  accent: '#FF6B35',
  accentHover: '#E85A28',
  green: '#0F6E56',
  greenBg: 'rgba(15,110,86,0.25)',
  yellow: '#BA7517',
  yellowBg: 'rgba(186,117,23,0.25)',
  gray: '#5F5E5A',
  grayBg: 'rgba(95,94,90,0.25)',
  red: '#A32D2D',
  redBg: 'rgba(163,45,45,0.25)',
  blue: '#185FA5',
  blueBg: 'rgba(24,95,165,0.25)',
  orange: '#D4700A',
  orangeBg: 'rgba(212,112,10,0.25)',
  text1: '#F0EDE6',
  text2: '#B4B2A9',
  text3: '#6B7B85',
  border: 'rgba(255,255,255,0.08)',
} as const;

const STATUS_CONFIG: Record<BookingStatus, { label: string; color: string; bg: string }> = {
  pending:   { label: '待确认', color: C.orange, bg: C.orangeBg },
  confirmed: { label: '已确认', color: C.blue,   bg: C.blueBg },
  arrived:   { label: '已到店', color: C.green,  bg: C.greenBg },
  cancelled: { label: '已取消', color: C.gray,   bg: C.grayBg },
  noshow:    { label: '爽约',   color: C.red,    bg: C.redBg },
};

const TIME_SLOTS = [
  '11:00', '11:30', '12:00', '12:30', '13:00', '13:30',
  '14:00', '14:30', '15:00', '15:30', '16:00', '16:30',
  '17:00', '17:30', '18:00', '18:30', '19:00', '19:30',
  '20:00', '20:30', '21:00',
];

const ROOM_TYPE_LABEL: Record<string, string> = { hall: '大厅', private: '包厢' };

// ─── Mock 数据 ───

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

const MOCK_BOOKINGS: Booking[] = [
  { id: 'b1', customerName: '张总',   phone: '13812346789', guestCount: 8,  date: todayStr(), timeSlot: '11:30', roomType: 'private', roomName: '牡丹厅', remark: '忌辣，准备茅台2瓶', status: 'pending' },
  { id: 'b2', customerName: '李女士', phone: '13912341234', guestCount: 4,  date: todayStr(), timeSlot: '11:30', roomType: 'hall',    roomName: 'A3桌',   remark: '儿童椅1把',          status: 'confirmed' },
  { id: 'b3', customerName: '王经理', phone: '13612345678', guestCount: 10, date: todayStr(), timeSlot: '12:00', roomType: 'private', roomName: '芙蓉厅', remark: '商务接待，提前摆台',  status: 'arrived' },
  { id: 'b4', customerName: '刘先生', phone: '15812344321', guestCount: 2,  date: todayStr(), timeSlot: '12:00', roomType: 'hall',    roomName: 'B5桌',   remark: '',                    status: 'confirmed' },
  { id: 'b5', customerName: '赵女士', phone: '17712348765', guestCount: 6,  date: todayStr(), timeSlot: '17:30', roomType: 'private', roomName: '梅花厅', remark: '生日聚会，蛋糕位',    status: 'pending' },
  { id: 'b6', customerName: '陈总',   phone: '13512349999', guestCount: 12, date: todayStr(), timeSlot: '18:00', roomType: 'private', roomName: '国宾厅', remark: '忌海鲜，高端宴请',    status: 'pending' },
  { id: 'b7', customerName: '孙先生', phone: '15012343456', guestCount: 3,  date: todayStr(), timeSlot: '18:30', roomType: 'hall',    roomName: 'C2桌',   remark: '靠窗位',              status: 'cancelled' },
  { id: 'b8', customerName: '周女士', phone: '18812347777', guestCount: 5,  date: todayStr(), timeSlot: '19:00', roomType: 'private', roomName: '兰花厅', remark: '家庭聚餐',            status: 'noshow' },
];

// ─── API ───

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || '';
const TENANT_ID = (import.meta.env.VITE_TENANT_ID as string) || '';
const STORE_ID = (import.meta.env.VITE_STORE_ID as string) || 'store_001';

function getHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  if (TENANT_ID) h['X-Tenant-ID'] = TENANT_ID;
  return h;
}

async function apiFetchBookings(date: string): Promise<Booking[]> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/booking/list?store_id=${STORE_ID}&date=${date}`,
    { headers: getHeaders() },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return (json.data?.items ?? []).map((b: Record<string, unknown>) => ({
    id: (b.booking_id ?? b.id) as string,
    customerName: b.customer_name as string,
    phone: (b.phone ?? '') as string,
    guestCount: b.guest_count as number,
    date: (b.date ?? date) as string,
    timeSlot: ((b.time_slot ?? '') as string).slice(0, 5),
    roomType: (b.room_type ?? 'hall') as 'hall' | 'private',
    roomName: (b.room_name ?? b.room_or_table ?? '') as string,
    remark: (b.remark ?? b.special_requests ?? '') as string,
    status: b.status as BookingStatus,
  }));
}

async function apiUpdateBookingStatus(id: string, status: BookingStatus): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/booking/${encodeURIComponent(id)}/status`,
    {
      method: 'PUT',
      headers: getHeaders(),
      body: JSON.stringify({ status }),
    },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
}

async function apiCreateBooking(payload: {
  customer_name: string;
  phone: string;
  guest_count: number;
  date: string;
  time_slot: string;
  room_type: string;
  room_name: string;
  remark: string;
}): Promise<Booking> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/booking`,
    {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ store_id: STORE_ID, ...payload }),
    },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  const d = json.data;
  return {
    id: d.booking_id ?? d.id,
    customerName: d.customer_name,
    phone: d.phone ?? '',
    guestCount: d.guest_count,
    date: payload.date,
    timeSlot: payload.time_slot,
    roomType: payload.room_type as 'hall' | 'private',
    roomName: payload.room_name,
    remark: payload.remark,
    status: 'pending',
  };
}

// ─── 辅助 ───

function vibrate() {
  if (navigator.vibrate) navigator.vibrate(50);
}

function maskPhone(phone: string): string {
  if (phone.length >= 7) return phone.slice(0, 3) + '****' + phone.slice(-4);
  return phone.slice(-4);
}

const EMPTY_FORM: NewBookingForm = {
  customerName: '',
  phone: '',
  guestCount: '',
  date: todayStr(),
  timeSlot: '18:00',
  roomType: 'hall',
  roomName: '',
  remark: '',
};

// ─── 组件 ───

/** Popconfirm 简易实现 */
function PopConfirm({
  message,
  onConfirm,
  onCancel,
}: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.6)',
    }} onClick={onCancel}>
      <div
        style={{
          background: C.bg2,
          borderRadius: 16,
          padding: '28px 32px',
          textAlign: 'center',
          minWidth: 300,
          border: `1px solid ${C.border}`,
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 18, color: C.text1, marginBottom: 24 }}>{message}</div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, height: 48, background: C.grayBg, color: C.text2,
              border: `1px solid ${C.border}`, borderRadius: 10, fontSize: 16,
              fontWeight: 600, cursor: 'pointer', minWidth: 48, minHeight: 48,
            }}
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            style={{
              flex: 1, height: 48, background: C.accent, color: '#fff',
              border: 'none', borderRadius: 10, fontSize: 16,
              fontWeight: 700, cursor: 'pointer', minWidth: 48, minHeight: 48,
            }}
          >
            确定
          </button>
        </div>
      </div>
    </div>
  );
}

/** 时间轴上的预约卡片 */
function TimelineCard({
  booking,
  isSelected,
  onSelect,
}: {
  booking: Booking;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const statusCfg = STATUS_CONFIG[booking.status];
  return (
    <div
      onClick={onSelect}
      style={{
        background: isSelected ? C.bg3 : C.bg2,
        border: `2px solid ${isSelected ? C.accent : C.border}`,
        borderRadius: 10,
        padding: '10px 14px',
        cursor: 'pointer',
        marginBottom: 6,
        transition: 'border-color 150ms',
        minHeight: 48,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: C.text1 }}>{booking.customerName}</span>
        <span style={{
          fontSize: 14, fontWeight: 600, color: statusCfg.color,
          background: statusCfg.bg, borderRadius: 6, padding: '2px 10px',
        }}>
          {statusCfg.label}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 16, color: C.text3 }}>
        <span>{booking.guestCount}人</span>
        <span>{maskPhone(booking.phone)}</span>
        <span>{ROOM_TYPE_LABEL[booking.roomType]}/{booking.roomName}</span>
      </div>
    </div>
  );
}

/** 左侧时间轴 */
function Timeline({
  bookings,
  selectedId,
  onSelect,
}: {
  bookings: Booking[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      WebkitOverflowScrolling: 'touch',
      padding: '12px 16px',
      background: C.bg2,
      borderRadius: 12,
      border: `1px solid ${C.border}`,
    }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: C.text1, marginBottom: 12 }}>
        今日预约时间轴
      </div>
      {TIME_SLOTS.map(slot => {
        const slotBookings = bookings.filter(b => b.timeSlot === slot);
        const isNowSlot = (() => {
          const now = new Date();
          const [h, m] = slot.split(':').map(Number);
          const slotMin = h * 60 + m;
          const nowMin = now.getHours() * 60 + now.getMinutes();
          return nowMin >= slotMin && nowMin < slotMin + 30;
        })();

        return (
          <div key={slot} style={{
            display: 'flex',
            gap: 12,
            marginBottom: 4,
            borderLeft: isNowSlot ? `3px solid ${C.accent}` : `3px solid ${C.border}`,
            paddingLeft: 12,
            paddingTop: 6,
            paddingBottom: 6,
            minHeight: 40,
          }}>
            {/* 时间标签 */}
            <div style={{
              width: 56,
              flexShrink: 0,
              fontSize: 16,
              fontWeight: isNowSlot ? 700 : 400,
              color: isNowSlot ? C.accent : C.text3,
              paddingTop: 2,
            }}>
              {slot}
            </div>
            {/* 预约卡片 */}
            <div style={{ flex: 1 }}>
              {slotBookings.length === 0 && (
                <div style={{ fontSize: 16, color: C.text3, opacity: 0.4, paddingTop: 2 }}>--</div>
              )}
              {slotBookings.map(b => (
                <TimelineCard
                  key={b.id}
                  booking={b}
                  isSelected={selectedId === b.id}
                  onSelect={() => onSelect(b.id)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** 右侧详情 + 操作 */
function DetailPanel({
  booking,
  onUpdateStatus,
  onCreateBooking,
}: {
  booking: Booking | null;
  onUpdateStatus: (id: string, status: BookingStatus) => void;
  onCreateBooking: (form: NewBookingForm) => void;
}) {
  const [confirmAction, setConfirmAction] = useState<{ id: string; status: BookingStatus; message: string } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<NewBookingForm>(EMPTY_FORM);

  const handleAction = (status: BookingStatus, message: string) => {
    if (!booking) return;
    setConfirmAction({ id: booking.id, status, message });
  };

  const handleConfirm = () => {
    if (!confirmAction) return;
    vibrate();
    onUpdateStatus(confirmAction.id, confirmAction.status);
    setConfirmAction(null);
  };

  const handleSubmit = () => {
    if (!form.customerName || !form.phone || !form.guestCount) return;
    vibrate();
    onCreateBooking(form);
    setForm(EMPTY_FORM);
    setShowForm(false);
  };

  const updateField = <K extends keyof NewBookingForm>(key: K, value: NewBookingForm[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: 48,
    background: C.bg1,
    color: C.text1,
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    padding: '0 14px',
    fontSize: 16,
    outline: 'none',
    minHeight: 48,
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 16,
    color: C.text3,
    display: 'block',
    marginBottom: 4,
    marginTop: 12,
  };

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: C.bg2,
      borderRadius: 12,
      border: `1px solid ${C.border}`,
      overflow: 'hidden',
    }}>
      {/* 切换按钮 */}
      <div style={{
        display: 'flex',
        borderBottom: `1px solid ${C.border}`,
      }}>
        <button
          onClick={() => setShowForm(false)}
          style={{
            flex: 1, height: 52, background: !showForm ? C.bg3 : 'transparent',
            color: !showForm ? C.accent : C.text3, border: 'none',
            fontSize: 17, fontWeight: 700, cursor: 'pointer',
            borderBottom: !showForm ? `2px solid ${C.accent}` : '2px solid transparent',
          }}
        >
          预约详情
        </button>
        <button
          onClick={() => setShowForm(true)}
          style={{
            flex: 1, height: 52, background: showForm ? C.bg3 : 'transparent',
            color: showForm ? C.accent : C.text3, border: 'none',
            fontSize: 17, fontWeight: 700, cursor: 'pointer',
            borderBottom: showForm ? `2px solid ${C.accent}` : '2px solid transparent',
          }}
        >
          新建预约
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 20, WebkitOverflowScrolling: 'touch' }}>
        {!showForm ? (
          /* 预约详情 */
          booking ? (
            <div>
              <div style={{ fontSize: 24, fontWeight: 800, color: C.text1, marginBottom: 16 }}>
                {booking.customerName}
              </div>
              <div style={{
                display: 'inline-block',
                fontSize: 16, fontWeight: 600,
                color: STATUS_CONFIG[booking.status].color,
                background: STATUS_CONFIG[booking.status].bg,
                borderRadius: 6, padding: '4px 14px', marginBottom: 16,
              }}>
                {STATUS_CONFIG[booking.status].label}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 24px', marginBottom: 24 }}>
                <DetailRow label="手机" value={booking.phone} />
                <DetailRow label="人数" value={`${booking.guestCount}人`} />
                <DetailRow label="日期" value={booking.date} />
                <DetailRow label="时段" value={booking.timeSlot} />
                <DetailRow label="类型" value={ROOM_TYPE_LABEL[booking.roomType]} />
                <DetailRow label="位置" value={booking.roomName} />
              </div>
              {booking.remark && (
                <div style={{ marginBottom: 24 }}>
                  <div style={{ fontSize: 16, color: C.text3, marginBottom: 4 }}>备注</div>
                  <div style={{ fontSize: 17, color: C.text1, background: C.bg3, borderRadius: 8, padding: '10px 14px' }}>
                    {booking.remark}
                  </div>
                </div>
              )}

              {/* 操作按钮 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {booking.status === 'pending' && (
                  <button
                    onClick={() => handleAction('confirmed', `确认 ${booking.customerName} 的预约？`)}
                    style={{
                      height: 56, background: C.blue, color: '#fff',
                      border: 'none', borderRadius: 12, fontSize: 18,
                      fontWeight: 700, cursor: 'pointer', minHeight: 48,
                    }}
                  >
                    确认预约
                  </button>
                )}
                {(booking.status === 'pending' || booking.status === 'confirmed') && (
                  <button
                    onClick={() => handleAction('arrived', `标记 ${booking.customerName} 已到店？`)}
                    style={{
                      height: 56, background: C.green, color: '#fff',
                      border: 'none', borderRadius: 12, fontSize: 18,
                      fontWeight: 700, cursor: 'pointer', minHeight: 48,
                    }}
                  >
                    标记到店
                  </button>
                )}
                {(booking.status === 'pending' || booking.status === 'confirmed') && (
                  <button
                    onClick={() => handleAction('noshow', `标记 ${booking.customerName} 爽约？`)}
                    style={{
                      height: 56, background: C.red, color: '#fff',
                      border: 'none', borderRadius: 12, fontSize: 18,
                      fontWeight: 700, cursor: 'pointer', minHeight: 48,
                    }}
                  >
                    标记爽约
                  </button>
                )}
                {(booking.status === 'pending' || booking.status === 'confirmed') && (
                  <button
                    onClick={() => handleAction('cancelled', `取消 ${booking.customerName} 的预约？`)}
                    style={{
                      height: 56, background: C.grayBg, color: C.text2,
                      border: `1px solid ${C.border}`, borderRadius: 12,
                      fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 48,
                    }}
                  >
                    取消预约
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: C.text3, paddingTop: 80, fontSize: 18 }}>
              点击左侧预约卡片查看详情
            </div>
          )
        ) : (
          /* 新建预约表单 */
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.text1, marginBottom: 8 }}>新建预约</div>
            <label style={labelStyle}>姓名 *</label>
            <input
              value={form.customerName}
              onChange={e => updateField('customerName', e.target.value)}
              placeholder="客人姓名"
              style={inputStyle}
            />
            <label style={labelStyle}>手机号 *</label>
            <input
              type="tel"
              maxLength={11}
              value={form.phone}
              onChange={e => updateField('phone', e.target.value.replace(/\D/g, ''))}
              placeholder="手机号"
              style={inputStyle}
            />
            <label style={labelStyle}>人数 *</label>
            <input
              type="number"
              min={1}
              max={50}
              value={form.guestCount}
              onChange={e => updateField('guestCount', e.target.value)}
              placeholder="用餐人数"
              style={inputStyle}
            />
            <label style={labelStyle}>日期</label>
            <input
              type="date"
              value={form.date}
              onChange={e => updateField('date', e.target.value)}
              style={inputStyle}
            />
            <label style={labelStyle}>时段</label>
            <select
              value={form.timeSlot}
              onChange={e => updateField('timeSlot', e.target.value)}
              style={{ ...inputStyle, appearance: 'auto' }}
            >
              {TIME_SLOTS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <label style={labelStyle}>类型</label>
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              {(['hall', 'private'] as const).map(rt => (
                <button
                  key={rt}
                  onClick={() => updateField('roomType', rt)}
                  style={{
                    flex: 1, height: 48,
                    background: form.roomType === rt ? C.accent : C.bg1,
                    color: form.roomType === rt ? '#fff' : C.text2,
                    border: `1px solid ${form.roomType === rt ? C.accent : C.border}`,
                    borderRadius: 8, fontSize: 16, fontWeight: 600, cursor: 'pointer',
                    minHeight: 48, minWidth: 48,
                  }}
                >
                  {ROOM_TYPE_LABEL[rt]}
                </button>
              ))}
            </div>
            <label style={labelStyle}>包厢/桌位名</label>
            <input
              value={form.roomName}
              onChange={e => updateField('roomName', e.target.value)}
              placeholder="如：牡丹厅 / A3桌"
              style={inputStyle}
            />
            <label style={labelStyle}>备注</label>
            <textarea
              value={form.remark}
              onChange={e => updateField('remark', e.target.value)}
              placeholder="特殊要求、忌口等"
              rows={3}
              style={{
                ...inputStyle,
                height: 'auto',
                padding: '10px 14px',
                resize: 'vertical',
              }}
            />

            <button
              onClick={handleSubmit}
              disabled={!form.customerName || !form.phone || !form.guestCount}
              style={{
                width: '100%',
                height: 56,
                marginTop: 20,
                background: (!form.customerName || !form.phone || !form.guestCount) ? C.grayBg : C.accent,
                color: '#fff',
                border: 'none',
                borderRadius: 12,
                fontSize: 18,
                fontWeight: 700,
                cursor: (!form.customerName || !form.phone || !form.guestCount) ? 'not-allowed' : 'pointer',
                minHeight: 48,
              }}
            >
              确认创建
            </button>
          </div>
        )}
      </div>

      {/* Popconfirm */}
      {confirmAction && (
        <PopConfirm
          message={confirmAction.message}
          onConfirm={handleConfirm}
          onCancel={() => setConfirmAction(null)}
        />
      )}
    </div>
  );
}

/** 详情行 */
function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 16, color: C.text3 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 600, color: C.text1 }}>{value}</div>
    </div>
  );
}

// ─── 主组件 ───

export function BookingPanel() {
  const [bookings, setBookings] = useState<Booking[]>(MOCK_BOOKINGS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const fetchBookings = useCallback(async () => {
    try {
      const data = await apiFetchBookings(todayStr());
      setBookings(data);
    } catch {
      // API不可用，保持当前状态（首次加载用Mock）
    }
  }, []);

  // 10秒自动刷新
  useEffect(() => {
    fetchBookings();
    const timer = setInterval(fetchBookings, 10_000);
    return () => clearInterval(timer);
  }, [fetchBookings]);

  const handleUpdateStatus = useCallback(async (id: string, status: BookingStatus) => {
    try {
      await apiUpdateBookingStatus(id, status);
    } catch {
      // 降级本地状态更新
    }
    setBookings(prev => prev.map(b => b.id === id ? { ...b, status } : b));
  }, []);

  const handleCreateBooking = useCallback(async (form: NewBookingForm) => {
    try {
      const newBooking = await apiCreateBooking({
        customer_name: form.customerName,
        phone: form.phone,
        guest_count: parseInt(form.guestCount, 10),
        date: form.date,
        time_slot: form.timeSlot,
        room_type: form.roomType,
        room_name: form.roomName,
        remark: form.remark,
      });
      setBookings(prev => [...prev, newBooking]);
      setSelectedId(newBooking.id);
    } catch {
      // 降级：本地新增
      const localBooking: Booking = {
        id: `local_${Date.now()}`,
        customerName: form.customerName,
        phone: form.phone,
        guestCount: parseInt(form.guestCount, 10),
        date: form.date,
        timeSlot: form.timeSlot,
        roomType: form.roomType,
        roomName: form.roomName,
        remark: form.remark,
        status: 'pending',
      };
      setBookings(prev => [...prev, localBooking]);
      setSelectedId(localBooking.id);
    }
  }, []);

  const selectedBooking = bookings.find(b => b.id === selectedId) ?? null;

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: C.bg1,
      minWidth: 1024,
      minHeight: 768,
    }}>
      {/* 顶部 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 24px',
        height: 56,
        background: C.bg1,
        borderBottom: `1px solid ${C.border}`,
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 20, fontWeight: 800, color: C.accent }}>预约管理</span>
        <div style={{ display: 'flex', gap: 20, alignItems: 'center', fontSize: 16, color: C.text2 }}>
          <span>
            今日 <span style={{ fontWeight: 700, color: C.blue }}>{bookings.length}</span> 条预约
          </span>
          <span>
            待确认 <span style={{ fontWeight: 700, color: C.orange }}>{bookings.filter(b => b.status === 'pending').length}</span>
          </span>
          <span>
            已到店 <span style={{ fontWeight: 700, color: C.green }}>{bookings.filter(b => b.status === 'arrived').length}</span>
          </span>
        </div>
      </div>
      {/* 主体 */}
      <div style={{
        flex: 1,
        display: 'flex',
        gap: 12,
        padding: 12,
        overflow: 'hidden',
      }}>
        {/* 左侧50% — 时间轴 */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <Timeline bookings={bookings} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        {/* 右侧50% — 详情+操作+新建 */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <DetailPanel
            booking={selectedBooking}
            onUpdateStatus={handleUpdateStatus}
            onCreateBooking={handleCreateBooking}
          />
        </div>
      </div>
    </div>
  );
}
