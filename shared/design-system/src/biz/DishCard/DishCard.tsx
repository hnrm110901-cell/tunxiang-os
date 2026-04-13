/**
 * DishCard — 统一菜品卡片组件
 *
 * 三种 variant：
 *  - grid:       垂直卡片（图片上方，信息下方）—— POS 平板 / 桌面
 *  - horizontal: 图片左 + 信息右 —— H5 / 手机端
 *  - compact:    单行无图 —— 服务员端 / 搜索结果
 */
import { formatPrice } from '../../utils/formatPrice';
import { cn } from '../../utils/cn';
import type { DishCardProps } from './types';
import styles from './DishCard.module.css';

const TAG_COLORS: Record<string, string> = {
  signature: '#FF6B2C',
  new: '#22C55E',
  spicy1: '#F59E0B',
  spicy2: '#EF4444',
  spicy3: '#DC2626',
  seasonal: '#3B82F6',
};

export default function DishCard({
  dish,
  variant,
  quantity = 0,
  showMemberPrice = true,
  showTags = true,
  showAllergens = false,
  showImage = true,
  onAdd,
  onTap,
  className,
}: DishCardProps) {
  const hasMemberPrice =
    showMemberPrice &&
    dish.memberPriceFen != null &&
    dish.memberPriceFen < dish.priceFen;

  const imageUrl = dish.images?.[0] ?? '/placeholder-dish.png';
  const shouldShowImage = showImage && variant !== 'compact';

  return (
    <div
      className={cn(
        styles.card,
        styles[variant],
        dish.soldOut && styles.soldOut,
        'tx-pressable',
        className,
      )}
      onClick={onTap}
      role={onTap ? 'button' : undefined}
      tabIndex={onTap ? 0 : undefined}
      onKeyDown={onTap ? (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onTap?.();
        }
      } : undefined}
    >
      {/* Image */}
      {shouldShowImage && (
        <div className={styles.imageWrap}>
          <img
            src={imageUrl}
            alt={dish.name}
            className={styles.image}
            loading="lazy"
          />
          {dish.soldOut && (
            <div className={styles.soldOutOverlay}>已售罄</div>
          )}
          {showTags && dish.tags && dish.tags.length > 0 && (
            <div className={styles.tags}>
              {dish.tags.map((tag) => (
                <span
                  key={tag.type}
                  className={styles.tag}
                  style={{ background: TAG_COLORS[tag.type] ?? '#666' }}
                >
                  {tag.label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Info */}
      <div className={styles.info}>
        <div className={styles.name}>{dish.name}</div>

        {variant !== 'compact' && dish.description && (
          <div className={styles.desc}>{dish.description}</div>
        )}

        {showAllergens && dish.allergens && dish.allergens.length > 0 && (
          <div className={styles.allergens}>
            {dish.allergens.map((a) => (
              <span key={a.code} className={styles.allergen}>
                {a.name}
              </span>
            ))}
          </div>
        )}

        {/* Compact variant: inline tags */}
        {variant === 'compact' && showTags && dish.tags && dish.tags.length > 0 && (
          <div className={styles.tagsInline}>
            {dish.tags.map((tag) => (
              <span
                key={tag.type}
                className={styles.tagInline}
                style={{ color: TAG_COLORS[tag.type] ?? '#666' }}
              >
                {tag.label}
              </span>
            ))}
          </div>
        )}

        <div className={styles.bottom}>
          <div className={styles.priceRow}>
            <span className={styles.price}>
              {formatPrice(dish.priceFen)}
            </span>
            {hasMemberPrice && (
              <span className={styles.memberPrice}>
                {formatPrice(dish.memberPriceFen!)}
              </span>
            )}
          </div>

          {!dish.soldOut && (
            <button
              className={cn(styles.addBtn, 'tx-pressable')}
              onClick={(e) => {
                e.stopPropagation();
                onAdd();
              }}
              aria-label={`添加${dish.name}到购物车`}
              type="button"
            >
              {quantity > 0 ? (
                <span className={styles.badge}>{quantity}</span>
              ) : (
                <span className={styles.plus}>+</span>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
