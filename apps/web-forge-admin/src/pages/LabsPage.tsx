// Labs 实验区 · 完整页面
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

const KPI = [
  { label: '在试 Alpha',  value: '17',  delta: { text: '本周新增 2', tone: 'soft' as const } },
  { label: '本周试用',    value: '412', delta: { text: '▲ 47',      tone: 'success' as const } },
  { label: '毕业候选',    value: '3',   delta: { text: '待评审',     tone: 'soft' as const } },
  { label: '已毕业累计',  value: '8',   delta: { text: '总计',       tone: 'soft' as const } },
]

/* ── 毕业候选 ── */
const CANDIDATES = [
  { name: '春节流量预测', version: 'v0.9.3', trials: 247, star: 4.6, feedback: 47,  pct: 124 },
  { name: '川菜动态定价', version: 'v0.9.0', trials: 142, star: 4.4, feedback: 33,  pct: 71 },
  { name: '宴席预订 Agent', version: 'v0.7.2', trials: 89,  star: 4.8, feedback: 56, pct: 44 },
]

/* ── 毕业流程 ── */
const GRAD_STEPS = [
  { step: 1, label: '功能冻结',       status: 'pass' as const },
  { step: 2, label: '安全扫描通过',   status: 'pass' as const },
  { step: 3, label: '性能基线达标',   status: 'warn' as const },
  { step: 4, label: '文档 & SDK 完善', status: null },
  { step: 5, label: '定价策略确认',   status: null },
  { step: 6, label: '委员会投票',     status: null },
  { step: 7, label: '上架发布',       status: null },
]

/* ── 已毕业商品 ── */
interface Graduated {
  id: string
  name: string
  type: 'skill' | 'action' | 'widget' | 'adapter'
  gradDate: string
  alphaDays: number
  installs30d: number
  status: 'active' | 'paused'
  statusLabel: string
}

const GRADUATED: Graduated[] = [
  { id: '1', name: '智能配菜',   type: 'skill',   gradDate: '2025-09-12', alphaDays: 64, installs30d: 847, status: 'active', statusLabel: '活跃' },
  { id: '2', name: '自动赠饮',   type: 'action',  gradDate: '2025-10-28', alphaDays: 42, installs30d: 623, status: 'active', statusLabel: '活跃' },
  { id: '3', name: '海鲜溯源',   type: 'skill',   gradDate: '2025-12-05', alphaDays: 78, installs30d: 312, status: 'active', statusLabel: '活跃' },
  { id: '4', name: '实时客流',   type: 'widget',  gradDate: '2026-01-18', alphaDays: 55, installs30d: 204, status: 'active', statusLabel: '活跃' },
  { id: '5', name: '桌台热力图', type: 'widget',  gradDate: '2026-02-09', alphaDays: 38, installs30d: 156, status: 'active', statusLabel: '活跃' },
  { id: '6', name: '排班优化',   type: 'skill',   gradDate: '2026-02-27', alphaDays: 71, installs30d: 98,  status: 'active', statusLabel: '活跃' },
  { id: '7', name: '库存预警',   type: 'action',  gradDate: '2026-03-14', alphaDays: 49, installs30d: 187, status: 'active', statusLabel: '活跃' },
  { id: '8', name: '夜宵推荐',   type: 'skill',   gradDate: '2026-04-02', alphaDays: 33, installs30d: 74,  status: 'paused', statusLabel: '暂停' },
]

const GRAD_COLUMNS: Column<Graduated>[] = [
  { key: 'name',       label: '商品',         render: r => <span style={{ fontWeight: 500 }}>{r.name}</span> },
  { key: 'type',       label: '类型',         render: r => <Badge kind={r.type}>{r.type}</Badge> },
  { key: 'gradDate',   label: '毕业日期',     render: r => <span className="mono muted">{r.gradDate}</span> },
  { key: 'alphaDays',  label: 'Alpha 时长',   render: r => <span className="mono">{r.alphaDays}d</span>, align: 'right' },
  { key: 'installs30d', label: '毕业后 30d 安装', render: r => <span className="mono ember-soft">{r.installs30d.toLocaleString()}</span>, align: 'right' },
  { key: 'status',     label: '当前状态',     render: r => <Badge kind={r.status}>{r.statusLabel}</Badge> },
]

