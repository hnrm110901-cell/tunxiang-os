/**
 * 排队叫号管理面板 — 前台工作人员平板横屏专用
 * 左侧60%：小桌/中桌/大桌三列排队列表
 * 右侧40%：取号区（三个大按钮 + 手机号输入 + 号码确认弹窗）
 * 顶部栏：门店名 + 当前时间 + 今日已接待 + 当前等待
 * 10s自动刷新
 */
import { useState, useEffect, useCallback, useRef } from 'react';

// ─── 类型 ───

type QueueStatus = 'waiting' | 'called' | 'seated' | 'skipped' | 'cancelled';
type TableSize = 'small' | 'medium' | 'large';

interface QueueItem {
  id: string;
  number: string;
  size: TableSize;
  guestCount: number;
  phone: string;
  status: QueueStatus;
  takenAt: string;       // HH:mm
  waitMinutes: number;   // 已等待分钟
}

interface TakeNumberResult {
  number: string;
  size: TableSize;
  waitingAhead: number;
  estimatedWait: number;
}

// ─── 颜色常量（深色主题）───

const C = {
  bg1: '#0B1A20',
  bg2: '#112228',
  bg3: '#1A3038',
  accent: '#FF6B35',
  accentHover: '#E85A28',
  green: '#0F6E56',
  greenBg: 'rgba(15,110,86,0.2)',
  yellow: '#BA7517',
  yellowBg: 'rgba(186,117,23,0.25)',
  gray: '#5F5E5A',
  grayBg: 'rgba(95,94,90,0.25)',
  red: '#A32D2D',
  redBg: 'rgba(163,45,45,0.2)',
  blue: '#185FA5',
  blueBg: 'rgba(24,95,165,0.2)',
  text1: '#F0EDE6',
  text2: '#B4B2A9',
  text3: '#6B7B85',
  border: 'rgba(255,255,255,0.08)',
} as const;

const SIZE_LABELS: Record<TableSize, { label: string; range: string; prefix: string }> = {
  small:  { label: '小桌', range: '1-2人', prefix: 'S' },
  medium: { label: '中桌', range: '3-4人', prefix: 'M' },
  large:  { label: '大桌', range: '5人+',  prefix: 'L' },
};

// ─── Mock 数据 ───

const MOCK_QUEUE: QueueItem[] = [
  { id: 'q1', number: 'S001', size: 'small',  guestCount: 2, phone: '138****1234', status: 'called',  takenAt: '11:05', waitMinutes: 25 },
  { id: 'q2', number: 'S002', size: 'small',  guestCount: 1, phone: '139****5678', status: 'waiting', takenAt: '11:12', waitMinutes: 18 },
  { id: 'q3', number: 'S003', size: 'small',  guestCount: 2, phone: '',             status: 'waiting', takenAt: '11:20', waitMinutes: 10 },
  { id: 'q4', number: 'M001', size: 'medium', guestCount: 3, phone: '150****4321', status: 'waiting', takenAt: '11:08', waitMinutes: 22 },
  { id: 'q5', number: 'M002', size: 'medium', guestCount: 4, phone: '158****8765', status: 'called',  takenAt: '11:00', waitMinutes: 30 },
  { id: 'q6', number: 'M003', size: 'medium', guestCount: 4, phone: '',             status: 'waiting', takenAt: '11:25', waitMinutes: 5 },
  { id: 'q7', number: 'L001', size: 'large',  guestCount: 8, phone: '177****9999', status: 'called',  takenAt: '10:50', waitMinutes: 40 },
  { id: 'q8', number: 'L002', size: 'large',  guestCount: 6, phone: '188****1111', status: 'waiting', takenAt: '11:10', waitMinutes: 20 },
  { id: 'q9', number: 'L003', size: 'large',  guestCount: 10, phone: '135****2222', status: 'waiting', takenAt: '11:30', waitMinutes: 0 },
];

// ─── API ───

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || '';
const TENANT_ID = (import.meta.env.VITE_TENANT_ID as string) || '';
const STORE_ID = (import.meta.env.VITE_STORE_ID as string) || 'store_001';
const STORE_NAME = (import.meta.env.VITE_STORE_NAME as string) || '屯象旗舰店';

function getHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  if (TENANT_ID) h['X-Tenant-ID'] = TENANT_ID;
  return h;
}

function classifySize(guestCount: number): TableSize {
  if (guestCount <= 2) return 'small';
  if (guestCount <= 4) return 'medium';
  return 'large';
}

async function apiFetchQueue(): Promise<QueueItem[]> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/waitlist?store_id=${STORE_ID}`,
    { headers: getHeaders() },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return (json.data?.items ?? []).map((q: Record<string, unknown>) => ({
    id: (q.waitlist_id ?? q.id) as string,
    number: (q.queue_number ?? q.number) as string,
    size: classifySize(q.guest_count as number),
    guestCount: q.guest_count as number,
    phone: (q.phone ?? '') as string,
    status: q.status as QueueStatus,
    takenAt: ((q.created_at ?? q.taken_at ?? '') as string).slice(11, 16),
    waitMinutes: q.wait_minutes as number ?? 0,
  }));
}

async function apiCallNumber(id: string): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/waitlist/${encodeURIComponent(id)}/call`,
    { method: 'POST', headers: getHeaders() },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
}

async function apiSkipNumber(id: string): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/waitlist/${encodeURIComponent(id)}/skip`,
    { method: 'POST', headers: getHeaders() },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
}

async function apiSeatNumber(id: string): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/waitlist/${encodeURIComponent(id)}/seat`,
    { method: 'POST', headers: getHeaders() },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
}

async function apiTakeNumber(payload: {
  guest_count: number;
  phone: string;
  size: TableSize;
}): Promise<TakeNumberResult> {
  const resp = await fetch(
    `${API_BASE}/api/v1/trade/waitlist`,
    {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ store_id: STORE_ID, ...payload }),
    },
  );
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return {
    number: json.data.queue_number ?? json.data.number,
    size: payload.size,
    waitingAhead: json.data.waiting_ahead ?? 0,
    estimatedWait: json.data.estimated_wait_min ?? 0,
  };
}

// ─── 辅助函数 ───

function vibrate() {
  if (navigator.vibrate) navigator.vibrate(50);
}

function formatTime(date: Date): string {
  return date.toTimeString().slice(0, 5);
}

// ─── 组件 ───

/** 顶部栏 */
function TopBar({ queue }: { queue: QueueItem[] }) {
  const [time, setTime] = useState(() => formatTime(new Date()));
  useEffect(() => {
    const t = setInterval(() => setTime(formatTime(new Date())), 10_000);
    return () => clearInterval(t);
  }, []);

  const waiting = queue.filter(q => q.status === 'waiting' || q.status === 'called').length;
  const seated = queue.filter(q => q.status === 'seated').length;

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 24px',
      height: 56,
      background: C.bg1,
      borderBottom: `1px solid ${C.border}`,
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 20, fontWeight: 800, color: C.accent }}>{STORE_NAME}</span>
      <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
        <span style={{ fontSize: 16, color: C.text2 }}>
          今日已接待 <span style={{ fontSize: 22, fontWeight: 700, color: C.green }}>{seated}</span> 桌
        </span>
        <span style={{ fontSize: 16, color: C.text2 }}>
          当前等待 <span style={{ fontSize: 22, fontWeight: 700, color: waiting > 10 ? C.red : C.accent }}>{waiting}</span> 桌
        </span>
        <span style={{ fontSize: 20, fontWeight: 700, color: C.text2 }}>{time}</span>
      </div>
    </div>
  );
}

