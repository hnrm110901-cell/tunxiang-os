/**
 * 营业日配置页 — /hq/business-day/config
 * P0-04: 营业日/餐段/班次配置
 * API: GET/POST /api/v1/ops/business-days/*
 *      GET/POST /api/v1/ops/shifts/*
 */
import { useEffect, useState, useCallback } from 'react';
import { apiGet, apiPost, apiPatch } from '../../api/client';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface MealPeriod {
  id: string;
  name: string;
  start_time: string; // HH:MM
  end_time: string;
  is_auto_switch: boolean;
}

interface ShiftTemplate {
  id: string;
  name: string;
  start_time: string;
  end_time: string;
}

interface BusinessDayConfig {
  store_id: string;
  store_name: string;
  cutoff_time: string; // HH:MM
  auto_close_enabled: boolean;
  timezone: string;
  meal_periods: MealPeriod[];
  shift_templates: ShiftTemplate[];
}

interface StoreOption { id: string; name: string; }

// ─── 降级数据 ──────────────────────────────────────────────────────────────────

const FALLBACK_STORES: StoreOption[] = [
  { id: 'demo_store_01', name: '徐记海鲜（五一广场店）' },
  { id: 'demo_store_02', name: '徐记海鲜（梅溪湖店）' },
];

const FALLBACK_CONFIG: BusinessDayConfig = {
  store_id: 'demo_store_01',
  store_name: '徐记海鲜（五一广场店）',
  cutoff_time: '04:00',
  auto_close_enabled: true,
  timezone: 'Asia/Shanghai',
  meal_periods: [
    { id: 'mp1', name: '早茶', start_time: '07:00', end_time: '10:30', is_auto_switch: true },
    { id: 'mp2', name: '午市', start_time: '10:30', end_time: '14:00', is_auto_switch: true },
    { id: 'mp3', name: '下午茶', start_time: '14:00', end_time: '17:00', is_auto_switch: true },
    { id: 'mp4', name: '晚市', start_time: '17:00', end_time: '21:30', is_auto_switch: true },
    { id: 'mp5', name: '夜宵', start_time: '21:30', end_time: '04:00', is_auto_switch: true },
  ],
  shift_templates: [
    { id: 'st1', name: '早班', start_time: '07:00', end_time: '15:00' },
    { id: 'st2', name: '晚班', start_time: '14:00', end_time: '23:00' },
    { id: 'st3', name: '通班', start_time: '09:00', end_time: '21:00' },
  ],
};

// ─── 组件 ──────────────────────────────────────────────────────────────────────

