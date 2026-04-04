/**
 * 等候区互动屏
 * 布局：1920x1080，给等位顾客看
 * 上半：排队叫号信息（大/中/小桌分别显示）
 * 下半：推荐菜品轮播 + 品牌故事卡片
 * 10秒轮询排队数据
 */
import { useState, useEffect, useCallback, type CSSProperties } from 'react';

/* ======================== 类型 ======================== */
interface TableQueue {
  label: string;
  current_number: string;
  waiting_count: number;
}

interface QueueData {
  store_name: string;
  current_call: string; // 当前叫到的号码
  queues: TableQueue[];  // 小桌/中桌/大桌
}

interface RecommendDish {
  name: string;
  price: number;
  image_placeholder: string; // 占位色
  reason: string;
}

interface BrandStory {
  title: string;
  content: string;
}

/* ======================== Mock数据 ======================== */
const MOCK_QUEUE: QueueData = {
  store_name: '徐记海鲜 \u00b7 长沙总店',
  current_call: 'A038',
  queues: [
    { label: '小桌 (2人)', current_number: 'A038', waiting_count: 5 },
    { label: '中桌 (4人)', current_number: 'B021', waiting_count: 8 },
    { label: '大桌 (8人)', current_number: 'C012', waiting_count: 3 },
  ],
};

const RECOMMEND_DISHES: RecommendDish[] = [
  { name: '蒜蓉粉丝蒸扇贝', price: 68, image_placeholder: '#2a4a3a', reason: '今日鲜捞，蒜香四溢' },
  { name: '清蒸石斑鱼', price: 188, image_placeholder: '#3a2a4a', reason: '深海野生，肉质弹嫩' },
  { name: '避风塘炒蟹', price: 158, image_placeholder: '#4a3a2a', reason: '港式经典，酥脆可口' },
  { name: '龙虾刺身拼盘', price: 388, image_placeholder: '#2a3a4a', reason: '主厨推荐，极致鲜甜' },
  { name: '白灼基围虾', price: 98, image_placeholder: '#3a4a2a', reason: '活虾现做，原汁原味' },
];

const BRAND_STORIES: BrandStory[] = [
  {
    title: '品牌故事',
    content: '徐记海鲜创立于1999年，秉承"新鲜为本、品质至上"的经营理念，二十余年来坚持每日从产地直采新鲜海鲜，为顾客呈现最地道的海鲜美味。',
  },
  {
    title: '匠心工艺',
    content: '我们的每一位厨师都经过严格的培训与考核，传承粤式海鲜烹饪精髓，结合湖湘口味创新，打造独一无二的味觉体验。',
  },
  {
    title: '食材承诺',
    content: '所有海鲜均来自深海优质产区，当日捕捞、冷链直达，从海洋到餐桌不超过24小时。每一道菜品都可追溯食材来源。',
  },
];

/* ======================== API ======================== */
async function fetchQueueData(storeId = 'store-001'): Promise<QueueData> {
  const res = await fetch(`/api/v1/trade/waitlist/detailed?store_id=${storeId}`, {
    headers: { 'X-Tenant-ID': 'demo-tenant' },
  });
  if (!res.ok) throw new Error('API error');
  const json = await res.json();
  if (!json.ok) throw new Error('API error');
  return json.data as QueueData;
}

