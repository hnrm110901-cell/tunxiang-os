/**
 * 班次管理页面 — 开班 / 当班仪表盘 / 交班入口
 * 调用 handoverApi: fetchShiftSnapshot, openShift
 * 深色主题，匹配 HandoverPage 样式
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchShiftSnapshot,
  openShift,
  type ShiftSnapshot,
} from '../api/handoverApi';

/* ---------- 样式常量（与 HandoverPage 一致） ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#0F6E56',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
};

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

/* ---------- 配置 ---------- */
const STORE_ID = import.meta.env.VITE_STORE_ID || '';
const CASHIER_ID = localStorage.getItem('employeeId') || '';

const CHANNEL_COLORS: Record<string, string> = {
  wechat: '#07C160', alipay: '#1677FF', cash: '#faad14',
  unionpay: '#e6002d', credit_account: '#185FA5', refund: '#ff4d4f',
  微信支付: '#07C160', 支付宝: '#1677FF', 现金: '#faad14',
  银联刷卡: '#e6002d', 企业挂账: '#185FA5', 退款: '#ff4d4f',
};

/* ---------- 面额配置（开班初始现金清点用） ---------- */
const DENOMINATIONS = [
  { label: '100元', valueFen: 10000 },
  { label: '50元', valueFen: 5000 },
  { label: '20元', valueFen: 2000 },
  { label: '10元', valueFen: 1000 },
  { label: '5元', valueFen: 500 },
  { label: '1元', valueFen: 100 },
  { label: '硬币', valueFen: 100 },
];

const AUTO_REFRESH_MS = 60_000;

