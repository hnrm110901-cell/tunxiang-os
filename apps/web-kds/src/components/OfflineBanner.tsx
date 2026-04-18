/**
 * OfflineBanner — KDS 顶栏连接健康提示（Sprint C2）
 *
 * 三态：
 *   online    → 不渲染（return null）
 *   degraded  → 黄色横条 "连接不稳定"
 *   offline   → 橙色横条 "离线只读 · 已断线 MM:SS"
 *
 * 粘性定位（sticky top-0），点击不可关闭。
 *
 * 不使用项目中尚未引入的 Tailwind — 通过内联 class 标识颜色以便单元测试断言，
 * 同时回退使用 inline style 完整渲染。
 */
import type { ConnectionHealth } from '../hooks/useConnectionHealth';

interface OfflineBannerProps {
  health: ConnectionHealth;
  offlineDurationMs: number;
}

function formatDuration(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function OfflineBanner({ health, offlineDurationMs }: OfflineBannerProps) {
  if (health === 'online') return null;

  const isOffline = health === 'offline';
  const bg = isOffline ? '#F97316' /* orange-500 */ : '#F59E0B' /* yellow-500 */;
  const className = isOffline ? 'tx-kds-banner-orange' : 'tx-kds-banner-yellow';

  const text = isOffline
    ? `离线只读 · 已断线 ${formatDuration(offlineDurationMs)}`
    : '连接不稳定';

  return (
    <div
      className={className}
      role="alert"
      aria-live="polite"
      style={{
        position: 'sticky',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        backgroundColor: bg,
        color: '#0D1117',
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        fontSize: 14,
        fontWeight: 700,
        letterSpacing: 0.5,
        boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
        userSelect: 'none',
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: '#0D1117',
          animation: isOffline ? 'kds-pulse 1.2s infinite' : undefined,
        }}
      />
      <span>{text}</span>
    </div>
  );
}
