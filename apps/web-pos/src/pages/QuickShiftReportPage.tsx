/**
 * QuickShiftReportPage — 快餐结班报表（POS端）
 *
 * 路由: /quick/shift-report
 *
 * 功能:
 *   - 当班营业汇总（5个数字卡片：营业额/订单数/客单价/退单数/实收）
 *   - 各支付渠道汇总（微信/支付宝/现金/会员卡/银联）
 *   - 前10热销品项列表
 *   - 打印报表按钮（TXBridge 或 HTTP）
 *
 * 数据来源（API）:
 *   GET /api/v1/quick-cashier/shift-report?store_id=&date=
 *   — 返回当班汇总数据；如端点未就绪，使用 Mock 数据降级
 *
 * Store-POS 终端规范（tx-ui 技能）:
 *   - 禁用 Ant Design，所有组件手写触控优化
 *   - 点击区域 ≥ 48×48px
 *   - 最小字体 16px
 *   - 触控反馈：scale(0.97) + 200ms transition
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── Design Tokens ────────────────────────────────────────────────────────────
const T = {
  primary:    '#FF6B35',
  primaryAct: '#E55A28',
  bg:         '#0B1A20',
  card:       '#112228',
  card2:      '#162A38',
  border:     '#1A3A48',
  success:    '#0F6E56',
  successLt:  '#4ADE80',
  warning:    '#BA7517',
  danger:     '#A32D2D',
  info:       '#185FA5',
  muted:      '#64748B',
  text:       '#E0E0E0',
  textSub:    '#94A3B8',
  white:      '#FFFFFF',
} as const;

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;

function getBase(): string {
  return (window as unknown as Record<string, unknown>).__API_BASE__ as string || '';
}
function getTenantId(): string {
  return (
    (window as unknown as Record<string, unknown>).__TENANT_ID__ as string ||
    localStorage.getItem('tenant_id') || ''
  );
}
function getStoreId(): string {
  return (
    (window as unknown as Record<string, unknown>).__STORE_ID__ as string ||
    localStorage.getItem('store_id') ||
    import.meta.env.VITE_STORE_ID || ''
  );
}
function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

// ─── 数据类型 ──────────────────────────────────────────────────────────────────

interface PayChannelSummary {
  method: string;
  label: string;
  amount_fen: number;
  order_count: number;
}

interface TopDishItem {
  rank: number;
  dish_name: string;
  qty: number;
  revenue_fen: number;
}

interface QuickShiftReportData {
  store_name: string;
  biz_date: string;
  shift_start: string;
  shift_end?: string;
  /** 营业额（分） */
  total_revenue_fen: number;
  /** 订单总数 */
  order_count: number;
  /** 客单价（分） */
  avg_order_fen: number;
  /** 退单数 */
  refund_count: number;
  /** 实收（分，扣退款后） */
  net_revenue_fen: number;
  /** 各渠道汇总 */
  channels: PayChannelSummary[];
  /** 热销前10品项 */
  top_dishes: TopDishItem[];
}

// ─── Mock 数据（API 未就绪时降级） ─────────────────────────────────────────────

const MOCK_REPORT: QuickShiftReportData = {
  store_name: '屯象快餐示例门店',
  biz_date: todayStr(),
  shift_start: new Date(Date.now() - 8 * 3600 * 1000).toISOString(),
  total_revenue_fen: 382600,
  order_count: 87,
  avg_order_fen: 4397,
  refund_count: 2,
  net_revenue_fen: 371800,
  channels: [
    { method: 'wechat',         label: '微信支付', amount_fen: 198000, order_count: 45 },
    { method: 'alipay',         label: '支付宝',   amount_fen: 112600, order_count: 26 },
    { method: 'cash',           label: '现金',     amount_fen: 52000,  order_count: 12 },
    { method: 'member_balance', label: '会员余额',  amount_fen: 16000,  order_count: 3  },
    { method: 'unionpay',       label: '银联',     amount_fen: 4000,   order_count: 1  },
  ],
  top_dishes: [
    { rank: 1,  dish_name: '剁椒鱼头',    qty: 34, revenue_fen: 299200 },
    { rank: 2,  dish_name: '毛氏红烧肉',  qty: 28, revenue_fen: 162400 },
    { rank: 3,  dish_name: '白米饭',      qty: 82, revenue_fen: 24600  },
    { rank: 4,  dish_name: '辣椒炒肉',    qty: 21, revenue_fen: 79800  },
    { rank: 5,  dish_name: '酸辣粉',      qty: 18, revenue_fen: 27000  },
    { rank: 6,  dish_name: '招牌套餐A',   qty: 15, revenue_fen: 59700  },
    { rank: 7,  dish_name: '可乐',        qty: 30, revenue_fen: 15000  },
    { rank: 8,  dish_name: '臭豆腐',      qty: 12, revenue_fen: 14400  },
    { rank: 9,  dish_name: '凉拌黄瓜',    qty: 11, revenue_fen: 13200  },
    { rank: 10, dish_name: '蒜蓉大虾',    qty: 9,  revenue_fen: 61200  },
  ],
};

