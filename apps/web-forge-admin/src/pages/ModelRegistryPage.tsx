// 模型注册表 · Snowflake Model Registry + MLflow 风格
import { PageHeader, KpiCard, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

/* ── KPI ── */
const KPI = [
  { label: '注册模型',     value: '17',   delta: { text: '▲3 本月',    tone: 'success' as const } },
  { label: '生产中',       value: '12',   delta: { text: '8 fine-tuned', tone: 'soft' as const } },
  { label: '灰度中',       value: '3',    delta: { text: 'A/B 测试',    tone: 'soft' as const } },
  { label: '平均推理延迟',  value: '84ms', delta: { text: 'p99 247ms',   tone: 'soft' as const } },
  { label: '模型漂移告警',  value: '1',    delta: { text: '需关注',      tone: 'warning' as const } },
]

/* ── 模型目录 ── */
interface Model {
  id: string
  name: string
  provider: string
  usage: string
  agent: string
  version: string
  deploy: string
  latency: string
  accuracy: string
  drift: string
  status: 'pass' | 'warn' | 'labs'
  statusLabel: string
}

const MODELS: Model[] = [
  { id: '1',  name: 'tx-discount-guard-v3',  provider: '屯象自研', usage: '折扣风控', agent: '折扣守护', version: 'v3.2.1',       deploy: '生产',    latency: '18ms',  accuracy: '99.2%', drift: '正常', status: 'pass', statusLabel: '正常' },
  { id: '2',  name: 'tx-menu-recommend-v2',   provider: '屯象自研', usage: '菜品推荐', agent: '菜品推荐', version: 'v2.8.0',       deploy: '生产',    latency: '84ms',  accuracy: '94.7%', drift: '正常', status: 'pass', statusLabel: '正常' },
  { id: '3',  name: 'tx-inventory-forecast',  provider: '屯象自研', usage: '库存预测', agent: '库存预警', version: 'v1.4.2',       deploy: '生产',    latency: '31ms',  accuracy: '92.1%', drift: '正常', status: 'pass', statusLabel: '正常' },
  { id: '4',  name: 'tx-traffic-predict-v2',  provider: '屯象自研', usage: '客流预测', agent: '客流预测', version: 'v2.1.0',       deploy: '生产',    latency: '124ms', accuracy: '88.4%', drift: '漂移',  status: 'warn', statusLabel: '漂移' },
  { id: '5',  name: 'claude-sonnet-4',        provider: 'Anthropic', usage: '通用推理', agent: 'Master Agent', version: 'sonnet-4', deploy: '生产',    latency: '847ms', accuracy: '--',    drift: '--',   status: 'pass', statusLabel: '正常' },
  { id: '6',  name: 'claude-haiku-4',         provider: 'Anthropic', usage: '快速分类', agent: '多Agent',     version: 'haiku-4',  deploy: '生产',    latency: '124ms', accuracy: '--',    drift: '--',   status: 'pass', statusLabel: '正常' },
  { id: '7',  name: 'gpt-4o-mini',            provider: 'OpenAI',    usage: '文案生成', agent: '内容Agent',   version: '2024-07',  deploy: '生产',    latency: '412ms', accuracy: '--',    drift: '--',   status: 'pass', statusLabel: '正常' },
  { id: '8',  name: 'tx-churn-predict',       provider: '屯象自研', usage: '流失预测', agent: '会员洞察', version: 'v1.2.0',       deploy: '生产',    latency: '67ms',  accuracy: '91.8%', drift: '正常', status: 'pass', statusLabel: '正常' },
  { id: '9',  name: 'tx-food-safety-cv',      provider: '屯象自研', usage: '后厨视觉', agent: '巡店质检', version: 'v3.0.1',       deploy: '生产',    latency: '247ms', accuracy: '96.4%', drift: '正常', status: 'pass', statusLabel: '正常' },
  { id: '10', name: 'tx-delivery-routing',    provider: '屯象自研', usage: '配送路径', agent: '外卖调度', version: 'v1.1.0',       deploy: '灰度50%', latency: '412ms', accuracy: '87.2%', drift: '--',   status: 'warn', statusLabel: '灰度' },
  { id: '11', name: 'tx-menu-recommend-v3',   provider: '屯象自研', usage: '菜品推荐', agent: '菜品推荐', version: 'v3.0.0-beta',  deploy: '灰度5%',  latency: '72ms',  accuracy: '95.8%', drift: '--',   status: 'labs', statusLabel: '实验' },
  { id: '12', name: 'tx-audit-anomaly',       provider: '屯象自研', usage: '异常检测', agent: '财务稽核', version: 'v2.0.0-rc',    deploy: '灰度10%', latency: '89ms',  accuracy: '94.1%', drift: '--',   status: 'labs', statusLabel: '实验' },
]

const MODEL_COLUMNS: Column<Model>[] = [
  { key: 'name',     label: '模型',     render: r => <span className="mono" style={{ fontWeight: 500, fontSize: 12 }}>{r.name}</span> },
  { key: 'provider', label: 'Provider', render: r => <span style={{ fontSize: 12 }}>{r.provider}</span> },
  { key: 'usage',    label: '用途',     render: r => <span style={{ fontSize: 12 }}>{r.usage}</span> },
  { key: 'agent',    label: 'Agent',    render: r => <span className="muted" style={{ fontSize: 12 }}>{r.agent}</span> },
  { key: 'version',  label: '版本',     render: r => <span className="mono dim" style={{ fontSize: 11 }}>{r.version}</span> },
  { key: 'deploy',   label: '部署',     render: r => (
    <Badge kind={r.deploy === '生产' ? 'active' : 'paused'}>{r.deploy}</Badge>
  )},
  { key: 'latency',  label: '推理延迟', render: r => <span className="mono">{r.latency}</span>, align: 'right' },
  { key: 'accuracy', label: '准确率',   render: r => <span className="mono ember-soft">{r.accuracy}</span>, align: 'right' },
  { key: 'drift',    label: '漂移',     render: r => (
    <span className={r.drift === '漂移' ? 'mono ember' : 'mono muted'} style={{ fontSize: 11 }}>{r.drift}</span>
  )},
  { key: 'status',   label: '状态',     render: r => <Badge kind={r.status}>{r.statusLabel}</Badge> },
]

/* ── 版本管理时间线 ── */
const VERSION_TIMELINE = [
  { version: 'v3.0.0-beta', deploy: '灰度5%',  date: '04-25', accuracy: '95.8%', delta: '+1.1%', current: true },
  { version: 'v2.8.0',      deploy: '生产',     date: '04-12', accuracy: '94.7%', delta: '',      current: false },
  { version: 'v2.7.0',      deploy: '归档',     date: '03-28', accuracy: '93.2%', delta: '',      current: false },
  { version: 'v2.5.0',      deploy: '归档',     date: '03-01', accuracy: '91.4%', delta: '',      current: false },
]

/* ── A/B 测试 ── */
const AB_TESTS = [
  { name: '菜品推荐 v2.8 vs v3.0-beta', traffic: '5%',  days: 3, metric: '转化率 +2.4%',  pValue: 0.034, significant: true },
  { name: '配送路径 v1.0 vs v1.1',       traffic: '50%', days: 7, metric: '配送时效 -3min', pValue: 0.087, significant: false },
  { name: '异常检测 v1.x vs v2.0-rc',    traffic: '10%', days: 1, metric: '数据不足',       pValue: null,  significant: false },
]

export default function ModelRegistryPage() {
  return (
    <>
      <PageHeader
        crumb="AI OPS / 模型注册表"
        title="模型注册表"
        subtitle="17 模型 · 4 Provider · 最新部署 2h 前"
        actions={<>
          <Button size="sm" variant="ghost">部署历史</Button>
          <Button size="sm" variant="secondary">性能基准</Button>
          <Button size="sm" variant="primary">注册新模型</Button>
        </>}
      />

      {/* KPI 行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 模型目录表 */}
      <Card padding={0} style={{ overflow: 'hidden', marginBottom: 12 }}>
        <div style={{ padding: '10px 14px 0', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
          模型目录 <span className="muted" style={{ fontSize: 11 }}>12 条记录</span>
        </div>
        <Table columns={MODEL_COLUMNS} data={MODELS} rowKey={r => r.id} />
      </Card>

      {/* grid-2: 版本管理 + 漂移检测 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* 左: 版本管理 */}
        <Card>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 12 }}>
            版本管理 · tx-menu-recommend
          </div>
          {VERSION_TIMELINE.map((v, i) => (
            <div key={v.version} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 0',
              borderBottom: i < VERSION_TIMELINE.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
            }}>
              {/* 时间线节点 */}
              <div style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: v.current ? 'var(--ember-500)' : v.deploy === '生产' ? 'var(--green-400)' : 'var(--ink-400)',
                flexShrink: 0,
              }} />
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                  <span className="mono" style={{ fontWeight: 500, fontSize: 12 }}>{v.version}</span>
                  <Badge kind={v.deploy === '生产' ? 'active' : v.deploy === '归档' ? 'paused' : 'labs'}>
                    {v.deploy}
                  </Badge>
                </div>
                <div style={{ fontSize: 11 }}>
                  <span className="muted">{v.date}</span>
                  <span className="dim" style={{ margin: '0 6px' }}>·</span>
                  <span className="muted">准确率 </span>
                  <span className="mono ember-soft">{v.accuracy}</span>
                  {v.delta && (
                    <span className="mono ember" style={{ marginLeft: 4, fontSize: 10 }}>{v.delta}</span>
                  )}
                </div>
              </div>
              {v.current && (
                <span style={{ fontSize: 10, color: 'var(--ember-500)' }}>&#9650; 趋势上升</span>
              )}
            </div>
          ))}
          {/* 趋势箭头 */}
          <div style={{ marginTop: 8, textAlign: 'right', fontSize: 11 }}>
            <span className="mono ember-soft">91.4% → 95.8%</span>
            <span className="mono ember" style={{ marginLeft: 6 }}>▲ +4.4pp</span>
          </div>
        </Card>

        {/* 右: 漂移检测 */}
        <Card style={{ border: '1px solid var(--amber-200)' }}>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--amber-200)', marginBottom: 12 }}>
            漂移检测
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--amber-200)', display: 'inline-block' }} />
              <span className="mono" style={{ fontSize: 12, fontWeight: 500 }}>tx-traffic-predict-v2</span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6, paddingLeft: 14 }}>
              <div>预测偏差从 <span className="mono ember">±8%</span> 扩大到 <span className="mono ember">±14%</span></div>
            </div>
          </div>
          <div style={{ borderTop: '0.5px dotted var(--border-tertiary)', paddingTop: 8, marginBottom: 10 }}>
            <div className="lbl-sm dim" style={{ marginBottom: 4 }}>原因推测</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              五一假期模式 vs 平日训练集，节假日客流规律与日常差异显著
            </div>
          </div>
          <div style={{ borderTop: '0.5px dotted var(--border-tertiary)', paddingTop: 8, marginBottom: 12 }}>
            <div className="lbl-sm dim" style={{ marginBottom: 4 }}>建议</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              补充节假日数据重训，覆盖春节/五一/十一/暑假模式
            </div>
          </div>
          <Button size="sm" variant="primary">触发重训 pipeline</Button>
        </Card>
      </div>

      {/* A/B 测试面板 */}
      <Card>
        <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff', marginBottom: 12 }}>
          A/B 测试面板 <span className="muted" style={{ fontSize: 11 }}>3 实验进行中</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {AB_TESTS.map((t, i) => (
            <div key={t.name} style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 0',
              borderBottom: i < AB_TESTS.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 3 }}>{t.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  <span className="mono muted">{t.traffic}</span>
                  <span className="dim" style={{ margin: '0 6px' }}>·</span>
                  <span className="muted">运行 {t.days} 天</span>
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className={`mono ${t.significant ? 'ember' : 'muted'}`} style={{ fontSize: 13, marginBottom: 2 }}>
                  {t.metric}
                </div>
                <div style={{ fontSize: 11 }}>
                  {t.pValue !== null ? (
                    <>
                      <span className="mono muted">p={t.pValue}</span>
                      {t.significant ? (
                        <Badge kind="pass" style={{ marginLeft: 6 }}>显著</Badge>
                      ) : (
                        <Badge kind="paused" style={{ marginLeft: 6 }}>未达标</Badge>
                      )}
                    </>
                  ) : (
                    <span className="dim">数据不足</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
