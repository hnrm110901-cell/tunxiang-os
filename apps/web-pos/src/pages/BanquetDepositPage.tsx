/**
 * BanquetDepositPage — 宴会定金管理 POS 页面（模块4.1）
 *
 * 路由：/banquet-deposit
 * 功能：
 *   - Tab1 收定金：场次选择 + 金额 + 支付方式 + 备注
 *   - Tab2 查询/抵扣：查看当前场次定金余额，结账时一键抵扣
 *   - Tab3 退定金：退还余额
 *
 * 终端：安卓 POS / iPad（TXTouch 风格，大按钮大字体）
 */
import { useState, useEffect, useCallback } from 'react';
import React from 'react';
import { txFetch } from '../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface BanquetSession {
  id: string;
  contact_name: string | null;
  session_date: string;
  time_slot: string;
  guest_count: number;
  status: string;
}

interface DepositRecord {
  id: string;
  amount_fen: number;
  balance_fen: number;
  payment_method: string;
  status: string;
  collected_at: string;
  notes: string | null;
}

interface DepositBalance {
  session_id: string;
  contact_name: string | null;
  session_status: string;
  order_total_fen: number;
  total_collected_fen: number;
  total_balance_fen: number;
  remaining_payable_fen: number;
  records: DepositRecord[];
}

type TabKey = 'collect' | 'balance' | 'refund';

const PAYMENT_METHODS = [
  { value: 'cash', label: '现金' },
  { value: 'wechat', label: '微信' },
  { value: 'alipay', label: '支付宝' },
  { value: 'bank_transfer', label: '转账' },
];

function fmtYuan(fen: number) {
  return `¥${(fen / 100).toFixed(2)}`;
}

// ─── 样式常量 ─────────────────────────────────────────────────────────────────

const S = {
  page: {
    minHeight: '100vh',
    background: '#F8F7F5',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    color: '#2C2C2A',
  } as React.CSSProperties,
  header: {
    background: '#1E2A3A',
    padding: '16px 20px',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  } as React.CSSProperties,
  headerTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: '#FFF',
    margin: 0,
  } as React.CSSProperties,
  tabBar: {
    display: 'flex',
    background: '#FFF',
    borderBottom: '2px solid #E8E6E1',
  } as React.CSSProperties,
  tabBtn: (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: '14px 0',
    background: 'none',
    border: 'none',
    borderBottom: active ? '3px solid #FF6B35' : '3px solid transparent',
    color: active ? '#FF6B35' : '#888',
    fontSize: 15,
    fontWeight: active ? 700 : 400,
    cursor: 'pointer',
  }),
  body: {
    padding: '20px 20px',
    maxWidth: 600,
    margin: '0 auto',
  } as React.CSSProperties,
  card: {
    background: '#FFF',
    borderRadius: 12,
    padding: '20px',
    marginBottom: 16,
    boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
  } as React.CSSProperties,
  label: {
    fontSize: 14,
    color: '#666',
    marginBottom: 6,
    display: 'block',
  } as React.CSSProperties,
  select: {
    width: '100%',
    height: 48,
    borderRadius: 8,
    border: '1.5px solid #D5D2CC',
    padding: '0 12px',
    fontSize: 16,
    background: '#FFF',
    marginBottom: 16,
  } as React.CSSProperties,
  input: {
    width: '100%',
    height: 48,
    borderRadius: 8,
    border: '1.5px solid #D5D2CC',
    padding: '0 12px',
    fontSize: 20,
    fontWeight: 600,
    boxSizing: 'border-box' as const,
    marginBottom: 16,
  } as React.CSSProperties,
  btn: (color: string, disabled?: boolean): React.CSSProperties => ({
    width: '100%',
    height: 52,
    borderRadius: 10,
    border: 'none',
    background: disabled ? '#ccc' : color,
    color: '#FFF',
    fontSize: 17,
    fontWeight: 700,
    cursor: disabled ? 'not-allowed' : 'pointer',
    marginTop: 4,
  }),
  pmGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 8,
    marginBottom: 16,
  } as React.CSSProperties,
  pmBtn: (active: boolean): React.CSSProperties => ({
    height: 42,
    borderRadius: 8,
    border: `2px solid ${active ? '#FF6B35' : '#D5D2CC'}`,
    background: active ? '#FFF5F0' : '#FFF',
    color: active ? '#FF6B35' : '#2C2C2A',
    fontSize: 15,
    fontWeight: active ? 700 : 400,
    cursor: 'pointer',
  }),
};

// ─── 场次选择器 ───────────────────────────────────────────────────────────────

