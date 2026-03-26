/**
 * IntelDashboardPage -- 市场情报总览
 * 路由: /hq/market-intel/dashboard
 */
import { useState } from 'react';

// ---- 颜色常量 ----
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

// ---- 类型定义 ----
interface TrendTopic {
  id: string;
  keyword: string;
  heat: number;
  trend: 'up' | 'down' | 'stable';
  changePercent: number;
}

interface IntelAlert {
  id: string;
  type: '新品机会' | '风险预警' | '竞对动作' | '热门趋势';
  title: string;
  severity: 'high' | 'medium' | 'low';
  date: string;
}

interface CompetitorAction {
  id: string;
  competitor: string;
  action: string;
  date: string;
  impact: 'high' | 'medium' | 'low';
  detail: string;
}

interface MarketHeatPoint {
  month: string;
  heat: number;
  mentions: number;
}

interface CategoryCompetition {
  category: string;
  ourShare: number;
  competitors: { name: string; share: number }[];
}

interface DemandTopic {
  keyword: string;
  size: number;
  sentiment: 'positive' | 'neutral' | 'negative';
}

interface AgentSuggestion {
  id: string;
  type: '新品' | '营销' | '防御' | '优化';
  title: string;
  reason: string;
  confidence: number;
  priority: 'P0' | 'P1' | 'P2';
}

interface BottomCard {
  id: string;
  type: '新品机会' | '新原料机会' | '试点建议' | '最新报告';
  title: string;
  summary: string;
  score?: number;
  date: string;
  tag: string;
}

// ---- Mock 数据 ----
const MOCK_TRENDS: TrendTopic[] = [
  { id: 't-1', keyword: '酸汤火锅', heat: 95, trend: 'up', changePercent: 42 },
  { id: 't-2', keyword: '健康轻食', heat: 88, trend: 'up', changePercent: 28 },
  { id: 't-3', keyword: '一人食套餐', heat: 82, trend: 'up', changePercent: 35 },
  { id: 't-4', keyword: '地方特色菜', heat: 78, trend: 'stable', changePercent: 5 },
  { id: 't-5', keyword: '预制菜到家', heat: 75, trend: 'up', changePercent: 18 },
  { id: 't-6', keyword: '性价比套餐', heat: 92, trend: 'up', changePercent: 22 },
  { id: 't-7', keyword: '围炉煮茶', heat: 65, trend: 'down', changePercent: -12 },
  { id: 't-8', keyword: '国潮餐饮', heat: 70, trend: 'stable', changePercent: 3 },
];

const MOCK_ALERTS: IntelAlert[] = [
  { id: 'a-1', type: '新品机会', title: '酸汤系列搜索量激增40%', severity: 'high', date: '2026-03-26' },
  { id: 'a-2', type: '新品机会', title: '一人食套餐需求持续增长', severity: 'medium', date: '2026-03-25' },
  { id: 'a-3', type: '新品机会', title: '健康轻食成新趋势', severity: 'medium', date: '2026-03-24' },
  { id: 'a-4', type: '风险预警', title: '海底捞推出低价套餐抢占市场', severity: 'high', date: '2026-03-26' },
  { id: 'a-5', type: '风险预警', title: '预制菜负面舆情上升', severity: 'medium', date: '2026-03-25' },
  { id: 'a-6', type: '风险预警', title: '原材料价格波动预警', severity: 'low', date: '2026-03-23' },
  { id: 'a-7', type: '竞对动作', title: '太二开出第500家店', severity: 'high', date: '2026-03-26' },
  { id: 'a-8', type: '竞对动作', title: '西贝上线预制菜电商', severity: 'medium', date: '2026-03-25' },
  { id: 'a-9', type: '竞对动作', title: '费大厨推出外卖套餐', severity: 'medium', date: '2026-03-24' },
  { id: 'a-10', type: '竞对动作', title: '望湘园品牌升级', severity: 'low', date: '2026-03-22' },
  { id: 'a-11', type: '热门趋势', title: '小红书酸汤相关内容+200%', severity: 'high', date: '2026-03-26' },
  { id: 'a-12', type: '热门趋势', title: '抖音"一人食"话题破10亿播放', severity: 'medium', date: '2026-03-25' },
];

