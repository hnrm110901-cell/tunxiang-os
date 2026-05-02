/**
 * ConnectionHealth — Sprint C2+ 连接健康详情面板
 *
 * 底栏浮动指示器（绿/黄/红圆点），悬停展开详情面板显示：
 *   - 连接状态（online / degraded / offline）
 *   - latency（最近 ping/pong 延迟）
 *   - uptime（本次在线连续时长）
 *   - 本地缓存订单数
 *   - 手动重连按钮
 *
 * 使用 useConnection() 读取 ConnectionContext 广播的信号。
 * 不使用 Tailwind — 遵循项目中现有组件风格（内联 style）。
 */
import { useState } from 'react';
import { useConnection } from '../contexts/ConnectionContext';

// ─── 样式常量 ─────────────────────────────────────────────────────────────

type HealthStyle = { dot: string; bg: string; label: string };

const HEALTH_STYLE: Record<string, HealthStyle> = {
  online: {
    dot: '#22C55E',    // green-500
    bg: 'rgba(34,197,94,0.15)',
    label: '在线',
  },
  degraded: {
    dot: '#FACC15',    // yellow-400
    bg: 'rgba(250,204,21,0.15)',
    label: '不稳定',
  },
  offline: {
    dot: '#EF4444',    // red-500
    bg: 'rgba(239,68,68,0.15)',
    label: '离线',
  },
};

function formatDuration(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}时${m}分${s}秒`;
  if (m > 0) return `${m}分${s}秒`;
  return `${s}秒`;
}

function formatLatency(ms: number): string {
  if (ms < 0) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ─── 组件 ──────────────────────────────────────────────────────────────────

export function ConnectionHealth() {
  const { status, isDegraded, latency, uptime, cachedOrders, reconnect, offlineDurationMs } =
    useConnection();
  const [expanded, setExpanded] = useState(false);

  const style = HEALTH_STYLE[status] ?? HEALTH_STYLE.offline;
  const dotAnimation = status === 'online' ? undefined : 'kds-pulse 1.2s infinite';

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 12,
        right: 12,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: 6,
      }}
    >
      {/* ─── 浮动指示器（底部圆点按钮） ─── */}
      <button
        type="button"
        onClick={() => setExpanded((x) => !x)}
        data-testid="connection-health-indicator"
        aria-label={`连接状态: ${style.label}`}
        title={`连接${style.label}`}
        style={{
          width: 36,
          height: 36,
          borderRadius: '50%',
          border: `2px solid ${style.dot}`,
          background: style.bg,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
          transition: 'transform 0.15s',
        }}
      >
        <span
          style={{
            width: 14,
            height: 14,
            borderRadius: '50%',
            backgroundColor: style.dot,
            animation: dotAnimation ?? undefined,
          }}
        />
      </button>

      {/* ─── 详情面板（展开时） ─── */}
      {expanded && (
        <div
          data-testid="connection-health-panel"
          style={{
            background: '#1F2937',
            border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: 10,
            padding: '12px 16px',
            minWidth: 220,
            color: '#F0F0F0',
            fontSize: 13,
            lineHeight: 1.6,
            boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
          }}
        >
          {/* 状态行 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: style.dot,
                animation: dotAnimation ?? undefined,
              }}
            />
            <span style={{ fontWeight: 700 }}>连接{style.label}</span>
            {isDegraded && (
              <span
                style={{
                  fontSize: 11,
                  color: '#FACC15',
                  background: 'rgba(250,204,21,0.15)',
                  padding: '1px 6px',
                  borderRadius: 4,
                }}
              >
                降级
              </span>
            )}
          </div>

          {/* 指标列表 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 12px', fontSize: 12 }}>
            <span style={{ color: 'rgba(255,255,255,0.5)' }}>延迟</span>
            <span style={{ fontVariantNumeric: 'tabular-nums', color: latency > 200 ? '#FBBF24' : undefined }}>
              {formatLatency(latency)}
            </span>

            <span style={{ color: 'rgba(255,255,255,0.5)' }}>在线时长</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>
              {status === 'offline' ? '-' : formatDuration(uptime)}
            </span>

            {status === 'offline' && (
              <>
                <span style={{ color: 'rgba(255,255,255,0.5)' }}>断线时长</span>
                <span style={{ fontVariantNumeric: 'tabular-nums', color: '#F87171' }}>
                  {formatDuration(offlineDurationMs)}
                </span>
              </>
            )}

            <span style={{ color: 'rgba(255,255,255,0.5)' }}>本地缓存</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>
              {cachedOrders} 单
            </span>
          </div>

          {/* 操作按钮 */}
          <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
            <button
              type="button"
              onClick={() => {
                reconnect();
                setExpanded(false);
              }}
              data-testid="connection-health-reconnect"
              style={{
                flex: 1,
                padding: '4px 8px',
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.2)',
                background: 'rgba(255,255,255,0.08)',
                color: '#F0F0F0',
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              重新连接
            </button>
            <button
              type="button"
              onClick={() => setExpanded(false)}
              style={{
                padding: '4px 8px',
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.1)',
                background: 'transparent',
                color: 'rgba(255,255,255,0.5)',
                fontSize: 12,
                cursor: 'pointer',
              }}
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
