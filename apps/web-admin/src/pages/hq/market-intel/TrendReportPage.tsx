/**
 * TrendReportPage — 趋势报告中心
 * 路由: /hq/market-intel/reports
 * 报告列表 + 报告预览 + 自动生成调度 + 导出选项
 */
import { useState } from 'react';

const BG_0 = '#0f1923';
const BG_1 = '#1a2836';
const BG_2 = '#243442';
const BRAND = '#ff6b2c';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const CYAN = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'list' | 'preview' | 'schedule' | 'export';
type ReportType = '全部' | '竞对周报' | '需求周报' | '新品周报' | '原料周报' | '商圈周报' | '月报';

interface Report {
  id: string;
  title: string;
  type: ReportType;
  date: string;
  status: '已发布' | '生成中' | '待审核' | '草稿';
  summary: string;
  keyFindings: string[];
  readCount: number;
  pageCount: number;
}

interface ScheduleItem {
  id: string;
  reportType: string;
  frequency: '每周一' | '每周五' | '每月1日' | '每月15日' | '每季度';
  lastGenerated: string;
  nextGenerate: string;
  recipients: string[];
  status: '启用' | '暂停';
  autoPublish: boolean;
}

const MOCK_REPORTS: Report[] = [
  {
    id: 'rpt1', title: '2026年第12周竞对动态周报', type: '竞对周报', date: '2026-03-24', status: '已发布',
    summary: '本周竞对动态活跃，海底捞推出酸汤系列直接切入我方优势品类，太二第500店开业加速扩张。建议重点关注酸汤品类防御和一人食套餐差异化。',
    keyFindings: ['海底捞酸汤系列上线，定价89-129元，直接竞争我方酸汤品类', '太二第500家店开业，加速二三线下沉', '费大厨外卖套餐39.9元，低价抢占午市外卖', '望湘园品牌升级，"新湘菜"定位差异化'],
    readCount: 45, pageCount: 12,
  },
  {
    id: 'rpt2', title: '2026年第12周消费需求周报', type: '需求周报', date: '2026-03-24', status: '已发布',
    summary: '酸汤品类搜索热度持续攀升，一人食需求增长稳定，健康轻食成为新趋势关键词。性价比仍是消费者最关注因素。',
    keyFindings: ['酸汤搜索量周增40%，成为最热品类关键词', '一人食需求稳步增长35%，午间场景为主', '健康饮食相关搜索增28%', '性价比关注度持续高位'],
    readCount: 38, pageCount: 8,
  },
  {
    id: 'rpt3', title: '2026年第12周新品机会周报', type: '新品周报', date: '2026-03-24', status: '已发布',
    summary: '本周发现3个高分新品机会：酸汤火锅系列(87分)、一人食精品套餐(82分)、节气限定菜品(75分)。酸汤系列紧迫度最高，建议优先启动。',
    keyFindings: ['酸汤火锅系列适配度87分，紧迫度最高', '一人食精品套餐适配度82分，午市场景潜力大', '节气限定菜品社交传播潜力高', '云南酸笋作为新原料机会值得关注'],
    readCount: 32, pageCount: 6,
  },
  {
    id: 'rpt4', title: '2026年第12周原料趋势周报', type: '原料周报', date: '2026-03-24', status: '已发布',
    summary: '云南酸笋搜索热度+60%，可用于酸汤配菜。低脂椰奶作为健康饮品原料有开发价值。辣椒价格近期稳定。',
    keyFindings: ['云南酸笋搜索热度+60%，供应稳定', '低脂椰奶需求上升，可开发甜品线', '辣椒价格稳定在8.5元/斤', '进口牛肉价格微涨3%'],
    readCount: 18, pageCount: 5,
  },
  {
    id: 'rpt5', title: '2026年第12周商圈情报周报', type: '商圈周报', date: '2026-03-24', status: '已发布',
    summary: '五一广场商圈客流量恢复至疫前120%水平，新开3家餐饮门店。梅溪湖商圈周末客流增长显著。',
    keyFindings: ['五一广场客流恢复至120%，竞争加剧', '梅溪湖周末客流增15%，家庭客群为主', '河西大学城工作日午市客流稳定', '星沙商圈新增2家湘菜竞品'],
    readCount: 22, pageCount: 7,
  },
  {
    id: 'rpt6', title: '2026年3月市场情报月报', type: '月报', date: '2026-03-26', status: '生成中',
    summary: '(生成中...)',
    keyFindings: [],
    readCount: 0, pageCount: 0,
  },
  {
    id: 'rpt7', title: '2026年第11周竞对动态周报', type: '竞对周报', date: '2026-03-17', status: '已发布',
    summary: '费大厨抖音直播卖券单场破200万，太二联名故宫IP打造主题店。建议加强线上营销投入。',
    keyFindings: ['费大厨抖音直播单场200万', '太二故宫联名主题店', '海底捞会员日8折活动', '西贝预制菜筹备上线'],
    readCount: 56, pageCount: 10,
  },
];

