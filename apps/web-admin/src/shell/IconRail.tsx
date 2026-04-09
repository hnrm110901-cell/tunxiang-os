/**
 * Icon Rail — 一级导航（56px 图标导轨）
 * 纯图标，36px 按钮，圆角 9px
 */

const MODULES = [
  { id: 'dashboard', icon: '📊', label: '驾驶舱' },
  { id: 'trade', icon: '💰', label: '交易' },
  { id: 'menu', icon: '🍽️', label: '菜品' },
  { id: 'store', icon: '🏬', label: '门店' },
  { id: 'member', icon: '👥', label: '会员' },
  { id: 'growth', icon: '🚀', label: '增长' },
  { id: 'ops', icon: '🎯', label: '经营' },
  { id: 'analytics', icon: '📈', label: '分析' },
  { id: 'finance', icon: '💹', label: '财务' },
  { id: 'org', icon: '🏢', label: '组织' },
  { id: 'agent', icon: '🤖', label: 'Agent' },
];

interface IconRailProps {
  activeModule: string;
  onModuleChange: (id: string) => void;
}

export function IconRail({ activeModule, onModuleChange }: IconRailProps) {
  return (
    <nav style={{
      width: 56, background: 'var(--bg-1, #112228)',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '8px 0', gap: 4, borderRight: '1px solid var(--bg-2, #1a2a33)',
    }}>
      {MODULES.map((m) => (
        <button
          key={m.id}
          onClick={() => onModuleChange(m.id)}
          title={m.label}
          style={{
            width: 36, height: 36, border: 'none', borderRadius: 9, cursor: 'pointer',
            fontSize: 18, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: activeModule === m.id ? 'var(--brand-bg, rgba(255,107,44,0.08))' : 'transparent',
            transition: 'all var(--duration-fast, .15s)',
          }}
        >
          {m.icon}
        </button>
      ))}
      <div style={{ flex: 1 }} />
      <button title="帮助" style={{
        width: 36, height: 36, border: 'none', borderRadius: 9, cursor: 'pointer',
        fontSize: 16, background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>❓</button>
    </nav>
  );
}
