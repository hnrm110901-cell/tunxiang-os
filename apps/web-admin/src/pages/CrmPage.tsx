/**
 * CrmPage — 客户经营
 * 会员列表 + RFM 分层 + 营销活动 + 客户旅程
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

const mockMembers = [
  { name: '张先生', phone: '138****8821', rfm: '高价值', visits: 32, spent: '¥8,640' },
  { name: '李女士', phone: '159****3302', rfm: '待唤醒', visits: 3, spent: '¥420' },
  { name: '王总', phone: '186****7710', rfm: '忠诚客', visits: 56, spent: '¥15,200' },
];

const mockCampaigns = [
  { name: '春季新品尝鲜券', type: '优惠券', reach: 1280, convert: '8.2%' },
  { name: '老客回馈 88 折', type: '折扣活动', reach: 640, convert: '12.5%' },
];

const mockRfm = [
  { segment: '高价值客户', count: 320, pct: '12%', color: '#66BB6A' },
  { segment: '忠诚客户', count: 580, pct: '22%', color: '#4FC3F7' },
  { segment: '新客户', count: 460, pct: '17%', color: '#FFA726' },
  { segment: '待唤醒客户', count: 1280, pct: '49%', color: '#EF5350' },
];

export function CrmPage() {
  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>客户经营</h1>
      <p style={subtitleStyle}>会员列表 / RFM 分层 / 营销活动 / 客户旅程</p>

      <div style={gridStyle}>
        {/* 会员列表 */}
        <div style={cardStyle}>
          <div style={cardTitle}>会员列表</div>
          {mockMembers.map((m) => (
            <div key={m.phone} style={listItem}>
              <span>{m.name}</span>
              <span style={{ color: '#8899A6' }}>{m.phone}</span>
              <span style={tagStyle(m.rfm === '高价值' ? '#66BB6A' : m.rfm === '忠诚客' ? '#4FC3F7' : '#EF5350')}>
                {m.rfm}
              </span>
              <span>{m.spent}</span>
            </div>
          ))}
        </div>

        {/* RFM 分层 */}
        <div style={cardStyle}>
          <div style={cardTitle}>RFM 客户分层</div>
          {mockRfm.map((r) => (
            <div key={r.segment} style={{ ...listItem, alignItems: 'center' }}>
              <span>{r.segment}</span>
              <span>{r.count} 人</span>
              <div style={{ width: '80px', height: '6px', backgroundColor: '#1E3A47', borderRadius: '3px' }}>
                <div style={{ width: r.pct, height: '100%', backgroundColor: r.color, borderRadius: '3px' }} />
              </div>
              <span style={{ color: r.color }}>{r.pct}</span>
            </div>
          ))}
        </div>

        {/* 营销活动 */}
        <div style={cardStyle}>
          <div style={cardTitle}>进行中的营销活动</div>
          {mockCampaigns.map((c) => (
            <div key={c.name} style={{ ...listItem, flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                <span style={{ fontWeight: 600 }}>{c.name}</span>
                <span style={tagStyle('#4FC3F7')}>{c.type}</span>
              </div>
              <div style={{ display: 'flex', gap: '16px', color: '#8899A6', fontSize: '12px' }}>
                <span>触达 {c.reach} 人</span>
                <span>转化率 <span style={{ color: '#66BB6A' }}>{c.convert}</span></span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
