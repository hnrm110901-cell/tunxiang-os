/**
 * 收银/点餐页面 — 对接 tx-trade API
 * 左侧菜品列表 + 右侧购物车
 */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { createOrder, addItem as apiAddItem } from '../api/tradeApi';

const MOCK_DISHES = [
  { id: 'd1', name: '剁椒鱼头', priceFen: 8800, category: '热菜', station: '热菜档' },
  { id: 'd2', name: '农家小炒肉', priceFen: 4200, category: '热菜', station: '热菜档' },
  { id: 'd3', name: '凉拌黄瓜', priceFen: 900, category: '凉菜', station: '凉菜档' },
  { id: 'd4', name: '口味虾', priceFen: 12800, category: '热菜', station: '热菜档' },
  { id: 'd5', name: '米饭', priceFen: 300, category: '主食', station: 'default' },
  { id: 'd6', name: '酸梅汤', priceFen: 800, category: '饮品', station: 'default' },
];

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const STORE_ID = import.meta.env.VITE_STORE_ID || '11111111-1111-1111-1111-111111111111';

export function CashierPage() {
  const { tableNo } = useParams();
  const navigate = useNavigate();
  const store = useOrderStore();
  const { items, totalFen, discountFen, orderId } = store;
  const finalFen = totalFen - discountFen;
  const [loading, setLoading] = useState(false);

  // 页面加载时自动开单（调用 tx-trade API）
  useEffect(() => {
    if (!orderId && tableNo) {
      setLoading(true);
      createOrder(STORE_ID, tableNo)
        .then((res) => store.setOrder(res.order_id, res.order_no, tableNo))
        .catch((e) => console.error('开单失败(离线模式):', e))
        .finally(() => setLoading(false));
    }
  }, []);

  const handleAddDish = async (dish: typeof MOCK_DISHES[0]) => {
    const existing = items.find((i) => i.dishId === dish.id);
    if (existing) {
      store.updateQuantity(existing.id, existing.quantity + 1);
    } else {
      store.addItem({ dishId: dish.id, name: dish.name, quantity: 1, priceFen: dish.priceFen, notes: '', kitchenStation: dish.station });
    }

    // 同步到后端（失败不阻断前端操作）
    if (orderId) {
      apiAddItem(orderId, dish.id, dish.name, 1, dish.priceFen).catch(() => {});
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 菜品 */}
      <div style={{ flex: 1, padding: 16, overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>桌号: {tableNo}</h3>
          {loading && <span style={{ color: '#faad14', fontSize: 12 }}>开单中...</span>}
          {store.orderNo && <span style={{ color: '#52c41a', fontSize: 12 }}>{store.orderNo}</span>}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {MOCK_DISHES.map((d) => (
            <div key={d.id} onClick={() => handleAddDish(d)}
              style={{ padding: 12, borderRadius: 8, background: '#1a2a33', cursor: 'pointer', textAlign: 'center' }}>
              <div style={{ fontWeight: 'bold' }}>{d.name}</div>
              <div style={{ color: '#FF6B2C', fontSize: 14 }}>{fen2yuan(d.priceFen)}</div>
              <div style={{ fontSize: 11, color: '#666' }}>{d.category}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 右侧 — 购物车 */}
      <div style={{ width: 320, background: '#112228', padding: 16, display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ margin: '0 0 12px' }}>当前订单</h3>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {items.length === 0 && <div style={{ color: '#666', textAlign: 'center', marginTop: 40 }}>点击菜品加入订单</div>}
          {items.map((item) => (
            <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #1a2a33' }}>
              <div>
                <div>{item.name}</div>
                <div style={{ fontSize: 12, color: '#999' }}>{fen2yuan(item.priceFen)} × {item.quantity}</div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button onClick={() => item.quantity > 1 ? store.updateQuantity(item.id, item.quantity - 1) : store.removeItem(item.id)} style={btnStyle}>-</button>
                <span>{item.quantity}</span>
                <button onClick={() => store.updateQuantity(item.id, item.quantity + 1)} style={btnStyle}>+</button>
              </div>
            </div>
          ))}
        </div>

        <div style={{ borderTop: '1px solid #333', paddingTop: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 20, fontWeight: 'bold', color: '#FF6B2C' }}>
            <span>应付</span><span>{fen2yuan(finalFen)}</span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={() => { store.clear(); navigate('/tables'); }} style={{ ...actionBtn, background: '#333' }}>返回</button>
          <button
            onClick={() => items.length > 0 && navigate(`/settle/${orderId || 'temp'}`)}
            disabled={items.length === 0}
            style={{ ...actionBtn, background: items.length > 0 ? '#FF6B2C' : '#444' }}>
            结算
          </button>
        </div>
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = { width: 28, height: 28, border: 'none', borderRadius: 4, background: '#333', color: '#fff', cursor: 'pointer', fontSize: 16 };
const actionBtn: React.CSSProperties = { flex: 1, padding: 12, border: 'none', borderRadius: 8, color: '#fff', fontSize: 16, cursor: 'pointer' };
