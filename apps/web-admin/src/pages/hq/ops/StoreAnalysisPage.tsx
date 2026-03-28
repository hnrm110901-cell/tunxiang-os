/**
 * 门店分析 — 营收趋势、翻台率、客单价、高峰时段、门店对比
 * 调用 GET /api/v1/analysis/store/*
 */
import { useState } from 'react';

const STORES = ['芙蓉路店', '岳麓店', '星沙店', '河西店', '开福店'];

const MOCK_STORE_KPI = [
  { label: '营收', value: '¥85,600', trend: '+15.2%', up: true },
  { label: '翻台率', value: '3.2', trend: '+0.4', up: true },
  { label: '客单价', value: '¥68.5', trend: '+2.8%', up: true },
  { label: '高峰时段', value: '11:30-13:00', trend: '午市', up: true },
];

const MOCK_COMPARE = [
  { name: '芙蓉路店', revenue: 85600, turnover: 3.2, avgPrice: 68.5, peakOrders: 42 },
  { name: '岳麓店', revenue: 64000, turnover: 2.8, avgPrice: 62.1, peakOrders: 35 },
  { name: '星沙店', revenue: 52000, turnover: 2.4, avgPrice: 58.3, peakOrders: 28 },
];

export function StoreAnalysisPage() {
  const [selectedStores, setSelectedStores] = useState<string[]>(['芙蓉路店']);
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week');

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

      {/* 门店 KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {MOCK_STORE_KPI.map((kpi) => (
          <div key={kpi.label} style={{ background: '#112228', borderRadius: 8, padding: 16 }}>
            <div style={{ fontSize: 12, color: '#999' }}>{kpi.label}</div>
            <div style={{ fontSize: 24, fontWeight: 'bold', margin: '4px 0' }}>{kpi.value}</div>
            <div style={{ fontSize: 11, color: kpi.up ? '#52c41a' : '#ff4d4f' }}>
              {kpi.up ? '↑' : '↓'} {kpi.trend}
            </div>
          </div>
        ))}
      </div>

      {/* ECharts 占位：营收趋势图 */}
      <div style={{
        background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16,
        minHeight: 280, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ textAlign: 'center', color: '#666' }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>📊</div>
          <div style={{ fontSize: 13 }}>营收趋势折线图 — ECharts 接入点</div>
          <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>GET /api/v1/analysis/store/revenue-trend?stores={selectedStores.join(',')}&period={period}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* ECharts 占位：翻台率/客单价 */}
        <div style={{
          background: '#112228', borderRadius: 8, padding: 20,
          minHeight: 220, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ textAlign: 'center', color: '#666' }}>
            <div style={{ fontSize: 36, marginBottom: 8 }}>🔄</div>
            <div style={{ fontSize: 13 }}>翻台率/客单价双轴图 — ECharts 接入点</div>
            <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>GET /api/v1/analysis/store/turnover</div>
          </div>
        </div>

        {/* ECharts 占位：高峰时段热力图 */}
        <div style={{
          background: '#112228', borderRadius: 8, padding: 20,
          minHeight: 220, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ textAlign: 'center', color: '#666' }}>
            <div style={{ fontSize: 36, marginBottom: 8 }}>🔥</div>
            <div style={{ fontSize: 13 }}>高峰时段热力图 — ECharts 接入点</div>
            <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>GET /api/v1/analysis/store/peak-hours</div>
          </div>
        </div>
      </div>

      {/* 门店对比表格 */}
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
            {MOCK_COMPARE.map((s) => (
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
    </div>
  );
}
