/**
 * 食安巡检执行页面 — 服务员/店长手机端
 * 4个功能Tab: 留样记录 / 温度记录 / 巡检执行 / 问题上报
 */
import { useState, useCallback } from 'react';
import { txFetch } from '../api/index';

const STORE_ID = import.meta.env.VITE_STORE_ID || '';

// ─── 类型 ───

type TabKey = 'sample' | 'temp' | 'inspect' | 'report';

interface TabDef { key: TabKey; label: string; icon: string }
const TABS: TabDef[] = [
  { key: 'sample', label: '留样', icon: '🧪' },
  { key: 'temp', label: '温度', icon: '🌡️' },
  { key: 'inspect', label: '巡检', icon: '📋' },
  { key: 'report', label: '上报', icon: '⚠️' },
];

const MEAL_PERIODS = ['早餐', '午餐', '晚餐'];
const EQUIPMENT_TYPES = [
  { id: 'fridge', label: '冷藏柜', min: 0, max: 4 },
  { id: 'freezer', label: '冷冻柜', min: -30, max: -18 },
  { id: 'hot', label: '热展柜', min: 60, max: 100 },
  { id: 'prep', label: '备餐区', min: 15, max: 25 },
];
const CHECKLIST_TYPES = ['日检', '周检', '月检'];
const SEVERITY_OPTIONS = [
  { value: 'minor', label: '轻微', color: '#faad14' },
  { value: 'major', label: '严重', color: '#FF6B2C' },
  { value: 'critical', label: '重大', color: '#ff4d4f' },
];
const VIOLATION_TYPES = ['食材过期', '温度异常', '卫生不达标', '操作违规', '设备故障', '其他'];

export function FoodSafetyPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('sample');
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const showResult = (msg: string) => { setSuccess(msg); setTimeout(() => setSuccess(null), 3000); };
  const showError = (msg: string) => { setError(msg); setTimeout(() => setError(null), 5000); };

  return (
    <div style={{ minHeight: '100vh', background: '#f5f6f8', fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' }}>
      {/* 顶部 */}
      <div style={{ background: '#fff', padding: '16px 20px', borderBottom: '1px solid #e8e8e8' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#1a1a1a' }}>食安巡检</h1>
      </div>

      {/* Tab 栏 */}
      <div style={{ display: 'flex', background: '#fff', borderBottom: '1px solid #e8e8e8' }}>
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              flex: 1, padding: '14px 0', border: 'none', background: 'none',
              borderBottom: activeTab === tab.key ? '3px solid #FF6B35' : '3px solid transparent',
              color: activeTab === tab.key ? '#FF6B35' : '#999',
              fontSize: 15, fontWeight: activeTab === tab.key ? 700 : 400,
              cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
            }}
          >
            <span style={{ fontSize: 20 }}>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* 结果提示 */}
      {success && <div style={{ margin: '12px 16px 0', padding: 12, borderRadius: 8, background: '#f0fff4', border: '1px solid #52c41a', color: '#0f6e56', fontSize: 15 }}>{success}</div>}
      {error && <div style={{ margin: '12px 16px 0', padding: 12, borderRadius: 8, background: '#fff5f5', border: '1px solid #ff4d4f', color: '#ff4d4f', fontSize: 15 }}>{error}</div>}

      {/* 内容区 */}
      <div style={{ padding: 16 }}>
        {activeTab === 'sample' && <SampleTab submitting={submitting} setSubmitting={setSubmitting} onSuccess={showResult} onError={showError} />}
        {activeTab === 'temp' && <TempTab submitting={submitting} setSubmitting={setSubmitting} onSuccess={showResult} onError={showError} />}
        {activeTab === 'inspect' && <InspectTab submitting={submitting} setSubmitting={setSubmitting} onSuccess={showResult} onError={showError} />}
        {activeTab === 'report' && <ReportTab submitting={submitting} setSubmitting={setSubmitting} onSuccess={showResult} onError={showError} />}
      </div>
    </div>
  );
}

