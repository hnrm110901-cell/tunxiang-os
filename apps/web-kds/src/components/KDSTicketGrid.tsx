/**
 * KDSTicketGrid — Toast-style KDS 出餐票据网格视图
 *
 * Store 终端组件：
 * - 不使用 Ant Design
 * - 最小字体 16px，标题 >= 24px
 * - 最小触控区域 48x48px
 * - 使用 CSS 变量 var(--tx-*)
 * - 支持滑动完成手势
 * - 按工龄着色（绿/黄/红）
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import styles from './KDSTicketGrid.module.css';

// ─── Types ────────────────────────────────────────────────────
export interface KDSTicket {
  id: string;
  orderId: string;
  tableNo: string;
  items: { name: string; qty: number; spec?: string; priority: 'normal' | 'rush' }[];
  createdAt: number; // timestamp ms
  timeLimitMin: number;
  isVip: boolean;
  station: string;
  status: 'pending' | 'cooking' | 'fulfilled';
}

type Station = '全部' | '热菜档' | '凉菜档' | '面点档' | '汤档';

const STATIONS: Station[] = ['全部', '热菜档', '凉菜档', '面点档', '汤档'];

// ─── Mock Data ────────────────────────────────────────────────
const now = Date.now();
const min = (m: number) => m * 60 * 1000;

const INITIAL_TICKETS: KDSTicket[] = [
  {
    id: 'T001', orderId: 'ORD-0328-001', tableNo: 'A01',
    items: [{ name: '剁椒鱼头', qty: 1, spec: '少辣', priority: 'normal' }, { name: '小炒肉', qty: 1, priority: 'normal' }],
    createdAt: now - min(3), timeLimitMin: 15, isVip: true, station: '热菜档', status: 'pending',
  },
  {
    id: 'T002', orderId: 'ORD-0328-002', tableNo: 'A03',
    items: [{ name: '口味虾', qty: 1, spec: '中辣', priority: 'rush' }],
    createdAt: now - min(8), timeLimitMin: 12, isVip: false, station: '热菜档', status: 'cooking',
  },
  {
    id: 'T003', orderId: 'ORD-0328-003', tableNo: 'B01',
    items: [{ name: '凉拌黄瓜', qty: 2, priority: 'normal' }, { name: '蒜泥白肉', qty: 1, priority: 'normal' }],
    createdAt: now - min(2), timeLimitMin: 8, isVip: false, station: '凉菜档', status: 'pending',
  },
  {
    id: 'T004', orderId: 'ORD-0328-004', tableNo: 'B05',
    items: [{ name: '土鸡汤', qty: 1, spec: '加枸杞', priority: 'normal' }],
    createdAt: now - min(20), timeLimitMin: 18, isVip: true, station: '汤档', status: 'cooking',
  },
  {
    id: 'T005', orderId: 'ORD-0328-005', tableNo: 'C02',
    items: [{ name: '酸辣土豆丝', qty: 1, priority: 'normal' }, { name: '辣椒炒肉', qty: 1, priority: 'rush' }],
    createdAt: now - min(14), timeLimitMin: 12, isVip: false, station: '热菜档', status: 'pending',
  },
  {
    id: 'T006', orderId: 'ORD-0328-006', tableNo: 'A08',
    items: [{ name: '葱油拌面', qty: 2, priority: 'normal' }, { name: '小笼包', qty: 1, spec: '鲜肉', priority: 'normal' }],
    createdAt: now - min(5), timeLimitMin: 10, isVip: false, station: '面点档', status: 'pending',
  },
  {
    id: 'T007', orderId: 'ORD-0328-007', tableNo: 'D01',
    items: [{ name: '皮蛋豆腐', qty: 1, priority: 'normal' }],
    createdAt: now - min(1), timeLimitMin: 8, isVip: false, station: '凉菜档', status: 'pending',
  },
  {
    id: 'T008', orderId: 'ORD-0328-008', tableNo: 'A12',
    items: [{ name: '红烧五花肉', qty: 1, priority: 'normal' }, { name: '蒸鱼头', qty: 1, spec: '微辣', priority: 'rush' }],
    createdAt: now - min(16), timeLimitMin: 15, isVip: true, station: '热菜档', status: 'cooking',
  },
  {
    id: 'T009', orderId: 'ORD-0328-009', tableNo: 'B03',
    items: [{ name: '酸辣汤', qty: 1, priority: 'normal' }],
    createdAt: now - min(6), timeLimitMin: 12, isVip: false, station: '汤档', status: 'pending',
  },
  {
    id: 'T010', orderId: 'ORD-0328-010', tableNo: 'C05',
    items: [{ name: '馒头', qty: 4, priority: 'normal' }, { name: '花卷', qty: 2, priority: 'normal' }],
    createdAt: now - min(4), timeLimitMin: 10, isVip: false, station: '面点档', status: 'cooking',
  },
];

// ─── Helpers ──────────────────────────────────────────────────
function getTicketAge(createdAt: number, timeLimitMin: number, currentTime: number): 'green' | 'yellow' | 'red' {
  const elapsedMs = currentTime - createdAt;
  const limitMs = timeLimitMin * 60 * 1000;
  if (elapsedMs >= limitMs) return 'red';
  if (elapsedMs >= limitMs * 0.5) return 'yellow';
  return 'green';
}

function formatCountdown(createdAt: number, timeLimitMin: number, currentTime: number): string {
  const elapsedMs = currentTime - createdAt;
  const limitMs = timeLimitMin * 60 * 1000;
  const remainingMs = limitMs - elapsedMs;

  if (remainingMs <= 0) {
    const overMs = Math.abs(remainingMs);
    const overMin = Math.floor(overMs / 60000);
    const overSec = Math.floor((overMs % 60000) / 1000);
    return `-${overMin}:${String(overSec).padStart(2, '0')}`;
  }

  const remMin = Math.floor(remainingMs / 60000);
  const remSec = Math.floor((remainingMs % 60000) / 1000);
  return `${remMin}:${String(remSec).padStart(2, '0')}`;
}

function formatElapsed(createdAt: number, currentTime: number): string {
  const ms = currentTime - createdAt;
  const totalMin = Math.floor(ms / 60000);
  return `${totalMin}分钟`;
}

// ─── Swipeable Ticket Card ────────────────────────────────────
const SWIPE_THRESHOLD = 72;

function TicketCard({
  ticket,
  currentTime,
  onFulfill,
}: {
  ticket: KDSTicket;
  currentTime: number;
  onFulfill: (id: string) => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const touchStartX = useRef(0);
  const touchCurrentX = useRef(0);
  const isSwiping = useRef(false);

  const age = getTicketAge(ticket.createdAt, ticket.timeLimitMin, currentTime);
  const countdown = formatCountdown(ticket.createdAt, ticket.timeLimitMin, currentTime);
  const elapsed = formatElapsed(ticket.createdAt, currentTime);
  const isOverdue = age === 'red';

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchCurrentX.current = e.touches[0].clientX;
    isSwiping.current = false;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    touchCurrentX.current = e.touches[0].clientX;
    const diff = touchStartX.current - touchCurrentX.current;

    if (diff > 30) {
      isSwiping.current = true;
    }

    if (isSwiping.current && cardRef.current) {
      const translateX = Math.max(-SWIPE_THRESHOLD - 20, -diff);
      cardRef.current.style.transform = `translateX(${Math.min(0, translateX)}px)`;
      cardRef.current.style.transition = 'none';
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    const diff = touchStartX.current - touchCurrentX.current;

    if (cardRef.current) {
      cardRef.current.style.transition = 'transform 0.3s ease';

      if (diff >= SWIPE_THRESHOLD) {
        cardRef.current.style.transform = 'translateX(-100%)';
        cardRef.current.style.opacity = '0';
        setTimeout(() => onFulfill(ticket.id), 300);
      } else {
        cardRef.current.style.transform = 'translateX(0)';
      }
    }

    isSwiping.current = false;
  }, [ticket.id, onFulfill]);

  const ageClass = age === 'green' ? styles.ticketGreen : age === 'yellow' ? styles.ticketYellow : styles.ticketRed;

  return (
    <div className={styles.ticketWrapper}>
      {/* Swipe reveal background */}
      <div className={styles.swipeReveal}>
        <span className={styles.swipeRevealText}>出餐完成</span>
      </div>
      <div
        ref={cardRef}
        className={`${styles.ticketCard} ${ageClass} ${ticket.isVip ? styles.ticketVip : ''} ${isOverdue ? styles.ticketPulse : ''}`}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Header */}
        <div className={styles.ticketHeader}>
          <div className={styles.ticketTableNo}>
            {ticket.tableNo}
            {ticket.isVip && <span className={styles.vipBadge}>VIP</span>}
          </div>
          <div className={`${styles.ticketCountdown} ${isOverdue ? styles.countdownOverdue : ''}`}>
            {countdown}
          </div>
        </div>

        {/* Items */}
        <div className={styles.ticketItems}>
          {ticket.items.map((item, idx) => (
            <div key={idx} className={styles.ticketItem}>
              <div className={styles.ticketItemRow}>
                {item.priority === 'rush' && <span className={styles.rushBadge}>加急</span>}
                <span className={styles.ticketItemName}>{item.name}</span>
                <span className={styles.ticketItemQty}>x{item.qty}</span>
              </div>
              {item.spec && <div className={styles.ticketItemSpec}>{item.spec}</div>}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className={styles.ticketFooter}>
          <span className={styles.ticketOrderId}>{ticket.orderId}</span>
          <span className={styles.ticketElapsed}>已等 {elapsed}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Fulfilled Ticket (collapsed) ────────────────────────────
function FulfilledCard({ ticket }: { ticket: KDSTicket & { fulfilledAt: number } }) {
  const totalItems = ticket.items.reduce((s, i) => s + i.qty, 0);
  const duration = Math.floor((ticket.fulfilledAt - ticket.createdAt) / 60000);
  return (
    <div className={styles.fulfilledCard}>
      <span className={styles.fulfilledTable}>{ticket.tableNo}</span>
      <span className={styles.fulfilledSummary}>{totalItems}道菜</span>
      <span className={styles.fulfilledDuration}>{duration}分钟</span>
      {ticket.isVip && <span className={styles.vipBadgeSmall}>VIP</span>}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────
export function KDSTicketGrid() {
  const [tickets, setTickets] = useState<KDSTicket[]>(INITIAL_TICKETS);
  const [fulfilledTickets, setFulfilledTickets] = useState<(KDSTicket & { fulfilledAt: number })[]>([]);
  const [activeStation, setActiveStation] = useState<Station>('全部');
  const [currentTime, setCurrentTime] = useState(Date.now());
  const [showFulfilled, setShowFulfilled] = useState(true);

  // TODO: Audio.play() on new ticket

  // Update timer every second
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleFulfill = useCallback((id: string) => {
    setTickets(prev => {
      const ticket = prev.find(t => t.id === id);
      if (ticket) {
        setFulfilledTickets(fp => [{ ...ticket, status: 'fulfilled' as const, fulfilledAt: Date.now() }, ...fp].slice(0, 20));
      }
      return prev.filter(t => t.id !== id);
    });
  }, []);

  // Filtered active tickets
  const activeTickets = tickets
    .filter(t => t.status !== 'fulfilled')
    .filter(t => activeStation === '全部' || t.station === activeStation);

  // Stats
  const pendingCount = tickets.filter(t => t.status === 'pending').length;
  const cookingCount = tickets.filter(t => t.status === 'cooking').length;
  const overdueCount = tickets.filter(t =>
    t.status !== 'fulfilled' &&
    getTicketAge(t.createdAt, t.timeLimitMin, currentTime) === 'red'
  ).length;
  const avgTimeMin = fulfilledTickets.length > 0
    ? Math.round(fulfilledTickets.reduce((s, t) => s + (t.fulfilledAt - t.createdAt) / 60000, 0) / fulfilledTickets.length)
    : 0;

  return (
    <div className={styles.container}>
      {/* ─── Stats Bar ──────────────────────────────────────── */}
      <div className={styles.statsBar}>
        <div className={styles.statsTitle}>后厨出餐看板</div>
        <div className={styles.statsItems}>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>待出</span>
            <span className={styles.statValue}>{pendingCount + cookingCount}</span>
          </div>
          <div className={`${styles.statItem} ${overdueCount > 0 ? styles.statDanger : ''}`}>
            <span className={styles.statLabel}>超时</span>
            <span className={`${styles.statValue} ${overdueCount > 0 ? styles.statValueDanger : ''}`}>
              {overdueCount}
            </span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statLabel}>平均出餐</span>
            <span className={styles.statValue}>{avgTimeMin > 0 ? `${avgTimeMin}分` : '--'}</span>
          </div>
        </div>
      </div>

      <div className={styles.mainLayout}>
        {/* ─── Station Filter Sidebar ─────────────────────── */}
        <div className={styles.sidebar}>
          {STATIONS.map(station => (
            <button
              key={station}
              className={`${styles.stationBtn} ${activeStation === station ? styles.stationBtnActive : ''}`}
              onClick={() => setActiveStation(station)}
            >
              {station}
              {station !== '全部' && (
                <span className={styles.stationCount}>
                  {tickets.filter(t => t.status !== 'fulfilled' && t.station === station).length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* ─── Ticket Grid ────────────────────────────────── */}
        <div className={styles.gridArea}>
          <div className={styles.ticketGrid}>
            {activeTickets.length === 0 && (
              <div className={styles.emptyState}>
                <span className={styles.emptyIcon}>&#10003;</span>
                <span className={styles.emptyText}>当前无待出订单</span>
              </div>
            )}
            {activeTickets.map(ticket => (
              <TicketCard
                key={ticket.id}
                ticket={ticket}
                currentTime={currentTime}
                onFulfill={handleFulfill}
              />
            ))}
          </div>

          {/* ─── Recently Fulfilled ──────────────────────── */}
          {fulfilledTickets.length > 0 && (
            <div className={styles.fulfilledSection}>
              <button
                className={styles.fulfilledToggle}
                onClick={() => setShowFulfilled(!showFulfilled)}
              >
                <span>已完成 ({fulfilledTickets.length})</span>
                <span className={`${styles.fulfilledArrow} ${showFulfilled ? styles.fulfilledArrowOpen : ''}`}>
                  &#9662;
                </span>
              </button>
              {showFulfilled && (
                <div className={styles.fulfilledList}>
                  {fulfilledTickets.map(ticket => (
                    <FulfilledCard key={ticket.id} ticket={ticket} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default KDSTicketGrid;
