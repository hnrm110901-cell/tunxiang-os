import type { ReactNode } from 'react'

interface PageHeaderProps {
  crumb: string
  title: string
  subtitle?: string
  actions?: ReactNode
}

export function PageHeader({ crumb, title, subtitle, actions }: PageHeaderProps) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-end',
      marginBottom: 14,
      paddingBottom: 12,
      borderBottom: '0.5px solid var(--border-tertiary)'
    }}>
      <div>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          letterSpacing: '0.1em',
          color: 'var(--ember-300)',
          textTransform: 'uppercase',
          marginBottom: 4
        }}>{crumb}</div>
        <h1 style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 22,
          fontWeight: 500,
          color: '#fff',
          lineHeight: 1.2
        }}>{title}</h1>
        {subtitle && (
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 3 }}>{subtitle}</div>
        )}
      </div>
      {actions && <div style={{ display: 'flex', gap: 8 }}>{actions}</div>}
    </div>
  )
}
