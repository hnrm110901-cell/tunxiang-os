/**
 * 快速点餐视图 — 服务员扫码/手动选桌后点菜
 */
import { useState } from 'react';

const DISHES = [
  { id: '1', name: '剁椒鱼头', price: 88, cat: '热菜' },
  { id: '2', name: '小炒肉', price: 42, cat: '热菜' },
  { id: '3', name: '凉拌黄瓜', price: 9, cat: '凉菜' },
  { id: '4', name: '口味虾', price: 128, cat: '热菜' },
  { id: '5', name: '米饭', price: 3, cat: '主食' },
  { id: '6', name: '酸梅汤', price: 8, cat: '饮品' },
];

interface CartItem { id: string; name: string; qty: number; price: number }

export function QuickOrderView() {
  const [cart, setCart] = useState<CartItem[]>([]);
  const [tableNo, setTableNo] = useState('');

  const addToCart = (d: typeof DISHES[0]) => {
    setCart(prev => {
      const existing = prev.find(i => i.id === d.id);
      if (existing) return prev.map(i => i.id === d.id ? { ...i, qty: i.qty + 1 } : i);
      return [...prev, { id: d.id, name: d.name, qty: 1, price: d.price }];
    });
  };

  const total = cart.reduce((s, i) => s + i.price * i.qty, 0);

  return (
    <div style={{ padding: 16 }}>
      {/* 桌号选择 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input placeholder="输入桌号" value={tableNo} onChange={e => setTableNo(e.target.value)}
          style={{ flex: 1, padding: 10, background: '#112228', border: '1px solid #333', borderRadius: 6, color: '#fff', fontSize: 16 }} />
        <button style={{ padding: '10px 16px', background: '#333', color: '#fff', border: 'none', borderRadius: 6 }}>
          扫码
        </button>
      </div>

      {/* 菜品 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {DISHES.map(d => (
          <button key={d.id} onClick={() => addToCart(d)}
            style={{ padding: 12, background: '#112228', border: 'none', borderRadius: 8, color: '#fff', textAlign: 'left', cursor: 'pointer' }}>
            <div style={{ fontWeight: 'bold' }}>{d.name}</div>
            <div style={{ color: '#FF6B2C', fontSize: 14 }}>¥{d.price}</div>
          </button>
        ))}
      </div>

      {/* 购物车摘要 */}
      {cart.length > 0 && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 12 }}>
          {cart.map(i => (
            <div key={i.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 14 }}>
              <span>{i.name} ×{i.qty}</span>
              <span style={{ color: '#FF6B2C' }}>¥{i.price * i.qty}</span>
            </div>
          ))}
          <div style={{ borderTop: '1px solid #333', marginTop: 8, paddingTop: 8, display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontWeight: 'bold' }}>合计</span>
            <span style={{ fontWeight: 'bold', color: '#FF6B2C', fontSize: 18 }}>¥{total}</span>
          </div>
          <button onClick={() => { alert(`已下单到 ${tableNo || '未指定桌号'}`); setCart([]); }}
            style={{ width: '100%', marginTop: 8, padding: 12, background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer' }}>
            下单
          </button>
        </div>
      )}
    </div>
  );
}
