/**
 * NewProductOpportunityPage — 新品机会详情（真实API版）
 * 路由: /hq/market-intel/new-products/:opportunityId
 * API: GET /api/v1/analytics/new-product-opportunities/{id}
 *      POST /api/v1/orchestrate  (AI深度分析)
 *      POST /api/v1/menu/rd/opportunities  (加入研发计划)
 */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
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
const CYAN = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

type OpportunityStatus = '待评估' | '评估中' | '试点中' | '已采纳' | '已否决';
type TrendDir = 'up' | 'down' | 'stable';

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

interface BomItem {
  ingredient: string;
  amount: string;
  cost_estimate: string;
  note?: string;
}

interface PricingRange {
  low: number;
  mid: number;
  high: number;
  recommended: number;
  competitor_avg?: number;
}

interface RiskItem {
  type: '市场' | '供应链' | '口味' | '运营' | '竞对';
  level: 'high' | 'medium' | 'low';
  description: string;
  mitigation: string;
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
  trend: TrendDir;
}

interface StoreMatch {
  store_name: string;
  match_score: number;
  reasons: string[];
}

interface OpportunityDetail {
  id: string;
  name: string;
  score: number;
  status: OpportunityStatus;
  is_favorite: boolean;
  summary: string;
  fit_scenarios: string[];
  suggested_dish_types: string[];
  recommended_flavors: string[];
  scores: ScoreDimension[];
  trend_sources: TrendSource[];
  store_matches: StoreMatch[];
  related_competitors: RelatedCompetitor[];
  related_topics: RelatedTopic[];
  bom_suggestions: BomItem[];
  pricing_range: PricingRange;
  risks: RiskItem[];
}

interface AiAnalysis {
  summary: string;
  market_demand: string;
  competitor_status: string;
  recommendation: string;
  confidence: number;
  generated_at: string;
}

// ---- 辅助映射 ----

const statusColors: Record<OpportunityStatus, string> = {
  '待评估': TEXT_3, '评估中': BLUE, '试点中': CYAN,
  '已采纳': GREEN, '已否决': RED,
};

const trendIcons: Record<TrendDir, string> = { up: '↑', down: '↓', stable: '→' };
const trendColors: Record<TrendDir, string> = { up: GREEN, down: RED, stable: TEXT_3 };

const riskColors: Record<'high' | 'medium' | 'low', string> = {
  high: RED, medium: YELLOW, low: GREEN,
};

const sourceTypeColors: Record<TrendSource['type'], string> = {
  '竞对': RED, '搜索': BLUE, '评论': YELLOW, '社媒': PURPLE, '行业': CYAN,
};

// ---- 子组件：综合评分雷达（水平条形图） ----

