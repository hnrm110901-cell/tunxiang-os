/**
 * ContentCenterPage — 内容资产中心
 * 路由: /hq/growth/content
 * 文案/海报/短信/企微/小程序/节日模板 + 内容生成工作台 + 审核队列 + 效果统计
 */
import { useState } from 'react';

// ---- 颜色常量 ----
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型 ----
type ContentType = '全部' | '文案' | '海报' | '短信' | '企微' | '小程序' | '节日';
type TabKey = 'templates' | 'workbench' | 'review' | 'stats';

interface Template {
  id: string;
  name: string;
  type: ContentType;
  scene: string;
  previewText: string;
  usageCount: number;
  conversionRate: number;
  status: '已发布' | '草稿' | '待审核';
  updatedAt: string;
}

interface ReviewItem {
  id: string;
  title: string;
  type: ContentType;
  submitter: string;
  submitTime: string;
  status: '待审核' | '已通过' | '已拒绝';
  content: string;
}

interface ContentStat {
  id: string;
  title: string;
  type: ContentType;
  sendCount: number;
  openRate: number;
  clickRate: number;
  conversionRate: number;
  revenue: number;
  date: string;
}

// ---- Mock 数据 ----
const MOCK_TEMPLATES: Template[] = [
  { id: 't1', name: '新客欢迎短信', type: '短信', scene: '新客首单', previewText: '【尝在一起】欢迎加入！首单满100减20，点击领取→', usageCount: 3420, conversionRate: 18.5, status: '已发布', updatedAt: '2026-03-25' },
  { id: 't2', name: '复购召回企微', type: '企微', scene: '30天未复购', previewText: '好久不见！专属回归礼包已为您准备好，满80减15~', usageCount: 1856, conversionRate: 12.3, status: '已发布', updatedAt: '2026-03-24' },
  { id: 't3', name: '春季新品海报', type: '海报', scene: '新品推广', previewText: '[春季限定] 酸汤系列上新！酸汤肥牛/酸汤鱼/酸汤虾滑', usageCount: 2130, conversionRate: 8.7, status: '已发布', updatedAt: '2026-03-23' },
  { id: 't4', name: '会员日小程序弹窗', type: '小程序', scene: '会员日', previewText: '会员专属双倍积分日！今天消费积分翻倍~', usageCount: 5620, conversionRate: 22.1, status: '已发布', updatedAt: '2026-03-22' },
  { id: 't5', name: '清明节文案', type: '节日', scene: '清明节', previewText: '清明时节，一碗温暖的汤让思念有了归处', usageCount: 0, conversionRate: 0, status: '草稿', updatedAt: '2026-03-26' },
  { id: 't6', name: '裂变分享海报', type: '海报', scene: '老带新', previewText: '邀请好友得¥20券！分享即得，好友下单再得¥10', usageCount: 1245, conversionRate: 15.6, status: '已发布', updatedAt: '2026-03-21' },
  { id: 't7', name: '低峰引流短信', type: '短信', scene: '低峰时段', previewText: '【尝在一起】下午茶时段(14:00-17:00)到店享8折！限今日', usageCount: 890, conversionRate: 6.2, status: '已发布', updatedAt: '2026-03-20' },
  { id: 't8', name: '储值推广文案', type: '文案', scene: '储值营销', previewText: '充500送80！会员储值享更多优惠，余额永不过期', usageCount: 1670, conversionRate: 9.8, status: '已发布', updatedAt: '2026-03-19' },
  { id: 't9', name: '新品试吃邀请', type: '企微', scene: '新品试吃', previewText: '您被选为新品体验官！免费试吃酸汤系列，期待您的反馈~', usageCount: 340, conversionRate: 42.3, status: '待审核', updatedAt: '2026-03-26' },
  { id: 't10', name: '端午节套餐推广', type: '节日', scene: '端午节', previewText: '端午粽情，全家团圆套餐6折起！', usageCount: 0, conversionRate: 0, status: '草稿', updatedAt: '2026-03-26' },
];