/** 单张等待卡片 */
function QueueCard({
  item,
  onCall,
  onSkip,
  onSeat,
}: {
  item: QueueItem;
  onCall: () => void;
  onSkip: () => void;
  onSeat: () => void;
}) {
  const isCalled = item.status === 'called';
  const isWaiting = item.status === 'waiting';

  const cardBg = isCalled ? C.yellowBg : C.bg3;
  const borderColor = isCalled ? C.yellow : C.border;

  return (
    <div style={{
      background: cardBg,
      border: `2px solid ${borderColor}`,
      borderRadius: 12,
      padding: 12,
      marginBottom: 8,
    }}>
      {/* 号码 + 人数 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontSize: 28, fontWeight: 800, color: C.text1 }}>{item.number}</span>
        <span style={{
          fontSize: 16,
          fontWeight: 600,
          color: C.text2,
          background: C.bg1,
          borderRadius: 6,
          padding: '2px 10px',
        }}>
          {item.guestCount}人
        </span>
      </div>
      {/* 手机尾号 + 等待时长 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 16, color: C.text3 }}>
          {item.phone ? item.phone.slice(-4) : '--'}
        </span>
        <span style={{ fontSize: 16, color: item.waitMinutes > 30 ? C.red : C.text3 }}>
          等{item.waitMinutes}分钟
        </span>
      </div>
      {/* 状态标签 */}
      {isCalled && (
        <div style={{
          fontSize: 16, fontWeight: 700, color: C.yellow,
          textAlign: 'center', marginBottom: 8,
        }}>
          已叫号
        </div>
      )}
      {/* 操作按钮 */}
      {(isWaiting || isCalled) && (
        <div style={{ display: 'flex', gap: 6 }}>
          {isWaiting && (
            <button
              onClick={() => { vibrate(); onCall(); }}
              style={{
                flex: 2,
                height: 88,
                background: C.accent,
                color: '#fff',
                border: 'none',
                borderRadius: 10,
                fontSize: 20,
                fontWeight: 800,
                cursor: 'pointer',
              }}
            >
              叫号
            </button>
          )}
          {isCalled && (
            <button
              onClick={() => { vibrate(); onSeat(); }}
              style={{
                flex: 2,
                height: 88,
                background: C.green,
                color: '#fff',
                border: 'none',
                borderRadius: 10,
                fontSize: 20,
                fontWeight: 800,
                cursor: 'pointer',
              }}
            >
              入座
            </button>
          )}
          <button
            onClick={() => { vibrate(); onSkip(); }}
            style={{
              flex: 1,
              height: isCalled ? 88 : 48,
              background: C.grayBg,
              color: C.text2,
              border: `1px solid ${C.border}`,
              borderRadius: 10,
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
              minWidth: 48,
              minHeight: 48,
            }}
          >
            过号
          </button>
        </div>
      )}
    </div>
  );
}

