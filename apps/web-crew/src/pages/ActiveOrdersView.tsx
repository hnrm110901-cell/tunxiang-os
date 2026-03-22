/**
 * 进行中订单 — 催菜/加菜入口
 */

const ACTIVE_ORDERS = [
  { id: '1', tableNo: 'A01', items: 3, elapsed: 12, status: 'preparing', total: 168 },
  { id: '2', tableNo: 'A03', elapsed: 25, items: 5, status: 'preparing', total: 285 },
  { id: '3', tableNo: 'B01', elapsed: 35, items: 8, status: 'pending', total: 520 },
];

export function ActiveOrdersView() {
  const handleRush = (tableNo: string) => alert(`已催菜：${tableNo}`);
  const handleAddDish = (tableNo: string) => alert(`跳转加菜：${tableNo}`);

  return (
    <div style={{ padding: 16 }}>
      <h3 style={{ margin: '0 0 12px' }}>进行中订单</h3>
      {ACTIVE_ORDERS.map(o => (
        <div key={o.id} style={{
          padding: 14, marginBottom: 8, borderRadius: 8, background: '#112228',
          borderLeft: `4px solid ${o.elapsed > 20 ? '#ff4d4f' : o.elapsed > 12 ? '#faad14' : '#52c41a'}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 18, fontWeight: 'bold' }}>{o.tableNo}</span>
            <span style={{ color: o.elapsed > 20 ? '#ff4d4f' : '#999' }}>{o.elapsed}分钟</span>
          </div>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>
            {o.items} 道菜 · ¥{o.total}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => handleRush(o.tableNo)}
              style={{ flex: 1, padding: 8, background: '#ff4d4f33', color: '#ff4d4f', border: '1px solid #ff4d4f', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
              催菜
            </button>
            <button onClick={() => handleAddDish(o.tableNo)}
              style={{ flex: 1, padding: 8, background: '#1890ff33', color: '#1890ff', border: '1px solid #1890ff', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
              加菜
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
