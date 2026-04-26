// Agent 联盟市场 (v3.0)
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '共享清单', value: '8',       delta: { text: '累计',        tone: 'soft'    as const } },
  { label: '参与品牌', value: '3',       delta: { text: '▲ 1 本月',    tone: 'success' as const } },
  { label: '联盟安装', value: '47',      delta: { text: '▲ 12 本月',   tone: 'success' as const } },
  { label: '联盟收入', value: '¥18.4k',  delta: { text: '▲ 24% MoM',  tone: 'success' as const } },
]

interface AllianceRow {
  id: string
  app: string
  owner: string
  shareMode: string
  shareModeBadge: 'active' | 'pass' | 'warn'
  authorized: string
  split: string
  installs: number
  revenue: string
}

const ALLIANCES: AllianceRow[] = [
  { id: 's1', app: '海鲜溯源',     owner: '徐记海鲜', shareMode: 'invited', shareModeBadge: 'warn',   authorized: '2 品牌',  split: '70:30', installs: 24, revenue: '¥8.4k' },
  { id: 's2', app: '智能配菜',     owner: '屯象官方', shareMode: 'public',  shareModeBadge: 'pass',   authorized: '--',      split: '60:40', installs: 18, revenue: '¥6.2k' },
  { id: 's3', app: '客流预测',     owner: '屯象官方', shareMode: 'public',  shareModeBadge: 'pass',   authorized: '--',      split: '60:40', installs: 12, revenue: '¥1.8k' },
  { id: 's4', app: '食安巡检',     owner: '最黔线',   shareMode: 'invited', shareModeBadge: 'warn',   authorized: '1 品牌',  split: '75:25', installs: 8,  revenue: '¥0.9k' },
  { id: 's5', app: '会员唤醒',     owner: '尚宫厨',   shareMode: 'invited', shareModeBadge: 'warn',   authorized: '1 品牌',  split: '70:30', installs: 6,  revenue: '¥0.6k' },
  { id: 's6', app: '外卖出餐节奏', owner: '长沙青菜', shareMode: 'public',  shareModeBadge: 'pass',   authorized: '--',      split: '65:35', installs: 4,  revenue: '¥0.5k' },
]

const ALLIANCE_COLS: Column<AllianceRow>[] = [
  { key: 'app',        label: '应用',       render: r => <span style={{ fontWeight: 500 }}>{r.app}</span> },
  { key: 'owner',      label: '拥有者',     render: r => <span className="muted">{r.owner}</span>, width: 80 },
  { key: 'shareMode',  label: '共享模式',   render: r => <Badge kind={r.shareModeBadge}>{r.shareMode}</Badge>, width: 72 },
  { key: 'authorized', label: '被授权品牌', render: r => <span className="muted">{r.authorized}</span>, width: 72 },
  { key: 'split',      label: '分成比例',   render: r => <span className="mono">{r.split}</span>, width: 56, align: 'center' },
  { key: 'installs',   label: '安装数',     render: r => <span className="mono">{r.installs}</span>, width: 48, align: 'right' },
  { key: 'revenue',    label: '收入',       render: r => <span className="mono" style={{ color: 'var(--green-400)' }}>{r.revenue}</span>, width: 64, align: 'right' },
  { key: 'op',         label: '操作',       render: () => <Button size="sm" variant="ghost">详情</Button>, width: 56, align: 'center' },
]

const FLOW_STEPS = [
  { step: '拥有者开发 Agent', icon: '🛠' },
  { step: '共享给联盟品牌',   icon: '🤝' },
  { step: '使用方按结果付费', icon: '💰' },
  { step: '拥有者 70% + 平台 30%', icon: '📊' },
]

export default function AllianceMarketPage() {
  return (
    <>
      <PageHeader
        crumb="ECOSYSTEM / 跨品牌联盟"
        title="Agent 联盟市场"
        subtitle="让品牌间共享 Agent 能力 · 8 个共享清单 · 3 品牌参与"
        actions={<>
          <Button size="sm" variant="secondary">联盟收入</Button>
          <Button size="sm" variant="primary">创建共享</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 联盟共享清单 */}
      <Card style={{ marginBottom: 12 }}>
        <div className="lbl-sm muted" style={{ marginBottom: 8 }}>联盟共享清单 · {ALLIANCES.length} 条</div>
        <Table columns={ALLIANCE_COLS} data={ALLIANCES} rowKey={r => r.id} />
      </Card>

      {/* 联盟商业模型 */}
      <Card variant="emphasis">
        <div className="lbl-sm" style={{ marginBottom: 12, fontWeight: 600 }}>联盟商业模型</div>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12,
          textAlign: 'center',
        }}>
          {FLOW_STEPS.map((s, i) => (
            <div key={s.step} style={{ position: 'relative' }}>
              <div style={{
                padding: '12px 8px', background: 'var(--bg-surface)', borderRadius: 8,
                border: '1px solid var(--border-tertiary)',
              }}>
                <div style={{ fontSize: 24, marginBottom: 6 }}>{s.icon}</div>
                <div style={{ fontSize: 11, fontWeight: 500, lineHeight: 1.4 }}>{s.step}</div>
              </div>
              {i < FLOW_STEPS.length - 1 && (
                <div style={{
                  position: 'absolute', right: -10, top: '50%', transform: 'translateY(-50%)',
                  color: 'var(--text-tertiary)', fontSize: 14, fontWeight: 600, zIndex: 1,
                }}>→</div>
              )}
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 12, padding: '8px 10px', background: 'var(--bg-surface)', borderRadius: 4,
          fontSize: 11, color: 'var(--text-tertiary)', lineHeight: 1.6, textAlign: 'center',
        }}>
          跨品牌复用 Agent 能力，降低重复开发成本，拥有者获得被动收入
        </div>
      </Card>
    </>
  )
}
