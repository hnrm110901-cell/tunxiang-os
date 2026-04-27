// 财务结算 · 完整页
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

const KPI = [
  { label: '本月GMV',    value: '¥2.10M',  delta: { text: '▲ 18.4%', tone: 'success' as const } },
  { label: '屯象抽佣',   value: '¥630k',   delta: { text: '30% 平均',  tone: 'soft' as const } },
  { label: '应付ISV',    value: '¥1.47M',  delta: { text: '70% 分成',  tone: 'soft' as const } },
  { label: '本月退款',    value: '¥18.4k',  delta: { text: '4 笔待处',  tone: 'soft' as const } },
  { label: '发票待开',    value: '87',      delta: { text: '本月新增',  tone: 'soft' as const } },
]

interface LedgerRow {
  id: string
  isv: string
  products: number
  gmv: string
  gmvNum: number
  ratio: string
  ratioNote: string
  tunxiang: string
  payable: string
  settled: boolean
}

const LEDGER: LedgerRow[] = [
  { id: '1', isv: '屯象官方',     products: 38, gmv: '¥1.42M', gmvNum: 1420000, ratio: '100%', ratioNote: '自营',   tunxiang: '¥1.42M',  payable: '--',      settled: true },
  { id: '2', isv: '长沙青菜科技',  products: 12, gmv: '¥247k',  gmvNum: 247000,  ratio: '30%',  ratioNote: '标准',   tunxiang: '¥74.1k',  payable: '¥172.9k', settled: true },
  { id: '3', isv: '湘味数智',     products: 7,  gmv: '¥84k',   gmvNum: 84000,   ratio: '30%',  ratioNote: '标准',   tunxiang: '¥25.2k',  payable: '¥58.8k',  settled: false },
  { id: '4', isv: '明厨亮灶',     products: 5,  gmv: '¥42k',   gmvNum: 42000,   ratio: '25%',  ratioNote: '金牌',   tunxiang: '¥10.5k',  payable: '¥31.5k',  settled: true },
  { id: '5', isv: '宴会管家',     products: 4,  gmv: '¥38k',   gmvNum: 38000,   ratio: '30%',  ratioNote: '标准',   tunxiang: '¥11.4k',  payable: '¥26.6k',  settled: false },
  { id: '6', isv: '川味数据',     products: 2,  gmv: '¥4.2k',  gmvNum: 4200,    ratio: '35%',  ratioNote: '新人',   tunxiang: '¥1.47k',  payable: '¥2.73k',  settled: false },
]

const LEDGER_COLUMNS: Column<LedgerRow>[] = [
  { key: 'isv',      label: 'ISV',      render: r => <span style={{ fontWeight: 500 }}>{r.isv}</span> },
  { key: 'products', label: '商品数',    render: r => <span className="mono">{r.products}</span>, align: 'right' },
  { key: 'gmv',      label: '本月GMV',   render: r => <span className="mono ember">{r.gmv}</span>, align: 'right' },
  { key: 'ratio',    label: '抽佣比例',  render: r => <span className="mono">{r.ratio} <span className="muted" style={{ fontSize: 10 }}>{r.ratioNote}</span></span>, align: 'right' },
  { key: 'tunxiang', label: '屯象',      render: r => <span className="mono ember-soft">{r.tunxiang}</span>, align: 'right' },
  { key: 'payable',  label: '应付ISV',   render: r => <span className="mono">{r.payable}</span>, align: 'right' },
  { key: 'settled',  label: '结算',      render: r => <Badge kind={r.settled ? 'pass' : 'warn'}>{r.settled ? '已结' : '待结'}</Badge> },
]

const REFUNDS = [
  { isv: '长沙青菜科技', product: '实时客流热力', amount: '¥5,980', reason: '功能不符预期', days: 3 },
  { isv: '湘味数智',     product: '智能排班',    amount: '¥4,200', reason: '重复购买',     days: 5 },
  { isv: '宴会管家',     product: '宴席排期',    amount: '¥3,800', reason: '试用期退款',   days: 1 },
  { isv: '川味数据',     product: '菜品成本分析', amount: '¥4,420', reason: '数据不准确',   days: 7 },
]

const GMV_CHART = [
  { month: '11月', gmv: 1780, commission: 534 },
  { month: '12月', gmv: 1920, commission: 576 },
  { month: '1月',  gmv: 1640, commission: 492 },
  { month: '2月',  gmv: 1380, commission: 414 },
  { month: '3月',  gmv: 1870, commission: 561 },
  { month: '4月',  gmv: 2100, commission: 630 },
]
const GMV_MAX = 2100

