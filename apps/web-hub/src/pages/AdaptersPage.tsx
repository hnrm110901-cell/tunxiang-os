/**
 * Adapter监控 — 品智/G10/金蝶连接状态
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
  dot: (ok: boolean) => ({
    display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
    background: ok ? '#22C55E' : '#EF4444', marginRight: 6,
  }) as React.CSSProperties,
  badge: (color: string) => ({
    display: 'inline-block', padding: '2px 10px', borderRadius: 20,
    fontSize: 11, fontWeight: 600, background: `${color}22`, color,
  }) as React.CSSProperties,
};

const adapters = [
  { name: '品智POS', merchant: '尝在一起', type: 'POS', status: true, syncRate: '99.8%', lastSync: '1分钟前', errors: 0 },
  { name: '品智POS', merchant: '最黔线', type: 'POS', status: true, syncRate: '99.5%', lastSync: '3分钟前', errors: 2 },
  { name: 'G10进销存', merchant: '尚宫厨', type: '供应链', status: true, syncRate: '98.2%', lastSync: '10分钟前', errors: 5 },
  { name: '金蝶财务', merchant: '尝在一起', type: '财务', status: false, syncRate: '95.1%', lastSync: '2小时前', errors: 12 },
  { name: '微生活会员', merchant: '最黔线', type: '会员', status: true, syncRate: '99.9%', lastSync: '30秒前', errors: 0 },
];

export function AdaptersPage() {
  const online = adapters.filter((a) => a.status).length;
  const totalErrors = adapters.reduce((sum, a) => sum + a.errors, 0);
  return (
    <div style={s.page}>
      <div style={s.title}>Adapter监控</div>
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>Adapter总数</div><div style={s.cardValue}>{adapters.length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>在线</div><div style={{ ...s.cardValue, color: '#22C55E' }}>{online}</div></div>
        <div style={s.card}><div style={s.cardLabel}>离线</div><div style={{ ...s.cardValue, color: '#EF4444' }}>{adapters.length - online}</div></div>
        <div style={s.card}><div style={s.cardLabel}>今日错误数</div><div style={{ ...s.cardValue, color: '#F59E0B' }}>{totalErrors}</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>所有Adapter连接</div>
        <button style={s.btn}>+ 新建连接</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>Adapter</th>
            <th style={s.th}>商户</th>
            <th style={s.th}>类型</th>
            <th style={s.th}>连接状态</th>
            <th style={s.th}>同步率</th>
            <th style={s.th}>最后同步</th>
            <th style={s.th}>错误数</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {adapters.map((a, i) => (
            <tr key={i}>
              <td style={s.td}>{a.name}</td>
              <td style={s.td}>{a.merchant}</td>
              <td style={s.td}><span style={s.badge('#3B82F6')}>{a.type}</span></td>
              <td style={s.td}><span style={s.dot(a.status)} />{a.status ? '已连接' : '断开'}</td>
              <td style={s.td}>{a.syncRate}</td>
              <td style={s.td}>{a.lastSync}</td>
              <td style={s.td}>{a.errors > 0 ? <span style={{ color: '#EF4444' }}>{a.errors}</span> : '0'}</td>
              <td style={s.td}>
                <button style={s.btnSec}>重连</button>
                <button style={s.btnSec}>查看日志</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
