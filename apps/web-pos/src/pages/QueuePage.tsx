/**
 * 排队管理页 — 取号/叫号/排队列表/统计
 */
import { useState } from 'react';

/* ---------- Types ---------- */
interface QueueItem {
  id: string;
  number: string;
  partySize: number;
  waitTime: number; // 分钟
  status: 'waiting' | 'called' | 'seated' | 'abandoned';
  createdAt: string;
}

/* ---------- Mock Data ---------- */
const initialQueue: QueueItem[] = [
  { id: '1', number: 'A001', partySize: 2, waitTime: 45, status: 'waiting', createdAt: '11:30' },
  { id: '2', number: 'A002', partySize: 4, waitTime: 38, status: 'waiting', createdAt: '11:37' },
  { id: '3', number: 'A003', partySize: 6, waitTime: 25, status: 'called', createdAt: '11:50' },
  { id: '4', number: 'B001', partySize: 2, waitTime: 18, status: 'waiting', createdAt: '11:57' },
  { id: '5', number: 'B002', partySize: 3, waitTime: 10, status: 'waiting', createdAt: '12:05' },
  { id: '6', number: 'A004', partySize: 8, waitTime: 5, status: 'waiting', createdAt: '12:10' },
];

let nextA = 5;
let nextB = 3;

const statusLabel: Record<string, string> = { waiting: '等待中', called: '已叫号', seated: '已入座', abandoned: '已放弃' };
const statusColor: Record<string, string> = { waiting: '#faad14', called: '#1890ff', seated: '#52c41a', abandoned: '#666' };

