/**
 * GrowthDashboardPage — 增长中心仪表盘
 * HQ 增长分析总览：KPI、趋势、雷达图、门店排行、预警、Agent建议
 */
import { useState } from 'react';

// ---- 颜色常量 ----
const BG_0 = '#0B1A20';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
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

interface KPICard {
  label: string;
  value: string;
  change: number; // 百分比变化
  unit?: string;
}

interface TrendPoint {
  date: string;
  newCustomers: number;
  repeatRate: number;
  activeRate: number;
}

interface RadarDimension {
  label: string;
  value: number; // 0-100
}

interface StoreRankItem {
  rank: number;
  storeName: string;
  newCustomers: number;
  repeatRate: number;
  revenue: number;
  trend: 'up' | 'down' | 'flat';
}

interface AlertItem {
  id: string;
  severity: 'high' | 'medium' | 'low';
  title: string;
  detail: string;
  store: string;
}

interface AgentSuggestion {
  id: string;
  type: string;
  title: string;
  detail: string;
  expectedImpact: string;
  confidence: number;
}

interface CampaignRow {
  id: string;
  name: string;
  type: string;
  startDate: string;
  endDate: string;
  targetCount: number;
  reachCount: number;
  convertCount: number;
  roi: number;
  status: '进行中' | '已结束' | '待启动';
}

type TimeRange = '今日' | '本周' | '本月' | '近30天' | '近90天';
type Region = '全部区域' | '华中区' | '华东区' | '华南区' | '西南区';
type Brand = '全部品牌' | '尝在一起' | '最黔线' | '尚宫厨';

// ---- Mock 数据 ----

const MOCK_KPIS: KPICard[] = [
  { label: '新客数', value: '2,847', change: 12.3 },
  { label: '首单转复购率', value: '34.2%', change: 2.8 },
  { label: '会员活跃率', value: '61.7%', change: -1.5 },
  { label: '裂变率', value: '8.4%', change: 3.2 },
  { label: '活动ROI', value: '3.6', change: 0.8, unit: 'x' },
];

const MOCK_TREND: TrendPoint[] = [
  { date: '03-20', newCustomers: 380, repeatRate: 31.2, activeRate: 58.4 },
  { date: '03-21', newCustomers: 420, repeatRate: 32.1, activeRate: 59.2 },
  { date: '03-22', newCustomers: 395, repeatRate: 33.0, activeRate: 60.1 },
  { date: '03-23', newCustomers: 510, repeatRate: 33.8, activeRate: 61.0 },
  { date: '03-24', newCustomers: 460, repeatRate: 34.5, activeRate: 61.5 },
  { date: '03-25', newCustomers: 430, repeatRate: 34.2, activeRate: 61.7 },
  { date: '03-26', newCustomers: 452, repeatRate: 34.8, activeRate: 62.3 },
];

const MOCK_RADAR: RadarDimension[] = [
  { label: '拉新能力', value: 78 },
  { label: '留存能力', value: 65 },
  { label: '复购驱动', value: 72 },
  { label: '客单提升', value: 58 },
  { label: '裂变传播', value: 45 },
  { label: '活动效率', value: 82 },
];

const MOCK_STORE_RANK: StoreRankItem[] = [
  { rank: 1, storeName: '芙蓉路店', newCustomers: 523, repeatRate: 38.2, revenue: 287600, trend: 'up' },
  { rank: 2, storeName: '万达广场店', newCustomers: 487, repeatRate: 36.5, revenue: 265300, trend: 'up' },
  { rank: 3, storeName: '梅溪湖店', newCustomers: 412, repeatRate: 35.1, revenue: 234800, trend: 'flat' },
  { rank: 4, storeName: '五一广场店', newCustomers: 398, repeatRate: 33.7, revenue: 221500, trend: 'down' },
  { rank: 5, storeName: '星沙店', newCustomers: 356, repeatRate: 31.2, revenue: 198700, trend: 'up' },
  { rank: 6, storeName: '河西大学城店', newCustomers: 341, repeatRate: 30.8, revenue: 187200, trend: 'flat' },
  { rank: 7, storeName: '开福寺店', newCustomers: 330, repeatRate: 29.5, revenue: 176400, trend: 'down' },
];

