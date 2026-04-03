/**
 * ReviewTopicPage — 评论话题分析
 * 路由: /hq/market-intel/reviews
 * 调用 /api/v1/analytics/reviews/topics（降级至 /api/v1/analysis/dish/negative-reviews）
 * 话题列表（话题词/频率/情感/门店分布）+ 时间范围筛选 7/30/90 天
 */
import { useState, useEffect } from 'react';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
const BG   = '#0d1e28';
const BG_1 = '#1a2a33';
const BG_2 = '#243442';
const BRAND  = '#ff6b2c';
const GREEN  = '#52c41a';
const RED    = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE   = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型 ----
type DaysRange = 7 | 30 | 90;
type Sentiment = 'positive' | 'neutral' | 'negative';
type SentimentFilter = Sentiment | '全部';

interface TopicItem {
  id: string;
  keyword: string;
  category: string;
  sentiment: Sentiment;
  count: number;
  trend: 'up' | 'down' | 'stable';
  trendPct: number;
  storeDistribution: Array<{ storeName: string; count: number }>;
  sampleReviews: string[];
}

// 后端评论话题接口数据形状（带降级兼容）
interface ApiTopicData {
  topics?: ApiTopicRow[];
  items?: ApiNegReviewRow[];
  total?: number;
}

interface ApiTopicRow {
  topic_id?: string;
  keyword: string;
  category?: string;
  sentiment?: Sentiment;
  count: number;
  trend?: string;
  trend_pct?: number;
  store_distribution?: Array<{ store_name: string; count: number }>;
  sample_reviews?: string[];
}

interface ApiNegReviewRow {
  dish_id: string;
  dish_name: string;
  avg_rating: number;
  review_count: number;
  negative_count: number;
  sample_comments?: string[];
}

// ---- 默认离线数据 ----
const FALLBACK_TOPICS: TopicItem[] = [
  { id: 't1', keyword: '辣椒炒肉', category: '好评', sentiment: 'positive', count: 1256, trend: 'up', trendPct: 15, storeDistribution: [{ storeName: '芙蓉路店', count: 423 }, { storeName: '梅溪湖店', count: 312 }, { storeName: '万达广场店', count: 289 }], sampleReviews: ['辣椒炒肉太好吃了！肉嫩椒香', '来长沙必吃，味道正宗'] },
  { id: 't2', keyword: '等位太久', category: '等待', sentiment: 'negative', count: 645, trend: 'up', trendPct: 22, storeDistribution: [{ storeName: '五一广场店', count: 245 }, { storeName: '万达广场店', count: 156 }, { storeName: '芙蓉路店', count: 98 }], sampleReviews: ['周末等了一个半小时，体验很差', '叫号系统混乱，容易错过'] },
  { id: 't3', keyword: '味道正宗', category: '好评', sentiment: 'positive', count: 1034, trend: 'stable', trendPct: 2, storeDistribution: [{ storeName: '芙蓉路店', count: 345 }, { storeName: '梅溪湖店', count: 278 }], sampleReviews: ['味道很正宗，像妈妈做的家常菜', '湘菜味道到位，辣而不燥'] },
  { id: 't4', keyword: '性价比高', category: '性价比', sentiment: 'positive', count: 789, trend: 'up', trendPct: 12, storeDistribution: [{ storeName: '河西大学城店', count: 256 }, { storeName: '星沙店', count: 198 }], sampleReviews: ['人均60多，吃得很好，超划算', '4个人200块搞定，太值了'] },
  { id: 't5', keyword: '上菜慢', category: '等待', sentiment: 'negative', count: 423, trend: 'down', trendPct: -5, storeDistribution: [{ storeName: '河西大学城店', count: 178 }, { storeName: '开福寺店', count: 134 }], sampleReviews: ['等了40分钟才上第一道菜', '午休时间根本来不及等'] },
  { id: 't6', keyword: '菜品偏咸', category: '差评', sentiment: 'negative', count: 234, trend: 'up', trendPct: 18, storeDistribution: [{ storeName: '全部门店', count: 234 }], sampleReviews: ['辣椒炒肉味道不错但有点太咸了', '希望能调整口味，稍微清淡一点'] },
  { id: 't7', keyword: '酸汤鱼绝了', category: '好评', sentiment: 'positive', count: 267, trend: 'up', trendPct: 120, storeDistribution: [{ storeName: '梅溪湖店', count: 189 }, { storeName: '芙蓉路店', count: 78 }], sampleReviews: ['新出的酸汤鱼太好吃了！汤鲜鱼嫩', '喝了三碗汤，必须推荐'] },
  { id: 't8', keyword: '环境干净', category: '卫生', sentiment: 'positive', count: 567, trend: 'stable', trendPct: 0, storeDistribution: [{ storeName: '梅溪湖店', count: 198 }, { storeName: '芙蓉路店', count: 167 }], sampleReviews: ['环境很干净整洁，很放心', '桌椅干净，整体卫生条件好'] },
  { id: 't9', keyword: '服务热情', category: '服务', sentiment: 'positive', count: 892, trend: 'up', trendPct: 8, storeDistribution: [{ storeName: '芙蓉路店', count: 312 }, { storeName: '梅溪湖店', count: 256 }], sampleReviews: ['服务员很热情，全程笑脸', '主动帮忙推荐菜品，体验很好'] },
  { id: 't10', keyword: '排队叫号混乱', category: '等待', sentiment: 'negative', count: 178, trend: 'up', trendPct: 25, storeDistribution: [{ storeName: '万达广场店', count: 98 }, { storeName: '五一广场店', count: 80 }], sampleReviews: ['叫到我号的时候没听到，又被跳过了', '叫号系统不完善，需要改进'] },
];

