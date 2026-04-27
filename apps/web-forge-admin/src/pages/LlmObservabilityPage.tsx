// LLM 可观测 · Token / 成本 / 延迟 / 幻觉检测
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '本月 Token',   value: '47.2M',  delta: { text: '▲ 18%',        tone: 'warn' as const } },
  { label: '本月成本',      value: '¥28.4k', delta: { text: '▲ 12%',        tone: 'warn' as const } },
  { label: '日均调用',      value: '142k',   delta: { text: '次',            tone: 'soft' as const } },
  { label: '平均延迟',      value: '184ms',  delta: { text: 'p99 847ms',    tone: 'soft' as const } },
  { label: '幻觉检测率',    value: '0.12%',  delta: { text: '↓ 0.04%',      tone: 'success' as const } },
  { label: '成本/千次',     value: '¥0.20',  delta: { text: '↓ 8%',         tone: 'success' as const } },
]

const PROVIDERS = [
  { name: 'Anthropic (Claude)', cost: '¥18.2k', pct: 64, note: '主力推理 + Master Agent', color: 'var(--ember-500)' },
  { name: '屯象自研模型',        cost: '¥4.2k',  pct: 15, note: '10 个 fine-tuned 模型 (GPU 成本)', color: 'var(--blue-400)' },
  { name: 'OpenAI',             cost: '¥3.8k',  pct: 13, note: '文案 + 辅助', color: 'var(--green-400)' },
  { name: '阿里通义',            cost: '¥2.2k',  pct: 8,  note: '中文特化场景', color: 'var(--ink-400)' },
]

const AGENTS = [
  { name: 'Master Agent',  tokens: '12.4M', cost: '¥8.2k', note: '最大消费者' },
  { name: '菜品推荐',       tokens: '8.7M',  cost: '¥4.1k', note: '' },
  { name: '会员洞察',       tokens: '6.2M',  cost: '¥3.8k', note: '' },
  { name: '客流预测',       tokens: '5.8M',  cost: '¥3.2k', note: '' },
  { name: '外卖调度',       tokens: '4.1M',  cost: '¥2.8k', note: '' },
  { name: '其他 4 Agent',   tokens: '10.0M', cost: '¥6.3k', note: '' },
]

const LATENCY_PCTS = [
  { label: 'p50', value: 84,  display: '84ms',  color: 'var(--green-400)' },
  { label: 'p75', value: 147, display: '147ms', color: 'var(--green-400)' },
  { label: 'p90', value: 284, display: '284ms', color: 'var(--amber-400)' },
  { label: 'p95', value: 412, display: '412ms', color: 'var(--amber-400)' },
  { label: 'p99', value: 847, display: '847ms', color: 'var(--ember-500)' },
]

interface ModelLatency {
  model: string
  calls: string
  p50: string
  p90: string
  p99: string
  errorRate: string
}

const MODEL_LATENCY: ModelLatency[] = [
  { model: 'claude-sonnet-4',   calls: '24k',  p50: '284ms', p90: '624ms', p99: '847ms', errorRate: '0.02%' },
  { model: 'claude-haiku-4',    calls: '87k',  p50: '42ms',  p90: '124ms', p99: '284ms', errorRate: '0.01%' },
  { model: 'tx-自研 (GPU)',      calls: '142k', p50: '31ms',  p90: '84ms',  p99: '247ms', errorRate: '0.04%' },
  { model: 'gpt-4o-mini',       calls: '18k',  p50: '124ms', p90: '412ms', p99: '847ms', errorRate: '0.08%' },
  { model: 'qwen-turbo',        calls: '12k',  p50: '67ms',  p90: '184ms', p99: '412ms', errorRate: '0.03%' },
]

const MODEL_COLS: Column<ModelLatency>[] = [
  { key: 'model',     label: '模型',     render: r => <span className="mono" style={{ fontWeight: 500 }}>{r.model}</span> },
  { key: 'calls',     label: '调用次数', render: r => <span className="mono">{r.calls}</span>, width: 80, align: 'right' },
  { key: 'p50',       label: 'p50',      render: r => <span className="mono">{r.p50}</span>, width: 80, align: 'right' },
  { key: 'p90',       label: 'p90',      render: r => <span className="mono">{r.p90}</span>, width: 80, align: 'right' },
  { key: 'p99',       label: 'p99',      render: r => <span className="mono ember-soft">{r.p99}</span>, width: 80, align: 'right' },
  { key: 'errorRate', label: '错误率',   render: r => <span className="mono" style={{ color: parseFloat(r.errorRate) >= 0.05 ? 'var(--ember-500)' : 'var(--text-secondary)' }}>{r.errorRate}</span>, width: 72, align: 'right' },
]

