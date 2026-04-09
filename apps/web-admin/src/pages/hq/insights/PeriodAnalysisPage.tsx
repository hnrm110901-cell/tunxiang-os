/**
 * 餐段分析页 — /hq/insights/periods
 * P1: 按早/中/晚餐段分析营收、客流、菜品结构、翻台率
 *
 * API: GET /api/v1/analytics/period-analysis?store_id=&date=
 */
import { useEffect, useState } from 'react';
import { apiGet } from '../../../api/client';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface PeriodData {
  periodName: string;
  startTime: string;
  endTime: string;
  revenueFen: number;
  orderCount: number;
  guestCount: number;
  avgCheckFen: number;
  tableTurnRate: number;
  topDishes: { name: string; count: number; revenueFen: number }[];
  peakHour: string;
  occupancyRate: number;
}

interface StoreOption { id: string; name: string; }

// ─── Fallback ──────────────────────────────────────────────────────────────────

const FALLBACK_STORES: StoreOption[] = [
  { id: 'store-001', name: '徐记海鲜·芙蓉店' },
  { id: 'store-002', name: '徐记海鲜·梅溪湖店' },
];

const FALLBACK_PERIODS: PeriodData[] = [
  {
    periodName: '午餐', startTime: '11:00', endTime: '14:00',
    revenueFen: 3850000, orderCount: 185, guestCount: 555, avgCheckFen: 6940, tableTurnRate: 1.8,
    topDishes: [
      { name: '剁椒鱼头', count: 68, revenueFen: 598400 },
      { name: '口味虾', count: 52, revenueFen: 665600 },
      { name: '农家小炒肉', count: 95, revenueFen: 399000 },
      { name: '蒜蓉粉丝蒸扇贝', count: 48, revenueFen: 326400 },
      { name: '米饭', count: 420, revenueFen: 126000 },
    ],
    peakHour: '12:00-12:30', occupancyRate: 0.92,
  },
  {
    periodName: '晚餐', startTime: '17:00', endTime: '21:00',
    revenueFen: 4280000, orderCount: 195, guestCount: 630, avgCheckFen: 6800, tableTurnRate: 1.5,
    topDishes: [
      { name: '口味虾', count: 78, revenueFen: 998400 },
      { name: '剁椒鱼头', count: 72, revenueFen: 633600 },
      { name: '红烧肉', count: 55, revenueFen: 319000 },
      { name: '鲈鱼（活）', count: 35, revenueFen: 406000 },
      { name: '酸梅汤', count: 180, revenueFen: 144000 },
    ],
    peakHour: '18:30-19:00', occupancyRate: 0.98,
  },
  {
    periodName: '夜宵', startTime: '21:00', endTime: '23:30',
    revenueFen: 430000, orderCount: 40, guestCount: 75, avgCheckFen: 5700, tableTurnRate: 0.5,
    topDishes: [
      { name: '口味虾', count: 22, revenueFen: 281600 },
      { name: '凉拌黄瓜', count: 18, revenueFen: 16200 },
      { name: '酸梅汤', count: 35, revenueFen: 28000 },
    ],
    peakHour: '21:30-22:00', occupancyRate: 0.35,
  },
];

// ─── 辅助 ──────────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

function getToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const PERIOD_COLORS: Record<string, string> = {
  '早餐': '#BA7517', '午餐': '#FF6B35', '下午茶': '#185FA5', '晚餐': '#A32D2D', '夜宵': '#7C3AED',
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function PeriodAnalysisPage() {
  const [stores, setStores] = useState<StoreOption[]>(FALLBACK_STORES);
  const [selectedStore, setSelectedStore] = useState('');
  const [selectedDate, setSelectedDate] = useState(getToday());
  const [periods, setPeriods] = useState<PeriodData[]>(FALLBACK_PERIODS);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiGet<{ items: StoreOption[] }>('/api/v1/trade/stores')
      .then(res => { if (res.ok && res.data?.items?.length) { setStores(res.data.items); setSelectedStore(res.data.items[0].id); } else { setSelectedStore(FALLBACK_STORES[0].id); } })
      .catch(() => { setSelectedStore(FALLBACK_STORES[0].id); });
  }, []);

  useEffect(() => {
    if (!selectedStore) return;
    setLoading(true);
    apiGet<{ periods: PeriodData[] }>(`/api/v1/analytics/period-analysis?store_id=${selectedStore}&date=${selectedDate}`)
      .then(res => { if (res.ok && res.data?.periods?.length) setPeriods(res.data.periods); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedStore, selectedDate]);

  const totalRevenue = periods.reduce((s, p) => s + p.revenueFen, 0);

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600, color: '#1E2A3A' }}>餐段分析</div>
          <div style={{ fontSize: 13, color: '#6B7280', marginTop: 4 }}>按时段分析营收结构、客流高峰、热销菜品</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={selectedStore} onChange={e => setSelectedStore(e.target.value)} style={selectStyle}>
            {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)} style={selectStyle} />
        </div>
      </div>

      {loading && <div style={{ textAlign: 'center', color: '#9CA3AF', padding: 20 }}>加载中...</div>}

      {/* 营收占比条 */}
      <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #E5E7EB', padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>营收占比</div>
        <div style={{ display: 'flex', height: 32, borderRadius: 6, overflow: 'hidden' }}>
          {periods.map(p => {
            const ratio = totalRevenue > 0 ? (p.revenueFen / totalRevenue) * 100 : 0;
            return (
              <div key={p.periodName} style={{ width: `${ratio}%`, background: PERIOD_COLORS[p.periodName] || '#6B7280', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 12, fontWeight: 500, minWidth: ratio > 8 ? 0 : 'auto' }}>
                {ratio > 10 ? `${p.periodName} ${ratio.toFixed(0)}%` : ''}
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 12, color: '#6B7280' }}>
          {periods.map(p => (
            <div key={p.periodName} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: PERIOD_COLORS[p.periodName] || '#6B7280' }} />
              {p.periodName}: {fen2yuan(p.revenueFen)}
            </div>
          ))}
        </div>
      </div>

      {/* 餐段卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
        {periods.map(p => {
          const color = PERIOD_COLORS[p.periodName] || '#6B7280';
          return (
            <div key={p.periodName} style={{ background: '#fff', borderRadius: 8, border: '1px solid #E5E7EB', overflow: 'hidden' }}>
              {/* 头部 */}
              <div style={{ padding: '14px 16px', borderBottom: '1px solid #F3F4F6', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 4, height: 24, borderRadius: 2, background: color }} />
                  <span style={{ fontSize: 16, fontWeight: 600 }}>{p.periodName}</span>
                  <span style={{ fontSize: 13, color: '#9CA3AF' }}>{p.startTime}~{p.endTime}</span>
                </div>
                <span style={{ fontSize: 18, fontWeight: 700, color }}>{fen2yuan(p.revenueFen)}</span>
              </div>

              {/* KPI */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, background: '#F3F4F6' }}>
                {[
                  { label: '订单', value: `${p.orderCount}单` },
                  { label: '客流', value: `${p.guestCount}人` },
                  { label: '客单价', value: fen2yuan(p.avgCheckFen) },
                  { label: '翻台率', value: `${p.tableTurnRate.toFixed(1)}` },
                  { label: '上座率', value: pct(p.occupancyRate) },
                  { label: '高峰时段', value: p.peakHour },
                ].map(kpi => (
                  <div key={kpi.label} style={{ background: '#fff', padding: '8px 12px', textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: '#9CA3AF' }}>{kpi.label}</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#1E2A3A' }}>{kpi.value}</div>
                  </div>
                ))}
              </div>

              {/* 热销 TOP5 */}
              <div style={{ padding: 14 }}>
                <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 6 }}>热销 TOP {p.topDishes.length}</div>
                {p.topDishes.map((d, i) => (
                  <div key={d.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 13 }}>
                    <span><span style={{ color: i < 3 ? '#FF6B35' : '#9CA3AF', fontWeight: 600, marginRight: 6 }}>{i + 1}</span>{d.name}</span>
                    <span style={{ color: '#6B7280' }}>{d.count}份 · {fen2yuan(d.revenueFen)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const selectStyle: React.CSSProperties = { padding: '6px 12px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 14, background: '#fff' };
