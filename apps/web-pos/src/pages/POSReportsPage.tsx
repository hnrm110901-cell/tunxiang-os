/**
 * 门店报表页 — 日报/菜品Top10/支付方式/时段客流
 */
import { useState } from 'react';

/* ---------- Mock Data ---------- */
const mockDaily = {
  revenue: { today: 12680, yesterday: 11720, diff: '+8.2%' },
  cost: { today: 4280, yesterday: 4150, diff: '+3.1%' },
  traffic: { today: 86, yesterday: 77, diff: '+11.7%' },
  grossMargin: { today: '66.2%', yesterday: '64.6%', diff: '+1.6%' },
};

const mockTop10 = [
  { rank: 1, name: '剁椒鱼头', qty: 28, revenue: 2520, trend: 'up' },
  { rank: 2, name: '小炒肉', qty: 25, revenue: 1500, trend: 'up' },
  { rank: 3, name: '口味虾', qty: 22, revenue: 2640, trend: 'down' },
  { rank: 4, name: '外婆鸡', qty: 18, revenue: 1260, trend: 'up' },
  { rank: 5, name: '辣椒炒肉', qty: 16, revenue: 896, trend: 'same' },
  { rank: 6, name: '红烧肉', qty: 14, revenue: 980, trend: 'down' },
  { rank: 7, name: '凉拌黄瓜', qty: 13, revenue: 390, trend: 'up' },
  { rank: 8, name: '酸菜鱼', qty: 12, revenue: 1080, trend: 'up' },
  { rank: 9, name: '米饭', qty: 68, revenue: 204, trend: 'same' },
  { rank: 10, name: '可乐/雪碧', qty: 45, revenue: 360, trend: 'same' },
];

const mockPayment = [
  { method: '微信支付', amount: 6820, percent: 53.8 },
  { method: '支付宝', amount: 2980, percent: 23.5 },
  { method: '现金', amount: 1520, percent: 12.0 },
  { method: '银行卡', amount: 860, percent: 6.8 },
  { method: '会员储值', amount: 500, percent: 3.9 },
];

const mockTimeslot = [
  { period: '午餐 11:00-14:00', traffic: 42, revenue: 6180, avgPrice: 147 },
  { period: '下午茶 14:00-17:00', traffic: 8, revenue: 640, avgPrice: 80 },
  { period: '晚餐 17:00-21:30', traffic: 36, revenue: 5860, avgPrice: 163 },
];

const trendIcon: Record<string, string> = { up: '/\\', down: '\\/', same: '--' };
const trendColor: Record<string, string> = { up: '#52c41a', down: '#ff4d4f', same: '#666' };

