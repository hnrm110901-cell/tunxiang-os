// 审核中心 · 审核工作流
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '待审核', value: '12',  delta: { text: '3 紧急',     tone: 'soft'    as const }, alert: true },
  { label: '扫描中', value: '4',   delta: { text: '自动流水线', tone: 'soft'    as const } },
  { label: '本周通过', value: '23', delta: { text: '▲ 6',       tone: 'success' as const } },
  { label: '本周拒',  value: '3',  delta: { text: '拒绝率 11%', tone: 'soft'    as const } },
]

interface QueueItem {
  id: string
  name: string
  isv: string
  kind: 'skill' | 'action' | 'adapter' | 'theme' | 'widget'
  submitted: string
  stage: string
  stageBadge: 'warn' | 'pass' | 'active' | 'paused'
  sla: string
  slaUrgent: boolean
}

const QUEUE: QueueItem[] = [
  { id: 'r1', name: '智能配菜 v2.2.0', isv: '屯象官方',   kind: 'skill',   submitted: '04-23', stage: '人工复核', stageBadge: 'warn',   sla: '2h',  slaUrgent: true  },
  { id: 'r2', name: '美团外卖 v4.1',   isv: '美团ISV',    kind: 'adapter', submitted: '04-24', stage: '安全扫描', stageBadge: 'active', sla: '4h',  slaUrgent: true  },
  { id: 'r3', name: 'L0-PZ 主题 v1.1', isv: '长沙青菜',   kind: 'theme',   submitted: '04-24', stage: '会签中',   stageBadge: 'paused', sla: '6h',  slaUrgent: false },
  { id: 'r4', name: '夜间增亮 v1.2',   isv: '湘味数智',   kind: 'widget',  submitted: '04-25', stage: '排队中',   stageBadge: 'paused', sla: '8h',  slaUrgent: false },
  { id: 'r5', name: '桌台合并 v0.9',   isv: '明厨亮灶',   kind: 'action',  submitted: '04-25', stage: '排队中',   stageBadge: 'paused', sla: '8h',  slaUrgent: false },
]

const QUEUE_COLS: Column<QueueItem>[] = [
  { key: 'name',  label: '商品',  render: r => <span style={{ fontWeight: 500 }}>{r.name}</span> },
  { key: 'isv',   label: 'ISV',   render: r => <span className="muted">{r.isv}</span> },
  { key: 'kind',  label: '类型',  render: r => <Badge kind={r.kind}>{r.kind.toUpperCase()}</Badge> },
  { key: 'sub',   label: '提交',  render: r => <span className="mono muted">{r.submitted}</span>, width: 64 },
  { key: 'stage', label: '阶段',  render: r => <Badge kind={r.stageBadge}>{r.stage}</Badge> },
  { key: 'sla',   label: 'SLA',   render: r => <span className="mono" style={{ color: r.slaUrgent ? 'var(--ember-500)' : 'var(--text-tertiary)' }}>{r.sla}</span>, width: 48, align: 'right' },
  { key: 'op',    label: '操作',  render: () => <Button size="sm" variant="ghost">审核</Button>, width: 64, align: 'center' },
]

const AUTO_CHECKS = [
  { name: '代码安全扫描',       result: 'pass' as const, note: '0 漏洞' },
  { name: '性能基准',           result: 'pass' as const, note: 'P95 < 120ms' },
  { name: 'Master Agent 兼容性', result: 'warn' as const, note: '待处理 1 项' },
  { name: '三条硬约束',         result: 'pass' as const, note: '全部合规' },
  { name: 'License',            result: 'pass' as const, note: 'MIT' },
]

const HUMAN_CHECKS = [
  { name: '功能完整性验证',   done: true,  warn: false },
  { name: 'UI/UX 一致性',     done: true,  warn: false },
  { name: '数据隔离(RLS)',    done: true,  warn: false },
  { name: 'API 速率限制',     done: true,  warn: false },
  { name: '多语言支持',       done: true,  warn: false },
  { name: '可回滚验证',       done: false, warn: true  },
  { name: '文档 & CHANGELOG', done: false, warn: false },
]

const GRAYSCALE_STEPS = [
  { pct: '5%',   desc: '内部员工 + 种子商户',  duration: '24h' },
  { pct: '50%',  desc: '金牌以上商户',          duration: '72h' },
  { pct: '100%', desc: '全量发布',              duration: '—'   },
]

const VERSION_HISTORY = [
  { ver: 'v2.1.3', date: '04-10', result: '通过', badge: 'pass' as const },
  { ver: 'v2.1.0', date: '03-22', result: '通过', badge: 'pass' as const },
  { ver: 'v2.0.0', date: '02-15', result: '要求修改 → 通过', badge: 'warn' as const },
  { ver: 'v1.9.2', date: '01-08', result: '通过', badge: 'pass' as const },
]

