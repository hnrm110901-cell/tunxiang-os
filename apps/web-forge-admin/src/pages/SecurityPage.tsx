// 安全合规 · 告警/CVE/应急下架/数据流向
import { PageHeader, KpiCard, Card, Button, Badge } from '@/components/ui'
import { Table, type Column } from '@/components/ui/Table'

const KPI = [
  { label: '待处理告警', value: '3',     delta: { text: '2P1 · 1P2',     tone: 'soft' as const }, alert: true },
  { label: 'CVE监控',   value: '142',   delta: { text: '0 high',        tone: 'success' as const } },
  { label: '本月扫描',   value: '1,247', delta: { text: '自动流水线',     tone: 'soft' as const } },
  { label: '应急下架累', value: '2',     delta: { text: '年度统计',       tone: 'soft' as const } },
]

interface AlertItem {
  id: string
  level: 'P1' | 'P2'
  type: string
  product: string
  desc: string
  found: string
  status: string
  statusBadge: 'warn' | 'active' | 'paused'
}

const ALERTS: AlertItem[] = [
  { id: 'a1', level: 'P1', type: '权限提升',  product: '抖音来客 v2.5', desc: '权限模型变更未声明',        found: '3d 前', status: '分析中',    statusBadge: 'warn'   },
  { id: 'a2', level: 'P1', type: '依赖CVE',   product: '客如云 v2.9',   desc: 'jackson-databind CVE',   found: '5d 前', status: '通知ISV',   statusBadge: 'active' },
  { id: 'a3', level: 'P2', type: 'SAST警告',  product: '桌台合并 v0.9', desc: '1处低风险SQL拼接',         found: '7d 前', status: '回修中',    statusBadge: 'paused' },
]

const ALERT_COLS: Column<AlertItem>[] = [
  { key: 'level',   label: '等级',   render: r => <Badge kind={r.level === 'P1' ? 'fail' : 'warn'}>{r.level}</Badge>, width: 56 },
  { key: 'type',    label: '类型',   render: r => <span>{r.type}</span> },
  { key: 'product', label: '商品',   render: r => <span style={{ fontWeight: 500 }}>{r.product}</span> },
  { key: 'desc',    label: '描述',   render: r => <span className="muted">{r.desc}</span> },
  { key: 'found',   label: '发现时间', render: r => <span className="mono muted">{r.found}</span>, width: 72 },
  { key: 'status',  label: '状态',   render: r => <Badge kind={r.statusBadge}>{r.status}</Badge> },
  { key: 'op',      label: '操作',   render: () => <Button size="sm" variant="ghost">处理</Button>, width: 64, align: 'center' },
]

const TAKEDOWN_HISTORY = [
  { date: '2026-02-14', product: '扫码点餐 v3.0', reason: '高危 CVE 未修复 48h，自动触发应急下架', resolver: '系统自动' },
  { date: '2026-01-22', product: '会员积分 v1.7', reason: 'ISV 主动申请下架，发现数据越权读取', resolver: '人工确认' },
]

/* --- Trust Center: 隐私影响评估 --- */
interface PiaItem {
  feature: string
  dataType: string
  risk: '低' | '中' | '高'
  status: string
  statusBadge: 'pass' | 'warn'
  lastDate: string
}

const PIA_DATA: PiaItem[] = [
  { feature: '菜品推荐', dataType: '消费偏好',          risk: '低', status: '已通过',        statusBadge: 'pass', lastDate: '2026-04-10' },
  { feature: '会员洞察', dataType: '用户画像+消费记录',  risk: '中', status: '已通过',        statusBadge: 'pass', lastDate: '2026-04-08' },
  { feature: '巡店质检', dataType: '视频+图像',          risk: '高', status: '已通过(附条件)', statusBadge: 'pass', lastDate: '2026-04-05' },
  { feature: '客流预测', dataType: '位置+人数',          risk: '中', status: '已通过',        statusBadge: 'pass', lastDate: '2026-03-28' },
  { feature: '外卖调度', dataType: '地址+电话',          risk: '高', status: '待复审',        statusBadge: 'warn', lastDate: '-' },
]

const PIA_COLS: Column<PiaItem>[] = [
  { key: 'feature',  label: 'AI 功能',  render: r => <span style={{ fontWeight: 500 }}>{r.feature}</span> },
  { key: 'dataType', label: '数据类型', render: r => <span className="muted">{r.dataType}</span> },
  { key: 'risk',     label: '风险等级', render: r => <Badge kind={r.risk === '高' ? 'fail' : r.risk === '中' ? 'warn' : 'pass'}>{r.risk}</Badge>, width: 72 },
  { key: 'status',   label: '评估状态', render: r => <Badge kind={r.statusBadge}>{r.status}</Badge> },
  { key: 'lastDate', label: '最近评估', render: r => <span className="mono muted">{r.lastDate}</span>, width: 96 },
]

