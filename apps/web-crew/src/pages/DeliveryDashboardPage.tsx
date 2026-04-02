/**
 * 外卖接单面板 — 多平台订单聚合
 *
 * 路由: /delivery
 * 功能: 新订单接单/拒绝 → 开始备餐 → 备餐完成 → 骑手取餐 → 完成
 * 实时: 每10秒轮询，新订单到达时浏览器通知 + 标题闪烁
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { txFetch } from '../api/index';

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

type OrderStatus =
  | 'pending_accept'
  | 'confirmed'
  | 'accepted'
  | 'cooking'
  | 'ready'
  | 'delivering'
  | 'completed'
  | 'cancelled'
  | 'rejected';

type Platform = 'meituan' | 'eleme' | 'douyin' | 'wechat' | 'manual';

interface OrderItem {
  name: string;
  qty: number;
  price_fen: number;
  spec?: string;
}

interface DeliveryOrder {
  id: string;
  platform: Platform;
  platform_name: string;
  platform_order_no: string | null;
  status: OrderStatus;
  store_id: string;
  customer_name: string | null;
  customer_phone: string | null;
  delivery_address: string | null;
  items: OrderItem[];
  note: string | null;
  total_fen: number;
  actual_revenue_fen: number | null;
  commission_fen: number | null;
  estimated_delivery_min: number | null;
  estimated_prep_time: number | null;
  rider_name: string | null;
  rider_phone: string | null;
  accepted_at: string | null;
  ready_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

interface OrderListData {
  items: DeliveryOrder[];
  total: number;
  page: number;
  size: number;
}

interface DailyStats {
  total_orders: number;
  accepted_count: number;
  cancelled_count: number;
  total_revenue_fen: number;
  platform_breakdown: Record<string, number>;
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const PLATFORM_COLOR: Record<string, string> = {
  meituan: '#F5A623',
  eleme:   '#0099FF',
  douyin:  '#FE2C55',
  wechat:  '#07C160',
  manual:  '#64748b',
};

const STATUS_LABEL: Record<string, string> = {
  pending_accept: '待接单',
  confirmed:      '待接单',
  accepted:       '已接单',
  cooking:        '备餐中',
  ready:          '待取餐',
  delivering:     '配送中',
  completed:      '已完成',
  cancelled:      '已取消',
  rejected:       '已拒绝',
};

const NEXT_ACTION: Record<string, { label: string; targetStatus: string }> = {
  accepted: { label: '开始备餐', targetStatus: 'cooking' },
  cooking:  { label: '备餐完成', targetStatus: 'ready' },
  ready:    { label: '骑手已取', targetStatus: 'delivering' },
  delivering: { label: '已完成', targetStatus: 'completed' },
};

const STORE_ID = (window as { __STORE_ID__?: string }).__STORE_ID__ || '';

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

function fenToYuan(fen: number | null | undefined): string {
  if (fen == null) return '—';
  return `¥${(fen / 100).toFixed(2)}`;
}

function formatTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function elapsedMin(iso: string | null): number {
  if (!iso) return 0;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
}

// 构造平台状态查询参数
function statusQueryForTab(tab: TabType): string {
  if (tab === 'new') return 'pending_accept,confirmed';
  if (tab === 'active') return 'accepted,cooking,ready,delivering';
  return 'completed';
}

// ─── 子组件：平台标签 ──────────────────────────────────────────────────────────

function PlatformBadge({ platform, name }: { platform: string; name: string }) {
  const color = PLATFORM_COLOR[platform] || '#64748b';
  return (
    <span style={{
      background: color,
      color: '#fff',
      fontSize: 13,
      fontWeight: 700,
      padding: '2px 8px',
      borderRadius: 4,
    }}>
      {name || platform}
    </span>
  );
}

// ─── 子组件：订单卡片 ──────────────────────────────────────────────────────────

interface CardProps {
  order: DeliveryOrder;
  tab: TabType;
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  onStatusNext: (id: string, targetStatus: string) => void;
  loading: string | null; // order id currently loading
}

function OrderCard({ order, tab, onAccept, onReject, onStatusNext, loading }: CardProps) {
  const isLoading = loading === order.id;
  const platformColor = PLATFORM_COLOR[order.platform] || '#64748b';
  const elapsed = elapsedMin(order.created_at);
  const nextAction = NEXT_ACTION[order.status];

  return (
    <div style={{
      background: '#112228',
      borderRadius: 12,
      marginBottom: 12,
      overflow: 'hidden',
      border: `1px solid #1a3040`,
    }}>
      {/* 平台色条 */}
      <div style={{ height: 4, background: platformColor }} />

      {/* 订单头部 */}
      <div style={{ padding: '12px 16px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <PlatformBadge platform={order.platform} name={order.platform_name} />
          <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>
            #{order.platform_order_no || order.id.slice(-6).toUpperCase()}
          </span>
          <span style={{ fontSize: 14, color: '#94a3b8', marginLeft: 'auto' }}>
            {formatTime(order.created_at)}来单
          </span>
          {order.estimated_delivery_min && (
            <span style={{ fontSize: 14, color: '#f59e0b' }}>
              ⏱ {order.estimated_delivery_min}分钟送达
            </span>
          )}
        </div>

        {tab === 'active' && (
          <div style={{ marginTop: 6 }}>
            <span style={{
              fontSize: 13,
              background: 'rgba(255,107,44,0.15)',
              color: '#FF6B35',
              padding: '2px 8px',
              borderRadius: 12,
            }}>
              {STATUS_LABEL[order.status] || order.status}
              {elapsed > 0 && ` · 已${elapsed}分钟`}
            </span>
          </div>
        )}
      </div>

      {/* 分割线 */}
      <div style={{ margin: '10px 16px', borderTop: '1px solid #1e3545' }} />

      {/* 菜品列表 */}
      <div style={{ padding: '0 16px' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '4px 16px',
        }}>
          {order.items.map((item, idx) => (
            <div key={idx} style={{ fontSize: 15, color: '#cbd5e1' }}>
              {item.name}
              {item.spec ? `(${item.spec})` : ''} × {item.qty}
            </div>
          ))}
        </div>
      </div>

      {/* 备注 */}
      {order.note && (
        <>
          <div style={{ margin: '10px 16px', borderTop: '1px solid #1e3545' }} />
          <div style={{ padding: '0 16px', fontSize: 14, color: '#f59e0b' }}>
            备注：{order.note}
          </div>
        </>
      )}

      {/* 分割线 + 金额 */}
      <div style={{ margin: '10px 16px', borderTop: '1px solid #1e3545' }} />
      <div style={{ padding: '0 16px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}>
        <span style={{ fontSize: 17, fontWeight: 700, color: '#fff' }}>
          实收 {fenToYuan(order.actual_revenue_fen ?? order.total_fen)}
        </span>
        {(order.commission_fen ?? 0) > 0 && (
          <span style={{ fontSize: 13, color: '#64748b' }}>
            平台佣金 {fenToYuan(order.commission_fen)}
          </span>
        )}
      </div>

      {/* 操作按钮区 */}
      {tab === 'new' && (
        <div style={{ padding: '0 16px 16px', display: 'flex', gap: 10 }}>
          <button
            disabled={isLoading}
            onClick={() => onAccept(order.id)}
            style={{
              flex: 2,
              minHeight: 56,
              background: isLoading ? '#444' : '#FF6B35',
              color: '#fff',
              border: 'none',
              borderRadius: 10,
              fontSize: 18,
              fontWeight: 700,
              cursor: isLoading ? 'not-allowed' : 'pointer',
            }}
          >
            {isLoading ? '处理中…' : '接单并打印'}
          </button>
          <button
            disabled={isLoading}
            onClick={() => onReject(order.id)}
            style={{
              flex: 1,
              minHeight: 56,
              background: 'transparent',
              color: '#ef4444',
              border: '1.5px solid #ef4444',
              borderRadius: 10,
              fontSize: 17,
              fontWeight: 600,
              cursor: isLoading ? 'not-allowed' : 'pointer',
            }}
          >
            拒绝
          </button>
        </div>
      )}

      {tab === 'active' && nextAction && (
        <div style={{ padding: '0 16px 16px' }}>
          <button
            disabled={isLoading}
            onClick={() => onStatusNext(order.id, nextAction.targetStatus)}
            style={{
              width: '100%',
              minHeight: 52,
              background: isLoading ? '#444' : '#0099FF',
              color: '#fff',
              border: 'none',
              borderRadius: 10,
              fontSize: 17,
              fontWeight: 700,
              cursor: isLoading ? 'not-allowed' : 'pointer',
            }}
          >
            {isLoading ? '处理中…' : nextAction.label}
          </button>
        </div>
      )}

      {/* 骑手信息（delivering状态） */}
      {order.status === 'delivering' && order.rider_name && (
        <div style={{ padding: '0 16px 12px', fontSize: 14, color: '#94a3b8' }}>
          骑手：{order.rider_name}
          {order.rider_phone && ` · ${order.rider_phone}`}
        </div>
      )}
    </div>
  );
}

// ─── 子组件：今日统计汇总 ──────────────────────────────────────────────────────

function StatsCard({ stats }: { stats: DailyStats | null }) {
  if (!stats) {
    return (
      <div style={{ padding: '40px 16px', textAlign: 'center', color: '#64748b', fontSize: 16 }}>
        加载统计数据中…
      </div>
    );
  }

  const breakdown = stats.platform_breakdown || {};
  const total = Object.values(breakdown).reduce((s, n) => s + n, 0) || 1;

  return (
    <div style={{ padding: '0 16px' }}>
      {/* 汇总数字 */}
      <div style={{
        background: '#112228',
        borderRadius: 12,
        padding: 16,
        marginBottom: 12,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 12,
      }}>
        <div>
          <div style={{ fontSize: 13, color: '#64748b' }}>今日单量</div>
          <div style={{ fontSize: 28, fontWeight: 800, color: '#FF6B35' }}>{stats.total_orders}</div>
        </div>
        <div>
          <div style={{ fontSize: 13, color: '#64748b' }}>总收入（扣佣后）</div>
          <div style={{ fontSize: 24, fontWeight: 800, color: '#fff' }}>
            {fenToYuan(stats.total_revenue_fen)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 13, color: '#64748b' }}>接单数</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#07C160' }}>{stats.accepted_count}</div>
        </div>
        <div>
          <div style={{ fontSize: 13, color: '#64748b' }}>取消数</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#ef4444' }}>{stats.cancelled_count}</div>
        </div>
      </div>

      {/* 平台分布色块进度条 */}
      {Object.keys(breakdown).length > 0 && (
        <div style={{
          background: '#112228',
          borderRadius: 12,
          padding: 16,
        }}>
          <div style={{ fontSize: 14, color: '#64748b', marginBottom: 10 }}>平台分布</div>
          {/* 色块百分比bar */}
          <div style={{ display: 'flex', height: 20, borderRadius: 6, overflow: 'hidden', marginBottom: 12 }}>
            {Object.entries(breakdown).map(([platform, count]) => {
              const pct = count / total * 100;
              return (
                <div
                  key={platform}
                  style={{
                    width: `${pct}%`,
                    background: PLATFORM_COLOR[platform] || '#64748b',
                    minWidth: pct > 0 ? 4 : 0,
                  }}
                />
              );
            })}
          </div>
          {/* 图例 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px' }}>
            {Object.entries(breakdown).map(([platform, count]) => {
              const pct = Math.round(count / total * 100);
              const nameMap: Record<string, string> = {
                meituan: '美团', eleme: '饿了么', douyin: '抖音', wechat: '微信', manual: '手动',
              };
              return (
                <div key={platform} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{
                    width: 10, height: 10, borderRadius: 2,
                    background: PLATFORM_COLOR[platform] || '#64748b',
                  }} />
                  <span style={{ fontSize: 14, color: '#cbd5e1' }}>
                    {nameMap[platform] || platform} {count}单 ({pct}%)
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Tab 类型 ──────────────────────────────────────────────────────────────────

type TabType = 'new' | 'active' | 'done';

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function DeliveryDashboardPage() {
  const [tab, setTab] = useState<TabType>('new');
  const [orders, setOrders] = useState<DeliveryOrder[]>([]);
  const [stats, setStats] = useState<DailyStats | null>(null);
  const [loadingOrder, setLoadingOrder] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newOrderCount, setNewOrderCount] = useState(0);

  // 用于检测新到订单（轮询对比）
  const knownIdsRef = useRef<Set<string>>(new Set());
  // 标题闪烁定时器
  const titleFlashRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // 是否已初始化（首次加载不触发通知）
  const initializedRef = useRef(false);

  // ── 标题闪烁 ────────────────────────────────────────────────────────────────

  const startTitleFlash = useCallback(() => {
    if (titleFlashRef.current) return;
    let on = true;
    const origTitle = document.title;
    titleFlashRef.current = setInterval(() => {
      document.title = on ? '[新订单] 屯象收银' : origTitle;
      on = !on;
    }, 800);
    // 10秒后停止
    setTimeout(() => {
      if (titleFlashRef.current) {
        clearInterval(titleFlashRef.current);
        titleFlashRef.current = null;
        document.title = origTitle;
      }
    }, 10000);
  }, []);

  // ── 浏览器通知 ──────────────────────────────────────────────────────────────

  const notifyNewOrder = useCallback((count: number) => {
    startTitleFlash();
    if (!('Notification' in window)) return;
    if (Notification.permission === 'granted') {
      new Notification(`${count > 1 ? `${count}个` : ''}新外卖订单到达！`, {
        body: '请及时接单',
        icon: '/favicon.ico',
        tag: 'delivery-new-order',
      });
    } else if (Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, [startTitleFlash]);

  // ── 加载订单列表 ────────────────────────────────────────────────────────────

  const loadOrders = useCallback(async (silent = false) => {
    if (!silent) setError(null);
    try {
      const statusParam = statusQueryForTab(tab === 'done' ? 'done' : tab);
      const storeParam = STORE_ID ? `&store_id=${encodeURIComponent(STORE_ID)}` : '';
      const data = await txFetch<OrderListData>(
        `/api/v1/delivery/orders?status=${encodeURIComponent(statusParam)}&size=50${storeParam}`,
      );
      const fetched = data.items || [];

      if (tab === 'new') {
        setNewOrderCount(fetched.length);
        // 检测新增订单
        if (initializedRef.current) {
          const newOnes = fetched.filter(o => !knownIdsRef.current.has(o.id));
          if (newOnes.length > 0) {
            notifyNewOrder(newOnes.length);
          }
        }
        fetched.forEach(o => knownIdsRef.current.add(o.id));
        initializedRef.current = true;
      }

      setOrders(fetched);
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : '加载失败');
      }
    }
  }, [tab, notifyNewOrder]);

  // ── 加载统计 ────────────────────────────────────────────────────────────────

  const loadStats = useCallback(async () => {
    if (!STORE_ID) return;
    try {
      const today = new Date().toISOString().slice(0, 10);
      const data = await txFetch<DailyStats>(
        `/api/v1/delivery/stats?store_id=${encodeURIComponent(STORE_ID)}&date=${today}`,
      );
      setStats(data);
    } catch {
      // 统计加载失败不影响主流程
    }
  }, []);

  // ── 页面可见时轮询 ──────────────────────────────────────────────────────────

  useEffect(() => {
    loadOrders();
    if (tab === 'done') loadStats();

    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadOrders(true);
      }
    }, 10000);

    return () => clearInterval(interval);
  }, [tab, loadOrders, loadStats]);

  // ── 操作：接单 ──────────────────────────────────────────────────────────────

  const handleAccept = useCallback(async (orderId: string) => {
    setLoadingOrder(orderId);
    try {
      await txFetch(`/api/v1/delivery/orders/${orderId}/accept`, {
        method: 'POST',
        body: JSON.stringify({ prep_time_minutes: 20 }),
      });
      // 如在安卓环境，调用打印
      if ((window as { TXBridge?: { print: (s: string) => void } }).TXBridge) {
        (window as { TXBridge: { print: (s: string) => void } }).TXBridge.print(
          `[外卖接单] 订单: ${orderId}`,
        );
      }
      await loadOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : '接单失败');
    } finally {
      setLoadingOrder(null);
    }
  }, [loadOrders]);

  // ── 操作：拒绝 ──────────────────────────────────────────────────────────────

  const handleReject = useCallback(async (orderId: string) => {
    setLoadingOrder(orderId);
    try {
      await txFetch(`/api/v1/delivery/orders/${orderId}/reject`, {
        method: 'POST',
        body: JSON.stringify({ reason: '暂停接单', reason_code: 'paused' }),
      });
      await loadOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : '拒单失败');
    } finally {
      setLoadingOrder(null);
    }
  }, [loadOrders]);

  // ── 操作：状态流转 ──────────────────────────────────────────────────────────

  const handleStatusNext = useCallback(async (orderId: string, targetStatus: string) => {
    setLoadingOrder(orderId);
    try {
      await txFetch(`/api/v1/delivery/orders/${orderId}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: targetStatus }),
      });
      await loadOrders();
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    } finally {
      setLoadingOrder(null);
    }
  }, [loadOrders]);

  // ── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <div style={{ minHeight: '100vh', background: '#0B1A20', color: '#fff', paddingBottom: 80 }}>
      {/* 顶部标题栏 */}
      <div style={{
        padding: '16px 16px 0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <h1 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>外卖接单</h1>
        <button
          onClick={() => loadOrders()}
          style={{
            background: 'transparent',
            border: '1px solid #1e3545',
            color: '#94a3b8',
            borderRadius: 8,
            padding: '6px 14px',
            fontSize: 14,
            cursor: 'pointer',
          }}
        >
          刷新
        </button>
      </div>

      {/* Tab 切换 */}
      <div style={{
        display: 'flex',
        padding: '12px 16px 0',
        gap: 0,
        borderBottom: '1px solid #1e3545',
      }}>
        {([
          { key: 'new', label: '新订单' },
          { key: 'active', label: '进行中' },
          { key: 'done', label: '今日完成' },
        ] as const).map(({ key, label }) => {
          const isActive = tab === key;
          return (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                flex: 1,
                background: 'transparent',
                border: 'none',
                color: isActive ? '#FF6B35' : '#64748b',
                fontSize: 16,
                fontWeight: isActive ? 700 : 400,
                padding: '10px 4px 12px',
                cursor: 'pointer',
                position: 'relative',
                minHeight: 48,
              }}
            >
              {label}
              {/* 新订单红色badge */}
              {key === 'new' && newOrderCount > 0 && (
                <span style={{
                  position: 'absolute',
                  top: 6,
                  right: '50%',
                  transform: 'translateX(calc(50% + 20px))',
                  background: '#ef4444',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 700,
                  minWidth: 18,
                  height: 18,
                  borderRadius: 9,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: '0 4px',
                }}>
                  {newOrderCount > 99 ? '99+' : newOrderCount}
                </span>
              )}
              {/* 下划线激活指示 */}
              {isActive && (
                <div style={{
                  position: 'absolute',
                  bottom: 0,
                  left: '20%',
                  right: '20%',
                  height: 2,
                  background: '#FF6B35',
                  borderRadius: 1,
                }} />
              )}
            </button>
          );
        })}
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          margin: '12px 16px 0',
          padding: '10px 14px',
          background: 'rgba(239,68,68,0.15)',
          border: '1px solid rgba(239,68,68,0.4)',
          borderRadius: 8,
          fontSize: 14,
          color: '#fca5a5',
        }}>
          {error}
          <button
            onClick={() => setError(null)}
            style={{ background: 'none', border: 'none', color: '#fca5a5', cursor: 'pointer', float: 'right' }}
          >
            ✕
          </button>
        </div>
      )}

      {/* 主内容区 */}
      <div style={{ padding: '12px 16px 0' }}>
        {/* 今日完成 - 统计面板 */}
        {tab === 'done' && (
          <>
            <StatsCard stats={stats} />
            <div style={{ marginTop: 12 }}>
              {orders.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#64748b', fontSize: 16, padding: '40px 0' }}>
                  今日暂无已完成订单
                </div>
              ) : (
                orders.map(order => (
                  <div
                    key={order.id}
                    style={{
                      background: '#112228',
                      borderRadius: 10,
                      padding: 14,
                      marginBottom: 10,
                      borderLeft: `3px solid ${PLATFORM_COLOR[order.platform] || '#64748b'}`,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <PlatformBadge platform={order.platform} name={order.platform_name} />
                        <span style={{ fontSize: 15, color: '#fff' }}>
                          #{order.platform_order_no || order.id.slice(-6).toUpperCase()}
                        </span>
                      </div>
                      <span style={{ fontSize: 16, fontWeight: 700, color: '#07C160' }}>
                        {fenToYuan(order.actual_revenue_fen ?? order.total_fen)}
                      </span>
                    </div>
                    <div style={{ marginTop: 6, fontSize: 13, color: '#64748b' }}>
                      {formatTime(order.completed_at || order.created_at)} 完成 ·
                      {order.items.length}个菜品
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}

        {/* 新订单 / 进行中 */}
        {(tab === 'new' || tab === 'active') && (
          <>
            {orders.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#64748b', fontSize: 16, padding: '60px 0' }}>
                {tab === 'new' ? '暂无新订单' : '暂无进行中的订单'}
              </div>
            ) : (
              orders.map(order => (
                <OrderCard
                  key={order.id}
                  order={order}
                  tab={tab}
                  onAccept={handleAccept}
                  onReject={handleReject}
                  onStatusNext={handleStatusNext}
                  loading={loadingOrder}
                />
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
