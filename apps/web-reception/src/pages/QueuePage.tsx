/**
 * 排队叫号 — 大桌/小桌分开排队，取号/叫号/过号
 *
 * 使用 @tx-ds/biz QueueTicket 共享组件渲染排队号牌
 */
import { useState, useCallback } from 'react';
import { QueueTicket, StatusBar } from '@tx-ds/biz';
import type { QueueTicketData, QueueTicketStatus, TableSize } from '@tx-ds/biz';

type QueueStatus = 'waiting' | 'called' | 'seated' | 'skipped';

interface QueueItem {
  id: string;
  number: string;        // 排队号 如"大01"
  type: 'large' | 'small'; // 大桌(6人+) / 小桌(1-5人)
  guestCount: number;
  customerName: string;
  phone: string;
  status: QueueStatus;
  takenAt: string;       // 取号时间
  estimatedWait: number; // 预估等待分钟
}

const INITIAL_QUEUE: QueueItem[] = [
  { id: 'Q1', number: '大01', type: 'large', guestCount: 8,  customerName: '钱先生', phone: '138****1111', status: 'called',  takenAt: '11:05', estimatedWait: 0 },
  { id: 'Q2', number: '大02', type: 'large', guestCount: 6,  customerName: '吴女士', phone: '139****2222', status: 'waiting', takenAt: '11:12', estimatedWait: 20 },
  { id: 'Q3', number: '大03', type: 'large', guestCount: 10, customerName: '郑总',   phone: '136****3333', status: 'waiting', takenAt: '11:20', estimatedWait: 40 },
  { id: 'Q4', number: '小01', type: 'small', guestCount: 2,  customerName: '冯先生', phone: '150****4444', status: 'seated',  takenAt: '10:50', estimatedWait: 0 },
  { id: 'Q5', number: '小02', type: 'small', guestCount: 3,  customerName: '陈女士', phone: '158****5555', status: 'called',  takenAt: '11:00', estimatedWait: 0 },
  { id: 'Q6', number: '小03', type: 'small', guestCount: 2,  customerName: '褚先生', phone: '177****6666', status: 'waiting', takenAt: '11:08', estimatedWait: 10 },
  { id: 'Q7', number: '小04', type: 'small', guestCount: 4,  customerName: '卫小姐', phone: '188****7777', status: 'waiting', takenAt: '11:15', estimatedWait: 25 },
  { id: 'Q8', number: '小05', type: 'small', guestCount: 1,  customerName: '蒋先生', phone: '135****8888', status: 'skipped', takenAt: '10:55', estimatedWait: 0 },
];

