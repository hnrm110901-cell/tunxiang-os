/**
 * NewProductOpportunityPage -- 新品机会详情
 * 路由: /hq/market-intel/new-products/:opportunityId
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';

// ---- 颜色常量 ----
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
type OpportunityStatus = '待评估' | '评估中' | '试点中' | '已采纳' | '已否决';

interface ScoreDimension {
  label: string;
  score: number;
  color: string;
}

interface TrendSource {
  type: '竞对' | '搜索' | '评论' | '社媒' | '行业';
  content: string;
  metric?: string;
  date: string;
}

interface StoreMatch {
  storeName: string;
  matchScore: number;
  reasons: string[];
}

interface PilotPlan {
  duration: string;
  storeCount: number;
  targetMetrics: string[];
  estimatedCost: number;
  expectedRevenue: number;
  suggestedDishes: string[];
}

interface SampleData {
  id: string;
  source: string;
  content: string;
  date: string;
  sentiment: 'positive' | 'neutral' | 'negative';
}

interface RelatedCompetitor {
  name: string;
  action: string;
  date: string;
  detail: string;
}

interface RelatedTopic {
  keyword: string;
  heat: number;
  trend: 'up' | 'down' | 'stable';
}

interface HistoricalPilot {
  name: string;
  store: string;
  period: string;
  result: '成功' | '失败' | '进行中';
  avgDailySales: number;
  satisfaction: number;
}

interface OpportunityDetail {
  id: string;
  name: string;
  score: number;
  status: OpportunityStatus;
  isFavorite: boolean;
  summary: string;
  fitScenarios: string[];
  suggestedDishTypes: string[];
  recommendedFlavors: string[];
  scores: ScoreDimension[];
  trendSources: TrendSource[];
  storeMatches: StoreMatch[];
  pilotPlan: PilotPlan;
  samples: SampleData[];
  relatedCompetitors: RelatedCompetitor[];
  relatedTopics: RelatedTopic[];
  historicalPilots: HistoricalPilot[];
}

// ---- Mock 数据 ----
const MOCK_OPPORTUNITIES: Record<string, OpportunityDetail> = {
  'opp-1': {
    id: 'opp-1', name: '酸汤火锅', score: 87, status: '待评估', isFavorite: false,
    summary: '酸汤类菜品在全国范围内搜索量激增40%，社交媒体相关内容增长200%。海底捞等头部品牌已推出酸汤系列，市场验证充分。酸汤口味与湘菜品牌高度适配，建议优先开发酸汤鱼、酸汤肥牛等核心产品。',
    fitScenarios: ['家庭聚餐', '朋友聚会', '冬季暖身', '情侣约会'],
    suggestedDishTypes: ['酸汤鱼', '酸汤肥牛', '酸汤肥肠', '酸汤时蔬'],
    recommendedFlavors: ['酸辣', '番茄酸汤', '酸笋酸汤', '贵州红酸汤'],
    scores: [
      { label: '市场热度', score: 95, color: RED },
      { label: '品牌适配', score: 78, color: BLUE },
      { label: '客群适配', score: 82, color: GREEN },
      { label: '成本可行', score: 75, color: YELLOW },
      { label: '供应稳定', score: 80, color: CYAN },
    ],
    trendSources: [
      { type: '竞对', content: '海底捞全国门店推出6款酸汤锅底，定价89-129元', metric: '覆盖率100%', date: '2026-03-25' },
      { type: '搜索', content: '"酸汤"关键词搜索量同比增长40%', metric: '月搜索量120万', date: '2026-03-24' },
      { type: '评论', content: '大众点评/美团顾客提及"想吃酸汤"相关评论增长65%', metric: '月评论2.8万条', date: '2026-03-23' },
      { type: '社媒', content: '小红书"酸汤"相关笔记增长200%，抖音话题播放量破5亿', metric: '互动率8.5%', date: '2026-03-22' },
      { type: '行业', content: '2026年餐饮趋势报告将"酸汤"列为年度TOP3风味趋势', date: '2026-03-20' },
    ],
    storeMatches: [
      { storeName: '芙蓉路店', matchScore: 92, reasons: ['家庭客群占比高', '厨房条件满足', '商圈消费力匹配'] },
      { storeName: '五一店', matchScore: 85, reasons: ['年轻客群多', '翻台率高', '外卖占比大'] },
      { storeName: '武汉光谷店', matchScore: 78, reasons: ['湖北酸汤接受度高', '竞争较少', '新店需要引流'] },
      { storeName: '梅溪湖店', matchScore: 75, reasons: ['家庭客群增长快', '周末客流大'] },
      { storeName: '广州天河店', matchScore: 70, reasons: ['广东酸汤接受度待验证', '但消费力强'] },
    ],
    pilotPlan: {
      duration: '14天',
      storeCount: 3,
      targetMetrics: ['日均销量 >= 50份', '好评率 >= 85%', '毛利率 >= 55%', '复购率 >= 30%'],
      estimatedCost: 28000,
      expectedRevenue: 84000,
      suggestedDishes: ['酸汤鱼(主打)', '酸汤肥牛', '酸汤时蔬(低成本配搭)'],
    },
    samples: [
      { id: 's-1', source: '小红书', content: '最近酸汤火锅太火了吧！长沙哪里有好吃的酸汤鱼推荐？', date: '2026-03-25', sentiment: 'positive' },
      { id: 's-2', source: '大众点评', content: '希望尝在一起能出酸汤系列，他们家的鱼做得好，酸汤鱼一定好吃', date: '2026-03-24', sentiment: 'positive' },
      { id: 's-3', source: '抖音评论', content: '看了酸汤肥牛的视频馋死了，长沙有没有正宗的酸汤店？', date: '2026-03-23', sentiment: 'positive' },
      { id: 's-4', source: '美团评论', content: '去海底捞吃了酸汤锅底，感觉一般，不够正宗', date: '2026-03-22', sentiment: 'neutral' },
      { id: 's-5', source: '微博', content: '贵州酸汤才是正宗！其他品牌做的都不行', date: '2026-03-21', sentiment: 'negative' },
    ],
    relatedCompetitors: [
      { name: '海底捞', action: '推出6款酸汤锅底', date: '2026-03-25', detail: '全国门店同步上线，主打酸汤肥牛和酸汤鱼' },
      { name: '太二', action: '酸菜鱼+酸汤组合', date: '2026-03-20', detail: '在酸菜鱼基础上增加酸汤系列，形成双品类矩阵' },
      { name: '费大厨', action: '限时酸汤辣椒炒肉', date: '2026-03-18', detail: '将招牌辣椒炒肉与酸汤结合，推出限时新品' },
    ],
    relatedTopics: [
      { keyword: '酸汤', heat: 95, trend: 'up' },
      { keyword: '贵州风味', heat: 72, trend: 'up' },
      { keyword: '酸笋', heat: 68, trend: 'up' },
      { keyword: '番茄锅', heat: 60, trend: 'stable' },
      { keyword: '低脂火锅', heat: 55, trend: 'up' },
    ],
    historicalPilots: [
      { name: '酸菜鱼试点', store: '芙蓉路店', period: '2025-11-01 ~ 2025-11-14', result: '成功', avgDailySales: 62, satisfaction: 88 },
      { name: '椰子鸡试点', store: '五一店', period: '2025-09-15 ~ 2025-09-28', result: '失败', avgDailySales: 18, satisfaction: 65 },
      { name: '剁椒系列扩展', store: '梅溪湖店', period: '2026-01-10 ~ 2026-01-23', result: '成功', avgDailySales: 45, satisfaction: 82 },
    ],
  },
  'opp-2': {
    id: 'opp-2', name: '一人食精品套餐', score: 82, status: '评估中', isFavorite: true,
    summary: '一人食消费场景持续增长，抖音"一人食"话题播放量破10亿。年轻白领和学生客群需求旺盛，竞对费大厨已推出外卖一人食套餐。建议开发堂食+外卖双场景一人食套餐。',
    fitScenarios: ['白领午餐', '学生快餐', '外卖场景', '晚间独食'],
    suggestedDishTypes: ['主菜+米饭+小菜', '迷你套餐', '轻食碗', '拌饭系列'],
    recommendedFlavors: ['经典湘味', '微辣', '酸辣', '清淡'],
    scores: [
      { label: '市场热度', score: 88, color: RED },
      { label: '品牌适配', score: 85, color: BLUE },
      { label: '客群适配', score: 82, color: GREEN },
      { label: '成本可行', score: 82, color: YELLOW },
      { label: '供应稳定', score: 90, color: CYAN },
    ],
    trendSources: [
      { type: '社媒', content: '抖音"一人食"话题播放量破10亿', metric: '月增长35%', date: '2026-03-25' },
      { type: '竞对', content: '费大厨上线39.9元外卖一人食套餐', metric: '日均200单', date: '2026-03-22' },
      { type: '搜索', content: '"一人食 湘菜"搜索量增长55%', metric: '月搜索量45万', date: '2026-03-20' },
      { type: '评论', content: '顾客多次提到"一个人来吃份量太大"', metric: '月提及1.2万次', date: '2026-03-18' },
    ],
    storeMatches: [
      { storeName: '五一店', matchScore: 90, reasons: ['白领客群密集', '午间翻台率高', '外卖占比35%'] },
      { storeName: '芙蓉路店', matchScore: 82, reasons: ['学生客群多', '周边写字楼密集'] },
      { storeName: '武汉光谷店', matchScore: 80, reasons: ['IT从业者多', '一人食需求旺'] },
    ],
    pilotPlan: {
      duration: '7天',
      storeCount: 2,
      targetMetrics: ['日均销量 >= 80份', '好评率 >= 80%', '毛利率 >= 60%'],
      estimatedCost: 12000,
      expectedRevenue: 44800,
      suggestedDishes: ['辣椒炒肉饭', '剁椒鱼头饭', '酸菜肉丝饭'],
    },
    samples: [
      { id: 's-1', source: '美团评论', content: '一个人来吃，菜的份量太大了，希望有小份', date: '2026-03-24', sentiment: 'neutral' },
      { id: 's-2', source: '抖音', content: '一人食湘菜套餐，39块钱吃得又好又饱', date: '2026-03-22', sentiment: 'positive' },
    ],
    relatedCompetitors: [
      { name: '费大厨', action: '推出外卖一人食套餐', date: '2026-03-22', detail: '39.9元含主菜+米饭+小菜，美团专属' },
    ],
    relatedTopics: [
      { keyword: '一人食', heat: 88, trend: 'up' },
      { keyword: '快餐化', heat: 72, trend: 'up' },
      { keyword: '小份菜', heat: 65, trend: 'up' },
    ],
    historicalPilots: [],
  },
  'opp-3': {
    id: 'opp-3', name: '低脂健康套餐', score: 79, status: '待评估', isFavorite: false,
    summary: '健康饮食在年轻消费群体中持续走热，低盐低脂成为餐饮新关键词。建议在现有菜品基础上推出卡路里标注和健康标签系列。',
    fitScenarios: ['健身人群', '减脂期', '白领午餐', '轻食场景'],
    suggestedDishTypes: ['蒸菜系列', '少油炒菜', '沙拉碗', '杂粮饭'],
    recommendedFlavors: ['清蒸', '白灼', '酸辣轻口', '蒜蓉'],
    scores: [
      { label: '市场热度', score: 85, color: RED },
      { label: '品牌适配', score: 72, color: BLUE },
      { label: '客群适配', score: 78, color: GREEN },
      { label: '成本可行', score: 80, color: YELLOW },
      { label: '供应稳定', score: 85, color: CYAN },
    ],
    trendSources: [
      { type: '社媒', content: '小红书"健康餐饮"笔记增长80%', metric: '月笔记量15万', date: '2026-03-24' },
      { type: '搜索', content: '"低脂 湘菜"搜索量增长30%', date: '2026-03-22' },
    ],
    storeMatches: [
      { storeName: '芙蓉路店', matchScore: 80, reasons: ['年轻客群多', '健身房周边'] },
      { storeName: '五一店', matchScore: 75, reasons: ['白领需求旺'] },
    ],
    pilotPlan: {
      duration: '10天',
      storeCount: 2,
      targetMetrics: ['日均销量 >= 40份', '好评率 >= 82%', '毛利率 >= 58%'],
      estimatedCost: 15000,
      expectedRevenue: 32000,
      suggestedDishes: ['清蒸鲈鱼', '蒜蓉西兰花', '杂粮饭套餐'],
    },
    samples: [
      { id: 's-1', source: '小红书', content: '有没有健康的湘菜推荐？减脂期也想吃辣', date: '2026-03-23', sentiment: 'positive' },
    ],
    relatedCompetitors: [],
    relatedTopics: [
      { keyword: '健康饮食', heat: 85, trend: 'up' },
      { keyword: '低盐低脂', heat: 65, trend: 'up' },
      { keyword: '卡路里标注', heat: 55, trend: 'up' },
    ],
    historicalPilots: [],
  },
};

// 为 opp-4 ~ opp-10 生成简单默认数据
const DEFAULT_DETAIL = (id: string, name: string, score: number, status: OpportunityStatus): OpportunityDetail => ({
  id, name, score, status, isFavorite: false,
  summary: `${name}是基于市场趋势分析发现的新品机会，综合评分${score}分，目前处于${status}阶段。`,
  fitScenarios: ['待分析'],
  suggestedDishTypes: ['待确定'],
  recommendedFlavors: ['待确定'],
  scores: [
    { label: '市场热度', score: Math.round(score * 0.85), color: RED },
    { label: '品牌适配', score: Math.round(score * 0.9), color: BLUE },
    { label: '客群适配', score: Math.round(score * 0.88), color: GREEN },
    { label: '成本可行', score: Math.round(score * 0.92), color: YELLOW },
    { label: '供应稳定', score: Math.round(score * 0.95), color: CYAN },
  ],
  trendSources: [{ type: '行业', content: '来源于市场情报Agent自动发现', date: '2026-03-20' }],
  storeMatches: [{ storeName: '芙蓉路店', matchScore: 75, reasons: ['待详细评估'] }],
  pilotPlan: { duration: '14天', storeCount: 1, targetMetrics: ['待设定'], estimatedCost: 10000, expectedRevenue: 25000, suggestedDishes: ['待确定'] },
  samples: [],
  relatedCompetitors: [],
  relatedTopics: [{ keyword: name, heat: score, trend: 'up' }],
  historicalPilots: [],
});

const FALLBACK_MAP: Record<string, [string, number, OpportunityStatus]> = {
  'opp-4': ['酸笋系列配菜', 75, '试点中'],
  'opp-5': ['春季时令菜品', 73, '已采纳'],
  'opp-6': ['外卖专属套餐', 80, '评估中'],
  'opp-7': ['儿童友好餐', 68, '待评估'],
  'opp-8': ['下午茶甜品', 58, '已否决'],
  'opp-9': ['预制菜到家系列', 72, '评估中'],
  'opp-10': ['辣度分级体系', 77, '已采纳'],
};

function getOpportunity(id: string): OpportunityDetail | null {
  if (MOCK_OPPORTUNITIES[id]) return MOCK_OPPORTUNITIES[id];
  const fb = FALLBACK_MAP[id];
  if (fb) return DEFAULT_DETAIL(id, fb[0], fb[1], fb[2]);
  return null;
}

// ---- 组件 ----

function ScoreRadar({ scores }: { scores: ScoreDimension[] }) {
  return (
    <div style={{
      display: 'flex', gap: 12, flexWrap: 'wrap',
    }}>
      {scores.map(s => (
        <div key={s.label} style={{
          flex: 1, minWidth: 100, textAlign: 'center', padding: '10px 8px',
          background: BG_2, borderRadius: 8,
        }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: s.color, marginBottom: 4 }}>{s.score}</div>
          <div style={{ fontSize: 11, color: TEXT_3 }}>{s.label}</div>
          <div style={{
            height: 4, borderRadius: 2, background: BG_1, marginTop: 6,
          }}>
            <div style={{
              width: `${s.score}%`, height: '100%', borderRadius: 2, background: s.color,
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function SourceIcon({ type }: { type: TrendSource['type'] }) {
  const icons: Record<string, string> = { '竞对': '\uD83C\uDFAF', '搜索': '\uD83D\uDD0D', '评论': '\uD83D\uDCAC', '社媒': '\uD83D\uDCF1', '行业': '\uD83D\uDCCA' };
  const colors: Record<string, string> = { '竞对': RED, '搜索': BLUE, '评论': GREEN, '社媒': PURPLE, '行业': CYAN };
  return (
    <span style={{
      fontSize: 10, padding: '2px 6px', borderRadius: 4,
      background: colors[type] + '22', color: colors[type], fontWeight: 600,
    }}>{icons[type]} {type}</span>
  );
}

type TabKey = 'samples' | 'competitors' | 'topics' | 'pilots';

export function NewProductOpportunityPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>('samples');
  const [isFavorite, setIsFavorite] = useState(false);

  const opp = getOpportunity(id || '');

  if (!opp) {
    return (
      <div style={{ maxWidth: 1200, margin: '0 auto', textAlign: 'center', paddingTop: 80 }}>
        <h2 style={{ color: TEXT_3 }}>未找到该机会</h2>
        <button onClick={() => navigate('/hq/market-intel/new-products')} style={{
          padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
          background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700, marginTop: 16,
        }}>返回列表</button>
      </div>
    );
  }

  const statusColors: Record<string, string> = {
    '待评估': YELLOW, '评估中': BLUE, '试点中': BRAND, '已采纳': GREEN, '已否决': TEXT_4,
  };

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'samples', label: '原始样本' },
    { key: 'competitors', label: '关联竞对' },
    { key: 'topics', label: '关联主题' },
    { key: 'pilots', label: '历史试点' },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* 返回按钮 */}
      <button onClick={() => navigate('/hq/market-intel/new-products')} style={{
        background: 'none', border: 'none', color: TEXT_3, cursor: 'pointer',
        fontSize: 13, padding: 0, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 4,
      }}>
        &larr; 返回新品机会列表
      </button>

      {/* 顶部 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16,
        flexWrap: 'wrap', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>{opp.name}</h2>
          <div style={{
            width: 44, height: 44, borderRadius: '50%',
            border: `3px solid ${opp.score >= 80 ? GREEN : opp.score >= 65 ? YELLOW : RED}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16, fontWeight: 700, color: opp.score >= 80 ? GREEN : opp.score >= 65 ? YELLOW : RED,
          }}>{opp.score}</div>
          <span style={{
            fontSize: 12, padding: '3px 10px', borderRadius: 6,
            background: (statusColors[opp.status] || TEXT_4) + '22',
            color: statusColors[opp.status] || TEXT_4, fontWeight: 600,
          }}>{opp.status}</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setIsFavorite(!isFavorite)} style={{
            padding: '8px 16px', borderRadius: 8, border: `1px solid ${BG_2}`, cursor: 'pointer',
            background: isFavorite ? YELLOW + '22' : BG_1, color: isFavorite ? YELLOW : TEXT_3,
            fontSize: 13, fontWeight: 600,
          }}>
            {isFavorite ? '\u2605 已收藏' : '\u2606 收藏'}
          </button>
          <button style={{
            padding: '8px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700,
          }}>
            创建试点
          </button>
        </div>
      </div>

      {/* 评分卡 */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: 18, marginBottom: 16,
        border: `1px solid ${BG_2}`,
      }}>
        <ScoreRadar scores={opp.scores} />
      </div>

      {/* 中部双栏: 机会说明 | 趋势来源 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{
          flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
          border: `1px solid ${BG_2}`,
        }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>机会说明</h3>
          <div style={{ fontSize: 13, color: TEXT_2, lineHeight: 1.8, marginBottom: 14 }}>{opp.summary}</div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, fontWeight: 600 }}>适配场景</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {opp.fitScenarios.map((s, i) => (
                <span key={i} style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 4,
                  background: BLUE + '22', color: BLUE,
                }}>{s}</span>
              ))}
            </div>
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, fontWeight: 600 }}>建议菜型</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {opp.suggestedDishTypes.map((d, i) => (
                <span key={i} style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 4,
                  background: GREEN + '22', color: GREEN,
                }}>{d}</span>
              ))}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, fontWeight: 600 }}>推荐风味</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {opp.recommendedFlavors.map((f, i) => (
                <span key={i} style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 4,
                  background: BRAND + '22', color: BRAND,
                }}>{f}</span>
              ))}
            </div>
          </div>
        </div>

        <div style={{
          flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
          border: `1px solid ${BG_2}`,
        }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>趋势来源</h3>
          {opp.trendSources.map((ts, i) => (
            <div key={i} style={{
              padding: '10px 0',
              borderBottom: i < opp.trendSources.length - 1 ? `1px solid ${BG_2}` : 'none',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <SourceIcon type={ts.type} />
                <span style={{ fontSize: 11, color: TEXT_4 }}>{ts.date}</span>
              </div>
              <div style={{ fontSize: 13, color: TEXT_2, lineHeight: 1.5 }}>{ts.content}</div>
              {ts.metric && (
                <div style={{ fontSize: 11, color: BRAND, marginTop: 2, fontWeight: 600 }}>{ts.metric}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 下部双栏: 适配门店建议 | 试点方案建议 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{
          flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
          border: `1px solid ${BG_2}`,
        }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>适配门店建议</h3>
          {opp.storeMatches.map((store, i) => (
            <div key={i} style={{
              padding: '10px 0',
              borderBottom: i < opp.storeMatches.length - 1 ? `1px solid ${BG_2}` : 'none',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{store.storeName}</span>
                <span style={{
                  fontSize: 14, fontWeight: 700,
                  color: store.matchScore >= 85 ? GREEN : store.matchScore >= 70 ? YELLOW : TEXT_3,
                }}>匹配 {store.matchScore}</span>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {store.reasons.map((r, j) => (
                  <span key={j} style={{
                    fontSize: 10, padding: '2px 6px', borderRadius: 3,
                    background: BG_2, color: TEXT_3,
                  }}>{r}</span>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div style={{
          flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
          border: `1px solid ${BG_2}`,
        }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>试点方案建议</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
            <div style={{ background: BG_2, borderRadius: 8, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: BRAND }}>{opp.pilotPlan.duration}</div>
              <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>建议周期</div>
            </div>
            <div style={{ background: BG_2, borderRadius: 8, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: BLUE }}>{opp.pilotPlan.storeCount}家</div>
              <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>建议门店</div>
            </div>
            <div style={{ background: BG_2, borderRadius: 8, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: RED }}>{(opp.pilotPlan.estimatedCost / 10000).toFixed(1)}万</div>
              <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>预估成本</div>
            </div>
            <div style={{ background: BG_2, borderRadius: 8, padding: 12, textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: GREEN }}>{(opp.pilotPlan.expectedRevenue / 10000).toFixed(1)}万</div>
              <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>预期收入</div>
            </div>
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, fontWeight: 600 }}>目标指标</div>
            {opp.pilotPlan.targetMetrics.map((m, i) => (
              <div key={i} style={{ fontSize: 12, color: TEXT_2, padding: '3px 0', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: GREEN }}>&#10003;</span> {m}
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, fontWeight: 600 }}>建议菜品</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {opp.pilotPlan.suggestedDishes.map((d, i) => (
                <span key={i} style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 4,
                  background: BRAND + '22', color: BRAND,
                }}>{d}</span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 底部Tab切换 */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: 18,
        border: `1px solid ${BG_2}`,
      }}>
        <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
          {tabs.map(t => (
            <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
              padding: '8px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: activeTab === t.key ? BRAND : BG_2,
              color: activeTab === t.key ? '#fff' : TEXT_3,
              fontSize: 13, fontWeight: 600, transition: 'all .15s',
            }}>{t.label}</button>
          ))}
        </div>

        {/* 原始样本 */}
        {activeTab === 'samples' && (
          <div>
            {opp.samples.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 30, color: TEXT_4 }}>暂无原始样本数据</div>
            ) : opp.samples.map(s => {
              const sentColors: Record<string, string> = { positive: GREEN, neutral: TEXT_3, negative: RED };
              const sentLabels: Record<string, string> = { positive: '正面', neutral: '中性', negative: '负面' };
              return (
                <div key={s.id} style={{
                  padding: '12px 0',
                  borderBottom: `1px solid ${BG_2}`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: BLUE + '22', color: BLUE, fontWeight: 600,
                    }}>{s.source}</span>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: sentColors[s.sentiment] + '22',
                      color: sentColors[s.sentiment], fontWeight: 600,
                    }}>{sentLabels[s.sentiment]}</span>
                    <span style={{ fontSize: 11, color: TEXT_4 }}>{s.date}</span>
                  </div>
                  <div style={{ fontSize: 13, color: TEXT_2, lineHeight: 1.6 }}>"{s.content}"</div>
                </div>
              );
            })}
          </div>
        )}

        {/* 关联竞对 */}
        {activeTab === 'competitors' && (
          <div>
            {opp.relatedCompetitors.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 30, color: TEXT_4 }}>暂无关联竞对数据</div>
            ) : opp.relatedCompetitors.map((c, i) => {
              const compColors: Record<string, string> = {
                '海底捞': RED, '西贝': BLUE, '太二': GREEN, '费大厨': BRAND, '望湘园': PURPLE,
              };
              return (
                <div key={i} style={{
                  padding: '12px 0',
                  borderBottom: i < opp.relatedCompetitors.length - 1 ? `1px solid ${BG_2}` : 'none',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 4,
                      background: (compColors[c.name] || TEXT_4) + '22',
                      color: compColors[c.name] || TEXT_4, fontWeight: 600,
                    }}>{c.name}</span>
                    <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{c.action}</span>
                    <span style={{ fontSize: 11, color: TEXT_4 }}>{c.date}</span>
                  </div>
                  <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.5 }}>{c.detail}</div>
                </div>
              );
            })}
          </div>
        )}

        {/* 关联主题 */}
        {activeTab === 'topics' && (
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {opp.relatedTopics.map((t, i) => {
              const trendIcons: Record<string, string> = { up: '\u2191', down: '\u2193', stable: '\u2192' };
              const trendColors: Record<string, string> = { up: GREEN, down: RED, stable: TEXT_3 };
              return (
                <div key={i} style={{
                  background: BG_2, borderRadius: 8, padding: '12px 16px', minWidth: 140,
                }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: TEXT_1, marginBottom: 4 }}>{t.keyword}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 12, color: BRAND, fontWeight: 600 }}>热度 {t.heat}</span>
                    <span style={{ fontSize: 14, color: trendColors[t.trend], fontWeight: 700 }}>{trendIcons[t.trend]}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* 历史试点 */}
        {activeTab === 'pilots' && (
          <div>
            {opp.historicalPilots.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 30, color: TEXT_4 }}>暂无历史试点数据</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {['试点名称', '门店', '周期', '结果', '日均销量', '满意度'].map(h => (
                        <th key={h} style={{
                          textAlign: 'left', padding: '8px 12px', fontSize: 12, color: TEXT_3,
                          borderBottom: `1px solid ${BG_2}`, fontWeight: 600,
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {opp.historicalPilots.map((p, i) => {
                      const resultColors: Record<string, string> = { '成功': GREEN, '失败': RED, '进行中': BLUE };
                      return (
                        <tr key={i}>
                          <td style={{ padding: '8px 12px', fontSize: 13, color: TEXT_1, borderBottom: `1px solid ${BG_2}` }}>{p.name}</td>
                          <td style={{ padding: '8px 12px', fontSize: 13, color: TEXT_2, borderBottom: `1px solid ${BG_2}` }}>{p.store}</td>
                          <td style={{ padding: '8px 12px', fontSize: 11, color: TEXT_3, borderBottom: `1px solid ${BG_2}` }}>{p.period}</td>
                          <td style={{ padding: '8px 12px', borderBottom: `1px solid ${BG_2}` }}>
                            <span style={{
                              fontSize: 11, padding: '2px 6px', borderRadius: 4,
                              background: resultColors[p.result] + '22',
                              color: resultColors[p.result], fontWeight: 600,
                            }}>{p.result}</span>
                          </td>
                          <td style={{ padding: '8px 12px', fontSize: 13, color: TEXT_2, fontWeight: 600, borderBottom: `1px solid ${BG_2}` }}>{p.avgDailySales}份</td>
                          <td style={{ padding: '8px 12px', fontSize: 13, color: p.satisfaction >= 80 ? GREEN : YELLOW, fontWeight: 600, borderBottom: `1px solid ${BG_2}` }}>{p.satisfaction}%</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
