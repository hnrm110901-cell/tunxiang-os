// 集成监控 · OS/Agent/Hub/Labs 同步状态 + 事件总线 + API配额
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '屯象OS',       value: <span style={{ color: 'var(--green-400)' }}>健康</span>,  delta: { text: 'v3.0.3 在线', tone: 'success' as const } },
  { label: 'Master Agent', value: <span style={{ color: 'var(--green-400)' }}>健康</span>,  delta: { text: 'v3.4.1 在线', tone: 'success' as const } },
  { label: 'Hub',          value: <span style={{ color: 'var(--green-400)' }}>健康</span>,  delta: { text: 'v2.1.0 在线', tone: 'success' as const } },
  { label: 'Labs',         value: <span style={{ color: 'var(--amber-200)' }}>降级</span>,  delta: { text: '1 服务异常',  tone: 'soft'    as const } },
]

interface StreamItem {
  id: string
  stream: string
  producer: string
  consumer: string
  depth: number | string
  qps: number
  p99: string
  status: 'pass' | 'warn'
  statusLabel: string
}

const STREAMS: StreamItem[] = [
  { id: 's1', stream: 'forge.product.published',   producer: 'Forge Admin',  consumer: 'Hub+Agent',            depth: 0,   qps: 0.8,  p99: '12ms',  status: 'pass', statusLabel: '正常' },
  { id: 's2', stream: 'forge.product.installed',    producer: 'Hub',          consumer: 'Forge+Agent+Finance',  depth: 3,   qps: 8.4,  p99: '42ms',  status: 'pass', statusLabel: '正常' },
  { id: 's3', stream: 'forge.product.uninstalled',  producer: 'Hub',          consumer: 'Forge+Finance',        depth: 0,   qps: 1.2,  p99: '38ms',  status: 'pass', statusLabel: '正常' },
  { id: 's4', stream: 'forge.skill.executed',        producer: 'Agent',        consumer: 'Forge analytics',      depth: 42,  qps: 147,  p99: '8ms',   status: 'pass', statusLabel: '正常' },
  { id: 's5', stream: 'labs.alpha.feedback',          producer: 'Labs',         consumer: 'Forge review',         depth: 182, qps: 3.2,  p99: '412ms', status: 'warn', statusLabel: '积压' },
]

const STREAM_COLS: Column<StreamItem>[] = [
  { key: 'stream',   label: '事件流',   render: r => <span className="mono" style={{ fontSize: 10 }}>{r.stream}</span> },
  { key: 'producer', label: '生产者',   render: r => <span className="muted">{r.producer}</span> },
  { key: 'consumer', label: '消费者',   render: r => <span className="muted">{r.consumer}</span> },
  { key: 'depth',    label: '队列深度', render: r => <span className={`mono ${r.status === 'warn' ? 'ember-soft' : ''}`}>{r.depth}</span>, width: 72, align: 'right' },
  { key: 'qps',      label: 'QPS',      render: r => <span className="mono">{r.qps}</span>, width: 56, align: 'right' },
  { key: 'p99',      label: 'p99延时',  render: r => <span className={`mono ${r.status === 'warn' ? 'ember-soft' : 'muted'}`}>{r.p99}</span>, width: 64, align: 'right' },
  { key: 'status',   label: '状态',     render: r => <Badge kind={r.status}>{r.status === 'pass' ? '正常' : r.statusLabel}</Badge>, width: 64 },
]

const API_QUOTAS = [
  { label: '读API',    used: '42M',  limit: '100M', pct: 42,   color: 'var(--green-400)' },
  { label: '写API',    used: '3.2M', limit: '10M',  pct: 32,   color: 'var(--green-400)' },
  { label: 'Webhook',  used: '847k', limit: '1M',   pct: 84.7, color: 'var(--ember-500)' },
]

export default function IntegrationsPage() {
  return (
    <>
      <PageHeader
        crumb="GUARDRAIL / 集成监控"
        title="集成监控"
        subtitle="与 OS / Agent / Hub / Labs 同步状态"
        actions={<>
          <Button size="sm" variant="ghost">事件总线</Button>
          <Button size="sm" variant="secondary">API配额</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 主内容: 2fr 1fr */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
        {/* 左: 事件总线表 */}
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <div className="lbl-sm muted" style={{ padding: '12px 12px 8px' }}>事件总线 · Redis Streams</div>
          <Table columns={STREAM_COLS} data={STREAMS} rowKey={r => r.id} />
        </Card>

        {/* 右: API配额 + 服务异常 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* API配额(本月) */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 10 }}>API配额（本月）</div>
            {API_QUOTAS.map(q => (
              <div key={q.label} style={{ marginBottom: 10, fontSize: 11 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span className="muted">{q.label}</span>
                  <span className="mono">{q.used} / {q.limit}<span className="dim" style={{ marginLeft: 4 }}>{q.pct}%</span></span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-surface)', borderRadius: 3 }}>
                  <div style={{ width: `${q.pct}%`, height: '100%', background: q.color, borderRadius: 3 }} />
                </div>
              </div>
            ))}
          </Card>

          {/* 服务异常 */}
          <Card variant="emphasis">
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 1 服务异常</div>
            <div style={{ fontSize: 11, lineHeight: 1.7 }}>
              <div style={{ fontWeight: 500, marginBottom: 4 }}>labs-alpha-feedback-collector</div>
              <div className="muted">
                Labs alpha 反馈收集器消费速率低于生产速率，队列深度 182 持续积压。
                p99 延时 412ms 超过阈值（目标 &lt; 100ms）。建议扩容消费者实例或降低采样率。
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <Button size="sm" variant="secondary" style={{ width: '100%' }}>查看 Grafana</Button>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
