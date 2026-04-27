// MCP Server & Tool 目录 · MCP 2025-03-26
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: 'MCP Server', value: '12',    delta: { text: '全部在线',    tone: 'success' as const } },
  { label: 'MCP Tools',  value: '47',    delta: { text: '▲ 5 本周',    tone: 'success' as const } },
  { label: '日调用',      value: '14.2k', delta: { text: '▲ 12% 环比',  tone: 'success' as const } },
  { label: '平均延迟',    value: '42ms',  delta: { text: 'p99 128ms',   tone: 'soft'    as const } },
]

/* ─── MCP Server 注册表 ─── */
interface ServerRow {
  id: string
  server: string
  app: string
  transport: string
  tools: number
  health: 'green' | 'amber' | 'red'
  dailyCalls: string
  p99: string
  status: 'active' | 'paused'
}

const SERVER_DATA: ServerRow[] = [
  { id: 's1', server: 'tx-trade-mcp',    app: '交易履约',    transport: 'stdio',      tools: 12, health: 'green', dailyCalls: '4,247', p99: '42ms',  status: 'active' },
  { id: 's2', server: 'tx-menu-mcp',     app: '菜品菜单',    transport: 'stdio',      tools: 8,  health: 'green', dailyCalls: '2,812', p99: '38ms',  status: 'active' },
  { id: 's3', server: 'tx-member-mcp',   app: '会员CDP',     transport: 'stdio',      tools: 6,  health: 'green', dailyCalls: '1,847', p99: '56ms',  status: 'active' },
  { id: 's4', server: 'tx-supply-mcp',   app: '供应链',      transport: 'stdio',      tools: 5,  health: 'green', dailyCalls: '1,242', p99: '44ms',  status: 'active' },
  { id: 's5', server: 'tx-finance-mcp',  app: '财务结算',    transport: 'stdio',      tools: 4,  health: 'green', dailyCalls: '847',   p99: '62ms',  status: 'active' },
  { id: 's6', server: 'tx-analytics-mcp', app: '经营分析',   transport: 'streamable-http', tools: 3, health: 'green', dailyCalls: '1,412', p99: '84ms', status: 'active' },
  { id: 's7', server: 'meituan-adapter',  app: '美团Adapter', transport: 'streamable-http', tools: 4, health: 'amber', dailyCalls: '2,147', p99: '187ms', status: 'active' },
  { id: 's8', server: 'douyin-adapter',   app: '抖音Adapter', transport: 'streamable-http', tools: 3, health: 'amber', dailyCalls: '642',  p99: '214ms', status: 'active' },
]

const HEALTH_DOT: Record<string, string> = {
  green: 'var(--green-400)',
  amber: 'var(--amber-200)',
  red:   'var(--ember-500)',
}

const SERVER_COLS: Column<ServerRow>[] = [
  { key: 'server',     label: 'Server',    render: r => <span className="mono" style={{ fontWeight: 500, fontSize: 11 }}>{r.server}</span>, width: 140 },
  { key: 'app',        label: '关联应用',   render: r => <span className="muted">{r.app}</span>, width: 90 },
  { key: 'transport',  label: '传输协议',   render: r => <Badge kind={r.transport === 'stdio' ? 'skill' : 'adapter'}>{r.transport}</Badge>, width: 120 },
  { key: 'tools',      label: 'Tools数',   render: r => <span className="mono">{r.tools}</span>, width: 60, align: 'center' },
  { key: 'health',     label: '健康',      render: r => (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
      <div style={{ width: 8, height: 8, borderRadius: '50%', background: HEALTH_DOT[r.health], boxShadow: r.health !== 'green' ? `0 0 4px ${HEALTH_DOT[r.health]}` : undefined }} />
    </div>
  ), width: 48, align: 'center' },
  { key: 'dailyCalls', label: '日调用',     render: r => <span className="mono muted">{r.dailyCalls}</span>, width: 72, align: 'right' },
  { key: 'p99',        label: 'p99延迟',   render: r => {
    const ms = parseInt(r.p99)
    return <span className="mono" style={{ color: ms > 150 ? 'var(--amber-200)' : 'var(--text-tertiary)' }}>{r.p99}</span>
  }, width: 72, align: 'right' },
  { key: 'status',     label: '状态',      render: r => <Badge kind={r.status}>{r.status === 'active' ? '运行' : '暂停'}</Badge>, width: 56, align: 'center' },
]

/* ─── 热门 Tools ─── */
interface ToolRow {
  id: string
  tool: string
  server: string
  entity: string
  minTier: string
  calls: string
}