const MOCK_SCHEDULES: ScheduleItem[] = [
  { id: 'sch1', reportType: '竞对周报', frequency: '每周一', lastGenerated: '2026-03-24', nextGenerate: '2026-03-31', recipients: ['CEO', '营销总监', '品牌经理'], status: '启用', autoPublish: true },
  { id: 'sch2', reportType: '需求周报', frequency: '每周一', lastGenerated: '2026-03-24', nextGenerate: '2026-03-31', recipients: ['CEO', '产品总监', '研发经理'], status: '启用', autoPublish: true },
  { id: 'sch3', reportType: '新品周报', frequency: '每周一', lastGenerated: '2026-03-24', nextGenerate: '2026-03-31', recipients: ['产品总监', '研发经理', '厨师长'], status: '启用', autoPublish: false },
  { id: 'sch4', reportType: '原料周报', frequency: '每周五', lastGenerated: '2026-03-21', nextGenerate: '2026-03-28', recipients: ['采购总监', '供应链经理'], status: '启用', autoPublish: true },
  { id: 'sch5', reportType: '商圈周报', frequency: '每周一', lastGenerated: '2026-03-24', nextGenerate: '2026-03-31', recipients: ['拓展总监', '运营总监'], status: '启用', autoPublish: true },
  { id: 'sch6', reportType: '月报', frequency: '每月1日', lastGenerated: '2026-03-01', nextGenerate: '2026-04-01', recipients: ['CEO', '全体高管'], status: '启用', autoPublish: false },
];

