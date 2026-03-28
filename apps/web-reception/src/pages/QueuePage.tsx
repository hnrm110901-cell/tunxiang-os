/**
 * 排队叫号 — 大桌/小桌分开排队，取号/叫号/过号
 */
import { useState } from 'react';

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

const STATUS_CONFIG: Record<QueueStatus, { label: string; color: string; bg: string }> = {
  waiting: { label: '等待中', color: 'var(--tx-info)',    bg: '#EBF3FF' },
  called:  { label: '已叫号', color: 'var(--tx-primary)', bg: 'var(--tx-primary-light)' },
  seated:  { label: '已入座', color: 'var(--tx-success)', bg: '#E8F5F0' },
  skipped: { label: '已过号', color: 'var(--tx-text-3)',  bg: '#F0F0F0' },
};

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

  const handleCall = (id: string) => {
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'called' as QueueStatus } : q));
  };

  const handleSkip = (id: string) => {
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'skipped' as QueueStatus } : q));
  };

  const handleSeat = (id: string) => {
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'seated' as QueueStatus } : q));
  };

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
            fontSize: 20,
            fontWeight: 700,
            color: 'var(--tx-info)',
          }}>
            大桌等待: {largeWaiting}组
          </div>
          <div style={{
            background: '#EBF3FF',
            padding: '8px 20px',
            borderRadius: 'var(--tx-radius-sm)',
            fontSize: 20,
            fontWeight: 700,
            color: 'var(--tx-info)',
          }}>
            小桌等待: {smallWaiting}组
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
          onCall={handleCall}
          onSkip={handleSkip}
          onSeat={handleSeat}
        />
        {/* 小桌 */}
        <QueueColumn
          title="小桌 (1-5人)"
          items={smallQueue}
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
  title, items, onCall, onSkip, onSeat,
}: {
  title: string;
  items: QueueItem[];
  onCall: (id: string) => void;
  onSkip: (id: string) => void;
  onSeat: (id: string) => void;
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
      }}>
        {items.map(item => {
          const st = STATUS_CONFIG[item.status];
          return (
            <div key={item.id} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 16,
              padding: 16,
              borderRadius: 'var(--tx-radius-md)',
              border: `2px solid ${item.status === 'called' ? 'var(--tx-primary)' : 'var(--tx-border)'}`,
              background: item.status === 'called' ? 'var(--tx-primary-light)' : '#fff',
              opacity: item.status === 'skipped' || item.status === 'seated' ? 0.5 : 1,
            }}>
              {/* 排队号 */}
              <div style={{
                fontSize: 28,
                fontWeight: 800,
                color: item.status === 'called' ? 'var(--tx-primary)' : 'var(--tx-text-1)',
                minWidth: 64,
              }}>
                {item.number}
              </div>

              {/* 信息 */}
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 20, fontWeight: 600 }}>
                  {item.customerName} <span style={{ color: 'var(--tx-text-3)' }}>{item.guestCount}人</span>
                </div>
                <div style={{ fontSize: 16, color: 'var(--tx-text-3)', marginTop: 2 }}>
                  取号 {item.takenAt}
                  {item.status === 'waiting' && item.estimatedWait > 0 && (
                    <span> | 预计等 {item.estimatedWait}分钟</span>
                  )}
                </div>
              </div>

              {/* 状态 + 操作 */}
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: st.color,
                  background: st.bg,
                  padding: '4px 12px',
                  borderRadius: 6,
                }}>
                  {st.label}
                </span>
                {item.status === 'waiting' && (
                  <button
                    onClick={() => onCall(item.id)}
                    style={{
                      minWidth: 72,
                      height: 48,
                      borderRadius: 'var(--tx-radius-sm)',
                      border: 'none',
                      background: 'var(--tx-primary)',
                      color: '#fff',
                      fontSize: 18,
                      fontWeight: 700,
                      cursor: 'pointer',
                    }}
                  >叫号</button>
                )}
                {item.status === 'called' && (
                  <>
                    <button
                      onClick={() => onSeat(item.id)}
                      style={{
                        minWidth: 72,
                        height: 48,
                        borderRadius: 'var(--tx-radius-sm)',
                        border: 'none',
                        background: 'var(--tx-success)',
                        color: '#fff',
                        fontSize: 18,
                        fontWeight: 700,
                        cursor: 'pointer',
                      }}
                    >入座</button>
                    <button
                      onClick={() => onSkip(item.id)}
                      style={{
                        minWidth: 72,
                        height: 48,
                        borderRadius: 'var(--tx-radius-sm)',
                        border: '2px solid var(--tx-border)',
                        background: '#fff',
                        color: 'var(--tx-text-2)',
                        fontSize: 18,
                        fontWeight: 700,
                        cursor: 'pointer',
                      }}
                    >过号</button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