// ---- API ----
async function fetchReviewTopics(days: DaysRange): Promise<{ topics: TopicItem[]; isFallback: boolean }> {
  try {
    // 优先调用专用话题接口
    const data = await txFetch<ApiTopicData>(
      `/api/v1/analytics/reviews/topics?days=${days}`
    );
    if (data?.topics?.length) {
      const topics: TopicItem[] = data.topics.map((t, i) => ({
        id: t.topic_id || `t${i}`,
        keyword: t.keyword,
        category: t.category || '话题',
        sentiment: t.sentiment || 'neutral',
        count: t.count,
        trend: (t.trend as 'up' | 'down' | 'stable') || 'stable',
        trendPct: t.trend_pct || 0,
        storeDistribution: (t.store_distribution || []).map((sd) => ({
          storeName: sd.store_name,
          count: sd.count,
        })),
        sampleReviews: t.sample_reviews || [],
      }));
      return { topics, isFallback: false };
    }
    throw new Error('empty');
  } catch {
    // 降级：调用差评菜品接口转换
    try {
      const neg = await txFetch<ApiTopicData>(
        `/api/v1/analysis/dish/negative-reviews?store_id=hq&days=${days}&limit=10`
      );
      if (neg?.items?.length) {
        const topics: TopicItem[] = neg.items.map((r, i) => ({
          id: `neg-${i}`,
          keyword: r.dish_name,
          category: '差评菜品',
          sentiment: 'negative',
          count: r.negative_count,
          trend: 'stable',
          trendPct: 0,
          storeDistribution: [],
          sampleReviews: r.sample_comments || [],
        }));
        return { topics, isFallback: false };
      }
    } catch {
      // 二级降级：使用离线数据
    }
    return { topics: FALLBACK_TOPICS, isFallback: true };
  }
}

// ---- 子组件 ----

const SENT_COLORS: Record<Sentiment, string> = { positive: GREEN, neutral: TEXT_3, negative: RED };
const SENT_LABELS: Record<Sentiment, string> = { positive: '正面', neutral: '中性', negative: '负面' };

function SentimentBadge({ s }: { s: Sentiment }) {
  return (
    <span style={{
      fontSize: 10, padding: '1px 6px', borderRadius: 4,
      background: SENT_COLORS[s] + '22', color: SENT_COLORS[s], fontWeight: 600,
    }}>{SENT_LABELS[s]}</span>
  );
}

