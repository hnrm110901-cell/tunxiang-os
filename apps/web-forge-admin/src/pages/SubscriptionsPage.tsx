// 安装订阅 · 完整页面
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

const KPI = [
  { label: '活跃订阅', value: '14,287', delta: { text: '▲ 8.4%', tone: 'success' as const } },
  { label: '本月新签', value: '1,247',  delta: { text: '▲ 12%',  tone: 'success' as const } },
  { label: '试用中',   value: '1,847',  delta: { text: '本月启动', tone: 'soft' as const } },
  { label: '试用→付费', value: '38.2%', delta: { text: '▲ 4.1%', tone: 'success' as const } },
  { label: '退订率',   value: '8.2%',   delta: { text: '312 笔',  tone: 'soft' as const } },
]

/* ── 最近订阅活动 ── */
interface SubActivity {
  id: string
  time: string
  product: string
  action: string
  actionKind: 'active' | 'pass' | 'warn' | 'fail' | 'labs'
  customer: string
  amount: string
}

const ACTIVITIES: SubActivity[] = [
  { id: '1', time: '12:31', product: '智能配菜',     action: '订阅',  actionKind: 'active', customer: '湘遇·华南旗舰店', amount: '+¥299' },
  { id: '2', time: '12:18', product: '美团外卖',     action: '安装',  actionKind: 'pass',   customer: '渝味·朝阳SOHO',   amount: '免费' },
  { id: '3', time: '12:04', product: 'L0-PZ 主题',   action: '安装',  actionKind: 'pass',   customer: '品智移民·总部',   amount: '免费' },
  { id: '4', time: '11:57', product: '春节流量预测', action: '试用',  actionKind: 'labs',   customer: '小龙坎·春熙路',   amount: '--' },
  { id: '5', time: '11:42', product: '夜间增亮',     action: '退订',  actionKind: 'fail',   customer: '张姐烧烤·万达',   amount: '--' },
  { id: '6', time: '11:30', product: '客流热力图',   action: '续费',  actionKind: 'active', customer: '乡村基·解放碑',   amount: '+¥199' },
]

const ACT_COLUMNS: Column<SubActivity>[] = [
  { key: 'time',     label: '时间', render: r => <span className="mono muted">{r.time}</span> },
  { key: 'product',  label: '商品', render: r => <span style={{ fontWeight: 500 }}>{r.product}</span> },
  { key: 'action',   label: '动作', render: r => <Badge kind={r.actionKind}>{r.action}</Badge> },
  { key: 'customer', label: '客户(店)', render: r => r.customer },
  { key: 'amount',   label: '金额', render: r => <span className="mono ember">{r.amount}</span>, align: 'right' },
]

/* ── 试用转化漏斗 ── */
const FUNNEL = [
  { stage: '试用启动',   value: 2847, pct: 100 },
  { stage: '用满 7 天',  value: 1924, pct: 67.6 },
  { stage: '转付费',     value: 1087, pct: 38.2 },
]

/* ── 退订 Top 原因 ── */
const CHURN_REASONS = [
  { reason: '价格过高',     pct: 38 },
  { reason: '功能不符',     pct: 24 },
  { reason: '员工不会用',   pct: 18 },
  { reason: '与现有冲突',   pct: 12 },
  { reason: '店关张',       pct: 8 },
]

export default function SubscriptionsPage() {
  return (
    <>
      <PageHeader
        crumb="ECOSYSTEM / 安装订阅"
        title="安装与订阅"
        subtitle="活跃订阅 14,287 · 试用 1,847 · 本月退订 312"
        actions={<>
          <Button size="sm" variant="ghost">导出账单</Button>
          <Button size="sm" variant="secondary">退订原因汇总</Button>
        </>}
      />

      {/* KPI 行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 主体 row-1-3 */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* 左：最近订阅活动表 */}
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>最近订阅活动</div>
          <Table columns={ACT_COLUMNS} data={ACTIVITIES} rowKey={r => r.id} />
        </Card>

        {/* 右侧面板 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 试用转化漏斗 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 10 }}>试用转化漏斗</div>
            {FUNNEL.map((f, i) => (
              <div key={f.stage} style={{ marginBottom: i < FUNNEL.length - 1 ? 10 : 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
                  <span>{f.stage}</span>
                  <span className="mono ember-soft">{f.value.toLocaleString()} / {f.pct}%</span>
                </div>
                <div style={{ height: 6, background: 'var(--bg-surface)', borderRadius: 3 }}>
                  <div style={{
                    width: `${f.pct}%`,
                    height: '100%',
                    background: i === 0 ? 'var(--ember-500)' : i === 1 ? 'var(--amber-200)' : 'var(--green-400)',
                    borderRadius: 3,
                  }} />
                </div>
              </div>
            ))}
          </Card>

          {/* 退订 Top 原因 */}
          <Card variant="emphasis">
            <div className="lbl ember" style={{ marginBottom: 10 }}>退订 Top 原因</div>
            {CHURN_REASONS.map(c => (
              <div key={c.reason} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
                  <span>{c.reason}</span>
                  <span className="mono ember-soft">{c.pct}%</span>
                </div>
                <div style={{ height: 5, background: 'var(--bg-surface)', borderRadius: 3 }}>
                  <div style={{
                    width: `${c.pct}%`,
                    height: '100%',
                    background: c.pct >= 30 ? 'var(--ember-500)' : 'var(--ink-400)',
                    borderRadius: 3,
                  }} />
                </div>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  )
}
