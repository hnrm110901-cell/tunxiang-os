import { useState, useEffect, useCallback, type CSSProperties } from 'react';
import DishCard from '../components/DishCard';
import type { DishItem, MenuWallLayout, RealtimeStatus } from '../api/menuWallApi';
import { getMenuWallLayout, getRealtimeStatus, getTimeRecommendation } from '../api/menuWallApi';

/** 30秒自动刷新 */
const REFRESH_INTERVAL = 30_000;

/** Mock数据 — 后端未就绪时使用 */
function getMockDishes(): DishItem[] {
  const names = [
    '招牌剁椒鱼头', '蒜蓉龙虾', '清蒸多宝鱼', '避风塘炒蟹',
    '白灼基围虾', '椒盐皮皮虾', '蒜蓉粉丝蒸扇贝', '红烧大黄鱼',
    '油焖大虾', '清蒸鲈鱼', '铁板黑椒牛柳', '松鼠桂鱼',
  ];
  return names.map((name, i) => ({
    id: `dish-${i}`,
    name,
    price: Math.floor(68 + Math.random() * 200),
    originalPrice: i % 4 === 0 ? Math.floor(100 + Math.random() * 200) : undefined,
    memberPrice: i % 5 === 0 ? Math.floor(50 + Math.random() * 100) : undefined,
    image: '',
    category: i < 6 ? '海鲜' : '热菜',
    description: `精选优质食材，大厨精心烹制，口感鲜美，回味无穷。`,
    tags: [['招牌', '必点'], ['鲜活', '现做'], ['特色', '人气'], ['经典', '限量']][i % 4],
    isSoldOut: i === 3 || i === 9,
    isRecommended: i < 3,
    isMarketPrice: i === 5,
    timeSlot: (['morning_tea', 'lunch', 'dinner', 'late_night'] as const)[i % 4],
    salesCount: Math.floor(100 + Math.random() * 500),
    rating: 4 + Math.random(),
  }));
}

export default function MenuWall() {
  const [dishes, setDishes] = useState<DishItem[]>([]);
  const [_layout, setLayout] = useState<MenuWallLayout | null>(null);
  const [fadeKey, setFadeKey] = useState(0);
  const [timeSlotLabel, setTimeSlotLabel] = useState('');
  const [lastUpdate, setLastUpdate] = useState('');

  /** 加载数据 */
  const loadData = useCallback(async () => {
    try {
      const [layoutData, timeRec] = await Promise.all([
        getMenuWallLayout(),
        getTimeRecommendation(),
      ]);
      setLayout(layoutData);
      if (layoutData.screens?.[0]?.dishes) {
        setDishes(layoutData.screens[0].dishes);
      }
      if (timeRec?.label) {
        setTimeSlotLabel(timeRec.label);
      }
    } catch {
      // 后端未就绪时使用mock数据
      setDishes(getMockDishes());
      const hour = new Date().getHours();
      if (hour < 11) setTimeSlotLabel('早茶推荐');
      else if (hour < 14) setTimeSlotLabel('午餐推荐');
      else if (hour < 21) setTimeSlotLabel('晚餐推荐');
      else setTimeSlotLabel('宵夜推荐');
    }
    setLastUpdate(new Date().toLocaleTimeString('zh-CN'));
    setFadeKey((k) => k + 1);
  }, []);

  /** 实时状态轮询(沽清/变价) */
  const pollStatus = useCallback(async () => {
    try {
      const status: RealtimeStatus = await getRealtimeStatus();
      setDishes((prev) =>
        prev.map((d) => {
          const soldOut = status.soldOutIds.includes(d.id);
          const priceUpdate = status.updatedPrices.find((p) => p.dishId === d.id);
          return {
            ...d,
            isSoldOut: soldOut || d.isSoldOut,
            price: priceUpdate ? priceUpdate.newPrice : d.price,
          };
        }),
      );
    } catch {
      // 静默处理 — 下次轮询会重试
    }
  }, []);

  useEffect(() => {
    loadData();
    const refreshTimer = setInterval(loadData, REFRESH_INTERVAL);
    const statusTimer = setInterval(pollStatus, 10_000);
    return () => {
      clearInterval(refreshTimer);
      clearInterval(statusTimer);
    };
  }, [loadData, pollStatus]);

  /** 自适应网格: 根据菜品数量决定 */
  const dishCount = dishes.length;
  const cols = dishCount <= 6 ? 3 : dishCount <= 9 ? 3 : 4;
  const rows = Math.ceil(dishCount / cols);

  const containerStyle: CSSProperties = {
    width: '100vw',
    height: '100vh',
    background: 'var(--tx-bg-dark)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    fontFamily: 'var(--tx-font)',
  };

  const headerStyle: CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 32px',
    borderBottom: '1px solid var(--tx-border)',
    flexShrink: 0,
  };

  const titleStyle: CSSProperties = {
    fontSize: 28,
    fontWeight: 700,
    color: 'var(--tx-primary)',
  };

  const subtitleStyle: CSSProperties = {
    fontSize: 18,
    color: 'var(--tx-text-secondary)',
  };

  const gridStyle: CSSProperties = {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: `repeat(${cols}, 1fr)`,
    gridTemplateRows: `repeat(${rows}, 1fr)`,
    gap: 16,
    padding: 16,
    overflow: 'hidden',
  };

  return (
    <div style={containerStyle}>
      {/* 顶部栏 */}
      <div style={headerStyle}>
        <div style={titleStyle}>
          {timeSlotLabel || '今日推荐'}
        </div>
        <div style={subtitleStyle}>
          更新于 {lastUpdate}
        </div>
      </div>

      {/* 菜品网格 */}
      <div key={fadeKey} style={gridStyle}>
        {dishes.slice(0, cols * rows).map((dish, i) => (
          <DishCard
            key={dish.id}
            dish={dish}
            size={dishCount <= 6 ? 'medium' : 'small'}
            animationDelay={i * 60}
          />
        ))}
      </div>
    </div>
  );
}
