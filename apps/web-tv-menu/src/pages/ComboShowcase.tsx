import { useState, useEffect, useRef, type CSSProperties } from 'react';
import type { ComboItem } from '../api/menuWallApi';

/** Mock套餐数据 */
function getMockCombos(): ComboItem[] {
  return [
    {
      id: 'combo-1',
      name: '海鲜盛宴(8人)',
      price: 1688,
      image: '',
      servesCount: '8-10人',
      description: '精选顶级海鲜，包含波龙、帝王蟹等珍贵食材，适合商务宴请',
      dishes: [
        { name: '波士顿龙虾', quantity: 1 },
        { name: '清蒸多宝鱼', quantity: 1 },
        { name: '蒜蓉龙虾', quantity: 1 },
        { name: '避风塘炒蟹', quantity: 1 },
        { name: '白灼基围虾', quantity: 1 },
        { name: '蒜蓉粉丝蒸扇贝', quantity: 1 },
        { name: '时蔬拼盘', quantity: 1 },
        { name: '海鲜粥', quantity: 1 },
        { name: '精美果盘', quantity: 1 },
      ],
    },
    {
      id: 'combo-2',
      name: '家庭欢聚套餐(4人)',
      price: 688,
      image: '',
      servesCount: '4-6人',
      description: '精心搭配，老少皆宜，家庭聚餐首选',
      dishes: [
        { name: '招牌剁椒鱼头', quantity: 1 },
        { name: '油焖大虾', quantity: 1 },
        { name: '铁板黑椒牛柳', quantity: 1 },
        { name: '清炒时蔬', quantity: 1 },
        { name: '蛋炒饭', quantity: 1 },
        { name: '甜品拼盘', quantity: 1 },
      ],
    },
    {
      id: 'combo-3',
      name: '商务精选套餐(6人)',
      price: 1288,
      image: '',
      servesCount: '6-8人',
      description: '高端食材，精致摆盘，彰显品味的商务宴请之选',
      dishes: [
        { name: '松鼠桂鱼', quantity: 1 },
        { name: '蒜蓉龙虾', quantity: 1 },
        { name: '清蒸多宝鱼', quantity: 1 },
        { name: '红烧大黄鱼', quantity: 1 },
        { name: '白灼基围虾', quantity: 1 },
        { name: '时蔬双拼', quantity: 1 },
        { name: '精美果盘', quantity: 1 },
      ],
    },
    {
      id: 'combo-4',
      name: '双人浪漫晚餐',
      price: 388,
      image: '',
      servesCount: '2人',
      description: '精选双人份海鲜与甜品，浪漫约会的完美选择',
      dishes: [
        { name: '清蒸鲈鱼', quantity: 1 },
        { name: '蒜蓉粉丝蒸扇贝', quantity: 1 },
        { name: '铁板黑椒牛柳', quantity: 1 },
        { name: '甜品双人份', quantity: 1 },
      ],
    },
  ];
}

/** 自动轮播间隔 */
const CAROUSEL_INTERVAL = 6_000;

