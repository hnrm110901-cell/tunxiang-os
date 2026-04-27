import type { CSSProperties, ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  variant?: 'default' | 'elevated' | 'emphasis' | 'warn' | 'danger'
  padding?: number | string
  style?: CSSProperties
  className?: string
}

const VARIANT: Record<string, CSSProperties> = {
  default:  { background: 'var(--bg-secondary)', border: '0.5px solid var(--border-secondary)' },
  elevated: { background: 'var(--bg-surface)', border: '0.5px solid var(--border-secondary)' },
  emphasis: { background: 'var(--bg-secondary)', border: '1px solid var(--ember-500)' },
  warn:     { background: 'var(--bg-secondary)', border: '1px solid var(--amber-200)' },
  danger:   { background: 'var(--ember-900)', border: '1px solid var(--ember-500)' }
}

export function Card({ children, variant = 'default', padding = 14, style, className }: CardProps) {
  return (
    <div className={className} style={{
      ...VARIANT[variant],
      borderRadius: 'var(--r-md)',
      padding: typeof padding === 'number' ? padding : padding,
      ...style
    }}>
      {children}
    </div>
  )
}
