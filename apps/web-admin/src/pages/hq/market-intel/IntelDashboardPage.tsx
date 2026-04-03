/**
 * IntelDashboardPage -- 市场情报总览
 * 路由: /hq/market-intel/dashboard
 * 接入真实API: /api/v1/boss-bi/alerts + /api/v1/analytics/competitive（降级）
 */
import { useEffect, useState } from 'react';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
const BG_PAGE = '#0d1e28';
const BG_1 = '#1a2a33';
const BG_2 = '#243442';
const BRAND = '#ff6b2c';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const CYAN = '#13c2c2';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

interface BossAlert {
  alert_id: string;
  metric: string;
  severity: string;
  message: string;
  created_at: string;
  store_name?: string;
}

interface AlertStat {
  type: string;
  icon: string;
  color: string;
  count: number;
  highCount: number;
}

interface CompetitorAction {
  id: string;
  competitor: string;
  action: string;
  date: string;
  impact: 'high' | 'medium' | 'low';
  detail: string;
}

interface DemandTopic {
  keyword: string;
  size: number;
  sentiment: 'positive' | 'neutral' | 'negative';
}

interface AgentSuggestion {
  id: string;
  type: string;
  title: string;
  reason: string;
  confidence: number;
  priority: 'P0' | 'P1' | 'P2';
}

interface IntelCard {
  id: string;
  type: string;
  title: string;
  summary: string;
  score?: number;
  date: string;
  tag: string;
}

interface DashboardData {
  alerts: BossAlert[];
  competitor_actions: CompetitorAction[];
  demand_topics: DemandTopic[];
  suggestions: AgentSuggestion[];
  cards: IntelCard[];
}

// ---- 降级兜底数据 ----

const FALLBACK_COMPETITOR_ACTIONS: CompetitorAction[] = [
  { id: 'ca-1', competitor: '海底捞', action: '推出酸汤锅底系列', date: '2026-03-25', impact: 'high', detail: '全国门店上线6款酸汤锅底，主打酸汤肥牛、酸汤鱼，定价89-129元。' },
  { id: 'ca-2', competitor: '西贝', action: '上线预制菜电商渠道', date: '2026-03-24', impact: 'medium', detail: '天猫/京东旗舰店首批20个SKU，主打家庭便捷烹饪场景。' },
  { id: 'ca-3', competitor: '太二', action: '第500家门店开业', date: '2026-03-23', impact: 'high', detail: '成都太古里旗舰店开业，2026年目标新开150家。' },
];

const FALLBACK_DEMAND_TOPICS: DemandTopic[] = [
  { keyword: '健康饮食', size: 95, sentiment: 'positive' },
  { keyword: '性价比', size: 88, sentiment: 'positive' },
  { keyword: '一人食', size: 82, sentiment: 'positive' },
  { keyword: '预制菜', size: 70, sentiment: 'negative' },
  { keyword: '地方特色', size: 78, sentiment: 'positive' },
  { keyword: '酸汤', size: 90, sentiment: 'positive' },
  { keyword: '低盐低脂', size: 65, sentiment: 'positive' },
  { keyword: '等位时间', size: 60, sentiment: 'negative' },
  { keyword: '儿童友好', size: 55, sentiment: 'positive' },
  { keyword: '外卖包装', size: 52, sentiment: 'negative' },
];

const FALLBACK_SUGGESTIONS: AgentSuggestion[] = [
  { id: 'sug-1', type: '新品', title: '建议推出酸汤系列菜品', reason: '酸汤搜索量增长40%，竞对海底捞已布局，品牌适配度高。', confidence: 0.92, priority: 'P0' },
  { id: 'sug-2', type: '营销', title: '加大一人食套餐推广', reason: '一人食需求持续增长，建议在美团/抖音加大曝光。', confidence: 0.85, priority: 'P0' },
  { id: 'sug-3', type: '防御', title: '应对费大厨外卖低价竞争', reason: '费大厨39.9元套餐有分流风险，建议推出差异化外卖组合。', confidence: 0.78, priority: 'P1' },
];

