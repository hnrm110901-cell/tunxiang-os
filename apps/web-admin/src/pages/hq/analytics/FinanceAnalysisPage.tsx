/**
 * 财务分析页 -- F6 总部端
 * 功能: 收入构成 + 支付渠道分布 + 折扣结构分析 + 门店利润排行
 * API: /api/v1/analytics/revenue, /api/v1/analytics/cost, /api/v1/analytics/channel-margin
 */
import { useState, useEffect, useCallback } from 'react';
import { TxLineChart, TxBarChart } from '../../../components/charts';
import { txFetch } from '../../../api';

// ---------- 类型 ----------
interface RevenueChannel {
  name: string;
  amount: number;
  percent: number;
  color: string;
}

interface PaymentMethod {
  name: string;
  amount: number;
  percent: number;
  txCount: number;
}

interface DiscountItem {
  type: string;
  amount: number;
  percent: number;
  orderCount: number;
  avgDiscount: number;
}

interface StoreProfitRow {
  rank: number;
  name: string;
  revenue: number;
  cost: number;
  profit: number;
  margin: number;
  trend: string;
}

interface RevenueData {
  channels: RevenueChannel[];
  trend: { month: string; dine_in: number; delivery: number; banquet: number }[];
}

interface CostData {
  payments: PaymentMethod[];
  payment_trend: { month: string; wechat: number; alipay: number; other: number }[];
  discounts: DiscountItem[];
  discount_trend: { month: string; total: number; abnormal: number }[];
}

interface ChannelMarginData {
  store_profits: StoreProfitRow[];
}

interface FinanceSummary {
  total_revenue: number;
  total_profit: number;
  avg_margin: number;
  total_discount: number;
}

// ---------- 工具 ----------
const formatMoney = (v: number) => '\u00A5' + (v / 100).toLocaleString(undefined, { minimumFractionDigits: 0 });
const marginColor = (m: number) => m >= 45 ? '#0F6E56' : m >= 38 ? '#BA7517' : '#A32D2D';

const PERIOD_MAP: Record<string, string> = {
  '今日': 'today',
  '本周': 'week',
  '本月': 'month',
  '本季': 'quarter',
};