const MOCK_ALERTS: AlertItem[] = [
  { id: 'a1', severity: 'high', title: '复购率骤降', detail: '近7天首单转复购率从38%降至28%，下降10个百分点', store: '五一广场店' },
  { id: 'a2', severity: 'medium', title: '新客获取成本上升', detail: '本周获客成本较上周上升22%，达到¥18.5/人', store: '全品牌' },
  { id: 'a3', severity: 'low', title: '会员活跃率波动', detail: '周末活跃率低于工作日平均水平5个百分点', store: '河西大学城店' },
];

const MOCK_SUGGESTIONS: AgentSuggestion[] = [
  { id: 's1', type: '复购提升', title: '对30天未复购新客发放回归券', detail: '目标人群1,247人，建议发放满80减15回归券，预计召回率18%', expectedImpact: '+¥33,600', confidence: 0.82 },
  { id: 's2', type: '裂变激励', title: '启动老带新裂变活动', detail: '高频复购客户中有342人社交活跃度高，建议推送分享得券活动', expectedImpact: '+156新客', confidence: 0.76 },
  { id: 's3', type: '沉默唤醒', title: '沉睡客户短信唤醒', detail: '60-90天未到店客户823人，建议分时段发送个性化短信', expectedImpact: '+¥12,400', confidence: 0.71 },
];

const MOCK_CAMPAIGNS: CampaignRow[] = [
  { id: 'c1', name: '春季回归季', type: '回归券', startDate: '03-15', endDate: '03-31', targetCount: 2400, reachCount: 2156, convertCount: 387, roi: 4.2, status: '进行中' },
  { id: 'c2', name: '新客首单立减', type: '新客券', startDate: '03-01', endDate: '03-31', targetCount: 5000, reachCount: 4230, convertCount: 1247, roi: 3.8, status: '进行中' },
  { id: 'c3', name: '会员日双倍积分', type: '积分活动', startDate: '03-20', endDate: '03-20', targetCount: 8600, reachCount: 5420, convertCount: 892, roi: 2.9, status: '已结束' },
  { id: 'c4', name: '老带新裂变', type: '裂变活动', startDate: '03-10', endDate: '03-25', targetCount: 1200, reachCount: 980, convertCount: 156, roi: 5.1, status: '已结束' },
  { id: 'c5', name: '清明节套餐', type: '限时套餐', startDate: '04-03', endDate: '04-06', targetCount: 3000, reachCount: 0, convertCount: 0, roi: 0, status: '待启动' },
];

// ---- 组件 ----

function FilterBar({ brand, setBrand, timeRange, setTimeRange, region, setRegion }: {
  brand: Brand; setBrand: (v: Brand) => void;
  timeRange: TimeRange; setTimeRange: (v: TimeRange) => void;
  region: Region; setRegion: (v: Region) => void;
}) {
  const selectStyle: React.CSSProperties = {
    background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none',
    cursor: 'pointer', minWidth: 100,
  };
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
      background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`, marginBottom: 16,
      flexWrap: 'wrap',
    }}>
      <span style={{ fontSize: 13, color: TEXT_3, fontWeight: 600 }}>筛选</span>
      <select value={brand} onChange={e => setBrand(e.target.value as Brand)} style={selectStyle}>
        <option>全部品牌</option>
        <option>尝在一起</option>
        <option>最黔线</option>
        <option>尚宫厨</option>
      </select>
      <select value={timeRange} onChange={e => setTimeRange(e.target.value as TimeRange)} style={selectStyle}>
        <option>今日</option>
        <option>本周</option>
        <option>本月</option>
        <option>近30天</option>
        <option>近90天</option>
      </select>
      <select value={region} onChange={e => setRegion(e.target.value as Region)} style={selectStyle}>
        <option>全部区域</option>
        <option>华中区</option>
        <option>华东区</option>
        <option>华南区</option>
        <option>西南区</option>
      </select>
      <select style={selectStyle}>
        <option>全部门店组</option>
        <option>直营店</option>
        <option>加盟店</option>
        <option>旗舰店</option>
      </select>
    </div>
  );
}

function KPICardsRow({ kpis }: { kpis: KPICard[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${kpis.length}, 1fr)`, gap: 12, marginBottom: 16 }}>
      {kpis.map((kpi, i) => (
        <div key={i} style={{
          background: BG_1, borderRadius: 10, padding: '16px 18px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: TEXT_1 }}>
            {kpi.value}{kpi.unit ? <span style={{ fontSize: 14, color: TEXT_3, marginLeft: 2 }}>{kpi.unit}</span> : null}
          </div>
          <div style={{
            fontSize: 12, marginTop: 4,
            color: kpi.change >= 0 ? GREEN : RED,
          }}>
            {kpi.change >= 0 ? '+' : ''}{kpi.change}% 较上期
          </div>
        </div>
      ))}
    </div>
  );
}

