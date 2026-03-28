/**
 * 财务分析页 -- F6 总部端
 * 功能: 收入构成饼图 + 支付渠道分布 + 折扣结构分析 + 门店利润排行
 * 调用 GET /api/v1/finance/analytics/*
 */
import { useState } from 'react';
import { ChartPlaceholder } from '../../../components/ChartPlaceholder';

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

// ---------- Mock 数据 ----------
const MOCK_REVENUE_CHANNELS: RevenueChannel[] = [
  { name: '堂食', amount: 186500, percent: 62.3, color: '#FF6B2C' },
  { name: '外卖', amount: 78200, percent: 26.1, color: '#185FA5' },
  { name: '宴席', amount: 34800, percent: 11.6, color: '#0F6E56' },
];

const MOCK_PAYMENTS: PaymentMethod[] = [
  { name: '微信支付', amount: 142300, percent: 47.5, txCount: 1860 },
  { name: '支付宝', amount: 89600, percent: 29.9, txCount: 1120 },
  { name: '现金', amount: 28500, percent: 9.5, txCount: 380 },
  { name: '银行卡', amount: 22800, percent: 7.6, txCount: 210 },
  { name: '会员储值', amount: 16300, percent: 5.5, txCount: 290 },
];

const MOCK_DISCOUNTS: DiscountItem[] = [
  { type: '满减优惠', amount: 12800, percent: 35.6, orderCount: 420, avgDiscount: 30.5 },
  { type: '会员折扣', amount: 9600, percent: 26.7, orderCount: 310, avgDiscount: 31.0 },
  { type: '新客立减', amount: 5400, percent: 15.0, orderCount: 180, avgDiscount: 30.0 },
  { type: '团购核销', amount: 4800, percent: 13.3, orderCount: 160, avgDiscount: 30.0 },
  { type: '员工餐', amount: 3400, percent: 9.4, orderCount: 85, avgDiscount: 40.0 },
];

const MOCK_STORE_PROFIT: StoreProfitRow[] = [
  { rank: 1, name: '芙蓉路店', revenue: 85600, cost: 42800, profit: 42800, margin: 50.0, trend: '+3.2%' },
  { rank: 2, name: '望城店', revenue: 72300, cost: 37200, profit: 35100, margin: 48.5, trend: '+1.8%' },
  { rank: 3, name: '开福店', revenue: 64500, cost: 33900, profit: 30600, margin: 47.4, trend: '+2.1%' },
  { rank: 4, name: '岳麓店', revenue: 58200, cost: 31400, profit: 26800, margin: 46.0, trend: '-0.5%' },
  { rank: 5, name: '星沙店', revenue: 52000, cost: 29100, profit: 22900, margin: 44.0, trend: '-1.2%' },
  { rank: 6, name: '雨花店', revenue: 46800, cost: 27300, profit: 19500, margin: 41.7, trend: '-2.3%' },
  { rank: 7, name: '天心店', revenue: 38500, cost: 23100, profit: 15400, margin: 40.0, trend: '-3.1%' },
  { rank: 8, name: '河西店', revenue: 32600, cost: 21200, profit: 11400, margin: 35.0, trend: '-4.5%' },
];

// ---------- 工具 ----------
const formatMoney = (v: number) => '\u00A5' + (v / 100).toLocaleString(undefined, { minimumFractionDigits: 0 });
const marginColor = (m: number) => m >= 45 ? '#0F6E56' : m >= 38 ? '#BA7517' : '#A32D2D';

// ---------- 组件 ----------
export function FinanceAnalysisPage() {
  const [period, setPeriod] = useState('本月');

  const totalRevenue = MOCK_REVENUE_CHANNELS.reduce((s, c) => s + c.amount, 0);
  const totalDiscount = MOCK_DISCOUNTS.reduce((s, d) => s + d.amount, 0);

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

      {/* 汇总卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: '总营收', value: formatMoney(totalRevenue), color: '#FF6B2C' },
          { label: '总利润', value: formatMoney(MOCK_STORE_PROFIT.reduce((s, r) => s + r.profit, 0)), color: '#0F6E56' },
          { label: '平均毛利率', value: '44.6%', color: '#185FA5' },
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
          <div style={{ display: 'flex', gap: 20 }}>
            {/* 简易饼图占位 */}
            <div style={{
              width: 140, height: 140, borderRadius: '50%',
              background: `conic-gradient(
                ${MOCK_REVENUE_CHANNELS[0].color} 0% ${MOCK_REVENUE_CHANNELS[0].percent}%,
                ${MOCK_REVENUE_CHANNELS[1].color} ${MOCK_REVENUE_CHANNELS[0].percent}% ${MOCK_REVENUE_CHANNELS[0].percent + MOCK_REVENUE_CHANNELS[1].percent}%,
                ${MOCK_REVENUE_CHANNELS[2].color} ${MOCK_REVENUE_CHANNELS[0].percent + MOCK_REVENUE_CHANNELS[1].percent}% 100%
              )`,
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
              {MOCK_REVENUE_CHANNELS.map((ch) => (
                <div key={ch.name} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: ch.color, flexShrink: 0 }} />
                  <span style={{ fontSize: 13, color: '#ccc', flex: 1 }}>{ch.name}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{formatMoney(ch.amount)}</span>
                  <span style={{ fontSize: 11, color: '#999', width: 40, textAlign: 'right' }}>{ch.percent}%</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <ChartPlaceholder
              title="收入构成趋势"
              chartType="Area"
              apiEndpoint="GET /api/v1/finance/analytics/revenue-composition"
              height={160}
            />
          </div>
        </div>

        {/* 支付渠道分布 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>支付渠道分布</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {MOCK_PAYMENTS.map((pm) => (
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

          <div style={{ marginTop: 16 }}>
            <ChartPlaceholder
              title="支付渠道趋势"
              chartType="Bar"
              apiEndpoint="GET /api/v1/finance/analytics/payment-channels"
              height={160}
            />
          </div>
        </div>
      </div>

      {/* 折扣结构 + 门店利润排行 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 折扣结构分析 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            折扣结构分析
            <span style={{
              fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
              background: '#BA751720', color: '#BA7517', fontWeight: 600,
            }}>
              总折扣 {formatMoney(totalDiscount)}
            </span>
          </h3>
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
              {MOCK_DISCOUNTS.map((d) => (
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

          <div style={{ marginTop: 12 }}>
            <ChartPlaceholder
              title="折扣趋势与异常检测"
              chartType="Line"
              apiEndpoint="GET /api/v1/finance/analytics/discount-trend"
              height={140}
            />
          </div>
        </div>

        {/* 门店利润排行 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>门店利润排行</h3>
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
              {MOCK_STORE_PROFIT.map((s) => (
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
        </div>
      </div>
    </div>
  );
}
