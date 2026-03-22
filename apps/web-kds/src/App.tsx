/**
 * KDS 出餐屏 — 后厨核心交互
 * 大屏展示待出餐订单，点击确认出餐
 */
import { useState, useEffect } from 'react';

interface KDSOrder {
  id: string;
  orderNo: string;
  tableNo: string;
  items: { name: string; quantity: number; notes: string }[];
  createdAt: string;
  elapsedMinutes: number;
  status: 'pending' | 'preparing' | 'ready';
}

// Mock 数据（接入 WebSocket 后替换）
const MOCK_ORDERS: KDSOrder[] = [
  {
    id: '1', orderNo: 'TX001', tableNo: 'A01',
    items: [{ name: '剁椒鱼头', quantity: 1, notes: '少辣' }, { name: '农家小炒肉', quantity: 1, notes: '' }],
    createdAt: '14:25', elapsedMinutes: 8, status: 'preparing',
  },
  {
    id: '2', orderNo: 'TX002', tableNo: 'A03',
    items: [{ name: '口味虾', quantity: 1, notes: '中辣' }, { name: '凉拌黄瓜', quantity: 2, notes: '' }],
    createdAt: '14:28', elapsedMinutes: 5, status: 'pending',
  },
  {
    id: '3', orderNo: 'TX003', tableNo: 'B01',
    items: [{ name: '剁椒鱼头', quantity: 2, notes: '' }, { name: '口味虾', quantity: 1, notes: '微辣' }, { name: '米饭', quantity: 6, notes: '' }],
    createdAt: '14:30', elapsedMinutes: 3, status: 'pending',
  },
  {
    id: '4', orderNo: 'TX004', tableNo: 'B02',
    items: [{ name: '农家小炒肉', quantity: 2, notes: '多放辣椒' }],
    createdAt: '14:32', elapsedMinutes: 1, status: 'pending',
  },
];

const statusColor = { pending: '#faad14', preparing: '#1890ff', ready: '#52c41a' };
const statusLabel = { pending: '待制作', preparing: '制作中', ready: '可出餐' };

function timeColor(minutes: number): string {
  if (minutes >= 20) return '#ff4d4f';
  if (minutes >= 12) return '#faad14';
  return '#52c41a';
}

export default function App() {
  const [orders, setOrders] = useState(MOCK_ORDERS);
  const [now, setNow] = useState(Date.now());

  // 每分钟刷新时间
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(timer);
  }, []);

  const handleStatusChange = (id: string, newStatus: KDSOrder['status']) => {
    setOrders((prev) =>
      prev.map((o) => (o.id === id ? { ...o, status: newStatus } : o))
        .filter((o) => !(o.id === id && newStatus === 'ready'))
    );
  };

  const pendingCount = orders.filter((o) => o.status === 'pending').length;
  const preparingCount = orders.filter((o) => o.status === 'preparing').length;

  return (
    <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#fff', padding: 16 }}>
      {/* 顶部状态栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, padding: '0 8px' }}>
        <h2 style={{ margin: 0, fontSize: 24 }}>后厨出餐屏</h2>
        <div style={{ display: 'flex', gap: 24, fontSize: 16 }}>
          <span>待制作 <strong style={{ color: '#faad14' }}>{pendingCount}</strong></span>
          <span>制作中 <strong style={{ color: '#1890ff' }}>{preparingCount}</strong></span>
          <span>总计 <strong>{orders.length}</strong></span>
        </div>
      </div>

      {/* 订单卡片网格 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
        {orders.map((order) => (
          <div key={order.id} style={{
            background: '#112228',
            borderRadius: 8,
            borderLeft: `4px solid ${statusColor[order.status]}`,
            padding: 16,
            display: 'flex',
            flexDirection: 'column',
          }}>
            {/* 头部 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <div>
                <span style={{ fontSize: 20, fontWeight: 'bold' }}>{order.tableNo}</span>
                <span style={{ fontSize: 12, color: '#666', marginLeft: 8 }}>{order.orderNo}</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 20, fontWeight: 'bold', color: timeColor(order.elapsedMinutes) }}>
                  {order.elapsedMinutes}分
                </div>
                <div style={{ fontSize: 10, color: '#666' }}>{order.createdAt}</div>
              </div>
            </div>

            {/* 菜品列表 */}
            <div style={{ flex: 1, marginBottom: 12 }}>
              {order.items.map((item, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #1a2a33' }}>
                  <span style={{ fontSize: 16, fontWeight: 'bold' }}>
                    {item.name}
                    {item.notes && <span style={{ fontSize: 11, color: '#ff4d4f', marginLeft: 4 }}>({item.notes})</span>}
                  </span>
                  <span style={{ fontSize: 18, fontWeight: 'bold', color: '#FF6B2C' }}>×{item.quantity}</span>
                </div>
              ))}
            </div>

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 8 }}>
              {order.status === 'pending' && (
                <button onClick={() => handleStatusChange(order.id, 'preparing')}
                  style={{ flex: 1, padding: 10, background: '#1890ff', color: '#fff', border: 'none', borderRadius: 6, fontSize: 14, cursor: 'pointer' }}>
                  开始制作
                </button>
              )}
              {order.status === 'preparing' && (
                <button onClick={() => handleStatusChange(order.id, 'ready')}
                  style={{ flex: 1, padding: 10, background: '#52c41a', color: '#fff', border: 'none', borderRadius: 6, fontSize: 14, cursor: 'pointer' }}>
                  出餐完成
                </button>
              )}
            </div>
          </div>
        ))}

        {orders.length === 0 && (
          <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: 80, color: '#666' }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>✓</div>
            <div style={{ fontSize: 20 }}>所有订单已出餐</div>
          </div>
        )}
      </div>
    </div>
  );
}