const HALLUCINATION_CATEGORIES = [
  { label: '价格幻觉',  count: 142, desc: 'Agent 生成错误价格', tone: 'ember' },
  { label: '菜品不存在', count: 87,  desc: '推荐已下架菜品',    tone: 'warn' },
  { label: '数据编造',   count: 68,  desc: '虚构统计数据',      tone: 'warn' },
  { label: '逻辑矛盾',   count: 44,  desc: '前后推理矛盾',      tone: 'soft' },
]

const OPTIMIZATIONS = [
  '将菜品推荐的 few-shot 从 8 例减到 4 例，预计省 22% Token（¥902/月）且准确率不降',
  '外卖调度可从 Claude Sonnet 降级到 Haiku，延迟减 60%，成本减 70%',
  'Master Agent 的长上下文调用中 40% 可启用缓存，月省约 ¥3.2k',
]

const DAILY_COSTS = [
  680, 720, 840, 910, 780, 650, 620, 880, 950, 1020,
  980, 870, 920, 1050, 1100, 940, 860, 790, 830, 970,
  1040, 1080, 990, 920, 870, 950, 1010, 1060, 980, 900,
]

export default function LlmObservabilityPage() {
  const maxDaily = Math.max(...DAILY_COSTS)

  return (
    <>
      <PageHeader
        crumb="AI OPS / LLM 可观测"
        title="LLM 可观测性"
        subtitle="本月 Token 消耗 47.2M · 成本 ¥28.4k · 4 Provider"
        actions={<>
          <Button size="sm" variant="ghost">成本报告</Button>
          <Button size="sm" variant="secondary">预算预警</Button>
          <Button size="sm" variant="primary">Provider 配置</Button>
        </>}
      />

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* Section 1: Provider 成本分解 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* Left: Provider 成本占比 */}
        <Card>
          <div className="lbl" style={{ marginBottom: 12 }}>Provider 成本占比</div>

          {/* Stacked bar */}
          <div style={{ display: 'flex', height: 24, borderRadius: 4, overflow: 'hidden', marginBottom: 14 }}>
            {PROVIDERS.map(p => (
              <div key={p.name} style={{
                width: `${p.pct}%`,
                background: p.color,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                {p.pct >= 13 && <span style={{ fontSize: 10, fontWeight: 600, color: '#000' }}>{p.pct}%</span>}
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {PROVIDERS.map(p => (
              <div key={p.name} style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '4px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12,
              }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: p.color, display: 'inline-block', flexShrink: 0
                }} />
                <span style={{ flex: 1 }}>{p.name}</span>
                <span className="mono ember-soft" style={{ width: 56, textAlign: 'right' }}>{p.cost}</span>
                <span className="mono muted" style={{ width: 32, textAlign: 'right' }}>{p.pct}%</span>
              </div>
            ))}
          </div>
          <div className="muted" style={{ fontSize: 10, marginTop: 8 }}>
            {PROVIDERS.map(p => `${p.name.split(' ')[0]}: ${p.note}`).join(' · ')}
          </div>
        </Card>

        {/* Right: Token 消耗 by Agent */}
        <Card>
          <div className="lbl" style={{ marginBottom: 12 }}>Token 消耗 by Agent</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {AGENTS.map((a, i) => (
              <div key={a.name} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '5px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12,
              }}>
                <span>
                  <span className="mono" style={{
                    color: i === 0 ? 'var(--ember-500)' : 'var(--text-secondary)',
                    fontWeight: i === 0 ? 600 : 400,
                    marginRight: 8,
                  }}>{String(i + 1).padStart(2, '0')}</span>
                  {a.name}
                  {a.note && <span className="muted" style={{ fontSize: 10, marginLeft: 6 }}>({a.note})</span>}
                </span>
                <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <span className="mono muted">{a.tokens} tok</span>
                  <span className="mono ember-soft" style={{ width: 52, textAlign: 'right' }}>{a.cost}</span>
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Section 2: 延迟分析 */}
      <Card style={{ marginBottom: 12 }}>
        <div className="lbl" style={{ marginBottom: 4 }}>延迟分布 · 本周</div>
        <div className="lbl-sm dim" style={{ marginBottom: 14 }}>Percentile breakdown</div>

        {/* Latency bars */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16, height: 120, marginBottom: 16, paddingLeft: 8 }}>
          {LATENCY_PCTS.map(p => {
            const h = Math.round((p.value / 847) * 100)
            return (
              <div key={p.label} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, gap: 4 }}>
                <span className="mono" style={{ fontSize: 11, color: p.color, fontWeight: 600 }}>{p.display}</span>
                <div style={{
                  width: '100%',
                  maxWidth: 48,
                  height: h,
                  background: p.color,
                  borderRadius: '4px 4px 0 0',
                  opacity: 0.85,
                }} />
                <span className="mono dim" style={{ fontSize: 10 }}>{p.label}</span>
              </div>
            )
          })}
        </div>

        {/* Model latency table */}
        <div className="lbl-sm muted" style={{ marginBottom: 8 }}>按模型延迟</div>
        <Table columns={MODEL_COLS} data={MODEL_LATENCY} rowKey={r => r.model} />
      </Card>

      {/* Section 3: 幻觉检测 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* Left: 幻觉检测仪表板 */}
        <Card>
          <div className="lbl" style={{ marginBottom: 10 }}>
            幻觉检测仪表板
            <Badge kind="warn" style={{ marginLeft: 8 }}>4 严重</Badge>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12, marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">本月检测</span>
              <span className="mono">284k 响应</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">幻觉标记</span>
              <span className="mono ember-soft">341 次 (0.12%)</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">严重幻觉</span>
              <span className="mono ember">4 次 (自动拦截)</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">已人工复核</span>
              <span className="mono">287 / 341</span>
            </div>
          </div>

          <div className="lbl-sm dim" style={{ marginBottom: 8 }}>分类明细</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {HALLUCINATION_CATEGORIES.map(c => (
              <div key={c.label} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '4px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12,
              }}>
                <span>
                  <span className={c.tone === 'ember' ? 'ember' : ''} style={{ fontWeight: c.tone === 'ember' ? 600 : 400 }}>{c.label}</span>
                  <span className="muted" style={{ fontSize: 10, marginLeft: 8 }}>{c.desc}</span>
                </span>
                <span className={`mono ${c.tone === 'ember' ? 'ember' : 'ember-soft'}`}>{c.count} 次</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Right: 成本优化建议 */}
        <Card>
          <div className="lbl" style={{ marginBottom: 12 }}>成本优化建议</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {OPTIMIZATIONS.map((opt, i) => (
              <div key={i} style={{
                padding: '10px 12px',
                background: 'var(--surface-secondary)',
                borderRadius: 6,
                borderLeft: '3px solid var(--ember-500)',
                fontSize: 12,
                lineHeight: 1.6,
              }}>
                <span className="mono ember-soft" style={{ fontWeight: 600, marginRight: 8 }}>#{i + 1}</span>
                {opt}
              </div>
            ))}
          </div>
          <div className="muted" style={{ fontSize: 10, marginTop: 12, textAlign: 'right' }}>
            合计可优化 ≈ ¥5.0k/月 (18% 成本)
          </div>
        </Card>
      </div>

      {/* Section 4: 预算与趋势 */}
      <Card>
        <div className="lbl" style={{ marginBottom: 4 }}>30 天成本趋势</div>
        <div className="lbl-sm dim" style={{ marginBottom: 12 }}>日成本 · 颜色由低到高</div>

        {/* Daily cost bars */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 80, marginBottom: 14 }}>
          {DAILY_COSTS.map((cost, i) => {
            const ratio = cost / maxDaily
            const h = Math.round(ratio * 72) + 8
            const color = ratio < 0.75 ? 'var(--green-400)' : ratio < 0.9 ? 'var(--amber-400)' : 'var(--ember-500)'
            return (
              <div key={i} title={`Day ${i + 1}: ¥${cost}`} style={{
                flex: 1,
                height: h,
                background: color,
                borderRadius: '2px 2px 0 0',
                opacity: 0.8,
                cursor: 'default',
              }} />
            )
          })}
        </div>

        {/* Budget progress */}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 8 }}>
          <span className="muted">本月预算 <span className="mono">¥35k</span></span>
          <span>已用 <span className="mono ember-soft">¥28.4k</span> <span className="muted">(81%)</span></span>
          <span className="muted">预计月末 <span className="mono ember">¥34.8k</span></span>
        </div>
        <div style={{
          width: '100%',
          height: 8,
          background: 'var(--surface-tertiary)',
          borderRadius: 4,
          overflow: 'hidden',
        }}>
          <div style={{
            width: '81%',
            height: '100%',
            background: 'linear-gradient(90deg, var(--green-400), var(--amber-400), var(--ember-500))',
            borderRadius: 4,
          }} />
        </div>
      </Card>
    </>
  )
}
