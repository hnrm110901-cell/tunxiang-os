/**
 * Agent全局监控 — 所有商户健康度
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
  healthBar: (pct: number) => ({
    width: 100, height: 6, borderRadius: 3, background: '#1A3540', position: 'relative' as const, display: 'inline-block',
  }) as React.CSSProperties,
  healthFill: (pct: number) => ({
    width: `${pct}%`, height: '100%', borderRadius: 3, position: 'absolute' as const, top: 0, left: 0,
    background: pct > 90 ? '#22C55E' : pct > 70 ? '#F59E0B' : '#EF4444',
  }) as React.CSSProperties,
};

const agents = [
  { merchant: '尝在一起', agent: '折扣守护', health: 98, decisions: 1245, alerts: 3, lastRun: '10秒前' },
  { merchant: '尝在一起', agent: '出餐调度', health: 95, decisions: 3670, alerts: 8, lastRun: '5秒前' },
  { merchant: '最黔线', agent: '折扣守护', health: 92, decisions: 567, alerts: 5, lastRun: '15秒前' },
  { merchant: '尚宫厨', agent: '智能排菜', health: 88, decisions: 234, alerts: 12, lastRun: '1分钟前' },
  { merchant: '湘味传奇', agent: '库存预警', health: 65, decisions: 89, alerts: 28, lastRun: '30分钟前' },
];

export function AgentMonitorPage() {
  const avgHealth = Math.round(agents.reduce((sum, a) => sum + a.health, 0) / agents.length);
  const totalDecisions = agents.reduce((sum, a) => sum + a.decisions, 0);
  return (
    <div style={s.page}>
      <div style={s.title}>Agent全局监控</div>
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>运行中Agent</div><div style={s.cardValue}>{agents.length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>平均健康度</div><div style={{ ...s.cardValue, color: avgHealth > 80 ? '#22C55E' : '#F59E0B' }}>{avgHealth}%</div></div>
        <div style={s.card}><div style={s.cardLabel}>今日决策数</div><div style={{ ...s.cardValue, color: '#3B82F6' }}>{totalDecisions.toLocaleString()}</div></div>
        <div style={s.card}><div style={s.cardLabel}>今日告警</div><div style={{ ...s.cardValue, color: '#F59E0B' }}>{agents.reduce((sum, a) => sum + a.alerts, 0)}</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>所有商户Agent实例</div>
        <button style={s.btn}>批量重启</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>商户</th>
            <th style={s.th}>Agent</th>
            <th style={s.th}>健康度</th>
            <th style={s.th}>今日决策</th>
            <th style={s.th}>告警</th>
            <th style={s.th}>最后运行</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((a, i) => (
            <tr key={i}>
              <td style={s.td}>{a.merchant}</td>
              <td style={s.td}>{a.agent}</td>
              <td style={s.td}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={s.healthBar(a.health)}>
                    <div style={s.healthFill(a.health)} />
                  </div>
                  <span style={{ fontSize: 12, color: a.health > 90 ? '#22C55E' : a.health > 70 ? '#F59E0B' : '#EF4444' }}>{a.health}%</span>
                </div>
              </td>
              <td style={s.td}>{a.decisions.toLocaleString()}</td>
              <td style={s.td}>{a.alerts > 10 ? <span style={{ color: '#EF4444' }}>{a.alerts}</span> : a.alerts}</td>
              <td style={s.td}>{a.lastRun}</td>
              <td style={s.td}>
                <button style={s.btnSec}>查看详情</button>
                <button style={s.btnSec}>重启</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
