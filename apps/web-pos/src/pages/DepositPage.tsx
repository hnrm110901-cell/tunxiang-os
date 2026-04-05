/**
 * 押金管理页面 — POS端
 * 三 Tab 布局：押金列表 / 收取押金 / 押金台账
 * 右侧详情面板：押金详情 + 操作按钮（抵扣/退款/转收入）
 */
import { useState, useEffect, useCallback } from 'react';
import { useAuthStore } from '../store/authStore';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '';

async function txFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const employee = useAuthStore.getState().employee;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(TENANT ? { 'X-Tenant-ID': TENANT } : {}),
    ...(employee ? { 'X-Operator-ID': employee.id } : {}),
  };
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers as Record<string, string> || {}) },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const fen2yuanNum = (fen: number) => (fen / 100).toFixed(2);

// ── 类型 ──

interface Deposit {
  id: string;
  customer_id: string | null;
  reservation_id: string | null;
  order_id: string | null;
  amount_fen: number;
  applied_amount_fen: number;
  refunded_amount_fen: number;
  remaining_fen: number;
  status: string;
  payment_method: string;
  collected_at: string;
  expires_at: string;
  operator_id: string;
}

interface DepositDetail extends Deposit {
  store_id: string;
  payment_ref: string | null;
  remark: string | null;
  created_at: string;
  updated_at: string;
}

interface LedgerData {
  store_id: string;
  start_date: string;
  end_date: string;
  total_count: number;
  total_collected_fen: number;
  total_applied_fen: number;
  total_refunded_fen: number;
  total_converted_fen: number;
  total_outstanding_fen: number;
}

interface AgingBucket {
  count: number;
  amount_fen: number;
}

interface AgingData {
  store_id: string;
  aging: {
    '0_7_days': AgingBucket;
    '8_30_days': AgingBucket;
    '31_90_days': AgingBucket;
    over_90_days: AgingBucket;
  };
}

type Tab = 'list' | 'collect' | 'ledger';

const STATUS_MAP: Record<string, { label: string; color: string; bg: string }> = {
  collected:          { label: '已收',   color: '#4ade80', bg: '#4ade8022' },
  partially_applied:  { label: '部分抵扣', color: '#faad14', bg: '#faad1422' },
  fully_applied:      { label: '已用',   color: '#185FA5', bg: '#185FA522' },
  refunded:           { label: '已退',   color: '#ef4444', bg: '#ef444422' },
  converted:          { label: '已转',   color: '#a78bfa', bg: '#a78bfa22' },
  written_off:        { label: '已核销', color: '#6b7280', bg: '#6b728022' },
};

const PAYMENT_LABELS: Record<string, string> = {
  wechat: '微信', alipay: '支付宝', cash: '现金', card: '银行卡',
};

const STATUS_FILTERS = [
  { key: '', label: '全部' },
  { key: 'collected', label: '已收' },
  { key: 'partially_applied', label: '部分抵扣' },
  { key: 'fully_applied', label: '已用' },
  { key: 'refunded', label: '已退' },
  { key: 'converted', label: '已转' },
];

// ── 样式常量 ──

const colors = {
  bg: '#0B1A20',
  card: '#112228',
  cardHover: '#152E36',
  border: '#1E3A45',
  accent: '#FF6B2C',
  accentHover: '#FF8B5C',
  textPrimary: '#E0E7EB',
  textSecondary: '#6B8A99',
  textMuted: '#3D5A68',
  danger: '#ef4444',
  dangerBg: '#ef444422',
  success: '#4ade80',
  successBg: '#4ade8022',
  info: '#38bdf8',
  infoBg: '#38bdf822',
};

