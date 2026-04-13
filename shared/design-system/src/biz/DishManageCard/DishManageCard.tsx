/**
 * DishManageCard — 菜品管理卡片（admin/管理端使用）
 *
 * 用于菜品列表的卡片式展示，显示菜品图片、名称、价格、
 * 四象限标识、成本率、库存状态等管理信息。
 * 支持操作按钮（编辑/上下架/沽清）。
 */
import { useMemo } from 'react';
import styles from './DishManageCard.module.css';
import { cn } from '../../utils/cn';
import { formatPrice } from '../../utils/formatPrice';

export interface DishManageData {
  id: string;
  name: string;
  category: string;
  priceFen: number;
  costFen?: number;
  costRate?: number;
  imageUrl?: string;
  isAvailable: boolean;
  isSoldOut?: boolean;
  quadrant?: 'star' | 'cash_cow' | 'question' | 'dog';
  stockStatus?: 'normal' | 'low' | 'out_of_stock';
  tags?: string[];
  monthlyNew?: boolean;
}

export interface DishManageCardProps {
  dish: DishManageData;
  selected?: boolean;
  onEdit?: (dish: DishManageData) => void;
  onToggleAvailable?: (dish: DishManageData) => void;
  onToggleSoldOut?: (dish: DishManageData) => void;
  onClick?: (dish: DishManageData) => void;
}

const QUADRANT_META: Record<string, { label: string; icon: string; color: string }> = {
  star:     { label: '明星', icon: '⭐', color: '#FF6B35' },
  cash_cow: { label: '金牛', icon: '🐂', color: '#185FA5' },
  question: { label: '问题', icon: '❓', color: '#BA7517' },
  dog:      { label: '瘦狗', icon: '🐕', color: '#8899A6' },
};

const STOCK_META: Record<string, { label: string; color: string }> = {
  normal:       { label: '正常', color: '#0F6E56' },
  low:          { label: '低库存', color: '#BA7517' },
  out_of_stock: { label: '缺货', color: '#A32D2D' },
};

export default function DishManageCard({
  dish,
  selected,
  onEdit,
  onToggleAvailable,
  onToggleSoldOut,
  onClick,
}: DishManageCardProps) {
  const quadrant = dish.quadrant ? QUADRANT_META[dish.quadrant] : null;
  const stock = dish.stockStatus ? STOCK_META[dish.stockStatus] : null;

  const costRatePct = useMemo(() => {
    if (dish.costRate == null) return null;
    return (dish.costRate * 100).toFixed(1);
  }, [dish.costRate]);

  const costRateColor = useMemo(() => {
    if (dish.costRate == null) return '#8899A6';
    if (dish.costRate > 0.5) return '#A32D2D';
    if (dish.costRate >= 0.3) return '#BA7517';
    return '#0F6E56';
  }, [dish.costRate]);

  return (
    <div
      className={cn(
        styles.card,
        selected && styles.selected,
        !dish.isAvailable && styles.unavailable,
      )}
      onClick={() => onClick?.(dish)}
    >
      {/* Image */}
      <div className={styles.imageWrap}>
        {dish.imageUrl ? (
          <img src={dish.imageUrl} alt={dish.name} className={styles.image} loading="lazy" />
        ) : (
          <div className={styles.placeholder}>
            <span>{dish.name[0]}</span>
          </div>
        )}
        {dish.isSoldOut && <div className={styles.soldOutBadge}>沽清</div>}
        {dish.monthlyNew && <div className={styles.newBadge}>NEW</div>}
      </div>

      {/* Info */}
      <div className={styles.info}>
        <div className={styles.nameRow}>
          <span className={styles.name}>{dish.name}</span>
          {quadrant && (
            <span className={styles.quadrantBadge} style={{ color: quadrant.color }}>
              {quadrant.icon}
            </span>
          )}
        </div>

        <div className={styles.category}>{dish.category}</div>

        <div className={styles.priceRow}>
          <span className={styles.price}>{formatPrice(dish.priceFen)}</span>
          {costRatePct && (
            <span className={styles.costRate} style={{ color: costRateColor }}>
              成本{costRatePct}%
            </span>
          )}
          {stock && (
            <span className={styles.stockBadge} style={{ color: stock.color }}>
              {stock.label}
            </span>
          )}
        </div>

        {/* Action buttons */}
        <div className={styles.actions}>
          {onEdit && (
            <button
              type="button"
              className={cn(styles.actionBtn, styles.editBtn)}
              onClick={(e) => { e.stopPropagation(); onEdit(dish); }}
            >
              编辑
            </button>
          )}
          {onToggleAvailable && (
            <button
              type="button"
              className={cn(styles.actionBtn, dish.isAvailable ? styles.offBtn : styles.onBtn)}
              onClick={(e) => { e.stopPropagation(); onToggleAvailable(dish); }}
            >
              {dish.isAvailable ? '下架' : '上架'}
            </button>
          )}
          {onToggleSoldOut && (
            <button
              type="button"
              className={cn(styles.actionBtn, dish.isSoldOut ? styles.restoreBtn : styles.soldoutBtn)}
              onClick={(e) => { e.stopPropagation(); onToggleSoldOut(dish); }}
            >
              {dish.isSoldOut ? '恢复' : '沽清'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
