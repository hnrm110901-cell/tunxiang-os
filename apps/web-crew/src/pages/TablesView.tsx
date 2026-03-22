/**
 * 桌台状态视图（服务员视角）
 */
const TABLES = [
  { no: 'A01', seats: 4, status: 'occupied', guests: 3, orderTime: '14:25', amount: 16800 },
  { no: 'A02', seats: 4, status: 'free', guests: 0, orderTime: '', amount: 0 },
  { no: 'A03', seats: 6, status: 'occupied', guests: 5, orderTime: '14:10', amount: 28500 },
  { no: 'B01', seats: 8, status: 'occupied', guests: 8, orderTime: '13:45', amount: 52000 },
  { no: 'B02', seats: 10, status: 'free', guests: 0, orderTime: '', amount: 0 },
];

const colors: Record<string, string> = { free: '#52c41a', occupied: '#FF6B2C', reserved: '#faad14' };

export function TablesView() {
  return (
    <div style={{ padding: 16 }}>
      <h3 style={{ margin: '0 0 12px' }}>桌台状态</h3>
      {TABLES.map(t => (
        <div key={t.no} style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: 14, marginBottom: 8, borderRadius: 8, background: '#112228',
          borderLeft: `4px solid ${colors[t.status]}`,
        }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 'bold' }}>{t.no}</div>
            <div style={{ fontSize: 12, color: '#666' }}>{t.seats}人桌</div>
          </div>
          {t.status === 'occupied' ? (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 14 }}>{t.guests}人 · {t.orderTime}</div>
              <div style={{ fontSize: 16, color: '#FF6B2C', fontWeight: 'bold' }}>¥{(t.amount / 100).toFixed(0)}</div>
            </div>
          ) : (
            <span style={{ color: '#52c41a', fontSize: 14 }}>空闲</span>
          )}
        </div>
      ))}
    </div>
  );
}