export default function ReviewPage() {
  return (
    <>
      <PageHeader
        crumb="CORE / 审核中心"
        title="审核工作流"
        subtitle="SLA 8h · 当前 94% 达标 · 本周通过 23"
        actions={<>
          <Button size="sm" variant="ghost">拒审模板</Button>
          <Button size="sm" variant="secondary">SLA 看板</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 待审队列 */}
      <Card style={{ marginBottom: 12 }}>
        <div className="lbl-sm muted" style={{ marginBottom: 8 }}>待审队列</div>
        <Table columns={QUEUE_COLS} data={QUEUE} rowKey={r => r.id} selectedKey="r1" />
      </Card>

      {/* 主内容 2fr 1fr */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
        {/* 左栏 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 选中的审核商品 */}
          <Card variant="emphasis">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div>
                <div style={{ fontFamily: 'var(--font-serif)', fontSize: 15, color: '#fff' }}>智能配菜 v2.2.0</div>
                <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                  <Badge kind="skill">SKILL</Badge>{' '}
                  <Badge kind="official">屯象官方</Badge>
                </div>
              </div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--green-400)', textAlign: 'right' }}>
                <span style={{ color: 'var(--green-400)' }}>+384</span>{' '}
                <span style={{ color: 'var(--ember-500)' }}>-127</span>
                <div className="muted" style={{ fontSize: 10 }}>diff · 14 files</div>
              </div>
            </div>
            <div className="muted" style={{ fontSize: 11, lineHeight: 1.6 }}>
              升级菜品推荐算法，新增季节性食材权重、毛利约束参数；修复多店模式下
              同步延迟 &gt; 3s 的问题。依赖 master-agent &ge; 3.4.0。
            </div>
          </Card>

          {/* 自动化检查 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>自动化检查 · 5 项</div>
            {AUTO_CHECKS.map(c => (
              <div key={c.name} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 11
              }}>
                <span>{c.name}</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className="mono muted">{c.note}</span>
                  <Badge kind={c.result}>{c.result === 'pass' ? 'PASS' : 'WARN'}</Badge>
                </span>
              </div>
            ))}
          </Card>

          {/* 人工检查 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>人工审核清单 · {HUMAN_CHECKS.filter(h => h.done).length}/{HUMAN_CHECKS.length}</div>
            {HUMAN_CHECKS.map(c => (
              <div key={c.name} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 11,
                color: c.done ? 'var(--text-secondary)' : c.warn ? 'var(--amber-200)' : 'var(--text-tertiary)'
              }}>
                <span style={{
                  width: 14, height: 14, borderRadius: 3, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 10, fontFamily: 'var(--font-mono)',
                  background: c.done ? 'var(--green-900)' : c.warn ? 'var(--amber-900)' : 'var(--bg-surface)',
                  color: c.done ? 'var(--green-200)' : c.warn ? 'var(--amber-200)' : 'var(--text-tertiary)',
                  border: c.done ? 'none' : '0.5px solid var(--border-secondary)'
                }}>{c.done ? '✓' : c.warn ? '!' : ''}</span>
                <span>{c.name}</span>
              </div>
            ))}
          </Card>
        </div>

        {/* 右栏 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 决策卡片 */}
          <Card variant="emphasis">
            <div className="lbl ember" style={{ marginBottom: 10 }}>— 审核决策</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Button size="sm" variant="primary" style={{ width: '100%' }}>通过 · 进入灰度</Button>
              <Button size="sm" variant="secondary" style={{ width: '100%', borderColor: 'var(--amber-200)', color: 'var(--amber-200)' }}>要求修改</Button>
              <Button size="sm" variant="secondary" style={{ width: '100%' }}>升级到资深</Button>
              <Button size="sm" variant="ghost" style={{ width: '100%', color: 'var(--ember-500)', borderColor: 'var(--ember-500)', border: '0.5px solid var(--ember-500)' }}>拒绝</Button>
            </div>
          </Card>

          {/* 灰度路径 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>灰度路径</div>
            {GRAYSCALE_STEPS.map((s, i) => (
              <div key={s.pct} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '6px 0', borderBottom: i < GRAYSCALE_STEPS.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
                fontSize: 11
              }}>
                <span className="mono" style={{ color: 'var(--ember-500)', width: 36, fontWeight: 600 }}>{s.pct}</span>
                <span style={{ flex: 1 }}>{s.desc}</span>
                <span className="mono muted">{s.duration}</span>
              </div>
            ))}
          </Card>

          {/* 历史版本 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>该商品历史</div>
            {VERSION_HISTORY.map(v => (
              <div key={v.ver} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 11
              }}>
                <span className="mono" style={{ color: 'var(--text-secondary)' }}>{v.ver}</span>
                <span className="mono muted">{v.date}</span>
                <Badge kind={v.badge}>{v.result}</Badge>
              </div>
            ))}
          </Card>

          {/* 给作者反馈 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>给作者反馈</div>
            <textarea
              placeholder="输入审核意见、建议或修改要求…"
              style={{
                width: '100%', minHeight: 80, padding: 8, fontSize: 11,
                background: 'var(--bg-surface)', color: 'var(--text-primary)',
                border: '0.5px solid var(--border-secondary)', borderRadius: 4,
                fontFamily: 'var(--font-sans)', resize: 'vertical', outline: 'none'
              }}
            />
            <div style={{ marginTop: 6, display: 'flex', justifyContent: 'flex-end' }}>
              <Button size="sm" variant="secondary">发送反馈</Button>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
