/**
 * 快捷键提示浮层 — 按住 Alt 键时显示
 *
 * 半透明遮罩 + 快捷键网格，松开 Alt 自动关闭。
 * 遵循 Store 终端触控规范：最小字体 16px，按钮 >= 48px。
 */
import type { FC } from 'react';

interface ShortcutOverlayProps {
  visible: boolean;
  shortcuts: Array<{ key: string; label: string; disabled: boolean }>;
}

const C = {
  bg: 'rgba(11, 26, 32, 0.92)',
  card: '#112228',
  accent: '#FF6B35',
  text: '#E0E0E0',
  textDim: '#8899A6',
  border: '#1A3A48',
} as const;

export const ShortcutOverlay: FC<ShortcutOverlayProps> = ({ visible, shortcuts }) => {
  if (!visible) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: C.bg,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 32,
      }}
    >
      <h2
        style={{
          color: C.accent,
          fontSize: 24,
          fontWeight: 700,
          marginBottom: 32,
          fontFamily: 'inherit',
        }}
      >
        POS 快捷键
      </h2>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
          gap: 16,
          maxWidth: 900,
          width: '100%',
        }}
      >
        {shortcuts.map((s) => (
          <div
            key={s.key}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '12px 16px',
              borderRadius: 12,
              background: C.card,
              border: `1px solid ${C.border}`,
              opacity: s.disabled ? 0.4 : 1,
              minHeight: 48,
            }}
          >
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                minWidth: 56,
                height: 36,
                borderRadius: 6,
                background: C.accent,
                color: '#fff',
                fontSize: 16,
                fontWeight: 700,
                fontFamily: 'monospace',
                padding: '0 8px',
                flexShrink: 0,
              }}
            >
              {s.key}
            </span>
            <span style={{ color: C.text, fontSize: 17, fontWeight: 500 }}>
              {s.label}
            </span>
          </div>
        ))}
      </div>

      <p style={{ color: C.textDim, fontSize: 16, marginTop: 32 }}>
        松开 Alt 键关闭此面板
      </p>
    </div>
  );
};
