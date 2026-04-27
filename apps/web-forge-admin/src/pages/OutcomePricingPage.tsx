// 结果计价引擎 · 按可量化业务结果计费
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

const KPI = [
  { label: '结果定义',     value: '24',      delta: { text: '个活跃',      tone: 'soft'    as const } },
  { label: '本月结果事件',  value: '1,247',   delta: { text: '次归因',      tone: 'soft'    as const } },
  { label: '已验证',       value: '1,184',   delta: { text: '94.9%',       tone: 'success' as const } },
  { label: '结果收入',     value: '¥42.8k',  delta: { text: '▲ 22.1%',    tone: 'success' as const } },
  { label: '平均每结果',   value: '¥34.3',   delta: { text: '/次',         tone: 'soft'    as const } },
]

interface OutcomeRow {
  id: string
  name: string
  app: string
  type: string
  price: string
  window: string
  verify: string
  count: number
  revenue: string
}

const OUTCOME_DATA: OutcomeRow[] = [
  { id: '1', name: '推荐接受', app: '智能配菜',   type: 'recommendation_accepted', price: '¥5',  window: '24h', verify: 'auto',   count: 412, revenue: '¥2,060' },
  { id: '2', name: '流失挽回', app: '会员洞察',   type: 'churn_prevented',         price: '¥15', window: '72h', verify: 'hybrid', count: 87,  revenue: '¥1,305' },
  { id: '3', name: '客诉解决', app: '智能客服',   type: 'complaint_resolved',      price: '¥8',  window: '48h', verify: 'auto',   count: 142, revenue: '¥1,136' },
  { id: '4', name: '成本节约', app: '库存预警',   type: 'cost_saved',              price: '¥3',  window: '24h', verify: 'auto',   count: 324, revenue: '¥972' },
  { id: '5', name: '营收提升', app: '动态定价',   type: 'revenue_lift',            price: '¥10', window: '24h', verify: 'auto',   count: 64,  revenue: '¥640' },
  { id: '6', name: '转化成功', app: '私域运营',   type: 'conversion',              price: '¥12', window: '48h', verify: 'hybrid', count: 47,  revenue: '¥564' },
  { id: '7', name: '加购成功', app: '菜品推荐',   type: 'upsell_success',          price: '¥5',  window: '24h', verify: 'auto',   count: 89,  revenue: '¥445' },
  { id: '8', name: '复购驱动', app: '支付后营销', type: 'retention',               price: '¥8',  window: '72h', verify: 'auto',   count: 82,  revenue: '¥656' },
]

const OUTCOME_COLS: Column<OutcomeRow>[] = [
  { key: 'name',    label: '结果名称', render: r => <span style={{ fontWeight: 500 }}>{r.name}</span>, width: 90 },
  { key: 'app',     label: '应用',     render: r => <span className="muted">{r.app}</span>, width: 80 },
  { key: 'type',    label: '类型',     render: r => <span className="mono dim" style={{ fontSize: 10 }}>{r.type}</span>, width: 140 },
  { key: 'price',   label: '单价',     render: r => <span className="mono ember">{r.price}</span>, width: 56, align: 'right' },
  { key: 'window',  label: '归因窗口', render: r => <span className="mono muted">{r.window}</span>, width: 72, align: 'center' },
  { key: 'verify',  label: '验证方式', render: r => <Badge kind={r.verify === 'auto' ? 'pass' : 'warn'}>{r.verify}</Badge>, width: 72, align: 'center' },
  { key: 'count',   label: '本月次数', render: r => <span className="mono">{r.count}</span>, width: 72, align: 'right' },
  { key: 'revenue', label: '本月收入', render: r => <span className="mono ember">{r.revenue}</span>, width: 80, align: 'right' },
]

const TREND_HEIGHTS = [
  38, 42, 35, 50, 44, 48, 52, 46, 40, 55, 60, 58, 54, 48, 62, 70,
  65, 58, 72, 68, 74, 78, 70, 66, 80, 75, 82, 78, 85, 90,
]