/* ======================== 主组件 ======================== */
export default function WaitingDisplayPage() {
  const [queueData, setQueueData] = useState<QueueData>(MOCK_QUEUE);
  const [currentTime, setCurrentTime] = useState('');
  const [blink, setBlink] = useState(false);
  const [dishIndex, setDishIndex] = useState(0);
  const [storyIndex, setStoryIndex] = useState(0);
  const [dishFade, setDishFade] = useState(true);
  const [storyFade, setStoryFade] = useState(true);

  /* 实时时钟 */
  useEffect(() => {
    const update = () => {
      setCurrentTime(new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }));
    };
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, []);

  /* 新号码闪烁 */
  const triggerBlink = useCallback(() => {
    setBlink(true);
    setTimeout(() => setBlink(false), 2000);
  }, []);

  /* 10秒轮询排队数据 */
  const loadData = useCallback(async () => {
    try {
      const fresh = await fetchQueueData();
      setQueueData((prev) => {
        if (prev.current_call !== fresh.current_call) triggerBlink();
        return fresh;
      });
    } catch {
      // 静默降级
    }
  }, [triggerBlink]);

  useEffect(() => {
    loadData();
    const t = setInterval(loadData, 10_000);
    return () => clearInterval(t);
  }, [loadData]);

  /* 菜品轮播 10s */
  useEffect(() => {
    const t = setInterval(() => {
      setDishFade(false);
      setTimeout(() => {
        setDishIndex((prev) => (prev + 1) % RECOMMEND_DISHES.length);
        setDishFade(true);
      }, 400);
    }, 10_000);
    return () => clearInterval(t);
  }, []);

  /* 品牌故事轮播 30s */
  useEffect(() => {
    const t = setInterval(() => {
      setStoryFade(false);
      setTimeout(() => {
        setStoryIndex((prev) => (prev + 1) % BRAND_STORIES.length);
        setStoryFade(true);
      }, 400);
    }, 30_000);
    return () => clearInterval(t);
  }, []);

  /* CSS注入 */
  useEffect(() => {
    const styleId = 'waiting-blink-style';
    if (!document.getElementById(styleId)) {
      const style = document.createElement('style');
      style.id = styleId;
      style.textContent = `
        @keyframes waiting-blink {
          0%, 100% { opacity: 1; }
          25% { opacity: 0.2; }
          50% { opacity: 1; }
          75% { opacity: 0.2; }
        }
      `;
      document.head.appendChild(style);
    }
    return () => {
      const el = document.getElementById(styleId);
      if (el) el.remove();
    };
  }, []);

  const currentDish = RECOMMEND_DISHES[dishIndex];
  const currentStory = BRAND_STORIES[storyIndex];

  /* ===== 样式 ===== */
  const rootStyle: CSSProperties = {
    width: 1920,
    height: 1080,
    overflow: 'hidden',
    background: 'linear-gradient(180deg, #0d0500 0%, #1a0a00 40%, #0d0500 100%)',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    cursor: 'none',
    userSelect: 'none',
  };

  /* 顶部信息条 */
  const headerStyle: CSSProperties = {
    flexShrink: 0,
    height: 60,
    background: 'linear-gradient(90deg, #3d1200 0%, #2a0e00 50%, #3d1200 100%)',
    borderBottom: '2px solid #FF6B35',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 60px',
  };

  /* 排队信息区（上半） */
  const queueSectionStyle: CSSProperties = {
    height: '50%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '20px 60px',
    gap: 30,
    borderBottom: '2px solid #2a1500',
  };

  /* 娱乐区（下半） */
  const entertainSectionStyle: CSSProperties = {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  };

  /* 当前叫号大字 */
  const bigNumberStyle: CSSProperties = {
    fontSize: 200,
    fontWeight: 900,
    color: '#E53935',
    lineHeight: 1,
    fontVariantNumeric: 'tabular-nums',
    textShadow: '0 0 80px rgba(229, 57, 53, 0.6)',
    letterSpacing: 8,
    animation: blink ? 'waiting-blink 0.5s ease-in-out 4' : 'none',
  };

  /* 桌型卡片 */
  const queueCardStyle: CSSProperties = {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid #3d2000',
    borderRadius: 16,
    padding: '20px 40px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 8,
    minWidth: 260,
  };

  return (
    <div style={rootStyle}>
      {/* ===== 顶部 ===== */}
      <div style={headerStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 6,
            background: 'linear-gradient(135deg, #FF6B35, #FF8555)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 18, fontWeight: 900, color: '#fff',
          }}>TX</div>
          <span style={{ fontSize: 26, fontWeight: 800, color: '#fff', letterSpacing: 4 }}>
            {queueData.store_name}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 30 }}>
          <span style={{ fontSize: 20, fontWeight: 700, color: '#FF6B35' }}>排队叫号</span>
          <span style={{
            fontSize: 24, fontWeight: 600, color: '#c8a882',
            fontVariantNumeric: 'tabular-nums',
          }}>{currentTime}</span>
        </div>
      </div>

      {/* ===== 排队信息区（上半 50%） ===== */}
      <div style={queueSectionStyle}>
        {/* 当前叫号 */}
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 36, fontWeight: 700, color: '#c8a882', letterSpacing: 8, marginBottom: 10 }}>
            当前叫号
          </div>
          <div style={bigNumberStyle}>{queueData.current_call}</div>
        </div>

        {/* 小桌/中桌/大桌 */}
        <div style={{ display: 'flex', gap: 40 }}>
          {queueData.queues.map((q, i) => (
            <div key={i} style={queueCardStyle}>
              <div style={{ fontSize: 22, fontWeight: 600, color: '#9e7a55', letterSpacing: 2 }}>
                {q.label}
              </div>
              <div style={{
                fontSize: 48, fontWeight: 900, color: '#FF6B35',
                fontVariantNumeric: 'tabular-nums',
                textShadow: '0 0 20px rgba(255, 107, 53, 0.4)',
              }}>
                {q.current_number}
              </div>
              <div style={{ fontSize: 18, color: '#888' }}>
                等待 <span style={{ fontSize: 24, fontWeight: 800, color: '#FFD54F' }}>{q.waiting_count}</span> 桌
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ===== 娱乐区（下半 50%） ===== */}
      <div style={entertainSectionStyle}>
        {/* 左侧：推荐菜品轮播 */}
        <div style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '30px 60px',
          borderRight: '2px solid #2a1500',
          opacity: dishFade ? 1 : 0,
          transition: 'opacity 0.4s ease',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
            {/* 菜品图片占位 */}
            <div style={{
              width: 360, height: 360, borderRadius: 20,
              background: currentDish.image_placeholder,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 28, color: 'rgba(255,255,255,0.2)', fontWeight: 600,
              border: '2px solid #3d2000',
              flexShrink: 0,
            }}>
              菜品图片
            </div>
            {/* 菜品信息 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ fontSize: 20, color: '#FF6B35', fontWeight: 700, letterSpacing: 4 }}>
                今日推荐
              </div>
              <div style={{ fontSize: 48, fontWeight: 900, color: '#fff', letterSpacing: 4 }}>
                {currentDish.name}
              </div>
              <div style={{ fontSize: 56, fontWeight: 900, color: '#FF6B35', fontVariantNumeric: 'tabular-nums' }}>
                {'\u00A5'}{currentDish.price}
              </div>
              <div style={{
                fontSize: 24, color: '#c8a882', lineHeight: 1.6,
                padding: '12px 20px', borderRadius: 8,
                background: 'rgba(255,255,255,0.03)', border: '1px solid #3d2000',
              }}>
                {currentDish.reason}
              </div>
              <div style={{ fontSize: 16, color: '#555' }}>
                {dishIndex + 1} / {RECOMMEND_DISHES.length} \u00b7 每10秒自动切换
              </div>
            </div>
          </div>
        </div>

        {/* 右侧：品牌故事卡片 */}
        <div style={{
          width: 480,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '40px 40px',
          opacity: storyFade ? 1 : 0,
          transition: 'opacity 0.4s ease',
        }}>
          <div style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid #3d2000',
            borderRadius: 20,
            padding: '40px 36px',
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
            width: '100%',
          }}>
            {/* 装饰引号 */}
            <div style={{ fontSize: 60, color: '#FF6B35', lineHeight: 0.6, opacity: 0.4 }}>{'\u201C'}</div>
            <div style={{ fontSize: 28, fontWeight: 800, color: '#fff', letterSpacing: 4 }}>
              {currentStory.title}
            </div>
            <div style={{ fontSize: 20, color: '#c8a882', lineHeight: 1.8, letterSpacing: 1 }}>
              {currentStory.content}
            </div>
            <div style={{ fontSize: 60, color: '#FF6B35', lineHeight: 0.6, opacity: 0.4, textAlign: 'right' }}>{'\u201D'}</div>
          </div>
          <div style={{ fontSize: 14, color: '#555', marginTop: 16 }}>
            {storyIndex + 1} / {BRAND_STORIES.length} \u00b7 每30秒自动切换
          </div>
        </div>
      </div>
    </div>
  );
}
