/**
 * 页面B：今日特价/推荐展示屏
 * 布局：1920×1080，深色渐变背景，2行3列特价菜品卡片 + 右下角倒计时
 * 纯展示（无用户交互）
 */
import { useState, useEffect, type CSSProperties } from 'react';
import { formatPrice } from '@tx-ds/utils';

/* ======================== 类型 ======================== */
interface SpecialDish {
  id: string;
  name: string;
  originalPrice_fen: number;
  specialPrice_fen: number;
  spec: string;
  tag: string;
  tagColor: string;
  image?: string;
}

/* ======================== Mock数据 ======================== */
const MOCK_SPECIALS: SpecialDish[] = [
  { id: '1', name: '招牌剁椒鱼头', originalPrice_fen: 11800, specialPrice_fen: 8800, spec: '1个（约2.5斤）', tag: '今日推荐', tagColor: '#FF6B35' },
  { id: '2', name: '清蒸大闸蟹', originalPrice_fen: 12800, specialPrice_fen: 9800, spec: '只（约3两）', tag: '限时特价', tagColor: '#E53935' },
  { id: '3', name: '蒜蓉龙虾套餐', originalPrice_fen: 38800, specialPrice_fen: 29800, spec: '2人套餐', tag: '超值套餐', tagColor: '#9C27B0' },
  { id: '4', name: '松鼠桂鱼', originalPrice_fen: 13800, specialPrice_fen: 9800, spec: '条（约0.8斤）', tag: '限量20份', tagColor: '#F57C00' },
  { id: '5', name: '秘制东坡肉', originalPrice_fen: 8800, specialPrice_fen: 5800, spec: '例', tag: '厨师推荐', tagColor: '#0288D1' },
  { id: '6', name: '四海海鲜锅', originalPrice_fen: 48800, specialPrice_fen: 35800, spec: '4人位', tag: '家庭首选', tagColor: '#00897B' },
];

