/**
 * CompetitorDetailPage — 竞对详情页
 * 路由: /hq/market-intel/competitors/:competitorId
 * 基本信息 + 评分趋势折线图 + 热门菜品 + 最新活动 + 点评主题标签
 */
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

// ---- 颜色常量（与 CompetitorCenterPage 保持一致） ----
const BG_1 = '#1a2836';
const BG_2 = '#243442';
const BRAND = '#ff6b2c';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

type ThreatLevel = 'high' | 'medium' | 'low';

interface CompetitorInfo {
  id: string;
  name: string;
  logo: string;
  category: string;
  priceRange: string;
  storeCount: number;
  currentRating: number;
  reviewCount: number;
  threatLevel: ThreatLevel;
  color: string;
  city: string;
  founded: string;
  tagline: string;
}

interface RatingPoint {
  month: string;
  rating: number;
  reviewCount: number;
}

interface TopDish {
  rank: number;
  name: string;
  mentions: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  avgPrice: number;
  isSignature: boolean;
}

interface ActivityItem {
  id: string;
  date: string;
  title: string;
  category: '新品' | '促销' | '活动' | '扩张' | '品牌';
  detail: string;
  impact: 'high' | 'medium' | 'low';
}

interface ReviewTheme {
  keyword: string;
  count: number;
  sentiment: 'positive' | 'negative';
}

// ---- Mock 数据 ----

const MOCK_COMPETITORS: Record<string, CompetitorInfo> = {
  'c1': {
    id: 'c1', name: '海底捞', logo: 'H', category: '火锅', priceRange: '¥80-150/人',
    storeCount: 1380, currentRating: 4.5, reviewCount: 2450000, threatLevel: 'high',
    color: RED, city: '全国', founded: '1994',
    tagline: '服务标杆，火锅龙头',
  },
  'c2': {
    id: 'c2', name: '西贝', logo: 'X', category: '西北菜', priceRange: '¥60-130/人',
    storeCount: 420, currentRating: 4.3, reviewCount: 980000, threatLevel: 'medium',
    color: BLUE, city: '全国', founded: '1988',
    tagline: '食材好，自然好',
  },
  'c3': {
    id: 'c3', name: '太二', logo: 'T', category: '酸菜鱼', priceRange: '¥50-90/人',
    storeCount: 500, currentRating: 4.4, reviewCount: 1200000, threatLevel: 'high',
    color: GREEN, city: '全国', founded: '2015',
    tagline: '酸菜鱼领跑者',
  },
  'c4': {
    id: 'c4', name: '费大厨', logo: 'F', category: '湘菜', priceRange: '¥50-100/人',
    storeCount: 180, currentRating: 4.6, reviewCount: 650000, threatLevel: 'high',
    color: BRAND, city: '湖南/北京/上海', founded: '2012',
    tagline: '辣椒炒肉领先者',
  },
  'c5': {
    id: 'c5', name: '望湘园', logo: 'W', category: '湘菜', priceRange: '¥40-80/人',
    storeCount: 220, currentRating: 4.1, reviewCount: 520000, threatLevel: 'medium',
    color: PURPLE, city: '湖南/全国', founded: '1998',
    tagline: '老牌湘菜连锁',
  },
};

const MOCK_RATING_TREND: RatingPoint[] = [
  { month: '2025-10', rating: 4.4, reviewCount: 18200 },
  { month: '2025-11', rating: 4.3, reviewCount: 19500 },
  { month: '2025-12', rating: 4.4, reviewCount: 22800 },
  { month: '2026-01', rating: 4.5, reviewCount: 20100 },
  { month: '2026-02', rating: 4.6, reviewCount: 24600 },
  { month: '2026-03', rating: 4.5, reviewCount: 28400 },
];

const MOCK_TOP_DISHES: TopDish[] = [
  { rank: 1, name: '辣椒炒肉', mentions: 48200, sentiment: 'positive', avgPrice: 58, isSignature: true },
  { rank: 2, name: '毛氏红烧肉', mentions: 35600, sentiment: 'positive', avgPrice: 78, isSignature: true },
  { rank: 3, name: '剁椒鱼头', mentions: 29800, sentiment: 'positive', avgPrice: 98, isSignature: false },
  { rank: 4, name: '农家小炒肉', mentions: 22100, sentiment: 'positive', avgPrice: 48, isSignature: false },
  { rank: 5, name: '手撕鸡', mentions: 18900, sentiment: 'neutral', avgPrice: 68, isSignature: false },
  { rank: 6, name: '一人食套餐', mentions: 15400, sentiment: 'positive', avgPrice: 39.9, isSignature: false },
  { rank: 7, name: '藜蒿炒腊肉', mentions: 12300, sentiment: 'positive', avgPrice: 58, isSignature: false },
  { rank: 8, name: '双椒炒猪耳', mentions: 9800, sentiment: 'neutral', avgPrice: 52, isSignature: false },
];

