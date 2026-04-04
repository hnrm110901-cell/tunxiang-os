/**
 * 页面C：等位叫号屏
 * 布局：1920×1080，显示当前叫号、等待桌数、最近叫号记录
 * 每10秒从API刷新，纯展示（无用户交互）
 */
import { useState, useEffect, useCallback, type CSSProperties } from 'react';

/* ======================== 类型 ======================== */
interface WaitlistData {
  current_number: string;
  waiting_tables: number;
  recent_numbers: string[];
  store_name: string;
  estimated_minutes: number;
}

/* ======================== Mock数据 ======================== */
const MOCK_WAITLIST: WaitlistData = {
  current_number: 'A025',
  waiting_tables: 8,
  recent_numbers: ['A019', 'A020', 'A021', 'A022', 'A023', 'A024', 'A025'],
  store_name: '徐记海鲜 · 长沙总店',
  estimated_minutes: 25,
};

/* ======================== API ======================== */
async function fetchWaitlist(storeId = 'store-001'): Promise<WaitlistData> {
  const res = await fetch(`/api/v1/trade/waitlist/current?store_id=${storeId}`, {
    headers: { 'X-Tenant-ID': 'demo-tenant' },
  });
  if (!res.ok) throw new Error('API error');
  const json = await res.json();
  if (!json.ok) throw new Error('API error');
  return json.data as WaitlistData;
}