function TopicRow({ topic }: { topic: TopicItem }) {
  const [expanded, setExpanded] = useState(false);
  const trendColor = topic.trend === 'up'
    ? (topic.sentiment === 'negative' ? RED : GREEN)
    : topic.trend === 'down' ? GREEN : TEXT_4;

  return (
    <div style={{ background: BG_1, borderRadius: 8, border: `1px solid ${BG_2}`, marginBottom: 8 }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', cursor: 'pointer' }}
        onClick={() => setExpanded((e) => !e)}
      >
        {/* 情感指示条 */}
        <div style={{
          width: 4, height: 40, borderRadius: 2, flexShrink: 0,
          background: SENT_COLORS[topic.sentiment],
        }} />

        {/* 话题词 */}
        <div style={{ minWidth: 120 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: TEXT_1 }}>{topic.keyword}</div>
          <div style={{ fontSize: 10, color: TEXT_4, marginTop: 2 }}>{topic.category}</div>
        </div>

        {/* 情感 */}
        <div style={{ minWidth: 60 }}>
          <SentimentBadge s={topic.sentiment} />
        </div>

        {/* 频率 */}
        <div style={{ minWidth: 80 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{topic.count.toLocaleString()}</div>
          <div style={{ fontSize: 10, color: TEXT_4 }}>次提及</div>
        </div>

        {/* 趋势 */}
        <div style={{ minWidth: 80 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: trendColor }}>
            {topic.trend === 'up' ? '↑ 上升' : topic.trend === 'down' ? '↓ 下降' : '→ 稳定'}
          </span>
          {topic.trendPct !== 0 && (
            <div style={{ fontSize: 11, color: trendColor }}>
              {topic.trendPct > 0 ? '+' : ''}{topic.trendPct}%
            </div>
          )}
        </div>

        {/* 门店分布预览 */}
        <div style={{ flex: 1, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {topic.storeDistribution.slice(0, 3).map((sd) => (
            <span key={sd.storeName} style={{
              fontSize: 10, padding: '2px 6px', borderRadius: 4,
              background: BG_2, color: TEXT_3,
            }}>{sd.storeName} {sd.count}</span>
          ))}
        </div>

        <span style={{ fontSize: 12, color: TEXT_4 }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {expanded && (
        <div style={{ borderTop: `1px solid ${BG_2}`, padding: '12px 16px', background: BG_2 + '88' }}>
          {/* 门店分布详情 */}
          {topic.storeDistribution.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 6 }}>门店分布</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {topic.storeDistribution.map((sd) => {
                  const maxCount = Math.max(...topic.storeDistribution.map((x) => x.count));
                  const pct = Math.round((sd.count / maxCount) * 100);
                  return (
                    <div key={sd.storeName} style={{ minWidth: 120 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_2, marginBottom: 3 }}>
                        <span>{sd.storeName}</span>
                        <span>{sd.count}</span>
                      </div>
                      <div style={{ height: 4, borderRadius: 2, background: BG_2 }}>
                        <div style={{
                          width: `${pct}%`, height: '100%', borderRadius: 2,
                          background: SENT_COLORS[topic.sentiment],
                        }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {/* 样本评论 */}
          {topic.sampleReviews.length > 0 && (
            <div>
              <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 6 }}>代表性评价</div>
              {topic.sampleReviews.slice(0, 2).map((review, i) => (
                <div key={i} style={{
                  fontSize: 12, color: TEXT_2, lineHeight: 1.6,
                  padding: '6px 10px', background: BG_1, borderRadius: 4,
                  borderLeft: `3px solid ${SENT_COLORS[topic.sentiment]}44`,
                  marginBottom: 6, fontStyle: 'italic',
                }}>
                  "{review}"
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryKPI({ label, value, color, sub }: { label: string; value: string; color: string; sub?: string }) {
  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: '14px 16px', border: `1px solid ${BG_2}` }}>
      <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ---- 主页面 ----

export function ReviewTopicPage() {
  const [days, setDays] = useState<DaysRange>(30);
  const [topics, setTopics] = useState<TopicItem[]>([]);
  const [isFallback, setIsFallback] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sentFilter, setSentFilter] = useState<SentimentFilter>('全部');
  const [sortBy, setSortBy] = useState<'count' | 'trend'>('count');
  const [searchKw, setSearchKw] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchReviewTopics(days).then(({ topics: data, isFallback: fb }) => {
      if (!cancelled) {
        setTopics(data);
        setIsFallback(fb);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [days]);

  const filtered = topics
    .filter((t) => sentFilter === '全部' || t.sentiment === sentFilter)
    .filter((t) => !searchKw || t.keyword.includes(searchKw) || t.category.includes(searchKw))
    .sort((a, b) => {
      if (sortBy === 'count') return b.count - a.count;
      return Math.abs(b.trendPct) - Math.abs(a.trendPct);
    });

  const posCount = topics.filter((t) => t.sentiment === 'positive').length;
  const negCount = topics.filter((t) => t.sentiment === 'negative').length;
  const totalMentions = topics.reduce((s, t) => s + t.count, 0);
  const posMentions = topics.filter((t) => t.sentiment === 'positive').reduce((s, t) => s + t.count, 0);
  const posRate = totalMentions > 0 ? ((posMentions / totalMentions) * 100).toFixed(1) : '0';

  const daysOptions: DaysRange[] = [7, 30, 90];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG, minHeight: '100%', padding: '0 0 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>评论话题分析</h2>
        <div style={{ display: 'flex', gap: 6 }}>
          {daysOptions.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              style={{
                padding: '6px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
                background: days === d ? BRAND : BG_1,
                color: days === d ? '#fff' : TEXT_3,
                fontSize: 12, fontWeight: 600,
              }}
            >近 {d} 天</button>
          ))}
        </div>
      </div>

      {/* 降级提示 */}
      {isFallback && !loading && (
        <div style={{
          marginBottom: 14, padding: '10px 16px',
          background: BLUE + '11', borderRadius: 8, border: `1px solid ${BLUE}33`,
          fontSize: 12, color: BLUE,
        }}>
          当前展示参考数据。接入评论数据源后将显示真实顾客评论话题。
        </div>
      )}

      {/* KPI 汇总 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        <SummaryKPI label="话题总数" value={loading ? '...' : String(topics.length)} color={TEXT_1} />
        <SummaryKPI label="正面话题" value={loading ? '...' : String(posCount)} color={GREEN} />
        <SummaryKPI label="负面话题" value={loading ? '...' : String(negCount)} color={RED} />
        <SummaryKPI label="正面占比" value={loading ? '...' : `${posRate}%`} color={GREEN} />
        <SummaryKPI label="总提及次数" value={loading ? '...' : totalMentions.toLocaleString()} color={BRAND} />
      </div>

      {/* 过滤与搜索栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16,
        padding: '12px 16px', background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['全部', 'positive', 'neutral', 'negative'] as SentimentFilter[]).map((s) => {
            const label = s === '全部' ? '全部' : SENT_LABELS[s];
            const color = s === '全部' ? BRAND : SENT_COLORS[s];
            return (
              <button
                key={s}
                onClick={() => setSentFilter(s)}
                style={{
                  padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  background: sentFilter === s ? color + '22' : BG_2,
                  color: sentFilter === s ? color : TEXT_3,
                  fontSize: 12, fontWeight: 600,
                  outline: sentFilter === s ? `1px solid ${color}44` : 'none',
                }}
              >{label}</button>
            );
          })}
        </div>
        <div style={{ width: 1, height: 20, background: BG_2 }} />
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as 'count' | 'trend')}
          style={{
            background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
            color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer',
          }}
        >
          <option value="count">按提及次数排序</option>
          <option value="trend">按趋势变化排序</option>
        </select>
        <input
          type="text"
          placeholder="搜索话题关键词..."
          value={searchKw}
          onChange={(e) => setSearchKw(e.target.value)}
          style={{
            background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
            color: TEXT_1, padding: '6px 12px', fontSize: 13, outline: 'none',
            '::placeholder': { color: TEXT_4 } as React.CSSProperties,
          } as React.CSSProperties}
        />
        <span style={{ fontSize: 12, color: TEXT_4, marginLeft: 'auto' }}>
          {filtered.length} / {topics.length} 个话题
        </span>
      </div>

      {/* 列表表头 */}
      {!loading && filtered.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '6px 16px',
          color: TEXT_4, fontSize: 11, fontWeight: 600,
        }}>
          <span style={{ width: 4, flexShrink: 0 }} />
          <span style={{ minWidth: 120 }}>话题词 / 分类</span>
          <span style={{ minWidth: 60 }}>情感</span>
          <span style={{ minWidth: 80 }}>提及次数</span>
          <span style={{ minWidth: 80 }}>趋势变化</span>
          <span style={{ flex: 1 }}>门店分布</span>
          <span style={{ width: 20 }} />
        </div>
      )}

      {/* 状态 */}
      {loading && (
        <div style={{ padding: '48px 0', textAlign: 'center', color: TEXT_4 }}>加载中...</div>
      )}
      {!loading && filtered.length === 0 && (
        <div style={{ padding: '48px 0', textAlign: 'center', color: TEXT_4 }}>
          {searchKw ? `未找到包含"${searchKw}"的话题` : '暂无话题数据'}
        </div>
      )}

      {/* 话题列表 */}
      {!loading && filtered.map((topic) => (
        <TopicRow key={topic.id} topic={topic} />
      ))}
    </div>
  );
}
