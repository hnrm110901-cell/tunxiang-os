/**
 * CompetitorDetailPage — 竞对详情页（真实API版）
 * 路由: /hq/market-intel/competitors/:competitorId
 * API: GET /api/v1/analytics/competitors/{competitorId}
 */
import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { txFetchData } from '../../../api';

// ---- 颜色常量（深色主题） ----
const BG_0 = '#0d1e28';
const BG_1 = '#1a2a33';
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
  price_range: string;
  store_count: number;
  current_rating: number;
  review_count: number;
  threat_level: ThreatLevel;
  color?: string;
  city: string;
  founded: string;
  tagline: string;
}

interface RatingPoint {
  month: string;
  rating: number;
  review_count: number;
}

interface TopDish {
  rank: number;
  name: string;
  mentions: number;
  sentiment: 'positive' | 'neutral' | 'negative';
  avg_price: number;
  is_signature: boolean;
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

interface PriceComparison {
  category: string;
  competitor_price: number;
  our_price: number;
}

interface CompetitorDetail {
  info: CompetitorInfo;
  rating_trend: RatingPoint[];
  top_dishes: TopDish[];
  activities: ActivityItem[];
  review_themes_positive: ReviewTheme[];
  review_themes_negative: ReviewTheme[];
  price_comparison: PriceComparison[];
}

// ---- 辅助常量 ----
const threatColors: Record<ThreatLevel, string> = { high: RED, medium: YELLOW, low: GREEN };
const threatLabels: Record<ThreatLevel, string> = { high: '高威胁', medium: '中威胁', low: '低威胁' };

// ---- 子组件：基本信息卡片 ----

function InfoCard({ info }: { info: CompetitorInfo }) {
  const accentColor = info.color ?? BRAND;
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`, borderTop: `3px solid ${accentColor}`, marginBottom: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
        <div style={{
          width: 52, height: 52, borderRadius: 12, background: accentColor + '22',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 24, fontWeight: 900, color: accentColor,
        }}>{info.logo}</div>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>{info.name}</div>
          <div style={{ fontSize: 12, color: TEXT_3, marginTop: 2 }}>{info.tagline}</div>
        </div>
        <span style={{
          marginLeft: 'auto', fontSize: 11, padding: '3px 10px', borderRadius: 10,
          background: threatColors[info.threat_level] + '22',
          color: threatColors[info.threat_level], fontWeight: 700,
        }}>{threatLabels[info.threat_level]}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 14 }}>
        {[
          { label: '品类', value: info.category },
          { label: '价格带', value: info.price_range },
          { label: '门店数', value: info.store_count.toLocaleString() + ' 家' },
          {
            label: '当前评分', value: String(info.current_rating),
            color: info.current_rating >= 4.4 ? GREEN : YELLOW,
          },
          { label: '累计评价', value: (info.review_count / 10000).toFixed(0) + ' 万条' },
          { label: '创立', value: info.founded + ' 年' },
        ].map(item => (
          <div key={item.label}>
            <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{
              fontSize: 15, fontWeight: 700,
              color: (item as { color?: string }).color ?? TEXT_1,
            }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 子组件：评分趋势（手写SVG折线） ----

function RatingTrendChart({ data, color }: { data: RatingPoint[]; color: string }) {
  if (!data.length) return null;
  const chartH = 160;
  const minRating = 4.0;
  const maxRating = 5.0;
  const xStep = 80;
  const scale = (v: number) => chartH - ((v - minRating) / (maxRating - minRating)) * (chartH - 24) - 12;
  const points = data.map((d, i) => `${i * xStep + 40},${scale(d.rating)}`).join(' ');
  const totalW = (data.length - 1) * xStep + 80;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>近 6 个月评分趋势</div>
      <svg width="100%" height={chartH + 30} viewBox={`0 0 ${totalW} ${chartH + 30}`} style={{ overflow: 'visible' }}>
        {[4.0, 4.2, 4.4, 4.6, 4.8, 5.0].map(v => (
          <g key={v}>
            <line x1={0} y1={scale(v)} x2={totalW} y2={scale(v)} stroke={BG_2} strokeWidth={1} />
            <text x={2} y={scale(v)} fill={TEXT_4} fontSize={9} dominantBaseline="middle">{v.toFixed(1)}</text>
          </g>
        ))}
        {/* 渐变填充区域 */}
        <defs>
          <linearGradient id="ratingGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <polygon
          fill="url(#ratingGrad)"
          points={`${data.map((d, i) => `${i * xStep + 40},${scale(d.rating)}`).join(' ')} ${(data.length - 1) * xStep + 40},${chartH} 40,${chartH}`}
        />
        <polyline fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" points={points} />
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
              {(d.review_count / 1000).toFixed(0)}k评
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ---- 子组件：价格对比 ----

function PriceComparisonPanel({ data }: { data: PriceComparison[] }) {
  if (!data.length) return null;
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`, marginBottom: 16,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>价格对比</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr)', gap: 12 }}>
        {data.map(item => {
          const diff = item.our_price - item.competitor_price;
          const diffColor = diff > 0 ? RED : diff < 0 ? GREEN : TEXT_3;
          return (
            <div key={item.category} style={{
              background: BG_2, borderRadius: 8, padding: '12px 14px',
            }}>
              <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 8 }}>{item.category}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: TEXT_4 }}>竞对</span>
                <span style={{ fontSize: 14, fontWeight: 700, color: TEXT_1 }}>¥{item.competitor_price}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: TEXT_4 }}>我方</span>
                <span style={{ fontSize: 14, fontWeight: 700, color: TEXT_1 }}>¥{item.our_price}</span>
              </div>
              <div style={{ textAlign: 'right', fontSize: 11, color: diffColor, fontWeight: 600 }}>
                {diff > 0 ? '+' : ''}{diff} 元
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- 子组件：热门菜品（菜品对比） ----