function TrendChart({ data }: { data: TrendPoint[] }) {
  const maxCustomers = Math.max(...data.map(d => d.newCustomers));
  const chartHeight = 180;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 16 }}>增长趋势</div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, fontSize: 11 }}>
        <span style={{ color: BRAND }}>--- 新客数</span>
        <span style={{ color: GREEN }}>--- 复购率%</span>
        <span style={{ color: BLUE }}>--- 活跃率%</span>
      </div>
      {/* 简化折线图 - 使用 SVG */}
      <svg width="100%" height={chartHeight} viewBox={`0 0 ${data.length * 80} ${chartHeight}`} style={{ overflow: 'visible' }}>
        {/* 网格线 */}
        {[0, 1, 2, 3, 4].map(i => (
          <line key={i} x1={0} y1={i * (chartHeight / 4)} x2={data.length * 80} y2={i * (chartHeight / 4)}
            stroke={BG_2} strokeWidth={1} />
        ))}
        {/* 新客数折线 */}
        <polyline
          fill="none" stroke={BRAND} strokeWidth={2}
          points={data.map((d, i) => `${i * 80 + 40},${chartHeight - (d.newCustomers / maxCustomers) * (chartHeight - 20) - 10}`).join(' ')}
        />
        {data.map((d, i) => (
          <circle key={`nc-${i}`} cx={i * 80 + 40} cy={chartHeight - (d.newCustomers / maxCustomers) * (chartHeight - 20) - 10}
            r={3} fill={BRAND} />
        ))}
        {/* 复购率折线 */}
        <polyline
          fill="none" stroke={GREEN} strokeWidth={2}
          points={data.map((d, i) => `${i * 80 + 40},${chartHeight - (d.repeatRate / 50) * (chartHeight - 20) - 10}`).join(' ')}
        />
        {data.map((d, i) => (
          <circle key={`rr-${i}`} cx={i * 80 + 40} cy={chartHeight - (d.repeatRate / 50) * (chartHeight - 20) - 10}
            r={3} fill={GREEN} />
        ))}
        {/* 活跃率折线 */}
        <polyline
          fill="none" stroke={BLUE} strokeWidth={2}
          points={data.map((d, i) => `${i * 80 + 40},${chartHeight - (d.activeRate / 80) * (chartHeight - 20) - 10}`).join(' ')}
        />
        {data.map((d, i) => (
          <circle key={`ar-${i}`} cx={i * 80 + 40} cy={chartHeight - (d.activeRate / 80) * (chartHeight - 20) - 10}
            r={3} fill={BLUE} />
        ))}
        {/* X 轴标签 */}
        {data.map((d, i) => (
          <text key={`lbl-${i}`} x={i * 80 + 40} y={chartHeight + 2} textAnchor="middle" fill={TEXT_4} fontSize={10}>
            {d.date}
          </text>
        ))}
      </svg>
    </div>
  );
}

