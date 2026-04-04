/**
 * PrepStation — 备料预备站
 *
 * 显示未来30分钟的预计用料，提醒厨师提前备好食材。
 * 左侧：食材需求列表（按食材聚合，状态切换）
 * 右侧：即将出单预览（按预计出单时间排序）
 *
 * KDS规范：触屏 / 深色背景 / 无Ant Design / 最小48px点击区
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

// ─── Types ───

type PrepStatus = 'pending' | 'done' | 'shortage';
type PrepUrgency = 'high' | 'normal' | 'low';

interface PrepItem {
  id: string;
  name: string;
  quantity: string;
  from_orders: number;
  status: PrepStatus;
  urgency?: PrepUrgency;
}

interface UpcomingOrder {
  time: string;
  table: string;
  dishes: string[];
  minutes_until: number;
}

// ─── Mock Data ───

const MOCK_PREP_ITEMS: PrepItem[] = [
  { id: 'p1', name: '活基围虾', quantity: '850g', from_orders: 3, status: 'pending', urgency: 'high' },
  { id: 'p2', name: '鲜豆腐', quantity: '5块', from_orders: 2, status: 'done' },
  { id: 'p3', name: '五花肉', quantity: '600g', from_orders: 4, status: 'pending', urgency: 'normal' },
  { id: 'p4', name: '鸡蛋', quantity: '12个', from_orders: 5, status: 'shortage' },
  { id: 'p5', name: '青椒', quantity: '200g', from_orders: 2, status: 'pending', urgency: 'normal' },
  { id: 'p6', name: '蒜苗', quantity: '100g', from_orders: 3, status: 'pending', urgency: 'low' },
];

const MOCK_UPCOMING_ORDERS: UpcomingOrder[] = [
  { time: '15:28', table: '桌3', dishes: ['鱼香肉丝×2', '蒸蛋羹×1'], minutes_until: 2 },
  { time: '15:31', table: '桌5', dishes: ['红烧肉×1', '青椒炒肉×1'], minutes_until: 5 },
  { time: '15:33', table: '桌1', dishes: ['宫保鸡丁×3'], minutes_until: 7 },
  { time: '15:38', table: '外卖#001', dishes: ['鱼香肉丝×1', '麻婆豆腐×1', '米饭×2'], minutes_until: 12 },
];

// ─── Constants ───

const BRAND_COLOR = '#FF6B35';
const BG_MAIN = '#1a1a1a';
const BG_CARD = '#2d2d2d';
const BG_DARK = '#141414';
const TEXT_WHITE = '#ffffff';
const TEXT_GRAY = '#888888';
const GREEN = '#52c41a';
const ORANGE = '#FF8C00';

const API_BASE = (window as any).__STORE_API_BASE__ || '';

// ─── 缺料确认弹窗 ───

function ShortageConfirmDialog({
  item,
  onConfirm,
  onCancel,
}: {
  item: PrepItem;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.85)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: BG_CARD,
          borderRadius: 16,
          padding: 32,
          width: 420,
          border: `2px solid ${ORANGE}`,
        }}
      >
        <div style={{ fontSize: 22, fontWeight: 700, color: TEXT_WHITE, marginBottom: 12 }}>
          确认标记缺料？
        </div>
        <div style={{ fontSize: 18, color: TEXT_GRAY, marginBottom: 24 }}>
          <span style={{ color: TEXT_WHITE, fontWeight: 700 }}>{item.name}</span>（{item.quantity}）
          将标记为缺料，并通知管理员。
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onConfirm}
            style={{
              flex: 1,
              minHeight: 64,
              background: ORANGE,
              color: TEXT_WHITE,
              border: 'none',
              borderRadius: 10,
              fontSize: 20,
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            确认缺料
          </button>
          <button
            onClick={onCancel}
            style={{
              flex: 1,
              minHeight: 64,
              background: '#222',
              color: TEXT_GRAY,
              border: `1px solid #333`,
              borderRadius: 10,
              fontSize: 20,
              cursor: 'pointer',
            }}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 单条食材行 ───

function PrepItemRow({
  item,
  onStatusChange,
}: {
  item: PrepItem;
  onStatusChange: (id: string, status: PrepStatus) => void;
}) {
  const isDone = item.status === 'done';
  const isShortage = item.status === 'shortage';

  const rowBg = isDone ? '#1a2a1a' : isShortage ? '#2a1a00' : BG_CARD;
  const borderColor = isShortage ? ORANGE : isDone ? '#2d4a2d' : '#3a3a3a';
  const nameColor = isDone ? TEXT_GRAY : TEXT_WHITE;

  return (
    <div
      style={{
        background: rowBg,
        border: `1.5px solid ${borderColor}`,
        borderRadius: 10,
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        minHeight: 64,
        opacity: isDone ? 0.75 : 1,
        transition: 'all 0.2s',
      }}
    >
      {/* 紧急标记 */}
      {item.urgency === 'high' && !isDone && (
        <div
          style={{
            width: 6,
            flexShrink: 0,
            alignSelf: 'stretch',
            background: '#FF3B30',
            borderRadius: 3,
          }}
        />
      )}

      {/* 食材信息 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 22,
            fontWeight: isDone ? 400 : 700,
            color: nameColor,
            textDecoration: isDone ? 'line-through' : 'none',
            marginBottom: 2,
          }}
        >
          {item.name}
        </div>
        <div style={{ fontSize: 16, color: TEXT_GRAY }}>
          {item.quantity}
          <span style={{ marginLeft: 8, color: '#555', fontSize: 14 }}>
            来自 {item.from_orders} 单
          </span>
        </div>
      </div>

      {/* 3个状态按钮 */}
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        {/* 待备料 ○ */}
        <button
          onClick={() => onStatusChange(item.id, 'pending')}
          title="标记为待备料"
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            border: `2px solid ${item.status === 'pending' ? '#888' : '#333'}`,
            background: item.status === 'pending' ? '#333' : 'transparent',
            color: item.status === 'pending' ? TEXT_WHITE : '#444',
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          ○
        </button>

        {/* 已备好 ✓ */}
        <button
          onClick={() => {
            // 触发震动（微信/安卓WebView环境）
            try {
              if ((window as any).wx?.vibrateLong) {
                (window as any).wx.vibrateLong({ type: 'heavy' });
              } else if (navigator.vibrate) {
                navigator.vibrate(200);
              }
            } catch {
              // 非微信环境忽略
            }
            onStatusChange(item.id, 'done');
          }}
          title="标记已备好"
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            border: `2px solid ${item.status === 'done' ? GREEN : '#333'}`,
            background: item.status === 'done' ? GREEN : 'transparent',
            color: item.status === 'done' ? TEXT_WHITE : '#444',
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          ✓
        </button>

        {/* 缺料 ⚠ */}
        <button
          onClick={() => onStatusChange(item.id, 'shortage')}
          title="标记缺料"
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            border: `2px solid ${item.status === 'shortage' ? ORANGE : '#333'}`,
            background: item.status === 'shortage' ? ORANGE : 'transparent',
            color: item.status === 'shortage' ? TEXT_WHITE : '#444',
            fontSize: 18,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          ⚠
        </button>
      </div>
    </div>
  );
}