export function BusinessDayConfigPage() {
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState('');
  const [config, setConfig] = useState<BusinessDayConfig>(FALLBACK_CONFIG);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<'overview' | 'meals' | 'shifts'>('overview');

  // 编辑状态
  const [cutoffTime, setCutoffTime] = useState('04:00');
  const [autoClose, setAutoClose] = useState(true);
  const [meals, setMeals] = useState<MealPeriod[]>([]);
  const [shifts, setShifts] = useState<ShiftTemplate[]>([]);

  // ─── 加载 ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const res = await apiGet<{ items: StoreOption[] }>('/api/v1/trade/stores?page=1&size=100');
        if (res.items?.length) { setStores(res.items); setSelectedStoreId(res.items[0].id); }
        else { setStores(FALLBACK_STORES); setSelectedStoreId(FALLBACK_STORES[0].id); }
      } catch { setStores(FALLBACK_STORES); setSelectedStoreId(FALLBACK_STORES[0].id); }
    })();
  }, []);

  const loadConfig = useCallback(async () => {
    if (!selectedStoreId) return;
    setLoading(true);
    try {
      const res = await apiGet<BusinessDayConfig>(`/api/v1/ops/business-day-config?store_id=${selectedStoreId}`);
      setConfig(res);
      setCutoffTime(res.cutoff_time);
      setAutoClose(res.auto_close_enabled);
      setMeals(res.meal_periods);
      setShifts(res.shift_templates);
    } catch {
      setConfig(FALLBACK_CONFIG);
      setCutoffTime(FALLBACK_CONFIG.cutoff_time);
      setAutoClose(FALLBACK_CONFIG.auto_close_enabled);
      setMeals(FALLBACK_CONFIG.meal_periods);
      setShifts(FALLBACK_CONFIG.shift_templates);
    }
    setLoading(false);
  }, [selectedStoreId]);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  // ─── 保存 ──────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    setSaving(true);
    try {
      await apiPost('/api/v1/ops/business-day-config', {
        store_id: selectedStoreId,
        cutoff_time: cutoffTime,
        auto_close_enabled: autoClose,
        meal_periods: meals,
        shift_templates: shifts,
      });
    } catch (err) {
      console.error('保存失败', err);
    }
    setSaving(false);
  };

  // ─── 餐段编辑 ──────────────────────────────────────────────────────────────
  const updateMeal = (idx: number, field: keyof MealPeriod, value: string | boolean) => {
    setMeals((prev) => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m));
  };
  const addMeal = () => {
    setMeals((prev) => [...prev, { id: `mp_new_${Date.now()}`, name: '新餐段', start_time: '12:00', end_time: '14:00', is_auto_switch: true }]);
  };
  const removeMeal = (idx: number) => {
    setMeals((prev) => prev.filter((_, i) => i !== idx));
  };

  // ─── 班次编辑 ──────────────────────────────────────────────────────────────
  const updateShift = (idx: number, field: keyof ShiftTemplate, value: string) => {
    setShifts((prev) => prev.map((s, i) => i === idx ? { ...s, [field]: value } : s));
  };
  const addShift = () => {
    setShifts((prev) => [...prev, { id: `st_new_${Date.now()}`, name: '新班次', start_time: '09:00', end_time: '18:00' }]);
  };
  const removeShift = (idx: number) => {
    setShifts((prev) => prev.filter((_, i) => i !== idx));
  };

  // ─── 样式 ──────────────────────────────────────────────────────────────────
  const brand = '#FF6B35';
  const bg1 = '#112228';
  const bg2 = '#1a2a33';
  const bg0 = '#0B1A20';
  const text1 = '#E8E6E1';
  const text2 = '#999';
  const text3 = '#666';

  const tabs = [
    { key: 'overview' as const, label: '营业日总览' },
    { key: 'meals' as const, label: '餐段配置' },
    { key: 'shifts' as const, label: '班次模板' },
  ];

  // ─── 时间轴可视化（24小时） ────────────────────────────────────────────────
  const renderTimeline = () => {
    const hours = Array.from({ length: 24 }, (_, i) => i);
    const parseTime = (t: string) => { const [h, m] = t.split(':').map(Number); return h + m / 60; };
    return (
      <div style={{ background: bg1, borderRadius: 12, padding: 20, border: `1px solid ${bg2}`, marginTop: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>24小时时间轴</div>
        {/* 时间刻度 */}
        <div style={{ position: 'relative', height: 20, marginBottom: 4 }}>
          {hours.filter((h) => h % 3 === 0).map((h) => (
            <span key={h} style={{ position: 'absolute', left: `${(h / 24) * 100}%`, fontSize: 10, color: text3, transform: 'translateX(-50%)' }}>{String(h).padStart(2, '0')}:00</span>
          ))}
        </div>
        {/* 餐段条 */}
        <div style={{ position: 'relative', height: 28, background: bg2, borderRadius: 6, marginBottom: 8 }}>
          {meals.map((mp, idx) => {
            const s = parseTime(mp.start_time);
            const e = parseTime(mp.end_time);
            const left = (s / 24) * 100;
            const width = e > s ? ((e - s) / 24) * 100 : ((24 - s + e) / 24) * 100;
            const colors = ['#FF6B35', '#0F6E56', '#185FA5', '#8B5CF6', '#D97706'];
            const c = colors[idx % colors.length];
            return (
              <div key={mp.id} style={{ position: 'absolute', left: `${left}%`, width: `${width}%`, height: '100%', background: `${c}44`, borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ fontSize: 10, color: c, fontWeight: 600, whiteSpace: 'nowrap' }}>{mp.name}</span>
              </div>
            );
          })}
        </div>
        {/* 班次条 */}
        <div style={{ position: 'relative', height: 28, background: bg2, borderRadius: 6 }}>
          {shifts.map((st, idx) => {
            const s = parseTime(st.start_time);
            const e = parseTime(st.end_time);
            const left = (s / 24) * 100;
            const width = e > s ? ((e - s) / 24) * 100 : ((24 - s + e) / 24) * 100;
            const colors = ['#3B82F6', '#10B981', '#F59E0B'];
            const c = colors[idx % colors.length];
            return (
              <div key={st.id} style={{ position: 'absolute', left: `${left}%`, width: `${width}%`, height: '100%', background: `${c}44`, borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ fontSize: 10, color: c, fontWeight: 600, whiteSpace: 'nowrap' }}>{st.name}</span>
              </div>
            );
          })}
        </div>
        {/* 日结线 */}
        <div style={{ position: 'relative', height: 0, marginTop: -56 }}>
          {(() => {
            const ct = parseTime(cutoffTime);
            const left = (ct / 24) * 100;
            return (
              <div style={{ position: 'absolute', left: `${left}%`, top: -8, height: 72, borderLeft: '2px dashed #A32D2D', zIndex: 1 }}>
                <span style={{ position: 'absolute', top: -16, left: 4, fontSize: 10, color: '#A32D2D', fontWeight: 600, whiteSpace: 'nowrap' }}>日结 {cutoffTime}</span>
              </div>
            );
          })()}
        </div>
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, color: text1 }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>营业日与餐段配置</h2>
          <p style={{ fontSize: 13, color: text2, margin: '4px 0 0' }}>统一门店营业日、班次、餐段统计口径</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select
            value={selectedStoreId}
            onChange={(e) => setSelectedStoreId(e.target.value)}
            style={{ padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg1, color: text1, fontSize: 13 }}
          >
            {stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button onClick={handleSave} disabled={saving} style={{ padding: '8px 16px', borderRadius: 8, border: 'none', background: brand, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: saving ? 0.6 : 1 }}>
            {saving ? '保存中...' : '发布配置'}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${bg2}`, paddingBottom: 0 }}>
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{ padding: '8px 18px', borderRadius: '8px 8px 0 0', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: activeTab === t.key ? 600 : 400, background: activeTab === t.key ? bg1 : 'transparent', color: activeTab === t.key ? brand : text2, borderBottom: activeTab === t.key ? `2px solid ${brand}` : '2px solid transparent' }}>
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: text2 }}>加载中...</div>
      ) : (
        <>
          {/* 总览 Tab */}
          {activeTab === 'overview' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* 核心参数卡片 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                <div style={{ background: bg1, borderRadius: 12, padding: 20, border: `1px solid ${bg2}` }}>
                  <div style={{ fontSize: 11, color: text2, marginBottom: 4 }}>📅 日结时间点</div>
                  <div style={{ fontSize: 28, fontWeight: 700 }}>{cutoffTime}</div>
                  <div style={{ fontSize: 11, color: text3, marginTop: 4 }}>日结前交易归属前一个营业日</div>
                </div>
                <div style={{ background: bg1, borderRadius: 12, padding: 20, border: `1px solid ${bg2}` }}>
                  <div style={{ fontSize: 11, color: text2, marginBottom: 4 }}>🍽️ 餐段数</div>
                  <div style={{ fontSize: 28, fontWeight: 700 }}>{meals.length}</div>
                  <div style={{ fontSize: 11, color: text3, marginTop: 4 }}>{meals.map((m) => m.name).join(' → ')}</div>
                </div>
                <div style={{ background: bg1, borderRadius: 12, padding: 20, border: `1px solid ${bg2}` }}>
                  <div style={{ fontSize: 11, color: text2, marginBottom: 4 }}>👥 班次模板</div>
                  <div style={{ fontSize: 28, fontWeight: 700 }}>{shifts.length}</div>
                  <div style={{ fontSize: 11, color: text3, marginTop: 4 }}>{shifts.map((s) => s.name).join('、')}</div>
                </div>
              </div>
              {/* 时间轴 */}
              {renderTimeline()}
              {/* 日结时间编辑 */}
              <div style={{ background: bg1, borderRadius: 12, padding: 20, border: `1px solid ${bg2}` }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>基础设置</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                  <label style={{ fontSize: 12, color: text2 }}>
                    日结时间（跨日时间点）
                    <input type="time" value={cutoffTime} onChange={(e) => setCutoffTime(e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                  </label>
                  <label style={{ fontSize: 12, color: text2, display: 'flex', flexDirection: 'column' }}>
                    自动闭店
                    <div style={{ marginTop: 8 }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13, color: text1 }}>
                        <input type="checkbox" checked={autoClose} onChange={() => setAutoClose(!autoClose)} style={{ accentColor: brand }} />
                        到达日结时间后自动触发闭店流程
                      </label>
                    </div>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* 餐段配置 Tab */}
          {activeTab === 'meals' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {meals.map((mp, idx) => (
                <div key={mp.id} style={{ background: bg1, borderRadius: 12, padding: 16, border: `1px solid ${bg2}`, display: 'grid', gridTemplateColumns: '1fr 120px 120px auto auto', gap: 12, alignItems: 'end' }}>
                  <label style={{ fontSize: 12, color: text2 }}>
                    餐段名称
                    <input value={mp.name} onChange={(e) => updateMeal(idx, 'name', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                  </label>
                  <label style={{ fontSize: 12, color: text2 }}>
                    开始
                    <input type="time" value={mp.start_time} onChange={(e) => updateMeal(idx, 'start_time', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                  </label>
                  <label style={{ fontSize: 12, color: text2 }}>
                    结束
                    <input type="time" value={mp.end_time} onChange={(e) => updateMeal(idx, 'end_time', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: 12, color: text2, paddingBottom: 4 }}>
                    <input type="checkbox" checked={mp.is_auto_switch} onChange={() => updateMeal(idx, 'is_auto_switch', !mp.is_auto_switch)} style={{ accentColor: brand }} />
                    自动
                  </label>
                  <button onClick={() => removeMeal(idx)} style={{ padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: 'transparent', color: '#A32D2D', fontSize: 12, cursor: 'pointer' }}>删除</button>
                </div>
              ))}
              <button onClick={addMeal} style={{ padding: '10px 20px', borderRadius: 8, border: `1px dashed ${bg2}`, background: 'transparent', color: text2, fontSize: 13, cursor: 'pointer' }}>+ 添加餐段</button>
              {renderTimeline()}
            </div>
          )}

          {/* 班次模板 Tab */}
          {activeTab === 'shifts' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {shifts.map((st, idx) => (
                <div key={st.id} style={{ background: bg1, borderRadius: 12, padding: 16, border: `1px solid ${bg2}`, display: 'grid', gridTemplateColumns: '1fr 120px 120px auto', gap: 12, alignItems: 'end' }}>
                  <label style={{ fontSize: 12, color: text2 }}>
                    班次名称
                    <input value={st.name} onChange={(e) => updateShift(idx, 'name', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                  </label>
                  <label style={{ fontSize: 12, color: text2 }}>
                    开始
                    <input type="time" value={st.start_time} onChange={(e) => updateShift(idx, 'start_time', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                  </label>
                  <label style={{ fontSize: 12, color: text2 }}>
                    结束
                    <input type="time" value={st.end_time} onChange={(e) => updateShift(idx, 'end_time', e.target.value)} style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: bg0, color: text1, fontSize: 14 }} />
                  </label>
                  <button onClick={() => removeShift(idx)} style={{ padding: '8px 12px', borderRadius: 8, border: `1px solid ${bg2}`, background: 'transparent', color: '#A32D2D', fontSize: 12, cursor: 'pointer' }}>删除</button>
                </div>
              ))}
              <button onClick={addShift} style={{ padding: '10px 20px', borderRadius: 8, border: `1px dashed ${bg2}`, background: 'transparent', color: text2, fontSize: 13, cursor: 'pointer' }}>+ 添加班次</button>
              {renderTimeline()}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default BusinessDayConfigPage;
