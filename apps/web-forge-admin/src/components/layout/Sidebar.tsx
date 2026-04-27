import { NavLink, useLocation } from 'react-router-dom'
import { MENU, DOMAIN_LABELS } from '@/data/menuConfig'
import type { MenuDomain } from '@/types/menu'

const DOMAINS: MenuDomain[] = ['CORE', 'ECOSYSTEM', 'BUSINESS', 'GUARDRAIL']

const PILL_TONE: Record<string, string> = {
  danger: 'background: var(--ember-900); color: var(--ember-500)',
  warn:   'background: var(--amber-900); color: var(--amber-100)',
  info:   'background: var(--ember-900); color: var(--ember-300)'
}

export function Sidebar() {
  const location = useLocation()

  return (
    <aside style={{
      background: 'var(--ink-950)',
      borderRight: '1px solid var(--border-tertiary)',
      overflowY: 'auto',
      padding: '8px 0'
    }}>
      {DOMAINS.map(domain => (
        <div key={domain}>
          <div style={{
            padding: '10px 14px 4px',
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            letterSpacing: '0.14em',
            color: 'var(--ember-300)',
            textTransform: 'uppercase'
          }}>
            {DOMAIN_LABELS[domain]}
          </div>
          {MENU.filter(m => m.domain === domain).map(item => {
            const active = location.pathname === item.path
            return (
              <div key={item.id}>
                <NavLink
                  to={item.path}
                  style={{
                    padding: '6px 14px',
                    fontSize: 12,
                    color: active ? 'var(--ember-500)' : 'var(--text-secondary)',
                    background: active ? 'var(--bg-surface)' : 'transparent',
                    borderLeft: active ? '2px solid var(--ember-500)' : '2px solid transparent',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontWeight: active ? 500 : 400
                  }}
                >
                  <span>{item.icon} {item.label}</span>
                  {item.badge && (
                    <span style={{
                      ...Object.fromEntries(PILL_TONE[item.badge.tone].split(';').map(s => {
                        const [k, v] = s.split(':').map(p => p.trim())
                        return [k.replace(/-([a-z])/g, (_, c) => c.toUpperCase()), v]
                      })),
                      padding: '1px 6px',
                      borderRadius: 3,
                      fontSize: 8,
                      fontFamily: 'var(--font-mono)'
                    }}>
                      {item.badge.text}
                    </span>
                  )}
                </NavLink>
                {active && (
                  <div>
                    {item.subItems.map(sub => (
                      <a key={sub.path} href={sub.path} style={{
                        padding: '5px 14px 5px 30px',
                        fontSize: 11,
                        color: 'var(--text-tertiary)',
                        display: 'block'
                      }}>› {sub.label}</a>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}

      <div style={{
        padding: 14,
        borderTop: '0.5px solid var(--border-tertiary)',
        marginTop: 14,
        fontFamily: 'var(--font-mono)',
        fontSize: 8,
        color: 'var(--text-tertiary)',
        lineHeight: 1.6
      }}>
        Forge Admin · 2.0<br/>
        14 模块 · 70+ 子页<br/>
        single source: marketplace.json
      </div>
    </aside>
  )
}
