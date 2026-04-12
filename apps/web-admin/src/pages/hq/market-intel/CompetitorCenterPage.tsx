/**
 * CompetitorCenterPage — 竞品中心
 * 路由: /hq/market-intel/competitors
 * 接入真实API: /api/v1/analytics/competitive（降级）
 * 竞品列表（名称/类型/距离/评分/人均）+ 新增竞品弹窗
 */
import { useEffect, useState } from 'react';
import { txFetchData } from '../../../api';

// ---- 颜色常量 ----
const BG_PAGE = '#0d1e28';
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

type TabKey = 'list' | 'timeline' | 'price' | 'radar';

interface Competitor {
  id: string;
  name: string;
  logo: string;
  category: string;
  storeCount: number;
  avgTicket: number;
  rating: number;
  distanceKm?: number;
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
  category: string;
}

interface PriceRow {
  dish: string;
  ours: number;
  competitors: { name: string; price: number }[];
}

interface RadarDimension {
  label: string;
  ours: number;
  competitor: number;
}

interface AddCompetitorForm {
  name: string;
  category: string;
  avgTicket: string;
  rating: string;
  distanceKm: string;
}

// ---- 降级数据 ----

const FALLBACK_COMPETITORS: Competitor[] = [
  { id: 'c1', name: '海底捞', logo: 'H', category: '火锅', storeCount: 1380, avgTicket: 112, rating: 4.5, distanceKm: 0.8, recentAction: '推出酸汤锅底系列', recentActionDate: '2026-03-25', threatLevel: 'high', color: RED },
  { id: 'c2', name: '西贝', logo: 'X', category: '西北菜', storeCount: 420, avgTicket: 95, rating: 4.3, distanceKm: 1.2, recentAction: '上线预制菜电商', recentActionDate: '2026-03-24', threatLevel: 'medium', color: BLUE },
  { id: 'c3', name: '太二', logo: 'T', category: '酸菜鱼', storeCount: 500, avgTicket: 78, rating: 4.4, distanceKm: 0.5, recentAction: '第500家门店开业', recentActionDate: '2026-03-23', threatLevel: 'high', color: GREEN },
  { id: 'c4', name: '费大厨', logo: 'F', category: '湘菜', storeCount: 180, avgTicket: 85, rating: 4.6, distanceKm: 0.3, recentAction: '推出外卖套餐', recentActionDate: '2026-03-22', threatLevel: 'high', color: BRAND },
  { id: 'c5', name: '望湘园', logo: 'W', category: '湘菜', storeCount: 220, avgTicket: 72, rating: 4.1, distanceKm: 1.5, recentAction: '品牌视觉升级', recentActionDate: '2026-03-20', threatLevel: 'medium', color: PURPLE },
];

const FALLBACK_TIMELINE: CompetitorAction[] = [
  { id: 'ta1', competitor: '海底捞', action: '推出酸汤锅底系列', date: '2026-03-25', impact: 'high', detail: '全国门店上线6款酸汤锅底，主打酸汤肥牛、酸汤鱼，定价89-129元。', category: '新品' },
  { id: 'ta2', competitor: '太二', action: '第500家门店开业', date: '2026-03-23', impact: 'high', detail: '成都太古里旗舰店开业，2026年目标新开150家，加速下沉市场。', category: '扩张' },
  { id: 'ta3', competitor: '费大厨', action: '推出外卖专属套餐', date: '2026-03-22', impact: 'medium', detail: '美团上线一人食套餐39.9元，含辣椒炒肉+米饭+小菜+汤。', category: '外卖' },
  { id: 'ta4', competitor: '西贝', action: '上线预制菜电商', date: '2026-03-24', impact: 'medium', detail: '天猫/京东旗舰店首批20个SKU，主打家庭便捷烹饪场景。', category: '新品' },
  { id: 'ta5', competitor: '望湘园', action: '品牌视觉全面升级', date: '2026-03-20', impact: 'low', detail: '新logo"新湘菜"定位，首批10家门店翻新完成。', category: '品牌升级' },
];

const FALLBACK_PRICES: PriceRow[] = [
  { dish: '辣椒炒肉', ours: 48, competitors: [{ name: '费大厨', price: 58 }, { name: '望湘园', price: 42 }] },
  { dish: '剁椒鱼头', ours: 88, competitors: [{ name: '费大厨', price: 98 }, { name: '望湘园', price: 78 }] },
  { dish: '酸汤肥牛', ours: 68, competitors: [{ name: '海底捞', price: 89 }, { name: '费大厨', price: 0 }] },
  { dish: '酸菜鱼', ours: 78, competitors: [{ name: '太二', price: 69 }, { name: '望湘园', price: 62 }] },
  { dish: '一人食套餐', ours: 42, competitors: [{ name: '费大厨', price: 39.9 }, { name: '望湘园', price: 35 }] },
  { dish: '人均消费', ours: 65, competitors: [{ name: '海底捞', price: 112 }, { name: '西贝', price: 95 }, { name: '太二', price: 78 }, { name: '费大厨', price: 85 }] },
];

