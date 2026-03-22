/**
 * 桌台图页面 — POS 首页
 * 显示所有桌台状态，点击开单
 */
import { useNavigate } from 'react-router-dom';

const MOCK_TABLES = [
  { no: 'A01', seats: 4, status: 'free', area: '大厅' },
  { no: 'A02', seats: 4, status: 'occupied', area: '大厅' },
  { no: 'A03', seats: 6, status: 'free', area: '大厅' },
  { no: 'B01', seats: 8, status: 'reserved', area: '包间' },
  { no: 'B02', seats: 10, status: 'free', area: '包间' },
  { no: 'B03', seats: 12, status: 'occupied', area: '包间' },
];

const statusColor: Record<string, string> = {
  free: '#52c41a',
  occupied: '#ff4d4f',
  reserved: '#faad14',
  cleaning: '#1890ff',
};

export function TableMapPage() {
  const navigate = useNavigate();

  return (
    <div style={{ padding: 16, background: '#0B1A20', minHeight: '100vh', color: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>桌台总览</h2>
        <button
          onClick={() => navigate('/shift')}
          style={{ padding: '8px 16px', background: '#333', color: '#fff', border: 'none', borderRadius: 4 }}
        >
          交接班
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {Object.entries(statusColor).map(([s, c]) => (
          <span key={s} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: c, display: 'inline-block' }} />
            {s === 'free' ? '空闲' : s === 'occupied' ? '在用' : s === 'reserved' ? '已订' : '清理中'}
          </span>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
        {MOCK_TABLES.map((t) => (
          <div
            key={t.no}
            onClick={() => t.status === 'free' && navigate(`/cashier/${t.no}`)}
            style={{
              padding: 16,
              borderRadius: 8,
              background: '#1a2a33',
              border: `2px solid ${statusColor[t.status]}`,
              cursor: t.status === 'free' ? 'pointer' : 'default',
              opacity: t.status === 'free' ? 1 : 0.6,
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: 24, fontWeight: 'bold' }}>{t.no}</div>
            <div style={{ fontSize: 12, color: '#999' }}>{t.area} · {t.seats}人</div>
            <div style={{ fontSize: 12, color: statusColor[t.status], marginTop: 4 }}>
              {t.status === 'free' ? '空闲' : t.status === 'occupied' ? '在用' : '已订'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