// ─── 通用 Props ───
interface TabProps {
  submitting: boolean;
  setSubmitting: (v: boolean) => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

// ─── 留样记录 Tab ───
function SampleTab({ submitting, setSubmitting, onSuccess, onError }: TabProps) {
  const [mealPeriod, setMealPeriod] = useState(MEAL_PERIODS[1]);
  const [dishName, setDishName] = useState('');
  const [weightG, setWeightG] = useState(150);
  const [tempC, setTempC] = useState(3);
  const [sampler, setSampler] = useState('');

  const handleSubmit = useCallback(async () => {
    if (!dishName.trim() || !sampler.trim()) return;
    if (weightG < 125) { onError('留样重量不得低于125g'); return; }
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/food-safety/samples', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID, meal_period: mealPeriod, dish_name: dishName,
          sample_weight_g: weightG, storage_temp_celsius: tempC, sampler_name: sampler,
        }),
      });
      onSuccess(`${dishName} 留样记录已提交`);
      setDishName(''); setWeightG(150); setSampler('');
    } catch (err) { onError(err instanceof Error ? err.message : '提交失败'); }
    finally { setSubmitting(false); }
  }, [dishName, sampler, weightG, tempC, mealPeriod, setSubmitting, onSuccess, onError]);

  return (
    <div style={cardStyle}>
      <h3 style={sectionTitle}>留样记录</h3>
      <Field label="餐段">
        <div style={{ display: 'flex', gap: 8 }}>
          {MEAL_PERIODS.map(p => (
            <Chip key={p} selected={mealPeriod === p} onClick={() => setMealPeriod(p)}>{p}</Chip>
          ))}
        </div>
      </Field>
      <Field label="菜品名称 *">
        <input value={dishName} onChange={e => setDishName(e.target.value)} placeholder="输入菜品名称" style={inputStyle} />
      </Field>
      <Field label={`留样重量 (g) — 最低125g ${weightG < 125 ? '⚠️ 不足' : '✓'}`}>
        <input type="number" value={weightG} onChange={e => setWeightG(Number(e.target.value))} style={inputStyle} />
      </Field>
      <Field label={`存储温度 (°C) ${tempC > 4 ? '⚠️ 超标！应≤4°C' : '✓'}`}>
        <input type="number" value={tempC} onChange={e => setTempC(Number(e.target.value))} step={0.5} style={inputStyle} />
      </Field>
      <Field label="留样人 *">
        <input value={sampler} onChange={e => setSampler(e.target.value)} placeholder="姓名" style={inputStyle} />
      </Field>
      <SubmitBtn onClick={handleSubmit} disabled={submitting || !dishName.trim() || !sampler.trim()} loading={submitting}>提交留样</SubmitBtn>
    </div>
  );
}

// ─── 温度记录 Tab ───
function TempTab({ submitting, setSubmitting, onSuccess, onError }: TabProps) {
  const [equipment, setEquipment] = useState(EQUIPMENT_TYPES[0].id);
  const [tempC, setTempC] = useState(3);
  const [recorder, setRecorder] = useState('');

  const eqConfig = EQUIPMENT_TYPES.find(e => e.id === equipment)!;
  const outOfRange = tempC < eqConfig.min || tempC > eqConfig.max;

  const handleSubmit = useCallback(async () => {
    if (!recorder.trim()) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/food-safety/temperatures', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID, equipment_type: equipment, equipment_label: eqConfig.label,
          temperature_celsius: tempC, recorder_name: recorder,
        }),
      });
      onSuccess(`${eqConfig.label} 温度 ${tempC}°C 已记录${outOfRange ? ' (异常已上报)' : ''}`);
      setRecorder('');
    } catch (err) { onError(err instanceof Error ? err.message : '提交失败'); }
    finally { setSubmitting(false); }
  }, [equipment, tempC, recorder, eqConfig, outOfRange, setSubmitting, onSuccess, onError]);

  return (
    <div style={cardStyle}>
      <h3 style={sectionTitle}>温度记录</h3>
      <Field label="设备类型">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {EQUIPMENT_TYPES.map(eq => (
            <Chip key={eq.id} selected={equipment === eq.id} onClick={() => { setEquipment(eq.id); setTempC(eq.id === 'freezer' ? -20 : eq.id === 'hot' ? 65 : 3); }}>
              {eq.label}
            </Chip>
          ))}
        </div>
      </Field>
      <Field label={`当前温度 (°C) — 标准: ${eqConfig.min}~${eqConfig.max}°C`}>
        <input type="number" value={tempC} onChange={e => setTempC(Number(e.target.value))} step={0.5} style={{ ...inputStyle, borderColor: outOfRange ? '#ff4d4f' : '#e8e8e8', color: outOfRange ? '#ff4d4f' : '#1a1a1a' }} />
        {outOfRange && <div style={{ color: '#ff4d4f', fontSize: 14, marginTop: 4, fontWeight: 600 }}>⚠️ 温度超出安全范围！将自动触发预警</div>}
      </Field>
      <Field label="记录人 *">
        <input value={recorder} onChange={e => setRecorder(e.target.value)} placeholder="姓名" style={inputStyle} />
      </Field>
      <SubmitBtn onClick={handleSubmit} disabled={submitting || !recorder.trim()} loading={submitting} danger={outOfRange}>
        {outOfRange ? '提交异常记录' : '提交温度记录'}
      </SubmitBtn>
    </div>
  );
}

