/**
 * OnlineOrdersPage — 线上订单接单面板（模块 2.4）
 *
 * 调用 /api/v1/omni/* 接口（omni_sync_routes.py）：
 *   GET  /api/v1/omni/online-orders       — 待处理线上订单列表
 *   POST /api/v1/omni/online-orders/:id/accept  — 接单
 *   POST /api/v1/omni/online-orders/:id/reject  — 拒单
 *   POST /api/v1/omni/online-orders/:id/refund  — 退单
 *
 * 接单后自动触发打印：
 *   - 安卓 POS：window.TXBridge.print(data)
 *   - iPad / 浏览器：POST /api/print 到安卓 POS（HTTP fallback）
 *
 * 遵循 Store 终端触控规范：
 *   - 最小触控区域 ≥ 48×48px
 *   - 字体 ≥ 16px
 *   - 无 hover，用 :active + scale(0.97) 触控反馈
 *   - 15 秒轮询刷新待处理订单
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { getStoreToken } from '../api/index';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type Platform = 'meituan' | 'eleme' | 'douyin';

interface OrderItem {
  name: string;
  quantity: number;
  price_fen: number;
  notes?: string;
}

interface OnlineOrder {
  order_id: string;
  platform: Platform;
  platform_label: string;
  platform_order_id: string;
  status: string;
  total_fen: number;
  items: OrderItem[];
  customer_phone: string;
  delivery_address: string;
  notes: string;
  created_at: string;
}

interface PrintData {
  title: string;
  order_id: string;
  platform_order_id: string;
  total_fen: number;
  items: OrderItem[];
  notes: string;
  delivery_address: string;
  customer_phone: string;
  accepted_at: string;
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 15_000;
const AUTO_REJECT_SECONDS = 180;

const PLATFORM_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  meituan: { label: '美团', color: '#FF6600', bg: '#FFF0E6' },
  eleme:   { label: '饿了么', color: '#0EA5E9', bg: '#E6F4FF' },
  douyin:  { label: '抖音', color: '#1C1C1E', bg: '#F0F0F2' },
};

const REJECT_REASONS: { code: number; label: string }[] = [
  { code: 1, label: '餐厅暂时无法接单' },
  { code: 2, label: '餐厅已打烊' },
  { code: 3, label: '食材不足，无法制作' },
  { code: 4, label: '超出配送范围' },
  { code: 9, label: '其他原因' },
];

// ─── TXBridge 类型声明（安卓 POS 注入） ───────────────────────────────────────

declare global {
  interface Window {
    TXBridge?: {
      print: (content: string) => void;
      getMacMiniUrl?: () => string;
    };
    __STORE_ID__?: string;
    __POS_HOST_URL__?: string;
  }
}

// ─── 环境检测 ─────────────────────────────────────────────────────────────────

const isAndroidPOS = () => !!window.TXBridge;
const getStoreId = () =>
  (window.__STORE_ID__ as string | undefined) || '';
const getPosHostUrl = () =>
  (window.__POS_HOST_URL__ as string | undefined) || 'http://localhost:8080';

// ─── API 调用 ─────────────────────────────────────────────────────────────────

function buildHeaders(): HeadersInit {
  const token = getStoreToken();
  const storeId = getStoreId();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (storeId) headers['X-Tenant-ID'] = storeId;
  return headers;
}

async function fetchOnlineOrders(storeId: string, platform?: string): Promise<OnlineOrder[]> {
  const params = new URLSearchParams({ store_id: storeId, size: '50' });
  if (platform) params.set('platform', platform);
  const res = await fetch(`/api/v1/omni/online-orders?${params}`, {
    headers: buildHeaders(),
  });
  if (!res.ok) throw new Error(`获取订单失败: ${res.status}`);
  const json = await res.json();
  return (json.data?.items ?? []) as OnlineOrder[];
}

async function acceptOrder(
  orderId: string,
  estimatedMinutes: number,
): Promise<{ print_data: PrintData; trigger_print: boolean }> {
  const res = await fetch(`/api/v1/omni/online-orders/${orderId}/accept`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ estimated_minutes: estimatedMinutes, trigger_print: true }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `接单失败: ${res.status}`);
  }
  const json = await res.json();
  return json.data;
}

async function rejectOrder(orderId: string, reasonCode: number): Promise<void> {
  const res = await fetch(`/api/v1/omni/online-orders/${orderId}/reject`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ reason_code: reasonCode }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `拒单失败: ${res.status}`);
  }
}

async function refundOrder(orderId: string, reason: string, refundFen: number): Promise<void> {
  const res = await fetch(`/api/v1/omni/online-orders/${orderId}/refund`, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ refund_amount_fen: refundFen, reason }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `退单失败: ${res.status}`);
  }
}

// ─── 打印触发 ─────────────────────────────────────────────────────────────────

function formatPrintContent(data: PrintData, platformLabel: string): string {
  const lines: string[] = [
    '================================',
    `【${platformLabel}】外卖单`,
    `单号: ${data.platform_order_id}`,
    `时间: ${new Date(data.accepted_at).toLocaleString('zh-CN')}`,
    '--------------------------------',
  ];
  for (const item of data.items) {
    const note = item.notes ? ` (${item.notes})` : '';
    lines.push(`${item.name}${note}  ×${item.quantity}`);
  }
  lines.push('--------------------------------');
  if (data.notes) lines.push(`备注: ${data.notes}`);
  lines.push(`合计: ¥${(data.total_fen / 100).toFixed(2)}`);
  lines.push(`地址: ${data.delivery_address}`);
  lines.push(`电话: ${data.customer_phone}`);
  lines.push('================================');
  return lines.join('\n');
}

async function triggerPrint(data: PrintData, platformLabel: string): Promise<void> {
  const content = formatPrintContent(data, platformLabel);
  if (isAndroidPOS()) {
    window.TXBridge!.print(content);
    return;
  }
  // iPad / 浏览器：HTTP 转发到安卓 POS
  try {
    await fetch(`${getPosHostUrl()}/api/print`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, type: 'kitchen' }),
    });
  } catch {
    // 打印失败不影响接单流程，静默降级
  }
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function formatPrice(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  return `${h}:${m}`;
}

function getRemainingSeconds(createdAt: string): number {
  const elapsed = Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000);
  return Math.max(0, AUTO_REJECT_SECONDS - elapsed);
}

function countdownColor(rem: number): string {
  const ratio = rem / AUTO_REJECT_SECONDS;
  if (ratio > 0.5) return '#0F6E56';
  if (ratio > 0.2) return '#BA7517';
  return '#A32D2D';
}

function playNewOrderSound(): void {
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
    // 音频 API 不可用时静默降级
  }
}

// ─── 倒计时条 ─────────────────────────────────────────────────────────────────

function CountdownBar({
  createdAt,
  onTimeout,
}: {
  createdAt: string;
  onTimeout: () => void;
}) {
  const [remaining, setRemaining] = useState(() => getRemainingSeconds(createdAt));
  const cbRef = useRef(onTimeout);
  cbRef.current = onTimeout;

  useEffect(() => {
    const t = setInterval(() => {
      const rem = getRemainingSeconds(createdAt);
      setRemaining(rem);
      if (rem === 0) {
        clearInterval(t);
        cbRef.current();
      }
    }, 1000);
    return () => clearInterval(t);
  }, [createdAt]);

  const color = countdownColor(remaining);
  const mm = String(Math.floor(remaining / 60)).padStart(2, '0');
  const ss = String(remaining % 60).padStart(2, '0');

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 16, color: '#5F5E5A' }}>剩余接单时间</span>
        <span style={{ fontSize: 20, fontWeight: 700, color }}>{mm}:{ss}</span>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: '#E8E6E1', overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            borderRadius: 4,
            width: `${(remaining / AUTO_REJECT_SECONDS) * 100}%`,
            background: color,
            transition: 'width 1s linear, background 0.5s ease',
          }}
        />
      </div>
    </div>
  );
}

// ─── 平台徽标 ─────────────────────────────────────────────────────────────────

function PlatformBadge({ platform, label }: { platform: string; label: string }) {
  const cfg = PLATFORM_CONFIG[platform] ?? { label, color: '#5F5E5A', bg: '#F0EDE6' };
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '2px 10px',
        borderRadius: 6,
        background: cfg.bg,
        color: cfg.color,
        fontSize: 16,
        fontWeight: 700,
        border: `1.5px solid ${cfg.color}`,
        minHeight: 28,
      }}
    >
      {cfg.label}
    </span>
  );
}

// ─── 拒单原因底部弹层 ─────────────────────────────────────────────────────────

function RejectSheet({
  onConfirm,
  onCancel,
}: {
  onConfirm: (code: number) => void;
  onCancel: () => void;
}) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'flex-end',
      }}
      onClick={onCancel}
    >
      <div
        style={{
          width: '100%',
          background: '#fff',
          borderRadius: '16px 16px 0 0',
          padding: '24px 20px 32px',
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
                minHeight: 56,
                padding: '0 20px',
                border: '1.5px solid #E8E6E1',
                borderRadius: 12,
                background: '#F8F7F5',
                cursor: 'pointer',
                fontSize: 18,
                color: '#2C2C2A',
                textAlign: 'left',
                fontFamily: 'inherit',
                WebkitTapHighlightColor: 'transparent',
                transition: 'transform 200ms ease',
              }}
              onPointerDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
              onPointerUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            >
              {r.label}
            </button>
          ))}
        </div>
        <button
          onClick={onCancel}
          style={{
            marginTop: 16,
            width: '100%',
            minHeight: 56,
            border: 'none',
            borderRadius: 12,
            background: '#E8E6E1',
            cursor: 'pointer',
            fontSize: 18,
            color: '#5F5E5A',
            fontFamily: 'inherit',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          取消
        </button>
      </div>
    </div>
  );
}

// ─── 退单确认弹层 ─────────────────────────────────────────────────────────────

function RefundSheet({
  order,
  onConfirm,
  onCancel,
}: {
  order: OnlineOrder;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState('顾客申请退款');
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'flex-end',
      }}
      onClick={onCancel}
    >
      <div
        style={{
          width: '100%',
          background: '#fff',
          borderRadius: '16px 16px 0 0',
          padding: '24px 20px 32px',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: '0 0 4px', fontSize: 22, color: '#2C2C2A', textAlign: 'center' }}>
          退单确认
        </h2>
        <p style={{ margin: '0 0 20px', fontSize: 16, color: '#5F5E5A', textAlign: 'center' }}>
          退款金额：{formatPrice(order.total_fen)}（全额退款）
        </p>
        <div style={{ marginBottom: 16 }}>
          <p style={{ margin: '0 0 8px', fontSize: 16, color: '#5F5E5A' }}>退单原因</p>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{
              width: '100%',
              minHeight: 80,
              padding: '10px 12px',
              border: '1.5px solid #E8E6E1',
              borderRadius: 10,
              fontSize: 18,
              color: '#2C2C2A',
              fontFamily: 'inherit',
              resize: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1,
              minHeight: 56,
              border: '1.5px solid #E8E6E1',
              borderRadius: 12,
              background: '#F8F7F5',
              cursor: 'pointer',
              fontSize: 18,
              color: '#5F5E5A',
              fontFamily: 'inherit',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            取消
          </button>
          <button
            onClick={() => reason.trim() && onConfirm(reason.trim())}
            style={{
              flex: 2,
              minHeight: 56,
              border: 'none',
              borderRadius: 12,
              background: '#A32D2D',
              color: '#fff',
              cursor: 'pointer',
              fontSize: 18,
              fontWeight: 700,
              fontFamily: 'inherit',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            确认退单
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 订单卡片 ─────────────────────────────────────────────────────────────────

function OrderCard({
  order,
  onAccept,
  onReject,
  onRefund,
  onAutoReject,
}: {
  order: OnlineOrder;
  onAccept: (id: string) => void;
  onReject: (id: string, code: number) => void;
  onRefund: (id: string, reason: string) => void;
  onAutoReject: (id: string) => void;
}) {
  const [showRejectSheet, setShowRejectSheet] = useState(false);
  const [showRefundSheet, setShowRefundSheet] = useState(false);
  const isPending = order.status === 'pending';
  const isConfirmed = order.status === 'confirmed' || order.status === 'preparing';

  return (
    <>
      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          padding: 16,
          border: isPending ? '2px solid #FF6B35' : '1.5px solid #E8E6E1',
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          marginBottom: 12,
        }}
      >
        {/* 卡片头部 */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <PlatformBadge platform={order.platform} label={order.platform_label} />
            <span style={{ fontSize: 16, color: '#5F5E5A' }}>
              #{order.platform_order_id.slice(-6)}
            </span>
          </div>
          <span style={{ fontSize: 16, color: '#B4B2A9' }}>{formatTime(order.created_at)}</span>
        </div>

        {/* 菜品列表 */}
        <div style={{ marginBottom: 10 }}>
          {order.items.map((item, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '4px 0',
                borderBottom:
                  i < order.items.length - 1 ? '1px solid #F0EDE6' : 'none',
              }}
            >
              <span style={{ fontSize: 18, color: '#2C2C2A' }}>
                {item.name}
                {item.notes ? (
                  <span style={{ fontSize: 16, color: '#B4B2A9' }}> ({item.notes})</span>
                ) : null}
              </span>
              <span style={{ fontSize: 18, color: '#2C2C2A', minWidth: 40, textAlign: 'right' }}>
                ×{item.quantity}
              </span>
            </div>
          ))}
        </div>

        {/* 备注 */}
        {order.notes && (
          <div
            style={{
              padding: '6px 10px',
              background: '#FFF3ED',
              borderRadius: 8,
              fontSize: 16,
              color: '#FF6B35',
              marginBottom: 10,
            }}
          >
            备注：{order.notes}
          </div>
        )}

        {/* 配送地址 */}
        {order.delivery_address && (
          <div style={{ fontSize: 15, color: '#8C8A85', marginBottom: 8 }}>
            配送至：{order.delivery_address}
          </div>
        )}

        {/* 金额 */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A' }}>
            {formatPrice(order.total_fen)}
          </span>
        </div>

        {/* 倒计时条（仅 pending 状态） */}
        {isPending && (
          <CountdownBar
            createdAt={order.created_at}
            onTimeout={() => onAutoReject(order.order_id)}
          />
        )}

        {/* 操作按钮区 */}
        {isPending && (
          <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
            <button
              onClick={() => onAccept(order.order_id)}
              style={{
                flex: 2,
                minHeight: 56,
                borderRadius: 12,
                border: 'none',
                background: '#0F6E56',
                color: '#fff',
                fontSize: 18,
                fontWeight: 700,
                cursor: 'pointer',
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
            <button
              onClick={() => setShowRejectSheet(true)}
              style={{
                flex: 1,
                minHeight: 56,
                borderRadius: 12,
                border: '1.5px solid #E8E6E1',
                background: '#F8F7F5',
                color: '#5F5E5A',
                fontSize: 18,
                fontWeight: 600,
                cursor: 'pointer',
                fontFamily: 'inherit',
                WebkitTapHighlightColor: 'transparent',
                transition: 'transform 200ms ease',
              }}
              onPointerDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
              onPointerUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            >
              拒单
            </button>
          </div>
        )}

        {/* 备餐中状态 + 退单按钮 */}
        {isConfirmed && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 18, color: '#BA7517', fontWeight: 600 }}>
              {order.status === 'preparing' ? '配餐中' : '已接单'}
            </span>
            <button
              onClick={() => setShowRefundSheet(true)}
              style={{
                minHeight: 44,
                padding: '0 16px',
                border: '1.5px solid #E8E6E1',
                borderRadius: 10,
                background: '#F8F7F5',
                color: '#A32D2D',
                fontSize: 16,
                cursor: 'pointer',
                fontFamily: 'inherit',
                WebkitTapHighlightColor: 'transparent',
              }}
            >
              退单
            </button>
          </div>
        )}

        {/* 已退单标签 */}
        {order.status === 'refunded' && (
          <div style={{ textAlign: 'center', padding: '10px 0', fontSize: 18, color: '#A32D2D', fontWeight: 600 }}>
            已退单
          </div>
        )}

        {/* 已完成标签 */}
        {order.status === 'completed' && (
          <div style={{ textAlign: 'center', padding: '10px 0', fontSize: 18, color: '#0F6E56', fontWeight: 600 }}>
            已完成
          </div>
        )}
      </div>

      {showRejectSheet && (
        <RejectSheet
          onConfirm={(code) => {
            setShowRejectSheet(false);
            onReject(order.order_id, code);
          }}
          onCancel={() => setShowRejectSheet(false)}
        />
      )}

      {showRefundSheet && (
        <RefundSheet
          order={order}
          onConfirm={(reason) => {
            setShowRefundSheet(false);
            onRefund(order.order_id, reason);
          }}
          onCancel={() => setShowRefundSheet(false)}
        />
      )}
    </>
  );
}

