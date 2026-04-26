// 旧系统 Adapter 矩阵 · 完整页
import { PageHeader, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

interface Adapter {
  id: string
  name: string
  slug: string
  system: string
  version: string
  health: number
  stores: number
  quotaPct: number
  errorRate: string
  lastUpgrade: string
  status: 'pass' | 'warn'
  statusLabel: string
}

const ADAPTERS: Adapter[] = [
  { id: '1',  name: '品智POS',       slug: 'pinzhi',            system: '品智POS v6',        version: 'v4.2.1', health: 98, stores: 412,  quotaPct: 72, errorRate: '0.02%', lastUpgrade: '04-12', status: 'pass', statusLabel: '正常' },
  { id: '2',  name: '奥琦玮G10',     slug: 'aoqiwei',           system: '奥琦玮 G10',        version: 'v3.1.0', health: 96, stores: 214,  quotaPct: 58, errorRate: '0.04%', lastUpgrade: '04-08', status: 'pass', statusLabel: '正常' },
  { id: '3',  name: '天财商龙',      slug: 'tiancai-shanglong', system: '天财商龙 v8',       version: 'v3.8.2', health: 94, stores: 187,  quotaPct: 44, errorRate: '0.08%', lastUpgrade: '03-28', status: 'pass', statusLabel: '正常' },
  { id: '4',  name: '客如云',        slug: 'keruyun',           system: '客如云 SaaS',       version: 'v2.9.4', health: 78, stores: 142,  quotaPct: 87, errorRate: '0.42%', lastUpgrade: '03-02', status: 'warn', statusLabel: '需升级' },
  { id: '5',  name: '微生活CRM',     slug: 'weishenghuo',       system: '微生活 CRM v5',     version: 'v2.4.0', health: 90, stores: 87,   quotaPct: 31, errorRate: '0.11%', lastUpgrade: '04-05', status: 'pass', statusLabel: '正常' },
  { id: '6',  name: '美团SaaS',      slug: 'meituan',           system: '美团餐饮SaaS',      version: 'v4.0.3', health: 99, stores: 1142, quotaPct: 92, errorRate: '0.01%', lastUpgrade: '04-20', status: 'pass', statusLabel: '正常' },
  { id: '7',  name: '饿了么',        slug: 'eleme',             system: '饿了么开放平台',    version: 'v3.8.0', health: 97, stores: 987,  quotaPct: 81, errorRate: '0.03%', lastUpgrade: '04-18', status: 'pass', statusLabel: '正常' },
  { id: '8',  name: '抖音来客',      slug: 'douyin',            system: '抖音来客',          version: 'v2.5.1', health: 82, stores: 624,  quotaPct: 64, errorRate: '0.28%', lastUpgrade: '03-15', status: 'warn', statusLabel: '权审中' },
  { id: '9',  name: '易鼎',          slug: 'yiding',            system: '易鼎 ERP',          version: 'v1.8.2', health: 91, stores: 42,   quotaPct: 12, errorRate: '0.07%', lastUpgrade: '04-01', status: 'pass', statusLabel: '正常' },
  { id: '10', name: '诺诺发票',      slug: 'nuonuo',            system: '诺诺电子发票',      version: 'v2.1.0', health: 96, stores: 847,  quotaPct: 54, errorRate: '0.02%', lastUpgrade: '04-14', status: 'pass', statusLabel: '正常' },
  { id: '11', name: '小红书',        slug: 'xiaohongshu',       system: '小红书开放平台',    version: 'v1.4.0', health: 75, stores: 218,  quotaPct: 38, errorRate: '0.51%', lastUpgrade: '02-20', status: 'warn', statusLabel: '需关注' },
  { id: '12', name: 'ERP通用',       slug: 'erp',               system: 'ERP 通用协议',      version: 'v3.0.1', health: 93, stores: 142,  quotaPct: 42, errorRate: '0.09%', lastUpgrade: '04-10', status: 'pass', statusLabel: '正常' },
  { id: '13', name: '物流配送',      slug: 'logistics',         system: '物流配送聚合',      version: 'v2.2.0', health: 88, stores: 412,  quotaPct: 67, errorRate: '0.13%', lastUpgrade: '04-06', status: 'pass', statusLabel: '正常' },
  { id: '14', name: '外卖聚合工厂',  slug: 'delivery_factory',  system: '外卖聚合工厂',      version: 'v2.0.0', health: 95, stores: 847,  quotaPct: 78, errorRate: '0.05%', lastUpgrade: '04-16', status: 'pass', statusLabel: '正常' },
  { id: '15', name: '微信外卖',      slug: 'wechat_delivery',   system: '微信外卖小程序',    version: 'v1.6.0', health: 91, stores: 324,  quotaPct: 48, errorRate: '0.11%', lastUpgrade: '04-03', status: 'pass', statusLabel: '正常' },
]

const UPGRADES = [
  { date: '04-28', adapter: '客如云', from: 'v2.9.4', to: 'v3.0.0', note: 'API v3 兼容升级' },
  { date: '05-01', adapter: '抖音来客', from: 'v2.5.1', to: 'v2.6.0', note: '权限审核修复' },
  { date: '05-05', adapter: '小红书', from: 'v1.4.0', to: 'v1.5.0', note: '错误率优化' },
  { date: '05-10', adapter: '饿了么', from: 'v3.8.0', to: 'v3.9.0', note: '新增批量订单接口' },
  { date: '05-15', adapter: '美团SaaS', from: 'v4.0.3', to: 'v4.1.0', note: '门店分组 API 对接' },
]

const WARNINGS = [
  { adapter: '客如云', msg: 'API v2 将于 2026-06-01 停用，需升级至 v3.0.0 适配新鉴权', severity: 'high' as const },
  { adapter: '抖音来客', msg: '团购券核销权限变更，需补充 ICP+食品经营许可证白名单', severity: 'medium' as const },
]

const COLUMNS: Column<Adapter>[] = [
  { key: 'name',     label: 'Adapter',  render: r => <div><div style={{ fontWeight: 500 }}>{r.name}</div><div className="lbl-sm muted">{r.slug}</div></div> },
  { key: 'system',   label: '对接系统',  render: r => <span className="dim">{r.system}</span> },
  { key: 'version',  label: '当前版本',  render: r => <span className="mono ember-soft">{r.version}</span>, align: 'right' },
  { key: 'health',   label: '健康',      render: r => (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
        background: r.health >= 90 ? 'var(--green-400)' : 'var(--amber-400)'
      }} />
      <span className="mono" style={{ color: r.health >= 90 ? 'var(--green-400)' : 'var(--amber-400)' }}>{r.health}</span>
    </span>
  ), align: 'right' },
  { key: 'stores',   label: '接入店',    render: r => <span className="mono">{r.stores.toLocaleString()}</span>, align: 'right' },
  { key: 'quota',    label: 'API配额',   render: r => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ flex: 1, height: 4, background: 'var(--bg-surface)', borderRadius: 2, minWidth: 40 }}>
        <div style={{ width: `${r.quotaPct}%`, height: '100%', borderRadius: 2, background: r.quotaPct > 85 ? 'var(--ember-500)' : 'var(--green-400)' }} />
      </div>
      <span className="mono muted" style={{ fontSize: 10, width: 28, textAlign: 'right' }}>{r.quotaPct}%</span>
    </div>
  ) },
  { key: 'errorRate', label: '30d错误率', render: r => <span className="mono" style={{ color: parseFloat(r.errorRate) > 0.3 ? 'var(--ember-500)' : 'var(--text-tertiary)' }}>{r.errorRate}</span>, align: 'right' },
  { key: 'lastUpgrade', label: '上版本',  render: r => <span className="mono muted">{r.lastUpgrade}</span>, align: 'right' },
  { key: 'status',   label: '状态',      render: r => <Badge kind={r.status}>{r.statusLabel}</Badge> },
]