function ScorePanel({ scores }: { scores: ScoreDimension[] }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>综合评分维度</div>
      {scores.map(s => (
        <div key={s.label} style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: TEXT_2 }}>{s.label}</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: s.color }}>{s.score}</span>
          </div>
          <div style={{ height: 6, borderRadius: 3, background: BG_2 }}>
            <div style={{
              width: `${s.score}%`, height: '100%', borderRadius: 3,
              background: s.color, transition: 'width 0.6s ease',
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- 子组件：市场需求分析 ----

function MarketDemandPanel({ sources, topics }: {
  sources: TrendSource[];
  topics: RelatedTopic[];
}) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>市场需求分析</div>
      {sources.map((s, i) => (
        <div key={i} style={{
          display: 'flex', gap: 10, marginBottom: 10, padding: '10px 12px',
          background: BG_2, borderRadius: 8,
        }}>
          <span style={{
            fontSize: 10, padding: '2px 7px', borderRadius: 6, flexShrink: 0,
            background: sourceTypeColors[s.type] + '22',
            color: sourceTypeColors[s.type], fontWeight: 700,
            alignSelf: 'flex-start', marginTop: 1,
          }}>{s.type}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, color: TEXT_1, marginBottom: 2 }}>{s.content}</div>
            {s.metric && (
              <span style={{ fontSize: 11, color: BRAND, fontWeight: 600 }}>{s.metric}</span>
            )}
          </div>
          <span style={{ fontSize: 10, color: TEXT_4, flexShrink: 0, alignSelf: 'flex-end' }}>{s.date}</span>
        </div>
      ))}

      {topics.length > 0 && (
        <>
          <div style={{ fontSize: 12, color: TEXT_3, margin: '14px 0 8px' }}>相关热词</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {topics.map((t, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '4px 10px', borderRadius: 20,
                background: BG_2, border: `1px solid ${BG_2}`,
              }}>
                <span style={{ fontSize: 12, color: TEXT_2 }}>{t.keyword}</span>
                <span style={{
                  fontSize: 11, fontWeight: 700,
                  color: t.heat >= 80 ? RED : t.heat >= 60 ? YELLOW : TEXT_3,
                }}>{t.heat}</span>
                <span style={{ fontSize: 11, color: trendColors[t.trend] }}>{trendIcons[t.trend]}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---- 子组件：竞品现状 ----

function CompetitorStatusPanel({ competitors }: { competitors: RelatedCompetitor[] }) {
  if (!competitors.length) {
    return (
      <div style={{
        background: BG_1, borderRadius: 10, padding: '18px 22px',
        border: `1px solid ${BG_2}`,
      }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 12 }}>竞品现状</div>
        <div style={{ textAlign: 'center', padding: '24px 0', color: TEXT_4, fontSize: 13 }}>
          暂无竞品相关动态
        </div>
      </div>
    );
  }
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>竞品现状</div>
      {competitors.map((c, i) => (
        <div key={i} style={{
          padding: '10px 12px', background: BG_2, borderRadius: 8, marginBottom: 10,
          borderLeft: `3px solid ${RED}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: TEXT_1 }}>{c.name}</span>
            <span style={{ fontSize: 12, color: YELLOW }}>{c.action}</span>
            <span style={{ fontSize: 10, color: TEXT_4, marginLeft: 'auto' }}>{c.date}</span>
          </div>
          <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6 }}>{c.detail}</div>
        </div>
      ))}
    </div>
  );
}

// ---- 子组件：BOM 建议 ----

function BomPanel({ items }: { items: BomItem[] }) {
  if (!items.length) return null;
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>BOM 建议（参考物料清单）</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              {['原料', '用量', '成本估算', '备注'].map(h => (
                <th key={h} style={{
                  textAlign: 'left', padding: '6px 10px',
                  color: TEXT_4, fontWeight: 600, fontSize: 11,
                  borderBottom: `1px solid ${BG_2}`,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '8px 10px', color: TEXT_1, fontWeight: 600 }}>{item.ingredient}</td>
                <td style={{ padding: '8px 10px', color: TEXT_2 }}>{item.amount}</td>
                <td style={{ padding: '8px 10px', color: YELLOW, fontWeight: 600 }}>{item.cost_estimate}</td>
                <td style={{ padding: '8px 10px', color: TEXT_3 }}>{item.note ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- 子组件：定价区间 ----

function PricingPanel({ pricing }: { pricing: PricingRange }) {
  const items = [
    { label: '低端区间', value: pricing.low, color: GREEN },
    { label: '中间区间', value: pricing.mid, color: BLUE },
    { label: '高端区间', value: pricing.high, color: YELLOW },
    { label: '建议定价', value: pricing.recommended, color: BRAND },
    ...(pricing.competitor_avg != null
      ? [{ label: '竞对均价', value: pricing.competitor_avg, color: RED }]
      : []),
  ];

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>定价区间建议</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {items.map(item => (
          <div key={item.label} style={{
            flex: '1 1 100px', background: BG_2, borderRadius: 8, padding: '12px 14px',
            textAlign: 'center', border: item.label === '建议定价' ? `2px solid ${BRAND}` : '2px solid transparent',
          }}>
            <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 6 }}>{item.label}</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: item.color }}>¥{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 子组件：风险评估 ----

function RiskPanel({ risks }: { risks: RiskItem[] }) {
  if (!risks.length) return null;
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>风险评估</div>
      {risks.map((r, i) => (
        <div key={i} style={{
          padding: '10px 12px', background: BG_2, borderRadius: 8,
          marginBottom: 10, borderLeft: `3px solid ${riskColors[r.level]}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 6,
              background: riskColors[r.level] + '22', color: riskColors[r.level], fontWeight: 700,
            }}>{r.type}风险 · {r.level === 'high' ? '高' : r.level === 'medium' ? '中' : '低'}</span>
          </div>
          <div style={{ fontSize: 13, color: TEXT_1, marginBottom: 4 }}>{r.description}</div>
          <div style={{ fontSize: 12, color: TEXT_3 }}>
            <span style={{ color: GREEN, fontWeight: 600 }}>应对：</span>{r.mitigation}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- 子组件：门店适配 ----

function StoreMatchPanel({ matches }: { matches: StoreMatch[] }) {
  if (!matches.length) return null;
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>门店适配分析</div>
      {matches.map((m, i) => (
        <div key={i} style={{
          display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12,
          padding: '10px 12px', background: BG_2, borderRadius: 8,
        }}>
          <div style={{ flexShrink: 0, textAlign: 'center' }}>
            <div style={{
              width: 46, height: 46, borderRadius: '50%', border: `3px solid ${
                m.match_score >= 85 ? GREEN : m.match_score >= 70 ? YELLOW : RED
              }`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14, fontWeight: 800,
              color: m.match_score >= 85 ? GREEN : m.match_score >= 70 ? YELLOW : RED,
            }}>{m.match_score}</div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: TEXT_1, marginBottom: 4 }}>
              {m.store_name}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {m.reasons.map((r, j) => (
                <span key={j} style={{
                  fontSize: 10, padding: '2px 7px', borderRadius: 10,
                  background: BLUE + '22', color: BLUE,
                }}>{r}</span>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- 子组件：AI深度分析面板 ----

function AiAnalysisPanel({
  analysis, loading, onTrigger,
}: {
  analysis: AiAnalysis | null;
  loading: boolean;
  onTrigger: () => void;
}) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '18px 22px',
      border: `1px solid ${BLUE}44`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 6,
          background: BLUE + '22', color: BLUE, fontWeight: 700,
        }}>AI</span>
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>智能深度分析</span>
        <span style={{ flex: 1 }} />
        {!analysis && !loading && (
          <button onClick={onTrigger} style={{
            padding: '6px 14px', borderRadius: 6, border: 'none',
            background: BLUE, color: '#fff', fontSize: 12, cursor: 'pointer',
            fontWeight: 600,
          }}>触发AI分析</button>
        )}
        {loading && (
          <span style={{ fontSize: 12, color: BLUE }}>AI 分析中...</span>
        )}
        {analysis && !loading && (
          <button onClick={onTrigger} style={{
            padding: '5px 12px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: 'transparent', color: TEXT_3, fontSize: 11, cursor: 'pointer',
          }}>重新分析</button>
        )}
      </div>

      {loading && (
        <div style={{
          textAlign: 'center', padding: '32px 0', color: BLUE, fontSize: 13,
          animation: 'pulse 1.5s ease-in-out infinite',
        }}>
          menu_advisor Agent 正在深度分析，通常需要 10-30 秒...
        </div>
      )}

      {!loading && !analysis && (
        <div style={{
          textAlign: 'center', padding: '32px 0',
          color: TEXT_4, fontSize: 13,
        }}>
          点击「触发AI分析」获取 Agent 的深度市场洞察与研发建议
        </div>
      )}

      {!loading && analysis && (
        <div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            marginBottom: 12, padding: '8px 12px',
            background: BG_2, borderRadius: 8,
          }}>
            <span style={{ fontSize: 12, color: TEXT_4 }}>综合置信度</span>
            <div style={{ flex: 1, height: 6, borderRadius: 3, background: BG_0 }}>
              <div style={{
                width: `${analysis.confidence * 100}%`, height: '100%', borderRadius: 3,
                background: analysis.confidence >= 0.8 ? GREEN : analysis.confidence >= 0.6 ? YELLOW : RED,
              }} />
            </div>
            <span style={{ fontSize: 12, fontWeight: 700, color: TEXT_1 }}>
              {(analysis.confidence * 100).toFixed(0)}%
            </span>
          </div>

          {[
            { title: '综合结论', content: analysis.summary, color: BRAND },
            { title: '市场需求判断', content: analysis.market_demand, color: BLUE },
            { title: '竞品格局评估', content: analysis.competitor_status, color: YELLOW },
            { title: '研发建议', content: analysis.recommendation, color: GREEN },
          ].map(sec => (
            <div key={sec.title} style={{ marginBottom: 14 }}>
              <div style={{
                fontSize: 12, color: sec.color, fontWeight: 600, marginBottom: 5,
              }}>{sec.title}</div>
              <div style={{
                fontSize: 13, color: TEXT_2, lineHeight: 1.7,
                padding: '8px 12px', background: BG_2, borderRadius: 8,
              }}>{sec.content}</div>
            </div>
          ))}

          <div style={{ textAlign: 'right', fontSize: 10, color: TEXT_4 }}>
            生成于 {analysis.generated_at}
          </div>
        </div>
      )}
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

export function NewProductOpportunityPage() {
  const { opportunityId } = useParams<{ opportunityId: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<OpportunityDetail | null>(null);

  const [aiLoading, setAiLoading] = useState(false);
  const [aiAnalysis, setAiAnalysis] = useState<AiAnalysis | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  const [addingToRd, setAddingToRd] = useState(false);
  const [rdSuccess, setRdSuccess] = useState(false);

  // 加载机会详情
  useEffect(() => {
    if (!opportunityId) return;
    setLoading(true);
    setError(null);
    txFetchData<OpportunityDetail>(
      `/api/v1/analytics/new-product-opportunities/${encodeURIComponent(opportunityId)}`
    )
      .then(data => { setDetail(data); })
      .catch(err => { setError(err instanceof Error ? err.message : '加载失败'); })
      .finally(() => { setLoading(false); });
  }, [opportunityId]);

  // AI深度分析
  const handleAiAnalysis = async () => {
    if (!opportunityId || aiLoading) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const result = await txFetchData<AiAnalysis>('/api/v1/orchestrate', {
        method: 'POST',
        body: JSON.stringify({
          agent: 'menu_advisor',
          action: 'analyze_opportunity',
          params: { opportunity_id: opportunityId },
        }),
      });
      setAiAnalysis(result);
    } catch (err) {
      setAiError(err instanceof Error ? err.message : 'AI分析失败');
    } finally {
      setAiLoading(false);
    }
  };

  // 加入研发计划
  const handleAddToRd = async () => {
    if (!opportunityId || addingToRd || rdSuccess) return;
    setAddingToRd(true);
    try {
      await txFetchData('/api/v1/menu/rd/opportunities', {
        method: 'POST',
        body: JSON.stringify({ opportunity_id: opportunityId }),
      });
      setRdSuccess(true);
    } catch {
      // 静默失败，保持按钮可重试
    } finally {
      setAddingToRd(false);
    }
  };

  const totalScore = detail?.score ?? 0;
  const scoreColor = totalScore >= 85 ? GREEN : totalScore >= 70 ? YELLOW : RED;

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG_0, minHeight: '100vh', padding: 16 }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
      `}</style>

      {/* 顶部导航 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <button
          onClick={() => navigate('/hq/market-intel/new-products')}
          style={{
            padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: 'transparent', color: TEXT_3, fontSize: 12, cursor: 'pointer',
          }}
        >← 返回新品机会</button>
        <span style={{ color: TEXT_4 }}>/</span>
        <span style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>
          {detail?.name ?? '机会详情'}
        </span>
        {detail && (
          <span style={{
            fontSize: 11, padding: '3px 10px', borderRadius: 10,
            background: statusColors[detail.status] + '22',
            color: statusColors[detail.status], fontWeight: 700,
          }}>{detail.status}</span>
        )}
        <div style={{ flex: 1 }} />
        {/* 加入研发计划按钮 */}
        {!loading && !error && detail && (
          <button
            onClick={handleAddToRd}
            disabled={addingToRd || rdSuccess}
            style={{
              padding: '8px 18px', borderRadius: 8, border: 'none',
              background: rdSuccess ? GREEN : BRAND,
              color: '#fff', fontSize: 13, cursor: addingToRd || rdSuccess ? 'not-allowed' : 'pointer',
              fontWeight: 700, opacity: addingToRd ? 0.7 : 1,
              transition: 'background 0.3s',
            }}
          >
            {rdSuccess ? '✓ 已加入研发计划' : addingToRd ? '提交中...' : '+ 加入研发计划'}
          </button>
        )}
      </div>

      {/* 加载骨架 */}
      {loading && (
        <>
          <SkeletonBlock h={120} />
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            <SkeletonBlock h={200} mb={0} />
            <SkeletonBlock h={200} mb={0} />
          </div>
          <SkeletonBlock h={180} />
          <SkeletonBlock h={160} />
          <SkeletonBlock h={200} />
        </>
      )}

      {/* 降级提示 */}
      {!loading && error && (
        <div style={{
          background: BG_1, borderRadius: 10, padding: '48px 24px',
          border: `1px solid ${BG_2}`, textAlign: 'center',
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🔍</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: TEXT_1, marginBottom: 8 }}>
            该机会数据整理中
          </div>
          <div style={{ fontSize: 13, color: TEXT_3, marginBottom: 20 }}>
            {error}。市场情报 Agent 正在持续分析，稍后再来查看。
          </div>
          <button
            onClick={() => navigate('/hq/market-intel/new-products')}
            style={{
              padding: '8px 20px', borderRadius: 8, border: 'none',
              background: BRAND, color: '#fff', fontSize: 13, cursor: 'pointer',
            }}
          >返回新品机会列表</button>
        </div>
      )}

      {/* 正常内容 */}
      {!loading && !error && detail && (
        <>
          {/* 顶部摘要卡 */}
          <div style={{
            background: BG_1, borderRadius: 10, padding: '18px 22px',
            border: `1px solid ${BG_2}`, borderTop: `3px solid ${scoreColor}`,
            marginBottom: 16,
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
              <div style={{
                width: 60, height: 60, borderRadius: 14, flexShrink: 0,
                background: scoreColor + '22',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexDirection: 'column',
              }}>
                <div style={{ fontSize: 22, fontWeight: 900, color: scoreColor, lineHeight: 1 }}>
                  {totalScore}
                </div>
                <div style={{ fontSize: 9, color: TEXT_4, marginTop: 2 }}>综合评分</div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: TEXT_1, marginBottom: 8 }}>
                  {detail.name}
                </div>
                <div style={{ fontSize: 13, color: TEXT_2, lineHeight: 1.7, marginBottom: 10 }}>
                  {detail.summary}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {detail.fit_scenarios.map(s => (
                    <span key={s} style={{
                      fontSize: 11, padding: '2px 9px', borderRadius: 10,
                      background: CYAN + '18', color: CYAN,
                    }}>{s}</span>
                  ))}
                  {detail.suggested_dish_types.slice(0, 4).map(t => (
                    <span key={t} style={{
                      fontSize: 11, padding: '2px 9px', borderRadius: 10,
                      background: BRAND + '18', color: BRAND,
                    }}>{t}</span>
                  ))}
                  {detail.recommended_flavors.slice(0, 3).map(f => (
                    <span key={f} style={{
                      fontSize: 11, padding: '2px 9px', borderRadius: 10,
                      background: PURPLE + '18', color: PURPLE,
                    }}>{f}</span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* 主体两栏布局 */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, alignItems: 'flex-start' }}>
            {/* 左栏 */}
            <div style={{ flex: 3, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
              <MarketDemandPanel sources={detail.trend_sources} topics={detail.related_topics} />
              <CompetitorStatusPanel competitors={detail.related_competitors} />
              {detail.bom_suggestions?.length > 0 && <BomPanel items={detail.bom_suggestions} />}
            </div>
            {/* 右栏 */}
            <div style={{ flex: 2, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
              <ScorePanel scores={detail.scores} />
              {detail.pricing_range && <PricingPanel pricing={detail.pricing_range} />}
              <StoreMatchPanel matches={detail.store_matches} />
            </div>
          </div>

          {/* 风险评估（全宽） */}
          {detail.risks?.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <RiskPanel risks={detail.risks} />
            </div>
          )}

          {/* AI错误提示 */}
          {aiError && (
            <div style={{
              padding: '10px 14px', borderRadius: 8, marginBottom: 12,
              background: RED + '18', border: `1px solid ${RED}44`,
              fontSize: 12, color: RED,
            }}>
              AI分析失败：{aiError}。请稍后重试。
            </div>
          )}

          {/* AI深度分析（全宽） */}
          <AiAnalysisPanel
            analysis={aiAnalysis}
            loading={aiLoading}
            onTrigger={handleAiAnalysis}
          />
        </>
      )}
    </div>
  );
}
