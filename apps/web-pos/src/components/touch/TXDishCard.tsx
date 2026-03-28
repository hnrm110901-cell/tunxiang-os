/**
 * TXDishCard — POS 菜品卡片（触控优化）
 *
 * 规范:
 *   - 最小尺寸 120×140px
 *   - 沽清态: 灰色遮罩 + "已沽清"
 *   - 已点态: 右上角橙色数量角标
 *   - 长按: 查看详情/做法选择
 *   - 触控反馈: 按下 scale(0.97)
 */
import { useRef, useCallback } from 'react';
import styles from './TXDishCard.module.css';

export interface TXDishCardProps {
  name: string;
  price: number;           // 分为单位
  image?: string;
  tags?: string[];         // 如"招牌""辣""新品"
  soldOut?: boolean;
  quantity?: number;       // 已点数量
  onPress: () => void;
  onLongPress?: () => void;
}

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(fen % 100 === 0 ? 0 : 2)}`;

export function TXDishCard({
  name,
  price,
  image,
  tags,
  soldOut = false,
  quantity = 0,
  onPress,
  onLongPress,
}: TXDishCardProps) {
  const longPressTimer = useRef<ReturnType<typeof setTimeout>>();

  const handleTouchStart = useCallback(() => {
    if (onLongPress) {
      longPressTimer.current = setTimeout(onLongPress, 500);
    }
  }, [onLongPress]);

  const handleTouchEnd = useCallback(() => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = undefined;
    }
  }, []);

  const handleClick = useCallback(() => {
    if (!soldOut) onPress();
  }, [soldOut, onPress]);

  return (
    <div
      className={`${styles.card} ${soldOut ? styles.soldOut : ''} tx-pressable`}
      onClick={handleClick}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleTouchEnd}
      role="button"
      aria-disabled={soldOut}
      aria-label={`${name} ${fen2yuan(price)}${soldOut ? ' 已沽清' : ''}`}
    >
      {/* 菜品图片 */}
      {image ? (
        <div className={styles.imageWrap}>
          <img src={image} alt={name} className={styles.image} loading="lazy" />
        </div>
      ) : (
        <div className={styles.imagePlaceholder}>
          <span className={styles.placeholderIcon}>🍽</span>
        </div>
      )}

      {/* 菜品信息 */}
      <div className={styles.info}>
        <div className={styles.name}>{name}</div>
        <div className={styles.price}>{fen2yuan(price)}</div>
      </div>

      {/* 标签 */}
      {tags && tags.length > 0 && (
        <div className={styles.tags}>
          {tags.map(tag => (
            <span key={tag} className={styles.tag}>{tag}</span>
          ))}
        </div>
      )}

      {/* 已点数量角标 */}
      {quantity > 0 && (
        <div className={styles.badge}>{quantity > 99 ? '99+' : quantity}</div>
      )}

      {/* 沽清遮罩 */}
      {soldOut && (
        <div className={styles.soldOutOverlay}>
          <span className={styles.soldOutText}>已沽清</span>
        </div>
      )}
    </div>
  );
}
