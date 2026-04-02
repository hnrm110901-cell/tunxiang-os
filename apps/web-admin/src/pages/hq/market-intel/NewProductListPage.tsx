/**
 * NewProductListPage — 新品机会列表
 * 路由: /hq/market-intel/new-products
 * 调用 /api/v1/analytics/new-product-opportunities（降级至竞品分析接口）
 * 机会列表（菜品名/市场热度/竞争度/推荐理由）+ 排序筛选
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
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
type OpportunityStatus = '待评估' | '评估中' | '试点中' | '已采纳' | '已否决';

interface Opportunity {
  id: string;
  name: string;
  score: number;
  status: OpportunityStatus;
  category: string;
  source: string;
  heatScore: number;       // 市场热度 0-100
  competitionScore: number; // 竞争度 0-100（越高越激烈）
  brandFit: number;        // 品牌契合度
  costFeasibility: number; // 成本可行性
  date: string;
  tags: string[];
  reason: string;          // 推荐理由
}

interface ApiOpportunityData {
  opportunities?: ApiOpportunityRow[];
  items?: ApiOpportunityRow[];
  total?: number;
}

interface ApiOpportunityRow {
  opportunity_id?: string;
  dish_name?: string;
  name?: string;
  score?: number;
  heat_score?: number;
  competition_score?: number;
  brand_fit?: number;
  cost_feasibility?: number;
  category?: string;
  source?: string;
  status?: string;
  date?: string;
  tags?: string[];
  reason?: string;
}

// ---- 默认离线数据 ----
const FALLBACK_OPPORTUNITIES: Opportunity[] = [
  { id: 'opp-1', name: '酸汤火锅', score: 87, status: '待评估', category: '汤锅', source: '市场趋势+竞对', heatScore: 95, competitionScore: 72, brandFit: 78, costFeasibility: 75, date: '2026-03-26', tags: ['高热度', '竞对在做'], reason: '酸汤品类搜索热度持续攀升，海底捞已跟进，建议优先启动防御性开发' },
  { id: 'opp-2', name: '一人食精品套餐', score: 82, status: '评估中', category: '套餐', source: '需求趋势', heatScore: 88, competitionScore: 45, brandFit: 85, costFeasibility: 82, date: '2026-03-25', tags: ['需求增长', '低成本'], reason: '单身经济发酵，午间一人食需求稳步增长35%，竞争度较低，契合品牌' },
  { id: 'opp-3', name: '低脂健康套餐', score: 79, status: '待评估', category: '健康餐', source: '社媒趋势', heatScore: 85, competitionScore: 52, brandFit: 72, costFeasibility: 80, date: '2026-03-24', tags: ['健康趋势'], reason: '健康轻食搜索增28%，消费者对低油低盐菜品接受度提升，符合长期趋势' },
  { id: 'opp-4', name: '酸笋系列配菜', score: 75, status: '试点中', category: '配菜', source: '原料发现', heatScore: 70, competitionScore: 28, brandFit: 80, costFeasibility: 78, date: '2026-03-23', tags: ['新原料', '试点中'], reason: '云南酸笋搜索量+60%，供应稳定，作为酸汤配菜可实现差异化' },
  { id: 'opp-5', name: '外卖专属套餐', score: 80, status: '评估中', category: '套餐', source: '竞对分析', heatScore: 82, competitionScore: 68, brandFit: 78, costFeasibility: 88, date: '2026-03-21', tags: ['防御策略', '外卖'], reason: '费大厨39.9元外卖套餐抢占午市，需推出有竞争力的外卖专属定价' },
  { id: 'opp-6', name: '春季时令菜品', score: 73, status: '已采纳', category: '时令', source: '节气策略', heatScore: 65, competitionScore: 35, brandFit: 82, costFeasibility: 85, date: '2026-03-22', tags: ['节气限定'], reason: '清明前后春笋、香椿等时令食材上市，推出季节限定可提升品牌调性' },
  { id: 'opp-7', name: '辣度分级体系', score: 77, status: '已采纳', category: '产品优化', source: '顾客反馈', heatScore: 68, competitionScore: 22, brandFit: 90, costFeasibility: 92, date: '2026-03-17', tags: ['体验优化', '低成本'], reason: '菜品偏咸/偏辣差评占比18%上升，辣度分级可有效降低负面反馈' },
  { id: 'opp-8', name: '儿童友好餐', score: 68, status: '待评估', category: '亲子', source: '需求洞察', heatScore: 55, competitionScore: 38, brandFit: 75, costFeasibility: 72, date: '2026-03-20', tags: ['家庭客群'], reason: '周末家庭客群占比提升，儿童友好餐可提高家庭聚餐场景吸引力' },
  { id: 'opp-9', name: '预制菜到家系列', score: 72, status: '评估中', category: '预制菜', source: '渠道拓展', heatScore: 75, competitionScore: 78, brandFit: 65, costFeasibility: 70, date: '2026-03-18', tags: ['新渠道', '风险'], reason: '到家渠道增长潜力大，但需谨慎处理品牌形象风险，建议以试点形式推进' },
  { id: 'opp-10', name: '下午茶甜品', score: 58, status: '已否决', category: '甜品', source: '社媒趋势', heatScore: 48, competitionScore: 85, brandFit: 45, costFeasibility: 68, date: '2026-03-19', tags: ['品牌偏离'], reason: '甜品赛道竞争激烈，与湘菜品牌定位偏差较大，暂不建议进入' },
];

// ---- API ----
async function fetchNewProductOpportunities(): Promise<{ items: Opportunity[]; isFallback: boolean }> {
  try {
    const data = await txFetch<ApiOpportunityData>(
      '/api/v1/analytics/new-product-opportunities'
    );
    const rows = data?.opportunities || data?.items || [];
    if (rows.length) {
      const items: Opportunity[] = rows.map((r, i) => ({
        id: r.opportunity_id || `api-${i}`,
        name: r.dish_name || r.name || '未知',
        score: r.score ?? 50,
        status: (r.status as OpportunityStatus) || '待评估',
        category: r.category || '其他',
        source: r.source || '数据中台',
        heatScore: r.heat_score ?? 50,
        competitionScore: r.competition_score ?? 50,
        brandFit: r.brand_fit ?? 50,
        costFeasibility: r.cost_feasibility ?? 50,
        date: r.date || new Date().toISOString().slice(0, 10),
        tags: r.tags || [],
        reason: r.reason || '',
      }));
      return { items, isFallback: false };
    }
    return { items: FALLBACK_OPPORTUNITIES, isFallback: true };
  } catch {
    return { items: FALLBACK_OPPORTUNITIES, isFallback: true };
  }
}

// ---- 子组件 ----

const STATUS_COLORS: Record<OpportunityStatus, string> = {
  '待评估': YELLOW, '评估中': BLUE, '试点中': BRAND, '已采纳': GREEN, '已否决': TEXT_4,
};

function ScoreCircle({ score }: { score: number }) {
  const color = score >= 80 ? GREEN : score >= 65 ? YELLOW : RED;
  return (
    <div style={{
      width: 48, height: 48, borderRadius: '50%',
      border: `3px solid ${color}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 16, fontWeight: 700, color, flexShrink: 0,
    }}>{score}</div>
  );
}

function DimBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ flex: 1, minWidth: 80 }}>
      <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 3 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <div style={{ flex: 1, height: 4, borderRadius: 2, background: BG_2 }}>
          <div style={{ width: `${value}%`, height: '100%', borderRadius: 2, background: color }} />
        </div>
        <span style={{ fontSize: 10, color: TEXT_4, minWidth: 20 }}>{value}</span>
      </div>
    </div>
  );
}

function OpportunityCard({ opp, onClick }: { opp: Opportunity; onClick: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const sc = STATUS_COLORS[opp.status] || TEXT_4;

  return (
    <div
      style={{
        background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
        marginBottom: 8, overflow: 'hidden',
      }}
    >
      {/* 主行 */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px', cursor: 'pointer' }}
        onClick={() => setExpanded((e) => !e)}
      >
        <ScoreCircle score={opp.score} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{opp.name}</span>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: sc + '22', color: sc, fontWeight: 600,
            }}>{opp.status}</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>{opp.category}</span>
          </div>

          {/* 四维度指标 */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <DimBar label="市场热度" value={opp.heatScore} color={BRAND} />
            <DimBar label="竞争激烈度" value={opp.competitionScore} color={RED} />
            <DimBar label="品牌契合" value={opp.brandFit} color={BLUE} />
            <DimBar label="成本可行" value={opp.costFeasibility} color={GREEN} />
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
          <span style={{ fontSize: 11, color: TEXT_4 }}>{opp.date}</span>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {opp.tags.map((tag, i) => (
              <span key={i} style={{
                fontSize: 10, padding: '1px 5px', borderRadius: 3,
                background: BG_2, color: TEXT_3,
              }}>{tag}</span>
            ))}
          </div>
          <span style={{ fontSize: 11, color: TEXT_4 }}>{opp.source}</span>
        </div>

        <span style={{ fontSize: 12, color: TEXT_4, marginLeft: 8 }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {/* 展开：推荐理由 + 操作 */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${BG_2}`, padding: '12px 18px', background: BG_2 + '88' }}>
          {opp.reason && (
            <div style={{
              fontSize: 12, color: TEXT_2, lineHeight: 1.7, marginBottom: 12,
              padding: '8px 12px', background: BG_1, borderRadius: 6,
              borderLeft: `3px solid ${BRAND}44`,
            }}>
              <span style={{ fontSize: 11, color: BRAND, fontWeight: 600 }}>推荐理由: </span>
              {opp.reason}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={(e) => { e.stopPropagation(); onClick(); }}
              style={{
                padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: BRAND, color: '#fff', fontSize: 12, fontWeight: 600,
              }}
            >查看详情</button>
            {opp.status === '待评估' && (
              <button
                onClick={(e) => e.stopPropagation()}
                style={{
                  padding: '6px 14px', borderRadius: 6,
                  border: `1px solid ${BLUE}44`, cursor: 'pointer',
                  background: BLUE + '11', color: BLUE, fontSize: 12, fontWeight: 600,
                }}
              >启动评估</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function NewProductListPage() {
  const navigate = useNavigate();
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [isFallback, setIsFallback] = useState(false);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('全部');
  const [sortBy, setSortBy] = useState<'score' | 'date' | 'heat' | 'competition'>('score');
  const [searchKw, setSearchKw] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchNewProductOpportunities().then(({ items, isFallback: fb }) => {
      if (!cancelled) {
        setOpportunities(items);
        setIsFallback(fb);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);

  const statuses = ['全部', '待评估', '评估中', '试点中', '已采纳', '已否决'];

  const filtered = opportunities
    .filter((o) => statusFilter === '全部' || o.status === statusFilter)
    .filter((o) => !searchKw || o.name.includes(searchKw) || o.category.includes(searchKw))
    .sort((a, b) => {
      if (sortBy === 'score') return b.score - a.score;
      if (sortBy === 'heat') return b.heatScore - a.heatScore;
      if (sortBy === 'competition') return a.competitionScore - b.competitionScore; // 竞争低的排前
      return b.date.localeCompare(a.date);
    });

  const statusCounts = statuses.reduce((acc, s) => {
    acc[s] = s === '全部'
      ? opportunities.length
      : opportunities.filter((o) => o.status === s).length;
    return acc;
  }, {} as Record<string, number>);

  const avgScore = opportunities.length
    ? Math.round(opportunities.reduce((s, o) => s + o.score, 0) / opportunities.length)
    : 0;
  const highOpps = opportunities.filter((o) => o.score >= 80).length;
  const pendingCount = opportunities.filter((o) => o.status === '待评估').length;

  const sortOptions = [
    { value: 'score', label: '综合评分' },
    { value: 'heat', label: '市场热度' },
    { value: 'competition', label: '竞争低优先' },
    { value: 'date', label: '发现时间' },
  ] as const;

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', background: BG, minHeight: '100%', padding: '0 0 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>新品机会列表</h2>
          {isFallback && !loading && (
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 10,
              background: YELLOW + '22', color: YELLOW, fontWeight: 600,
            }}>参考数据</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: TEXT_3 }}>排序:</span>
          {sortOptions.map((s) => (
            <button
              key={s.value}
              onClick={() => setSortBy(s.value)}
              style={{
                padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: sortBy === s.value ? BRAND : BG_1,
                color: sortBy === s.value ? '#fff' : TEXT_3,
                fontSize: 11, fontWeight: 600,
              }}
            >{s.label}</button>
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
          当前展示参考数据。接入市场情报数据源后将显示 AI 实时分析的新品机会。
        </div>
      )}

      {/* KPI 汇总 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: '机会总数', value: loading ? '...' : String(opportunities.length), color: TEXT_1 },
          { label: '高分机会 (≥80)', value: loading ? '...' : String(highOpps), color: GREEN },
          { label: '待评估', value: loading ? '...' : String(pendingCount), color: YELLOW },
          { label: '平均评分', value: loading ? '...' : String(avgScore), color: BRAND },
        ].map((kpi) => (
          <div key={kpi.label} style={{
            background: BG_1, borderRadius: 10, padding: '14px 16px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      {/* 状态筛选 + 搜索 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        {statuses.map((s) => {
          const color = STATUS_COLORS[s as OpportunityStatus] || BRAND;
          return (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              style={{
                padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
                background: statusFilter === s ? color + '22' : BG_1,
                color: statusFilter === s ? color : TEXT_3,
                fontSize: 12, fontWeight: 600,
                border: `1px solid ${statusFilter === s ? color + '44' : BG_2}`,
              }}
            >
              {s} ({statusCounts[s]})
            </button>
          );
        })}
        <input
          type="text"
          placeholder="搜索菜品/分类..."
          value={searchKw}
          onChange={(e) => setSearchKw(e.target.value)}
          style={{
            marginLeft: 'auto', background: BG_2, border: `1px solid ${BG_2}`,
            borderRadius: 6, color: TEXT_1, padding: '6px 12px', fontSize: 12,
            outline: 'none', minWidth: 160,
          }}
        />
      </div>

      {/* 加载 */}
      {loading && (
        <div style={{ padding: '48px 0', textAlign: 'center', color: TEXT_4 }}>加载中...</div>
      )}

      {/* 空状态 */}
      {!loading && filtered.length === 0 && (
        <div style={{
          padding: '60px 20px', textAlign: 'center',
          background: BG_1, borderRadius: 10, border: `1px dashed ${BG_2}`,
        }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>🍽️</div>
          <div style={{ fontSize: 15, color: TEXT_3 }}>
            {searchKw ? `未找到"${searchKw}"相关机会` : '暂无新品机会数据'}
          </div>
          <div style={{ fontSize: 12, color: TEXT_4, marginTop: 8 }}>
            AI 将持续分析市场趋势，自动识别新品开发机会
          </div>
        </div>
      )}

      {/* 机会列表 */}
      {!loading && filtered.map((opp) => (
        <OpportunityCard
          key={opp.id}
          opp={opp}
          onClick={() => navigate(`/hq/market-intel/new-products/${opp.id}`)}
        />
      ))}

      {/* 列表底部说明 */}
      {!loading && filtered.length > 0 && (
        <div style={{
          marginTop: 16, padding: '12px 16px',
          background: BG_1, borderRadius: 8, border: `1px solid ${BG_2}`,
          fontSize: 12, color: TEXT_4, lineHeight: 1.7,
        }}>
          评分说明：综合评分 = 市场热度(40%) + 品牌契合度(35%) + 成本可行性(25%)，
          竞争激烈度作为参考维度（竞争低的机会窗口期更长）。
          建议优先推进评分 ≥ 80 且竞争度 &lt; 50 的机会。
        </div>
      )}
    </div>
  );
}
