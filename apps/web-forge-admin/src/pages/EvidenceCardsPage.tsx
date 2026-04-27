// 信任证据管理 · 证据卡片矩阵
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

const KPI = [
  { label: '活跃证据',   value: '47',     delta: { text: '张',        tone: 'soft'    as const } },
  { label: '应用覆盖',   value: '38/47',  delta: { text: '81%',       tone: 'success' as const } },
  { label: '平均信任分', value: '84',     delta: { text: '▲ 3',       tone: 'success' as const } },
  { label: '即将过期',   value: '5',      delta: { text: '30天内',    tone: 'danger'  as const } },
]

/* ─── 证据类型 ─── */
const CARD_TYPES = [
  { icon: '\ud83d\udd12', label: '安全扫描', key: 'security' },
  { icon: '\u26a1',       label: '性能基准', key: 'perf' },
  { icon: '\ud83d\udee1\ufe0f', label: '护栏测试', key: 'guardrail' },
  { icon: '\ud83d\udcca', label: '业务验证', key: 'biz' },
  { icon: '\ud83c\udfc5', label: '合规认证', key: 'compliance' },
  { icon: '\u2b50',       label: '客户案例', key: 'case' },
  { icon: '\ud83d\udd10', label: '数据隐私', key: 'privacy' },
]

/* ─── 证据矩阵 ─── */
const MATRIX_APPS = [
  { app: '智能配菜',   cards: { security: true, perf: true, guardrail: true, biz: true, compliance: true, case: true, privacy: true } },
  { app: '会员洞察',   cards: { security: true, perf: true, guardrail: true, biz: true, compliance: true, case: false, privacy: true } },
  { app: '智能客服',   cards: { security: true, perf: true, guardrail: true, biz: true, compliance: false, case: true, privacy: true } },
  { app: '库存预警',   cards: { security: true, perf: true, guardrail: false, biz: true, compliance: true, case: false, privacy: false } },
  { app: '动态定价',   cards: { security: true, perf: false, guardrail: true, biz: true, compliance: true, case: false, privacy: true } },
  { app: '私域运营',   cards: { security: true, perf: true, guardrail: true, biz: false, compliance: false, case: true, privacy: true } },
  { app: '菜品推荐',   cards: { security: true, perf: true, guardrail: false, biz: true, compliance: false, case: false, privacy: false } },
  { app: '支付后营销', cards: { security: false, perf: true, guardrail: true, biz: true, compliance: false, case: false, privacy: true } },
]

/* ─── 证据卡片明细 ─── */
interface EvidenceRow {
  id: string
  app: string
  type: string
  title: string
  score: number
  verifier: string
  expiry: string
  status: 'active' | 'expiring' | 'expired'
}

const EVIDENCE_DATA: EvidenceRow[] = [
  { id: '1',  app: '智能配菜',   type: '安全扫描', title: 'OWASP Top10 全通过',        score: 95, verifier: '屯象安全团队', expiry: '2026-10-15', status: 'active' },
  { id: '2',  app: '智能配菜',   type: '性能基准', title: 'P99 < 120ms @500并发',      score: 92, verifier: '性能实验室',   expiry: '2026-08-20', status: 'active' },
  { id: '3',  app: '会员洞察',   type: '护栏测试', title: 'PII脱敏 100% 覆盖',         score: 88, verifier: '合规审计',     expiry: '2026-07-01', status: 'active' },
  { id: '4',  app: '智能客服',   type: '业务验证', title: '客诉解决率 94.2%',           score: 87, verifier: '业务运营',     expiry: '2026-06-15', status: 'active' },
  { id: '5',  app: '库存预警',   type: '合规认证', title: '等保三级备案',               score: 90, verifier: '等保测评机构', expiry: '2027-03-01', status: 'active' },
  { id: '6',  app: '动态定价',   type: '数据隐私', title: 'GDPR/个保法双合规',          score: 85, verifier: '隐私顾问',     expiry: '2026-05-20', status: 'expiring' },
  { id: '7',  app: '私域运营',   type: '客户案例', title: '尝在一起复购率+18%',         score: 82, verifier: '客户确认',     expiry: '2026-05-10', status: 'expiring' },
  { id: '8',  app: '智能配菜',   type: '护栏测试', title: '食安约束 100% 拦截',         score: 96, verifier: '食安专家',     expiry: '2026-09-30', status: 'active' },
  { id: '9',  app: '支付后营销', type: '安全扫描', title: '支付链路渗透测试',           score: 78, verifier: '外部审计',     expiry: '2026-05-05', status: 'expiring' },
  { id: '10', app: '菜品推荐',   type: '性能基准', title: '推荐延迟 P95 < 80ms',       score: 89, verifier: '性能实验室',   expiry: '2026-11-01', status: 'active' },
]

const STATUS_BADGE: Record<string, 'pass' | 'warn' | 'fail'> = {
  active: 'pass', expiring: 'warn', expired: 'fail'
}
const STATUS_LABEL: Record<string, string> = {
  active: '有效', expiring: '即将过期', expired: '已过期'
}