// ─── API 调用 ─────────────────────────────────────────────────────────────────

async function fetchShiftReport(
  storeId: string,
  bizDate: string,
): Promise<QuickShiftReportData> {
  try {
    const url = `${getBase()}/api/v1/quick-cashier/shift-report?store_id=${encodeURIComponent(storeId)}&date=${bizDate}`;
    const resp = await fetch(url, {
      headers: { 'X-Tenant-ID': getTenantId() },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const json = (await resp.json()) as { ok: boolean; data: QuickShiftReportData };
    if (!json.ok) throw new Error('API returned ok=false');
    return json.data;
  } catch {
    // API 尚未就绪时降级到 Mock 数据，不阻断收银流程
    console.warn('[QuickShiftReport] API unavailable, using mock data');
    return MOCK_REPORT;
  }
}

// ─── 打印函数 ─────────────────────────────────────────────────────────────────

function buildPrintText(report: QuickShiftReportData): string {
  const channelLines = report.channels
    .map(c => `  ${c.label.padEnd(8)} ${fen2yuan(c.amount_fen).padStart(10)}  ${c.order_count}单`)
    .join('\n');

  const topLines = report.top_dishes
    .slice(0, 10)
    .map(d => `  ${String(d.rank).padStart(2)}. ${d.dish_name.padEnd(10)} ×${d.qty}  ${fen2yuan(d.revenue_fen)}`)
    .join('\n');

  return `
================================
    快 餐 结 班 报 表
================================
门店: ${report.store_name}
日期: ${report.biz_date}
开班: ${report.shift_start.slice(0, 16).replace('T', ' ')}
结班: ${report.shift_end ? report.shift_end.slice(0, 16).replace('T', ' ') : '（当前时间）'}
--------------------------------
营业额: ${fen2yuan(report.total_revenue_fen).padStart(12)}
订单数: ${String(report.order_count).padStart(12)}单
客单价: ${fen2yuan(report.avg_order_fen).padStart(12)}
退单数: ${String(report.refund_count).padStart(12)}单
实  收: ${fen2yuan(report.net_revenue_fen).padStart(12)}
--------------------------------
支付渠道明细:
${channelLines}
--------------------------------
热销品项 TOP10:
${topLines}
================================
`.trim() + '\n';
}

function printReport(report: QuickShiftReportData): void {
  const text = buildPrintText(report);
  const w = window as unknown as Record<string, unknown>;
  if (w.TXBridge) {
    (w.TXBridge as { print: (s: string) => void }).print(text);
  } else {
    fetch(`${getBase()}/api/v1/print/text`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': getTenantId(),
      },
      body: JSON.stringify({ content: text, copies: 1 }),
    }).catch(() => {
      console.warn('[QuickShiftReport] 打印失败');
    });
  }
}

// ─── 子组件 ───────────────────────────────────────────────────────────────────

/** 触控按钮 */
function TxBtn({
  label,
  bgColor,
  disabled = false,
  loading = false,
  fullWidth = false,
  onPress,
}: {
  label: string;
  bgColor: string;
  disabled?: boolean;
  loading?: boolean;
  fullWidth?: boolean;
  onPress: () => void;
}) {
  return (
    <button
      onClick={onPress}
      disabled={disabled || loading}
      style={{
        minHeight: 56,
        width: fullWidth ? '100%' : undefined,
        padding: '0 24px',
        background: disabled || loading ? T.muted : bgColor,
        border: 'none',
        borderRadius: 12,
        color: T.white,
        fontSize: 18,
        fontWeight: 700,
        cursor: disabled || loading ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        transition: 'transform 200ms ease',
      }}
      onPointerDown={e => {
        if (!disabled && !loading)
          (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
      }}
      onPointerUp={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
      onPointerLeave={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
    >
      {loading ? '加载中...' : label}
    </button>
  );
}

/** 汇总数字卡片 */
function SummaryCard({
  label,
  value,
  subValue,
  accent = false,
}: {
  label: string;
  value: string;
  subValue?: string;
  accent?: boolean;
}) {
  return (
    <div
      style={{
        background: T.card,
        border: `1px solid ${accent ? T.primary : T.border}`,
        borderRadius: 12,
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minWidth: 120,
        flex: 1,
      }}
    >
      <span style={{ fontSize: 14, color: T.muted }}>{label}</span>
      <span
        style={{
          fontSize: 26,
          fontWeight: 800,
          color: accent ? T.primary : T.text,
          lineHeight: 1.1,
        }}
      >
        {value}
      </span>
      {subValue && (
        <span style={{ fontSize: 13, color: T.textSub }}>{subValue}</span>
      )}
    </div>
  );
}

/** 支付渠道行 */
function ChannelRow({ channel }: { channel: PayChannelSummary }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '14px 0',
        borderBottom: `1px solid ${T.border}`,
        gap: 12,
      }}
    >
      <span style={{ flex: 1, fontSize: 17, color: T.text }}>{channel.label}</span>
      <span style={{ fontSize: 15, color: T.textSub }}>{channel.order_count}单</span>
      <span
        style={{ fontSize: 20, fontWeight: 700, color: T.text, minWidth: 100, textAlign: 'right' }}
      >
        {fen2yuan(channel.amount_fen)}
      </span>
    </div>
  );
}