function RadarChart({ dimensions }: { dimensions: RadarDimension[] }) {
  const cx = 130, cy = 110, r = 80;
  const n = dimensions.length;
  const angleStep = (2 * Math.PI) / n;

  const getPoint = (index: number, value: number) => {
    const angle = angleStep * index - Math.PI / 2;
    const dist = (value / 100) * r;
    return { x: cx + dist * Math.cos(angle), y: cy + dist * Math.sin(angle) };
  };

  const polygonPoints = dimensions.map((d, i) => {
    const p = getPoint(i, d.value);
    return `${p.x},${p.y}`;
  }).join(' ');


  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`, minWidth: 300,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>增长健康雷达</div>
      <svg width={260} height={240} viewBox="0 0 260 240">
        {/* 背景多边形 */}
        {[20, 40, 60, 80, 100].map(v => (
          <polygon key={v}
            points={dimensions.map((_, i) => { const p = getPoint(i, v); return `${p.x},${p.y}`; }).join(' ')}
            fill="none" stroke={BG_2} strokeWidth={1}
          />
        ))}
        {/* 轴线 */}
        {dimensions.map((_, i) => {
          const p = getPoint(i, 100);
          return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke={BG_2} strokeWidth={1} />;
        })}
        {/* 数据多边形 */}
        <polygon points={polygonPoints} fill={BRAND + '33'} stroke={BRAND} strokeWidth={2} />
        {/* 数据点 */}
        {dimensions.map((d, i) => {
          const p = getPoint(i, d.value);
          return <circle key={i} cx={p.x} cy={p.y} r={4} fill={BRAND} />;
        })}
        {/* 标签 */}
        {dimensions.map((d, i) => {
          const p = getPoint(i, 120);
          return (
            <text key={i} x={p.x} y={p.y} textAnchor="middle" dominantBaseline="middle"
              fill={TEXT_3} fontSize={11}>
              {d.label} {d.value}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

function StoreRankTable({ stores }: { stores: StoreRankItem[] }) {
  const trendIcons: Record<string, { symbol: string; color: string }> = {
    up: { symbol: '\u2191', color: GREEN },
    down: { symbol: '\u2193', color: RED },
    flat: { symbol: '-', color: TEXT_4 },
  };
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>门店排行榜</div>
      <div style={{ fontSize: 11, color: TEXT_4, display: 'grid', gridTemplateColumns: '36px 1fr 70px 70px 90px 30px', gap: 4, padding: '0 0 8px', borderBottom: `1px solid ${BG_2}` }}>
        <span>排名</span><span>门店</span><span>新客数</span><span>复购率</span><span>营收</span><span>趋势</span>
      </div>
      {stores.map(s => {
        const t = trendIcons[s.trend];
        return (
          <div key={s.rank} style={{
            display: 'grid', gridTemplateColumns: '36px 1fr 70px 70px 90px 30px',
            gap: 4, padding: '8px 0', borderBottom: `1px solid ${BG_2}`,
            fontSize: 13, alignItems: 'center',
          }}>
            <span style={{
              width: 24, height: 24, borderRadius: 12, display: 'inline-flex',
              alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700,
              background: s.rank <= 3 ? BRAND + '22' : BG_2,
              color: s.rank <= 3 ? BRAND : TEXT_4,
            }}>{s.rank}</span>
            <span style={{ color: TEXT_1, fontWeight: 500 }}>{s.storeName}</span>
            <span style={{ color: TEXT_2 }}>{s.newCustomers}</span>
            <span style={{ color: TEXT_2 }}>{s.repeatRate}%</span>
            <span style={{ color: TEXT_2 }}>\u00A5{(s.revenue / 10000).toFixed(1)}万</span>
            <span style={{ color: t.color, fontWeight: 700 }}>{t.symbol}</span>
          </div>
        );
      })}
    </div>
  );
}

function AlertCards({ alerts }: { alerts: AlertItem[] }) {
  const sevColors: Record<string, string> = { high: RED, medium: YELLOW, low: BLUE };
  const sevLabels: Record<string, string> = { high: '严重', medium: '警告', low: '提示' };
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>预警卡片</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {alerts.map(a => (
          <div key={a.id} style={{
            padding: '12px 14px', borderRadius: 8,
            background: sevColors[a.severity] + '11',
            borderLeft: `3px solid ${sevColors[a.severity]}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
                background: sevColors[a.severity] + '22', color: sevColors[a.severity],
              }}>{sevLabels[a.severity]}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{a.title}</span>
            </div>
            <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 2 }}>{a.detail}</div>
            <div style={{ fontSize: 11, color: TEXT_4 }}>门店: {a.store}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentSuggestionsPanel({ suggestions }: { suggestions: AgentSuggestion[] }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 15, fontWeight: 700 }}>Agent 建议</span>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 10,
          background: PURPLE + '22', color: PURPLE, fontWeight: 600,
        }}>AI</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {suggestions.map(s => (
          <div key={s.id} style={{
            padding: '12px 14px', borderRadius: 8,
            background: BG_2, border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
                background: BRAND + '22', color: BRAND,
              }}>{s.type}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{s.title}</span>
            </div>
            <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 6 }}>{s.detail}</div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: GREEN }}>{s.expectedImpact}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 40, height: 4, borderRadius: 2, background: BG_0 }}>
                  <div style={{ width: `${s.confidence * 100}%`, height: '100%', borderRadius: 2, background: BRAND }} />
                </div>
                <span style={{ fontSize: 10, color: TEXT_4 }}>{Math.round(s.confidence * 100)}%</span>
              </div>
            </div>
            <button style={{
              marginTop: 8, padding: '4px 14px', borderRadius: 6, border: 'none',
              background: BRAND + '22', color: BRAND, fontSize: 11, fontWeight: 600,
              cursor: 'pointer',
            }}>采纳建议</button>
          </div>
        ))}
      </div>
    </div>
  );
}