const EVIDENCE_COLS: Column<EvidenceRow>[] = [
  { key: 'app',      label: '应用',   render: r => <span style={{ fontWeight: 500 }}>{r.app}</span>, width: 80 },
  { key: 'type',     label: '类型',   render: r => <span className="muted">{r.type}</span>, width: 72 },
  { key: 'title',    label: '标题',   render: r => <span style={{ fontSize: 11 }}>{r.title}</span>, width: 180 },
  { key: 'score',    label: '得分',   render: r => (
    <span className="mono" style={{ color: r.score >= 90 ? 'var(--green-400)' : r.score >= 80 ? 'var(--amber-400)' : 'var(--ember-500)' }}>
      {r.score}
    </span>
  ), width: 48, align: 'center' },
  { key: 'verifier', label: '验证方', render: r => <span className="muted" style={{ fontSize: 11 }}>{r.verifier}</span>, width: 90 },
  { key: 'expiry',   label: '有效期', render: r => <span className="mono muted" style={{ fontSize: 10 }}>{r.expiry}</span>, width: 80 },
  { key: 'status',   label: '状态',   render: r => <Badge kind={STATUS_BADGE[r.status]}>{STATUS_LABEL[r.status]}</Badge>, width: 72, align: 'center' },
]

/* ─── 示例信任画像 ─── */
const TRUST_PROFILE = [
  { type: '\ud83d\udd12 安全扫描', title: 'OWASP Top10 全通过',    score: 95, status: '有效' },
  { type: '\u26a1 性能基准',       title: 'P99<120ms @500并发',     score: 92, status: '有效' },
  { type: '\ud83d\udee1\ufe0f 护栏测试', title: '食安约束100%拦截', score: 96, status: '有效' },
  { type: '\ud83d\udcca 业务验证', title: '推荐接受率41.2%',        score: 87, status: '有效' },
  { type: '\ud83c\udfc5 合规认证', title: '等保三级备案',           score: 90, status: '有效' },
  { type: '\ud83d\udd10 数据隐私', title: 'GDPR/个保法双合规',     score: 85, status: '即将过期' },
]

export default function EvidenceCardsPage() {
  return (
    <>
      <PageHeader
        crumb="GUARDRAIL / 证据卡片"
        title="信任证据管理"
        subtitle="47 张活跃证据 · 7 种类型 · 平均信任分 84"
        actions={<>
          <Button size="sm" variant="ghost">批量生成</Button>
          <Button size="sm" variant="secondary">过期管理</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 证据卡片矩阵 */}
      <Card style={{ marginBottom: 12 }}>
        <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 10 }}>
          证据卡片矩阵
          <span className="mono muted" style={{ fontSize: 11, marginLeft: 8 }}>{MATRIX_APPS.length} 应用 x {CARD_TYPES.length} 类型</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: `80px repeat(${CARD_TYPES.length}, 1fr)`, gap: 4, fontSize: 11 }}>
            {/* header */}
            <div />
            {CARD_TYPES.map(t => (
              <div key={t.key} style={{ textAlign: 'center', padding: '4px 0' }}>
                <div>{t.icon}</div>
                <div className="muted" style={{ fontSize: 9 }}>{t.label}</div>
              </div>
            ))}
            {/* rows */}
            {MATRIX_APPS.map(row => [
              <div key={row.app} style={{ fontWeight: 500, padding: '6px 0', display: 'flex', alignItems: 'center' }}>{row.app}</div>,
              ...CARD_TYPES.map(t => (
                <div key={`${row.app}-${t.key}`} style={{ textAlign: 'center', padding: '6px 0' }}>
                  <span style={{
                    display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                    background: (row.cards as Record<string, boolean>)[t.key]
                      ? 'var(--green-400)' : 'var(--bg-surface)',
                    border: (row.cards as Record<string, boolean>)[t.key]
                      ? 'none' : '1px solid var(--border-tertiary)',
                  }} />
                </div>
              )),
            ])}
          </div>
        </div>
      </Card>

      {/* 证据卡片明细 */}
      <Card padding={0} style={{ overflow: 'hidden', marginBottom: 12 }}>
        <div style={{ padding: '10px 12px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>证据卡片明细 · {EVIDENCE_DATA.length} 张</div>
        <Table columns={EVIDENCE_COLS} data={EVIDENCE_DATA} rowKey={r => r.id} />
      </Card>

      {/* 示例 — 智能配菜信任画像 */}
      <Card variant="emphasis">
        <div className="lbl ember" style={{ marginBottom: 10 }}>— 示例 · 智能配菜信任画像</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {TRUST_PROFILE.map(p => (
            <div key={p.type} style={{
              padding: '10px 12px', background: 'var(--bg-surface)', borderRadius: 8,
              border: '1px solid var(--border-tertiary)'
            }}>
              <div style={{ fontSize: 12, marginBottom: 4 }}>{p.type}</div>
              <div style={{ fontWeight: 500, fontSize: 12, marginBottom: 6 }}>{p.title}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="mono" style={{
                  fontSize: 16, fontWeight: 600,
                  color: p.score >= 90 ? 'var(--green-400)' : 'var(--amber-400)'
                }}>{p.score}</span>
                <Badge kind={p.status === '有效' ? 'pass' : 'warn'}>{p.status}</Badge>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