// ─── 即将出单预览行 ───

function UpcomingOrderRow({
  order,
  isUrgent,
}: {
  order: UpcomingOrder;
  isUrgent: boolean;
}) {
  return (
    <div
      style={{
        padding: '10px 14px',
        borderLeft: isUrgent ? `4px solid ${ORANGE}` : '4px solid transparent',
        background: isUrgent ? 'rgba(255,140,0,0.08)' : 'transparent',
        borderRadius: 6,
        minHeight: 48,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <div
        style={{
          fontSize: 16,
          color: isUrgent ? ORANGE : TEXT_GRAY,
          fontFamily: 'monospace',
          flexShrink: 0,
          width: 44,
        }}
      >
        {order.time}
      </div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: TEXT_WHITE,
          flexShrink: 0,
          width: 64,
        }}
      >
        {order.table}
      </div>
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <div
          style={{
            fontSize: 16,
            color: TEXT_GRAY,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {order.dishes.slice(0, 2).join(' · ')}
          {order.dishes.length > 2 && (
            <span style={{ color: '#555' }}> +{order.dishes.length - 2}</span>
          )}
        </div>
      </div>
      {isUrgent && (
        <div
          style={{
            fontSize: 14,
            color: ORANGE,
            fontWeight: 700,
            flexShrink: 0,
          }}
        >
          {order.minutes_until}分钟
        </div>
      )}
    </div>
  );
}

// ─── Main Component ───

export default function PrepStation() {
  const navigate = useNavigate();
  const [items, setItems] = useState<PrepItem[]>([]);
  const [upcomingOrders, setUpcomingOrders] = useState<UpcomingOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(new Date());
  const [shortageTarget, setShortageTarget] = useState<PrepItem | null>(null);
  const [batchConfirmVisible, setBatchConfirmVisible] = useState(false);

  // 实时时钟
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // 拉取备料数据（无 API 时用 Mock）
  const fetchData = useCallback(async () => {
    setLoading(true);
    if (!API_BASE) {
      // Mock 模式
      setItems(MOCK_PREP_ITEMS);
      setUpcomingOrders(MOCK_UPCOMING_ORDERS);
      setLoading(false);
      return;
    }
    try {
      const [prepRes, ordersRes] = await Promise.all([
        txFetch<{ items: PrepItem[] }>(`/api/v1/trade/kds/prep-items?minutes=30`),
        txFetch<{ items: UpcomingOrder[] }>(`/api/v1/trade/orders?status=pending&limit=15`),
      ]);
      setItems(prepRes.items);
      setUpcomingOrders(ordersRes.items);
    } catch {
      // 降级到 Mock
      setItems(MOCK_PREP_ITEMS);
      setUpcomingOrders(MOCK_UPCOMING_ORDERS);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 30_000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // 状态变更（含 API 提交）
  const handleStatusChange = useCallback(async (id: string, newStatus: PrepStatus) => {
    const item = items.find(i => i.id === id);
    if (!item) return;

    // 缺料需要确认
    if (newStatus === 'shortage' && item.status !== 'shortage') {
      setShortageTarget(item);
      return;
    }

    // 乐观更新
    setItems(prev => prev.map(i => i.id === id ? { ...i, status: newStatus } : i));

    // API 提交
    if (API_BASE) {
      try {
        await txFetch(
          `/api/v1/trade/kds/prep-items/${encodeURIComponent(id)}`,
          { method: 'PATCH', body: JSON.stringify({ status: newStatus }) },
        );
      } catch {
        // 离线时保留本地状态
      }
    }
  }, [items]);

  const confirmShortage = useCallback(async () => {
    if (!shortageTarget) return;
    const id = shortageTarget.id;
    setShortageTarget(null);

    setItems(prev => prev.map(i => i.id === id ? { ...i, status: 'shortage' as PrepStatus } : i));

    if (API_BASE) {
      try {
        await txFetch(
          `/api/v1/trade/kds/prep-items/${encodeURIComponent(id)}`,
          { method: 'PATCH', body: JSON.stringify({ status: 'shortage' }) },
        );
      } catch {
        // 离线时保留本地状态
      }
    }
  }, [shortageTarget]);

  // 批量标记已备（只标记 pending 状态的）
  const handleBatchMarkDone = useCallback(() => {
    const pendingItems = items.filter(i => i.status === 'pending');
    if (pendingItems.length === 0) return;
    setBatchConfirmVisible(true);
  }, [items]);

  const confirmBatchDone = useCallback(async () => {
    setBatchConfirmVisible(false);
    const ids = items.filter(i => i.status === 'pending').map(i => i.id);
    setItems(prev => prev.map(i => ids.includes(i.id) ? { ...i, status: 'done' as PrepStatus } : i));

    if (API_BASE) {
      try {
        await Promise.all(
          ids.map(id =>
            txFetch(
              `/api/v1/trade/kds/prep-items/${encodeURIComponent(id)}`,
              { method: 'PATCH', body: JSON.stringify({ status: 'done' }) },
            )
          )
        );
      } catch {
        // 离线时保留本地状态
      }
    }
  }, [items]);

  // 排序：缺料 > 高urgency待备 > 普通待备 > 已备好
  const sortedItems = [...items].sort((a, b) => {
    const order = (item: PrepItem) => {
      if (item.status === 'shortage') return 0;
      if (item.status === 'done') return 10;
      if (item.urgency === 'high') return 1;
      if (item.urgency === 'normal') return 2;
      return 3;
    };
    return order(a) - order(b);
  });

  const doneCount = items.filter(i => i.status === 'done').length;
  const totalCount = items.length;
  const pendingCount = items.filter(i => i.status === 'pending').length;
  const shortageCount = items.filter(i => i.status === 'shortage').length;

  const clockStr = now.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  return (
    <div
      style={{
        background: BG_MAIN,
        minHeight: '100vh',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        color: TEXT_WHITE,
        overflow: 'hidden',
      }}
    >
      {/* ── 缺料确认弹窗 ── */}
      {shortageTarget && (
        <ShortageConfirmDialog
          item={shortageTarget}
          onConfirm={confirmShortage}
          onCancel={() => setShortageTarget(null)}
        />
      )}

      {/* ── 批量确认弹窗 ── */}
      {batchConfirmVisible && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.85)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              background: BG_CARD,
              borderRadius: 16,
              padding: 32,
              width: 400,
              border: `2px solid ${GREEN}`,
            }}
          >
            <div style={{ fontSize: 22, fontWeight: 700, color: TEXT_WHITE, marginBottom: 12 }}>
              批量标记已备？
            </div>
            <div style={{ fontSize: 18, color: TEXT_GRAY, marginBottom: 24 }}>
              将 <b style={{ color: GREEN }}>{pendingCount} 项</b> 待备料食材标记为已备好。
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={confirmBatchDone}
                style={{
                  flex: 1,
                  minHeight: 64,
                  background: GREEN,
                  color: TEXT_WHITE,
                  border: 'none',
                  borderRadius: 10,
                  fontSize: 20,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                确认
              </button>
              <button
                onClick={() => setBatchConfirmVisible(false)}
                style={{
                  flex: 1,
                  minHeight: 64,
                  background: '#222',
                  color: TEXT_GRAY,
                  border: '1px solid #333',
                  borderRadius: 10,
                  fontSize: 20,
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 头部 64px ── */}
      <header
        style={{
          height: 64,
          minHeight: 64,
          background: '#111',
          borderBottom: `2px solid ${BRAND_COLOR}22`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 20px',
          gap: 16,
          flexShrink: 0,
        }}
      >
        {/* 返回按钮 */}
        <button
          onClick={() => navigate('/board')}
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            background: '#222',
            border: '1px solid #333',
            color: TEXT_GRAY,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          ←
        </button>

        {/* 标题 */}
        <span style={{ fontSize: 24, fontWeight: 700, color: TEXT_WHITE, flexShrink: 0 }}>
          备料预备站
        </span>

        {/* 实时时钟 */}
        <span
          style={{
            fontSize: 20,
            fontFamily: 'monospace',
            color: TEXT_GRAY,
            flexShrink: 0,
          }}
        >
          {clockStr}
        </span>

        {/* 弹性占位 */}
        <div style={{ flex: 1 }} />

        {/* 刷新按钮 */}
        <button
          onClick={fetchData}
          style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            background: BRAND_COLOR,
            border: 'none',
            color: TEXT_WHITE,
            fontSize: 18,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
          title="刷新"
        >
          ↻
        </button>

        {/* 完成计数 */}
        <div
          style={{
            fontSize: 16,
            color: doneCount === totalCount && totalCount > 0 ? GREEN : TEXT_WHITE,
            fontWeight: 700,
            flexShrink: 0,
            background: '#222',
            borderRadius: 8,
            padding: '8px 16px',
            minHeight: 48,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <span style={{ color: GREEN }}>{doneCount}</span>
          <span style={{ color: TEXT_GRAY }}>/{totalCount} 已备</span>
          {shortageCount > 0 && (
            <span style={{ color: ORANGE, marginLeft: 10 }}>
              ⚠{shortageCount}缺料
            </span>
          )}
        </div>
      </header>

      {/* ── 主体区域 ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── 左侧：食材需求列表 60% ── */}
        <div
          style={{
            width: '60%',
            display: 'flex',
            flexDirection: 'column',
            borderRight: '1px solid #2a2a2a',
            overflow: 'hidden',
          }}
        >
          {/* 左侧标题栏 */}
          <div
            style={{
              padding: '12px 16px',
              background: BG_DARK,
              borderBottom: '1px solid #2a2a2a',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: 18, fontWeight: 700, color: TEXT_WHITE }}>
              食材需求
            </span>
            <span style={{ fontSize: 14, color: TEXT_GRAY }}>
              未来30分钟
            </span>
            {shortageCount > 0 && (
              <span
                style={{
                  fontSize: 14,
                  color: ORANGE,
                  fontWeight: 700,
                  background: `${ORANGE}22`,
                  padding: '3px 10px',
                  borderRadius: 6,
                  border: `1px solid ${ORANGE}44`,
                }}
              >
                ⚠ {shortageCount}项缺料
              </span>
            )}
          </div>

          {/* 食材列表（可滚动）*/}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: 12,
              WebkitOverflowScrolling: 'touch',
            }}
          >
            {loading ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: 40,
                  color: TEXT_GRAY,
                  fontSize: 18,
                }}
              >
                加载中…
              </div>
            ) : sortedItems.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: 60,
                  color: '#444',
                  fontSize: 18,
                }}
              >
                暂无备料任务
              </div>
            ) : (
              sortedItems.map(item => (
                <div key={item.id} style={{ marginBottom: 8 }}>
                  <PrepItemRow item={item} onStatusChange={handleStatusChange} />
                </div>
              ))
            )}
          </div>
        </div>

        {/* ── 右侧：即将出单预览 40% ── */}
        <div
          style={{
            width: '40%',
            background: BG_DARK,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* 右侧标题栏 */}
          <div
            style={{
              padding: '12px 16px',
              borderBottom: '1px solid #2a2a2a',
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: 18, fontWeight: 700, color: TEXT_WHITE }}>
              即将出单预览
            </span>
            <span style={{ fontSize: 14, color: TEXT_GRAY, marginLeft: 8 }}>
              未来30分钟
            </span>
          </div>

          {/* 出单列表 */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '8px 12px',
              WebkitOverflowScrolling: 'touch',
            }}
          >
            {upcomingOrders.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  padding: 40,
                  color: '#444',
                  fontSize: 18,
                }}
              >
                暂无即将出单
              </div>
            ) : (
              upcomingOrders.map((order, idx) => (
                <UpcomingOrderRow
                  key={idx}
                  order={order}
                  isUrgent={order.minutes_until <= 5}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {/* ── 底部操作条 80px ── */}
      <div
        style={{
          height: 80,
          minHeight: 80,
          background: '#111',
          borderTop: '1px solid #2a2a2a',
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          gap: 12,
          flexShrink: 0,
        }}
      >
        {/* 批量标记已备 */}
        <button
          onClick={handleBatchMarkDone}
          disabled={pendingCount === 0}
          style={{
            flex: 2,
            height: 64,
            background: pendingCount > 0 ? GREEN : '#1a2a1a',
            color: pendingCount > 0 ? TEXT_WHITE : '#444',
            border: 'none',
            borderRadius: 12,
            fontSize: 20,
            fontWeight: 700,
            cursor: pendingCount > 0 ? 'pointer' : 'not-allowed',
            transition: 'all 0.2s',
          }}
        >
          ✓ 批量标记已备
          {pendingCount > 0 && (
            <span
              style={{
                marginLeft: 8,
                fontSize: 16,
                background: 'rgba(255,255,255,0.2)',
                padding: '2px 10px',
                borderRadius: 20,
              }}
            >
              {pendingCount}项
            </span>
          )}
        </button>

        {/* 报告缺料 */}
        <button
          onClick={() => navigate('/shortage-report')}
          style={{
            flex: 1,
            height: 64,
            background: 'transparent',
            color: ORANGE,
            border: `2px solid ${ORANGE}`,
            borderRadius: 12,
            fontSize: 20,
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          ⚠ 报告缺料
        </button>
      </div>
    </div>
  );
}
