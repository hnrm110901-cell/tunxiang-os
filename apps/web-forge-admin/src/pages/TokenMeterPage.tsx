// Token 用量与计费 · 应用级 Token 计量
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

const KPI = [
  { label: '本月Token',   value: '47.2M',  delta: { text: '总消耗',    tone: 'soft'    as const } },
  { label: '成本',        value: '¥28.4k', delta: { text: '▲ 12.3%',  tone: 'soft'    as const } },
  { label: '日均',        value: '1.57M',  delta: { text: 'Token/天',  tone: 'soft'    as const } },
  { label: '预算使用率',   value: '81%',    delta: { text: '¥35k预算',  tone: 'soft'    as const } },
  { label: '超预算应用',   value: '2',      delta: { text: '需关注',    tone: 'danger'  as const } },
  { label: '成本/千次',   value: '¥0.20',  delta: { text: '平均',      tone: 'soft'    as const } },
]

interface TokenRow {
  id: string
  app: string
  input: string
  output: string
  total: string
  cost: string
  budget: string
  usage: number
}

const TOKEN_DATA: TokenRow[] = [
  { id: '1', app: '智能配菜',   input: '4.2M',  output: '2.8M',  total: '7.0M',  cost: '¥4,200',  budget: '¥5,000',  usage: 84 },
  { id: '2', app: '会员洞察',   input: '3.8M',  output: '2.4M',  total: '6.2M',  cost: '¥3,720',  budget: '¥4,000',  usage: 93 },
  { id: '3', app: '智能客服',   input: '5.1M',  output: '3.2M',  total: '8.3M',  cost: '¥4,980',  budget: '¥5,500',  usage: 91 },
  { id: '4', app: '库存预警',   input: '2.4M',  output: '1.1M',  total: '3.5M',  cost: '¥2,100',  budget: '¥3,000',  usage: 70 },
  { id: '5', app: '动态定价',   input: '3.2M',  output: '2.0M',  total: '5.2M',  cost: '¥3,120',  budget: '¥4,000',  usage: 78 },
  { id: '6', app: '私域运营',   input: '2.8M',  output: '1.8M',  total: '4.6M',  cost: '¥2,760',  budget: '¥3,500',  usage: 79 },
  { id: '7', app: '菜品推荐',   input: '3.6M',  output: '2.2M',  total: '5.8M',  cost: '¥3,480',  budget: '¥4,500',  usage: 77 },
  { id: '8', app: '支付后营销', input: '2.6M',  output: '1.4M',  total: '4.0M',  cost: '¥2,400',  budget: '¥3,000',  usage: 80 },
]

const usageColor = (pct: number) => pct >= 90 ? 'var(--ember-500)' : pct >= 80 ? 'var(--amber-400)' : 'var(--green-400)'

