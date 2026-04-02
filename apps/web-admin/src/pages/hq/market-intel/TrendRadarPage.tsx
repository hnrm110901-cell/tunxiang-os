/**
 * TrendRadarPage — 趋势雷达
 * 路由: /hq/market-intel/trend-radar
 * 调用 /api/v1/analytics/competitive 获取竞品/趋势数据，降级展示手写 SVG 条形图
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
const PURPLE = '#722ed1';
const CYAN   = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型 ----
type TrendCategory = '菜品' | '原料' | '风味' | '场景' | '全部';
type TrendDirection = 'rising' | 'falling' | 'stable';

interface TrendSignal {
  id: string;
  keyword: string;
  category: TrendCategory;
  score: number;
  direction: TrendDirection;
  changePercent: number;
  sources: string[];
  description: string;
  relatedKeywords: string[];
}

// 来自后端的分析数据形状（竞品分析接口返回降级处理）
interface CompetitiveData {
  analysis?: Record<string, unknown>;
  trends?: TrendSignal[];
  keywords?: Array<{ keyword: string; score: number; direction: string }>;
}

// ---- 默认离线数据（后端无市场趋势专用接口时使用）----
const FALLBACK_SIGNALS: TrendSignal[] = [
  { id: 't01', keyword: '酸汤火锅', category: '菜品', score: 96, direction: 'rising', changePercent: 42, sources: ['小红书', '抖音', '大众点评'], description: '酸汤风味持续爆火，竞对海底捞已跟进推出酸汤系列。', relatedKeywords: ['苗族酸汤', '贵州酸汤', '酸辣鱼'] },
  { id: 't02', keyword: '性价比套餐', category: '场景', score: 93, direction: 'rising', changePercent: 28, sources: ['美团外卖', '大众点评'], description: '消费降级背景下，60元以下聚餐套餐需求激增。', relatedKeywords: ['实惠套餐', '双人餐'] },
  { id: 't03', keyword: '一人食', category: '场景', score: 88, direction: 'rising', changePercent: 35, sources: ['抖音', '美团外卖'], description: '单身经济持续发酵，工作日午餐和晚餐场景需求旺盛。', relatedKeywords: ['独自享用', '迷你套餐'] },
  { id: 't04', keyword: '健康轻食', category: '场景', score: 85, direction: 'rising', changePercent: 22, sources: ['小红书', '微博'], description: '健康饮食意识升级，低油低盐、高蛋白标签对决策影响增强。', relatedKeywords: ['低卡饮食', '减脂餐'] },
  { id: 't05', keyword: '云南米线', category: '菜品', score: 82, direction: 'rising', changePercent: 38, sources: ['抖音', '小红书'], description: '过桥米线在年轻群体中快速爆火，成都多家专营店排队。', relatedKeywords: ['过桥米线', '砂锅米线'] },
  { id: 't06', keyword: '花椒', category: '原料', score: 78, direction: 'rising', changePercent: 18, sources: ['大众点评', '美团外卖'], description: '藤椒、青花椒分别形成独特风味标签，新川菜中用量增加。', relatedKeywords: ['藤椒', '青花椒', '麻辣'] },
  { id: 't07', keyword: '酸笋', category: '原料', score: 74, direction: 'rising', changePercent: 60, sources: ['小红书', '抖音'], description: '酸笋作为酸汤底料核心食材搜索量激增。', relatedKeywords: ['螺蛳粉', '腌制蔬菜'] },
  { id: 't08', keyword: '夜市烧烤', category: '场景', score: 76, direction: 'rising', changePercent: 15, sources: ['微博', '抖音'], description: '夜间经济复苏，室外烧烤需求随春季到来大幅提升。', relatedKeywords: ['露营烧烤', '夜宵经济'] },
  { id: 't09', keyword: '地方小吃', category: '菜品', score: 72, direction: 'stable', changePercent: 5, sources: ['大众点评'], description: '县城特色小吃持续走俏，各省代表性小吃稳定增长。', relatedKeywords: ['老字号', '网红小吃'] },
  { id: 't10', keyword: '低卡椰奶', category: '原料', score: 65, direction: 'rising', changePercent: 25, sources: ['小红书', '抖音'], description: '低脂椰奶作为甜品/饮品基底在健康赛道异军突起。', relatedKeywords: ['植物基', '燕麦奶'] },
  { id: 't11', keyword: '围炉煮茶', category: '场景', score: 52, direction: 'falling', changePercent: -28, sources: ['小红书'], description: '去年爆火的围炉煮茶热度快速衰退，同质化严重。', relatedKeywords: ['新中式茶饮'] },
  { id: 't12', keyword: '预制菜', category: '菜品', score: 48, direction: 'falling', changePercent: -18, sources: ['微博', '大众点评'], description: '预制菜负面舆情持续，消费者对餐厅使用预制菜警惕性升高。', relatedKeywords: ['现炒现做', '手工菜'] },
];

// ---- API ----
async function fetchTrendSignals(): Promise<{ signals: TrendSignal[]; isFallback: boolean }> {
  try {
    const data = await txFetch<CompetitiveData>('/api/v1/analytics/competitive?store_id=hq');
    // 如果后端返回了 trends 字段就用真实数据
    if (data?.trends?.length) {
      return { signals: data.trends, isFallback: false };
    }
    // 如果有 keywords 字段，转换格式
    if (data?.keywords?.length) {
      const signals: TrendSignal[] = data.keywords.map((k, i) => ({
        id: `api-${i}`,
        keyword: k.keyword,
        category: '菜品',
        score: Math.round(k.score),
        direction: (k.direction as TrendDirection) || 'stable',
        changePercent: 0,
        sources: ['数据中台'],
        description: '',
        relatedKeywords: [],
      }));
      return { signals, isFallback: false };
    }
    return { signals: FALLBACK_SIGNALS, isFallback: true };
  } catch {
    return { signals: FALLBACK_SIGNALS, isFallback: true };
  }
}

// ---- 子组件 ----

const DIR_CONFIG: Record<TrendDirection, { symbol: string; color: string; label: string }> = {
  rising:  { symbol: '↑', color: GREEN,  label: '上升' },
  falling: { symbol: '↓', color: RED,    label: '下降' },
  stable:  { symbol: '→', color: TEXT_3, label: '稳定' },
};

const CAT_COLORS: Record<string, string> = {
  '菜品': BRAND, '原料': CYAN, '风味': PURPLE, '场景': BLUE, '全部': TEXT_3,
};

/** 手写 SVG 条形图，展示趋势强度 */
function TrendBarChart({ signals }: { signals: TrendSignal[] }) {
  const top10 = [...signals].sort((a, b) => b.score - a.score).slice(0, 10);
  const maxScore = Math.max(...top10.map((s) => s.score), 100);
  const BAR_WIDTH = 360;
  const ROW_H = 32;
  const svgH = top10.length * ROW_H + 20;

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}`, marginBottom: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>趋势强度排行（Top 10）</div>
      <svg width="100%" viewBox={`0 0 600 ${svgH}`} style={{ display: 'block' }}>
        {top10.map((s, i) => {
          const y = i * ROW_H + 10;
          const barLen = (s.score / maxScore) * BAR_WIDTH;
          const dirCfg = DIR_CONFIG[s.direction];
          const barColor = s.direction === 'falling' ? RED : s.score >= 80 ? GREEN : YELLOW;
          return (
            <g key={s.id}>
              {/* 关键词标签 */}
              <text x={0} y={y + 16} fontSize={12} fill={TEXT_2} fontWeight={s.score >= 80 ? '700' : '400'}>
                {s.keyword}
              </text>
              {/* 背景条 */}
              <rect x={110} y={y + 6} width={BAR_WIDTH} height={14} rx={7} fill={BG_2} />
              {/* 进度条 */}
              <rect x={110} y={y + 6} width={barLen} height={14} rx={7} fill={barColor} opacity={0.85} />
              {/* 分数 */}
              <text x={110 + BAR_WIDTH + 8} y={y + 18} fontSize={11} fill={barColor} fontWeight="700">
                {s.score}
              </text>
              {/* 方向符号 */}
              <text x={110 + BAR_WIDTH + 36} y={y + 18} fontSize={13} fill={dirCfg.color} fontWeight="700">
                {dirCfg.symbol}
              </text>
              {/* 变化幅度 */}
              <text x={110 + BAR_WIDTH + 52} y={y + 18} fontSize={10} fill={dirCfg.color}>
                {s.changePercent > 0 ? '+' : ''}{s.changePercent}%
              </text>
            </g>
          );
        })}
      </svg>
    </div>
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

function SignalRow({ signal, onToggleFav, isFaved }: {
  signal: TrendSignal;
  onToggleFav: (id: string) => void;
  isFaved: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const dir = DIR_CONFIG[signal.direction];
  const catColor = CAT_COLORS[signal.category] || TEXT_3;

  return (
    <div style={{
      background: BG_1, borderRadius: 8, border: `1px solid ${BG_2}`,
      marginBottom: 8,
    }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', cursor: 'pointer' }}
        onClick={() => setExpanded((e) => !e)}
      >
        {/* 收藏 */}
        <button
          onClick={(e) => { e.stopPropagation(); onToggleFav(signal.id); }}
          style={{
            width: 28, height: 28, borderRadius: 6, border: 'none', cursor: 'pointer',
            background: isFaved ? YELLOW + '22' : 'transparent',
            color: isFaved ? YELLOW : TEXT_4, fontSize: 14,
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}
        >{isFaved ? '★' : '☆'}</button>

        {/* 关键词 */}
        <div style={{ minWidth: 110 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: TEXT_1 }}>{signal.keyword}</div>
          <div style={{ display: 'flex', gap: 4, marginTop: 3, flexWrap: 'wrap' }}>
            {signal.sources.map((src) => (
              <span key={src} style={{ fontSize: 9, color: TEXT_3 }}>{src}</span>
            ))}
          </div>
        </div>

        {/* 类别 */}
        <span style={{
          fontSize: 11, padding: '2px 8px', borderRadius: 6, minWidth: 44, textAlign: 'center',
          background: catColor + '22', color: catColor, fontWeight: 600,
        }}>{signal.category}</span>

        {/* 分数 */}
        <div style={{ minWidth: 100 }}>
          <ScoreBar score={signal.score} />
        </div>

        {/* 方向 */}
        <div style={{ minWidth: 80 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: dir.color }}>
            {dir.symbol} {dir.label}
          </span>
          <div style={{ fontSize: 11, color: dir.color }}>
            {signal.changePercent > 0 ? '+' : ''}{signal.changePercent}%
          </div>
        </div>

        <span style={{ marginLeft: 'auto', fontSize: 12, color: TEXT_4 }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {expanded && signal.description && (
        <div style={{ borderTop: `1px solid ${BG_2}`, padding: '12px 16px', background: BG_2 + '88' }}>
          <p style={{ margin: '0 0 8px', fontSize: 12, color: TEXT_2, lineHeight: 1.7 }}>{signal.description}</p>
          {signal.relatedKeywords.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, color: TEXT_4 }}>相关词:</span>
              {signal.relatedKeywords.map((kw) => (
                <span key={kw} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 10,
                  background: BG_2, color: TEXT_3,
                }}>{kw}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function TrendRadarPage() {
  const [signals, setSignals] = useState<TrendSignal[]>([]);
  const [isFallback, setIsFallback] = useState(false);
  const [loading, setLoading] = useState(true);
  const [filterCat, setFilterCat] = useState<TrendCategory>('全部');
  const [filterDir, setFilterDir] = useState<TrendDirection | '全部'>('全部');
  const [sortBy, setSortBy] = useState<'score' | 'change'>('score');
  const [favIds, setFavIds] = useState<Set<string>>(new Set());
  const [showFavOnly, setShowFavOnly] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchTrendSignals().then(({ signals: data, isFallback: fb }) => {
      if (!cancelled) {
        setSignals(data);
        setIsFallback(fb);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);

  const toggleFav = (id: string) => {
    setFavIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const filtered = signals
    .filter((s) => filterCat === '全部' || s.category === filterCat)
    .filter((s) => filterDir === '全部' || s.direction === filterDir)
    .filter((s) => !showFavOnly || favIds.has(s.id))
    .sort((a, b) => sortBy === 'score'
      ? b.score - a.score
      : Math.abs(b.changePercent) - Math.abs(a.changePercent));

  const categories: TrendCategory[] = ['全部', '菜品', '原料', '风味', '场景'];
  const directions: (TrendDirection | '全部')[] = ['全部', 'rising', 'falling', 'stable'];
  const dirLabels: Record<string, string> = {
    '全部': '全部趋势', rising: '↑ 上升中', falling: '↓ 下降中', stable: '→ 稳定',
  };

  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer',
  };

  const risingCount = signals.filter((s) => s.direction === 'rising').length;
  const fallingCount = signals.filter((s) => s.direction === 'falling').length;
  const highScoreCount = signals.filter((s) => s.score >= 80).length;

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG, minHeight: '100%', padding: '0 0 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>趋势雷达</h2>
        <span style={{
          fontSize: 11, padding: '2px 8px', borderRadius: 10,
          background: BRAND + '22', color: BRAND, fontWeight: 600,
        }}>
          {loading ? '加载中...' : `共 ${signals.length} 个趋势信号`}
        </span>
        {isFallback && !loading && (
          <span style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 10,
            background: YELLOW + '22', color: YELLOW, fontWeight: 600,
          }}>参考数据</span>
        )}
        {favIds.size > 0 && (
          <span style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 10,
            background: YELLOW + '22', color: YELLOW, fontWeight: 600,
          }}>★ 已收藏 {favIds.size} 个</span>
        )}
      </div>

      {/* 降级提示 */}
      {isFallback && !loading && (
        <div style={{
          marginBottom: 14, padding: '10px 16px',
          background: BLUE + '11', borderRadius: 8, border: `1px solid ${BLUE}33`,
          fontSize: 12, color: BLUE,
        }}>
          当前展示的是市场参考数据。接入市场情报数据源后将显示实时趋势。
        </div>
      )}

      {/* 统计卡片 */}
      {!loading && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
          {[
            { label: '上升趋势', count: risingCount,   color: GREEN  },
            { label: '下降趋势', count: fallingCount,  color: RED    },
            { label: '高分机会 (≥80)', count: highScoreCount, color: BRAND },
            { label: '收藏关注', count: favIds.size,   color: YELLOW },
          ].map((item) => (
            <div key={item.label} style={{
              background: BG_1, borderRadius: 10, padding: '14px 18px',
              border: `1px solid ${BG_2}`,
            }}>
              <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: item.color }}>{item.count}</div>
            </div>
          ))}
        </div>
      )}

      {/* SVG 条形图 */}
      {!loading && filtered.length > 0 && (
        <TrendBarChart signals={filtered} />
      )}

      {/* 过滤栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16,
        padding: '12px 16px', background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterCat(cat)}
              style={{
                padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: filterCat === cat ? (cat === '全部' ? BRAND : CAT_COLORS[cat] ?? BRAND) : BG_2,
                color: filterCat === cat ? '#fff' : TEXT_3,
                fontSize: 12, fontWeight: 600,
              }}
            >{cat}</button>
          ))}
        </div>
        <div style={{ width: 1, height: 20, background: BG_2 }} />
        <select value={filterDir} onChange={(e) => setFilterDir(e.target.value as TrendDirection | '全部')} style={selectStyle}>
          {directions.map((d) => <option key={d} value={d}>{dirLabels[d]}</option>)}
        </select>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as 'score' | 'change')} style={selectStyle}>
          <option value="score">按趋势分数排序</option>
          <option value="change">按变化幅度排序</option>
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, color: TEXT_2 }}>
          <input
            type="checkbox"
            checked={showFavOnly}
            onChange={(e) => setShowFavOnly(e.target.checked)}
            style={{ accentColor: YELLOW }}
          />
          仅收藏
        </label>
        <span style={{ fontSize: 12, color: TEXT_4, marginLeft: 'auto' }}>
          显示 {filtered.length} / {signals.length} 个
        </span>
      </div>

      {/* 列表表头 */}
      {!loading && filtered.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '6px 16px',
          color: TEXT_4, fontSize: 11, fontWeight: 600,
        }}>
          <span style={{ width: 28 }} />
          <span style={{ minWidth: 110 }}>关键词 / 来源</span>
          <span style={{ minWidth: 44 }}>类别</span>
          <span style={{ minWidth: 100 }}>趋势分数</span>
          <span style={{ minWidth: 80 }}>方向 / 变化</span>
          <span style={{ marginLeft: 'auto' }}>展开详情</span>
        </div>
      )}

      {/* 加载状态 */}
      {loading && (
        <div style={{ padding: '48px 0', textAlign: 'center', color: TEXT_4 }}>加载中...</div>
      )}

      {/* 空状态 */}
      {!loading && filtered.length === 0 && (
        <div style={{ padding: '48px 0', textAlign: 'center', color: TEXT_4 }}>
          暂无匹配的趋势信号
        </div>
      )}

      {/* 信号列表 */}
      {!loading && filtered.map((signal) => (
        <SignalRow
          key={signal.id}
          signal={signal}
          isFaved={favIds.has(signal.id)}
          onToggleFav={toggleFav}
        />
      ))}
    </div>
  );
}
