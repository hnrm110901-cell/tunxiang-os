// 运行时沙箱 · 策略管控 + 违规流 + Token预算 + OWASP检查
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '运行中',   value: '47',  delta: { text: '全部正常',   tone: 'success' as const } },
  { label: '沙箱模式', value: '7',   delta: { text: 'T0/T1 隔离', tone: 'soft'    as const } },
  { label: '已熔断',   value: '1',   delta: { text: '桌台合并',   tone: 'soft'    as const }, alert: true },
  { label: '本月违规', value: '23',  delta: { text: '▼ 8 环比',   tone: 'success' as const } },
]

/* ─── 策略表 ─── */
interface PolicyRow {
  id: string
  app: string
  tier: string
  tokenBudget: string
  rateLimit: string
  sandbox: boolean
  killSwitch: boolean
}

const POLICY_DATA: PolicyRow[] = [
  { id: 'p1', app: '智能配菜',      tier: 'T4', tokenBudget: '500k/日',  rateLimit: '1000/min', sandbox: false, killSwitch: false },
  { id: 'p2', app: '美团 Adapter',  tier: 'T4', tokenBudget: '800k/日',  rateLimit: '2000/min', sandbox: false, killSwitch: false },
  { id: 'p3', app: '折扣守护',      tier: 'T4', tokenBudget: '300k/日',  rateLimit: '500/min',  sandbox: false, killSwitch: false },
  { id: 'p4', app: '实时客流热力',   tier: 'T2', tokenBudget: '100k/日',  rateLimit: '200/min',  sandbox: false, killSwitch: false },
  { id: 'p5', app: '抖音营销',      tier: 'T2', tokenBudget: '80k/日',   rateLimit: '100/min',  sandbox: false, killSwitch: false },
  { id: 'p6', app: '桌台合并',      tier: 'T1', tokenBudget: '20k/日',   rateLimit: '50/min',   sandbox: true,  killSwitch: true },
  { id: 'p7', app: '春节流量预测',   tier: 'T0', tokenBudget: '10k/日',   rateLimit: '20/min',   sandbox: true,  killSwitch: false },
  { id: 'p8', app: '川菜动态定价',   tier: 'T1', tokenBudget: '30k/日',   rateLimit: '50/min',   sandbox: true,  killSwitch: false },
]

const POLICY_COLS: Column<PolicyRow>[] = [
  { key: 'app',         label: '应用',     render: r => <span style={{ fontWeight: 500 }}>{r.app}</span>, width: 120 },
  { key: 'tier',        label: '信任等级',  render: r => <Badge kind={r.tier === 'T4' ? 'official' : r.tier === 'T3' ? 'integration' : r.tier === 'T2' ? 'isv' : r.tier === 'T1' ? 'skill' : 'labs'}>{r.tier}</Badge>, width: 72, align: 'center' },
  { key: 'tokenBudget', label: 'Token预算/日', render: r => <span className="mono muted">{r.tokenBudget}</span>, width: 90 },
  { key: 'rateLimit',   label: '速率限制',  render: r => <span className="mono muted">{r.rateLimit}</span>, width: 90 },
  { key: 'sandbox',     label: '沙箱模式',  render: r => r.sandbox
    ? <Badge kind="warn">沙箱</Badge>
    : <span className="dim">—</span>, width: 72, align: 'center' },
  { key: 'killSwitch',  label: '熔断',     render: r => r.killSwitch
    ? <span className="mono" style={{ color: 'var(--ember-500)', fontWeight: 600 }}>KILLED</span>
    : <span className="dim">—</span>, width: 64, align: 'center' },
  { key: 'op',          label: '操作',     render: r => r.killSwitch
    ? <Button size="sm" variant="ghost" style={{ color: 'var(--green-400)' }}>恢复</Button>
    : <Button size="sm" variant="ghost">编辑</Button>, width: 64, align: 'center' },
]

/* ─── 实时违规流 ─── */
const VIOLATIONS = [
  { time: '12:42:18', app: '抖音营销',    type: '权限越界',   severity: 'fail' as const,  desc: '未授权读取 Customer.phone 字段' },
  { time: '12:38:04', app: '桌台合并',    type: 'Token超额',  severity: 'warn' as const,  desc: '日 Token 用量达预算 120%，触发熔断' },
  { time: '11:57:22', app: '川菜动态定价', type: '速率违规',   severity: 'warn' as const,  desc: '1分钟内 78 次调用，超 50/min 限制' },
  { time: '11:12:45', app: '抖音营销',    type: 'Prompt注入', severity: 'fail' as const,  desc: '检测到恶意 Prompt 模板注入尝试' },
  { time: '10:34:11', app: '春节流量预测', type: '沙箱逃逸',   severity: 'warn' as const,  desc: '尝试访问沙箱外 Store 实体，已拦截' },
]

