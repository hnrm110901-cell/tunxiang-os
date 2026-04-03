/**
 * DigitalMenuBoardPage — 数字菜单展示屏
 *
 * 适用场景：面向顾客的门店数字菜单大屏（Store-KDS 终端，全屏展示）。
 *
 * 布局：
 *   顶部品牌栏：门店名称 + Logo + 当前时间
 *   主体：3列菜品网格（含沽清、新品、特惠标签）
 *   底部：纯 CSS marquee 滚动公告栏
 *
 * 实时性：
 *   WebSocket 订阅 /ws/menu-board-updates
 *   事件：dish_soldout / dish_available / price_update / announcement_update
 *   断线 3 秒后自动重连。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── Types ───

interface DishItem {
  id: string;
  name: string;
  price: number;           // 分
  original_price?: number; // 分，有值时显示划线原价
  image_url?: string;
  category: string;
  is_available: boolean;
  is_new?: boolean;
  is_special?: boolean;    // 特惠
}

interface BoardConfig {
  store_name: string;
  logo_url?: string;
  announcement: string;
  category_order: string[];
}

// ─── Constants ───

const API_BASE: string =
  (window as Record<string, unknown>).__STORE_API_BASE__ as string || '';
const TENANT_ID: string =
  (window as Record<string, unknown>).__TENANT_ID__ as string || '';
const STORE_ID: string =
  (window as Record<string, unknown>).__STORE_ID__ as string || '';
const WS_BASE: string =
  (window as Record<string, unknown>).__KDS_WS_URL__ as string || '';

const HEADERS: Record<string, string> = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
};

// ─── Mock data（开发环境用） ───

const MOCK_DISHES: DishItem[] = [
  { id: 'd1', name: '宫保鸡丁',  price: 3800,  category: '热菜', is_available: true,  is_new: false, is_special: false },
  { id: 'd2', name: '佛跳墙',    price: 18800, original_price: 22800, category: '热菜', is_available: true,  is_new: false, is_special: true  },
  { id: 'd3', name: '清蒸鲈鱼',  price: 9800,  category: '海鲜', is_available: false, is_new: false, is_special: false },
  { id: 'd4', name: '醉鹅',      price: 8800,  category: '热菜', is_available: true,  is_new: true,  is_special: false },
  { id: 'd5', name: '凉拌黄瓜',  price: 1800,  category: '凉菜', is_available: true,  is_new: false, is_special: false },
  { id: 'd6', name: '小笼包',    price: 2200,  category: '主食', is_available: true,  is_new: true,  is_special: false },
  { id: 'd7', name: '牛腩煲',    price: 7800,  original_price: 9800, category: '热菜', is_available: true, is_new: false, is_special: true },
  { id: 'd8', name: '蒜蓉大虾',  price: 12800, category: '海鲜', is_available: true,  is_new: false, is_special: false },
  { id: 'd9', name: '夫妻肺片',  price: 4200,  category: '凉菜', is_available: false, is_new: false, is_special: false },
];

const MOCK_CONFIG: BoardConfig = {
  store_name: '屯象餐厅',
  announcement: '今日特供：佛跳墙限量10份 · 营业时间 10:00–22:00 · 服务电话 400-888-8888 · 欢迎光临，祝您用餐愉快！',
  category_order: ['热菜', '海鲜', '凉菜', '主食'],
};

// ─── Helpers ───

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function formatTime(d: Date): string {
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  const ss = d.getSeconds().toString().padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

// ─── Sub-components ───

function DishCard({ dish }: { dish: DishItem }) {
  const soldOut = !dish.is_available;

  return (
    <div
      style={{
        position: 'relative',
        background: soldOut ? 'rgba(30,30,30,0.5)' : '#1E1E1E',
        borderRadius: 12,
        overflow: 'hidden',
        border: soldOut ? '1px solid #333' : '1px solid #2A2A2A',
        opacity: soldOut ? 0.65 : 1,
        transition: 'opacity 0.4s',
      }}
    >
      {/* 菜品图片占位 */}
      <div
        style={{
          width: '100%',
          paddingBottom: '62%',
          position: 'relative',
          background: soldOut ? '#1A1A1A' : '#2A2A2A',
          flexShrink: 0,
        }}
      >
        {dish.image_url ? (
          <img
            src={dish.image_url}
            alt={dish.name}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'cover',
              filter: soldOut ? 'grayscale(100%)' : 'none',
            }}
          />
        ) : (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: 8,
                background: soldOut ? '#333' : '#3A3A3A',
              }}
            />
          </div>
        )}

        {/* 已售完红色斜角标签 */}
        {soldOut && (
          <div
            style={{
              position: 'absolute',
              top: 12,
              right: -24,
              width: 90,
              textAlign: 'center',
              background: '#A32D2D',
              color: '#fff',
              fontSize: 13,
              fontWeight: 700,
              padding: '3px 0',
              transform: 'rotate(35deg)',
              transformOrigin: 'center',
              letterSpacing: 1,
              boxShadow: '0 1px 4px rgba(0,0,0,0.5)',
            }}
          >
            已售完
          </div>
        )}

        {/* 新品 badge */}
        {dish.is_new && !soldOut && (
          <div
            style={{
              position: 'absolute',
              top: 8,
              left: 8,
              background: '#FF6B35',
              color: '#fff',
              fontSize: 12,
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 4,
              letterSpacing: 1,
            }}
          >
            NEW
          </div>
        )}

        {/* 特惠 badge */}
        {dish.is_special && !soldOut && (
          <div
            style={{
              position: 'absolute',
              top: dish.is_new ? 34 : 8,
              left: 8,
              background: '#0F6E56',
              color: '#fff',
              fontSize: 12,
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 4,
              letterSpacing: 1,
            }}
          >
            特惠
          </div>
        )}
      </div>

      {/* 菜品信息 */}
      <div style={{ padding: '12px 14px 14px' }}>
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: soldOut ? '#555' : '#F0F0F0',
            marginBottom: 6,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {dish.name}
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span
            style={{
              fontSize: 22,
              fontWeight: 800,
              color: soldOut ? '#555' : '#FF6B35',
              fontFamily: 'monospace',
            }}
          >
            ¥{fenToYuan(dish.price)}
          </span>
          {dish.original_price && !soldOut && (
            <span
              style={{
                fontSize: 15,
                color: '#555',
                textDecoration: 'line-through',
                fontFamily: 'monospace',
              }}
            >
              ¥{fenToYuan(dish.original_price)}
            </span>
          )}
        </div>

        <div
          style={{
            marginTop: 6,
            fontSize: 13,
            color: soldOut ? '#444' : '#888',
          }}
        >
          {soldOut ? '暂时售完' : '可点'}
        </div>
      </div>
    </div>
  );
}