/* ======================== 营业结束时间倒计时 ======================== */
function getCountdown(): string {
  const now = new Date();
  const close = new Date(now);
  close.setHours(22, 0, 0, 0);
  if (now >= close) close.setDate(close.getDate() + 1);
  const diff = Math.max(0, close.getTime() - now.getTime());
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  const s = Math.floor((diff % 60_000) / 1_000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/* ======================== 特价卡片组件 ======================== */
function SpecialCard({ dish, index }: { dish: SpecialDish; index: number }) {
  const cardStyle: CSSProperties = {
    background: 'rgba(255, 255, 255, 0.05)',
    borderRadius: 16,
    border: '1px solid rgba(255, 107, 53, 0.25)',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    animation: `tx-fade-in 0.5s ease-out ${index * 100}ms both`,
    position: 'relative',
  };

  const imgAreaStyle: CSSProperties = {
    width: '100%',
    height: 240,
    background: `linear-gradient(135deg, hsl(${30 + index * 15}, 50%, 15%) 0%, hsl(${20 + index * 10}, 60%, 10%) 100%)`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    position: 'relative',
  };

  const tagStyle: CSSProperties = {
    position: 'absolute',
    top: 16,
    left: 16,
    background: dish.tagColor,
    color: '#fff',
    fontSize: 22,
    fontWeight: 700,
    padding: '6px 16px',
    borderRadius: 20,
    letterSpacing: 1,
  };

  const infoStyle: CSSProperties = {
    padding: '16px 20px',
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  };

  const nameStyle: CSSProperties = {
    fontSize: 36,
    fontWeight: 800,
    color: '#FFFFFF',
    lineHeight: 1.2,
  };

  const specStyle: CSSProperties = {
    fontSize: 22,
    color: '#c8a882',
  };

  const priceRowStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'baseline',
    gap: 16,
    marginTop: 'auto',
  };

  const originalPriceStyle: CSSProperties = {
    fontSize: 24,
    color: '#888',
    textDecoration: 'line-through',
  };

  const specialPriceStyle: CSSProperties = {
    fontSize: 48,
    fontWeight: 900,
    color: '#FF6B35',
    lineHeight: 1,
  };

  const originalDisplay = formatPrice(dish.originalPrice_fen);
  const specialDisplay = formatPrice(dish.specialPrice_fen);

  return (
    <div style={cardStyle}>
      {/* 图片区域 */}
      <div style={imgAreaStyle}>
        {dish.image ? (
          <img src={dish.image} alt={dish.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
            <circle cx="40" cy="40" r="36" fill={`${dish.tagColor}30`} />
            <path d="M24 40 Q40 24 56 40 Q40 56 24 40Z" fill={`${dish.tagColor}60`} />
            <circle cx="40" cy="40" r="10" fill={`${dish.tagColor}80`} />
          </svg>
        )}
        <div style={tagStyle}>{dish.tag}</div>
      </div>

      {/* 信息区 */}
      <div style={infoStyle}>
        <div style={nameStyle}>{dish.name}</div>
        <div style={specStyle}>{dish.spec}</div>
        <div style={priceRowStyle}>
          <span style={originalPriceStyle}>{originalDisplay}</span>
          <span style={specialPriceStyle}>{specialDisplay}</span>
        </div>
      </div>
    </div>
  );
}

/* ======================== 主组件 ======================== */
export default function SpecialDisplayPage() {
  const [countdown, setCountdown] = useState(getCountdown());
  const [currentTime, setCurrentTime] = useState('');

  /* 倒计时 + 实时时钟 */
  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown(getCountdown());
      setCurrentTime(new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }));
    }, 1000);
    setCurrentTime(new Date().toLocaleTimeString('zh-CN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }));
    return () => clearInterval(timer);
  }, []);

  /* ===== 样式 ===== */
  const rootStyle: CSSProperties = {
    width: 1920,
    height: 1080,
    overflow: 'hidden',
    background: 'linear-gradient(135deg, #1a0a00 0%, #3d1a00 50%, #1a0a00 100%)',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    cursor: 'none',
    userSelect: 'none',
    position: 'relative',
  };

  const headerStyle: CSSProperties = {
    flexShrink: 0,
    padding: '32px 60px 16px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  };

  const titleStyle: CSSProperties = {
    fontSize: 60,
    fontWeight: 900,
    color: '#FF6B35',
    letterSpacing: 8,
    textShadow: '0 0 40px rgba(255, 107, 53, 0.5)',
    lineHeight: 1,
  };

  const subtitleStyle: CSSProperties = {
    fontSize: 28,
    color: '#c8a882',
    letterSpacing: 4,
    marginTop: 8,
  };

  const clockStyle: CSSProperties = {
    textAlign: 'right',
  };

  const clockTimeStyle: CSSProperties = {
    fontSize: 40,
    fontWeight: 700,
    color: '#FF6B35',
    fontVariantNumeric: 'tabular-nums',
    letterSpacing: 2,
    display: 'block',
  };

  const clockLabelStyle: CSSProperties = {
    fontSize: 22,
    color: '#9e7a55',
    letterSpacing: 2,
  };

  const gridStyle: CSSProperties = {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gridTemplateRows: 'repeat(2, 1fr)',
    gap: 20,
    padding: '12px 48px 0',
    overflow: 'hidden',
  };

  const footerStyle: CSSProperties = {
    flexShrink: 0,
    height: 80,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    padding: '0 60px',
    gap: 20,
  };

  const countdownLabelStyle: CSSProperties = {
    fontSize: 26,
    color: '#c8a882',
    letterSpacing: 2,
  };

  const countdownValueStyle: CSSProperties = {
    fontSize: 44,
    fontWeight: 800,
    color: '#FF6B35',
    fontVariantNumeric: 'tabular-nums',
    letterSpacing: 4,
    textShadow: '0 0 20px rgba(255, 107, 53, 0.4)',
  };

  /* 装饰光晕 */
  const glowStyle: CSSProperties = {
    position: 'absolute',
    top: -200,
    left: '50%',
    transform: 'translateX(-50%)',
    width: 800,
    height: 400,
    background: 'radial-gradient(ellipse, rgba(255, 107, 53, 0.08) 0%, transparent 70%)',
    pointerEvents: 'none',
  };

  return (
    <div style={rootStyle}>
      {/* 装饰光晕 */}
      <div style={glowStyle} />

      {/* ===== 顶部标题 ===== */}
      <div style={headerStyle}>
        <div>
          <div style={titleStyle}>今日特推</div>
          <div style={subtitleStyle}>TODAY'S SPECIAL RECOMMENDATIONS</div>
        </div>
        <div style={clockStyle}>
          <span style={clockTimeStyle}>{currentTime}</span>
          <span style={clockLabelStyle}>徐记海鲜 · 长沙总店</span>
        </div>
      </div>

      {/* ===== 特价菜品网格 ===== */}
      <div style={gridStyle}>
        {MOCK_SPECIALS.map((dish, i) => (
          <SpecialCard key={dish.id} dish={dish} index={i} />
        ))}
      </div>

      {/* ===== 底部倒计时 ===== */}
      <div style={footerStyle}>
        <span style={countdownLabelStyle}>今日营业结束倒计时</span>
        <span style={countdownValueStyle}>{countdown}</span>
      </div>
    </div>
  );
}