export default function ComboShowcase() {
  const [combos, setCombos] = useState<ComboItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [touchMode] = useState(() => new URLSearchParams(window.location.search).has('touch'));
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    setCombos(getMockCombos());
  }, []);

  /** 自动轮播 */
  useEffect(() => {
    if (combos.length === 0) return;
    timerRef.current = setInterval(() => {
      setIsTransitioning(true);
      setTimeout(() => {
        setCurrentIndex((prev) => (prev + 1) % combos.length);
        setIsTransitioning(false);
      }, 400);
    }, CAROUSEL_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [combos.length]);

  if (combos.length === 0) return null;
  const combo = combos[currentIndex];

  const containerStyle: CSSProperties = {
    width: '100vw',
    height: '100vh',
    background: 'var(--tx-bg-dark)',
    display: 'flex',
    fontFamily: 'var(--tx-font)',
    overflow: 'hidden',
  };

  const leftStyle: CSSProperties = {
    flex: 1.2,
    position: 'relative',
    overflow: 'hidden',
    transition: 'opacity 0.4s ease',
    opacity: isTransitioning ? 0 : 1,
  };

  const imageStyle: CSSProperties = {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    background: 'linear-gradient(135deg, #1A1A1A 0%, #2A2A2A 100%)',
  };

  const gradientOverlayStyle: CSSProperties = {
    position: 'absolute',
    inset: 0,
    background: 'linear-gradient(to right, transparent 60%, rgba(10,10,10,0.95) 100%)',
  };

  const rightStyle: CSSProperties = {
    flex: 1,
    padding: '48px 40px',
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    transition: 'opacity 0.4s ease, transform 0.4s ease',
    opacity: isTransitioning ? 0 : 1,
    transform: isTransitioning ? 'translateX(20px)' : 'translateX(0)',
  };

  const priceStyle: CSSProperties = {
    fontSize: 56,
    fontWeight: 900,
    color: 'var(--tx-primary)',
    marginBottom: 12,
  };

  const nameStyle: CSSProperties = {
    fontSize: 40,
    fontWeight: 700,
    color: '#FFF',
    marginBottom: 12,
  };

  const servesStyle: CSSProperties = {
    fontSize: 20,
    color: 'var(--tx-text-secondary)',
    marginBottom: 24,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  };

  const descStyle: CSSProperties = {
    fontSize: 20,
    color: 'var(--tx-text-secondary)',
    lineHeight: 1.6,
    marginBottom: 32,
  };

  const dishListStyle: CSSProperties = {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '8px 24px',
    marginBottom: 40,
  };

  const dishItemStyle: CSSProperties = {
    fontSize: 18,
    color: 'var(--tx-text-secondary)',
    padding: '6px 0',
    borderBottom: '1px solid rgba(255,255,255,0.05)',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  };

  const dotStyle: CSSProperties = {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: 'var(--tx-primary)',
    flexShrink: 0,
  };

  const indicatorContainerStyle: CSSProperties = {
    display: 'flex',
    gap: 12,
    alignItems: 'center',
  };

  return (
    <div style={containerStyle}>
      {/* 左侧大图 */}
      <div style={leftStyle}>
        {combo.image ? (
          <img src={combo.image} alt={combo.name} style={imageStyle} />
        ) : (
          <div style={{
            ...imageStyle,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 120,
          }}>
            🍽️
          </div>
        )}
        <div style={gradientOverlayStyle} />
      </div>

      {/* 右侧信息 */}
      <div style={rightStyle}>
        <div style={priceStyle}>
          <span style={{ fontSize: 28, verticalAlign: 'top' }}>¥</span>
          {combo.price}
        </div>
        <div style={nameStyle}>{combo.name}</div>
        <div style={servesStyle}>
          <span style={{ fontSize: 22 }}>👥</span>
          适合 {combo.servesCount}
        </div>
        <div style={descStyle}>{combo.description}</div>

        {/* 菜品组成 */}
        <div style={{ fontSize: 16, color: '#666', marginBottom: 12, fontWeight: 600, letterSpacing: 2 }}>
          套餐包含
        </div>
        <div style={dishListStyle}>
          {combo.dishes.map((d) => (
            <div key={d.name} style={dishItemStyle}>
              <span style={dotStyle} />
              {d.name}
              {d.quantity > 1 && <span style={{ color: '#666' }}> x{d.quantity}</span>}
            </div>
          ))}
        </div>

        {/* 底部: 预订按钮(触控模式) + 轮播指示器 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {touchMode && (
            <button style={{
              padding: '16px 48px',
              fontSize: 22,
              fontWeight: 700,
              background: 'var(--tx-primary)',
              color: '#FFF',
              border: 'none',
              borderRadius: 12,
              cursor: 'pointer',
              transition: 'transform 0.2s ease',
            }}>
              立即预订
            </button>
          )}
          <div style={indicatorContainerStyle}>
            {combos.map((_, i) => (
              <div
                key={i}
                style={{
                  width: i === currentIndex ? 32 : 10,
                  height: 10,
                  borderRadius: 5,
                  background: i === currentIndex ? 'var(--tx-primary)' : '#333',
                  transition: 'all 0.3s ease',
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