const MOCK_ACTIVITIES: ActivityItem[] = [
  { id: 'a1', date: '2026-03-25', title: '推出酸汤系列新品', category: '新品', impact: 'high', detail: '上线酸汤肥牛、酸汤鱼两款核心产品，全国门店同步供应，定价89-129元，针对年轻消费群体。' },
  { id: 'a2', date: '2026-03-18', title: '会员日全场8折', category: '促销', impact: 'medium', detail: '银卡及以上会员每月18日享受8折优惠，限堂食，不可叠加其他优惠券使用。' },
  { id: 'a3', date: '2026-03-15', title: '抖音直播带货专场', category: '活动', impact: 'medium', detail: '联合抖音头部美食博主直播卖券，100元代金券售价69元，单场销售额超200万，新增粉丝8.2万。' },
  { id: 'a4', date: '2026-03-10', title: '外卖专属一人食套餐上线', category: '新品', impact: 'high', detail: '美团/饿了么同步上线39.9元一人食套餐，含主菜+米饭+小菜+汤，主打午餐白领场景。' },
  { id: 'a5', date: '2026-03-05', title: '北京第30家门店开业', category: '扩张', impact: 'medium', detail: '北京三里屯旗舰店盛大开业，面积约1200㎡，设有包间8间，预计月流水200万。' },
];

const MOCK_REVIEW_THEMES_POS: ReviewTheme[] = [
  { keyword: '服务好', count: 12840, sentiment: 'positive' },
  { keyword: '食材新鲜', count: 10650, sentiment: 'positive' },
  { keyword: '口味正宗', count: 9320, sentiment: 'positive' },
  { keyword: '辣度合适', count: 7890, sentiment: 'positive' },
  { keyword: '环境好', count: 6540, sentiment: 'positive' },
  { keyword: '性价比高', count: 5820, sentiment: 'positive' },
  { keyword: '分量足', count: 4960, sentiment: 'positive' },
  { keyword: '会再来', count: 4380, sentiment: 'positive' },
  { keyword: '打包方便', count: 3210, sentiment: 'positive' },
  { keyword: '推荐朋友', count: 2980, sentiment: 'positive' },
];

const MOCK_REVIEW_THEMES_NEG: ReviewTheme[] = [
  { keyword: '等位太久', count: 8920, sentiment: 'negative' },
  { keyword: '偏贵', count: 6340, sentiment: 'negative' },
  { keyword: '出餐慢', count: 4780, sentiment: 'negative' },
  { keyword: '停车难', count: 3560, sentiment: 'negative' },
  { keyword: '分量少', count: 2890, sentiment: 'negative' },
  { keyword: '口味变了', count: 2340, sentiment: 'negative' },
  { keyword: '服务一般', count: 1980, sentiment: 'negative' },
  { keyword: '嘈杂', count: 1750, sentiment: 'negative' },
  { keyword: '外卖包装差', count: 1420, sentiment: 'negative' },
  { keyword: '优惠不多', count: 1180, sentiment: 'negative' },
];

// ---- 子组件 ----

const threatColors: Record<ThreatLevel, string> = { high: RED, medium: YELLOW, low: GREEN };
const threatLabels: Record<ThreatLevel, string> = { high: '高威胁', medium: '中威胁', low: '低威胁' };