export function DepositPage() {
  const [tab, setTab] = useState<Tab>('list');
  const [deposits, setDeposits] = useState<Deposit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [selected, setSelected] = useState<DepositDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // ── Tab 1: List ──

  const loadDeposits = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page: '1', size: '50' });
      if (statusFilter) params.set('status', statusFilter);
      const data = await txFetch<{ items: Deposit[]; total: number }>(
        `/api/v1/deposits/store/${STORE_ID}?${params.toString()}`,
      );
      setDeposits(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载押金列表失败');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { loadDeposits(); }, [loadDeposits]);

  const loadDetail = async (id: string) => {
    setDetailLoading(true);
    try {
      const data = await txFetch<DepositDetail>(`/api/v1/deposits/${id}`);
      setSelected(data);
    } catch (err) {
      alert(err instanceof Error ? err.message : '加载详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  // ── Tab 2: Collect Form ──

  const [form, setForm] = useState({
    customer_name: '',
    phone: '',
    amount_yuan: '',
    payment_method: 'cash',
    reservation_id: '',
    remark: '',
  });
  const [collecting, setCollecting] = useState(false);

  const handleCollect = async () => {
    const amountYuan = parseFloat(form.amount_yuan);
    if (!amountYuan || amountYuan <= 0) { alert('请输入有效金额'); return; }
    setCollecting(true);
    try {
      await txFetch('/api/v1/deposits/', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID,
          amount_fen: Math.round(amountYuan * 100),
          payment_method: form.payment_method,
          reservation_id: form.reservation_id || undefined,
          remark: [form.customer_name, form.phone, form.remark].filter(Boolean).join(' | ') || undefined,
        }),
      });
      alert('押金收取成功');
      setForm({ customer_name: '', phone: '', amount_yuan: '', payment_method: 'cash', reservation_id: '', remark: '' });
      setTab('list');
      loadDeposits();
    } catch (err) {
      alert(err instanceof Error ? err.message : '押金收取失败');
    } finally {
      setCollecting(false);
    }
  };

  // ── Tab 3: Ledger ──

  const [ledger, setLedger] = useState<LedgerData | null>(null);
  const [aging, setAging] = useState<AgingData | null>(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  const loadLedger = useCallback(async () => {
    setLedgerLoading(true);
    try {
      const today = new Date();
      const end = today.toISOString().split('T')[0];
      const start = new Date(today.getFullYear(), today.getMonth() - 3, today.getDate())
        .toISOString().split('T')[0];
      const [ledgerData, agingData] = await Promise.all([
        txFetch<LedgerData>(`/api/v1/deposits/report/ledger?store_id=${STORE_ID}&start_date=${start}&end_date=${end}`),
        txFetch<AgingData>(`/api/v1/deposits/report/aging?store_id=${STORE_ID}`),
      ]);
      setLedger(ledgerData);
      setAging(agingData);
    } catch (err) {
      alert(err instanceof Error ? err.message : '加载台账失败');
    } finally {
      setLedgerLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'ledger') loadLedger();
  }, [tab, loadLedger]);

  // ── Detail Actions ──

  const [actionLoading, setActionLoading] = useState(false);
  const [applyModal, setApplyModal] = useState(false);
  const [refundModal, setRefundModal] = useState(false);
  const [applyForm, setApplyForm] = useState({ order_id: '', amount_yuan: '' });
  const [refundForm, setRefundForm] = useState({ amount_yuan: '', remark: '' });

  const handleApply = async () => {
    if (!selected) return;
    const amountFen = Math.round(parseFloat(applyForm.amount_yuan) * 100);
    if (!amountFen || amountFen <= 0) { alert('请输入有效金额'); return; }
    if (!applyForm.order_id.trim()) { alert('请输入订单ID'); return; }
    setActionLoading(true);
    try {
      await txFetch(`/api/v1/deposits/${selected.id}/apply`, {
        method: 'POST',
        body: JSON.stringify({ order_id: applyForm.order_id, apply_amount_fen: amountFen }),
      });
      alert('抵扣成功');
      setApplyModal(false);
      setApplyForm({ order_id: '', amount_yuan: '' });
      await loadDetail(selected.id);
      loadDeposits();
    } catch (err) {
      alert(err instanceof Error ? err.message : '抵扣失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRefund = async () => {
    if (!selected) return;
    const amountFen = Math.round(parseFloat(refundForm.amount_yuan) * 100);
    if (!amountFen || amountFen <= 0) { alert('请输入有效金额'); return; }
    setActionLoading(true);
    try {
      await txFetch(`/api/v1/deposits/${selected.id}/refund`, {
        method: 'POST',
        body: JSON.stringify({ refund_amount_fen: amountFen, remark: refundForm.remark || undefined }),
      });
      alert('退款成功');
      setRefundModal(false);
      setRefundForm({ amount_yuan: '', remark: '' });
      await loadDetail(selected.id);
      loadDeposits();
    } catch (err) {
      alert(err instanceof Error ? err.message : '退款失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleConvert = async () => {
    if (!selected) return;
    if (!confirm(`确认将余额 ${fen2yuan(selected.remaining_fen)} 转为收入？此操作不可撤销。`)) return;
    setActionLoading(true);
    try {
      await txFetch(`/api/v1/deposits/${selected.id}/convert`, {
        method: 'POST',
        body: JSON.stringify({ remark: '手动转收入' }),
      });
      alert('转收入成功');
      await loadDetail(selected.id);
      loadDeposits();
    } catch (err) {
      alert(err instanceof Error ? err.message : '转收入失败');
    } finally {
      setActionLoading(false);
    }
  };

  // ── 渲染 ──

  const statusCfg = (s: string) => STATUS_MAP[s] || { label: s, color: '#6b7280', bg: '#6b728022' };

  const canApply = selected && ['collected', 'partially_applied'].includes(selected.status) && selected.remaining_fen > 0;
  const canRefund = selected && !['refunded', 'fully_applied', 'converted', 'written_off'].includes(selected.status) && selected.remaining_fen > 0;
  const canConvert = selected && !['refunded', 'converted', 'written_off'].includes(selected.status) && selected.remaining_fen > 0;

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 44px)', background: colors.bg, color: colors.textPrimary }}>
      {/* ── 左侧主区域 ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Tab 栏 */}
        <div style={{ display: 'flex', gap: '0', borderBottom: `1px solid ${colors.border}`, background: colors.card }}>
          {([
            { key: 'list' as Tab, label: '押金列表' },
            { key: 'collect' as Tab, label: '收取押金' },
            { key: 'ledger' as Tab, label: '押金台账' },
          ]).map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: '14px 28px',
                background: tab === t.key ? colors.bg : 'transparent',
                color: tab === t.key ? colors.accent : colors.textSecondary,
                border: 'none',
                borderBottom: tab === t.key ? `2px solid ${colors.accent}` : '2px solid transparent',
                fontSize: '14px',
                fontWeight: tab === t.key ? 600 : 400,
                cursor: 'pointer',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab 内容 */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px' }}>

          {/* ── Tab 1: 押金列表 ── */}
          {tab === 'list' && (
            <div>
              {/* 状态筛选 */}
              <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
                {STATUS_FILTERS.map(f => (
                  <button
                    key={f.key}
                    onClick={() => setStatusFilter(f.key)}
                    style={{
                      padding: '6px 16px',
                      borderRadius: '6px',
                      border: `1px solid ${statusFilter === f.key ? colors.accent : colors.border}`,
                      background: statusFilter === f.key ? `${colors.accent}22` : colors.card,
                      color: statusFilter === f.key ? colors.accent : colors.textSecondary,
                      fontSize: '13px',
                      cursor: 'pointer',
                    }}
                  >
                    {f.label}
                  </button>
                ))}
              </div>

              {loading && <div style={{ color: colors.textSecondary, padding: '40px', textAlign: 'center' }}>加载中...</div>}
              {error && <div style={{ color: colors.danger, padding: '40px', textAlign: 'center' }}>{error}</div>}

              {!loading && !error && deposits.length === 0 && (
                <div style={{ color: colors.textMuted, padding: '60px', textAlign: 'center', fontSize: '14px' }}>
                  暂无押金记录
                </div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {deposits.map(d => {
                  const sc = statusCfg(d.status);
                  const isActive = selected?.id === d.id;
                  return (
                    <div
                      key={d.id}
                      onClick={() => loadDetail(d.id)}
                      style={{
                        background: isActive ? colors.cardHover : colors.card,
                        border: `1px solid ${isActive ? colors.accent : colors.border}`,
                        borderRadius: '8px',
                        padding: '14px 16px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        transition: 'border-color 0.15s',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        {/* 金额 */}
                        <div style={{ minWidth: '90px' }}>
                          <div style={{ fontSize: '18px', fontWeight: 700, color: colors.textPrimary }}>
                            {fen2yuan(d.amount_fen)}
                          </div>
                          {d.remaining_fen > 0 && d.remaining_fen < d.amount_fen && (
                            <div style={{ fontSize: '11px', color: colors.textSecondary, marginTop: '2px' }}>
                              余额 {fen2yuan(d.remaining_fen)}
                            </div>
                          )}
                        </div>
                        {/* 信息 */}
                        <div>
                          <div style={{ fontSize: '13px', color: colors.textPrimary }}>
                            {PAYMENT_LABELS[d.payment_method] || d.payment_method}
                            {d.reservation_id && (
                              <span style={{ color: colors.textMuted, fontSize: '11px', marginLeft: '8px' }}>
                                预订 {d.reservation_id.slice(0, 8)}...
                              </span>
                            )}
                            {d.order_id && (
                              <span style={{ color: colors.textMuted, fontSize: '11px', marginLeft: '8px' }}>
                                订单 {d.order_id.slice(0, 8)}...
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: '11px', color: colors.textSecondary, marginTop: '4px' }}>
                            {new Date(d.collected_at).toLocaleString('zh-CN')}
                          </div>
                        </div>
                      </div>
                      {/* 状态 */}
                      <span style={{
                        padding: '3px 10px',
                        borderRadius: '4px',
                        fontSize: '12px',
                        fontWeight: 500,
                        background: sc.bg,
                        color: sc.color,
                      }}>
                        {sc.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Tab 2: 收取押金 ── */}
          {tab === 'collect' && (
            <div style={{ maxWidth: '520px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '20px', color: colors.textPrimary }}>
                收取押金
              </h3>

              {/* 客户姓名 */}
              <div style={{ marginBottom: '16px' }}>
                <label style={labelStyle}>客户姓名</label>
                <input
                  value={form.customer_name}
                  onChange={e => setForm(p => ({ ...p, customer_name: e.target.value }))}
                  placeholder="选填"
                  style={inputStyle}
                />
              </div>

              {/* 联系电话 */}
              <div style={{ marginBottom: '16px' }}>
                <label style={labelStyle}>联系电话</label>
                <input
                  value={form.phone}
                  onChange={e => setForm(p => ({ ...p, phone: e.target.value }))}
                  placeholder="选填"
                  style={inputStyle}
                />
              </div>

              {/* 金额 */}
              <div style={{ marginBottom: '16px' }}>
                <label style={labelStyle}>押金金额（元）<span style={{ color: colors.danger }}>*</span></label>
                <input
                  type="number"
                  value={form.amount_yuan}
                  onChange={e => setForm(p => ({ ...p, amount_yuan: e.target.value }))}
                  placeholder="0.00"
                  min="0"
                  step="0.01"
                  style={inputStyle}
                />
              </div>

              {/* 支付方式 */}
              <div style={{ marginBottom: '16px' }}>
                <label style={labelStyle}>支付方式</label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  {(['cash', 'wechat', 'alipay', 'card'] as const).map(m => (
                    <button
                      key={m}
                      onClick={() => setForm(p => ({ ...p, payment_method: m }))}
                      style={{
                        padding: '8px 18px',
                        borderRadius: '6px',
                        border: `1px solid ${form.payment_method === m ? colors.accent : colors.border}`,
                        background: form.payment_method === m ? `${colors.accent}22` : colors.card,
                        color: form.payment_method === m ? colors.accent : colors.textSecondary,
                        fontSize: '13px',
                        cursor: 'pointer',
                      }}
                    >
                      {PAYMENT_LABELS[m]}
                    </button>
                  ))}
                </div>
              </div>

              {/* 关联预订 */}
              <div style={{ marginBottom: '16px' }}>
                <label style={labelStyle}>关联预订ID</label>
                <input
                  value={form.reservation_id}
                  onChange={e => setForm(p => ({ ...p, reservation_id: e.target.value }))}
                  placeholder="选填，输入预订ID"
                  style={inputStyle}
                />
              </div>

              {/* 备注 */}
              <div style={{ marginBottom: '24px' }}>
                <label style={labelStyle}>备注</label>
                <input
                  value={form.remark}
                  onChange={e => setForm(p => ({ ...p, remark: e.target.value }))}
                  placeholder="选填"
                  style={inputStyle}
                />
              </div>

              {/* 提交 */}
              <button
                onClick={handleCollect}
                disabled={collecting || !form.amount_yuan}
                style={{
                  width: '100%',
                  padding: '14px',
                  borderRadius: '8px',
                  border: 'none',
                  background: collecting || !form.amount_yuan ? colors.textMuted : colors.accent,
                  color: '#fff',
                  fontSize: '15px',
                  fontWeight: 600,
                  cursor: collecting || !form.amount_yuan ? 'not-allowed' : 'pointer',
                }}
              >
                {collecting ? '处理中...' : '确认收取'}
              </button>
            </div>
          )}

          {/* ── Tab 3: 押金台账 ── */}
          {tab === 'ledger' && (
            <div>
              {ledgerLoading && <div style={{ color: colors.textSecondary, padding: '40px', textAlign: 'center' }}>加载中...</div>}

              {!ledgerLoading && ledger && (
                <>
                  {/* 汇总卡片 */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '24px' }}>
                    <SummaryCard label="累计收取" value={fen2yuan(ledger.total_collected_fen)} color={colors.success} />
                    <SummaryCard label="已抵扣" value={fen2yuan(ledger.total_applied_fen)} color={colors.info} />
                    <SummaryCard label="已退还" value={fen2yuan(ledger.total_refunded_fen)} color={colors.danger} />
                    <SummaryCard label="在途余额" value={fen2yuan(ledger.total_outstanding_fen)} color={colors.accent} />
                  </div>

                  {/* 额外指标 */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px', marginBottom: '24px' }}>
                    <SummaryCard label="已转收入" value={fen2yuan(ledger.total_converted_fen)} color="#a78bfa" />
                    <SummaryCard label="押金笔数" value={`${ledger.total_count} 笔`} color={colors.textPrimary} />
                  </div>

                  {/* 账龄分析 */}
                  {aging && (
                    <>
                      <h4 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', color: colors.textPrimary }}>
                        未结押金账龄分析
                      </h4>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
                        <AgingCard label="0-7天" data={aging.aging['0_7_days']} color={colors.success} />
                        <AgingCard label="8-30天" data={aging.aging['8_30_days']} color={colors.info} />
                        <AgingCard label="31-90天" data={aging.aging['31_90_days']} color="#faad14" />
                        <AgingCard label="90天+" data={aging.aging.over_90_days} color={colors.danger} />
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── 右侧详情面板 ── */}
      <div
        style={{
          width: selected ? '380px' : '0',
          borderLeft: selected ? `1px solid ${colors.border}` : 'none',
          background: colors.card,
          overflow: 'auto',
          transition: 'width 0.2s',
          flexShrink: 0,
        }}
      >
        {detailLoading && (
          <div style={{ padding: '40px', textAlign: 'center', color: colors.textSecondary }}>加载中...</div>
        )}

        {selected && !detailLoading && (
          <div style={{ padding: '20px' }}>
            {/* 关闭 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>押金详情</h3>
              <button
                onClick={() => setSelected(null)}
                style={{ background: 'transparent', border: 'none', color: colors.textSecondary, fontSize: '18px', cursor: 'pointer' }}
              >
                x
              </button>
            </div>

            {/* 金额 */}
            <div style={{ textAlign: 'center', marginBottom: '20px' }}>
              <div style={{ fontSize: '28px', fontWeight: 700, color: colors.textPrimary }}>{fen2yuan(selected.amount_fen)}</div>
              <span style={{
                display: 'inline-block',
                marginTop: '8px',
                padding: '3px 12px',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 500,
                background: statusCfg(selected.status).bg,
                color: statusCfg(selected.status).color,
              }}>
                {statusCfg(selected.status).label}
              </span>
            </div>

            {/* 详细信息 */}
            <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: '16px' }}>
              <DetailRow label="押金ID" value={selected.id.slice(0, 8) + '...'} />
              <DetailRow label="支付方式" value={PAYMENT_LABELS[selected.payment_method] || selected.payment_method} />
              <DetailRow label="已抵扣" value={fen2yuan(selected.applied_amount_fen)} />
              <DetailRow label="已退还" value={fen2yuan(selected.refunded_amount_fen)} />
              <DetailRow label="可用余额" value={fen2yuan(selected.remaining_fen)} highlight />
              <DetailRow label="收取时间" value={new Date(selected.collected_at).toLocaleString('zh-CN')} />
              <DetailRow label="到期时间" value={new Date(selected.expires_at).toLocaleString('zh-CN')} />
              {selected.payment_ref && <DetailRow label="支付流水号" value={selected.payment_ref} />}
              {selected.reservation_id && <DetailRow label="关联预订" value={selected.reservation_id.slice(0, 8) + '...'} />}
              {selected.order_id && <DetailRow label="关联订单" value={selected.order_id.slice(0, 8) + '...'} />}
              {selected.remark && <DetailRow label="备注" value={selected.remark} />}
            </div>

            {/* 操作按钮 */}
            <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {canApply && (
                <button onClick={() => { setApplyForm({ order_id: '', amount_yuan: fen2yuanNum(selected.remaining_fen) }); setApplyModal(true); }} style={actionBtnStyle(colors.info)}>
                  抵扣消费
                </button>
              )}
              {canRefund && (
                <button onClick={() => { setRefundForm({ amount_yuan: fen2yuanNum(selected.remaining_fen), remark: '' }); setRefundModal(true); }} style={actionBtnStyle(colors.danger)}>
                  退押金
                </button>
              )}
              {canConvert && (
                <button onClick={handleConvert} disabled={actionLoading} style={actionBtnStyle('#a78bfa')}>
                  {actionLoading ? '处理中...' : '转收入'}
                </button>
              )}
            </div>
          </div>
        )}

        {!selected && !detailLoading && (
          <div style={{ padding: '60px 20px', textAlign: 'center', color: colors.textMuted, fontSize: '13px' }}>
            点击押金记录查看详情
          </div>
        )}
      </div>

      {/* ── 抵扣弹窗 ── */}
      {applyModal && (
        <Modal title="抵扣消费" onClose={() => setApplyModal(false)}>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>订单ID <span style={{ color: colors.danger }}>*</span></label>
            <input
              value={applyForm.order_id}
              onChange={e => setApplyForm(p => ({ ...p, order_id: e.target.value }))}
              placeholder="输入要抵扣的订单ID"
              style={inputStyle}
            />
          </div>
          <div style={{ marginBottom: '20px' }}>
            <label style={labelStyle}>抵扣金额（元）<span style={{ color: colors.danger }}>*</span></label>
            <input
              type="number"
              value={applyForm.amount_yuan}
              onChange={e => setApplyForm(p => ({ ...p, amount_yuan: e.target.value }))}
              min="0"
              step="0.01"
              style={inputStyle}
            />
            {selected && (
              <div style={{ fontSize: '11px', color: colors.textSecondary, marginTop: '4px' }}>
                可用余额: {fen2yuan(selected.remaining_fen)}
              </div>
            )}
          </div>
          <button onClick={handleApply} disabled={actionLoading} style={{ ...actionBtnStyle(colors.accent), width: '100%' }}>
            {actionLoading ? '处理中...' : '确认抵扣'}
          </button>
        </Modal>
      )}

      {/* ── 退款弹窗 ── */}
      {refundModal && (
        <Modal title="退还押金" onClose={() => setRefundModal(false)}>
          <div style={{ marginBottom: '16px' }}>
            <label style={labelStyle}>退还金额（元）<span style={{ color: colors.danger }}>*</span></label>
            <input
              type="number"
              value={refundForm.amount_yuan}
              onChange={e => setRefundForm(p => ({ ...p, amount_yuan: e.target.value }))}
              min="0"
              step="0.01"
              style={inputStyle}
            />
            {selected && (
              <div style={{ fontSize: '11px', color: colors.textSecondary, marginTop: '4px' }}>
                可用余额: {fen2yuan(selected.remaining_fen)}
              </div>
            )}
          </div>
          <div style={{ marginBottom: '20px' }}>
            <label style={labelStyle}>退款原因</label>
            <input
              value={refundForm.remark}
              onChange={e => setRefundForm(p => ({ ...p, remark: e.target.value }))}
              placeholder="选填"
              style={inputStyle}
            />
          </div>
          <button onClick={handleRefund} disabled={actionLoading} style={{ ...actionBtnStyle(colors.danger), width: '100%' }}>
            {actionLoading ? '处理中...' : '确认退款'}
          </button>
        </Modal>
      )}
    </div>
  );
}

// ── 子组件 ──

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '12px',
  color: '#6B8A99',
  marginBottom: '6px',
  fontWeight: 500,
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  borderRadius: '6px',
  border: '1px solid #1E3A45',
  background: '#0B1A20',
  color: '#E0E7EB',
  fontSize: '14px',
  outline: 'none',
  boxSizing: 'border-box',
};

function actionBtnStyle(color: string): React.CSSProperties {
  return {
    padding: '10px 16px',
    borderRadius: '6px',
    border: `1px solid ${color}`,
    background: `${color}22`,
    color,
    fontSize: '13px',
    fontWeight: 600,
    cursor: 'pointer',
    textAlign: 'center',
  };
}

function SummaryCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      background: '#112228',
      border: '1px solid #1E3A45',
      borderRadius: '8px',
      padding: '16px',
    }}>
      <div style={{ fontSize: '11px', color: '#6B8A99', marginBottom: '6px' }}>{label}</div>
      <div style={{ fontSize: '20px', fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

function AgingCard({ label, data, color }: { label: string; data: AgingBucket; color: string }) {
  return (
    <div style={{
      background: '#112228',
      border: '1px solid #1E3A45',
      borderRadius: '8px',
      padding: '14px',
    }}>
      <div style={{ fontSize: '12px', color, fontWeight: 600, marginBottom: '8px' }}>{label}</div>
      <div style={{ fontSize: '18px', fontWeight: 700, color: '#E0E7EB' }}>
        {`¥${(data.amount_fen / 100).toFixed(2)}`}
      </div>
      <div style={{ fontSize: '11px', color: '#6B8A99', marginTop: '4px' }}>{data.count ?? 0} 笔</div>
    </div>
  );
}

function DetailRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: '13px' }}>
      <span style={{ color: '#6B8A99' }}>{label}</span>
      <span style={{ color: highlight ? '#FF6B2C' : '#E0E7EB', fontWeight: highlight ? 600 : 400 }}>{value}</span>
    </div>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: '#112228', borderRadius: '12px', padding: '24px',
        width: '400px', maxWidth: '90vw', border: '1px solid #1E3A45',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0, color: '#E0E7EB' }}>{title}</h3>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#6B8A99', fontSize: '18px', cursor: 'pointer' }}>x</button>
        </div>
        {children}
      </div>
    </div>
  );
}
