/**
 * CompetitorCenterPage — 竞对中心
 * 路由: /hq/market-intel/competitors
 * 竞对卡片 + 动态时间线 + 价格对比 + 雷达基准图
 */
import { useState } from 'react';

const BG_0 = '#0f1923';
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

type TabKey = 'cards' | 'timeline' | 'price' | 'radar';

interface Competitor {
  id: string;
  name: string;
  logo: string;
  category: string;
  storeCount: number;
  avgTicket: number;
  rating: number;
  recentAction: string;
  recentActionDate: string;
  threatLevel: 'high' | 'medium' | 'low';
  color: string;
}

interface CompetitorAction {
  id: string;
  competitor: string;
  action: string;
  date: string;
  impact: 'high' | 'medium' | 'low';
  detail: string;
  category: '价格战' | '新品' | '扩张' | '营销' | '品牌升级' | '外卖';
}

interface PriceItem {
  dish: string;
  ours: number;
  competitors: { name: string; price: number }[];
}

interface RadarDimension {
  label: string;
  ours: number;
  competitor: number;
}

const MOCK_COMPETITORS: Competitor[] = [
  { id: 'c1', name: '海底捞', logo: 'H', category: '火锅', storeCount: 1380, avgTicket: 112, rating: 4.5, recentAction: '推出酸汤锅底系列', recentActionDate: '2026-03-25', threatLevel: 'high', color: RED },
  { id: 'c2', name: '西贝', logo: 'X', category: '西北菜', storeCount: 420, avgTicket: 95, rating: 4.3, recentAction: '上线预制菜电商', recentActionDate: '2026-03-24', threatLevel: 'medium', color: BLUE },
  { id: 'c3', name: '太二', logo: 'T', category: '酸菜鱼', storeCount: 500, avgTicket: 78, rating: 4.4, recentAction: '第500家门店开业', recentActionDate: '2026-03-23', threatLevel: 'high', color: GREEN },
  { id: 'c4', name: '费大厨', logo: 'F', category: '湘菜', storeCount: 180, avgTicket: 85, rating: 4.6, recentAction: '推出外卖套餐', recentActionDate: '2026-03-22', threatLevel: 'high', color: BRAND },
  { id: 'c5', name: '望湘园', logo: 'W', category: '湘菜', storeCount: 220, avgTicket: 72, rating: 4.1, recentAction: '品牌视觉升级', recentActionDate: '2026-03-20', threatLevel: 'medium', color: PURPLE },
];

const MOCK_TIMELINE: CompetitorAction[] = [
  { id: 'ta1', competitor: '海底捞', action: '推出酸汤锅底系列', date: '2026-03-25', impact: 'high', detail: '全国门店上线6款酸汤锅底，主打酸汤肥牛、酸汤鱼，定价89-129元。', category: '新品' },
  { id: 'ta2', competitor: '太二', action: '第500家门店开业', date: '2026-03-23', impact: 'high', detail: '成都太古里旗舰店开业，2026年目标新开150家。加速二三线城市下沉。', category: '扩张' },
  { id: 'ta3', competitor: '费大厨', action: '推出外卖专属套餐', date: '2026-03-22', impact: 'medium', detail: '美团上线一人食套餐39.9元，含辣椒炒肉+米饭+小菜+汤。', category: '外卖' },
  { id: 'ta4', competitor: '西贝', action: '上线预制菜电商', date: '2026-03-24', impact: 'medium', detail: '天猫/京东旗舰店首批20个SKU，主打家庭便捷烹饪场景。', category: '新品' },
  { id: 'ta5', competitor: '望湘园', action: '品牌视觉全面升级', date: '2026-03-20', impact: 'low', detail: '新logo"新湘菜"定位，首批10家门店翻新完成。', category: '品牌升级' },
  { id: 'ta6', competitor: '海底捞', action: '会员日全场8折', date: '2026-03-18', impact: 'medium', detail: '每月18日会员日全场8折，针对银卡以上会员。', category: '价格战' },
  { id: 'ta7', competitor: '费大厨', action: '抖音直播卖券', date: '2026-03-16', impact: 'medium', detail: '抖音直播卖100元代金券（售价69元），单场销售额破200万。', category: '营销' },
  { id: 'ta8', competitor: '太二', action: '联名IP主题店', date: '2026-03-15', impact: 'low', detail: '与故宫文创联名，推出限定包装和主题门店装修。', category: '营销' },
];

