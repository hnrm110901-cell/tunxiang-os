/**
 * 计费账单 — HaaS+SaaS+AI三层收入
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
  pieRow: { display: 'flex', justifyContent: 'space-around', alignItems: 'center' } as React.CSSProperties,
  pieItem: { textAlign: 'center' as const } as React.CSSProperties,
  pieDot: (color: string) => ({
    display: 'inline-block', width: 12, height: 12, borderRadius: '50%', background: color, marginRight: 6,
  }) as React.CSSProperties,
  toolbar: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } as React.CSSProperties,
  btn: {
    background: '#FF6B2C', color: '#FFF', border: 'none', borderRadius: 6,
    padding: '8px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
  } as React.CSSProperties,
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
};

const revenue = { haas: 156000, saas: 234000, ai: 89000 };
const total = revenue.haas + revenue.saas + revenue.ai;
const pcts = {
  haas: Math.round((revenue.haas / total) * 100),
  saas: Math.round((revenue.saas / total) * 100),
  ai: Math.round((revenue.ai / total) * 100),
};

const bills = [
  { merchant: '尝在一起', month: '2026-03', haas: 48000, saas: 72000, ai: 28000, status: '已付' },
  { merchant: '最黔线', month: '2026-03', haas: 32000, saas: 48000, ai: 18000, status: '已付' },
  { merchant: '尚宫厨', month: '2026-03', haas: 42000, saas: 66000, ai: 25000, status: '待付' },
  { merchant: '湘味传奇', month: '2026-03', haas: 18000, saas: 28000, ai: 10000, status: '逾期' },
  { merchant: '老长沙米粉', month: '2026-03', haas: 16000, saas: 20000, ai: 8000, status: '已停' },
];

const statusColor: Record<string, string> = { '已付': '#22C55E', '待付': '#F59E0B', '逾期': '#EF4444', '已停': '#6B8A97' };

export function BillingPage() {
  return (
    <div style={s.page}>
      <div style={s.title}>计费账单</div>
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>本月总收入</div><div style={s.cardValue}>{(total / 10000).toFixed(1)}万</div></div>
        <div style={s.card}><div style={s.cardLabel}>HaaS收入</div><div style={{ ...s.cardValue, color: '#3B82F6' }}>{(revenue.haas / 10000).toFixed(1)}万</div></div>
        <div style={s.card}><div style={s.cardLabel}>SaaS收入</div><div style={{ ...s.cardValue, color: '#22C55E' }}>{(revenue.saas / 10000).toFixed(1)}万</div></div>
        <div style={s.card}><div style={s.cardLabel}>AI收入</div><div style={{ ...s.cardValue, color: '#A855F7' }}>{(revenue.ai / 10000).toFixed(1)}万</div></div>
      </div>

      <div style={s.row}>
        <div style={s.section}>
          <div style={s.sectionTitle}>三层收入占比</div>
          <div style={s.pieRow}>
            <div style={s.pieItem}>
              <div style={{ width: 120, height: 120, borderRadius: '50%', background: `conic-gradient(#3B82F6 0% ${pcts.haas}%, #22C55E ${pcts.haas}% ${pcts.haas + pcts.saas}%, #A855F7 ${pcts.haas + pcts.saas}% 100%)`, margin: '0 auto 12px' }} />
            </div>
            <div>
              <div style={{ marginBottom: 8, fontSize: 13 }}><span style={s.pieDot('#3B82F6')} />HaaS {pcts.haas}%</div>
              <div style={{ marginBottom: 8, fontSize: 13 }}><span style={s.pieDot('#22C55E')} />SaaS {pcts.saas}%</div>
              <div style={{ marginBottom: 8, fontSize: 13 }}><span style={s.pieDot('#A855F7')} />AI {pcts.ai}%</div>
            </div>
          </div>
        </div>
        <div style={s.section}>
          <div style={s.sectionTitle}>收入趋势说明</div>
          <div style={{ fontSize: 13, color: '#8BA5B2', lineHeight: 1.8 }}>
            <p>SaaS收入占比最高（{pcts.saas}%），为核心收入来源。</p>
            <p>HaaS（Mac mini + 安卓POS硬件租赁）占 {pcts.haas}%。</p>
            <p>AI增值服务（Agent智能决策）占 {pcts.ai}%，增速最快。</p>
          </div>
        </div>
      </div>

      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>本月账单明细</div>
        <button style={s.btn}>+ 新建账单</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>商户</th>
            <th style={s.th}>月份</th>
            <th style={s.th}>HaaS</th>
            <th style={s.th}>SaaS</th>
            <th style={s.th}>AI</th>
            <th style={s.th}>合计</th>
            <th style={s.th}>状态</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {bills.map((b) => (
            <tr key={b.merchant}>
              <td style={s.td}>{b.merchant}</td>
              <td style={s.td}>{b.month}</td>
              <td style={s.td}>{b.haas.toLocaleString()}</td>
              <td style={s.td}>{b.saas.toLocaleString()}</td>
              <td style={s.td}>{b.ai.toLocaleString()}</td>
              <td style={s.td}><strong>{(b.haas + b.saas + b.ai).toLocaleString()}</strong></td>
              <td style={s.td}><span style={{ color: statusColor[b.status] || '#6B8A97', fontWeight: 600 }}>{b.status}</span></td>
              <td style={s.td}>
                <button style={s.btnSec}>查看详情</button>
                <button style={s.btnSec}>催款</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
