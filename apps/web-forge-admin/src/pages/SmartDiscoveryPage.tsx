// 智能发现引擎 · 意图搜索 + Agent组合推荐
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

const KPI = [
  { label: '本月搜索',     value: '2,847',  delta: { text: '次',         tone: 'soft'    as const } },
  { label: '点击率',       value: '38.2%',  delta: { text: '▲ 5.1%',    tone: 'success' as const } },
  { label: '组合推荐',     value: '12',     delta: { text: '套活跃',     tone: 'soft'    as const } },
  { label: '通过组合安装',  value: '+24%',   delta: { text: '安装提升',   tone: 'success' as const } },
]

/* ─── 场景化推荐 ─── */
interface ScenarioRow {
  id: string
  role: string
  pain: string
  combo: string
  appCount: number
  synergyScore: number
}

const SCENARIO_DATA: ScenarioRow[] = [
  { id: '1', role: '品牌总监', pain: '跨店对比效率低',     combo: '经营驾驶舱+数据分析+异常检测',  appCount: 3, synergyScore: 92 },
  { id: '2', role: '门店店长', pain: '午市客流持续下降',   combo: '客流预测+智能配菜+支付后营销',  appCount: 3, synergyScore: 88 },
  { id: '3', role: '运营经理', pain: '会员复购率不达标',   combo: '会员洞察+私域运营+优惠券引擎',  appCount: 3, synergyScore: 85 },
  { id: '4', role: '财务总监', pain: '成本核算跨系统',     combo: '财务稽核+库存预警+供应商管理',  appCount: 3, synergyScore: 90 },
]

const SCENARIO_COLS: Column<ScenarioRow>[] = [
  { key: 'role',         label: '角色',     render: r => <span style={{ fontWeight: 500 }}>{r.role}</span>, width: 80 },
  { key: 'pain',         label: '痛点',     render: r => <span className="muted">{r.pain}</span>, width: 140 },
  { key: 'combo',        label: '推荐组合', render: r => <span style={{ fontSize: 11 }}>{r.combo}</span>, width: 200 },
  { key: 'appCount',     label: '应用数',   render: r => <span className="mono">{r.appCount}</span>, width: 56, align: 'center' },
  { key: 'synergyScore', label: '协同分',   render: r => (
    <span className="mono" style={{ color: r.synergyScore >= 90 ? 'var(--green-400)' : 'var(--amber-400)' }}>
      {r.synergyScore}
    </span>
  ), width: 64, align: 'center' },
]

const HOT_QUERIES = [
  { query: '午市客流下降',       count: 247, ctr: '42%' },
  { query: '会员复购提升',       count: 198, ctr: '38%' },
  { query: '菜品成本优化',       count: 176, ctr: '35%' },
  { query: '外卖渠道对比',       count: 142, ctr: '41%' },
  { query: '库存周转率低',       count: 128, ctr: '37%' },
  { query: '排班效率提升',       count: 114, ctr: '33%' },
  { query: '宴席预订管理',       count: 97,  ctr: '29%' },
  { query: '食安检查自动化',     count: 86,  ctr: '44%' },
  { query: '客诉处理流程',       count: 73,  ctr: '36%' },
  { query: '新店选址分析',       count: 64,  ctr: '31%' },
]

export default function SmartDiscoveryPage() {
  return (
    <>
      <PageHeader
        crumb="ECOSYSTEM / 智能发现"
        title="智能发现引擎"
        subtitle="意图搜索 · Agent 组合推荐 · 场景化着陆"
        actions={<>
          <Button size="sm" variant="ghost">搜索分析</Button>
          <Button size="sm" variant="secondary">组合管理</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 意图搜索演示 */}
      <Card variant="emphasis" style={{ marginBottom: 12 }}>
        <div className="lbl ember" style={{ marginBottom: 10 }}>— 意图搜索演示</div>

        {/* 搜索输入 */}
        <div style={{
          padding: '10px 14px', background: 'var(--bg-surface)', borderRadius: 8,
          border: '1px solid var(--border-secondary)', fontSize: 14, color: '#fff', marginBottom: 12
        }}>
          "午市客流下降怎么办"
        </div>

        {/* 解析意图 */}
        <div style={{ marginBottom: 12 }}>
          <span className="lbl-sm muted" style={{ marginRight: 8 }}>解析意图</span>
          {['客流预测', '营销触达', '菜品优化'].map(tag => (
            <Badge key={tag} kind="skill" style={{ marginRight: 4 }}>{tag}</Badge>
          ))}
        </div>

        {/* 推荐结果 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 10 }}>
          {[
            { name: '客流预测Agent', star: '4.6', installs: '3.2k' },
            { name: '智能配菜Agent', star: '4.8', installs: '2.1k' },
            { name: '支付后营销',     star: '4.5', installs: '1.8k' },
          ].map(r => (
            <div key={r.name} style={{
              padding: '10px 12px', background: 'var(--bg-surface)', borderRadius: 8,
              border: '1px solid var(--border-tertiary)'
            }}>
              <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 4 }}>{r.name}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                <span className="mono" style={{ color: 'var(--amber-400)' }}>&#9733;{r.star}</span>
                <span className="muted">{r.installs}安装</span>
              </div>
            </div>
          ))}
        </div>

        {/* 组合推荐 */}
        <div style={{ textAlign: 'center' }}>
          <Badge kind="integration">三件协同 效果+40%</Badge>
        </div>
      </Card>

      {/* row-2: 场景化推荐 + 热门搜索 */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>场景化推荐</div>
          <Table columns={SCENARIO_COLS} data={SCENARIO_DATA} rowKey={r => r.id} />
        </Card>

        <Card>
          <div className="lbl ember" style={{ marginBottom: 8 }}>— 热门搜索 · Top 10</div>
          {HOT_QUERIES.map((q, i) => (
            <div key={q.query} style={{
              display: 'grid', gridTemplateColumns: '16px 1fr auto auto',
              gap: 8, alignItems: 'center',
              padding: '4px 0', fontSize: 11,
              borderBottom: i < HOT_QUERIES.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none'
            }}>
              <span className="mono dim" style={{ fontSize: 10 }}>{i + 1}</span>
              <span style={{ fontWeight: i < 3 ? 500 : 400 }}>{q.query}</span>
              <span className="mono muted">{q.count}</span>
              <span className="mono" style={{ color: 'var(--green-400)', fontSize: 10 }}>{q.ctr}</span>
            </div>
          ))}
        </Card>
      </div>
    </>
  )
}
