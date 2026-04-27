import type { ReactNode } from 'react'
import { TopNav } from './TopNav'
import { Sidebar } from './Sidebar'

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gridTemplateRows: '42px 1fr', height: '100vh', overflow: 'hidden' }}>
      <TopNav />
      <Sidebar />
      <main style={{ overflowY: 'auto', padding: '18px 22px' }}>
        {children}
      </main>
    </div>
  )
}
