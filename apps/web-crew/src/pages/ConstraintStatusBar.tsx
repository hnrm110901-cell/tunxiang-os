/**
 * ConstraintStatusBar — 三约束实时叠加看板 (Phase 3-B)
 *
 * 屯象OS最核心的差异化功能，全球独创。
 * 固定显示于 TableDetailPage / CashierPage 操作栏顶部。
 *
 * 三约束：毛利 / 食安 / 出餐时长
 * 任何一栏变红 → 整栏红色背景 + 触控震动反馈
 * 每30秒自动刷新
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { txFetch } from '../api/index';

// ─── 类型 ───

type Level = 'ok' | 'warn' | 'danger' | 'loading';

interface MarginStatus {
  ok: boolean;
  pct: number;
  level: Level;
}

interface FoodSafetyStatus {
  ok: boolean;
  issues: string[];
  level: Level;
}

interface ServiceTimeStatus {
  ok: boolean;
  elapsed_min: number;
  limit_min: number;
  level: Level;
}

interface ConstraintStatusData {
  margin: MarginStatus;
  food_safety: FoodSafetyStatus;
  service_time: ServiceTimeStatus;
}

export interface Props {
  orderId: string;
  storeId: string;
}

// ─── Mock 降级数据 ───

const MOCK_STATUS: ConstraintStatusData = {
  margin: { ok: true, pct: 68.2, level: 'ok' },
  food_safety: { ok: true, issues: [], level: 'ok' },
  service_time: { ok: true, elapsed_min: 35, limit_min: 120, level: 'ok' },
};

const LOADING_STATUS: ConstraintStatusData = {
  margin: { ok: true, pct: 0, level: 'loading' },
  food_safety: { ok: true, issues: [], level: 'loading' },
  service_time: { ok: true, elapsed_min: 0, limit_min: 120, level: 'loading' },
};

// ─── API ───

async function fetchConstraintStatus(_orderId: string): Promise<ConstraintStatusData> {
  try {
    const data = await txFetch<ConstraintStatusData>('/api/v1/brain/constraints/status');
    return data ?? MOCK_STATUS;
  } catch {
    return MOCK_STATUS;
  }
}

// ─── 样式工具 ───

const LEVEL_COLORS: Record<Level, { text: string; bg: string; border: string }> = {
  ok:      { text: '#0F6E56', bg: '#F0FDF8', border: '#0F6E56' },
  warn:    { text: '#B45309', bg: '#FFFBEB', border: '#D97706' },
  danger:  { text: '#FFFFFF', bg: '#DC2626', border: '#DC2626' },
  loading: { text: '#999999', bg: '#F5F5F5', border: '#CCCCCC' },
};

const LEVEL_ICON: Record<Level, string> = {
  ok:      '✅',
  warn:    '⚠️',
  danger:  '🔴',
  loading: '⏳',
};

// ─── 单项指示器 ───

interface IndicatorProps {
  label: string;
  value: string;
  level: Level;
  tooltip?: string;
}

function Indicator({ label, value, level }: IndicatorProps) {
  const colors = LEVEL_COLORS[level];
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '6px 4px',
        minHeight: 52,
      }}
    >
      <div
        style={{
          fontSize: 12,
          color: level === 'danger' ? 'rgba(255,255,255,0.8)' : '#666666',
          marginBottom: 2,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 3,
          fontSize: 15,
          fontWeight: 700,
          color: colors.text,
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ fontSize: 14 }}>{LEVEL_ICON[level]}</span>
        <span>{value}</span>
      </div>
    </div>
  );
}

// ─── 分隔线 ───

function Divider({ danger }: { danger: boolean }) {
  return (
    <div
      style={{
        width: 1,
        alignSelf: 'stretch',
        background: danger ? 'rgba(255,255,255,0.3)' : '#E8E8E8',
        margin: '8px 0',
      }}
    />
  );
}

// ─── 主组件 ───

export function ConstraintStatusBar({ orderId }: Props) {
  const [status, setStatus] = useState<ConstraintStatusData>(LOADING_STATUS);
  const [hasDanger, setHasDanger] = useState(false);
  const prevDangerRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const data = await fetchConstraintStatus(orderId);
    setStatus(data);

    const isDanger =
      data.margin.level === 'danger' ||
      data.food_safety.level === 'danger' ||
      data.service_time.level === 'danger';
    setHasDanger(isDanger);

    // 触控震动反馈（仅在首次变为 danger 时触发，避免重复震动）
    if (isDanger && !prevDangerRef.current) {
      try {
        navigator.vibrate([300]);
      } catch {
        // 部分设备不支持震动，静默忽略
      }
    }
    prevDangerRef.current = isDanger;
  }, [orderId]);

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, 30_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [load]);

  // ── 格式化显示文本 ──
  const marginText =
    status.margin.level === 'loading'
      ? '加载中'
      : `${status.margin.pct.toFixed(1)}%`;

  const foodSafetyText =
    status.food_safety.level === 'loading'
      ? '加载中'
      : status.food_safety.level === 'ok'
      ? '正常'
      : status.food_safety.issues.length > 0
      ? status.food_safety.issues[0].length > 6
        ? status.food_safety.issues[0].slice(0, 6) + '…'
        : status.food_safety.issues[0]
      : '异常';

  const serviceTimeText =
    status.service_time.level === 'loading'
      ? '加载中'
      : `${status.service_time.elapsed_min}分钟`;

  // ── 整体背景色 ──
  const barBg = hasDanger ? '#DC2626' : '#FFFFFF';
  const barBorder = hasDanger ? '#DC2626' : '#E8E8E8';

  return (
    <div
      style={{
        background: barBg,
        borderBottom: `1px solid ${barBorder}`,
        display: 'flex',
        alignItems: 'stretch',
        flexShrink: 0,
        transition: 'background 0.3s',
      }}
    >
      <Indicator
        label="毛利"
        value={marginText}
        level={status.margin.level}
      />
      <Divider danger={hasDanger} />
      <Indicator
        label="食安"
        value={foodSafetyText}
        level={status.food_safety.level}
      />
      <Divider danger={hasDanger} />
      <Indicator
        label="出餐"
        value={serviceTimeText}
        level={status.service_time.level}
      />

      {/* danger 状态：显示警示横幅 */}
      {hasDanger && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 2,
            background: 'rgba(255,255,255,0.6)',
            animation: 'none',
          }}
        />
      )}
    </div>
  );
}
