/**
 * 桌台状态视图（服务员视角）
 */
import { useNavigate } from 'react-router-dom';

const TABLES = [
  { no: 'A01', seats: 4, status: 'occupied', guests: 3, orderTime: '14:25', amount: 16800, orderId: 'ord_001' },
  { no: 'A02', seats: 4, status: 'free', guests: 0, orderTime: '', amount: 0, orderId: '' },
  { no: 'A03', seats: 6, status: 'occupied', guests: 5, orderTime: '14:10', amount: 28500, orderId: 'ord_002' },
  { no: 'B01', seats: 8, status: 'occupied', guests: 8, orderTime: '13:45', amount: 52000, orderId: 'ord_003' },
  { no: 'B02', seats: 10, status: 'free', guests: 0, orderTime: '', amount: 0, orderId: '' },
];

const colors: Record<string, string> = { free: '#52c41a', occupied: '#FF6B2C', reserved: '#faad14' };

export function TablesView() {
  const navigate = useNavigate();

  const handleTableTap = (t: typeof TABLES[0]) => {
    if (t.status === 'occupied') {
      navigate(`/table-detail?table=${t.no}&order_id=${t.orderId}`);
    } else {
      navigate(`/open-table?table=${t.no}`);
    }
  };

  const parseScanResult = (raw: string) => {
    let tableNo = '';
    if (raw.startsWith('txos://table/')) {
      const parts = raw.split('/');
      tableNo = parts[parts.length - 1];
    } else if (/^[A-Za-z0-9]{2,6}$/.test(raw.trim())) {
      tableNo = raw.trim().toUpperCase();
    }

    if (!tableNo) {
      return;
    }

    navigate(`/open-table?table=${encodeURIComponent(tableNo)}&prefilled=true`);
  };

  const handleScanQR = () => {
    if ((window as any).TXBridge) {
      (window as any).TXBridge.scan();
      (window as any).TXBridge.onScanResult = (result: string) => {
        parseScanResult(result);
      };
    } else {
      const mock = prompt('开发模式 - 输入桌台号（如 A01）:');
      if (mock) parseScanResult(`txos://table/store_001/${mock.trim().toUpperCase()}`);
    }
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>桌台状态</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => navigate('/table-map')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              minHeight: 48,
              padding: '0 16px',
              background: 'transparent',
              border: '1.5px solid #FF6B35',
              borderRadius: 8,
              color: '#FF6B35',
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            🗺️ 地图视图
          </button>
          <button
            onClick={handleScanQR}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              minHeight: 48,
              padding: '0 16px',
              background: '#FF6B35',
              border: 'none',
              borderRadius: 8,
              color: '#ffffff',
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            📷 扫码开台
          </button>
        </div>
      </div>
      {TABLES.map(t => (
        <div
          key={t.no}
          onClick={() => handleTableTap(t)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: 14, marginBottom: 8, borderRadius: 8, background: '#112228',
            borderLeft: `4px solid ${colors[t.status]}`,
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
            activeOpacity: 0.7,
          }}
        >
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
            <span style={{ color: '#52c41a', fontSize: 14 }}>空闲 &gt;</span>
          )}
        </div>
      ))}
    </div>
  );
}
