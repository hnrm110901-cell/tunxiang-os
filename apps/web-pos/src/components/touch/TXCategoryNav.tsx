/**
 * TXCategoryNav — POS 左侧分类导航栏（触控优化）
 *
 * 规范:
 *   - 每项高度 ≥ 48px（触控安全区）
 *   - 选中态: 左侧 3px 品牌色条 + 背景高亮
 *   - 支持惯性滚动
 *   - 文字 ≥ 16px
 */
import styles from './TXCategoryNav.module.css';

export interface CategoryItem {
  id: string;
  name: string;
  count?: number;  // 该分类菜品数量
  icon?: string;   // emoji 或图标
}

export interface TXCategoryNavProps {
  categories: CategoryItem[];
  activeId: string;
  onSelect: (id: string) => void;
}

export function TXCategoryNav({ categories, activeId, onSelect }: TXCategoryNavProps) {
  return (
    <nav className={styles.nav} aria-label="菜品分类">
      {categories.map(cat => (
        <button
          key={cat.id}
          className={`${styles.item} ${cat.id === activeId ? styles.active : ''} tx-pressable`}
          onClick={() => onSelect(cat.id)}
          aria-current={cat.id === activeId ? 'page' : undefined}
        >
          {cat.icon && <span className={styles.icon}>{cat.icon}</span>}
          <span className={styles.label}>{cat.name}</span>
          {cat.count !== undefined && (
            <span className={styles.count}>{cat.count}</span>
          )}
        </button>
      ))}
    </nav>
  );
}