/* ─── Token 预算使用率 ─── */
const TOKEN_USAGE = [
  { app: '美团 Adapter',  used: 624000, budget: 800000, pct: 78 },
  { app: '智能配菜',      used: 412000, budget: 500000, pct: 82 },
  { app: '折扣守护',      used: 147000, budget: 300000, pct: 49 },
  { app: '实时客流热力',   used: 87000,  budget: 100000, pct: 87 },
  { app: '抖音营销',      used: 96000,  budget: 80000,  pct: 120 },
]

/* ─── OWASP Agentic Top 10 ─── */
const OWASP_ITEMS = [
  { id: 'A01', name: 'Prompt Injection',            status: 'pass' as const },
  { id: 'A02', name: 'Insecure Output Handling',    status: 'pass' as const },
  { id: 'A03', name: 'Tool/Function Call Risk',     status: 'warn' as const },
  { id: 'A04', name: 'Excessive Agency',            status: 'pass' as const },
  { id: 'A05', name: 'Insecure Plugin Design',      status: 'pass' as const },
  { id: 'A06', name: 'Information Disclosure',       status: 'warn' as const },
  { id: 'A07', name: 'Denial of Service',           status: 'pass' as const },
  { id: 'A08', name: 'Sensitive Data Exposure',     status: 'pass' as const },
  { id: 'A09', name: 'Supply Chain Compromise',     status: 'pass' as const },
  { id: 'A10', name: 'Improper Error Handling',     status: 'pass' as const },
]

export default function RuntimePolicyPage() {
  return (
    <>
      <PageHeader
        crumb="AI OPS / 运行时策略"
        title="运行时沙箱"
        subtitle="实时策略管控 · 47 应用运行中 · 1 已熔断"
        actions={<>
          <Button size="sm" variant="ghost">全局策略</Button>
          <Button size="sm" variant="secondary">违规报告</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 2列布局 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* 左：策略概览 */}
        <Card>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 10 }}>
            策略概览
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>8 应用</span>
          </div>
          <Table columns={POLICY_COLS} data={POLICY_DATA} rowKey={r => r.id} />
        </Card>

        {/* 右：违规 + Token + OWASP */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 实时违规流 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>实时违规流</div>
            {VIOLATIONS.map((v, i) => (
              <div key={v.time} style={{
                padding: '6px 0',
                borderBottom: i < VIOLATIONS.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
                fontSize: 11
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className="mono dim">{v.time}</span>
                    <span style={{ fontWeight: 500 }}>{v.app}</span>
                  </div>
                  <Badge kind={v.severity}>{v.type}</Badge>
                </div>
                <div className="muted">{v.desc}</div>
              </div>
            ))}
          </Card>

          {/* Token 预算使用率 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>Token 预算使用率</div>
            {TOKEN_USAGE.map((t, i) => {
              const barColor = t.pct > 80 ? 'var(--ember-500)' : t.pct > 60 ? 'var(--amber-200)' : 'var(--green-400)'
              return (
                <div key={t.app} style={{
                  padding: '5px 0',
                  borderBottom: i < TOKEN_USAGE.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
                  fontSize: 11
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span>{t.app}</span>
                    <span className="mono" style={{ color: barColor }}>{t.pct}%</span>
                  </div>
                  <div style={{ height: 4, background: 'var(--bg-surface)', borderRadius: 2 }}>
                    <div style={{ width: `${Math.min(t.pct, 100)}%`, height: '100%', background: barColor, borderRadius: 2 }} />
                  </div>
                </div>
              )
            })}
          </Card>

          {/* OWASP Agentic Top 10 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>OWASP Agentic Top 10</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 11 }}>
              {OWASP_ITEMS.map(o => (
                <div key={o.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '3px 0',
                  borderBottom: '0.5px dotted var(--border-tertiary)'
                }}>
                  <span>
                    <span className="mono dim" style={{ marginRight: 4 }}>{o.id}</span>
                    <span className="muted">{o.name}</span>
                  </span>
                  <Badge kind={o.status}>{o.status === 'pass' ? 'PASS' : 'WARN'}</Badge>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
