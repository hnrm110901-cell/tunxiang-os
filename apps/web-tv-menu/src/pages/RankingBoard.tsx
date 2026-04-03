import { useState, useEffect, useCallback, useRef, type CSSProperties } from 'react';
import type { RankingData, RankingItem } from '../api/menuWallApi';
import { getRankingBoard } from '../api/menuWallApi';

/** 三个榜单轮播 */
const METRICS = [
  { key: 'hot_sales', label: '本周热销 TOP10', icon: '🔥' },
  { key: 'best_rated', label: '好评最多 TOP10', icon: '⭐' },
  { key: 'repeat_buy', label: '回头客最爱 TOP10', icon: '💛' },
] as const;

/** 每8秒切换榜单 */
const SWITCH_INTERVAL = 8_000;

/** Mock排行数据 */
function getMockRanking(metricIdx: number): RankingItem[] {
  const dishes = [
    ['招牌剁椒鱼头', '蒜蓉龙虾', '清蒸多宝鱼', '避风塘炒蟹', '白灼基围虾',
     '椒盐皮皮虾', '蒜蓉粉丝蒸扇贝', '红烧大黄鱼', '油焖大虾', '清蒸鲈鱼'],
    ['松鼠桂鱼', '蒜蓉龙虾', '招牌剁椒鱼头', '铁板黑椒牛柳', '清蒸多宝鱼',
     '白灼基围虾', '红烧大黄鱼', '油焖大虾', '避风塘炒蟹', '蒜蓉粉丝蒸扇贝'],
    ['清蒸多宝鱼', '招牌剁椒鱼头', '蒜蓉龙虾', '白灼基围虾', '铁板黑椒牛柳',
     '椒盐皮皮虾', '避风塘炒蟹', '松鼠桂鱼', '油焖大虾', '红烧大黄鱼'],
  ];
  const labels = ['份', '分', '次'];
  return dishes[metricIdx].map((name, i) => ({
    rank: i + 1,
    dishId: `dish-${i}`,
    name,
    value: metricIdx === 1 ? +(4.5 + Math.random() * 0.5).toFixed(1) : Math.floor(300 - i * 25 + Math.random() * 20),
    label: labels[metricIdx],
  }));
}

const medalColors = ['var(--tx-gold)', 'var(--tx-silver)', 'var(--tx-bronze)'];

export default function RankingBoard() {
  const [currentMetricIdx, setCurrentMetricIdx] = useState(0);
  const [items, setItems] = useState<RankingItem[]>([]);
  const [isFading, setIsFading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  const loadRanking = useCallback(async (metricIdx: number) => {
    const metric = METRICS[metricIdx];
    try {
      const data: RankingData = await getRankingBoard(metric.key);
      setItems(data.items);
    } catch {
      setItems(getMockRanking(metricIdx));
    }
  }, []);

  /** 切换榜单(带淡入淡出) */
  const switchMetric = useCallback(() => {
    setIsFading(true);
    setTimeout(() => {
      setCurrentMetricIdx((prev) => {
        const next = (prev + 1) % METRICS.length;
        loadRanking(next);
        return next;
      });
      setIsFading(false);
    }, 400);
  }, [loadRanking]);

  useEffect(() => {
    loadRanking(0);
    timerRef.current = setInterval(switchMetric, SWITCH_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [loadRanking, switchMetric]);

  const metric = METRICS[currentMetricIdx];

  const containerStyle: CSSProperties = {
    width: '100vw',
    height: '100vh',
    background: 'var(--tx-bg-dark)',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: 'var(--tx-font)',
    overflow: 'hidden',
  };

  const headerStyle: CSSProperties = {
    padding: '28px 48px',
    borderBottom: '2px solid var(--tx-border)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexShrink: 0,
  };

  const indicatorStyle: CSSProperties = {
    display: 'flex',
    gap: 12,
  };

  const listStyle: CSSProperties = {
    flex: 1,
    padding: '16px 48px',
    overflow: 'hidden',
    transition: 'opacity 0.4s ease',
    opacity: isFading ? 0 : 1,
  };

  return (
    <div style={containerStyle}>
      {/* 顶部 */}
      <div style={headerStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontSize: 40 }}>{metric.icon}</span>
          <span style={{ fontSize: 36, fontWeight: 700, color: '#FFF', letterSpacing: 2 }}>
            {metric.label}
          </span>
        </div>
        {/* 榜单指示器 */}
        <div style={indicatorStyle}>
          {METRICS.map((m, i) => (
            <div
              key={m.key}
              style={{
                width: 40,
                height: 6,
                borderRadius: 3,
                background: i === currentMetricIdx ? 'var(--tx-primary)' : '#333',
                transition: 'background 0.3s ease',
              }}
            />
          ))}
        </div>
      </div>

      {/* 排行列表 */}
      <div style={listStyle}>
        {items.map((item, i) => {
          const isTopThree = item.rank <= 3;
          const medalColor = isTopThree ? medalColors[item.rank - 1] : undefined;

          const rowStyle: CSSProperties = {
            display: 'flex',
            alignItems: 'center',
            padding: '14px 0',
            borderBottom: '1px solid rgba(255,255,255,0.05)',
            animation: `tx-slide-up 0.3s ease-out ${i * 60}ms both`,
          };

          const rankStyle: CSSProperties = {
            width: 80,
            fontSize: isTopThree ? 48 : 32,
            fontWeight: 900,
            color: medalColor || 'var(--tx-text-tertiary)',
            textAlign: 'center',
            flexShrink: 0,
            textShadow: isTopThree ? `0 2px 12px ${medalColor}66` : 'none',
          };

          const nameStyle: CSSProperties = {
            flex: 1,
            fontSize: isTopThree ? 30 : 24,
            fontWeight: isTopThree ? 700 : 500,
            color: isTopThree ? '#FFF' : 'var(--tx-text-secondary)',
            paddingLeft: 16,
          };

          const valueStyle: CSSProperties = {
            fontSize: isTopThree ? 32 : 24,
            fontWeight: 700,
            color: isTopThree ? 'var(--tx-primary)' : 'var(--tx-text-secondary)',
            fontVariantNumeric: 'tabular-nums',
            minWidth: 120,
            textAlign: 'right',
          };

          return (
            <div key={item.dishId} style={rowStyle}>
              <div style={rankStyle}>{item.rank}</div>
              {isTopThree && (
                <div style={{
                  width: 12,
                  height: 12,
                  borderRadius: '50%',
                  background: medalColor,
                  boxShadow: `0 0 12px ${medalColor}`,
                  flexShrink: 0,
                }} />
              )}
              <div style={nameStyle}>{item.name}</div>
              <div style={valueStyle}>
                {item.value}
                <span style={{ fontSize: 16, color: '#666', marginLeft: 4 }}>{item.label}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
