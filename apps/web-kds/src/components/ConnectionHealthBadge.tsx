/**
 * ConnectionHealthBadge — Sprint C2
 *
 * 右上角浮动徽章，反映 /kds/orders/delta 轮询的连接健康。
 * 状态来源：useKdsHealthStore (Zustand)。
 *
 * 状态机（每秒 tick 重算）：
 *   - synced       上次成功 < 10s 且 !inFlight                  → 绿
 *   - syncing      inFlight === true                            → 蓝
 *   - stale        10s ≤ since < 60s 且 failureStreak < 3        → 黄
 *   - disconnected since ≥ 60s 或 failureStreak ≥ 3              → 红
 *
 * 内容：
 *   - 状态文字（中文）
 *   - 上次成功时间（"x秒前" / "x分钟前"，从未成功显示 "—"）
 *   - 手动刷新按钮（onRefresh 由调用方提供）
 *
 * 不使用 Tailwind — 项目尚未引入。颜色用内联 style 表达，同时 className
 * 暴露为 data-status 便于 vitest 断言。
 */
import { useEffect, useState } from 'react';
import { useKdsHealthStore } from '../store/useKdsHealthStore';

export type ConnectionBadgeStatus =
  | 'synced'
  | 'syncing'
  | 'stale'
  | 'disconnected';

const STALE_AFTER_MS = 10_000;
const DISCONNECTED_AFTER_MS = 60_000;
const DISCONNECTED_FAILURE_STREAK = 3;

interface ConnectionHealthBadgeProps {
  /** 手动刷新回调；点击按钮时触发，由调用方实际去 fire 一次 poll */
  onRefresh?: () => void;
  /** 仅测试用：注入"当前时间"，便于 jsdom 下断言"x秒前" */
  nowProvider?: () => number;
  /** 仅测试用：覆盖默认 store hook */
  useStore?: typeof useKdsHealthStore;
}

interface DerivedState {
  status: ConnectionBadgeStatus;
  lastSuccessAgoSec: number | null;
}

function derive(
  now: number,
  lastSuccessAt: number,
  inFlight: boolean,
  failureStreak: number,
): DerivedState {
  const lastSuccessAgo = lastSuccessAt > 0 ? now - lastSuccessAt : Infinity;

  let status: ConnectionBadgeStatus;
  if (inFlight) {
    status = 'syncing';
  } else if (
    lastSuccessAgo > DISCONNECTED_AFTER_MS ||
    failureStreak >= DISCONNECTED_FAILURE_STREAK
  ) {
    status = 'disconnected';
  } else if (lastSuccessAgo >= STALE_AFTER_MS) {
    status = 'stale';
  } else {
    status = 'synced';
  }

  return {
    status,
    lastSuccessAgoSec:
      lastSuccessAt > 0 ? Math.max(0, Math.floor(lastSuccessAgo / 1000)) : null,
  };
}

function formatAgo(sec: number | null): string {
  if (sec === null) return '—';
  if (sec < 60) return `${sec}秒前`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}分钟前`;
  const h = Math.floor(m / 60);
  return `${h}小时前`;
}

const STATUS_META: Record<
  ConnectionBadgeStatus,
  { label: string; color: string; bg: string; border: string }
> = {
  synced: {
    label: '已同步',
    color: '#FFFFFF',
    bg: '#15803D', // green-700
    border: '#22C55E',
  },
  syncing: {
    label: '同步中',
    color: '#FFFFFF',
    bg: '#1D4ED8', // blue-700
    border: '#3B82F6',
  },
  stale: {
    label: '同步滞后',
    color: '#1F1F00',
    bg: '#FACC15', // yellow-400
    border: '#CA8A04',
  },
  disconnected: {
    label: '已断线',
    color: '#FFFFFF',
    bg: '#B91C1C', // red-700
    border: '#EF4444',
  },
};

export function ConnectionHealthBadge(props: ConnectionHealthBadgeProps = {}) {
  const { onRefresh, nowProvider, useStore } = props;
  const storeHook = useStore ?? useKdsHealthStore;
  const lastSuccessAt = storeHook((s) => s.lastSuccessAt);
  const inFlight = storeHook((s) => s.inFlight);
  const failureStreak = storeHook((s) => s.failureStreak);

  // 每秒 tick，使"x秒前"和过期阈值都活起来
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  // 引用 tick 让 lint 不报 unused，同时强制重渲
  void tick;

  const now = (nowProvider ?? Date.now)();
  const { status, lastSuccessAgoSec } = derive(
    now,
    lastSuccessAt,
    inFlight,
    failureStreak,
  );
  const meta = STATUS_META[status];

  return (
    <div
      data-testid="connection-health-badge"
      data-status={status}
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        top: 12,
        right: 12,
        zIndex: 10000,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 999,
        background: meta.bg,
        color: meta.color,
        border: `1px solid ${meta.border}`,
        fontSize: 13,
        fontWeight: 600,
        letterSpacing: 0.4,
        boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
        userSelect: 'none',
      }}
    >
      {/* 状态点 */}
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: meta.color,
          opacity: status === 'syncing' ? 0.7 : 1,
          animation:
            status === 'syncing' || status === 'disconnected'
              ? 'kds-pulse 1.2s infinite'
              : undefined,
        }}
      />
      <span data-testid="connection-health-badge-label">{meta.label}</span>
      <span
        data-testid="connection-health-badge-ago"
        style={{ opacity: 0.85, fontWeight: 400, fontVariantNumeric: 'tabular-nums' }}
      >
        {formatAgo(lastSuccessAgoSec)}
      </span>
      <button
        type="button"
        onClick={onRefresh}
        data-testid="connection-health-badge-refresh"
        aria-label="手动刷新"
        disabled={status === 'syncing'}
        style={{
          marginLeft: 4,
          padding: '2px 8px',
          minHeight: 24,
          borderRadius: 6,
          border: `1px solid ${meta.color}`,
          background: 'transparent',
          color: meta.color,
          fontSize: 12,
          fontWeight: 600,
          cursor: status === 'syncing' ? 'not-allowed' : 'pointer',
          opacity: status === 'syncing' ? 0.6 : 1,
        }}
      >
        刷新
      </button>
    </div>
  );
}
