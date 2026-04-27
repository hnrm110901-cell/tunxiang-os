// RBAC 权限 · 完整示范页(展示角色表格与双签审计)
import { PageHeader, Button, Badge, Card, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

interface Role {
  id: string
  name: string
  users: number
  perms: string
  denied: string
  highlight?: 'ember' | 'dim'
}

const ROLES: Role[] = [
  { id: '1', name: 'Forge超管',  users: 2, perms: '全部',                  denied: '--',       highlight: 'ember' },
  { id: '2', name: 'Forge Ops',  users: 4, perms: '商品/ISV/内容/分析',     denied: '财务/RBAC' },
  { id: '3', name: '审核员',     users: 6, perms: '审核中心/商品(只读)',      denied: '下架/财务' },
  { id: '4', name: '资深审核',   users: 3, perms: '审核+下架',              denied: 'RBAC' },
  { id: '5', name: '财务',       users: 2, perms: '抽佣/结算/发票/退款',     denied: '商品' },
  { id: '6', name: '安全官',     users: 2, perms: '安全合规/应急下架/审计',   denied: '财务' },
  { id: '7', name: 'ISV关系',    users: 8, perms: 'ISV沟通/邀请码/等级',    denied: '商品/审核' },
  { id: '8', name: '只读观察',   users: 5, perms: '所有页面只读',            denied: '所有写',   highlight: 'dim' },
]

const COLUMNS: Column<Role>[] = [
  { key: 'name',   label: '角色',   render: r => <span className={r.highlight === 'ember' ? 'ember' : r.highlight === 'dim' ? 'dim' : ''} style={{ fontWeight: 500 }}>{r.name}</span> },
  { key: 'users',  label: '用户数', render: r => <span className="mono">{r.users}</span>, align: 'right' },
  { key: 'perms',  label: '核心权限', render: r => <span className={r.highlight === 'dim' ? 'dim' : ''}>{r.perms}</span> },
  { key: 'denied', label: '不可',   render: r => <span className={r.highlight === 'dim' ? 'dim' : 'muted'}>{r.denied}</span> },
  { key: 'op',     label: '操作',   render: () => <a className="ember-soft" style={{ fontSize: 11, cursor: 'pointer' }}>编辑</a> },
]

const DUAL_SIGN = [
  { action: '抽佣调整',   signers: 'CTO + 财务' },
  { action: '应急下架',   signers: '安全官 + 超管' },
  { action: '角色权限变更', signers: '超管 × 2' },
  { action: '结算单签发',  signers: '财务 + Ops' },
]

const AUDIT_LOG = [
  { time: '14:32', action: '张工 修改审核员权限 → 新增「商品只读」' },
  { time: '11:08', action: '李总 双签通过 抽佣比例调整(标准ISV 30→28%)' },
  { time: '昨日',  action: '王安全官 应急下架「春节流量预测 v0.9.3」' },
  { time: '04-23', action: '系统 自动撤销 ISV「青菜科技」过期邀请码 ×3' },
  { time: '04-22', action: '张工 新建角色「只读观察」并分配 5 用户' },
]

export default function RbacPage() {
  return (
    <>
      <PageHeader
        crumb="GUARDRAIL / RBAC 权限"
        title="角色与权限"
        subtitle="7 角色 · 32 用户 · 全操作入审计"
        actions={<>
          <Button size="sm" variant="ghost">审计日志</Button>
          <Button size="sm" variant="secondary">权限矩阵</Button>
          <Button size="sm" variant="primary">新建角色</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
        {/* left: role table */}
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <Table columns={COLUMNS} data={ROLES} rowKey={r => r.id} />
        </Card>

        {/* right sidebar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Card>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>双签操作</span>
              <span className="lbl-sm muted">改动需2人</span>
            </div>
            {DUAL_SIGN.map(d => (
              <div key={d.action} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 12
              }}>
                <span>{d.action}</span>
                <span className="mono muted" style={{ fontSize: 11 }}>{d.signers}</span>
              </div>
            ))}
          </Card>

          <Card>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>最近5条审计</span>
            </div>
            {AUDIT_LOG.map((log, i) => (
              <div key={i} style={{
                borderBottom: '0.5px dotted var(--border-tertiary)', padding: '4px 0', fontSize: 11, lineHeight: 1.6
              }}>
                <span className="mono dim" style={{ marginRight: 8 }}>{log.time}</span>
                <span>{log.action}</span>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </>
  )
}
