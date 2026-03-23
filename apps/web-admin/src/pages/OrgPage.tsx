/**
 * OrgPage — 组织管理
 * 员工 + 排班 + 考勤 + 绩效
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

const mockEmployees = [
  { name: '陈师傅', role: '主厨', store: '芙蓉店', status: '在岗' },
  { name: '刘小妹', role: '服务员', store: '芙蓉店', status: '在岗' },
  { name: '张经理', role: '店长', store: '梅溪湖店', status: '休息' },
];

const mockSchedule = [
  { shift: '早班 08:00-16:00', people: 6, filled: 6, store: '芙蓉店' },
  { shift: '晚班 15:00-23:00', people: 8, filled: 7, store: '芙蓉店' },
  { shift: '早班 08:00-16:00', people: 5, filled: 5, store: '梅溪湖店' },
];

const mockPerformance = [
  { name: '陈师傅', metric: '出餐效率', score: 96, trend: '+3' },
  { name: '刘小妹', metric: '客户好评率', score: 92, trend: '+5' },
  { name: '张经理', metric: '门店综合', score: 88, trend: '-1' },
];

export function OrgPage() {
  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>组织管理</h1>
      <p style={subtitleStyle}>员工花名册 / 排班管理 / 考勤记录 / 绩效看板</p>

      <div style={gridStyle}>
        {/* 员工列表 */}
        <div style={cardStyle}>
          <div style={cardTitle}>员工花名册</div>
          {mockEmployees.map((e) => (
            <div key={e.name} style={listItem}>
              <span>{e.name}</span>
              <span style={{ color: '#8899A6' }}>{e.role}</span>
              <span style={{ color: '#8899A6' }}>{e.store}</span>
              <span style={{ color: e.status === '在岗' ? '#66BB6A' : '#FFA726' }}>{e.status}</span>
            </div>
          ))}
        </div>

        {/* 排班 */}
        <div style={cardStyle}>
          <div style={cardTitle}>今日排班</div>
          {mockSchedule.map((s, idx) => (
            <div key={idx} style={listItem}>
              <span>{s.store}</span>
              <span style={{ color: '#8899A6' }}>{s.shift}</span>
              <span style={{ color: s.filled === s.people ? '#66BB6A' : '#EF5350' }}>
                {s.filled}/{s.people} 人
              </span>
            </div>
          ))}
        </div>

        {/* 绩效 */}
        <div style={cardStyle}>
          <div style={cardTitle}>绩效看板</div>
          {mockPerformance.map((p) => (
            <div key={p.name} style={listItem}>
              <span>{p.name}</span>
              <span style={{ color: '#8899A6' }}>{p.metric}</span>
              <span style={{ color: '#4FC3F7', fontWeight: 600 }}>{p.score} 分</span>
              <span style={{ color: p.trend.startsWith('+') ? '#66BB6A' : '#EF5350' }}>
                {p.trend.startsWith('+') ? p.trend : p.trend}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
