import React, { useRef, useCallback } from 'react';
import styles from './TXScrollList.module.css';

export interface TXScrollListProps<T> {
  data: T[];
  renderItem: (item: T, index: number) => React.ReactNode;
  keyExtractor: (item: T) => string;
  onEndReached?: () => void;
  /** 水平滚动（用于KDS工单横排） */
  horizontal?: boolean;
  style?: React.CSSProperties;
  className?: string;
}

export function TXScrollList<T>({
  data,
  renderItem,
  keyExtractor,
  onEndReached,
  horizontal = false,
  style,
  className,
}: TXScrollListProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const endReachedCalledRef = useRef(false);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el || !onEndReached) return;

    if (horizontal) {
      const distanceFromEnd = el.scrollWidth - el.scrollLeft - el.clientWidth;
      if (distanceFromEnd < 80 && !endReachedCalledRef.current) {
        endReachedCalledRef.current = true;
        onEndReached();
      } else if (distanceFromEnd >= 80) {
        endReachedCalledRef.current = false;
      }
    } else {
      const distanceFromEnd = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (distanceFromEnd < 80 && !endReachedCalledRef.current) {
        endReachedCalledRef.current = true;
        onEndReached();
      } else if (distanceFromEnd >= 80) {
        endReachedCalledRef.current = false;
      }
    }
  }, [horizontal, onEndReached]);

  const containerClass = [
    styles.container,
    horizontal ? styles.horizontal : styles.vertical,
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      ref={containerRef}
      className={containerClass}
      style={style}
      onScroll={handleScroll}
    >
      {data.map((item, index) => (
        <div key={keyExtractor(item)} className={styles.item}>
          {renderItem(item, index)}
        </div>
      ))}
    </div>
  );
}

export default TXScrollList;
