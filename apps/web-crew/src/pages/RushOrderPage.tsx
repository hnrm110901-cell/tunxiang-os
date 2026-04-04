/**
 * 催菜提醒页 — 服务员处理催菜请求
 * 催菜列表(15s刷新) + 已通知厨房 + 赠送小菜
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useEffect, useCallback, useRef } from 'react';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  blue: '#3b82f6',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#ef4444',
  yellow: '#eab308',
  orange: '#f97316',
};

const BASE = 'http://localhost:8001';

/* ---------- 类型 ---------- */
interface RushItem {
  id: string;
  orderId: string;
  tableNo: string;
  dishName: string;
  rushCount: number;
  waitMinutes: number;
  handled: boolean;
  giftDish: string | null;
}

interface GiftDishOption {
  id: string;
  name: string;
}

/* ---------- 固定赠送小菜选项 ---------- */
const GIFT_DISHES: GiftDishOption[] = [
  { id: 'g1', name: '凉拌黄瓜' },
  { id: 'g2', name: '花生毛豆' },
  { id: 'g3', name: '泡椒凤爪' },
  { id: 'g4', name: '糖醋萝卜' },
  { id: 'g5', name: '酸梅汤' },
];

/* ---------- Mock 数据 ---------- */
function generateMockRushItems(): RushItem[] {
  const dishes = ['剁椒鱼头', '小炒黄牛肉', '酸菜鱼', '红烧肉', '蒜蓉蒸虾', '水煮鱼', '口味虾', '辣椒炒肉', '糖醋排骨', '清蒸鲈鱼'];
  const items: RushItem[] = [];
  for (let i = 0; i < 8; i++) {
    items.push({
      id: `rush-${i}`,
      orderId: `ord-${100 + i}`,
      tableNo: `${i < 5 ? 'A' : 'B'}${String((i % 5) + 1).padStart(2, '0')}`,
      dishName: dishes[i % dishes.length],
      rushCount: Math.max(1, 4 - Math.floor(i / 2)),
      waitMinutes: Math.floor(Math.random() * 30) + 10,
      handled: false,
      giftDish: null,
    });
  }
  return items.sort((a, b) => b.rushCount - a.rushCount);
}

/* ---------- 脉冲动画 CSS ---------- */
const pulseKeyframes = `
@keyframes rushPulse {
  0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.5); }
  70% { box-shadow: 0 0 0 10px rgba(239,68,68,0); }
  100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
}
`;

