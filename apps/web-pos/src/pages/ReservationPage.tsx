/**
 * 预订台账 — 双栏布局 + 嵌套子路由
 *
 * 路由结构（定义于 App.tsx）:
 *   /reservations        → ReservationPage（布局）+ ReservationIndex
 *   /reservations/new    → ReservationPage + ReservationForm（新建）
 *   /reservations/:id    → ReservationPage + ReservationDetail
 *   /reservations/:id/edit → ReservationPage + ReservationForm（编辑）
 */
import { useEffect, useState, useCallback } from 'react';
import { Outlet, useNavigate, useParams, useLocation } from 'react-router-dom';
import { useReservationStore } from '../store/reservationStore';
import type { Reservation, ReservationStatus, MealPeriod, TablePref } from '../api/reservationApi';

// ─── StoreId 获取 ──────────────────────────────────────────────────────────────
const STORE_ID: string =
  (window as unknown as Record<string, string>).__STORE_ID__ || '';

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const statusConfig: Record<ReservationStatus, { label: string; color: string }> = {
  pending:    { label: '待确认', color: '#faad14' },
  confirmed:  { label: '已确认', color: '#27AE60' },
  seated:     { label: '已就座', color: '#2D9CDB' },
  cancelled:  { label: '已取消', color: '#EB5757' },
  no_show:    { label: '爽约',    color: '#8C8C8C' },
};

const mealPeriodLabel: Record<MealPeriod, string> = {
  lunch:  '午市 (11:00-14:00)',
  dinner: '晚市 (17:00-21:00)',
};

const tablePrefOptions: { value: TablePref; label: string }[] = [
  { value: '靠窗', label: '靠窗' },
  { value: '包间', label: '包间' },
  { value: '户外', label: '户外' },
  { value: '大厅', label: '大厅' },
  { value: '无所谓', label: '无所谓' },
];

// ─── 样式 ──────────────────────────────────────────────────────────────────────

const C = {
  container: {
    display: 'flex',
    height: '100vh',
    background: '#0B1A20',
    color: 'rgba(255,255,255,0.92)',
    fontFamily: 'Noto Sans SC, sans-serif',
  } as React.CSSProperties,

  leftPanel: {
    width: 400,
    minWidth: 400,
    borderRight: '1px solid rgba(255,255,255,0.08)',
    display: 'flex',
    flexDirection: 'column' as const,
    background: '#0D2029',
  } as React.CSSProperties,

  rightPanel: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column' as const,
    background: '#0B1A20',
  } as React.CSSProperties,

  panelHeader: {
    padding: '16px 16px 12px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
  } as React.CSSProperties,

  panelTitle: {
    fontSize: 18,
    fontWeight: 700,
    margin: 0,
  } as React.CSSProperties,

  card: {
    background: '#112B36',
    borderRadius: 8,
    padding: 12,
    cursor: 'pointer',
    border: '1px solid transparent',
    transition: 'border-color 0.15s, background 0.15s',
  } as React.CSSProperties,

  btn: {
    height: 44,
    minWidth: 44,
    borderRadius: 8,
    border: 'none',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    padding: '0 20px',
  } as React.CSSProperties,

  btnPrimary: {
    background: '#FF6B35',
    color: '#fff',
  } as React.CSSProperties,

  btnSecondary: {
    background: 'rgba(255,255,255,0.08)',
    color: 'rgba(255,255,255,0.85)',
  } as React.CSSProperties,

  btnSuccess: {
    background: '#27AE60',
    color: '#fff',
  } as React.CSSProperties,

  btnDanger: {
    background: '#EB5757',
    color: '#fff',
  } as React.CSSProperties,

  formField: {
    marginBottom: 16,
  } as React.CSSProperties,

  formLabel: {
    fontSize: 13,
    fontWeight: 600,
    color: 'rgba(255,255,255,0.65)',
    marginBottom: 6,
    display: 'block',
  } as React.CSSProperties,

  input: {
    width: '100%',
    height: 44,
    padding: '0 14px',
    borderRadius: 8,
    border: '1px solid rgba(255,255,255,0.12)',
    background: 'rgba(255,255,255,0.06)',
    color: '#fff',
    fontSize: 15,
    outline: 'none',
    boxSizing: 'border-box' as const,
  } as React.CSSProperties,

  select: {
    width: '100%',
    height: 44,
    padding: '0 14px',
    borderRadius: 8,
    border: '1px solid rgba(255,255,255,0.12)',
    background: 'rgba(255,255,255,0.06)',
    color: '#fff',
    fontSize: 15,
    outline: 'none',
    boxSizing: 'border-box' as const,
    appearance: 'none' as const,
  } as React.CSSProperties,

  textarea: {
    width: '100%',
    minHeight: 80,
    padding: 12,
    borderRadius: 8,
    border: '1px solid rgba(255,255,255,0.12)',
    background: 'rgba(255,255,255,0.06)',
    color: '#fff',
    fontSize: 15,
    outline: 'none',
    resize: 'vertical' as const,
    boxSizing: 'border-box' as const,
    fontFamily: 'inherit',
  } as React.CSSProperties,

  filterBar: {
    display: 'flex',
    gap: 8,
    padding: '8px 16px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
  } as React.CSSProperties,

  filterChip: {
    padding: '4px 12px',
    borderRadius: 14,
    fontSize: 12,
    border: 'none',
    cursor: 'pointer',
    fontWeight: 500,
  } as React.CSSProperties,

  groupHeader: {
    fontSize: 11,
    fontWeight: 700,
    color: 'rgba(255,255,255,0.38)',
    padding: '12px 16px 6px',
    textTransform: 'uppercase' as const,
    letterSpacing: 1,
  } as React.CSSProperties,

  tag: {
    padding: '2px 10px',
    borderRadius: 10,
    fontSize: 11,
    fontWeight: 600,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,

  emptyState: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    color: 'rgba(255,255,255,0.25)',
    gap: 12,
  } as React.CSSProperties,

  scrollArea: {
    flex: 1,
    overflowY: 'auto' as const,
  } as React.CSSProperties,
};

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

