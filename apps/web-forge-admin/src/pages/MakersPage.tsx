// ISV 作坊主管理
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '注册 ISV', value: '147', delta: { text: '累计',     tone: 'soft'    as const } },
  { label: '月活 ISV', value: '84',  delta: { text: '▲ 6 本月', tone: 'success' as const } },
  { label: '本月新晋', value: '12',  delta: { text: '转化 26%', tone: 'success' as const } },
  { label: '实名待审', value: '4',   delta: { text: '需处理',   tone: 'soft'    as const }, alert: true },
]

type TierKind = 'official' | 'isv' | 'active' | 'labs' | 'paused'

interface MakerRow {
  id: string
  name: string
  tier: string
  tierBadge: TierKind
  products: number
  installs: string
  revenue: string
  rating: number
  status: string
  statusBadge: 'active' | 'paused' | 'warn'
}

const MAKERS: MakerRow[] = [
  { id: 'm1', name: '屯象官方',   tier: '顶级', tierBadge: 'official', products: 38,  installs: '124k', revenue: '¥82k',  rating: 4.9, status: '活跃', statusBadge: 'active' },
  { id: 'm2', name: '长沙青菜',   tier: '金牌', tierBadge: 'isv',      products: 12,  installs: '31k',  revenue: '¥24k',  rating: 4.7, status: '活跃', statusBadge: 'active' },
  { id: 'm3', name: '湘味数智',   tier: '金牌', tierBadge: 'isv',      products: 9,   installs: '18k',  revenue: '¥16k',  rating: 4.5, status: '活跃', statusBadge: 'active' },
  { id: 'm4', name: '明厨亮灶',   tier: '标准', tierBadge: 'active',   products: 5,   installs: '6.2k', revenue: '¥4.8k', rating: 4.2, status: '活跃', statusBadge: 'active' },
  { id: 'm5', name: '宴会管家',   tier: '标准', tierBadge: 'active',   products: 3,   installs: '3.1k', revenue: '¥2.1k', rating: 4.0, status: '活跃', statusBadge: 'active' },
  { id: 'm6', name: '川味数据',   tier: '新人', tierBadge: 'labs',     products: 1,   installs: '210',  revenue: '¥120',  rating: 0,   status: '审核中', statusBadge: 'warn' },
  { id: 'm7', name: '沉默 ISV',   tier: '沉默', tierBadge: 'paused',   products: 0,   installs: '—',    revenue: '—',     rating: 0,   status: '7 家',  statusBadge: 'paused' },
]

const MAKER_COLS: Column<MakerRow>[] = [
  { key: 'name',     label: 'ISV',      render: r => <span style={{ fontWeight: 500 }}>{r.name}</span> },
  { key: 'tier',     label: '等级',     render: r => <Badge kind={r.tierBadge}>{r.tier}</Badge>, width: 64 },
  { key: 'products', label: '商品',     render: r => <span className="mono">{r.products}</span>, width: 48, align: 'right' },
  { key: 'installs', label: '累计安装', render: r => <span className="mono">{r.installs}</span>, width: 72, align: 'right' },
  { key: 'revenue',  label: '月收益',   render: r => <span className="mono">{r.revenue}</span>,  width: 72, align: 'right' },
  { key: 'rating',   label: '评分',     render: r => <span className="mono" style={{ color: r.rating >= 4.5 ? 'var(--green-400)' : r.rating > 0 ? 'var(--text-secondary)' : 'var(--text-tertiary)' }}>{r.rating > 0 ? r.rating.toFixed(1) : '—'}</span>, width: 48, align: 'center' },
  { key: 'status',   label: '状态',     render: r => <Badge kind={r.statusBadge}>{r.status}</Badge>, width: 64 },
  { key: 'op',       label: '操作',     render: () => <Button size="sm" variant="ghost">详情</Button>, width: 56, align: 'center' },
]

const TIER_DIST = [
  { tier: '顶级', count: 8,  color: 'var(--ember-500)' },
  { tier: '金牌', count: 14, color: 'var(--amber-200)' },
  { tier: '标准', count: 42, color: 'var(--green-400)' },
  { tier: '新人', count: 20, color: 'var(--blue-400)'  },
  { tier: '沉默', count: 7,  color: 'var(--ink-400)'   },
]

const PENDING_VERIFY = [
  { id: 'v1', name: '张三', company: '长沙某科技', date: '04-24' },
  { id: 'v2', name: '李四', company: '武汉某信息', date: '04-24' },
  { id: 'v3', name: '王五', company: '个人开发者', date: '04-25' },
  { id: 'v4', name: '赵六', company: '深圳某餐饮', date: '04-25' },
]