/** 单列队列 */
function QueueColumn({
  size,
  items,
  onCall,
  onSkip,
  onSeat,
}: {
  size: TableSize;
  items: QueueItem[];
  onCall: (id: string) => void;
  onSkip: (id: string) => void;
  onSeat: (id: string) => void;
}) {
  const cfg = SIZE_LABELS[size];
  const active = items.filter(i => i.status === 'waiting' || i.status === 'called');
  const currentNumber = items.find(i => i.status === 'called')?.number ?? active[0]?.number ?? '--';
  const waitingCount = items.filter(i => i.status === 'waiting').length;
  const avgWait = waitingCount > 0
    ? Math.round(items.filter(i => i.status === 'waiting').reduce((s, i) => s + i.waitMinutes, 0) / waitingCount)
    : 0;

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: C.bg2,
      borderRadius: 12,
      overflow: 'hidden',
      border: `1px solid ${C.border}`,
    }}>
      {/* 列头 */}
      <div style={{
        padding: '14px 16px',
        borderBottom: `1px solid ${C.border}`,
        background: C.bg1,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: C.text1 }}>{cfg.label}（{cfg.range}）</span>
          <span style={{ fontSize: 16, color: C.text3 }}>等待 {waitingCount} 桌</span>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 16, color: C.text3, marginBottom: 2 }}>当前号码</div>
          <div style={{ fontSize: 48, fontWeight: 900, color: C.accent, lineHeight: 1.1 }}>{currentNumber}</div>
        </div>
        <div style={{ textAlign: 'center', marginTop: 4, fontSize: 16, color: C.text3 }}>
          预计等待 ~{avgWait} 分钟
        </div>
      </div>
      {/* 卡片列表 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 10, WebkitOverflowScrolling: 'touch' }}>
        {active.length === 0 && (
          <div style={{ textAlign: 'center', color: C.text3, padding: 32, fontSize: 16 }}>暂无排队</div>
        )}
        {active.map(item => (
          <QueueCard
            key={item.id}
            item={item}
            onCall={() => onCall(item.id)}
            onSkip={() => onSkip(item.id)}
            onSeat={() => onSeat(item.id)}
          />
        ))}
      </div>
    </div>
  );
}

/** 号码确认弹窗 */
function NumberConfirmModal({
  result,
  onClose,
}: {
  result: TakeNumberResult;
  onClose: () => void;
}) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.7)',
    }} onClick={onClose}>
      <div
        style={{
          background: C.bg2,
          borderRadius: 20,
          padding: '40px 48px',
          textAlign: 'center',
          minWidth: 340,
          border: `2px solid ${C.accent}`,
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 20, color: C.text2, marginBottom: 8 }}>您的排队号码</div>
        <div style={{ fontSize: 72, fontWeight: 900, color: C.accent, lineHeight: 1.2, marginBottom: 12 }}>
          {result.number}
        </div>
        <div style={{ fontSize: 18, color: C.text2, marginBottom: 4 }}>
          {SIZE_LABELS[result.size].label}（{SIZE_LABELS[result.size].range}）
        </div>
        <div style={{ fontSize: 18, color: C.text2, marginBottom: 4 }}>
          前方等待 <span style={{ fontWeight: 700, color: C.accent }}>{result.waitingAhead}</span> 桌
        </div>
        <div style={{ fontSize: 18, color: C.text2, marginBottom: 24 }}>
          预计等待 <span style={{ fontWeight: 700, color: C.accent }}>~{result.estimatedWait}</span> 分钟
        </div>
        <button
          onClick={onClose}
          style={{
            width: '100%',
            height: 56,
            background: C.accent,
            color: '#fff',
            border: 'none',
            borderRadius: 12,
            fontSize: 20,
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          确定
        </button>
      </div>
    </div>
  );
}

/** 右侧取号区 */
function TakeNumberPanel({
  queue,
  onTake,
}: {
  queue: QueueItem[];
  onTake: (size: TableSize, phone: string) => void;
}) {
  const [phone, setPhone] = useState('');

  const countBySize = (s: TableSize) =>
    queue.filter(q => q.size === s && (q.status === 'waiting' || q.status === 'called')).length;

  const sizes: TableSize[] = ['small', 'medium', 'large'];

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
      padding: 20,
      background: C.bg2,
      borderRadius: 12,
      border: `1px solid ${C.border}`,
      height: '100%',
    }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: C.text1, textAlign: 'center' }}>取号</div>

      {/* 手机号输入 */}
      <div>
        <label style={{ fontSize: 16, color: C.text3, display: 'block', marginBottom: 6 }}>
          手机号（可选，方便短信通知）
        </label>
        <input
          type="tel"
          maxLength={11}
          value={phone}
          onChange={e => setPhone(e.target.value.replace(/\D/g, ''))}
          placeholder="请输入手机号"
          style={{
            width: '100%',
            height: 52,
            background: C.bg1,
            color: C.text1,
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            padding: '0 16px',
            fontSize: 18,
            outline: 'none',
          }}
        />
      </div>

      {/* 三个大按钮 */}
      {sizes.map(size => {
        const cfg = SIZE_LABELS[size];
        const waiting = countBySize(size);
        return (
          <button
            key={size}
            onClick={() => { vibrate(); onTake(size, phone); }}
            style={{
              height: 120,
              background: C.bg3,
              color: C.text1,
              border: `2px solid ${C.border}`,
              borderRadius: 14,
              cursor: 'pointer',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 4,
              transition: 'border-color 150ms',
            }}
            onPointerDown={e => { (e.currentTarget.style.borderColor = C.accent); }}
            onPointerUp={e => { (e.currentTarget.style.borderColor = C.border); }}
            onPointerLeave={e => { (e.currentTarget.style.borderColor = C.border); }}
          >
            <span style={{ fontSize: 24, fontWeight: 800 }}>{cfg.label}（{cfg.range}）</span>
            <span style={{ fontSize: 18, color: C.text3 }}>
              当前等待 <span style={{ fontWeight: 700, color: C.accent }}>{waiting}</span> 桌
            </span>
          </button>
        );
      })}

      <div style={{ flex: 1 }} />
    </div>
  );
}