/* ---------- 组件 ---------- */
export function RushOrderPage() {
  const [items, setItems] = useState<RushItem[]>([]);
  const [giftModalTarget, setGiftModalTarget] = useState<string | null>(null);
  const styleInjected = useRef(false);

  /* 注入动画 keyframes */
  useEffect(() => {
    if (styleInjected.current) return;
    const style = document.createElement('style');
    style.textContent = pulseKeyframes;
    document.head.appendChild(style);
    styleInjected.current = true;
    return () => { document.head.removeChild(style); };
  }, []);

  /* 加载催菜列表 */
  const loadRushItems = useCallback(async () => {
    try {
      const storeId = (window as unknown as Record<string, unknown>).__STORE_ID__ || 'demo';
      const res = await fetch(`${BASE}/api/v1/trade/orders/rush?store_id=${storeId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const list: RushItem[] = (json.data?.items ?? json.items ?? []).map((r: Record<string, unknown>, idx: number) => ({
        id: String(r.id ?? `rush-${idx}`),
        orderId: String(r.order_id ?? r.orderId ?? `ord-${idx}`),
        tableNo: String(r.table_no ?? r.tableNo ?? `T${idx + 1}`),
        dishName: String(r.dish_name ?? r.dishName ?? '未知菜品'),
        rushCount: Number(r.rush_count ?? r.rushCount ?? 1),
        waitMinutes: Number(r.wait_minutes ?? r.waitMinutes ?? 0),
        handled: Boolean(r.handled),
        giftDish: r.gift_dish ? String(r.gift_dish) : null,
      }));
      list.sort((a, b) => b.rushCount - a.rushCount);
      setItems(list);
    } catch (_err: unknown) {
      setItems(prev => prev.length > 0 ? prev : generateMockRushItems());
    }
  }, []);

  /* 初始加载 + 15s 轮询 */
  useEffect(() => {
    loadRushItems();
    const timer = setInterval(loadRushItems, 15000);
    return () => clearInterval(timer);
  }, [loadRushItems]);

  /* 标记已处理 */
  const handleNotifyKitchen = async (item: RushItem) => {
    if (typeof navigator.vibrate === 'function') navigator.vibrate(50);
    try {
      await fetch(`${BASE}/api/v1/trade/orders/${item.orderId}/rush-handled`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rush_id: item.id }),
      });
    } catch (_err: unknown) {
      // 离线静默
    }
    setItems(prev => {
      const updated = prev.map(i => i.id === item.id ? { ...i, handled: true } : i);
      return sortItems(updated);
    });
  };

  /* 赠送小菜 */
  const handleGiftDish = async (itemId: string, dish: GiftDishOption) => {
    if (typeof navigator.vibrate === 'function') navigator.vibrate(50);
    const target = items.find(i => i.id === itemId);
    if (!target) return;
    try {
      await fetch(`${BASE}/api/v1/trade/orders/${target.orderId}/gift-dish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rush_id: itemId, dish_id: dish.id, dish_name: dish.name }),
      });
    } catch (_err: unknown) {
      // 离线静默
    }
    setItems(prev => {
      const updated = prev.map(i => i.id === itemId ? { ...i, giftDish: dish.name, handled: true } : i);
      return sortItems(updated);
    });
    setGiftModalTarget(null);
  };

  /* 排序：未处理在前，催菜次数多在前 */
  function sortItems(list: RushItem[]): RushItem[] {
    return [...list].sort((a, b) => {
      if (a.handled !== b.handled) return a.handled ? 1 : -1;
      return b.rushCount - a.rushCount;
    });
  }

  /* 统计 */
  const activeCount = items.filter(i => !i.handled).length;
  const handledCount = items.filter(i => i.handled).length;
  const avgResponse = handledCount > 0
    ? Math.round(items.filter(i => i.handled).reduce((s, i) => s + i.waitMinutes, 0) / handledCount)
    : 0;

  /* 催菜等级颜色 */
  function rushColor(count: number): string {
    if (count >= 3) return C.danger;
    if (count === 2) return C.orange;
    return C.yellow;
  }

  return (
    <div style={{ background: C.bg, minHeight: '100vh', width: '100vw', paddingBottom: 16 }}>
      {/* 顶部统计 */}
      <div style={{
        padding: 16, borderBottom: `1px solid ${C.border}`,
        display: 'flex', justifyContent: 'space-around',
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: activeCount > 0 ? C.accent : C.green }}>{activeCount}</div>
          <div style={{ fontSize: 16, color: C.muted }}>当前催菜</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: C.green }}>{handledCount}</div>
          <div style={{ fontSize: 16, color: C.muted }}>已处理</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: C.text }}>{avgResponse}</div>
          <div style={{ fontSize: 16, color: C.muted }}>平均响应(分)</div>
        </div>
      </div>

      {/* 空状态 */}
      {items.length === 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', marginTop: 120 }}>
          <div style={{ fontSize: 64 }}>✅</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginTop: 16 }}>暂无催菜</div>
          <div style={{ fontSize: 16, color: C.muted, marginTop: 8 }}>所有菜品正常出餐中</div>
        </div>
      )}

      {/* 催菜列表 */}
      <div style={{ padding: '8px 8px 0' }}>
        {items.map(item => {
          const color = rushColor(item.rushCount);
          const isPulse = item.rushCount >= 3 && !item.handled;
          return (
            <div
              key={item.id}
              style={{
                background: item.handled ? 'rgba(17,34,40,0.5)' : C.card,
                borderRadius: 12, margin: 8, padding: 16,
                opacity: item.handled ? 0.55 : 1,
                border: `1px solid ${item.handled ? C.border : color}`,
                animation: isPulse ? 'rushPulse 1.5s infinite' : 'none',
              }}
            >
              {/* 桌号 + 菜名 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                <span style={{ fontSize: 24, fontWeight: 700, color: C.white }}>{item.tableNo}</span>
                <span style={{ fontSize: 18, color: C.text, flex: 1 }}>{item.dishName}</span>
              </div>

              {/* 催菜次数 + 等待时间 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 12, fontSize: 16 }}>
                <span style={{
                  padding: '4px 12px', borderRadius: 8,
                  background: `${color}22`, color, fontWeight: 700,
                }}>
                  催菜 {item.rushCount} 次
                </span>
                <span style={{ color: C.muted }}>已等 {item.waitMinutes} 分钟</span>
              </div>

              {/* 赠送信息 */}
              {item.giftDish && (
                <div style={{ fontSize: 16, color: C.green, marginBottom: 12 }}>
                  🎁 已赠送：{item.giftDish}
                </div>
              )}

              {/* 操作按钮 */}
              {!item.handled && (
                <div style={{ display: 'flex', gap: 12 }}>
                  <button
                    onClick={() => handleNotifyKitchen(item)}
                    style={{
                      flex: 1, height: 48, borderRadius: 10,
                      background: C.blue, color: C.white,
                      fontSize: 16, fontWeight: 700, border: 'none', cursor: 'pointer',
                    }}
                  >
                    已通知厨房
                  </button>
                  <button
                    onClick={() => setGiftModalTarget(item.id)}
                    style={{
                      flex: 1, height: 48, borderRadius: 10,
                      background: C.green, color: C.white,
                      fontSize: 16, fontWeight: 700, border: 'none', cursor: 'pointer',
                    }}
                  >
                    赠送小菜
                  </button>
                </div>
              )}

              {item.handled && !item.giftDish && (
                <div style={{ fontSize: 16, color: C.muted }}>✅ 已通知厨房</div>
              )}
            </div>
          );
        })}
      </div>

      {/* 赠送小菜弹窗 */}
      {giftModalTarget && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.7)', display: 'flex',
            alignItems: 'flex-end', justifyContent: 'center', zIndex: 200,
          }}
          onClick={() => setGiftModalTarget(null)}
        >
          <div
            style={{
              width: '100%', maxWidth: 480, background: C.card,
              borderRadius: '16px 16px 0 0', padding: 24,
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginBottom: 16 }}>
              选择赠送小菜
            </div>
            {GIFT_DISHES.map(dish => (
              <button
                key={dish.id}
                onClick={() => handleGiftDish(giftModalTarget, dish)}
                style={{
                  width: '100%', height: 52, marginBottom: 8, borderRadius: 10,
                  background: 'rgba(255,255,255,0.06)', border: `1px solid ${C.border}`,
                  color: C.text, fontSize: 18, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                {dish.name}
              </button>
            ))}
            <button
              onClick={() => setGiftModalTarget(null)}
              style={{
                width: '100%', height: 48, marginTop: 8, borderRadius: 10,
                background: 'transparent', border: `1px solid ${C.muted}`,
                color: C.muted, fontSize: 16, cursor: 'pointer',
              }}
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
