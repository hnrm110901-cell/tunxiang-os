/**
 * GrowthDashboardPage — 增长中心仪表盘（真实API版）
 *
 * API依赖：
 *   GET /api/v1/member/analytics/growth      — 新增/总量/渠道/LTV/平均消费
 *   GET /api/v1/member/analytics/activity    — 月活/活跃率/日趋势
 *   GET /api/v1/member/analytics/repurchase  — 复购率/消费间隔
 *   GET /api/v1/member/rfm/distribution      — RFM五层分布
 *   GET /api/v1/dashboard/summary            — 私域健康/门店排行/Agent决策
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../../../api';
import { useApi } from '../../../hooks/useApi';
import type { JourneyTemplateAttribution, AgentSuggestionDetail, P1Distribution } from '../../../api/growthHubApi';

// ---- 颜色常量（深色主题）----
const BG_0   = '#0d1e28';
const BG_1   = '#1a2a33';
const BG_2   = '#223340';
const BRAND  = '#FF6B35';
const GREEN  = '#0F6E56';
const RED    = '#A32D2D';
const YELLOW = '#BA7517';
const BLUE   = '#185FA5';
const TEAL   = '#13c2c2';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型 ----

type TimeRange = '今日' | '本周' | '本月' | '近30天' | '近90天';
type Brand    = '全部品牌' | '尝在一起' | '最黔线' | '尚宫厨';
type Region   = '全部区域' | '华中区' | '华东区' | '华南区' | '西南区';

interface GrowthData {
  new_members: number;
  new_members_change_pct: number;
  total_members: number;
  avg_spend_fen?: number;       // 人均消费（分）
  ltv_fen?: number;             // 生命周期价值（分）
  channels: { channel: string; count: number; ratio: number }[];
  daily_trend: { date: string; new_members: number }[];
}

interface ActivityData {
  mau: number;
  mau_change_pct: number;
  active_rate: number;
  active_rate_change_pct: number;
  daily_active: { date: string; active: number; active_rate: number }[];
}

interface RepurchaseData {
  repurchase_rate: number;
  repurchase_rate_change_pct: number;
  avg_interval_days: number;
  frequency_bands: { band: string; count: number }[];
}

interface RfmDistribution {
  distribution: { level: string; count: number; ratio: number }[];
  total: number;
}

interface DashboardSummary {
  kpi: {
    revenue_fen: number;
    order_count: number;
    avg_order_fen: number;
    cost_rate: number | null;
  };
  stores: {
    store_id: string;
    store_name: string;
    today_revenue_fen: number;
    today_orders: number;
    status: string;
  }[];
  decisions: {
    id: string;
    agent_id: string;
    action: string;
    decision_type: string;
    confidence: number | null;
    created_at: string | null;
  }[];
}

// ---- 增长中枢V2 类型 ----

interface GrowthDashboardStats {
  profiles: {
    total: number;
    first_order_only: number;
    second_order_done: number;
    stable_repeat: number;
    high_priority_reactivation: number;
    active_repairs: number;
  };
  enrollments: {
    total: number;
    active: number;
    paused: number;
    completed: number;
    observing: number;
  };
  touches_7d: {
    total: number;
    delivered: number;
    opened: number;
    clicked: number;
    attributed: number;
    attributed_revenue_fen: number;
  };
  suggestions_7d: {
    total: number;
    pending_review: number;
    approved: number;
    published: number;
    rejected: number;
  };
  funnel: {
    first_order: number;
    touched: number;
    revisited: number;
    repeat_customer: number;
    stable_repeat: number;
  };
  conversion_rates: {
    second_visit_rate: number;
    touch_open_rate: number;
    touch_attribution_rate: number;
  };
  mechanism_summary?: {
    mechanism_type: string;
    total: number;
    opened: number;
    attributed: number;
    open_rate: number;
    attribution_rate: number;
  }[];
}

// ---- 工具函数 ----

function getDateRange(range: TimeRange): { start_date: string; end_date: string } {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const today = fmt(now);
  const ago = (days: number) => { const d = new Date(now); d.setDate(d.getDate() - days); return fmt(d); };

  if (range === '今日') return { start_date: today, end_date: today };
  if (range === '本周') {
    const day = now.getDay() || 7;
    const d = new Date(now); d.setDate(d.getDate() - day + 1);
    return { start_date: fmt(d), end_date: today };
  }
  if (range === '本月') return { start_date: fmt(new Date(now.getFullYear(), now.getMonth(), 1)), end_date: today };
  if (range === '近30天') return { start_date: ago(29), end_date: today };
  return { start_date: ago(89), end_date: today };
}

const fmtYuan = (fen: number): string => {
  const y = fen / 100;
  return y >= 10000 ? `${(y / 10000).toFixed(1)}万` : `¥${Math.round(y).toLocaleString()}`;
};
const fmtPct = (v: number): string => `${(v * 100).toFixed(1)}%`;

// ---- 通用UI ----

function SectionSkeleton({ height = 160, label = '加载中...' }: { height?: number; label?: string }) {
  return (
    <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: TEXT_4, fontSize: 13 }}>
      {label}
    </div>
  );
}

function SectionError({ msg }: { msg: string }) {
  return (
    <div style={{ padding: '14px 16px', color: '#ff4d4f', fontSize: 12, background: '#ff4d4f11', borderRadius: 6, textAlign: 'center' }}>
      数据加载失败：{msg}
    </div>
  );
}

// ---- 筛选栏 ----

function FilterBar({ brand, setBrand, timeRange, setTimeRange, region, setRegion }: {
  brand: Brand; setBrand: (v: Brand) => void;
  timeRange: TimeRange; setTimeRange: (v: TimeRange) => void;
  region: Region; setRegion: (v: Region) => void;
}) {
  const sel: React.CSSProperties = {
    background: BG_0, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer', minWidth: 100,
  };
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', flexWrap: 'wrap',
      background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`, marginBottom: 16,
    }}>
      <span style={{ fontSize: 13, color: TEXT_3, fontWeight: 600 }}>筛选</span>
      <select value={brand} onChange={e => setBrand(e.target.value as Brand)} style={sel}>
        {(['全部品牌', '尝在一起', '最黔线', '尚宫厨'] as Brand[]).map(v => <option key={v}>{v}</option>)}
      </select>
      <select value={timeRange} onChange={e => setTimeRange(e.target.value as TimeRange)} style={sel}>
        {(['今日', '本周', '本月', '近30天', '近90天'] as TimeRange[]).map(v => <option key={v}>{v}</option>)}
      </select>
      <select value={region} onChange={e => setRegion(e.target.value as Region)} style={sel}>
        {(['全部区域', '华中区', '华东区', '华南区', '西南区'] as Region[]).map(v => <option key={v}>{v}</option>)}
      </select>
    </div>
  );
}

// ---- KPI 卡片行（4张：新增/月活/平均消费/LTV）----

interface KPIItem { label: string; value: string; subLabel: string; changePct: number | null; color?: string }

function KPICardsRow({ items, loading, error }: { items: KPIItem[]; loading: boolean; error: string | null }) {
  if (loading) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {[0,1,2,3].map(i => (
          <div key={i} style={{ background: BG_1, borderRadius: 10, padding: '16px 18px', border: `1px solid ${BG_2}` }}>
            <SectionSkeleton height={72} />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
      {items.map((kpi, i) => (
        <div key={i} style={{
          background: BG_1, borderRadius: 10, padding: '16px 18px',
          border: `1px solid ${BG_2}`, borderTop: `2px solid ${kpi.color ?? BRAND}`,
        }}>
          <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: TEXT_1 }}>{kpi.value}</div>
          <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>{kpi.subLabel}</div>
          {kpi.changePct !== null && (
            <div style={{ fontSize: 12, marginTop: 4, color: kpi.changePct >= 0 ? '#52c41a' : '#ff4d4f' }}>
              {kpi.changePct >= 0 ? '+' : ''}{kpi.changePct.toFixed(1)}% 较上期
            </div>
          )}
          {error && <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>数据暂不可用</div>}
        </div>
      ))}
    </div>
  );
}

// ---- SVG 折线图：会员增长趋势（30天）----

interface TrendPoint { date: string; newMembers: number; activeRate: number; repurchaseRate: number }

function TrendChart({ data, loading, error }: { data: TrendPoint[]; loading: boolean; error: string | null }) {
  const W = 560; const H = 160;
  const pL = 40; const pR = 16; const pT = 12; const pB = 24;
  const iW = W - pL - pR; const iH = H - pT - pB;

  const maxNew = data.length > 0 ? Math.max(...data.map(d => d.newMembers), 1) : 1;
  const xPos  = (i: number) => pL + (data.length <= 1 ? iW / 2 : (i / (data.length - 1)) * iW);
  const yNew  = (v: number) => pT + iH - (v / maxNew) * iH;
  const yRate = (v: number) => pT + iH - (Math.min(v, 100) / 100) * iH;

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}`, flex: 1, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>会员增长趋势</span>
        <div style={{ display: 'flex', gap: 14, fontSize: 11, color: TEXT_3 }}>
          <span><span style={{ color: BRAND }}>━</span> 新增会员</span>
          <span><span style={{ color: TEAL }}>━</span> 活跃率%</span>
          <span><span style={{ color: '#52c41a' }}>━</span> 复购率%</span>
        </div>
      </div>

      {loading && <SectionSkeleton height={H} />}
      {!loading && error && <SectionError msg={error} />}
      {!loading && !error && data.length === 0 && <SectionSkeleton height={H} label="暂无趋势数据" />}
      {!loading && !error && data.length > 0 && (
        <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible', display: 'block' }}>
          <defs>
            <linearGradient id="growGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={BRAND} stopOpacity="0.28" />
              <stop offset="100%" stopColor={BRAND} stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {/* 网格 */}
          {[0, 25, 50, 75, 100].map(v => (
            <g key={v}>
              <line x1={pL} y1={pT + iH - (v/100)*iH} x2={pL+iW} y2={pT + iH - (v/100)*iH}
                stroke={BG_2} strokeWidth={1} />
              <text x={pL - 4} y={pT + iH - (v/100)*iH + 4} textAnchor="end" fill={TEXT_4} fontSize={9}>{v}</text>
            </g>
          ))}

          {/* 新增面积 */}
          {data.length > 1 && (
            <polygon fill="url(#growGrad)" points={[
              `${xPos(0)},${pT+iH}`,
              ...data.map((d, i) => `${xPos(i)},${yNew(d.newMembers)}`),
              `${xPos(data.length-1)},${pT+iH}`,
            ].join(' ')} />
          )}

          {/* 新增折线 */}
          {data.length > 1 && (
            <polyline fill="none" stroke={BRAND} strokeWidth={2} strokeLinejoin="round"
              points={data.map((d, i) => `${xPos(i)},${yNew(d.newMembers)}`).join(' ')} />
          )}
          {data.map((d, i) => <circle key={`n${i}`} cx={xPos(i)} cy={yNew(d.newMembers)} r={3} fill={BRAND} />)}

          {/* 活跃率折线 */}
          {data.length > 1 && (
            <polyline fill="none" stroke={TEAL} strokeWidth={1.5} strokeDasharray="4 2"
              points={data.map((d, i) => `${xPos(i)},${yRate(d.activeRate)}`).join(' ')} />
          )}
          {data.map((d, i) => <circle key={`a${i}`} cx={xPos(i)} cy={yRate(d.activeRate)} r={2.5} fill={TEAL} />)}

          {/* 复购率折线 */}
          {data.length > 1 && (
            <polyline fill="none" stroke="#52c41a" strokeWidth={1.5} strokeDasharray="4 2"
              points={data.map((d, i) => `${xPos(i)},${yRate(d.repurchaseRate)}`).join(' ')} />
          )}
          {data.map((d, i) => <circle key={`r${i}`} cx={xPos(i)} cy={yRate(d.repurchaseRate)} r={2.5} fill="#52c41a" />)}

          {/* X轴标签（均匀抽取最多7个）*/}
          {data.map((d, i) => {
            const step = Math.max(1, Math.floor(data.length / 7));
            if (i % step !== 0 && i !== data.length - 1) return null;
            return <text key={`lbl${i}`} x={xPos(i)} y={H - 2} textAnchor="middle" fill={TEXT_4} fontSize={9}>{d.date.slice(5)}</text>;
          })}
        </svg>
      )}
    </div>
  );
}

