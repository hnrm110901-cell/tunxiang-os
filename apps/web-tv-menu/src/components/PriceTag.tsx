import { type CSSProperties } from 'react';

interface PriceTagProps {
  price: number;
  originalPrice?: number;
  memberPrice?: number;
  isMarketPrice?: boolean;
  isSoldOut?: boolean;
  size?: 'large' | 'medium' | 'small';
}

const fontSizes = {
  large: { main: 36, sub: 18, unit: 20 },
  medium: { main: 28, sub: 16, unit: 16 },
  small: { main: 22, sub: 14, unit: 14 },
};

export default function PriceTag({
  price,
  originalPrice,
  memberPrice,
  isMarketPrice = false,
  isSoldOut = false,
  size = 'medium',
}: PriceTagProps) {
  const fs = fontSizes[size];

  if (isSoldOut) {
    return (
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{
          fontSize: fs.main,
          fontWeight: 700,
          color: 'var(--tx-text-tertiary)',
          textDecoration: 'line-through',
        }}>
          ¥{price}
        </span>
      </div>
    );
  }

  // 时价模式
  if (isMarketPrice) {
    const containerStyle: CSSProperties = {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
    };
    const marketStyle: CSSProperties = {
      fontSize: fs.main,
      fontWeight: 700,
      color: '#FFD700',
      animation: 'tx-blink 2s infinite',
    };
    return (
      <div style={containerStyle}>
        <span style={marketStyle}>时价</span>
        {price > 0 && (
          <span style={{ fontSize: fs.sub, color: 'var(--tx-text-secondary)' }}>
            约¥{price}/斤
          </span>
        )}
      </div>
    );
  }

  // 促销价模式
  const hasPromo = originalPrice && originalPrice > price;
  // 会员价模式
  const hasVip = memberPrice && memberPrice < price;

  const containerStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'baseline',
    gap: 8,
    flexWrap: 'wrap',
  };

  const mainPriceStyle: CSSProperties = {
    fontSize: fs.main,
    fontWeight: 700,
    color: hasPromo ? 'var(--tx-seafood-up)' : 'var(--tx-text-primary)',
    lineHeight: 1,
  };

  const unitStyle: CSSProperties = {
    fontSize: fs.unit,
    color: 'var(--tx-text-secondary)',
  };

  const originalStyle: CSSProperties = {
    fontSize: fs.sub,
    color: 'var(--tx-text-tertiary)',
    textDecoration: 'line-through',
  };

  const vipStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontSize: fs.sub,
    color: '#FFD700',
    background: 'rgba(255, 215, 0, 0.1)',
    padding: '2px 8px',
    borderRadius: 4,
    border: '1px solid rgba(255, 215, 0, 0.3)',
  };

  return (
    <div style={containerStyle}>
      <span style={unitStyle}>¥</span>
      <span style={mainPriceStyle}>{price}</span>
      {hasPromo && (
        <span style={originalStyle}>¥{originalPrice}</span>
      )}
      {hasVip && (
        <span style={vipStyle}>
          VIP ¥{memberPrice}
        </span>
      )}
    </div>
  );
}
