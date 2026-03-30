/**
 * 趋势分析页 -- 总部端
 * 时间范围选择（7/30/90天/自定义）
 * 多指标叠加折线图 | 异常点标注（>2 sigma） | 预测线（虚线，线性回归）
 */
import { useState, useMemo, useCallback } from 'react';
import { TxLineChart } from '../../../components/charts';

// ---------- 类型 ----------
type TimeRange = '7d' | '30d' | '90d' | 'custom';

interface MetricConfig {
  key: string;
  label: string;
  unit: string;
  color: string;
  enabled: boolean;
}

interface DayPoint {
  date: string;
  revenue: number;
  avg_ticket: number;
  margin: number;
  turnover: number;
  orders: number;
}

// ---------- 工具 ----------
function generateMockData(days: number): DayPoint[] {
  const result: DayPoint[] = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const base = 25000 + Math.sin(i * 0.3) * 5000;
    const noise = (Math.random() - 0.5) * 6000;
    // 制造异常点
    const anomaly = (i === Math.floor(days * 0.3) || i === Math.floor(days * 0.7)) ? 12000 : 0;
    result.push({
      date: d.toISOString().slice(5, 10),
      revenue: Math.round(base + noise + anomaly),
      avg_ticket: Math.round(60 + Math.random() * 20),
      margin: parseFloat((42 + Math.random() * 10).toFixed(1)),
      turnover: parseFloat((2.0 + Math.random() * 1.5).toFixed(1)),
      orders: Math.round(380 + Math.random() * 100 + anomaly / 100),
    });
  }
  return result;
}