const TOOL_DATA: ToolRow[] = [
  { id: 't1', tool: 'create_order',       server: 'tx-trade-mcp',   entity: 'Order',      minTier: 'T3', calls: '3,247' },
  { id: 't2', tool: 'get_dish_recommend',  server: 'tx-menu-mcp',    entity: 'Dish',       minTier: 'T2', calls: '2,812' },
  { id: 't3', tool: 'query_inventory',     server: 'tx-supply-mcp',  entity: 'Ingredient', minTier: 'T2', calls: '1,847' },
  { id: 't4', tool: 'get_member_profile',  server: 'tx-member-mcp',  entity: 'Customer',   minTier: 'T3', calls: '1,542' },
  { id: 't5', tool: 'sync_meituan_order',  server: 'meituan-adapter', entity: 'Order',     minTier: 'T4', calls: '1,247' },
  { id: 't6', tool: 'get_store_metrics',   server: 'tx-analytics-mcp', entity: 'Store',    minTier: 'T2', calls: '984' },
]

const TOOL_COLS: Column<ToolRow>[] = [
  { key: 'tool',    label: 'Tool',     render: r => <span className="mono" style={{ fontWeight: 500, fontSize: 11 }}>{r.tool}</span>, width: 150 },
  { key: 'server',  label: 'Server',   render: r => <span className="mono muted" style={{ fontSize: 11 }}>{r.server}</span>, width: 130 },
  { key: 'entity',  label: '实体绑定',  render: r => <Badge kind="action">{r.entity}</Badge>, width: 90 },
  { key: 'minTier', label: '最低信任',  render: r => <Badge kind={r.minTier === 'T4' ? 'official' : r.minTier === 'T3' ? 'integration' : 'isv'}>{r.minTier}</Badge>, width: 72, align: 'center' },
  { key: 'calls',   label: '调用量',   render: r => <span className="mono muted">{r.calls}</span>, width: 72, align: 'right' },
]

/* ─── Ontology 覆盖 ─── */
const ONTOLOGY_COVERAGE = [
  { entity: 'Store',      color: 'var(--ember-500)', tools: 8,  pct: 17 },
  { entity: 'Order',      color: 'var(--green-400)', tools: 12, pct: 26 },
  { entity: 'Customer',   color: 'var(--blue-400)',  tools: 7,  pct: 15 },
  { entity: 'Dish',       color: 'var(--amber-200)', tools: 9,  pct: 19 },
  { entity: 'Ingredient', color: 'var(--green-200)', tools: 6,  pct: 13 },
  { entity: 'Employee',   color: 'var(--ink-300)',   tools: 5,  pct: 11 },
]

export default function MCPRegistryPage() {
  return (
    <>
      <PageHeader
        crumb="AI OPS / MCP 注册表"
        title="MCP Server & Tool 目录"
        subtitle="12 Server · 47 Tools · MCP 2025-03-26"
        actions={<>
          <Button size="sm" variant="ghost">注册 Server</Button>
          <Button size="sm" variant="secondary">健康检查</Button>
          <Button size="sm" variant="primary">MCP 文档</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* MCP Server 注册表 */}
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            MCP Server 注册表
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>8 Server</span>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Button size="sm" variant="ghost">筛选</Button>
            <Button size="sm" variant="ghost">刷新</Button>
          </div>
        </div>
        <Table columns={SERVER_COLS} data={SERVER_DATA} rowKey={r => r.id} />
      </Card>

      {/* 底部 2列 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {/* 热门 Tools */}
        <Card>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 10 }}>
            热门 Tools
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>Top 6</span>
          </div>
          <Table columns={TOOL_COLS} data={TOOL_DATA} rowKey={r => r.id} />
        </Card>

        {/* Ontology 覆盖 */}
        <Card>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 10 }}>
            Ontology 覆盖
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>6 核心实体 · 47 Tools</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {ONTOLOGY_COVERAGE.map((e, i) => (
              <div key={e.entity} style={{
                padding: '6px 0',
                borderBottom: i < ONTOLOGY_COVERAGE.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: e.color }} />
                    <span style={{ fontWeight: 500, fontSize: 12 }}>{e.entity}</span>
                  </div>
                  <span className="mono muted" style={{ fontSize: 11 }}>{e.tools} tools · {e.pct}%</span>
                </div>
                <div style={{ height: 4, background: 'var(--bg-surface)', borderRadius: 2 }}>
                  <div style={{ width: `${e.pct}%`, height: '100%', background: e.color, borderRadius: 2 }} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  )
}
