/**
 * 模板分配 — Pro/Standard/Lite
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
  badge: (color: string) => ({
    display: 'inline-block', padding: '2px 10px', borderRadius: 20,
    fontSize: 11, fontWeight: 600, background: `${color}22`, color,
  }) as React.CSSProperties,
};

const templates = [
  { name: 'Pro 旗舰版', tier: 'Pro', modules: 'POS+KDS+Agent+Analytics', merchants: 2, color: '#FF6B2C' },
  { name: 'Standard 标准版', tier: 'Standard', modules: 'POS+KDS+Agent', merchants: 2, color: '#3B82F6' },
  { name: 'Lite 轻量版', tier: 'Lite', modules: 'POS+KDS', merchants: 1, color: '#6B8A97' },
];

const assignments = [
  { merchant: '尝在一起', template: 'Pro', assignDate: '2025-06-15', stores: 12 },
  { merchant: '最黔线', template: 'Standard', assignDate: '2025-08-20', stores: 6 },
  { merchant: '尚宫厨', template: 'Pro', assignDate: '2025-07-10', stores: 8 },
  { merchant: '湘味传奇', template: 'Lite', assignDate: '2025-11-01', stores: 3 },
];

const tierColor: Record<string, string> = { Pro: '#FF6B2C', Standard: '#3B82F6', Lite: '#6B8A97' };

export function TemplatesPage() {
  return (
    <div style={s.page}>
      <div style={s.title}>模板配置</div>
      <div style={s.cards}>
        {templates.map((t) => (
          <div key={t.name} style={s.card}>
            <div style={s.cardLabel}>{t.name}</div>
            <div style={{ ...s.cardValue, color: t.color }}>{t.merchants}</div>
            <div style={{ fontSize: 11, color: '#6B8A97', marginTop: 4 }}>{t.modules}</div>
          </div>
        ))}
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>模板分配记录</div>
        <button style={s.btn}>+ 新建模板</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>商户</th>
            <th style={s.th}>模板</th>
            <th style={s.th}>分配日期</th>
            <th style={s.th}>覆盖门店</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {assignments.map((a) => (
            <tr key={a.merchant}>
              <td style={s.td}>{a.merchant}</td>
              <td style={s.td}><span style={s.badge(tierColor[a.template] || '#6B8A97')}>{a.template}</span></td>
              <td style={s.td}>{a.assignDate}</td>
              <td style={s.td}>{a.stores}</td>
              <td style={s.td}>
                <button style={s.btnSec}>升级</button>
                <button style={s.btnSec}>编辑</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
