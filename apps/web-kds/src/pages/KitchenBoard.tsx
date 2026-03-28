/**
 * KitchenBoard — 档口任务看板（核心页面）
 *
 * 三列布局：待制作 | 制作中 | 已完成
 * 每张卡片：桌号 + 菜名 + 数量 + 等待时间 + VIP标记 + 备注
 * 按优先级排序，催菜标红，超时闪烁
 * 深色背景，触控优化（最小48x48按钮，最小16px字体）
 */
import { useState, useEffect, useCallback } from 'react';

// ─── Types ───

interface TicketItem {
  name: string;
  qty: number;
  notes: string;
  spec?: string;
}

interface KDSTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  items: TicketItem[];
  createdAt: number;        // timestamp ms
  status: 'pending' | 'cooking' | 'done';
  priority: 'normal' | 'rush' | 'vip';
  deptId: string;
  startedAt?: number;
  completedAt?: number;
}

// ─── Mock Data ───

const now = Date.now();
const min = (m: number) => m * 60 * 1000;

const MOCK_TICKETS: KDSTicket[] = [
  { id: 't1', orderNo: '001', tableNo: 'A01', items: [{ name: '剁椒鱼头', qty: 1, notes: '少辣' }, { name: '小炒肉', qty: 1, notes: '' }], createdAt: now - min(8), status: 'pending', priority: 'rush', deptId: 'hot' },
  { id: 't2', orderNo: '002', tableNo: 'A03', items: [{ name: '口味虾', qty: 2, notes: '中辣' }, { name: '炒青菜', qty: 1, notes: '' }], createdAt: now - min(5), status: 'pending', priority: 'normal', deptId: 'hot' },
  { id: 't3', orderNo: '003', tableNo: 'B01', items: [{ name: '鱼头', qty: 2, notes: '' }, { name: '米饭', qty: 6, notes: '' }], createdAt: now - min(18), status: 'cooking', priority: 'vip', deptId: 'hot', startedAt: now - min(10) },
  { id: 't4', orderNo: '004', tableNo: 'B02', items: [{ name: '外婆鸡', qty: 1, notes: '多放辣' }], createdAt: now - min(3), status: 'pending', priority: 'normal', deptId: 'steam' },
  { id: 't5', orderNo: '005', tableNo: 'A05', items: [{ name: '凉拌黄瓜', qty: 2, notes: '' }], createdAt: now - min(32), status: 'cooking', priority: 'rush', deptId: 'cold', startedAt: now - min(28) },
  { id: 't6', orderNo: '006', tableNo: 'C01', items: [{ name: '蒜蓉西兰花', qty: 1, notes: '' }], createdAt: now - min(12), status: 'cooking', priority: 'normal', deptId: 'hot', startedAt: now - min(8) },
  { id: 't7', orderNo: '007', tableNo: 'A02', items: [{ name: '酸菜鱼', qty: 1, notes: '微辣' }, { name: '辣椒炒肉', qty: 1, notes: '' }], createdAt: now - min(2), status: 'pending', priority: 'vip', deptId: 'hot' },
  { id: 't8', orderNo: '008', tableNo: 'B03', items: [{ name: '红烧肉', qty: 1, notes: '' }], createdAt: now - min(1), status: 'done', priority: 'normal', deptId: 'hot', startedAt: now - min(15), completedAt: now - min(1) },
  { id: 't9', orderNo: '009', tableNo: 'C02', items: [{ name: '蒸鲈鱼', qty: 1, notes: '' }], createdAt: now - min(20), status: 'done', priority: 'normal', deptId: 'steam', startedAt: now - min(18), completedAt: now - min(2) },
];

// ─── 超时阈值（分钟） ───
const TIMEOUT_WARN = 15;
const TIMEOUT_CRITICAL = 25;

// ─── 优先级排序权重 ───
function priorityWeight(p: string): number {
  if (p === 'rush') return 0;
  if (p === 'vip') return 1;
  return 2;
}

function sortTickets(tickets: KDSTicket[]): KDSTicket[] {
  return [...tickets].sort((a, b) => {
    const pw = priorityWeight(a.priority) - priorityWeight(b.priority);
    if (pw !== 0) return pw;
    return a.createdAt - b.createdAt; // 早的优先
  });
}

// ─── 时间格式 ───
function elapsedMin(ts: number): number {
  return Math.floor((Date.now() - ts) / 60000);
}