const MOCK_REVIEWS: ReviewItem[] = [
  { id: 'r1', title: '新品试吃邀请 - 企微推送', type: '企微', submitter: '李晓雯', submitTime: '2026-03-26 10:30', status: '待审核', content: '您被选为新品体验官！酸汤系列3款新菜品免费试吃，名额有限，点击预约→' },
  { id: 'r2', title: '清明节主题海报', type: '海报', submitter: '张明', submitTime: '2026-03-26 09:15', status: '待审核', content: '清明踏青·美食相伴，全场套餐85折，到店即送春茶一杯' },
  { id: 'r3', title: '沉睡客户唤醒短信 V2', type: '短信', submitter: '王芳', submitTime: '2026-03-25 16:45', status: '待审核', content: '【尝在一起】很想念您！专属¥25无门槛券已到账，7天内有效' },
  { id: 'r4', title: '母亲节预热文案', type: '文案', submitter: '陈思', submitTime: '2026-03-25 14:20', status: '已通过', content: '把爱煮成一桌好菜，母亲节全家宴预订开启！' },
  { id: 'r5', title: '会员生日祝福', type: '企微', submitter: '李晓雯', submitTime: '2026-03-24 11:00', status: '已通过', content: '生日快乐！送您一份生日专属大礼包：免费甜品+双倍积分+满100减30' },
  { id: 'r6', title: '周末限时折扣', type: '小程序', submitter: '赵磊', submitTime: '2026-03-24 09:30', status: '已拒绝', content: '本周末全场5折！——折扣力度过大，不符合毛利底线' },
];

const MOCK_STATS: ContentStat[] = [
  { id: 's1', title: '新客欢迎短信', type: '短信', sendCount: 3420, openRate: 72.3, clickRate: 28.5, conversionRate: 18.5, revenue: 68400, date: '2026-03-25' },
  { id: 's2', title: '复购召回企微', type: '企微', sendCount: 1856, openRate: 85.2, clickRate: 34.1, conversionRate: 12.3, revenue: 42300, date: '2026-03-24' },
  { id: 's3', title: '春季新品海报', type: '海报', sendCount: 2130, openRate: 0, clickRate: 15.6, conversionRate: 8.7, revenue: 35600, date: '2026-03-23' },
  { id: 's4', title: '会员日小程序弹窗', type: '小程序', sendCount: 5620, openRate: 0, clickRate: 42.8, conversionRate: 22.1, revenue: 128700, date: '2026-03-22' },
  { id: 's5', title: '裂变分享海报', type: '海报', sendCount: 1245, openRate: 0, clickRate: 22.4, conversionRate: 15.6, revenue: 28900, date: '2026-03-21' },
  { id: 's6', title: '低峰引流短信', type: '短信', sendCount: 890, openRate: 65.1, clickRate: 18.3, conversionRate: 6.2, revenue: 12400, date: '2026-03-20' },
  { id: 's7', title: '储值推广文案', type: '文案', sendCount: 1670, openRate: 78.4, clickRate: 25.7, conversionRate: 9.8, revenue: 83500, date: '2026-03-19' },
];

// ---- 子组件 ----

