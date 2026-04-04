/**
 * 页面A：主菜单展示屏
 * 布局：1920×1080，深色主题，左侧分类栏 + 右侧菜品网格 + 底部跑马灯
 * 纯展示（无用户交互），每60秒刷新API，每30秒自动切换分类
 */
import { useState, useEffect, useCallback, type CSSProperties } from 'react';

/* ======================== 类型 ======================== */
interface Category {
  id: string;
  name: string;
}

interface Dish {
  id: string;
  name: string;
  price_fen: number;
  spec: string;
  is_soldout: boolean;
  image?: string;
}

/* ======================== Mock数据 ======================== */
const MOCK_CATEGORIES: Category[] = [
  { id: '1', name: '招牌菜品' },
  { id: '2', name: '海鲜精选' },
  { id: '3', name: '家常小炒' },
  { id: '4', name: '汤羹炖品' },
  { id: '5', name: '主食面点' },
  { id: '6', name: '时令蔬菜' },
  { id: '7', name: '荤素凉菜' },
  { id: '8', name: '精酿饮品' },
  { id: '9', name: '酱卤拼盘' },
  { id: '10', name: '明炉烧烤' },
  { id: '11', name: '特色甜品' },
  { id: '12', name: '儿童套餐' },
];

const MOCK_DISHES_BY_CATEGORY: Record<string, Dish[]> = {
  '1': [
    { id: 'd1', name: '红烧狮子头', price_fen: 6800, spec: '例', is_soldout: false },
    { id: 'd2', name: '清蒸桂鱼', price_fen: 12800, spec: '条（约1.2斤）', is_soldout: false },
    { id: 'd3', name: '秘制东坡肉', price_fen: 5800, spec: '例', is_soldout: false },
    { id: 'd4', name: '招牌剁椒鱼头', price_fen: 8800, spec: '个', is_soldout: true },
    { id: 'd5', name: '外婆红烧肉', price_fen: 4800, spec: '例', is_soldout: false },
    { id: 'd6', name: '荷叶粉蒸肉', price_fen: 3800, spec: '例', is_soldout: false },
    { id: 'd7', name: '梅菜扣肉', price_fen: 4200, spec: '例', is_soldout: false },
    { id: 'd8', name: '糖醋里脊', price_fen: 3600, spec: '例', is_soldout: false },
    { id: 'd9', name: '松鼠桂鱼', price_fen: 9800, spec: '条', is_soldout: false },
    { id: 'd10', name: '锅包肉', price_fen: 3200, spec: '例', is_soldout: false },
    { id: 'd11', name: '北京烤鸭', price_fen: 16800, spec: '只', is_soldout: false },
    { id: 'd12', name: '叫花鸡', price_fen: 11800, spec: '只', is_soldout: true },
  ],
  '2': [
    { id: 's1', name: '蒜蓉龙虾', price_fen: 0, spec: '斤（时价）', is_soldout: false },
    { id: 's2', name: '清蒸大闸蟹', price_fen: 8800, spec: '只', is_soldout: false },
    { id: 's3', name: '白灼基围虾', price_fen: 6800, spec: '例', is_soldout: false },
    { id: 's4', name: '椒盐皮皮虾', price_fen: 5800, spec: '例', is_soldout: false },
    { id: 's5', name: '蒜蓉扇贝', price_fen: 4800, spec: '例（8个）', is_soldout: false },
    { id: 's6', name: '避风塘炒蟹', price_fen: 0, spec: '斤（时价）', is_soldout: false },
    { id: 's7', name: '清蒸多宝鱼', price_fen: 0, spec: '斤（时价）', is_soldout: true },
    { id: 's8', name: '油焖大虾', price_fen: 8800, spec: '例', is_soldout: false },
    { id: 's9', name: '盐焗虾', price_fen: 7200, spec: '例', is_soldout: false },
    { id: 's10', name: '蒸石斑鱼', price_fen: 0, spec: '斤（时价）', is_soldout: false },
    { id: 's11', name: '鲜炒花蛤', price_fen: 3800, spec: '例', is_soldout: false },
    { id: 's12', name: '葱烧海参', price_fen: 28800, spec: '例', is_soldout: false },
  ],
};

