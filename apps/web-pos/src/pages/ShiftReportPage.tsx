/**
 * 班次报告页 — ShiftReportPage
 * 收银员交接班前查看本班次完整财务数据、收银对账、支持打印交接单
 *
 * 数据来源：
 *   GET /api/v1/trade/shifts/current
 *   GET /api/v1/trade/shift-report?shift_id=
 *   GET /api/v1/trade/orders?shift_id=&status=paid
 *
 * 兼容：POS 横屏 / 竖屏，纯内联 CSS，禁止 Ant Design
 * 最小字体 16px，点击区域 ≥ 48×48 px
 * 打印：window.TXBridge?.print() 或 HTTP POST /api/v1/print/shift-report
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';

/* ─────────────────────────────────────────
   设计 Token（与屯象OS Token 规范对齐）
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

/* ─────────────────────────────────────────
   工具函数
───────────────────────────────────────── */
/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;
const fmt = (d: string | null): string => d ? d.replace('T', ' ').slice(0, 16) : '—';

/** 计算已工作时长（mm:ss 或 hh:mm:ss） */
function elapsedSince(startISO: string): string {
  const diff = Date.now() - new Date(startISO).getTime();
  if (diff < 0) return '0分钟';
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  return h > 0 ? `${h}小时${m}分钟` : `${m}分钟`;
}

/* ─────────────────────────────────────────
   类型定义
───────────────────────────────────────── */
interface ShiftInfo {
  shift_id:      string;
  store_name:    string;
  cashier_name:  string;
  start_time:    string;
  end_time:      string | null;
  status:        'active' | 'closed';
}

interface PaymentBreakdown {
  method:      string;
  label:       string;
  amount_fen:  number;
  count:       number;
  color:       string;
  icon:        string;
}

interface DiscountItem {
  type:        string;
  label:       string;
  count:       number;
  amount_fen:  number;
}

interface ShiftReport {
  total_revenue_fen:     number;
  total_orders:          number;
  void_orders:           number;
  total_discount_fen:    number;
  cash_fen:              number;
  electronic_fen:        number;
  refund_fen:            number;
  payments:              PaymentBreakdown[];
  discounts:             DiscountItem[];
}

interface Order {
  order_id:       string;
  created_at:     string;
  table_no:       string;
  total_fen:      number;
  payment_method: string;
  status:         'paid' | 'void' | 'refunded';
}

/* ─────────────────────────────────────────
   Mock 数据（API 失败时降级展示）
───────────────────────────────────────── */
const MOCK_SHIFT: ShiftInfo = {
  shift_id:     'SH-20260402-003',
  store_name:   '尝在一起·长沙湘江店',
  cashier_name: '李梅',
  start_time:   '2026-04-02T10:00:00',
  end_time:     null,
  status:       'active',
};

const MOCK_REPORT: ShiftReport = {
  total_revenue_fen:  3860000,
  total_orders:       128,
  void_orders:        3,
  total_discount_fen: 86500,
  refund_fen:         32000,
  cash_fen:           426000,
  electronic_fen:     3434000,
  payments: [
    { method: 'cash',       label: '现金',    amount_fen: 426000,  count: 24, color: '#FAAD14', icon: '💵' },
    { method: 'wechat',     label: '微信支付', amount_fen: 1850000, count: 62, color: '#07C160', icon: '💚' },
    { method: 'alipay',     label: '支付宝',  amount_fen: 876000,  count: 28, color: '#1677FF', icon: '💙' },
    { method: 'unionpay',   label: '银联刷卡', amount_fen: 428000,  count: 8,  color: '#E6002D', icon: '💳' },
    { method: 'stored',     label: '储值卡',  amount_fen: 218000,  count: 5,  color: '#9B59B6', icon: '🎫' },
    { method: 'credit',     label: '企业挂账', amount_fen: 62000,   count: 1,  color: '#185FA5', icon: '🏢' },
  ],
  discounts: [
    { type: 'member',    label: '会员折扣', count: 38, amount_fen: 45000 },
    { type: 'coupon',    label: '优惠券',   count: 12, amount_fen: 28000 },
    { type: 'manual',    label: '手动抹零', count: 5,  amount_fen: 8500  },
    { type: 'activity',  label: '活动优惠', count: 3,  amount_fen: 5000  },
  ],
};

