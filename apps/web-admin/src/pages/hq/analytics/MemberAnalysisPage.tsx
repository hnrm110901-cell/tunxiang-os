/**
 * 会员分析页 -- F6 总部端
 * 功能: 会员增长趋势 + 活跃度漏斗 + 复购率趋势 + 流失预警列表
 * API: /api/v1/member/analytics/overview, /clv, /churn-risk
 */
import { useState, useEffect, useCallback } from 'react';
import { TxLineChart, TxScatterChart } from '../../../components/charts';
import { txFetchData } from '../../../api';

// ---------- 类型 ----------
interface OverviewKPI {
  label: string;
  value: string;
  trend: string;
  up: boolean;
  color: string;
}

interface FunnelStep {
  name: string;
  value: number;
  color: string;
}

interface RepurchaseData {
  month: string;
  rate: number;
  orders: number;
}

interface CLVSegment {
  name: string;
  x: number;
  y: number;
  size: number;
}

interface ChurnRisk {
  id: string;
  name: string;
  phone: string;
  level: string;
  lastVisit: string;
  daysSince: number;
  totalSpend: number;
  visitCount: number;
  riskScore: number;
  suggestedAction: string;
}

interface GrowthPoint {
  month: string;
  total: number;
  new_members: number;
}

interface MemberOverviewData {
  kpi: OverviewKPI[];
  funnel: FunnelStep[];
  repurchase: RepurchaseData[];
  growth_trend: GrowthPoint[];
}

interface CLVData {
  segments: CLVSegment[];
}

interface ChurnRiskData {
  items: ChurnRisk[];
  total: number;
}

// ---------- 工具 ----------
const riskColor = (score: number) => score >= 80 ? '#A32D2D' : score >= 60 ? '#BA7517' : '#185FA5';
const levelColor = (level: string) =>
  level === '金卡' ? '#BA7517' : level === '银卡' ? '#888' : '#555';

const PERIOD_MAP: Record<string, string> = {
  '本周': 'week',
  '本月': 'month',
  '本季': 'quarter',
  '本年': 'year',
};