// ─── Main ───

export function DigitalMenuBoardPage() {
  const [dishes, setDishes] = useState<DishItem[]>([]);
  const [config, setConfig] = useState<BoardConfig>(MOCK_CONFIG);
  const [now, setNow] = useState(() => new Date());
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 时钟每秒更新
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // 拉取菜单数据
  const fetchBoardData = useCallback(async () => {
    if (!API_BASE) {
      setDishes(MOCK_DISHES);
      return;
    }
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/menu/board-data?store_id=${STORE_ID}`,
        { headers: HEADERS }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      if (body.ok) setDishes(body.data.dishes ?? []);
    } catch {
      // 接口不通时使用 mock 数据
      setDishes(MOCK_DISHES);
    }
  }, []);

  const fetchConfig = useCallback(async () => {
    if (!API_BASE) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/menu/board-config?store_id=${STORE_ID}`,
        { headers: HEADERS }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      if (body.ok) setConfig(body.data);
    } catch {
      // 保留默认 mock config
    }
  }, []);

  // WebSocket 连接 + 断线重连
  const connectWS = useCallback(() => {
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }

    const wsUrl = WS_BASE
      ? `${WS_BASE}/ws/menu-board-updates`
      : null;

    if (!wsUrl) {
      // 开发模式：不连接 WS
      setConnected(true);
      return;
    }

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (evt) => {
      try {
        const msg: { event: string; data: unknown } = JSON.parse(evt.data);
        if (msg.event === 'dish_soldout') {
          const { dish_id } = msg.data as { dish_id: string };
          setDishes((prev) =>
            prev.map((d) => (d.id === dish_id ? { ...d, is_available: false } : d))
          );
        } else if (msg.event === 'dish_available') {
          const { dish_id } = msg.data as { dish_id: string };
          setDishes((prev) =>
            prev.map((d) => (d.id === dish_id ? { ...d, is_available: true } : d))
          );
        } else if (msg.event === 'price_update') {
          const { dish_id, price } = msg.data as { dish_id: string; price: number };
          setDishes((prev) =>
            prev.map((d) => (d.id === dish_id ? { ...d, price } : d))
          );
        } else if (msg.event === 'announcement_update') {
          const { announcement } = msg.data as { announcement: string };
          setConfig((prev) => ({ ...prev, announcement }));
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      // 3 秒后自动重连
      reconnectRef.current = setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    fetchBoardData();
    fetchConfig();
    connectWS();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [fetchBoardData, fetchConfig, connectWS]);

  // 按分类顺序排列菜品
  const sortedDishes = [...dishes].sort((a, b) => {
    const ai = config.category_order.indexOf(a.category);
    const bi = config.category_order.indexOf(b.category);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

  const dateStr = `${now.getFullYear()}-${(now.getMonth() + 1).toString().padStart(2, '0')}-${now.getDate().toString().padStart(2, '0')} ${['日', '一', '二', '三', '四', '五', '六'][now.getDay()]}`;

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        background: '#111',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        overflow: 'hidden',
        userSelect: 'none',
        color: '#F0F0F0',
      }}
    >
      {/* ── 顶部品牌栏 ── */}
      <div
        style={{
          flexShrink: 0,
          height: 72,
          background: '#1A1A1A',
          borderBottom: '2px solid #FF6B35',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 32px',
        }}
      >
        {/* 左：Logo + 门店名 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {config.logo_url ? (
            <img
              src={config.logo_url}
              alt="logo"
              style={{ height: 44, width: 44, borderRadius: 8, objectFit: 'cover' }}
            />
          ) : (
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 8,
                background: '#FF6B35',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 22,
                fontWeight: 900,
                color: '#fff',
              }}
            >
              屯
            </div>
          )}
          <span style={{ fontSize: 28, fontWeight: 800, color: '#F0F0F0', letterSpacing: 1 }}>
            {config.store_name}
          </span>
        </div>

        {/* 右：日期 + 时间 + 连接状态 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 14, color: '#888' }}>{dateStr}</div>
            <div
              style={{
                fontSize: 32,
                fontWeight: 700,
                color: '#FF6B35',
                fontFamily: 'monospace',
                lineHeight: 1.1,
              }}
            >
              {formatTime(now)}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: 5,
                background: connected ? '#30D158' : '#FF3B30',
                boxShadow: connected ? '0 0 6px #30D158' : 'none',
              }}
            />
            <span style={{ fontSize: 13, color: '#666' }}>
              {connected ? '实时同步' : '重连中…'}
            </span>
          </div>
        </div>
      </div>

      {/* ── 主体菜品网格 ── */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '24px 28px 16px',
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {sortedDishes.length === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: '#444',
              gap: 16,
            }}
          >
            <div style={{ fontSize: 48 }}>🍽</div>
            <div style={{ fontSize: 22 }}>菜单加载中…</div>
          </div>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: 20,
            }}
          >
            {sortedDishes.map((dish) => (
              <DishCard key={dish.id} dish={dish} />
            ))}
          </div>
        )}
      </div>

      {/* ── 底部滚动公告栏 ── */}
      <div
        style={{
          flexShrink: 0,
          height: 48,
          background: '#FF6B35',
          display: 'flex',
          alignItems: 'center',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div
          style={{
            flexShrink: 0,
            padding: '0 16px',
            background: '#E55A28',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            fontSize: 16,
            fontWeight: 700,
            color: '#fff',
            letterSpacing: 2,
            whiteSpace: 'nowrap',
          }}
        >
          公告
        </div>
        <div
          style={{
            flex: 1,
            overflow: 'hidden',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <div
            className="menu-board-marquee"
            style={{
              display: 'inline-block',
              whiteSpace: 'nowrap',
              fontSize: 17,
              fontWeight: 500,
              color: '#fff',
              animation: 'marqueeScroll 28s linear infinite',
              paddingLeft: '100%',
            }}
          >
            {config.announcement}
          </div>
        </div>
      </div>

      {/* ── CSS 动画 ── */}
      <style>{`
        @keyframes marqueeScroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-100%); }
        }
      `}</style>
    </div>
  );
}
