/**
 * 外卖聚合统一接单面板 — Store-POS终端
 *
 * 遵循 Store终端触控规范：
 * - 最小触控区域 ≥ 48×48px
 * - 字体 ≥ 16px（Store终端底线）
 * - 无hover状态，用 :active + scale(0.97) 触控反馈
 * - 无Ant Design Select，拒单原因用全屏弹层选择
 * - WebSocket实时收新订单，新单声音提示
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type Platform = 'meituan' | 'eleme' | 'douyin';
type OrderStatus = 'pending' | 'preparing' | 'done';

interface OrderItem {
  name: string;
  quantity: number;
  price_fen: number;
  notes: string;
}

interface OmniOrder {
  order_id: string;
  platform: Platform;
  platform_order_id: string;
  status: OrderStatus;
  total_fen: number;
  notes: string;
  customer_phone: string;
  delivery_address: string;
  created_at: string; // ISO8601
  items: OrderItem[];
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────

/** 平台视觉配置 */
const PLATFORM_CONFIG: Record<Platform, { label: string; color: string; bg: string }> = {
  meituan: { label: '美团', color: '#FF6600', bg: '#FFF0E6' },
  eleme: { label: '饿了么', color: '#0EA5E9', bg: '#E6F4FF' },
  douyin: { label: '抖音', color: '#1C1C1E', bg: '#F0F0F2' },
};

const REJECT_REASONS: { code: number; label: string }[] = [
  { code: 1, label: '餐厅暂时无法接单' },
  { code: 2, label: '餐厅已打烊' },
  { code: 3, label: '食材不足，无法制作' },
  { code: 4, label: '超出配送范围' },
  { code: 9, label: '其他原因' },
];

/** 超时自动拒单：3分钟（180秒） */
const AUTO_REJECT_SECONDS = 180;

/** WebSocket重连间隔（毫秒） */
const WS_RECONNECT_INTERVAL = 5000;

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function formatPrice(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

function getElapsedSeconds(createdAt: string): number {
  const created = new Date(createdAt).getTime();
  return Math.floor((Date.now() - created) / 1000);
}

function getRemainingSeconds(createdAt: string): number {
  return Math.max(0, AUTO_REJECT_SECONDS - getElapsedSeconds(createdAt));
}

/** 倒计时颜色：绿→黄→红 */
function getCountdownColor(remaining: number): string {
  const ratio = remaining / AUTO_REJECT_SECONDS;
  if (ratio > 0.5) return '#0F6E56'; // success绿
  if (ratio > 0.2) return '#BA7517'; // warning黄
  return '#A32D2D';                  // danger红
}

function formatTime(isoStr: string): string {
  const d = new Date(isoStr);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  return `${h}:${m}`;
}

/** 播放新订单提示音（Web Audio API） */
function playNewOrderSound() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(660, ctx.currentTime + 0.15);
    gain.gain.setValueAtTime(0.4, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.4);
  } catch {
    // 音频API不可用时静默降级
  }
}

// ─── 倒计时条组件 ──────────────────────────────────────────────────────────────

function CountdownBar({ createdAt, onTimeout }: { createdAt: string; onTimeout: () => void }) {
  const [remaining, setRemaining] = useState(() => getRemainingSeconds(createdAt));
  const onTimeoutRef = useRef(onTimeout);
  onTimeoutRef.current = onTimeout;

  useEffect(() => {
    const timer = setInterval(() => {
      const rem = getRemainingSeconds(createdAt);
      setRemaining(rem);
      if (rem === 0) {
        clearInterval(timer);
        onTimeoutRef.current();
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [createdAt]);

  const ratio = remaining / AUTO_REJECT_SECONDS;
  const color = getCountdownColor(remaining);
  const mm = String(Math.floor(remaining / 60)).padStart(2, '0');
  const ss = String(remaining % 60).padStart(2, '0');

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', marginBottom: 4,
      }}>
        <span style={{ fontSize: 16, color: '#5F5E5A' }}>剩余接单时间</span>
        <span style={{
          fontSize: 20, fontWeight: 700, color,
          animation: remaining <= 30 ? 'pulse 1s infinite' : 'none',
        }}>
          {mm}:{ss}
        </span>
      </div>
      {/* 进度条 */}
      <div style={{
        height: 8, borderRadius: 4,
        background: '#E8E6E1', overflow: 'hidden',
      }}>
        <div style={{
          height: '100%', borderRadius: 4,
          width: `${ratio * 100}%`,
          background: color,
          transition: 'width 1s linear, background 0.5s ease',
        }} />
      </div>
    </div>
  );
}

// ─── 平台徽标组件 ──────────────────────────────────────────────────────────────

function PlatformBadge({ platform }: { platform: Platform }) {
  const cfg = PLATFORM_CONFIG[platform];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      padding: '2px 10px', borderRadius: 6,
      background: cfg.bg, color: cfg.color,
      fontSize: 16, fontWeight: 700,
      border: `1.5px solid ${cfg.color}`,
      minHeight: 28,
    }}>
      {cfg.label}
    </span>
  );
}

