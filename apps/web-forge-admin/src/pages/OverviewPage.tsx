// 总览仪表板 · 完整示范页(其余 12 页参照此结构)
import { PageHeader, KpiCard, Card, Button, AgentVoiceCard } from '@/components/ui'

const KPI = [
  { label: '总商品', value: '723',     delta: { text: '▲ 14 本周',   tone: 'success' as const } },
  { label: '月活 ISV', value: '84',    delta: { text: '▲ 6 本月',    tone: 'success' as const } },
  { label: '月安装', value: '47.2k',   delta: { text: '▲ 18% 同比',  tone: 'success' as const } },
  { label: '月 GMV', value: '¥2.10M',  delta: { text: '抽佣 ¥630k',  tone: 'soft'    as const } },
  { label: '待审核', value: '12',      delta: { text: '3 紧急',       tone: 'soft'    as const }, alert: true }
]

const PRODUCT_DIST = [
  { name: 'Skill',   count: 142, pct: 19.6, color: 'var(--ember-500)' },
  { name: 'Action',  count: 487, pct: 67.0, color: 'var(--green-400)' },
  { name: 'Adapter', count: 38,  pct: 5.3,  color: 'var(--blue-400)'  },
  { name: 'Theme',   count: 24,  pct: 3.3,  color: 'var(--amber-200)' },
  { name: 'Widget',  count: 63,  pct: 8.7,  color: 'var(--ink-400)'   },
  { name: 'Integ.',  count: 29,  pct: 4.0,  color: 'var(--ink-500)'   }
]

const TODOS = [
  { task: '智能配菜 v2.2 待审',   sla: '2h', urgent: true },
  { task: '美团 v4.1 安全扫描',   sla: '4h', urgent: true },
  { task: 'L0-PZ 主题需会签',    sla: '6h', urgent: false },
  { task: '4 ISV 实名待复核',     sla: '明日', urgent: false },
  { task: '本月结算单需签发',     sla: '5d', urgent: false }
]

export default function OverviewPage() {
  return (
    <>
      <PageHeader
        crumb="CORE / 总览"
        title="Forge 管理仪表板"
        subtitle="2026-04-25 · Forge Ops · 张工"
        actions={<>
          <Button size="sm" variant="ghost">导出周报</Button>
          <Button size="sm" variant="secondary">通知中心</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8, marginBottom: 12 }}>
        <Card>
          <div style={{ marginBottom: 10, fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>商品类型分布 · 723 件</div>
          <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr 40px', gap: 6, fontSize: 11, lineHeight: 2.2, alignItems: 'center' }}>
            {PRODUCT_DIST.map(p => (
              <>
                <span key={`${p.name}-l`} style={{ color: p.color }}>{p.name}</span>
                <div key={`${p.name}-b`} style={{ height: 6, background: 'var(--bg-surface)', borderRadius: 3 }}>
                  <div style={{ width: `${p.pct}%`, height: '100%', background: p.color, borderRadius: 3 }} />
                </div>
                <span key={`${p.name}-c`} className="mono muted" style={{ textAlign: 'right' }}>{p.count}</span>
              </>
            ))}
          </div>
        </Card>

        <Card variant="emphasis">
          <div className="lbl ember" style={{ marginBottom: 8 }}>— TODO · 今日 12</div>
          {TODOS.map(t => (
            <div key={t.task} style={{
              display: 'flex',
              justifyContent: 'space-between',
              borderBottom: '0.5px dotted var(--border-tertiary)',
              padding: '3px 0',
              fontSize: 11
            }}>
              <span>{t.task}</span>
              <span className="mono" style={{ color: t.urgent ? 'var(--ember-500)' : 'var(--text-tertiary)' }}>{t.sla}</span>
            </div>
          ))}
        </Card>
      </div>

      <AgentVoiceCard
        level="L2"
        title="MASTER AGENT 建议"
        body="湘遇华南6店毛利穿透底线 · 折扣守护 Agent 已拦截 4 张异常优惠 · 建议复核"
        actions={<>
          <Button variant="primary" size="sm">查看根因</Button>
          <Button variant="ghost" size="sm">忽略</Button>
        </>}
      />
    </>
  )
}