function CampaignTable({ campaigns }: { campaigns: CampaignRow[] }) {
  const statusColors: Record<string, string> = {
    '进行中': GREEN,
    '已结束': TEXT_4,
    '待启动': BLUE,
  };
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>活动表现</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['活动名称', '类型', '时间', '目标人数', '触达人数', '转化人数', 'ROI', '状态'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {campaigns.map(c => (
              <tr key={c.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{c.name}</td>
                <td style={{ padding: '10px', color: TEXT_3 }}>{c.type}</td>
                <td style={{ padding: '10px', color: TEXT_3, whiteSpace: 'nowrap' }}>{c.startDate} ~ {c.endDate}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{c.targetCount.toLocaleString()}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{c.reachCount.toLocaleString()}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{c.convertCount.toLocaleString()}</td>
                <td style={{ padding: '10px', color: c.roi >= 3 ? GREEN : c.roi >= 2 ? YELLOW : TEXT_3, fontWeight: 600 }}>
                  {c.roi > 0 ? `${c.roi}x` : '-'}
                </td>
                <td style={{ padding: '10px' }}>
                  <span style={{
                    fontSize: 11, padding: '2px 8px', borderRadius: 10,
                    background: statusColors[c.status] + '22',
                    color: statusColors[c.status],
                    fontWeight: 600,
                  }}>{c.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function GrowthDashboardPage() {
  const [brand, setBrand] = useState<Brand>('全部品牌');
  const [timeRange, setTimeRange] = useState<TimeRange>('近30天');
  const [region, setRegion] = useState<Region>('全部区域');

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>增长中心</h2>

      {/* 顶部全局筛选栏 */}
      <FilterBar
        brand={brand} setBrand={setBrand}
        timeRange={timeRange} setTimeRange={setTimeRange}
        region={region} setRegion={setRegion}
      />

      {/* KPI Cards */}
      <KPICardsRow kpis={MOCK_KPIS} />

      {/* 中部双栏: 趋势图 + 雷达图 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <TrendChart data={MOCK_TREND} />
        <RadarChart dimensions={MOCK_RADAR} />
      </div>

      {/* 下部三栏: 排行榜 + 预警 + Agent建议 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <StoreRankTable stores={MOCK_STORE_RANK} />
        <AlertCards alerts={MOCK_ALERTS} />
        <AgentSuggestionsPanel suggestions={MOCK_SUGGESTIONS} />
      </div>

      {/* 底部: 活动表现 */}
      <CampaignTable campaigns={MOCK_CAMPAIGNS} />
    </div>
  );
}