function InfoCard({ info }: { info: CompetitorInfo }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`, borderTop: `3px solid ${info.color}`, marginBottom: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
        <div style={{
          width: 52, height: 52, borderRadius: 12, background: info.color + '22',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 24, fontWeight: 900, color: info.color,
        }}>{info.logo}</div>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>{info.name}</div>
          <div style={{ fontSize: 12, color: TEXT_3, marginTop: 2 }}>{info.tagline}</div>
        </div>
        <span style={{
          marginLeft: 'auto', fontSize: 11, padding: '3px 10px', borderRadius: 10,
          background: threatColors[info.threatLevel] + '22',
          color: threatColors[info.threatLevel], fontWeight: 700,
        }}>{threatLabels[info.threatLevel]}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 14 }}>
        {[
          { label: '品类', value: info.category },
          { label: '价格带', value: info.priceRange },
          { label: '门店数', value: info.storeCount.toLocaleString() + ' 家' },
          { label: '当前评分', value: String(info.currentRating), color: info.currentRating >= 4.4 ? GREEN : YELLOW },
          { label: '累计评价', value: (info.reviewCount / 10000).toFixed(0) + ' 万条' },
          { label: '创立', value: info.founded + ' 年' },
        ].map(item => (
          <div key={item.label}>
            <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: (item as { color?: string }).color ?? TEXT_1 }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RatingTrendChart({ data, color }: { data: RatingPoint[]; color: string }) {
  const chartH = 160;
  const minRating = 4.0;
  const maxRating = 5.0;
  const scale = (v: number) => chartH - ((v - minRating) / (maxRating - minRating)) * (chartH - 24) - 12;
  const xStep = 80;

  const points = data.map((d, i) => `${i * xStep + 40},${scale(d.rating)}`).join(' ');

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>近 3 个月评分趋势</div>
      <svg width="100%" height={chartH + 30} viewBox={`0 0 ${(data.length - 1) * xStep + 80} ${chartH + 30}`} style={{ overflow: 'visible' }}>
        {/* 网格线 */}
        {[4.0, 4.2, 4.4, 4.6, 4.8, 5.0].map(v => (
          <g key={v}>
            <line x1={0} y1={scale(v)} x2={(data.length - 1) * xStep + 80} y2={scale(v)} stroke={BG_2} strokeWidth={1} />
            <text x={0} y={scale(v)} fill={TEXT_4} fontSize={9} dominantBaseline="middle">{v.toFixed(1)}</text>
          </g>
        ))}
        {/* 折线 */}
        <polyline fill="none" stroke={color} strokeWidth={2.5} points={points} />
        {/* 数据点 */}
        {data.map((d, i) => (
          <g key={i}>
            <circle cx={i * xStep + 40} cy={scale(d.rating)} r={4} fill={color} />
            <text x={i * xStep + 40} y={scale(d.rating) - 10} textAnchor="middle" fill={color} fontSize={10} fontWeight={700}>
              {d.rating}
            </text>
            <text x={i * xStep + 40} y={chartH + 14} textAnchor="middle" fill={TEXT_4} fontSize={10}>
              {d.month.slice(5)}月
            </text>
            <text x={i * xStep + 40} y={chartH + 24} textAnchor="middle" fill={TEXT_4} fontSize={9}>
              {(d.reviewCount / 1000).toFixed(0)}k评
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function TopDishesPanel({ dishes }: { dishes: TopDish[] }) {
  const maxMentions = dishes[0]?.mentions ?? 1;
  const sentimentColors: Record<TopDish['sentiment'], string> = { positive: GREEN, neutral: TEXT_3, negative: RED };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>热门菜品 Top 8</div>
      {dishes.map(dish => (
        <div key={dish.rank} style={{
          display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10,
        }}>
          <span style={{
            width: 22, height: 22, borderRadius: 11, display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700,
            background: dish.rank <= 3 ? BRAND + '22' : BG_2,
            color: dish.rank <= 3 ? BRAND : TEXT_4, flexShrink: 0,
          }}>{dish.rank}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{ fontSize: 13, color: TEXT_1, fontWeight: dish.isSignature ? 700 : 500 }}>{dish.name}</span>
              {dish.isSignature && (
                <span style={{
                  fontSize: 9, padding: '1px 5px', borderRadius: 4,
                  background: BRAND + '22', color: BRAND, fontWeight: 600,
                }}>招牌</span>
              )}
              <span style={{ fontSize: 11, color: TEXT_3, marginLeft: 'auto' }}>¥{dish.avgPrice}</span>
            </div>
            <div style={{ height: 6, borderRadius: 3, background: BG_2 }}>
              <div style={{
                width: `${(dish.mentions / maxMentions) * 100}%`, height: '100%', borderRadius: 3,
                background: sentimentColors[dish.sentiment],
              }} />
            </div>
          </div>
          <span style={{ fontSize: 11, color: TEXT_3, minWidth: 52, textAlign: 'right' }}>
            {(dish.mentions / 10000).toFixed(1)}w次
          </span>
        </div>
      ))}
    </div>
  );
}

function ActivityTimeline({ activities }: { activities: ActivityItem[] }) {
  const catColors: Record<ActivityItem['category'], string> = {
    '新品': GREEN, '促销': YELLOW, '活动': BLUE, '扩张': PURPLE, '品牌': BRAND,
  };
  const impactColors: Record<ActivityItem['impact'], string> = {
    high: RED, medium: YELLOW, low: TEXT_4,
  };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>最新活动动态</div>
      {activities.map((a, i) => (
        <div key={a.id} style={{
          position: 'relative', paddingLeft: 24, paddingBottom: 16,
          borderLeft: i < activities.length - 1 ? `2px solid ${BG_2}` : '2px solid transparent',
          marginLeft: 6,
        }}>
          <div style={{
            position: 'absolute', left: -6, top: 3, width: 12, height: 12, borderRadius: '50%',
            background: impactColors[a.impact], border: `2px solid #0f1923`,
          }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: catColors[a.category] + '22', color: catColors[a.category], fontWeight: 600,
            }}>{a.category}</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>{a.date}</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 4 }}>{a.title}</div>
          <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6 }}>{a.detail}</div>
        </div>
      ))}
    </div>
  );
}

