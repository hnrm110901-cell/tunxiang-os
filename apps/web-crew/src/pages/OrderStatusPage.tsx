/**
 * 出餐进度追踪页面 — 全屏查看每道菜的制作状态
 * 对标: Square KDS Mobile + Toast Go 2 出餐追踪
 *
 * 状态色: 绿色(已出) / 黄色(制作中) / 灰色(待制作) / 红色(超时)
 * 支持一键催菜
 * Phase 3-A: 出餐时间预测（AI-Native）
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
  warning: '#BA7517',
  info: '#185FA5',
};

const API_BASE = (window as any).__API_BASE__ || '';

/* ---------- 预计时间颜色 ---------- */
function estimateColor(minutes: number): string {
  if (minutes < 5)  return '#22c55e';   // 绿：快好了
  if (minutes <= 15) return '#94a3b8';  // 灰：正常
  if (minutes <= 30) return '#FF9F0A';  // 橙：提醒
  return '#FF3B30';                      // 红：超时预警
}

/* ---------- 预测数据类型 ---------- */

interface OrderCompletionPrediction {
  order_id: string;
  estimated_minutes: number;
  earliest_dish: string;
  latest_dish: string;
  pending_count: number;
}

/* ---------- KDS 数据类型 ---------- */
interface KdsItem {
  taskId: string;
  dishName: string;
  qty: number;
  spec?: string;
  status: 'pending' | 'cooking' | 'done';
  createdAt: string;
  isOvertime: boolean;
  rushCount: number;
  /** Phase 3-A: 预计还需N分钟（来自预测API） */
  estimatedMinutes?: number;
  estimatedConfidence?: 'high' | 'medium' | 'low';
}

/* ---------- 辅助函数 ---------- */
const statusColor = (status: string, isOvertime: boolean) => {
  if (isOvertime) return C.danger;
  if (status === 'done') return C.green;
  if (status === 'cooking') return C.warning;
  return C.muted;
};

const statusLabel = (status: string, isOvertime: boolean) => {
  if (isOvertime) return '超时';
  if (status === 'done') return '已出餐';
  if (status === 'cooking') return '制作中';
  return '待制作';
};

const statusBg = (status: string, isOvertime: boolean) => {
  if (isOvertime) return `${C.danger}22`;
  if (status === 'done') return `${C.green}15`;
  if (status === 'cooking') return `${C.warning}15`;
  return C.card;
};

/* ---------- 组件 ---------- */
function buildKdsUrl(tableNo: string, orderId: string): string {
  const params = new URLSearchParams();
  if (tableNo) params.set('table_no', tableNo);
  if (orderId) params.set('order_id', orderId);
  return `/api/v1/trade/orders/status?${params.toString()}`;
}

