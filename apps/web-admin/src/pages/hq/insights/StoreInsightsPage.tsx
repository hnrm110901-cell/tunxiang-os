/**
 * 门店经营洞察 — /hq/insights/stores
 * P1: 多门店经营对比、健康度评分、营收/客流/翻台率排名
 *
 * API: GET /api/v1/analytics/store-insights?date=&period=
 */
import { useEffect, useState, useMemo } from 'react';
import { formatPrice } from '@tx-ds/utils';
import { apiGet } from '../../../api/client';

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface StoreMetric {
  storeId: string;
  storeName: string;
  region: string;
  revenueFen: number;
  orderCount: number;
  guestCount: number;
  avgCheckFen: number;
  tableTurnRate: number;
  grossMargin: number;
  healthScore: number;     // 0-100
  revenueGrowth: number;   // 环比增长率
  complaintCount: number;
}

type SortKey = 'revenueFen' | 'orderCount' | 'guestCount' | 'tableTurnRate' | 'grossMargin' | 'healthScore';
type Period = 'today' | 'week' | 'month';

// ─── Fallback ──────────────────────────────────────────────────────────────────

const FALLBACK: StoreMetric[] = [
  { storeId: 's1', storeName: '徐记海鲜·芙蓉店', region: '长沙', revenueFen: 8560000, orderCount: 420, guestCount: 1260, avgCheckFen: 6800, tableTurnRate: 3.2, grossMargin: 0.62, healthScore: 92, revenueGrowth: 0.08, complaintCount: 1 },
  { storeId: 's2', storeName: '徐记海鲜·梅溪湖店', region: '长沙', revenueFen: 6320000, orderCount: 310, guestCount: 930, avgCheckFen: 6800, tableTurnRate: 2.8, grossMargin: 0.58, healthScore: 85, revenueGrowth: 0.05, complaintCount: 3 },
  { storeId: 's3', storeName: '徐记海鲜·IFS店', region: '长沙', revenueFen: 12800000, orderCount: 580, guestCount: 1740, avgCheckFen: 7400, tableTurnRate: 3.8, grossMargin: 0.65, healthScore: 96, revenueGrowth: 0.12, complaintCount: 0 },
  { storeId: 's4', storeName: '徐记海鲜·武汉光谷店', region: '武汉', revenueFen: 5100000, orderCount: 260, guestCount: 780, avgCheckFen: 6500, tableTurnRate: 2.5, grossMargin: 0.55, healthScore: 78, revenueGrowth: -0.03, complaintCount: 5 },
  { storeId: 's5', storeName: '徐记海鲜·深圳万象城店', region: '深圳', revenueFen: 15200000, orderCount: 650, guestCount: 1950, avgCheckFen: 7800, tableTurnRate: 4.1, grossMargin: 0.68, healthScore: 98, revenueGrowth: 0.15, complaintCount: 0 },
  { storeId: 's6', storeName: '徐记海鲜·广州天河店', region: '广州', revenueFen: 9800000, orderCount: 470, guestCount: 1410, avgCheckFen: 6950, tableTurnRate: 3.5, grossMargin: 0.60, healthScore: 88, revenueGrowth: 0.06, complaintCount: 2 },
];

// ─── 辅助 ──────────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

function healthColor(score: number): string {
  if (score >= 90) return '#0F6E56';
  if (score >= 75) return '#BA7517';
  return '#A32D2D';
}

