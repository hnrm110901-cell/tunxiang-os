/**
 * 日结报表页 — DailySettlementPage
 * 店长在当日营业结束后进行日结对账、确认日结
 *
 * 数据来源：
 *   GET  http://localhost:8005/api/v1/ops/daily-settlement?date=YYYY-MM-DD
 *   POST http://localhost:8005/api/v1/ops/daily-settlement/close
 *
 * 纯 inline style，禁止 Ant Design
 * 最小字体 16px，点击区域 ≥ 48×48 px，主操作 ≥ 88px 高
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ─────────────────────────────────────────
   设计 Token
───────────────────────────────────────── */
const T = {
  primary:   '#FF6B35',
  primaryAct:'#E55A28',
  navy:      '#1E2A3A',
  navyLight: '#2C3E50',
  success:   '#0F6E56',
  danger:    '#A32D2D',
  warning:   '#BA7517',
  info:      '#185FA5',
  textPri:   '#E2E8F0',
  textSec:   '#94A3B8',
  border:    '#2C3E50',
  bgBase:    '#0B1820',
  bgCard:    '#112230',
  bgCard2:   '#162A38',
  white:     '#FFFFFF',
} as const;

const BASE_OPS  = 'http://localhost:8005';
const TENANT_ID = (window as unknown as Record<string, unknown>).__TENANT_ID__ as string | undefined || '';

/* ─────────────────────────────────────────
   工具函数
───────────────────────────────────────── */
const fen2yuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;

function fmtDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

function weekday(d: Date): string {
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
}

/* ─────────────────────────────────────────
   类型定义
───────────────────────────────────────── */
interface PaymentSummary {
  method:     string;
  label:      string;
  amount_fen: number;
  count:      number;
  color:      string;
}

interface ChannelSummary {
  channel: string;
  label:   string;
  count:   number;
  amount_fen: number;
}

interface RefundRecord {
  order_id:   string;
  time:       string;
  amount_fen: number;
  reason:     string;
}

interface DiscountRecord {
  order_id:   string;
  time:       string;
  amount_fen: number;
  type:       string;
}

interface CreditRecord {
  order_id:   string;
  company:    string;
  amount_fen: number;
  time:       string;
}

interface DailyData {
  date:               string;
  is_closed:          boolean;
  total_revenue_fen:  number;
  total_orders:       number;
  avg_ticket_fen:     number;
  table_turnover:     number;
  channels:           ChannelSummary[];
  payments:           PaymentSummary[];
  refunds:            RefundRecord[];
  discounts:          DiscountRecord[];
  credits:            CreditRecord[];
}

/* ─────────────────────────────────────────
   Mock 数据
───────────────────────────────────────── */
const MOCK: DailyData = {
  date: fmtDate(new Date()),
  is_closed: false,
  total_revenue_fen:  8650000,
  total_orders:       312,
  avg_ticket_fen:     27724,
  table_turnover:     2.8,
  channels: [
    { channel: 'dine_in',  label: '堂食',     count: 218, amount_fen: 5980000 },
    { channel: 'takeaway',  label: '外卖',     count: 64,  amount_fen: 1620000 },
    { channel: 'retail',    label: '零售',     count: 22,  amount_fen: 450000  },
    { channel: 'stored',    label: '储值充值', count: 8,   amount_fen: 600000  },
  ],
  payments: [
    { method: 'cash',     label: '现金',     amount_fen: 860000,  count: 45,  color: '#FAAD14' },
    { method: 'wechat',   label: '微信支付', amount_fen: 3850000, count: 142, color: '#07C160' },
    { method: 'alipay',   label: '支付宝',   amount_fen: 2180000, count: 78,  color: '#1677FF' },
    { method: 'unionpay', label: '银行卡',   amount_fen: 960000,  count: 26,  color: '#E6002D' },
    { method: 'stored',   label: '储值卡',   amount_fen: 620000,  count: 18,  color: '#9B59B6' },
    { method: 'credit',   label: '挂账',     amount_fen: 180000,  count: 3,   color: '#185FA5' },
  ],
  refunds: [
    { order_id: 'ORD-0402-0087', time: '12:35', amount_fen: 15800, reason: '菜品问题退款' },
    { order_id: 'ORD-0402-0156', time: '18:22', amount_fen: 8600,  reason: '顾客取消' },
  ],
  discounts: [
    { order_id: 'ORD-0402-0045', time: '11:40', amount_fen: 3200, type: '会员折扣' },
    { order_id: 'ORD-0402-0103', time: '13:15', amount_fen: 5000, type: '满减活动' },
    { order_id: 'ORD-0402-0211', time: '19:08', amount_fen: 2800, type: '手动抹零' },
  ],
  credits: [
    { order_id: 'ORD-0402-0198', company: '长沙科技有限公司', amount_fen: 128000, time: '12:50' },
    { order_id: 'ORD-0402-0267', company: '湖南教育集团',     amount_fen: 52000,  time: '18:40' },
  ],
};