export default function SecurityPage() {
  return (
    <>
      <PageHeader
        crumb="GUARDRAIL / 安全合规"
        title="安全合规"
        subtitle="3 待处理 · 7 年审计日志留存 · CVE 监控"
        actions={<>
          <Button size="sm" variant="ghost" style={{ background: 'transparent', color: 'var(--crimson-400)', border: '0.5px solid var(--crimson-600)' }}>应急下架</Button>
          <Button size="sm" variant="secondary">数据流向审计</Button>
        </>}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {KPI.map(k => <KpiCard key={k.label} {...k} />)}
      </div>

      {/* 告警与漏洞 */}
      <Card style={{ marginBottom: 12 }}>
        <div className="lbl-sm muted" style={{ marginBottom: 8 }}>告警与漏洞</div>
        <Table columns={ALERT_COLS} data={ALERTS} rowKey={r => r.id} />
      </Card>

      {/* 底部 2 栏 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {/* 应急下架历史 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 8 }}>应急下架历史</div>
          {TAKEDOWN_HISTORY.map((t, i) => (
            <div key={t.date} style={{
              padding: '8px 0',
              borderBottom: i < TAKEDOWN_HISTORY.length - 1 ? '0.5px dotted var(--border-tertiary)' : 'none',
              fontSize: 11
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span className="mono ember-soft">{t.date}</span>
                <span className="mono muted">{t.resolver}</span>
              </div>
              <div style={{ fontWeight: 500, marginBottom: 2 }}>{t.product}</div>
              <div className="muted">{t.reason}</div>
            </div>
          ))}
        </Card>

        {/* 数据流向审计 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 10 }}>数据流向审计</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 11, marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">本月外呼</span>
              <span className="mono">1.2M</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">越权尝试</span>
              <span className="mono ember">42</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">数据出境</span>
              <span className="mono">0</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0' }}>
              <span className="muted">异常IP</span>
              <span className="mono ember-soft">3</span>
            </div>
          </div>
          <Button size="sm" variant="secondary" style={{ width: '100%' }}>下载审计报告</Button>
        </Card>
      </div>

      {/* === Trust Center · 对标 ServiceNow / Salesforce Trust === */}

      <div style={{ marginTop: 32, marginBottom: 8 }}>
        <h2 style={{ fontFamily: 'serif', fontSize: 20, fontWeight: 600, letterSpacing: '-0.02em', marginBottom: 2 }}>Trust Center</h2>
        <span className="muted" style={{ fontSize: 11 }}>合规 · 数据主权 · 隐私</span>
      </div>

      {/* 合规状态 4-grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        {([
          { title: '等保三级',     badge: 'pass' as const, badgeText: '已通过', meta: '到期 2027-03-15' },
          { title: 'ISO 27001',   badge: 'pass' as const, badgeText: '认证中', meta: '预计 2026-Q3' },
          { title: 'SOC 2 Type II', badge: 'warn' as const, badgeText: '准备中', meta: '审计启动 2026-06' },
          { title: 'GDPR / PIPL', badge: 'pass' as const, badgeText: '合规',   meta: '最近评估 2026-04-01' },
        ]).map(c => (
          <Card key={c.title} style={{ padding: '12px 14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontWeight: 600, fontSize: 12 }}>{c.title}</span>
              <Badge kind={c.badge}>{c.badgeText}</Badge>
            </div>
            <span className="mono muted" style={{ fontSize: 10 }}>{c.meta}</span>
          </Card>
        ))}
      </div>

      {/* AI 安全态势 + 数据主权 2-grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {/* AI 安全态势 */}
        <Card style={{ borderLeft: '2px solid var(--accent-emphasis, #6e56cf)' }}>
          <div className="lbl-sm" style={{ marginBottom: 10, fontWeight: 600 }}>AI 安全态势</div>
          {([
            { label: 'Prompt 注入防护',  stat: '本月拦截 847 次 · 成功率 99.97%' },
            { label: '模型输出过滤',     stat: '敏感信息检测 24k 次 · 拦截 142 次' },
            { label: '数据脱敏',         stat: 'PII 检测覆盖率 100% · 自动脱敏' },
            { label: '对抗样本检测',     stat: '异常输入 3 次 · 已拦截' },
            { label: '模型越狱防护',     stat: '尝试 12 次 · 全部拦截' },
          ]).map((item, i) => (
            <div key={item.label} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '6px 0', fontSize: 11,
              borderBottom: i < 4 ? '0.5px dotted var(--border-tertiary)' : 'none',
            }}>
              <span style={{ fontWeight: 500 }}>{item.label}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="mono muted">{item.stat}</span>
                <Badge kind="pass">OK</Badge>
              </span>
            </div>
          ))}
        </Card>

        {/* 数据主权与驻留 */}
        <Card>
          <div className="lbl-sm muted" style={{ marginBottom: 10 }}>数据主权与驻留</div>
          {([
            { label: '数据中心', value: '阿里云 华南（广州）· 同城双活' },
            { label: '数据出境', value: '0 次 · 严格境内' },
            { label: '加密',     value: 'AES-256 静态 + TLS 1.3 传输' },
            { label: '备份',     value: '每日增量 · 每周全量 · 异地灾备' },
            { label: '密钥管理', value: '阿里云 KMS · 每 90 天轮换' },
          ]).map((item, i) => (
            <div key={item.label} style={{
              display: 'flex', justifyContent: 'space-between',
              padding: '6px 0', fontSize: 11,
              borderBottom: i < 4 ? '0.5px dotted var(--border-tertiary)' : 'none',
            }}>
              <span className="muted">{item.label}</span>
              <span className="mono">{item.value}</span>
            </div>
          ))}
        </Card>
      </div>

      {/* 隐私影响评估 · AI 专项 */}
      <Card style={{ marginBottom: 12 }}>
        <div className="lbl-sm muted" style={{ marginBottom: 8 }}>隐私影响评估 · AI 专项</div>
        <Table
          columns={PIA_COLS}
          data={PIA_DATA}
          rowKey={r => r.feature}
        />
      </Card>
    </>
  )
}
