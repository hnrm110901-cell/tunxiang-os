/**
 * 趋势分析页 -- 总部端
 * 接入真实数据：boss-bi/store/{id}/trend + boss-bi/alerts + orchestrate
 * 手写SVG折线图，无图表库依赖
 */
import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { txFetchData } from '../../../api';

// ---------- 类型 ----------

type TimeRange = '7d' | '30d' | '90d';

interface MetricConfig {
  key: keyof TrendPoint;
  label: string;
  unit: string;
  color: string;
  enabled: boolean;
}

/** 后端 boss-bi/store/{id}/trend 返回的单日数据点 */
interface TrendPoint {
  date: string;
  revenue_fen: number;    // 营收（分）
  avg_ticket_fen: number; // 客单价（分）
  margin_pct: number;     // 毛利率（%）
  turnover_rate: number;  // 翻台率
  order_count: number;    // 订单数
}

/** boss-bi/alerts 返回的单条预警 */
interface BossAlert {
  store_id: string;
  store_name: string;
  metric: string;
  current_value: number;
  deviation_pct: number;
  severity: 'critical' | 'warning' | 'info';
  message: string;
  suggestion?: string;
  created_at: string;
}

interface StoreOption {
  store_id: string;
  store_name: string;
}

// ---------- 工具 ----------

function calcMeanStd(values: number[]): { mean: number; std: number } {
  const n = values.length;
  if (n === 0) return { mean: 0, std: 0 };
  const mean = values.reduce((s, v) => s + v, 0) / n;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / n;
  return { mean, std: Math.sqrt(variance) };
}

