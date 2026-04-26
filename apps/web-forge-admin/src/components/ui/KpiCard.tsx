import { Card } from './Card'

interface KpiCardProps {
  label: string
  value: string | number
  delta?: { text: string; tone: 'success' | 'danger' | 'muted' | 'soft' }
  alert?: boolean
}

const DELTA_COLOR: Record<string, string> = {
  success: 'var(--green-400)',
  danger:  'var(--ember-500)',
  muted:   'var(--text-tertiary)',
  soft:    'var(--ember-300)'
}

export function KpiCard({ label, value, delta, alert }: KpiCardProps) {
  return (
    <Card variant={alert ? 'danger' : 'default'} padding={12}>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 9,
        letterSpacing: '0.12em',
        color: alert ? 'var(--ember-500)' : 'var(--text-tertiary)',
        textTransform: 'uppercase',
        marginBottom: 4
      }}>{label}</div>
      <div style={{
        fontFamily: 'var(--font-serif)',
        fontSize: 24,
        fontWeight: 500,
        color: alert ? 'var(--ember-500)' : '#fff',
        lineHeight: 1.1
      }}>{value}</div>
      {delta && (
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          marginTop: 4,
          color: DELTA_COLOR[delta.tone]
        }}>{delta.text}</div>
      )}
    </Card>
  )
}
