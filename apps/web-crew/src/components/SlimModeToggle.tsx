/**
 * SlimModeToggle — 简约模式切换按钮
 *
 * 高峰期开启：桌台卡片大字体 + 隐藏次要信息，只保留核心操作。
 * 状态持久化到 Zustand store（localStorage）。
 */
import { useCrewStore } from '../store/crewStore';

interface SlimModeToggleProps {
  /** 是否以图标+文字紧凑模式展示（用于顶部栏） */
  compact?: boolean;
}

export function SlimModeToggle({ compact = false }: SlimModeToggleProps) {
  const { isSlimMode, toggleSlimMode } = useCrewStore();

  if (compact) {
    return (
      <button
        onClick={toggleSlimMode}
        title={isSlimMode ? '退出简约模式' : '开启简约模式（高峰期）'}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          minHeight: 48,
          padding: '0 12px',
          background: isSlimMode ? 'var(--tx-primary, #FF6B35)' : 'transparent',
          border: `1.5px solid ${isSlimMode ? 'var(--tx-primary, #FF6B35)' : '#3a4a55'}`,
          borderRadius: 8,
          color: isSlimMode ? '#fff' : '#aaa',
          fontSize: 14,
          fontWeight: 600,
          cursor: 'pointer',
          WebkitTapHighlightColor: 'transparent',
          transition: 'all 0.2s ease',
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ fontSize: 16 }}>{isSlimMode ? '⚡' : '☰'}</span>
        {isSlimMode ? '简约' : '标准'}
      </button>
    );
  }

  // 完整模式（用于设置页或独立展示）
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '14px 16px',
        background: '#112228',
        borderRadius: 10,
        gap: 12,
      }}
    >
      <div>
        <div style={{ fontSize: 16, color: '#fff', fontWeight: 600 }}>
          ⚡ 简约模式
        </div>
        <div style={{ fontSize: 13, color: '#888', marginTop: 2 }}>
          高峰期只显示：收款 / 加菜 / 催菜
        </div>
      </div>

      {/* Toggle Switch */}
      <button
        onClick={toggleSlimMode}
        style={{
          position: 'relative',
          width: 52,
          height: 28,
          borderRadius: 14,
          background: isSlimMode ? 'var(--tx-primary, #FF6B35)' : '#3a4a55',
          border: 'none',
          cursor: 'pointer',
          flexShrink: 0,
          transition: 'background 0.25s ease',
          WebkitTapHighlightColor: 'transparent',
          padding: 0,
        }}
        aria-label={isSlimMode ? '关闭简约模式' : '开启简约模式'}
        aria-checked={isSlimMode}
        role="switch"
      >
        <span
          style={{
            position: 'absolute',
            top: 3,
            left: isSlimMode ? 27 : 3,
            width: 22,
            height: 22,
            borderRadius: 11,
            background: '#fff',
            transition: 'left 0.25s ease',
            boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
          }}
        />
      </button>
    </div>
  );
}