const FALLBACK_RADAR: RadarDimension[] = [
  { label: '品牌知名度', ours: 55, competitor: 92 },
  { label: '菜品创新', ours: 72, competitor: 68 },
  { label: '性价比', ours: 85, competitor: 45 },
  { label: '服务质量', ours: 68, competitor: 95 },
  { label: '门店覆盖', ours: 35, competitor: 88 },
  { label: '会员粘性', ours: 62, competitor: 75 },
  { label: '外卖体验', ours: 58, competitor: 72 },
  { label: '营销能力', ours: 45, competitor: 82 },
];

// ---- API 调用 ----

async function fetchCompetitors(): Promise<Competitor[]> {
  try {
    const res = await txFetchData<{ items?: Competitor[] }>('/api/v1/analytics/competitive');
    if (res.items && res.items.length > 0) return res.items;
  } catch {
    // 降级
  }
  return FALLBACK_COMPETITORS;
}

// ---- 新增竞品弹窗 ----

function AddCompetitorModal({ onClose, onAdd }: { onClose: () => void; onAdd: (c: Competitor) => void }) {
  const [form, setForm] = useState<AddCompetitorForm>({
    name: '', category: '湘菜', avgTicket: '', rating: '', distanceKm: '',
  });
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!form.name.trim()) return;
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/analytics/competitors', {
        method: 'POST',
        body: JSON.stringify({
          name: form.name,
          category: form.category,
          avg_ticket: parseFloat(form.avgTicket) || 0,
          rating: parseFloat(form.rating) || 0,
          distance_km: parseFloat(form.distanceKm) || 0,
        }),
      });
    } catch {
      // 降级：本地添加
    }
    const newComp: Competitor = {
      id: 'new-' + Date.now(),
      name: form.name,
      logo: form.name.slice(0, 1),
      category: form.category,
      storeCount: 0,
      avgTicket: parseFloat(form.avgTicket) || 0,
      rating: parseFloat(form.rating) || 0,
      distanceKm: parseFloat(form.distanceKm) || 0,
      recentAction: '新加入监测',
      recentActionDate: new Date().toISOString().slice(0, 10),
      threatLevel: 'medium',
      color: CYAN,
    };
    onAdd(newComp);
    setSubmitting(false);
    onClose();
  };

  const inputStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_1, padding: '8px 12px', fontSize: 13, outline: 'none', width: '100%', boxSizing: 'border-box',
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }} onClick={onClose}>
      <div style={{
        background: BG_1, borderRadius: 12, padding: 24, width: 400,
        border: `1px solid ${BG_2}`,
      }} onClick={e => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 20px', fontSize: 16, fontWeight: 700, color: TEXT_1 }}>新增竞品</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, display: 'block', marginBottom: 4 }}>竞品名称 *</label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="如：某某餐厅" style={inputStyle} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, display: 'block', marginBottom: 4 }}>品类</label>
            <select value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} style={inputStyle}>
              <option>湘菜</option><option>火锅</option><option>酸菜鱼</option><option>西北菜</option><option>其他</option>
            </select>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 12, color: TEXT_3, display: 'block', marginBottom: 4 }}>人均（元）</label>
              <input value={form.avgTicket} onChange={e => setForm(f => ({ ...f, avgTicket: e.target.value }))}
                placeholder="68" type="number" style={inputStyle} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 12, color: TEXT_3, display: 'block', marginBottom: 4 }}>评分</label>
              <input value={form.rating} onChange={e => setForm(f => ({ ...f, rating: e.target.value }))}
                placeholder="4.2" type="number" step="0.1" min="1" max="5" style={inputStyle} />
            </div>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, display: 'block', marginBottom: 4 }}>距离（km）</label>
            <input value={form.distanceKm} onChange={e => setForm(f => ({ ...f, distanceKm: e.target.value }))}
              placeholder="0.5" type="number" step="0.1" style={inputStyle} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
          <button onClick={onClose} style={{
            flex: 1, padding: '10px 0', borderRadius: 8, border: `1px solid ${BG_2}`,
            background: 'transparent', color: TEXT_3, fontSize: 14, cursor: 'pointer',
          }}>取消</button>
          <button onClick={handleSubmit} disabled={!form.name.trim() || submitting} style={{
            flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
            background: form.name.trim() ? BRAND : BG_2,
            color: form.name.trim() ? '#fff' : TEXT_4, fontSize: 14, cursor: form.name.trim() ? 'pointer' : 'default',
            fontWeight: 600,
          }}>{submitting ? '保存中...' : '确认新增'}</button>
        </div>
      </div>
    </div>
  );
}

