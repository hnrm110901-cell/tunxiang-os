/**
 * TradePage — 交易管理
 * 订单列表 + 支付记录 + 日结
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

const mockOrders = [
  { id: 'ORD-20260322-001', table: 'A03', amount: '¥268.00', status: '已完成' },
  { id: 'ORD-20260322-002', table: 'B07', amount: '¥152.50', status: '出餐中' },
  { id: 'ORD-20260322-003', table: 'C01', amount: '¥89.00', status: '待支付' },
];

const mockPayments = [
  { method: '微信支付', count: 128, total: '¥18,640' },
  { method: '支付宝', count: 42, total: '¥6,120' },
  { method: '现金', count: 8, total: '¥960' },
];

export function TradePage() {
  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>交易管理</h1>
      <p style={subtitleStyle}>订单列表 / 支付记录 / 日结报表</p>

      <div style={gridStyle}>
        {/* 订单列表 */}
        <div style={cardStyle}>
          <div style={cardTitle}>今日订单</div>
          {mockOrders.map((o) => (
            <div key={o.id} style={listItem}>
              <span>{o.id}</span>
              <span>桌号 {o.table}</span>
              <span>{o.amount}</span>
              <span style={{ color: o.status === '已完成' ? '#66BB6A' : o.status === '出餐中' ? '#FFA726' : '#EF5350' }}>
                {o.status}
              </span>
            </div>
          ))}
        </div>

        {/* 支付记录 */}
        <div style={cardStyle}>
          <div style={cardTitle}>支付汇总</div>
          {mockPayments.map((p) => (
            <div key={p.method} style={listItem}>
              <span>{p.method}</span>
              <span>{p.count} 笔</span>
              <span style={{ color: '#4FC3F7' }}>{p.total}</span>
            </div>
          ))}
        </div>

        {/* 日结 */}
        <div style={cardStyle}>
          <div style={cardTitle}>日结概览</div>
          <div style={{ ...listItem, fontWeight: 600 }}>
            <span>营业额</span>
            <span style={{ color: '#66BB6A', fontSize: '18px' }}>¥25,720</span>
          </div>
          <div style={listItem}>
            <span>订单数</span>
            <span>178 单</span>
          </div>
          <div style={listItem}>
            <span>客单价</span>
            <span>¥144.49</span>
          </div>
        </div>
      </div>
    </div>
  );
}
