/**
 * TrendRadarPage — 趋势雷达页
 * 路由: /hq/market-intel/trend-radar
 * 趋势信号列表（关键词/类别/分数/方向/来源）+ 按类别过滤 + 收藏功能
 */
import { useState } from 'react';

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

type TrendCategory = '菜品' | '原料' | '风味' | '场景';
type TrendDirection = 'rising' | 'falling' | 'stable';
type TrendSource = '小红书' | '抖音' | '大众点评' | '微博' | '美团外卖' | '搜索引擎';

interface TrendSignal {
  id: string;
  keyword: string;
  category: TrendCategory;
  score: number;          // 0-100
  direction: TrendDirection;
  changePercent: number;
  sources: TrendSource[];
  heat7d: number[];       // 近7天热度（7个点）
  lastUpdated: string;
  description: string;
  relatedKeywords: string[];
}

// ---- Mock 数据 ----

const MOCK_SIGNALS: TrendSignal[] = [
  {
    id: 't01', keyword: '酸汤火锅', category: '菜品', score: 96, direction: 'rising', changePercent: 42,
    sources: ['小红书', '抖音', '大众点评'],
    heat7d: [72, 75, 80, 84, 88, 92, 96],
    lastUpdated: '2026-03-31 08:00',
    description: '酸汤风味持续爆火，以苗族酸汤为代表的新式酸汤锅底在全国快速扩散，竞对海底捞已跟进。',
    relatedKeywords: ['苗族酸汤', '贵州酸汤', '酸辣鱼'],
  },
  {
    id: 't02', keyword: '性价比套餐', category: '场景', score: 93, direction: 'rising', changePercent: 28,
    sources: ['美团外卖', '大众点评', '搜索引擎'],
    heat7d: [75, 78, 80, 82, 85, 90, 93],
    lastUpdated: '2026-03-31 08:00',
    description: '消费降级背景下，60元以下的聚餐套餐需求激增，一人食和双人套餐均受益。',
    relatedKeywords: ['实惠套餐', '划算聚餐', '双人餐'],
  },
  {
    id: 't03', keyword: '一人食', category: '场景', score: 88, direction: 'rising', changePercent: 35,
    sources: ['抖音', '小红书', '美团外卖'],
    heat7d: [68, 72, 74, 78, 82, 85, 88],
    lastUpdated: '2026-03-31 08:00',
    description: '单身经济持续发酵，一人食场景在工作日午餐和下班后晚餐需求旺盛。',
    relatedKeywords: ['独自享用', '一个人吃饭', '迷你套餐'],
  },
  {
    id: 't04', keyword: '健康轻食', category: '场景', score: 85, direction: 'rising', changePercent: 22,
    sources: ['小红书', '微博', '搜索引擎'],
    heat7d: [70, 72, 74, 76, 80, 82, 85],
    lastUpdated: '2026-03-31 08:00',
    description: '健康饮食意识升级，低油低盐、高蛋白、全谷物等标签对消费决策影响增强。',
    relatedKeywords: ['低卡饮食', '高蛋白', '全谷物', '减脂餐'],
  },
  {
    id: 't05', keyword: '云南米线', category: '菜品', score: 82, direction: 'rising', changePercent: 38,
    sources: ['抖音', '小红书', '大众点评'],
    heat7d: [55, 60, 64, 70, 74, 78, 82],
    lastUpdated: '2026-03-31 08:00',
    description: '过桥米线和昭通抹芋米线在年轻群体中快速爆火，成都已有多家专营店排队火爆。',
    relatedKeywords: ['过桥米线', '昭通米线', '砂锅米线'],
  },
  {
    id: 't06', keyword: '花椒', category: '原料', score: 78, direction: 'rising', changePercent: 18,
    sources: ['大众点评', '美团外卖', '搜索引擎'],
    heat7d: [62, 64, 66, 70, 72, 76, 78],
    lastUpdated: '2026-03-31 08:00',
    description: '新川菜中花椒用量和品类增加，藤椒、青花椒、红花椒分别形成独特风味标签。',
    relatedKeywords: ['藤椒', '青花椒', '麻辣鲜香'],
  },
  {
    id: 't07', keyword: '夜市烧烤', category: '场景', score: 76, direction: 'rising', changePercent: 15,
    sources: ['微博', '抖音', '大众点评'],
    heat7d: [60, 62, 65, 68, 70, 72, 76],
    lastUpdated: '2026-03-31 08:00',
    description: '夜间经济复苏，室外烧烤摊档和露营烧烤场景需求随春季到来大幅提升。',
    relatedKeywords: ['露营烧烤', '夜市摊', '夜宵经济'],
  },
  {
    id: 't08', keyword: '酸笋', category: '原料', score: 74, direction: 'rising', changePercent: 60,
    sources: ['小红书', '抖音'],
    heat7d: [40, 48, 54, 60, 65, 70, 74],
    lastUpdated: '2026-03-31 08:00',
    description: '酸笋作为酸汤底料核心食材搜索量激增，同时在螺蛳粉、酸鸭脚等南方特色菜中大量使用。',
    relatedKeywords: ['螺蛳粉', '笋干', '腌制蔬菜'],
  },
  {
    id: 't09', keyword: '地方小吃', category: '菜品', score: 72, direction: 'stable', changePercent: 5,
    sources: ['大众点评', '搜索引擎'],
    heat7d: [68, 70, 70, 72, 71, 73, 72],
    lastUpdated: '2026-03-31 08:00',
    description: '县城特色小吃持续走俏，各省代表性小吃（长沙臭豆腐/武汉热干面等）在外省开设连锁稳定增长。',
    relatedKeywords: ['地方特产', '老字号', '网红小吃'],
  },
  {
    id: 't10', keyword: '围炉煮茶', category: '场景', score: 52, direction: 'falling', changePercent: -28,
    sources: ['小红书', '抖音'],
    heat7d: [80, 75, 70, 65, 60, 56, 52],
    lastUpdated: '2026-03-31 08:00',
    description: '去年爆火的围炉煮茶热度快速衰退，市场进入成熟期后新鲜感减弱，同质化严重。',
    relatedKeywords: ['新中式茶饮', '茶艺体验'],
  },
  {
    id: 't11', keyword: '预制菜', category: '菜品', score: 48, direction: 'falling', changePercent: -18,
    sources: ['微博', '搜索引擎', '大众点评'],
    heat7d: [68, 65, 62, 60, 56, 52, 48],
    lastUpdated: '2026-03-31 08:00',
    description: '预制菜负面舆情持续发酵，消费者对餐厅使用预制菜的警惕性升高，标注"现炒"成营销亮点。',
    relatedKeywords: ['料理包', '现炒现做', '手工菜'],
  },
  {
    id: 't12', keyword: '低卡椰奶', category: '原料', score: 65, direction: 'rising', changePercent: 25,
    sources: ['小红书', '抖音'],
    heat7d: [45, 50, 53, 58, 60, 63, 65],
    lastUpdated: '2026-03-31 08:00',
    description: '低脂椰奶作为甜品/饮品基底在健康赛道异军突起，适配东南亚风味和新式甜品开发。',
    relatedKeywords: ['椰汁', '燕麦奶', '植物基'],
  },
];

