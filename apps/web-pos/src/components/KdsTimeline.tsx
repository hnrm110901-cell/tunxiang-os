import { txColors } from '@tx/tokens';
/**
 * KdsTimeline — 出餐节奏引擎时间线视图
 *
 * 水平条状时间线展示每张订单的完整生命周期：
 *   ordered → preparing → ready → served
 * 按紧急程度排序（超时 > 偏慢 > 正常）
 *
 * 配色：
 *   🟢 正常 (< 5min)     #10B981
 *   🟡 偏慢 (5-10min)    #F59E0B
 *   🔴 超时 (> 10min)    #EF4444
 */
// ─── Types ──────────────────────────────────────────────────────────────────────

interface TimelineOrder {
  id: string;
  callNumber: string;
  orderType: 'dine_in' | 'pack' | 'takeaway';
  status: 'pending' | 'preparing' | 'ready' | 'called' | 'completed';
  items: { name: string; qty: number }[];
  createdAt: string;
  readyAt: string | null;
  /** 各阶段耗时（秒），由调用方基于事件数据计算 */
  stageDurations?: {
    ordered: number;   // 已点 → 制作中
    preparing: number; // 制作中 → 已出餐
    ready: number;     // 已出餐 → 已取餐
  };
}

interface KdsTimelineProps {
  orders: TimelineOrder[];
  /** 预期总出餐时间（秒），默认 600（10 分钟） */
  expectedTimeSec?: number;
}

// ─── Design Tokens ──────────────────────────────────────────────────────────────

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: txColors.primary,
  success: '#10B981',
  warning: '#F59E0B',
  danger: '#EF4444',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
  dimText: '#6B7280',
  barBg: '#1A3A48',
};

// ─── Helpers ────────────────────────────────────────────────────────────────────

function elapsedSec(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
}