function TopDishesPanel({ dishes }: { dishes: TopDish[] }) {
  const maxMentions = dishes[0]?.mentions ?? 1;
  const sentimentColors: Record<TopDish['sentiment'], string> = {
    positive: GREEN, neutral: TEXT_3, negative: RED,
  };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>热门菜品对比 Top 8</div>
      {dishes.map(dish => (
        <div key={dish.rank} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <span style={{
            width: 22, height: 22, borderRadius: 11, display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700,
            background: dish.rank <= 3 ? BRAND + '22' : BG_2,
            color: dish.rank <= 3 ? BRAND : TEXT_4, flexShrink: 0,
          }}>{dish.rank}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{
                fontSize: 13, color: TEXT_1,
                fontWeight: dish.is_signature ? 700 : 500,
              }}>{dish.name}</span>
              {dish.is_signature && (
                <span style={{
                  fontSize: 9, padding: '1px 5px', borderRadius: 4,
                  background: BRAND + '22', color: BRAND, fontWeight: 600,
                }}>招牌</span>
              )}
              <span style={{ fontSize: 11, color: TEXT_3, marginLeft: 'auto' }}>¥{dish.avg_price}</span>
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

// ---- 子组件：营业动态时间线（近30天） ----

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
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16, gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>近 30 天营业动态</span>
        <span style={{
          fontSize: 10, padding: '2px 7px', borderRadius: 8,
          background: BLUE + '22', color: BLUE,
        }}>动态更新</span>
      </div>
      {activities.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px 0', color: TEXT_4, fontSize: 13 }}>
          暂无近期活动记录
        </div>
      ) : activities.map((a, i) => (
        <div key={a.id} style={{
          position: 'relative', paddingLeft: 24, paddingBottom: 16,
          borderLeft: i < activities.length - 1 ? `2px solid ${BG_2}` : '2px solid transparent',
          marginLeft: 6,
        }}>
          <div style={{
            position: 'absolute', left: -6, top: 3, width: 12, height: 12, borderRadius: '50%',
            background: impactColors[a.impact], border: `2px solid ${BG_0}`,
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

// ---- 子组件：口碑热词 ----

function ReviewThemePanel({
  positive, negative,
}: { positive: ReviewTheme[]; negative: ReviewTheme[] }) {
  const [tab, setTab] = useState<'positive' | 'negative'>('positive');
  const themes = tab === 'positive' ? positive : negative;
  const maxCount = themes[0]?.count ?? 1;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>口碑热词</span>
        <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
          {(['positive', 'negative'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: tab === t ? (t === 'positive' ? GREEN : RED) : BG_2,
              color: tab === t ? '#fff' : TEXT_3, fontSize: 11, fontWeight: 600,
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

// ---- 骨架屏 ----

function SkeletonBlock({ h = 120, mb = 16 }: { h?: number; mb?: number }) {
  return (
    <div style={{
      height: h, borderRadius: 10, background: BG_1,
      marginBottom: mb, border: `1px solid ${BG_2}`,
      animation: 'pulse 1.5s ease-in-out infinite',
    }} />
  );
}

// ---- 主页面 ----

export function CompetitorDetailPage() {
  const { competitorId } = useParams<{ competitorId: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<CompetitorDetail | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async (showRefreshing = false) => {
    if (!competitorId) return;
    try {
      if (showRefreshing) setRefreshing(true);
      else setLoading(true);
      setError(null);
      const data = await txFetchData<CompetitorDetail>(
        `/api/v1/analytics/competitors/${encodeURIComponent(competitorId)}`
      );
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '数据加载失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [competitorId]);

  const accentColor = detail?.info.color ?? BRAND;

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG_0, minHeight: '100vh', padding: 16 }}>
      {/* CSS 动画 */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
      `}</style>

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
        <span style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>
          {detail?.info.name ?? '竞对详情'}
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => loadData(true)}
          disabled={refreshing}
          style={{
            padding: '8px 16px', borderRadius: 8, border: `1px solid ${BG_2}`,
            background: BG_2, color: TEXT_2, fontSize: 12, cursor: refreshing ? 'not-allowed' : 'pointer',
            opacity: refreshing ? 0.6 : 1,
          }}
        >
          {refreshing ? '采集中...' : '立即采集最新数据'}
        </button>
      </div>

      {/* 加载中骨架 */}
      {loading && (
        <>
          <SkeletonBlock h={130} />
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            <SkeletonBlock h={220} mb={0} />
            <SkeletonBlock h={220} mb={0} />
          </div>
          <SkeletonBlock h={200} />
          <div style={{ display: 'flex', gap: 16 }}>
            <SkeletonBlock h={280} mb={0} />
            <SkeletonBlock h={280} mb={0} />
          </div>
        </>
      )}

      {/* 数据收集降级提示 */}
      {!loading && error && (
        <div style={{
          background: BG_1, borderRadius: 10, padding: '48px 24px',
          border: `1px solid ${BG_2}`, textAlign: 'center',
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📡</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: TEXT_1, marginBottom: 8 }}>
            该竞品数据收集中
          </div>
          <div style={{ fontSize: 13, color: TEXT_3, marginBottom: 20 }}>
            {error}。系统正在持续采集竞对数据，通常 24-48 小时内完成首次建档。
          </div>
          <button
            onClick={() => navigate('/hq/market-intel/competitors')}
            style={{
              padding: '8px 20px', borderRadius: 8, border: 'none',
              background: BRAND, color: '#fff', fontSize: 13, cursor: 'pointer',
            }}
          >返回竞对列表</button>
        </div>
      )}

      {/* 正常内容 */}
      {!loading && !error && detail && (
        <>
          {/* 基本信息 */}
          <InfoCard info={detail.info} />

          {/* 价格对比 */}
          {detail.price_comparison?.length > 0 && (
            <PriceComparisonPanel data={detail.price_comparison} />
          )}

          {/* 评分趋势 + 热门菜品对比 */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            {detail.rating_trend?.length > 0 && (
              <RatingTrendChart data={detail.rating_trend} color={accentColor} />
            )}
            {detail.top_dishes?.length > 0 && (
              <TopDishesPanel dishes={detail.top_dishes} />
            )}
          </div>

          {/* 近30天营业动态 + 口碑热词 */}
          <div style={{ display: 'flex', gap: 16 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <ActivityTimeline activities={detail.activities ?? []} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <ReviewThemePanel
                positive={detail.review_themes_positive ?? []}
                negative={detail.review_themes_negative ?? []}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