export default function FinancePage() {
  return (
    <>
      <PageHeader
        crumb="BUSINESS / 财务结算"
        title="财务结算"
        subtitle="月 GMV ¥2.10M · 抽佣 ¥630k · 70/30 默认"
        actions={<>
          <Button size="sm" variant="ghost">税务报表</Button>
          <Button size="sm" variant="secondary">生成月度结算单</Button>
          <Button size="sm" variant="primary">导出 ¥ 账</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* row-1: 账本 + 右侧卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8, marginBottom: 12 }}>
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>本月抽佣账本 · Top {LEDGER.length}</div>
          <Table columns={LEDGER_COLUMNS} data={LEDGER} rowKey={r => r.id} />
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 抽佣比例策略 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 抽佣比例策略</div>
            {[
              { tier: '顶级 ISV', rate: '15%', color: 'var(--green-400)' },
              { tier: '金牌 ISV', rate: '25%', color: 'var(--blue-400)' },
              { tier: '标准',     rate: '30%', color: 'var(--text-secondary)' },
              { tier: '新人',     rate: '35%', color: 'var(--amber-400)' },
              { tier: 'Labs',     rate: '免费', color: 'var(--ink-400)' },
            ].map(t => (
              <div key={t.tier} style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '3px 0', fontSize: 11,
                borderBottom: '0.5px dotted var(--border-tertiary)'
              }}>
                <span className="dim">{t.tier}</span>
                <span className="mono" style={{ color: t.color }}>{t.rate}</span>
              </div>
            ))}
            <div className="muted" style={{ fontSize: 10, marginTop: 6 }}>年 GMV &gt; ¥500k 可申请金牌；年 GMV &gt; ¥2M 可升顶级</div>
          </Card>

          {/* 结算节奏 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 结算节奏</div>
            {[
              { label: '结算日', value: '每月 5 日' },
              { label: '到账方式', value: 'T+0 电汇' },
              { label: '起付金额', value: '≥ ¥1,000' },
            ].map(s => (
              <div key={s.label} style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '3px 0', fontSize: 11,
                borderBottom: '0.5px dotted var(--border-tertiary)'
              }}>
                <span className="dim">{s.label}</span>
                <span className="mono ember-soft">{s.value}</span>
              </div>
            ))}
          </Card>

          {/* 退款待处理 */}
          <Card variant="warn">
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 退款 · {REFUNDS.length} 笔待处理</div>
            {REFUNDS.map(r => (
              <div key={r.product} style={{
                borderBottom: '0.5px dotted var(--border-tertiary)',
                padding: '4px 0', fontSize: 11
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 500 }}>{r.isv}</span>
                  <span className="mono ember">{r.amount}</span>
                </div>
                <div className="muted" style={{ fontSize: 10 }}>{r.product} · {r.reason} · {r.days}d ago</div>
              </div>
            ))}
          </Card>
        </div>
      </div>

      {/* row-2: 图表 + 发票 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {/* 6月 GMV 与抽佣 - stacked bar */}
        <Card>
          <div className="lbl ember" style={{ marginBottom: 10 }}>— 12月 GMV 与抽佣</div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, height: 100 }}>
            {GMV_CHART.map(m => (
              <div key={m.month} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                <span className="mono muted" style={{ fontSize: 9 }}>¥{m.gmv >= 1000 ? (m.gmv / 1000).toFixed(1) + 'M' : m.gmv + 'k'}</span>
                <div style={{ width: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: 70 }}>
                  <div style={{
                    height: `${(m.commission / GMV_MAX) * 70}px`,
                    background: 'var(--ember-500)',
                    borderRadius: '2px 2px 0 0',
                  }} />
                  <div style={{
                    height: `${((m.gmv - m.commission) / GMV_MAX) * 70}px`,
                    background: 'var(--green-400)',
                    borderRadius: '0 0 2px 2px',
                  }} />
                </div>
                <span className="mono muted" style={{ fontSize: 9 }}>{m.month}</span>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 10 }}>
            <span><span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--ember-500)', borderRadius: 2, marginRight: 4 }} />抽佣</span>
            <span><span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--green-400)', borderRadius: 2, marginRight: 4 }} />ISV 分成</span>
          </div>
        </Card>

        {/* 发票管理 */}
        <Card>
          <div className="lbl ember" style={{ marginBottom: 10 }}>— 发票管理</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              { label: '待开票',   value: 87,  color: 'var(--amber-400)' },
              { label: '开票中',   value: 14,  color: 'var(--blue-400)' },
              { label: '已寄出',   value: 412, color: 'var(--green-400)' },
              { label: '电子发票', value: 847, color: 'var(--text-secondary)' },
            ].map(inv => (
              <div key={inv.label} style={{
                padding: '10px 8px',
                background: 'var(--bg-surface)',
                borderRadius: 6,
                textAlign: 'center'
              }}>
                <div className="mono" style={{ fontSize: 20, color: inv.color, fontWeight: 600 }}>{inv.value}</div>
                <div className="lbl-sm muted" style={{ marginTop: 2 }}>{inv.label}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  )
}
