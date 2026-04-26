// 工作流编排市场 (v3.0)
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '工作流',   value: '12',     delta: { text: '累计',        tone: 'soft'    as const } },
  { label: '活跃',     value: '8',      delta: { text: '运行中',      tone: 'success' as const } },
  { label: '日执行',   value: '847',    delta: { text: '▲ 18% WoW',   tone: 'success' as const } },
  { label: '平均成功率', value: '94.2%', delta: { text: '目标≥95%',   tone: 'success' as const } },
]

interface WorkflowRow {
  id: string
  name: string
  steps: number
  trigger: string
  status: string
  statusBadge: 'active' | 'warn' | 'pass' | 'paused'
  installs: number
  successRate: string
  dailyExec: number
  value: string
}

const WORKFLOWS: WorkflowRow[] = [
  { id: 'w1', name: '午市利润最大化', steps: 4, trigger: 'schedule 11:00',       status: 'active', statusBadge: 'active', installs: 42, successRate: '96%', dailyExec: 124, value: '¥2.4k/月' },
  { id: 'w2', name: '沉睡客户唤醒',   steps: 3, trigger: 'event member.dormant', status: 'active', statusBadge: 'active', installs: 38, successRate: '92%', dailyExec: 87,  value: '¥1.8k/月' },
  { id: 'w3', name: '晚市出餐优化',   steps: 5, trigger: 'schedule 17:00',       status: 'active', statusBadge: 'active', installs: 31, successRate: '94%', dailyExec: 142, value: '¥1.2k/月' },
  { id: 'w4', name: '新品上架全流程', steps: 6, trigger: 'manual',               status: 'active', statusBadge: 'active', installs: 24, successRate: '88%', dailyExec: 12,  value: '--' },
  { id: 'w5', name: '食材成本预警',   steps: 3, trigger: 'event inventory.low',   status: 'active', statusBadge: 'active', installs: 47, successRate: '97%', dailyExec: 247, value: '¥3.6k/月' },
  { id: 'w6', name: '会员生日关怀',   steps: 4, trigger: 'schedule daily 8:00',   status: 'active', statusBadge: 'active', installs: 52, successRate: '99%', dailyExec: 235, value: '¥0.8k/月' },
]

const WORKFLOW_COLS: Column<WorkflowRow>[] = [
  { key: 'name',        label: '工作流',   render: r => <span style={{ fontWeight: 500 }}>{r.name}</span> },
  { key: 'steps',       label: '步骤数',   render: r => <span className="mono">{r.steps} 步</span>, width: 48, align: 'center' },
  { key: 'trigger',     label: '触发方式', render: r => <span className="mono muted" style={{ fontSize: 10 }}>{r.trigger}</span>, width: 120 },
  { key: 'status',      label: '状态',     render: r => <Badge kind={r.statusBadge}>{r.status}</Badge>, width: 56 },
  { key: 'installs',    label: '安装数',   render: r => <span className="mono">{r.installs}</span>, width: 48, align: 'right' },
  { key: 'successRate', label: '成功率',   render: r => {
    const v = parseFloat(r.successRate)
    const c = v >= 95 ? 'var(--green-400)' : v >= 90 ? 'var(--blue-400)' : 'var(--amber-400)'
    return <span className="mono" style={{ color: c }}>{r.successRate}</span>
  }, width: 56, align: 'center' },
  { key: 'dailyExec',   label: '日均执行', render: r => <span className="mono">{r.dailyExec}</span>, width: 56, align: 'right' },
  { key: 'value',       label: '预估价值', render: r => <span className="mono" style={{ color: r.value !== '--' ? 'var(--green-400)' : 'var(--text-tertiary)' }}>{r.value}</span>, width: 72, align: 'right' },
]

const EXAMPLE_STEPS = [
  { num: 1, agent: '客流预测 Agent', action: 'predict_lunch_traffic', output: 'output: 287 人',   color: 'var(--blue-400)' },
  { num: 2, agent: '智能排菜 Agent', action: 'optimize_menu',         output: 'condition: 客流>100', color: 'var(--green-400)' },
  { num: 3, agent: '库存预警 Agent', action: 'check_availability',    output: 'verify ingredients', color: 'var(--amber-400)' },
  { num: 4, agent: '折扣守护 Agent', action: 'validate_pricing',      output: 'constraint: 毛利≥28%', color: 'var(--ember-500)' },
]

export default function WorkflowEditorPage() {
  return (
    <>
      <PageHeader
        crumb="AI OPS / Agent 编排"
        title="工作流编排市场"
        subtitle="不卖零件，卖解决方案 · 12 个工作流 · 日均 847 次执行"
        actions={<>
          <Button size="sm" variant="secondary">执行日志</Button>
          <Button size="sm" variant="primary">创建工作流</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 工作流目录 */}
      <Card style={{ marginBottom: 12 }}>
        <div className="lbl-sm muted" style={{ marginBottom: 8 }}>工作流目录 · {WORKFLOWS.length} 条</div>
        <Table columns={WORKFLOW_COLS} data={WORKFLOWS} rowKey={r => r.id} />
      </Card>

      {/* 工作流示例 */}
      <Card variant="emphasis">
        <div className="lbl-sm" style={{ marginBottom: 12, fontWeight: 600 }}>工作流示例 · 午市利润最大化</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
          {EXAMPLE_STEPS.map((s, i) => (
            <div key={s.num} style={{ position: 'relative' }}>
              <div style={{
                padding: '12px 10px', background: 'var(--bg-surface)', borderRadius: 8,
                borderTop: `3px solid ${s.color}`,
              }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 22, height: 22, borderRadius: '50%', background: s.color,
                  color: '#fff', fontSize: 11, fontWeight: 700, marginBottom: 8,
                }}>
                  {s.num}
                </div>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{s.agent}</div>
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-secondary)',
                  padding: '4px 6px', background: 'var(--bg-base)', borderRadius: 3, marginBottom: 4,
                }}>
                  {s.action}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{s.output}</div>
              </div>
              {i < EXAMPLE_STEPS.length - 1 && (
                <div style={{
                  position: 'absolute', right: -8, top: '50%', transform: 'translateY(-50%)',
                  color: 'var(--text-tertiary)', fontSize: 14, fontWeight: 600, zIndex: 1,
                }}>→</div>
              )}
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 12, padding: '8px 10px', background: 'var(--bg-surface)', borderRadius: 4,
          fontSize: 11, color: 'var(--text-tertiary)', lineHeight: 1.6, textAlign: 'center',
        }}>
          4 个 Agent 串联协作，每天 11:00 自动执行，预估月价值 ¥2.4k
        </div>
      </Card>
    </>
  )
}
