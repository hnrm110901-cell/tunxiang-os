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
import { txFetch } from '../../../api';

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
  const [brand, setBrand]         = useState<Brand>('全部品牌');
  const [timeRange, setTimeRange] = useState<TimeRange>('近30天');
  const [region, setRegion]       = useState<Region>('全部区域');

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

      </div>
    </div>
  );
}
