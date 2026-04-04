/**
 * LiveSeafoodPage -- 活鲜鱼缸管理看板
 *
 * 海鲜档口员工使用的鱼缸管理页面（POS端）。
 * 核心功能：鱼缸总览、品种库存、温度记录、损耗登记、到货入缸、调价。
 * 对接 tx-supply /api/v1/supply/live-seafood/* 系列接口。
 *
 * 设计适配：徐记海鲜 23 套系统替换方案，活鲜池管理为其核心业务环节。
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── API 基础 ────────────────────────────────────────────────────────────────

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

async function txFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options?.headers as Record<string, string> || {}),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface TankItem {
  tank_id: string;
  zone_name: string;
  species: string[];
  species_names: string[];
  current_stock_kg: number;
  capacity_kg: number;
  temperature: number;
  temp_min: number;
  temp_max: number;
  mortality_today: number;
  status: '正常' | '预警' | '停用';
  alert_level: 'normal' | 'warning' | 'critical';
}

interface SpeciesItem {
  species_key: string;
  species_name: string;
  alive_kg: number;
  weak_kg: number;
  sales_today_kg: number;
  mortality_today_kg: number;
  price_fen_per_jin: number;
  stock_status: '充足' | '偏少' | '缺货';
}

type ModalType = 'temperature' | 'mortality' | 'receive' | 'price' | null;
type TabType = 'tanks' | 'species';

// ─── Fallback 数据 ──────────────────────────────────────────────────────────

const FALLBACK_TANKS: TankItem[] = [
  { tank_id: 't1', zone_name: 'A区1号缸', species: ['lobster'], species_names: ['龙虾'], current_stock_kg: 18.5, capacity_kg: 30, temperature: 14.5, temp_min: 12, temp_max: 18, mortality_today: 0, status: '正常', alert_level: 'normal' },
  { tank_id: 't2', zone_name: 'A区2号缸', species: ['grouper'], species_names: ['石斑鱼'], current_stock_kg: 25.0, capacity_kg: 40, temperature: 22.0, temp_min: 18, temp_max: 25, mortality_today: 1, status: '正常', alert_level: 'normal' },
  { tank_id: 't3', zone_name: 'B区龙虾池', species: ['boston_lobster'], species_names: ['波士顿龙虾'], current_stock_kg: 12.0, capacity_kg: 20, temperature: 7.8, temp_min: 5, temp_max: 10, mortality_today: 0, status: '正常', alert_level: 'normal' },
  { tank_id: 't4', zone_name: 'B区帝王蟹缸', species: ['king_crab'], species_names: ['帝王蟹'], current_stock_kg: 6.5, capacity_kg: 15, temperature: 4.2, temp_min: 2, temp_max: 6, mortality_today: 2, status: '预警', alert_level: 'warning' },
  { tank_id: 't5', zone_name: 'C区鲍鱼池', species: ['abalone'], species_names: ['鲍鱼'], current_stock_kg: 8.0, capacity_kg: 20, temperature: 19.5, temp_min: 15, temp_max: 22, mortality_today: 0, status: '正常', alert_level: 'normal' },
  { tank_id: 't6', zone_name: 'C区象拔蚌缸', species: ['geoduck'], species_names: ['象拔蚌'], current_stock_kg: 4.2, capacity_kg: 12, temperature: 11.0, temp_min: 8, temp_max: 15, mortality_today: 0, status: '正常', alert_level: 'normal' },
  { tank_id: 't7', zone_name: 'D区东星斑缸', species: ['leopard_coral_grouper'], species_names: ['东星斑'], current_stock_kg: 3.5, capacity_kg: 15, temperature: 29.0, temp_min: 20, temp_max: 28, mortality_today: 1, status: '预警', alert_level: 'warning' },
  { tank_id: 't8', zone_name: 'D区澳龙池', species: ['australian_lobster'], species_names: ['澳洲龙虾'], current_stock_kg: 0, capacity_kg: 20, temperature: 0, temp_min: 15, temp_max: 20, mortality_today: 0, status: '停用', alert_level: 'normal' },
];

const FALLBACK_SPECIES: SpeciesItem[] = [
  { species_key: 'lobster', species_name: '龙虾', alive_kg: 18.5, weak_kg: 0.5, sales_today_kg: 3.2, mortality_today_kg: 0, price_fen_per_jin: 12800, stock_status: '充足' },
  { species_key: 'grouper', species_name: '石斑鱼', alive_kg: 25.0, weak_kg: 1.0, sales_today_kg: 5.5, mortality_today_kg: 0.3, price_fen_per_jin: 8800, stock_status: '充足' },
  { species_key: 'boston_lobster', species_name: '波士顿龙虾', alive_kg: 12.0, weak_kg: 0.8, sales_today_kg: 4.0, mortality_today_kg: 0, price_fen_per_jin: 16800, stock_status: '充足' },
  { species_key: 'king_crab', species_name: '帝王蟹', alive_kg: 6.5, weak_kg: 0.3, sales_today_kg: 8.0, mortality_today_kg: 0.6, price_fen_per_jin: 39800, stock_status: '偏少' },
  { species_key: 'abalone', species_name: '鲍鱼', alive_kg: 8.0, weak_kg: 0.2, sales_today_kg: 1.5, mortality_today_kg: 0, price_fen_per_jin: 5800, stock_status: '充足' },
  { species_key: 'geoduck', species_name: '象拔蚌', alive_kg: 4.2, weak_kg: 0.1, sales_today_kg: 2.0, mortality_today_kg: 0, price_fen_per_jin: 18800, stock_status: '偏少' },
  { species_key: 'leopard_coral_grouper', species_name: '东星斑', alive_kg: 3.5, weak_kg: 0.5, sales_today_kg: 2.5, mortality_today_kg: 0.2, price_fen_per_jin: 28800, stock_status: '偏少' },
  { species_key: 'australian_lobster', species_name: '澳洲龙虾', alive_kg: 0, weak_kg: 0, sales_today_kg: 0, mortality_today_kg: 0, price_fen_per_jin: 22800, stock_status: '缺货' },
];

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number): string => `${(fen / 100).toFixed(0)}`;

function getTempColor(temp: number, min: number, max: number): string {
  if (temp === 0) return '#6B8A99';
  if (temp < min) return '#3B82F6';       // blue - too cold
  if (temp > max) return '#EF4444';       // red - too hot
  return '#22C55E';                        // green - normal
}

function getUsagePercent(current: number, capacity: number): number {
  if (capacity <= 0) return 0;
  return Math.min(100, Math.round((current / capacity) * 100));
}

function getUsageBarColor(pct: number): string {
  if (pct >= 90) return '#EF4444';
  if (pct >= 70) return '#F59E0B';
  return '#22C55E';
}

function getStatusBadge(status: string): { bg: string; color: string } {
  switch (status) {
    case '正常': return { bg: 'rgba(34,197,94,0.15)', color: '#22C55E' };
    case '预警': return { bg: 'rgba(245,158,11,0.15)', color: '#F59E0B' };
    case '停用': return { bg: 'rgba(107,138,153,0.15)', color: '#6B8A99' };
    default:     return { bg: 'rgba(107,138,153,0.15)', color: '#6B8A99' };
  }
}

function getStockStatusBadge(status: string): { bg: string; color: string } {
  switch (status) {
    case '充足': return { bg: 'rgba(34,197,94,0.15)', color: '#22C55E' };
    case '偏少': return { bg: 'rgba(245,158,11,0.15)', color: '#F59E0B' };
    case '缺货': return { bg: 'rgba(239,68,68,0.15)', color: '#EF4444' };
    default:     return { bg: 'rgba(107,138,153,0.15)', color: '#6B8A99' };
  }
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function LiveSeafoodPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabType>('tanks');
  const [tanks, setTanks] = useState<TankItem[]>(FALLBACK_TANKS);
  const [species, setSpecies] = useState<SpeciesItem[]>(FALLBACK_SPECIES);
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<ModalType>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  // modal form states
  const [formTankId, setFormTankId] = useState('');
  const [formTemp, setFormTemp] = useState('');
  const [formRecorder, setFormRecorder] = useState('');
  const [formSpecies, setFormSpecies] = useState('');
  const [formQuantityG, setFormQuantityG] = useState('');
  const [formCause, setFormCause] = useState<string>('自然死亡');
  const [formQuantityKg, setFormQuantityKg] = useState('');
  const [formSupplier, setFormSupplier] = useState('');
  const [formBatchNo, setFormBatchNo] = useState('');
  const [formTankZone, setFormTankZone] = useState('');
  const [formPriceFen, setFormPriceFen] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // ── 加载数据 ──

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [tankData, speciesData] = await Promise.all([
        txFetch<TankItem[]>(`/api/v1/supply/live-seafood/tanks?store_id=${encodeURIComponent(STORE_ID)}`).catch(() => null),
        txFetch<SpeciesItem[]>(`/api/v1/supply/live-seafood/species?store_id=${encodeURIComponent(STORE_ID)}`).catch(() => null),
      ]);
      if (tankData) setTanks(tankData);
      if (speciesData) setSpecies(speciesData);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Toast ──

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 2500);
  };

  // ── 弹窗重置 ──

  const openModal = (type: ModalType) => {
    setFormTankId(tanks[0]?.tank_id || '');
    setFormTemp('');
    setFormRecorder('');
    setFormSpecies(species[0]?.species_key || '');
    setFormQuantityG('');
    setFormCause('自然死亡');
    setFormQuantityKg('');
    setFormSupplier('');
    setFormBatchNo('');
    setFormTankZone(tanks[0]?.zone_name || '');
    setFormPriceFen('');
    setSubmitting(false);
    setModal(type);
  };

  // ── 提交：温度记录 ──

  const submitTemperature = async () => {
    if (!formTankId || !formTemp) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/supply/live-seafood/temperature', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID,
          tank_id: formTankId,
          temperature: parseFloat(formTemp),
          recorder_name: formRecorder || undefined,
        }),
      });
      showToast('温度记录成功');
      setModal(null);
      loadData();
    } catch (err) {
      showToast(err instanceof Error ? err.message : '记录失败');
    } finally {
      setSubmitting(false);
    }
  };

  // ── 提交：损耗登记 ──

  const submitMortality = async () => {
    if (!formSpecies || !formQuantityG) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/supply/live-seafood/mortality', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID,
          species: formSpecies,
          quantity_g: parseInt(formQuantityG, 10),
          cause: formCause,
        }),
      });
      showToast('损耗登记成功');
      setModal(null);
      loadData();
    } catch (err) {
      showToast(err instanceof Error ? err.message : '登记失败');
    } finally {
      setSubmitting(false);
    }
  };

  // ── 提交：到货入缸 ──

  const submitReceive = async () => {
    if (!formSpecies || !formQuantityKg) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/supply/live-seafood/receive', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID,
          species: formSpecies,
          quantity_kg: parseFloat(formQuantityKg),
          supplier: formSupplier || undefined,
          batch_no: formBatchNo || undefined,
          tank_zone: formTankZone || undefined,
        }),
      });
      showToast('到货入缸成功');
      setModal(null);
      loadData();
    } catch (err) {
      showToast(err instanceof Error ? err.message : '入缸失败');
    } finally {
      setSubmitting(false);
    }
  };

  // ── 提交：调价 ──

  const submitPrice = async () => {
    if (!formSpecies || !formPriceFen) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/supply/live-seafood/price', {
        method: 'PUT',
        body: JSON.stringify({
          store_id: STORE_ID,
          species: formSpecies,
          price_fen_per_jin: parseInt(formPriceFen, 10),
        }),
      });
      showToast('调价成功');
      setModal(null);
      loadData();
    } catch (err) {
      showToast(err instanceof Error ? err.message : '调价失败');
    } finally {
      setSubmitting(false);
    }
  };

  // ── 统计摘要 ──

  const totalTanks = tanks.length;
  const activeTanks = tanks.filter(t => t.status !== '停用').length;
  const warningTanks = tanks.filter(t => t.alert_level === 'warning' || t.alert_level === 'critical').length;
  const totalMortalityToday = tanks.reduce((sum, t) => sum + t.mortality_today, 0);

  // ── 渲染 ──

  return (
    <div style={{ minHeight: '100vh', background: '#0B1A20', color: '#E0E7EB', fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif' }}>

      {/* ── 顶部栏 ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: '#112228', borderBottom: '1px solid #1E3A45' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
            style={{ ...touchBtn, background: '#1E3A45', width: 48, height: 48, fontSize: 20 }}
          >
            &larr;
          </button>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#E0E7EB' }}>
            活鲜鱼缸管理
          </h1>
          {loading && <span style={{ color: '#F59E0B', fontSize: 14 }}>刷新中...</span>}
        </div>
        <button
          type="button"
          onClick={loadData}
          style={{ ...touchBtn, background: '#1E3A45', padding: '0 16px', height: 44, fontSize: 15, color: '#FF6B2C' }}
        >
          刷新
        </button>
      </div>

      {/* ── 统计摘要 ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, padding: '12px 16px' }}>
        <SummaryCard label="运行中" value={`${activeTanks}/${totalTanks}`} color="#22C55E" />
        <SummaryCard label="预警" value={String(warningTanks)} color={warningTanks > 0 ? '#F59E0B' : '#6B8A99'} />
        <SummaryCard label="今日损耗" value={`${totalMortalityToday}尾`} color={totalMortalityToday > 0 ? '#EF4444' : '#6B8A99'} />
        <SummaryCard label="品种" value={`${species.filter(s => s.alive_kg > 0).length}种`} color="#3B82F6" />
      </div>

      {/* ── Tab 切换 + 快捷操作 ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px 12px' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <TabButton active={tab === 'tanks'} label="鱼缸总览" onClick={() => setTab('tanks')} />
          <TabButton active={tab === 'species'} label="品种库存" onClick={() => setTab('species')} />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <ActionChip label="温度记录" onClick={() => openModal('temperature')} />
          <ActionChip label="损耗登记" onClick={() => openModal('mortality')} />
          <ActionChip label="到货入缸" onClick={() => openModal('receive')} />
          <ActionChip label="调价" onClick={() => openModal('price')} />
        </div>
      </div>

      {/* ── 内容区 ── */}
      <div style={{ padding: '0 16px 24px', overflowY: 'auto' }}>
        {tab === 'tanks' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {tanks.map(tank => (
              <TankCard key={tank.tank_id} tank={tank} />
            ))}
          </div>
        )}

        {tab === 'species' && (
          <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 15 }}>
              <thead>
                <tr style={{ background: '#112228', borderBottom: '1px solid #1E3A45' }}>
                  {['品种', '存活(kg)', '弱体(kg)', '今日销售(kg)', '今日损耗(kg)', '时价(元/斤)', '状态'].map(h => (
                    <th key={h} style={{ padding: '12px 10px', textAlign: 'left', color: '#6B8A99', fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {species.map(sp => {
                  const badge = getStockStatusBadge(sp.stock_status);
                  return (
                    <tr key={sp.species_key} style={{ borderBottom: '1px solid #1E3A45' }}>
                      <td style={{ padding: '14px 10px', fontWeight: 600, fontSize: 16, color: '#E0E7EB' }}>{sp.species_name}</td>
                      <td style={tdStyle}>{sp.alive_kg.toFixed(1)}</td>
                      <td style={{ ...tdStyle, color: sp.weak_kg > 0 ? '#F59E0B' : '#6B8A99' }}>{sp.weak_kg.toFixed(1)}</td>
                      <td style={tdStyle}>{sp.sales_today_kg.toFixed(1)}</td>
                      <td style={{ ...tdStyle, color: sp.mortality_today_kg > 0 ? '#EF4444' : '#6B8A99' }}>{sp.mortality_today_kg.toFixed(1)}</td>
                      <td style={{ ...tdStyle, color: '#FF6B2C', fontWeight: 600 }}>{fen2yuan(sp.price_fen_per_jin)}</td>
                      <td style={tdStyle}>
                        <span style={{ display: 'inline-block', padding: '3px 10px', borderRadius: 6, background: badge.bg, color: badge.color, fontSize: 13, fontWeight: 600 }}>
                          {sp.stock_status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── 弹窗 ── */}
      {modal && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <div
            role="presentation"
            onClick={() => setModal(null)}
            style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }}
          />
          <div
            role="dialog"
            aria-modal="true"
            style={{ position: 'relative', background: '#112228', borderRadius: 16, padding: 24, width: '90%', maxWidth: 420, maxHeight: '80vh', overflowY: 'auto', border: '1px solid #1E3A45' }}
          >
            {modal === 'temperature' && (
              <>
                <h2 style={modalTitle}>温度记录</h2>
                <FormField label="选择鱼缸">
                  <select value={formTankId} onChange={e => setFormTankId(e.target.value)} style={selectStyle}>
                    {tanks.filter(t => t.status !== '停用').map(t => (
                      <option key={t.tank_id} value={t.tank_id}>{t.zone_name}</option>
                    ))}
                  </select>
                </FormField>
                <FormField label="水温 (C)">
                  <input
                    type="number"
                    inputMode="decimal"
                    step="0.1"
                    value={formTemp}
                    onChange={e => setFormTemp(e.target.value)}
                    placeholder="例如 18.5"
                    style={inputStyle}
                  />
                </FormField>
                <FormField label="记录人">
                  <input
                    type="text"
                    value={formRecorder}
                    onChange={e => setFormRecorder(e.target.value)}
                    placeholder="姓名（可选）"
                    style={inputStyle}
                  />
                </FormField>
                <ModalActions
                  onCancel={() => setModal(null)}
                  onConfirm={submitTemperature}
                  disabled={!formTankId || !formTemp}
                  loading={submitting}
                />
              </>
            )}

            {modal === 'mortality' && (
              <>
                <h2 style={modalTitle}>损耗登记</h2>
                <FormField label="品种">
                  <select value={formSpecies} onChange={e => setFormSpecies(e.target.value)} style={selectStyle}>
                    {species.filter(s => s.alive_kg > 0).map(s => (
                      <option key={s.species_key} value={s.species_key}>{s.species_name}</option>
                    ))}
                  </select>
                </FormField>
                <FormField label="损耗重量 (克)">
                  <input
                    type="number"
                    inputMode="numeric"
                    value={formQuantityG}
                    onChange={e => setFormQuantityG(e.target.value)}
                    placeholder="例如 500"
                    style={inputStyle}
                  />
                </FormField>
                <FormField label="原因">
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {['自然死亡', '设备故障', '运输损伤'].map(c => (
                      <button
                        key={c}
                        type="button"
                        onClick={() => setFormCause(c)}
                        style={{
                          ...touchBtn,
                          padding: '8px 16px',
                          fontSize: 15,
                          background: formCause === c ? 'rgba(255,107,44,0.15)' : '#1E3A45',
                          color: formCause === c ? '#FF6B2C' : '#6B8A99',
                          border: formCause === c ? '1.5px solid #FF6B2C' : '1.5px solid transparent',
                        }}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </FormField>
                <ModalActions
                  onCancel={() => setModal(null)}
                  onConfirm={submitMortality}
                  disabled={!formSpecies || !formQuantityG}
                  loading={submitting}
                />
              </>
            )}

            {modal === 'receive' && (
              <>
                <h2 style={modalTitle}>到货入缸</h2>
                <FormField label="品种">
                  <select value={formSpecies} onChange={e => setFormSpecies(e.target.value)} style={selectStyle}>
                    {species.map(s => (
                      <option key={s.species_key} value={s.species_key}>{s.species_name}</option>
                    ))}
                  </select>
                </FormField>
                <FormField label="到货重量 (kg)">
                  <input
                    type="number"
                    inputMode="decimal"
                    step="0.1"
                    value={formQuantityKg}
                    onChange={e => setFormQuantityKg(e.target.value)}
                    placeholder="例如 10.5"
                    style={inputStyle}
                  />
                </FormField>
                <FormField label="供应商">
                  <input
                    type="text"
                    value={formSupplier}
                    onChange={e => setFormSupplier(e.target.value)}
                    placeholder="供应商名称"
                    style={inputStyle}
                  />
                </FormField>
                <FormField label="批次号">
                  <input
                    type="text"
                    value={formBatchNo}
                    onChange={e => setFormBatchNo(e.target.value)}
                    placeholder="例如 BN20260404-001"
                    style={inputStyle}
                  />
                </FormField>
                <FormField label="目标鱼缸">
                  <select value={formTankZone} onChange={e => setFormTankZone(e.target.value)} style={selectStyle}>
                    {tanks.map(t => (
                      <option key={t.tank_id} value={t.zone_name}>{t.zone_name}</option>
                    ))}
                  </select>
                </FormField>
                <ModalActions
                  onCancel={() => setModal(null)}
                  onConfirm={submitReceive}
                  disabled={!formSpecies || !formQuantityKg}
                  loading={submitting}
                />
              </>
            )}

            {modal === 'price' && (
              <>
                <h2 style={modalTitle}>调价</h2>
                <FormField label="品种">
                  <select value={formSpecies} onChange={e => setFormSpecies(e.target.value)} style={selectStyle}>
                    {species.map(s => (
                      <option key={s.species_key} value={s.species_key}>
                        {s.species_name} (现价 {fen2yuan(s.price_fen_per_jin)}元/斤)
                      </option>
                    ))}
                  </select>
                </FormField>
                <FormField label="新价格 (分/斤)">
                  <input
                    type="number"
                    inputMode="numeric"
                    value={formPriceFen}
                    onChange={e => setFormPriceFen(e.target.value)}
                    placeholder="例如 12800 = 128元/斤"
                    style={inputStyle}
                  />
                </FormField>
                {formPriceFen && (
                  <div style={{ padding: '8px 0 4px', fontSize: 16, color: '#FF6B2C', fontWeight: 600 }}>
                    = {(parseInt(formPriceFen, 10) / 100).toFixed(2)} 元/斤
                  </div>
                )}
                <ModalActions
                  onCancel={() => setModal(null)}
                  onConfirm={submitPrice}
                  disabled={!formSpecies || !formPriceFen}
                  loading={submitting}
                />
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Toast ── */}
      {toastMsg && (
        <div style={{
          position: 'fixed', bottom: 80, left: '50%', transform: 'translateX(-50%)',
          background: '#22C55E', color: '#fff', padding: '12px 28px', borderRadius: 10,
          fontSize: 16, fontWeight: 600, zIndex: 2000, boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
        }}>
          {toastMsg}
        </div>
      )}
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function SummaryCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ background: '#112228', borderRadius: 10, padding: '12px 14px', border: '1px solid #1E3A45' }}>
      <div style={{ fontSize: 13, color: '#6B8A99', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

function TabButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        ...touchBtn,
        padding: '8px 20px',
        fontSize: 16,
        fontWeight: active ? 700 : 400,
        background: active ? 'rgba(255,107,44,0.12)' : 'transparent',
        color: active ? '#FF6B2C' : '#6B8A99',
        border: active ? '1.5px solid #FF6B2C' : '1.5px solid transparent',
      }}
    >
      {label}
    </button>
  );
}

function ActionChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        ...touchBtn,
        padding: '8px 14px',
        fontSize: 14,
        background: '#1E3A45',
        color: '#FF6B2C',
        fontWeight: 600,
      }}
    >
      {label}
    </button>
  );
}

function TankCard({ tank }: { tank: TankItem }) {
  const usage = getUsagePercent(tank.current_stock_kg, tank.capacity_kg);
  const tempColor = getTempColor(tank.temperature, tank.temp_min, tank.temp_max);
  const badge = getStatusBadge(tank.status);
  const barColor = getUsageBarColor(usage);

  return (
    <div style={{
      background: '#112228',
      borderRadius: 12,
      padding: 16,
      border: tank.alert_level === 'critical' ? '1.5px solid #EF4444'
            : tank.alert_level === 'warning' ? '1.5px solid #F59E0B'
            : '1px solid #1E3A45',
    }}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 700, color: '#E0E7EB' }}>{tank.zone_name}</div>
          <div style={{ fontSize: 14, color: '#6B8A99', marginTop: 2 }}>
            {tank.species_names.join(' / ') || '--'}
          </div>
        </div>
        <span style={{
          display: 'inline-block', padding: '3px 10px', borderRadius: 6,
          background: badge.bg, color: badge.color, fontSize: 12, fontWeight: 600,
        }}>
          {tank.status}
        </span>
      </div>

      {/* 库存用量条 */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#6B8A99', marginBottom: 4 }}>
          <span>库存</span>
          <span>{tank.current_stock_kg.toFixed(1)} / {tank.capacity_kg} kg</span>
        </div>
        <div style={{ height: 8, borderRadius: 4, background: '#1E3A45', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${usage}%`, borderRadius: 4, background: barColor, transition: 'width 300ms ease' }} />
        </div>
      </div>

      {/* 底部指标 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: tempColor }} />
          <span style={{ fontSize: 18, fontWeight: 700, color: tempColor, fontVariantNumeric: 'tabular-nums' }}>
            {tank.temperature > 0 ? `${tank.temperature.toFixed(1)}C` : '--'}
          </span>
          {tank.temperature > 0 && (
            <span style={{ fontSize: 12, color: '#6B8A99' }}>({tank.temp_min}-{tank.temp_max})</span>
          )}
        </div>
        {tank.mortality_today > 0 && (
          <span style={{ fontSize: 14, color: '#EF4444', fontWeight: 600 }}>
            损耗 {tank.mortality_today} 尾
          </span>
        )}
      </div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 14, color: '#6B8A99', marginBottom: 6, fontWeight: 500 }}>{label}</div>
      {children}
    </div>
  );
}

function ModalActions({ onCancel, onConfirm, disabled, loading }: {
  onCancel: () => void;
  onConfirm: () => void;
  disabled: boolean;
  loading: boolean;
}) {
  return (
    <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
      <button
        type="button"
        onClick={onCancel}
        style={{ ...touchBtn, flex: 1, height: 52, background: '#1E3A45', color: '#6B8A99', fontSize: 17, fontWeight: 600 }}
      >
        取消
      </button>
      <button
        type="button"
        onClick={onConfirm}
        disabled={disabled || loading}
        style={{
          ...touchBtn,
          flex: 2,
          height: 52,
          background: disabled || loading ? '#333' : '#FF6B2C',
          color: '#fff',
          fontSize: 17,
          fontWeight: 700,
          opacity: disabled || loading ? 0.5 : 1,
          cursor: disabled || loading ? 'not-allowed' : 'pointer',
        }}
      >
        {loading ? '提交中...' : '确认'}
      </button>
    </div>
  );
}

// ─── 共用样式 ─────────────────────────────────────────────────────────────────

const touchBtn: React.CSSProperties = {
  border: 'none',
  borderRadius: 8,
  color: '#E0E7EB',
  cursor: 'pointer',
  fontFamily: 'inherit',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  userSelect: 'none',
  WebkitUserSelect: 'none',
  minHeight: 44,
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  height: 48,
  padding: '0 14px',
  borderRadius: 8,
  border: '1.5px solid #1E3A45',
  background: '#0B1A20',
  color: '#E0E7EB',
  fontSize: 17,
  fontFamily: 'inherit',
  boxSizing: 'border-box',
  outline: 'none',
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  appearance: 'auto' as const,
};

const modalTitle: React.CSSProperties = {
  margin: '0 0 20px',
  fontSize: 20,
  fontWeight: 700,
  color: '#E0E7EB',
};

const tdStyle: React.CSSProperties = {
  padding: '14px 10px',
  fontSize: 15,
  color: '#B0BEC5',
  whiteSpace: 'nowrap',
};