function marginColor(margin: number): string {
  return margin < 0.4 ? '#A32D2D' : margin < 0.55 ? '#BA7517' : '#0F6E56';
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function StoreInsightsPage() {
  const [stores, setStores] = useState<StoreMetric[]>(FALLBACK);
  const [period, setPeriod] = useState<Period>('today');
  const [sortKey, setSortKey] = useState<SortKey>('revenueFen');
  const [sortAsc, setSortAsc] = useState(false);
  const [regionFilter, setRegionFilter] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    apiGet<{ items: StoreMetric[] }>(`/api/v1/analytics/store-insights?period=${period}`)
      .then(res => { if (res?.items?.length) setStores(res.items); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [period]);

  const regions = useMemo(() => [...new Set(stores.map(s => s.region))], [stores]);

  const sorted = useMemo(() => {
    let list = regionFilter ? stores.filter(s => s.region === regionFilter) : stores;
    list = [...list].sort((a, b) => {
      const diff = (a[sortKey] as number) - (b[sortKey] as number);
      return sortAsc ? diff : -diff;
    });
    return list;
  }, [stores, sortKey, sortAsc, regionFilter]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  // 汇总
  const totalRevenue = sorted.reduce((s, x) => s + x.revenueFen, 0);
  const totalOrders = sorted.reduce((s, x) => s + x.orderCount, 0);
  const avgHealth = sorted.length > 0 ? Math.round(sorted.reduce((s, x) => s + x.healthScore, 0) / sorted.length) : 0;

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600, color: '#1E2A3A' }}>门店经营洞察</div>
          <div style={{ fontSize: 13, color: '#6B7280', marginTop: 4 }}>多门店对比分析、健康度评分、排名</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['today', 'week', 'month'] as Period[]).map(p => (
            <button key={p} onClick={() => setPeriod(p)} style={{
              padding: '6px 14px', borderRadius: 6, fontSize: 13, cursor: 'pointer',
              background: period === p ? '#FF6B35' : '#fff', color: period === p ? '#fff' : '#374151',
              border: period === p ? 'none' : '1px solid #D1D5DB',
            }}>
              {p === 'today' ? '今日' : p === 'week' ? '本周' : '本月'}
            </button>
          ))}
        </div>
      </div>

      {/* 汇总卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        <SummaryCard label="门店数" value={`${sorted.length} 家`} />
        <SummaryCard label="总营收" value={fen2yuan(totalRevenue)} color="#FF6B35" />
        <SummaryCard label="总订单" value={`${totalOrders} 单`} />
        <SummaryCard label="平均健康度" value={`${avgHealth}分`} color={healthColor(avgHealth)} />
      </div>

      {/* 筛选 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <select value={regionFilter} onChange={e => setRegionFilter(e.target.value)}
          style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #D1D5DB', fontSize: 14 }}>
          <option value="">全部区域</option>
          {regions.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>

      {/* 表格 */}
      <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #E5E7EB', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: '#F8F7F5' }}>
              <th style={thStyle}>排名</th>
              <th style={thStyle}>门店</th>
              <th style={thStyle}>区域</th>
              <SortTh label="营收" sortKey="revenueFen" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <SortTh label="订单" sortKey="orderCount" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <SortTh label="客流" sortKey="guestCount" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <SortTh label="翻台率" sortKey="tableTurnRate" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <SortTh label="毛利率" sortKey="grossMargin" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <SortTh label="健康度" sortKey="healthScore" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <th style={thStyle}>环比</th>
              <th style={thStyle}>客诉</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={11} style={{ padding: 40, textAlign: 'center', color: '#9CA3AF' }}>加载中...</td></tr>
            ) : sorted.map((s, i) => (
              <tr key={s.storeId} style={{ borderBottom: '1px solid #F3F4F6' }}>
                <td style={tdStyle}><span style={{ display: 'inline-block', width: 24, height: 24, borderRadius: '50%', background: i < 3 ? '#FF6B35' : '#E5E7EB', color: i < 3 ? '#fff' : '#6B7280', textAlign: 'center', lineHeight: '24px', fontSize: 12, fontWeight: 600 }}>{i + 1}</span></td>
                <td style={{ ...tdStyle, fontWeight: 500 }}>{s.storeName}</td>
                <td style={tdStyle}>{s.region}</td>
                <td style={{ ...tdStyle, fontWeight: 600 }}>{fen2yuan(s.revenueFen)}</td>
                <td style={tdStyle}>{s.orderCount}</td>
                <td style={tdStyle}>{s.guestCount}</td>
                <td style={tdStyle}>{s.tableTurnRate.toFixed(1)}</td>
                <td style={tdStyle}><span style={{ color: marginColor(s.grossMargin), fontWeight: 500 }}>{pct(s.grossMargin)}</span></td>
                <td style={tdStyle}><span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 12, fontWeight: 600, color: healthColor(s.healthScore), background: `${healthColor(s.healthScore)}15` }}>{s.healthScore}</span></td>
                <td style={tdStyle}><span style={{ color: s.revenueGrowth >= 0 ? '#0F6E56' : '#A32D2D' }}>{s.revenueGrowth >= 0 ? '+' : ''}{pct(s.revenueGrowth)}</span></td>
                <td style={tdStyle}>{s.complaintCount > 0 ? <span style={{ color: '#A32D2D', fontWeight: 500 }}>{s.complaintCount}</span> : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function SummaryCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: '#fff', borderRadius: 8, border: '1px solid #E5E7EB', padding: '14px 16px' }}>
      <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, color: color || '#1E2A3A' }}>{value}</div>
    </div>
  );
}

function SortTh({ label, sortKey, current, asc, onClick }: { label: string; sortKey: SortKey; current: SortKey; asc: boolean; onClick: (k: SortKey) => void }) {
  const isActive = current === sortKey;
  return (
    <th style={{ ...thStyle, cursor: 'pointer', userSelect: 'none' }} onClick={() => onClick(sortKey)}>
      {label} {isActive ? (asc ? '↑' : '↓') : ''}
    </th>
  );
}

const thStyle: React.CSSProperties = { padding: '10px 12px', textAlign: 'left', fontWeight: 500, color: '#6B7280', borderBottom: '1px solid #E5E7EB', whiteSpace: 'nowrap', fontSize: 13 };
const tdStyle: React.CSSProperties = { padding: '10px 12px', whiteSpace: 'nowrap' };
