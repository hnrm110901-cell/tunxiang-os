import React, { useState, useEffect } from 'react';
import { useSwipe } from '../../hooks/useSwipe';
import styles from './TXKDSTicket.module.css';

export interface TXKDSTicketItem {
  name: string;
  qty: number;
  spec?: string;
  priority: 'normal' | 'rush';
}

export interface TXKDSTicketProps {
  orderId: string;
  tableNo: string;
  items: TXKDSTicketItem[];
  createdAt: Date;
  /** 出餐时限，单位：分钟 */
  timeLimit: number;
  isVip?: boolean;
  onComplete: () => void;
  onRush: () => void;
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function formatCountdown(secondsLeft: number): string {
  if (secondsLeft <= 0) {
    const abs = Math.abs(secondsLeft);
    return `-${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
  }
  return `${pad(Math.floor(secondsLeft / 60))}:${pad(secondsLeft % 60)}`;
}

export function TXKDSTicket({
  orderId,
  tableNo,
  items,
  createdAt,
  timeLimit,
  isVip = false,
  onComplete,
  onRush,
}: TXKDSTicketProps) {
  const totalSeconds = timeLimit * 60;
  const [secondsLeft, setSecondsLeft] = useState<number>(() => {
    const elapsed = Math.floor((Date.now() - createdAt.getTime()) / 1000);
    return totalSeconds - elapsed;
  });

  useEffect(() => {
    const interval = setInterval(() => {
      setSecondsLeft(() => {
        const elapsed = Math.floor((Date.now() - createdAt.getTime()) / 1000);
        return totalSeconds - elapsed;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [createdAt, totalSeconds]);

  // 颜色编码判断
  const ratio = secondsLeft / totalSeconds;
  const isOverdue = secondsLeft <= 0;
  const isUrgent = !isOverdue && ratio <= 0.5;

  // 左滑完成
  const swipeHandlers = useSwipe({
    threshold: 72,
    onSwipeEnd: (direction) => {
      if (direction === 'left') {
        onComplete();
      }
    },
  });

  const cardClass = [
    styles.ticket,
    isOverdue ? styles.overdue : '',
  ]
    .filter(Boolean)
    .join(' ');

  const countdownClass = [
    styles.countdown,
    isOverdue ? styles.countdownOverdue : '',
    isUrgent ? styles.countdownUrgent : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={cardClass} {...swipeHandlers}>
      {/* 头部：桌号 + VIP标识 */}
      <div className={styles.header}>
        <span className={styles.tableNo}>桌 {tableNo}</span>
        <div className={styles.headerRight}>
          {isVip && <span className={styles.vipBadge}>VIP</span>}
          <button
            type="button"
            className={styles.rushBtn}
            onClick={onRush}
            aria-label="加急"
          >
            加急
          </button>
        </div>
      </div>

      {/* 倒计时 */}
      <div className={countdownClass} aria-live="polite" aria-label={`剩余时间 ${formatCountdown(secondsLeft)}`}>
        {formatCountdown(secondsLeft)}
      </div>

      {/* 菜品列表 */}
      <ul className={styles.items}>
        {items.map((item, idx) => (
          <li key={`${item.name}-${idx}`} className={styles.item}>
            <span className={styles.itemName}>
              {item.priority === 'rush' && (
                <span className={styles.rushIcon} aria-label="加急">!</span>
              )}
              {item.name}
              {item.spec && <span className={styles.itemSpec}>{item.spec}</span>}
            </span>
            <span className={styles.itemQty}>×{item.qty}</span>
          </li>
        ))}
      </ul>

      {/* 底部提示 */}
      <div className={styles.footer}>
        <span className={styles.swipeHint}>← 滑动完成</span>
        <span className={styles.orderId}>#{orderId.slice(-6)}</span>
      </div>
    </div>
  );
}

export default TXKDSTicket;
