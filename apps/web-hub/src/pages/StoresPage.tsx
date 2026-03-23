/**
 * 全局门店管理 — 跨商户，在线状态
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
  dot: (online: boolean) => ({
    display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
    background: online ? '#22C55E' : '#EF4444', marginRight: 6,
  }) as React.CSSProperties,
};

const stores = [
  { name: '尝在一起(五一广场店)', merchant: '尝在一起', city: '长沙', online: true, posVer: '3.0.1', lastSync: '2分钟前' },
  { name: '尝在一起(万达店)', merchant: '尝在一起', city: '长沙', online: true, posVer: '3.0.1', lastSync: '1分钟前' },
  { name: '最黔线(太平街店)', merchant: '最黔线', city: '长沙', online: true, posVer: '3.0.0', lastSync: '5分钟前' },
  { name: '尚宫厨(天心店)', merchant: '尚宫厨', city: '长沙', online: false, posVer: '2.9.8', lastSync: '3小时前' },
  { name: '湘味传奇(侯家塘店)', merchant: '湘味传奇', city: '长沙', online: true, posVer: '3.0.1', lastSync: '30秒前' },
];

export function StoresPage() {
  const onlineCount = stores.filter((st) => st.online).length;
  return (
    <div style={s.page}>
      <div style={s.title}>门店总览</div>
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>门店总数</div><div style={s.cardValue}>{stores.length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>在线门店</div><div style={{ ...s.cardValue, color: '#22C55E' }}>{onlineCount}</div></div>
        <div style={s.card}><div style={s.cardLabel}>离线门店</div><div style={{ ...s.cardValue, color: '#EF4444' }}>{stores.length - onlineCount}</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>所有门店（跨商户）</div>
        <button style={s.btn}>+ 新建门店</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>门店名称</th>
            <th style={s.th}>所属商户</th>
            <th style={s.th}>城市</th>
            <th style={s.th}>在线状态</th>
            <th style={s.th}>POS版本</th>
            <th style={s.th}>最后同步</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {stores.map((st) => (
            <tr key={st.name}>
              <td style={s.td}>{st.name}</td>
              <td style={s.td}>{st.merchant}</td>
              <td style={s.td}>{st.city}</td>
              <td style={s.td}><span style={s.dot(st.online)} />{st.online ? '在线' : '离线'}</td>
              <td style={s.td}>{st.posVer}</td>
              <td style={s.td}>{st.lastSync}</td>
              <td style={s.td}>
                <button style={s.btnSec}>查看详情</button>
                <button style={s.btnSec}>编辑</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
