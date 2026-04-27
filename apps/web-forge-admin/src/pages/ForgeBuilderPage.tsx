// Forge Agent 构建器 (v2.5)
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '活跃项目', value: '24',  delta: { text: '累计',       tone: 'soft'    as const } },
  { label: '已提交',   value: '18',  delta: { text: '▲ 4 本月',   tone: 'success' as const } },
  { label: '通过率',   value: '72%', delta: { text: '目标≥80%',   tone: 'success' as const } },
  { label: 'TTHW',     value: '47 min', delta: { text: '目标≤15 min', tone: 'warn' as const }, alert: true },
]

const TEMPLATES = [
  { id: 't1', icon: '📊', name: '数据分析型', desc: '从多源数据中提取洞察，生成报表与可视化建议', usage: 124 },
  { id: 't2', icon: '⚡', name: '自动化执行型', desc: '监听事件触发自动化流程，减少人工干预', usage: 87 },
  { id: 't3', icon: '💬', name: '对话交互型', desc: '与门店人员自然对话，解答问题并执行指令', usage: 64 },
  { id: 't4', icon: '🔔', name: '监控预警型', desc: '持续监控业务指标，异常时主动预警推送', usage: 42 },
  { id: 't5', icon: '🧠', name: '优化决策型', desc: '基于历史数据与约束条件，输出最优决策方案', usage: 31 },
]

interface ProjectRow {
  id: string
  name: string
  developer: string
  template: string
  status: string
  statusBadge: 'active' | 'warn' | 'pass' | 'paused'
  created: string
}

const PROJECTS: ProjectRow[] = [
  { id: 'p1', name: '午市客流预测',     developer: '长沙青菜', template: '数据分析型', status: 'preview',   statusBadge: 'active', created: '04-20' },
  { id: 'p2', name: '沉睡会员唤醒',     developer: '湘味数智', template: '自动化执行型', status: 'submitted', statusBadge: 'pass',   created: '04-18' },
  { id: 'p3', name: '智能客服助手',       developer: '屯象官方', template: '对话交互型', status: 'building',  statusBadge: 'warn',   created: '04-22' },
  { id: 'p4', name: '食材过期预警',       developer: '明厨亮灶', template: '监控预警型', status: 'submitted', statusBadge: 'pass',   created: '04-15' },
  { id: 'p5', name: '排菜毛利优化',       developer: '宴会管家', template: '优化决策型', status: 'draft',     statusBadge: 'paused', created: '04-24' },
  { id: 'p6', name: '外卖出餐节奏',       developer: '川味数据', template: '自动化执行型', status: 'draft',     statusBadge: 'paused', created: '04-25' },
]

const PROJECT_COLS: Column<ProjectRow>[] = [
  { key: 'name',      label: '项目',    render: r => <span style={{ fontWeight: 500 }}>{r.name}</span> },
  { key: 'developer', label: '开发者',  render: r => <span className="muted">{r.developer}</span>, width: 80 },
  { key: 'template',  label: '模板',    render: r => <span className="muted">{r.template}</span>, width: 96 },
  { key: 'status',    label: '状态',    render: r => <Badge kind={r.statusBadge}>{r.status}</Badge>, width: 72 },
  { key: 'created',   label: '创建时间', render: r => <span className="mono muted">{r.created}</span>, width: 72, align: 'right' },
]

const FUNNEL = [
  { step: '注册',         count: 247, pct: 100,  color: 'var(--green-400)' },
  { step: 'SDK 安装',     count: 184, pct: 74.5, color: 'var(--green-400)' },
  { step: '首次提交',     count: 87,  pct: 35.2, color: 'var(--blue-400)'  },
  { step: '获 10+ 试用',  count: 42,  pct: 17.0, color: 'var(--amber-400)' },
  { step: '毕业 GA',      count: 18,  pct: 7.3,  color: 'var(--amber-400)' },
]

export default function ForgeBuilderPage() {
  return (
    <>
      <PageHeader
        crumb="ECOSYSTEM / Forge Builder"
        title="Forge Agent 构建器"
        subtitle="5 种模板 · 24 个活跃项目 · TTHW 47→15 min"
        actions={<>
          <Button size="sm" variant="secondary">模板库</Button>
          <Button size="sm" variant="primary">新建项目</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* 左栏 - 5种Agent模板 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 10 }}>5 种 Agent 模板</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {TEMPLATES.map(t => (
              <div key={t.id} style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 10px', background: 'var(--bg-surface)', borderRadius: 6,
              }}>
                <span style={{ fontSize: 20, width: 32, textAlign: 'center' }}>{t.icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: 12, marginBottom: 2 }}>{t.name}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-tertiary)', lineHeight: 1.4 }}>{t.desc}</div>
                </div>
                <span className="mono muted" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>使用 {t.usage} 次</span>
                <Button size="sm" variant="ghost">使用</Button>
              </div>
            ))}
          </div>
        </Card>

        {/* 右栏 - 最近项目 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 8 }}>最近项目 · {PROJECTS.length} 个</div>
          <Table columns={PROJECT_COLS} data={PROJECTS} rowKey={r => r.id} />
        </Card>
      </div>

      {/* 开发者旅程漏斗 */}
      <Card>
        <div className="lbl-sm muted" style={{ marginBottom: 10 }}>开发者旅程漏斗</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {FUNNEL.map(f => (
            <div key={f.step} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 72px', gap: 8, alignItems: 'center', fontSize: 11 }}>
              <span style={{ fontWeight: 500 }}>{f.step}</span>
              <div style={{ height: 10, background: 'var(--bg-surface)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${f.pct}%`, height: '100%', background: f.color, borderRadius: 4, transition: 'width 0.3s ease' }} />
              </div>
              <span className="mono" style={{ textAlign: 'right', color: f.pct <= 10 ? 'var(--ember-500)' : 'var(--text-secondary)' }}>
                {f.count} ({f.pct}%)
              </span>
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 12, padding: '8px 10px', background: 'var(--bg-surface)', borderRadius: 4,
          fontSize: 11, color: 'var(--amber-400)', lineHeight: 1.6,
        }}>
          瓶颈分析: <span style={{ fontWeight: 500 }}>SDK 安装 → 首次提交</span> 流失最大 (53%)，建议增加脚手架模板
        </div>
      </Card>
    </>
  )
}
