/**
 * DishGrid -- 菜品网格/列表容器，支持虚拟滚动
 *
 * - dishes.length <= virtualThreshold: 普通 CSS grid / flex 渲染
 * - dishes.length >  virtualThreshold: 基于 IntersectionObserver 的轻量虚拟滚动
 * - 不依赖 react-window 或其他外部虚拟滚动库
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { cn } from '../../utils/cn';
import DishCard from '../DishCard/DishCard';
import type { DishData } from '../DishCard/types';
import styles from './DishGrid.module.css';

export interface DishGridProps {
  dishes: DishData[];
  variant: 'grid' | 'horizontal';
  quantities?: Record<string, number>;
  onAddDish: (dish: DishData) => void;
  onTapDish?: (dish: DishData) => void;
  /** Enable virtual scrolling when dish count > threshold (default 50) */
  virtualThreshold?: number;
  className?: string;
}

/* ---------- estimated item dimensions ---------- */
const GRID_ROW_HEIGHT = 180;
const HORIZONTAL_ITEM_HEIGHT = 100;
const BUFFER_COUNT = 10;

/* ---------- simple (non-virtual) renderer ---------- */
function SimpleGrid({
  dishes,
  variant,
  quantities,
  onAddDish,
  onTapDish,
  className,
}: Omit<DishGridProps, 'virtualThreshold'>) {
  return (
    <div
      className={cn(
        variant === 'grid' ? styles.gridLayout : styles.horizontalLayout,
        className,
      )}
    >
      {dishes.map((dish) => (
        <DishCard
          key={dish.id}
          variant={variant}
          dish={dish}
          quantity={quantities?.[dish.id]}
          onAdd={() => onAddDish(dish)}
          onTap={onTapDish ? () => onTapDish(dish) : undefined}
        />
      ))}
    </div>
  );
}

/* ---------- virtual scroll renderer ---------- */

/**
 * Lightweight virtual scroll using IntersectionObserver.
 *
 * Strategy:
 *  - Render a spacer div whose total height equals items * rowHeight.
 *  - Track the visible range via a sentinel element placed in the middle.
 *  - Only render items within [visibleStart - BUFFER, visibleEnd + BUFFER].
 */
function VirtualGrid({
  dishes,
  variant,
  quantities,
  onAddDish,
  onTapDish,
  className,
}: Omit<DishGridProps, 'virtualThreshold'>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [visibleRange, setVisibleRange] = useState({ start: 0, end: 30 });

  const itemHeight = variant === 'grid' ? GRID_ROW_HEIGHT : HORIZONTAL_ITEM_HEIGHT;

  // For grid variant, estimate columns from container width
  const [columns, setColumns] = useState(variant === 'grid' ? 3 : 1);

  useEffect(() => {
    if (variant !== 'grid') {
      setColumns(1);
      return;
    }
    const container = containerRef.current;
    if (!container) return;

    const measure = () => {
      const w = container.clientWidth;
      // minmax(148px, 1fr) with 10px gap
      const cols = Math.max(1, Math.floor((w + 10) / (148 + 10)));
      setColumns(cols);
    };
    measure();

    const ro = new ResizeObserver(measure);
    ro.observe(container);
    return () => ro.disconnect();
  }, [variant]);

  const totalRows = Math.ceil(dishes.length / columns);
  const totalHeight = totalRows * itemHeight;

  // Scroll handler: compute visible range
  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const scrollTop = container.scrollTop;
    const viewportHeight = container.clientHeight;

    const startRow = Math.floor(scrollTop / itemHeight);
    const endRow = Math.ceil((scrollTop + viewportHeight) / itemHeight);

    const startIndex = Math.max(0, (startRow - BUFFER_COUNT) * columns);
    const endIndex = Math.min(dishes.length, (endRow + BUFFER_COUNT) * columns);

    setVisibleRange({ start: startIndex, end: endIndex });
  }, [columns, itemHeight, dishes.length]);

  // Initial measurement + scroll listener
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    handleScroll();
    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  // Slice visible dishes
  const visibleDishes = useMemo(
    () => dishes.slice(visibleRange.start, visibleRange.end),
    [dishes, visibleRange.start, visibleRange.end],
  );

  // Offset for the first visible item
  const startRow = Math.floor(visibleRange.start / columns);
  const offsetTop = startRow * itemHeight;

  return (
    <div
      ref={containerRef}
      className={cn(styles.virtualContainer, className)}
    >
      <div className={styles.virtualSpacer} style={{ height: totalHeight }}>
        <div
          className={
            variant === 'grid' ? styles.gridLayout : styles.horizontalLayout
          }
          style={{
            position: 'absolute',
            top: offsetTop,
            left: 0,
            right: 0,
          }}
        >
          {visibleDishes.map((dish) => (
            <DishCard
              key={dish.id}
              variant={variant}
              dish={dish}
              quantity={quantities?.[dish.id]}
              onAdd={() => onAddDish(dish)}
              onTap={onTapDish ? () => onTapDish(dish) : undefined}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- DishGrid (public API) ---------- */
export default function DishGrid({
  dishes,
  variant,
  quantities,
  onAddDish,
  onTapDish,
  virtualThreshold = 50,
  className,
}: DishGridProps) {
  const useVirtual = dishes.length > virtualThreshold;

  const Renderer = useVirtual ? VirtualGrid : SimpleGrid;

  return (
    <Renderer
      dishes={dishes}
      variant={variant}
      quantities={quantities}
      onAddDish={onAddDish}
      onTapDish={onTapDish}
      className={className}
    />
  );
}