// ---- 子组件 ----

const directionConfig: Record<TrendDirection, { symbol: string; color: string; label: string }> = {
  rising: { symbol: '↑', color: GREEN, label: '上升' },
  falling: { symbol: '↓', color: RED, label: '下降' },
  stable: { symbol: '→', color: TEXT_3, label: '稳定' },
};

const categoryColors: Record<TrendCategory, string> = {
  '菜品': BRAND, '原料': CYAN, '风味': PURPLE, '场景': BLUE,
};

const sourceColors: Record<TrendSource, string> = {
  '小红书': RED, '抖音': TEXT_1, '大众点评': YELLOW, '微博': BLUE, '美团外卖': BRAND, '搜索引擎': TEXT_3,
};

function SparkLine({ data, color }: { data: number[]; color: string }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 70, h = 28;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * (h - 4) - 2}`).join(' ');
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <polyline fill="none" stroke={color} strokeWidth={1.5} points={pts} />
      {data.map((v, i) => (
        <circle key={i} cx={(i / (data.length - 1)) * w} cy={h - ((v - min) / range) * (h - 4) - 2} r={2} fill={color} />
      ))}
    </svg>
  );
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? GREEN : score >= 60 ? YELLOW : RED;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 60, height: 6, borderRadius: 3, background: BG_2 }}>
        <div style={{ width: `${score}%`, height: '100%', borderRadius: 3, background: color }} />
      </div>
      <span style={{ fontSize: 12, color, fontWeight: 700, minWidth: 24 }}>{score}</span>
    </div>
  );
}

function TrendSignalRow({
  signal,
  isFavorited,
  onToggleFavorite,
  isHighlighted,
}: {
  signal: TrendSignal;
  isFavorited: boolean;
  onToggleFavorite: (id: string) => void;
  isHighlighted: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const dir = directionConfig[signal.direction];

  return (
    <div style={{
      background: isHighlighted ? BRAND + '11' : BG_1,
      borderRadius: 8,
      border: `1px solid ${isHighlighted ? BRAND + '44' : BG_2}`,
      marginBottom: 8,
      transition: 'all .2s',
    }}>
      {/* 主行 */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', cursor: 'pointer' }}
        onClick={() => setExpanded(e => !e)}
      >
        {/* 收藏按钮 */}
        <button
          onClick={e => { e.stopPropagation(); onToggleFavorite(signal.id); }}
          style={{
            width: 28, height: 28, borderRadius: 6, border: 'none', cursor: 'pointer',
            background: isFavorited ? YELLOW + '22' : 'transparent',
            color: isFavorited ? YELLOW : TEXT_4,
            fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}
          title={isFavorited ? '取消收藏' : '收藏关注'}
        >{isFavorited ? '★' : '☆'}</button>

        {/* 关键词 */}
        <div style={{ minWidth: 110 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: TEXT_1 }}>{signal.keyword}</span>
            {isHighlighted && (
              <span style={{
                fontSize: 9, padding: '1px 5px', borderRadius: 4,
                background: BRAND, color: '#fff', fontWeight: 700, animation: 'pulse 1.5s infinite',
              }}>变动</span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 4, marginTop: 3, flexWrap: 'wrap' }}>
            {signal.sources.map(src => (
              <span key={src} style={{ fontSize: 9, color: sourceColors[src], opacity: 0.8 }}>{src}</span>
            ))}
          </div>
        </div>

        {/* 类别 */}
        <span style={{
          fontSize: 11, padding: '2px 8px', borderRadius: 6, minWidth: 44, textAlign: 'center',
          background: categoryColors[signal.category] + '22',
          color: categoryColors[signal.category], fontWeight: 600,
        }}>{signal.category}</span>

        {/* 趋势分数 */}
        <div style={{ minWidth: 100 }}>
          <ScoreBar score={signal.score} />
        </div>

        {/* 方向 */}
        <div style={{ minWidth: 72 }}>
          <span style={{
            fontSize: 13, fontWeight: 700, color: dir.color,
          }}>{dir.symbol} {dir.label}</span>
          <div style={{ fontSize: 11, color: dir.color }}>
            {signal.changePercent > 0 ? '+' : ''}{signal.changePercent}%
          </div>
        </div>

        {/* 7天走势 */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
          <SparkLine data={signal.heat7d} color={dir.color} />
        </div>

        {/* 更新时间 */}
        <span style={{ fontSize: 11, color: TEXT_4, minWidth: 80, textAlign: 'right' }}>
          {signal.lastUpdated.slice(5)}
        </span>

        {/* 展开按钮 */}
        <span style={{ fontSize: 12, color: TEXT_4, marginLeft: 4 }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {/* 展开内容 */}
      {expanded && (
        <div style={{
          borderTop: `1px solid ${BG_2}`, padding: '12px 16px',
          background: BG_2 + '88',
        }}>
          <p style={{ margin: '0 0 8px', fontSize: 12, color: TEXT_2, lineHeight: 1.7 }}>{signal.description}</p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, color: TEXT_4 }}>相关词:</span>
            {signal.relatedKeywords.map(kw => (
              <span key={kw} style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 10,
                background: BG_2, color: TEXT_3,
              }}>{kw}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function TrendRadarPage() {
  const [filterCategory, setFilterCategory] = useState<TrendCategory | '全部'>('全部');
  const [filterDirection, setFilterDirection] = useState<TrendDirection | '全部'>('全部');
  const [sortBy, setSortBy] = useState<'score' | 'change'>('score');
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set(['t01', 't02']));
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false);

  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer',
  };

  const toggleFavorite = (id: string) => {
    setFavoriteIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const filtered = MOCK_SIGNALS
    .filter(s => filterCategory === '全部' || s.category === filterCategory)
    .filter(s => filterDirection === '全部' || s.direction === filterDirection)
    .filter(s => !showFavoritesOnly || favoriteIds.has(s.id))
    .sort((a, b) => sortBy === 'score' ? b.score - a.score : Math.abs(b.changePercent) - Math.abs(a.changePercent));

  // 收藏的趋势若有较大变化则高亮
  const getHighlighted = (signal: TrendSignal) =>
    favoriteIds.has(signal.id) && Math.abs(signal.changePercent) >= 20;

  const categories: (TrendCategory | '全部')[] = ['全部', '菜品', '原料', '风味', '场景'];
  const directions: (TrendDirection | '全部')[] = ['全部', 'rising', 'falling', 'stable'];
  const directionLabels: Record<TrendDirection | '全部', string> = {
    '全部': '全部趋势', rising: '↑ 上升中', falling: '↓ 下降中', stable: '→ 稳定',
  };

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>趋势雷达</h2>
        <span style={{
          fontSize: 11, padding: '2px 8px', borderRadius: 10,
          background: BRAND + '22', color: BRAND, fontWeight: 600,
        }}>共 {MOCK_SIGNALS.length} 个趋势信号</span>
        {favoriteIds.size > 0 && (
          <span style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 10,
            background: YELLOW + '22', color: YELLOW, fontWeight: 600,
          }}>★ 已收藏 {favoriteIds.size} 个</span>
        )}
      </div>

      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: '上升趋势', count: MOCK_SIGNALS.filter(s => s.direction === 'rising').length, color: GREEN },
          { label: '下降趋势', count: MOCK_SIGNALS.filter(s => s.direction === 'falling').length, color: RED },
          { label: '高分机会 (≥80)', count: MOCK_SIGNALS.filter(s => s.score >= 80).length, color: BRAND },
          { label: '收藏关注', count: favoriteIds.size, color: YELLOW },
        ].map(item => (
          <div key={item.label} style={{
            background: BG_1, borderRadius: 10, padding: '14px 18px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: item.color }}>{item.count}</div>
          </div>
        ))}
      </div>

      {/* 过滤栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16,
        padding: '12px 16px', background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
        flexWrap: 'wrap',
      }}>
        {/* 类别筛选 */}
        <div style={{ display: 'flex', gap: 4 }}>
          {categories.map(cat => (
            <button key={cat} onClick={() => setFilterCategory(cat)} style={{
              padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: filterCategory === cat ? (cat === '全部' ? BRAND : categoryColors[cat as TrendCategory] ?? BRAND) : BG_2,
              color: filterCategory === cat ? '#fff' : TEXT_3,
              fontSize: 12, fontWeight: 600,
            }}>{cat}</button>
          ))}
        </div>
        <div style={{ width: 1, height: 20, background: BG_2 }} />
        {/* 方向筛选 */}
        <select value={filterDirection} onChange={e => setFilterDirection(e.target.value as TrendDirection | '全部')} style={selectStyle}>
          {directions.map(d => <option key={d} value={d}>{directionLabels[d]}</option>)}
        </select>
        {/* 排序 */}
        <select value={sortBy} onChange={e => setSortBy(e.target.value as 'score' | 'change')} style={selectStyle}>
          <option value="score">按趋势分数排序</option>
          <option value="change">按变化幅度排序</option>
        </select>
        {/* 仅收藏 */}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, color: TEXT_2 }}>
          <input
            type="checkbox"
            checked={showFavoritesOnly}
            onChange={e => setShowFavoritesOnly(e.target.checked)}
            style={{ accentColor: YELLOW }}
          />
          仅显示收藏
        </label>
        <span style={{ fontSize: 12, color: TEXT_4, marginLeft: 'auto' }}>
          显示 {filtered.length} / {MOCK_SIGNALS.length} 个
        </span>
      </div>

      {/* 列表表头 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '6px 16px',
        color: TEXT_4, fontSize: 11, fontWeight: 600,
      }}>
        <span style={{ width: 28 }} />
        <span style={{ minWidth: 110 }}>关键词 / 来源</span>
        <span style={{ minWidth: 44 }}>类别</span>
        <span style={{ minWidth: 100 }}>趋势分数</span>
        <span style={{ minWidth: 72 }}>方向 / 变化</span>
        <span style={{ flex: 1, textAlign: 'center' }}>7天走势</span>
        <span style={{ minWidth: 80, textAlign: 'right' }}>更新时间</span>
        <span style={{ width: 20 }} />
      </div>

      {/* 信号列表 */}
      {filtered.length === 0 ? (
        <div style={{
          padding: '48px 0', textAlign: 'center',
          color: TEXT_4, fontSize: 14,
        }}>
          暂无匹配的趋势信号
        </div>
      ) : (
        filtered.map(signal => (
          <TrendSignalRow
            key={signal.id}
            signal={signal}
            isFavorited={favoriteIds.has(signal.id)}
            onToggleFavorite={toggleFavorite}
            isHighlighted={getHighlighted(signal)}
          />
        ))
      )}
    </div>
  );
}
