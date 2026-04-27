import type { ReactNode } from 'react'

type Level = 'L1' | 'L2' | 'L3'

interface AgentVoiceCardProps {
  level: Level
  title: string
  body: ReactNode
  actions?: ReactNode
}

// 9 大 Agent 跨 16 端的统一视觉签名
// L1 耳语 · L2 建议 · L3 硬约束
export function AgentVoiceCard({ level, title, body, actions }: AgentVoiceCardProps) {
  const STYLE: Record<Level, React.CSSProperties> = {
    L1: { background: 'var(--bg-surface)', borderRadius: 'var(--r-md)', padding: 12 },
    L2: { background: 'var(--bg-surface)', borderLeft: '2px solid var(--ember-300)', borderRadius: '0 var(--r-md) var(--r-md) 0', padding: 12 },
    L3: { background: 'var(--ember-900)', border: '1.5px solid var(--ember-500)', borderRadius: 'var(--r-md)', padding: 12 }
  }

  const LABEL: Record<Level, { text: string; color: string }> = {
    L1: { text: 'L1 · WHISPER',   color: 'var(--text-tertiary)' },
    L2: { text: 'L2 · SUGGEST',   color: 'var(--ember-300)' },
    L3: { text: 'L3 · INTERRUPT', color: 'var(--ember-500)' }
  }

  return (
    <div style={STYLE[level]}>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 9,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: LABEL[level].color,
        marginBottom: 6
      }}>— {LABEL[level].text} · {title}</div>
      <div style={{
        fontSize: 12,
        color: level === 'L3' ? 'var(--ember-100)' : 'var(--text-primary)',
        lineHeight: 1.6
      }}>{body}</div>
      {actions && <div style={{ marginTop: 8, display: 'flex', gap: 6 }}>{actions}</div>}
    </div>
  )
}
