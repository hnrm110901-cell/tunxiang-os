/**
 * QueueTicket — 排队号牌卡片
 *
 * 跨端共享组件，用于：
 *   - web-reception 排队叫号屏
 *   - web-reception 前台面板
 *   - h5 顾客端排队进度查看
 *   - web-pos 收银台排队提示
 *
 * 展示：排队号码、桌型、人数、等待时长、状态、操作按钮
 */
import styles from './QueueTicket.module.css';
import { cn } from '../../utils/cn';

export type QueueTicketStatus = 'waiting' | 'called' | 'seated' | 'skipped' | 'cancelled';
export type TableSize = 'small' | 'medium' | 'large';

export interface QueueTicketData {
  id: string;
  /** 排队号码，如 "S001" / "大03" */
  number: string;
  size: TableSize;
  guestCount: number;
  customerName?: string;
  phone?: string;
  status: QueueTicketStatus;
  /** 取号时间 HH:mm */
  takenAt: string;
  /** 已等待分钟 */
  waitMinutes: number;
  /** 预估剩余等待分钟 */
  estimatedWait?: number;
}

export interface QueueTicketProps {
  ticket: QueueTicketData;
  /** 紧凑模式（适合列表行） */
  compact?: boolean;
  /** 叫号 */
  onCall?: (ticket: QueueTicketData) => void;
  /** 入座 */
  onSeat?: (ticket: QueueTicketData) => void;
  /** 过号 */
  onSkip?: (ticket: QueueTicketData) => void;
  onClick?: (ticket: QueueTicketData) => void;
}

const STATUS_META: Record<QueueTicketStatus, { label: string; className: string }> = {
  waiting:   { label: '等待中', className: 'statusWaiting' },
  called:    { label: '已叫号', className: 'statusCalled' },
  seated:    { label: '已入座', className: 'statusSeated' },
  skipped:   { label: '过号', className: 'statusSkipped' },
  cancelled: { label: '已取消', className: 'statusCancelled' },
};

const SIZE_META: Record<TableSize, { label: string; icon: string }> = {
  small:  { label: '小桌', icon: '🪑' },
  medium: { label: '中桌', icon: '🍽' },
  large:  { label: '大桌', icon: '🏛' },
};

export default function QueueTicket({
  ticket,
  compact,
  onCall,
  onSeat,
  onSkip,
  onClick,
}: QueueTicketProps) {
  const statusMeta = STATUS_META[ticket.status] ?? STATUS_META.waiting;
  const sizeMeta = SIZE_META[ticket.size] ?? SIZE_META.small;

  const isActive = ticket.status === 'waiting' || ticket.status === 'called';
  const isUrgent = ticket.waitMinutes >= 30 && ticket.status === 'waiting';

  return (
    <div
      className={cn(
        styles.card,
        compact && styles.compact,
        !isActive && styles.inactive,
        isUrgent && styles.urgent,
        ticket.status === 'called' && styles.called,
      )}
      onClick={() => onClick?.(ticket)}
    >
      {/* Number + Status */}
      <div className={styles.header}>
        <span className={cn(styles.number, ticket.status === 'called' && styles.numberCalled)}>
          {ticket.number}
        </span>
        <span className={cn(styles.statusBadge, styles[statusMeta.className])}>
          {statusMeta.label}
        </span>
      </div>

      {/* Info row */}
      <div className={styles.infoRow}>
        <span className={styles.sizeBadge}>
          {sizeMeta.label} · {ticket.guestCount}人
        </span>
        {ticket.customerName && (
          <span className={styles.name}>{ticket.customerName}</span>
        )}
        <span className={cn(styles.waitTime, isUrgent && styles.waitTimeUrgent)}>
          {ticket.waitMinutes > 0 ? `${ticket.waitMinutes}分钟` : '刚取号'}
        </span>
      </div>

      {/* Estimated wait (for waiting status) */}
      {ticket.status === 'waiting' && ticket.estimatedWait != null && ticket.estimatedWait > 0 && (
        <div className={styles.estimate}>
          预计还需 ~{ticket.estimatedWait} 分钟
        </div>
      )}

      {/* Actions */}
      {isActive && (onCall || onSeat || onSkip) && (
        <div className={styles.actions}>
          {onCall && ticket.status === 'waiting' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.callBtn)}
              onClick={(e) => { e.stopPropagation(); onCall(ticket); }}
            >
              叫号
            </button>
          )}
          {onSeat && (ticket.status === 'called' || ticket.status === 'waiting') && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.seatBtn)}
              onClick={(e) => { e.stopPropagation(); onSeat(ticket); }}
            >
              入座
            </button>
          )}
          {onSkip && ticket.status === 'waiting' && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.skipBtn)}
              onClick={(e) => { e.stopPropagation(); onSkip(ticket); }}
            >
              过号
            </button>
          )}
        </div>
      )}
    </div>
  );
}