export default function AdaptersPage() {
  return (
    <>
      <PageHeader
        crumb="ECOSYSTEM / 旧系统 Adapter"
        title="15 个 Adapter 矩阵"
        subtitle="承载 23 套替换叙事 · 平均健康度 92 · 接入 1,247 店"
        actions={<>
          <Button size="sm" variant="ghost">兼容矩阵</Button>
          <Button size="sm" variant="secondary">升级日历</Button>
        </>}
      />

      <Card padding={0} style={{ overflow: 'hidden', marginBottom: 12 }}>
        <Table columns={COLUMNS} data={ADAPTERS} rowKey={r => r.id} />
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {/* 本月升级日历 */}
        <Card>
          <div className="lbl ember" style={{ marginBottom: 8 }}>— 本月升级日历 · {UPGRADES.length}</div>
          {UPGRADES.map(u => (
            <div key={u.date + u.adapter} style={{
              display: 'grid', gridTemplateColumns: '48px 80px 1fr',
              gap: 8, alignItems: 'center',
              borderBottom: '0.5px dotted var(--border-tertiary)',
              padding: '5px 0', fontSize: 11
            }}>
              <span className="mono ember-soft">{u.date}</span>
              <span style={{ fontWeight: 500 }}>{u.adapter}</span>
              <span className="muted">{u.from} → {u.to} · {u.note}</span>
            </div>
          ))}
        </Card>

        {/* 兼容性预警 */}
        <Card variant="warn">
          <div className="lbl ember" style={{ marginBottom: 8 }}>— 兼容性预警 · {WARNINGS.length}</div>
          {WARNINGS.map(w => (
            <div key={w.adapter} style={{
              borderBottom: '0.5px dotted var(--border-tertiary)',
              padding: '6px 0', fontSize: 11
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ fontWeight: 500 }}>{w.adapter}</span>
                <Badge kind={w.severity === 'high' ? 'fail' : 'warn'}>{w.severity === 'high' ? '高' : '中'}</Badge>
              </div>
              <div className="muted">{w.msg}</div>
            </div>
          ))}
        </Card>
      </div>
    </>
  )
}
