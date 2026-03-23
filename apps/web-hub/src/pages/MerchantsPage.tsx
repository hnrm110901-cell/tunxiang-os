/**
 * 商户管理 — 开户/续费/停用/升级
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
  cardValueGreen: { fontSize: 28, fontWeight: 700, color: '#22C55E' } as React.CSSProperties,
  cardValueRed: { fontSize: 28, fontWeight: 700, color: '#EF4444' } as React.CSSProperties,
  cardValueBlue: { fontSize: 28, fontWeight: 700, color: '#3B82F6' } as React.CSSProperties,
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
  badge: (color: string) => ({
    display: 'inline-block', padding: '2px 10px', borderRadius: 20,
    fontSize: 11, fontWeight: 600, background: `${color}22`, color,
  }) as React.CSSProperties,
};

const merchants = [
  { name: '尝在一起', plan: 'Pro', stores: 12, expire: '2026-12-31', status: '正常' },
  { name: '最黔线', plan: 'Standard', stores: 6, expire: '2026-09-15', status: '正常' },
  { name: '尚宫厨', plan: 'Pro', stores: 8, expire: '2026-06-30', status: '正常' },
  { name: '湘味传奇', plan: 'Lite', stores: 3, expire: '2026-03-28', status: '即将到期' },
  { name: '老长沙米粉', plan: 'Standard', stores: 15, expire: '2025-12-01', status: '已停用' },
];

const statusColor: Record<string, string> = {
  '正常': '#22C55E',
  '即将到期': '#F59E0B',
  '已停用': '#EF4444',
};

export function MerchantsPage() {
  return (
    <div style={s.page}>
      <div style={s.title}>商户管理</div>
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>商户总数</div><div style={s.cardValue}>5</div></div>
        <div style={s.card}><div style={s.cardLabel}>正常运营</div><div style={s.cardValueGreen}>3</div></div>
        <div style={s.card}><div style={s.cardLabel}>即将到期</div><div style={{ ...s.cardValue, color: '#F59E0B' }}>1</div></div>
        <div style={s.card}><div style={s.cardLabel}>已停用</div><div style={s.cardValueRed}>1</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>全部商户</div>
        <button style={s.btn}>+ 新建商户</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>商户名称</th>
            <th style={s.th}>套餐</th>
            <th style={s.th}>门店数</th>
            <th style={s.th}>到期日</th>
            <th style={s.th}>状态</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {merchants.map((m) => (
            <tr key={m.name}>
              <td style={s.td}>{m.name}</td>
              <td style={s.td}><span style={s.badge('#3B82F6')}>{m.plan}</span></td>
              <td style={s.td}>{m.stores}</td>
              <td style={s.td}>{m.expire}</td>
              <td style={s.td}><span style={s.badge(statusColor[m.status] || '#6B8A97')}>{m.status}</span></td>
              <td style={s.td}>
                <button style={s.btnSec}>编辑</button>
                <button style={s.btnSec}>续费</button>
                <button style={s.btnSec}>查看详情</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
