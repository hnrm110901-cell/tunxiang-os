/**
 * Topbar-HQ — 顶栏（48px，贯穿全宽）
 * Logo + Command Palette 触发器(⌘K) + 通知 + 用户
 */

interface TopbarHQProps {
  onToggleAgent: () => void;
}

export function TopbarHQ({ onToggleAgent }: TopbarHQProps) {
  return (
    <header style={{
      height: 48, background: 'var(--bg-1, #112228)',
      borderBottom: '1px solid var(--bg-2, #1a2a33)',
      display: 'flex', alignItems: 'center', padding: '0 16px', gap: 12,
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 140 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 7, background: 'var(--brand)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 'bold', color: '#fff',
        }}>TX</div>
        <span style={{ fontFamily: 'var(--font-title)', fontWeight: 700, fontSize: 13 }}>屯象OS</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-4)' }}>v3.0</span>
      </div>

      {/* Command Palette 触发器 */}
      <div style={{
        flex: 1, maxWidth: 480, padding: '6px 12px', borderRadius: 8,
        background: 'var(--bg-0)', border: '1px solid var(--bg-2)',
        display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
      }}>
        <span style={{ fontSize: 14 }}>🔍</span>
        <span style={{ fontSize: 12, color: 'var(--text-4)', flex: 1 }}>搜索菜品、订单、功能...</span>
        <kbd style={{
          padding: '2px 6px', borderRadius: 4, background: 'var(--bg-2)',
          fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)',
        }}>⌘K</kbd>
      </div>

      <div style={{ flex: 1 }} />

      {/* 右侧工具 */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)' }}>
        {new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
      </span>

      <button onClick={onToggleAgent} title="Agent Console" style={{
        width: 32, height: 32, border: 'none', borderRadius: 8, cursor: 'pointer',
        background: 'transparent', fontSize: 16,
      }}>🤖</button>

      <button title="通知" style={{
        width: 32, height: 32, border: 'none', borderRadius: 8, cursor: 'pointer',
        background: 'transparent', fontSize: 16, position: 'relative',
      }}>
        🔔
        <span style={{
          position: 'absolute', top: 2, right: 2, width: 8, height: 8,
          borderRadius: '50%', background: 'var(--red)',
        }} />
      </button>

      {/* 用户头像 */}
      <div style={{
        width: 28, height: 28, borderRadius: '50%',
        background: 'linear-gradient(135deg, var(--brand), var(--purple))',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 'bold', color: '#fff', cursor: 'pointer',
      }}>未</div>
    </header>
  );
}