function formatElapsed(ts: number): string {
  const total = Math.floor((Date.now() - ts) / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

type TimeLevel = 'normal' | 'warning' | 'critical';

function getTimeLevel(ts: number): TimeLevel {
  const m = elapsedMin(ts);
  if (m >= TIMEOUT_CRITICAL) return 'critical';
  if (m >= TIMEOUT_WARN) return 'warning';
  return 'normal';
}

const TIME_COLORS: Record<TimeLevel, string> = {
  normal: '#0F6E56',
  warning: '#BA7517',
  critical: '#A32D2D',
};

// ─── Component ───

export function KitchenBoard() {
  const [tickets, setTickets] = useState<KDSTicket[]>(MOCK_TICKETS);
  const [tick, setTick] = useState(0);
  const [selectedDept, setSelectedDept] = useState<string>('all');

  // 每秒刷新倒计时
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // 开始制作
  const startCooking = useCallback((id: string) => {
    setTickets(prev => prev.map(t =>
      t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t
    ));
  }, []);

  // 完成出品
  const completeCooking = useCallback((id: string) => {
    setTickets(prev => prev.map(t =>
      t.id === id ? { ...t, status: 'done' as const, completedAt: Date.now() } : t
    ));
  }, []);

  // 按档口过滤
  const filtered = selectedDept === 'all' ? tickets : tickets.filter(t => t.deptId === selectedDept);

  const pending = sortTickets(filtered.filter(t => t.status === 'pending'));
  const cooking = sortTickets(filtered.filter(t => t.status === 'cooking'));
  const done = filtered.filter(t => t.status === 'done').sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0)).slice(0, 10);

  return (
    <div style={{
      background: '#0A0A0A', color: '#E0E0E0', height: '100vh',
      display: 'flex', flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
    }}>
      {/* Agent 预警条占位 */}

      {/* 顶栏 */}
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 20px', background: '#111', borderBottom: '1px solid #222',
        minHeight: 56,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <span style={{ fontWeight: 'bold', fontSize: 24, color: '#FF6B35' }}>后厨看板</span>
          <DeptTabs selected={selectedDept} onChange={setSelectedDept} />
        </div>
        <div style={{ display: 'flex', gap: 32, fontSize: 18 }}>
          <span>
            待制作 <b style={{ color: '#BA7517', fontSize: 28, fontFamily: 'JetBrains Mono, monospace' }}>{pending.length}</b>
          </span>
          <span>
            制作中 <b style={{ color: '#1890ff', fontSize: 28, fontFamily: 'JetBrains Mono, monospace' }}>{cooking.length}</b>
          </span>
          <span>
            已完成 <b style={{ color: '#0F6E56', fontSize: 28, fontFamily: 'JetBrains Mono, monospace' }}>{done.length}</b>
          </span>
        </div>
      </header>

      {/* 三列看板 */}
      <div style={{ flex: 1, display: 'flex', gap: 2, overflow: 'hidden' }}>
        {/* 待制作 */}
        <BoardColumn
          title="待制作"
          count={pending.length}
          color="#BA7517"
          bgColor="#1a1a00"
        >
          {pending.map(t => (
            <TicketCard
              key={t.id}
              ticket={t}
              actionLabel="开始制作"
              actionColor="#1890ff"
              onAction={() => startCooking(t.id)}
              tick={tick}
            />
          ))}
        </BoardColumn>

        {/* 制作中 */}
        <BoardColumn
          title="制作中"
          count={cooking.length}
          color="#1890ff"
          bgColor="#001a1a"
        >
          {cooking.map(t => (
            <TicketCard
              key={t.id}
              ticket={t}
              actionLabel="完成出品"
              actionColor="#0F6E56"
              onAction={() => completeCooking(t.id)}
              tick={tick}
            />
          ))}
        </BoardColumn>

        {/* 已完成 */}
        <BoardColumn
          title="已完成"
          count={done.length}
          color="#0F6E56"
          bgColor="#001a00"
        >
          {done.map(t => (
            <DoneCard key={t.id} ticket={t} />
          ))}
        </BoardColumn>
      </div>

      {/* 脉冲动画 CSS */}
      <style>{`
        @keyframes kds-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
        @keyframes kds-border-flash {
          0%, 100% { border-color: #A32D2D; }
          50% { border-color: #ff4d4f; }
        }
      `}</style>
    </div>
  );
}

// ─── 档口选项卡 ───

const DEPT_OPTIONS = [
  { id: 'all', label: '全部' },
  { id: 'hot', label: '炒炉' },
  { id: 'cold', label: '凉菜' },
  { id: 'steam', label: '蒸菜' },
  { id: 'bar', label: '吧台' },
];

function DeptTabs({ selected, onChange }: { selected: string; onChange: (id: string) => void }) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      {DEPT_OPTIONS.map(d => (
        <button
          key={d.id}
          onClick={() => onChange(d.id)}
          style={{
            padding: '8px 20px',
            minHeight: 48,
            minWidth: 48,
            fontSize: 16,
            fontWeight: selected === d.id ? 'bold' : 'normal',
            color: selected === d.id ? '#fff' : '#888',
            background: selected === d.id ? '#FF6B35' : '#222',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
            transition: 'transform 200ms ease',
          }}
        >
          {d.label}
        </button>
      ))}
    </div>
  );
}