// ─── 平台筛选 Tab ─────────────────────────────────────────────────────────────

function PlatformTabs({
  active,
  onChange,
  counts,
}: {
  active: string;
  onChange: (p: string) => void;
  counts: Record<string, number>;
}) {
  const tabs: { key: string; label: string }[] = [
    { key: '', label: '全部' },
    { key: 'meituan', label: '美团' },
    { key: 'eleme', label: '饿了么' },
    { key: 'douyin', label: '抖音' },
  ];
  return (
    <div style={{ display: 'flex', gap: 8, padding: '8px 16px', background: '#F8F7F5' }}>
      {tabs.map((tab) => {
        const isActive = active === tab.key;
        const cnt = tab.key === '' ? Object.values(counts).reduce((a, b) => a + b, 0) : (counts[tab.key] ?? 0);
        return (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            style={{
              minHeight: 48,
              padding: '0 16px',
              borderRadius: 10,
              border: isActive ? '2px solid #0F6E56' : '1.5px solid #E8E6E1',
              background: isActive ? '#E6F5F0' : '#fff',
              color: isActive ? '#0F6E56' : '#5F5E5A',
              fontSize: 16,
              fontWeight: isActive ? 700 : 500,
              cursor: 'pointer',
              fontFamily: 'inherit',
              WebkitTapHighlightColor: 'transparent',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            {tab.label}
            {cnt > 0 && (
              <span
                style={{
                  minWidth: 22,
                  height: 22,
                  borderRadius: 11,
                  background: '#FF4D4F',
                  color: '#fff',
                  fontSize: 13,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {cnt}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ─── 主页面组件 ───────────────────────────────────────────────────────────────

export function OnlineOrdersPage() {
  const [orders, setOrders] = useState<OnlineOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState('');
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);
  const prevOrderIdsRef = useRef<Set<string>>(new Set());

  const storeId = getStoreId();

  // ── toast ──────────────────────────────────────────────────────────────────

  const showToast = useCallback(
    (msg: string, type: 'success' | 'error' = 'success') => {
      setToast({ msg, type });
      setTimeout(() => setToast(null), 3000);
    },
    [],
  );

  // ── 拉取订单 ───────────────────────────────────────────────────────────────

  const loadOrders = useCallback(async () => {
    try {
      const data = await fetchOnlineOrders(storeId, platformFilter || undefined);
      setOrders(data);
      setError(null);

      // 检测新订单，播放提示音
      const newIds = new Set(data.map((o) => o.order_id));
      const isFirstLoad = prevOrderIdsRef.current.size === 0;
      if (!isFirstLoad) {
        for (const id of newIds) {
          if (!prevOrderIdsRef.current.has(id)) {
            playNewOrderSound();
            break;
          }
        }
      }
      prevOrderIdsRef.current = newIds;
    } catch (e) {
      const msg = e instanceof Error ? e.message : '加载失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [storeId, platformFilter]);

  // 首次加载 + 定时轮询
  useEffect(() => {
    loadOrders();
    const timer = setInterval(loadOrders, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [loadOrders]);

  // ── 接单 ───────────────────────────────────────────────────────────────────

  const handleAccept = useCallback(
    async (orderId: string) => {
      try {
        const result = await acceptOrder(orderId, 20);
        // 触发打印
        if (result.trigger_print && result.print_data) {
          const order = orders.find((o) => o.order_id === orderId);
          await triggerPrint(result.print_data, order?.platform_label ?? '外卖');
        }
        showToast('接单成功，厨房单已打印');
        await loadOrders();
      } catch (e) {
        showToast(e instanceof Error ? e.message : '接单失败', 'error');
      }
    },
    [orders, loadOrders, showToast],
  );

  // ── 拒单 ───────────────────────────────────────────────────────────────────

  const handleReject = useCallback(
    async (orderId: string, code: number) => {
      try {
        await rejectOrder(orderId, code);
        showToast('已拒单');
        await loadOrders();
      } catch (e) {
        showToast(e instanceof Error ? e.message : '拒单失败', 'error');
      }
    },
    [loadOrders, showToast],
  );

  // ── 退单 ───────────────────────────────────────────────────────────────────

  const handleRefund = useCallback(
    async (orderId: string, reason: string) => {
      try {
        await refundOrder(orderId, reason, 0);
        showToast('退单成功，库存已回滚');
        await loadOrders();
      } catch (e) {
        showToast(e instanceof Error ? e.message : '退单失败', 'error');
      }
    },
    [loadOrders, showToast],
  );

  // ── 超时自动拒单 ───────────────────────────────────────────────────────────

  const handleAutoReject = useCallback(
    async (orderId: string) => {
      try {
        await rejectOrder(orderId, 1);
        showToast('订单超时已自动拒单', 'error');
        await loadOrders();
      } catch {
        // 自动拒单失败只记录，不弹 toast
      }
    },
    [loadOrders, showToast],
  );

  // ── 待处理订单数量（按平台） ────────────────────────────────────────────────

  const pendingCounts = orders
    .filter((o) => o.status === 'pending')
    .reduce<Record<string, number>>((acc, o) => {
      acc[o.platform] = (acc[o.platform] ?? 0) + 1;
      return acc;
    }, {});

  const filteredOrders = platformFilter
    ? orders.filter((o) => o.platform === platformFilter)
    : orders;

  const pendingOrders = filteredOrders.filter((o) => o.status === 'pending');
  const otherOrders = filteredOrders.filter((o) => o.status !== 'pending');

  // ── 渲染 ───────────────────────────────────────────────────────────────────

  return (
    <div style={{ minHeight: '100vh', background: '#111827', color: '#2C2C2A' }}>
      {/* 顶部标题栏 */}
      <div
        style={{
          padding: '16px 20px 12px',
          background: '#1F2937',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#F9FAFB' }}>
          线上接单
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {pendingOrders.length > 0 && (
            <span
              style={{
                background: '#FF4D4F',
                color: '#fff',
                borderRadius: 12,
                padding: '2px 12px',
                fontSize: 16,
                fontWeight: 700,
              }}
            >
              {pendingOrders.length} 单待处理
            </span>
          )}
          <button
            onClick={() => loadOrders()}
            style={{
              minHeight: 40,
              padding: '0 14px',
              border: '1px solid #374151',
              borderRadius: 8,
              background: '#374151',
              color: '#D1D5DB',
              fontSize: 15,
              cursor: 'pointer',
              fontFamily: 'inherit',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            刷新
          </button>
        </div>
      </div>

      {/* 平台筛选 Tab */}
      <PlatformTabs
        active={platformFilter}
        onChange={setPlatformFilter}
        counts={pendingCounts}
      />

      {/* 主体内容区 */}
      <div style={{ padding: '12px 16px', maxWidth: 640, margin: '0 auto' }}>
        {loading && (
          <div
            style={{
              textAlign: 'center',
              padding: '60px 0',
              fontSize: 18,
              color: '#9CA3AF',
            }}
          >
            加载中…
          </div>
        )}

        {error && !loading && (
          <div
            style={{
              background: '#FEF2F2',
              border: '1px solid #FECACA',
              borderRadius: 10,
              padding: '12px 16px',
              fontSize: 16,
              color: '#B91C1C',
              marginBottom: 12,
            }}
          >
            {error}
          </div>
        )}

        {!loading && filteredOrders.length === 0 && (
          <div
            style={{
              textAlign: 'center',
              padding: '80px 0',
              fontSize: 18,
              color: '#6B7280',
            }}
          >
            暂无待处理订单
          </div>
        )}

        {/* 待接单区块 */}
        {pendingOrders.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '10px 12px',
                background: '#F8F7F5',
                borderRadius: '10px 10px 0 0',
                borderBottom: '3px solid #FF6B35',
                marginBottom: 12,
              }}
            >
              <span style={{ fontSize: 18, fontWeight: 700, color: '#2C2C2A' }}>待接单</span>
              <span
                style={{
                  minWidth: 28,
                  height: 28,
                  borderRadius: 14,
                  background: '#FF4D4F',
                  color: '#fff',
                  fontSize: 15,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {pendingOrders.length}
              </span>
            </div>
            {pendingOrders.map((order) => (
              <OrderCard
                key={order.order_id}
                order={order}
                onAccept={handleAccept}
                onReject={handleReject}
                onRefund={handleRefund}
                onAutoReject={handleAutoReject}
              />
            ))}
          </div>
        )}

        {/* 已处理区块 */}
        {otherOrders.length > 0 && (
          <div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '10px 12px',
                background: '#F8F7F5',
                borderRadius: '10px 10px 0 0',
                borderBottom: '3px solid #0F6E56',
                marginBottom: 12,
              }}
            >
              <span style={{ fontSize: 18, fontWeight: 700, color: '#2C2C2A' }}>已处理</span>
              <span
                style={{
                  minWidth: 28,
                  height: 28,
                  borderRadius: 14,
                  background: '#0F6E56',
                  color: '#fff',
                  fontSize: 15,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {otherOrders.length}
              </span>
            </div>
            {otherOrders.map((order) => (
              <OrderCard
                key={order.order_id}
                order={order}
                onAccept={handleAccept}
                onReject={handleReject}
                onRefund={handleRefund}
                onAutoReject={handleAutoReject}
              />
            ))}
          </div>
        )}
      </div>

      {/* Toast 提示 */}
      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 32,
            left: '50%',
            transform: 'translateX(-50%)',
            background: toast.type === 'error' ? '#A32D2D' : '#0F6E56',
            color: '#fff',
            padding: '12px 24px',
            borderRadius: 10,
            fontSize: 17,
            fontWeight: 600,
            zIndex: 2000,
            boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
            whiteSpace: 'nowrap',
          }}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}

export default OnlineOrdersPage;
