import { type CSSProperties } from 'react';
import type { DishItem } from '../api/menuWallApi';
import PriceTag from './PriceTag';
import SoldOutOverlay from './SoldOutOverlay';
import TimeSlotBadge from './TimeSlotBadge';

type DishCardSize = 'hero' | 'medium' | 'small';

interface DishCardProps {
  dish: DishItem;
  size?: DishCardSize;
  animationDelay?: number;
  onClick?: (dish: DishItem) => void;
}

const sizeStyles: Record<DishCardSize, CSSProperties> = {
  hero: {
    width: '100%',
    height: '100%',
    minHeight: 480,
  },
  medium: {
    width: '100%',
    height: '100%',
    minHeight: 320,
  },
  small: {
    width: '100%',
    height: '100%',
    minHeight: 220,
  },
};

const imageSizes: Record<DishCardSize, CSSProperties> = {
  hero: { height: '65%' },
  medium: { height: '55%' },
  small: { height: '50%' },
};

const nameFontSizes: Record<DishCardSize, number> = {
  hero: 32,
  medium: 24,
  small: 20,
};

export default function DishCard({ dish, size = 'medium', animationDelay = 0, onClick }: DishCardProps) {
  const isRecommended = dish.isRecommended && !dish.isSoldOut;

  const cardStyle: CSSProperties = {
    ...sizeStyles[size],
    position: 'relative',
    borderRadius: 'var(--tx-radius-md)',
    overflow: 'hidden',
    background: 'var(--tx-bg-card)',
    border: isRecommended ? '2px solid var(--tx-primary)' : '1px solid var(--tx-border)',
    transition: 'transform 0.3s ease, box-shadow 0.3s ease',
    animation: `tx-fade-in 0.4s ease-out ${animationDelay}ms both`,
    cursor: onClick ? 'pointer' : 'default',
    display: 'flex',
    flexDirection: 'column',
  };

  const imageContainerStyle: CSSProperties = {
    ...imageSizes[size],
    position: 'relative',
    overflow: 'hidden',
    flexShrink: 0,
  };

  const imageStyle: CSSProperties = {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    filter: dish.isSoldOut ? 'grayscale(100%) brightness(0.5)' : 'none',
    transition: 'filter 0.3s ease',
  };

  const infoStyle: CSSProperties = {
    padding: size === 'hero' ? '20px 24px' : size === 'medium' ? '16px 20px' : '12px 16px',
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'space-between',
  };

  const nameStyle: CSSProperties = {
    fontSize: nameFontSizes[size],
    fontWeight: 700,
    color: dish.isSoldOut ? 'var(--tx-text-tertiary)' : 'var(--tx-text-primary)',
    textDecoration: dish.isSoldOut ? 'line-through' : 'none',
    lineHeight: 1.3,
    marginBottom: 8,
  };

  const tagsStyle: CSSProperties = {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap',
    marginBottom: 8,
  };

  const tagStyle: CSSProperties = {
    fontSize: size === 'small' ? 12 : 14,
    padding: '2px 8px',
    borderRadius: 4,
    background: 'var(--tx-primary-light)',
    color: 'var(--tx-primary)',
  };

  const descStyle: CSSProperties = {
    fontSize: size === 'hero' ? 18 : 14,
    color: 'var(--tx-text-secondary)',
    lineHeight: 1.5,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    display: '-webkit-box',
    WebkitLineClamp: size === 'hero' ? 3 : 2,
    WebkitBoxOrient: 'vertical' as const,
  };

  return (
    <div style={cardStyle} onClick={() => onClick?.(dish)}>
      {/* 图片区域 */}
      <div style={imageContainerStyle}>
        <img
          src={dish.image || '/placeholder-dish.jpg'}
          alt={dish.name}
          style={imageStyle}
          loading="lazy"
        />
        {/* 推荐高亮角标 */}
        {isRecommended && (
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            background: 'var(--tx-primary)',
            color: '#FFF',
            fontSize: size === 'small' ? 12 : 14,
            fontWeight: 700,
            padding: '4px 12px 4px 8px',
            borderBottomRightRadius: 12,
          }}>
            主厨推荐
          </div>
        )}
        {/* 时段角标 */}
        {dish.timeSlot && !dish.isSoldOut && (
          <div style={{ position: 'absolute', top: 8, right: 8 }}>
            <TimeSlotBadge slot={dish.timeSlot} />
          </div>
        )}
      </div>

      {/* 信息区域 */}
      <div style={infoStyle}>
        <div>
          <div style={nameStyle}>{dish.name}</div>
          {dish.tags.length > 0 && size !== 'small' && (
            <div style={tagsStyle}>
              {dish.tags.slice(0, size === 'hero' ? 5 : 3).map((tag) => (
                <span key={tag} style={tagStyle}>{tag}</span>
              ))}
            </div>
          )}
          {dish.description && size === 'hero' && (
            <div style={descStyle}>{dish.description}</div>
          )}
        </div>
        <PriceTag
          price={dish.price}
          originalPrice={dish.originalPrice}
          memberPrice={dish.memberPrice}
          isMarketPrice={dish.isMarketPrice}
          isSoldOut={dish.isSoldOut}
          size={size === 'hero' ? 'large' : size === 'medium' ? 'medium' : 'small'}
        />
      </div>

      {/* 沽清覆盖层 */}
      {dish.isSoldOut && <SoldOutOverlay />}
    </div>
  );
}
