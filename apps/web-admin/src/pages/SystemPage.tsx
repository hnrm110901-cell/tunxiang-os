/**
 * SystemPage — 系统设置
 * 品牌配置 + 角色权限 + 集成管理
 */

const containerStyle: React.CSSProperties = {
  backgroundColor: '#0B1A20',
  color: '#E0E0E0',
  minHeight: '100vh',
  padding: '24px 32px',
  fontFamily: 'system-ui, -apple-system, sans-serif',
};

const headerStyle: React.CSSProperties = {
  fontSize: '24px',
  fontWeight: 700,
  color: '#FFFFFF',
  marginBottom: '8px',
};

const subtitleStyle: React.CSSProperties = {
  fontSize: '14px',
  color: '#8899A6',
  marginBottom: '24px',
};

const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
  gap: '20px',
};

const cardStyle: React.CSSProperties = {
  backgroundColor: '#112B36',
  borderRadius: '12px',
  padding: '20px',
  border: '1px solid #1E3A47',
};

const cardTitle: React.CSSProperties = {
  fontSize: '16px',
  fontWeight: 600,
  color: '#4FC3F7',
  marginBottom: '12px',
};

const listItem: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  padding: '8px 0',
  borderBottom: '1px solid #1E3A47',
  fontSize: '13px',
};

const tagStyle = (color: string): React.CSSProperties => ({
  backgroundColor: color,
  color: '#FFF',
  borderRadius: '4px',
  padding: '2px 8px',
  fontSize: '11px',
});

const mockBrands = [
  { name: '尝在一起', stores: 12, plan: '专业版', status: '运行中' },
  { name: '最黔线', stores: 6, plan: '标准版', status: '运行中' },
  { name: '尚宫厨', stores: 3, plan: '标准版', status: '试运营' },
];

const mockRoles = [
  { role: '超级管理员', users: 2, permissions: '全部权限' },
  { role: '区域经理', users: 5, permissions: '查看+审批' },
  { role: '店长', users: 12, permissions: '门店管理' },
  { role: '收银员', users: 36, permissions: '收银+查单' },
];

const mockIntegrations = [
  { name: '品智 POS', type: '适配器', status: '已对接', sync: '实时' },
  { name: '微信支付', type: '支付', status: '已对接', sync: '实时' },
  { name: '金蝶财务', type: '财务', status: '对接中', sync: '每日' },
];

export function SystemPage() {
  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>系统设置</h1>
      <p style={subtitleStyle}>品牌配置 / 角色权限 / 集成管理</p>

      <div style={gridStyle}>
        {/* 品牌配置 */}
        <div style={cardStyle}>
          <div style={cardTitle}>品牌配置</div>
          {mockBrands.map((b) => (
            <div key={b.name} style={listItem}>
              <span style={{ fontWeight: 600 }}>{b.name}</span>
              <span style={{ color: '#8899A6' }}>{b.stores} 家门店</span>
              <span style={tagStyle('#4FC3F7')}>{b.plan}</span>
              <span style={{ color: b.status === '运行中' ? '#66BB6A' : '#FFA726' }}>{b.status}</span>
            </div>
          ))}
        </div>

        {/* 角色权限 */}
        <div style={cardStyle}>
          <div style={cardTitle}>角色权限</div>
          {mockRoles.map((r) => (
            <div key={r.role} style={listItem}>
              <span>{r.role}</span>
              <span style={{ color: '#8899A6' }}>{r.users} 人</span>
              <span style={{ color: '#4FC3F7' }}>{r.permissions}</span>
            </div>
          ))}
        </div>

        {/* 集成管理 */}
        <div style={cardStyle}>
          <div style={cardTitle}>集成管理</div>
          {mockIntegrations.map((i) => (
            <div key={i.name} style={listItem}>
              <span>{i.name}</span>
              <span style={tagStyle('#8899A6')}>{i.type}</span>
              <span style={{ color: i.status === '已对接' ? '#66BB6A' : '#FFA726' }}>{i.status}</span>
              <span style={{ color: '#8899A6' }}>同步: {i.sync}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
