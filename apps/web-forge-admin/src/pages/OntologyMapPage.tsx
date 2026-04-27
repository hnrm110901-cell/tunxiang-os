// Ontology 实体映射 · 6 核心实体 × 应用绑定关系
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '核心实体', value: '6',   delta: { text: 'Ontology L1', tone: 'soft'    as const } },
  { label: '绑定应用', value: '47',  delta: { text: '▲ 5 本周',    tone: 'success' as const } },
  { label: '绑定关系', value: '142', delta: { text: '▲ 12 本月',   tone: 'success' as const } },
  { label: '约束规则', value: '38',  delta: { text: '全部生效',    tone: 'success' as const } },
]

/* ─── 实体卡片数据 ─── */
interface EntityCard {
  name: string
  icon: string
  color: string
  readCount: number
  writeCount: number
  rwCount: number
  constraints: number
  topApps: { app: string; mode: 'read' | 'write' | 'rw' }[]
}

const ENTITIES: EntityCard[] = [
  {
    name: 'Store', icon: '■', color: 'var(--ember-500)',
    readCount: 18, writeCount: 4, rwCount: 6, constraints: 7,
    topApps: [
      { app: '智能配菜', mode: 'rw' },
      { app: '客流预测', mode: 'read' },
      { app: '巡店质检', mode: 'write' },
    ]
  },
  {
    name: 'Order', icon: '■', color: 'var(--green-400)',
    readCount: 22, writeCount: 8, rwCount: 10, constraints: 9,
    topApps: [
      { app: '美团 Adapter', mode: 'rw' },
      { app: '折扣守护', mode: 'read' },
      { app: '财务稽核', mode: 'read' },
    ]
  },
  {
    name: 'Customer', icon: '■', color: 'var(--blue-400)',
    readCount: 14, writeCount: 3, rwCount: 5, constraints: 8,
    topApps: [
      { app: '会员洞察', mode: 'rw' },
      { app: '私域运营', mode: 'read' },
      { app: '抖音营销', mode: 'read' },
    ]
  },
  {
    name: 'Dish', icon: '■', color: 'var(--amber-200)',
    readCount: 16, writeCount: 5, rwCount: 7, constraints: 6,
    topApps: [
      { app: '智能配菜', mode: 'rw' },
      { app: '川菜动态定价', mode: 'read' },
      { app: '海鲜溯源', mode: 'rw' },
    ]
  },
  {
    name: 'Ingredient', icon: '■', color: 'var(--green-200)',
    readCount: 10, writeCount: 4, rwCount: 3, constraints: 5,
    topApps: [
      { app: '库存预警', mode: 'rw' },
      { app: '海鲜溯源', mode: 'read' },
      { app: '智能配菜', mode: 'read' },
    ]
  },
  {
    name: 'Employee', icon: '■', color: 'var(--ink-300)',
    readCount: 8, writeCount: 2, rwCount: 3, constraints: 3,
    topApps: [
      { app: '排班助手', mode: 'rw' },
      { app: '巡店质检', mode: 'read' },
      { app: '绩效分析', mode: 'read' },
    ]
  },
]

const MODE_BADGE: Record<string, 'pass' | 'warn' | 'active'> = {
  read: 'pass', write: 'warn', rw: 'active'
}
const MODE_LABEL: Record<string, string> = {
  read: 'R', write: 'W', rw: 'RW'
}

/* ─── FORGE_MANIFEST 提交历史 ─── */
interface ManifestRow {
  id: string
  app: string
  version: string
  submitted: string
  checksum: string
  bindings: number
  tools: number
  status: 'pass' | 'warn' | 'fail'
  statusLabel: string
}