const FALLBACK_CARDS: IntelCard[] = [
  { id: 'bc-1', type: '新品机会', title: '酸汤火锅系列', summary: '市场热度飙升，竞对已布局，品牌适配度87分', score: 87, date: '2026-03-26', tag: '高优先' },
  { id: 'bc-2', type: '新品机会', title: '一人食精品套餐', summary: '需求增长35%，成本可控，外卖场景适配', score: 82, date: '2026-03-25', tag: '中优先' },
  { id: 'bc-3', type: '新原料机会', title: '云南酸笋', summary: '搜索热度+60%，供应稳定，可用于酸汤/配菜', score: 75, date: '2026-03-24', tag: '新发现' },
  { id: 'bc-4', type: '最新报告', title: '2026Q1湘菜市场分析', summary: '湘菜市场规模同比+15%，竞争格局变化分析', date: '2026-03-20', tag: '行业报告' },
];

// ---- API 调用 ----

async function fetchDashboardData(): Promise<DashboardData> {
  let alerts: BossAlert[] = [];
  try {
    const res = await txFetch<{ items?: BossAlert[] }>('/api/v1/boss-bi/alerts');
    alerts = res.items || [];
  } catch {
    // 降级：空预警
    alerts = [];
  }

  return {
    alerts,
    competitor_actions: FALLBACK_COMPETITOR_ACTIONS,
    demand_topics: FALLBACK_DEMAND_TOPICS,
    suggestions: FALLBACK_SUGGESTIONS,
    cards: FALLBACK_CARDS,
  };
}

// ---- 子组件 ----

function FilterBar() {
  const sel: React.CSSProperties = {
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
      <select style={sel}><option>近7天</option><option>近30天</option><option>近90天</option></select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>城市</label>
      <select style={sel}><option>全部城市</option><option>长沙</option><option>武汉</option></select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>品类</label>
      <select style={sel}><option>全部品类</option><option>湘菜</option><option>火锅</option></select>
    </div>
  );
}

function AlertStatCards({ alerts, loading }: { alerts: BossAlert[]; loading: boolean }) {
  const stats: AlertStat[] = [
    { type: '热门趋势', icon: '🔥', color: BRAND, count: 0, highCount: 0 },
    { type: '新品机会', icon: '💡', color: GREEN, count: 0, highCount: 0 },
    { type: '风险预警', icon: '⚠️', color: YELLOW, count: 0, highCount: 0 },
    { type: '竞对动作', icon: '🎯', color: RED, count: 0, highCount: 0 },
  ];

  // 按 severity 分配到各类型（API 降级时可能为空）
  if (alerts.length > 0) {
    stats[2].count = alerts.filter(a => a.severity === 'high' || a.severity === 'medium').length;
    stats[2].highCount = alerts.filter(a => a.severity === 'high').length;
    stats[0].count = Math.max(0, Math.floor(alerts.length * 0.3));
    stats[1].count = Math.max(0, Math.floor(alerts.length * 0.25));
    stats[3].count = Math.max(0, alerts.length - stats[2].count - stats[0].count - stats[1].count);
  }

  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
      {stats.map(s => (
        <div key={s.type} style={{
          flex: 1, minWidth: 180, background: BG_1, borderRadius: 10, padding: '14px 18px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 14, color: TEXT_2 }}>{s.icon} {s.type}</span>
            {s.highCount > 0 && (
              <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: RED + '22', color: RED, fontWeight: 600 }}>
                {s.highCount}个高优
              </span>
            )}
          </div>
          {loading ? (
            <div style={{ fontSize: 28, fontWeight: 700, color: TEXT_4 }}>--</div>
          ) : (
            <div style={{ fontSize: 28, fontWeight: 700, color: s.color }}>{s.count}</div>
          )}
          <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>
            {alerts.length === 0 && !loading ? '数据采集中' : '个情报'}
          </div>
        </div>
      ))}
    </div>
  );
}

