/**
 * 开台点单页 — 三栏布局（蓝图 P0 核心页面）
 * 左：分类导航 | 中：菜品网格 | 右：购物车
 * 决策7指标：收银员3次点击内完成
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { WineStorageQuickView } from '../components/WineStorageQuickView';

const CATEGORIES = ['推荐', '招牌菜', '热菜', '凉菜', '汤羹', '主食', '饮品'];

const DISH_DATA: Record<string, { id: string; name: string; price: number; tags?: string[] }[]> = {
  '推荐': [
    { id: 'd1', name: '剁椒鱼头', price: 88, tags: ['招牌'] },
    { id: 'd4', name: '口味虾', price: 128, tags: ['招牌'] },
    { id: 'd2', name: '农家小炒肉', price: 42 },
  ],
  '招牌菜': [
    { id: 'd1', name: '剁椒鱼头', price: 88 },
    { id: 'd4', name: '口味虾', price: 128 },
    { id: 'd3', name: '毛氏红烧肉', price: 68 },
    { id: 'd11', name: '臭豆腐', price: 28 },
  ],
  '热菜': [
    { id: 'd2', name: '农家小炒肉', price: 42 },
    { id: 'd5', name: '辣椒炒肉', price: 38 },
    { id: 'd6', name: '红烧茄子', price: 28 },
    { id: 'd7', name: '干锅花菜', price: 32 },
    { id: 'd8', name: '外婆菜炒蛋', price: 26 },
    { id: 'd9', name: '湘西外婆鸡', price: 58 },
  ],
  '凉菜': [
    { id: 'd10', name: '凉拌黄瓜', price: 9 },
    { id: 'd12', name: '皮蛋豆腐', price: 12 },
    { id: 'd13', name: '口水鸡', price: 28 },
  ],
  '主食': [
    { id: 'd14', name: '米饭', price: 3 },
    { id: 'd15', name: '蛋炒饭', price: 18 },
    { id: 'd16', name: '长沙米粉', price: 15 },
  ],
  '饮品': [
    { id: 'd17', name: '酸梅汤', price: 8 },
    { id: 'd18', name: '鲜榨橙汁', price: 15 },
  ],
};

export function OpenTablePage() {
  // tableNo = 台位展示编号（如 "A03"），tableId = 台位 UUID（用于存酒快查）
  const { tableNo, tableId } = useParams<{ tableNo?: string; tableId?: string }>();
  const navigate = useNavigate();
  const store = useOrderStore();
  const [activeCat, setActiveCat] = useState('推荐');
  const dishes = DISH_DATA[activeCat] || [];

  const handleAdd = (d: { id: string; name: string; price: number }) => {
    const existing = store.items.find(i => i.dishId === d.id);
    if (existing) {
      store.updateQuantity(existing.id, existing.quantity + 1);
    } else {
      store.addItem({ dishId: d.id, name: d.name, quantity: 1, priceFen: d.price * 100, notes: '', kitchenStation: 'default' });
    }
  };

  const total = store.totalFen;
  const itemCount = store.items.reduce((s, i) => s + i.quantity, 0);

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左栏：分类 */}
      <div style={{ width: 90, background: '#112228', paddingTop: 8, borderRight: '1px solid #1a2a33' }}>
        {CATEGORIES.map(cat => (
          <div key={cat} onClick={() => setActiveCat(cat)} style={{
            padding: '12px 8px', textAlign: 'center', fontSize: 13, cursor: 'pointer',
            background: activeCat === cat ? '#0B1A20' : 'transparent',
            color: activeCat === cat ? '#FF6B2C' : '#999',
            borderLeft: activeCat === cat ? '3px solid #FF6B2C' : '3px solid transparent',
          }}>
            {cat}
          </div>
        ))}
      </div>

      {/* 中栏：菜品网格 */}
      <div style={{ flex: 1, padding: 12, overflowY: 'auto' }}>
        {/* 存酒快查角标：若台位有存酒记录则显示橙色提示 */}
        {tableId && (
          <div style={{ marginBottom: 10 }}>
            <WineStorageQuickView
              tableId={tableId}
              tableName={tableNo || '本台'}
            />
          </div>
        )}
        <div style={{ fontSize: 11, color: '#666', marginBottom: 8 }}>
          桌号 {tableNo} · {activeCat} · {dishes.length} 道
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
          {dishes.map(d => (
            <div key={d.id} onClick={() => handleAdd(d)} style={{
              padding: 14, borderRadius: 8, background: '#112228', cursor: 'pointer',
              textAlign: 'center', position: 'relative',
            }}>
              {d.tags?.map(t => (
                <span key={t} style={{ position: 'absolute', top: 4, right: 4, fontSize: 9, padding: '1px 4px', borderRadius: 4, background: '#FF6B2C', color: '#fff' }}>{t}</span>
              ))}
              <div style={{ fontSize: 15, fontWeight: 'bold', marginBottom: 4 }}>{d.name}</div>
              <div style={{ color: '#FF6B2C', fontWeight: 'bold' }}>¥{d.price}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 右栏：购物车 */}
      <div style={{ width: 260, background: '#112228', padding: 12, display: 'flex', flexDirection: 'column', borderLeft: '1px solid #1a2a33' }}>
        <h4 style={{ margin: '0 0 8px', fontSize: 14 }}>已选 {itemCount} 件</h4>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {store.items.map(item => (
            <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: 13, borderBottom: '1px solid #1a2a33' }}>
              <span>{item.name}</span>
              <span style={{ color: '#FF6B2C' }}>×{item.quantity} ¥{(item.priceFen * item.quantity / 100).toFixed(0)}</span>
            </div>
          ))}
        </div>
        <div style={{ borderTop: '1px solid #333', paddingTop: 8, marginTop: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 18, fontWeight: 'bold', color: '#FF6B2C', marginBottom: 8 }}>
            <span>合计</span><span>¥{(total / 100).toFixed(0)}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate(`/tables`)} style={{ flex: 1, padding: 10, background: '#333', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>返回</button>
            <button onClick={() => navigate(`/settle/${store.orderId || 'temp'}`)} disabled={itemCount === 0}
              style={{ flex: 2, padding: 10, background: itemCount > 0 ? '#FF6B2C' : '#444', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 15 }}>
              下单结算
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