const MANIFEST_DATA: ManifestRow[] = [
  { id: 'm1', app: '智能配菜',      version: 'v2.3.1', submitted: '2026-04-25 10:42', checksum: 'a3f8c2d1', bindings: 14, tools: 8,  status: 'pass', statusLabel: '已通过' },
  { id: 'm2', app: '美团 Adapter',  version: 'v4.1.0', submitted: '2026-04-24 16:18', checksum: 'b7e4f912', bindings: 12, tools: 4,  status: 'pass', statusLabel: '已通过' },
  { id: 'm3', app: '实时客流热力',   version: 'v1.2.0', submitted: '2026-04-23 09:34', checksum: 'c5d2a847', bindings: 6,  tools: 3,  status: 'warn', statusLabel: '待复核' },
  { id: 'm4', app: '抖音营销',      version: 'v2.5.1', submitted: '2026-04-22 14:21', checksum: 'e8b1c3f4', bindings: 8,  tools: 3,  status: 'fail', statusLabel: '被拒绝' },
  { id: 'm5', app: '川菜动态定价',   version: 'v0.9.0', submitted: '2026-04-20 11:08', checksum: 'f2a7d5e9', bindings: 4,  tools: 2,  status: 'pass', statusLabel: '已通过' },
]

const MANIFEST_COLS: Column<ManifestRow>[] = [
  { key: 'app',       label: '应用',    render: r => <span style={{ fontWeight: 500 }}>{r.app}</span>, width: 120 },
  { key: 'version',   label: '版本',    render: r => <Badge kind="skill">{r.version}</Badge>, width: 72 },
  { key: 'submitted', label: '提交时间', render: r => <span className="mono muted" style={{ fontSize: 11 }}>{r.submitted}</span>, width: 130 },
  { key: 'checksum',  label: '校验',    render: r => <span className="mono dim" style={{ fontSize: 10 }}>{r.checksum}</span>, width: 72 },
  { key: 'bindings',  label: '绑定数',  render: r => <span className="mono">{r.bindings}</span>, width: 56, align: 'center' },
  { key: 'tools',     label: '工具数',  render: r => <span className="mono">{r.tools}</span>, width: 56, align: 'center' },
  { key: 'status',    label: '状态',    render: r => <Badge kind={r.status}>{r.statusLabel}</Badge>, width: 72, align: 'center' },
]

export default function OntologyMapPage() {
  return (
    <>
      <PageHeader
        crumb="AI OPS / Ontology 绑定"
        title="Ontology 实体映射"
        subtitle="6 核心实体 · 47 应用 · 142 绑定关系"
        actions={<>
          <Button size="sm" variant="ghost">绑定矩阵</Button>
          <Button size="sm" variant="secondary">导出清单</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 6 实体卡片 · 3列 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
        {ENTITIES.map(e => (
          <Card key={e.name} style={{ borderLeft: `2px solid ${e.color}` }}>
            {/* 标题行 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: e.color, fontSize: 14 }}>{e.icon}</span>
                <span style={{ fontFamily: 'var(--font-serif)', fontSize: 15, fontWeight: 600, color: '#fff' }}>{e.name}</span>
              </div>
              <span className="mono dim" style={{ fontSize: 10 }}>{e.constraints} 约束</span>
            </div>

            {/* 读写计数 */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 10, fontSize: 11 }}>
              <div>
                <span className="dim" style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em' }}>READ </span>
                <span className="mono" style={{ color: 'var(--green-400)' }}>{e.readCount}</span>
              </div>
              <div>
                <span className="dim" style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em' }}>WRITE </span>
                <span className="mono" style={{ color: 'var(--amber-200)' }}>{e.writeCount}</span>
              </div>
              <div>
                <span className="dim" style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em' }}>R+W </span>
                <span className="mono" style={{ color: 'var(--ember-500)' }}>{e.rwCount}</span>
              </div>
            </div>

            {/* Top 3 应用 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {e.topApps.map(a => (
                <div key={a.app} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '3px 0',
                  borderTop: '0.5px dotted var(--border-tertiary)',
                  fontSize: 11
                }}>
                  <span className="muted">{a.app}</span>
                  <Badge kind={MODE_BADGE[a.mode]}>{MODE_LABEL[a.mode]}</Badge>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>

      {/* FORGE_MANIFEST 提交历史 */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            FORGE_MANIFEST 提交历史
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>最近 5 条</span>
          </div>
          <Button size="sm" variant="ghost">查看全部</Button>
        </div>
        <Table columns={MANIFEST_COLS} data={MANIFEST_DATA} rowKey={r => r.id} />
      </Card>
    </>
  )
}
