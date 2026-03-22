/**
 * KDS 出餐看板 — 三列布局（蓝图 P0）
 * 待制作 | 制作中 | 异常/超时
 *
 * 餐饮顾问建议：高对比配色，大字号，厨师手湿也能看清
 */
import { useState, useEffect } from 'react';

interface KDSTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  items: { name: string; qty: number; notes: string }[];
  createdAt: string;
  elapsed: number; // 分钟
  status: 'pending' | 'preparing' | 'abnormal';
  priority: 'normal' | 'rush' | 'vip';
}

const MOCK: KDSTicket[] = [
  { id: '1', orderNo: '001', tableNo: 'A01', items: [{ name: '剁椒鱼头', qty: 1, notes: '少辣' }, { name: '小炒肉', qty: 1, notes: '' }], createdAt: '14:25', elapsed: 8, status: 'pending', priority: 'normal' },
  { id: '2', orderNo: '002', tableNo: 'A03', items: [{ name: '口味虾', qty: 1, notes: '中辣' }], createdAt: '14:22', elapsed: 11, status: 'preparing', priority: 'rush' },
  { id: '3', orderNo: '003', tableNo: 'B01', items: [{ name: '鱼头', qty: 2, notes: '' }, { name: '米饭', qty: 6, notes: '' }], createdAt: '14:15', elapsed: 18, status: 'preparing', priority: 'vip' },
  { id: '4', orderNo: '004', tableNo: 'B02', items: [{ name: '外婆鸡', qty: 1, notes: '多放辣' }], createdAt: '14:28', elapsed: 5, status: 'pending', priority: 'normal' },
  { id: '5', orderNo: '005', tableNo: 'A05', items: [{ name: '凉拌黄瓜', qty: 2, notes: '' }], createdAt: '13:55', elapsed: 38, status: 'abnormal', priority: 'normal' },
];

const COL_STYLE = { flex: 1, display: 'flex' as const, flexDirection: 'column' as const, gap: 8, overflowY: 'auto' as const, padding: 8 };
const priorityBorder: Record<string, string> = { normal: '#333', rush: '#faad14', vip: '#722ed1' };

export default function App() {
  const [tickets, setTickets] = useState(MOCK);

  const move = (id: string, to: KDSTicket['status']) => {
    setTickets(prev => to === 'abnormal'
      ? prev.map(t => t.id === id ? { ...t, status: to } : t)
      : prev.filter(t => t.id !== id || to !== 'preparing').map(t => t.id === id ? { ...t, status: to } : t)
    );
  };

  const complete = (id: string) => setTickets(prev => prev.filter(t => t.id !== id));

  const pending = tickets.filter(t => t.status === 'pending');
  const preparing = tickets.filter(t => t.status === 'preparing');
  const abnormal = tickets.filter(t => t.status === 'abnormal');

  return (
    <div style={{ background: '#000', color: '#fff', height: '100vh', display: 'flex', flexDirection: 'column', fontFamily: 'Noto Sans SC, sans-serif' }}>
      {/* 顶部状态栏 */}
      <header style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 16px', background: '#111', fontSize: 16 }}>
        <span style={{ fontWeight: 'bold', fontSize: 20 }}>🔥 后厨看板</span>
        <div style={{ display: 'flex', gap: 24 }}>
          <span>待制作 <b style={{ color: '#faad14', fontSize: 24 }}>{pending.length}</b></span>
          <span>制作中 <b style={{ color: '#1890ff', fontSize: 24 }}>{preparing.length}</b></span>
          <span style={{ color: abnormal.length > 0 ? '#ff4d4f' : '#666' }}>异常 <b style={{ fontSize: 24 }}>{abnormal.length}</b></span>
        </div>
      </header>

      {/* 三列看板 */}
      <div style={{ flex: 1, display: 'flex', gap: 2, overflow: 'hidden' }}>
        {/* 待制作 */}
        <div style={{ ...COL_STYLE, background: '#1a1a00' }}>
          <div style={{ textAlign: 'center', padding: 4, fontSize: 14, fontWeight: 'bold', color: '#faad14', borderBottom: '2px solid #faad14' }}>
            待制作 ({pending.length})
          </div>
          {pending.map(t => <TicketCard key={t.id} t={t} onAction={() => move(t.id, 'preparing')} actionLabel="开始制作" actionColor="#1890ff" />)}
        </div>

        {/* 制作中 */}
        <div style={{ ...COL_STYLE, background: '#001a1a' }}>
          <div style={{ textAlign: 'center', padding: 4, fontSize: 14, fontWeight: 'bold', color: '#1890ff', borderBottom: '2px solid #1890ff' }}>
            制作中 ({preparing.length})
          </div>
          {preparing.map(t => <TicketCard key={t.id} t={t} onAction={() => complete(t.id)} actionLabel="出餐完成" actionColor="#52c41a" />)}
        </div>

        {/* 异常/超时 */}
        <div style={{ ...COL_STYLE, background: '#1a0000' }}>
          <div style={{ textAlign: 'center', padding: 4, fontSize: 14, fontWeight: 'bold', color: '#ff4d4f', borderBottom: '2px solid #ff4d4f' }}>
            异常 ({abnormal.length})
          </div>
          {abnormal.map(t => <TicketCard key={t.id} t={t} onAction={() => complete(t.id)} actionLabel="已处理" actionColor="#52c41a" isAbnormal />)}
        </div>
      </div>
    </div>
  );
}

function TicketCard({ t, onAction, actionLabel, actionColor, isAbnormal }: {
  t: KDSTicket; onAction: () => void; actionLabel: string; actionColor: string; isAbnormal?: boolean;
}) {
  const timeColor = t.elapsed >= 25 ? '#ff4d4f' : t.elapsed >= 15 ? '#faad14' : '#52c41a';

  return (
    <div style={{
      background: '#111', borderRadius: 8, padding: 12,
      borderLeft: `5px solid ${isAbnormal ? '#ff4d4f' : priorityBorder[t.priority]}`,
      animation: t.priority === 'rush' ? 'pulse 2s infinite' : undefined,
    }}>
      {/* 头部：桌号 + 时间 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <div>
          <span style={{ fontSize: 22, fontWeight: 'bold' }}>{t.tableNo}</span>
          <span style={{ fontSize: 11, color: '#666', marginLeft: 6 }}>#{t.orderNo}</span>
          {t.priority !== 'normal' && (
            <span style={{
              marginLeft: 6, fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: t.priority === 'rush' ? '#faad14' : '#722ed1', color: '#fff',
            }}>
              {t.priority === 'rush' ? '催' : 'VIP'}
            </span>
          )}
        </div>
        <div style={{ fontSize: 24, fontWeight: 'bold', color: timeColor, fontFamily: 'JetBrains Mono, monospace' }}>
          {t.elapsed}′
        </div>
      </div>

      {/* 菜品 */}
      {t.items.map((item, i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 18, fontWeight: 'bold' }}>
          <span>
            {item.name}
            {item.notes && <span style={{ fontSize: 12, color: '#ff4d4f', marginLeft: 4 }}>({item.notes})</span>}
          </span>
          <span style={{ color: '#FF6B2C' }}>×{item.qty}</span>
        </div>
      ))}

      {/* 操作按钮 */}
      <button onClick={onAction} style={{
        width: '100%', marginTop: 8, padding: 10, border: 'none', borderRadius: 6,
        background: actionColor, color: '#fff', fontSize: 16, fontWeight: 'bold', cursor: 'pointer',
      }}>
        {actionLabel}
      </button>
    </div>
  );
}