const MOCK_PRICES: PriceItem[] = [
  { dish: '辣椒炒肉', ours: 48, competitors: [{ name: '费大厨', price: 58 }, { name: '望湘园', price: 42 }] },
  { dish: '剁椒鱼头', ours: 88, competitors: [{ name: '费大厨', price: 98 }, { name: '望湘园', price: 78 }] },
  { dish: '小炒黄牛肉', ours: 58, competitors: [{ name: '费大厨', price: 68 }, { name: '望湘园', price: 52 }] },
  { dish: '酸汤肥牛', ours: 68, competitors: [{ name: '海底捞', price: 89 }, { name: '费大厨', price: 0 }] },
  { dish: '酸菜鱼', ours: 78, competitors: [{ name: '太二', price: 69 }, { name: '望湘园', price: 62 }] },
  { dish: '一人食套餐', ours: 42, competitors: [{ name: '费大厨', price: 39.9 }, { name: '望湘园', price: 35 }] },
  { dish: '米饭', ours: 3, competitors: [{ name: '费大厨', price: 3 }, { name: '太二', price: 0 }, { name: '望湘园', price: 2 }] },
  { dish: '人均消费', ours: 65, competitors: [{ name: '海底捞', price: 112 }, { name: '西贝', price: 95 }, { name: '太二', price: 78 }, { name: '费大厨', price: 85 }, { name: '望湘园', price: 72 }] },
];

const MOCK_RADAR: RadarDimension[] = [
  { label: '品牌知名度', ours: 55, competitor: 92 },
  { label: '菜品创新', ours: 72, competitor: 68 },
  { label: '性价比', ours: 85, competitor: 45 },
  { label: '服务质量', ours: 68, competitor: 95 },
  { label: '门店覆盖', ours: 35, competitor: 88 },
  { label: '会员粘性', ours: 62, competitor: 75 },
  { label: '外卖体验', ours: 58, competitor: 72 },
  { label: '营销能力', ours: 45, competitor: 82 },
];

