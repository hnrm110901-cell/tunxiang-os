import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  label: string
  render: (row: T, idx: number) => ReactNode
  align?: 'left' | 'right' | 'center'
  width?: number | string
}

interface TableProps<T> {
  columns: Column<T>[]
  data: T[]
  rowKey: (row: T) => string
  selectedKey?: string
}

export function Table<T>({ columns, data, rowKey, selectedKey }: TableProps<T>) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
      <thead>
        <tr style={{ background: 'var(--bg-surface)' }}>
          {columns.map(c => (
            <th key={c.key} style={{
              padding: '8px 12px',
              textAlign: c.align ?? 'left',
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              letterSpacing: '0.1em',
              color: 'var(--text-tertiary)',
              textTransform: 'uppercase',
              fontWeight: 400,
              borderBottom: '0.5px solid var(--border-secondary)',
              width: c.width
            }}>{c.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((row, idx) => {
          const key = rowKey(row)
          const selected = selectedKey === key
          return (
            <tr key={key} style={{
              background: selected ? 'var(--bg-surface)' : undefined,
              borderLeft: selected ? '2px solid var(--ember-500)' : undefined
            }}>
              {columns.map(c => (
                <td key={c.key} style={{
                  padding: '8px 12px',
                  textAlign: c.align ?? 'left',
                  borderTop: '0.5px solid var(--border-tertiary)',
                  color: 'var(--text-primary)',
                  verticalAlign: 'middle'
                }}>{c.render(row, idx)}</td>
              ))}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