/* ---------- Component ---------- */
export function QueuePage() {
  const [queue, setQueue] = useState<QueueItem[]>(initialQueue);
  const [showTakeNumber, setShowTakeNumber] = useState(false);
  const [selectedSize, setSelectedSize] = useState(2);

  const waitingList = queue.filter(q => q.status === 'waiting' || q.status === 'called');
  const avgWait = waitingList.length > 0
    ? Math.round(waitingList.reduce((s, q) => s + q.waitTime, 0) / waitingList.length)
    : 0;
  const abandonCount = queue.filter(q => q.status === 'abandoned').length;
  const abandonRate = queue.length > 0 ? ((abandonCount / queue.length) * 100).toFixed(1) : '0.0';

  const handleTakeNumber = () => {
    const isLarge = selectedSize > 4;
    const prefix = isLarge ? 'A' : 'B';
    const num = isLarge ? nextA++ : nextB++;
    const number = `${prefix}${String(num).padStart(3, '0')}`;
    const now = new Date();
    const timeStr = `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`;
    setQueue(prev => [...prev, {
      id: Date.now().toString(), number, partySize: selectedSize,
      waitTime: 0, status: 'waiting', createdAt: timeStr,
    }]);
    setShowTakeNumber(false);
  };

  const handleCall = (id: string) => {
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'called' } : q));
  };

  const handleSeat = (id: string) => {
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'seated' } : q));
  };

  const handleAbandon = (id: string) => {
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'abandoned' } : q));
  };

  const callNext = () => {
    const next = queue.find(q => q.status === 'waiting');
    if (next) handleCall(next.id);
  };

  return (
    <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0', fontFamily: 'Noto Sans SC, sans-serif', padding: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 22, color: '#fff' }}>排队管理</h1>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={callNext} style={{
            padding: '8px 20px', background: '#1890ff', color: '#fff',
            border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 'bold',
          }}>
            叫下一位
          </button>
          <button onClick={() => setShowTakeNumber(true)} style={{
            padding: '8px 20px', background: '#52c41a', color: '#fff',
            border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 'bold',
          }}>
            取号
          </button>
        </div>
      </div>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
        <div style={{ background: '#112B36', borderRadius: 10, padding: 16, textAlign: 'center' }}>
          <div style={{ fontSize: 12, color: '#8899A6' }}>当前等待</div>
          <div style={{ fontSize: 32, fontWeight: 'bold', color: '#faad14' }}>{waitingList.length}</div>
          <div style={{ fontSize: 11, color: '#666' }}>组</div>
        </div>
        <div style={{ background: '#112B36', borderRadius: 10, padding: 16, textAlign: 'center' }}>
          <div style={{ fontSize: 12, color: '#8899A6' }}>平均等待</div>
          <div style={{ fontSize: 32, fontWeight: 'bold', color: '#1890ff' }}>{avgWait}</div>
          <div style={{ fontSize: 11, color: '#666' }}>分钟</div>
        </div>
        <div style={{ background: '#112B36', borderRadius: 10, padding: 16, textAlign: 'center' }}>
          <div style={{ fontSize: 12, color: '#8899A6' }}>放弃率</div>
          <div style={{ fontSize: 32, fontWeight: 'bold', color: '#ff4d4f' }}>{abandonRate}%</div>
          <div style={{ fontSize: 11, color: '#666' }}>今日</div>
        </div>
      </div>

      {/* Queue List */}
      <div style={{ background: '#112B36', borderRadius: 10, overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '80px 60px 80px 100px 1fr',
          padding: '10px 16px', background: '#0D2430', fontSize: 12, color: '#8899A6', fontWeight: 'bold',
        }}>
          <span>号码</span><span>人数</span><span>等待</span><span>状态</span><span>操作</span>
        </div>
        {queue.filter(q => q.status !== 'seated').map(item => (
          <div key={item.id} style={{
            display: 'grid', gridTemplateColumns: '80px 60px 80px 100px 1fr',
            padding: '12px 16px', borderBottom: '1px solid #1A3A48', alignItems: 'center',
            background: item.status === 'called' ? '#1A2A3A' : 'transparent',
          }}>
            <span style={{ fontSize: 16, fontWeight: 'bold', color: '#fff' }}>{item.number}</span>
            <span>{item.partySize}人</span>
            <span style={{ color: item.waitTime > 30 ? '#ff4d4f' : '#faad14' }}>{item.waitTime}分钟</span>
            <span style={{ color: statusColor[item.status], fontSize: 13 }}>{statusLabel[item.status]}</span>
            <div style={{ display: 'flex', gap: 6 }}>
              {item.status === 'waiting' && (
                <button onClick={() => handleCall(item.id)} style={{
                  padding: '4px 12px', background: '#1890ff', color: '#fff',
                  border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12,
                }}>叫号</button>
              )}
              {item.status === 'called' && (
                <button onClick={() => handleSeat(item.id)} style={{
                  padding: '4px 12px', background: '#52c41a', color: '#fff',
                  border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12,
                }}>入座</button>
              )}
              {(item.status === 'waiting' || item.status === 'called') && (
                <button onClick={() => handleAbandon(item.id)} style={{
                  padding: '4px 12px', background: 'transparent', color: '#ff4d4f',
                  border: '1px solid #ff4d4f', borderRadius: 4, cursor: 'pointer', fontSize: 12,
                }}>放弃</button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Take Number Modal */}
      {showTakeNumber && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{ background: '#112B36', borderRadius: 12, padding: 24, width: 340 }}>
            <h3 style={{ margin: '0 0 16px', color: '#fff', fontSize: 18 }}>取号</h3>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, color: '#8899A6', marginBottom: 8 }}>用餐人数</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {[1, 2, 3, 4, 5, 6, 8, 10].map(n => (
                  <button key={n} onClick={() => setSelectedSize(n)} style={{
                    width: 50, height: 40, borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 'bold',
                    background: selectedSize === n ? '#1890ff' : '#1A3A48',
                    color: selectedSize === n ? '#fff' : '#aaa',
                    border: selectedSize === n ? '2px solid #1890ff' : '1px solid #2A4A58',
                  }}>
                    {n}人
                  </button>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 12, color: '#8899A6', marginBottom: 16 }}>
              {selectedSize > 4 ? 'A区（大桌）' : 'B区（小桌）'} - 预计等待 {waitingList.length * 8} 分钟
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={handleTakeNumber} style={{
                flex: 1, padding: '10px 0', background: '#52c41a', color: '#fff',
                border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 15, fontWeight: 'bold',
              }}>确认取号</button>
              <button onClick={() => setShowTakeNumber(false)} style={{
                flex: 1, padding: '10px 0', background: '#1A3A48', color: '#aaa',
                border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 15,
              }}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
