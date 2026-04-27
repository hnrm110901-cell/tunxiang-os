// 生态飞轮仪表盘 (v3.0)
import { PageHeader, KpiCard, Card, Button } from '@/components/ui'

const KPI_GRID = [
  { label: 'ISV 活跃度',   value: '60.2%',           delta: { text: '目标≥60%',     tone: 'success' as const } },
  { label: '商品质量分',   value: '4.34',            delta: { text: '目标≥4.2',     tone: 'success' as const } },
  { label: '安装密度',     value: '8.2 件/店',       delta: { text: '目标≥8',       tone: 'success' as const } },
  { label: '结果转化率',   value: '12.4%',           delta: { text: '目标≥15%',     tone: 'warn'    as const }, alert: true },
  { label: 'Token 效率',   value: '3.8 结果/千Token', delta: { text: '↑ 月环比',    tone: 'success' as const } },
  { label: '开发者 NPS',   value: '47',              delta: { text: '目标≥50',      tone: 'warn'    as const }, alert: true },
  { label: 'TTHW',         value: '47 min',          delta: { text: '目标≤15 min',  tone: 'warn'    as const }, alert: true },
  { label: '生态 GMV',     value: '¥2.10M',          delta: { text: '↑ 20% MoM',   tone: 'success' as const } },
]

const FLYWHEEL = [
  '更多 ISV',
  '更丰富 Agent',
  '更高安装密度',
  '更多结果收入',
  '更高 ISV 分成',
  '吸引更多 ISV',
]

export default function EcosystemHealthPage() {
  const score = 74
  const prevScore = 68
  const pct = (score / 100) * 360

  return (
    <>
      <PageHeader
        crumb="BUSINESS / 生态健康"
        title="生态飞轮仪表盘"
        subtitle="8 大指标 · 综合评分 74 · 飞轮正在加速"
        actions={<>
          <Button size="sm" variant="ghost">计算指标</Button>
          <Button size="sm" variant="secondary">历史趋势</Button>
        </>}
      />

      {/* 8 KPI grid-4 x 2 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI_GRID.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 综合评分 */}
      <Card style={{ marginBottom: 12, textAlign: 'center', padding: '24px 16px' }}>
        <div className="lbl-sm muted" style={{ marginBottom: 16 }}>综合评分</div>
        <div style={{ position: 'relative', display: 'inline-block', width: 140, height: 140 }}>
          {/* CSS circular progress */}
          <div style={{
            width: 140, height: 140, borderRadius: '50%',
            background: `conic-gradient(var(--green-400) 0deg, var(--green-400) ${pct}deg, var(--bg-surface) ${pct}deg)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <div style={{
              width: 110, height: 110, borderRadius: '50%', background: 'var(--bg-base)',
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            }}>
              <span style={{ fontSize: 36, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {score}
              </span>
              <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>/ 100</span>
            </div>
          </div>
        </div>
        <div style={{ marginTop: 12, fontSize: 13, color: 'var(--text-secondary)' }}>
          vs 上月 {prevScore} · <span style={{ color: 'var(--green-400)', fontWeight: 600 }}>▲ +{score - prevScore}</span>
        </div>
      </Card>

      {/* 飞轮效应 */}
      <Card>
        <div className="lbl-sm muted" style={{ marginBottom: 16 }}>飞轮效应</div>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexWrap: 'wrap', gap: 6, padding: '12px 0',
        }}>
          {FLYWHEEL.map((step, i) => (
            <span key={step} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                padding: '8px 14px', background: 'var(--bg-surface)', borderRadius: 20,
                fontSize: 12, fontWeight: 500, border: '1px solid var(--border-tertiary)',
                whiteSpace: 'nowrap',
              }}>
                {step}
              </span>
              <span style={{ color: 'var(--text-tertiary)', fontSize: 14, fontWeight: 600 }}>
                {i < FLYWHEEL.length - 1 ? '→' : '→ 🔄'}
              </span>
            </span>
          ))}
        </div>
        <div style={{
          marginTop: 12, padding: '10px 12px', background: 'var(--bg-surface)', borderRadius: 4,
          fontSize: 11, color: 'var(--text-tertiary)', lineHeight: 1.8, textAlign: 'center',
        }}>
          飞轮健康度: 6/8 指标达标 · 2 项 (结果转化率、TTHW) 需重点突破<br/>
          飞轮加速策略: 降低 TTHW → 吸引更多 ISV → 提高安装密度 → 提升结果转化
        </div>
      </Card>
    </>
  )
}