const MOCK_COMPETITOR_ACTIONS: CompetitorAction[] = [
  { id: 'ca-1', competitor: '海底捞', action: '推出酸汤锅底系列', date: '2026-03-25', impact: 'high', detail: '海底捞全国门店上线6款酸汤锅底，主打酸汤肥牛、酸汤鱼，定价89-129元，目标年轻客群。' },
  { id: 'ca-2', competitor: '西贝', action: '上线预制菜电商渠道', date: '2026-03-24', impact: 'medium', detail: '西贝在天猫/京东开设预制菜旗舰店，首批上线20个SKU，主打家庭场景。' },
  { id: 'ca-3', competitor: '太二', action: '第500家门店开业', date: '2026-03-23', impact: 'high', detail: '太二酸菜鱼第500家门店在成都太古里开业，宣布2026年目标新开150家。' },
  { id: 'ca-4', competitor: '费大厨', action: '推出外卖专属套餐', date: '2026-03-22', impact: 'medium', detail: '费大厨上线美团外卖专属一人食套餐，定价39.9元，含主菜+米饭+小菜。' },
  { id: 'ca-5', competitor: '望湘园', action: '品牌视觉全面升级', date: '2026-03-20', impact: 'low', detail: '望湘园启动品牌升级，新logo主打"新湘菜"定位，首批10家门店完成翻新。' },
];

const MOCK_MARKET_HEAT: MarketHeatPoint[] = [
  { month: '2025-10', heat: 62, mentions: 12500 },
  { month: '2025-11', heat: 68, mentions: 14200 },
  { month: '2025-12', heat: 75, mentions: 18600 },
  { month: '2026-01', heat: 72, mentions: 16800 },
  { month: '2026-02', heat: 80, mentions: 21300 },
  { month: '2026-03', heat: 92, mentions: 28500 },
];

const MOCK_CATEGORY_COMPETITION: CategoryCompetition[] = [
  { category: '湘菜正餐', ourShare: 18, competitors: [{ name: '费大厨', share: 22 }, { name: '望湘园', share: 15 }, { name: '其他', share: 45 }] },
  { category: '火锅/汤锅', ourShare: 5, competitors: [{ name: '海底捞', share: 35 }, { name: '其他', share: 60 }] },
  { category: '酸菜鱼', ourShare: 8, competitors: [{ name: '太二', share: 28 }, { name: '其他', share: 64 }] },
  { category: '家庭聚餐', ourShare: 12, competitors: [{ name: '西贝', share: 20 }, { name: '海底捞', share: 18 }, { name: '其他', share: 50 }] },
];

const MOCK_DEMAND_TOPICS: DemandTopic[] = [
  { keyword: '健康饮食', size: 95, sentiment: 'positive' },
  { keyword: '性价比', size: 88, sentiment: 'positive' },
  { keyword: '一人食', size: 82, sentiment: 'positive' },
  { keyword: '预制菜', size: 70, sentiment: 'negative' },
  { keyword: '地方特色', size: 78, sentiment: 'positive' },
  { keyword: '酸汤', size: 90, sentiment: 'positive' },
  { keyword: '低盐低脂', size: 65, sentiment: 'positive' },
  { keyword: '环境氛围', size: 72, sentiment: 'neutral' },
  { keyword: '等位时间', size: 60, sentiment: 'negative' },
  { keyword: '儿童友好', size: 55, sentiment: 'positive' },
  { keyword: '辣度可选', size: 68, sentiment: 'positive' },
  { keyword: '食材新鲜', size: 85, sentiment: 'positive' },
  { keyword: '外卖包装', size: 52, sentiment: 'negative' },
  { keyword: '下午茶', size: 48, sentiment: 'neutral' },
  { keyword: '节气限定', size: 58, sentiment: 'positive' },
];

const MOCK_AGENT_SUGGESTIONS: AgentSuggestion[] = [
  { id: 'sug-1', type: '新品', title: '建议推出酸汤系列菜品', reason: '酸汤搜索量增长40%, 竞对海底捞已推出, 我方品牌适配度高。建议优先开发酸汤鱼和酸汤肥牛。', confidence: 0.92, priority: 'P0' },
  { id: 'sug-2', type: '营销', title: '加大一人食套餐推广', reason: '一人食需求持续增长, 我方有成本优势, 建议在美团/抖音加大曝光。', confidence: 0.85, priority: 'P0' },
  { id: 'sug-3', type: '防御', title: '应对费大厨外卖低价竞争', reason: '费大厨39.9元套餐对我方外卖客群有分流风险, 建议推出差异化外卖组合。', confidence: 0.78, priority: 'P1' },
  { id: 'sug-4', type: '优化', title: '强化健康轻食产品线', reason: '健康饮食持续高热, 建议增加低盐低脂标签和卡路里标注。', confidence: 0.75, priority: 'P1' },
  { id: 'sug-5', type: '新品', title: '试点节气限定菜品', reason: '节气限定内容在社交媒体表现好, 建议春季推出时令菜品提升话题度。', confidence: 0.7, priority: 'P2' },
];

