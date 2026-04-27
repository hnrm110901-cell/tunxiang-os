// 数据分析 · 多维分析仪表板
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'

const TABS = ['商品热度', 'ISV健康度', 'GMV趋势', '流失分析', '客户画像']

const TOP10_PRODUCTS = [
  { rank: '01', name: '美团Adapter',  installs: '8.7k' },
  { rank: '02', name: '微信支付',     installs: '5.4k' },
  { rank: '03', name: '饿了么',       installs: '5.1k' },
  { rank: '04', name: '智能配菜',     installs: '3.2k' },
  { rank: '05', name: '自动赠饮',     installs: '2.1k' },
  { rank: '06', name: 'L0-PZ主题',    installs: '1.8k' },
  { rank: '07', name: '客流热力',     installs: '942' },
  { rank: '08', name: '海鲜溯源',     installs: '412' },
]

const RISING = [
  { name: 'L0-TCSL',   delta: '+412%' },
  { name: '微信支付',   delta: '+184%' },
  { name: '春节流量',   delta: '+147%' },
  { name: '智能配菜',   delta: '+94%' },
  { name: '桌台排队',   delta: '+62%' },
]

const FALLING = [
  { name: '客如云',   delta: '-32%' },
  { name: '抖音来客', delta: '-18%' },
  { name: '夜间增亮', delta: '-12%' },
]

const CUSTOMER_TYPES = [
  { label: 'A类直营', count: '412店', color: 'var(--ember-500)' },
  { label: 'B类中型', count: '624店', color: 'var(--blue-400)' },
  { label: 'C类Lite', count: '211店', color: 'var(--ink-400)' },
]

/* === Revenue Intelligence Data === */

const COHORT_HEADERS = ['M0', 'M1', 'M2', 'M3', 'M6', 'M12']

const COHORT_DATA = [
  { cohort: '2025-Q1', values: [100, 92, 87, 84, 78, 72] },
  { cohort: '2025-Q2', values: [100, 94, 89, 86, 81, null] },
  { cohort: '2025-Q3', values: [100, 91, 85, 82, null, null] },
  { cohort: '2025-Q4', values: [100, 93, 88, null, null, null] },
  { cohort: '2026-Q1', values: [100, 95, null, null, null, null] },
]

const CHURN_RISKS = [
  { level: '高风险(30天内)', stores: 14, mrr: '¥4.2k', color: 'var(--ember-500)' },
  { level: '中风险(60天内)', stores: 28, mrr: '¥6.8k', color: 'var(--amber-500)' },
  { level: '低风险(90天内)', stores: 42, mrr: '¥8.4k', color: 'var(--text-tertiary)' },
]

const CHURN_SIGNALS = [
  { signal: '登录频率下降 >50%', count: '18 店' },
  { signal: 'Skill 使用量骤降', count: '12 店' },
  { signal: '退订率环比上升', count: '8 店' },
  { signal: '客诉未解决 >7d', count: '4 店' },
]

const EXPANSION_ITEMS = [
  { title: 'Upsell 机会', desc: '47 店可升级套餐', impact: '预计 +¥14k MRR' },
  { title: 'Cross-sell 机会', desc: '124 店未安装高匹配 Skill', impact: '预计 +¥8.2k MRR' },
  { title: '价格优化', desc: '3 个 Skill 定价低于价值', impact: '提价 10% 影响 <2% 退订' },
]

function retentionColor(val: number | null): string {
  if (val === null) return 'transparent'
  if (val >= 90) return 'rgba(34,197,94,0.18)'
  if (val >= 80) return 'rgba(245,158,11,0.18)'
  return 'rgba(239,68,68,0.18)'
}

