/**
 * OrderTicketCard — 订单/出餐工单卡片
 *
 * 多端共享组件，用于：
 *   - KDS 出餐屏（KitchenBoard / SwimLaneBoard / StationBoard）
 *   - 服务员PWA 订单详情
 *   - POS 订单列表
 *
 * 展示：桌号、单号、菜品列表、状态、倒计时、操作按钮
 */
import React, { useMemo } from 'react';
import styles from './OrderTicketCard.module.css';
import { cn } from '../../utils/cn';
import { useSwipe } from '../../hooks/useSwipe';

export interface TicketDishItem {
  id: string;
  name: string;
  qty: number;
  /** 做法/规格 */
  spec?: string;
  /** 备注 */
  remark?: string;
  /** 是否已出 */
  served?: boolean;
}

export type TicketStatus = 'pending' | 'cooking' | 'done' | 'timeout' | 'cancelled';
export type TicketPriority = 'normal' | 'rush' | 'vip';

export interface OrderTicketData {
  id: string;
  orderNo: string;
  tableNo: string;
  items: TicketDishItem[];
  status: TicketStatus;
  priority?: TicketPriority;
  /** 下单时间 ISO */
  createdAt: string;
  /** 超时阈值（分钟） */
  timeoutMinutes?: number;
  /** 渠道标签 */
  channel?: string;
  /** 人数 */
  guestCount?: number;
  /** 备注 */
  remark?: string;
}

export interface OrderTicketCardProps {
  ticket: OrderTicketData;
  /** 紧凑模式（KDS横排） */
  compact?: boolean;
  /** KDS大屏模式（大字体 + 大按钮） */
  kds?: boolean;
  /** 当前时间戳（ms），用于计算倒计时 */
  now?: number;
  /** 是否暂停出品 */
  isPaused?: boolean;
  /** 催单闪烁 */
  isFlashing?: boolean;
  /** 自定义主操作按钮文案（覆盖默认的"开始制作"/"出餐完成"） */
  actionLabel?: string;
  onStart?: (ticket: OrderTicketData) => void;
  onComplete?: (ticket: OrderTicketData) => void;
  onRush?: (ticket: OrderTicketData) => void;
  /** 停菜/恢复回调 */
  onPause?: (ticket: OrderTicketData) => void;
  /** 抢单回调 */
  onGrab?: (ticket: OrderTicketData) => void;
  onClick?: (ticket: OrderTicketData) => void;
  /** 启用左滑手势（KDS 大屏左滑完成出餐） */
  swipeable?: boolean;
  /** 左滑完成回调（swipeable=true 时使用） */
  onSwipeComplete?: (ticket: OrderTicketData) => void;
  /** 左滑底层提示文案（默认 "完成"） */
  swipeLabel?: string;
}

const STATUS_META: Record<TicketStatus, { label: string; className: string }> = {
  pending:   { label: '等待', className: 'statusPending' },
  cooking:   { label: '制作中', className: 'statusCooking' },
  done:      { label: '已出', className: 'statusDone' },
  timeout:   { label: '超时', className: 'statusTimeout' },
  cancelled: { label: '已取消', className: 'statusCancelled' },
};

const PRIORITY_META: Record<TicketPriority, { label: string; className: string }> = {
  normal: { label: '', className: '' },
  rush:   { label: '加急', className: 'priorityRush' },
  vip:    { label: 'VIP', className: 'priorityVip' },
};