/* ─────────────────────────────────────────
   确认弹窗
───────────────────────────────────────── */
interface ConfirmDialogProps {
  title:    string;
  message:  string;
  onOk:     () => void;
  onCancel: () => void;
}

function ConfirmDialog({ title, message, onOk, onCancel }: ConfirmDialogProps) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: T.bgCard, borderRadius: 16,
        padding: 32, maxWidth: 460, width: '90%',
        border: `1px solid ${T.border}`,
        boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 22, color: T.textPri }}>{title}</h3>
        <p style={{ margin: '0 0 28px', fontSize: 18, color: T.textSec, lineHeight: 1.6 }}>{message}</p>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, minHeight: 56, borderRadius: 12,
              background: T.bgCard2, border: `1px solid ${T.border}`,
              color: T.textPri, fontSize: 18, fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            onClick={onOk}
            style={{
              flex: 2, minHeight: 56, borderRadius: 12,
              background: T.danger, border: 'none',
              color: T.white, fontSize: 18, fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            确认日结
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────
   横向柱状图（纯CSS）
───────────────────────────────────────── */
function PaymentBar({ payments, total }: { payments: PaymentSummary[]; total: number }) {
  return (
    <div style={{
      background: T.bgCard, borderRadius: 16,
      border: `1px solid ${T.border}`, padding: 20,
    }}>
      {/* 柱状图 */}
      <div style={{
        display: 'flex', height: 32, borderRadius: 8, overflow: 'hidden',
        marginBottom: 20, background: T.bgCard2,
      }}>
        {payments.map(p => {
          const pct = total > 0 ? (p.amount_fen / total) * 100 : 0;
          if (pct < 0.5) return null;
          return (
            <div
              key={p.method}
              title={`${p.label}: ${pct.toFixed(1)}%`}
              style={{
                width: `${pct}%`, background: p.color,
                minWidth: pct > 2 ? 2 : 0,
                transition: 'width 0.3s',
              }}
            />
          );
        })}
      </div>

      {/* 图例 + 数值 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 24px' }}>
        {payments.map(p => {
          const pct = total > 0 ? ((p.amount_fen / total) * 100).toFixed(1) : '0.0';
          return (
            <div key={p.method} style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 140 }}>
              <div style={{ width: 14, height: 14, borderRadius: 4, background: p.color, flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 16, color: T.textSec }}>{p.label} ({pct}%)</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: T.textPri }}>{fen2yuan(p.amount_fen)}</div>
                <div style={{ fontSize: 14, color: T.textSec }}>{p.count}笔</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────
   打印工具
───────────────────────────────────────── */
function buildDailyPrintText(data: DailyData): string {
  const sep = () => '='.repeat(40);
  const dash = () => '-'.repeat(40);
  const right = (l: string, r: string) => {
    const space = Math.max(1, 40 - l.length - r.length);
    return l + ' '.repeat(space) + r;
  };

  const lines: string[] = [
    sep(),
    '          日  结  报  表'.padEnd(40),
    sep(),
    right('日期:', data.date),
    right('今日营收:', fen2yuan(data.total_revenue_fen)),
    right('订单数:', `${data.total_orders} 单`),
    right('客单价:', fen2yuan(data.avg_ticket_fen)),
    right('翻台率:', `${data.table_turnover}x`),
    sep(),
    '【收入明细】'.padEnd(40),
    dash(),
    ...data.channels.map(c => right(`  ${c.label}(${c.count}笔):`, fen2yuan(c.amount_fen))),
    sep(),
    '【支付方式】'.padEnd(40),
    dash(),
    ...data.payments.map(p => right(`  ${p.label}(${p.count}笔):`, fen2yuan(p.amount_fen))),
    sep(),
  ];

  if (data.refunds.length > 0) {
    lines.push('【退款记录】'.padEnd(40), dash());
    data.refunds.forEach(r => lines.push(right(`  ${r.order_id}:`, `-${fen2yuan(r.amount_fen)}`)));
    lines.push(sep());
  }

  lines.push('', '  店长签字: ___________________', '', sep());
  return lines.join('\n');
}

async function callPrint(content: string): Promise<void> {
  const w = window as unknown as Record<string, unknown>;
  if (typeof w.TXBridge === 'object' && w.TXBridge !== null) {
    const bridge = w.TXBridge as { print?: (s: string) => void };
    if (typeof bridge.print === 'function') {
      bridge.print(content);
      return;
    }
  }
  await fetch('/api/v1/print/daily-settlement', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': TENANT_ID },
    body: JSON.stringify({ content }),
  });
}

/* ─────────────────────────────────────────
   主组件
───────────────────────────────────────── */
export function DailySettlementPage() {
  const navigate = useNavigate();

  const [selectedDate, setSelectedDate] = useState<Date>(new Date());
  const [data, setData]         = useState<DailyData | null>(null);
  const [loading, setLoading]   = useState(true);
  const [isMock, setIsMock]     = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [closing, setClosing]   = useState(false);
  const [printing, setPrinting] = useState(false);
  const [printOk, setPrintOk]   = useState(false);

  const dateStr = fmtDate(selectedDate);
  const isToday = dateStr === fmtDate(new Date());

  /* ── 加载数据 ── */
  const loadData = useCallback(async (date: string) => {
    setLoading(true);
    setError(null);
    try {
      const headers: HeadersInit = { 'X-Tenant-ID': TENANT_ID };
      const res = await fetch(`${BASE_OPS}/api/v1/ops/daily-settlement?date=${date}`, { headers });
      if (!res.ok) throw new Error(`日结数据获取失败 (${res.status})`);
      const json = await res.json();
      setData(json.data ?? json);
      setIsMock(false);
    } catch (e) {
      setData({ ...MOCK, date });
      setIsMock(true);
      setError(e instanceof Error ? e.message : '网络异常');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadData(dateStr); }, [dateStr, loadData]);

  /* ── 日期切换 ── */
  const shiftDate = (days: number) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + days);
    if (d > new Date()) return; // 不能选未来
    setSelectedDate(d);
  };

  /* ── 打印日结单 ── */
  const handlePrint = async () => {
    if (!data) return;
    setPrinting(true);
    try {
      await callPrint(buildDailyPrintText(data));
      setPrintOk(true);
      setTimeout(() => setPrintOk(false), 3000);
    } catch {
      alert('打印失败，请检查打印机连接');
    } finally {
      setPrinting(false);
    }
  };

  /* ── 确认日结 ── */
  const handleClose = async () => {
    setShowConfirm(false);
    setClosing(true);
    navigator.vibrate?.(50);
    try {
      const res = await fetch(`${BASE_OPS}/api/v1/ops/daily-settlement/close`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': TENANT_ID,
        },
        body: JSON.stringify({ date: dateStr }),
      });
      if (!res.ok) throw new Error('日结失败');
      setData(prev => prev ? { ...prev, is_closed: true } : prev);
    } catch {
      if (isMock) {
        setData(prev => prev ? { ...prev, is_closed: true } : prev);
      } else {
        alert('日结请求失败，请重试');
      }
    } finally {
      setClosing(false);
    }
  };

  /* ── 加载中 ── */
  if (loading) {
    return (
      <div style={{
        background: T.bgBase, minHeight: '100vh',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: T.textSec, fontSize: 20,
      }}>
        加载日结数据中...
      </div>
    );
  }

  if (!data) return null;

  const totalPaymentFen = data.payments.reduce((s, p) => s + p.amount_fen, 0);

  return (
    <div style={{
      background: T.bgBase, minHeight: '100vh', color: T.textPri,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    }}>

      {/* ── Mock 横幅 ── */}
      {isMock && (
        <div style={{
          background: `${T.warning}25`, borderBottom: `2px solid ${T.warning}`,
          padding: '10px 20px', textAlign: 'center',
          fontSize: 16, color: T.warning, fontWeight: 600,
        }}>
          演示数据（API 未连通：{error}）
        </div>
      )}

      {/* ── 已日结标识 ── */}
      {data.is_closed && (
        <div style={{
          background: `${T.success}25`, borderBottom: `2px solid ${T.success}`,
          padding: '12px 20px', textAlign: 'center',
          fontSize: 18, color: T.success, fontWeight: 700,
        }}>
          {dateStr} 已日结
        </div>
      )}

      {/* ═══════════════════════════════════════
          顶部：日期选择
      ═══════════════════════════════════════ */}
      <div style={{
        background: T.navy, padding: '16px 24px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: `1px solid ${T.border}`,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 48, minHeight: 48, borderRadius: 12,
            background: T.bgCard, border: `1px solid ${T.border}`,
            color: T.textPri, fontSize: 18, cursor: 'pointer',
          }}
        >
          返回
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <button
            onClick={() => shiftDate(-1)}
            style={{
              minWidth: 48, minHeight: 48, borderRadius: 12,
              background: T.bgCard, border: `1px solid ${T.border}`,
              color: T.textPri, fontSize: 24, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            &lt;
          </button>
          <div style={{ textAlign: 'center', minWidth: 160 }}>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{dateStr}</div>
            <div style={{ fontSize: 16, color: T.textSec }}>{weekday(selectedDate)}{isToday ? ' (今天)' : ''}</div>
          </div>
          <button
            onClick={() => shiftDate(1)}
            disabled={isToday}
            style={{
              minWidth: 48, minHeight: 48, borderRadius: 12,
              background: isToday ? T.bgCard2 : T.bgCard,
              border: `1px solid ${T.border}`,
              color: isToday ? T.textSec : T.textPri, fontSize: 24,
              cursor: isToday ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            &gt;
          </button>
        </div>

        <div style={{ fontSize: 20, fontWeight: 700, color: T.textSec }}>
          日结报表
        </div>
      </div>

      {/* ═══════════════════════════════════════
          主内容区
      ═══════════════════════════════════════ */}
      <div style={{
        padding: '20px 24px 160px',
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
      }}>

        {/* ── 营业概览（4张大卡片） ── */}
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
            营业概览
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
            <BigCard label="今日营收" value={fen2yuan(data.total_revenue_fen)} color={T.primary} />
            <BigCard label="订单数" value={`${data.total_orders}`} unit="单" color={T.textPri} />
            <BigCard label="客单价" value={fen2yuan(data.avg_ticket_fen)} color={T.info} />
            <BigCard label="翻台率" value={`${data.table_turnover}`} unit="x" color={T.success} />
          </div>
        </section>

        {/* ── 收入明细 ── */}
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
            收入明细
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            {data.channels.map(c => (
              <div key={c.channel} style={{
                background: T.bgCard, borderRadius: 16, padding: '18px 20px',
                border: `1px solid ${T.border}`,
              }}>
                <div style={{ fontSize: 16, color: T.textSec, marginBottom: 8 }}>{c.label}</div>
                <div style={{ fontSize: 28, fontWeight: 800, color: T.textPri, marginBottom: 4 }}>
                  {fen2yuan(c.amount_fen)}
                </div>
                <div style={{ fontSize: 16, color: T.textSec }}>{c.count} 笔</div>
              </div>
            ))}
          </div>
        </section>

        {/* ── 支付方式汇总（横向柱状图） ── */}
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
            支付方式汇总
          </h2>
          <PaymentBar payments={data.payments} total={totalPaymentFen} />
        </section>

        {/* ── 异常记录：退款 ── */}
        {data.refunds.length > 0 && (
          <section style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
              退款记录（{data.refunds.length}笔）
            </h2>
            <div style={{
              background: T.bgCard, borderRadius: 16,
              border: `1px solid ${T.border}`, overflow: 'hidden',
            }}>
              {data.refunds.map((r, idx) => (
                <div key={r.order_id} style={{
                  display: 'flex', alignItems: 'center', gap: 16,
                  padding: '14px 20px', minHeight: 56,
                  borderBottom: idx < data.refunds.length - 1 ? `1px solid ${T.border}` : 'none',
                }}>
                  <span style={{ fontSize: 16, color: T.textSec, minWidth: 50 }}>{r.time}</span>
                  <span style={{ fontSize: 16, color: T.textSec, flex: '0 0 140px' }}>{r.order_id}</span>
                  <span style={{ flex: 1, fontSize: 16, color: T.textPri }}>{r.reason}</span>
                  <span style={{ fontSize: 20, fontWeight: 700, color: T.danger }}>
                    -{fen2yuan(r.amount_fen)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── 异常记录：折扣 ── */}
        {data.discounts.length > 0 && (
          <section style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
              折扣记录（{data.discounts.length}笔）
            </h2>
            <div style={{
              background: T.bgCard, borderRadius: 16,
              border: `1px solid ${T.border}`, overflow: 'hidden',
            }}>
              {data.discounts.map((d, idx) => (
                <div key={`${d.order_id}-${idx}`} style={{
                  display: 'flex', alignItems: 'center', gap: 16,
                  padding: '14px 20px', minHeight: 56,
                  borderBottom: idx < data.discounts.length - 1 ? `1px solid ${T.border}` : 'none',
                }}>
                  <span style={{ fontSize: 16, color: T.textSec, minWidth: 50 }}>{d.time}</span>
                  <span style={{ fontSize: 16, color: T.textSec, flex: '0 0 140px' }}>{d.order_id}</span>
                  <span style={{ flex: 1, fontSize: 16, color: T.textPri }}>{d.type}</span>
                  <span style={{ fontSize: 20, fontWeight: 700, color: T.warning }}>
                    -{fen2yuan(d.amount_fen)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── 异常记录：挂账 ── */}
        {data.credits.length > 0 && (
          <section style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
              挂账记录（{data.credits.length}笔）
            </h2>
            <div style={{
              background: T.bgCard, borderRadius: 16,
              border: `1px solid ${T.border}`, overflow: 'hidden',
            }}>
              {data.credits.map((c, idx) => (
                <div key={c.order_id} style={{
                  display: 'flex', alignItems: 'center', gap: 16,
                  padding: '14px 20px', minHeight: 56,
                  borderBottom: idx < data.credits.length - 1 ? `1px solid ${T.border}` : 'none',
                }}>
                  <span style={{ fontSize: 16, color: T.textSec, minWidth: 50 }}>{c.time}</span>
                  <span style={{ fontSize: 16, color: T.textSec, flex: '0 0 140px' }}>{c.order_id}</span>
                  <span style={{ flex: 1, fontSize: 16, color: T.textPri }}>{c.company}</span>
                  <span style={{ fontSize: 20, fontWeight: 700, color: T.info }}>
                    {fen2yuan(c.amount_fen)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      {/* ═══════════════════════════════════════
          底部操作栏（固定）
      ═══════════════════════════════════════ */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: T.navy,
        borderTop: `1px solid ${T.border}`,
        padding: '12px 24px',
        display: 'flex', gap: 12,
        zIndex: 100,
      }}>
        {/* 打印日结单 */}
        <button
          onClick={() => void handlePrint()}
          disabled={printing}
          style={{
            flex: 1, minHeight: 60, borderRadius: 14,
            background: printing ? T.navyLight : printOk ? T.success : T.navyLight,
            border: `1px solid ${printOk ? T.success : T.border}`,
            color: printOk ? T.white : T.textPri,
            fontSize: 18, fontWeight: 600,
            cursor: printing ? 'wait' : 'pointer',
            transition: 'all 0.2s',
          }}
        >
          {printing ? '打印中...' : printOk ? '已打印' : '打印日结单'}
        </button>

        {/* 确认日结 — 88px 高主操作 */}
        {data.is_closed ? (
          <div style={{
            flex: 2, minHeight: 88, borderRadius: 14,
            background: `${T.success}30`, border: `2px solid ${T.success}`,
            color: T.success, fontSize: 22, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            已日结
          </div>
        ) : (
          <button
            onClick={() => { navigator.vibrate?.(50); setShowConfirm(true); }}
            disabled={closing}
            style={{
              flex: 2, minHeight: 88, borderRadius: 14,
              background: closing ? T.navyLight : T.primary,
              border: 'none',
              color: T.white, fontSize: 22, fontWeight: 700,
              cursor: closing ? 'wait' : 'pointer',
              transition: 'background 0.15s',
              boxShadow: closing ? 'none' : `0 4px 12px ${T.primary}60`,
            }}
          >
            {closing ? '日结中...' : '确认日结'}
          </button>
        )}
      </div>

      {/* ── 确认弹窗 ── */}
      {showConfirm && (
        <ConfirmDialog
          title="确认日结？"
          message={`${dateStr} 的营业数据将被锁定，日结后不可修改。营收 ${fen2yuan(data.total_revenue_fen)} / ${data.total_orders} 单。确认继续？`}
          onOk={() => void handleClose()}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
}

/* ─────────────────────────────────────────
   大数字卡片
───────────────────────────────────────── */
interface BigCardProps {
  label: string;
  value: string;
  unit?:  string;
  color: string;
}

function BigCard({ label, value, unit, color }: BigCardProps) {
  return (
    <div style={{
      background: T.bgCard, borderRadius: 16,
      padding: '18px 20px',
      border: `1px solid ${T.border}`,
      borderTop: `3px solid ${color}`,
      minHeight: 100,
    }}>
      <div style={{ fontSize: 16, color: T.textSec, marginBottom: 8 }}>{label}</div>
      <div style={{
        fontSize: 36, fontWeight: 800, color,
        display: 'flex', alignItems: 'baseline', gap: 4,
      }}>
        {value}
        {unit && <span style={{ fontSize: 18, fontWeight: 500, color: T.textSec }}>{unit}</span>}
      </div>
    </div>
  );
}