const TOKEN_COLS: Column<TokenRow>[] = [
  { key: 'app',    label: '应用',      render: r => <span style={{ fontWeight: 500 }}>{r.app}</span>, width: 90 },
  { key: 'input',  label: '本月Input', render: r => <span className="mono muted">{r.input}</span>, width: 80, align: 'right' },
  { key: 'output', label: '本月Output', render: r => <span className="mono muted">{r.output}</span>, width: 80, align: 'right' },
  { key: 'total',  label: '总Token',   render: r => <span className="mono">{r.total}</span>, width: 72, align: 'right' },
  { key: 'cost',   label: '成本',      render: r => <span className="mono ember">{r.cost}</span>, width: 72, align: 'right' },
  { key: 'budget', label: '预算',      render: r => <span className="mono muted">{r.budget}</span>, width: 72, align: 'right' },
  { key: 'usage',  label: '使用率',    render: r => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--bg-surface)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${r.usage}%`, height: '100%', background: usageColor(r.usage), borderRadius: 3 }} />
      </div>
      <span className="mono" style={{ fontSize: 10, color: usageColor(r.usage), minWidth: 28 }}>{r.usage}%</span>
    </div>
  ), width: 120 },
]

const PRICING_CONFIG = [
  { app: '智能配菜', inputPrice: '¥0.015', outputPrice: '¥0.020' },
  { app: '会员洞察', inputPrice: '¥0.018', outputPrice: '¥0.024' },
  { app: '智能客服', inputPrice: '¥0.012', outputPrice: '¥0.016' },
  { app: '动态定价', inputPrice: '¥0.020', outputPrice: '¥0.028' },
]

const BUDGET_ALERTS = [
  { app: '会员洞察', usage: 93, budget: '¥4,000', forecast: '¥4,300', overage: '¥300' },
  { app: '智能客服', usage: 91, budget: '¥5,500', forecast: '¥5,940', overage: '¥440' },
]

const COST_TIPS = [
  { title: '启用 Prompt 缓存', saving: '¥2.1k/月', desc: '智能配菜 56% 重复 Prompt 可缓存' },
  { title: '切换轻量模型',       saving: '¥1.8k/月', desc: '库存预警简单查询可用 Haiku 替代' },
  { title: '批处理窗口合并',     saving: '¥0.9k/月', desc: '支付后营销可批量推理降低开销' },
]

export default function TokenMeterPage() {
  return (
    <>
      <PageHeader
        crumb="BUSINESS / Token 计量"
        title="Token 用量与计费"
        subtitle="本月 47.2M Token · ¥28.4k 成本 · 12 应用计量"
        actions={<>
          <Button size="sm" variant="ghost">定价配置</Button>
          <Button size="sm" variant="secondary">预算管理</Button>
          <Button size="sm" variant="primary">成本报告</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* row-1: Token排行 + 右侧卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8, marginBottom: 12 }}>
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>应用Token使用排行 · {TOKEN_DATA.length} 应用</div>
          <Table columns={TOKEN_COLS} data={TOKEN_DATA} rowKey={r => r.id} />
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* Token定价配置 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 8 }}>— Token定价配置</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: '4px 12px', fontSize: 11, alignItems: 'center' }}>
              <span className="lbl-sm muted">应用</span>
              <span className="lbl-sm muted">Input/千</span>
              <span className="lbl-sm muted">Output/千</span>
              {PRICING_CONFIG.map(p => [
                <span key={`${p.app}-n`} style={{ fontWeight: 500, padding: '3px 0', borderBottom: '0.5px dotted var(--border-tertiary)' }}>{p.app}</span>,
                <span key={`${p.app}-i`} className="mono ember-soft" style={{ padding: '3px 0', borderBottom: '0.5px dotted var(--border-tertiary)' }}>{p.inputPrice}</span>,
                <span key={`${p.app}-o`} className="mono ember-soft" style={{ padding: '3px 0', borderBottom: '0.5px dotted var(--border-tertiary)' }}>{p.outputPrice}</span>,
              ])}
            </div>
          </Card>

          {/* 预算预警 */}
          <Card variant="warn">
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 预算预警 · {BUDGET_ALERTS.length} 应用</div>
            {BUDGET_ALERTS.map((a, i) => (
              <div key={a.app} style={{
                padding: '6px 0', fontSize: 11,
                borderBottom: i < BUDGET_ALERTS.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ fontWeight: 500 }}>{a.app}</span>
                  <Badge kind="warn">{a.usage}%</Badge>
                </div>
                <div className="muted">
                  预算 {a.budget} · 预计 {a.forecast} · 超出 <span className="ember">{a.overage}</span>
                </div>
              </div>
            ))}
          </Card>

          {/* 成本优化建议 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 成本优化建议</div>
            {COST_TIPS.map((t, i) => (
              <div key={t.title} style={{
                padding: '6px 0', fontSize: 11,
                borderBottom: i < COST_TIPS.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <span style={{ fontWeight: 500 }}>{t.title}</span>
                  <span className="mono" style={{ color: 'var(--green-400)' }}>-{t.saving}</span>
                </div>
                <div className="muted">{t.desc}</div>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  )
}