/** 热销品项行 */
function DishRow({ dish }: { dish: TopDishItem }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '12px 0',
        borderBottom: `1px solid ${T.border}`,
        gap: 12,
      }}
    >
      <span
        style={{
          width: 28,
          height: 28,
          borderRadius: 6,
          background: dish.rank <= 3 ? T.primary : T.card2,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 14,
          fontWeight: 700,
          color: T.white,
          flexShrink: 0,
        }}
      >
        {dish.rank}
      </span>
      <span style={{ flex: 1, fontSize: 17, color: T.text }}>{dish.dish_name}</span>
      <span style={{ fontSize: 15, color: T.textSub }}>×{dish.qty}</span>
      <span
        style={{ fontSize: 17, fontWeight: 600, color: T.text, minWidth: 90, textAlign: 'right' }}
      >
        {fen2yuan(dish.revenue_fen)}
      </span>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function QuickShiftReportPage() {
  const navigate = useNavigate();
  const [report, setReport] = useState<QuickShiftReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [printing, setPrinting] = useState(false);

  const storeId = getStoreId();

  const loadReport = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchShiftReport(storeId, todayStr());
      setReport(data);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    void loadReport();
  }, [loadReport]);

  const handlePrint = () => {
    if (!report) return;
    setPrinting(true);
    try {
      printReport(report);
    } finally {
      setTimeout(() => setPrinting(false), 800);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        background: T.bg,
        color: T.text,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* 顶栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '16px 20px',
          borderBottom: `1px solid ${T.border}`,
          background: T.card,
          gap: 16,
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => navigate(-1)}
          style={{
            minHeight: 48,
            minWidth: 48,
            background: 'transparent',
            border: `1px solid ${T.border}`,
            borderRadius: 10,
            color: T.text,
            fontSize: 22,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onPointerDown={e =>
            ((e.currentTarget as HTMLElement).style.transform = 'scale(0.97)')
          }
          onPointerUp={e =>
            ((e.currentTarget as HTMLElement).style.transform = 'scale(1)')
          }
          onPointerLeave={e =>
            ((e.currentTarget as HTMLElement).style.transform = 'scale(1)')
          }
          aria-label="返回"
        >
          ‹
        </button>

        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: T.white }}>
            快餐结班报表
          </div>
          {report && (
            <div style={{ fontSize: 14, color: T.muted, marginTop: 2 }}>
              {report.store_name} · {report.biz_date}
            </div>
          )}
        </div>

        <TxBtn
          label={printing ? '打印中...' : '🖨️ 打印报表'}
          bgColor={T.primary}
          disabled={!report || loading}
          loading={printing}
          onPress={handlePrint}
        />

        <TxBtn
          label="刷新"
          bgColor={T.info}
          disabled={loading}
          onPress={() => void loadReport()}
        />
      </div>

      {/* 内容区 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: 20,
          display: 'flex',
          flexDirection: 'column',
          gap: 24,
        }}
      >
        {loading ? (
          <div
            style={{
              textAlign: 'center',
              color: T.muted,
              padding: '80px 0',
              fontSize: 18,
            }}
          >
            加载中...
          </div>
        ) : !report ? (
          <div
            style={{
              textAlign: 'center',
              color: T.muted,
              padding: '80px 0',
              fontSize: 18,
            }}
          >
            暂无数据
          </div>
        ) : (
          <>
            {/* 一、营业汇总 5 个数字卡片 */}
            <section>
              <h2 style={{ fontSize: 17, color: T.textSub, marginBottom: 12, fontWeight: 600 }}>
                营业汇总
              </h2>
              <div
                style={{
                  display: 'flex',
                  gap: 12,
                  flexWrap: 'wrap',
                }}
              >
                <SummaryCard
                  label="营业额"
                  value={fen2yuan(report.total_revenue_fen)}
                  accent
                />
                <SummaryCard
                  label="订单数"
                  value={`${report.order_count}单`}
                />
                <SummaryCard
                  label="客单价"
                  value={fen2yuan(report.avg_order_fen)}
                />
                <SummaryCard
                  label="退单数"
                  value={`${report.refund_count}单`}
                  subValue={report.refund_count > 0 ? '有退单' : ''}
                />
                <SummaryCard
                  label="实收金额"
                  value={fen2yuan(report.net_revenue_fen)}
                  subValue="已扣退款"
                />
              </div>
            </section>

            {/* 二、各支付渠道汇总 */}
            <section>
              <h2 style={{ fontSize: 17, color: T.textSub, marginBottom: 12, fontWeight: 600 }}>
                各渠道收款
              </h2>
              <div
                style={{
                  background: T.card,
                  borderRadius: 12,
                  padding: '0 20px',
                  border: `1px solid ${T.border}`,
                }}
              >
                {/* 表头 */}
                <div
                  style={{
                    display: 'flex',
                    padding: '12px 0',
                    borderBottom: `1px solid ${T.border}`,
                    fontSize: 14,
                    color: T.muted,
                    gap: 12,
                  }}
                >
                  <span style={{ flex: 1 }}>渠道</span>
                  <span>笔数</span>
                  <span style={{ minWidth: 100, textAlign: 'right' }}>金额</span>
                </div>
                {report.channels.map(ch => (
                  <ChannelRow key={ch.method} channel={ch} />
                ))}
                {/* 合计行 */}
                <div
                  style={{
                    display: 'flex',
                    padding: '14px 0',
                    gap: 12,
                    fontSize: 17,
                    fontWeight: 700,
                    color: T.text,
                  }}
                >
                  <span style={{ flex: 1 }}>合计</span>
                  <span style={{ color: T.textSub, fontWeight: 400 }}>
                    {report.channels.reduce((s, c) => s + c.order_count, 0)}单
                  </span>
                  <span
                    style={{
                      minWidth: 100,
                      textAlign: 'right',
                      color: T.primary,
                      fontSize: 20,
                    }}
                  >
                    {fen2yuan(report.channels.reduce((s, c) => s + c.amount_fen, 0))}
                  </span>
                </div>
              </div>
            </section>

            {/* 三、热销品项 TOP10 */}
            <section>
              <h2 style={{ fontSize: 17, color: T.textSub, marginBottom: 12, fontWeight: 600 }}>
                热销品项 TOP10
              </h2>
              <div
                style={{
                  background: T.card,
                  borderRadius: 12,
                  padding: '0 20px',
                  border: `1px solid ${T.border}`,
                }}
              >
                {/* 表头 */}
                <div
                  style={{
                    display: 'flex',
                    padding: '12px 0',
                    borderBottom: `1px solid ${T.border}`,
                    fontSize: 14,
                    color: T.muted,
                    gap: 12,
                    alignItems: 'center',
                  }}
                >
                  <span style={{ width: 28 }}>#</span>
                  <span style={{ flex: 1 }}>品项</span>
                  <span>销量</span>
                  <span style={{ minWidth: 90, textAlign: 'right' }}>营收</span>
                </div>
                {report.top_dishes.map(dish => (
                  <DishRow key={dish.rank} dish={dish} />
                ))}
              </div>
            </section>

            {/* 四、班次时间信息 */}
            <section>
              <div
                style={{
                  background: T.card,
                  borderRadius: 12,
                  padding: '16px 20px',
                  border: `1px solid ${T.border}`,
                  display: 'flex',
                  gap: 32,
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <div style={{ fontSize: 13, color: T.muted }}>开班时间</div>
                  <div style={{ fontSize: 17, color: T.text, marginTop: 4 }}>
                    {report.shift_start.slice(0, 16).replace('T', ' ')}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 13, color: T.muted }}>结班时间</div>
                  <div style={{ fontSize: 17, color: T.text, marginTop: 4 }}>
                    {report.shift_end
                      ? report.shift_end.slice(0, 16).replace('T', ' ')
                      : '未结班（当前班次）'}
                  </div>
                </div>
              </div>
            </section>

            {/* 底部打印按钮（大按钮，触控友好） */}
            <div style={{ paddingBottom: 32 }}>
              <TxBtn
                label={printing ? '打印中...' : '打印结班报表'}
                bgColor={T.primary}
                fullWidth
                loading={printing}
                onPress={handlePrint}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default QuickShiftReportPage;