function retentionTextColor(val: number | null): string {
  if (val === null) return 'var(--text-tertiary)'
  if (val >= 90) return 'var(--green-400, #4ade80)'
  if (val >= 80) return 'var(--amber-400, #fbbf24)'
  return 'var(--ember-500)'
}

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader
        crumb="BUSINESS / 数据分析"
        title="数据分析"
        subtitle="商品 / ISV / GMV / 流失 多维分析"
        actions={<>
          <Button size="sm" variant="ghost">自定义报表</Button>
          <Button size="sm" variant="secondary">订阅周报</Button>
        </>}
      />

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {TABS.map((tab, i) => (
          <span key={tab} style={{
            padding: '6px 12px',
            fontSize: 12,
            color: i === 0 ? 'var(--ember-500)' : 'var(--text-secondary)',
            cursor: 'pointer',
            borderBottom: i === 0 ? '2px solid var(--ember-500)' : '2px solid transparent',
            fontWeight: i === 0 ? 500 : 400
          }}>{tab}</span>
        ))}
      </div>

      {/* Top section: 2-col grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* Left: Top 10 Products */}
        <Card>
          <div style={{ marginBottom: 10, fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            本周Top10商品 <span className="muted" style={{ fontSize: 11 }}>by installs</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {TOP10_PRODUCTS.map((p, i) => (
              <div key={p.rank} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '3px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12
              }}>
                <span>
                  <span className="mono" style={{
                    color: i < 3 ? 'var(--ember-500)' : 'var(--text-tertiary)',
                    fontWeight: i < 3 ? 600 : 400,
                    marginRight: 8
                  }}>{p.rank}</span>
                  {p.name}
                </span>
                <span className="mono muted">{p.installs}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Right: Rising & Falling */}
        <Card>
          <div style={{ marginBottom: 10, fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            本周Top5上升商品
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
            {RISING.map(r => (
              <div key={r.name} style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '3px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12
              }}>
                <span>{r.name}</span>
                <span className="mono ember">{r.delta}</span>
              </div>
            ))}
          </div>

          <div style={{ borderTop: '1px solid var(--border-secondary)', paddingTop: 10 }}>
            <div className="lbl-sm dim" style={{ marginBottom: 6 }}>下降Top3</div>
            {FALLING.map(f => (
              <div key={f.name} style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '3px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12
              }}>
                <span className="muted">{f.name}</span>
                <span className="mono dim">{f.delta}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Bottom section: 3-col grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {/* 客户类型分布 */}
        <Card>
          <div className="lbl" style={{ marginBottom: 10 }}>客户类型分布</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {CUSTOMER_TYPES.map(ct => (
              <div key={ct.label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: ct.color, display: 'inline-block', flexShrink: 0
                }} />
                <span style={{ flex: 1 }}>{ct.label}</span>
                <span className="mono ember-soft">{ct.count}</span>
              </div>
            ))}
          </div>
          <div className="mono muted" style={{ fontSize: 11, marginTop: 8, textAlign: 'right' }}>
            总计 1,247 店
          </div>
        </Card>

        {/* 平均客单 */}
        <Card>
          <div className="lbl" style={{ marginBottom: 10 }}>平均客单</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
            <span className="mono ember" style={{ fontSize: 22, fontWeight: 600 }}>¥1,683</span>
            <span className="mono ember-soft" style={{ fontSize: 11 }}>▲8.2%</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">A类直营</span>
              <span className="mono">¥3,420</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">B类中型</span>
              <span className="mono">¥1,280</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">C类Lite</span>
              <span className="mono">¥680</span>
            </div>
          </div>
        </Card>

        {/* 平均订阅件数 */}
        <Card>
          <div className="lbl" style={{ marginBottom: 10 }}>平均订阅件数</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
            <span className="mono ember" style={{ fontSize: 22, fontWeight: 600 }}>11.5</span>
            <span className="muted" style={{ fontSize: 11 }}>/店</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">A类直营</span>
              <span className="mono">18.2 件</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">B类中型</span>
              <span className="mono">10.6 件</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="muted">C类Lite</span>
              <span className="mono">4.8 件</span>
            </div>
          </div>
        </Card>
      </div>

      {/* === Revenue Intelligence · 对标 Salesforce Revenue Cloud === */}

      {/* Section header */}
      <div style={{
        marginTop: 24, marginBottom: 12, paddingBottom: 8,
        borderBottom: '1px solid var(--border-secondary)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'
      }}>
        <span style={{ fontFamily: 'var(--font-serif)', fontSize: 16, color: '#fff', fontWeight: 500 }}>
          Revenue Intelligence
        </span>
        <span className="mono muted" style={{ fontSize: 11 }}>MRR / ARR / LTV / Cohort</span>
      </div>

      {/* KPI row — grid-4 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        <Card>
          <div className="lbl" style={{ marginBottom: 6 }}>MRR</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="mono ember" style={{ fontSize: 22, fontWeight: 600 }}>¥2.10M</span>
          </div>
          <div className="mono" style={{ fontSize: 11, marginTop: 4, color: 'var(--green-400, #4ade80)' }}>
            ▲ 18.4% MoM
          </div>
        </Card>

        <Card>
          <div className="lbl" style={{ marginBottom: 6 }}>ARR</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="mono ember" style={{ fontSize: 22, fontWeight: 600 }}>¥25.2M</span>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>预测</div>
        </Card>

        <Card>
          <div className="lbl" style={{ marginBottom: 6 }}>平均 LTV</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="mono ember" style={{ fontSize: 22, fontWeight: 600 }}>¥18,247</span>
            <span className="muted" style={{ fontSize: 11 }}>/店</span>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>24 月</div>
        </Card>

        <Card>
          <div className="lbl" style={{ marginBottom: 6 }}>CAC 回收</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="mono ember" style={{ fontSize: 22, fontWeight: 600 }}>4.2</span>
            <span className="muted" style={{ fontSize: 11 }}>月</span>
          </div>
          <div className="mono" style={{ fontSize: 11, marginTop: 4, color: 'var(--green-400, #4ade80)' }}>
            目标 &le; 6
          </div>
        </Card>
      </div>

      {/* Cohort + Churn — grid-2 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* Left: Cohort 留存分析 */}
        <Card>
          <div style={{ marginBottom: 10, fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            Cohort 留存分析
          </div>
          {/* Header row */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '80px repeat(6, 1fr)',
            gap: 4, marginBottom: 4, fontSize: 11
          }}>
            <span className="muted" />
            {COHORT_HEADERS.map(h => (
              <span key={h} className="mono muted" style={{ textAlign: 'center' }}>{h}</span>
            ))}
          </div>
          {/* Data rows */}
          {COHORT_DATA.map(row => (
            <div key={row.cohort} style={{
              display: 'grid',
              gridTemplateColumns: '80px repeat(6, 1fr)',
              gap: 4, marginBottom: 3, fontSize: 11
            }}>
              <span className="mono muted" style={{ fontSize: 10 }}>{row.cohort}</span>
              {row.values.map((val, i) => (
                <span key={i} className="mono" style={{
                  textAlign: 'center',
                  padding: '2px 4px',
                  borderRadius: 3,
                  background: retentionColor(val),
                  color: retentionTextColor(val),
                  fontWeight: val !== null ? 500 : 400,
                  fontSize: 11
                }}>
                  {val !== null ? `${val}%` : '--'}
                </span>
              ))}
            </div>
          ))}
        </Card>

        {/* Right: 预测性流失预警 */}
        <Card variant="emphasis">
          <div style={{ marginBottom: 10, fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            预测性流失预警
          </div>

          {/* Risk tiers */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
            {CHURN_RISKS.map(r => (
              <div key={r.level} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '4px 0', borderBottom: '0.5px dotted var(--border-tertiary)', fontSize: 12
              }}>
                <span style={{ color: r.color, fontWeight: 500 }}>{r.level}</span>
                <span className="mono" style={{ color: r.color }}>
                  {r.stores} 店 · {r.mrr} MRR at risk
                </span>
              </div>
            ))}
          </div>

          {/* 流失信号 */}
          <div style={{ borderTop: '1px solid var(--border-secondary)', paddingTop: 10 }}>
            <div className="lbl-sm dim" style={{ marginBottom: 6 }}>流失信号</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {CHURN_SIGNALS.map(s => (
                <div key={s.signal} style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '2px 0', fontSize: 11
                }}>
                  <span className="muted">{s.signal}</span>
                  <span className="mono ember-soft">{s.count}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 12 }}>
            <Button size="sm" variant="secondary">查看干预建议</Button>
          </div>
        </Card>
      </div>

      {/* 扩展收入机会 */}
      <Card>
        <div style={{ marginBottom: 10, fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
          扩展收入机会
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {EXPANSION_ITEMS.map(item => (
            <div key={item.title} style={{
              padding: '10px 12px',
              borderRadius: 6,
              border: '1px solid var(--border-secondary)',
              background: 'var(--bg-secondary, rgba(255,255,255,0.03))'
            }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: '#fff', marginBottom: 4 }}>
                {item.title}
              </div>
              <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>{item.desc}</div>
              <Badge variant="ember">{item.impact}</Badge>
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