// ─── 巡检执行 Tab ───
function InspectTab({ submitting, setSubmitting, onSuccess, onError }: TabProps) {
  const [checkType, setCheckType] = useState(CHECKLIST_TYPES[0]);
  const [items, setItems] = useState([
    { name: '厨房地面清洁', score: 10 },
    { name: '冰箱温度正常', score: 10 },
    { name: '食材标签完整', score: 10 },
    { name: '员工着装规范', score: 10 },
    { name: '垃圾分类正确', score: 10 },
    { name: '消毒记录完整', score: 10 },
    { name: '排烟设备正常', score: 10 },
    { name: '灭火器在有效期', score: 10 },
    { name: '洗手液/纸巾充足', score: 10 },
    { name: '明厨亮灶摄像头正常', score: 10 },
  ]);
  const [violations, setViolations] = useState('');
  const [inspector, setInspector] = useState('');

  const totalScore = items.reduce((s, i) => s + i.score, 0);

  const updateScore = (idx: number, score: number) => {
    setItems(prev => prev.map((item, i) => i === idx ? { ...item, score: Math.max(0, Math.min(10, score)) } : item));
  };

  const handleSubmit = useCallback(async () => {
    if (!inspector.trim()) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/food-safety/inspections', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID, checklist_type: checkType,
          items: items.map(i => ({ name: i.name, max_score: 10, actual_score: i.score })),
          overall_score: totalScore, violations: violations ? [violations] : [],
          inspector_name: inspector,
        }),
      });
      onSuccess(`${checkType}巡检已提交，总分 ${totalScore}/100`);
      setViolations(''); setInspector('');
    } catch (err) { onError(err instanceof Error ? err.message : '提交失败'); }
    finally { setSubmitting(false); }
  }, [checkType, items, totalScore, violations, inspector, setSubmitting, onSuccess, onError]);

  return (
    <div style={cardStyle}>
      <h3 style={sectionTitle}>巡检执行</h3>
      <Field label="检查类型">
        <div style={{ display: 'flex', gap: 8 }}>
          {CHECKLIST_TYPES.map(t => <Chip key={t} selected={checkType === t} onClick={() => setCheckType(t)}>{t}</Chip>)}
        </div>
      </Field>

      {/* 评分列表 */}
      <div style={{ marginBottom: 16 }}>
        {items.map((item, idx) => (
          <div key={item.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #f0f0f0' }}>
            <span style={{ fontSize: 15, color: item.score < 6 ? '#ff4d4f' : '#1a1a1a' }}>{item.name}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button onClick={() => updateScore(idx, item.score - 1)} style={miniBtn}>-</button>
              <span style={{ fontSize: 18, fontWeight: 700, minWidth: 30, textAlign: 'center', color: item.score < 6 ? '#ff4d4f' : '#1a1a1a' }}>{item.score}</span>
              <button onClick={() => updateScore(idx, item.score + 1)} style={{ ...miniBtn, background: '#FF6B35', color: '#fff' }}>+</button>
            </div>
          </div>
        ))}
      </div>

      {/* 总分 */}
      <div style={{ textAlign: 'center', padding: 16, background: totalScore >= 80 ? '#f0fff4' : totalScore >= 60 ? '#fffbe6' : '#fff5f5', borderRadius: 8, marginBottom: 16 }}>
        <div style={{ fontSize: 36, fontWeight: 800, color: totalScore >= 80 ? '#0f6e56' : totalScore >= 60 ? '#ba7517' : '#ff4d4f' }}>{totalScore}<span style={{ fontSize: 18 }}>/100</span></div>
        <div style={{ fontSize: 14, color: '#999' }}>{totalScore >= 80 ? '合格' : totalScore >= 60 ? '需整改' : '不合格'}</div>
      </div>

      <Field label="违规事项（可选）">
        <textarea value={violations} onChange={e => setViolations(e.target.value)} placeholder="描述发现的问题..." style={{ ...inputStyle, minHeight: 60, resize: 'vertical' }} />
      </Field>
      <Field label="巡检人 *">
        <input value={inspector} onChange={e => setInspector(e.target.value)} placeholder="姓名" style={inputStyle} />
      </Field>
      <SubmitBtn onClick={handleSubmit} disabled={submitting || !inspector.trim()} loading={submitting}>提交巡检</SubmitBtn>
    </div>
  );
}