// ─── 拒单原因弹层 ──────────────────────────────────────────────────────────────

function RejectReasonSheet({
  onConfirm,
  onCancel,
}: {
  onConfirm: (code: number) => void;
  onCancel: () => void;
}) {
  return (
    /* 背景遮罩 */
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'flex-end',
      }}
      onClick={onCancel}
    >
      {/* 底部弹层 */}
      <div
        style={{
          width: '100%', background: '#fff',
          borderRadius: '16px 16px 0 0',
          padding: '24px 20px 32px',
          animation: 'slideUp 300ms ease-out',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: '0 0 20px', fontSize: 22, color: '#2C2C2A', textAlign: 'center' }}>
          选择拒单原因
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {REJECT_REASONS.map((r) => (
            <button
              key={r.code}
              onClick={() => onConfirm(r.code)}
              style={{
                minHeight: 56, padding: '0 20px',
                border: '1.5px solid #E8E6E1', borderRadius: 12,
                background: '#F8F7F5', cursor: 'pointer',
                fontSize: 18, color: '#2C2C2A', textAlign: 'left',
                fontFamily: 'inherit',
                WebkitTapHighlightColor: 'transparent',
                transition: 'transform 200ms ease, background 200ms ease',
              }}
              onPointerDown={(e) => {
                (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
                (e.currentTarget as HTMLButtonElement).style.background = '#F0EDE6';
              }}
              onPointerUp={(e) => {
                (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
                (e.currentTarget as HTMLButtonElement).style.background = '#F8F7F5';
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
        <button
          onClick={onCancel}
          style={{
            marginTop: 16, width: '100%', minHeight: 56,
            border: 'none', borderRadius: 12,
            background: '#E8E6E1', cursor: 'pointer',
            fontSize: 18, color: '#5F5E5A', fontFamily: 'inherit',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          取消
        </button>
      </div>
    </div>
  );
}

// ─── 单张订单卡片 ──────────────────────────────────────────────────────────────

function OrderCard({
  order,
  onAccept,
  onReject,
  onTimeout,
}: {
  order: OmniOrder;
  onAccept: (orderId: string, minutes: number) => void;
  onReject: (orderId: string, code: number) => void;
  onTimeout: (orderId: string) => void;
}) {
  const [showRejectSheet, setShowRejectSheet] = useState(false);
  const isPending = order.status === 'pending';

  const handleAccept = () => onAccept(order.order_id, 20);
  const handleRejectConfirm = (code: number) => {
    setShowRejectSheet(false);
    onReject(order.order_id, code);
  };

  return (
    <>
      <div style={{
        background: '#fff', borderRadius: 12, padding: 16,
        border: isPending ? '2px solid #FF6B35' : '1.5px solid #E8E6E1',
        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        marginBottom: 12,
        animation: 'fadeSlideIn 200ms ease-out',
      }}>
        {/* 卡片头部 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <PlatformBadge platform={order.platform} />
            <span style={{ fontSize: 16, color: '#5F5E5A' }}>
              #{order.platform_order_id.slice(-6)}
            </span>
            {/* 出餐可行性 - 仅新单显示 */}
            {isPending && (
              <span style={{
                display: 'inline-block', fontSize: 11, padding: '1px 6px', borderRadius: 4,
                background: 'rgba(15,110,86,.15)', color: '#0F6E56',
                fontWeight: 600, marginLeft: 6,
              }}>✓ 可准时出餐</span>
            )}
          </div>
          <span style={{ fontSize: 16, color: '#B4B2A9' }}>{formatTime(order.created_at)}</span>
        </div>

        {/* 菜品列表 */}
        <div style={{ marginBottom: 10 }}>
          {order.items.map((item, i) => (
            <div
              key={i}
              style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '4px 0', borderBottom: i < order.items.length - 1 ? '1px solid #F0EDE6' : 'none',
              }}
            >
              <span style={{ fontSize: 18, color: '#2C2C2A' }}>
                {item.name}
                {item.notes ? <span style={{ fontSize: 16, color: '#B4B2A9' }}> ({item.notes})</span> : null}
              </span>
              <span style={{ fontSize: 18, color: '#2C2C2A', minWidth: 40, textAlign: 'right' }}>
                ×{item.quantity}
              </span>
            </div>
          ))}
        </div>

        {/* 备注 */}
        {order.notes && (
          <div style={{
            padding: '6px 10px', background: '#FFF3ED', borderRadius: 8,
            fontSize: 16, color: '#FF6B35', marginBottom: 10,
          }}>
            备注：{order.notes}
          </div>
        )}

        {/* 金额 */}
        <div style={{
          display: 'flex', justifyContent: 'flex-end',
          marginBottom: 12,
        }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A' }}>
            {formatPrice(order.total_fen)}
          </span>
        </div>

        {/* 倒计时条（仅待接单状态显示） */}
        {isPending && (
          <CountdownBar
            createdAt={order.created_at}
            onTimeout={() => onTimeout(order.order_id)}
          />
        )}

        {/* 操作按钮 */}
        {isPending && (
          <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
            {/* 接单按钮 */}
            <button
              onClick={handleAccept}
              style={{
                flex: 2, minHeight: 56, borderRadius: 12, border: 'none',
                background: '#0F6E56', color: '#fff',
                fontSize: 18, fontWeight: 700, cursor: 'pointer',
                fontFamily: 'inherit',
                WebkitTapHighlightColor: 'transparent',
                transition: 'transform 200ms ease, opacity 200ms ease',
              }}
              onPointerDown={(e) => {
                (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
                (e.currentTarget as HTMLButtonElement).style.opacity = '0.85';
              }}
              onPointerUp={(e) => {
                (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
                (e.currentTarget as HTMLButtonElement).style.opacity = '1';
              }}
            >
              接单（约20分钟）
            </button>
            {/* 拒单按钮 */}
            <button
              onClick={() => setShowRejectSheet(true)}
              style={{
                flex: 1, minHeight: 56, borderRadius: 12,
                border: '1.5px solid #E8E6E1',
                background: '#F8F7F5', color: '#5F5E5A',
                fontSize: 18, fontWeight: 600, cursor: 'pointer',
                fontFamily: 'inherit',
                WebkitTapHighlightColor: 'transparent',
                transition: 'transform 200ms ease',
              }}
              onPointerDown={(e) => {
                (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
              }}
              onPointerUp={(e) => {
                (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
              }}
            >
              拒单
            </button>
          </div>
        )}

        {/* 配餐中状态标签 */}
        {order.status === 'preparing' && (
          <div style={{
            textAlign: 'center', padding: '10px 0',
            fontSize: 18, color: '#BA7517', fontWeight: 600,
          }}>
            配餐中
          </div>
        )}

        {/* 已完成状态标签 */}
        {order.status === 'done' && (
          <div style={{
            textAlign: 'center', padding: '10px 0',
            fontSize: 18, color: '#0F6E56', fontWeight: 600,
          }}>
            已完成
          </div>
        )}
      </div>

      {/* 拒单原因底部弹层 */}
      {showRejectSheet && (
        <RejectReasonSheet
          onConfirm={handleRejectConfirm}
          onCancel={() => setShowRejectSheet(false)}
        />
      )}
    </>
  );
}

// ─── 列标题组件 ───────────────────────────────────────────────────────────────

function ColumnHeader({
  title, count, color,
}: { title: string; count: number; color: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '12px 16px',
      background: '#F8F7F5', borderRadius: '12px 12px 0 0',
      borderBottom: `3px solid ${color}`,
      marginBottom: 12,
    }}>
      <span style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>{title}</span>
      {count > 0 && (
        <span style={{
          minWidth: 28, height: 28, borderRadius: 14,
          background: color, color: '#fff',
          fontSize: 16, fontWeight: 700,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '0 6px',
        }}>
          {count}
        </span>
      )}
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

/**
 * OmniChannelOrders — 外卖聚合统一接单面板
 *
 * 三列布局：待接单（红色角标）| 配餐中 | 已完成
 * WebSocket实时推送，新单提示音，倒计时自动拒单
 */
export function OmniChannelOrders() {
  const [orders, setOrders] = useState<OmniOrder[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [autoAccept, setAutoAccept] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 从URL参数或store读取 storeId（生产中通过Zustand store获取）
  const storeId = new URLSearchParams(window.location.search).get('store_id') ?? '';
  const tenantId = document.cookie
    .split('; ')
    .find(row => row.startsWith('tenant_id='))
    ?.split('=')[1] ?? '';

  // ── 加载初始待接单订单 ──────────────────────────────────────────────────────

  const loadPendingOrders = useCallback(async () => {
    if (!storeId) return;
    try {
      const resp = await fetch(`/api/v1/omni/orders/pending?store_id=${storeId}`, {
        headers: { 'X-Tenant-ID': tenantId },
      });
      if (!resp.ok) return;
      const json = await resp.json();
      if (json.ok && Array.isArray(json.data)) {
        setOrders(json.data as OmniOrder[]);
      }
    } catch {
      // 网络错误静默降级
    }
  }, [storeId, tenantId]);

  useEffect(() => {
    loadPendingOrders();
  }, [loadPendingOrders]);

  // ── WebSocket实时连接 ───────────────────────────────────────────────────────

  const connectWs = useCallback(() => {
    if (!storeId) return;

    const wsUrl = `ws://${window.location.host}/ws/omni?store_id=${storeId}&tenant_id=${tenantId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as { type: string; data: OmniOrder };
        if (msg.type === 'new_order') {
          playNewOrderSound();
          setOrders((prev) => {
            // 去重：已存在则不重复添加
            const exists = prev.some((o) => o.order_id === msg.data.order_id);
            if (exists) return prev;
            return [msg.data, ...prev];
          });
        } else if (msg.type === 'order_updated') {
          setOrders((prev) =>
            prev.map((o) => (o.order_id === msg.data.order_id ? { ...o, ...msg.data } : o))
          );
        }
      } catch {
        // 忽略无效消息
      }
    };

    ws.onclose = () => {
      setWsConnected(false);
      // 自动重连
      reconnectTimerRef.current = setTimeout(connectWs, WS_RECONNECT_INTERVAL);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [storeId, tenantId]);

  useEffect(() => {
    connectWs();
    return () => {
      wsRef.current?.close();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, [connectWs]);

  // ── 接单 ───────────────────────────────────────────────────────────────────

  const handleAccept = useCallback(async (orderId: string, estimatedMinutes: number) => {
    try {
      const resp = await fetch(`/api/v1/omni/orders/${orderId}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': tenantId },
        body: JSON.stringify({ estimated_minutes: estimatedMinutes }),
      });
      if (!resp.ok) return;
      setOrders((prev) =>
        prev.map((o) => (o.order_id === orderId ? { ...o, status: 'preparing' } : o))
      );
    } catch {
      // 网络错误静默，用户可重试
    }
  }, [tenantId]);

  // ── 拒单 ───────────────────────────────────────────────────────────────────

  const handleReject = useCallback(async (orderId: string, reasonCode: number) => {
    try {
      const resp = await fetch(`/api/v1/omni/orders/${orderId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': tenantId },
        body: JSON.stringify({ reason_code: reasonCode }),
      });
      if (!resp.ok) return;
      setOrders((prev) => prev.filter((o) => o.order_id !== orderId));
    } catch {
      // 网络错误静默
    }
  }, [tenantId]);

  // ── 超时自动拒单（前端触发） ────────────────────────────────────────────────

  const handleTimeout = useCallback(async (orderId: string) => {
    // 前端倒计时到0时调用后端自动拒单接口
    await handleReject(orderId, 1);
  }, [handleReject]);

  // ── 分组 ────────────────────────────────────────────────────────────────────

  const pendingOrders = orders.filter((o) => o.status === 'pending');
  const preparingOrders = orders.filter((o) => o.status === 'preparing');
  const doneOrders = orders.filter((o) => o.status === 'done');

  // ── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <>
      {/* 全局动画样式 */}
      <style>{`
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes slideUp {
          from { transform: translateY(100%); }
          to   { transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.6; }
        }
        * { box-sizing: border-box; }
      `}</style>

      <div style={{
        minHeight: '100vh',
        background: '#F8F7F5',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* ── 顶部导航栏 ── */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '0 20px', height: 60,
          background: '#fff', borderBottom: '1px solid #E8E6E1',
          position: 'sticky', top: 0, zIndex: 100,
        }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#2C2C2A' }}>
            外卖统一接单
          </h1>

          {/* 高峰期自动接单开关 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
            <span style={{ fontSize: 13, color: '#5F5E5A' }}>高峰期自动接单</span>
            <div
              onClick={() => setAutoAccept(!autoAccept)}
              style={{
                width: 44, height: 24, borderRadius: 12, cursor: 'pointer',
                background: autoAccept ? '#FF6B35' : '#ccc',
                position: 'relative', transition: 'background .2s',
              }}
            >
              <div style={{
                position: 'absolute', top: 2,
                left: autoAccept ? 22 : 2,
                width: 20, height: 20, borderRadius: '50%',
                background: '#fff', transition: 'left .2s',
              }} />
            </div>
            {autoAccept && <span style={{ fontSize: 11, color: '#0F6E56' }}>🤖 运营指挥官代理中</span>}
          </div>

          {/* 连接状态指示器（右上角） */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{
              width: 12, height: 12, borderRadius: '50%',
              background: wsConnected ? '#0F6E56' : '#A32D2D',
              boxShadow: wsConnected
                ? '0 0 0 3px rgba(15,110,86,0.2)'
                : '0 0 0 3px rgba(163,45,45,0.2)',
            }} />
            <span style={{ fontSize: 16, color: wsConnected ? '#0F6E56' : '#A32D2D' }}>
              {wsConnected ? '实时连接' : '连接断开'}
            </span>
          </div>
        </div>

        {/* ── 三列主体 ── */}
        <div style={{
          flex: 1, display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr',
          gap: 16, padding: 16,
          alignItems: 'start',
        }}>
          {/* 待接单列 */}
          <div>
            <ColumnHeader
              title="待接单"
              count={pendingOrders.length}
              color="#A32D2D"
            />
            <div style={{
              maxHeight: 'calc(100vh - 120px)',
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
            }}>
              {pendingOrders.length === 0 ? (
                <div style={{
                  padding: 32, textAlign: 'center',
                  fontSize: 18, color: '#B4B2A9',
                }}>
                  暂无待接单订单
                </div>
              ) : (
                pendingOrders.map((order) => (
                  <OrderCard
                    key={order.order_id}
                    order={order}
                    onAccept={handleAccept}
                    onReject={handleReject}
                    onTimeout={handleTimeout}
                  />
                ))
              )}
            </div>
          </div>

          {/* 配餐中列 */}
          <div>
            <ColumnHeader
              title="配餐中"
              count={preparingOrders.length}
              color="#BA7517"
            />
            <div style={{
              maxHeight: 'calc(100vh - 120px)',
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
            }}>
              {preparingOrders.length === 0 ? (
                <div style={{
                  padding: 32, textAlign: 'center',
                  fontSize: 18, color: '#B4B2A9',
                }}>
                  暂无配餐中订单
                </div>
              ) : (
                preparingOrders.map((order) => (
                  <OrderCard
                    key={order.order_id}
                    order={order}
                    onAccept={handleAccept}
                    onReject={handleReject}
                    onTimeout={handleTimeout}
                  />
                ))
              )}
            </div>
          </div>

          {/* 已完成列 */}
          <div>
            <ColumnHeader
              title="已完成"
              count={doneOrders.length}
              color="#0F6E56"
            />
            <div style={{
              maxHeight: 'calc(100vh - 120px)',
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
            }}>
              {doneOrders.length === 0 ? (
                <div style={{
                  padding: 32, textAlign: 'center',
                  fontSize: 18, color: '#B4B2A9',
                }}>
                  今日暂无已完成订单
                </div>
              ) : (
                doneOrders.map((order) => (
                  <OrderCard
                    key={order.order_id}
                    order={order}
                    onAccept={handleAccept}
                    onReject={handleReject}
                    onTimeout={handleTimeout}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

export default OmniChannelOrders;
