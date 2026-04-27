// AI 自动化审核 (v2.5)
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '本月审核',   value: '47',     delta: { text: '累计',         tone: 'soft'    as const } },
  { label: 'AI 自动通过', value: '28',    delta: { text: '60%',          tone: 'success' as const } },
  { label: '需人工',     value: '14',     delta: { text: '30%',          tone: 'soft'    as const } },
  { label: '被拒',       value: '5',      delta: { text: '10%',          tone: 'soft'    as const } },
  { label: '平均耗时',   value: '4.2 min', delta: { text: '目标≤3 min',  tone: 'success' as const } },
]

interface ReviewRow {
  id: string
  app: string
  version: string
  autoScore: number
  passItems: string
  failItems: string
  aiSuggestion: string
  manualItems: number
  result: string
  resultBadge: 'pass' | 'warn' | 'active' | 'paused'
}

const REVIEWS: ReviewRow[] = [
  { id: 'a1', app: '智能配菜',     version: 'v2.2.0', autoScore: 94, passItems: '9/10', failItems: 'Ontology绑定', aiSuggestion: '建议补充实体映射', manualItems: 2, result: '待人工',  resultBadge: 'warn'   },
  { id: 'a2', app: '美团外卖适配', version: 'v4.1',   autoScore: 88, passItems: '8/10', failItems: 'PII检测/速率', aiSuggestion: '敏感字段需脱敏', manualItems: 3, result: '待人工',  resultBadge: 'warn'   },
  { id: 'a3', app: '客流预测',     version: 'v1.3',   autoScore: 96, passItems: '10/10', failItems: '--', aiSuggestion: '自动通过', manualItems: 0, result: '已通过',  resultBadge: 'pass'   },
  { id: 'a4', app: '折扣守护',     version: 'v3.0.1', autoScore: 100, passItems: '10/10', failItems: '--', aiSuggestion: '自动通过', manualItems: 0, result: '已通过',  resultBadge: 'pass'   },
  { id: 'a5', app: '桌台合并',     version: 'v0.9',   autoScore: 52, passItems: '5/10', failItems: 'SAST/CVE/性能/内存/Agent兼容', aiSuggestion: '多项不达标，建议重构', manualItems: 3, result: '已拒绝',  resultBadge: 'active' },
  { id: 'a6', app: '夜间增亮',     version: 'v1.2',   autoScore: 78, passItems: '7/10', failItems: 'PII/Agent兼容/Ontology', aiSuggestion: '需补充兼容层', manualItems: 2, result: '审核中',  resultBadge: 'paused' },
]

const scoreColor = (s: number) => s >= 80 ? 'var(--green-400)' : s >= 60 ? 'var(--amber-400)' : 'var(--ember-500)'

const REVIEW_COLS: Column<ReviewRow>[] = [
  { key: 'app',        label: '应用',     render: r => <span style={{ fontWeight: 500 }}>{r.app}</span> },
  { key: 'version',    label: '版本',     render: r => <span className="mono muted">{r.version}</span>, width: 64 },
  { key: 'autoScore',  label: '自动得分', render: r => <span className="mono" style={{ fontWeight: 600, color: scoreColor(r.autoScore) }}>{r.autoScore}</span>, width: 64, align: 'center' },
  { key: 'passItems',  label: '通过/失败', render: r => <span className="mono muted">{r.passItems}</span>, width: 64, align: 'center' },
  { key: 'aiSuggestion', label: 'AI 建议', render: r => <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{r.aiSuggestion}</span>, width: 140 },
  { key: 'manualItems', label: '人工项', render: r => <span className="mono">{r.manualItems}</span>, width: 48, align: 'center' },
  { key: 'result',     label: '结果',     render: r => <Badge kind={r.resultBadge}>{r.result}</Badge>, width: 64 },
]

const AUTO_CHECKS = [
  { name: 'SAST 静态分析',   rate: 100 },
  { name: 'CVE 漏洞扫描',    rate: 98 },
  { name: '性能基准测试',    rate: 94 },
  { name: '内存泄漏检查',    rate: 96 },
  { name: 'Agent 兼容验证',  rate: 88 },
  { name: '硬约束合规',      rate: 100 },
  { name: 'License 审计',    rate: 100 },
  { name: 'PII 数据检测',    rate: 92 },
  { name: 'Ontology 绑定',   rate: 90 },
  { name: '速率配置校验',    rate: 96 },
]

const MANUAL_CHECKS = [
  { name: '商业合理性判断', reason: 'AI 无法替代' },
  { name: '用户体验主观评估', reason: '需要真实操作' },
  { name: '屯象品牌一致性', reason: '需要审美判断' },
]

const barColor = (r: number) => r >= 95 ? 'var(--green-400)' : r >= 85 ? 'var(--blue-400)' : 'var(--amber-400)'

export default function AutoReviewPage() {
  return (
    <>
      <PageHeader
        crumb="CORE / AI 审核官"
        title="AI 自动化审核"
        subtitle="自动化 70% 检查 · 人工 30% 判断 · 平均审核 4.2 min"
        actions={<>
          <Button size="sm" variant="ghost">审核模板</Button>
          <Button size="sm" variant="secondary">审核报告</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 最新审核结果 */}
      <Card style={{ marginBottom: 12 }}>
        <div className="lbl-sm muted" style={{ marginBottom: 8 }}>最新审核结果 · {REVIEWS.length} 条</div>
        <Table columns={REVIEW_COLS} data={REVIEWS} rowKey={r => r.id} />
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {/* 自动化检查项 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 10 }}>自动化检查项 · {AUTO_CHECKS.length} 项</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {AUTO_CHECKS.map(c => (
              <div key={c.name} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 48px', gap: 8, alignItems: 'center', fontSize: 11 }}>
                <span style={{ fontWeight: 500 }}>{c.name}</span>
                <div style={{ height: 8, background: 'var(--bg-surface)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${c.rate}%`, height: '100%', background: barColor(c.rate), borderRadius: 4 }} />
                </div>
                <span className="mono" style={{ textAlign: 'right', color: barColor(c.rate) }}>{c.rate}%</span>
              </div>
            ))}
          </div>
        </Card>

        {/* 人工必须 */}
        <Card variant="emphasis">
          <div className="lbl ember" style={{ marginBottom: 10 }}>— 人工必须 · 3 项</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {MANUAL_CHECKS.map(c => (
              <div key={c.name} style={{
                padding: '10px 12px', background: 'var(--bg-surface)', borderRadius: 6,
                borderLeft: '3px solid var(--ember-500)',
              }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{c.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{c.reason}</div>
              </div>
            ))}
          </div>
          <div style={{
            marginTop: 12, padding: '8px 10px', background: 'var(--bg-surface)', borderRadius: 4,
            fontSize: 10, color: 'var(--text-tertiary)', lineHeight: 1.6,
          }}>
            AI 处理 70% 标准化检查，人工专注 30% 需要判断力的审核项。审核效率提升 4x。
          </div>
        </Card>
      </div>
    </>
  )
}