// ─── 问题上报 Tab ───
function ReportTab({ submitting, setSubmitting, onSuccess, onError }: TabProps) {
  const [severity, setSeverity] = useState('minor');
  const [vioType, setVioType] = useState(VIOLATION_TYPES[0]);
  const [desc, setDesc] = useState('');
  const [reporter, setReporter] = useState('');

  const handleSubmit = useCallback(async () => {
    if (!desc.trim() || !reporter.trim()) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/food-safety/violations', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID, severity, violation_type: vioType,
          description: desc, reporter_name: reporter,
        }),
      });
      onSuccess(`${vioType}问题已上报`);
      setDesc(''); setReporter('');
    } catch (err) { onError(err instanceof Error ? err.message : '提交失败'); }
    finally { setSubmitting(false); }
  }, [severity, vioType, desc, reporter, setSubmitting, onSuccess, onError]);

  return (
    <div style={cardStyle}>
      <h3 style={sectionTitle}>问题上报</h3>
      <Field label="严重程度">
        <div style={{ display: 'flex', gap: 8 }}>
          {SEVERITY_OPTIONS.map(s => (
            <Chip key={s.value} selected={severity === s.value} onClick={() => setSeverity(s.value)} color={s.color}>{s.label}</Chip>
          ))}
        </div>
      </Field>
      <Field label="问题类型">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {VIOLATION_TYPES.map(t => <Chip key={t} selected={vioType === t} onClick={() => setVioType(t)}>{t}</Chip>)}
        </div>
      </Field>
      <Field label="问题描述 *">
        <textarea value={desc} onChange={e => setDesc(e.target.value)} placeholder="详细描述发现的问题..." style={{ ...inputStyle, minHeight: 80, resize: 'vertical' }} />
      </Field>
      <Field label="上报人 *">
        <input value={reporter} onChange={e => setReporter(e.target.value)} placeholder="姓名" style={inputStyle} />
      </Field>
      <SubmitBtn onClick={handleSubmit} disabled={submitting || !desc.trim() || !reporter.trim()} loading={submitting} danger={severity === 'critical'}>
        提交上报
      </SubmitBtn>
    </div>
  );
}

// ─── 通用组件 ───

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', fontSize: 14, color: '#666', marginBottom: 6, fontWeight: 500 }}>{label}</label>
      {children}
    </div>
  );
}

function Chip({ children, selected, onClick, color }: { children: React.ReactNode; selected: boolean; onClick: () => void; color?: string }) {
  const accent = color || '#FF6B35';
  return (
    <button onClick={onClick} style={{
      padding: '8px 16px', borderRadius: 20, border: `1.5px solid ${selected ? accent : '#e8e8e8'}`,
      background: selected ? `${accent}15` : '#fff', color: selected ? accent : '#666',
      fontSize: 15, fontWeight: selected ? 600 : 400, cursor: 'pointer',
    }}>
      {children}
    </button>
  );
}

function SubmitBtn({ children, onClick, disabled, loading, danger }: { children: React.ReactNode; onClick: () => void; disabled: boolean; loading: boolean; danger?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      width: '100%', padding: 14, borderRadius: 10, border: 'none',
      background: disabled ? '#ccc' : danger ? '#ff4d4f' : '#FF6B35',
      color: '#fff', fontSize: 17, fontWeight: 700, cursor: disabled ? 'not-allowed' : 'pointer',
      minHeight: 48, marginTop: 8,
    }}>
      {loading ? '提交中...' : children}
    </button>
  );
}

// ─── 样式 ───
const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.08)' };
const sectionTitle: React.CSSProperties = { margin: '0 0 16px', fontSize: 18, fontWeight: 700, color: '#1a1a1a' };
const inputStyle: React.CSSProperties = { width: '100%', padding: '12px 14px', borderRadius: 8, border: '1.5px solid #e8e8e8', fontSize: 16, outline: 'none', boxSizing: 'border-box', color: '#1a1a1a', background: '#fafafa' };
const miniBtn: React.CSSProperties = { width: 32, height: 32, borderRadius: 6, border: '1px solid #e8e8e8', background: '#f5f5f5', fontSize: 18, fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' };
