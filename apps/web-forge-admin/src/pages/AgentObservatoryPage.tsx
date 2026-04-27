// Agent 天眼 · 屯象 Forge AI OPS 旗舰页
// Inspired by ServiceNow AI Control Tower + Datadog LLM Observability
import { PageHeader, KpiCard, Card, Button, Badge, AgentVoiceCard } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

/* ─── Agent 定义 ─── */
interface Agent {
  id: string
  name: string
  role: string
  status: 'online' | 'degraded' | 'offline'
  executions: string
  executionsRaw: number
  p99: string
  successRate: string
  color: string
  sparkline: number[] // 5 bar heights (0-100)
}

const AGENTS: Agent[] = [
  { id: 'master',    name: 'Master Agent',    role: '总调度',   status: 'online',   executions: '12,847', executionsRaw: 12847, p99: '42ms',  successRate: '99.7%', color: 'var(--ember-500)', sparkline: [80, 92, 88, 95, 90] },
  { id: 'discount',  name: '折扣守护 Agent',   role: '毛利防线', status: 'online',   executions: '8,421',  executionsRaw: 8421,  p99: '18ms',  successRate: '99.9%', color: 'var(--green-400)', sparkline: [70, 75, 82, 78, 85] },
  { id: 'dish',      name: '菜品推荐 Agent',   role: '智能配菜', status: 'online',   executions: '6,247',  executionsRaw: 6247,  p99: '84ms',  successRate: '99.2%', color: 'var(--blue-400)',  sparkline: [60, 72, 68, 80, 76] },
  { id: 'inventory', name: '库存预警 Agent',   role: '智能补货', status: 'online',   executions: '4,812',  executionsRaw: 4812,  p99: '31ms',  successRate: '99.8%', color: 'var(--amber-200)', sparkline: [55, 62, 58, 70, 65] },
  { id: 'traffic',   name: '客流预测 Agent',   role: '流量洞察', status: 'online',   executions: '3,247',  executionsRaw: 3247,  p99: '124ms', successRate: '98.7%', color: 'var(--green-200)', sparkline: [45, 52, 60, 55, 48] },
  { id: 'inspect',   name: '巡店质检 Agent',   role: '后厨监控', status: 'online',   executions: '2,184',  executionsRaw: 2184,  p99: '247ms', successRate: '99.1%', color: 'var(--blue-200)',  sparkline: [30, 38, 42, 35, 40] },
  { id: 'member',    name: '会员洞察 Agent',   role: 'CRM 智能', status: 'online',   executions: '5,412',  executionsRaw: 5412,  p99: '67ms',  successRate: '99.4%', color: 'var(--ember-300)', sparkline: [65, 70, 78, 72, 80] },
  { id: 'finance',   name: '财务稽核 Agent',   role: '账务合规', status: 'online',   executions: '1,847',  executionsRaw: 1847,  p99: '89ms',  successRate: '99.6%', color: 'var(--ink-300)',   sparkline: [25, 30, 28, 35, 32] },
  { id: 'delivery',  name: '外卖调度 Agent',   role: '配送优化', status: 'degraded', executions: '947',    executionsRaw: 947,   p99: '412ms', successRate: '94.2%', color: 'var(--amber-100)', sparkline: [40, 35, 20, 15, 12] },
]

/* ─── 实时执行追踪 ─── */
interface Trace {
  id: string
  time: string
  agent: string
  skill: string
  input: string
  latency: string
  tokens: string
  decision: string
  status: 'pass' | 'warn'
}