const MOCK_ORDERS: Order[] = Array.from({ length: 20 }, (_, i) => ({
  order_id:       `ORD-20260402-${String(i + 1).padStart(4, '0')}`,
  created_at:     `2026-04-02T${String(10 + Math.floor(i * 0.6)).padStart(2, '0')}:${String((i * 7) % 60).padStart(2, '0')}:00`,
  table_no:       `A${Math.floor(Math.random() * 20) + 1}`,
  total_fen:      Math.floor(Math.random() * 60000) + 5000,
  payment_method: ['微信支付', '支付宝', '现金', '银联刷卡', '储值卡'][Math.floor(Math.random() * 5)],
  status:         i % 15 === 0 ? 'void' : 'paid',
}));

/* ─────────────────────────────────────────
   打印工具
───────────────────────────────────────── */
const TENANT_ID = (window as unknown as Record<string, unknown>).__TENANT_ID__ as string | undefined || '';

function buildPrintText(shift: ShiftInfo, report: ShiftReport, orders: Order[]): string {
  const line  = (s = '')   => s.padEnd(40, ' ');
  const sep   = ()          => '='.repeat(40);
  const dash  = ()          => '-'.repeat(40);
  const right = (l: string, r: string) => {
    const space = Math.max(1, 40 - l.length - r.length);
    return l + ' '.repeat(space) + r;
  };

  const now = new Date().toLocaleString('zh-CN', { hour12: false });
  const lines: string[] = [
    sep(),
    line('          交  接  班  报  告'),
    sep(),
    right('门店:', shift.store_name.slice(0, 16)),
    right('收银员:', shift.cashier_name),
    right('班次号:', shift.shift_id),
    right('开班时间:', fmt(shift.start_time)),
    right('结束时间:', shift.end_time ? fmt(shift.end_time) : '(进行中)'),
    right('打印时间:', now),
    sep(),
    line('【核心数据】'),
    dash(),
    right('本班营收:', fen2yuan(report.total_revenue_fen)),
    right('订单总数:', `${report.total_orders} 单`),
    right('现金收入:', fen2yuan(report.cash_fen)),
    right('电子支付:', fen2yuan(report.electronic_fen)),
    right('折扣总额:', `-${fen2yuan(report.total_discount_fen)}`),
    right('作废单数:', `${report.void_orders} 单`),
    sep(),
    line('【支付方式明细】'),
    dash(),
    ...report.payments.map(p => right(`  ${p.label}(${p.count}笔):`, fen2yuan(p.amount_fen))),
    dash(),
    right('合计:', fen2yuan(report.total_revenue_fen)),
    sep(),
  ];

  if (report.discounts.length > 0) {
    lines.push(line('【折扣明细】'));
    lines.push(dash());
    report.discounts.forEach(d => {
      lines.push(right(`  ${d.label}(${d.count}次):`, `-${fen2yuan(d.amount_fen)}`));
    });
    lines.push(dash());
    lines.push(right('折扣合计:', `-${fen2yuan(report.total_discount_fen)}`));
    lines.push(sep());
  }

  lines.push(line('【最近订单（最多20笔）】'));
  lines.push(dash());
  lines.push('时间    桌号  金额      状态');
  orders.slice(0, 20).forEach(o => {
    const t    = o.created_at.slice(11, 16);
    const tbl  = o.table_no.padEnd(4);
    const amt  = fen2yuan(o.total_fen).padStart(9);
    const stat = o.status === 'void' ? '[作废]' : o.status === 'refunded' ? '[退款]' : '';
    lines.push(`${t}  ${tbl}  ${amt}  ${stat}`);
  });
  lines.push(sep());
  lines.push(line());
  lines.push(line('  收银员签字: ___________________'));
  lines.push(line('  接班人签字: ___________________'));
  lines.push(line());
  lines.push(sep());

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
  // 降级：HTTP POST 打印接口
  await fetch('/api/v1/print/shift-report', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
    },
    body: JSON.stringify({ content }),
  });
}

