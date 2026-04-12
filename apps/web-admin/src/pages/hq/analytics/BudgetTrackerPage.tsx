/**
 * 预算追踪页 — Budget vs Actual
 * 功能: 总预算执行概览 + 分类预算执行表格 + 设置预算 Modal + 执行记录录入
 * 调用 GET /api/v1/finance/budgets/summary  POST /api/v1/finance/budgets  POST /api/v1/finance/budgets/{id}/execute
 */
import { useState, useCallback, useEffect } from 'react';
import { txFetchData } from '../../../api';

// ─── 类型定义 ───

interface BudgetPlan {
  id: string;
  store_id: string;
  period_type: 'monthly' | 'quarterly' | 'yearly';
  period: string;
  category: string;
  budget_amount_fen: number;
  status: 'draft' | 'approved' | 'active' | 'closed';
  created_at: string;
}

interface BudgetProgress {
  budget_id: string;
  budget_amount_fen: number;
  executed_amount_fen: number;
  execution_rate: number; // 0.0–∞
  remaining_fen: number;
  status: 'normal' | 'warning' | 'over_budget';
}

interface BudgetSummary {
  period: string;
  categories: Record<string, BudgetProgress>;
  total: BudgetProgress;
}

interface BudgetFormData {
  store_id: string;
  period_type: 'monthly' | 'quarterly' | 'yearly';
  period: string;
  revenue: string;
  ingredient_cost: string;
  labor_cost: string;
  fixed_cost: string;
  marketing_cost: string;
  total: string;
}

interface ExecuteFormData {
  category: string;
  amount_yuan: string;
  remark: string;
}

// ─── 常量 ───

const CATEGORY_META: Record<string, { label: string; icon: string }> = {
  revenue:         { label: '营收',     icon: '💵' },
  ingredient_cost: { label: '食材成本', icon: '🍜' },
  labor_cost:      { label: '人工成本', icon: '👥' },
  fixed_cost:      { label: '固定成本', icon: '🏢' },
  marketing_cost:  { label: '营销费用', icon: '📣' },
  total:           { label: '总预算',   icon: '📊' },
};

const CATEGORY_ORDER = ['revenue', 'ingredient_cost', 'labor_cost', 'fixed_cost', 'marketing_cost', 'total'];

const STORE_OPTIONS = [
  { id: 'store_001', name: '芙蓉路店' },
  { id: 'store_002', name: '望城店' },
  { id: 'store_003', name: '开福店' },
  { id: 'store_004', name: '岳麓店' },
];

// ─── 工具函数 ───

/** 分转元，千分位格式 */
function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 });
}

/** 元转分 */
function yuanToFen(yuan: string): number {
  const v = parseFloat(yuan);
  return isNaN(v) ? 0 : Math.round(v * 100);
}

/** 获取近6个月列表（YYYY-MM 格式），最新在前 */
function getRecentMonths(): string[] {
  const months: string[] = [];
  const now = new Date();
  for (let i = 0; i < 6; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    months.push(`${y}-${m}`);
  }
  return months;
}

/** 本月 YYYY-MM */
function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

/** 本季 YYYY-Qn */
function currentQuarter(): string {
  const now = new Date();
  const q = Math.floor(now.getMonth() / 3) + 1;
  return `${now.getFullYear()}-Q${q}`;
}

/** 本年 YYYY */
function currentYear(): string {
  return String(new Date().getFullYear());
}

/** 执行率转颜色 */
function rateColor(rate: number): string {
  if (rate > 1.0) return '#FF4D4D';
  if (rate >= 0.8) return '#BA7517';
  return '#0F6E56';
}

function rateStatusLabel(status: 'normal' | 'warning' | 'over_budget'): string {
  if (status === 'over_budget') return '⚠️ 超支';
  if (status === 'warning')    return '🟡 警告';
  return '🟢 正常';
}

function rateStatusColor(status: 'normal' | 'warning' | 'over_budget'): string {
  if (status === 'over_budget') return '#FF4D4D';
  if (status === 'warning')    return '#BA7517';
  return '#0F6E56';
}

