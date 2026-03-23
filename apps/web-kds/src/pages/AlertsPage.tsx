/**
 * KDS 超时告警 — 实时超时订单 + 历史告警
 * 大字号设计，厨房友好
 */
import { useState } from 'react';

/* ---------- Types ---------- */
interface AlertItem {
  id: string;
  tableNo: string;
  orderNo: string;
  items: string[];
  elapsed: number; // 分钟
  stall: string;
  chef: string;
  createdAt: string;
  resolved: boolean;
  resolvedAt?: string;
}

/* ---------- Mock Data ---------- */
const mockAlerts: AlertItem[] = [
  { id: '1', tableNo: 'A05', orderNo: '005', items: ['剁椒鱼头', '口味虾'], elapsed: 42, stall: '热菜档口', chef: '王师傅', createdAt: '13:55', resolved: false },
  { id: '2', tableNo: 'B01', orderNo: '008', items: ['外婆鸡', '红烧肉'], elapsed: 35, stall: '蒸菜档口', chef: '张师傅', createdAt: '14:02', resolved: false },
  { id: '3', tableNo: 'A02', orderNo: '012', items: ['酸菜鱼'], elapsed: 31, stall: '热菜档口', chef: '李师傅', createdAt: '14:15', resolved: false },
  { id: '4', tableNo: 'A01', orderNo: '003', items: ['小炒肉', '米饭x3'], elapsed: 28, stall: '热菜档口', chef: '王师傅', createdAt: '11:30', resolved: true, resolvedAt: '12:05' },
  { id: '5', tableNo: 'B02', orderNo: '006', items: ['蒸鲈鱼'], elapsed: 33, stall: '蒸菜档口', chef: '张师傅', createdAt: '12:10', resolved: true, resolvedAt: '12:48' },
  { id: '6', tableNo: 'A03', orderNo: '009', items: ['口味虾x2', '凉拌黄瓜'], elapsed: 26, stall: '热菜档口', chef: '李师傅', createdAt: '13:00', resolved: true, resolvedAt: '13:30' },
];

/* ---------- Component ---------- */
export function AlertsPage() {
  const [alerts, setAlerts] = useState(mockAlerts);
  const [tab, setTab] = useState<'active' | 'history'>('active');

  const activeAlerts = alerts.filter(a => !a.resolved);
  const historyAlerts = alerts.filter(a => a.resolved);

  const handleResolve = (id: string) => {
    const now = new Date();
    const timeStr = `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`;
    setAlerts(prev => prev.map(a =>
      a.id === id ? { ...a, resolved: true, resolvedAt: timeStr } : a
    ));
  };

  const isRed = (elapsed: number) => elapsed >= 30;

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '10px 28px', cursor: 'pointer', fontSize: 18, fontWeight: 'bold',
    background: active ? '#ff4d4f' : '#1A3A48', color: active ? '#fff' : '#8899A6',
    border: 'none', borderRadius: 8,
  });

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: 'Noto Sans SC, sans-serif', padding: 16,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#fff' }}>
          超时告警
          {activeAlerts.length > 0 && (
            <span style={{
              display: 'inline-block', marginLeft: 12, fontSize: 18,
              padding: '2px 12px', borderRadius: 12, background: '#ff4d4f', color: '#fff',
            }}>
              {activeAlerts.length}
            </span>
          )}
        </h1>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button onClick={() => setTab('active')} style={tabStyle(tab === 'active')}>
          实时告警 ({activeAlerts.length})
        </button>
        <button onClick={() => setTab('history')} style={{
          ...tabStyle(tab === 'history'),
          background: tab === 'history' ? '#1890ff' : '#1A3A48',
        }}>
          历史记录 ({historyAlerts.length})
        </button>
      </div>

      {/* Active Alerts */}
      {tab === 'active' && (
        <div>
          {activeAlerts.length === 0 && (
            <div style={{ textAlign: 'center', padding: 60, color: '#52c41a', fontSize: 24 }}>
              当前无超时订单
            </div>
          )}
          {activeAlerts.map(alert => (
            <div key={alert.id} style={{
              background: isRed(alert.elapsed) ? '#2A0A0A' : '#112B36',
              border: isRed(alert.elapsed) ? '2px solid #ff4d4f' : '1px solid #1A3A48',
              borderRadius: 12, padding: 18, marginBottom: 10,
              animation: isRed(alert.elapsed) ? 'none' : undefined,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 32, fontWeight: 'bold', color: '#fff' }}>{alert.tableNo}</span>
                  <span style={{ fontSize: 16, color: '#666' }}>#{alert.orderNo}</span>
                  <span style={{
                    fontSize: 14, padding: '2px 10px', borderRadius: 4,
                    background: '#1A3A48', color: '#8899A6',
                  }}>
                    {alert.stall}
                  </span>
                </div>
                <div style={{
                  fontSize: 40, fontWeight: 'bold',
                  color: isRed(alert.elapsed) ? '#ff4d4f' : '#faad14',
                  fontFamily: 'JetBrains Mono, monospace',
                }}>
                  {alert.elapsed}'
                </div>
              </div>

              <div style={{ fontSize: 20, fontWeight: 'bold', marginBottom: 10 }}>
                {alert.items.join(' / ')}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 16, color: '#8899A6' }}>
                  {alert.chef} | 下单 {alert.createdAt}
                </span>
                <button onClick={() => handleResolve(alert.id)} style={{
                  padding: '10px 28px', background: '#52c41a', color: '#fff',
                  border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 18, fontWeight: 'bold',
                }}>
                  已处理
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* History */}
      {tab === 'history' && (
        <div>
          {historyAlerts.map(alert => (
            <div key={alert.id} style={{
              background: '#112B36', borderRadius: 10, padding: 14, marginBottom: 8,
              opacity: 0.7, borderLeft: '4px solid #666',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 22, fontWeight: 'bold', color: '#aaa' }}>{alert.tableNo}</span>
                  <span style={{ fontSize: 16 }}>{alert.items.join(' / ')}</span>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{
                    fontSize: 20, fontWeight: 'bold', color: '#faad14',
                    fontFamily: 'JetBrains Mono, monospace',
                  }}>
                    {alert.elapsed}'
                  </div>
                  <div style={{ fontSize: 12, color: '#666' }}>
                    {alert.stall} | {alert.chef} | 处理于 {alert.resolvedAt}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