function formatDuration(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${min}m${s}s` : `${min}min`;
}

function pacingLevel(totalSec: number, expectedSec: number): 'normal' | 'slow' | 'overdue' {
  if (totalSec <= expectedSec) return 'normal';
  if (totalSec <= expectedSec * 1.5) return 'slow';
  return 'overdue';
}

const PACING_COLOR = { normal: '#10B981', slow: '#F59E0B', overdue: '#EF4444' };
const PACING_LABEL = { normal: '正常', slow: '偏慢', overdue: '超时' };

// ─── Component ──────────────────────────────────────────────────────────────────

export function KdsTimeline({ orders, expectedTimeSec = 600 }: KdsTimelineProps) {
  // 每帧重新计算（父组件 1s ticker 驱动），确保耗时实时更新
  const withPacing = orders.map((o) => {
    const total = elapsedSec(o.createdAt);
    return { ...o, totalSec: total, pacing: pacingLevel(total, expectedTimeSec) };
  });
  const orderMap: Record<string, number> = { overdue: 0, slow: 1, normal: 2 };
  const sorted = [...withPacing].sort(
    (a, b) => orderMap[a.pacing] - orderMap[b.pacing] || b.totalSec - a.totalSec,
  );

  if (sorted.length === 0) {
    return (
      <div style={{ textAlign: 'center', color: C.dimText, padding: 60, fontSize: 16 }}>
        暂无出餐中的订单
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 图例 */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 4 }}>
        {(['normal', 'slow', 'overdue'] as const).map((level) => (
          <div key={level} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: PACING_COLOR[level], display: 'inline-block' }} />
            <span style={{ fontSize: 12, color: C.muted }}>{PACING_LABEL[level]}</span>
          </div>
        ))}
        <div style={{ marginLeft: 'auto', fontSize: 12, color: C.muted }}>
          预期出餐 ≤ {formatDuration(expectedTimeSec)}
        </div>
      </div>

      {sorted.map((order) => {
        const pct = Math.min((order.totalSec / expectedTimeSec) * 100, 100);
        const pColor = PACING_COLOR[order.pacing];
        const stageDuration = order.stageDurations;

        return (
          <div
            key={order.id}
            style={{
              background: C.card,
              border: `1px solid ${order.pacing === 'overdue' ? 'rgba(239,68,68,0.3)' : C.border}`,
              borderRadius: 12,
              padding: '14px 18px',
              borderLeft: `4px solid ${pColor}`,
            }}
          >
            {/* 头部 */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 22, fontWeight: 900, color: C.white }}>
                  #{order.callNumber}
                </span>
                <span style={{
                  padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                  background: order.orderType === 'dine_in' ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                  color: order.orderType === 'dine_in' ? C.success : C.warning,
                }}>
                  {order.orderType === 'dine_in' ? '堂食' : '打包'}
                </span>
                <span style={{
                  padding: '2px 10px', borderRadius: 10, fontSize: 11, fontWeight: 700,
                  background: `${pColor}18`,
                  color: pColor,
                }}>
                  {PACING_LABEL[order.pacing]}
                </span>
              </div>
              <div style={{ fontSize: 13, color: pColor, fontWeight: 600 }}>
                {formatDuration(order.totalSec)}
              </div>
            </div>

            {/* 菜品摘要 */}
            <div style={{ fontSize: 12, color: C.muted, marginBottom: 10 }}>
              {order.items.slice(0, 3).map((item) => item.name).join('、')}
              {order.items.length > 3 && <span> 等{order.items.length}项</span>}
            </div>

            {/* 时间线进度条 */}
            <div style={{ position: 'relative', marginTop: 4 }}>
              {/* 背景条 */}
              <div style={{
                height: 20, borderRadius: 10,
                background: C.barBg, overflow: 'hidden',
                position: 'relative',
              }}>
                {/* 已过时间填充 */}
                <div style={{
                  height: '100%', borderRadius: 10,
                  width: `${Math.min(pct, 100)}%`,
                  background: `linear-gradient(90deg, ${C.success}, ${pColor})`,
                  transition: 'width 1s ease',
                  opacity: 0.85,
                }} />
              </div>

              {/* 阶段标记 */}
              <div style={{
                position: 'absolute', top: 0, left: 0, right: 0, height: 20,
                display: 'flex', alignItems: 'center', padding: '0 8px',
                pointerEvents: 'none',
              }}>
                {/* ordered 阶段 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: C.white, fontWeight: 600 }}>
                  <span>📋</span>
                  <span>已点</span>
                  {stageDuration && <span style={{ opacity: 0.6, fontWeight: 400 }}>{formatDuration(stageDuration.ordered)}</span>}
                </div>
                {order.status !== 'pending' && (
                  <>
                    <span style={{ margin: '0 6px', color: C.muted, fontSize: 10 }}>▶</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: C.white, fontWeight: 600 }}>
                      <span>👨‍🍳</span>
                      <span>制作中</span>
                      {stageDuration && <span style={{ opacity: 0.6, fontWeight: 400 }}>{formatDuration(stageDuration.preparing)}</span>}
                    </div>
                  </>
                )}
                {(order.status === 'ready' || order.status === 'called') && (
                  <>
                    <span style={{ margin: '0 6px', color: C.muted, fontSize: 10 }}>▶</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: C.success, fontWeight: 600 }}>
                      <span>✅</span>
                      <span>待取餐</span>
                      {stageDuration && <span style={{ opacity: 0.6, fontWeight: 400 }}>{formatDuration(stageDuration.ready)}</span>}
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* 时间标尺 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 10, color: C.muted }}>
              <span>下单 {order.createdAt ? new Date(order.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '--'}</span>
              <span>预期 {formatDuration(expectedTimeSec)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 工具：从订单数据推导阶段耗时 ───────────────────────────────────────────────

export function deriveStageDurations(
  createdAt: string,
  readyAt: string | null,
  status: string,
): { ordered: number; preparing: number; ready: number } {
  const now = Date.now();
  const created = new Date(createdAt).getTime();
  const ready = readyAt ? new Date(readyAt).getTime() : null;
  const total = Math.floor((now - created) / 1000);

  // 根据状态合理分配阶段耗时
  switch (status) {
    case 'pending':
      return { ordered: total, preparing: 0, ready: 0 };
    case 'preparing': {
      // 假设一半时间在 ordered，一半在 preparing
      const half = Math.floor(total / 2);
      return { ordered: half, preparing: total - half, ready: 0 };
    }
    case 'ready':
    case 'called': {
      if (ready) {
        const totalBeforeReady = Math.floor((ready - created) / 1000);
        const ordered = Math.floor(totalBeforeReady * 0.4);
        const preparing = totalBeforeReady - ordered;
        const readyPhase = Math.floor((now - ready) / 1000);
        return { ordered: Math.max(ordered, 0), preparing: Math.max(preparing, 0), ready: Math.max(readyPhase, 0) };
      }
      return { ordered: Math.floor(total * 0.4), preparing: Math.floor(total * 0.4), ready: Math.floor(total * 0.2) };
    }
    default:
      return { ordered: total, preparing: 0, ready: 0 };
  }
}