export function QueuePage() {
  const [queue, setQueue] = useState<QueueItem[]>(INITIAL_QUEUE);
  const [showTakeNumber, setShowTakeNumber] = useState(false);
  const [newType, setNewType] = useState<'large' | 'small'>('small');
  const [newCount, setNewCount] = useState(2);
  const [newName, setNewName] = useState('');

  const largeQueue = queue.filter(q => q.type === 'large');
  const smallQueue = queue.filter(q => q.type === 'small');

  const largeWaiting = largeQueue.filter(q => q.status === 'waiting').length;
  const smallWaiting = smallQueue.filter(q => q.status === 'waiting').length;

  /** QueueItem → QueueTicketData 映射 */
  const toTicketData = useCallback((item: QueueItem): QueueTicketData => {
    // 计算已等待分钟
    const now = new Date();
    const [hh, mm] = item.takenAt.split(':').map(Number);
    const takenDate = new Date();
    takenDate.setHours(hh, mm, 0, 0);
    const waitMinutes = Math.max(0, Math.round((now.getTime() - takenDate.getTime()) / 60000));

    return {
      id: item.id,
      number: item.number,
      size: item.type as TableSize,  // 'large'|'small' → TableSize
      guestCount: item.guestCount,
      customerName: item.customerName,
      phone: item.phone || undefined,
      status: item.status as QueueTicketStatus,
      takenAt: item.takenAt,
      waitMinutes,
      estimatedWait: item.status === 'waiting' ? item.estimatedWait : undefined,
    };
  }, []);

  const handleCall = useCallback((ticket: QueueTicketData) => {
    setQueue(prev => prev.map(q => q.id === ticket.id ? { ...q, status: 'called' as QueueStatus } : q));
  }, []);

  const handleSkip = useCallback((ticket: QueueTicketData) => {
    setQueue(prev => prev.map(q => q.id === ticket.id ? { ...q, status: 'skipped' as QueueStatus } : q));
  }, []);

  const handleSeat = useCallback((ticket: QueueTicketData) => {
    setQueue(prev => prev.map(q => q.id === ticket.id ? { ...q, status: 'seated' as QueueStatus } : q));
  }, []);

  const handleTakeNumber = () => {
    if (!newName.trim()) return;
    const typePrefix = newType === 'large' ? '大' : '小';
    const existingOfType = queue.filter(q => q.type === newType);
    const nextNum = String(existingOfType.length + 1).padStart(2, '0');
    const newItem: QueueItem = {
      id: `Q${Date.now()}`,
      number: `${typePrefix}${nextNum}`,
      type: newType,
      guestCount: newCount,
      customerName: newName.trim(),
      phone: '',
      status: 'waiting',
      takenAt: new Date().toTimeString().slice(0, 5),
      estimatedWait: (newType === 'large' ? largeWaiting : smallWaiting) * 20 + 15,
    };
    setQueue(prev => [...prev, newItem]);
    setShowTakeNumber(false);
    setNewName('');
    setNewCount(2);
  };

  return (
    <div style={{ padding: 24, height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 32, fontWeight: 800 }}>排队叫号</h1>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <div style={{
            background: '#EBF3FF',
            padding: '8px 20px',
            borderRadius: 'var(--tx-radius-sm)',
          }}>
            <StatusBar
              size="compact"
              items={[
                { label: '大桌等待', value: largeWaiting, suffix: '组', color: 'var(--tx-info)' },
                { label: '小桌等待', value: smallWaiting, suffix: '组', color: 'var(--tx-info)' },
              ]}
            />
          </div>
          <button
            onClick={() => setShowTakeNumber(true)}
            style={{
              minWidth: 120,
              height: 56,
              borderRadius: 'var(--tx-radius-md)',
              border: 'none',
              background: 'var(--tx-primary)',
              color: '#fff',
              fontSize: 22,
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            取号
          </button>
        </div>
      </div>

      {/* 两列排队列表 */}
      <div style={{ flex: 1, display: 'flex', gap: 24, overflow: 'hidden' }}>
        {/* 大桌 */}
        <QueueColumn
          title="大桌 (6人及以上)"
          items={largeQueue}
          toTicketData={toTicketData}
          onCall={handleCall}
          onSkip={handleSkip}
          onSeat={handleSeat}
        />
        {/* 小桌 */}
        <QueueColumn
          title="小桌 (1-5人)"
          items={smallQueue}
          toTicketData={toTicketData}
          onCall={handleCall}
          onSkip={handleSkip}
          onSeat={handleSeat}
        />
      </div>

      {/* 取号弹层 */}
      {showTakeNumber && (
        <div style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 100,
        }}>
          <div style={{
            background: '#fff',
            borderRadius: 'var(--tx-radius-lg)',
            padding: 32,
            width: 420,
            boxShadow: 'var(--tx-shadow-md)',
          }}>
            <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 24 }}>取号排队</h2>

            {/* 类型选择 */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>桌型</div>
              <div style={{ display: 'flex', gap: 12 }}>
                {(['small', 'large'] as const).map(t => (
                  <button
                    key={t}
                    onClick={() => setNewType(t)}
                    style={{
                      flex: 1,
                      height: 56,
                      borderRadius: 'var(--tx-radius-md)',
                      border: `2px solid ${newType === t ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
                      background: newType === t ? 'var(--tx-primary-light)' : '#fff',
                      color: newType === t ? 'var(--tx-primary)' : 'var(--tx-text-2)',
                      fontSize: 20,
                      fontWeight: 700,
                      cursor: 'pointer',
                    }}
                  >
                    {t === 'small' ? '小桌 (1-5人)' : '大桌 (6人+)'}
                  </button>
                ))}
              </div>
            </div>

            {/* 人数 */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>用餐人数</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <button
                  onClick={() => setNewCount(Math.max(1, newCount - 1))}
                  style={{
                    width: 56, height: 56,
                    borderRadius: 'var(--tx-radius-md)',
                    border: '2px solid var(--tx-border)',
                    background: '#fff',
                    fontSize: 24,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >-</button>
                <span style={{ fontSize: 32, fontWeight: 800, minWidth: 40, textAlign: 'center' }}>{newCount}</span>
                <button
                  onClick={() => setNewCount(newCount + 1)}
                  style={{
                    width: 56, height: 56,
                    borderRadius: 'var(--tx-radius-md)',
                    border: '2px solid var(--tx-border)',
                    background: '#fff',
                    fontSize: 24,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >+</button>
              </div>
            </div>

            {/* 称呼 */}
            <div style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 18, color: 'var(--tx-text-2)', marginBottom: 8 }}>称呼</div>
              <input
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="客户称呼"
                style={{
                  width: '100%',
                  height: 56,
                  borderRadius: 'var(--tx-radius-md)',
                  border: '2px solid var(--tx-border)',
                  padding: '0 16px',
                  fontSize: 20,
                  outline: 'none',
                }}
              />
            </div>

            {/* 按钮组 */}
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={() => setShowTakeNumber(false)}
                style={{
                  flex: 1, height: 56,
                  borderRadius: 'var(--tx-radius-md)',
                  border: '2px solid var(--tx-border)',
                  background: '#fff',
                  fontSize: 20,
                  fontWeight: 700,
                  cursor: 'pointer',
                  color: 'var(--tx-text-2)',
                }}
              >取消</button>
              <button
                onClick={handleTakeNumber}
                style={{
                  flex: 1, height: 56,
                  borderRadius: 'var(--tx-radius-md)',
                  border: 'none',
                  background: 'var(--tx-primary)',
                  color: '#fff',
                  fontSize: 20,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >确认取号</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function QueueColumn({
  title, items, toTicketData, onCall, onSkip, onSeat,
}: {
  title: string;
  items: QueueItem[];
  toTicketData: (item: QueueItem) => QueueTicketData;
  onCall: (ticket: QueueTicketData) => void;
  onSkip: (ticket: QueueTicketData) => void;
  onSeat: (ticket: QueueTicketData) => void;
}) {
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: '#fff',
      borderRadius: 'var(--tx-radius-lg)',
      boxShadow: 'var(--tx-shadow-sm)',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '16px 20px',
        background: 'var(--tx-bg-2)',
        fontSize: 22,
        fontWeight: 700,
        borderBottom: '2px solid var(--tx-border)',
      }}>
        {title}
      </div>
      <div style={{
        flex: 1,
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        /* 覆盖 QueueTicket 暗色默认变量 → 亮色主题 */
        '--tx-bg-card': '#fff',
        '--tx-border': 'var(--tx-border, #E5E7EB)',
        '--tx-text-primary': 'var(--tx-text-1, #1F2937)',
        '--tx-text-secondary': 'var(--tx-text-2, #6B7280)',
        '--tx-text-tertiary': 'var(--tx-text-3, #9CA3AF)',
      } as React.CSSProperties}>
        {items.map(item => (
          <QueueTicket
            key={item.id}
            ticket={toTicketData(item)}
            onCall={onCall}
            onSeat={onSeat}
            onSkip={onSkip}
          />
        ))}
      </div>
    </div>
  );
}