// ─── 看板列 ───

function BoardColumn({ title, count, color, bgColor, children }: {
  title: string; count: number; color: string; bgColor: string; children: React.ReactNode;
}) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      background: bgColor, overflow: 'hidden',
    }}>
      <div style={{
        textAlign: 'center', padding: '10px 0', fontSize: 20,
        fontWeight: 'bold', color, borderBottom: `3px solid ${color}`,
      }}>
        {title} ({count})
      </div>
      <div style={{
        flex: 1, overflowY: 'auto', padding: 10, display: 'flex',
        flexDirection: 'column', gap: 10,
        WebkitOverflowScrolling: 'touch',
      }}>
        {children}
      </div>
    </div>
  );
}

// ─── 工单卡片 ───

function TicketCard({ ticket: t, actionLabel, actionColor, onAction, tick: _tick }: {
  ticket: KDSTicket; actionLabel: string; actionColor: string;
  onAction: () => void; tick: number;
}) {
  const level = getTimeLevel(t.createdAt);
  const elapsed = formatElapsed(t.createdAt);
  const isRush = t.priority === 'rush';
  const isVip = t.priority === 'vip';
  const isCritical = level === 'critical';

  const borderColor = isCritical
    ? '#A32D2D'
    : isRush ? '#BA7517' : isVip ? '#722ed1' : '#333';

  return (
    <div style={{
      background: isCritical ? '#1a0505' : '#111',
      borderRadius: 12,
      padding: 14,
      borderLeft: `6px solid ${borderColor}`,
      border: isCritical ? '2px solid #A32D2D' : undefined,
      borderLeftWidth: 6,
      borderLeftStyle: 'solid',
      borderLeftColor: borderColor,
      animation: isCritical ? 'kds-border-flash 1.5s infinite' : isRush ? 'kds-pulse 2s infinite' : undefined,
    }}>
      {/* 头部：桌号 + 标签 + 时间 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>{t.tableNo}</span>
          <span style={{ fontSize: 16, color: '#666' }}>#{t.orderNo}</span>
          {isRush && (
            <span style={{
              fontSize: 16, padding: '2px 10px', borderRadius: 6,
              background: '#A32D2D', color: '#fff', fontWeight: 'bold',
            }}>
              催
            </span>
          )}
          {isVip && (
            <span style={{
              fontSize: 16, padding: '2px 10px', borderRadius: 6,
              background: 'linear-gradient(135deg, #C5A347, #E8D48B)', color: '#1a1a00', fontWeight: 'bold',
            }}>
              VIP
            </span>
          )}
        </div>
        <div style={{
          fontSize: 28, fontWeight: 'bold',
          color: TIME_COLORS[level],
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          {elapsed}
        </div>
      </div>

      {/* 菜品列表 */}
      {t.items.map((item, i) => (
        <div key={i} style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '4px 0', fontSize: 20, fontWeight: 'bold',
        }}>
          <span style={{ flex: 1 }}>
            {item.name}
            {item.notes && (
              <span style={{ fontSize: 16, color: '#A32D2D', marginLeft: 6, fontWeight: 'normal' }}>
                ({item.notes})
              </span>
            )}
          </span>
          <span style={{ color: '#FF6B35', fontSize: 22, minWidth: 50, textAlign: 'right' }}>
            x{item.qty}
          </span>
        </div>
      ))}

      {/* 操作按钮 */}
      <button
        onClick={onAction}
        style={{
          width: '100%', marginTop: 10, padding: '14px 0',
          border: 'none', borderRadius: 8,
          background: actionColor, color: '#fff',
          fontSize: 20, fontWeight: 'bold',
          cursor: 'pointer', minHeight: 56,
          transition: 'transform 200ms ease',
        }}
        onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
        onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
      >
        {actionLabel}
      </button>
    </div>
  );
}

// ─── 已完成卡片（简化） ───

function DoneCard({ ticket: t }: { ticket: KDSTicket }) {
  const totalMin = t.completedAt && t.startedAt
    ? Math.floor((t.completedAt - t.createdAt) / 60000)
    : 0;

  return (
    <div style={{
      background: '#111', borderRadius: 12, padding: 12,
      borderLeft: '6px solid #0F6E56', opacity: 0.75,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 22, fontWeight: 'bold', color: '#aaa' }}>{t.tableNo}</span>
          <span style={{ fontSize: 16, color: '#555' }}>#{t.orderNo}</span>
        </div>
        <span style={{ fontSize: 20, color: '#0F6E56', fontFamily: 'JetBrains Mono, monospace', fontWeight: 'bold' }}>
          {totalMin}'
        </span>
      </div>
      <div style={{ fontSize: 18, color: '#888' }}>
        {t.items.map(i => `${i.name}x${i.qty}`).join(' / ')}
      </div>
    </div>
  );
}
