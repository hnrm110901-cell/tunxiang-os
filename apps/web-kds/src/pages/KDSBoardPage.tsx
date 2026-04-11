/**
 * KDS 出餐看板 — 三列布局（蓝图 P0）
 * 待制作 | 制作中 | 异常/超时
 *
 * 保留兼容旧版路由 /board-legacy
 * 已迁移至 TXTouch 字体规范（KDS 标题≥24px，倒计时32px，菜品20px）
 */
import { useState } from 'react';
import { TXKDSTicket, type TXKDSTicketItem } from '@tx/touch/components/TXKDSTicket';

// KDS_TIMEOUT_MINUTES：旧版看板固定 25 分钟上限
const KDS_TIMEOUT_MINUTES = 25;
const now = Date.now();
const min = (m: number) => m * 60 * 1000;

interface LegacyTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  items: TXKDSTicketItem[];
  createdAt: Date;
  status: 'pending' | 'preparing' | 'abnormal';
  isVip: boolean;
}

const MOCK: LegacyTicket[] = [
  {
    id: '1', orderNo: '001', tableNo: 'A01', status: 'pending', isVip: false,
    createdAt: new Date(now - min(8)),
    items: [{ name: '剁椒鱼头', qty: 1, spec: '少辣', priority: 'normal' }, { name: '小炒肉', qty: 1, priority: 'normal' }],
  },
  {
    id: '2', orderNo: '002', tableNo: 'A03', status: 'preparing', isVip: false,
    createdAt: new Date(now - min(11)),
    items: [{ name: '口味虾', qty: 1, spec: '中辣', priority: 'rush' }],
  },
  {
    id: '3', orderNo: '003', tableNo: 'B01', status: 'preparing', isVip: true,
    createdAt: new Date(now - min(18)),
    items: [{ name: '鱼头', qty: 2, priority: 'normal' }, { name: '米饭', qty: 6, priority: 'normal' }],
  },
  {
    id: '4', orderNo: '004', tableNo: 'B02', status: 'pending', isVip: false,
    createdAt: new Date(now - min(5)),
    items: [{ name: '外婆鸡', qty: 1, spec: '多放辣', priority: 'normal' }],
  },
  {
    id: '5', orderNo: '005', tableNo: 'A05', status: 'abnormal', isVip: false,
    createdAt: new Date(now - min(38)),
    items: [{ name: '凉拌黄瓜', qty: 2, priority: 'normal' }],
  },
];

const COL_STYLE = {
  flex: 1, display: 'flex' as const, flexDirection: 'column' as const,
  gap: 12, overflowY: 'auto' as const, padding: 12,
  WebkitOverflowScrolling: 'touch' as const,
};

export function KDSBoardPage() {
  const [tickets, setTickets] = useState(MOCK);

  const move = (id: string, to: LegacyTicket['status']) => {
    setTickets(prev =>
      prev.map(t => t.id === id ? { ...t, status: to } : t)
    );
  };

  const complete = (id: string) => setTickets(prev => prev.filter(t => t.id !== id));

  const pending = tickets.filter(t => t.status === 'pending');
  const preparing = tickets.filter(t => t.status === 'preparing');
  const abnormal = tickets.filter(t => t.status === 'abnormal');

  return (
    <div style={{
      background: '#0A0A0A', color: '#E0E0E0', height: '100vh',
      display: 'flex', flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
    }}>
      {/* 顶栏 — KDS标题≥24px，计数≥28px */}
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 20px', background: '#111', borderBottom: '1px solid #222', minHeight: 56,
      }}>
        <span style={{ fontWeight: 'bold', fontSize: 24, color: '#FF6B35' }}>后厨看板（旧版）</span>
        <div style={{ display: 'flex', gap: 32, fontSize: 18 }}>
          <span>待制作 <b style={{ color: '#BA7517', fontSize: 28 }}>{pending.length}</b></span>
          <span>制作中 <b style={{ color: '#4A9EFF', fontSize: 28 }}>{preparing.length}</b></span>
          <span style={{ color: abnormal.length > 0 ? '#A32D2D' : '#555' }}>
            异常 <b style={{ fontSize: 28 }}>{abnormal.length}</b>
          </span>
        </div>
      </header>

      {/* 三列看板 */}
      <div style={{ flex: 1, display: 'flex', gap: 2, overflow: 'hidden' }}>
        {/* 待制作列 */}
        <div style={{ ...COL_STYLE, background: '#111500' }}>
          <div style={{
            textAlign: 'center', padding: '8px 0', fontSize: 20,
            fontWeight: 'bold', color: '#BA7517', borderBottom: '3px solid #BA7517',
          }}>
            待制作 ({pending.length})
          </div>
          {pending.map(t => (
            <TXKDSTicket
              key={t.id}
              orderId={t.orderNo}
              tableNo={t.tableNo}
              items={t.items}
              createdAt={t.createdAt}
              timeLimit={KDS_TIMEOUT_MINUTES}
              isVip={t.isVip}
              onComplete={() => move(t.id, 'preparing')}
              onRush={() => move(t.id, 'preparing')}
            />
          ))}
        </div>

        {/* 制作中列 */}
        <div style={{ ...COL_STYLE, background: '#001515' }}>
          <div style={{
            textAlign: 'center', padding: '8px 0', fontSize: 20,
            fontWeight: 'bold', color: '#4A9EFF', borderBottom: '3px solid #4A9EFF',
          }}>
            制作中 ({preparing.length})
          </div>
          {preparing.map(t => (
            <TXKDSTicket
              key={t.id}
              orderId={t.orderNo}
              tableNo={t.tableNo}
              items={t.items}
              createdAt={t.createdAt}
              timeLimit={KDS_TIMEOUT_MINUTES}
              isVip={t.isVip}
              onComplete={() => complete(t.id)}
              onRush={() => {/* 已在制作中，加急通知已处理 */}}
            />
          ))}
        </div>

        {/* 异常列 */}
        <div style={{ ...COL_STYLE, background: '#150000' }}>
          <div style={{
            textAlign: 'center', padding: '8px 0', fontSize: 20,
            fontWeight: 'bold', color: '#A32D2D', borderBottom: '3px solid #A32D2D',
          }}>
            异常 ({abnormal.length})
          </div>
          {abnormal.map(t => (
            <TXKDSTicket
              key={t.id}
              orderId={t.orderNo}
              tableNo={t.tableNo}
              items={t.items}
              createdAt={t.createdAt}
              timeLimit={KDS_TIMEOUT_MINUTES}
              isVip={t.isVip}
              onComplete={() => complete(t.id)}
              onRush={() => complete(t.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