function getMockDishesForCategory(categoryId: string): Dish[] {
  return MOCK_DISHES_BY_CATEGORY[categoryId] || MOCK_DISHES_BY_CATEGORY['1'];
}

/* ======================== 跑马灯文案 ======================== */
const TICKER_MESSAGES = [
  '🔥 今日特价：红烧狮子头 ¥68，限量50份，先到先得！',
  '🎉 本周新品上线：荷塘月色特色套餐，4人位仅 ¥298！',
  '⭐ 会员专享：扫码加入会员，当日消费享9折优惠！',
  '🌿 食材承诺：所有食材每日清晨新鲜采购，品质保证！',
  '📱 扫码点餐：无需等待服务员，随时随地点您喜爱的菜品！',
];

/* ======================== API ======================== */
async function fetchCategories(): Promise<Category[]> {
  const res = await fetch('/api/v1/menu/categories', {
    headers: { 'X-Tenant-ID': 'demo-tenant' },
  });
  if (!res.ok) throw new Error('API error');
  const json = await res.json();
  if (!json.ok) throw new Error('API error');
  return json.data as Category[];
}

async function fetchDishes(categoryId: string): Promise<Dish[]> {
  const res = await fetch(
    `/api/v1/menu/dishes?category_id=${categoryId}&is_available=true`,
    { headers: { 'X-Tenant-ID': 'demo-tenant' } },
  );
  if (!res.ok) throw new Error('API error');
  const json = await res.json();
  if (!json.ok) throw new Error('API error');
  return json.data as Dish[];
}

