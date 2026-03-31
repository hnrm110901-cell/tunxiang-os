/**
 * ReviewTopicPage — 口碑主题中心
 * 路由: /hq/market-intel/reviews
 * 主题词云 + 门店对比矩阵 + 待处理问题列表 + 营销亮点
 */
import { useState } from 'react';

const BG_1 = '#1a2836';
const BG_2 = '#243442';
const BRAND = '#ff6b2c';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'cloud' | 'matrix' | 'issues' | 'highlights';

interface TopicItem {
  keyword: string;
  category: '好评' | '差评' | '菜品' | '服务' | '卫生' | '等待' | '性价比';
  sentiment: 'positive' | 'neutral' | 'negative';
  count: number;
  trend: 'up' | 'down' | 'stable';
  trendPct: number;
}

interface StoreReviewScore {
  storeName: string;
  overall: number;
  food: number;
  service: number;
  environment: number;
  wait: number;
  value: number;
  reviewCount: number;
  negativeCount: number;
}

interface ActionableIssue {
  id: string;
  topic: string;
  storeName: string;
  severity: 'high' | 'medium' | 'low';
  sampleReview: string;
  mentionCount: number;
  trend: 'up' | 'down' | 'stable';
  suggestedAction: string;
  status: '待处理' | '处理中' | '已解决';
}

interface MarketingHighlight {
  id: string;
  topic: string;
  storeName: string;
  sampleReview: string;
  positiveCount: number;
  shareability: number;
  suggestedUse: string;
}

const MOCK_TOPICS: TopicItem[] = [
  { keyword: '辣椒炒肉', category: '好评', sentiment: 'positive', count: 1256, trend: 'up', trendPct: 15 },
  { keyword: '服务热情', category: '服务', sentiment: 'positive', count: 892, trend: 'up', trendPct: 8 },
  { keyword: '等位太久', category: '等待', sentiment: 'negative', count: 645, trend: 'up', trendPct: 22 },
  { keyword: '味道正宗', category: '好评', sentiment: 'positive', count: 1034, trend: 'stable', trendPct: 2 },
  { keyword: '环境干净', category: '卫生', sentiment: 'positive', count: 567, trend: 'stable', trendPct: 0 },
  { keyword: '性价比高', category: '性价比', sentiment: 'positive', count: 789, trend: 'up', trendPct: 12 },
  { keyword: '上菜慢', category: '等待', sentiment: 'negative', count: 423, trend: 'down', trendPct: -5 },
  { keyword: '分量足', category: '好评', sentiment: 'positive', count: 678, trend: 'stable', trendPct: 3 },
  { keyword: '菜品偏咸', category: '差评', sentiment: 'negative', count: 234, trend: 'up', trendPct: 18 },
  { keyword: '服务员态度差', category: '差评', sentiment: 'negative', count: 156, trend: 'down', trendPct: -10 },
  { keyword: '新品好吃', category: '菜品', sentiment: 'positive', count: 345, trend: 'up', trendPct: 35 },
  { keyword: '厕所脏', category: '卫生', sentiment: 'negative', count: 89, trend: 'down', trendPct: -15 },
  { keyword: '装修有特色', category: '好评', sentiment: 'positive', count: 432, trend: 'stable', trendPct: 1 },
  { keyword: '排队叫号混乱', category: '等待', sentiment: 'negative', count: 178, trend: 'up', trendPct: 25 },
  { keyword: '酸汤鱼绝了', category: '菜品', sentiment: 'positive', count: 267, trend: 'up', trendPct: 120 },
  { keyword: '米饭硬', category: '差评', sentiment: 'negative', count: 112, trend: 'stable', trendPct: 0 },
  { keyword: '适合聚餐', category: '好评', sentiment: 'positive', count: 534, trend: 'up', trendPct: 6 },
  { keyword: '空调太冷', category: '差评', sentiment: 'negative', count: 67, trend: 'down', trendPct: -20 },
];

const MOCK_STORE_SCORES: StoreReviewScore[] = [
  { storeName: '芙蓉路店', overall: 4.6, food: 4.7, service: 4.5, environment: 4.6, wait: 4.2, value: 4.5, reviewCount: 3240, negativeCount: 86 },
  { storeName: '万达广场店', overall: 4.4, food: 4.5, service: 4.3, environment: 4.4, wait: 3.8, value: 4.3, reviewCount: 2860, negativeCount: 124 },
  { storeName: '梅溪湖店', overall: 4.5, food: 4.6, service: 4.4, environment: 4.7, wait: 4.0, value: 4.4, reviewCount: 2450, negativeCount: 78 },
  { storeName: '五一广场店', overall: 4.2, food: 4.3, service: 4.0, environment: 4.1, wait: 3.5, value: 4.1, reviewCount: 3560, negativeCount: 215 },
  { storeName: '星沙店', overall: 4.3, food: 4.4, service: 4.2, environment: 4.3, wait: 3.9, value: 4.4, reviewCount: 1890, negativeCount: 95 },
  { storeName: '河西大学城店', overall: 4.1, food: 4.2, service: 3.9, environment: 4.0, wait: 3.6, value: 4.5, reviewCount: 2120, negativeCount: 167 },
  { storeName: '开福寺店', overall: 4.0, food: 4.1, service: 3.8, environment: 3.9, wait: 3.4, value: 4.2, reviewCount: 1670, negativeCount: 143 },
];