function SessionSelector({
  value,
  onChange,
}: {
  value: string;
  onChange: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<BanquetSession[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    txFetch('/api/v1/banquet/sessions?status=confirmed&size=50')
      .then((r: { data?: { items?: BanquetSession[] } }) => setSessions(r?.data?.items ?? []))
      .catch(() => setSessions([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <label style={S.label}>选择宴席场次</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={S.select}
        disabled={loading}
      >
        <option value="">{loading ? '加载中…' : '— 请选择场次 —'}</option>
        {sessions.map(s => (
          <option key={s.id} value={s.id}>
            {s.contact_name ?? '未命名'} · {s.session_date} ·
            {s.time_slot === 'dinner' ? '晚宴' : s.time_slot === 'lunch' ? '午宴' : s.time_slot} ·
            {s.guest_count}人
          </option>
        ))}
      </select>
    </div>
  );
}

// ─── Tab1：收定金 ─────────────────────────────────────────────────────────────

function CollectTab() {
  const [sessionId, setSessionId] = useState('');
  const [amountYuan, setAmountYuan] = useState('');
  const [paymentMethod, setPaymentMethod] = useState('cash');
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    const amtFen = Math.round(parseFloat(amountYuan) * 100);
    if (!sessionId) { setError('请选择场次'); return; }
    if (!amtFen || amtFen <= 0) { setError('请输入有效金额'); return; }

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await txFetch('/api/v1/banquet/deposits', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          amount_fen: amtFen,
          payment_method: paymentMethod,
          notes: notes || undefined,
        }),
      }) as { ok?: boolean; data?: { amount_fen?: number } };
      if (resp?.ok) {
        setResult(`定金收取成功 ${fmtYuan(resp.data?.amount_fen ?? amtFen)}`);
        setAmountYuan('');
        setNotes('');
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={S.body}>
      <div style={S.card}>
        <SessionSelector value={sessionId} onChange={setSessionId} />

        <label style={S.label}>定金金额（元）</label>
        <input
          type="number"
          placeholder="0.00"
          value={amountYuan}
          onChange={e => setAmountYuan(e.target.value)}
          style={S.input}
          min="0"
          step="0.01"
        />

        <label style={S.label}>收款方式</label>
        <div style={S.pmGrid}>
          {PAYMENT_METHODS.map(pm => (
            <button
              key={pm.value}
              style={S.pmBtn(paymentMethod === pm.value)}
              onClick={() => setPaymentMethod(pm.value)}
            >
              {pm.label}
            </button>
          ))}
        </div>

        <label style={S.label}>备注（可选）</label>
        <input
          type="text"
          placeholder="如：婚宴定金"
          value={notes}
          onChange={e => setNotes(e.target.value)}
          style={{ ...S.input, fontSize: 15, fontWeight: 400, marginBottom: 20 }}
        />

        {error && (
          <div style={{
            background: '#FFF5F5', border: '1px solid #FFCDD2',
            borderRadius: 8, padding: '10px 14px',
            color: '#D32F2F', marginBottom: 12, fontSize: 14,
          }}>
            {error}
          </div>
        )}
        {result && (
          <div style={{
            background: '#F0FFF4', border: '1px solid #C6F6D5',
            borderRadius: 8, padding: '10px 14px',
            color: '#276749', marginBottom: 12, fontSize: 14,
          }}>
            ✓ {result}
          </div>
        )}

        <button
          style={S.btn('#FF6B35', loading || !sessionId || !amountYuan)}
          disabled={loading || !sessionId || !amountYuan}
          onClick={handleSubmit}
        >
          {loading ? '处理中…' : '确认收款'}
        </button>
      </div>
    </div>
  );
}

// ─── Tab2：查询/抵扣 ──────────────────────────────────────────────────────────

function BalanceTab() {
  const [sessionId, setSessionId] = useState('');
  const [balance, setBalance] = useState<DepositBalance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applyAmt, setApplyAmt] = useState('');
  const [orderTotal, setOrderTotal] = useState('');
  const [applyResult, setApplyResult] = useState<string | null>(null);
  const [applyLoading, setApplyLoading] = useState(false);

  const loadBalance = useCallback(async (sid: string) => {
    if (!sid) return;
    setLoading(true);
    setError(null);
    setBalance(null);
    try {
      const resp = await txFetch(`/api/v1/banquet/deposits/${sid}`) as { ok?: boolean; data?: DepositBalance };
      if (resp?.ok && resp.data) {
        setBalance(resp.data);
        setOrderTotal(String((resp.data.order_total_fen / 100).toFixed(2)));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleApply = async () => {
    if (!balance || !applyAmt) return;
    const applyFen = Math.round(parseFloat(applyAmt) * 100);
    const totalFen = Math.round(parseFloat(orderTotal) * 100);
    if (applyFen <= 0 || totalFen <= 0) { setError('请填写有效金额'); return; }

    setApplyLoading(true);
    setError(null);
    setApplyResult(null);
    try {
      const resp = await txFetch(`/api/v1/banquet/deposits/${sessionId}/apply`, {
        method: 'POST',
        body: JSON.stringify({
          apply_amount_fen: applyFen,
          order_total_fen: totalFen,
        }),
      }) as { ok?: boolean; data?: { deducted_fen?: number; remaining_payable_fen?: number } };
      if (resp?.ok && resp.data) {
        const { deducted_fen = 0, remaining_payable_fen = 0 } = resp.data;
        setApplyResult(
          `抵扣 ${fmtYuan(deducted_fen)}，剩余应付 ${fmtYuan(remaining_payable_fen)}`
        );
        await loadBalance(sessionId);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setApplyLoading(false);
    }
  };

  return (
    <div style={S.body}>
      <div style={S.card}>
        <SessionSelector
          value={sessionId}
          onChange={(id) => { setSessionId(id); if (id) loadBalance(id); }}
        />
        {!sessionId && (
          <div style={{ color: '#999', textAlign: 'center', padding: '24px 0', fontSize: 14 }}>
            请选择场次以查看定金余额
          </div>
        )}
        {loading && (
          <div style={{ color: '#999', textAlign: 'center', padding: '24px 0' }}>加载中…</div>
        )}
        {error && (
          <div style={{ background: '#FFF5F5', border: '1px solid #FFCDD2', borderRadius: 8, padding: '10px 14px', color: '#D32F2F', marginBottom: 12, fontSize: 14 }}>
            {error}
          </div>
        )}

        {balance && !loading && (
          <>
            {/* 余额展示 */}
            <div style={{
              background: '#FFF5F0', borderRadius: 10, padding: '16px 18px', marginBottom: 16,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ color: '#888', fontSize: 14 }}>已收定金</span>
                <span style={{ color: '#2C2C2A', fontSize: 16, fontWeight: 600 }}>
                  {fmtYuan(balance.total_collected_fen)}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ color: '#888', fontSize: 14 }}>可用余额</span>
                <span style={{ color: '#FF6B35', fontSize: 22, fontWeight: 700 }}>
                  {fmtYuan(balance.total_balance_fen)}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#888', fontSize: 14 }}>结账总额</span>
                <span style={{ color: '#2C2C2A', fontSize: 16, fontWeight: 600 }}>
                  {fmtYuan(balance.order_total_fen)}
                </span>
              </div>
            </div>

            {/* 抵扣区 */}
            {balance.total_balance_fen > 0 && (
              <div style={{ marginBottom: 12 }}>
                <label style={S.label}>结账总额（元）</label>
                <input
                  type="number"
                  value={orderTotal}
                  onChange={e => setOrderTotal(e.target.value)}
                  style={{ ...S.input, marginBottom: 10 }}
                  placeholder="0.00"
                />
                <label style={S.label}>抵扣定金金额（元，留空=全额抵扣）</label>
                <input
                  type="number"
                  value={applyAmt}
                  onChange={e => setApplyAmt(e.target.value)}
                  style={{ ...S.input, marginBottom: 10 }}
                  placeholder={fmtYuan(balance.total_balance_fen).replace('¥', '')}
                />
                {applyResult && (
                  <div style={{ background: '#F0FFF4', border: '1px solid #C6F6D5', borderRadius: 8, padding: '10px 14px', color: '#276749', marginBottom: 10, fontSize: 14 }}>
                    ✓ {applyResult}
                  </div>
                )}
                <button
                  style={S.btn('#276749', applyLoading)}
                  disabled={applyLoading}
                  onClick={handleApply}
                >
                  {applyLoading ? '处理中…' : `抵扣定金 ${fmtYuan(balance.total_balance_fen)}`}
                </button>
              </div>
            )}

            {balance.total_balance_fen === 0 && (
              <div style={{ color: '#888', textAlign: 'center', fontSize: 14, padding: '12px 0' }}>
                定金已全部使用
              </div>
            )}

            {/* 定金记录列表 */}
            {balance.records.length > 0 && (
              <div>
                <div style={{ color: '#888', fontSize: 13, marginBottom: 8 }}>收款记录</div>
                {balance.records.map(rec => (
                  <div key={rec.id} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 0', borderBottom: '1px solid #F0EDE8',
                  }}>
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 500 }}>
                        {fmtYuan(rec.amount_fen)}
                        <span style={{ fontSize: 12, color: '#999', marginLeft: 6 }}>
                          {PAYMENT_METHODS.find(p => p.value === rec.payment_method)?.label ?? rec.payment_method}
                        </span>
                      </div>
                      <div style={{ fontSize: 12, color: '#999' }}>
                        {new Date(rec.collected_at).toLocaleString()}
                      </div>
                    </div>
                    <span style={{
                      padding: '2px 10px', borderRadius: 10, fontSize: 12,
                      background: rec.status === 'active' ? '#F0FFF4' : '#FFF5F0',
                      color: rec.status === 'active' ? '#276749' : '#C05621',
                    }}>
                      {rec.status === 'active' ? '可用' : rec.status === 'applied' ? '已抵扣' : '已退款'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─── Tab3：退定金 ─────────────────────────────────────────────────────────────

function RefundTab() {
  const [sessionId, setSessionId] = useState('');
  const [balance, setBalance] = useState<number | null>(null);
  const [refundAmt, setRefundAmt] = useState('');
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const loadBalance = useCallback(async (sid: string) => {
    if (!sid) return;
    setBalance(null);
    try {
      const resp = await txFetch(`/api/v1/banquet/deposits/${sid}`) as { ok?: boolean; data?: DepositBalance };
      if (resp?.ok && resp.data) {
        setBalance(resp.data.total_balance_fen);
      }
    } catch {
      setBalance(0);
    }
  }, []);

  const handleRefund = async () => {
    const refundFen = Math.round(parseFloat(refundAmt) * 100);
    if (!sessionId) { setError('请选择场次'); return; }
    if (!refundFen || refundFen <= 0) { setError('请输入退款金额'); return; }
    if (!reason.trim()) { setError('请填写退款原因'); return; }

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await txFetch(`/api/v1/banquet/deposits/${sessionId}/refund`, {
        method: 'POST',
        body: JSON.stringify({
          refund_amount_fen: refundFen,
          refund_reason: reason,
        }),
      }) as { ok?: boolean; data?: { refunded_fen?: number; remaining_balance_fen?: number } };
      if (resp?.ok && resp.data) {
        const { refunded_fen = 0, remaining_balance_fen = 0 } = resp.data;
        setResult(
          `退款成功 ${fmtYuan(refunded_fen)}，剩余余额 ${fmtYuan(remaining_balance_fen)}`
        );
        setRefundAmt('');
        setReason('');
        await loadBalance(sessionId);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={S.body}>
      <div style={S.card}>
        <SessionSelector
          value={sessionId}
          onChange={(id) => { setSessionId(id); if (id) loadBalance(id); }}
        />

        {balance !== null && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: '#FFF5F0', borderRadius: 8, padding: '12px 16px', marginBottom: 16,
          }}>
            <span style={{ color: '#888', fontSize: 14 }}>可退余额</span>
            <span style={{ color: '#FF6B35', fontSize: 22, fontWeight: 700 }}>
              {fmtYuan(balance)}
            </span>
          </div>
        )}

        <label style={S.label}>退款金额（元）</label>
        <input
          type="number"
          placeholder="0.00"
          value={refundAmt}
          onChange={e => setRefundAmt(e.target.value)}
          style={S.input}
          min="0"
          step="0.01"
        />

        <label style={S.label}>退款原因</label>
        <input
          type="text"
          placeholder="如：宴席取消"
          value={reason}
          onChange={e => setReason(e.target.value)}
          style={{ ...S.input, fontSize: 15, fontWeight: 400, marginBottom: 20 }}
        />

        {error && (
          <div style={{ background: '#FFF5F5', border: '1px solid #FFCDD2', borderRadius: 8, padding: '10px 14px', color: '#D32F2F', marginBottom: 12, fontSize: 14 }}>
            {error}
          </div>
        )}
        {result && (
          <div style={{ background: '#F0FFF4', border: '1px solid #C6F6D5', borderRadius: 8, padding: '10px 14px', color: '#276749', marginBottom: 12, fontSize: 14 }}>
            ✓ {result}
          </div>
        )}

        <button
          style={S.btn('#C05621', loading || !sessionId || !refundAmt || !reason)}
          disabled={loading || !sessionId || !refundAmt || !reason}
          onClick={handleRefund}
        >
          {loading ? '处理中…' : '确认退款'}
        </button>
      </div>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function BanquetDepositPage() {
  const [tab, setTab] = useState<TabKey>('collect');

  const TABS: { key: TabKey; label: string }[] = [
    { key: 'collect', label: '收定金' },
    { key: 'balance', label: '余额/抵扣' },
    { key: 'refund', label: '退定金' },
  ];

  return (
    <div style={S.page}>
      <div style={S.header}>
        <button
          onClick={() => window.history.back()}
          style={{ background: 'none', border: 'none', color: '#FFF', cursor: 'pointer', fontSize: 18, padding: 0 }}
        >
          ‹
        </button>
        <h1 style={S.headerTitle}>宴会定金管理</h1>
      </div>

      <div style={S.tabBar}>
        {TABS.map(t => (
          <button key={t.key} style={S.tabBtn(tab === t.key)} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'collect' && <CollectTab />}
      {tab === 'balance' && <BalanceTab />}
      {tab === 'refund' && <RefundTab />}
    </div>
  );
}

export default BanquetDepositPage;
