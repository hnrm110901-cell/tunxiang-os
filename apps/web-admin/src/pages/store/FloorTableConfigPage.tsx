/**
 * 桌台配置页 — /hq/floor/tables
 * P0-03: 总部级楼层/区域/桌台CRUD + 平面图预览
 * API: GET /api/v1/trade/tables?store_id=XXX
 *      POST /api/v1/trade/tables
 *      PATCH /api/v1/trade/tables/{id}
 */
import { useEffect, useState, useCallback } from 'react';
import { apiGet, apiPost, apiPatch } from '../../api/client';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

type TableType = 'small' | 'medium' | 'large' | 'private_room' | 'vip';
type TableStatus = 'idle' | 'reserved' | 'opened' | 'ordered' | 'serving' | 'dining' | 'pending_payment' | 'cleaning';

interface AreaItem { id: string; name: string; store_id: string; area_type: string; }

interface TableItem {
  id: string;
  store_id: string;
  area_id: string;
  code: string;
  name: string | null;
  table_type: TableType;
  seat_capacity: number;
  min_capacity: number | null;
  max_capacity: number | null;
  status: TableStatus;
  is_private_room: boolean;
  is_vip_room: boolean;
  supports_reservation: boolean;
  supports_queue: boolean;
  supports_merge: boolean;
  low_consumption_amount: number | null;
  cleaning_sla_minutes: number | null;
  turnover_target_minutes: number | null;
  enabled: boolean;
  x: number | null;
  y: number | null;
  width: number | null;
  height: number | null;
  shape: string | null;
}

interface StoreOption { id: string; name: string; }

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const TABLE_TYPE_LABELS: Record<TableType, string> = {
  small: '小桌', medium: '中桌', large: '大桌', private_room: '包间', vip: 'VIP',
};

const TABLE_TYPE_COLORS: Record<TableType, { color: string; bg: string }> = {
  small:        { color: '#0F6E56', bg: '#0F6E5618' },
  medium:       { color: '#185FA5', bg: '#185FA518' },
  large:        { color: '#FF6B35', bg: '#FF6B3518' },
  private_room: { color: '#8B5CF6', bg: '#8B5CF618' },
  vip:          { color: '#D97706', bg: '#D9770618' },
};

// ─── 降级数据 ──────────────────────────────────────────────────────────────────

const FALLBACK_STORES: StoreOption[] = [
  { id: 'demo_store_01', name: '徐记海鲜（五一广场店）' },
  { id: 'demo_store_02', name: '徐记海鲜（梅溪湖店）' },
];

const FALLBACK_AREAS: AreaItem[] = [
  { id: 'area_main', name: '大厅', store_id: 'demo_store_01', area_type: 'hall' },
  { id: 'area_vip', name: '包厢区', store_id: 'demo_store_01', area_type: 'private' },
  { id: 'area_bar', name: '吧台区', store_id: 'demo_store_01', area_type: 'bar' },
];