function CompetitorCards({ competitors }: { competitors: Competitor[] }) {
  const threatColors: Record<string, string> = { high: RED, medium: YELLOW, low: GREEN };
  const threatLabels: Record<string, string> = { high: '高威胁', medium: '中威胁', low: '低威胁' };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
      {competitors.map(c => (
        <div key={c.id} style={{
          background: BG_1, borderRadius: 10, padding: 16,
          border: `1px solid ${BG_2}`, cursor: 'pointer',
          borderTop: `3px solid ${c.color}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{
                width: 40, height: 40, borderRadius: 8, background: c.color + '22',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 18, fontWeight: 800, color: c.color,
              }}>{c.logo}</div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{c.name}</div>
                <div style={{ fontSize: 11, color: TEXT_3 }}>{c.category}</div>
              </div>
            </div>
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 4,
              background: threatColors[c.threatLevel] + '22', color: threatColors[c.threatLevel], fontWeight: 600,
            }}>{threatLabels[c.threatLevel]}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 10, color: TEXT_4 }}>门店数</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{c.storeCount.toLocaleString()}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: TEXT_4 }}>人均消费</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{'\u00A5'}{c.avgTicket}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: TEXT_4 }}>评分</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: c.rating >= 4.4 ? GREEN : YELLOW }}>{c.rating}</div>
            </div>
          </div>
          <div style={{
            padding: '8px 10px', background: BG_2, borderRadius: 6,
            borderLeft: `3px solid ${c.color}44`,
          }}>
            <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 2 }}>最新动态 · {c.recentActionDate}</div>
            <div style={{ fontSize: 12, color: TEXT_1, fontWeight: 500 }}>{c.recentAction}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function ActionTimeline({ actions }: { actions: CompetitorAction[] }) {
  const impactColors: Record<string, string> = { high: RED, medium: YELLOW, low: TEXT_4 };
  const catColors: Record<string, string> = { '价格战': RED, '新品': GREEN, '扩张': BLUE, '营销': PURPLE, '品牌升级': CYAN, '外卖': BRAND };
  const competitorColors: Record<string, string> = { '海底捞': RED, '西贝': BLUE, '太二': GREEN, '费大厨': BRAND, '望湘园': PURPLE };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>竞对动态时间线</h3>
      {actions.map((a, i) => (
        <div key={a.id} style={{
          position: 'relative', paddingLeft: 24, paddingBottom: 16,
          borderLeft: i < actions.length - 1 ? `2px solid ${BG_2}` : '2px solid transparent',
          marginLeft: 8,
        }}>
          <div style={{
            position: 'absolute', left: -6, top: 2, width: 12, height: 12, borderRadius: '50%',
            background: impactColors[a.impact], border: `2px solid ${BG_1}`,
          }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 4,
              background: (competitorColors[a.competitor] || TEXT_4) + '22',
              color: competitorColors[a.competitor] || TEXT_4, fontWeight: 600,
            }}>{a.competitor}</span>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: (catColors[a.category] || TEXT_4) + '22',
              color: catColors[a.category] || TEXT_4, fontWeight: 600,
            }}>{a.category}</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>{a.date}</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 4 }}>{a.action}</div>
          <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6 }}>{a.detail}</div>
        </div>
      ))}
    </div>
  );
}

function PriceComparison({ prices }: { prices: PriceItem[] }) {
  const allCompetitors = Array.from(new Set(prices.flatMap(p => p.competitors.map(c => c.name))));

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>价格对比表</h3>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              <th style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>菜品/指标</th>
              <th style={{ textAlign: 'left', padding: '8px 10px', color: BRAND, fontWeight: 600, fontSize: 11 }}>我方</th>
              {allCompetitors.map(name => (
                <th key={name} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {prices.map(p => (
              <tr key={p.dish} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{p.dish}</td>
                <td style={{ padding: '10px', color: BRAND, fontWeight: 700 }}>{'\u00A5'}{p.ours}</td>
                {allCompetitors.map(name => {
                  const comp = p.competitors.find(c => c.name === name);
                  if (!comp || comp.price === 0) return <td key={name} style={{ padding: '10px', color: TEXT_4 }}>-</td>;
                  const diff = comp.price - p.ours;
                  return (
                    <td key={name} style={{ padding: '10px' }}>
                      <span style={{ color: TEXT_2 }}>{'\u00A5'}{comp.price}</span>
                      {diff !== 0 && (
                        <span style={{ fontSize: 10, marginLeft: 4, color: diff > 0 ? GREEN : RED }}>
                          {diff > 0 ? '+' : ''}{diff.toFixed(0)}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{
        marginTop: 12, padding: '8px 12px', background: BG_2, borderRadius: 6,
        fontSize: 11, color: TEXT_3,
      }}>
        绿色数字表示竞对价格高于我方（我方有价格优势），红色表示竞对价格低于我方
      </div>
    </div>
  );
}

function BenchmarkRadar({ dimensions, selectedCompetitor }: { dimensions: RadarDimension[]; selectedCompetitor: string }) {
  const cx = 180, cy = 160, r = 110;
  const n = dimensions.length;
  const angleStep = (2 * Math.PI) / n;

  const getPoint = (index: number, value: number) => {
    const angle = angleStep * index - Math.PI / 2;
    const dist = (value / 100) * r;
    return { x: cx + dist * Math.cos(angle), y: cy + dist * Math.sin(angle) };
  };

  const oursPoints = dimensions.map((d, i) => { const p = getPoint(i, d.ours); return `${p.x},${p.y}`; }).join(' ');
  const compPoints = dimensions.map((d, i) => { const p = getPoint(i, d.competitor); return `${p.x},${p.y}`; }).join(' ');

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>竞对基准雷达图</h3>
        <div style={{ display: 'flex', gap: 12, fontSize: 11 }}>
          <span style={{ color: BRAND }}>--- 我方</span>
          <span style={{ color: BLUE }}>--- {selectedCompetitor}</span>
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <svg width={360} height={340} viewBox="0 0 360 340">
          {/* Background rings */}
          {[20, 40, 60, 80, 100].map(v => (
            <polygon key={v}
              points={dimensions.map((_, i) => { const p = getPoint(i, v); return `${p.x},${p.y}`; }).join(' ')}
              fill="none" stroke={BG_2} strokeWidth={1}
            />
          ))}
          {/* Axes */}
          {dimensions.map((_, i) => {
            const p = getPoint(i, 100);
            return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke={BG_2} strokeWidth={1} />;
          })}
          {/* Our polygon */}
          <polygon points={oursPoints} fill={BRAND + '33'} stroke={BRAND} strokeWidth={2} />
          {dimensions.map((d, i) => {
            const p = getPoint(i, d.ours);
            return <circle key={`o${i}`} cx={p.x} cy={p.y} r={4} fill={BRAND} />;
          })}
          {/* Competitor polygon */}
          <polygon points={compPoints} fill={BLUE + '22'} stroke={BLUE} strokeWidth={2} strokeDasharray="5,3" />
          {dimensions.map((d, i) => {
            const p = getPoint(i, d.competitor);
            return <circle key={`c${i}`} cx={p.x} cy={p.y} r={4} fill={BLUE} />;
          })}
          {/* Labels */}
          {dimensions.map((d, i) => {
            const p = getPoint(i, 125);
            return (
              <text key={i} x={p.x} y={p.y} textAnchor="middle" dominantBaseline="middle"
                fill={TEXT_3} fontSize={11}>
                {d.label}
              </text>
            );
          })}
        </svg>
      </div>
      {/* Score comparison */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 10 }}>
        {dimensions.map((d, i) => {
          const diff = d.ours - d.competitor;
          return (
            <div key={i} style={{ background: BG_2, borderRadius: 6, padding: '8px 10px', textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 2 }}>{d.label}</div>
              <div style={{ display: 'flex', justifyContent: 'center', gap: 8, fontSize: 12 }}>
                <span style={{ color: BRAND, fontWeight: 600 }}>{d.ours}</span>
                <span style={{ color: TEXT_4 }}>vs</span>
                <span style={{ color: BLUE, fontWeight: 600 }}>{d.competitor}</span>
              </div>
              <div style={{ fontSize: 10, color: diff >= 0 ? GREEN : RED, marginTop: 2 }}>
                {diff >= 0 ? '+' : ''}{diff}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function CompetitorCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('cards');
  const [selectedCompetitor, setSelectedCompetitor] = useState('海底捞');

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'cards', label: '竞对卡片' },
    { key: 'timeline', label: '动态时间线' },
    { key: 'price', label: '价格对比' },
    { key: 'radar', label: '基准雷达' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>竞对中心</h2>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {tabs.map(t => (
            <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
              padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: activeTab === t.key ? BRAND : BG_1,
              color: activeTab === t.key ? '#fff' : TEXT_3,
              fontSize: 13, fontWeight: 600,
            }}>{t.label}</button>
          ))}
        </div>
        {activeTab === 'radar' && (
          <select value={selectedCompetitor} onChange={e => setSelectedCompetitor(e.target.value)} style={{
            background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
            color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer', marginLeft: 12,
          }}>
            {MOCK_COMPETITORS.map(c => <option key={c.id}>{c.name}</option>)}
          </select>
        )}
      </div>

      {activeTab === 'cards' && <CompetitorCards competitors={MOCK_COMPETITORS} />}
      {activeTab === 'timeline' && <ActionTimeline actions={MOCK_TIMELINE} />}
      {activeTab === 'price' && <PriceComparison prices={MOCK_PRICES} />}
      {activeTab === 'radar' && <BenchmarkRadar dimensions={MOCK_RADAR} selectedCompetitor={selectedCompetitor} />}
    </div>
  );
}