const MOCK_BOTTOM_CARDS: BottomCard[] = [
  { id: 'bc-1', type: '新品机会', title: '酸汤火锅系列', summary: '市场热度飙升, 竞对已布局, 品牌适配度87分', score: 87, date: '2026-03-26', tag: '高优先' },
  { id: 'bc-2', type: '新品机会', title: '一人食精品套餐', summary: '需求增长35%, 成本可控, 外卖场景适配', score: 82, date: '2026-03-25', tag: '中优先' },
  { id: 'bc-3', type: '新原料机会', title: '云南酸笋', summary: '搜索热度+60%, 供应稳定, 可用于酸汤/配菜', score: 75, date: '2026-03-24', tag: '新发现' },
  { id: 'bc-4', type: '新原料机会', title: '低脂椰奶', summary: '健康饮品趋势, 可开发甜品/饮品线', score: 68, date: '2026-03-23', tag: '待评估' },
  { id: 'bc-5', type: '试点建议', title: '芙蓉路店酸汤试点', summary: '14天周期, 3款核心菜品, 目标日均50份', date: '2026-03-26', tag: '待启动' },
  { id: 'bc-6', type: '试点建议', title: '五一店一人食试点', summary: '商圈白领密集, 午间时段切入, 7天周期', date: '2026-03-25', tag: '已批准' },
  { id: 'bc-7', type: '最新报告', title: '2026Q1湘菜市场分析', summary: '湘菜市场规模同比+15%, 竞争格局变化分析', date: '2026-03-20', tag: '行业报告' },
  { id: 'bc-8', type: '最新报告', title: '竞对月度动态汇总', summary: '5大竞对3月动态汇总, 含战略分析和应对建议', date: '2026-03-18', tag: '竞情报告' },
];

// ---- 组件 ----

function IntelFilterBar() {
  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer',
  };
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
      padding: '12px 16px', background: BG_1, borderRadius: 10, marginBottom: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <label style={{ fontSize: 13, color: TEXT_3 }}>时间</label>
      <select style={selectStyle}>
        <option>近7天</option><option>近30天</option><option>近90天</option><option>本年</option>
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>城市</label>
      <select style={selectStyle}>
        <option>全部城市</option><option>长沙</option><option>武汉</option><option>广州</option><option>深圳</option>
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>商圈</label>
      <select style={selectStyle}>
        <option>全部商圈</option><option>五一广场</option><option>芙蓉路</option><option>梅溪湖</option><option>光谷</option>
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>品类</label>
      <select style={selectStyle}>
        <option>全部品类</option><option>湘菜</option><option>火锅</option><option>酸菜鱼</option><option>快餐</option>
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>竞对组</label>
      <select style={selectStyle}>
        <option>默认竞对组</option><option>海底捞+西贝</option><option>太二+费大厨</option><option>全部竞对</option>
      </select>
    </div>
  );
}

function IntelStatCards({ alerts }: { alerts: IntelAlert[] }) {
  const types: { type: IntelAlert['type']; icon: string; color: string }[] = [
    { type: '热门趋势', icon: '\uD83D\uDD25', color: BRAND },
    { type: '新品机会', icon: '\uD83D\uDCA1', color: GREEN },
    { type: '风险预警', icon: '\u26A0\uFE0F', color: YELLOW },
    { type: '竞对动作', icon: '\uD83C\uDFAF', color: RED },
  ];
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
      {types.map(t => {
        const count = alerts.filter(a => a.type === t.type).length;
        const highCount = alerts.filter(a => a.type === t.type && a.severity === 'high').length;
        return (
          <div key={t.type} style={{
            flex: 1, minWidth: 180, background: BG_1, borderRadius: 10, padding: '14px 18px',
            border: `1px solid ${BG_2}`, cursor: 'pointer', transition: 'border-color .15s',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: 14, color: TEXT_2 }}>{t.icon} {t.type}</span>
              {highCount > 0 && (
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: RED + '22', color: RED, fontWeight: 600,
                }}>{highCount}个高优</span>
              )}
            </div>
            <div style={{ fontSize: 28, fontWeight: 700, color: t.color }}>{count}</div>
            <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>个情报</div>
          </div>
        );
      })}
    </div>
  );
}