const TRACES: Trace[] = [
  { id: 't1', time: '12:31:42', agent: 'Master Agent',  skill: '折扣策略评估', input: '湘遇华南6店午市折扣',      latency: '42ms',  tokens: '1,247', decision: '拦截异常折扣',         status: 'pass' },
  { id: 't2', time: '12:31:38', agent: '折扣守护',       skill: '毛利底线校验', input: '牛肉组合套餐 ¥38',        latency: '18ms',  tokens: '384',   decision: '毛利 32% > 28% 底线',  status: 'pass' },
  { id: 't3', time: '12:31:35', agent: '菜品推荐',       skill: '智能配菜',     input: '徐记海鲜 晚市推荐',       latency: '84ms',  tokens: '2,147', decision: '推荐 8 道 · 毛利 42%',  status: 'pass' },
  { id: 't4', time: '12:31:21', agent: '库存预警',       skill: '补货预测',     input: '最黔线长沙3店 鲈鱼',      latency: '31ms',  tokens: '847',   decision: '触发补货 15kg',        status: 'pass' },
  { id: 't5', time: '12:31:14', agent: '客流预测',       skill: '午市预测',     input: '尚宫厨 周六午市',         latency: '124ms', tokens: '3,247', decision: '预测 287 人 ±12%',      status: 'pass' },
  { id: 't6', time: '12:30:58', agent: '外卖调度',       skill: '配送分配',     input: '美团 #MT-8842',          latency: '412ms', tokens: '4,812', decision: '超时重试 2 次',         status: 'warn' },
  { id: 't7', time: '12:30:42', agent: '会员洞察',       skill: '流失预警',     input: 'VIP 王女士 30d 未到',     latency: '67ms',  tokens: '1,847', decision: '触发赠饮挽回',          status: 'pass' },
  { id: 't8', time: '12:30:28', agent: '财务稽核',       skill: '日终对账',     input: '华南区 4 店昨日',         latency: '89ms',  tokens: '2,412', decision: '差异 ¥0.00',            status: 'pass' },
]

const TRACE_COLUMNS: Column<Trace>[] = [
  { key: 'time',     label: '时间',        width: 72,  render: r => <span className="mono muted">{r.time}</span> },
  { key: 'agent',    label: 'Agent',       width: 100, render: r => <span style={{ fontWeight: 500 }}>{r.agent}</span> },
  { key: 'skill',    label: 'Skill/Action', width: 110, render: r => <span className="ember-soft">{r.skill}</span> },
  { key: 'input',    label: '输入摘要',     render: r => <span className="muted" style={{ fontSize: 11 }}>{r.input}</span> },
  { key: 'latency',  label: '延迟',        width: 64, align: 'right', render: r => {
    const ms = parseInt(r.latency)
    return <span className="mono" style={{ color: ms > 200 ? 'var(--amber-100)' : 'var(--text-tertiary)' }}>{r.latency}</span>
  }},
  { key: 'tokens',   label: 'Token',       width: 64, align: 'right', render: r => <span className="mono dim">{r.tokens}</span> },
  { key: 'decision', label: '决策',        width: 160, render: r => <span style={{ fontSize: 11 }}>{r.decision}</span> },
  { key: 'status',   label: '状态',        width: 56, align: 'center', render: r => <Badge kind={r.status}>{r.status.toUpperCase()}</Badge> },
]

/* ─── 7 天健康矩阵 ─── */
const DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '今天']

type HealthStatus = 'green' | 'amber' | 'red'

const HEALTH_MATRIX: Record<string, HealthStatus[]> = {
  'Master Agent':    ['green','green','green','green','green','green','green'],
  '折扣守护':        ['green','green','green','green','green','green','green'],
  '菜品推荐':        ['green','green','green','amber','green','green','green'],
  '库存预警':        ['green','green','green','green','green','green','green'],
  '客流预测':        ['green','amber','green','green','green','green','green'],
  '巡店质检':        ['green','green','green','green','green','green','green'],
  '会员洞察':        ['green','green','green','green','green','green','green'],
  '财务稽核':        ['green','green','green','green','green','green','green'],
  '外卖调度':        ['green','green','amber','amber','amber','amber','amber'],
}

const HEALTH_COLOR: Record<HealthStatus, string> = {
  green: 'var(--green-400)',
  amber: 'var(--amber-200)',
  red:   'var(--ember-500)',
}

