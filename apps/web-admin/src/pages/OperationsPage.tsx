/**
 * OperationsPage — 日清日结
 * E1-E8 时间轴 + 巡航状态
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

const timelineItem: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  padding: '10px 0',
  borderBottom: '1px solid #1E3A47',
  fontSize: '13px',
};

const dot = (done: boolean): React.CSSProperties => ({
  width: '10px',
  height: '10px',
  borderRadius: '50%',
  backgroundColor: done ? '#66BB6A' : '#8899A6',
  flexShrink: 0,
});

const mockTimeline = [
  { code: 'E1', name: '早班交接', time: '08:30', done: true },
  { code: 'E2', name: '食材验收', time: '09:00', done: true },
  { code: 'E3', name: '开市准备', time: '10:30', done: true },
  { code: 'E4', name: '午高峰巡检', time: '12:00', done: true },
  { code: 'E5', name: '午低谷盘点', time: '14:30', done: false },
  { code: 'E6', name: '晚高峰巡检', time: '18:00', done: false },
  { code: 'E7', name: '闭市清洁', time: '21:30', done: false },
  { code: 'E8', name: '日结封账', time: '22:00', done: false },
];

const mockCruise = [
  { store: '长沙芙蓉店', status: '午高峰运行中', health: 92 },
  { store: '长沙梅溪湖店', status: '午低谷盘点中', health: 88 },
  { store: '株洲神农城店', status: '午高峰运行中', health: 95 },
];

export function OperationsPage() {
  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>日清日结</h1>
      <p style={subtitleStyle}>E1-E8 时间轴流程 / 门店巡航状态</p>

      <div style={gridStyle}>
        {/* 时间轴 */}
        <div style={{ ...cardStyle, gridColumn: 'span 1' }}>
          <div style={cardTitle}>今日流程时间轴</div>
          {mockTimeline.map((t) => (
            <div key={t.code} style={timelineItem}>
              <div style={dot(t.done)} />
              <span style={{ color: '#4FC3F7', fontWeight: 600, width: '28px' }}>{t.code}</span>
              <span style={{ flex: 1 }}>{t.name}</span>
              <span style={{ color: '#8899A6' }}>{t.time}</span>
              <span style={{ color: t.done ? '#66BB6A' : '#8899A6', fontSize: '12px' }}>
                {t.done ? '已完成' : '待执行'}
              </span>
            </div>
          ))}
        </div>

        {/* 巡航状态 */}
        <div style={cardStyle}>
          <div style={cardTitle}>门店巡航状态</div>
          {mockCruise.map((c) => (
            <div key={c.store} style={{ ...timelineItem, flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                <span style={{ fontWeight: 600 }}>{c.store}</span>
                <span style={{ color: c.health >= 90 ? '#66BB6A' : '#FFA726' }}>健康度 {c.health}%</span>
              </div>
              <span style={{ color: '#8899A6', fontSize: '12px' }}>{c.status}</span>
              <div style={{ width: '100%', height: '4px', backgroundColor: '#1E3A47', borderRadius: '2px' }}>
                <div style={{ width: `${c.health}%`, height: '100%', backgroundColor: c.health >= 90 ? '#66BB6A' : '#FFA726', borderRadius: '2px' }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
