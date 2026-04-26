// 系统配置 · 完整示范页(展示表单配置与自动化规则)
import { PageHeader, Card, Button, Badge } from '@/components/ui'

const COMMISSION_ROWS = [
  { label: '顶级ISV', value: '15' },
  { label: '金牌ISV', value: '25' },
  { label: '标准ISV', value: '30' },
  { label: '新人ISV', value: '35' },
]

const SLA_ROWS = [
  { label: 'P0紧急', value: '2h' },
  { label: 'P1标准', value: '8h' },
  { label: 'P2一般', value: '24h' },
  { label: 'Labs Alpha', value: '72h' },
]

const AUTOMATION_RULES = [
  '提交后SAST扫描',
  '性能基准CI',
  '审核SLA提醒',
  '退订率≥30%通知ISV',
  '评分≤3.0复审',
  '沉默ISV邮件唤醒',
  '新CVE应急通知',
  'Labs阈值毕业候选',
]

const TEMPLATES = [
  '审核通过通知',
  '审核驳回说明',
  'ISV入驻欢迎信',
  '结算单确认',
  '安全漏洞通报',
  'Labs毕业恭喜',
]

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        crumb="GUARDRAIL / 系统配置"
        title="系统配置"
        subtitle="修改任何配置都需 CTO 双签 · 改动入审计日志"
        actions={<>
          <Button size="sm" variant="ghost">配置历史</Button>
        </>}
      />

      {/* top grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
            <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>抽佣比例</span>
            <span className="lbl-sm muted">CTO + 财务双签</span>
          </div>
          {COMMISSION_ROWS.map(r => (
            <div key={r.label} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 12
            }}>
              <span style={{ flex: 1 }}>{r.label}</span>
              <input
                defaultValue={r.value}
                readOnly
                className="mono"
                style={{
                  width: 60, textAlign: 'right', padding: '3px 8px',
                  background: 'var(--bg-surface)', border: '1px solid var(--border-secondary)',
                  borderRadius: 4, color: 'var(--ember-500)', fontSize: 12,
                  fontFamily: 'var(--font-mono)'
                }}
              />
              <span className="mono muted" style={{ fontSize: 11 }}>%</span>
              <Button size="sm" variant="ghost">改</Button>
            </div>
          ))}
        </Card>

        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
            <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>审核SLA</span>
            <span className="lbl-sm muted">影响所有审核员</span>
          </div>
          {SLA_ROWS.map(r => (
            <div key={r.label} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 12
            }}>
              <span style={{ flex: 1 }}>{r.label}</span>
              <input
                defaultValue={r.value}
                readOnly
                className="mono"
                style={{
                  width: 60, textAlign: 'right', padding: '3px 8px',
                  background: 'var(--bg-surface)', border: '1px solid var(--border-secondary)',
                  borderRadius: 4, color: 'var(--ember-500)', fontSize: 12,
                  fontFamily: 'var(--font-mono)'
                }}
              />
              <Button size="sm" variant="ghost">改</Button>
            </div>
          ))}
        </Card>
      </div>

      {/* bottom grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
            <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>自动化规则</span>
            <span className="lbl-sm muted">8启用</span>
          </div>
          {AUTOMATION_RULES.map(rule => (
            <div key={rule} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 12
            }}>
              <span>{rule}</span>
              <Badge kind="active">启用</Badge>
            </div>
          ))}
        </Card>

        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
            <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>通知模板</span>
            <span className="lbl-sm muted">12模板</span>
          </div>
          {TEMPLATES.map(tpl => (
            <div key={tpl} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              borderBottom: '0.5px dotted var(--border-tertiary)', padding: '5px 0', fontSize: 12
            }}>
              <span>{tpl}</span>
              <a className="ember-soft" style={{ fontSize: 11, cursor: 'pointer' }}>编辑</a>
            </div>
          ))}
          <div className="dim" style={{ fontSize: 11, marginTop: 8, textAlign: 'center' }}>+ 6 个</div>
        </Card>
      </div>
    </>
  )
}
