import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'destructive' | 'warn'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
  variant?: Variant
  size?: Size
}

const VARIANT_STYLE: Record<Variant, React.CSSProperties> = {
  primary:     { background: 'var(--ember-500)', color: '#fff', fontFamily: 'var(--font-serif)' },
  secondary:   { background: 'transparent', color: 'var(--ember-500)', border: '1px solid var(--ember-500)' },
  ghost:       { background: 'transparent', color: 'var(--text-secondary)', border: '0.5px solid var(--border-secondary)' },
  destructive: { background: 'transparent', color: 'var(--crimson-400)', border: '0.5px solid var(--crimson-600)' },
  warn:        { background: 'transparent', color: 'var(--amber-100)', border: '1px solid var(--amber-200)' }
}

const SIZE_STYLE: Record<Size, React.CSSProperties> = {
  sm: { padding: '4px 10px', fontSize: 11 },
  md: { padding: '7px 14px', fontSize: 12 },
  lg: { padding: '10px 20px', fontSize: 13 }
}

export function Button({ children, variant = 'ghost', size = 'md', style, ...rest }: ButtonProps) {
  return (
    <button
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        borderRadius: 6,
        fontWeight: 500,
        cursor: 'pointer',
        transition: '.15s',
        ...VARIANT_STYLE[variant],
        ...SIZE_STYLE[size],
        ...style
      }}
      {...rest}
    >
      {children}
    </button>
  )
}
