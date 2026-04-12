/**
 * 菜品分析 — 销量/毛利排行、四象限散点图、退菜率、菜单优化建议
 * API: GET /api/v1/analytics/dish-analysis?store_id={storeId}&period={period}
 */
import { useState, useEffect, useCallback } from 'react';
import { TxScatterChart } from '../../../components/charts';
import { txFetchData } from '../../../api';

interface SalesRankItem {
  rank: number;
  name: string;
  sales: number;
  revenue: number;
  trend: string;
}

interface MarginRankItem {
  rank: number;
  name: string;
  margin: number;
  revenue: number;
  sales: number;
}

interface ReturnRankItem {
  name: string;
  returnRate: number;
  returnCount: number;
  reason: string;
}

interface SuggestionItem {
  type: string;
  icon: string;
  title: string;
  desc: string;
}

interface ScatterPoint {
  name: string;
  x: number;
  y: number;
  size: number;
}

interface DishAnalysisData {
  sales_rank: SalesRankItem[];
  margin_rank: MarginRankItem[];
  return_rank: ReturnRankItem[];
  suggestions: SuggestionItem[];
  quadrant_data: ScatterPoint[];
}

const EMPTY_DATA: DishAnalysisData = {
  sales_rank: [],
  margin_rank: [],
  return_rank: [],
  suggestions: [],
  quadrant_data: [],
};

const marginColor = (m: number) => m >= 65 ? '#52c41a' : m >= 50 ? '#faad14' : '#ff4d4f';

export function DishAnalysisPage() {
  const [tab, setTab] = useState<'overview' | 'quadrant'>('overview');
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('week');
  const [storeId] = useState('');
  const [data, setData] = useState<DishAnalysisData>(EMPTY_DATA);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ period });
      if (storeId) params.set('store_id', storeId);
      const res = await txFetchData<DishAnalysisData>(
        `/api/v1/analytics/dish-analysis?${params.toString()}`
      );
      setData(res ?? EMPTY_DATA);
    } catch {
      setData(EMPTY_DATA);
    } finally {
      setLoading(false);
    }
  }, [storeId, period]);

  useEffect(() => { load(); }, [load]);

  const { sales_rank, margin_rank, return_rank, suggestions, quadrant_data } = data;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>菜品分析</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {([['overview', '总览'], ['quadrant', '四象限']] as const).map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: tab === key ? '#FF6B2C' : '#1a2a33',
              color: tab === key ? '#fff' : '#999',
            }}>{label}</button>
          ))}
          <div style={{ width: 1, background: '#1a2a33' }} />
          {(['day', 'week', 'month'] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)} style={{
              padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: period === p ? '#1a2a33' : 'transparent',
              color: period === p ? '#fff' : '#666',
            }}>{p === 'day' ? '日' : p === 'week' ? '周' : '月'}</button>
          ))}
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', color: '#999', padding: 16, fontSize: 13 }}>加载中...</div>
      )}

      {tab === 'overview' ? (
        <>
          {/* 双列表：销量排行 + 毛利排行 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            {/* 销量排行 */}
            <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>销量排行 TOP5</h3>
              {sales_rank.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#666', padding: 24, fontSize: 13 }}>暂无数据</div>
              ) : (
                sales_rank.map((d) => (
                  <div key={d.rank} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 0', borderBottom: '1px solid #1a2a33',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{
                        width: 24, height: 24, borderRadius: '50%', fontSize: 11, fontWeight: 700,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: d.rank <= 3 ? '#FF6B2C' : '#1a2a33',
                        color: d.rank <= 3 ? '#fff' : '#999',
                      }}>{d.rank}</span>
                      <span style={{ fontSize: 13 }}>{d.name}</span>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{d.sales} 份</div>
                      <div style={{ fontSize: 11, color: d.trend.startsWith('+') ? '#52c41a' : '#ff4d4f' }}>{d.trend}</div>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* 毛利排行 */}
            <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
              <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>毛利排行 TOP5</h3>
              {margin_rank.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#666', padding: 24, fontSize: 13 }}>暂无数据</div>
              ) : (
                margin_rank.map((d) => (
                  <div key={d.rank} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 0', borderBottom: '1px solid #1a2a33',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{
                        width: 24, height: 24, borderRadius: '50%', fontSize: 11, fontWeight: 700,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: d.rank <= 3 ? '#FF6B2C' : '#1a2a33',
                        color: d.rank <= 3 ? '#fff' : '#999',
                      }}>{d.rank}</span>
                      <span style={{ fontSize: 13 }}>{d.name}</span>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: marginColor(d.margin) }}>{d.margin}%</div>
                      <div style={{ fontSize: 11, color: '#999' }}>{d.sales} 份</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* 退菜率排行 */}
          <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>退菜率排行</h3>
            {return_rank.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#666', padding: 24, fontSize: 13 }}>暂无退菜数据</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                {return_rank.map((d) => (
                  <div key={d.name} style={{
                    padding: 14, borderRadius: 8, background: '#0B1A20',
                    borderTop: '2px solid #ff4d4f',
                  }}>
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{d.name}</div>
                    <div style={{ fontSize: 22, fontWeight: 'bold', color: '#ff4d4f' }}>{d.returnRate}%</div>
                    <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>退菜 {d.returnCount} 份</div>
                    <div style={{ fontSize: 11, color: '#666', marginTop: 2 }}>主因：{d.reason}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 菜单优化建议 */}
          <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>菜单优化建议</h3>
            {suggestions.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#666', padding: 24, fontSize: 13 }}>暂无优化建议</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {suggestions.map((s) => (
                  <div key={s.title} style={{
                    padding: 14, borderRadius: 8, background: '#0B1A20',
                    border: '1px solid #1a2a33',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{ fontSize: 18 }}>{s.icon}</span>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{s.title}</span>
                    </div>
                    <div style={{ fontSize: 12, color: '#999', lineHeight: 1.6 }}>{s.desc}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      ) : (
        /* 四象限散点图 */
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 16 }}>菜品四象限分析</h3>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 16 }}>X轴：销量 / Y轴：毛利率 / 气泡大小：营收</div>
          {quadrant_data.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 60, fontSize: 13 }}>暂无四象限数据</div>
          ) : (
            <TxScatterChart
              data={quadrant_data}
              height={480}
              xLabel="销量(份)"
              yLabel="毛利率(%)"
              xUnit="份"
              yUnit="%"
              showQuadrants
              quadrantLabels={['明星(高销高利)', '问号(低销高利)', '瘦狗(低销低利)', '金牛(高销低利)']}
            />
          )}
        </div>
      )}
    </div>
  );
}
