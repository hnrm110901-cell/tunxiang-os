/**
 * ROIOverviewPage -- 全渠道 ROI 总览
 * 路由: /hq/growth/roi
 */
import { useState, useMemo } from 'react';

// ---- 颜色常量 ----
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
type AttributionModel = 'first-touch' | 'last-touch' | 'multi-touch';

interface ChannelROI {
  id: string;
  name: string;
  investment: number;
  revenue: number;
  roi: number;
  cac: number;
  ltv: number;
  color: string;
}

interface SegmentROI {
  id: string;
  name: string;
  investment: number;
  revenue: number;
  roi: number;
  avgOrderValue: number;
  retention: number;
}

interface CampaignROI {
  id: string;
  name: string;
  channel: string;
  investment: number;
  revenue: number;
  roi: number;
  status: '进行中' | '已结束' | '计划中';
  startDate: string;
  endDate: string;
}

interface AttributionPath {
  from: string;
  to: string;
  value: number;
}

interface ProfitTrend {
  month: string;
  investment: number;
  revenue: number;
  profit: number;
}

// ---- Mock 数据 ----
const MOCK_CHANNELS: ChannelROI[] = [
  { id: 'ch-1', name: '美团/大众点评', investment: 128000, revenue: 512000, roi: 4.0, cac: 35, ltv: 680, color: '#1890ff' },
  { id: 'ch-2', name: '抖音本地生活', investment: 95000, revenue: 342000, roi: 3.6, cac: 28, ltv: 520, color: '#ff4d4f' },
  { id: 'ch-3', name: '微信私域', investment: 42000, revenue: 252000, roi: 6.0, cac: 12, ltv: 890, color: '#52c41a' },
  { id: 'ch-4', name: '小红书种草', investment: 68000, revenue: 204000, roi: 3.0, cac: 45, ltv: 450, color: '#722ed1' },
  { id: 'ch-5', name: '线下地推', investment: 35000, revenue: 175000, roi: 5.0, cac: 18, ltv: 720, color: '#faad14' },
];

const MOCK_SEGMENTS: SegmentROI[] = [
  { id: 'seg-1', name: '家庭聚餐客群', investment: 85000, revenue: 425000, roi: 5.0, avgOrderValue: 380, retention: 0.72 },
  { id: 'seg-2', name: '商务宴请客群', investment: 72000, revenue: 360000, roi: 5.0, avgOrderValue: 680, retention: 0.58 },
  { id: 'seg-3', name: '年轻白领客群', investment: 98000, revenue: 343000, roi: 3.5, avgOrderValue: 128, retention: 0.65 },
  { id: 'seg-4', name: '周边居民客群', investment: 45000, revenue: 270000, roi: 6.0, avgOrderValue: 95, retention: 0.82 },
  { id: 'seg-5', name: '旅游打卡客群', investment: 68000, revenue: 136000, roi: 2.0, avgOrderValue: 165, retention: 0.25 },
];

const MOCK_CAMPAIGNS: CampaignROI[] = [
  { id: 'camp-1', name: '春季新品推广', channel: '抖音本地生活', investment: 45000, revenue: 180000, roi: 4.0, status: '进行中', startDate: '2026-03-01', endDate: '2026-03-31' },
  { id: 'camp-2', name: '会员日满减', channel: '微信私域', investment: 18000, revenue: 108000, roi: 6.0, status: '进行中', startDate: '2026-03-15', endDate: '2026-03-31' },
  { id: 'camp-3', name: '美团霸王餐', channel: '美团/大众点评', investment: 32000, revenue: 96000, roi: 3.0, status: '已结束', startDate: '2026-02-15', endDate: '2026-03-10' },
  { id: 'camp-4', name: '开业周年庆', channel: '线下地推', investment: 25000, revenue: 125000, roi: 5.0, status: '已结束', startDate: '2026-02-01', endDate: '2026-02-28' },
  { id: 'camp-5', name: '小红书达人探店', channel: '小红书种草', investment: 38000, revenue: 114000, roi: 3.0, status: '计划中', startDate: '2026-04-01', endDate: '2026-04-30' },
];

const MOCK_ATTRIBUTION_PATHS: AttributionPath[] = [
  { from: '小红书种草', to: '美团搜索', value: 3200 },
  { from: '美团搜索', to: '到店消费', value: 2800 },
  { from: '抖音视频', to: '抖音团购', value: 4500 },
  { from: '抖音团购', to: '到店核销', value: 3800 },
  { from: '微信推送', to: '小程序下单', value: 2100 },
  { from: '小程序下单', to: '到店消费', value: 1900 },
  { from: '朋友推荐', to: '美团搜索', value: 1500 },
  { from: '线下传单', to: '扫码关注', value: 800 },
  { from: '扫码关注', to: '小程序下单', value: 650 },
  { from: '抖音视频', to: '小红书种草', value: 1200 },
];