function formatTime(time: string): string {
  return time.slice(0, 5);
}

function isEditable(s: ReservationStatus): boolean {
  return s === 'pending' || s === 'confirmed';
}

function isActive(s: ReservationStatus): boolean {
  return s !== 'cancelled' && s !== 'no_show';
}

// ─── 左面板：预订列表 ───────────────────────────────────────────────────────────

function ReservationListPanel({
  reservations,
  selectedId,
  filterStatus,
  onFilterChange,
  onSelect,
  onNew,
}: {
  reservations: Reservation[];
  selectedId: string | null;
  filterStatus: ReservationStatus | 'all';
  onFilterChange: (v: ReservationStatus | 'all') => void;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const filtered = filterStatus === 'all'
    ? reservations
    : reservations.filter((r) => r.status === filterStatus);

  const lunchItems = filtered.filter((r) => r.mealPeriod === 'lunch');
  const dinnerItems = filtered.filter((r) => r.mealPeriod === 'dinner');

  return (
    <div style={C.leftPanel}>
      <div style={C.panelHeader}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={C.panelTitle}>预订台账</h3>
          <button style={{ ...C.btn, ...C.btnPrimary }} onClick={onNew}>
            + 新增预订
          </button>
        </div>
      </div>

      {/* 状态筛选 */}
      <div style={C.filterBar}>
        {(['all', 'pending', 'confirmed', 'seated', 'cancelled', 'no_show'] as const).map((s) => {
          const label = s === 'all' ? '全部' : statusConfig[s].label;
          const active = filterStatus === s;
          return (
            <button
              key={s}
              style={{
                ...C.filterChip,
                background: active ? '#FF6B35' : 'rgba(255,255,255,0.06)',
                color: active ? '#fff' : 'rgba(255,255,255,0.65)',
              }}
              onClick={() => onFilterChange(s)}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* 列表 */}
      <div style={C.scrollArea}>
        {filtered.length === 0 ? (
          <div style={{ ...C.emptyState, padding: 40 }}>
            <div style={{ fontSize: 48, opacity: 0.3 }}>📋</div>
            <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.3)' }}>暂无预订记录</div>
          </div>
        ) : (
          <>
            {lunchItems.length > 0 && (
              <>
                <div style={C.groupHeader}>{mealPeriodLabel.lunch}</div>
                {lunchItems.map((r) => (
                  <ReservationRow key={r.id} r={r} active={r.id === selectedId} onSelect={() => onSelect(r.id)} />
                ))}
              </>
            )}
            {dinnerItems.length > 0 && (
              <>
                <div style={C.groupHeader}>{mealPeriodLabel.dinner}</div>
                {dinnerItems.map((r) => (
                  <ReservationRow key={r.id} r={r} active={r.id === selectedId} onSelect={() => onSelect(r.id)} />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ReservationRow({ r, active, onSelect }: { r: Reservation; active: boolean; onSelect: () => void }) {
  const s = statusConfig[r.status];
  return (
    <div
      onClick={onSelect}
      style={{
        ...C.card,
        margin: '4px 12px',
        background: active ? '#1A3340' : '#112B36',
        borderColor: active ? '#FF6B35' : 'transparent',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 2 }}>
            {r.customerName}
            <span style={{ fontWeight: 400, fontSize: 13, color: 'rgba(255,255,255,0.45)', marginLeft: 8 }}>
              {r.guestCount}人
            </span>
          </div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)' }}>
            {formatTime(r.time)} · {r.tableNo || '待分桌'} · {r.contactPhone}
          </div>
        </div>
        <span style={{ ...C.tag, background: s.color + '22', color: s.color }}>
          {s.label}
        </span>
      </div>
    </div>
  );
}

// ─── 右面板：空状态 / 指标 ──────────────────────────────────────────────────────

function ReservationIndex() {
  const reservations = useReservationStore((s) => s.reservations);
  const navigate = useNavigate();

  const total = reservations.length;
  const activeCount = reservations.filter((r) => r.status === 'confirmed').length;
  const todayCount = reservations.filter((r) => {
    const today = new Date();
    const d = r.date;
    return d === `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  }).length;

  return (
    <div style={{ padding: 24 }}>
      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 24 }}>
        {[
          { label: '今日预订', value: todayCount, color: '#FF6B35' },
          { label: '待接待', value: activeCount, color: '#27AE60' },
          { label: '本月累计', value: total, color: '#2D9CDB' },
        ].map((stat) => (
          <div key={stat.label} style={{ background: '#112B36', borderRadius: 10, padding: 20 }}>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', marginBottom: 8 }}>{stat.label}</div>
            <div style={{ fontSize: 36, fontWeight: 700, color: stat.color }}>{stat.value}</div>
          </div>
        ))}
      </div>

      {/* 操作引导 */}
      <div style={{
        background: 'rgba(255,107,53,0.06)',
        border: '1px solid rgba(255,107,53,0.2)',
        borderRadius: 10,
        padding: 24,
        textAlign: 'center',
      }}>
        <div style={{ fontSize: 15, color: 'rgba(255,255,255,0.65)', marginBottom: 16 }}>
          请从左侧选择预订查看详情，或创建新的预订记录
        </div>
        <button
          style={{ ...C.btn, ...C.btnPrimary, fontSize: 15, padding: '0 32px' }}
          onClick={() => navigate('/reservations/new')}
        >
          + 新建预订
        </button>
      </div>
    </div>
  );
}

// ─── 右面板：预订详情 ───────────────────────────────────────────────────────────

function ReservationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const reservations = useReservationStore((s) => s.reservations);
  const { cancel, confirmArrival } = useReservationStore();
  const [showCancel, setShowCancel] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [showSeat, setShowSeat] = useState(false);
  const [tableNo, setTableNo] = useState('');

  const r = reservations.find((x) => x.id === id);

  if (!r) {
    return (
      <div style={C.emptyState}>
        <div style={{ fontSize: 48 }}>🔍</div>
        <div style={{ fontSize: 14 }}>未找到该预订</div>
        <button style={{ ...C.btn, ...C.btnSecondary }} onClick={() => navigate('/reservations')}>返回列表</button>
      </div>
    );
  }

  const s = statusConfig[r.status];
  const editable = isEditable(r.status);

  const handleCancel = async () => {
    if (!r) return;
    await cancel(r.id, cancelReason || undefined);
    setShowCancel(false);
    setCancelReason('');
  };

  const handleSeat = async () => {
    if (!r || !tableNo) return;
    await confirmArrival(r.id, tableNo);
    setShowSeat(false);
    setTableNo('');
  };

  return (
    <div style={{ padding: 24, overflowY: 'auto', height: '100%' }}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
            <h2 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>{r.customerName}</h2>
            <span style={{ ...C.tag, background: s.color + '22', color: s.color, fontSize: 13, padding: '3px 14px' }}>
              {s.label}
            </span>
          </div>
          <div style={{ color: 'rgba(255,255,255,0.45)', fontSize: 14 }}>预订号: {r.id.slice(0, 8)}</div>
        </div>
        <button style={{ ...C.btn, ...C.btnSecondary }} onClick={() => navigate('/reservations')}>
          ← 返回
        </button>
      </div>

      {/* 信息卡片 */}
      <div style={{ background: '#112B36', borderRadius: 10, padding: 20, marginBottom: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {[
            { label: '联系电话', value: r.contactPhone },
            { label: '用餐人数', value: `${r.guestCount} 位` },
            { label: '用餐日期', value: r.date },
            { label: '用餐时间', value: `${formatTime(r.time)}（${r.mealPeriod === 'lunch' ? '午市' : '晚市'}）` },
            { label: '桌台号', value: r.tableNo || '待分桌' },
            { label: '桌台偏好', value: r.tablePref || '未指定' },
          ].map((item) => (
            <div key={item.label}>
              <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.38)', marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{item.value}</div>
            </div>
          ))}
        </div>
        {r.notes && (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.38)', marginBottom: 4 }}>备注</div>
            <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.65)' }}>{r.notes}</div>
          </div>
        )}
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.38)', marginBottom: 4 }}>创建时间</div>
          <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.45)' }}>{r.createdAt}</div>
        </div>
      </div>

      {/* 操作按钮 */}
      {isActive(r.status) && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {editable && (
            <button
              style={{ ...C.btn, ...C.btnPrimary }}
              onClick={() => navigate(`/reservations/${r.id}/edit`)}
            >
              编辑
            </button>
          )}
          {r.status === 'confirmed' && (
            <button
              style={{ ...C.btn, ...C.btnSuccess }}
              onClick={() => { setTableNo(r.tableNo || ''); setShowSeat(true); }}
            >
              确认到店
            </button>
          )}
          {editable && (
            <button
              style={{ ...C.btn, ...C.btnDanger }}
              onClick={() => setShowCancel(true)}
            >
              取消预订
            </button>
          )}
        </div>
      )}

      {/* 取消弹窗 */}
      {showCancel && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{ background: '#112B36', borderRadius: 12, padding: 24, width: 360 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>取消预订</h3>
            <div style={C.formField}>
              <label style={C.formLabel}>取消原因（可选）</label>
              <input
                style={C.input}
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
                placeholder="请输入取消原因"
              />
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button style={{ ...C.btn, ...C.btnDanger, flex: 1 }} onClick={handleCancel}>确认取消</button>
              <button style={{ ...C.btn, ...C.btnSecondary, flex: 1 }} onClick={() => setShowCancel(false)}>返回</button>
            </div>
          </div>
        </div>
      )}

      {/* 到店弹窗 */}
      {showSeat && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{ background: '#112B36', borderRadius: 12, padding: 24, width: 360 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>确认到店</h3>
            <div style={C.formField}>
              <label style={C.formLabel}>桌台号</label>
              <input
                style={C.input}
                value={tableNo}
                onChange={(e) => setTableNo(e.target.value)}
                placeholder="请输入桌号，如 A01"
              />
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button style={{ ...C.btn, ...C.btnSuccess, flex: 1 }} onClick={handleSeat} disabled={!tableNo}>确认入座</button>
              <button style={{ ...C.btn, ...C.btnSecondary, flex: 1 }} onClick={() => setShowSeat(false)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 右面板：新建/编辑表单 ──────────────────────────────────────────────────────

interface FormData {
  customerName: string;
  contactPhone: string;
  guestCount: number;
  date: string;
  time: string;
  mealPeriod: MealPeriod;
  tablePref: TablePref | '';
  tableNo: string;
  notes: string;
}

const emptyForm: FormData = {
  customerName: '',
  contactPhone: '',
  guestCount: 2,
  date: '',
  time: '',
  mealPeriod: 'dinner',
  tablePref: '',
  tableNo: '',
  notes: '',
};

function ReservationForm() {
  const { id } = useParams();
  const navigate = useNavigate();
  const reservations = useReservationStore((s) => s.reservations);
  const { create, update: updateReservation } = useReservationStore();
  const isEdit = !!id;

  const existing = isEdit ? reservations.find((r) => r.id === id) : null;

  const [form, setForm] = useState<FormData>(() => {
    if (existing) {
      return {
        customerName: existing.customerName,
        contactPhone: existing.contactPhone,
        guestCount: existing.guestCount,
        date: existing.date,
        time: existing.time,
        mealPeriod: existing.mealPeriod,
        tablePref: existing.tablePref as TablePref | '',
        tableNo: existing.tableNo,
        notes: existing.notes,
      };
    }
    return { ...emptyForm };
  });
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof FormData, string>>>({});

  const update = (field: keyof FormData, value: string | number) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const validate = (): boolean => {
    const e: Partial<Record<keyof FormData, string>> = {};
    if (!form.customerName.trim()) e.customerName = '请输入顾客姓名';
    if (!form.contactPhone.trim()) e.contactPhone = '请输入联系电话';
    else if (!/^1\d{10}$/.test(form.contactPhone.trim())) e.contactPhone = '请输入有效的手机号';
    if (form.guestCount < 1) e.guestCount = '人数至少为1';
    if (!form.date) e.date = '请选择日期';
    if (!form.time) e.time = '请选择时间';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    setSaving(true);

    if (isEdit && id) {
      await updateReservation(id, {
        customerName: form.customerName,
        contactPhone: form.contactPhone,
        guestCount: form.guestCount,
        date: form.date,
        time: form.time,
        mealPeriod: form.mealPeriod,
        tablePref: form.tablePref || undefined,
        tableNo: form.tableNo || undefined,
        notes: form.notes || undefined,
      });
    } else {
      await create(STORE_ID, {
        customerName: form.customerName,
        contactPhone: form.contactPhone,
        guestCount: form.guestCount,
        date: form.date,
        time: form.time,
        mealPeriod: form.mealPeriod,
        tablePref: form.tablePref || undefined,
        tableNo: form.tableNo || undefined,
        notes: form.notes || undefined,
      });
    }
    setSaving(false);
    navigate(isEdit ? `/reservations/${id}` : '/reservations');
  };

  return (
    <div style={{ padding: 24, overflowY: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
          {isEdit ? '修改预订' : '新建预订'}
        </h2>
        <button style={{ ...C.btn, ...C.btnSecondary }} onClick={() => navigate(isEdit ? `/reservations/${id}` : '/reservations')}>
          取消
        </button>
      </div>

      <div style={{ background: '#112B36', borderRadius: 10, padding: 24, maxWidth: 480 }}>
        {/* 顾客姓名 */}
        <div style={C.formField}>
          <label style={C.formLabel}>顾客姓名 *</label>
          <input
            style={{ ...C.input, borderColor: errors.customerName ? '#EB5757' : 'rgba(255,255,255,0.12)' }}
            value={form.customerName}
            onChange={(e) => update('customerName', e.target.value)}
            placeholder="请输入姓名"
          />
          {errors.customerName && <div style={{ fontSize: 12, color: '#EB5757', marginTop: 4 }}>{errors.customerName}</div>}
        </div>

        {/* 联系电话 */}
        <div style={C.formField}>
          <label style={C.formLabel}>联系电话 *</label>
          <input
            style={{ ...C.input, borderColor: errors.contactPhone ? '#EB5757' : 'rgba(255,255,255,0.12)' }}
            value={form.contactPhone}
            onChange={(e) => update('contactPhone', e.target.value)}
            placeholder="请输入手机号"
            type="tel"
          />
          {errors.contactPhone && <div style={{ fontSize: 12, color: '#EB5757', marginTop: 4 }}>{errors.contactPhone}</div>}
        </div>

        {/* 人数 */}
        <div style={C.formField}>
          <label style={C.formLabel}>用餐人数 *</label>
          <input
            style={{ ...C.input, borderColor: errors.guestCount ? '#EB5757' : 'rgba(255,255,255,0.12)', width: 120 }}
            value={form.guestCount}
            onChange={(e) => update('guestCount', Math.max(1, parseInt(e.target.value) || 1))}
            type="number"
            min={1}
          />
          {errors.guestCount && <div style={{ fontSize: 12, color: '#EB5757', marginTop: 4 }}>{errors.guestCount}</div>}
        </div>

        {/* 日期 + 时间 */}
        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ ...C.formField, flex: 1 }}>
            <label style={C.formLabel}>日期 *</label>
            <input
              style={{ ...C.input, borderColor: errors.date ? '#EB5757' : 'rgba(255,255,255,0.12)' }}
              value={form.date}
              onChange={(e) => update('date', e.target.value)}
              type="date"
            />
            {errors.date && <div style={{ fontSize: 12, color: '#EB5757', marginTop: 4 }}>{errors.date}</div>}
          </div>
          <div style={{ ...C.formField, flex: 1 }}>
            <label style={C.formLabel}>时间 *</label>
            <input
              style={{ ...C.input, borderColor: errors.time ? '#EB5757' : 'rgba(255,255,255,0.12)' }}
              value={form.time}
              onChange={(e) => update('time', e.target.value)}
              type="time"
            />
            {errors.time && <div style={{ fontSize: 12, color: '#EB5757', marginTop: 4 }}>{errors.time}</div>}
          </div>
        </div>

        {/* 用餐时段 */}
        <div style={C.formField}>
          <label style={C.formLabel}>用餐时段 *</label>
          <select
            style={C.select}
            value={form.mealPeriod}
            onChange={(e) => update('mealPeriod', e.target.value)}
          >
            <option value="lunch">午市</option>
            <option value="dinner">晚市</option>
          </select>
        </div>

        {/* 桌台偏好 */}
        <div style={C.formField}>
          <label style={C.formLabel}>桌台偏好</label>
          <select
            style={C.select}
            value={form.tablePref}
            onChange={(e) => update('tablePref', e.target.value)}
          >
            <option value="">未指定</option>
            {tablePrefOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        {/* 桌台号 */}
        <div style={C.formField}>
          <label style={C.formLabel}>指定桌台</label>
          <input
            style={C.input}
            value={form.tableNo}
            onChange={(e) => update('tableNo', e.target.value)}
            placeholder="如 A01（留空则由系统分配）"
          />
        </div>

        {/* 备注 */}
        <div style={C.formField}>
          <label style={C.formLabel}>备注</label>
          <textarea
            style={C.textarea}
            value={form.notes}
            onChange={(e) => update('notes', e.target.value)}
            placeholder="特殊要求、过敏信息等"
          />
        </div>

        {/* 提交 */}
        <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
          <button
            style={{ ...C.btn, ...C.btnPrimary, flex: 1, height: 48, fontSize: 16 }}
            onClick={handleSubmit}
            disabled={saving}
          >
            {saving ? '保存中...' : isEdit ? '保存修改' : '创建预订'}
          </button>
          <button
            style={{ ...C.btn, ...C.btnSecondary, flex: 1, height: 48 }}
            onClick={() => navigate(isEdit ? `/reservations/${id}` : '/reservations')}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 主布局（两栏 + Outlet） ────────────────────────────────────────────────────

export function ReservationPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const reservations = useReservationStore((s) => s.reservations);
  const loading = useReservationStore((s) => s.loading);
  const fetchList = useReservationStore((s) => s.fetchList);
  const [filterStatus, setFilterStatus] = useState<ReservationStatus | 'all'>('all');

  // 从 URL 中提取当前选中的预订 ID
  const match = location.pathname.match(/\/reservations\/([^/]+)/);
  const selectedId = match && match[1] !== 'new' ? match[1] : null;

  useEffect(() => {
    fetchList(STORE_ID);
  }, [fetchList]);

  const handleSelect = useCallback((id: string) => {
    navigate(`/reservations/${id}`);
  }, [navigate]);

  const handleNew = useCallback(() => {
    navigate('/reservations/new');
  }, [navigate]);

  return (
    <div style={C.container}>
      <ReservationListPanel
        reservations={reservations}
        selectedId={selectedId}
        filterStatus={filterStatus}
        onFilterChange={setFilterStatus}
        onSelect={handleSelect}
        onNew={handleNew}
      />
      <div style={C.rightPanel}>
        {loading && reservations.length === 0 ? (
          <div style={C.emptyState}>
            <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.45)' }}>加载中...</div>
          </div>
        ) : (
          <Outlet />
        )}
      </div>
    </div>
  );
}

// ─── 子路由组件导出 ─────────────────────────────────────────────────────────────

export { ReservationIndex as ReservationIndexView };
export { ReservationDetail as ReservationDetailView };
export { ReservationForm as ReservationFormView };