/* ======================== 主组件 ======================== */
export default function QueueDisplayPage() {
  const [data, setData] = useState<WaitlistData>(MOCK_WAITLIST);
  const [currentTime, setCurrentTime] = useState('');
  const [pulse, setPulse] = useState(false);

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

  /* 叫号数字脉冲动画触发器 */
  const triggerPulse = useCallback(() => {
    setPulse(true);
    setTimeout(() => setPulse(false), 800);
  }, []);

  /* 每10秒刷新等位数据 */
  const loadData = useCallback(async () => {
    try {
      const fresh = await fetchWaitlist();
      setData((prev) => {
        if (prev.current_number !== fresh.current_number) triggerPulse();
        return fresh;
      });
    } catch {
      // 静默降级，保留上次数据
    }
  }, [triggerPulse]);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 10_000);
    return () => clearInterval(timer);
  }, [loadData]);

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

  /* 顶部欢迎横幅 */
  const bannerStyle: CSSProperties = {
    flexShrink: 0,
    height: 160,
    background: 'linear-gradient(90deg, #3d1200 0%, #2a0e00 50%, #3d1200 100%)',
    borderBottom: '3px solid #FF6B35',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 80px',
  };

  const welcomeStyle: CSSProperties = {
    fontSize: 56,
    fontWeight: 900,
    color: '#FFFFFF',
    letterSpacing: 8,
    textShadow: '0 2px 20px rgba(255, 107, 53, 0.3)',
  };

  const storeTagStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-end',
    gap: 8,
  };

  const storeNameStyle: CSSProperties = {
    fontSize: 36,
    fontWeight: 700,
    color: '#FF6B35',
    letterSpacing: 4,
  };

  const clockStyle: CSSProperties = {
    fontSize: 32,
    fontWeight: 600,
    color: '#c8a882',
    fontVariantNumeric: 'tabular-nums',
    letterSpacing: 2,
  };

  /* 中间主内容区 */
  const mainStyle: CSSProperties = {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 0,
    overflow: 'hidden',
  };

  /* 左侧：当前叫号 */
  const currentCallStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '40px 60px',
    borderRight: '2px solid #3d2000',
    gap: 20,
  };

  const callLabelStyle: CSSProperties = {
    fontSize: 40,
    fontWeight: 700,
    color: '#c8a882',
    letterSpacing: 8,
  };

  const callNumberStyle: CSSProperties = {
    fontSize: 200,
    fontWeight: 900,
    color: '#E53935',
    lineHeight: 1,
    fontVariantNumeric: 'tabular-nums',
    textShadow: '0 0 60px rgba(229, 57, 53, 0.6)',
    transition: 'transform 0.3s ease',
    transform: pulse ? 'scale(1.1)' : 'scale(1)',
    letterSpacing: 4,
  };

  const callSubStyle: CSSProperties = {
    fontSize: 32,
    color: '#9e7a55',
    letterSpacing: 2,
  };

  /* 右侧：等待桌数 + 预计时间 */
  const waitingStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '40px 60px',
    gap: 40,
  };

  const waitBlockStyle: CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 12,
  };

  const waitLabelStyle: CSSProperties = {
    fontSize: 36,
    fontWeight: 600,
    color: '#c8a882',
    letterSpacing: 4,
  };

  const waitCountStyle: CSSProperties = {
    fontSize: 140,
    fontWeight: 900,
    color: '#FF6B35',
    lineHeight: 1,
    fontVariantNumeric: 'tabular-nums',
    textShadow: '0 0 40px rgba(255, 107, 53, 0.5)',
  };

  const waitUnitStyle: CSSProperties = {
    fontSize: 40,
    fontWeight: 700,
    color: '#FF6B35',
  };

  const dividerStyle: CSSProperties = {
    width: 200,
    height: 2,
    background: 'linear-gradient(90deg, transparent, #3d2000, transparent)',
  };

  const etaLabelStyle: CSSProperties = {
    fontSize: 32,
    color: '#9e7a55',
    letterSpacing: 2,
  };

  const etaValueStyle: CSSProperties = {
    fontSize: 64,
    fontWeight: 800,
    color: '#FFD54F',
    lineHeight: 1,
    fontVariantNumeric: 'tabular-nums',
    textShadow: '0 0 20px rgba(255, 213, 79, 0.4)',
  };

  /* 底部最近叫号记录 */
  const historyStyle: CSSProperties = {
    flexShrink: 0,
    height: 130,
    background: '#2d1500',
    borderTop: '3px solid #3d2000',
    display: 'flex',
    alignItems: 'center',
    padding: '0 80px',
    gap: 20,
  };

  const historyLabelStyle: CSSProperties = {
    fontSize: 28,
    fontWeight: 700,
    color: '#9e7a55',
    letterSpacing: 4,
    flexShrink: 0,
    marginRight: 20,
  };

  const historyListStyle: CSSProperties = {
    display: 'flex',
    gap: 20,
    flex: 1,
    alignItems: 'center',
  };

  return (
    <div style={rootStyle}>
      {/* ===== 顶部横幅 ===== */}
      <div style={bannerStyle}>
        <div style={welcomeStyle}>欢迎光临</div>
        <div style={storeTagStyle}>
          <div style={storeNameStyle}>{data.store_name}</div>
          <div style={clockStyle}>{currentTime}</div>
        </div>
      </div>

      {/* ===== 主内容：叫号 + 等待 ===== */}
      <div style={mainStyle}>
        {/* 当前叫号 */}
        <div style={currentCallStyle}>
          <div style={callLabelStyle}>当前叫号</div>
          <div style={callNumberStyle}>{data.current_number}</div>
          <div style={callSubStyle}>请持号牌前往取餐</div>
        </div>

        {/* 等待信息 */}
        <div style={waitingStyle}>
          <div style={waitBlockStyle}>
            <div style={waitLabelStyle}>前方等待</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={waitCountStyle}>{data.waiting_tables}</span>
              <span style={waitUnitStyle}>桌</span>
            </div>
          </div>

          <div style={dividerStyle} />

          <div style={waitBlockStyle}>
            <div style={etaLabelStyle}>预计等待时间</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span style={etaValueStyle}>{data.estimated_minutes}</span>
              <span style={{ fontSize: 36, fontWeight: 700, color: '#FFD54F' }}>分钟</span>
            </div>
          </div>
        </div>
      </div>

      {/* ===== 底部历史记录 ===== */}
      <div style={historyStyle}>
        <div style={historyLabelStyle}>最近叫号</div>
        <div style={historyListStyle}>
          {data.recent_numbers.map((num, index) => {
            const isLatest = index === data.recent_numbers.length - 1;
            const chipStyle: CSSProperties = {
              padding: '12px 28px',
              borderRadius: 8,
              fontSize: isLatest ? 36 : 28,
              fontWeight: isLatest ? 800 : 500,
              color: isLatest ? '#fff' : '#9e7a55',
              background: isLatest ? '#E53935' : 'rgba(255, 255, 255, 0.06)',
              border: isLatest ? '2px solid #E53935' : '2px solid #3d2000',
              letterSpacing: 2,
              transition: 'all 0.3s ease',
              flexShrink: 0,
            };
            return (
              <div key={`${num}-${index}`} style={chipStyle}>
                {num}
              </div>
            );
          })}
        </div>

        {/* 右侧提示 */}
        <div style={{
          flexShrink: 0,
          fontSize: 26,
          color: '#666',
          letterSpacing: 2,
          textAlign: 'right',
        }}>
          每10秒自动刷新
        </div>
      </div>
    </div>
  );
}
