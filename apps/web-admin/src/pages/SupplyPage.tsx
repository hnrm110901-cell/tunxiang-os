/**
 * SupplyPage — 供应链管理
 * 库存 + 采购 + 供应商 + 损耗
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

const alertBadge: React.CSSProperties = {
  backgroundColor: '#EF5350',
  color: '#FFF',
  borderRadius: '4px',
  padding: '2px 8px',
  fontSize: '11px',
};

const mockInventory = [
  { name: '鲈鱼', stock: '12 kg', expiry: '明天', alert: true },
  { name: '五花肉', stock: '25 kg', expiry: '3天后', alert: false },
  { name: '小米椒', stock: '3 kg', expiry: '今天', alert: true },
];

const mockPurchase = [
  { id: 'PO-0322-01', supplier: '湘菜鲜配', items: 8, total: '¥3,280', status: '已到货' },
  { id: 'PO-0322-02', supplier: '农鲜达', items: 5, total: '¥1,650', status: '配送中' },
];

const mockWaste = [
  { item: '青菜叶', amount: '2.3 kg', reason: '过期报废', cost: '¥18' },
  { item: '三文鱼边角', amount: '0.8 kg', reason: '加工损耗', cost: '¥64' },
  { item: '米饭', amount: '1.5 kg', reason: '余量报废', cost: '¥6' },
];

export function SupplyPage() {
  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>供应链管理</h1>
      <p style={subtitleStyle}>库存监控 / 采购管理 / 供应商 / 损耗分析</p>

      <div style={gridStyle}>
        {/* 库存监控 */}
        <div style={cardStyle}>
          <div style={cardTitle}>库存预警</div>
          {mockInventory.map((i) => (
            <div key={i.name} style={listItem}>
              <span>{i.name}</span>
              <span>{i.stock}</span>
              <span style={{ color: '#8899A6' }}>到期: {i.expiry}</span>
              {i.alert && <span style={alertBadge}>预警</span>}
            </div>
          ))}
        </div>

        {/* 采购单 */}
        <div style={cardStyle}>
          <div style={cardTitle}>今日采购单</div>
          {mockPurchase.map((p) => (
            <div key={p.id} style={listItem}>
              <span>{p.id}</span>
              <span style={{ color: '#8899A6' }}>{p.supplier}</span>
              <span>{p.total}</span>
              <span style={{ color: p.status === '已到货' ? '#66BB6A' : '#FFA726' }}>{p.status}</span>
            </div>
          ))}
        </div>

        {/* 损耗 */}
        <div style={cardStyle}>
          <div style={cardTitle}>今日损耗记录</div>
          {mockWaste.map((w) => (
            <div key={w.item} style={listItem}>
              <span>{w.item}</span>
              <span>{w.amount}</span>
              <span style={{ color: '#8899A6' }}>{w.reason}</span>
              <span style={{ color: '#EF5350' }}>{w.cost}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
