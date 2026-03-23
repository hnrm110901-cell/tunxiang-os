/**
 * CatalogPage — 菜品管理
 * 菜品列表 + 分类 + BOM + 排名
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

const mockDishes = [
  { name: '招牌剁椒鱼头', category: '招牌菜', price: '¥128', margin: '62%' },
  { name: '小炒黄牛肉', category: '湘菜', price: '¥68', margin: '58%' },
  { name: '茶油土鸡汤', category: '汤品', price: '¥88', margin: '71%' },
];

const mockCategories = [
  { name: '招牌菜', count: 12, status: '已上架' },
  { name: '湘菜', count: 28, status: '已上架' },
  { name: '时令特供', count: 5, status: '部分上架' },
];

const mockRanking = [
  { rank: 1, name: '招牌剁椒鱼头', sales: 342, trend: '+12%' },
  { rank: 2, name: '小炒黄牛肉', sales: 286, trend: '+8%' },
  { rank: 3, name: '口味虾', sales: 231, trend: '-3%' },
];

export function CatalogPage() {
  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>菜品管理</h1>
      <p style={subtitleStyle}>菜品列表 / 分类管理 / BOM配方 / 销量排名</p>

      <div style={gridStyle}>
        {/* 菜品列表 */}
        <div style={cardStyle}>
          <div style={cardTitle}>菜品列表</div>
          {mockDishes.map((d) => (
            <div key={d.name} style={listItem}>
              <span>{d.name}</span>
              <span style={{ color: '#8899A6' }}>{d.category}</span>
              <span>{d.price}</span>
              <span style={{ color: '#66BB6A' }}>{d.margin}</span>
            </div>
          ))}
        </div>

        {/* 分类管理 */}
        <div style={cardStyle}>
          <div style={cardTitle}>菜品分类</div>
          {mockCategories.map((c) => (
            <div key={c.name} style={listItem}>
              <span>{c.name}</span>
              <span>{c.count} 道</span>
              <span style={{ color: c.status === '已上架' ? '#66BB6A' : '#FFA726' }}>{c.status}</span>
            </div>
          ))}
        </div>

        {/* 销量排名 */}
        <div style={cardStyle}>
          <div style={cardTitle}>本周销量排名</div>
          {mockRanking.map((r) => (
            <div key={r.rank} style={listItem}>
              <span style={{ color: '#4FC3F7', fontWeight: 600 }}>#{r.rank}</span>
              <span>{r.name}</span>
              <span>{r.sales} 份</span>
              <span style={{ color: r.trend.startsWith('+') ? '#66BB6A' : '#EF5350' }}>{r.trend}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