// ---------- 组件 ----------
export function FinanceAnalysisPage() {
  const [period, setPeriod] = useState('本月');
  const [loading, setLoading] = useState(false);

  const [revenueChannels, setRevenueChannels] = useState<RevenueChannel[]>([]);
  const [revenueTrend, setRevenueTrend] = useState<{ month: string; dine_in: number; delivery: number; banquet: number }[]>([]);
  const [payments, setPayments] = useState<PaymentMethod[]>([]);
  const [paymentTrend, setPaymentTrend] = useState<{ month: string; wechat: number; alipay: number; other: number }[]>([]);
  const [discounts, setDiscounts] = useState<DiscountItem[]>([]);
  const [discountTrend, setDiscountTrend] = useState<{ month: string; total: number; abnormal: number }[]>([]);
  const [storeProfits, setStoreProfits] = useState<StoreProfitRow[]>([]);
  const [summary, setSummary] = useState<FinanceSummary>({ total_revenue: 0, total_profit: 0, avg_margin: 0, total_discount: 0 });

  const loadData = useCallback(async () => {
    setLoading(true);
    const p = PERIOD_MAP[period] ?? 'month';
    const today = new Date().toISOString().slice(0, 10);
    try {
      const [revRes, costRes, marginRes] = await Promise.allSettled([
        txFetch<RevenueData>(`/api/v1/analytics/revenue?period=${p}`),
        txFetch<CostData>(`/api/v1/analytics/cost?period=${p}`),
        txFetch<ChannelMarginData>(`/api/v1/analytics/channel-margin?date=${today}`),
      ]);
      if (revRes.status === 'fulfilled' && revRes.value.data) {
        const d = revRes.value.data;
        setRevenueChannels(d.channels ?? []);
        setRevenueTrend(d.trend ?? []);
      }
      if (costRes.status === 'fulfilled' && costRes.value.data) {
        const d = costRes.value.data;
        setPayments(d.payments ?? []);
        setPaymentTrend(d.payment_trend ?? []);
        setDiscounts(d.discounts ?? []);
        setDiscountTrend(d.discount_trend ?? []);
      }
      if (marginRes.status === 'fulfilled' && marginRes.value.data) {
        setStoreProfits(marginRes.value.data.store_profits ?? []);
      }
    } catch {
      // 保持空数据
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 汇总计算
  const totalRevenue = revenueChannels.reduce((s, c) => s + c.amount, 0);
  const totalDiscount = discounts.reduce((s, d) => s + d.amount, 0);
  const totalProfit = storeProfits.reduce((s, r) => s + r.profit, 0);
  const avgMargin = storeProfits.length > 0
    ? storeProfits.reduce((s, r) => s + r.margin, 0) / storeProfits.length
    : 0;

  // 趋势图数据准备
  const trendLabels = revenueTrend.map(r => r.month);
  const revTrendDatasets = trendLabels.length > 0 ? [
    { name: '堂食', values: revenueTrend.map(r => r.dine_in), color: '#FF6B2C' },
    { name: '外卖', values: revenueTrend.map(r => r.delivery), color: '#185FA5' },
    { name: '宴席', values: revenueTrend.map(r => r.banquet), color: '#0F6E56' },
  ] : [];

  const payLabels = paymentTrend.map(r => r.month);
  const payTrendDatasets = payLabels.length > 0 ? [
    { name: '微信支付', values: paymentTrend.map(r => r.wechat), color: '#0F6E56' },
    { name: '支付宝', values: paymentTrend.map(r => r.alipay), color: '#185FA5' },
    { name: '其他', values: paymentTrend.map(r => r.other), color: '#BA7517' },
  ] : [];

  const discLabels = discountTrend.map(r => r.month);
  const discTrendDatasets = discLabels.length > 0 ? [
    { name: '折扣总额', values: discountTrend.map(r => r.total), color: '#BA7517' },
    { name: '异常折扣', values: discountTrend.map(r => r.abnormal), color: '#A32D2D' },
  ] : [];

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>财务分析</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {['今日', '本周', '本月', '本季'].map((d) => (
            <button key={d} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: period === d ? '#FF6B2C' : '#1a2a33',
              color: period === d ? '#fff' : '#999',
            }} onClick={() => setPeriod(d)}>
              {d}
            </button>
          ))}
        </div>
      </div>

      {/* 加载中提示 */}
      {loading && (
        <div style={{ textAlign: 'center', color: '#999', padding: '8px 0', fontSize: 12 }}>数据加载中...</div>
      )}

      {/* 汇总卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: '总营收', value: formatMoney(totalRevenue), color: '#FF6B2C' },
          { label: '总利润', value: formatMoney(totalProfit), color: '#0F6E56' },
          { label: '平均毛利率', value: `${avgMargin.toFixed(1)}%`, color: '#185FA5' },
          { label: '折扣总额', value: formatMoney(totalDiscount), color: '#BA7517' },
        ].map((kpi) => (
          <div key={kpi.label} style={{
            background: '#112228', borderRadius: 8, padding: 16,
            borderLeft: `3px solid ${kpi.color}`,
          }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
            <div style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      {/* 收入构成 + 支付渠道 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 收入构成 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>收入构成</h3>
          {revenueChannels.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无数据</div>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 20 }}>
                {/* 简易饼图 */}
                <div style={{
                  width: 140, height: 140, borderRadius: '50%',
                  background: revenueChannels.length >= 3
                    ? `conic-gradient(
                        ${revenueChannels[0].color} 0% ${revenueChannels[0].percent}%,
                        ${revenueChannels[1].color} ${revenueChannels[0].percent}% ${revenueChannels[0].percent + revenueChannels[1].percent}%,
                        ${revenueChannels[2]?.color ?? '#888'} ${revenueChannels[0].percent + revenueChannels[1].percent}% 100%
                      )`
                    : '#1a2a33',
                  position: 'relative', flexShrink: 0,
                }}>
                  <div style={{
                    position: 'absolute', inset: 25, borderRadius: '50%', background: '#112228',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexDirection: 'column',
                  }}>
                    <div style={{ fontSize: 11, color: '#999' }}>总计</div>
                    <div style={{ fontSize: 16, fontWeight: 'bold', color: '#fff' }}>{formatMoney(totalRevenue)}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, flex: 1, justifyContent: 'center' }}>
                  {revenueChannels.map((ch) => (
                    <div key={ch.name} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ width: 10, height: 10, borderRadius: 2, background: ch.color, flexShrink: 0 }} />
                      <span style={{ fontSize: 13, color: '#ccc', flex: 1 }}>{ch.name}</span>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{formatMoney(ch.amount)}</span>
                      <span style={{ fontSize: 11, color: '#999', width: 40, textAlign: 'right' }}>{ch.percent}%</span>
                    </div>
                  ))}
                </div>
              </div>
              {revTrendDatasets.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <TxLineChart
                    data={{ labels: trendLabels, datasets: revTrendDatasets }}
                    height={160}
                    showArea
                    unit="元"
                  />
                </div>
              )}
            </>
          )}
        </div>

        {/* 支付渠道分布 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>支付渠道分布</h3>
          {payments.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无数据</div>
          ) : (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {payments.map((pm) => (
                  <div key={pm.name}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 13, color: '#ccc' }}>{pm.name}</span>
                      <span style={{ fontSize: 12, color: '#999' }}>
                        {formatMoney(pm.amount)} | {pm.txCount}笔 | {pm.percent}%
                      </span>
                    </div>
                    <div style={{ height: 10, borderRadius: 5, background: '#0B1A20', overflow: 'hidden' }}>
                      <div style={{
                        width: `${pm.percent}%`, height: '100%', borderRadius: 5,
                        background: '#FF6B2C', opacity: 0.6 + (pm.percent / 100) * 0.4,
                        transition: 'width 0.6s ease',
                      }} />
                    </div>
                  </div>
                ))}
              </div>
              {payTrendDatasets.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <TxBarChart
                    data={{ labels: payLabels, datasets: payTrendDatasets }}
                    height={160}
                    unit="元"
                  />
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* 折扣结构 + 门店利润排行 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 折扣结构分析 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            折扣结构分析
            {totalDiscount > 0 && (
              <span style={{
                fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
                background: '#BA751720', color: '#BA7517', fontWeight: 600,
              }}>
                总折扣 {formatMoney(totalDiscount)}
              </span>
            )}
          </h3>
          {discounts.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无数据</div>
          ) : (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                    <th style={{ padding: '8px 4px' }}>类型</th>
                    <th style={{ padding: '8px 4px', textAlign: 'right' }}>金额</th>
                    <th style={{ padding: '8px 4px', textAlign: 'right' }}>占比</th>
                    <th style={{ padding: '8px 4px', textAlign: 'right' }}>单量</th>
                    <th style={{ padding: '8px 4px', textAlign: 'right' }}>均折</th>
                  </tr>
                </thead>
                <tbody>
                  {discounts.map((d) => (
                    <tr key={d.type} style={{ borderTop: '1px solid #1a2a33' }}>
                      <td style={{ padding: '10px 4px', color: '#ccc' }}>{d.type}</td>
                      <td style={{ padding: '10px 4px', textAlign: 'right', color: '#fff', fontWeight: 600 }}>
                        {formatMoney(d.amount)}
                      </td>
                      <td style={{ padding: '10px 4px', textAlign: 'right', color: '#999' }}>{d.percent}%</td>
                      <td style={{ padding: '10px 4px', textAlign: 'right', color: '#999' }}>{d.orderCount}</td>
                      <td style={{ padding: '10px 4px', textAlign: 'right' }}>
                        <span style={{
                          padding: '2px 6px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                          background: d.avgDiscount > 35 ? '#A32D2D20' : '#0F6E5620',
                          color: d.avgDiscount > 35 ? '#A32D2D' : '#0F6E56',
                        }}>
                          {d.avgDiscount}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {discTrendDatasets.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <TxLineChart
                    data={{ labels: discLabels, datasets: discTrendDatasets }}
                    height={140}
                    unit="元"
                  />
                </div>
              )}
            </>
          )}
        </div>

        {/* 门店利润排行 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>门店利润排行</h3>
          {storeProfits.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无数据</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                  <th style={{ padding: '8px 4px' }}>#</th>
                  <th style={{ padding: '8px 4px' }}>门店</th>
                  <th style={{ padding: '8px 4px', textAlign: 'right' }}>营收</th>
                  <th style={{ padding: '8px 4px', textAlign: 'right' }}>利润</th>
                  <th style={{ padding: '8px 4px', textAlign: 'right' }}>毛利率</th>
                  <th style={{ padding: '8px 4px', textAlign: 'right' }}>趋势</th>
                </tr>
              </thead>
              <tbody>
                {storeProfits.map((s) => (
                  <tr key={s.rank} style={{ borderTop: '1px solid #1a2a33' }}>
                    <td style={{ padding: '10px 4px', fontWeight: 'bold', color: '#FF6B2C' }}>{s.rank}</td>
                    <td style={{ padding: '10px 4px', color: '#ccc' }}>{s.name}</td>
                    <td style={{ padding: '10px 4px', textAlign: 'right', color: '#fff' }}>
                      {formatMoney(s.revenue)}
                    </td>
                    <td style={{ padding: '10px 4px', textAlign: 'right', color: '#fff', fontWeight: 600 }}>
                      {formatMoney(s.profit)}
                    </td>
                    <td style={{ padding: '10px 4px', textAlign: 'right' }}>
                      <span style={{
                        padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                        background: marginColor(s.margin) + '20', color: marginColor(s.margin),
                      }}>
                        {s.margin}%
                      </span>
                    </td>
                    <td style={{
                      padding: '10px 4px', textAlign: 'right', fontSize: 11,
                      color: s.trend.startsWith('+') ? '#0F6E56' : '#A32D2D',
                    }}>
                      {s.trend.startsWith('+') ? '\u2191' : '\u2193'}{s.trend}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