function linearRegression(values: number[]): { slope: number; intercept: number } {
  const n = values.length;
  if (n < 2) return { slope: 0, intercept: values[0] || 0 };
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (let i = 0; i < n; i++) {
    sumX += i; sumY += values[i];
    sumXY += i * values[i]; sumX2 += i * i;
  }
  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

function formatVal(v: number, unit: string): string {
  if (unit === '%') return `${v.toFixed(1)}%`;
  if (unit === '元') {
    // 后端营收/客单价单位是分
    const yuan = v / 100;
    if (yuan >= 10000) return `${(yuan / 10000).toFixed(1)}万元`;
    return `${yuan.toLocaleString()}元`;
  }
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万${unit}`;
  return `${v.toLocaleString()}${unit}`;
}

/** 将分转为元后格式化 */
function fenToYuan(fen: number): number {
  return fen / 100;
}

function niceStep(range: number, targetTicks: number): number {
  const rough = range / targetTicks;
  if (rough <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const normalized = rough / mag;
  let nice: number;
  if (normalized <= 1.5) nice = 1;
  else if (normalized <= 3.5) nice = 2;
  else if (normalized <= 7.5) nice = 5;
  else nice = 10;
  return nice * mag;
}

// ---------- 常量 ----------

const RANGE_OPTIONS: { key: TimeRange; label: string; days: number }[] = [
  { key: '7d', label: '7天', days: 7 },
  { key: '30d', label: '30天', days: 30 },
  { key: '90d', label: '90天', days: 90 },
];

const DEFAULT_METRICS: MetricConfig[] = [
  { key: 'revenue_fen', label: '营收', unit: '元', color: '#FF6B2C', enabled: true },
  { key: 'avg_ticket_fen', label: '客单价', unit: '元', color: '#185FA5', enabled: false },
  { key: 'margin_pct', label: '毛利率', unit: '%', color: '#0F6E56', enabled: false },
  { key: 'turnover_rate', label: '翻台率', unit: '次', color: '#BA7517', enabled: false },
  { key: 'order_count', label: '订单数', unit: '单', color: '#8B5CF6', enabled: false },
];

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#A32D2D',
  warning: '#BA7517',
  info: '#185FA5',
};

const SEVERITY_LABEL: Record<string, string> = {
  critical: '严重',
  warning: '警告',
  info: '提示',
};

const PREDICT_DAYS = 7;

// ---------- SVG 折线图（手写，无图表库） ----------

interface LineChartDataset {
  name: string;
  values: number[];       // 已归一化（元/次/单/%）
  color: string;
  unit: string;
  anomalies: Set<number>; // 异常点索引
}

interface LineChartProps {
  labels: string[];
  datasets: LineChartDataset[];
  height?: number;
}

function SVGLineChart({ labels, datasets, height = 300 }: LineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(700);
  const [tooltip, setTooltip] = useState<{
    x: number; y: number; label: string;
    values: { name: string; value: number; unit: string; color: string; isAnomaly: boolean }[];
  } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      setWidth(entries[0].contentRect.width);
    });
    obs.observe(el);
    setWidth(el.clientWidth);
    return () => obs.disconnect();
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!labels.length || !datasets.length) return;
      const pad = { top: 24, right: 24, bottom: 40, left: 60 };
      const plotW = width - pad.left - pad.right;
      const xStep = labels.length > 1 ? plotW / (labels.length - 1) : plotW;
      const toXLocal = (i: number) => pad.left + i * xStep;
      const rect = e.currentTarget.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      let closestIdx = 0, closestDist = Infinity;
      for (let i = 0; i < labels.length; i++) {
        const dist = Math.abs(toXLocal(i) - mx);
        if (dist < closestDist) { closestDist = dist; closestIdx = i; }
      }
      if (closestDist < xStep + 10) {
        setTooltip({
          x: toXLocal(closestIdx),
          y: e.clientY - rect.top,
          label: labels[closestIdx],
          values: datasets.map((ds) => ({
            name: ds.name,
            value: ds.values[closestIdx] ?? 0,
            unit: ds.unit,
            color: ds.color,
            isAnomaly: ds.anomalies.has(closestIdx),
          })),
        });
      } else {
        setTooltip(null);
      }
    },
    [labels, datasets, width],
  );
  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  if (!labels.length || !datasets.length) {
    return (
      <div ref={containerRef} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
        暂无数据
      </div>
    );
  }

  const pad = { top: 24, right: 24, bottom: 40, left: 60 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const xStep = labels.length > 1 ? plotW / (labels.length - 1) : plotW;
  const toX = (i: number) => pad.left + i * xStep;

  // 多指标各自独立Y轴范围（归一化 0-1 相对高度叠加，用各自min/max）
  // 若只有单指标，正常计算Y轴；多指标则各自归一化到图表高度内
  const allVals = datasets.flatMap((d) => d.values.filter(isFinite));
  const rawMin = allVals.length ? Math.min(...allVals) : 0;
  const rawMax = allVals.length ? Math.max(...allVals) : 1;
  const range = rawMax - rawMin || 1;
  const step = niceStep(range, 5);
  const yMin = Math.floor(rawMin / step) * step;
  const yMax = Math.ceil(rawMax / step) * step + step * 0.1;
  const yRange = yMax - yMin || 1;
  const toY = (v: number) => pad.top + plotH - ((v - yMin) / yRange) * plotH;

  // Y轴刻度
  const yTicks: number[] = [];
  for (let v = yMin; v <= yMax + step * 0.01; v += step) {
    yTicks.push(Math.round(v * 1000) / 1000);
  }

  // X轴标签间隔（每7天或适量显示）
  const maxLabels = Math.max(1, Math.floor(plotW / 60));
  const labelStep = Math.ceil(labels.length / maxLabels);

  // 生成折线路径（跳过 NaN）
  const buildPath = (values: number[]) => {
    const segments: string[] = [];
    let pen = false;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (!isFinite(v)) { pen = false; continue; }
      segments.push(`${pen ? 'L' : 'M'}${toX(i).toFixed(1)},${toY(v).toFixed(1)}`);
      pen = true;
    }
    return segments.join(' ');
  };

  return (
    <div ref={containerRef} style={{ width: '100%', position: 'relative' }}>
      <svg
        width={width}
        height={height}
        style={{ display: 'block' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {/* Y轴网格线 + 刻度 */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={pad.left} y1={toY(v)} x2={width - pad.right} y2={toY(v)}
              stroke="#1a2a33" strokeDasharray="4,3" />
            <text x={pad.left - 8} y={toY(v) + 4} textAnchor="end" fill="#666" fontSize={10}>
              {v >= 10000 ? `${(v / 10000).toFixed(0)}W` : v.toLocaleString()}
            </text>
          </g>
        ))}

        {/* X轴基线 */}
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom}
          stroke="#2a3a43" />

        {/* X轴标签 */}
        {labels.map((lbl, i) =>
          i % labelStep === 0 ? (
            <text key={i} x={toX(i)} y={height - pad.bottom + 14} textAnchor="middle" fill="#666" fontSize={10}>
              {lbl}
            </text>
          ) : null,
        )}

        {/* 面积填充 */}
        {datasets.map((ds, di) => {
          const baseY = toY(yMin);
          const pts = ds.values
            .map((v, i) => isFinite(v) ? `${toX(i).toFixed(1)},${toY(v).toFixed(1)}` : null)
            .filter(Boolean);
          if (pts.length < 2) return null;
          // 找第一个和最后一个有效点索引
          const firstIdx = ds.values.findIndex(isFinite);
          const lastIdx = ds.values.length - 1 - [...ds.values].reverse().findIndex(isFinite);
          const areaPath = `M${toX(firstIdx).toFixed(1)},${toY(ds.values[firstIdx]).toFixed(1)} ${buildPath(ds.values).replace(/^M[^ ]+/, '')} L${toX(lastIdx).toFixed(1)},${baseY.toFixed(1)} L${toX(firstIdx).toFixed(1)},${baseY.toFixed(1)} Z`;
          return (
            <path key={`area-${di}`} d={areaPath}
              fill={ds.color} opacity={0.08} />
          );
        })}

        {/* 折线 */}
        {datasets.map((ds, di) => (
          <path key={`line-${di}`} d={buildPath(ds.values)}
            fill="none" stroke={ds.color} strokeWidth={2} strokeLinejoin="round" />
        ))}

        {/* 正常数据点 */}
        {datasets.map((ds, di) =>
          ds.values.map((v, i) => {
            if (!isFinite(v)) return null;
            if (ds.anomalies.has(i)) return null; // 异常点单独渲染
            return (
              <circle key={`dot-${di}-${i}`} cx={toX(i)} cy={toY(v)} r={2.5}
                fill={ds.color} stroke="#0B1A20" strokeWidth={1} />
            );
          }),
        )}

        {/* 异常点（红色圆圈） */}
        {datasets.map((ds) =>
          [...ds.anomalies].map((i) => {
            const v = ds.values[i];
            if (!isFinite(v)) return null;
            return (
              <g key={`anomaly-${ds.name}-${i}`}>
                <circle cx={toX(i)} cy={toY(v)} r={7}
                  fill="none" stroke="#A32D2D" strokeWidth={1.5} opacity={0.7} />
                <circle cx={toX(i)} cy={toY(v)} r={3}
                  fill="#A32D2D" />
              </g>
            );
          }),
        )}

        {/* Tooltip竖线 */}
        {tooltip && (
          <line x1={tooltip.x} y1={pad.top} x2={tooltip.x} y2={height - pad.bottom}
            stroke="#FF6B2C" strokeWidth={1} strokeDasharray="3,3" opacity={0.6} />
        )}
      </svg>

      {/* Tooltip浮层 */}
      {tooltip && (
        <div style={{
          position: 'absolute',
          left: Math.min(tooltip.x + 12, width - 170),
          top: Math.max(tooltip.y - 10, 4),
          background: '#1a2a33',
          border: '1px solid #2a3a43',
          borderRadius: 6,
          padding: '8px 12px',
          pointerEvents: 'none',
          zIndex: 20,
          minWidth: 140,
        }}>
          <div style={{ fontSize: 11, color: '#999', marginBottom: 6 }}>{tooltip.label}</div>
          {tooltip.values.map((v) => (
            <div key={v.name} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: v.isAnomaly ? '#A32D2D' : v.color, flexShrink: 0 }} />
              <span style={{ color: '#ccc' }}>{v.name}</span>
              <span style={{ color: v.isAnomaly ? '#A32D2D' : '#fff', fontWeight: 600, marginLeft: 'auto' }}>
                {v.unit === '元' ? `${(v.value / 100).toLocaleString()}元` : `${v.value.toLocaleString()}${v.unit}`}
              </span>
              {v.isAnomaly && <span style={{ fontSize: 9, color: '#A32D2D', marginLeft: 2 }}>异常</span>}
            </div>
          ))}
        </div>
      )}

      {/* 图例 */}
      {datasets.length > 1 && (
        <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 8, flexWrap: 'wrap' }}>
          {datasets.map((ds) => (
            <div key={ds.name} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#999' }}>
              <span style={{ width: 12, height: 3, borderRadius: 1, background: ds.color }} />
              {ds.name}
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#999' }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', border: '1.5px solid #A32D2D', display: 'inline-block' }} />
            异常点
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- 主组件 ----------

export function TrendAnalysisPage() {
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');
  const [metrics, setMetrics] = useState<MetricConfig[]>(DEFAULT_METRICS);
  const [storeId, setStoreId] = useState<string>('');
  const [storeOptions, setStoreOptions] = useState<StoreOption[]>([]);
  const [trendData, setTrendData] = useState<TrendPoint[]>([]);
  const [bossAlerts, setBossAlerts] = useState<BossAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiReport, setAiReport] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiExpanded, setAiExpanded] = useState(true);

  const days = RANGE_OPTIONS.find((r) => r.key === timeRange)?.days ?? 30;

  // ---------- 初始化：获取门店列表 ----------
  useEffect(() => {
    txFetchData<{ items: { store_id: string; store_name: string }[] }>(
      '/api/v1/dashboard/store-ranking?period=day',
    ).then((res) => {
      const opts = res.items.map((s) => ({ store_id: s.store_id, store_name: s.store_name }));
      setStoreOptions(opts);
      if (opts.length > 0 && !storeId) setStoreId(opts[0].store_id);
    }).catch(() => {
      // 门店列表加载失败时静默处理，保留空选择
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- 拉取趋势数据 ----------
  useEffect(() => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    setTrendData([]);
    txFetchData<{ store_id: string; days: number; trend: TrendPoint[] }>(
      `/api/v1/boss-bi/store/${encodeURIComponent(storeId)}/trend?days=${days}`,
    ).then((res) => {
      setTrendData(res.trend || []);
    }).catch((err: Error) => {
      setError(err.message || '趋势数据加载失败');
    }).finally(() => setLoading(false));
  }, [storeId, days]);

  // ---------- 拉取异常预警 ----------
  useEffect(() => {
    setAlertsLoading(true);
    txFetchData<{ alerts: BossAlert[]; total: number; threshold_pct: number }>(
      '/api/v1/boss-bi/alerts',
    ).then((res) => {
      setBossAlerts(res.alerts || []);
    }).catch(() => {
      setBossAlerts([]);
    }).finally(() => setAlertsLoading(false));
  }, []);

  // ---------- 指标切换 ----------
  const toggleMetric = useCallback((key: keyof TrendPoint) => {
    setMetrics((prev) => prev.map((m) => m.key === key ? { ...m, enabled: !m.enabled } : m));
  }, []);

  const enabledMetrics = metrics.filter((m) => m.enabled);

  // ---------- 计算各指标归一化值（分→元）+ 异常检测 ----------
  const processedDatasets = useMemo((): LineChartDataset[] => {
    return enabledMetrics.map((m) => {
      const raw = trendData.map((d) => {
        const v = (d as unknown as Record<string, number>)[m.key as string] ?? 0;
        // 分→元单位转换
        return (m.key === 'revenue_fen' || m.key === 'avg_ticket_fen') ? fenToYuan(v) : v;
      });
      const { mean, std } = calcMeanStd(raw);
      const anomalies = new Set<number>();
      raw.forEach((v, i) => { if (Math.abs(v - mean) > 2 * std) anomalies.add(i); });
      return { name: m.label, values: raw, color: m.color, unit: m.unit, anomalies };
    });
  }, [enabledMetrics, trendData]);

  // ---------- 预测线（线性回归，延伸7天） ----------
  const { predictLabels, predictDatasets } = useMemo(() => {
    if (!trendData.length) return { predictLabels: [], predictDatasets: [] };
    const actualLabels = trendData.map((d) => d.date.slice(5)); // MM-DD
    const futureLabels: string[] = [];
    const lastDate = new Date(trendData[trendData.length - 1].date);
    for (let i = 1; i <= PREDICT_DAYS; i++) {
      const fd = new Date(lastDate);
      fd.setDate(fd.getDate() + i);
      futureLabels.push(fd.toISOString().slice(5, 10));
    }
    const allLabels = [...actualLabels, ...futureLabels];

    const pds: LineChartDataset[] = enabledMetrics.map((m) => {
      const raw = trendData.map((d) => {
        const v = (d as unknown as Record<string, number>)[m.key as string] ?? 0;
        return (m.key === 'revenue_fen' || m.key === 'avg_ticket_fen') ? fenToYuan(v) : v;
      });
      // 实际数据（末尾追加预测）
      const recent = raw.slice(-7);
      const { slope, intercept } = linearRegression(recent);
      const predicted: number[] = [
        ...raw.map(() => NaN), // 实际段用NaN（只显示预测段）
      ];
      // 连接点（最后一个实际值）
      predicted[raw.length - 1] = raw[raw.length - 1];
      for (let i = 1; i <= PREDICT_DAYS; i++) {
        predicted.push(Math.max(0, intercept + slope * (recent.length - 1 + i)));
      }
      return { name: `${m.label}(预测)`, values: predicted, color: m.color, unit: m.unit, anomalies: new Set() };
    });
    return { predictLabels: allLabels, predictDatasets: pds };
  }, [trendData, enabledMetrics]);

  // ---------- 指标摘要卡片 ----------
  const metricSummaries = useMemo(() => {
    return enabledMetrics.map((m) => {
      const raw = trendData.map((d) => {
        const v = (d as unknown as Record<string, number>)[m.key as string] ?? 0;
        return (m.key === 'revenue_fen' || m.key === 'avg_ticket_fen') ? fenToYuan(v) : v;
      });
      if (!raw.length) return { ...m, avg: 0, max: 0, min: 0, changePct: 0, anomalyCount: 0 };
      const avg = raw.reduce((s, v) => s + v, 0) / raw.length;
      const max = Math.max(...raw);
      const min = Math.min(...raw);
      // 环比：前半段均值 vs 后半段均值
      const mid = Math.floor(raw.length / 2);
      const firstHalf = raw.slice(0, mid).reduce((s, v) => s + v, 0) / (mid || 1);
      const secondHalf = raw.slice(mid).reduce((s, v) => s + v, 0) / (raw.length - mid || 1);
      const changePct = firstHalf > 0 ? ((secondHalf - firstHalf) / firstHalf) * 100 : 0;
      const { mean, std } = calcMeanStd(raw);
      const anomalyCount = raw.filter((v) => Math.abs(v - mean) > 2 * std).length;
      return { ...m, avg, max, min, changePct, anomalyCount };
    });
  }, [enabledMetrics, trendData]);

  // ---------- AI 趋势解读 ----------
  const handleGenerateReport = useCallback(async () => {
    if (!storeId || !trendData.length) return;
    setAiLoading(true);
    setAiReport(null);
    try {
      const result = await txFetchData<{ synthesis: string }>('/api/v1/orchestrate', {
        method: 'POST',
        body: JSON.stringify({
          intent: `分析门店 ${storeId} 近${days}天的经营趋势，找出关键变化点和原因`,
          context: {
            store_id: storeId,
            days,
            trend_data: trendData,
            metrics: enabledMetrics.map((m) => m.label),
          },
        }),
      });
      setAiReport(result.synthesis || '暂无分析结果');
      setAiExpanded(true);
    } catch (err) {
      setAiReport(`AI 分析失败：${(err as Error).message}`);
    } finally {
      setAiLoading(false);
    }
  }, [storeId, days, trendData, enabledMetrics]);

  // ---------- 图表标签 ----------
  const chartLabels = useMemo(
    () => trendData.map((d) => d.date.slice(5)),
    [trendData],
  );

  // 合并实际折线 + 预测折线数据集（预测数据集用虚线效果：通过数据集分离体现）
  const allDatasets = useMemo(() => {
    if (!trendData.length) return processedDatasets;
    return processedDatasets;
  }, [processedDatasets, trendData]);

  // ---------- 渲染 ----------
  return (
    <div style={{ color: '#e0e0e0', minHeight: '100vh' }}>
      {/* ── Section 1: 控制栏 ─────────────────────────────── */}
      <div style={{
        background: '#112228', borderRadius: 8, padding: '16px 20px',
        marginBottom: 16, display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center',
      }}>
        {/* 标题 */}
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#fff', marginRight: 8 }}>
          趋势分析
        </h2>

        {/* 门店选择 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: '#999' }}>门店</span>
          <select
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
            style={{
              background: '#0B1A20', border: '1px solid #2a3a43', borderRadius: 6,
              color: '#e0e0e0', padding: '5px 10px', fontSize: 13, cursor: 'pointer',
              minWidth: 160,
            }}
          >
            {storeOptions.length === 0 && (
              <option value="">全集团汇总</option>
            )}
            {storeOptions.map((s) => (
              <option key={s.store_id} value={s.store_id}>{s.store_name}</option>
            ))}
          </select>
        </div>

        {/* 时间范围 */}
        <div style={{ display: 'flex', gap: 6 }}>
          {RANGE_OPTIONS.map((r) => (
            <button key={r.key} onClick={() => setTimeRange(r.key)} style={{
              padding: '5px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: timeRange === r.key ? '#FF6B2C' : '#1a2a33',
              color: timeRange === r.key ? '#fff' : '#999',
            }}>
              {r.label}
            </button>
          ))}
        </div>

        {/* 指标多选 */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {metrics.map((m) => (
            <button key={m.key as string} onClick={() => toggleMetric(m.key)} style={{
              padding: '5px 14px', borderRadius: 20, cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              border: m.enabled ? `2px solid ${m.color}` : '2px solid #2a3a43',
              background: m.enabled ? `${m.color}18` : 'transparent',
              color: m.enabled ? m.color : '#666',
              display: 'flex', alignItems: 'center', gap: 5,
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%',
                background: m.enabled ? m.color : '#444',
              }} />
              {m.label}
            </button>
          ))}
        </div>

        {/* 生成报告 */}
        <button
          onClick={handleGenerateReport}
          disabled={aiLoading || !storeId || !trendData.length}
          style={{
            marginLeft: 'auto', padding: '7px 18px', borderRadius: 6, border: 'none',
            cursor: aiLoading || !storeId || !trendData.length ? 'not-allowed' : 'pointer',
            background: '#185FA5', color: '#fff', fontSize: 13, fontWeight: 600,
            opacity: aiLoading || !storeId || !trendData.length ? 0.5 : 1,
            display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          {aiLoading ? (
            <>
              <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid #fff', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
              分析中…
            </>
          ) : '✦ 生成AI报告'}
        </button>
      </div>

      {/* ── Section 2: 趋势折线图 ────────────────────────── */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>
            多指标趋势
            {storeOptions.find((s) => s.store_id === storeId) && (
              <span style={{ fontWeight: 400, fontSize: 12, color: '#999', marginLeft: 8 }}>
                {storeOptions.find((s) => s.store_id === storeId)?.store_name} · 近{days}天
              </span>
            )}
          </h3>
          <div style={{ display: 'flex', gap: 12, fontSize: 11, color: '#666', alignItems: 'center' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 16, height: 2, background: '#FF6B2C', display: 'inline-block' }} />
              实际值
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', border: '1.5px solid #A32D2D', display: 'inline-block' }} />
              异常点（&gt;2σ）
            </span>
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#666' }}>
            <div style={{ fontSize: 13 }}>加载中…</div>
          </div>
        ) : error ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#A32D2D', fontSize: 13 }}>
            {error}
            <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>图表暂无法显示，请检查网络或联系管理员</div>
          </div>
        ) : enabledMetrics.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#666' }}>请在上方选择至少一个指标</div>
        ) : !trendData.length ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#666' }}>暂无趋势数据</div>
        ) : (
          <SVGLineChart
            labels={chartLabels}
            datasets={allDatasets}
            height={300}
          />
        )}
      </div>

      {/* ── Section 3: 指标摘要卡片 ──────────────────────── */}
      {metricSummaries.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${Math.min(metricSummaries.length, 5)}, 1fr)`,
          gap: 12, marginBottom: 16,
        }}>
          {metricSummaries.map((m) => {
            const isUp = m.changePct >= 0;
            return (
              <div key={m.key as string} style={{
                background: '#112228', borderRadius: 8, padding: '14px 16px',
                borderTop: `3px solid ${m.color}`,
              }}>
                <div style={{ fontSize: 12, color: m.color, fontWeight: 700, marginBottom: 10 }}>
                  {m.label}
                </div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#fff', marginBottom: 4 }}>
                  {m.unit === '元'
                    ? `¥${(m.avg / 1).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                    : m.unit === '%'
                    ? `${m.avg.toFixed(1)}%`
                    : m.avg.toFixed(1)
                  }
                </div>
                <div style={{ fontSize: 11, color: '#666', marginBottom: 6 }}>时间段均值</div>
                <div style={{ display: 'flex', gap: 8, fontSize: 11, color: '#999', marginBottom: 6 }}>
                  <span>↑ {m.unit === '元' ? `¥${m.max.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : m.unit === '%' ? `${m.max.toFixed(1)}%` : m.max.toFixed(1)}</span>
                  <span>↓ {m.unit === '元' ? `¥${m.min.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : m.unit === '%' ? `${m.min.toFixed(1)}%` : m.min.toFixed(1)}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{
                    fontSize: 12, fontWeight: 700,
                    color: isUp ? '#0F6E56' : '#A32D2D',
                  }}>
                    {isUp ? '↑' : '↓'} {Math.abs(m.changePct).toFixed(1)}%
                  </span>
                  {m.anomalyCount > 0 && (
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 10,
                      background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
                    }}>
                      {m.anomalyCount} 次异常
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Section 4: AI 趋势解读 ───────────────────────── */}
      {(aiReport || aiLoading) && (
        <div style={{ background: '#0B1A20', borderRadius: 8, marginBottom: 16, border: '1px solid #185FA540' }}>
          <div
            onClick={() => setAiExpanded((v) => !v)}
            style={{
              padding: '14px 20px', display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 10,
                background: '#185FA520', color: '#185FA5', fontWeight: 700,
              }}>AI</span>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>趋势解读</span>
            </div>
            <span style={{ color: '#666', fontSize: 13 }}>{aiExpanded ? '▲ 收起' : '▼ 展开'}</span>
          </div>
          {aiExpanded && (
            <div style={{ padding: '0 20px 20px' }}>
              {aiLoading ? (
                <div style={{ color: '#666', fontSize: 13 }}>AI 正在分析，请稍候…</div>
              ) : (
                <pre style={{
                  margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                  fontSize: 13, lineHeight: 1.7, color: '#c8d8e0',
                  background: '#0d1f28', borderRadius: 6, padding: '14px 16px',
                }}>
                  {aiReport}
                </pre>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Section 5: 预测趋势 + 异常预警列表 ─────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 预测趋势 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700 }}>预测趋势（未来7天）</h3>
          {!trendData.length ? (
            <div style={{ color: '#666', fontSize: 13, textAlign: 'center', padding: 20 }}>暂无数据</div>
          ) : enabledMetrics.length === 0 ? (
            <div style={{ color: '#666', fontSize: 13, textAlign: 'center', padding: 20 }}>请选择指标</div>
          ) : (
            <>
              {/* 预测折线小图 */}
              {predictLabels.length > 0 && predictDatasets.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <SVGLineChart
                    labels={predictLabels}
                    datasets={predictDatasets}
                    height={160}
                  />
                </div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {enabledMetrics.map((m) => {
                  const raw = trendData.map((d) => {
                    const v = (d as unknown as Record<string, number>)[m.key as string] ?? 0;
                    return (m.key === 'revenue_fen' || m.key === 'avg_ticket_fen') ? fenToYuan(v) : v;
                  });
                  const recent = raw.slice(-7);
                  const { slope, intercept } = linearRegression(recent);
                  const lastVal = raw[raw.length - 1] ?? 0;
                  const futureVal = Math.max(0, intercept + slope * (recent.length - 1 + PREDICT_DAYS));
                  const changePct = lastVal > 0 ? ((futureVal - lastVal) / lastVal) * 100 : 0;
                  const isUp = changePct >= 0;
                  return (
                    <div key={m.key as string} style={{
                      padding: '10px 14px', borderRadius: 6, background: '#0B1A20',
                      borderLeft: `3px solid ${m.color}`,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: m.color }}>{m.label}</span>
                        <span style={{ fontSize: 12, fontWeight: 700, color: isUp ? '#0F6E56' : '#A32D2D' }}>
                          {isUp ? '↑' : '↓'} {Math.abs(changePct).toFixed(1)}%
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                        当前 {formatVal(lastVal, m.unit)} → 预测 {formatVal(futureVal, m.unit)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* 异常预警列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
            异常预警
            {bossAlerts.length > 0 && (
              <span style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 10,
                background: '#A32D2D20', color: '#A32D2D', fontWeight: 700,
              }}>{bossAlerts.length}</span>
            )}
          </h3>
          {alertsLoading ? (
            <div style={{ color: '#666', fontSize: 13, textAlign: 'center', padding: 20 }}>加载中…</div>
          ) : bossAlerts.length === 0 ? (
            <div style={{ color: '#666', fontSize: 13, textAlign: 'center', padding: 30 }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>✓</div>
              暂无异常预警
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 480, overflowY: 'auto' }}>
              {bossAlerts.map((a, i) => {
                const sColor = SEVERITY_COLOR[a.severity] || '#666';
                return (
                  <div key={i} style={{
                    padding: '12px 14px', borderRadius: 6, background: '#0B1A20',
                    borderLeft: `3px solid ${sColor}`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{
                          fontSize: 10, padding: '1px 6px', borderRadius: 4,
                          background: `${sColor}25`, color: sColor, fontWeight: 700,
                        }}>
                          {SEVERITY_LABEL[a.severity] || a.severity}
                        </span>
                        <span style={{ fontSize: 12, fontWeight: 600, color: '#ccc' }}>{a.store_name}</span>
                      </div>
                      <span style={{ fontSize: 10, color: '#666' }}>
                        {a.created_at ? new Date(a.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''}
                      </span>
                    </div>
                    <div style={{ fontSize: 12, color: '#aaa', marginBottom: a.suggestion ? 6 : 0 }}>
                      {a.message}
                    </div>
                    {a.suggestion && (
                      <div style={{ fontSize: 11, color: '#185FA5' }}>
                        建议：{a.suggestion}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: '#555', marginTop: 4 }}>
                      指标：{a.metric} · 偏差 {(a.deviation_pct * 100).toFixed(1)}%
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* CSS keyframe for spin */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