/* ======================== 子组件：菜品卡片 ======================== */
function DishCardTV({ dish }: { dish: Dish }) {
  const cardStyle: CSSProperties = {
    position: 'relative',
    background: '#2a1500',
    borderRadius: 12,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    border: '1px solid #3d2200',
  };

  const imgAreaStyle: CSSProperties = {
    width: '100%',
    height: 150,
    background: 'linear-gradient(135deg, #3d2000 0%, #2a1800 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  };

  const infoStyle: CSSProperties = {
    padding: '12px 14px',
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  };

  const nameStyle: CSSProperties = {
    fontSize: 24,
    fontWeight: 700,
    color: '#FFFFFF',
    lineHeight: 1.3,
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 1,
    WebkitBoxOrient: 'vertical',
  };

  const specStyle: CSSProperties = {
    fontSize: 18,
    color: '#9e7a55',
    lineHeight: 1.3,
  };

  const priceStyle: CSSProperties = {
    fontSize: 32,
    fontWeight: 800,
    color: '#FF6B35',
    lineHeight: 1.2,
    marginTop: 'auto',
  };

  const soldoutOverlayStyle: CSSProperties = {
    position: 'absolute',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.72)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 2,
  };

  const soldoutTextStyle: CSSProperties = {
    fontSize: 28,
    fontWeight: 700,
    color: '#B0B0B0',
    letterSpacing: 4,
    border: '2px solid #666',
    padding: '8px 20px',
    borderRadius: 8,
  };

  const priceDisplay = dish.price_fen > 0
    ? `¥${(dish.price_fen / 100).toFixed(0)}`
    : '时价';

  return (
    <div style={cardStyle}>
      {/* 图片区域 */}
      <div style={imgAreaStyle}>
        {dish.image ? (
          <img src={dish.image} alt={dish.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
            <circle cx="32" cy="32" r="28" fill="#4a2800" />
            <path d="M20 32 Q32 20 44 32 Q32 44 20 32Z" fill="#6b3c00" />
            <circle cx="32" cy="32" r="8" fill="#8b5200" />
          </svg>
        )}
      </div>

      {/* 菜品信息 */}
      <div style={infoStyle}>
        <div style={nameStyle}>{dish.name}</div>
        <div style={specStyle}>{dish.spec}</div>
        <div style={priceStyle}>{priceDisplay}</div>
      </div>

      {/* 售罄蒙层 */}
      {dish.is_soldout && (
        <div style={soldoutOverlayStyle}>
          <span style={soldoutTextStyle}>今日售罄</span>
        </div>
      )}
    </div>
  );
}

/* ======================== 主组件 ======================== */
export default function MenuDisplayPage() {
  const [categories, setCategories] = useState<Category[]>(MOCK_CATEGORIES);
  const [dishes, setDishes] = useState<Dish[]>([]);
  const [activeCatIndex, setActiveCatIndex] = useState(0);
  const [currentTime, setCurrentTime] = useState('');
  const [tickerIndex, setTickerIndex] = useState(0);

  /* 实时时钟 */
  useEffect(() => {
    const updateTime = () => {
      setCurrentTime(new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  /* 跑马灯文案轮换 */
  useEffect(() => {
    const timer = setInterval(() => {
      setTickerIndex((i) => (i + 1) % TICKER_MESSAGES.length);
    }, 10_000);
    return () => clearInterval(timer);
  }, []);

  /* 加载分类列表（降级mock） */
  const loadCategories = useCallback(async () => {
    try {
      const data = await fetchCategories();
      if (data.length > 0) setCategories(data);
    } catch {
      setCategories(MOCK_CATEGORIES);
    }
  }, []);

  /* 加载当前分类的菜品（降级mock） */
  const loadDishes = useCallback(async (categoryId: string) => {
    try {
      const data = await fetchDishes(categoryId);
      setDishes(data);
    } catch {
      setDishes(getMockDishesForCategory(categoryId));
    }
  }, []);

  /* 初始化 + 60秒全量刷新 */
  useEffect(() => {
    loadCategories();
    const timer = setInterval(loadCategories, 60_000);
    return () => clearInterval(timer);
  }, [loadCategories]);

  /* 分类切换时加载菜品 */
  useEffect(() => {
    if (categories.length === 0) return;
    const cat = categories[activeCatIndex];
    loadDishes(cat.id);
  }, [activeCatIndex, categories, loadDishes]);

  /* 每30秒自动切换分类 */
  useEffect(() => {
    const timer = setInterval(() => {
      setActiveCatIndex((i) => (i + 1) % categories.length);
    }, 30_000);
    return () => clearInterval(timer);
  }, [categories.length]);

  /* ===== 样式 ===== */
  const rootStyle: CSSProperties = {
    width: 1920,
    height: 1080,
    overflow: 'hidden',
    background: '#1a0a00',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    cursor: 'none',
    userSelect: 'none',
  };

  /* 顶栏 80px */
  const headerStyle: CSSProperties = {
    height: 80,
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 40px',
    background: 'linear-gradient(90deg, #2d1200 0%, #1a0a00 100%)',
    borderBottom: '2px solid #3d2000',
  };

  const logoStyle: CSSProperties = {
    fontSize: 36,
    fontWeight: 900,
    color: '#FF6B35',
    letterSpacing: 2,
  };

  const storeNameStyle: CSSProperties = {
    fontSize: 32,
    fontWeight: 600,
    color: '#FFE0CC',
    letterSpacing: 4,
    position: 'absolute',
    left: '50%',
    transform: 'translateX(-50%)',
  };

  const clockStyle: CSSProperties = {
    fontSize: 36,
    fontWeight: 700,
    color: '#FF6B35',
    fontVariantNumeric: 'tabular-nums',
    letterSpacing: 2,
  };

  /* 中间主体区域 900px */
  const bodyStyle: CSSProperties = {
    height: 900,
    flexShrink: 0,
    display: 'flex',
    overflow: 'hidden',
  };

  /* 左侧分类栏 240px */
  const categoryBarStyle: CSSProperties = {
    width: 240,
    flexShrink: 0,
    background: '#2d1500',
    borderRight: '2px solid #3d2000',
    display: 'flex',
    flexDirection: 'column',
    overflowY: 'hidden',
    padding: '12px 0',
  };

  /* 菜品展示区 */
  const dishGridWrapStyle: CSSProperties = {
    flex: 1,
    padding: '20px 24px',
    overflow: 'hidden',
  };

  const dishGridStyle: CSSProperties = {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gridTemplateRows: 'repeat(3, 1fr)',
    gap: 16,
    height: '100%',
  };

  /* 底部跑马灯 100px */
  const tickerStyle: CSSProperties = {
    height: 100,
    flexShrink: 0,
    background: '#FF6B35',
    display: 'flex',
    alignItems: 'center',
    overflow: 'hidden',
    borderTop: '2px solid #e55a28',
  };

  const tickerLabelStyle: CSSProperties = {
    flexShrink: 0,
    padding: '0 28px',
    fontSize: 28,
    fontWeight: 700,
    color: '#fff',
    background: '#cc4f1e',
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    borderRight: '2px solid #e55a28',
    letterSpacing: 2,
  };

  const tickerTrackStyle: CSSProperties = {
    flex: 1,
    overflow: 'hidden',
    position: 'relative',
  };

  const tickerTextStyle: CSSProperties = {
    display: 'inline-block',
    fontSize: 28,
    fontWeight: 600,
    color: '#fff',
    whiteSpace: 'nowrap',
    animation: 'tx-scroll-left 18s linear infinite',
    letterSpacing: 1,
  };

  return (
    <div style={rootStyle}>
      {/* ===== 顶栏 ===== */}
      <div style={{ ...headerStyle, position: 'relative' }}>
        <div style={logoStyle}>屯象餐饮</div>
        <div style={storeNameStyle}>徐记海鲜 · 长沙总店</div>
        <div style={clockStyle}>{currentTime}</div>
      </div>

      {/* ===== 主体 ===== */}
      <div style={bodyStyle}>
        {/* 左侧分类栏 */}
        <div style={categoryBarStyle}>
          {categories.map((cat, index) => {
            const isActive = index === activeCatIndex;
            const itemStyle: CSSProperties = {
              height: 68,
              display: 'flex',
              alignItems: 'center',
              paddingLeft: isActive ? 20 : 24,
              fontSize: 24,
              fontWeight: isActive ? 700 : 400,
              color: isActive ? '#FF6B35' : '#c8a882',
              background: isActive ? 'rgba(255, 107, 53, 0.12)' : 'transparent',
              borderLeft: isActive ? '5px solid #FF6B35' : '5px solid transparent',
              cursor: 'none',
              transition: 'all 0.3s ease',
              letterSpacing: 1,
              flexShrink: 0,
            };
            return (
              <div key={cat.id} style={itemStyle}>
                {cat.name}
              </div>
            );
          })}
        </div>

        {/* 菜品展示区 */}
        <div style={dishGridWrapStyle}>
          <div style={dishGridStyle}>
            {dishes.slice(0, 12).map((dish) => (
              <DishCardTV key={dish.id} dish={dish} />
            ))}
          </div>
        </div>
      </div>

      {/* ===== 底部跑马灯 ===== */}
      <div style={tickerStyle}>
        <div style={tickerLabelStyle}>今日特惠</div>
        <div style={tickerTrackStyle}>
          <div style={tickerTextStyle}>
            {TICKER_MESSAGES[tickerIndex]}
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
            {TICKER_MESSAGES[(tickerIndex + 1) % TICKER_MESSAGES.length]}
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
            {TICKER_MESSAGES[(tickerIndex + 2) % TICKER_MESSAGES.length]}
          </div>
        </div>
      </div>
    </div>
  );
}
