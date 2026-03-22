/**
 * Agent 监控页 — 9 个 Skill Agent 状态概览
 */

const AGENTS = [
  { id: 'discount_guard', name: '折扣守护', priority: 'P0', location: '边缘+云端', actions: 6, implemented: 6, status: 'active' },
  { id: 'smart_menu', name: '智能排菜', priority: 'P0', location: '云端', actions: 8, implemented: 8, status: 'active' },
  { id: 'serve_dispatch', name: '出餐调度', priority: 'P1', location: '边缘', actions: 7, implemented: 7, status: 'active' },
  { id: 'member_insight', name: '会员洞察', priority: 'P1', location: '云端', actions: 9, implemented: 9, status: 'active' },
  { id: 'inventory_alert', name: '库存预警', priority: 'P1', location: '边缘+云端', actions: 9, implemented: 9, status: 'active' },
  { id: 'finance_audit', name: '财务稽核', priority: 'P1', location: '云端', actions: 7, implemented: 7, status: 'active' },
  { id: 'store_inspect', name: '巡店质检', priority: 'P2', location: '云端', actions: 7, implemented: 7, status: 'active' },
  { id: 'smart_service', name: '智能客服', priority: 'P2', location: '云端', actions: 9, implemented: 9, status: 'active' },
  { id: 'private_ops', name: '私域运营', priority: 'P2', location: '云端', actions: 11, implemented: 11, status: 'active' },
];

const priorityColor: Record<string, string> = { P0: '#ff4d4f', P1: '#faad14', P2: '#1890ff' };
const statusColor: Record<string, string> = { active: '#52c41a', skeleton: '#666' };

export function AgentMonitorPage() {
  const totalActions = AGENTS.reduce((s, a) => s + a.actions, 0);
  const implementedActions = AGENTS.reduce((s, a) => s + a.implemented, 0);
  const pct = Math.round(implementedActions / totalActions * 100);

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 8 }}>Agent OS 监控</h2>
      <p style={{ color: '#999', marginBottom: 20 }}>
        1 Master + 9 Skill Agent · {implementedActions}/{totalActions} actions 已实现 ({pct}%)
      </p>

      {/* 总进度条 */}
      <div style={{ background: '#1a2a33', borderRadius: 8, height: 12, marginBottom: 24, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: '#FF6B2C', borderRadius: 8 }} />
      </div>

      {/* Agent 卡片网格 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        {AGENTS.map((agent) => {
          const implPct = agent.actions > 0 ? Math.round(agent.implemented / agent.actions * 100) : 0;
          return (
            <div key={agent.id} style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: 16, fontWeight: 'bold' }}>{agent.name}</span>
                <span style={{
                  padding: '2px 8px', borderRadius: 10, fontSize: 11,
                  background: priorityColor[agent.priority] + '22',
                  color: priorityColor[agent.priority],
                }}>{agent.priority}</span>
              </div>
              <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>
                {agent.location} · {agent.actions} actions
              </div>
              {/* 实现进度 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, height: 6, background: '#1a2a33', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: `${implPct}%`, height: '100%', borderRadius: 3,
                    background: implPct === 100 ? '#52c41a' : implPct > 0 ? '#FF6B2C' : '#333',
                  }} />
                </div>
                <span style={{ fontSize: 11, color: '#999', width: 40, textAlign: 'right' }}>{implPct}%</span>
              </div>
              <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>
                {agent.implemented}/{agent.actions} 已实现
              </div>
              <div style={{ marginTop: 8 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: statusColor[agent.status],
                  display: 'inline-block', marginRight: 6,
                }} />
                <span style={{ fontSize: 11, color: statusColor[agent.status] }}>
                  {agent.status === 'active' ? '运行中' : '骨架'}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 三条硬约束状态 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginTop: 24 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 16 }}>三条硬约束</h3>
        <div style={{ display: 'flex', gap: 24 }}>
          {[
            { name: '毛利底线', desc: '折扣/赠送不可使毛利低于阈值', status: 'enforced' },
            { name: '食安合规', desc: '临期/过期食材不可用于出品', status: 'enforced' },
            { name: '客户体验', desc: '出餐时间不可超过门店上限', status: 'enforced' },
          ].map((c) => (
            <div key={c.name} style={{ flex: 1, padding: 12, background: '#0B1A20', borderRadius: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <span style={{ color: '#52c41a' }}>✓</span>
                <span style={{ fontWeight: 'bold', fontSize: 14 }}>{c.name}</span>
              </div>
              <div style={{ fontSize: 12, color: '#666' }}>{c.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
