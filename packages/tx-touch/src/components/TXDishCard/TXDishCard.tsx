import React from 'react';
import { useLongPress } from '../../hooks/useLongPress';
import { fenToYuan } from '../../utils/currency';
import styles from './TXDishCard.module.css';

export interface TXDishCardProps {
  name: string;
  /** 价格，单位：分（整数） */
  price: number;
  image?: string;
  tags?: string[];
  soldOut?: boolean;
  /** 已点数量，>0 时右上角显示橙色角标 */
  quantity?: number;
  onPress: () => void;
  onLongPress?: () => void;
}

export function TXDishCard({
  name,
  price,
  image,
  tags = [],
  soldOut = false,
  quantity = 0,
  onPress,
  onLongPress,
}: TXDishCardProps) {
  const longPressHandlers = useLongPress(
    () => onLongPress?.(),
    500,
  );

  const handleClick = () => {
    if (!soldOut) {
      onPress();
    }
  };

  return (
    <div
      className={`${styles.card} ${soldOut ? styles.soldOut : ''}`}
      onClick={handleClick}
      {...longPressHandlers}
    >
      {/* 图片区域 */}
      <div className={styles.imageWrapper}>
        {image ? (
          <img src={image} alt={name} className={styles.image} />
        ) : (
          <div className={styles.imagePlaceholder} aria-hidden="true" />
        )}
        {/* 已点数量角标 */}
        {quantity > 0 && (
          <span className={styles.quantityBadge} aria-label={`已点${quantity}份`}>
            {quantity >= 10 ? '9+' : quantity}
          </span>
        )}
      </div>

      {/* 信息区域 */}
      <div className={styles.info}>
        <p className={styles.name}>{name}</p>

        {tags.length > 0 && (
          <div className={styles.tags}>
            {tags.map((tag) => (
              <span key={tag} className={styles.tag}>
                {tag}
              </span>
            ))}
          </div>
        )}

        <p className={styles.price}>¥{fenToYuan(price)}</p>
      </div>

      {/* 已沽清遮罩 */}
      {soldOut && (
        <div className={styles.soldOutOverlay} aria-label="已沽清">
          <span className={styles.soldOutText}>已沽清</span>
        </div>
      )}
    </div>
  );
}

export default TXDishCard;