export default function MakersPage() {
  return (
    <>
      <PageHeader
        crumb="ECOSYSTEM / ISV 作坊主"
        title="作坊主管理"
        subtitle="月活 84 · 顶级 8 / 金牌 14 / 标准 42 / 新人 20 / 沉默 7"
        actions={<>
          <Button size="sm" variant="ghost">邀请码</Button>
          <Button size="sm" variant="secondary">实名审核 4</Button>
          <Button size="sm" variant="primary">导出名册</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 主内容 2fr 1fr */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
        {/* 左栏 - 作坊主名册 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 8 }}>作坊主名册 · {MAKERS.length} 条记录</div>
          <Table columns={MAKER_COLS} data={MAKERS} rowKey={r => r.id} />
        </Card>

        {/* 右栏 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 等级分布 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 10 }}>等级分布</div>
            <div style={{ display: 'grid', gridTemplateColumns: '48px 1fr 32px', gap: 6, fontSize: 11, lineHeight: 2.2, alignItems: 'center' }}>
              {TIER_DIST.map(t => (
                <>
                  <span key={`${t.tier}-l`} style={{ color: t.color, fontWeight: 500 }}>{t.tier}</span>
                  <div key={`${t.tier}-b`} style={{ height: 6, background: 'var(--bg-surface)', borderRadius: 3 }}>
                    <div style={{ width: `${(t.count / 50) * 100}%`, height: '100%', background: t.color, borderRadius: 3 }} />
                  </div>
                  <span key={`${t.tier}-c`} className="mono muted" style={{ textAlign: 'right' }}>{t.count}</span>
                </>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text-tertiary)', lineHeight: 1.6 }}>
              升级路径：新人 → 标准（3 商品 + 100 安装）→ 金牌（评分 ≥ 4.5 + ¥5k 月收益）→ 顶级（邀请制）
            </div>
          </Card>

          {/* 实名待审 */}
          <Card variant="emphasis">
            <div className="lbl ember" style={{ marginBottom: 8 }}>— 实名待审 · 4</div>
            {PENDING_VERIFY.map(v => (
              <div key={v.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 11
              }}>
                <span style={{ fontWeight: 500 }}>{v.name}</span>
                <span className="muted">{v.company}</span>
                <span className="mono muted">{v.date}</span>
                <Button size="sm" variant="ghost">审核</Button>
              </div>
            ))}
            <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end' }}>
              <Button size="sm" variant="secondary">批量审核</Button>
            </div>
          </Card>

          {/* 邀请码 */}
          <Card>
            <div className="lbl-sm muted" style={{ marginBottom: 8 }}>邀请码管理</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 6 }}>
              <span className="muted">已发放</span>
              <span className="mono">47</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 10 }}>
              <span className="muted">已激活</span>
              <span className="mono" style={{ color: 'var(--green-400)' }}>38</span>
            </div>
            <div style={{
              padding: '8px 10px', background: 'var(--bg-surface)', borderRadius: 4,
              fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ember-500)',
              letterSpacing: '0.08em', marginBottom: 8, textAlign: 'center'
            }}>
              TX-2026-04-AXKM
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 8 }}>
              最新邀请码 · 有效期 7 天
            </div>
            <Button size="sm" variant="primary" style={{ width: '100%' }}>生成新邀请码</Button>
          </Card>
        </div>
      </div>

      {/* === Developer Enablement · 对标 Shopify / Stripe Developer Platform === */}

      <div style={{ marginTop: 24, marginBottom: 4 }}>
        <h2 style={{ fontFamily: 'var(--font-serif, Georgia, serif)', fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
          开发者赋能
        </h2>
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>SDK · 认证 · TTHW</span>
      </div>

      {/* KPI 3-col */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
        <KpiCard
          label="TTHW (Time To Hello World)"
          value="47 min"
          delta={{ text: '目标 ≤ 30 min', tone: 'warn' as const }}
          alert
        />
        <KpiCard
          label="SDK 周下载"
          value="1,247"
          delta={{ text: '▲ 24%', tone: 'success' as const }}
        />
        <KpiCard
          label="文档满意度"
          value="4.2 / 5.0"
          delta={{ text: '47 条反馈', tone: 'success' as const }}
        />
      </div>

      {/* ISV 认证体系 + SDK & API 使用分析 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* ISV 认证体系 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 8 }}>ISV 认证体系</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-tertiary)' }}>
                {['认证', '要求', '已认证', '通过率'].map(h => (
                  <th key={h} style={{ textAlign: h === '已认证' || h === '通过率' ? 'right' : 'left', padding: '4px 6px', fontWeight: 500, color: 'var(--text-secondary)', fontSize: 10 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {([
                { cert: '基础认证', req: '实名 + 1 件上架',           count: 64, rate: '87%' },
                { cert: '银牌认证', req: '3 件 + ★4.0 + 安全扫描',    count: 32, rate: '72%' },
                { cert: '金牌认证', req: '5 件 + ★4.5 + API 审计',    count: 14, rate: '58%' },
                { cert: '铂金认证', req: '10 件 + ★4.7 + 屯象认证培训', count: 8,  rate: '44%' },
              ] as const).map(r => (
                <tr key={r.cert} style={{ borderBottom: '0.5px dotted var(--border-tertiary)' }}>
                  <td style={{ padding: '5px 6px', fontWeight: 500 }}>{r.cert}</td>
                  <td style={{ padding: '5px 6px', color: 'var(--text-secondary)' }}>{r.req}</td>
                  <td className="mono" style={{ padding: '5px 6px', textAlign: 'right' }}>{r.count}</td>
                  <td className="mono" style={{ padding: '5px 6px', textAlign: 'right', color: Number(r.rate.replace('%', '')) >= 70 ? 'var(--green-400)' : 'var(--amber-400)' }}>{r.rate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        {/* SDK & API 使用分析 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 8 }}>SDK & API 使用分析</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {([
              { name: 'Master Agent SDK v3.0', downloads: '842/周', badge: 'active' as const, badgeText: '稳定' },
              { name: 'Skill Builder SDK v2.1', downloads: '324/周', badge: 'active' as const, badgeText: '稳定' },
              { name: 'Action Runtime v1.8',    downloads: '187/周', badge: 'active' as const, badgeText: '稳定' },
              { name: 'Adapter Toolkit v1.2',   downloads: '94/周',  badge: 'warn' as const,   badgeText: '需更新文档' },
            ] as const).map(s => (
              <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, padding: '4px 0', borderBottom: '0.5px dotted var(--border-tertiary)' }}>
                <span style={{ fontWeight: 500 }}>{s.name}</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className="mono muted">下载 {s.downloads}</span>
                  <Badge kind={s.badge}>{s.badgeText}</Badge>
                </span>
              </div>
            ))}
          </div>

          {/* Mini chart: API 调用趋势 */}
          <div style={{ marginTop: 12 }}>
            <div className="lbl-sm muted" style={{ marginBottom: 6 }}>API 调用趋势 · 4 周</div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 48 }}>
              {([
                { week: 'W1', value: 62 },
                { week: 'W2', value: 71 },
                { week: 'W3', value: 68 },
                { week: 'W4', value: 84 },
              ] as const).map(w => (
                <div key={w.week} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                  <div style={{
                    width: '100%', height: `${(w.value / 100) * 48}px`,
                    background: w.value >= 80 ? 'var(--green-400)' : 'var(--blue-400)',
                    borderRadius: '2px 2px 0 0',
                  }} />
                  <span style={{ fontSize: 9, color: 'var(--text-tertiary)' }}>{w.week}</span>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 4, textAlign: 'right' }}>
              单位: 万次/周
            </div>
          </div>
        </Card>
      </div>

      {/* 开发者旅程漏斗 */}
      <Card>
        <div className="lbl-sm muted" style={{ marginBottom: 10 }}>开发者旅程漏斗</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {([
            { step: '注册开发者账号',       count: 247, pct: 100,   color: 'var(--green-400)' },
            { step: '完成 SDK 安装',        count: 184, pct: 74.5,  color: 'var(--green-400)' },
            { step: '提交第一个 Alpha',      count: 87,  pct: 35.2,  color: 'var(--blue-400)'  },
            { step: 'Alpha 获得 10+ 试用',  count: 42,  pct: 17.0,  color: 'var(--amber-400)' },
            { step: '毕业到正式商品',        count: 18,  pct: 7.3,   color: 'var(--amber-400)' },
            { step: '月收入 > ¥10k',        count: 8,   pct: 3.2,   color: 'var(--ember-500)' },
          ] as const).map(f => (
            <div key={f.step} style={{ display: 'grid', gridTemplateColumns: '160px 1fr 72px', gap: 8, alignItems: 'center', fontSize: 11 }}>
              <span style={{ fontWeight: 500 }}>{f.step}</span>
              <div style={{ height: 10, background: 'var(--bg-surface)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${f.pct}%`, height: '100%', background: f.color, borderRadius: 4, transition: 'width 0.3s ease' }} />
              </div>
              <span className="mono" style={{ textAlign: 'right', color: f.pct <= 10 ? 'var(--ember-500)' : 'var(--text-secondary)' }}>
                {f.count} ({f.pct}%)
              </span>
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 12, padding: '8px 10px', background: 'var(--bg-surface)', borderRadius: 4,
          fontSize: 11, color: 'var(--amber-400)', lineHeight: 1.6,
        }}>
          瓶颈分析: <span style={{ fontWeight: 500 }}>SDK 安装 → 首次提交</span> 流失最大 (53%)，建议增加脚手架模板
        </div>
      </Card>
    </>
  )
}