// ---- 竞品列表视图 ----

function CompetitorList({ competitors, loading }: { competitors: Competitor[]; loading: boolean }) {
  const threatColors: Record<string, string> = { high: RED, medium: YELLOW, low: GREEN };
  const threatLabels: Record<string, string> = { high: '高威胁', medium: '中威胁', low: '低威胁' };

  if (loading) {
    return (
      <div style={{ padding: '48px 0', textAlign: 'center', color: TEXT_4, fontSize: 14 }}>
        数据加载中...
      </div>
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
            {['竞品', '品类', '门店数', '人均', '评分', '距离', '威胁', '最新动态'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '10px 14px', color: TEXT_4, fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap' }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {competitors.map(c => (
            <tr key={c.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
              <td style={{ padding: '14px', whiteSpace: 'nowrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 6, background: c.color + '22',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 14, fontWeight: 800, color: c.color, flexShrink: 0,
                  }}>{c.logo}</div>
                  <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{c.name}</span>
                </div>
              </td>
              <td style={{ padding: '14px', color: TEXT_3, fontSize: 12 }}>{c.category}</td>
              <td style={{ padding: '14px', color: TEXT_2, fontWeight: 600 }}>{c.storeCount.toLocaleString()}</td>
              <td style={{ padding: '14px', color: BRAND, fontWeight: 700 }}>¥{c.avgTicket}</td>
              <td style={{ padding: '14px' }}>
                <span style={{ color: c.rating >= 4.4 ? GREEN : YELLOW, fontWeight: 700 }}>{c.rating}</span>
                <span style={{ color: TEXT_4, fontSize: 11 }}> ★</span>
              </td>
              <td style={{ padding: '14px', color: TEXT_3, fontSize: 12 }}>
                {c.distanceKm != null ? `${c.distanceKm}km` : '-'}
              </td>
              <td style={{ padding: '14px' }}>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: threatColors[c.threatLevel] + '22', color: threatColors[c.threatLevel], fontWeight: 600,
                }}>{threatLabels[c.threatLevel]}</span>
              </td>
              <td style={{ padding: '14px', minWidth: 200 }}>
                <div style={{ fontSize: 12, color: TEXT_2 }}>{c.recentAction}</div>
                <div style={{ fontSize: 10, color: TEXT_4, marginTop: 2 }}>{c.recentActionDate}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- 动态时间线视图 ----

function ActionTimeline({ actions }: { actions: CompetitorAction[] }) {
  const impactColors: Record<string, string> = { high: RED, medium: YELLOW, low: TEXT_4 };
  const catColors: Record<string, string> = { '价格战': RED, '新品': GREEN, '扩张': BLUE, '营销': PURPLE, '品牌升级': CYAN, '外卖': BRAND };
  const competitorColors: Record<string, string> = { '海底捞': RED, '西贝': BLUE, '太二': GREEN, '费大厨': BRAND, '望湘园': PURPLE };

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>竞对动态时间线</h3>
      {actions.map((a, i) => (
        <div key={a.id} style={{
          position: 'relative', paddingLeft: 24, paddingBottom: 16,
          borderLeft: i < actions.length - 1 ? `2px solid ${BG_2}` : '2px solid transparent',
          marginLeft: 8,
        }}>
          <div style={{
            position: 'absolute', left: -6, top: 2, width: 12, height: 12, borderRadius: '50%',
            background: impactColors[a.impact], border: `2px solid ${BG_PAGE}`,
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

// ---- 价格对比视图 ----

function PriceComparison({ prices }: { prices: PriceRow[] }) {
  const allCompetitors = Array.from(new Set(prices.flatMap(p => p.competitors.map(c => c.name))));

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
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
                <td style={{ padding: '10px', color: BRAND, fontWeight: 700 }}>¥{p.ours}</td>
                {allCompetitors.map(name => {
                  const comp = p.competitors.find(c => c.name === name);
                  if (!comp || comp.price === 0) return <td key={name} style={{ padding: '10px', color: TEXT_4 }}>-</td>;
                  const diff = comp.price - p.ours;
                  return (
                    <td key={name} style={{ padding: '10px' }}>
                      <span style={{ color: TEXT_2 }}>¥{comp.price}</span>
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
      <div style={{ marginTop: 12, padding: '8px 12px', background: BG_2, borderRadius: 6, fontSize: 11, color: TEXT_3 }}>
        绿色数字表示竞对价格高于我方（我方有价格优势），红色表示竞对价格低于我方
      </div>
    </div>
  );
}

// ---- 雷达图视图 ----

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
    <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>竞对基准雷达图</h3>
        <div style={{ display: 'flex', gap: 12, fontSize: 11 }}>
          <span style={{ color: BRAND }}>我方</span>
          <span style={{ color: BLUE }}>{selectedCompetitor}</span>
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <svg width={360} height={340} viewBox="0 0 360 340">
          {[20, 40, 60, 80, 100].map(v => (
            <polygon key={v} points={dimensions.map((_, i) => { const p = getPoint(i, v); return `${p.x},${p.y}`; }).join(' ')}
              fill="none" stroke={BG_2} strokeWidth={1} />
          ))}
          {dimensions.map((_, i) => { const p = getPoint(i, 100); return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke={BG_2} strokeWidth={1} />; })}
          <polygon points={oursPoints} fill={BRAND + '33'} stroke={BRAND} strokeWidth={2} />
          {dimensions.map((d, i) => { const p = getPoint(i, d.ours); return <circle key={`o${i}`} cx={p.x} cy={p.y} r={4} fill={BRAND} />; })}
          <polygon points={compPoints} fill={BLUE + '22'} stroke={BLUE} strokeWidth={2} strokeDasharray="5,3" />
          {dimensions.map((d, i) => { const p = getPoint(i, d.competitor); return <circle key={`c${i}`} cx={p.x} cy={p.y} r={4} fill={BLUE} />; })}
          {dimensions.map((d, i) => { const p = getPoint(i, 125); return <text key={i} x={p.x} y={p.y} textAnchor="middle" dominantBaseline="middle" fill={TEXT_3} fontSize={11}>{d.label}</text>; })}
        </svg>
      </div>
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
  const [activeTab, setActiveTab] = useState<TabKey>('list');
  const [selectedCompetitor, setSelectedCompetitor] = useState('海底捞');
  const [competitors, setCompetitors] = useState<Competitor[]>(FALLBACK_COMPETITORS);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [dataNote, setDataNote] = useState('');

  useEffect(() => {
    setLoading(true);
    fetchCompetitors()
      .then(list => {
        setCompetitors(list);
        if (list === FALLBACK_COMPETITORS) setDataNote('数据采集中，展示参考数据');
        else setDataNote('');
      })
      .catch(() => setDataNote('数据采集中，展示参考数据'))
      .finally(() => setLoading(false));
  }, []);

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'list', label: '竞品列表' },
    { key: 'timeline', label: '动态时间线' },
    { key: 'price', label: '价格对比' },
    { key: 'radar', label: '基准雷达' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG_PAGE, minHeight: '100vh', padding: '0 0 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>竞品中心</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {dataNote && (
            <span style={{ fontSize: 12, color: YELLOW, background: YELLOW + '15', padding: '4px 10px', borderRadius: 6 }}>
              {dataNote}
            </span>
          )}
          <button onClick={() => setShowAdd(true)} style={{
            padding: '8px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: BRAND, color: '#fff', fontSize: 13, fontWeight: 600,
          }}>+ 新增竞品</button>
        </div>
      </div>

      {/* 统计概览 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        {[
          { label: '已监测竞品', value: competitors.length, color: BRAND },
          { label: '高威胁竞品', value: competitors.filter(c => c.threatLevel === 'high').length, color: RED },
          { label: '本月新动态', value: FALLBACK_TIMELINE.length, color: YELLOW },
          { label: '平均评分', value: (competitors.reduce((s, c) => s + c.rating, 0) / Math.max(competitors.length, 1)).toFixed(1), color: GREEN },
        ].map(item => (
          <div key={item.label} style={{
            flex: 1, minWidth: 150, background: BG_1, borderRadius: 10, padding: '14px 18px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 26, fontWeight: 700, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>

      {/* Tab 导航 */}
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
            {competitors.map(c => <option key={c.id}>{c.name}</option>)}
          </select>
        )}
      </div>

      {/* 内容区 */}
      {activeTab === 'list' && (
        <div style={{ background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`, overflow: 'hidden' }}>
          <CompetitorList competitors={competitors} loading={loading} />
        </div>
      )}
      {activeTab === 'timeline' && <ActionTimeline actions={FALLBACK_TIMELINE} />}
      {activeTab === 'price' && <PriceComparison prices={FALLBACK_PRICES} />}
      {activeTab === 'radar' && <BenchmarkRadar dimensions={FALLBACK_RADAR} selectedCompetitor={selectedCompetitor} />}

      {/* 新增竞品弹窗 */}
      {showAdd && (
        <AddCompetitorModal
          onClose={() => setShowAdd(false)}
          onAdd={(c) => setCompetitors(prev => [...prev, c])}
        />
      )}
    </div>
  );
}