const MOCK_ISSUES: ActionableIssue[] = [
  { id: 'ai1', topic: '等位太久', storeName: '五一广场店', severity: 'high', sampleReview: '周末等了快一个半小时，叫号系统也乱，体验很差', mentionCount: 245, trend: 'up', suggestedAction: '增加等位管理系统，优化翻台率，增加预约取号渠道', status: '处理中' },
  { id: 'ai2', topic: '上菜慢', storeName: '河西大学城店', severity: 'high', sampleReview: '点完餐等了40分钟才上第一道菜，午休时间根本来不及', mentionCount: 178, trend: 'stable', suggestedAction: '优化后厨动线，增加午间备菜量，推出午市快速套餐', status: '待处理' },
  { id: 'ai3', topic: '菜品偏咸', storeName: '全部门店', severity: 'medium', sampleReview: '辣椒炒肉味道不错但有点太咸了，希望能调整下', mentionCount: 234, trend: 'up', suggestedAction: '调研各门店厨师用盐量标准，统一SOP，增加"少盐"选项', status: '待处理' },
  { id: 'ai4', topic: '排队叫号混乱', storeName: '万达广场店', severity: 'medium', sampleReview: '叫到我号的时候没听到，结果又被跳过了，很不合理', mentionCount: 98, trend: 'up', suggestedAction: '升级叫号系统，增加短信/微信提醒功能', status: '待处理' },
  { id: 'ai5', topic: '服务员态度差', storeName: '开福寺店', severity: 'medium', sampleReview: '服务员好像不太耐烦，催了两次才给加水', mentionCount: 67, trend: 'down', suggestedAction: '加强服务培训，建立服务质量考核机制', status: '已解决' },
  { id: 'ai6', topic: '米饭质量', storeName: '星沙店', severity: 'low', sampleReview: '米饭煮得有点硬，不太好吃', mentionCount: 45, trend: 'stable', suggestedAction: '检查米饭设备和米品质量，调整蒸煮参数', status: '待处理' },
];

const MOCK_HIGHLIGHTS: MarketingHighlight[] = [
  { id: 'mh1', topic: '辣椒炒肉', storeName: '芙蓉路店', sampleReview: '来长沙必吃的辣椒炒肉！肉嫩辣椒香，配上米饭简直绝了', positiveCount: 456, shareability: 92, suggestedUse: '小红书/抖音种草内容，突出"来长沙必吃"定位' },
  { id: 'mh2', topic: '性价比', storeName: '全部门店', sampleReview: '人均60-70就能吃得很好，4个人200多搞定，太划算了', positiveCount: 345, shareability: 85, suggestedUse: '美团/大众点评推广语，强调高性价比聚餐选择' },
  { id: 'mh3', topic: '酸汤鱼', storeName: '梅溪湖店', sampleReview: '新出的酸汤鱼太好吃了！汤鲜鱼嫩，喝了三碗汤', positiveCount: 267, shareability: 95, suggestedUse: '新品推广素材，用户UGC二次传播' },
  { id: 'mh4', topic: '适合聚餐', storeName: '全部门店', sampleReview: '朋友聚餐首选，菜品丰富分量大，环境也好拍照', positiveCount: 234, shareability: 78, suggestedUse: '聚餐场景营销，朋友聚会/家庭聚餐推荐' },
  { id: 'mh5', topic: '装修特色', storeName: '芙蓉路店', sampleReview: '装修很有湖南特色，拍照打卡很好看，适合发朋友圈', positiveCount: 189, shareability: 88, suggestedUse: '打卡营销，鼓励顾客拍照分享' },
];