function MarketHeatChart({ data }: { data: MarketHeatPoint[] }) {
  const maxHeat = Math.max(...data.map(d => d.heat));
  const chartH = 160;
  return (
    <div style={{
      flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>市场热度趋势</h3>
      <div style={{ display: 'flex', alignItems: 'flex-end', height: chartH, padding: '0 4px' }}>
        {data.map((d, i) => {
          const h = (d.heat / maxHeat) * (chartH - 30);
          return (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: BRAND, fontWeight: 600, marginBottom: 4 }}>{d.heat}</span>
              <div style={{
                width: '60%', height: h, borderRadius: '4px 4px 0 0',
                background: `linear-gradient(180deg, ${BRAND}, ${BRAND}44)`,
              }} />
              <span style={{ fontSize: 10, color: TEXT_4, marginTop: 6 }}>{d.month.slice(5)}月</span>
              <span style={{ fontSize: 9, color: TEXT_4 }}>{(d.mentions / 1000).toFixed(1)}k</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CategoryCompetitionChart({ data }: { data: CategoryCompetition[] }) {
  return (
    <div style={{
      flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>品类竞争态势</h3>
      {data.map((cat, i) => (
        <div key={i} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 13, color: TEXT_2, marginBottom: 6, fontWeight: 600 }}>{cat.category}</div>
          <div style={{ display: 'flex', height: 20, borderRadius: 4, overflow: 'hidden' }}>
            <div style={{ width: `${cat.ourShare}%`, background: BRAND, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {cat.ourShare >= 8 && <span style={{ fontSize: 9, color: '#fff', fontWeight: 700 }}>我方 {cat.ourShare}%</span>}
            </div>
            {cat.competitors.map((comp, j) => {
              const colors = [BLUE, GREEN, PURPLE, YELLOW];
              return (
                <div key={j} style={{
                  width: `${comp.share}%`, background: colors[j % colors.length] + '88',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  {comp.share >= 12 && <span style={{ fontSize: 9, color: '#fff' }}>{comp.name} {comp.share}%</span>}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, color: BRAND }}>--- 我方</span>
        <span style={{ fontSize: 10, color: BLUE }}>--- 竞对1</span>
        <span style={{ fontSize: 10, color: GREEN }}>--- 竞对2</span>
        <span style={{ fontSize: 10, color: PURPLE }}>--- 其他</span>
      </div>
    </div>
  );
}

function CompetitorTimeline({ actions }: { actions: CompetitorAction[] }) {
  const impactColors: Record<string, string> = { high: RED, medium: YELLOW, low: TEXT_4 };
  const competitorColors: Record<string, string> = {
    '海底捞': RED, '西贝': BLUE, '太二': GREEN, '费大厨': BRAND, '望湘园': PURPLE,
  };
  return (
    <div style={{
      flex: 1, minWidth: 260, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>竞对动态摘要</h3>
      {actions.map((a, i) => (
        <div key={a.id} style={{
          position: 'relative', paddingLeft: 20, paddingBottom: 14,
          borderLeft: i < actions.length - 1 ? `2px solid ${BG_2}` : '2px solid transparent',
          marginLeft: 6,
        }}>
          <div style={{
            position: 'absolute', left: -5, top: 2, width: 10, height: 10, borderRadius: '50%',
            background: impactColors[a.impact],
          }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span style={{
              fontSize: 11, padding: '1px 6px', borderRadius: 4,
              background: (competitorColors[a.competitor] || TEXT_4) + '22',
              color: competitorColors[a.competitor] || TEXT_4,
              fontWeight: 600,
            }}>{a.competitor}</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>{a.date}</span>
          </div>
          <div style={{ fontSize: 13, color: TEXT_1, fontWeight: 600, marginBottom: 2 }}>{a.action}</div>
          <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.5 }}>{a.detail}</div>
        </div>
      ))}
    </div>
  );
}

function DemandTopicCloud({ topics }: { topics: DemandTopic[] }) {
  const sentimentColors: Record<string, string> = { positive: GREEN, neutral: TEXT_3, negative: RED };
  return (
    <div style={{
      flex: 1, minWidth: 220, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>需求变化主题</h3>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center' }}>
        {topics.map((t, i) => {
          const fontSize = Math.max(11, Math.min(22, t.size / 5 + 4));
          return (
            <span key={i} style={{
              fontSize, fontWeight: t.size > 80 ? 700 : 500,
              color: sentimentColors[t.sentiment],
              padding: '3px 8px', borderRadius: 6,
              background: sentimentColors[t.sentiment] + '11',
              cursor: 'pointer', transition: 'transform .15s',
              display: 'inline-block',
            }}>
              {t.keyword}
            </span>
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 12 }}>
        <span style={{ fontSize: 10, color: GREEN }}>--- 正面</span>
        <span style={{ fontSize: 10, color: TEXT_3 }}>--- 中性</span>
        <span style={{ fontSize: 10, color: RED }}>--- 负面</span>
      </div>
    </div>
  );
}

function AgentSuggestionsCard({ suggestions }: { suggestions: AgentSuggestion[] }) {
  const typeColors: Record<string, string> = { '新品': GREEN, '营销': BLUE, '防御': RED, '优化': YELLOW };
  const priorityColors: Record<string, string> = { P0: RED, P1: YELLOW, P2: TEXT_4 };
  return (
    <div style={{
      flex: 1, minWidth: 260, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>Agent建议</h3>
      {suggestions.map((s, i) => (
        <div key={s.id} style={{
          padding: '10px 0',
          borderBottom: i < suggestions.length - 1 ? `1px solid ${BG_2}` : 'none',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: typeColors[s.type] + '22', color: typeColors[s.type], fontWeight: 600,
            }}>{s.type}</span>
            <span style={{
              fontSize: 10, padding: '1px 5px', borderRadius: 4,
              background: priorityColors[s.priority] + '22', color: priorityColors[s.priority], fontWeight: 600,
            }}>{s.priority}</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>置信度 {(s.confidence * 100).toFixed(0)}%</span>
          </div>
          <div style={{ fontSize: 13, color: TEXT_1, fontWeight: 600, marginBottom: 2 }}>{s.title}</div>
          <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.5 }}>{s.reason}</div>
        </div>
      ))}
    </div>
  );
}

function BottomCardsRow({ cards }: { cards: BottomCard[] }) {
  const [filter, setFilter] = useState<string>('全部');
  const types = ['全部', '新品机会', '新原料机会', '试点建议', '最新报告'];
  const typeColors: Record<string, string> = { '新品机会': GREEN, '新原料机会': CYAN, '试点建议': BRAND, '最新报告': BLUE };
  const filtered = filter === '全部' ? cards : cards.filter(c => c.type === filter);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>情报卡片</h3>
        <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
          {types.map(t => (
            <button key={t} onClick={() => setFilter(t)} style={{
              padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: filter === t ? BRAND : BG_2,
              color: filter === t ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600, transition: 'all .15s',
            }}>{t}</button>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 4 }}>
        {filtered.map(card => (
          <div key={card.id} style={{
            minWidth: 240, maxWidth: 280, background: BG_2, borderRadius: 8, padding: 14,
            cursor: 'pointer', transition: 'transform .15s', flexShrink: 0,
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: (typeColors[card.type] || TEXT_4) + '22',
                color: typeColors[card.type] || TEXT_4, fontWeight: 600,
              }}>{card.type}</span>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: BRAND + '22', color: BRAND,
              }}>{card.tag}</span>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 6 }}>{card.title}</div>
            <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.5, marginBottom: 8 }}>{card.summary}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 10, color: TEXT_4 }}>{card.date}</span>
              {card.score != null && (
                <span style={{ fontSize: 13, fontWeight: 700, color: card.score >= 80 ? GREEN : YELLOW }}>{card.score}分</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function IntelDashboardPage() {
  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>市场情报中心</h2>

      {/* 顶部筛选 */}
      <IntelFilterBar />

      {/* 情报卡统计 */}
      <IntelStatCards alerts={MOCK_ALERTS} />

      {/* 中部双栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <MarketHeatChart data={MOCK_MARKET_HEAT} />
        <CategoryCompetitionChart data={MOCK_CATEGORY_COMPETITION} />
      </div>

      {/* 下部三栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <CompetitorTimeline actions={MOCK_COMPETITOR_ACTIONS} />
        <DemandTopicCloud topics={MOCK_DEMAND_TOPICS} />
        <AgentSuggestionsCard suggestions={MOCK_AGENT_SUGGESTIONS} />
      </div>

      {/* 底部横向卡片 */}
      <BottomCardsRow cards={MOCK_BOTTOM_CARDS} />
    </div>
  );
}
