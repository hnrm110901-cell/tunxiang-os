import type { ReactNode } from 'react'
import { PageHeader, Button, Card } from '@/components/ui'

interface StubProps {
  crumb: string
  title: string
  subtitle?: string
  prototypeAnchor: string
  children?: ReactNode
}

// 临时占位 · 12 个页面照 OverviewPage / CatalogPage 的模式逐步充实
// 当前从 forge-admin-prototype.html 的对应 section 拷贝并 React 化
export function PageStub({ crumb, title, subtitle, prototypeAnchor, children }: StubProps) {
  return (
    <>
      <PageHeader
        crumb={crumb}
        title={title}
        subtitle={subtitle}
        actions={<Button size="sm" variant="ghost">📐 查看 Prototype</Button>}
      />
      <Card>
        <div style={{ padding: 32, textAlign: 'center' }}>
          <div className="lbl ember-soft" style={{ marginBottom: 8 }}>—— PAGE STUB · 待迁移自 prototype.html ——</div>
          <div className="h-serif" style={{ fontSize: 14, marginBottom: 12 }}>
            参照 <code style={{ background: 'var(--bg-surface)', padding: '2px 8px', borderRadius: 3, fontFamily: 'var(--font-mono)' }}>{prototypeAnchor}</code>
          </div>
          <div className="muted" style={{ fontSize: 11, lineHeight: 1.7 }}>
            完整 UI 设计已在 <code style={{ fontFamily: 'var(--font-mono)' }}>outputs/forge-admin-prototype.html</code> 中。<br/>
            按 OverviewPage / CatalogPage 模式拷贝并 React 化。<br/>
            约 200-400 行 / 页 · 1 名前端 1 天可完成全部 12 页。
          </div>
        </div>
        {children}
      </Card>
    </>
  )
}