const MOCK_PROFIT_TREND: ProfitTrend[] = [
  { month: '2025-10', investment: 320000, revenue: 1120000, profit: 800000 },
  { month: '2025-11', investment: 345000, revenue: 1242000, profit: 897000 },
  { month: '2025-12', investment: 380000, revenue: 1520000, profit: 1140000 },
  { month: '2026-01', investment: 310000, revenue: 1085000, profit: 775000 },
  { month: '2026-02', investment: 355000, revenue: 1420000, profit: 1065000 },
  { month: '2026-03', investment: 368000, revenue: 1485000, profit: 1117000 },
];

// ---- 组件 ----

function FilterBar({
  attribution,
  onAttributionChange,
}: {
  attribution: AttributionModel;
  onAttributionChange: (m: AttributionModel) => void;
}) {
  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer',
  };
  const models: { value: AttributionModel; label: string }[] = [
    { value: 'first-touch', label: '首触归因' },
    { value: 'last-touch', label: '末触归因' },
    { value: 'multi-touch', label: '多触点归因' },
  ];
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
      padding: '12px 16px', background: BG_1, borderRadius: 10, marginBottom: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <label style={{ fontSize: 13, color: TEXT_3 }}>时间</label>
      <select style={selectStyle}>
        <option>本月</option><option>上月</option><option>近90天</option><option>本年</option>
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>品牌</label>
      <select style={selectStyle}>
        <option>全部品牌</option><option>尝在一起</option><option>最黔线</option><option>尚宫厨</option>
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>区域</label>
      <select style={selectStyle}>
        <option>全部区域</option><option>长沙</option><option>武汉</option><option>广州</option>
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>渠道</label>
      <select style={selectStyle}>
        <option>全部渠道</option>
        {MOCK_CHANNELS.map(c => <option key={c.id}>{c.name}</option>)}
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>人群</label>
      <select style={selectStyle}>
        <option>全部人群</option>
        {MOCK_SEGMENTS.map(s => <option key={s.id}>{s.name}</option>)}
      </select>
      <label style={{ fontSize: 13, color: TEXT_3 }}>归因模型</label>
      <div style={{ display: 'flex', gap: 4 }}>
        {models.map(m => (
          <button
            key={m.value}
            onClick={() => onAttributionChange(m.value)}
            style={{
              padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: attribution === m.value ? BRAND : BG_2,
              color: attribution === m.value ? '#fff' : TEXT_3,
              fontSize: 12, fontWeight: 600, transition: 'all .15s',
            }}
          >
            {m.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function KPICard({ label, value, subLabel, subValue, color }: {
  label: string; value: string; subLabel?: string; subValue?: string; color?: string;
}) {
  return (
    <div style={{
      flex: 1, minWidth: 140, background: BG_1, borderRadius: 10, padding: '16px 18px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || TEXT_1 }}>{value}</div>
      {subLabel && (
        <div style={{ fontSize: 11, color: TEXT_4, marginTop: 6 }}>
          {subLabel}: <span style={{ color: TEXT_3 }}>{subValue}</span>
        </div>
      )}
    </div>
  );
}

function ROIBar({ label, value, maxValue, color, investment, revenue }: {
  label: string; value: number; maxValue: number; color: string; investment: number; revenue: number;
}) {
  const pct = Math.min((value / maxValue) * 100, 100);
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 13, color: TEXT_2 }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color }}>{value.toFixed(1)}x</span>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: BG_2 }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 4, background: color, transition: 'width .3s' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
        <span style={{ fontSize: 10, color: TEXT_4 }}>投入 {(investment / 10000).toFixed(1)}万</span>
        <span style={{ fontSize: 10, color: TEXT_4 }}>产出 {(revenue / 10000).toFixed(1)}万</span>
      </div>
    </div>
  );
}

function SegmentRankCard({ segments }: { segments: SegmentROI[] }) {
  const sorted = [...segments].sort((a, b) => b.roi - a.roi);
  const maxROI = Math.max(...sorted.map(s => s.roi));
  return (
    <div style={{
      flex: 1, minWidth: 280, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>人群ROI排行</h3>
      {sorted.map((seg, i) => {
        const colors = [GREEN, BLUE, BRAND, PURPLE, YELLOW];
        return (
          <div key={seg.id} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 13, color: TEXT_2 }}>
                <span style={{ color: TEXT_4, marginRight: 6 }}>#{i + 1}</span>
                {seg.name}
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: colors[i] }}>{seg.roi.toFixed(1)}x</span>
            </div>
            <div style={{ height: 6, borderRadius: 3, background: BG_2 }}>
              <div style={{
                width: `${(seg.roi / maxROI) * 100}%`, height: '100%', borderRadius: 3,
                background: colors[i], transition: 'width .3s',
              }} />
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 2 }}>
              <span style={{ fontSize: 10, color: TEXT_4 }}>客单价 {seg.avgOrderValue}元</span>
              <span style={{ fontSize: 10, color: TEXT_4 }}>留存率 {(seg.retention * 100).toFixed(0)}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CampaignRankCard({ campaigns }: { campaigns: CampaignROI[] }) {
  const sorted = [...campaigns].sort((a, b) => b.roi - a.roi);
  const statusColors: Record<string, string> = { '进行中': GREEN, '已结束': TEXT_4, '计划中': BLUE };
  return (
    <div style={{
      flex: 1, minWidth: 280, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>活动ROI排行</h3>
      {sorted.map((camp, i) => (
        <div key={camp.id} style={{
          padding: '10px 0', borderBottom: i < sorted.length - 1 ? `1px solid ${BG_2}` : 'none',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12, color: TEXT_4 }}>#{i + 1}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{camp.name}</span>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: statusColors[camp.status] + '22',
                color: statusColors[camp.status],
              }}>{camp.status}</span>
            </div>
            <span style={{ fontSize: 15, fontWeight: 700, color: BRAND }}>{camp.roi.toFixed(1)}x</span>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <span style={{ fontSize: 11, color: TEXT_4 }}>渠道: {camp.channel}</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>投入: {(camp.investment / 10000).toFixed(1)}万</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>产出: {(camp.revenue / 10000).toFixed(1)}万</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function AttributionPathCard({ paths }: { paths: AttributionPath[] }) {
  const nodes = Array.from(new Set(paths.flatMap(p => [p.from, p.to])));
  const maxVal = Math.max(...paths.map(p => p.value));

  return (
    <div style={{
      flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>归因路径分析</h3>
      <div style={{ display: 'flex', gap: 20, marginBottom: 16, flexWrap: 'wrap' }}>
        {nodes.map((node, i) => {
          const nodeColors = [BLUE, GREEN, BRAND, PURPLE, YELLOW, '#13c2c2', '#eb2f96', '#2f54eb', '#fa8c16', '#a0d911'];
          return (
            <span key={node} style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 4,
              background: nodeColors[i % nodeColors.length] + '22',
              color: nodeColors[i % nodeColors.length],
              fontWeight: 600,
            }}>{node}</span>
          );
        })}
      </div>
      {paths.map((path, i) => {
        const width = (path.value / maxVal) * 100;
        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
          }}>
            <span style={{ fontSize: 11, color: TEXT_3, minWidth: 80, textAlign: 'right' }}>{path.from}</span>
            <div style={{ flex: 1, position: 'relative', height: 16 }}>
              <div style={{
                position: 'absolute', left: 0, top: 4, height: 8, borderRadius: 4,
                width: `${width}%`, background: `linear-gradient(90deg, ${BRAND}88, ${BRAND})`,
                transition: 'width .3s',
              }} />
            </div>
            <span style={{ fontSize: 11, color: TEXT_3, minWidth: 80 }}>{path.to}</span>
            <span style={{ fontSize: 11, color: TEXT_2, fontWeight: 600, minWidth: 40, textAlign: 'right' }}>{path.value}</span>
          </div>
        );
      })}
      <div style={{ fontSize: 11, color: TEXT_4, marginTop: 12, textAlign: 'center' }}>
        * 数值表示该路径的转化用户数
      </div>
    </div>
  );
}

function ProfitTrendCard({ trends }: { trends: ProfitTrend[] }) {
  const maxVal = Math.max(...trends.map(t => Math.max(t.revenue, t.investment, t.profit)));
  const chartH = 180;

  return (
    <div style={{
      flex: 1, minWidth: 340, background: BG_1, borderRadius: 10, padding: 18,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>利润贡献趋势</h3>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 0, height: chartH, padding: '0 8px' }}>
        {trends.map((t, i) => {
          const revH = (t.revenue / maxVal) * (chartH - 30);
          const invH = (t.investment / maxVal) * (chartH - 30);
          const profH = (t.profit / maxVal) * (chartH - 30);
          return (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: chartH - 30 }}>
                <div style={{
                  width: 12, height: revH, borderRadius: '3px 3px 0 0',
                  background: BLUE, opacity: 0.8,
                }} title={`产出 ${(t.revenue / 10000).toFixed(1)}万`} />
                <div style={{
                  width: 12, height: profH, borderRadius: '3px 3px 0 0',
                  background: GREEN, opacity: 0.8,
                }} title={`利润 ${(t.profit / 10000).toFixed(1)}万`} />
                <div style={{
                  width: 12, height: invH, borderRadius: '3px 3px 0 0',
                  background: RED, opacity: 0.5,
                }} title={`投入 ${(t.investment / 10000).toFixed(1)}万`} />
              </div>
              <span style={{ fontSize: 10, color: TEXT_4, marginTop: 4 }}>{t.month.slice(5)}</span>
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 12 }}>
        <span style={{ fontSize: 11, color: BLUE }}>--- 产出</span>
        <span style={{ fontSize: 11, color: GREEN }}>--- 利润</span>
        <span style={{ fontSize: 11, color: RED }}>--- 投入</span>
      </div>
      <div style={{ marginTop: 12 }}>
        {trends.map((t, i) => (
          <div key={i} style={{
            display: 'flex', justifyContent: 'space-between', padding: '4px 0',
            borderBottom: i < trends.length - 1 ? `1px solid ${BG_2}` : 'none',
          }}>
            <span style={{ fontSize: 11, color: TEXT_3 }}>{t.month}</span>
            <span style={{ fontSize: 11, color: BLUE }}>产出 {(t.revenue / 10000).toFixed(1)}万</span>
            <span style={{ fontSize: 11, color: RED }}>投入 {(t.investment / 10000).toFixed(1)}万</span>
            <span style={{ fontSize: 11, color: GREEN, fontWeight: 600 }}>利润 {(t.profit / 10000).toFixed(1)}万</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function ROIOverviewPage() {
  const [attribution, setAttribution] = useState<AttributionModel>('multi-touch');

  const totals = useMemo(() => {
    const totalInvestment = MOCK_CHANNELS.reduce((s, c) => s + c.investment, 0);
    const totalRevenue = MOCK_CHANNELS.reduce((s, c) => s + c.revenue, 0);
    const overallROI = totalRevenue / totalInvestment;
    const profitContribution = totalRevenue - totalInvestment;
    const avgCAC = MOCK_CHANNELS.reduce((s, c) => s + c.cac, 0) / MOCK_CHANNELS.length;
    const avgLTV = MOCK_CHANNELS.reduce((s, c) => s + c.ltv, 0) / MOCK_CHANNELS.length;
    return { totalInvestment, totalRevenue, overallROI, profitContribution, avgCAC, avgLTV };
  }, []);

  const maxChannelROI = Math.max(...MOCK_CHANNELS.map(c => c.roi));

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>全渠道ROI总览</h2>

      {/* 顶部筛选 */}
      <FilterBar attribution={attribution} onAttributionChange={setAttribution} />

      {/* KPI Cards */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <KPICard label="总投入" value={`${(totals.totalInvestment / 10000).toFixed(1)}万`} subLabel="环比" subValue="+6.8%" />
        <KPICard label="总产出" value={`${(totals.totalRevenue / 10000).toFixed(1)}万`} subLabel="环比" subValue="+12.3%" color={BLUE} />
        <KPICard label="综合ROI" value={`${totals.overallROI.toFixed(1)}x`} subLabel="目标" subValue="3.5x" color={BRAND} />
        <KPICard label="利润贡献" value={`${(totals.profitContribution / 10000).toFixed(1)}万`} subLabel="利润率" subValue={`${((totals.profitContribution / totals.totalRevenue) * 100).toFixed(0)}%`} color={GREEN} />
        <KPICard label="平均CAC" value={`${totals.avgCAC.toFixed(0)}元`} subLabel="环比" subValue="-5.2%" color={YELLOW} />
        <KPICard label="平均LTV" value={`${totals.avgLTV.toFixed(0)}元`} subLabel="LTV/CAC" subValue={`${(totals.avgLTV / totals.avgCAC).toFixed(1)}x`} color={PURPLE} />
      </div>

      {/* 中部三栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        {/* 渠道ROI排行 */}
        <div style={{
          flex: 1, minWidth: 280, background: BG_1, borderRadius: 10, padding: 18,
          border: `1px solid ${BG_2}`,
        }}>
          <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700 }}>渠道ROI排行</h3>
          {[...MOCK_CHANNELS].sort((a, b) => b.roi - a.roi).map(ch => (
            <ROIBar
              key={ch.id}
              label={ch.name}
              value={ch.roi}
              maxValue={maxChannelROI}
              color={ch.color}
              investment={ch.investment}
              revenue={ch.revenue}
            />
          ))}
        </div>

        {/* 人群ROI排行 */}
        <SegmentRankCard segments={MOCK_SEGMENTS} />

        {/* 活动ROI排行 */}
        <CampaignRankCard campaigns={MOCK_CAMPAIGNS} />
      </div>

      {/* 下部双栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <AttributionPathCard paths={MOCK_ATTRIBUTION_PATHS} />
        <ProfitTrendCard trends={MOCK_PROFIT_TREND} />
      </div>
    </div>
  );
}
