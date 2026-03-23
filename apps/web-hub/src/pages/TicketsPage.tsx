/**
 * 工单系统 — 报障/实施/SLA
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

const tickets = [
  { id: 'TK-2026-001', merchant: '尝在一起', store: '五一广场店', type: '报障', title: 'POS打印机断连', priority: 'P1', status: '处理中', sla: '2小时', created: '2026-03-23 09:15' },
  { id: 'TK-2026-002', merchant: '最黔线', store: '太平街店', type: '实施', title: '新门店部署', priority: 'P2', status: '待分配', sla: '48小时', created: '2026-03-22 14:30' },
  { id: 'TK-2026-003', merchant: '尚宫厨', store: '天心店', type: '报障', title: 'Mac mini离线', priority: 'P0', status: '处理中', sla: '1小时', created: '2026-03-23 10:00' },
  { id: 'TK-2026-004', merchant: '湘味传奇', store: '侯家塘店', type: '实施', title: 'Adapter对接金蝶', priority: 'P2', status: '已完成', sla: '72小时', created: '2026-03-20 11:00' },
  { id: 'TK-2026-005', merchant: '尝在一起', store: '万达店', type: '报障', title: 'KDS屏幕卡顿', priority: 'P1', status: '待分配', sla: '4小时', created: '2026-03-23 08:45' },
];

const priorityColor: Record<string, string> = { P0: '#EF4444', P1: '#F59E0B', P2: '#3B82F6' };
const statusColor: Record<string, string> = { '处理中': '#F59E0B', '待分配': '#3B82F6', '已完成': '#22C55E' };

export function TicketsPage() {
  const open = tickets.filter((t) => t.status !== '已完成').length;
  return (
    <div style={s.page}>
      <div style={s.title}>工单中心</div>
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>工单总数</div><div style={s.cardValue}>{tickets.length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>未完成</div><div style={{ ...s.cardValue, color: '#F59E0B' }}>{open}</div></div>
        <div style={s.card}><div style={s.cardLabel}>P0工单</div><div style={{ ...s.cardValue, color: '#EF4444' }}>{tickets.filter((t) => t.priority === 'P0').length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>SLA达标率</div><div style={{ ...s.cardValue, color: '#22C55E' }}>87%</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>所有工单</div>
        <button style={s.btn}>+ 新建工单</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>工单号</th>
            <th style={s.th}>商户</th>
            <th style={s.th}>门店</th>
            <th style={s.th}>类型</th>
            <th style={s.th}>标题</th>
            <th style={s.th}>优先级</th>
            <th style={s.th}>状态</th>
            <th style={s.th}>SLA</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((t) => (
            <tr key={t.id}>
              <td style={s.td}>{t.id}</td>
              <td style={s.td}>{t.merchant}</td>
              <td style={s.td}>{t.store}</td>
              <td style={s.td}><span style={s.badge('#3B82F6')}>{t.type}</span></td>
              <td style={s.td}>{t.title}</td>
              <td style={s.td}><span style={s.badge(priorityColor[t.priority] || '#6B8A97')}>{t.priority}</span></td>
              <td style={s.td}><span style={{ color: statusColor[t.status] || '#6B8A97', fontWeight: 600 }}>{t.status}</span></td>
              <td style={s.td}>{t.sla}</td>
              <td style={s.td}>
                <button style={s.btnSec}>处理</button>
                <button style={s.btnSec}>查看详情</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
