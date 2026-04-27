import type { ReactNode } from 'react'

type BadgeKind = 'skill' | 'action' | 'adapter' | 'theme' | 'widget' | 'integration'
              | 'official' | 'isv' | 'labs'
              | 'pass' | 'warn' | 'fail' | 'active' | 'paused'

const STYLE: Record<BadgeKind, React.CSSProperties> = {
  skill:       { background: 'var(--ember-900)', color: 'var(--ember-300)' },
  action:      { background: 'var(--green-900)', color: 'var(--green-200)' },
  adapter:     { background: 'var(--blue-900)',  color: 'var(--blue-200)'  },
  theme:       { background: 'var(--amber-900)', color: 'var(--amber-100)' },
  widget:      { background: 'var(--ink-600)',   color: 'var(--ink-200)'   },
  integration: { background: 'var(--ink-700)',   color: 'var(--ink-300)'   },
  official:    { background: 'var(--ember-500)', color: '#fff' },
  isv:         { background: 'var(--ink-600)',   color: 'var(--ink-300)'   },
  labs:        { background: 'transparent', color: 'var(--ember-300)', border: '0.5px dashed var(--ember-300)' },
  pass:        { background: 'var(--green-900)', color: 'var(--green-200)' },
  warn:        { background: 'var(--amber-900)', color: 'var(--amber-100)' },
  fail:        { background: 'var(--ember-900)', color: 'var(--ember-500)' },
  active:      { background: 'var(--green-900)', color: 'var(--green-200)' },
  paused:      { background: 'var(--ink-600)',   color: 'var(--ink-300)'   }
}

export function Badge({ kind, children }: { kind: BadgeKind; children: ReactNode }) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 7px',
      borderRadius: 3,
      fontFamily: 'var(--font-mono)',
      fontSize: 9,
      letterSpacing: '0.04em',
      ...STYLE[kind]
    }}>{children}</span>
  )
}