// ---- 渠道来源分布（水平条形）----

const CH_COLORS = [BRAND, BLUE, '#52c41a', TEAL, PURPLE, YELLOW];

function ChannelSection({ channels, total, loading, error }: {
  channels: { channel: string; count: number; ratio: number }[];
  total: number;
  loading: boolean;
  error: string | null;
}) {
  const display = channels.length > 0 ? channels : [
    { channel: '扫码点餐',   count: 0, ratio: 0.38 },
    { channel: '小程序',     count: 0, ratio: 0.28 },
    { channel: '美团/饿了么', count: 0, ratio: 0.18 },
    { channel: '线下推广',   count: 0, ratio: 0.10 },
    { channel: '老带新',     count: 0, ratio: 0.06 },
  ];

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}`, minWidth: 260 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>渠道来源分布</div>
      {loading && <SectionSkeleton height={160} />}
      {!loading && error && <SectionError msg={error} />}
      {!loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {display.slice(0, 6).map((ch, i) => (
            <div key={ch.channel}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12 }}>
                <span style={{ color: TEXT_2 }}>{ch.channel}</span>
                <span style={{ color: CH_COLORS[i % CH_COLORS.length], fontWeight: 600 }}>
                  {ch.count > 0 ? ch.count.toLocaleString() + ' · ' : ''}{(ch.ratio * 100).toFixed(1)}%
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: BG_2 }}>
                <div style={{
                  height: '100%', borderRadius: 3, transition: 'width 0.6s ease',
                  width: `${(ch.ratio * 100).toFixed(1)}%`,
                  background: CH_COLORS[i % CH_COLORS.length],
                }} />
              </div>
            </div>
          ))}
          {total > 0 && <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>期间新增 {total.toLocaleString()} 人</div>}
          {channels.length === 0 && !error && <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>渠道数据加载中，显示默认分布</div>}
        </div>
      )}
    </div>
  );
}

// ---- RFM 会员分层 ----

const RFM_CFG: Record<string, { label: string; color: string; desc: string }> = {
  S1: { label: '高价值', color: BRAND,  desc: '高频高消费' },
  S2: { label: '潜力客', color: '#52c41a', desc: '较活跃' },
  S3: { label: '一般客', color: YELLOW, desc: '偶尔消费' },
  S4: { label: '流失预警', color: '#ff4d4f', desc: '长期未到店' },
  S5: { label: '沉睡客', color: TEXT_4,  desc: '极低活跃' },
};

function RFMSection({ distribution, total, loading, error }: {
  distribution: { level: string; count: number; ratio: number }[];
  total: number; loading: boolean; error: string | null;
}) {
  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}`, flex: 1, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>RFM 会员分层</span>
        {total > 0 && <span style={{ fontSize: 11, color: TEXT_3 }}>共 {total.toLocaleString()} 位会员</span>}
      </div>

      {loading && <SectionSkeleton height={160} />}
      {!loading && error && <SectionError msg={error} />}
      {!loading && !error && distribution.length === 0 && <SectionSkeleton height={160} label="暂无RFM数据" />}
      {!loading && !error && distribution.length > 0 && (
        <>
          {/* 堆积进度条 */}
          <div style={{ display: 'flex', height: 20, borderRadius: 4, overflow: 'hidden', marginBottom: 16 }}>
            {distribution.map(d => {
              const cfg = RFM_CFG[d.level] ?? { color: TEXT_4, label: d.level, desc: '' };
              return (
                <div key={d.level} title={`${cfg.label}: ${(d.ratio * 100).toFixed(1)}%`}
                  style={{
                    width: `${(d.ratio * 100).toFixed(2)}%`,
                    background: cfg.color, minWidth: d.ratio > 0 ? 2 : 0, transition: 'width 0.6s ease',
                  }} />
              );
            })}
          </div>
          {/* 明细列表 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {distribution.map(d => {
              const cfg = RFM_CFG[d.level] ?? { color: TEXT_4, label: d.level, desc: '' };
              return (
                <div key={d.level} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '6px 10px', borderRadius: 6, background: BG_2,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 8, height: 8, borderRadius: 2, background: cfg.color }} />
                    <span style={{ fontSize: 12, fontWeight: 600, color: cfg.color }}>{d.level}</span>
                    <span style={{ fontSize: 12, color: TEXT_3 }}>{cfg.label}</span>
                    <span style={{ fontSize: 11, color: TEXT_4 }}>{cfg.desc}</span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: TEXT_1 }}>{d.count.toLocaleString()}</span>
                    <span style={{ fontSize: 11, color: TEXT_4, marginLeft: 4 }}>{(d.ratio * 100).toFixed(1)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

// ---- 私域健康度仪表盘 ----

function MetricRow({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '8px 10px', borderRadius: 6, background: BG_2,
    }}>
      <span style={{ fontSize: 12, color: TEXT_3 }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ fontSize: 14, fontWeight: 700, color }}>{value}</span>
        {sub && <span style={{ fontSize: 10, color: TEXT_4, marginLeft: 4 }}>{sub}</span>}
      </div>
    </div>
  );
}

function PrivateDomainSection({ summary, loading, error }: {
  summary: DashboardSummary | null; loading: boolean; error: string | null;
}) {
  const calcScore = (s: DashboardSummary): number => {
    const orderBase   = Math.min(s.kpi.order_count / 200, 1) * 40;
    const storeActive = s.stores.length > 0
      ? (s.stores.filter(st => st.today_orders > 0).length / s.stores.length) * 40 : 0;
    const agentBonus  = Math.min(s.decisions.length * 4, 20);
    return Math.round(orderBase + storeActive + agentBonus);
  };

  const score         = summary ? calcScore(summary) : null;
  const activeStores  = summary ? summary.stores.filter(s => s.today_orders > 0).length : 0;
  const totalStores   = summary ? summary.stores.length : 0;
  const activeRate    = totalStores > 0 ? activeStores / totalStores : 0;
  const scoreColor    = score === null ? TEXT_4 : score >= 80 ? '#52c41a' : score >= 60 ? YELLOW : '#ff4d4f';

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}`, minWidth: 280 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>私域健康度</div>
      {loading && <SectionSkeleton height={200} />}
      {!loading && error && <SectionError msg={error} />}
      {!loading && !error && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 20 }}>
            <svg width={80} height={80} viewBox="0 0 80 80">
              <circle cx={40} cy={40} r={32} fill="none" stroke={BG_2} strokeWidth={8} />
              {score !== null && (
                <circle cx={40} cy={40} r={32} fill="none" stroke={scoreColor} strokeWidth={8}
                  strokeDasharray={`${(score / 100) * 201} 201`} strokeDashoffset={50}
                  strokeLinecap="round" transform="rotate(-90 40 40)"
                  style={{ transition: 'stroke-dasharray 1s ease' }} />
              )}
              <text x={40} y={44} textAnchor="middle" fill={scoreColor} fontSize={20} fontWeight={700}>
                {score ?? '--'}
              </text>
            </svg>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700, color: scoreColor }}>
                {score === null ? '--' : score >= 80 ? '健康' : score >= 60 ? '良好' : '待提升'}
              </div>
              <div style={{ fontSize: 12, color: TEXT_3, marginTop: 4 }}>综合健康分</div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <MetricRow
              label="今日活跃门店"
              value={totalStores > 0 ? `${activeStores}/${totalStores}` : '--'}
              sub={totalStores > 0 ? fmtPct(activeRate) : ''}
              color={activeRate >= 0.8 ? '#52c41a' : activeRate >= 0.5 ? YELLOW : '#ff4d4f'}
            />
            <MetricRow
              label="今日营收"
              value={summary ? fmtYuan(summary.kpi.revenue_fen) : '--'}
              sub={summary ? `${summary.kpi.order_count.toLocaleString()} 单` : ''}
              color={BRAND}
            />
            <MetricRow
              label="客单价"
              value={summary?.kpi.avg_order_fen ? `¥${(summary.kpi.avg_order_fen / 100).toFixed(0)}` : '--'}
              sub="今日均值"
              color={BLUE}
            />
            <MetricRow
              label="Agent近期决策"
              value={`${summary?.decisions.length ?? '--'} 条`}
              sub="最近5条"
              color={PURPLE}
            />
          </div>

          {summary && summary.decisions.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 8 }}>最近 Agent 决策</div>
              {summary.decisions.slice(0, 3).map(d => (
                <div key={d.id} style={{ padding: '6px 10px', borderRadius: 6, background: BG_2, marginBottom: 6, fontSize: 11 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ color: PURPLE, fontWeight: 600 }}>{d.agent_id}</span>
                    {d.confidence !== null && (
                      <span style={{ color: TEXT_4 }}>置信度 {Math.round((d.confidence ?? 0) * 100)}%</span>
                    )}
                  </div>
                  <div style={{ color: TEXT_3 }}>{d.action ?? d.decision_type}</div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---- 门店营收排行 ----

function StoreRankSection({ stores, loading, error }: {
  stores: DashboardSummary['stores']; loading: boolean; error: string | null;
}) {
  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}`, flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 12 }}>今日门店营收排行</div>
      {loading && <SectionSkeleton height={200} />}
      {!loading && error && <SectionError msg={error} />}
      {!loading && !error && stores.length === 0 && <SectionSkeleton height={120} label="暂无门店数据" />}
      {!loading && !error && stores.length > 0 && (
        <>
          <div style={{
            fontSize: 11, color: TEXT_4,
            display: 'grid', gridTemplateColumns: '28px 1fr 80px 60px 60px',
            gap: 4, padding: '0 0 8px', borderBottom: `1px solid ${BG_2}`,
          }}>
            <span>#</span><span>门店</span><span>营收</span><span>订单</span><span>状态</span>
          </div>
          {stores.slice(0, 8).map((s, idx) => (
            <div key={s.store_id} style={{
              display: 'grid', gridTemplateColumns: '28px 1fr 80px 60px 60px',
              gap: 4, padding: '8px 0', borderBottom: `1px solid ${BG_2}`,
              fontSize: 13, alignItems: 'center',
            }}>
              <span style={{
                width: 22, height: 22, borderRadius: 11,
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, fontWeight: 700,
                background: idx < 3 ? BRAND + '22' : BG_2,
                color: idx < 3 ? BRAND : TEXT_4,
              }}>{idx + 1}</span>
              <span style={{ color: TEXT_1, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {s.store_name}
              </span>
              <span style={{ color: TEXT_2 }}>{fmtYuan(s.today_revenue_fen)}</span>
              <span style={{ color: TEXT_2 }}>{s.today_orders}</span>
              <span style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 4,
                background: s.status === 'open' ? '#52c41a22' : BG_2,
                color: s.status === 'open' ? '#52c41a' : TEXT_4,
              }}>
                {s.status === 'open' ? '营业中' : s.status === 'closed' ? '已闭店' : s.status}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function GrowthDashboardPage() {
  const navigate = useNavigate();
  const [brand, setBrand]         = useState<Brand>('全部品牌');
  const [timeRange, setTimeRange] = useState<TimeRange>('近30天');
  const [region, setRegion]       = useState<Region>('全部区域');

  // 增长中枢V2数据
  const { data: growthStats, loading: loadingGrowthV2 } = useApi<GrowthDashboardStats>(
    '/api/v1/growth/dashboard-stats',
    { cacheMs: 15_000 },
  );

  // 缺口1: 模板框架效果对比
  const { data: templateAttrData, loading: loadingTemplateAttr } = useApi<{ items: JourneyTemplateAttribution[]; days: number }>(
    '/api/v1/growth/attribution/by-journey-template?days=7',
    { cacheMs: 15_000 },
  );

  // 缺口2: Agent高优先建议TOP3
  const { data: topSuggestions, loading: loadingTopSuggestions } = useApi<{ items: AgentSuggestionDetail[]; total: number }>(
    '/api/v1/growth/agent-suggestions?review_state=pending_review&size=3',
    { cacheMs: 15_000 },
  );

  // 缺口3: P1四维分布
  const { data: p1Dist, loading: loadingP1Dist } = useApi<P1Distribution>(
    '/api/v1/growth/p1/distribution',
    { cacheMs: 15_000 },
  );

  const [growthData,    setGrowthData]    = useState<GrowthData | null>(null);
  const [activityData,  setActivityData]  = useState<ActivityData | null>(null);
  const [repurchaseData,setRepurchaseData]= useState<RepurchaseData | null>(null);
  const [rfmData,       setRfmData]       = useState<RfmDistribution | null>(null);
  const [dashboardData, setDashboardData] = useState<DashboardSummary | null>(null);

  const [loadingKpi,       setLoadingKpi]       = useState(true);
  const [loadingTrend,     setLoadingTrend]      = useState(true);
  const [loadingRfm,       setLoadingRfm]        = useState(true);
  const [loadingDashboard, setLoadingDashboard]  = useState(true);

  const [errorKpi,       setErrorKpi]       = useState<string | null>(null);
  const [errorTrend,     setErrorTrend]     = useState<string | null>(null);
  const [errorRfm,       setErrorRfm]       = useState<string | null>(null);
  const [errorDashboard, setErrorDashboard] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    const { start_date, end_date } = getDateRange(timeRange);
    const qs = `start_date=${start_date}&end_date=${end_date}`;

    setLoadingKpi(true); setLoadingTrend(true); setLoadingRfm(true); setLoadingDashboard(true);
    setErrorKpi(null);   setErrorTrend(null);   setErrorRfm(null);   setErrorDashboard(null);

    const [growthRes, activityRes, repurchaseRes, rfmRes, dashboardRes] = await Promise.allSettled([
      txFetch<{ ok: boolean; data: GrowthData }>(`/api/v1/member/analytics/growth?${qs}`),
      txFetch<{ ok: boolean; data: ActivityData }>(`/api/v1/member/analytics/activity?${qs}`),
      txFetch<{ ok: boolean; data: RepurchaseData }>(`/api/v1/member/analytics/repurchase?${qs}`),
      txFetch<{ ok: boolean; data: RfmDistribution }>('/api/v1/member/rfm/distribution'),
      txFetch<{ ok: boolean; data: DashboardSummary }>('/api/v1/dashboard/summary'),
    ]);

    // --- KPI 数据（growth + activity + repurchase）---
    let kpiErr: string | null = null;
    if (growthRes.status === 'fulfilled' && growthRes.value.ok) {
      setGrowthData(growthRes.value.data);
    } else {
      kpiErr = growthRes.status === 'rejected' ? (growthRes.reason?.message ?? '请求失败') : '增长数据异常';
    }
    if (activityRes.status === 'fulfilled' && activityRes.value.ok) {
      setActivityData(activityRes.value.data);
    } else if (!kpiErr) {
      kpiErr = activityRes.status === 'rejected' ? (activityRes.reason?.message ?? '请求失败') : '活跃度数据异常';
    }
    if (repurchaseRes.status === 'fulfilled' && repurchaseRes.value.ok) {
      setRepurchaseData(repurchaseRes.value.data);
    }
    setErrorKpi(kpiErr);
    setLoadingKpi(false);

    // --- 趋势 ---
    const trendOk = growthRes.status === 'fulfilled' && growthRes.value.ok
      && activityRes.status === 'fulfilled' && activityRes.value.ok;
    setErrorTrend(trendOk ? null : '趋势数据不完整');
    setLoadingTrend(false);

    // --- RFM ---
    if (rfmRes.status === 'fulfilled' && rfmRes.value.ok) {
      setRfmData(rfmRes.value.data);
      setErrorRfm(null);
    } else {
      setErrorRfm(rfmRes.status === 'rejected' ? (rfmRes.reason?.message ?? '请求失败') : 'RFM数据异常');
    }
    setLoadingRfm(false);

    // --- 私域仪表盘 ---
    if (dashboardRes.status === 'fulfilled' && dashboardRes.value.ok) {
      setDashboardData(dashboardRes.value.data);
      setErrorDashboard(null);
    } else {
      setErrorDashboard(
        dashboardRes.status === 'rejected' ? (dashboardRes.reason?.message ?? '请求失败') : '仪表盘数据异常'
      );
    }
    setLoadingDashboard(false);
  }, [timeRange]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // ---- 派生：4张KPI卡片 ----
  const kpiItems: KPIItem[] = [
    {
      label: '新增会员',
      value: growthData ? growthData.new_members.toLocaleString() : '--',
      subLabel: `总会员 ${growthData ? growthData.total_members.toLocaleString() : '--'}`,
      changePct: growthData?.new_members_change_pct ?? null,
      color: BRAND,
    },
    {
      label: '月活会员（MAU）',
      value: activityData ? activityData.mau.toLocaleString() : '--',
      subLabel: `活跃率 ${activityData ? fmtPct(activityData.active_rate) : '--'}`,
      changePct: activityData?.mau_change_pct ?? null,
      color: TEAL,
    },
    {
      label: '人均消费',
      value: growthData?.avg_spend_fen
        ? `¥${(growthData.avg_spend_fen / 100).toFixed(0)}`
        : (dashboardData?.kpi.avg_order_fen ? `¥${(dashboardData.kpi.avg_order_fen / 100).toFixed(0)}` : '--'),
      subLabel: repurchaseData ? `复购率 ${fmtPct(repurchaseData.repurchase_rate)}` : '期间均值',
      changePct: repurchaseData?.repurchase_rate_change_pct ?? null,
      color: '#52c41a',
    },
    {
      label: '会员 LTV',
      value: growthData?.ltv_fen
        ? fmtYuan(growthData.ltv_fen)
        : '--',
      subLabel: repurchaseData ? `平均间隔 ${repurchaseData.avg_interval_days.toFixed(0)} 天` : '生命周期价值',
      changePct: null,
      color: BLUE,
    },
  ];

  // ---- 派生：趋势点 ----
  const trendPoints: TrendPoint[] = (() => {
    if (!growthData?.daily_trend || !activityData?.daily_active) return [];
    const actMap = new Map(activityData.daily_active.map(d => [d.date, d]));
    const globalRR = (repurchaseData?.repurchase_rate ?? 0) * 100;
    return growthData.daily_trend.map(g => ({
      date: g.date,
      newMembers: g.new_members,
      activeRate: (actMap.get(g.date)?.active_rate ?? 0) * 100,
      repurchaseRate: globalRR,
    }));
  })();

  return (
    <div style={{ background: BG_0, minHeight: '100vh', padding: '20px 24px' }}>
      <div style={{ maxWidth: 1400, margin: '0 auto' }}>

        {/* 页头 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>增长中心</h2>
          <button onClick={fetchAll} style={{
            padding: '6px 16px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: BG_1, color: TEXT_3, fontSize: 12, cursor: 'pointer',
          }}>
            刷新数据
          </button>
        </div>

        {/* 筛选栏 */}
        <FilterBar brand={brand} setBrand={setBrand} timeRange={timeRange} setTimeRange={setTimeRange} region={region} setRegion={setRegion} />

        {/* 4张KPI卡片 */}
        <KPICardsRow items={kpiItems} loading={loadingKpi} error={errorKpi} />

        {/* 趋势图 + 渠道分布 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          <TrendChart data={trendPoints} loading={loadingTrend} error={errorTrend} />
          <ChannelSection
            channels={growthData?.channels ?? []}
            total={growthData?.new_members ?? 0}
            loading={loadingKpi}
            error={errorKpi}
          />
        </div>

        {/* RFM分层 + 私域健康度 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          <RFMSection
            distribution={rfmData?.distribution ?? []}
            total={rfmData?.total ?? 0}
            loading={loadingRfm}
            error={errorRfm}
          />
          <PrivateDomainSection summary={dashboardData} loading={loadingDashboard} error={errorDashboard} />
        </div>

        {/* 门店排行 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <StoreRankSection stores={dashboardData?.stores ?? []} loading={loadingDashboard} error={errorDashboard} />
        </div>

        {/* ========== 增长中枢 V2 ========== */}

        <div style={{ borderTop: `1px solid ${BG_2}`, margin: '24px 0 16px', paddingTop: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 18, fontWeight: 700, color: TEXT_1 }}>增长中枢 V2</h3>
        </div>

        {/* 区域1: 增长中枢V2 KPI行（6卡）*/}
        {loadingGrowthV2 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 16 }}>
            {[0,1,2,3,4,5].map(i => (
              <div key={i} style={{ background: '#142833', borderRadius: 10, padding: '16px 14px', border: '1px solid #1e3a4a' }}>
                <SectionSkeleton height={60} />
              </div>
            ))}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 16 }}>
            {[
              { label: '二访率', value: growthStats?.conversion_rates.second_visit_rate, suffix: '%', format: (v: number) => (v * 100).toFixed(1), color: BRAND },
              { label: '高优先召回', value: growthStats?.profiles.high_priority_reactivation, suffix: ' 人', format: (v: number) => v.toLocaleString(), color: '#ff4d4f' },
              { label: '活跃旅程', value: growthStats?.enrollments.active, suffix: ' 条', format: (v: number) => v.toLocaleString(), color: TEAL },
              { label: '7日触达', value: growthStats?.touches_7d.delivered, suffix: ' 次', format: (v: number) => v.toLocaleString(), color: BLUE },
              { label: '触达打开率', value: growthStats?.conversion_rates.touch_open_rate, suffix: '%', format: (v: number) => (v * 100).toFixed(1), color: '#52c41a' },
              { label: '待审核建议', value: growthStats?.suggestions_7d.pending_review, suffix: ' 条', format: (v: number) => v.toLocaleString(), color: YELLOW },
            ].map((kpi, i) => (
              <div key={i} style={{
                background: '#142833', borderRadius: 10, padding: '16px 14px',
                border: '1px solid #1e3a4a', borderTop: `2px solid ${kpi.color}`,
              }}>
                <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#e8e8e8' }}>
                  {kpi.value != null ? kpi.format(kpi.value) : '--'}{kpi.value != null ? kpi.suffix : ''}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 区域2: 增长漏斗 + Agent待办（左右两栏）*/}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          {/* 左栏 — 增长漏斗 */}
          <div style={{ background: '#142833', borderRadius: 10, padding: 20, border: '1px solid #1e3a4a', flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>增长漏斗</div>
            {loadingGrowthV2 ? <SectionSkeleton height={140} /> : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {[
                  { label: '首单客户', value: growthStats?.funnel.first_order, color: BRAND },
                  { label: '已触达', value: growthStats?.funnel.touched, color: BLUE },
                  { label: '已回访', value: growthStats?.funnel.revisited, color: TEAL },
                  { label: '复购客户', value: growthStats?.funnel.repeat_customer, color: '#52c41a' },
                  { label: '稳定复购', value: growthStats?.funnel.stable_repeat, color: PURPLE },
                ].map((step, idx) => {
                  const maxVal = growthStats?.funnel.first_order || 1;
                  const pct = step.value != null ? Math.max((step.value / maxVal) * 100, 2) : 0;
                  return (
                    <div key={idx}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12 }}>
                        <span style={{ color: TEXT_2 }}>{step.label}</span>
                        <span style={{ color: step.color, fontWeight: 600 }}>{step.value?.toLocaleString() ?? '--'}</span>
                      </div>
                      <div style={{ height: 14, borderRadius: 4, background: BG_2 }}>
                        <div style={{
                          height: '100%', borderRadius: 4, background: step.color,
                          width: `${pct.toFixed(1)}%`, transition: 'width 0.6s ease',
                          display: 'flex', alignItems: 'center', justifyContent: 'flex-end', paddingRight: 6,
                          fontSize: 9, color: '#fff', fontWeight: 600,
                        }}>
                          {step.value != null && pct > 15 ? `${pct.toFixed(0)}%` : ''}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 右栏 — Agent待办速览 */}
          <div style={{ background: '#142833', borderRadius: 10, padding: 20, border: '1px solid #1e3a4a', minWidth: 280 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>Agent 待办速览</div>
            {loadingGrowthV2 ? <SectionSkeleton height={140} /> : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 10px', borderRadius: 6, background: BG_2 }}>
                  <span style={{ fontSize: 12, color: TEXT_3 }}>待审核</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: YELLOW }}>{growthStats?.suggestions_7d.pending_review ?? '--'} 条</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 10px', borderRadius: 6, background: BG_2 }}>
                  <span style={{ fontSize: 12, color: TEXT_3 }}>已发布</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: '#52c41a' }}>{growthStats?.suggestions_7d.published ?? '--'} 条</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 10px', borderRadius: 6, background: BG_2 }}>
                  <span style={{ fontSize: 12, color: TEXT_3 }}>活跃修复</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: BRAND }}>{growthStats?.profiles.active_repairs ?? '--'} 条</span>
                </div>
                <button
                  onClick={() => navigate('/hq/growth/agent-workbench')}
                  style={{
                    marginTop: 8, padding: '10px 0', borderRadius: 6,
                    background: BRAND, border: 'none', color: '#fff',
                    fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    transition: 'opacity 0.2s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
                  onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
                >
                  进入 Agent 工作台
                </button>

                {/* 缺口2: Agent高优先建议TOP3 */}
                {!loadingTopSuggestions && topSuggestions && topSuggestions.items.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 8, fontWeight: 600 }}>TOP 3 待审建议</div>
                    {topSuggestions.items.slice(0, 3).map((s) => {
                      const priorityColors: Record<string, string> = { high: '#ff4d4f', medium: YELLOW, low: '#52c41a' };
                      const priorityLabels: Record<string, string> = { high: '高优', medium: '中优', low: '低优' };
                      const typeLabels: Record<string, string> = {
                        reactivation: '召回', first_to_second: '首转二', service_repair: '修复',
                        retention: '留存', upsell: '提频', referral: '裂变',
                      };
                      const pColor = priorityColors[s.priority ?? ''] || TEXT_3;
                      const pLabel = priorityLabels[s.priority ?? ''] || (s.priority ?? '--');
                      const tLabel = typeLabels[s.suggestion_type] || s.suggestion_type;
                      const summary = s.explanation_summary || s.reasoning || '';
                      const truncated = summary.length > 50 ? summary.slice(0, 50) + '...' : summary;
                      return (
                        <div key={s.id} style={{
                          padding: '8px 10px', borderRadius: 6, background: BG_2, marginBottom: 6,
                          cursor: 'pointer', transition: 'opacity 0.2s',
                        }}
                          onClick={() => navigate('/hq/growth/agent-workbench')}
                          onMouseEnter={e => (e.currentTarget.style.opacity = '0.8')}
                          onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
                        >
                          <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
                            <span style={{
                              fontSize: 10, padding: '1px 6px', borderRadius: 3,
                              background: pColor + '22', color: pColor, fontWeight: 600,
                            }}>{pLabel}</span>
                            <span style={{
                              fontSize: 10, padding: '1px 6px', borderRadius: 3,
                              background: TEAL + '22', color: TEAL,
                            }}>{tLabel}</span>
                            {s.mechanism_type && (
                              <span style={{
                                fontSize: 10, padding: '1px 6px', borderRadius: 3,
                                background: PURPLE + '22', color: PURPLE,
                              }}>{s.mechanism_type}</span>
                            )}
                          </div>
                          <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.4 }}>{truncated || '暂无摘要'}</div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* 区域X: 机制效果速览 */}
        {growthStats?.mechanism_summary && growthStats.mechanism_summary.length > 0 && (
          <div style={{ background: '#142833', borderRadius: 10, padding: 20, border: '1px solid #1e3a4a', marginBottom: 16 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>机制效果速览（近7天）</div>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {growthStats.mechanism_summary.map((m) => {
                const mechColors: Record<string, string> = {
                  hook: TEAL, loss_aversion: BRAND, repair: RED, mixed: PURPLE,
                  social_proof: BLUE, scarcity: YELLOW, reciprocity: '#52c41a',
                };
                const mechLabels: Record<string, string> = {
                  hook: '钩子吸引', loss_aversion: '损失规避', repair: '服务修复',
                  mixed: '混合机制', social_proof: '社会认同', scarcity: '稀缺效应',
                  reciprocity: '互惠心理', authority: '权威背书', commitment: '承诺一致',
                };
                const color = mechColors[m.mechanism_type] || TEXT_3;
                return (
                  <div key={m.mechanism_type} style={{
                    flex: '1 1 180px', maxWidth: 220, padding: '12px 16px',
                    borderRadius: 8, background: BG_2, borderLeft: `3px solid ${color}`,
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color, marginBottom: 8 }}>
                      {mechLabels[m.mechanism_type] || m.mechanism_type}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_3, marginBottom: 4 }}>
                      <span>打开率</span>
                      <span style={{ fontWeight: 700, color: m.open_rate >= 20 ? '#52c41a' : m.open_rate >= 10 ? YELLOW : '#ff4d4f' }}>
                        {m.open_rate.toFixed(1)}%
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_3 }}>
                      <span>归因率</span>
                      <span style={{ fontWeight: 700, color: m.attribution_rate >= 5 ? '#52c41a' : m.attribution_rate >= 2 ? YELLOW : '#ff4d4f' }}>
                        {m.attribution_rate.toFixed(1)}%
                      </span>
                    </div>
                    <div style={{ fontSize: 10, color: TEXT_4, marginTop: 4 }}>
                      触达 {m.total} / 打开 {m.opened} / 归因 {m.attributed}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 缺口1: 模板框架效果对比 */}
        <div style={{ background: '#142833', borderRadius: 10, padding: 20, border: '1px solid #1e3a4a', marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>模板框架对比（近7天）</div>
          {loadingTemplateAttr ? <SectionSkeleton height={120} /> : (() => {
            const items = templateAttrData?.items || [];
            const groups: Record<string, { enrollments: number; completed: number; completionRate: number; touches: number; opened: number; attributed: number; openRate: number; attrRate: number }> = {};
            const typeMap: Record<string, { label: string; color: string }> = {
              first_to_second: { label: '首单转二访', color: '#52c41a' },
              reactivation: { label: '沉默召回', color: BRAND },
              service_repair: { label: '服务修复', color: '#ff4d4f' },
            };
            for (const it of items) {
              const jt = it.journey_type;
              if (!typeMap[jt]) continue;
              if (!groups[jt]) groups[jt] = { enrollments: 0, completed: 0, completionRate: 0, touches: 0, opened: 0, attributed: 0, openRate: 0, attrRate: 0 };
              const g = groups[jt];
              g.enrollments += it.total_enrollments;
              g.completed += it.completed;
              g.touches += it.total_touches;
              g.opened += it.opened;
              g.attributed += it.attributed;
            }
            for (const key of Object.keys(groups)) {
              const g = groups[key];
              g.completionRate = g.enrollments > 0 ? (g.completed / g.enrollments) * 100 : 0;
              g.openRate = g.touches > 0 ? (g.opened / g.touches) * 100 : 0;
              g.attrRate = g.touches > 0 ? (g.attributed / g.touches) * 100 : 0;
            }
            const keys = ['first_to_second', 'reactivation', 'service_repair'];
            return (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                {keys.map((jt) => {
                  const cfg = typeMap[jt];
                  const g = groups[jt];
                  return (
                    <div key={jt} style={{ padding: '14px 16px', borderRadius: 8, background: BG_2, borderTop: `3px solid ${cfg.color}` }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: cfg.color, marginBottom: 10 }}>{cfg.label}</div>
                      {g ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                            <span style={{ color: TEXT_3 }}>活跃enrollment</span>
                            <span style={{ color: '#e8e8e8', fontWeight: 600 }}>{g.enrollments}</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                            <span style={{ color: TEXT_3 }}>完成率</span>
                            <span style={{ color: g.completionRate >= 30 ? '#52c41a' : g.completionRate >= 15 ? YELLOW : '#ff4d4f', fontWeight: 600 }}>{g.completionRate.toFixed(1)}%</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                            <span style={{ color: TEXT_3 }}>触达打开率</span>
                            <span style={{ color: g.openRate >= 20 ? '#52c41a' : g.openRate >= 10 ? YELLOW : '#ff4d4f', fontWeight: 600 }}>{g.openRate.toFixed(1)}%</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                            <span style={{ color: TEXT_3 }}>归因到店率</span>
                            <span style={{ color: g.attrRate >= 5 ? '#52c41a' : g.attrRate >= 2 ? YELLOW : '#ff4d4f', fontWeight: 600 }}>{g.attrRate.toFixed(1)}%</span>
                          </div>
                        </div>
                      ) : (
                        <div style={{ fontSize: 12, color: TEXT_4, textAlign: 'center', padding: 16 }}>暂无数据</div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </div>

        {/* 区域3: 旅程运行状态速览 */}
        <div style={{ background: '#142833', borderRadius: 10, padding: 20, border: '1px solid #1e3a4a', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>旅程运行状态</span>
            <a
              onClick={() => navigate('/hq/growth/journey-runs')}
              style={{ fontSize: 12, color: TEAL, cursor: 'pointer', textDecoration: 'none' }}
            >
              查看全部 &rarr;
            </a>
          </div>
          {loadingGrowthV2 ? <SectionSkeleton height={60} /> : (
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {[
                { label: '活跃', value: growthStats?.enrollments.active, color: '#52c41a', bg: '#52c41a22' },
                { label: '暂停', value: growthStats?.enrollments.paused, color: '#fa8c16', bg: '#fa8c1622' },
                { label: '观察中', value: growthStats?.enrollments.observing, color: TEAL, bg: `${TEAL}22` },
                { label: '已完成', value: growthStats?.enrollments.completed, color: TEXT_3, bg: BG_2 },
              ].map((item, idx) => (
                <div key={idx} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '8px 16px', borderRadius: 8, background: item.bg,
                }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%', background: item.color, flexShrink: 0,
                  }} />
                  <span style={{ fontSize: 13, color: item.color, fontWeight: 600 }}>{item.label}</span>
                  <span style={{ fontSize: 18, fontWeight: 700, color: '#e8e8e8' }}>
                    {item.value?.toLocaleString() ?? '--'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 缺口3: P1客户分层概览 */}
        <div style={{ background: '#142833', borderRadius: 10, padding: 20, border: '1px solid #1e3a4a', marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>P1 客户分层概览</div>
          {loadingP1Dist ? <SectionSkeleton height={160} /> : (() => {
            const psyLabels: Record<string, string> = { near: '亲近', habit_break: '习惯断裂', fading: '淡化', abstracted: '疏远', lost: '失联' };
            const suLabels: Record<string, string> = { none: '无', potential: '潜力', active: '活跃', advocate: '倡导者' };
            const msLabels: Record<string, string> = { newcomer: '新客', regular: '常客', loyal: '忠实', vip: 'VIP', legend: '传奇' };
            const rfLabels: Record<string, string> = { none: '无', birthday_organizer: '生日组织者', family_host: '家庭聚餐', corporate_host: '商务宴请', super_referrer: '超级推荐人' };

            const renderDimension = (
              title: string,
              data: { level?: string; stage?: string; scenario?: string; count: number }[] | undefined,
              labels: Record<string, string>,
              barColor: string,
            ) => {
              if (!data || data.length === 0) return (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{title}</div>
                  <div style={{ fontSize: 11, color: TEXT_4 }}>暂无数据</div>
                </div>
              );
              const total = data.reduce((s, d) => s + d.count, 0) || 1;
              return (
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, fontWeight: 600 }}>{title}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    {data.map((d) => {
                      const key = d.level || d.stage || d.scenario || 'unknown';
                      const pct = (d.count / total) * 100;
                      return (
                        <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ fontSize: 11, color: TEXT_3, width: 80, textAlign: 'right', flexShrink: 0 }}>
                            {labels[key] || key}
                          </span>
                          <div style={{ flex: 1, height: 14, borderRadius: 3, background: BG_2, overflow: 'hidden' }}>
                            <div style={{
                              height: '100%', borderRadius: 3, background: barColor,
                              width: `${Math.max(pct, 1).toFixed(1)}%`, transition: 'width 0.6s ease',
                              display: 'flex', alignItems: 'center', justifyContent: 'flex-end', paddingRight: 4,
                              fontSize: 9, color: '#fff', fontWeight: 600, minWidth: 18,
                            }}>
                              {pct >= 8 ? `${pct.toFixed(0)}%` : ''}
                            </div>
                          </div>
                          <span style={{ fontSize: 11, color: TEXT_4, width: 50, textAlign: 'right', flexShrink: 0 }}>
                            {d.count}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            };

            return (
              <>
                {renderDimension('心理距离', p1Dist?.psych_distance, psyLabels, TEAL)}
                {renderDimension('超级用户', p1Dist?.super_user, suLabels, BRAND)}
                {renderDimension('成长里程碑', p1Dist?.milestones, msLabels, BLUE)}
                {renderDimension('裂变场景', p1Dist?.referral, rfLabels, PURPLE)}
              </>
            );
          })()}
        </div>

      </div>
    </div>
  );
}
