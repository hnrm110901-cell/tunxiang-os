// 商品管理 · 完整示范页(展示 Table 组件用法)
import { PageHeader, Button, Badge, Card, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

interface Product {
  id: string
  name: string
  uri: string
  type: 'skill' | 'action' | 'adapter' | 'theme' | 'widget' | 'integration'
  isv: string
  version: string
  installs: number
  rating: number | null
  price: string
  status: 'pass' | 'warn' | 'fail'
  statusLabel: string
}

const PRODUCTS: Product[] = [
  { id: '1', name: '智能配菜', uri: 'tx-skill://intelligent-prep', type: 'skill', isv: '屯象官方', version: 'v2.1.4', installs: 3247, rating: 4.8, price: '¥299/月', status: 'pass', statusLabel: '上架' },
  { id: '2', name: '美团外卖', uri: 'tx-adapter://meituan', type: 'adapter', isv: '屯象官方', version: 'v4.0.3', installs: 8742, rating: 4.9, price: '免费', status: 'pass', statusLabel: '上架' },
  { id: '3', name: '自动赠饮挽回', uri: 'tx-action://auto-comp-drink', type: 'action', isv: '屯象官方', version: 'v1.5.0', installs: 2148, rating: 4.7, price: '¥99/月', status: 'pass', statusLabel: '上架' },
  { id: '4', name: 'L0 品智移民皮肤', uri: 'tx-theme://legacy-pz', type: 'theme', isv: '屯象官方', version: 'v1.0.2', installs: 1847, rating: 4.9, price: '免费', status: 'pass', statusLabel: '上架' },
  { id: '5', name: '实时客流热力', uri: 'tx-widget://traffic-heat', type: 'widget', isv: '长沙青菜科技', version: 'v2.1.0', installs: 942, rating: 4.6, price: '¥199/月', status: 'pass', statusLabel: '上架' },
  { id: '6', name: '海鲜溯源', uri: 'tx-skill://seafood-trace', type: 'skill', isv: '屯象官方', version: 'v3.2.1', installs: 412, rating: 4.8, price: '¥499/月', status: 'pass', statusLabel: '上架' },
  { id: '7', name: '春节流量预测', uri: 'tx-skill://spring-festival', type: 'skill', isv: 'Labs', version: 'v0.9.3', installs: 247, rating: 4.6, price: '试用', status: 'warn', statusLabel: 'Alpha' },
  { id: '8', name: '桌台合并', uri: 'tx-action://table-merge', type: 'action', isv: '长沙青菜科技', version: 'v0.9.0', installs: 87, rating: null, price: '免费', status: 'warn', statusLabel: '回修' }
]

const COLUMNS: Column<Product>[] = [
  { key: 'name',     label: '商品',  render: r => <div><div style={{ fontWeight: 500 }}>{r.name}</div><div className="lbl">{r.uri}</div></div> },
  { key: 'type',     label: '类型',  render: r => <Badge kind={r.type}>{r.type}</Badge> },
  { key: 'isv',      label: 'ISV',  render: r => r.isv },
  { key: 'version',  label: '版本', render: r => <span className="mono ember-soft">{r.version}</span>, align: 'right' },
  { key: 'installs', label: '安装', render: r => <span className="mono">{r.installs.toLocaleString()}</span>, align: 'right' },
  { key: 'rating',   label: '评分', render: r => r.rating ? <span className="mono ember-soft">★{r.rating}</span> : <span className="mono muted">--</span>, align: 'right' },
  { key: 'price',    label: '价格', render: r => <span className="mono ember">{r.price}</span>, align: 'right' },
  { key: 'status',   label: '状态', render: r => <Badge kind={r.status}>{r.statusLabel}</Badge> },
  { key: 'op',       label: '操作', render: () => <a className="ember-soft" style={{ fontSize: 11 }}>详情</a> }
]

export default function CatalogPage() {
  return (
    <>
      <PageHeader
        crumb="CORE / 商品管理"
        title="商品目录"
        subtitle="723 件 · 上架 681 / 下架 28 / 草稿 14"
        actions={<>
          <Button size="sm" variant="ghost">批量操作</Button>
          <Button size="sm" variant="secondary">导出 CSV</Button>
          <Button size="sm" variant="primary">推荐位管理</Button>
        </>}
      />

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {['全部 723', 'Skill 142', 'Action 487', 'Adapter 38', 'Theme 24', 'Widget 63', 'Integration 29'].map((tab, i) => (
          <span key={tab} style={{
            padding: '6px 12px',
            fontSize: 12,
            color: i === 0 ? 'var(--ember-500)' : 'var(--text-secondary)',
            cursor: 'pointer',
            borderBottom: i === 0 ? '2px solid var(--ember-500)' : '2px solid transparent',
            fontWeight: i === 0 ? 500 : 400
          }}>{tab}</span>
        ))}
      </div>

      <Card padding={0} style={{ overflow: 'hidden' }}>
        <Table columns={COLUMNS} data={PRODUCTS} rowKey={r => r.id} />
      </Card>
    </>
  )
}