const FALLBACK_TABLES: TableItem[] = [
  { id: 't01', store_id: 'demo_store_01', area_id: 'area_main', code: 'A01', name: null, table_type: 'small', seat_capacity: 2, min_capacity: 1, max_capacity: 4, status: 'idle', is_private_room: false, is_vip_room: false, supports_reservation: true, supports_queue: true, supports_merge: true, low_consumption_amount: null, cleaning_sla_minutes: 5, turnover_target_minutes: 90, enabled: true, x: 0, y: 0, width: 80, height: 80, shape: 'square' },
  { id: 't02', store_id: 'demo_store_01', area_id: 'area_main', code: 'A02', name: null, table_type: 'medium', seat_capacity: 4, min_capacity: 2, max_capacity: 6, status: 'idle', is_private_room: false, is_vip_room: false, supports_reservation: true, supports_queue: true, supports_merge: true, low_consumption_amount: null, cleaning_sla_minutes: 5, turnover_target_minutes: 90, enabled: true, x: 120, y: 0, width: 100, height: 80, shape: 'rectangle' },
  { id: 't03', store_id: 'demo_store_01', area_id: 'area_main', code: 'A03', name: null, table_type: 'large', seat_capacity: 8, min_capacity: 4, max_capacity: 10, status: 'idle', is_private_room: false, is_vip_room: false, supports_reservation: true, supports_queue: true, supports_merge: false, low_consumption_amount: null, cleaning_sla_minutes: 8, turnover_target_minutes: 120, enabled: true, x: 260, y: 0, width: 120, height: 100, shape: 'round' },
  { id: 't04', store_id: 'demo_store_01', area_id: 'area_vip', code: 'V01', name: '牡丹厅', table_type: 'private_room', seat_capacity: 12, min_capacity: 6, max_capacity: 16, status: 'idle', is_private_room: true, is_vip_room: true, supports_reservation: true, supports_queue: false, supports_merge: false, low_consumption_amount: 200000, cleaning_sla_minutes: 15, turnover_target_minutes: 150, enabled: true, x: 0, y: 0, width: 160, height: 120, shape: 'rectangle' },
  { id: 't05', store_id: 'demo_store_01', area_id: 'area_vip', code: 'V02', name: '芙蓉厅', table_type: 'vip', seat_capacity: 20, min_capacity: 10, max_capacity: 24, status: 'idle', is_private_room: true, is_vip_room: true, supports_reservation: true, supports_queue: false, supports_merge: false, low_consumption_amount: 500000, cleaning_sla_minutes: 20, turnover_target_minutes: 180, enabled: true, x: 200, y: 0, width: 180, height: 140, shape: 'rectangle' },
];

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export function FloorTableConfigPage() {
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState('');
  const [areas, setAreas] = useState<AreaItem[]>([]);
  const [selectedAreaId, setSelectedAreaId] = useState('');
  const [tables, setTables] = useState<TableItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [showForm, setShowForm] = useState(false);
  const [editingTable, setEditingTable] = useState<TableItem | null>(null);

  // ─── 表单状态 ──────────────────────────────────────────────────────────────
  const [formCode, setFormCode] = useState('');
  const [formName, setFormName] = useState('');
  const [formType, setFormType] = useState<TableType>('small');
  const [formCapacity, setFormCapacity] = useState(4);
  const [formMinCap, setFormMinCap] = useState(1);
  const [formMaxCap, setFormMaxCap] = useState(6);
  const [formPrivate, setFormPrivate] = useState(false);
  const [formVip, setFormVip] = useState(false);
  const [formReservation, setFormReservation] = useState(true);
  const [formQueue, setFormQueue] = useState(true);
  const [formMerge, setFormMerge] = useState(true);
  const [formCleanSla, setFormCleanSla] = useState(5);
  const [formTurnover, setFormTurnover] = useState(90);
  const [formMinConsumption, setFormMinConsumption] = useState(0);

  // ─── 加载门店列表 ──────────────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const res = await apiGet<{ items: StoreOption[] }>('/api/v1/trade/stores?page=1&size=100');
        if (res.items?.length) { setStores(res.items); setSelectedStoreId(res.items[0].id); }
        else { setStores(FALLBACK_STORES); setSelectedStoreId(FALLBACK_STORES[0].id); }
      } catch { setStores(FALLBACK_STORES); setSelectedStoreId(FALLBACK_STORES[0].id); }
    })();
  }, []);

  // ─── 加载区域和桌台 ────────────────────────────────────────────────────────
  const loadTablesAndAreas = useCallback(async () => {
    if (!selectedStoreId) return;
    setLoading(true);
    try {
      const [areaRes, tableRes] = await Promise.all([
        apiGet<{ items: AreaItem[] }>(`/api/v1/trade/areas?store_id=${selectedStoreId}`),
        apiGet<{ items: TableItem[] }>(`/api/v1/trade/tables?store_id=${selectedStoreId}`),
      ]);
      const a = areaRes.items?.length ? areaRes.items : FALLBACK_AREAS;
      const t = tableRes.items?.length ? tableRes.items : FALLBACK_TABLES;
      setAreas(a); setTables(t);
      if (a.length && !selectedAreaId) setSelectedAreaId(a[0].id);
    } catch {
      setAreas(FALLBACK_AREAS); setTables(FALLBACK_TABLES);
      if (!selectedAreaId) setSelectedAreaId(FALLBACK_AREAS[0].id);
    }
    setLoading(false);
  }, [selectedStoreId, selectedAreaId]);

  useEffect(() => { loadTablesAndAreas(); }, [loadTablesAndAreas]);

  // ─── 过滤当前区域桌台 ──────────────────────────────────────────────────────
  const filteredTables = tables.filter((t) => !selectedAreaId || t.area_id === selectedAreaId);

  // ─── 统计 ──────────────────────────────────────────────────────────────────
  const totalTables = filteredTables.length;
  const totalSeats = filteredTables.reduce((s, t) => s + t.seat_capacity, 0);
  const privateCount = filteredTables.filter((t) => t.is_private_room).length;
  const vipCount = filteredTables.filter((t) => t.is_vip_room).length;

  // ─── 表单操作 ──────────────────────────────────────────────────────────────
  const openCreateForm = () => {
    setEditingTable(null);
    setFormCode(''); setFormName(''); setFormType('small'); setFormCapacity(4);
    setFormMinCap(1); setFormMaxCap(6); setFormPrivate(false); setFormVip(false);
    setFormReservation(true); setFormQueue(true); setFormMerge(true);
    setFormCleanSla(5); setFormTurnover(90); setFormMinConsumption(0);
    setShowForm(true);
  };

  const openEditForm = (t: TableItem) => {
    setEditingTable(t);
    setFormCode(t.code); setFormName(t.name || ''); setFormType(t.table_type);
    setFormCapacity(t.seat_capacity); setFormMinCap(t.min_capacity || 1);
    setFormMaxCap(t.max_capacity || t.seat_capacity + 2);
    setFormPrivate(t.is_private_room); setFormVip(t.is_vip_room);
    setFormReservation(t.supports_reservation); setFormQueue(t.supports_queue);
    setFormMerge(t.supports_merge); setFormCleanSla(t.cleaning_sla_minutes || 5);
    setFormTurnover(t.turnover_target_minutes || 90);
    setFormMinConsumption(t.low_consumption_amount ? t.low_consumption_amount / 100 : 0);
    setShowForm(true);
  };

  const handleSubmit = async () => {
    const body = {
      store_id: selectedStoreId,
      area_id: selectedAreaId,
      code: formCode,
      name: formName || null,
      table_type: formType,
      seat_capacity: formCapacity,
      min_capacity: formMinCap,
      max_capacity: formMaxCap,
      is_private_room: formPrivate,
      is_vip_room: formVip,
      supports_reservation: formReservation,
      supports_queue: formQueue,
      supports_merge: formMerge,
      cleaning_sla_minutes: formCleanSla,
      turnover_target_minutes: formTurnover,
      low_consumption_amount: formMinConsumption > 0 ? Math.round(formMinConsumption * 100) : null,
    };
    try {
      if (editingTable) {
        await apiPatch(`/api/v1/trade/tables/${editingTable.id}`, body);
      } else {
        await apiPost('/api/v1/trade/tables', body);
      }
      setShowForm(false);
      loadTablesAndAreas();
    } catch (err) {
      console.error('保存桌台失败', err);
    }
  };

  // ─── 样式常量 ──────────────────────────────────────────────────────────────
  const brand = '#FF6B35';
  const bg0 = '#0B1A20';
  const bg1 = '#112228';
  const bg2 = '#1a2a33';
  const text1 = '#E8E6E1';
  const text2 = '#999';
  const text3 = '#666';
  const cardRadius = 12;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, color: text1 }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>桌台配置</h2>
          <p style={{ fontSize: 13, color: text2, margin: '4px 0 0' }}>配置楼层、区域、桌台、包间与翻台参数</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select
            value={selectedStoreId}
            onChange={(e) => { setSelectedStoreId(e.target.value); setSelectedAreaId(''); }}
            style={{ padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg1, color: text1, fontSize: 13 }}
          >
            {stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button onClick={openCreateForm} style={{ padding: '8px 16px', borderRadius: 8, border: 'none', background: brand, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
            + 新建桌台
          </button>
        </div>
      </div>

      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {[
          { label: '桌台总数', value: totalTables, icon: '🪑' },
          { label: '总座位数', value: totalSeats, icon: '👤' },
          { label: '包间', value: privateCount, icon: '🚪' },
          { label: 'VIP', value: vipCount, icon: '⭐' },
        ].map((s) => (
          <div key={s.label} style={{ background: bg1, borderRadius: cardRadius, padding: '16px 20px', border: `1px solid ${bg2}` }}>
            <div style={{ fontSize: 11, color: text2, marginBottom: 4 }}>{s.icon} {s.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* 区域Tabs + 视图切换 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          <button
            onClick={() => setSelectedAreaId('')}
            style={{ padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: !selectedAreaId ? 600 : 400, background: !selectedAreaId ? `${brand}22` : 'transparent', color: !selectedAreaId ? brand : text2 }}
          >
            全部
          </button>
          {areas.map((a) => (
            <button
              key={a.id}
              onClick={() => setSelectedAreaId(a.id)}
              style={{ padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: selectedAreaId === a.id ? 600 : 400, background: selectedAreaId === a.id ? `${brand}22` : 'transparent', color: selectedAreaId === a.id ? brand : text2 }}
            >
              {a.name}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['grid', 'list'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              style={{ padding: '6px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, background: viewMode === m ? `${brand}22` : 'transparent', color: viewMode === m ? brand : text2 }}
            >
              {m === 'grid' ? '网格' : '列表'}
            </button>
          ))}
        </div>
      </div>

      {/* 桌台网格视图 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: text2 }}>加载中...</div>
      ) : viewMode === 'grid' ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
          {filteredTables.map((t) => {
            const tc = TABLE_TYPE_COLORS[t.table_type] || TABLE_TYPE_COLORS.small;
            return (
              <div
                key={t.id}
                onClick={() => openEditForm(t)}
                style={{ background: bg1, borderRadius: cardRadius, padding: 16, border: `1px solid ${bg2}`, cursor: 'pointer', transition: 'border-color .15s' }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = brand)}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = bg2)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 16, fontWeight: 700 }}>{t.code}</span>
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: tc.bg, color: tc.color }}>{TABLE_TYPE_LABELS[t.table_type]}</span>
                </div>
                {t.name && <div style={{ fontSize: 12, color: text2, marginBottom: 6 }}>{t.name}</div>}
                <div style={{ display: 'flex', gap: 12, fontSize: 12, color: text2 }}>
                  <span>👤 {t.seat_capacity}座</span>
                  <span>🕐 {t.turnover_target_minutes || '—'}分钟</span>
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                  {t.is_private_room && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#8B5CF618', color: '#8B5CF6' }}>包间</span>}
                  {t.is_vip_room && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#D9770618', color: '#D97706' }}>VIP</span>}
                  {t.supports_reservation && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#185FA518', color: '#185FA5' }}>可预定</span>}
                  {t.supports_merge && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#0F6E5618', color: '#0F6E56' }}>可并台</span>}
                  {!t.enabled && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 3, background: '#A32D2D18', color: '#A32D2D' }}>已停用</span>}
                </div>
                {t.low_consumption_amount != null && t.low_consumption_amount > 0 && (
                  <div style={{ marginTop: 6, fontSize: 11, color: text3 }}>最低消费 ¥{(t.low_consumption_amount / 100).toLocaleString()}</div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        /* 列表视图 */
        <div style={{ background: bg1, borderRadius: cardRadius, border: `1px solid ${bg2}`, overflow: 'hidden' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '80px 100px 1fr 80px 80px 120px 100px', padding: '10px 16px', background: bg2, fontSize: 11, color: text2, fontWeight: 600 }}>
            <span>桌号</span><span>类型</span><span>名称</span><span>座位</span><span>翻台(分)</span><span>属性</span><span>状态</span>
          </div>
          {filteredTables.map((t) => {
            const tc = TABLE_TYPE_COLORS[t.table_type] || TABLE_TYPE_COLORS.small;
            return (
              <div key={t.id} onClick={() => openEditForm(t)} style={{ display: 'grid', gridTemplateColumns: '80px 100px 1fr 80px 80px 120px 100px', padding: '10px 16px', borderBottom: `1px solid ${bg2}`, fontSize: 13, cursor: 'pointer', alignItems: 'center' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = `${bg2}88`)}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <span style={{ fontWeight: 600 }}>{t.code}</span>
                <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 4, background: tc.bg, color: tc.color, width: 'fit-content' }}>{TABLE_TYPE_LABELS[t.table_type]}</span>
                <span style={{ color: text2 }}>{t.name || '—'}</span>
                <span>{t.seat_capacity}</span>
                <span>{t.turnover_target_minutes || '—'}</span>
                <span style={{ display: 'flex', gap: 4 }}>
                  {t.is_private_room && <span style={{ fontSize: 9, padding: '1px 4px', borderRadius: 2, background: '#8B5CF618', color: '#8B5CF6' }}>包</span>}
                  {t.is_vip_room && <span style={{ fontSize: 9, padding: '1px 4px', borderRadius: 2, background: '#D9770618', color: '#D97706' }}>V</span>}
                  {t.supports_reservation && <span style={{ fontSize: 9, padding: '1px 4px', borderRadius: 2, background: '#185FA518', color: '#185FA5' }}>预</span>}
                </span>
                <span style={{ color: t.enabled ? '#0F6E56' : '#A32D2D', fontSize: 12 }}>{t.enabled ? '启用' : '停用'}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* 新建/编辑弹窗 */}
      {showForm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setShowForm(false)}>
          <div style={{ background: bg1, borderRadius: 16, padding: 28, width: 480, maxHeight: '80vh', overflow: 'auto', border: `1px solid ${bg2}` }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: 18, fontWeight: 700, margin: '0 0 20px' }}>{editingTable ? '编辑桌台' : '新建桌台'}</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {/* 桌号 */}
              <label style={{ fontSize: 12, color: text2 }}>
                桌号 *
                <input value={formCode} onChange={(e) => setFormCode(e.target.value)} placeholder="如 A01" style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
              </label>
              {/* 名称 */}
              <label style={{ fontSize: 12, color: text2 }}>
                名称（包间/VIP可填）
                <input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="如 牡丹厅" style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
              </label>
              {/* 桌型 */}
              <label style={{ fontSize: 12, color: text2 }}>
                桌型 *
                <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                  {(Object.keys(TABLE_TYPE_LABELS) as TableType[]).map((tt) => (
                    <button key={tt} onClick={() => setFormType(tt)} style={{ padding: '6px 14px', borderRadius: 6, border: `1px solid ${formType === tt ? brand : bg2}`, background: formType === tt ? `${brand}22` : 'transparent', color: formType === tt ? brand : text2, fontSize: 13, cursor: 'pointer' }}>
                      {TABLE_TYPE_LABELS[tt]}
                    </button>
                  ))}
                </div>
              </label>
              {/* 座位数 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                <label style={{ fontSize: 12, color: text2 }}>
                  标准座位 *
                  <input type="number" value={formCapacity} onChange={(e) => setFormCapacity(+e.target.value)} min={1} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                </label>
                <label style={{ fontSize: 12, color: text2 }}>
                  最小人数
                  <input type="number" value={formMinCap} onChange={(e) => setFormMinCap(+e.target.value)} min={1} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                </label>
                <label style={{ fontSize: 12, color: text2 }}>
                  最大人数
                  <input type="number" value={formMaxCap} onChange={(e) => setFormMaxCap(+e.target.value)} min={1} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                </label>
              </div>
              {/* 经营属性 */}
              <div style={{ fontSize: 12, color: text2 }}>
                经营属性
                <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
                  {[
                    { label: '包间', val: formPrivate, set: setFormPrivate },
                    { label: 'VIP', val: formVip, set: setFormVip },
                    { label: '可预定', val: formReservation, set: setFormReservation },
                    { label: '可排队', val: formQueue, set: setFormQueue },
                    { label: '可并台', val: formMerge, set: setFormMerge },
                  ].map((f) => (
                    <label key={f.label} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: 13, color: text1 }}>
                      <input type="checkbox" checked={f.val} onChange={() => f.set(!f.val)} style={{ accentColor: brand }} />
                      {f.label}
                    </label>
                  ))}
                </div>
              </div>
              {/* 运营参数 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                <label style={{ fontSize: 12, color: text2 }}>
                  清台SLA(分)
                  <input type="number" value={formCleanSla} onChange={(e) => setFormCleanSla(+e.target.value)} min={1} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                </label>
                <label style={{ fontSize: 12, color: text2 }}>
                  翻台目标(分)
                  <input type="number" value={formTurnover} onChange={(e) => setFormTurnover(+e.target.value)} min={1} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                </label>
                <label style={{ fontSize: 12, color: text2 }}>
                  最低消费(元)
                  <input type="number" value={formMinConsumption} onChange={(e) => setFormMinConsumption(+e.target.value)} min={0} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                </label>
              </div>
              {/* 操作按钮 */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                <button onClick={() => setShowForm(false)} style={{ padding: '8px 20px', borderRadius: 8, border: `1px solid ${bg2}`, background: 'transparent', color: text2, fontSize: 13, cursor: 'pointer' }}>取消</button>
                <button onClick={handleSubmit} disabled={!formCode} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', background: !formCode ? text3 : brand, color: '#fff', fontSize: 13, fontWeight: 600, cursor: !formCode ? 'not-allowed' : 'pointer' }}>
                  {editingTable ? '保存修改' : '创建桌台'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default FloorTableConfigPage;