export default function OutcomePricingPage() {
  return (
    <>
      <PageHeader
        crumb="BUSINESS / 结果计价"
        title="结果计价引擎"
        subtitle="按可量化业务结果计费 · 本月 ¥42.8k 结果收入 · 1,247 次归因"
        actions={<>
          <Button size="sm" variant="ghost">定义管理</Button>
          <Button size="sm" variant="secondary">归因报告</Button>
          <Button size="sm" variant="primary">导出账单</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* row-1: 结果定义表 + 右侧卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8, marginBottom: 12 }}>
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>结果定义 · {OUTCOME_DATA.length} 个</div>
          <Table columns={OUTCOME_COLS} data={OUTCOME_DATA} rowKey={r => r.id} />
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 归因链路示例 */}
          <Card variant="emphasis">
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 归因链路示例</div>
            <div style={{ fontSize: 11 }}>
              {['Agent决策', '门店执行', '客户行为', '结果确认', '收入计算'].map((step, i) => (
                <span key={step}>
                  <span style={{ fontWeight: 500, color: 'var(--ember-400)' }}>{step}</span>
                  {i < 4 && <span className="dim" style={{ margin: '0 6px' }}>&rarr;</span>}
                </span>
              ))}
            </div>
            <div style={{
              marginTop: 10, padding: '8px 10px',
              background: 'var(--bg-surface)', borderRadius: 6, fontSize: 11
            }}>
              <div className="muted" style={{ marginBottom: 4 }}>具体示例</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 500 }}>智能配菜推荐鲈鱼</span>
                <span className="dim">&rarr;</span>
                <span>服务员推荐</span>
                <span className="dim">&rarr;</span>
                <span>客户接受</span>
                <span className="dim">&rarr;</span>
                <span className="mono ember">¥5归因</span>
              </div>
            </div>
          </Card>

          {/* 三层定价模型 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 三层定价模型</div>
            {[
              { layer: 'Layer 1', name: '基础订阅', detail: '¥299/月', note: '访问权', color: 'var(--blue-400)' },
              { layer: 'Layer 2', name: 'Token',    detail: '¥0.02/千Token', note: '推理成本', color: 'var(--green-400)' },
              { layer: 'Layer 3', name: '结果',     detail: '¥5/次推荐接受', note: '价值创造', color: 'var(--ember-400)' },
            ].map((l, i) => (
              <div key={l.layer} style={{
                display: 'grid', gridTemplateColumns: '56px 1fr auto',
                gap: 8, alignItems: 'center',
                padding: '6px 0',
                borderBottom: i < 2 ? '0.5px dotted var(--border-tertiary)' : 'none'
              }}>
                <span className="mono" style={{ fontSize: 10, color: l.color }}>{l.layer}</span>
                <div>
                  <div style={{ fontWeight: 500, fontSize: 12 }}>{l.name}</div>
                  <div className="muted" style={{ fontSize: 10 }}>{l.note}</div>
                </div>
                <span className="mono ember-soft" style={{ fontSize: 12 }}>{l.detail}</span>
              </div>
            ))}
          </Card>
        </div>
      </div>

      {/* row-2: 结果收入趋势 */}
      <Card>
        <div className="lbl ember" style={{ marginBottom: 10 }}>— 结果收入趋势 · 30天</div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 100 }}>
          {TREND_HEIGHTS.map((h, i) => (
            <div key={i} style={{
              flex: 1,
              height: h,
              background: `var(--ember-${i >= 25 ? '400' : '600'})`,
              borderRadius: '2px 2px 0 0',
              opacity: 0.6 + (h / 90) * 0.4,
            }} />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <span className="mono muted" style={{ fontSize: 9 }}>30天前</span>
          <span className="mono muted" style={{ fontSize: 9 }}>今天</span>
        </div>
      </Card>
    </>
  )
}