export default function OrderTicketCard({
  ticket,
  compact,
  kds,
  now,
  isPaused,
  isFlashing,
  actionLabel,
  onStart,
  onComplete,
  onRush,
  onPause,
  onGrab,
  onClick,
  swipeable,
  onSwipeComplete,
  swipeLabel = '完成',
}: OrderTicketCardProps) {
  const statusMeta = STATUS_META[ticket.status] ?? STATUS_META.pending;
  const priorityMeta = PRIORITY_META[ticket.priority ?? 'normal'];

  // Calculate elapsed time
  const elapsed = useMemo(() => {
    const currentTime = now ?? Date.now();
    const created = new Date(ticket.createdAt).getTime();
    const diffMs = currentTime - created;
    const mins = Math.floor(diffMs / 60000);
    const secs = Math.floor((diffMs % 60000) / 1000);
    return { mins, secs, totalMins: mins };
  }, [now, ticket.createdAt]);

  // Time level for color coding
  const timeLevel: 'normal' | 'warning' | 'critical' = useMemo(() => {
    const timeout = ticket.timeoutMinutes ?? 25;
    const warn = Math.max(Math.floor(timeout * 0.6), 5);
    if (elapsed.totalMins >= timeout) return 'critical';
    if (elapsed.totalMins >= warn) return 'warning';
    return 'normal';
  }, [elapsed.totalMins, ticket.timeoutMinutes]);

  const isOvertime = timeLevel === 'critical';

  const servedCount = ticket.items.filter((i) => i.served).length;
  const totalCount = ticket.items.length;

  const hasActions = onStart || onComplete || onRush || onGrab || onPause;

  // Swipe gesture (optional, KDS left-swipe-to-complete)
  const { swipeHandlers, swipeOffset, isSwiping } = useSwipe({
    onSwipeLeft: swipeable && onSwipeComplete ? () => onSwipeComplete(ticket) : undefined,
    threshold: 72,
  });

  const cardContent = (
    <div
      className={cn(
        styles.card,
        compact && styles.compact,
        kds && styles.kds,
        isOvertime && styles.overtime,
        isFlashing && styles.flashing,
        isPaused && styles.paused,
        ticket.priority === 'rush' && styles.rush,
        ticket.priority === 'vip' && styles.vip,
      )}
      style={swipeable ? {
        transform: `translateX(${swipeOffset}px)`,
        transition: isSwiping ? 'none' : 'transform 0.25s ease',
        cursor: isSwiping ? 'grabbing' : 'grab',
        userSelect: 'none',
      } : undefined}
      {...(swipeable ? swipeHandlers : {})}
      onClick={() => onClick?.(ticket)}
    >
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.tableNo}>{ticket.tableNo}</span>
          <span className={styles.orderNo}>#{ticket.orderNo}</span>
          {ticket.channel && (
            <span className={styles.channelBadge}>{ticket.channel}</span>
          )}
          {priorityMeta.label && (
            <span className={cn(styles.priorityBadge, styles[priorityMeta.className])}>
              {priorityMeta.label}
            </span>
          )}
        </div>
        <div className={styles.headerRight}>
          <span className={cn(
            styles.timer,
            styles[`time${timeLevel.charAt(0).toUpperCase()}${timeLevel.slice(1)}`],
          )}>
            {elapsed.mins}:{elapsed.secs.toString().padStart(2, '0')}
          </span>
        </div>
      </div>

      {/* Meta row */}
      {(ticket.guestCount != null || totalCount > 0) && (
        <div className={styles.orderNoRow}>
          {ticket.guestCount != null && (
            <span className={styles.guestCount}>{ticket.guestCount}人</span>
          )}
          {totalCount > 0 && (
            <span className={styles.progress}>
              {servedCount}/{totalCount}
            </span>
          )}
        </div>
      )}

      {/* Dish list */}
      <div className={styles.dishList}>
        {ticket.items.map((item) => (
          <div
            key={item.id}
            className={cn(styles.dishRow, item.served && styles.dishServed)}
          >
            <span className={styles.dishQty}>x{item.qty}</span>
            <span className={styles.dishName}>{item.name}</span>
            {item.spec && <span className={styles.dishSpec}>{item.spec}</span>}
            {item.remark && <span className={styles.dishRemark}>{item.remark}</span>}
          </div>
        ))}
      </div>

      {/* Pause indicator */}
      {isPaused && (
        <div className={styles.pausedBanner}>
          ⏸ 已停菜 — 暂缓出品
        </div>
      )}

      {/* Remark */}
      {ticket.remark && (
        <div className={styles.ticketRemark}>
          <span className={styles.remarkIcon}>!</span> {ticket.remark}
        </div>
      )}

      {/* Actions */}
      {hasActions && (
        <div className={styles.actions}>
          {/* Grab mode button (highest priority) */}
          {onGrab && ticket.status === 'pending' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.grabBtn)}
              onClick={(e) => { e.stopPropagation(); onGrab(ticket); }}
            >
              抢单
            </button>
          )}
          {/* Rush button */}
          {onRush && ticket.status === 'pending' && !onGrab && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.rushBtn)}
              onClick={(e) => { e.stopPropagation(); onRush(ticket); }}
            >
              催单
            </button>
          )}
          {/* Primary action (start/complete) */}
          {onStart && ticket.status === 'pending' && !onGrab && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.startBtn)}
              disabled={isPaused}
              onClick={(e) => { e.stopPropagation(); onStart(ticket); }}
            >
              {actionLabel ?? '开始制作'}
            </button>
          )}
          {onComplete && ticket.status === 'cooking' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.completeBtn)}
              disabled={isPaused}
              onClick={(e) => { e.stopPropagation(); onComplete(ticket); }}
            >
              {actionLabel ?? '完成出品'}
            </button>
          )}
          {/* Pause/Resume toggle */}
          {onPause && ticket.status === 'cooking' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.pauseBtn, isPaused && styles.pauseBtnActive)}
              onClick={(e) => { e.stopPropagation(); onPause(ticket); }}
            >
              {isPaused ? '▶' : '⏸'}
            </button>
          )}
        </div>
      )}

      {/* Swipe hint text (cooking state) */}
      {swipeable && ticket.status === 'cooking' && (
        <div className={styles.swipeHint}>
          左滑完成出餐
        </div>
      )}
    </div>
  );

  // Swipeable wrapper: card sits on top of reveal layer
  if (swipeable) {
    return (
      <div className={styles.swipeWrapper}>
        {/* Reveal layer behind card */}
        <div
          className={styles.swipeReveal}
          style={{
            opacity: isSwiping && swipeOffset < -20
              ? Math.min(1, Math.abs(swipeOffset) / 72)
              : 0,
            transition: isSwiping ? 'none' : 'opacity 0.2s',
          }}
        >
          <span className={styles.swipeRevealText}>{swipeLabel}</span>
        </div>
        {cardContent}
      </div>
    );
  }

  return cardContent;
}
