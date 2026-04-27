// 信任分级管理 · T0-T4 五级信任治理
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: 'T4 官方',   value: '8',  delta: { text: '最高信任',   tone: 'success' as const } },
  { label: 'T3 信赖',   value: '4',  delta: { text: '可信 ISV',   tone: 'success' as const } },
  { label: 'T2 认证',   value: '12', delta: { text: '已认证',     tone: 'soft'    as const } },
  { label: 'T1 社区',   value: '18', delta: { text: '社区贡献',   tone: 'soft'    as const } },
  { label: 'T0 实验室', value: '7',  delta: { text: '沙箱隔离',   tone: 'soft'    as const } },
]

/* ─── 信任矩阵 ─── */
interface TrustRow {
  id: string
  app: string
  isv: string
  tier: 'T4' | 'T3' | 'T2' | 'T1' | 'T0'
  dataScope: string
  actionScope: string
  fund: boolean
  violations: number
  action: string | null
}

const TRUST_DATA: TrustRow[] = [
  { id: 'r1', app: '智能配菜',      isv: '屯象官方',  tier: 'T4', dataScope: 'full',       actionScope: 'all',           fund: true,  violations: 0, action: null },
  { id: 'r2', app: '美团 Adapter',  isv: '屯象官方',  tier: 'T4', dataScope: 'full',       actionScope: 'all',           fund: true,  violations: 0, action: null },
  { id: 'r3', app: '实时客流热力',   isv: '长沙青菜',  tier: 'T2', dataScope: 'read_write', actionScope: 'non_financial', fund: false, violations: 1, action: '升级申请' },
  { id: 'r4', app: '海鲜溯源',      isv: '屯象官方',  tier: 'T3', dataScope: 'read_write', actionScope: 'all',           fund: true,  violations: 0, action: null },
  { id: 'r5', app: '桌台合并',      isv: '长沙青菜',  tier: 'T1', dataScope: 'read',       actionScope: 'none',          fund: false, violations: 0, action: '升级申请' },
  { id: 'r6', app: '春节流量预测',   isv: 'Labs',     tier: 'T0', dataScope: 'none',       actionScope: 'none',          fund: false, violations: 0, action: null },
  { id: 'r7', app: '抖音营销',      isv: '抖音',      tier: 'T2', dataScope: 'read_write', actionScope: 'non_financial', fund: false, violations: 2, action: '复核' },
  { id: 'r8', app: '川菜动态定价',   isv: '川味数据',  tier: 'T1', dataScope: 'read',       actionScope: 'none',          fund: false, violations: 0, action: null },
]

const TIER_BADGE: Record<string, 'official' | 'integration' | 'isv' | 'skill' | 'labs'> = {
  T4: 'official', T3: 'integration', T2: 'isv', T1: 'skill', T0: 'labs'
}

const TRUST_COLS: Column<TrustRow>[] = [
  { key: 'app',         label: '应用',     render: r => <span style={{ fontWeight: 500 }}>{r.app}</span>, width: 120 },
  { key: 'isv',         label: 'ISV',      render: r => <span className="muted">{r.isv}</span>, width: 90 },
  { key: 'tier',        label: '当前等级',  render: r => <Badge kind={TIER_BADGE[r.tier]}>{r.tier}</Badge>, width: 72, align: 'center' },
  { key: 'dataScope',   label: '数据权限',  render: r => <span className="mono muted" style={{ fontSize: 11 }}>{r.dataScope}</span>, width: 90 },
  { key: 'actionScope', label: 'Action范围', render: r => <span className="mono muted" style={{ fontSize: 11 }}>{r.actionScope}</span>, width: 100 },
  { key: 'fund',        label: '资金操作',  render: r => <span style={{ color: r.fund ? 'var(--green-400)' : 'var(--text-tertiary)' }}>{r.fund ? '✓' : '✗'}</span>, width: 64, align: 'center' },
  { key: 'violations',  label: '违规(30d)', render: r => <span className="mono" style={{ color: r.violations > 0 ? 'var(--ember-500)' : 'var(--text-tertiary)' }}>{r.violations}</span>, width: 72, align: 'center' },
  { key: 'action',      label: '操作',     render: r => r.action
    ? <Button size="sm" variant={r.action === '复核' ? 'secondary' : 'ghost'}>{r.action}</Button>
    : <span className="dim">—</span>,
    width: 80, align: 'center' },
]