// ─── 主组件 ───

export function QueuePanel() {
  const [queue, setQueue] = useState<QueueItem[]>(MOCK_QUEUE);
  const [confirmResult, setConfirmResult] = useState<TakeNumberResult | null>(null);
  const counterRef = useRef<Record<TableSize, number>>({ small: 3, medium: 3, large: 3 });

  const fetchQueue = useCallback(async () => {
    try {
      const data = await apiFetchQueue();
      setQueue(data);
    } catch {
      // API不可用，保持当前状态（首次加载用Mock）
    }
  }, []);

  // 10秒自动刷新
  useEffect(() => {
    fetchQueue();
    const timer = setInterval(fetchQueue, 10_000);
    return () => clearInterval(timer);
  }, [fetchQueue]);

  const handleCall = useCallback(async (id: string) => {
    try {
      await apiCallNumber(id);
    } catch {
      // 降级本地状态更新
    }
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'called' as QueueStatus } : q));
  }, []);

  const handleSkip = useCallback(async (id: string) => {
    try {
      await apiSkipNumber(id);
    } catch {
      // 降级本地状态更新
    }
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'skipped' as QueueStatus } : q));
  }, []);

  const handleSeat = useCallback(async (id: string) => {
    try {
      await apiSeatNumber(id);
    } catch {
      // 降级本地状态更新
    }
    setQueue(prev => prev.map(q => q.id === id ? { ...q, status: 'seated' as QueueStatus } : q));
  }, []);

  const handleTake = useCallback(async (size: TableSize, phone: string) => {
    const guestMap: Record<TableSize, number> = { small: 2, medium: 3, large: 6 };
    try {
      const result = await apiTakeNumber({
        guest_count: guestMap[size],
        phone,
        size,
      });
      setConfirmResult(result);
      fetchQueue();
    } catch {
      // 降级：本地生成号码
      counterRef.current[size] += 1;
      const num = `${SIZE_LABELS[size].prefix}${String(counterRef.current[size]).padStart(3, '0')}`;
      const waitingAhead = queue.filter(q => q.size === size && (q.status === 'waiting' || q.status === 'called')).length;
      const newItem: QueueItem = {
        id: `local_${Date.now()}`,
        number: num,
        size,
        guestCount: guestMap[size],
        phone: phone ? phone.slice(0, 3) + '****' + phone.slice(-4) : '',
        status: 'waiting',
        takenAt: formatTime(new Date()),
        waitMinutes: 0,
      };
      setQueue(prev => [...prev, newItem]);
      setConfirmResult({
        number: num,
        size,
        waitingAhead,
        estimatedWait: waitingAhead * 8,
      });
    }
  }, [queue, fetchQueue]);

  const sizes: TableSize[] = ['small', 'medium', 'large'];

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: C.bg1,
      minWidth: 1024,
      minHeight: 768,
    }}>
      <TopBar queue={queue} />
      <div style={{
        flex: 1,
        display: 'flex',
        gap: 12,
        padding: 12,
        overflow: 'hidden',
      }}>
        {/* 左侧60% — 三列排队列表 */}
        <div style={{ flex: 6, display: 'flex', gap: 10, overflow: 'hidden' }}>
          {sizes.map(size => (
            <QueueColumn
              key={size}
              size={size}
              items={queue.filter(q => q.size === size)}
              onCall={handleCall}
              onSkip={handleSkip}
              onSeat={handleSeat}
            />
          ))}
        </div>
        {/* 右侧40% — 取号区 */}
        <div style={{ flex: 4, overflow: 'auto' }}>
          <TakeNumberPanel queue={queue} onTake={handleTake} />
        </div>
      </div>

      {/* 号码确认弹窗 */}
      {confirmResult && (
        <NumberConfirmModal result={confirmResult} onClose={() => setConfirmResult(null)} />
      )}
    </div>
  );
}
