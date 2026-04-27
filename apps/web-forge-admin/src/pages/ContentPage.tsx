// 内容运营 · Hero/Editor's Pick 排期 + 案例/博客管理
import { PageHeader, Card, Button, Badge, Table } from '@/components/ui'
import type { Column } from '@/components/ui/Table'

interface HeroRow {
  id: string
  week: string
  hero: string
  editor1: string
  editor2: string
  editor3: string
  curator: string
  isCurrent?: boolean
  isEmpty?: boolean
}

const HERO_SCHEDULE: HeroRow[] = [
  { id: '1', week: '本周',  hero: 'Master Agent SDK v3.0', editor1: '天财',     editor2: '海鲜溯源', editor3: '夜间增亮', curator: '张工',   isCurrent: true },
  { id: '2', week: 'W18',   hero: 'L0-TCSL',              editor1: '智能配菜', editor2: '桌台合并', editor3: '客流热力', curator: '李设计' },
  { id: '3', week: 'W19',   hero: '春节流量',              editor1: '美团v4.1', editor2: '诺诺发票', editor3: '会员洞察', curator: '王运营' },
  { id: '4', week: 'W20',   hero: '财务稽核Agent',         editor1: 'L0-PZ',    editor2: '巡店质检', editor3: '溯源链',   curator: '张工' },
  { id: '5', week: 'W21',   hero: '未排',                  editor1: '--',       editor2: '--',       editor3: '--',       curator: '待选',  isEmpty: true },
]

const HERO_COLUMNS: Column<HeroRow>[] = [
  { key: 'week',    label: '周次',    render: r => <span className={r.isCurrent ? 'mono ember' : 'mono muted'}>{r.week}</span> },
  { key: 'hero',    label: 'Hero',    render: r => <span style={{ fontWeight: r.isCurrent ? 500 : 400 }}>{r.hero}</span> },
  { key: 'editor1', label: 'Editor1', render: r => <span className={r.isEmpty ? 'dim' : ''}>{r.editor1}</span> },
  { key: 'editor2', label: 'Editor2', render: r => <span className={r.isEmpty ? 'dim' : ''}>{r.editor2}</span> },
  { key: 'editor3', label: 'Editor3', render: r => <span className={r.isEmpty ? 'dim' : ''}>{r.editor3}</span> },
  { key: 'curator', label: '策展人',  render: r => <span className={r.isEmpty ? 'dim' : 'ember-soft'}>{r.curator}</span> },
]

const CASE_DRAFTS = [
  '徐记海鲜 · 23套替换',
  '尚宫厨 · 上线30天GMV+18%',
  '最黔线 · 客如云迁移',
]

const BLOG_PENDING = [
  'Agent SDK v3.0 迁移指南',
  'RLS 策略最佳实践',
  '屯象OS等保三级实录',
  '从L0到L2：主题引擎演进',
]

export default function ContentPage() {
  return (
    <>
      <PageHeader
        crumb="BUSINESS / 内容运营"
        title="内容运营"
        subtitle="本周策展人 张工 · Hero 已排至 06-30"
        actions={<>
          <Button size="sm" variant="ghost">策展轮值</Button>
          <Button size="sm" variant="primary">新建Hero</Button>
        </>}
      />

      {/* Main row: 2fr table + 1fr side cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 8 }}>
        {/* Left: Hero calendar table */}
        <Card padding={0} style={{ overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px 6px', fontFamily: 'var(--font-serif)', fontSize: 14, color: '#fff' }}>
            Hero / Editor's Pick 日历
          </div>
          <Table columns={HERO_COLUMNS} data={HERO_SCHEDULE} rowKey={r => r.id} />
        </Card>

        {/* Right: side cards */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* 案例故事 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 8 }}>案例故事 · 草稿 3</div>
            {CASE_DRAFTS.map((c, i) => (
              <div key={c} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '4px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12
              }}>
                <span>{c}</span>
                <Badge kind="warn">草稿</Badge>
              </div>
            ))}
            <div style={{ marginTop: 8, textAlign: 'right' }}>
              <Button size="sm" variant="ghost">查看全部</Button>
            </div>
          </Card>

          {/* 开发者博客 */}
          <Card>
            <div className="lbl ember" style={{ marginBottom: 8 }}>开发者博客 · 待发 4</div>
            {BLOG_PENDING.map((b, i) => (
              <div key={b} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '4px 0',
                borderBottom: '0.5px dotted var(--border-tertiary)',
                fontSize: 12
              }}>
                <span>{b}</span>
                <Badge kind="soft">待发</Badge>
              </div>
            ))}
            <div style={{ marginTop: 8, textAlign: 'right' }}>
              <Button size="sm" variant="ghost">查看全部</Button>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