/* ─── Component ─── */
export default function AgentObservatoryPage() {
  return (
    <>
      {/* ── Header ── */}
      <PageHeader
        crumb="AI OPS / Agent 天眼"
        title="Agent Observatory"
        subtitle="9 大 Agent · 实时监控 · 73 Skill · 487 Action · 38 Adapter"
        actions={<>
          <Button size="sm" variant="ghost">全链路追踪</Button>
          <Button size="sm" variant="secondary">决策审计</Button>
          <Button size="sm" variant="ghost" style={{ color: 'var(--ember-500)', borderColor: 'var(--ember-500)' }}>紧急熔断</Button>
        </>}
      />

      {/* ══════════════════════════════════════════════
          Section 1: 9 Agent 状态卡片 · 3×3 grid
          ══════════════════════════════════════════════ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
        {AGENTS.map(a => {
          const isDegraded = a.status === 'degraded'
          const isOffline  = a.status === 'offline'
          const statusBadge = isDegraded ? 'warn' : isOffline ? 'fail' : 'active'
          const statusLabel = isDegraded ? '降级' : isOffline ? '离线' : '在线'

          return (
            <Card key={a.id} style={isDegraded ? { borderLeft: '2px solid var(--amber-200)' } : undefined}>
              {/* Top: icon + name + status */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 6,
                  background: a.color, opacity: isDegraded ? 0.6 : 1,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 12, fontWeight: 700, color: '#000',
                  flexShrink: 0
                }}>
                  {a.name.charAt(0)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#fff', lineHeight: 1.3 }}>{a.name}</div>
                  <div className="lbl-sm dim" style={{ marginTop: 1 }}>{a.role}</div>
                </div>
                <Badge kind={statusBadge}>{statusLabel}</Badge>
              </div>

              {/* Middle: big number */}
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
                <span className="mono" style={{
                  fontSize: 22, fontWeight: 600,
                  color: isDegraded ? 'var(--amber-100)' : 'var(--ember-500)'
                }}>{a.executions}</span>
                <span className="lbl-sm muted">次/今日</span>
              </div>

              {/* Bottom row: p99 + success + sparkline */}
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, fontSize: 11 }}>
                <div>
                  <span className="dim" style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em' }}>P99 </span>
                  <span className="mono" style={{
                    color: parseInt(a.p99) > 200 ? 'var(--amber-100)' : 'var(--text-secondary)'
                  }}>{a.p99}</span>
                </div>
                <div>
                  <span className="dim" style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em' }}>成功 </span>
                  <span className="mono" style={{
                    color: parseFloat(a.successRate) < 97 ? 'var(--amber-100)' : 'var(--green-400)'
                  }}>{a.successRate}</span>
                </div>

                {/* Mini sparkline: 5 bars */}
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, marginLeft: 'auto', height: 20 }}>
                  {a.sparkline.map((h, i) => (
                    <div key={i} style={{
                      width: 4, borderRadius: 1,
                      height: `${Math.max(h * 0.2, 2)}px`,
                      background: isDegraded ? 'var(--amber-200)' : a.color,
                      opacity: 0.4 + (i * 0.15)
                    }} />
                  ))}
                </div>
              </div>
            </Card>
          )
        })}
      </div>

      {/* ══════════════════════════════════════════════
          Section 2: 实时执行追踪
          ══════════════════════════════════════════════ */}
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            最近 Skill 执行链路
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>实时 · 8 条</span>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Button size="sm" variant="ghost">筛选</Button>
            <Button size="sm" variant="ghost">导出</Button>
          </div>
        </div>
        <Table columns={TRACE_COLUMNS} data={TRACES} rowKey={r => r.id} />
      </Card>

      {/* ══════════════════════════════════════════════
          Section 3: 决策审计面板 · 2-col grid
          ══════════════════════════════════════════════ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* Left: 今日决策摘要 */}
        <Card>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 12 }}>
            今日决策摘要
          </div>

          {/* Big total */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 14 }}>
            <span className="mono ember" style={{ fontSize: 26, fontWeight: 600 }}>47,247</span>
            <span className="lbl-sm muted">总决策</span>
          </div>

          {/* Breakdown rows */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12, marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>自主决策 <span className="dim">— Agent 自行处理</span></span>
              <span className="mono" style={{ color: 'var(--green-400)' }}>46,842 <span className="dim">(99.1%)</span></span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>上报人工 <span className="dim">— 需要人工确认</span></span>
              <span className="mono" style={{ color: 'var(--amber-200)' }}>387 <span className="dim">(0.8%)</span></span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>被否决 <span className="dim">— 人工否决 Agent 决策</span></span>
              <span className="mono" style={{ color: 'var(--ember-500)' }}>18 <span className="dim">(0.04%)</span></span>
            </div>
          </div>

          {/* Progress bar */}
          <div style={{ height: 6, background: 'var(--bg-surface)', borderRadius: 3, display: 'flex', overflow: 'hidden' }}>
            <div style={{ width: '99.1%', background: 'var(--green-400)', borderRadius: '3px 0 0 3px' }} />
            <div style={{ width: '0.8%',  background: 'var(--amber-200)' }} />
            <div style={{ width: '0.1%',  background: 'var(--ember-500)', borderRadius: '0 3px 3px 0' }} />
          </div>
        </Card>

        {/* Right: 三条硬约束拦截 */}
        <Card variant="emphasis">
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 12 }}>
            三条硬约束拦截
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12 }}>
            {/* 毛利底线 */}
            <div style={{ borderBottom: '0.5px dotted var(--border-tertiary)', paddingBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontWeight: 500 }}>毛利底线</span>
                <span className="mono ember">今日拦截 42 次</span>
              </div>
              <div className="muted" style={{ fontSize: 11 }}>累计 ¥184k 风险金额</div>
            </div>

            {/* 食安合规 */}
            <div style={{ borderBottom: '0.5px dotted var(--border-tertiary)', paddingBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontWeight: 500 }}>食安合规</span>
                <span className="mono" style={{ color: 'var(--green-400)' }}>今日 0 触发</span>
              </div>
              <div className="muted" style={{ fontSize: 11 }}>连续安全 127 天</div>
            </div>

            {/* 客户体验 */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontWeight: 500 }}>客户体验</span>
                <span className="mono" style={{ color: 'var(--amber-200)' }}>今日 4 次降级保护</span>
              </div>
              <div className="muted" style={{ fontSize: 11 }}>超时自动降级到人工</div>
            </div>
          </div>
        </Card>
      </div>

      {/* Agent Voice Card */}
      <div style={{ marginBottom: 12 }}>
        <AgentVoiceCard
          level="L2"
          title="MASTER AGENT 风控洞察"
          body="折扣守护已连续3天拦截湘遇华南区异常折扣，建议复核该区域定价策略"
          actions={<>
            <Button variant="primary" size="sm">查看详情</Button>
            <Button variant="ghost" size="sm">已知悉</Button>
          </>}
        />
      </div>

      {/* ══════════════════════════════════════════════
          Section 4: 7 天健康趋势
          ══════════════════════════════════════════════ */}
      <Card>
        <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 14 }}>
          7 天健康趋势
          <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>9 Agent × 7 天</span>
        </div>

        {/* Header row */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '120px repeat(7, 1fr)',
          gap: 4,
          marginBottom: 6
        }}>
          <div />
          {DAYS.map(d => (
            <div key={d} className="mono dim" style={{
              fontSize: 9, textAlign: 'center', textTransform: 'uppercase', letterSpacing: '0.08em'
            }}>{d}</div>
          ))}
        </div>

        {/* Matrix rows */}
        {Object.entries(HEALTH_MATRIX).map(([agentName, days]) => (
          <div key={agentName} style={{
            display: 'grid',
            gridTemplateColumns: '120px repeat(7, 1fr)',
            gap: 4,
            padding: '4px 0',
            borderTop: '0.5px solid var(--border-tertiary)',
            alignItems: 'center'
          }}>
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{agentName}</span>
            {days.map((s, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: HEALTH_COLOR[s],
                  opacity: s === 'green' ? 0.7 : 1,
                  boxShadow: s !== 'green' ? `0 0 4px ${HEALTH_COLOR[s]}` : undefined
                }} />
              </div>
            ))}
          </div>
        ))}

        {/* Legend */}
        <div style={{ display: 'flex', gap: 14, marginTop: 12, fontSize: 10 }}>
          {(['green', 'amber', 'red'] as HealthStatus[]).map(s => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: HEALTH_COLOR[s] }} />
              <span className="dim">{s === 'green' ? '正常' : s === 'amber' ? '降级' : '故障'}</span>
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