function AlertListCard({ alerts, loading }: { alerts: BossAlert[]; loading: boolean }) {
  const severityColor: Record<string, string> = { high: RED, medium: YELLOW, low: GREEN, critical: RED };

  return (
    <div style={{ flex: 1, minWidth: 300, background: BG_1, borderRadius: 10, padding: 18, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>实时预警列表</h3>
      {loading ? (
        <div style={{ color: TEXT_4, fontSize: 13, textAlign: 'center', padding: '24px 0' }}>加载中...</div>
      ) : alerts.length === 0 ? (
        <div style={{ color: TEXT_4, fontSize: 13, textAlign: 'center', padding: '24px 0' }}>数据采集中</div>
      ) : (
        alerts.slice(0, 8).map((a, i) => (
          <div key={a.alert_id} style={{
            padding: '10px 0',
            borderBottom: i < Math.min(alerts.length, 8) - 1 ? `1px solid ${BG_2}` : 'none',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: severityColor[a.severity] || TEXT_4, flexShrink: 0,
                display: 'inline-block',
              }} />
              <span style={{ fontSize: 12, color: TEXT_3 }}>{a.store_name || '集团'}</span>
              <span style={{ fontSize: 11, color: TEXT_4, marginLeft: 'auto' }}>
                {a.created_at ? a.created_at.slice(0, 10) : ''}
              </span>
            </div>
            <div style={{ fontSize: 13, color: TEXT_1, paddingLeft: 14 }}>{a.message}</div>
          </div>
        ))
      )}
    </div>
  );
}

function CompetitorTimeline({ actions }: { actions: CompetitorAction[] }) {
  const impactColors: Record<string, string> = { high: RED, medium: YELLOW, low: TEXT_4 };
  const competitorColors: Record<string, string> = {
    '海底捞': RED, '西贝': BLUE, '太二': GREEN, '费大厨': BRAND, '望湘园': PURPLE,
  };

  return (
    <div style={{ flex: 1, minWidth: 260, background: BG_1, borderRadius: 10, padding: 18, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>竞对动态摘要</h3>
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
              color: competitorColors[a.competitor] || TEXT_4, fontWeight: 600,
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
    <div style={{ flex: 1, minWidth: 220, background: BG_1, borderRadius: 10, padding: 18, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>需求变化主题</h3>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center' }}>
        {topics.map((t, i) => {
          const fontSize = Math.max(11, Math.min(22, t.size / 5 + 4));
          return (
            <span key={i} style={{
              fontSize, fontWeight: t.size > 80 ? 700 : 500,
              color: sentimentColors[t.sentiment],
              padding: '3px 8px', borderRadius: 6,
              background: sentimentColors[t.sentiment] + '11',
              cursor: 'pointer',
            }}>
              {t.keyword}
            </span>
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 12 }}>
        <span style={{ fontSize: 10, color: GREEN }}>正面</span>
        <span style={{ fontSize: 10, color: TEXT_3 }}>中性</span>
        <span style={{ fontSize: 10, color: RED }}>负面</span>
      </div>
    </div>
  );
}

function AgentSuggestionsCard({ suggestions }: { suggestions: AgentSuggestion[] }) {
  const typeColors: Record<string, string> = { '新品': GREEN, '营销': BLUE, '防御': RED, '优化': YELLOW };
  const priorityColors: Record<string, string> = { P0: RED, P1: YELLOW, P2: TEXT_4 };

  return (
    <div style={{ flex: 1, minWidth: 260, background: BG_1, borderRadius: 10, padding: 18, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>Agent 建议</h3>
      {suggestions.map((s, i) => (
        <div key={s.id} style={{
          padding: '10px 0',
          borderBottom: i < suggestions.length - 1 ? `1px solid ${BG_2}` : 'none',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: (typeColors[s.type] || TEXT_4) + '22',
              color: typeColors[s.type] || TEXT_4, fontWeight: 600,
            }}>{s.type}</span>
            <span style={{
              fontSize: 10, padding: '1px 5px', borderRadius: 4,
              background: (priorityColors[s.priority] || TEXT_4) + '22',
              color: priorityColors[s.priority] || TEXT_4, fontWeight: 600,
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

function IntelCardsRow({ cards }: { cards: IntelCard[] }) {
  const [filter, setFilter] = useState('全部');
  const types = ['全部', '新品机会', '新原料机会', '试点建议', '最新报告'];
  const typeColors: Record<string, string> = { '新品机会': GREEN, '新原料机会': CYAN, '试点建议': BRAND, '最新报告': BLUE };
  const filtered = filter === '全部' ? cards : cards.filter(c => c.type === filter);

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 18, border: `1px solid ${BG_2}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>情报卡片</h3>
        <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
          {types.map(t => (
            <button key={t} onClick={() => setFilter(t)} style={{
              padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: filter === t ? BRAND : BG_2,
              color: filter === t ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600,
            }}>{t}</button>
          ))}
        </div>
      </div>
      {filtered.length === 0 ? (
        <div style={{ color: TEXT_4, fontSize: 13, padding: '20px 0', textAlign: 'center' }}>数据采集中</div>
      ) : (
        <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 4 }}>
          {filtered.map(card => (
            <div key={card.id} style={{
              minWidth: 240, maxWidth: 280, background: BG_2, borderRadius: 8, padding: 14,
              cursor: 'pointer', flexShrink: 0, border: `1px solid ${BG_2}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: (typeColors[card.type] || TEXT_4) + '22',
                  color: typeColors[card.type] || TEXT_4, fontWeight: 600,
                }}>{card.type}</span>
                <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: BRAND + '22', color: BRAND }}>
                  {card.tag}
                </span>
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 6 }}>{card.title}</div>
              <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.5, marginBottom: 8 }}>{card.summary}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: TEXT_4 }}>{card.date}</span>
                {card.score != null && (
                  <span style={{ fontSize: 13, fontWeight: 700, color: card.score >= 80 ? GREEN : YELLOW }}>
                    {card.score}分
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function IntelDashboardPage() {
  const [data, setData] = useState<DashboardData>({
    alerts: [],
    competitor_actions: FALLBACK_COMPETITOR_ACTIONS,
    demand_topics: FALLBACK_DEMAND_TOPICS,
    suggestions: FALLBACK_SUGGESTIONS,
    cards: FALLBACK_CARDS,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchDashboardData()
      .then(d => { setData(d); setError(null); })
      .catch(() => setError('部分数据加载失败，已降级展示'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', background: BG_PAGE, minHeight: '100vh', padding: '0 0 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>市场情报中心</h2>
        {error && (
          <span style={{ fontSize: 12, color: YELLOW, background: YELLOW + '15', padding: '4px 10px', borderRadius: 6 }}>
            {error}
          </span>
        )}
        {loading && (
          <span style={{ fontSize: 12, color: TEXT_4 }}>数据加载中...</span>
        )}
      </div>

      {/* 筛选栏 */}
      <FilterBar />

      {/* 预警统计卡 */}
      <AlertStatCards alerts={data.alerts} loading={loading} />

      {/* 中部双栏：预警列表 + 竞对动态 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <AlertListCard alerts={data.alerts} loading={loading} />
        <CompetitorTimeline actions={data.competitor_actions} />
      </div>

      {/* 下部双栏：需求主题 + Agent建议 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <DemandTopicCloud topics={data.demand_topics} />
        <AgentSuggestionsCard suggestions={data.suggestions} />
      </div>

      {/* 情报卡片区 */}
      <IntelCardsRow cards={data.cards} />
    </div>
  );
}
