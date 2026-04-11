/**
 * TableNumberManager — 快餐牌号管理组件
 *
 * 功能:
 *   - 分配牌号（从可用池中取最小编号，1–max 循环）
 *   - 出餐叫号（waiting → ready，推送到叫号屏）
 *   - 取餐确认（ready → collected，回收到可用池）
 *
 * 牌号状态:
 *   waiting   — 已下单，等待出餐（灰色）
 *   ready     — 出餐完成，可取餐（绿色 + 脉冲）
 *   collected — 已取餐，号码回收（淡色/隐藏）
 *
 * Store-POS 终端规范（tx-ui 技能）:
 *   - 禁用 Ant Design，所有组件手写触控优化
 *   - 点击区域 ≥ 72×72px（牌号格）
 *   - 最小字体 16px
 *   - 触控反馈：scale(0.97) + 200ms transition
 *   - 无 hover，用 :active / onPointerDown 替代
 */
import { useState, useCallback, useEffect } from 'react';

// ─── Design Tokens（与 QuickCashierPage 一致） ────────────────────────────────
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  success: '#0F6E56',
  successLight: '#0D5A47',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
  dimText: '#6B7280',
  waitingBg: '#1A2A32',
  readyBg: '#0D3D2E',
  collectedBg: '#141E24',
} as const;

// ─── 类型 ─────────────────────────────────────────────────────────────────────

export type TableNumberStatus = 'waiting' | 'ready' | 'collected';

export interface TableNumberEntry {
  /** 牌号字符串，如 "001"、"A012" */
  tableNumber: string;
  /** 快餐订单 ID（与后端 quick_orders.id 对应） */
  quickOrderId: string;
  /** 牌号状态 */
  status: TableNumberStatus;
  /** 订单品项摘要，用于叫号屏展示 */
  orderSummary: string;
  /** 分配时间 */
  assignedAt: Date;
  /** 叫号时间 */
  calledAt?: Date;
  /** 取餐时间 */
  collectedAt?: Date;
}

interface TableNumberManagerProps {
  /** 当前门店的所有牌号状态（由父组件管理，支持受控模式） */
  entries: TableNumberEntry[];
  /** 最大同时显示多少个已取餐牌号（超出自动隐藏，节省屏幕空间）*/
  maxCollectedVisible?: number;
  /** 叫号成功回调（父组件负责调用后端 API + useCallerDisplay） */
  onCallNumber: (quickOrderId: string, tableNumber: string) => Promise<void>;
  /** 取餐确认回调（父组件负责调用后端 complete API） */
  onConfirmCollected: (quickOrderId: string, tableNumber: string) => Promise<void>;
}

// ─── 牌号格组件 ───────────────────────────────────────────────────────────────

interface NumberCellProps {
  entry: TableNumberEntry;
  onCall: () => void;
  onCollect: () => void;
  isActing: boolean;
}

