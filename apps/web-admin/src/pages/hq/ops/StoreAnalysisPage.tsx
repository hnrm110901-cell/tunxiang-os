/**
 * 门店分析 — 营收趋势、翻台率、客单价、高峰时段、门店对比
 * API: GET /api/v1/analytics/store-analysis?store_id={storeId}&period={period}
 *      GET /api/v1/analytics/store-comparison?store_ids={ids}&period={period}
 */
import { useState, useEffect, useCallback } from 'react';
import { TxLineChart, TxHeatmap } from '../../../components/charts';
import { txFetch } from '../../../api';

const STORES = ['芙蓉路店', '岳麓店', '星沙店', '河西店', '开福店'];

interface KpiItem {
  label: string;
  value: string;
  trend: string;
  up: boolean;
}

interface StoreAnalysisData {
  kpis: KpiItem[];
  revenue_trend: {
    labels: string[];
    datasets: { name: string; values: number[]; color: string }[];
  };
  turnover_avg_chart: {
    labels: string[];
    datasets: { name: string; values: number[]; color: string }[];
  };
  heatmap: {
    xLabels: string[];
    yLabels: string[];
    values: number[][];
  };
}

interface CompareItem {
  name: string;
  revenue: number;
  turnover: number;
  avgPrice: number;
  peakOrders: number;
}

const EMPTY_ANALYSIS: StoreAnalysisData = {
  kpis: [],
  revenue_trend: { labels: [], datasets: [] },
  turnover_avg_chart: { labels: [], datasets: [] },
  heatmap: { xLabels: [], yLabels: [], values: [] },
};

export function StoreAnalysisPage() {
  const [selectedStores, setSelectedStores] = useState<string[]>(['芙蓉路店']);
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week');
  const [analysisData, setAnalysisData] = useState<StoreAnalysisData>(EMPTY_ANALYSIS);
  const [compareData, setCompareData] = useState<CompareItem[]>([]);
  const [loading, setLoading] = useState(false);

  const loadAnalysis = useCallback(async () => {
    if (selectedStores.length === 0) return;
    setLoading(true);
    try {
      const storeId = selectedStores[0];
      const res = await txFetch<StoreAnalysisData>(
        `/api/v1/analytics/store-analysis?store_id=${encodeURIComponent(storeId)}&period=${period}`
      );
      setAnalysisData(res ?? EMPTY_ANALYSIS);
    } catch {
      setAnalysisData(EMPTY_ANALYSIS);
    } finally {
      setLoading(false);
    }
  }, [selectedStores, period]);

  const loadComparison = useCallback(async () => {
    if (selectedStores.length === 0) return;
    try {
      const ids = selectedStores.map(encodeURIComponent).join(',');
      const res = await txFetch<{ items: CompareItem[] }>(
        `/api/v1/analytics/store-comparison?store_ids=${ids}&period=${period}`
      );
      setCompareData(res?.items ?? []);
    } catch {
      setCompareData([]);
    }
  }, [selectedStores, period]);

  useEffect(() => {
    loadAnalysis();
    loadComparison();
  }, [loadAnalysis, loadComparison]);

  const toggleStore = (name: string) => {
    setSelectedStores((prev) =>
      prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]
    );
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>门店分析</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['day', 'week', 'month'] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: period === p ? '#FF6B2C' : '#1a2a33',
              color: period === p ? '#fff' : '#999',
            }}>
              {p === 'day' ? '日' : p === 'week' ? '周' : '月'}
            </button>
          ))}
        </div>
      </div>

      {/* 门店多选 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {STORES.map((s) => (
          <button key={s} onClick={() => toggleStore(s)} style={{
            padding: '5px 14px', borderRadius: 16, border: '1px solid',
            cursor: 'pointer', fontSize: 12,
            borderColor: selectedStores.includes(s) ? '#FF6B2C' : '#1a2a33',
            background: selectedStores.includes(s) ? 'rgba(255,107,44,0.1)' : '#112228',
            color: selectedStores.includes(s) ? '#FF6B2C' : '#999',
          }}>
            {s}
          </button>
        ))}
      </div>

      {loading && (
        <div style={{ textAlign: 'center', color: '#999', padding: 16, fontSize: 13 }}>加载中...</div>
      )}

      {/* 门店 KPI */}
      {analysisData.kpis.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
          {analysisData.kpis.map((kpi) => (
            <div key={kpi.label} style={{ background: '#112228', borderRadius: 8, padding: 16 }}>
              <div style={{ fontSize: 12, color: '#999' }}>{kpi.label}</div>
              <div style={{ fontSize: 24, fontWeight: 'bold', margin: '4px 0' }}>{kpi.value}</div>
              <div style={{ fontSize: 11, color: kpi.up ? '#52c41a' : '#ff4d4f' }}>
                {kpi.up ? '↑' : '↓'} {kpi.trend}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 营收趋势折线图 */}
      {analysisData.revenue_trend.datasets.length > 0 && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>营收趋势</h3>
          <TxLineChart
            data={analysisData.revenue_trend}
            height={280}
            showArea={selectedStores.length === 1}
            unit="元"
          />
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 翻台率/客单价双轴图 */}
        {analysisData.turnover_avg_chart.datasets.length > 0 && (
          <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>翻台率 / 客单价趋势</h3>
            <TxLineChart
              data={analysisData.turnover_avg_chart}
              height={220}
            />
          </div>
        )}

        {/* 高峰时段热力图 */}
        {analysisData.heatmap.xLabels.length > 0 && (
          <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>高峰时段热力图</h3>
            <TxHeatmap
              data={analysisData.heatmap}
              height={220}
              unit="单"
            />
          </div>
        )}
      </div>

      {/* 门店对比表格 */}
      {compareData.length > 0 && (
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>门店对比</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                <th style={{ padding: '8px 4px' }}>门店</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>营收</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>翻台率</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>客单价</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>高峰单量</th>
              </tr>
            </thead>
            <tbody>
              {compareData.map((s) => (
                <tr key={s.name} style={{
                  borderTop: '1px solid #1a2a33',
                  background: selectedStores.includes(s.name) ? 'rgba(255,107,44,0.05)' : 'transparent',
                }}>
                  <td style={{ padding: '10px 4px', fontWeight: 600 }}>{s.name}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>¥{s.revenue.toLocaleString()}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>{s.turnover}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>¥{s.avgPrice}</td>
                  <td style={{ padding: '10px 4px', textAlign: 'right' }}>{s.peakOrders}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