function linearRegression(values: number[]): { slope: number; intercept: number } {
  const n = values.length;
  if (n < 2) return { slope: 0, intercept: values[0] || 0 };
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (let i = 0; i < n; i++) {
    sumX += i;
    sumY += values[i];
    sumXY += i * values[i];
    sumX2 += i * i;
  }
  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

function calcMeanStd(values: number[]): { mean: number; std: number } {
  const n = values.length;
  if (n === 0) return { mean: 0, std: 0 };
  const mean = values.reduce((s, v) => s + v, 0) / n;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / n;
  return { mean, std: Math.sqrt(variance) };
}

// ---------- 常量 ----------
const RANGE_LABELS: Record<TimeRange, string> = { '7d': '7天', '30d': '30天', '90d': '90天', custom: '自定义' };

const DEFAULT_METRICS: MetricConfig[] = [
  { key: 'revenue', label: '营收', unit: '元', color: '#FF6B2C', enabled: true },
  { key: 'avg_ticket', label: '客单价', unit: '元', color: '#185FA5', enabled: false },
  { key: 'margin', label: '毛利率', unit: '%', color: '#0F6E56', enabled: false },
  { key: 'turnover', label: '翻台率', unit: '', color: '#BA7517', enabled: false },
  { key: 'orders', label: '订单数', unit: '单', color: '#8B5CF6', enabled: false },
];

const PREDICT_DAYS = 7; // 预测7天

// ---------- 组件 ----------
export function TrendAnalysisPage() {
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');
  const [metrics, setMetrics] = useState<MetricConfig[]>(DEFAULT_METRICS);

  const daysMap: Record<TimeRange, number> = { '7d': 7, '30d': 30, '90d': 90, custom: 30 };
  const days = daysMap[timeRange];

  const rawData = useMemo(() => generateMockData(days), [days]);

  const toggleMetric = useCallback((key: string) => {
    setMetrics((prev) => prev.map((m) => m.key === key ? { ...m, enabled: !m.enabled } : m));
  }, []);

  const enabledMetrics = metrics.filter((m) => m.enabled);

  // 计算异常点（每个指标独立判断）
  const anomalies = useMemo(() => {
    const result: Record<string, Set<number>> = {};
    for (const m of enabledMetrics) {
      const values = rawData.map((d) => (d as Record<string, number>)[m.key]);
      const { mean, std } = calcMeanStd(values);
      const anomalySet = new Set<number>();
      values.forEach((v, i) => {
        if (Math.abs(v - mean) > 2 * std) anomalySet.add(i);
      });
      result[m.key] = anomalySet;
    }
    return result;
  }, [rawData, enabledMetrics]);

  // 预测线数据（基于最近7天线性回归，延伸PREDICT_DAYS天）
  const predictions = useMemo(() => {
    const result: Record<string, number[]> = {};
    for (const m of enabledMetrics) {
      const values = rawData.map((d) => (d as Record<string, number>)[m.key]);
      const recentValues = values.slice(-7);
      const { slope, intercept } = linearRegression(recentValues);
      const lastIdx = recentValues.length - 1;
      const predicted: number[] = [];
      // 将实际数据用NaN填充，只在最后一个点连接
      for (let i = 0; i < values.length - 1; i++) predicted.push(NaN);
      predicted.push(values[values.length - 1]); // 连接点
      for (let i = 1; i <= PREDICT_DAYS; i++) {
        predicted.push(Math.max(0, Math.round((intercept + slope * (lastIdx + i)) * 10) / 10));
      }
      result[m.key] = predicted;
    }
    return result;
  }, [rawData, enabledMetrics]);

  // 构建图表数据（实际 + 预测）
  const chartLabels = useMemo(() => {
    const labels = rawData.map((d) => d.date);
    // 添加预测日期标签
    const lastDate = new Date();
    for (let i = 1; i <= PREDICT_DAYS; i++) {
      const fd = new Date(lastDate);
      fd.setDate(fd.getDate() + i);
      labels.push(fd.toISOString().slice(5, 10));
    }
    return labels;
  }, [rawData]);

  const chartDatasets = useMemo(() => {
    const datasets: { name: string; values: number[]; color: string }[] = [];
    for (const m of enabledMetrics) {
      const values = rawData.map((d) => (d as Record<string, number>)[m.key]);
      // 实际数据，预测部分填NaN
      const actual = [...values, ...Array(PREDICT_DAYS).fill(NaN)];
      datasets.push({ name: m.label, values: actual, color: m.color });
    }
    return datasets;
  }, [rawData, enabledMetrics]);

  // 异常点信息汇总
  const anomalySummary = useMemo(() => {
    const items: { metric: string; date: string; value: number; color: string }[] = [];
    for (const m of enabledMetrics) {
      const aSet = anomalies[m.key];
      if (!aSet) continue;
      aSet.forEach((idx) => {
        items.push({
          metric: m.label,
          date: rawData[idx]?.date || '',
          value: (rawData[idx] as Record<string, number>)?.[m.key] || 0,
          color: m.color,
        });
      });
    }
    return items;
  }, [anomalies, enabledMetrics, rawData]);

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>趋势分析</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {(Object.keys(RANGE_LABELS) as TimeRange[]).map((r) => (
            <button key={r} onClick={() => setTimeRange(r)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: timeRange === r ? '#FF6B2C' : '#1a2a33',
              color: timeRange === r ? '#fff' : '#999',
            }}>
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>

      {/* 指标选择 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        {metrics.map((m) => (
          <button key={m.key} onClick={() => toggleMetric(m.key)} style={{
            padding: '6px 16px', borderRadius: 20, cursor: 'pointer',
            fontSize: 12, fontWeight: 600,
            border: m.enabled ? `2px solid ${m.color}` : '2px solid #2a3a43',
            background: m.enabled ? `${m.color}15` : 'transparent',
            color: m.enabled ? m.color : '#666',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: m.enabled ? m.color : '#444',
            }} />
            {m.label}
          </button>
        ))}
      </div>

      {/* 主折线图 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>多指标趋势</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 11, color: '#666' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 20, height: 2, background: '#FF6B2C', display: 'inline-block' }} /> 实际值
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 20, height: 2, borderTop: '2px dashed #FF6B2C', display: 'inline-block' }} /> 预测值
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%', border: '2px solid #A32D2D',
                display: 'inline-block', background: '#A32D2D30',
              }} /> 异常点
            </span>
          </div>
        </div>
        {enabledMetrics.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#666' }}>请选择至少一个指标</div>
        ) : (
          <TxLineChart
            data={{ labels: chartLabels, datasets: chartDatasets }}
            height={360}
            showArea
            unit={enabledMetrics[0]?.unit || ''}
          />
        )}
      </div>

      {/* 预测摘要 + 异常点 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 线性回归预测 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>预测趋势（未来7天）</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {enabledMetrics.map((m) => {
              const values = rawData.map((d) => (d as Record<string, number>)[m.key]);
              const recentValues = values.slice(-7);
              const { slope } = linearRegression(recentValues);
              const lastVal = values[values.length - 1];
              const futureVal = lastVal + slope * PREDICT_DAYS;
              const changePercent = lastVal > 0 ? ((futureVal - lastVal) / lastVal * 100) : 0;
              const isUp = changePercent >= 0;
              return (
                <div key={m.key} style={{
                  padding: 12, borderRadius: 8, background: '#0B1A20',
                  borderLeft: `3px solid ${m.color}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: m.color }}>{m.label}</span>
                    <span style={{
                      fontSize: 12, fontWeight: 600,
                      color: isUp ? '#0F6E56' : '#A32D2D',
                    }}>
                      {isUp ? '\u2191' : '\u2193'} {Math.abs(changePercent).toFixed(1)}%
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                    当前 {lastVal.toLocaleString()}{m.unit} → 预测 {Math.round(futureVal).toLocaleString()}{m.unit}
                  </div>
                </div>
              );
            })}
            {enabledMetrics.length === 0 && (
              <div style={{ color: '#666', fontSize: 13, textAlign: 'center', padding: 20 }}>请选择指标查看预测</div>
            )}
          </div>
        </div>

        {/* 异常点标注 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            异常检测
            <span style={{
              fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
              background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
            }}>
              偏离 &gt;2 sigma
            </span>
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {anomalySummary.length === 0 ? (
              <div style={{ color: '#666', fontSize: 13, textAlign: 'center', padding: 20 }}>
                {enabledMetrics.length === 0 ? '请选择指标' : '未检测到异常'}
              </div>
            ) : (
              anomalySummary.map((a, i) => (
                <div key={i} style={{
                  padding: 10, borderRadius: 6, background: '#0B1A20',
                  borderLeft: '3px solid #A32D2D',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}>
                  <div>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: `${a.color}20`, color: a.color, fontWeight: 600, marginRight: 8,
                    }}>{a.metric}</span>
                    <span style={{ fontSize: 12, color: '#999' }}>{a.date}</span>
                  </div>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#A32D2D' }}>
                    {a.value.toLocaleString()}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
