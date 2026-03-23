/**
 * 平台数据 — 商户数/门店数/GMV
 */
const s = {
  page: { color: '#E0E0E0' } as React.CSSProperties,
  title: { fontSize: 22, fontWeight: 700, color: '#FFFFFF', marginBottom: 20 } as React.CSSProperties,
  cards: { display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  card: {
    flex: '1 1 200px', background: '#0D2129', borderRadius: 10, padding: '18px 20px',
    border: '1px solid #1A3540',
  } as React.CSSProperties,
  cardLabel: { fontSize: 12, color: '#6B8A97', marginBottom: 6 } as React.CSSProperties,
  cardValue: { fontSize: 28, fontWeight: 700, color: '#FF6B2C' } as React.CSSProperties,
  row: { display: 'flex', gap: 24, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  section: {
    flex: '1 1 320px', background: '#0D2129', borderRadius: 10, padding: 20,
    border: '1px solid #1A3540',
  } as React.CSSProperties,
  sectionTitle: { fontSize: 14, fontWeight: 600, color: '#FFFFFF', marginBottom: 16 } as React.CSSProperties,
  toolbar: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } as React.CSSProperties,
  btnSec: {
    background: 'transparent', color: '#FF6B2C', border: '1px solid #FF6B2C', borderRadius: 6,
    padding: '6px 14px', fontSize: 12, cursor: 'pointer', marginLeft: 6,
  } as React.CSSProperties,
  table: { width: '100%', borderCollapse: 'collapse' as const, fontSize: 13 } as React.CSSProperties,
  th: {
    textAlign: 'left' as const, padding: '10px 12px', borderBottom: '1px solid #1A3540',
    color: '#6B8A97', fontWeight: 600, fontSize: 12,
  } as React.CSSProperties,
  td: { padding: '10px 12px', borderBottom: '1px solid #112A33' } as React.CSSProperties,
  bar: (pct: number, color: string) => ({
    width: 120, height: 8, borderRadius: 4, background: '#1A3540', position: 'relative' as const, display: 'inline-block',
  }) as React.CSSProperties,
  barFill: (pct: number, color: string) => ({
    width: `${pct}%`, height: '100%', borderRadius: 4, position: 'absolute' as const, top: 0, left: 0,
    background: color,
  }) as React.CSSProperties,
};

const metrics = [
  { merchant: '尝在一起', stores: 12, monthGmv: 580000, orders: 12450, avgTicket: 46.6, growth: '+12%' },
  { merchant: '最黔线', stores: 6, monthGmv: 320000, orders: 7800, avgTicket: 41.0, growth: '+8%' },
  { merchant: '尚宫厨', stores: 8, monthGmv: 450000, orders: 5600, avgTicket: 80.4, growth: '+15%' },
  { merchant: '湘味传奇', stores: 3, monthGmv: 120000, orders: 3200, avgTicket: 37.5, growth: '-3%' },
];

const totalGmv = metrics.reduce((sum, m) => sum + m.monthGmv, 0);
const totalOrders = metrics.reduce((sum, m) => sum + m.orders, 0);
const totalStores = metrics.reduce((sum, m) => sum + m.stores, 0);
const maxGmv = Math.max(...metrics.map((m) => m.monthGmv));

export function PlatformDataPage() {
  return (
    <div style={s.page}>
      <div style={s.title}>平台数据</div>
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>商户总数</div><div style={s.cardValue}>{metrics.length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>门店总数</div><div style={{ ...s.cardValue, color: '#3B82F6' }}>{totalStores}</div></div>
        <div style={s.card}><div style={s.cardLabel}>本月GMV</div><div style={{ ...s.cardValue, color: '#22C55E' }}>{(totalGmv / 10000).toFixed(1)}万</div></div>
        <div style={s.card}><div style={s.cardLabel}>本月订单</div><div style={{ ...s.cardValue, color: '#A855F7' }}>{totalOrders.toLocaleString()}</div></div>
      </div>

      <div style={s.row}>
        <div style={s.section}>
          <div style={s.sectionTitle}>商户GMV排行</div>
          {metrics.sort((a, b) => b.monthGmv - a.monthGmv).map((m) => (
            <div key={m.merchant} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ fontSize: 13, width: 100 }}>{m.merchant}</span>
              <div style={s.bar(0, '')}>
                <div style={s.barFill(Math.round((m.monthGmv / maxGmv) * 100), '#FF6B2C')} />
              </div>
              <span style={{ fontSize: 12, color: '#FF6B2C', width: 60, textAlign: 'right' as const }}>{(m.monthGmv / 10000).toFixed(1)}万</span>
            </div>
          ))}
        </div>
        <div style={s.section}>
          <div style={s.sectionTitle}>关键指标汇总</div>
          <div style={{ fontSize: 13, color: '#8BA5B2', lineHeight: 2.0 }}>
            <div>平台月均客单价: <strong style={{ color: '#FFFFFF' }}>{(totalGmv / totalOrders).toFixed(1)}元</strong></div>
            <div>平均单店GMV: <strong style={{ color: '#FFFFFF' }}>{(totalGmv / totalStores / 10000).toFixed(2)}万</strong></div>
            <div>日均订单: <strong style={{ color: '#FFFFFF' }}>{Math.round(totalOrders / 30).toLocaleString()}单</strong></div>
            <div>活跃商户占比: <strong style={{ color: '#22C55E' }}>100%</strong></div>
          </div>
        </div>
      </div>

      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>商户经营数据</div>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>商户</th>
            <th style={s.th}>门店数</th>
            <th style={s.th}>本月GMV</th>
            <th style={s.th}>订单数</th>
            <th style={s.th}>客单价</th>
            <th style={s.th}>环比增长</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.merchant}>
              <td style={s.td}>{m.merchant}</td>
              <td style={s.td}>{m.stores}</td>
              <td style={s.td}>{(m.monthGmv / 10000).toFixed(1)}万</td>
              <td style={s.td}>{m.orders.toLocaleString()}</td>
              <td style={s.td}>{m.avgTicket.toFixed(1)}元</td>
              <td style={s.td}>
                <span style={{ color: m.growth.startsWith('+') ? '#22C55E' : '#EF4444', fontWeight: 600 }}>{m.growth}</span>
              </td>
              <td style={s.td}>
                <button style={s.btnSec}>查看详情</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