// ---------- 组件 ----------
export function MemberAnalysisPage() {
  const [period, setPeriod] = useState('本月');
  const [loading, setLoading] = useState(false);

  const [kpiList, setKpiList] = useState<OverviewKPI[]>([]);
  const [funnel, setFunnel] = useState<FunnelStep[]>([]);
  const [repurchase, setRepurchase] = useState<RepurchaseData[]>([]);
  const [growthTrend, setGrowthTrend] = useState<GrowthPoint[]>([]);
  const [clvSegments, setClvSegments] = useState<CLVSegment[]>([]);
  const [churnRisks, setChurnRisks] = useState<ChurnRisk[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    const p = PERIOD_MAP[period] ?? 'month';
    try {
      const [overviewRes, clvRes, churnRes] = await Promise.allSettled([
        txFetchData<MemberOverviewData>(`/api/v1/member/analytics/overview?period=${p}`),
        txFetchData<CLVData>(`/api/v1/member/analytics/clv?period=${p}`),
        txFetchData<ChurnRiskData>(`/api/v1/member/analytics/churn-risk?limit=10`),
      ]);
      if (overviewRes.status === 'fulfilled' && overviewRes.value.data) {
        const d = overviewRes.value.data;
        setKpiList(d.kpi ?? []);
        setFunnel(d.funnel ?? []);
        setRepurchase(d.repurchase ?? []);
        setGrowthTrend(d.growth_trend ?? []);
      }
      if (clvRes.status === 'fulfilled' && clvRes.value.data) {
        setClvSegments(clvRes.value.data.segments ?? []);
      }
      if (churnRes.status === 'fulfilled' && churnRes.value.data) {
        setChurnRisks(churnRes.value.data.items ?? []);
      }
    } catch {
      // 保持空数据
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const funnelMax = funnel[0]?.value ?? 1;

  const growthLabels = growthTrend.map(g => g.month);
  const growthDatasets = growthLabels.length > 0 ? [
    { name: '累计会员', values: growthTrend.map(g => g.total), color: '#FF6B2C' },
    { name: '新增会员', values: growthTrend.map(g => g.new_members), color: '#0F6E56' },
  ] : [];

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>会员分析</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {['本周', '本月', '本季', '本年'].map((d) => (
            <button key={d} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: period === d ? '#FF6B2C' : '#1a2a33',
              color: period === d ? '#fff' : '#999',
            }} onClick={() => setPeriod(d)}>
              {d}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', color: '#999', padding: '8px 0', fontSize: 12 }}>数据加载中...</div>
      )}

      {/* 概览卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {kpiList.length === 0
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} style={{ background: '#112228', borderRadius: 8, padding: 16, borderLeft: '3px solid #1a2a33', minHeight: 80 }} />
            ))
          : kpiList.map((kpi) => (
              <div key={kpi.label} style={{
                background: '#112228', borderRadius: 8, padding: 16,
                borderLeft: `3px solid ${kpi.color}`,
              }}>
                <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>{kpi.value}</div>
                <div style={{ fontSize: 11, marginTop: 4, color: kpi.up ? '#0F6E56' : '#A32D2D' }}>
                  {kpi.up ? '\u2191' : '\u2193'} {kpi.trend}
                </div>
              </div>
            ))
        }
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 会员增长趋势 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>会员增长趋势</h3>
          {growthDatasets.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无数据</div>
          ) : (
            <TxLineChart
              data={{ labels: growthLabels, datasets: growthDatasets }}
              height={240}
              showArea
            />
          )}
        </div>

        {/* 活跃度漏斗 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>活跃度漏斗</h3>
          {funnel.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无数据</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {funnel.map((step, i) => {
                const widthPct = Math.max((step.value / funnelMax) * 100, 20);
                const convRate = i > 0
                  ? ((step.value / funnel[i - 1].value) * 100).toFixed(1)
                  : null;
                return (
                  <div key={step.name}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 13, color: '#ccc' }}>{step.name}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 14, fontWeight: 'bold', color: '#fff' }}>
                          {step.value.toLocaleString()}
                        </span>
                        {convRate && (
                          <span style={{
                            fontSize: 10, padding: '1px 6px', borderRadius: 4,
                            background: '#185FA520', color: '#185FA5', fontWeight: 600,
                          }}>
                            {convRate}%
                          </span>
                        )}
                      </div>
                    </div>
                    <div style={{
                      height: 24, borderRadius: 6, background: '#0B1A20',
                      overflow: 'hidden', display: 'flex', justifyContent: 'center',
                    }}>
                      <div style={{
                        width: `${widthPct}%`, height: '100%', borderRadius: 6,
                        background: step.color, transition: 'width 0.6s ease',
                        opacity: 0.7 + (i === 0 ? 0.3 : 0),
                      }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 复购率趋势 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>复购率趋势</h3>
          {repurchase.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无数据</div>
          ) : (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {repurchase.map((item) => {
                  const barColor = item.rate >= 42 ? '#0F6E56' : item.rate >= 40 ? '#185FA5' : '#BA7517';
                  return (
                    <div key={item.month} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ width: 36, fontSize: 12, color: '#999', textAlign: 'right' }}>{item.month}</span>
                      <div style={{ flex: 1, height: 20, borderRadius: 4, background: '#0B1A20', overflow: 'hidden', position: 'relative' }}>
                        <div style={{
                          width: `${item.rate * 2}%`, height: '100%', borderRadius: 4,
                          background: barColor, transition: 'width 0.6s ease',
                        }} />
                        <span style={{
                          position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                          fontSize: 11, fontWeight: 600, color: '#fff',
                        }}>
                          {item.rate}%
                        </span>
                      </div>
                      <span style={{ width: 60, fontSize: 11, color: '#999', textAlign: 'right' }}>
                        {item.orders.toLocaleString()}单
                      </span>
                    </div>
                  );
                })}
              </div>
              {clvSegments.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <TxScatterChart
                    data={clvSegments}
                    height={140}
                    xLabel="客单价(元)"
                    yLabel="复购率(%)"
                    xUnit="元"
                    yUnit="%"
                  />
                </div>
              )}
            </>
          )}
        </div>

        {/* 流失预警列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            流失预警
            {churnRisks.length > 0 && (
              <span style={{
                fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
                background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
              }}>
                {churnRisks.length} 人
              </span>
            )}
          </h3>
          {churnRisks.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无流失预警</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {churnRisks.map((member) => (
                <div key={member.id} style={{
                  padding: 12, borderRadius: 8, background: '#0B1A20',
                  borderLeft: `3px solid ${riskColor(member.riskScore)}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>{member.name}</span>
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                        background: levelColor(member.level) + '30',
                        color: levelColor(member.level),
                      }}>
                        {member.level}
                      </span>
                    </div>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 10, fontWeight: 700,
                      background: riskColor(member.riskScore) + '20',
                      color: riskColor(member.riskScore),
                    }}>
                      风险 {member.riskScore}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#999', marginBottom: 4 }}>
                    <span>{member.daysSince}天未到店</span>
                    <span>累计 \u00A5{(member.totalSpend / 100).toLocaleString()} | {member.visitCount}次</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 11, color: '#185FA5' }}>{member.suggestedAction}</span>
                    <button style={{
                      padding: '3px 10px', borderRadius: 4, border: 'none',
                      background: '#FF6B2C20', color: '#FF6B2C',
                      cursor: 'pointer', fontWeight: 600, fontSize: 10,
                    }}>
                      执行
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