function ReviewThemePanel({ positive, negative }: { positive: ReviewTheme[]; negative: ReviewTheme[] }) {
  const [tab, setTab] = useState<'positive' | 'negative'>('positive');
  const themes = tab === 'positive' ? positive : negative;
  const maxCount = themes[0]?.count ?? 1;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>点评主题标签</span>
        <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
          {(['positive', 'negative'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: tab === t ? (t === 'positive' ? GREEN : RED) : BG_2,
              color: tab === t ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600,
            }}>{t === 'positive' ? '好评 Top10' : '差评 Top10'}</button>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {themes.map((theme, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 11, color: TEXT_4, minWidth: 18, textAlign: 'right' }}>{i + 1}</span>
            <span style={{ fontSize: 13, color: TEXT_2, minWidth: 80 }}>{theme.keyword}</span>
            <div style={{ flex: 1, height: 14, borderRadius: 3, background: BG_2 }}>
              <div style={{
                width: `${(theme.count / maxCount) * 100}%`, height: '100%', borderRadius: 3,
                background: theme.sentiment === 'positive' ? GREEN + '88' : RED + '88',
                display: 'flex', alignItems: 'center', paddingLeft: 6,
              }}>
                {(theme.count / maxCount) > 0.25 && (
                  <span style={{ fontSize: 9, color: '#fff' }}>{(theme.count / 10000).toFixed(1)}w</span>
                )}
              </div>
            </div>
            <span style={{ fontSize: 11, color: TEXT_3, minWidth: 46, textAlign: 'right' }}>
              {(theme.count / 10000).toFixed(1)}w
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function CompetitorDetailPage() {
  const { competitorId } = useParams<{ competitorId: string }>();
  const navigate = useNavigate();

  const info = MOCK_COMPETITORS[competitorId ?? 'c4'] ?? MOCK_COMPETITORS['c4'];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 顶部导航 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <button
          onClick={() => navigate('/hq/market-intel/competitors')}
          style={{
            padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: 'transparent', color: TEXT_3, fontSize: 12, cursor: 'pointer',
          }}
        >← 返回竞对列表</button>
        <span style={{ color: TEXT_4 }}>/</span>
        <span style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>{info.name} · 竞对详情</span>
        <div style={{ flex: 1 }} />
        <button style={{
          padding: '8px 16px', borderRadius: 8, border: `1px solid ${BG_2}`,
          background: BG_2, color: TEXT_2, fontSize: 12, cursor: 'pointer',
        }}>立即采集最新数据</button>
      </div>

      {/* 基本信息卡片 */}
      <InfoCard info={info} />

      {/* 评分趋势 + 热门菜品 */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
        <RatingTrendChart data={MOCK_RATING_TREND} color={info.color} />
        <TopDishesPanel dishes={MOCK_TOP_DISHES} />
      </div>

      {/* 活动动态 + 点评主题 */}
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ActivityTimeline activities={MOCK_ACTIVITIES} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <ReviewThemePanel positive={MOCK_REVIEW_THEMES_POS} negative={MOCK_REVIEW_THEMES_NEG} />
        </div>
      </div>
    </div>
  );
}
