/**
 * CategoryNav — 菜品分类导航
 *
 * 两种 layout：
 *  - sidebar: 垂直列表（80px 宽），左侧边栏 —— H5 点餐
 *  - topbar:  水平滚动标签，自动居中激活项 —— 服务员 / 加菜
 */
import { useRef, useEffect, useCallback } from 'react';
import { cn } from '../../utils/cn';
import styles from './CategoryNav.module.css';

export interface CategoryNavProps {
  categories: Array<{ id: string; name: string; icon?: string; count?: number }>;
  activeId: string;
  layout: 'sidebar' | 'topbar';
  onSelect: (categoryId: string) => void;
  className?: string;
}

export default function CategoryNav({
  categories,
  activeId,
  layout,
  onSelect,
  className,
}: CategoryNavProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLButtonElement>(null);

  // Auto-center active tab in topbar layout
  const scrollActiveIntoView = useCallback(() => {
    if (layout !== 'topbar' || !activeRef.current || !scrollRef.current) return;
    const container = scrollRef.current;
    const el = activeRef.current;
    const scrollLeft = el.offsetLeft - container.clientWidth / 2 + el.clientWidth / 2;
    container.scrollTo({ left: scrollLeft, behavior: 'smooth' });
  }, [layout]);

  useEffect(() => {
    scrollActiveIntoView();
  }, [activeId, scrollActiveIntoView]);

  return (
    <div
      ref={scrollRef}
      className={cn(styles.nav, styles[layout], className)}
      role="tablist"
    >
      {categories.map((cat) => {
        const isActive = cat.id === activeId;
        return (
          <button
            key={cat.id}
            ref={isActive ? activeRef : undefined}
            className={cn(styles.item, isActive && styles.active)}
            onClick={() => onSelect(cat.id)}
            role="tab"
            aria-selected={isActive}
            type="button"
          >
            {cat.icon && <span className={styles.icon}>{cat.icon}</span>}
            <span className={styles.label}>{cat.name}</span>
            {cat.count != null && (
              <span className={styles.count}>{cat.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