function mapApiItem(raw: {
  task_id?: string;
  id?: string;
  dish_name: string;
  quantity?: number;
  qty?: number;
  spec?: string;
  status: string;
  created_at?: string;
  overtime_threshold_min?: number;
  rush_count?: number;
}): KdsItem {
  const createdAt = raw.created_at
    ? new Date(raw.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : '';
  const elapsedMin = raw.created_at
    ? Math.floor((Date.now() - new Date(raw.created_at).getTime()) / 60000)
    : 0;
  const threshold = raw.overtime_threshold_min ?? 20;
  return {
    taskId: raw.task_id ?? raw.id ?? String(Math.random()),
    dishName: raw.dish_name,
    qty: raw.quantity ?? raw.qty ?? 1,
    spec: raw.spec,
    status: (raw.status as KdsItem['status']) ?? 'pending',
    createdAt,
    isOvertime: raw.status !== 'done' && elapsedMin > threshold,
    rushCount: raw.rush_count ?? 0,
  };
}

export function OrderStatusPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const tableNo = params.get('table') || '';
  const orderId = params.get('order_id') || '';

  const [items, setItems] = useState<KdsItem[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [orderPrediction, setOrderPrediction] = useState<OrderCompletionPrediction | null>(null);

  const doneCount = items.filter(i => i.status === 'done').length;
  const totalCount = items.length;
  const hasOvertime = items.some(i => i.isOvertime);

  async function fetchKdsItems() {
    try {
      const res = await fetch(`${API_BASE}${buildKdsUrl(tableNo, orderId)}`, {
        headers: { 'X-Tenant-ID': localStorage.getItem('tenant_id') ?? '' },
      });
      if (!res.ok) throw new Error(`获取出餐状态失败: ${res.status}`);
      const json = await res.json();
      const raw = json?.data?.items ?? json?.items ?? [];
      setItems(raw.map(mapApiItem));
      setLoadError('');
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '出餐状态加载失败');
    }
  }

  // 挂载时拉取 KDS 数据
  useEffect(() => {
    fetchKdsItems();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableNo, orderId]);

  // Phase 3-A: 挂载时拉取订单预测数据
  useEffect(() => {
    if (!orderId || !API_BASE) return;
    const fetchPrediction = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/predict/order/${orderId}/completion`);
        if (!res.ok) return;
        const json = await res.json();
        if (json.ok && json.data) {
          setOrderPrediction(json.data as OrderCompletionPrediction);
        }
      } catch {
        // 预测失败静默降级，不影响主流程
      }
    };
    fetchPrediction();
  }, [orderId]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchKdsItems().finally(() => setRefreshing(false));
  };

  const handleRush = async (taskId: string) => {
    // 乐观更新
    setItems(prev => prev.map(i =>
      i.taskId === taskId ? { ...i, rushCount: i.rushCount + 1 } : i
    ));
    try {
      await fetch(`${API_BASE}/api/v1/kds/tasks/${encodeURIComponent(taskId)}/rush`, {
        method: 'POST',
        headers: { 'X-Tenant-ID': localStorage.getItem('tenant_id') ?? '' },
      });
    } catch {
      // 催菜失败静默处理，乐观更新不回滚
    }
  };

  const handleRushAll = async () => {
    // 乐观更新全部未完成菜品
    setItems(prev => prev.map(i =>
      i.status !== 'done' ? { ...i, rushCount: i.rushCount + 1 } : i
    ));
    const pending = items.filter(i => i.status !== 'done');
    await Promise.allSettled(
      pending.map(i =>
        fetch(`${API_BASE}/api/v1/kds/tasks/${encodeURIComponent(i.taskId)}/rush`, {
          method: 'POST',
          headers: { 'X-Tenant-ID': localStorage.getItem('tenant_id') ?? '' },
        })
      )
    );
  };

  // 排序: 超时 > 制作中 > 待制作 > 已出
  const sortedItems = [...items].sort((a, b) => {
    const order = (i: KdsItem) => {
      if (i.isOvertime) return 0;
      if (i.status === 'cooking') return 1;
      if (i.status === 'pending') return 2;
      return 3;
    };
    return order(a) - order(b);
  });

  return (
    <div style={{ background: C.bg, minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* 顶部 */}
      <div style={{
        padding: '12px 16px', background: C.card,
        borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={() => navigate(-1)}
            style={{
              minWidth: 48, minHeight: 48, borderRadius: 12,
              background: C.card, border: `1px solid ${C.border}`,
              color: C.muted, fontSize: 16, cursor: 'pointer',
            }}
          >
            {'<'}
          </button>
          <div>
            <span style={{ fontSize: 20, fontWeight: 700, color: C.white }}>
              出餐进度
            </span>
            {tableNo && (
              <span style={{ fontSize: 16, color: C.muted, marginLeft: 8 }}>{tableNo}桌</span>
            )}
          </div>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          style={{
            minWidth: 48, minHeight: 48, borderRadius: 12,
            background: C.card, border: `1px solid ${C.border}`,
            color: refreshing ? C.muted : C.text, fontSize: 16, cursor: 'pointer',
          }}
        >
          {refreshing ? '...' : '刷新'}
        </button>
      </div>

      {/* 错误提示 */}
      {loadError && (
        <div style={{
          padding: '10px 16px',
          background: 'rgba(186,117,23,0.12)', borderBottom: `1px solid ${C.border}`,
          fontSize: 14, color: C.warning,
        }}>
          {loadError}
        </div>
      )}

      {/* 汇总条 */}
      <div style={{
        padding: '12px 16px', background: hasOvertime ? `${C.danger}15` : `${C.green}15`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: `1px solid ${C.border}`,
      }}>
        <div>
          <span style={{ fontSize: 18, fontWeight: 700, color: hasOvertime ? C.danger : C.green }}>
            已出 {doneCount} / {totalCount} 道
          </span>
          {/* Phase 3-A: 订单整体预测 */}
          {orderPrediction && doneCount < totalCount && (
            <div style={{ fontSize: 14, color: estimateColor(orderPrediction.estimated_minutes), marginTop: 2 }}>
              预计全部出餐：约 {orderPrediction.estimated_minutes} 分钟
            </div>
          )}
        </div>
        {doneCount < totalCount && (
          <button
            onClick={handleRushAll}
            style={{
              minHeight: 48, padding: '8px 20px', borderRadius: 10,
              background: C.danger, border: 'none',
              color: C.white, fontSize: 16, fontWeight: 700, cursor: 'pointer',
            }}
          >
            一键催全部
          </button>
        )}
      </div>

      {/* 菜品列表 */}
      <div style={{
        flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as any,
        padding: '12px', paddingBottom: 80,
      }}>
        {sortedItems.map(item => (
          <div
            key={item.taskId}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: 14, marginBottom: 8, borderRadius: 12,
              background: statusBg(item.status, item.isOvertime),
              borderLeft: `4px solid ${statusColor(item.status, item.isOvertime)}`,
            }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 18, fontWeight: 600, color: C.white }}>
                  {item.dishName}
                </span>
                <span style={{ fontSize: 16, color: C.muted }}>x{item.qty}</span>
                {item.spec && (
                  <span style={{ fontSize: 16, color: C.muted }}>/ {item.spec}</span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                <span style={{
                  fontSize: 16, fontWeight: 700, padding: '2px 8px', borderRadius: 6,
                  background: `${statusColor(item.status, item.isOvertime)}22`,
                  color: statusColor(item.status, item.isOvertime),
                }}>
                  {statusLabel(item.status, item.isOvertime)}
                </span>
                <span style={{ fontSize: 16, color: C.muted }}>
                  下单 {item.createdAt}
                </span>
                {item.rushCount > 0 && (
                  <span style={{ fontSize: 16, color: C.warning, fontWeight: 600 }}>
                    已催{item.rushCount}次
                  </span>
                )}
              </div>
              {/* Phase 3-A: 预计时间显示 */}
              {item.status !== 'done' && orderPrediction && orderPrediction.estimated_minutes > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                  <span style={{
                    fontSize: 14,
                    color: estimateColor(orderPrediction.estimated_minutes),
                    fontWeight: 600,
                  }}>
                    约 {orderPrediction.estimated_minutes} 分钟
                  </span>
                  <span style={{ fontSize: 12, color: C.muted }}>
                    {orderPrediction.estimated_minutes < 5
                      ? '快好了'
                      : orderPrediction.estimated_minutes > 30
                        ? '超时预警'
                        : ''}
                  </span>
                </div>
              )}
            </div>
            {item.status !== 'done' && (
              <button
                onClick={() => handleRush(item.taskId)}
                style={{
                  minWidth: 64, minHeight: 48, borderRadius: 10,
                  background: item.isOvertime ? C.danger : `${C.warning}22`,
                  border: item.isOvertime ? 'none' : `1px solid ${C.warning}`,
                  color: item.isOvertime ? C.white : C.warning,
                  fontSize: 16, fontWeight: 700, cursor: 'pointer',
                  flexShrink: 0, marginLeft: 8,
                }}
              >
                催菜
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