function TopicCloud({ topics }: { topics: TopicItem[] }) {
  const sentimentColors: Record<string, string> = { positive: GREEN, neutral: TEXT_3, negative: RED };
  const [filter, setFilter] = useState<string>('全部');
  const categories = ['全部', '好评', '差评', '菜品', '服务', '卫生', '等待', '性价比'];
  const filtered = filter === '全部' ? topics : topics.filter(t => t.category === filter);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>口碑主题词云</h3>
        {categories.map(c => (
          <button key={c} onClick={() => setFilter(c)} style={{
            padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: filter === c ? BRAND : BG_2, color: filter === c ? '#fff' : TEXT_3,
            fontSize: 11, fontWeight: 600,
          }}>{c}</button>
        ))}
      </div>

      {/* Word cloud */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center',
        padding: 20, minHeight: 200,
      }}>
        {filtered.sort((a, b) => b.count - a.count).map((t, i) => {
          const fontSize = Math.max(12, Math.min(28, t.count / 50 + 8));
          return (
            <span key={i} style={{
              fontSize, fontWeight: t.count > 500 ? 700 : 500,
              color: sentimentColors[t.sentiment],
              padding: '4px 10px', borderRadius: 6,
              background: sentimentColors[t.sentiment] + '11',
              cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              {t.keyword}
              {t.trend === 'up' && <span style={{ fontSize: 10, color: t.sentiment === 'negative' ? RED : GREEN }}>{'\u2191'}{t.trendPct}%</span>}
              {t.trend === 'down' && <span style={{ fontSize: 10, color: GREEN }}>{'\u2193'}{Math.abs(t.trendPct)}%</span>}
            </span>
          );
        })}
      </div>

      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 12 }}>
        <span style={{ fontSize: 11, color: GREEN }}>--- 正面</span>
        <span style={{ fontSize: 11, color: TEXT_3 }}>--- 中性</span>
        <span style={{ fontSize: 11, color: RED }}>--- 负面</span>
      </div>

      {/* Topic detail table */}
      <div style={{ marginTop: 16 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['主题词', '分类', '情感', '提及次数', '趋势', '变化'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 10).map((t, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '8px 10px', color: TEXT_1, fontWeight: 500 }}>{t.keyword}</td>
                <td style={{ padding: '8px 10px' }}>
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 4,
                    background: BG_2, color: TEXT_3, fontWeight: 600,
                  }}>{t.category}</span>
                </td>
                <td style={{ padding: '8px 10px' }}>
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 4,
                    background: sentimentColors[t.sentiment] + '22', color: sentimentColors[t.sentiment], fontWeight: 600,
                  }}>{t.sentiment === 'positive' ? '正面' : t.sentiment === 'negative' ? '负面' : '中性'}</span>
                </td>
                <td style={{ padding: '8px 10px', color: TEXT_2, fontWeight: 600 }}>{t.count}</td>
                <td style={{ padding: '8px 10px', color: t.trend === 'up' ? (t.sentiment === 'negative' ? RED : GREEN) : t.trend === 'down' ? GREEN : TEXT_4 }}>
                  {t.trend === 'up' ? '\u2191 上升' : t.trend === 'down' ? '\u2193 下降' : '- 稳定'}
                </td>
                <td style={{ padding: '8px 10px', color: t.trendPct > 0 ? (t.sentiment === 'negative' ? RED : GREEN) : GREEN }}>
                  {t.trendPct > 0 ? '+' : ''}{t.trendPct}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StoreMatrix({ stores }: { stores: StoreReviewScore[] }) {
  const scoreColor = (v: number) => v >= 4.4 ? GREEN : v >= 4.0 ? YELLOW : RED;
  const sorted = [...stores].sort((a, b) => b.overall - a.overall);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>门店口碑对比矩阵</h3>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['门店', '综合', '菜品', '服务', '环境', '等待', '性价比', '评价数', '差评数'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(s => (
              <tr key={s.storeName} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{s.storeName}</td>
                <td style={{ padding: '10px', color: scoreColor(s.overall), fontWeight: 700, fontSize: 15 }}>{s.overall}</td>
                <td style={{ padding: '10px', color: scoreColor(s.food) }}>{s.food}</td>
                <td style={{ padding: '10px', color: scoreColor(s.service) }}>{s.service}</td>
                <td style={{ padding: '10px', color: scoreColor(s.environment) }}>{s.environment}</td>
                <td style={{ padding: '10px', color: scoreColor(s.wait) }}>{s.wait}</td>
                <td style={{ padding: '10px', color: scoreColor(s.value) }}>{s.value}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{s.reviewCount.toLocaleString()}</td>
                <td style={{ padding: '10px', color: s.negativeCount > 150 ? RED : s.negativeCount > 100 ? YELLOW : TEXT_3 }}>
                  {s.negativeCount}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function IssuesList({ issues }: { issues: ActionableIssue[] }) {
  const sevColors: Record<string, string> = { high: RED, medium: YELLOW, low: BLUE };
  const sevLabels: Record<string, string> = { high: '紧急', medium: '一般', low: '低' };
  const statusColors: Record<string, string> = { '待处理': RED, '处理中': YELLOW, '已解决': GREEN };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>待处理问题列表</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {issues.map(issue => (
          <div key={issue.id} style={{
            padding: '14px 16px', background: BG_2, borderRadius: 8,
            borderLeft: `3px solid ${sevColors[issue.severity]}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: sevColors[issue.severity] + '22', color: sevColors[issue.severity], fontWeight: 700,
                }}>{sevLabels[issue.severity]}</span>
                <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{issue.topic}</span>
                <span style={{ fontSize: 11, color: TEXT_3 }}>{issue.storeName}</span>
              </div>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: statusColors[issue.status] + '22', color: statusColors[issue.status], fontWeight: 600,
              }}>{issue.status}</span>
            </div>
            <div style={{
              fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 8,
              padding: '6px 10px', background: BG_1, borderRadius: 4, fontStyle: 'italic',
            }}>
              "{issue.sampleReview}"
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: TEXT_4 }}>提及 {issue.mentionCount} 次</span>
              <span style={{ fontSize: 11, color: issue.trend === 'up' ? RED : GREEN }}>
                趋势 {issue.trend === 'up' ? '\u2191 上升' : issue.trend === 'down' ? '\u2193 下降' : '稳定'}
              </span>
            </div>
            <div style={{
              fontSize: 11, color: BLUE, padding: '6px 10px',
              background: BLUE + '11', borderRadius: 4,
            }}>
              建议: {issue.suggestedAction}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HighlightsPanel({ highlights }: { highlights: MarketingHighlight[] }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>营销亮点素材</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
        {highlights.map(h => (
          <div key={h.id} style={{
            padding: '14px 16px', background: BG_2, borderRadius: 8,
            borderTop: `3px solid ${GREEN}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{h.topic}</span>
              <span style={{ fontSize: 11, color: TEXT_3 }}>{h.storeName}</span>
            </div>
            <div style={{
              fontSize: 12, color: TEXT_2, lineHeight: 1.6, marginBottom: 10,
              padding: '8px 10px', background: BG_1, borderRadius: 4,
              borderLeft: `3px solid ${GREEN}44`,
            }}>
              "{h.sampleReview}"
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 11 }}>
              <span style={{ color: GREEN }}>正面提及: {h.positiveCount}</span>
              <span style={{ color: BRAND }}>传播力: {h.shareability}/100</span>
            </div>
            <div style={{
              fontSize: 11, color: BLUE, padding: '6px 10px',
              background: BLUE + '11', borderRadius: 4,
            }}>
              推荐用途: {h.suggestedUse}
            </div>
            <button style={{
              marginTop: 8, padding: '4px 14px', borderRadius: 6, border: 'none',
              background: GREEN + '22', color: GREEN, fontSize: 11, fontWeight: 600, cursor: 'pointer',
            }}>导出为营销素材</button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function ReviewTopicPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('cloud');
  const tabs: { key: TabKey; label: string }[] = [
    { key: 'cloud', label: '主题词云' },
    { key: 'matrix', label: '门店对比' },
    { key: 'issues', label: '待处理问题' },
    { key: 'highlights', label: '营销亮点' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>口碑主题中心</h2>

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: '总评价数', value: '17,790', change: 8.5, color: TEXT_1 },
          { label: '综合评分', value: '4.3', change: 0.1, color: GREEN },
          { label: '正面占比', value: '78.2%', change: 2.3, color: GREEN },
          { label: '负面占比', value: '12.5%', change: -1.2, color: RED },
          { label: '待处理问题', value: '4', change: 0, color: YELLOW },
        ].map((kpi, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: '14px 16px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
            {kpi.change !== 0 && (
              <div style={{ fontSize: 11, color: kpi.label === '负面占比' ? (kpi.change < 0 ? GREEN : RED) : (kpi.change > 0 ? GREEN : RED), marginTop: 4 }}>
                {kpi.change > 0 ? '+' : ''}{kpi.change}% 较上期
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: activeTab === t.key ? BRAND : BG_1,
            color: activeTab === t.key ? '#fff' : TEXT_3,
            fontSize: 13, fontWeight: 600,
          }}>{t.label}</button>
        ))}
      </div>

      {activeTab === 'cloud' && <TopicCloud topics={MOCK_TOPICS} />}
      {activeTab === 'matrix' && <StoreMatrix stores={MOCK_STORE_SCORES} />}
      {activeTab === 'issues' && <IssuesList issues={MOCK_ISSUES} />}
      {activeTab === 'highlights' && <HighlightsPanel highlights={MOCK_HIGHLIGHTS} />}
    </div>
  );
}
