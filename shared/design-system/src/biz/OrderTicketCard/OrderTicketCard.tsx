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
  /** 当前时间戳（ms），用于计算倒计时 */
  now?: number;
  onStart?: (ticket: OrderTicketData) => void;
  onComplete?: (ticket: OrderTicketData) => void;
  onRush?: (ticket: OrderTicketData) => void;
  onClick?: (ticket: OrderTicketData) => void;
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
  now,
  onStart,
  onComplete,
  onRush,
  onClick,
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

  const isOvertime = ticket.timeoutMinutes != null && elapsed.totalMins >= ticket.timeoutMinutes;

  const servedCount = ticket.items.filter((i) => i.served).length;
  const totalCount = ticket.items.length;

  return (
    <div
      className={cn(
        styles.card,
        compact && styles.compact,
        isOvertime && styles.overtime,
        ticket.priority === 'rush' && styles.rush,
        ticket.priority === 'vip' && styles.vip,
      )}
      onClick={() => onClick?.(ticket)}
    >
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.tableNo}>{ticket.tableNo}</span>
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
          <span className={cn(styles.statusBadge, styles[statusMeta.className])}>
            {statusMeta.label}
          </span>
          <span className={cn(styles.timer, isOvertime && styles.timerOvertime)}>
            {elapsed.mins}:{elapsed.secs.toString().padStart(2, '0')}
          </span>
        </div>
      </div>

      {/* Order number */}
      <div className={styles.orderNoRow}>
        <span className={styles.orderNo}>#{ticket.orderNo}</span>
        {ticket.guestCount != null && (
          <span className={styles.guestCount}>{ticket.guestCount}人</span>
        )}
        {totalCount > 0 && (
          <span className={styles.progress}>
            {servedCount}/{totalCount}
          </span>
        )}
      </div>

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

      {/* Remark */}
      {ticket.remark && (
        <div className={styles.ticketRemark}>
          <span className={styles.remarkIcon}>!</span> {ticket.remark}
        </div>
      )}

      {/* Actions */}
      {(onStart || onComplete || onRush) && (
        <div className={styles.actions}>
          {onRush && ticket.status === 'pending' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.rushBtn)}
              onClick={(e) => { e.stopPropagation(); onRush(ticket); }}
            >
              催单
            </button>
          )}
          {onStart && ticket.status === 'pending' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.startBtn)}
              onClick={(e) => { e.stopPropagation(); onStart(ticket); }}
            >
              开始制作
            </button>
          )}
          {onComplete && ticket.status === 'cooking' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.completeBtn)}
              onClick={(e) => { e.stopPropagation(); onComplete(ticket); }}
            >
              出餐完成
            </button>
          )}
        </div>
      )}
    </div>
  );
}