export default function LabsPage() {
  return (
    <>
      <PageHeader
        crumb="ECOSYSTEM / Labs 实验区"
        title="Labs · 彗星轨道"
        subtitle="Alpha 提交 17 · 试用反馈 1,247 · 待毕业 3"
        actions={<>
          <Button size="sm" variant="ghost">毕业评审委员会</Button>
          <Button size="sm" variant="secondary" style={{ border: '1.5px dashed var(--border-secondary)' }}>投递新 Alpha</Button>
        </>}
      />

      {/* KPI 行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* grid-2: 毕业候选 + 毕业流程 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* 左：毕业候选 */}
        <Card style={{ border: '1.5px dashed var(--border-secondary)', background: 'var(--bg-base)' }}>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 12 }}>毕业候选 · 3</div>
          {CANDIDATES.map((c, i) => (
            <div key={c.name} style={{
              padding: '10px 0',
              borderBottom: i < CANDIDATES.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <div>
                  <span style={{ fontWeight: 500, fontSize: 13 }}>{c.name}</span>
                  <span className="mono muted" style={{ marginLeft: 8, fontSize: 11 }}>{c.version}</span>
                </div>
                <div style={{ fontSize: 11 }}>
                  <span className="muted">试用 </span><span className="mono ember-soft">{c.trials}</span>
                  <span className="muted" style={{ margin: '0 6px' }}>·</span>
                  <span className="mono ember-soft">★{c.star}</span>
                  <span className="muted" style={{ margin: '0 6px' }}>·</span>
                  <span className="muted">反馈 </span><span className="mono">{c.feedback}</span>
                </div>
              </div>
              {/* progress bar */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, height: 6, background: 'var(--bg-surface)', borderRadius: 3 }}>
                  <div style={{
                    width: `${Math.min(c.pct, 100)}%`,
                    height: '100%',
                    background: c.pct >= 100 ? 'var(--green-400)' : c.pct >= 60 ? 'var(--amber-200)' : 'var(--ember-500)',
                    borderRadius: 3,
                  }} />
                </div>
                <span className="mono" style={{ fontSize: 11, color: c.pct >= 100 ? 'var(--green-400)' : 'var(--text-secondary)', minWidth: 36, textAlign: 'right' }}>{c.pct}%</span>
              </div>
              <div style={{ marginTop: 4, fontSize: 10 }}>
                <a className="ember-soft" style={{ cursor: 'pointer' }}>查看详情</a>
                <span className="dim" style={{ margin: '0 6px' }}>|</span>
                <a className="ember-soft" style={{ cursor: 'pointer' }}>反馈列表</a>
              </div>
            </div>
          ))}
        </Card>

        {/* 右：毕业流程 */}
        <Card>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 12 }}>毕业流程</div>
          {GRAD_STEPS.map((s, i) => (
            <div key={s.step} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '7px 0',
              borderBottom: i < GRAD_STEPS.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
            }}>
              {/* 时间线节点 */}
              <div style={{
                width: 22,
                height: 22,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 10,
                fontWeight: 600,
                background: s.status ? 'var(--bg-surface)' : 'var(--bg-base)',
                border: s.status ? 'none' : '1px dashed var(--border-tertiary)',
                color: s.status === 'pass' ? 'var(--green-400)' : s.status === 'warn' ? 'var(--amber-200)' : 'var(--text-tertiary)',
              }}>
                {s.step}
              </div>
              <span style={{ flex: 1, fontSize: 12, color: s.status ? 'var(--text-primary)' : 'var(--text-tertiary)' }}>{s.label}</span>
              {s.status && <Badge kind={s.status}>{s.status === 'pass' ? '通过' : '待修'}</Badge>}
              {!s.status && <span className="dim" style={{ fontSize: 10 }}>待启动</span>}
            </div>
          ))}
        </Card>
      </div>

      {/* 已毕业表格 */}
      <Card padding={0} style={{ overflow: 'hidden' }}>
        <div style={{ padding: '10px 14px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>已毕业 · 8 件</div>
        <Table columns={GRAD_COLUMNS} data={GRADUATED} rowKey={r => r.id} />
      </Card>
    </>
  )
}
