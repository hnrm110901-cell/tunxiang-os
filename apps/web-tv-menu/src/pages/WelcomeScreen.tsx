import { useState, useEffect, type CSSProperties } from 'react';
import type { DishItem } from '../api/menuWallApi';

/** Mock等位和推荐数据 */
const SCROLL_SPEED = 40; // 秒/轮

function getMockRecommends(): DishItem[] {
  return [
    '招牌剁椒鱼头', '蒜蓉龙虾', '清蒸多宝鱼', '避风塘炒蟹',
    '白灼基围虾', '松鼠桂鱼', '油焖大虾', '铁板黑椒牛柳',
  ].map((name, i) => ({
    id: `rec-${i}`,
    name,
    price: Math.floor(68 + Math.random() * 200),
    image: '',
    category: '推荐',
    tags: [],
    isSoldOut: false,
    isRecommended: true,
    isMarketPrice: false,
    description: '',
  }));
}

export default function WelcomeScreen() {
  const [waitingTables, setWaitingTables] = useState(12);
  const [estimatedMinutes, setEstimatedMinutes] = useState(25);
  const [recommends, setRecommends] = useState<DishItem[]>([]);
  const [currentTime, setCurrentTime] = useState('');

  useEffect(() => {
    setRecommends(getMockRecommends());

    // 更新时间
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }));
    };
    updateTime();
    const timer = setInterval(updateTime, 30_000);

    // 模拟等位变化
    const waitTimer = setInterval(() => {
      setWaitingTables((t) => Math.max(0, t + (Math.random() > 0.5 ? 1 : -1)));
      setEstimatedMinutes((m) => Math.max(5, m + (Math.random() > 0.5 ? 2 : -3)));
    }, 15_000);

    return () => {
      clearInterval(timer);
      clearInterval(waitTimer);
    };
  }, []);

  const containerStyle: CSSProperties = {
    width: '100vw',
    height: '100vh',
    background: 'var(--tx-bg-dark)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    fontFamily: 'var(--tx-font)',
    overflow: 'hidden',
  };

  const topStyle: CSSProperties = {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 40,
    width: '100%',
    maxWidth: 1200,
    padding: '40px 60px',
  };

  const logoStyle: CSSProperties = {
    fontSize: 72,
    fontWeight: 900,
    color: 'var(--tx-primary)',
    letterSpacing: 8,
    textShadow: '0 4px 24px rgba(255, 107, 44, 0.3)',
  };

  const timeStyle: CSSProperties = {
    fontSize: 24,
    color: 'var(--tx-text-tertiary)',
    letterSpacing: 2,
  };

  const waitingContainerStyle: CSSProperties = {
    display: 'flex',
    gap: 80,
    alignItems: 'center',
  };

  const waitingBlockStyle: CSSProperties = {
    textAlign: 'center',
  };

  const waitingNumberStyle: CSSProperties = {
    fontSize: 96,
    fontWeight: 900,
    color: '#FFFFFF',
    lineHeight: 1,
    fontVariantNumeric: 'tabular-nums',
  };

  const waitingLabelStyle: CSSProperties = {
    fontSize: 22,
    color: 'var(--tx-text-secondary)',
    marginTop: 8,
  };

  const dividerStyle: CSSProperties = {
    width: 2,
    height: 80,
    background: 'var(--tx-border)',
  };

  const qrContainerStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 16,
    padding: '24px 40px',
    background: 'rgba(255,255,255,0.05)',
    borderRadius: 'var(--tx-radius-lg)',
    border: '1px solid var(--tx-border)',
  };

  const qrPlaceholderStyle: CSSProperties = {
    width: 180,
    height: 180,
    background: '#FFFFFF',
    borderRadius: 12,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 14,
    color: '#333',
    fontWeight: 600,
  };

  const scrollBarStyle: CSSProperties = {
    width: '100%',
    height: 100,
    borderTop: '1px solid var(--tx-border)',
    display: 'flex',
    alignItems: 'center',
    overflow: 'hidden',
    flexShrink: 0,
    position: 'relative',
  };

  const scrollContentStyle: CSSProperties = {
    display: 'flex',
    gap: 60,
    whiteSpace: 'nowrap',
    animation: `tx-scroll-left ${SCROLL_SPEED}s linear infinite`,
  };

  const scrollItemStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    fontSize: 22,
    color: 'var(--tx-text-secondary)',
    flexShrink: 0,
  };

  const scrollPriceStyle: CSSProperties = {
    color: 'var(--tx-primary)',
    fontWeight: 700,
  };

  // 重复一份用于无缝滚动
  const scrollItems = [...recommends, ...recommends];

  return (
    <div style={containerStyle}>
      {/* 主区域 */}
      <div style={topStyle}>
        {/* Logo */}
        <div style={logoStyle}>屯象</div>
        <div style={timeStyle}>{currentTime}</div>

        {/* 等位信息 */}
        <div style={waitingContainerStyle}>
          <div style={waitingBlockStyle}>
            <div style={waitingNumberStyle}>{waitingTables}</div>
            <div style={waitingLabelStyle}>当前等位 (桌)</div>
          </div>
          <div style={dividerStyle} />
          <div style={waitingBlockStyle}>
            <div style={waitingNumberStyle}>{estimatedMinutes}</div>
            <div style={waitingLabelStyle}>预计等待 (分钟)</div>
          </div>
        </div>

        {/* 扫码排队 */}
        <div style={qrContainerStyle}>
          <div style={qrPlaceholderStyle}>
            扫码排队
          </div>
          <div style={{ fontSize: 18, color: 'var(--tx-text-secondary)' }}>
            微信扫码 · 在线排队 · 到号提醒
          </div>
        </div>
      </div>

      {/* 底部滚动推荐 */}
      <div style={scrollBarStyle}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 100, background: 'linear-gradient(to right, var(--tx-bg-dark), transparent)', zIndex: 1 }} />
        <div style={scrollContentStyle}>
          {scrollItems.map((dish, i) => (
            <div key={`${dish.id}-${i}`} style={scrollItemStyle}>
              <span style={{ color: 'var(--tx-primary)', fontSize: 16 }}>●</span>
              <span>{dish.name}</span>
              <span style={scrollPriceStyle}>¥{dish.price}</span>
            </div>
          ))}
        </div>
        <div style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 100, background: 'linear-gradient(to left, var(--tx-bg-dark), transparent)', zIndex: 1 }} />
      </div>
    </div>
  );
}