/* ─── 信任等级说明 ─── */
const TIER_DEFS = [
  { tier: 'T4', name: '官方',   scope: 'full + 资金',     desc: '屯象官方应用，全权限' },
  { tier: 'T3', name: '信赖',   scope: 'read_write + 资金', desc: '长期合作ISV，已审计' },
  { tier: 'T2', name: '认证',   scope: 'read_write',       desc: '通过安全认证，无资金权限' },
  { tier: 'T1', name: '社区',   scope: 'read',             desc: '社区开发者，只读数据' },
  { tier: 'T0', name: '实验室', scope: 'none',             desc: '沙箱隔离，无数据访问' },
]

/* ─── 待审核升级 ─── */
const PENDING_UPGRADES = [
  { app: '实时客流热力', from: 'T2', to: 'T3', isv: '长沙青菜', submitted: '2026-04-23', reason: '安全审计通过，申请资金操作权限' },
  { app: '桌台合并',    from: 'T1', to: 'T2', isv: '长沙青菜', submitted: '2026-04-22', reason: '功能稳定运行60天，申请write权限' },
  { app: '川菜动态定价', from: 'T1', to: 'T2', isv: '川味数据', submitted: '2026-04-20', reason: '完成等保三级备案，申请数据写入' },
]

export default function TrustTierPage() {
  return (
    <>
      <PageHeader
        crumb="AI OPS / 信任治理"
        title="信任分级管理"
        subtitle="T0-T4 五级 · 12 应用已认证 · 3 待升级审核"
        actions={<>
          <Button size="sm" variant="ghost">等级定义</Button>
          <Button size="sm" variant="secondary">审核队列</Button>
          <Button size="sm" variant="ghost" style={{ color: 'var(--ember-500)', borderColor: 'var(--ember-500)' }}>紧急熔断</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 主体：左2fr 右1fr */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* 左：信任矩阵 */}
        <Card>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 10 }}>
            应用信任矩阵
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>8 应用</span>
          </div>
          <Table columns={TRUST_COLS} data={TRUST_DATA} rowKey={r => r.id} />
        </Card>

        {/* 右：说明 + 待审核 + 降级 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 信任等级说明 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>信任等级说明</div>
            <div style={{ fontSize: 11 }}>
              {TIER_DEFS.map((t, i) => (
                <div key={t.tier} style={{
                  display: 'grid', gridTemplateColumns: '36px 48px 1fr',
                  gap: 8, alignItems: 'center',
                  padding: '5px 0',
                  borderBottom: i < TIER_DEFS.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none'
                }}>
                  <Badge kind={TIER_BADGE[t.tier]}>{t.tier}</Badge>
                  <span style={{ fontWeight: 500 }}>{t.name}</span>
                  <span className="muted">{t.desc}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* 待审核升级 */}
          <Card variant="emphasis">
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 待审核升级 · 3</div>
            {PENDING_UPGRADES.map((u, i) => (
              <div key={u.app} style={{
                padding: '6px 0',
                borderBottom: i < PENDING_UPGRADES.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
                fontSize: 11
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ fontWeight: 500 }}>{u.app}</span>
                  <span className="mono muted">{u.submitted}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
                  <Badge kind={TIER_BADGE[u.from]}>{u.from}</Badge>
                  <span className="dim" style={{ fontSize: 10 }}>→</span>
                  <Badge kind={TIER_BADGE[u.to]}>{u.to}</Badge>
                  <span className="muted" style={{ marginLeft: 4 }}>{u.isv}</span>
                </div>
                <div className="muted">{u.reason}</div>
              </div>
            ))}
          </Card>

          {/* 最近降级 */}
          <Card style={{ borderLeft: '2px solid var(--amber-200)' }}>
            <div className="lbl-sm" style={{ color: 'var(--amber-200)', marginBottom: 8 }}>最近降级</div>
            <div style={{ fontSize: 11 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontWeight: 500 }}>抖音营销</span>
                <span className="mono muted">2026-04-18</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
                <Badge kind="integration">T3</Badge>
                <span className="dim" style={{ fontSize: 10 }}>→</span>
                <Badge kind="isv">T2</Badge>
              </div>
              <div className="muted">原因：权限违规 — 未授权读取会员手机号字段，自动降级处理</div>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
