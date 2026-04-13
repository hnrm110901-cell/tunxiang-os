// @deprecated — use DishCard from @tx-ds/biz instead
import { useLang } from '@/i18n/LangContext';
import type { DishItem } from '@/api/menuApi';
import AllergenBadge from './AllergenBadge';
import styles from './DishCard.module.css';

interface DishCardProps {
  dish: DishItem;
  quantity: number;
  onAdd: () => void;
  onTap: () => void;
}

const TAG_COLORS: Record<string, string> = {
  signature: '#FF6B2C',
  new: '#22C55E',
  spicy1: '#F59E0B',
  spicy2: '#EF4444',
  spicy3: '#DC2626',
  seasonal: '#3B82F6',
};

export default function DishCard({ dish, quantity, onAdd, onTap }: DishCardProps) {
  const { t } = useLang();

  return (
    <div
      className={`${styles.card} ${dish.soldOut ? styles.soldOut : ''} tx-pressable tx-fade-in`}
      onClick={onTap}
    >
      {/* 菜品图片 */}
      <div className={styles.imageWrap}>
        <img
          src={dish.images[0] ?? '/placeholder-dish.png'}
          alt={dish.name}
          className={styles.image}
          loading="lazy"
        />
        {dish.soldOut && <div className={styles.soldOutOverlay}>{t('soldOut')}</div>}
        {dish.tags.length > 0 && (
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

      {/* 菜品信息 */}
      <div className={styles.info}>
        <div className={styles.name}>{dish.name}</div>
        <div className={styles.desc}>{dish.description}</div>

        {dish.allergens.length > 0 && (
          <div className={styles.allergens}>
            {dish.allergens.map((a) => (
              <AllergenBadge key={a.code} allergen={a} />
            ))}
          </div>
        )}

        <div className={styles.bottom}>
          <div className={styles.priceRow}>
            <span className={styles.price}>
              {t('yuan')}{dish.price}
            </span>
            {dish.memberPrice != null && dish.memberPrice < dish.price && (
              <span className={styles.memberPrice}>
                {t('yuan')}{dish.memberPrice}
              </span>
            )}
          </div>

          {!dish.soldOut && (
            <button
              className={`${styles.addBtn} tx-pressable`}
              onClick={(e) => { e.stopPropagation(); onAdd(); }}
              aria-label={t('addToCart')}
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