/* ─────────────────────────────────────────
   子组件：确认弹窗
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
        padding: 32, maxWidth: 420, width: '90%',
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
              background: T.primary, border: 'none',
              color: T.white, fontSize: 18, fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            确认完成交接
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────
   主页面组件
───────────────────────────────────────── */
export function ShiftReportPage() {
  const navigate = useNavigate();

  const [shift,       setShift]       = useState<ShiftInfo | null>(null);
  const [report,      setReport]      = useState<ShiftReport | null>(null);
  const [orders,      setOrders]      = useState<Order[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState<string | null>(null);
  const [isMock,      setIsMock]      = useState(false);
  const [printing,    setPrinting]    = useState(false);
  const [handovering, setHandovering] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [printOk,     setPrintOk]     = useState(false);
  const [handoverDone, setHandoverDone] = useState(false);

  /* ── 收银对账 ── */
  const [actualCashYuan, setActualCashYuan] = useState('');
  const [diffReason, setDiffReason] = useState('');

  /** 系统应收（现金部分） */
  const systemCashFen = report?.cash_fen ?? 0;
  /** 实际交款（分） */
  const actualCashFen = useMemo(() => {
    const v = parseFloat(actualCashYuan);
    return Number.isFinite(v) ? Math.round(v * 100) : 0;
  }, [actualCashYuan]);
  /** 差异（分）：正=长款，负=短款 */
  const diffFen = actualCashFen - systemCashFen;

  /** 已工作时长（实时更新） */
  const [elapsed, setElapsed] = useState('');
  useEffect(() => {
    if (!shift) return;
    const tick = () => setElapsed(elapsedSince(shift.start_time));
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, [shift]);

  /* ── 加载数据 ── */
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const headers: HeadersInit = { 'X-Tenant-ID': TENANT_ID };

      const shiftRes = await fetch('/api/v1/trade/shifts/current', { headers });
      if (!shiftRes.ok) throw new Error('班次信息获取失败');
      const shiftJson = await shiftRes.json();
      const shiftData: ShiftInfo = shiftJson.data ?? shiftJson;
      setShift(shiftData);

      const reportRes = await fetch(`/api/v1/trade/shift-report?shift_id=${shiftData.shift_id}`, { headers });
      if (!reportRes.ok) throw new Error('班次报告获取失败');
      const reportJson = await reportRes.json();
      setReport(reportJson.data ?? reportJson);

      const ordersRes = await fetch(`/api/v1/trade/orders?shift_id=${shiftData.shift_id}&status=paid&page=1&size=20`, { headers });
      if (!ordersRes.ok) throw new Error('订单列表获取失败');
      const ordersJson = await ordersRes.json();
      const items = ordersJson.data?.items ?? ordersJson.items ?? ordersJson;
      setOrders(Array.isArray(items) ? items : []);
    } catch (e) {
      // API 失败 → 降级 Mock 数据
      setShift(MOCK_SHIFT);
      setReport(MOCK_REPORT);
      setOrders(MOCK_ORDERS);
      setIsMock(true);
      setError(e instanceof Error ? e.message : '网络异常');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadData(); }, [loadData]);

  /* ── 打印 ── */
  const handlePrint = async () => {
    if (!shift || !report) return;
    setPrinting(true);
    try {
      const content = buildPrintText(shift, report, orders);
      await callPrint(content);
      setPrintOk(true);
      setTimeout(() => setPrintOk(false), 3000);
    } catch {
      alert('打印失败，请检查打印机连接');
    } finally {
      setPrinting(false);
    }
  };

  /* ── 确认交班 ── */
  const handleHandover = async () => {
    setShowConfirm(false);
    setHandovering(true);
    navigator.vibrate?.(50);
    try {
      const res = await fetch('/api/v1/trade/shifts/handover', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': TENANT_ID,
        },
        body: JSON.stringify({
          shift_id: shift?.shift_id,
          actual_cash_fen: actualCashFen,
          diff_fen: diffFen,
          diff_reason: diffReason || undefined,
        }),
      });
      if (!res.ok) throw new Error('交接失败');
      setHandoverDone(true);
    } catch {
      // Mock 模式也显示成功页
      if (isMock) {
        setHandoverDone(true);
      } else {
        alert('交接请求失败，请重试');
      }
    } finally {
      setHandovering(false);
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
        加载班次数据中…
      </div>
    );
  }

  if (!shift || !report) return null;

  const now = new Date().toLocaleString('zh-CN', { hour12: false });

  /* ── 交班成功页 ── */
  if (handoverDone) {
    return (
      <div style={{
        background: T.bgBase, minHeight: '100vh',
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        color: T.textPri, padding: 32,
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
      }}>
        <div style={{
          width: 96, height: 96, borderRadius: 48,
          background: `${T.success}30`, marginBottom: 24,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 48, color: T.success, fontWeight: 800,
        }}>
          OK
        </div>
        <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 12 }}>交班成功</h1>
        <p style={{ fontSize: 18, color: T.textSec, marginBottom: 32, textAlign: 'center', lineHeight: 1.6 }}>
          班次 {shift.shift_id} 已关闭<br />
          收银员：{shift.cashier_name} / 销售 {report.total_orders} 单 / 营收 {fen2yuan(report.total_revenue_fen)}
        </p>

        {/* 对账汇总 */}
        {actualCashFen > 0 && (
          <div style={{
            background: T.bgCard, borderRadius: 16, padding: '20px 28px',
            border: `1px solid ${T.border}`, marginBottom: 32, width: '100%', maxWidth: 400,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 17 }}>
              <span style={{ color: T.textSec }}>系统应收(现金)</span>
              <span>{fen2yuan(systemCashFen)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 17 }}>
              <span style={{ color: T.textSec }}>实际交款</span>
              <span>{fen2yuan(actualCashFen)}</span>
            </div>
            <div style={{
              display: 'flex', justifyContent: 'space-between', fontSize: 20, fontWeight: 700,
              paddingTop: 8, borderTop: `1px solid ${T.border}`,
              color: diffFen > 0 ? T.success : diffFen < 0 ? T.danger : T.textPri,
            }}>
              <span>{diffFen > 0 ? '长款' : diffFen < 0 ? '短款' : '平账'}</span>
              <span>{diffFen !== 0 ? fen2yuan(Math.abs(diffFen)) : '--'}</span>
            </div>
          </div>
        )}

        <div style={{
          background: `${T.info}20`, borderRadius: 12, padding: '14px 24px',
          fontSize: 17, color: T.info, marginBottom: 40, textAlign: 'center',
        }}>
          请提醒下一班收银员开班签到
        </div>

        <button
          onClick={() => navigate('/dashboard')}
          style={{
            minHeight: 64, minWidth: 240, borderRadius: 16,
            background: T.primary, border: 'none',
            color: T.white, fontSize: 20, fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          返回主页
        </button>
      </div>
    );
  }

  /* ── 渲染 ── */
  return (
    <div style={{
      background: T.bgBase, minHeight: '100vh',
      color: T.textPri,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    }}>

      {/* ── Mock 横幅 ── */}
      {isMock && (
        <div style={{
          background: `${T.warning}25`, borderBottom: `2px solid ${T.warning}`,
          padding: '10px 20px', textAlign: 'center',
          fontSize: 16, color: T.warning, fontWeight: 600,
        }}>
          演示数据（API 未连通：{error}）· 所有数字仅供参考
        </div>
      )}

      {/* ═══════════════════════════════════════
          顶部信息栏
      ═══════════════════════════════════════ */}
      <div style={{
        background: T.navy,
        padding: '16px 24px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 12,
        borderBottom: `1px solid ${T.border}`,
      }}>
        {/* 门店 + 班次信息 */}
        <div style={{ flex: '1 1 300px', minWidth: 0 }}>
          <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
            {shift.store_name}
          </div>
          <div style={{ fontSize: 17, color: T.textSec, display: 'flex', flexWrap: 'wrap', gap: '4px 16px' }}>
            <span>收银员：{shift.cashier_name}</span>
            <span>班次：{shift.shift_id}</span>
            <span>
              {fmt(shift.start_time)} ～ {shift.end_time ? fmt(shift.end_time) : '进行中'}
            </span>
            {elapsed && <span style={{ color: T.primary, fontWeight: 600 }}>已工作 {elapsed}</span>}
          </div>
        </div>

        {/* 当前时间 */}
        <div style={{ fontSize: 16, color: T.textSec, whiteSpace: 'nowrap' }}>
          {now}
        </div>

        {/* 打印按钮 */}
        <button
          onClick={() => void handlePrint()}
          disabled={printing}
          style={{
            minHeight: 56, minWidth: 120, padding: '0 24px',
            borderRadius: 12, border: 'none',
            background: printOk ? T.success : printing ? T.navyLight : T.primary,
            color: T.white, fontSize: 18, fontWeight: 700,
            cursor: printing ? 'wait' : 'pointer',
            transition: 'background 0.2s',
            display: 'flex', alignItems: 'center', gap: 8,
          }}
        >
          {printing ? '打印中…' : printOk ? '✓ 已打印' : '打印交接单'}
        </button>
      </div>

      {/* ═══════════════════════════════════════
          主内容区（可滚动）
      ═══════════════════════════════════════ */}
      <div style={{
        padding: '20px 24px 120px',
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
      }}>

        {/* ── 核心数据区（2x3 大字卡片） ── */}
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
            核心数据
          </h2>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 12,
          }}>
            <KPICard label="销售笔数" value={`${report.total_orders}`} unit="单" valueFontSize={48} />
            <KPICard label="销售总额" value={fen2yuan(report.total_revenue_fen)} valueColor={T.primary} valueFontSize={48} />
            <KPICard label="现金收款" value={fen2yuan(report.cash_fen)} valueFontSize={48} />
            <KPICard label="微信/支付宝" value={fen2yuan(report.electronic_fen)} sub="电子支付合计" valueFontSize={48} />
            <KPICard label="退款金额" value={`-${fen2yuan(report.refund_fen ?? 0)}`} valueColor={T.danger} valueFontSize={48} />
            <KPICard label="折扣总额" value={`-${fen2yuan(report.total_discount_fen)}`} valueColor={T.danger} valueFontSize={48} />
          </div>
        </section>

        {/* ── 收银对账区 ── */}
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
            收银对账
          </h2>
          <div style={{
            background: T.bgCard, borderRadius: 16,
            border: `1px solid ${T.border}`, padding: 24,
          }}>
            {/* 系统应收 vs 实际交款 */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20, marginBottom: 20 }}>
              <div style={{ flex: '1 1 200px' }}>
                <div style={{ fontSize: 16, color: T.textSec, marginBottom: 6 }}>系统应收（现金）</div>
                <div style={{ fontSize: 36, fontWeight: 800, color: T.textPri }}>{fen2yuan(systemCashFen)}</div>
              </div>
              <div style={{ flex: '1 1 200px' }}>
                <div style={{ fontSize: 16, color: T.textSec, marginBottom: 6 }}>实际交款</div>
                <input
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  placeholder="输入实际现金金额"
                  value={actualCashYuan}
                  onChange={e => setActualCashYuan(e.target.value)}
                  style={{
                    width: '100%', height: 64, borderRadius: 12,
                    background: T.bgCard2, border: `2px solid ${T.border}`,
                    color: T.textPri, fontSize: 28, fontWeight: 700,
                    padding: '0 16px', boxSizing: 'border-box',
                    outline: 'none',
                  }}
                  onFocus={e => { e.currentTarget.style.borderColor = T.primary; }}
                  onBlur={e => { e.currentTarget.style.borderColor = T.border; }}
                />
              </div>
              <div style={{ flex: '1 1 200px' }}>
                <div style={{ fontSize: 16, color: T.textSec, marginBottom: 6 }}>差异</div>
                {actualCashYuan ? (
                  <div style={{
                    fontSize: 36, fontWeight: 800,
                    color: diffFen > 0 ? T.success : diffFen < 0 ? T.danger : T.textPri,
                  }}>
                    {diffFen > 0 ? `+${fen2yuan(diffFen)} 长款` : diffFen < 0 ? `${fen2yuan(diffFen)} 短款` : '平账'}
                  </div>
                ) : (
                  <div style={{ fontSize: 20, color: T.textSec, lineHeight: '36px' }}>请先输入实际交款</div>
                )}
              </div>
            </div>

            {/* 差异原因备注 */}
            <div>
              <div style={{ fontSize: 16, color: T.textSec, marginBottom: 6 }}>差异原因备注</div>
              <textarea
                placeholder="如有差异请简要说明原因..."
                value={diffReason}
                onChange={e => setDiffReason(e.target.value)}
                rows={2}
                style={{
                  width: '100%', borderRadius: 12,
                  background: T.bgCard2, border: `1px solid ${T.border}`,
                  color: T.textPri, fontSize: 17, padding: '12px 16px',
                  boxSizing: 'border-box', resize: 'vertical',
                  outline: 'none', fontFamily: 'inherit',
                }}
                onFocus={e => { e.currentTarget.style.borderColor = T.primary; }}
                onBlur={e => { e.currentTarget.style.borderColor = T.border; }}
              />
            </div>
          </div>
        </section>

        {/* ── 支付方式明细 ── */}
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
            支付方式明细
          </h2>
          <div style={{
            background: T.bgCard, borderRadius: 16,
            border: `1px solid ${T.border}`,
            padding: '4px 0',
          }}>
            {/* 水平滚动列表（中小屏竖屏兼容） */}
            <div style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 0,
            }}>
              {report.payments.map((p, idx) => (
                <div
                  key={p.method}
                  style={{
                    flex: '1 1 140px',
                    padding: '16px 20px',
                    borderRight: idx < report.payments.length - 1 ? `1px solid ${T.border}` : 'none',
                    borderBottom: `1px solid ${T.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    minHeight: 72,
                  }}
                >
                  <div style={{
                    width: 44, height: 44, borderRadius: 12,
                    background: `${p.color}25`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 22, flexShrink: 0,
                  }}>
                    <span style={{ fontSize: 20 }}>{p.icon}</span>
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 16, color: T.textSec, marginBottom: 2 }}>
                      {p.label}
                      <span style={{ fontSize: 14, color: T.textSec, marginLeft: 6 }}>
                        ({p.count}笔)
                      </span>
                    </div>
                    <div style={{
                      fontSize: 22, fontWeight: 700, color: p.color,
                    }}>
                      {fen2yuan(p.amount_fen)}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* 合计行 */}
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '12px 20px',
              borderTop: `1px solid ${T.border}`,
              fontSize: 18, fontWeight: 700,
            }}>
              <span style={{ color: T.textSec }}>合计</span>
              <span style={{ color: T.primary, fontSize: 22 }}>
                {fen2yuan(report.total_revenue_fen)}
              </span>
            </div>
          </div>
        </section>

        {/* ── 折扣明细 ── */}
        {report.discounts.length > 0 && (
          <section style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
              折扣明细
            </h2>
            <div style={{
              background: T.bgCard, borderRadius: 16,
              border: `1px solid ${T.border}`,
              overflow: 'hidden',
            }}>
              {report.discounts.map((d, idx) => (
                <div
                  key={d.type}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 16,
                    padding: '14px 20px', minHeight: 56,
                    borderBottom: idx < report.discounts.length - 1 ? `1px solid ${T.border}` : 'none',
                  }}
                >
                  <div style={{
                    flex: 1, fontSize: 18, fontWeight: 600, color: T.textPri,
                  }}>
                    {d.label}
                  </div>
                  <div style={{ fontSize: 16, color: T.textSec, minWidth: 60, textAlign: 'center' }}>
                    {d.count} 次
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: T.danger, minWidth: 100, textAlign: 'right' }}>
                    -{fen2yuan(d.amount_fen)}
                  </div>
                </div>
              ))}
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '14px 20px',
                borderTop: `1px solid ${T.border}`,
                fontSize: 18, fontWeight: 700,
              }}>
                <span style={{ color: T.textSec }}>折扣合计</span>
                <span style={{ color: T.danger }}>-{fen2yuan(report.total_discount_fen)}</span>
              </div>
            </div>
          </section>
        )}

        {/* ── 最近20笔订单 ── */}
        <section style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 20, color: T.textSec, margin: '0 0 12px', fontWeight: 600 }}>
            最近 {Math.min(orders.length, 20)} 笔订单
          </h2>
          <div style={{
            background: T.bgCard, borderRadius: 16,
            border: `1px solid ${T.border}`,
            overflow: 'hidden',
          }}>
            {/* 表头 */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '130px 80px 1fr 120px 80px',
              padding: '10px 20px',
              background: T.bgCard2,
              borderBottom: `1px solid ${T.border}`,
              fontSize: 16, fontWeight: 700, color: T.textSec,
              gap: 8,
            }}>
              <span>时间</span>
              <span>桌号</span>
              <span>金额</span>
              <span>支付方式</span>
              <span style={{ textAlign: 'center' }}>状态</span>
            </div>

            {/* 订单列表 */}
            <div style={{
              overflowY: 'auto',
              maxHeight: 520,
              WebkitOverflowScrolling: 'touch',
            }}>
              {orders.slice(0, 20).map((o, idx) => {
                const isVoid = o.status === 'void';
                const isRefund = o.status === 'refunded';
                return (
                  <div
                    key={o.order_id}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '130px 80px 1fr 120px 80px',
                      padding: '12px 20px',
                      minHeight: 56,
                      alignItems: 'center',
                      gap: 8,
                      borderBottom: idx < orders.length - 1 ? `1px solid ${T.border}` : 'none',
                      background: isVoid ? `${T.danger}10` : 'transparent',
                    }}
                  >
                    <span style={{ fontSize: 16, color: T.textSec, fontVariantNumeric: 'tabular-nums' }}>
                      {o.created_at.slice(11, 16)}
                    </span>
                    <span style={{ fontSize: 17, fontWeight: 600 }}>{o.table_no}</span>
                    <span style={{
                      fontSize: 18, fontWeight: 700,
                      color: isVoid ? T.textSec : T.primary,
                      textDecoration: isVoid ? 'line-through' : 'none',
                    }}>
                      {fen2yuan(o.total_fen)}
                    </span>
                    <span style={{ fontSize: 16, color: T.textSec }}>{o.payment_method}</span>
                    <span style={{
                      textAlign: 'center', fontSize: 14, fontWeight: 700,
                      color: isVoid ? T.danger : isRefund ? T.warning : T.success,
                      background: isVoid ? `${T.danger}20` : isRefund ? `${T.warning}20` : `${T.success}20`,
                      borderRadius: 8, padding: '3px 6px',
                      display: 'inline-block',
                      whiteSpace: 'nowrap',
                    }}>
                      {isVoid ? '作废' : isRefund ? '退款' : '已付'}
                    </span>
                  </div>
                );
              })}

              {orders.length === 0 && (
                <div style={{
                  padding: 32, textAlign: 'center',
                  fontSize: 18, color: T.textSec,
                }}>
                  本班次暂无已付款订单
                </div>
              )}
            </div>
          </div>
        </section>
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
        {/* 打印交班单 */}
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
          {printing ? '打印中…' : printOk ? '已打印' : '打印交班单'}
        </button>

        {/* 确认交班 — 88px 高主操作 */}
        <button
          onClick={() => { navigator.vibrate?.(50); setShowConfirm(true); }}
          disabled={handovering}
          style={{
            flex: 2, minHeight: 88, borderRadius: 14,
            background: handovering ? T.navyLight : T.primary,
            border: 'none',
            color: T.white, fontSize: 22, fontWeight: 700,
            cursor: handovering ? 'wait' : 'pointer',
            transition: 'background 0.15s',
            boxShadow: handovering ? 'none' : `0 4px 12px ${T.primary}60`,
          }}
        >
          {handovering ? '交班中…' : '确认交班'}
        </button>
      </div>

      {/* ── 确认弹窗 ── */}
      {showConfirm && (
        <ConfirmDialog
          title="确认交班？"
          message={`班次 ${shift.shift_id} 将被正式关闭。${actualCashFen > 0 && diffFen !== 0 ? `当前${diffFen > 0 ? '长' : '短'}款 ${fen2yuan(Math.abs(diffFen))}。` : ''}请确认已打印交班单并与下一班核对无误。`}
          onOk={() => void handleHandover()}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
}

/* ─────────────────────────────────────────
   KPI 卡片子组件
───────────────────────────────────────── */
interface KPICardProps {
  label:         string;
  value:         string;
  unit?:         string;
  sub?:          string;
  valueColor?:   string;
  valueFontSize?: number;
  span?:         number;
}

function KPICard({
  label, value, unit, sub,
  valueColor = T.textPri,
  valueFontSize = 26,
  span = 1,
}: KPICardProps) {
  return (
    <div style={{
      background: T.bgCard, borderRadius: 16,
      padding: '18px 20px',
      border: `1px solid ${T.border}`,
      borderTop: `3px solid ${valueColor === T.primary ? T.primary : T.border}`,
      gridColumn: span > 1 ? `span ${span}` : undefined,
      minHeight: 90,
    }}>
      <div style={{ fontSize: 16, color: T.textSec, marginBottom: 8 }}>{label}</div>
      <div style={{
        fontSize: valueFontSize, fontWeight: 800,
        color: valueColor, lineHeight: 1.1,
        display: 'flex', alignItems: 'baseline', gap: 4,
      }}>
        {value}
        {unit && <span style={{ fontSize: 16, fontWeight: 500, color: T.textSec }}>{unit}</span>}
      </div>
      {sub && <div style={{ fontSize: 14, color: T.textSec, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}