function TabBar({ activeTab, setActiveTab }: { activeTab: TabKey; setActiveTab: (t: TabKey) => void }) {
  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: 'templates', label: '模板库', count: MOCK_TEMPLATES.length },
    { key: 'workbench', label: '内容生成工作台' },
    { key: 'review', label: '审核队列', count: MOCK_REVIEWS.filter(r => r.status === '待审核').length },
    { key: 'stats', label: '效果统计' },
  ];
  return (
    <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
      {tabs.map(t => (
        <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
          padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
          background: activeTab === t.key ? BRAND : BG_1,
          color: activeTab === t.key ? '#fff' : TEXT_3,
          fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {t.label}
          {t.count != null && (
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 10,
              background: activeTab === t.key ? '#ffffff33' : BG_2,
              color: activeTab === t.key ? '#fff' : TEXT_4,
            }}>{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

function TemplateGrid({ templates, typeFilter }: { templates: Template[]; typeFilter: ContentType }) {
  const filtered = typeFilter === '全部' ? templates : templates.filter(t => t.type === typeFilter);
  const statusColors: Record<string, string> = { '已发布': GREEN, '草稿': TEXT_4, '待审核': YELLOW };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
      {filtered.map(t => (
        <div key={t.id} style={{
          background: BG_1, borderRadius: 10, padding: 16,
          border: `1px solid ${BG_2}`, cursor: 'pointer',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: BRAND + '22', color: BRAND, fontWeight: 600,
              }}>{t.type}</span>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: BLUE + '22', color: BLUE, fontWeight: 600,
              }}>{t.scene}</span>
            </div>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: statusColors[t.status] + '22', color: statusColors[t.status], fontWeight: 600,
            }}>{t.status}</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 8 }}>{t.name}</div>
          <div style={{
            fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 10,
            padding: '8px 10px', background: BG_2, borderRadius: 6,
            borderLeft: `3px solid ${BRAND}44`,
          }}>{t.previewText}</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_4 }}>
            <span>使用 {t.usageCount.toLocaleString()} 次</span>
            <span>转化率 {t.conversionRate > 0 ? `${t.conversionRate}%` : '-'}</span>
            <span>{t.updatedAt}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function GenerationWorkbench() {
  const [contentType, setContentType] = useState<string>('短信');
  const [brand, setBrand] = useState<string>('尝在一起');
  const [segment, setSegment] = useState<string>('30天未复购');
  const [generated, setGenerated] = useState(false);

  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '8px 12px', fontSize: 13, outline: 'none',
    cursor: 'pointer', width: '100%',
  };

  const mockResults = [
    '【尝在一起】好久不见！我们的酸汤系列新品已上线，专属回归券满80减20已为您备好，7天内有效→',
    '【尝在一起】想念您的到来！春季新品等您品鉴，凭此短信到店享88折优惠，本周有效~',
    '【尝在一起】味道还记得吗？30天未见，送您一份暖心礼：免费甜品一份+满100减15，到店出示即可',
  ];

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      {/* 左侧配置区 */}
      <div style={{
        width: 320, background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`, flexShrink: 0,
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>生成配置</h3>
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>内容类型</label>
          <select value={contentType} onChange={e => setContentType(e.target.value)} style={selectStyle}>
            <option>文案</option><option>海报</option><option>短信</option>
            <option>企微</option><option>小程序</option><option>节日</option>
          </select>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>品牌</label>
          <select value={brand} onChange={e => setBrand(e.target.value)} style={selectStyle}>
            <option>尝在一起</option><option>最黔线</option><option>尚宫厨</option>
          </select>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>目标人群</label>
          <select value={segment} onChange={e => setSegment(e.target.value)} style={selectStyle}>
            <option>30天未复购</option><option>新客首单</option><option>沉睡客户</option>
            <option>高频复购</option><option>生日客户</option><option>全部会员</option>
          </select>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>营销场景</label>
          <select style={selectStyle}>
            <option>复购召回</option><option>新品推广</option><option>节日营销</option>
            <option>低峰引流</option><option>储值推广</option><option>裂变拉新</option>
          </select>
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>语气风格</label>
          <select style={selectStyle}>
            <option>温暖亲切</option><option>活泼俏皮</option><option>简洁商务</option><option>文艺情感</option>
          </select>
        </div>
        <button onClick={() => setGenerated(true)} style={{
          width: '100%', padding: '10px 0', borderRadius: 8, border: 'none',
          background: BRAND, color: '#fff', fontSize: 14, fontWeight: 700,
          cursor: 'pointer', marginTop: 8,
        }}>AI 生成内容</button>
      </div>

      {/* 右侧结果区 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {!generated ? (
          <div style={{
            background: BG_1, borderRadius: 10, padding: 40,
            border: `1px solid ${BG_2}`, textAlign: 'center',
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>AI</div>
            <div style={{ fontSize: 15, color: TEXT_3 }}>配置参数后点击「AI 生成内容」</div>
            <div style={{ fontSize: 12, color: TEXT_4, marginTop: 8 }}>AI 将根据品牌调性、目标人群和营销场景自动生成多个方案</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{
              background: BG_1, borderRadius: 10, padding: 16,
              border: `1px solid ${BG_2}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>生成结果</span>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 10,
                  background: PURPLE + '22', color: PURPLE, fontWeight: 600,
                }}>AI</span>
                <span style={{ fontSize: 11, color: TEXT_4 }}>品牌: {brand} | 人群: {segment} | 类型: {contentType}</span>
              </div>
              {mockResults.map((text, i) => (
                <div key={i} style={{
                  padding: '14px 16px', background: BG_2, borderRadius: 8,
                  marginBottom: 10, borderLeft: `3px solid ${i === 0 ? GREEN : BG_2}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, color: TEXT_2, fontWeight: 600 }}>方案 {i + 1}</span>
                    {i === 0 && <span style={{ fontSize: 10, color: GREEN, fontWeight: 600 }}>推荐</span>}
                  </div>
                  <div style={{ fontSize: 13, color: TEXT_1, lineHeight: 1.7, marginBottom: 10 }}>{text}</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button style={{
                      padding: '4px 12px', borderRadius: 6, border: 'none',
                      background: BRAND + '22', color: BRAND, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                    }}>采用</button>
                    <button style={{
                      padding: '4px 12px', borderRadius: 6, border: 'none',
                      background: BG_1, color: TEXT_3, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                    }}>编辑</button>
                    <button style={{
                      padding: '4px 12px', borderRadius: 6, border: 'none',
                      background: BG_1, color: TEXT_3, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                    }}>提交审核</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ReviewQueue({ reviews }: { reviews: ReviewItem[] }) {
  const statusColors: Record<string, string> = { '待审核': YELLOW, '已通过': GREEN, '已拒绝': RED };
  const [filter, setFilter] = useState<string>('全部');
  const filtered = filter === '全部' ? reviews : reviews.filter(r => r.status === filter);

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>内容审核队列</h3>
        {['全部', '待审核', '已通过', '已拒绝'].map(s => (
          <button key={s} onClick={() => setFilter(s)} style={{
            padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: filter === s ? BRAND : BG_2, color: filter === s ? '#fff' : TEXT_3,
            fontSize: 11, fontWeight: 600,
          }}>{s}</button>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {filtered.map(r => (
          <div key={r.id} style={{
            padding: '14px 16px', background: BG_2, borderRadius: 8,
            borderLeft: `3px solid ${statusColors[r.status]}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{r.title}</span>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: BRAND + '22', color: BRAND, fontWeight: 600,
                }}>{r.type}</span>
              </div>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: statusColors[r.status] + '22', color: statusColors[r.status], fontWeight: 600,
              }}>{r.status}</span>
            </div>
            <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 8 }}>{r.content}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: TEXT_4 }}>提交人: {r.submitter} | {r.submitTime}</span>
              {r.status === '待审核' && (
                <div style={{ display: 'flex', gap: 6 }}>
                  <button style={{
                    padding: '4px 14px', borderRadius: 6, border: 'none',
                    background: GREEN + '22', color: GREEN, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                  }}>通过</button>
                  <button style={{
                    padding: '4px 14px', borderRadius: 6, border: 'none',
                    background: RED + '22', color: RED, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                  }}>拒绝</button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatsTable({ stats }: { stats: ContentStat[] }) {
  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>内容效果统计</h3>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['内容标题', '类型', '发送量', '打开率', '点击率', '转化率', '贡献营收', '日期'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stats.map(s => (
              <tr key={s.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{s.title}</td>
                <td style={{ padding: '10px' }}>
                  <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: BRAND + '22', color: BRAND }}>{s.type}</span>
                </td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{s.sendCount.toLocaleString()}</td>
                <td style={{ padding: '10px', color: s.openRate > 70 ? GREEN : TEXT_2 }}>
                  {s.openRate > 0 ? `${s.openRate}%` : '-'}
                </td>
                <td style={{ padding: '10px', color: s.clickRate > 25 ? GREEN : TEXT_2 }}>{s.clickRate}%</td>
                <td style={{ padding: '10px', color: s.conversionRate > 15 ? GREEN : s.conversionRate > 8 ? YELLOW : TEXT_3, fontWeight: 600 }}>
                  {s.conversionRate}%
                </td>
                <td style={{ padding: '10px', color: GREEN, fontWeight: 600 }}>{'\u00A5'}{(s.revenue / 10000).toFixed(1)}万</td>
                <td style={{ padding: '10px', color: TEXT_4 }}>{s.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* 汇总行 */}
      <div style={{
        display: 'flex', gap: 20, padding: '12px 10px', marginTop: 8,
        background: BG_2, borderRadius: 8, fontSize: 12,
      }}>
        <span style={{ color: TEXT_3 }}>总发送量: <strong style={{ color: TEXT_1 }}>{stats.reduce((a, s) => a + s.sendCount, 0).toLocaleString()}</strong></span>
        <span style={{ color: TEXT_3 }}>平均转化率: <strong style={{ color: BRAND }}>{(stats.reduce((a, s) => a + s.conversionRate, 0) / stats.length).toFixed(1)}%</strong></span>
        <span style={{ color: TEXT_3 }}>总营收贡献: <strong style={{ color: GREEN }}>{'\u00A5'}{(stats.reduce((a, s) => a + s.revenue, 0) / 10000).toFixed(1)}万</strong></span>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function ContentCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('templates');
  const [typeFilter, setTypeFilter] = useState<ContentType>('全部');

  const typeOptions: ContentType[] = ['全部', '文案', '海报', '短信', '企微', '小程序', '节日'];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>内容资产中心</h2>

      {/* KPI 概览 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: '模板总数', value: '48', change: 6 },
          { label: '本月生成次数', value: '1,256', change: 23.4 },
          { label: '审核通过率', value: '87.3%', change: 2.1 },
          { label: '平均转化率', value: '14.2%', change: 1.8 },
          { label: '内容贡献营收', value: '\u00A539.9万', change: 15.6 },
        ].map((kpi, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: '14px 16px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: TEXT_1 }}>{kpi.value}</div>
            <div style={{ fontSize: 11, color: kpi.change >= 0 ? GREEN : RED, marginTop: 4 }}>
              {kpi.change >= 0 ? '+' : ''}{kpi.change}% 较上期
            </div>
          </div>
        ))}
      </div>

      {/* Tab 栏 */}
      <TabBar activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* 类型过滤（模板库 + 统计 可用） */}
      {(activeTab === 'templates' || activeTab === 'stats') && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
          {typeOptions.map(t => (
            <button key={t} onClick={() => setTypeFilter(t)} style={{
              padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: typeFilter === t ? BLUE : BG_2, color: typeFilter === t ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600,
            }}>{t}</button>
          ))}
        </div>
      )}

      {/* Tab 内容 */}
      {activeTab === 'templates' && <TemplateGrid templates={MOCK_TEMPLATES} typeFilter={typeFilter} />}
      {activeTab === 'workbench' && <GenerationWorkbench />}
      {activeTab === 'review' && <ReviewQueue reviews={MOCK_REVIEWS} />}
      {activeTab === 'stats' && <StatsTable stats={MOCK_STATS} />}
    </div>
  );
}
