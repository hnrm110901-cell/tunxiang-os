/**
 * Icon Rail — 一级导航（56px 图标导轨）
 * 纯图标，36px 按钮，圆角 9px
 */
import { useLang } from '../i18n/LangContext';

const MODULES = [
  { id: 'dashboard', icon: '📊', labelKey: 'nav.dashboard' },
  { id: 'trade', icon: '💰', labelKey: 'nav.trade' },
  { id: 'menu', icon: '🍽️', labelKey: 'nav.menu' },
  { id: 'store', icon: '🏬', labelKey: 'nav.store' },
  { id: 'member', icon: '👥', labelKey: 'nav.member' },
  { id: 'growth', icon: '🚀', labelKey: 'nav.growth' },
  { id: 'ops', icon: '🎯', labelKey: 'nav.ops' },
  { id: 'analytics', icon: '📈', labelKey: 'nav.analytics' },
  { id: 'finance', icon: '💹', labelKey: 'nav.finance' },
  { id: 'org', icon: '🏢', labelKey: 'nav.org' },
  { id: 'agent', icon: '🤖', labelKey: 'nav.agent' },
];

interface IconRailProps {
  activeModule: string;
  onModuleChange: (id: string) => void;
}

export function IconRail({ activeModule, onModuleChange }: IconRailProps) {
  const { t } = useLang();

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
          title={t(m.labelKey)}
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
      <button title={t('common.help')} style={{
        width: 36, height: 36, border: 'none', borderRadius: 9, cursor: 'pointer',
        fontSize: 16, background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>❓</button>
    </nav>
  );
}
