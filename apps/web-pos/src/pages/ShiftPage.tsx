/**
 * 交接班页面 — /shift
 * 完整开班/闭班流程、KPI概览、支付渠道对账、现金盘点
 *
 * API: GET  /api/v1/ops/shifts/current?store_id=
 *      POST /api/v1/ops/shifts/open
 *      POST /api/v1/ops/shifts/{id}/close
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

async function txFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}), ...(options.headers as Record<string, string> || {}) },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 类型 ──────────────────────────────────────────────────────────────────────

type ShiftStatus = 'not_started' | 'open' | 'closed';

interface PaymentChannel {
  method: string;
  label: string;
  color: string;
  totalFen: number;
  count: number;
}

interface ShiftSummary {
  shiftId: string | null;
  status: ShiftStatus;
  operatorName: string;
  startedAt: string | null;
  totalOrders: number;
  totalRevenueFen: number;
  totalGuests: number;
  avgPerGuestFen: number;
  refundCount: number;
  refundFen: number;
  discountFen: number;
  channels: PaymentChannel[];
  expectedCashFen: number;
}

const FALLBACK_SUMMARY: ShiftSummary = {
  shiftId: 'shift-demo-001',
  status: 'open',
  operatorName: '李经理',
  startedAt: new Date().toISOString(),
  totalOrders: 42,
  totalRevenueFen: 856000,
  totalGuests: 126,
  avgPerGuestFen: 6800,
  refundCount: 2,
  refundFen: 8800,
  discountFen: 32500,
  channels: [
    { method: 'wechat', label: '微信支付', color: '#07C160', totalFen: 480000, count: 22 },
    { method: 'alipay', label: '支付宝', color: '#1677FF', totalFen: 210000, count: 10 },
    { method: 'cash', label: '现金', color: '#faad14', totalFen: 125000, count: 6 },
    { method: 'unionpay', label: '银联刷卡', color: '#e6002d', totalFen: 41000, count: 4 },
  ],
  expectedCashFen: 125000,
};

function channelColor(method: string): string {
  const map: Record<string, string> = { wechat: '#07C160', alipay: '#1677FF', cash: '#faad14', unionpay: '#e6002d', douyin: '#000' };
  return map[method] ?? '#888';
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function ShiftPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<ShiftSummary>(FALLBACK_SUMMARY);
  const [loading, setLoading] = useState(false);
  const [actualCash, setActualCash] = useState('');
  const [cashNote, setCashNote] = useState('');
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  const [closing, setClosing] = useState(false);

  const loadShift = useCallback(async () => {
    setLoading(true);
    try {
      const data = await txFetch<Record<string, unknown>>(`/api/v1/ops/shifts/current?store_id=${STORE_ID}`);
      if (data && data.shift_id) {
        const channels: PaymentChannel[] = Array.isArray(data.channels)
          ? (data.channels as Record<string, unknown>[]).map(c => ({
              method: String(c.method || ''), label: String(c.label || c.method || ''),
              color: channelColor(String(c.method || '')),
              totalFen: Number(c.total_fen || 0), count: Number(c.count || 0),
            }))
          : FALLBACK_SUMMARY.channels;
        setSummary({
          shiftId: String(data.shift_id), status: (data.status as ShiftStatus) || 'open',
          operatorName: String(data.operator_name || ''), startedAt: String(data.started_at || ''),
          totalOrders: Number(data.total_orders || 0), totalRevenueFen: Number(data.total_revenue_fen || 0),
          totalGuests: Number(data.total_guests || 0), avgPerGuestFen: Number(data.avg_per_guest_fen || 0),
          refundCount: Number(data.refund_count || 0), refundFen: Number(data.refund_fen || 0),
          discountFen: Number(data.discount_fen || 0), channels, expectedCashFen: Number(data.expected_cash_fen || 0),
        });
      }
    } catch { /* 离线: 使用 fallback */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadShift(); }, [loadShift]);

  const handleOpenShift = async () => {
    setLoading(true);
    try {
      const data = await txFetch<{ shift_id: string }>('/api/v1/ops/shifts/open', {
        method: 'POST', body: JSON.stringify({ store_id: STORE_ID }),
      });
      setSummary(prev => ({ ...prev, shiftId: data.shift_id, status: 'open', startedAt: new Date().toISOString() }));
    } catch {
      setSummary(prev => ({ ...prev, status: 'open', startedAt: new Date().toISOString() }));
    }
    setLoading(false);
  };

  const handleCloseShift = async () => {
    if (!summary.shiftId) return;
    setClosing(true);
    const actualCashFen = Math.round(parseFloat(actualCash || '0') * 100);
    try {
      await txFetch(`/api/v1/ops/shifts/${summary.shiftId}/close`, {
        method: 'POST', body: JSON.stringify({ actual_cash_fen: actualCashFen, cash_note: cashNote }),
      });
    } catch { /* offline ok */ }
    setSummary(prev => ({ ...prev, status: 'closed' }));
    setClosing(false);
    setShowCloseConfirm(false);
  };

  const cashVarianceFen = actualCash ? Math.round(parseFloat(actualCash) * 100) - summary.expectedCashFen : 0;

  const elapsedTime = (() => {
    if (!summary.startedAt) return '';
    const ms = Date.now() - new Date(summary.startedAt).getTime();
    return `${Math.floor(ms / 3600000)}小时${Math.floor((ms % 3600000) / 60000)}分钟`;
  })();

  // ── 未开班 ──
  if (summary.status === 'not_started') {
    return (
      <div style={pageStyle}>
        <Header navigate={navigate} />
        <div style={{ textAlign: 'center', paddingTop: 80 }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🌅</div>
          <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>尚未开班</div>
          <div style={{ fontSize: 16, color: '#9CA3AF', marginBottom: 32 }}>点击下方按钮开始当班营业</div>
          <button type="button" onClick={handleOpenShift} disabled={loading}
            style={{ padding: '16px 60px', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 10, fontSize: 20, fontWeight: 600, cursor: 'pointer', minHeight: 56 }}>
            {loading ? '开班中...' : '开始营业'}
          </button>
        </div>
      </div>
    );
  }

  // ── 已闭班 ──
  if (summary.status === 'closed') {
    return (
      <div style={pageStyle}>
        <Header navigate={navigate} />
        <div style={{ textAlign: 'center', paddingTop: 60 }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>✅</div>
          <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8, color: '#52c41a' }}>本班已结束</div>
          <div style={{ fontSize: 16, color: '#9CA3AF', marginBottom: 8 }}>
            营业额: <strong style={{ color: '#FF6B35' }}>{fen2yuan(summary.totalRevenueFen)}</strong> · {summary.totalOrders}单
          </div>
          <button type="button" onClick={handleOpenShift}
            style={{ marginTop: 32, padding: '14px 48px', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 10, fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 52 }}>
            开始下一班
          </button>
        </div>
      </div>
    );
  }

  // ── 营业中 ──
  return (
    <div style={pageStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22 }}>交接班</h2>
          <div style={{ fontSize: 14, color: '#9CA3AF', marginTop: 4 }}>{summary.operatorName} · 已营业 {elapsedTime}</div>
        </div>
        <button type="button" onClick={() => navigate('/tables')} style={backBtnStyle}>返回</button>
      </div>

      {/* KPI 第一行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 12 }}>
        <KPICard label="总单数" value={`${summary.totalOrders} 单`} />
        <KPICard label="总营收" value={fen2yuan(summary.totalRevenueFen)} highlight />
        <KPICard label="客流" value={`${summary.totalGuests} 人`} />
        <KPICard label="客单价" value={fen2yuan(summary.avgPerGuestFen)} />
      </div>
      {/* KPI 第二行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 24 }}>
        <KPICard label="退款" value={`${summary.refundCount}笔 ${fen2yuan(summary.refundFen)}`} danger={summary.refundCount > 0} />
        <KPICard label="优惠减免" value={fen2yuan(summary.discountFen)} />
        <KPICard label="净收入" value={fen2yuan(summary.totalRevenueFen - summary.refundFen - summary.discountFen)} highlight />
      </div>

      {/* 支付渠道对账 */}
      <div style={{ background: '#112228', borderRadius: 10, padding: 16, marginBottom: 24 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 18 }}>支付渠道对账</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1a2a33' }}>
              <th style={thStyle}>渠道</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>笔数</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>金额</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>占比</th>
            </tr>
          </thead>
          <tbody>
            {summary.channels.map(ch => {
              const pct = summary.totalRevenueFen > 0 ? ((ch.totalFen / summary.totalRevenueFen) * 100).toFixed(1) : '0';
              return (
                <tr key={ch.method} style={{ borderBottom: '1px solid #1a2a33' }}>
                  <td style={{ padding: 12 }}>
                    <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: ch.color, marginRight: 8, verticalAlign: 'middle' }} />
                    {ch.label}
                  </td>
                  <td style={{ padding: 12, textAlign: 'right', color: '#9CA3AF' }}>{ch.count}</td>
                  <td style={{ padding: 12, textAlign: 'right', fontWeight: 600 }}>{fen2yuan(ch.totalFen)}</td>
                  <td style={{ padding: 12, textAlign: 'right', color: '#9CA3AF' }}>{pct}%</td>
                </tr>
              );
            })}
            <tr style={{ borderTop: '2px solid #333' }}>
              <td style={{ padding: 12, fontWeight: 600 }}>合计</td>
              <td style={{ padding: 12, textAlign: 'right', fontWeight: 600 }}>{summary.channels.reduce((s, c) => s + c.count, 0)}</td>
              <td style={{ padding: 12, textAlign: 'right', fontWeight: 600, color: '#FF6B35' }}>{fen2yuan(summary.totalRevenueFen)}</td>
              <td style={{ padding: 12, textAlign: 'right' }}>100%</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* 现金盘点 */}
      <div style={{ background: '#112228', borderRadius: 10, padding: 16, marginBottom: 24 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 18 }}>现金盘点</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 14, color: '#9CA3AF', marginBottom: 4 }}>应有现金</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#faad14' }}>{fen2yuan(summary.expectedCashFen)}</div>
          </div>
          <div>
            <div style={{ fontSize: 14, color: '#9CA3AF', marginBottom: 4 }}>实际现金（元）</div>
            <input type="number" value={actualCash} onChange={e => setActualCash(e.target.value)}
              placeholder="输入盘点金额" step="0.01"
              style={{ width: '100%', padding: '10px 12px', background: '#1a2a33', border: '1px solid #333', borderRadius: 8, color: '#fff', fontSize: 18, fontWeight: 600, outline: 'none', boxSizing: 'border-box' }} />
          </div>
        </div>
        {actualCash && (
          <div style={{ padding: '10px 14px', borderRadius: 8, marginBottom: 12, background: cashVarianceFen === 0 ? 'rgba(82,196,26,0.1)' : 'rgba(255,77,79,0.1)' }}>
            <span style={{ fontSize: 14, color: cashVarianceFen === 0 ? '#52c41a' : '#ff4d4f' }}>
              差异: {cashVarianceFen === 0 ? '无差异 ✓' : `${cashVarianceFen > 0 ? '+' : ''}${fen2yuan(cashVarianceFen)}`}
            </span>
          </div>
        )}
        <input value={cashNote} onChange={e => setCashNote(e.target.value)} placeholder="盘点备注（可选）"
          style={{ width: '100%', padding: '8px 12px', background: '#1a2a33', border: '1px solid #333', borderRadius: 8, color: '#fff', fontSize: 14, outline: 'none', boxSizing: 'border-box' }} />
      </div>

      {/* 操作按钮 */}
      <div style={{ display: 'flex', gap: 12 }}>
        <button type="button" onClick={() => loadShift()}
          style={{ flex: 1, padding: '14px 0', background: '#1a2a33', color: '#fff', border: '1px solid #333', borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 52 }}>
          刷新数据
        </button>
        <button type="button" onClick={() => setShowCloseConfirm(true)}
          style={{ flex: 2, padding: '14px 0', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 8, fontSize: 18, fontWeight: 600, cursor: 'pointer', minHeight: 52 }}>
          确认交接班
        </button>
      </div>

      {/* 闭班确认弹窗 */}
      {showCloseConfirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowCloseConfirm(false)}>
          <div style={{ background: '#1a2a33', borderRadius: 12, padding: 24, width: 400, maxWidth: '90vw' }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>确认交接班？</div>
            <div style={{ fontSize: 16, color: '#9CA3AF', marginBottom: 8 }}>本班营业额: <strong style={{ color: '#FF6B35' }}>{fen2yuan(summary.totalRevenueFen)}</strong></div>
            <div style={{ fontSize: 16, color: '#9CA3AF', marginBottom: 8 }}>总单数: <strong>{summary.totalOrders}</strong> 单</div>
            {actualCash && cashVarianceFen !== 0 && (
              <div style={{ fontSize: 16, color: '#ff4d4f', marginBottom: 8 }}>现金差异: {cashVarianceFen > 0 ? '+' : ''}{fen2yuan(cashVarianceFen)}</div>
            )}
            <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
              <button type="button" onClick={() => setShowCloseConfirm(false)}
                style={{ flex: 1, padding: '12px 0', background: '#333', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 48 }}>取消</button>
              <button type="button" onClick={handleCloseShift} disabled={closing}
                style={{ flex: 1, padding: '12px 0', background: '#FF6B35', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, fontWeight: 600, cursor: 'pointer', minHeight: 48, opacity: closing ? 0.6 : 1 }}>
                {closing ? '提交中...' : '确认交班'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function Header({ navigate }: { navigate: (path: string) => void }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
      <h2 style={{ margin: 0, fontSize: 22 }}>交接班</h2>
      <button type="button" onClick={() => navigate('/tables')} style={backBtnStyle}>返回</button>
    </div>
  );
}

function KPICard({ label, value, highlight, danger }: { label: string; value: string; highlight?: boolean; danger?: boolean }) {
  return (
    <div style={{ padding: 16, background: '#112228', borderRadius: 10, textAlign: 'center' }}>
      <div style={{ fontSize: 13, color: '#9CA3AF', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: danger ? '#ff4d4f' : highlight ? '#FF6B35' : '#fff' }}>{value}</div>
    </div>
  );
}

const pageStyle: React.CSSProperties = {
  padding: 20, background: '#0B1A20', minHeight: '100vh', color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
  maxWidth: 900, margin: '0 auto',
};

const backBtnStyle: React.CSSProperties = {
  padding: '8px 20px', background: '#1a2a33', color: '#fff', border: '1px solid #333',
  borderRadius: 8, fontSize: 16, cursor: 'pointer', minHeight: 48,
};

const thStyle: React.CSSProperties = { padding: 10, textAlign: 'left', color: '#6B7280', fontSize: 13, fontWeight: 500 };