/* ---------- Component ---------- */
export function POSReportsPage() {
  const [tab, setTab] = useState<'daily' | 'top10' | 'payment' | 'traffic'>('daily');

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '8px 20px', cursor: 'pointer', fontSize: 13, fontWeight: 'bold',
    background: active ? '#1890ff' : '#1A3A48', color: active ? '#fff' : '#8899A6',
    border: 'none', borderRadius: 6,
  });

  return (
    <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0', fontFamily: 'Noto Sans SC, sans-serif', padding: 20 }}>
      <h1 style={{ margin: '0 0 20px', fontSize: 22, color: '#fff' }}>门店报表</h1>

      {/* Tab Bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button onClick={() => setTab('daily')} style={tabStyle(tab === 'daily')}>日报</button>
        <button onClick={() => setTab('top10')} style={tabStyle(tab === 'top10')}>菜品Top10</button>
        <button onClick={() => setTab('payment')} style={tabStyle(tab === 'payment')}>支付方式</button>
        <button onClick={() => setTab('traffic')} style={tabStyle(tab === 'traffic')}>时段客流</button>
      </div>

      {/* Daily Report */}
      {tab === 'daily' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14 }}>
          {([
            { label: '营收', key: 'revenue' as const, unit: '元', color: '#52c41a' },
            { label: '成本', key: 'cost' as const, unit: '元', color: '#ff4d4f' },
            { label: '客流', key: 'traffic' as const, unit: '人', color: '#1890ff' },
            { label: '毛利率', key: 'grossMargin' as const, unit: '', color: '#722ed1' },
          ]).map(item => {
            const data = mockDaily[item.key];
            return (
              <div key={item.key} style={{
                background: '#112B36', borderRadius: 10, padding: 20,
                borderLeft: `4px solid ${item.color}`,
              }}>
                <div style={{ fontSize: 12, color: '#8899A6', marginBottom: 8 }}>{item.label}</div>
                <div style={{ fontSize: 30, fontWeight: 'bold', color: '#fff' }}>
                  {data.today}{item.unit && <span style={{ fontSize: 13, color: '#8899A6', marginLeft: 4 }}>{item.unit}</span>}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10, fontSize: 12 }}>
                  <span style={{ color: '#666' }}>昨日: {data.yesterday}{item.unit}</span>
                  <span style={{ color: data.diff.startsWith('+') ? '#52c41a' : '#ff4d4f' }}>{data.diff}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Top10 */}
      {tab === 'top10' && (
        <div style={{ background: '#112B36', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '50px 1fr 80px 100px 60px',
            padding: '10px 16px', background: '#0D2430', fontSize: 12, color: '#8899A6', fontWeight: 'bold',
          }}>
            <span>排名</span><span>菜品</span><span>销量</span><span>营收(元)</span><span>趋势</span>
          </div>
          {mockTop10.map(d => (
            <div key={d.rank} style={{
              display: 'grid', gridTemplateColumns: '50px 1fr 80px 100px 60px',
              padding: '12px 16px', borderBottom: '1px solid #1A3A48', alignItems: 'center',
            }}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                width: 26, height: 26, borderRadius: '50%', fontSize: 13, fontWeight: 'bold',
                background: d.rank <= 3 ? '#FF6B2C' : '#1A3A48',
                color: d.rank <= 3 ? '#fff' : '#8899A6',
              }}>{d.rank}</span>
              <span style={{ fontSize: 14, color: '#fff' }}>{d.name}</span>
              <span>{d.qty}份</span>
              <span style={{ color: '#E0C97F' }}>{d.revenue.toLocaleString()}</span>
              <span style={{ color: trendColor[d.trend], fontFamily: 'monospace' }}>{trendIcon[d.trend]}</span>
            </div>
          ))}
        </div>
      )}

      {/* Payment Method */}
      {tab === 'payment' && (
        <div style={{ background: '#112B36', borderRadius: 10, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 15, color: '#fff' }}>支付方式占比</h3>
          {mockPayment.map(p => (
            <div key={p.method} style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                <span>{p.method}</span>
                <span style={{ color: '#8899A6' }}>{p.amount.toLocaleString()}元 ({p.percent}%)</span>
              </div>
              <div style={{ height: 8, background: '#1A3A48', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  width: `${p.percent}%`, height: '100%', borderRadius: 4,
                  background: p.method === '微信支付' ? '#52c41a' :
                    p.method === '支付宝' ? '#1890ff' :
                    p.method === '现金' ? '#faad14' :
                    p.method === '银行卡' ? '#722ed1' : '#E0C97F',
                }} />
              </div>
            </div>
          ))}
          <div style={{ textAlign: 'center', color: '#666', fontSize: 12, marginTop: 16 }}>
            [饼图区域 - 待接入 ECharts]
          </div>
        </div>
      )}

      {/* Traffic by Period */}
      {tab === 'traffic' && (
        <div style={{ background: '#112B36', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 80px 100px 100px',
            padding: '10px 16px', background: '#0D2430', fontSize: 12, color: '#8899A6', fontWeight: 'bold',
          }}>
            <span>餐段</span><span>客流</span><span>营收(元)</span><span>客单价</span>
          </div>
          {mockTimeslot.map(t => (
            <div key={t.period} style={{
              display: 'grid', gridTemplateColumns: '1fr 80px 100px 100px',
              padding: '14px 16px', borderBottom: '1px solid #1A3A48', alignItems: 'center',
            }}>
              <span style={{ fontSize: 14, color: '#fff' }}>{t.period}</span>
              <span style={{ fontSize: 18, fontWeight: 'bold', color: '#1890ff' }}>{t.traffic}</span>
              <span style={{ color: '#E0C97F' }}>{t.revenue.toLocaleString()}</span>
              <span>{t.avgPrice}元</span>
            </div>
          ))}
          <div style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 80 }}>
              {mockTimeslot.map(t => {
                const maxTraffic = Math.max(...mockTimeslot.map(x => x.traffic));
                const h = (t.traffic / maxTraffic) * 100;
                return (
                  <div key={t.period} style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ height: `${h}%`, background: '#1890ff', borderRadius: '4px 4px 0 0', minHeight: 4 }} />
                    <div style={{ fontSize: 10, color: '#666', marginTop: 4 }}>{t.period.split(' ')[0]}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