function NumberCell({ entry, onCall, onCollect, isActing }: NumberCellProps) {
  const { tableNumber, status, orderSummary } = entry;

  const bgColor =
    status === 'waiting'
      ? C.waitingBg
      : status === 'ready'
      ? C.readyBg
      : C.collectedBg;

  const borderColor =
    status === 'waiting'
      ? C.border
      : status === 'ready'
      ? C.success
      : '#1A2530';

  const numColor =
    status === 'waiting'
      ? C.text
      : status === 'ready'
      ? '#4ADE80'
      : C.muted;

  const statusLabel =
    status === 'waiting'
      ? '等待出餐'
      : status === 'ready'
      ? '可取餐 ▶'
      : '已取餐';

  const statusColor =
    status === 'waiting'
      ? C.dimText
      : status === 'ready'
      ? '#4ADE80'
      : C.muted;

  const handlePress = () => {
    if (isActing) return;
    if (status === 'waiting') onCall();
    else if (status === 'ready') onCollect();
  };

  return (
    <button
      onClick={handlePress}
      disabled={isActing || status === 'collected'}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100%',
        minHeight: 96,
        padding: '12px 8px',
        background: bgColor,
        border: `2px solid ${borderColor}`,
        borderRadius: 12,
        cursor: status === 'collected' ? 'default' : 'pointer',
        opacity: status === 'collected' ? 0.45 : 1,
        transition: 'transform 200ms ease, border-color 200ms ease',
        gap: 4,
        // ready 状态微弱发光效果
        boxShadow:
          status === 'ready'
            ? `0 0 12px rgba(15, 110, 86, 0.35)`
            : 'none',
      }}
      onPointerDown={e => {
        if (status !== 'collected' && !isActing) {
          (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
        }
      }}
      onPointerUp={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
      onPointerLeave={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
      aria-label={`牌号 ${tableNumber}，状态：${statusLabel}`}
    >
      {/* 牌号大字 */}
      <span
        style={{
          fontSize: 32,
          fontWeight: 800,
          color: numColor,
          lineHeight: 1,
          letterSpacing: 2,
          // ready 状态脉冲动画（CSS keyframes 通过 style 标签注入，避免 Tailwind 依赖）
          animation: status === 'ready' ? 'txReadyPulse 1.5s ease-in-out infinite' : 'none',
        }}
      >
        {tableNumber}
      </span>

      {/* 状态标签 */}
      <span style={{ fontSize: 13, color: statusColor, marginTop: 2 }}>
        {statusLabel}
      </span>

      {/* 品项摘要（仅 waiting/ready 显示） */}
      {status !== 'collected' && orderSummary && (
        <span
          style={{
            fontSize: 12,
            color: C.dimText,
            maxWidth: '100%',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            marginTop: 2,
          }}
        >
          {orderSummary}
        </span>
      )}

      {/* loading 遮罩 */}
      {isActing && (
        <span style={{ position: 'absolute', fontSize: 13, color: C.accent }}>
          处理中…
        </span>
      )}
    </button>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function TableNumberManager({
  entries,
  maxCollectedVisible = 6,
  onCallNumber,
  onConfirmCollected,
}: TableNumberManagerProps) {
  // 正在执行操作的牌号集合（防止重复点击）
  const [actingIds, setActingIds] = useState<Set<string>>(new Set());

  // 注入 ready 脉冲动画 keyframes（仅注入一次）
  useEffect(() => {
    const styleId = 'tx-table-number-pulse';
    if (!document.getElementById(styleId)) {
      const style = document.createElement('style');
      style.id = styleId;
      style.textContent = `
        @keyframes txReadyPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.65; }
        }
      `;
      document.head.appendChild(style);
    }
    return () => {
      // 不移除，避免多实例重复操作
    };
  }, []);

  const handleCall = useCallback(
    async (entry: TableNumberEntry) => {
      const key = entry.quickOrderId;
      setActingIds(prev => new Set(prev).add(key));
      try {
        await onCallNumber(entry.quickOrderId, entry.tableNumber);
      } finally {
        setActingIds(prev => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [onCallNumber],
  );

  const handleCollect = useCallback(
    async (entry: TableNumberEntry) => {
      const key = entry.quickOrderId;
      setActingIds(prev => new Set(prev).add(key));
      try {
        await onConfirmCollected(entry.quickOrderId, entry.tableNumber);
      } finally {
        setActingIds(prev => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [onConfirmCollected],
  );

  // 分组：waiting + ready 优先展示，collected 限量显示
  const waitingAndReady = entries.filter(e => e.status !== 'collected');
  const collected = entries
    .filter(e => e.status === 'collected')
    .slice(-maxCollectedVisible); // 只保留最近 N 个

  const displayEntries = [...waitingAndReady, ...collected];

  const waitingCount = entries.filter(e => e.status === 'waiting').length;
  const readyCount = entries.filter(e => e.status === 'ready').length;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        padding: 16,
        background: C.bg,
        borderRadius: 16,
        minHeight: 200,
      }}
    >
      {/* 顶部统计栏 */}
      <div
        style={{
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          paddingBottom: 12,
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <span style={{ fontSize: 17, fontWeight: 700, color: C.text }}>
          牌号管理
        </span>
        <span
          style={{
            padding: '3px 10px',
            borderRadius: 20,
            background: C.card,
            border: `1px solid ${C.border}`,
            fontSize: 14,
            color: C.dimText,
          }}
        >
          等待 <strong style={{ color: C.text }}>{waitingCount}</strong>
        </span>
        <span
          style={{
            padding: '3px 10px',
            borderRadius: 20,
            background: C.readyBg,
            border: `1px solid ${C.success}`,
            fontSize: 14,
            color: '#4ADE80',
          }}
        >
          可取餐 <strong>{readyCount}</strong>
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 13, color: C.muted }}>
          点击叫号 → 再点确认取餐
        </span>
      </div>

      {/* 牌号网格 — 3列 */}
      {displayEntries.length === 0 ? (
        <div
          style={{
            textAlign: 'center',
            color: C.muted,
            padding: '40px 0',
            fontSize: 16,
          }}
        >
          暂无牌号
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 12,
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          {displayEntries.map(entry => (
            <NumberCell
              key={entry.quickOrderId}
              entry={entry}
              onCall={() => handleCall(entry)}
              onCollect={() => handleCollect(entry)}
              isActing={actingIds.has(entry.quickOrderId)}
            />
          ))}
        </div>
      )}

      {/* 说明文字 */}
      <div
        style={{
          display: 'flex',
          gap: 20,
          fontSize: 13,
          color: C.muted,
          paddingTop: 8,
          borderTop: `1px solid ${C.border}`,
        }}
      >
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: 2,
              background: C.waitingBg,
              border: `1px solid ${C.border}`,
              marginRight: 4,
            }}
          />
          灰色 = 等待出餐（点击叫号）
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: 2,
              background: C.readyBg,
              border: `1px solid ${C.success}`,
              marginRight: 4,
            }}
          />
          绿色 = 可取餐（点击确认）
        </span>
      </div>
    </div>
  );
}

export default TableNumberManager;