/* ---------- 组件 ---------- */
export function ShiftPage() {
  const navigate = useNavigate();

  // 班次状态：'loading' | 'no-shift' | 'active' | 'error'
  const [phase, setPhase] = useState<'loading' | 'no-shift' | 'active' | 'error'>('loading');
  const [shift, setShift] = useState<ShiftSnapshot | null>(null);
  const [errorMsg, setErrorMsg] = useState('');

  // 开班表单
  const [counts, setCounts] = useState<Record<string, number>>(
    Object.fromEntries(DENOMINATIONS.map(d => [d.label, 0])),
  );
  const [opening, setOpening] = useState(false);

  const initialCashFen = useMemo(
    () => DENOMINATIONS.reduce((sum, d) => sum + (counts[d.label] || 0) * d.valueFen, 0),
    [counts],
  );

  // ── 加载班次快照 ──
  const loadShift = useCallback(async () => {
    try {
      const data = await fetchShiftSnapshot(STORE_ID, CASHIER_ID);
      if (data && data.shift_id) {
        setShift(data);
        setPhase('active');
      } else {
        setPhase('no-shift');
      }
    } catch (err) {
      // 404 或 "no active shift" 类错误视为无班次
      const msg = err instanceof Error ? err.message : '加载失败';
      if (msg.includes('no active') || msg.includes('not found') || msg.includes('404')) {
        setPhase('no-shift');
      } else {
        setErrorMsg(msg);
        setPhase('error');
      }
    }
  }, []);

  useEffect(() => {
    loadShift();
  }, [loadShift]);

  // ── 自动刷新（当班中） ──
  useEffect(() => {
    if (phase !== 'active') return;
    const timer = setInterval(() => {
      loadShift();
    }, AUTO_REFRESH_MS);
    return () => clearInterval(timer);
  }, [phase, loadShift]);

  // ── 面额增减 ──
  const handleCountChange = (label: string, delta: number) => {
    setCounts(prev => ({
      ...prev,
      [label]: Math.max(0, (prev[label] || 0) + delta),
    }));
  };

  // ── 开班提交 ──
  const handleOpenShift = async () => {
    setOpening(true);
    try {
      const result = await openShift(STORE_ID, CASHIER_ID, initialCashFen);
      localStorage.setItem('activeShiftId', result.shift_id);
      // 重新加载班次快照
      await loadShift();
    } catch (err) {
      alert(`开班失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setOpening(false);
    }
  };

  // 渠道列表
  const channels = (shift?.channels ?? []).map(ch => ({
    name: ch.channel,
    fen: ch.amount_fen,
    color: CHANNEL_COLORS[ch.channel] || C.muted,
  }));

  return (
    <div style={{ padding: 24, background: C.bg, minHeight: '100vh', color: C.white }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 24 }}>
          {phase === 'active' ? '当班中' : phase === 'no-shift' ? '开班' : '班次管理'}
        </h2>
        <button
          onClick={() => navigate('/tables')}
          style={{
            minHeight: 48, padding: '8px 20px', background: '#1a2a33',
            color: C.white, border: 'none', borderRadius: 8,
            cursor: 'pointer', fontSize: 16,
          }}
        >
          返回
        </button>
      </div>

      {/* ═══ 加载中 ═══ */}
      {phase === 'loading' && (
        <div style={{ textAlign: 'center', padding: 60, color: C.muted, fontSize: 18 }}>
          加载班次数据中...
        </div>
      )}

      {/* ═══ 错误 ═══ */}
      {phase === 'error' && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ color: '#ff4d4f', fontSize: 18, marginBottom: 12 }}>{errorMsg}</div>
          <button
            onClick={() => { setPhase('loading'); loadShift(); }}
            style={{
              padding: '10px 24px', background: C.accent, color: C.white,
              border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer',
            }}
          >
            重试
          </button>
        </div>
      )}

      {/* ═══ 无班次 → 开班表单 ═══ */}
      {phase === 'no-shift' && (
        <div>
          {/* 提示 */}
          <div style={{
            background: `${C.accent}15`, borderRadius: 12, padding: 20, marginBottom: 24,
            border: `1px solid ${C.accent}40`, textAlign: 'center',
          }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.accent, marginBottom: 8 }}>
              当前无活跃班次
            </div>
            <div style={{ fontSize: 16, color: C.text }}>
              请清点备用金后开班
            </div>
          </div>

          {/* 面额清点 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 20, marginBottom: 24,
            border: `1px solid ${C.border}`,
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>备用金清点（按面额）</h3>
            {DENOMINATIONS.map(d => (
              <div key={d.label} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '10px 0', borderBottom: `1px solid ${C.border}`,
                minHeight: 56,
              }}>
                <span style={{ fontSize: 18, minWidth: 80 }}>{d.label}</span>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    onClick={() => handleCountChange(d.label, -1)}
                    style={{
                      width: 48, height: 48, borderRadius: 8,
                      background: '#1a2a33', border: 'none',
                      color: C.white, fontSize: 24, cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >
                    -
                  </button>
                  <span style={{
                    fontSize: 24, fontWeight: 'bold', minWidth: 48,
                    textAlign: 'center', color: C.white,
                  }}>
                    {counts[d.label]}
                  </span>
                  <button
                    onClick={() => handleCountChange(d.label, 1)}
                    style={{
                      width: 48, height: 48, borderRadius: 8,
                      background: C.accent, border: 'none',
                      color: C.white, fontSize: 24, cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >
                    +
                  </button>
                </div>

                <span style={{ fontSize: 16, color: C.muted, minWidth: 80, textAlign: 'right' }}>
                  {fen2yuan((counts[d.label] || 0) * d.valueFen)}
                </span>
              </div>
            ))}

            <div style={{
              display: 'flex', justifyContent: 'space-between', paddingTop: 16,
              fontSize: 20, fontWeight: 'bold',
            }}>
              <span>备用金合计</span>
              <span style={{ color: C.accent }}>{fen2yuan(initialCashFen)}</span>
            </div>
          </div>

          {/* 开班按钮 */}
          <button
            onClick={handleOpenShift}
            disabled={opening}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: opening ? '#1a2a33' : C.accent,
              border: 'none', color: C.white,
              fontSize: 20, fontWeight: 700,
              cursor: opening ? 'not-allowed' : 'pointer',
              opacity: opening ? 0.6 : 1,
            }}
          >
            {opening ? '开班中...' : '确认开班'}
          </button>
        </div>
      )}

      {/* ═══ 当班中 → 仪表盘 ═══ */}
      {phase === 'active' && shift && (
        <div>
          {/* 班次信息条 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 16, marginBottom: 16,
            border: `1px solid ${C.border}`,
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <div>
              <div style={{ fontSize: 16, color: C.muted }}>班次号: {shift.shift_id}</div>
              <div style={{ fontSize: 16, color: C.muted, marginTop: 4 }}>
                收银员: {shift.cashier_name}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 16, color: C.muted }}>开班时间</div>
              <div style={{ fontSize: 16, color: C.text, marginTop: 4 }}>
                {shift.start_time}
              </div>
            </div>
          </div>

          {/* KPI 卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            {[
              { label: '订单总数', value: `${shift.total_orders}`, sub: '单' },
              { label: '总营收', value: fen2yuan(shift.total_revenue_fen), sub: '' },
              { label: '客流量', value: `${shift.total_guests}`, sub: '人' },
              { label: '客单价', value: fen2yuan(shift.avg_per_guest_fen), sub: '' },
            ].map(kpi => (
              <div key={kpi.label} style={{
                background: C.card, borderRadius: 12, padding: 16, textAlign: 'center',
                border: `1px solid ${C.border}`,
                borderTop: `3px solid ${C.accent}`,
              }}>
                <div style={{ fontSize: 16, color: C.muted, marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ fontSize: 28, fontWeight: 'bold', color: C.accent }}>
                  {kpi.value}
                </div>
                {kpi.sub && <div style={{ fontSize: 16, color: C.muted }}>{kpi.sub}</div>}
              </div>
            ))}
          </div>

          {/* 各渠道金额 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 20, marginBottom: 24,
            border: `1px solid ${C.border}`,
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>各渠道金额</h3>
            {channels.map(ch => (
              <div key={ch.name} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '12px 0', borderBottom: `1px solid ${C.border}`,
                minHeight: 48,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: ch.color, display: 'inline-block',
                  }} />
                  <span style={{ fontSize: 18 }}>{ch.name}</span>
                </div>
                <span style={{
                  fontSize: 18, fontWeight: 'bold',
                  color: ch.fen < 0 ? '#ff4d4f' : C.white,
                }}>
                  {ch.fen < 0 ? `-${fen2yuan(-ch.fen)}` : fen2yuan(ch.fen)}
                </span>
              </div>
            ))}
            <div style={{
              display: 'flex', justifyContent: 'space-between', paddingTop: 12,
              fontSize: 20, fontWeight: 'bold',
            }}>
              <span>合计</span>
              <span style={{ color: C.accent }}>{fen2yuan(shift.total_revenue_fen)}</span>
            </div>
          </div>

          {/* 自动刷新提示 */}
          <div style={{
            textAlign: 'center', fontSize: 14, color: C.muted, marginBottom: 16,
          }}>
            数据每 60 秒自动刷新
          </div>

          {/* 交班按钮 */}
          <button
            onClick={() => navigate('/handover')}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: C.accent, border: 'none',
              color: C.white, fontSize: 20, fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            交班
          </button>
        </div>
      )}
    </div>
  );
}