// ─── 进度条组件 ───

function ProgressBar({ rate }: { rate: number }) {
  const pct = Math.min(100, rate * 100);
  const color = rateColor(rate);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        flex: 1, height: 8, background: '#0d1e28', borderRadius: 4, overflow: 'hidden', minWidth: 80,
      }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 4, background: color,
          transition: 'width 0.4s ease',
        }} />
      </div>
      <span style={{ fontSize: 12, color, minWidth: 38, textAlign: 'right' }}>
        {(rate * 100).toFixed(1)}%
      </span>
    </div>
  );
}

// ─── 设置预算 Modal ───

interface BudgetModalProps {
  onClose: () => void;
  onSaved: () => void;
}

function BudgetModal({ onClose, onSaved }: BudgetModalProps) {
  const [form, setForm] = useState<BudgetFormData>({
    store_id: STORE_OPTIONS[0].id,
    period_type: 'monthly',
    period: currentMonth(),
    revenue: '',
    ingredient_cost: '',
    labor_cost: '',
    fixed_cost: '',
    marketing_cost: '',
    total: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleChange = (field: keyof BudgetFormData, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }));
    // 自动填充周期默认值
    if (field === 'period_type') {
      if (value === 'monthly')   setForm(prev => ({ ...prev, period_type: 'monthly',   period: currentMonth() }));
      if (value === 'quarterly') setForm(prev => ({ ...prev, period_type: 'quarterly', period: currentQuarter() }));
      if (value === 'yearly')    setForm(prev => ({ ...prev, period_type: 'yearly',    period: currentYear() }));
    }
  };

  const handleSave = async (submitForApproval: boolean) => {
    setSaving(true);
    setError('');
    try {
      const categories = ['revenue', 'ingredient_cost', 'labor_cost', 'fixed_cost', 'marketing_cost', 'total'] as const;
      const payloads = categories
        .filter(cat => form[cat] !== '')
        .map(cat => ({
          store_id: form.store_id,
          period_type: form.period_type,
          period: form.period,
          category: cat,
          budget_amount_fen: yuanToFen(form[cat]),
          submit_for_approval: submitForApproval,
        }));

      if (payloads.length === 0) {
        setError('请至少填写一个类别的预算金额');
        setSaving(false);
        return;
      }

      await Promise.all(payloads.map(p =>
        txFetchData<BudgetPlan>('/api/v1/finance/budgets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(p),
        })
      ));
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px', borderRadius: 6,
    border: '1px solid #2a3a44', background: '#0d1e28',
    color: '#fff', fontSize: 13, outline: 'none', boxSizing: 'border-box',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block', color: '#888', fontSize: 12, marginBottom: 4,
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: 28, width: 520,
        maxHeight: '90vh', overflow: 'auto', border: '1px solid #2a3a44',
      }}>
        {/* 标题 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>设置预算计划</h3>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: '#888', fontSize: 20, cursor: 'pointer', padding: 0,
          }}>×</button>
        </div>

        {/* 门店 */}
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>门店</label>
          <select value={form.store_id} onChange={e => handleChange('store_id', e.target.value)} style={inputStyle}>
            {STORE_OPTIONS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>

        {/* 周期类型 */}
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>周期类型</label>
          <div style={{ display: 'flex', gap: 10 }}>
            {(['monthly', 'quarterly', 'yearly'] as const).map(pt => (
              <label key={pt} style={{
                display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                padding: '6px 14px', borderRadius: 6,
                background: form.period_type === pt ? '#0F6E5622' : '#0d1e28',
                border: `1px solid ${form.period_type === pt ? '#0F6E56' : '#2a3a44'}`,
                color: form.period_type === pt ? '#0F6E56' : '#888',
                fontSize: 13,
              }}>
                <input
                  type="radio" name="period_type" value={pt}
                  checked={form.period_type === pt}
                  onChange={e => handleChange('period_type', e.target.value)}
                  style={{ display: 'none' }}
                />
                {pt === 'monthly' ? '月度' : pt === 'quarterly' ? '季度' : '年度'}
              </label>
            ))}
          </div>
        </div>

        {/* 周期值 */}
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>
            周期值
            <span style={{ marginLeft: 6, color: '#555', fontSize: 11 }}>
              {form.period_type === 'monthly' ? '格式: YYYY-MM' : form.period_type === 'quarterly' ? '格式: YYYY-Q1' : '格式: YYYY'}
            </span>
          </label>
          <input
            type="text" value={form.period}
            onChange={e => handleChange('period', e.target.value)}
            style={inputStyle}
            placeholder={form.period_type === 'monthly' ? '如 2026-04' : form.period_type === 'quarterly' ? '如 2026-Q2' : '如 2026'}
          />
        </div>

        {/* 各类别预算 */}
        <div style={{ marginBottom: 8, color: '#888', fontSize: 12 }}>各类别预算金额（元，留空则不设置）</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
          {(['revenue', 'ingredient_cost', 'labor_cost', 'fixed_cost', 'marketing_cost', 'total'] as const).map(cat => (
            <div key={cat}>
              <label style={labelStyle}>
                {CATEGORY_META[cat].icon} {CATEGORY_META[cat].label}
              </label>
              <input
                type="number" min="0" step="0.01"
                value={form[cat]}
                onChange={e => handleChange(cat, e.target.value)}
                style={inputStyle}
                placeholder="输入金额（元）"
              />
            </div>
          ))}
        </div>

        {error && (
          <div style={{ color: '#FF4D4D', fontSize: 13, marginBottom: 12 }}>{error}</div>
        )}

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{
            padding: '8px 20px', borderRadius: 6, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13,
          }}>
            取消
          </button>
          <button onClick={() => handleSave(false)} disabled={saving} style={{
            padding: '8px 20px', borderRadius: 6, border: '1px solid #2a3a44',
            background: '#1a2a33', color: '#ccc', cursor: saving ? 'not-allowed' : 'pointer', fontSize: 13,
          }}>
            {saving ? '保存中...' : '保存草稿'}
          </button>
          <button onClick={() => handleSave(true)} disabled={saving} style={{
            padding: '8px 20px', borderRadius: 6, border: 'none',
            background: saving ? '#0F6E5666' : '#0F6E56', color: '#fff',
            cursor: saving ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 600,
          }}>
            {saving ? '提交中...' : '提交审批'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 执行记录录入区 ───

interface ExecuteSectionProps {
  budgets: BudgetPlan[];
  onRecorded: () => void;
}

function ExecuteSection({ budgets, onRecorded }: ExecuteSectionProps) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ExecuteFormData>({ category: 'ingredient_cost', amount_yuan: '', remark: '' });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  const handleRecord = async () => {
    if (!form.amount_yuan) { setMsg('请输入金额'); return; }
    // 找匹配的预算 id
    const matched = budgets.find(b => b.category === form.category);
    if (!matched) { setMsg('未找到对应预算，请先设置预算'); return; }

    setSaving(true);
    setMsg('');
    try {
      await txFetchData(`/api/v1/finance/budgets/${matched.id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          executed_amount_fen: yuanToFen(form.amount_yuan),
          remark: form.remark,
        }),
      });
      setMsg('✅ 记录成功');
      setForm({ category: 'ingredient_cost', amount_yuan: '', remark: '' });
      onRecorded();
    } catch (e: unknown) {
      setMsg(e instanceof Error ? e.message : '记录失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    padding: '7px 10px', borderRadius: 6, border: '1px solid #2a3a44',
    background: '#0d1e28', color: '#fff', fontSize: 13, outline: 'none',
  };

  return (
    <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', marginTop: 20 }}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          padding: '14px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          cursor: 'pointer', userSelect: 'none',
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 600 }}>📝 录入执行记录</span>
        <span style={{ color: '#888', fontSize: 13 }}>{open ? '▲ 收起' : '▼ 展开'}</span>
      </div>

      {open && (
        <div style={{ padding: '0 20px 20px', borderTop: '1px solid #2a3a44' }}>
          <div style={{ display: 'flex', gap: 12, marginTop: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            {/* 类别 */}
            <div>
              <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>预算类别</div>
              <select
                value={form.category}
                onChange={e => setForm(prev => ({ ...prev, category: e.target.value }))}
                style={{ ...inputStyle, minWidth: 130 }}
              >
                {CATEGORY_ORDER.map(cat => (
                  <option key={cat} value={cat}>
                    {CATEGORY_META[cat].icon} {CATEGORY_META[cat].label}
                  </option>
                ))}
              </select>
            </div>

            {/* 金额 */}
            <div>
              <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>实际执行金额（元）</div>
              <input
                type="number" min="0" step="0.01"
                value={form.amount_yuan}
                onChange={e => setForm(prev => ({ ...prev, amount_yuan: e.target.value }))}
                placeholder="如 38500.00"
                style={{ ...inputStyle, width: 140 }}
              />
            </div>

            {/* 备注 */}
            <div style={{ flex: 1, minWidth: 160 }}>
              <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>备注（可选）</div>
              <input
                type="text"
                value={form.remark}
                onChange={e => setForm(prev => ({ ...prev, remark: e.target.value }))}
                placeholder="备注说明..."
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
              />
            </div>

            {/* 按钮 */}
            <button onClick={handleRecord} disabled={saving} style={{
              padding: '8px 20px', borderRadius: 6, border: 'none',
              background: saving ? '#185FA566' : '#185FA5', color: '#fff',
              cursor: saving ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 600,
              flexShrink: 0,
            }}>
              {saving ? '记录中...' : '记录执行'}
            </button>
          </div>

          {msg && (
            <div style={{
              marginTop: 10, fontSize: 13,
              color: msg.startsWith('✅') ? '#0F6E56' : '#FF4D4D',
            }}>
              {msg}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───

export function BudgetTrackerPage() {
  const months = getRecentMonths();
  const [storeId, setStoreId] = useState(STORE_OPTIONS[0].id);
  const [periodType, setPeriodType] = useState<'monthly' | 'quarterly' | 'yearly'>('monthly');
  const [period, setPeriod] = useState(currentMonth());
  const [summary, setSummary] = useState<BudgetSummary | null>(null);
  const [budgets, setBudgets] = useState<BudgetPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState('');

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ store_id: storeId, period });
      const data = await txFetchData<BudgetSummary>(`/api/v1/finance/budgets/summary?${params}`);
      setSummary(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [storeId, period]);

  const fetchBudgets = useCallback(async () => {
    try {
      const params = new URLSearchParams({ store_id: storeId, period });
      const data = await txFetchData<{ items: BudgetPlan[] }>(`/api/v1/finance/budgets?${params}`);
      setBudgets(data.items || []);
    } catch {
      setBudgets([]);
    }
  }, [storeId, period]);

  useEffect(() => {
    fetchSummary();
    fetchBudgets();
  }, [fetchSummary, fetchBudgets]);

  const handlePeriodTypeChange = (pt: 'monthly' | 'quarterly' | 'yearly') => {
    setPeriodType(pt);
    if (pt === 'monthly')   setPeriod(currentMonth());
    if (pt === 'quarterly') setPeriod(currentQuarter());
    if (pt === 'yearly')    setPeriod(currentYear());
  };

  const total = summary?.total;
  const hasData = total && total.budget_amount_fen > 0;

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>

      {/* ── 页头 ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>📊 预算追踪</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>Budget vs Actual · 预算执行监控</p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* 门店选择 */}
          <select
            value={storeId}
            onChange={e => setStoreId(e.target.value)}
            style={{
              padding: '7px 12px', borderRadius: 6, border: '1px solid #2a3a44',
              background: '#1a2a33', color: '#fff', fontSize: 13, cursor: 'pointer', outline: 'none',
            }}
          >
            {STORE_OPTIONS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>

          {/* 周期类型 */}
          <div style={{ display: 'flex', border: '1px solid #2a3a44', borderRadius: 6, overflow: 'hidden' }}>
            {(['monthly', 'quarterly', 'yearly'] as const).map((pt, i) => (
              <button
                key={pt}
                onClick={() => handlePeriodTypeChange(pt)}
                style={{
                  padding: '7px 14px', fontSize: 13, border: 'none',
                  borderLeft: i > 0 ? '1px solid #2a3a44' : 'none',
                  background: periodType === pt ? '#185FA5' : '#1a2a33',
                  color: periodType === pt ? '#fff' : '#888',
                  cursor: 'pointer',
                }}
              >
                {pt === 'monthly' ? '本月' : pt === 'quarterly' ? '本季' : '本年'}
              </button>
            ))}
          </div>

          {/* 月份下拉（仅月度） */}
          {periodType === 'monthly' && (
            <select
              value={period}
              onChange={e => setPeriod(e.target.value)}
              style={{
                padding: '7px 12px', borderRadius: 6, border: '1px solid #2a3a44',
                background: '#1a2a33', color: '#fff', fontSize: 13, cursor: 'pointer', outline: 'none',
              }}
            >
              {months.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          )}

          {/* 设置预算 */}
          <button
            onClick={() => setShowModal(true)}
            style={{
              padding: '8px 16px', borderRadius: 6, border: 'none',
              background: '#0F6E56', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600,
            }}
          >
            + 设置预算
          </button>
        </div>
      </div>

      {/* ── 加载 / 错误 ── */}
      {loading && (
        <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
      )}
      {error && !loading && (
        <div style={{
          background: '#FF4D4D22', border: '1px solid #FF4D4D44', borderRadius: 8,
          padding: '12px 16px', color: '#FF4D4D', marginBottom: 20, fontSize: 14,
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* ── 无数据提示 ── */}
      {!loading && !error && !hasData && (
        <div style={{
          textAlign: 'center', padding: '60px 24px', background: '#1a2a33',
          borderRadius: 12, border: '2px dashed #2a3a44',
        }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
          <div style={{ fontSize: 16, color: '#ccc', marginBottom: 8 }}>
            {period} 尚未设置预算
          </div>
          <div style={{ color: '#888', fontSize: 13, marginBottom: 20 }}>
            点击「+ 设置预算」开始为本期设置预算目标
          </div>
          <button
            onClick={() => setShowModal(true)}
            style={{
              padding: '10px 24px', borderRadius: 8, border: 'none',
              background: '#0F6E56', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 600,
            }}
          >
            + 设置预算
          </button>
        </div>
      )}

      {/* ── Section 1：总预算执行概览 ── */}
      {!loading && hasData && total && (
        <div style={{
          background: '#1a2a33',
          border: `2px solid ${rateStatusColor(total.status)}44`,
          borderRadius: 12, padding: '20px 24px', marginBottom: 20,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            {/* 左：金额 */}
            <div>
              <div style={{ color: '#888', fontSize: 13, marginBottom: 4 }}>本期总预算</div>
              <div style={{ fontSize: 28, fontWeight: 700 }}>
                ¥ {fenToYuan(total.budget_amount_fen)}
              </div>
              <div style={{ color: '#888', fontSize: 13, marginTop: 8 }}>
                已执行：<span style={{ color: '#fff' }}>¥ {fenToYuan(total.executed_amount_fen)}</span>
                &nbsp;·&nbsp;
                剩余：<span style={{ color: total.remaining_fen < 0 ? '#FF4D4D' : '#0F6E56' }}>
                  ¥ {fenToYuan(Math.abs(total.remaining_fen))}{total.remaining_fen < 0 ? '（超支）' : ''}
                </span>
              </div>
            </div>

            {/* 右：执行进度 */}
            <div style={{ textAlign: 'right', minWidth: 180 }}>
              <div style={{ color: '#888', fontSize: 13, marginBottom: 4 }}>执行进度</div>
              <div style={{ fontSize: 32, fontWeight: 700, color: rateColor(total.execution_rate) }}>
                {(total.execution_rate * 100).toFixed(1)}%
              </div>
              <div style={{ marginTop: 4 }}>
                <span style={{
                  padding: '3px 12px', borderRadius: 12, fontSize: 13, fontWeight: 600,
                  background: `${rateStatusColor(total.status)}22`,
                  color: rateStatusColor(total.status),
                }}>
                  {rateStatusLabel(total.status)}
                </span>
              </div>
            </div>
          </div>

          {/* 进度条 */}
          <div style={{ marginTop: 16 }}>
            <div style={{ height: 12, background: '#0d1e28', borderRadius: 6, overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(100, total.execution_rate * 100)}%`,
                height: '100%', borderRadius: 6,
                background: rateColor(total.execution_rate),
                transition: 'width 0.5s ease',
              }} />
            </div>
          </div>
        </div>
      )}

      {/* ── Section 2：分类预算执行表格 ── */}
      {!loading && hasData && summary && (
        <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', marginBottom: 20 }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid #2a3a44', fontSize: 14, color: '#888' }}>
            分类预算执行明细 · {period}
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#0d1e28' }}>
                {['类别', '预算金额', '已执行', '执行率', '进度', '状态'].map(h => (
                  <th key={h} style={{
                    padding: '10px 16px', textAlign: 'left',
                    color: '#888', fontSize: 12, fontWeight: 500,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CATEGORY_ORDER.map(cat => {
                const prog = summary.categories[cat];
                if (!prog) return null;
                const meta = CATEGORY_META[cat];
                const isOver = prog.status === 'over_budget';

                return (
                  <tr
                    key={cat}
                    style={{
                      borderBottom: '1px solid #2a3a4440',
                      background: isOver ? '#FF4D4D11' : 'transparent',
                    }}
                  >
                    {/* 类别 */}
                    <td style={{ padding: '14px 16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 18 }}>{meta.icon}</span>
                        <span style={{ fontWeight: 600, fontSize: 14 }}>{meta.label}</span>
                      </div>
                    </td>

                    {/* 预算金额 */}
                    <td style={{ padding: '14px 16px', color: '#ccc', fontSize: 13 }}>
                      ¥ {fenToYuan(prog.budget_amount_fen)}
                    </td>

                    {/* 已执行 */}
                    <td style={{ padding: '14px 16px', fontSize: 13 }}>
                      <span style={{ color: isOver ? '#FF4D4D' : '#fff', fontWeight: isOver ? 700 : 400 }}>
                        ¥ {fenToYuan(prog.executed_amount_fen)}
                      </span>
                    </td>

                    {/* 执行率 */}
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{
                        fontSize: 14, fontWeight: 700,
                        color: rateColor(prog.execution_rate),
                      }}>
                        {(prog.execution_rate * 100).toFixed(1)}%
                      </span>
                    </td>

                    {/* 进度条 */}
                    <td style={{ padding: '14px 16px', minWidth: 140 }}>
                      <ProgressBar rate={prog.execution_rate} />
                    </td>

                    {/* 状态 */}
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{
                        padding: '3px 10px', borderRadius: 12, fontSize: 12,
                        background: `${rateStatusColor(prog.status)}22`,
                        color: rateStatusColor(prog.status),
                        fontWeight: 600,
                      }}>
                        {rateStatusLabel(prog.status)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Section 4：执行记录录入 ── */}
      {!loading && (
        <ExecuteSection budgets={budgets} onRecorded={() => { fetchSummary(); fetchBudgets(); }} />
      )}

      {/* ── 图例说明 ── */}
      {!loading && (
        <div style={{ display: 'flex', gap: 20, marginTop: 16, color: '#888', fontSize: 12 }}>
          <span>● <span style={{ color: '#0F6E56' }}>正常</span>：执行率 &lt; 80%</span>
          <span>● <span style={{ color: '#BA7517' }}>警告</span>：执行率 80%–100%</span>
          <span>● <span style={{ color: '#FF4D4D' }}>超支</span>：执行率 &gt; 100%</span>
        </div>
      )}

      {/* ── Modal ── */}
      {showModal && (
        <BudgetModal
          onClose={() => setShowModal(false)}
          onSaved={() => { fetchSummary(); fetchBudgets(); }}
        />
      )}
    </div>
  );
}