function ReportList({ reports, typeFilter }: { reports: Report[]; typeFilter: ReportType }) {
  const filtered = typeFilter === '全部' ? reports : reports.filter(r => r.type === typeFilter);
  const statusColors: Record<string, string> = { '已发布': GREEN, '生成中': BLUE, '待审核': YELLOW, '草稿': TEXT_4 };
  const typeColors: Record<string, string> = { '竞对周报': RED, '需求周报': BLUE, '新品周报': GREEN, '原料周报': BRAND, '商圈周报': PURPLE, '月报': CYAN };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {filtered.map(r => (
        <div key={r.id} style={{
          background: BG_1, borderRadius: 10, padding: 16,
          border: `1px solid ${BG_2}`, cursor: 'pointer',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: (typeColors[r.type] || TEXT_4) + '22', color: typeColors[r.type] || TEXT_4, fontWeight: 600,
              }}>{r.type}</span>
              <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{r.title}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: statusColors[r.status] + '22', color: statusColors[r.status], fontWeight: 600,
              }}>{r.status}</span>
            </div>
          </div>
          <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 10 }}>{r.summary}</div>
          {r.keyFindings.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              {r.keyFindings.map((f, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'flex-start', gap: 6,
                  fontSize: 11, color: TEXT_2, lineHeight: 1.6, marginBottom: 2,
                }}>
                  <span style={{ color: BRAND, flexShrink: 0 }}>{'\u2022'}</span>
                  <span>{f}</span>
                </div>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_4 }}>
            <span>{r.date}</span>
            <div style={{ display: 'flex', gap: 12 }}>
              <span>阅读 {r.readCount}</span>
              <span>{r.pageCount} 页</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReportPreview({ report }: { report: Report }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 24,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 24, paddingBottom: 16, borderBottom: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 10, color: BRAND, fontWeight: 600, marginBottom: 8 }}>屯象OS 市场情报中心</div>
          <h2 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 700, color: TEXT_1 }}>{report.title}</h2>
          <div style={{ fontSize: 12, color: TEXT_4 }}>{report.date} | {report.pageCount} 页 | 阅读 {report.readCount}</div>
        </div>

        {/* Executive Summary */}
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: BRAND, marginBottom: 10 }}>摘要</h3>
          <div style={{
            fontSize: 13, color: TEXT_2, lineHeight: 1.8,
            padding: '12px 16px', background: BG_2, borderRadius: 8,
            borderLeft: `3px solid ${BRAND}`,
          }}>{report.summary}</div>
        </div>

        {/* Key Findings */}
        {report.keyFindings.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: BRAND, marginBottom: 10 }}>核心发现</h3>
            {report.keyFindings.map((f, i) => (
              <div key={i} style={{
                display: 'flex', gap: 10, marginBottom: 8,
                padding: '10px 14px', background: BG_2, borderRadius: 6,
              }}>
                <span style={{
                  width: 22, height: 22, borderRadius: 11, background: BRAND + '22', color: BRAND,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, fontWeight: 700, flexShrink: 0,
                }}>{i + 1}</span>
                <span style={{ fontSize: 13, color: TEXT_1, lineHeight: 1.6 }}>{f}</span>
              </div>
            ))}
          </div>
        )}

        {/* Mock chart area */}
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: BRAND, marginBottom: 10 }}>数据图表</h3>
          <div style={{
            height: 160, background: BG_2, borderRadius: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: TEXT_4, fontSize: 13,
          }}>
            [图表区域 - 趋势图/对比图/雷达图]
          </div>
        </div>

        {/* Action items */}
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: BRAND, marginBottom: 10 }}>建议行动</h3>
          {[
            { priority: 'P0', action: '紧急启动酸汤系列菜品开发', owner: '产品总监' },
            { priority: 'P0', action: '优化一人食套餐定价策略', owner: '营销总监' },
            { priority: 'P1', action: '加强线上营销渠道投入', owner: '品牌经理' },
            { priority: 'P2', action: '关注望湘园品牌升级方向', owner: '战略部' },
          ].map((a, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6,
              padding: '8px 12px', background: BG_2, borderRadius: 6,
            }}>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: (a.priority === 'P0' ? RED : a.priority === 'P1' ? YELLOW : TEXT_4) + '22',
                color: a.priority === 'P0' ? RED : a.priority === 'P1' ? YELLOW : TEXT_4,
                fontWeight: 700,
              }}>{a.priority}</span>
              <span style={{ fontSize: 12, color: TEXT_1, flex: 1 }}>{a.action}</span>
              <span style={{ fontSize: 11, color: TEXT_3 }}>{a.owner}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ScheduleConfig({ schedules }: { schedules: ScheduleItem[] }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>自动生成调度配置</h3>
        <button style={{
          padding: '6px 14px', borderRadius: 6, border: 'none',
          background: BRAND, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
        }}>新增调度</button>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
            {['报告类型', '生成频率', '上次生成', '下次生成', '接收人', '自动发布', '状态', '操作'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {schedules.map(s => (
            <tr key={s.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
              <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{s.reportType}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>{s.frequency}</td>
              <td style={{ padding: '10px', color: TEXT_3 }}>{s.lastGenerated}</td>
              <td style={{ padding: '10px', color: BRAND }}>{s.nextGenerate}</td>
              <td style={{ padding: '10px' }}>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {s.recipients.map(r => (
                    <span key={r} style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: BG_2, color: TEXT_3,
                    }}>{r}</span>
                  ))}
                </div>
              </td>
              <td style={{ padding: '10px' }}>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: s.autoPublish ? GREEN + '22' : TEXT_4 + '22',
                  color: s.autoPublish ? GREEN : TEXT_4, fontWeight: 600,
                }}>{s.autoPublish ? '是' : '否'}</span>
              </td>
              <td style={{ padding: '10px' }}>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: (s.status === '启用' ? GREEN : TEXT_4) + '22',
                  color: s.status === '启用' ? GREEN : TEXT_4, fontWeight: 600,
                }}>{s.status}</span>
              </td>
              <td style={{ padding: '10px' }}>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button style={{
                    padding: '3px 10px', borderRadius: 4, border: 'none',
                    background: BG_2, color: TEXT_3, fontSize: 11, cursor: 'pointer',
                  }}>编辑</button>
                  <button style={{
                    padding: '3px 10px', borderRadius: 4, border: 'none',
                    background: BLUE + '22', color: BLUE, fontSize: 11, cursor: 'pointer',
                  }}>立即生成</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExportPanel() {
  const formats = [
    { name: 'PDF', desc: '高质量排版，适合管理层阅读', icon: 'PDF' },
    { name: 'Word', desc: '可编辑文档，适合二次加工', icon: 'DOC' },
    { name: 'Excel', desc: '数据表格，适合深度分析', icon: 'XLS' },
    { name: 'PPT', desc: '演示文档，适合会议汇报', icon: 'PPT' },
    { name: '邮件推送', desc: '自动发送到指定邮箱', icon: 'MAIL' },
    { name: '企微推送', desc: '推送到企业微信群', icon: 'WECOM' },
  ];

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>导出选项</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
        {formats.map(f => (
          <div key={f.name} style={{
            padding: '16px 18px', background: BG_2, borderRadius: 8,
            cursor: 'pointer', border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <span style={{
                width: 36, height: 36, borderRadius: 8, background: BRAND + '22',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 800, color: BRAND,
              }}>{f.icon}</span>
              <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{f.name}</span>
            </div>
            <div style={{ fontSize: 11, color: TEXT_3 }}>{f.desc}</div>
          </div>
        ))}
      </div>

      {/* Batch export */}
      <div style={{
        padding: '14px 16px', background: BG_2, borderRadius: 8,
        border: `1px dashed ${BRAND}44`,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1, marginBottom: 8 }}>批量导出</div>
        <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 12 }}>
          选择多份报告一键导出为压缩包，或合并为一份综合报告
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button style={{
            padding: '8px 16px', borderRadius: 6, border: 'none',
            background: BRAND, color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer',
          }}>批量导出 PDF</button>
          <button style={{
            padding: '8px 16px', borderRadius: 6, border: `1px solid ${BG_1}`,
            background: 'transparent', color: TEXT_3, fontSize: 12, fontWeight: 600, cursor: 'pointer',
          }}>合并为综合报告</button>
        </div>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function TrendReportPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('list');
  const [typeFilter, setTypeFilter] = useState<ReportType>('全部');
  const [previewId, setPreviewId] = useState('rpt1');

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'list', label: '报告列表' },
    { key: 'preview', label: '报告预览' },
    { key: 'schedule', label: '生成调度' },
    { key: 'export', label: '导出' },
  ];

  const typeOptions: ReportType[] = ['全部', '竞对周报', '需求周报', '新品周报', '原料周报', '商圈周报', '月报'];
  const previewReport = MOCK_REPORTS.find(r => r.id === previewId) || MOCK_REPORTS[0];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>趋势报告中心</h2>

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: '总报告数', value: '47', color: TEXT_1 },
          { label: '本月生成', value: '12', color: BRAND },
          { label: '总阅读量', value: '1,256', color: BLUE },
          { label: '调度任务', value: '6', color: GREEN },
          { label: '待审核', value: '1', color: YELLOW },
        ].map((kpi, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: '14px 16px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {tabs.map(t => (
            <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
              padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: activeTab === t.key ? BRAND : BG_1,
              color: activeTab === t.key ? '#fff' : TEXT_3,
              fontSize: 13, fontWeight: 600,
            }}>{t.label}</button>
          ))}
        </div>
        {activeTab === 'list' && (
          <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
            {typeOptions.map(t => (
              <button key={t} onClick={() => setTypeFilter(t)} style={{
                padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: typeFilter === t ? BLUE : BG_2, color: typeFilter === t ? '#fff' : TEXT_3,
                fontSize: 11, fontWeight: 600,
              }}>{t}</button>
            ))}
          </div>
        )}
        {activeTab === 'preview' && (
          <select value={previewId} onChange={e => setPreviewId(e.target.value)} style={{
            background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
            color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer', marginLeft: 12,
          }}>
            {MOCK_REPORTS.filter(r => r.status === '已发布').map(r => (
              <option key={r.id} value={r.id}>{r.title}</option>
            ))}
          </select>
        )}
      </div>

      {activeTab === 'list' && <ReportList reports={MOCK_REPORTS} typeFilter={typeFilter} />}
      {activeTab === 'preview' && <ReportPreview report={previewReport} />}
      {activeTab === 'schedule' && <ScheduleConfig schedules={MOCK_SCHEDULES} />}
      {activeTab === 'export' && <ExportPanel />}
    </div>
  );
}
