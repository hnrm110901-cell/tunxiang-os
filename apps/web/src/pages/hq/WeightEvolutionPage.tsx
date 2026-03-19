/**
 * 决策权重演化页（总部视角）
 * 路由：/hq/weight-evolution
 * 数据：GET /api/v1/decisions/weight-history?store_id={store_id}
 *
 * 展示 AI 在线学习过程中，四个决策维度权重随反馈数据的演化曲线。
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  ZCard, ZKpi, ZButton, ZSkeleton, ZEmpty, ZSelect,
} from '../../design-system/components';
import apiClient from '../../services/api';
import ReactECharts from 'echarts-for-react';
import styles from './WeightEvolutionPage.module.css';

// ── 常量 ───────────────────────────────────────────────────────────────────────

const DEMO_STORES = [
  { value: 'store_001', label: '北京朝阳店' },
  { value: 'store_002', label: '上海浦东店' },
  { value: 'store_003', label: '广州天河店' },
];

const DIM_LABELS: Record<string, string> = {
  financial:  '财务影响',
  urgency:    '紧迫程度',
  confidence: '置信度',
  execution:  '执行难度',
};

const DIM_COLORS: Record<string, string> = {
  financial:  '#FF6B2C',
  urgency:    '#007AFF',
  confidence: '#34C759',
  execution:  '#FF9500',
};

const DIMS = ['financial', 'urgency', 'confidence', 'execution'] as const;

// ── 类型 ───────────────────────────────────────────────────────────────────────

interface WeightSnapshot {
  ts:         string;
  financial:  number;
  urgency:    number;
  confidence: number;
  execution:  number;
}

interface WeightHistoryData {
  store_id:     string;
  current:      Record<string, number>;
  history:      WeightSnapshot[];
  sample_count: number;
}

// ── 图表 Option ───────────────────────────────────────────────────────────────

function buildChartOption(history: WeightSnapshot[]) {
  const labels = history.map(p => {
    const d = new Date(p.ts);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  });

  return {
    legend: {
      data: DIMS.map(d => DIM_LABELS[d]),
      bottom: 0,
      textStyle: { fontSize: 12 },
    },
    grid: { top: 12, bottom: 44, left: 48, right: 16 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { fontSize: 11, color: 'var(--text-tertiary)' },
      axisLine: { lineStyle: { color: 'var(--border-subtle, #f0f0f0)' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 0.65,
      splitLine: { lineStyle: { color: 'var(--border-subtle, #f0f0f0)' } },
      axisLabel: {
        formatter: (v: number) => `${Math.round(v * 100)}%`,
        fontSize: 11,
        color: 'var(--text-tertiary)',
      },
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) =>
        params.map(p =>
          `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${(p.value * 100).toFixed(1)}%</b>`
        ).join('<br/>'),
    },
    series: DIMS.map(dim => ({
      name:       DIM_LABELS[dim],
      type:       'line',
      smooth:     true,
      symbol:     'circle',
      symbolSize: 5,
      data:       history.map(p => p[dim]),
      lineStyle:  { color: DIM_COLORS[dim], width: 2 },
      itemStyle:  { color: DIM_COLORS[dim] },
    })),
  };
}

// ════════════════════════════════════════════════════════════════════════════
// WeightEvolutionPage
// ════════════════════════════════════════════════════════════════════════════

const WeightEvolutionPage: React.FC = () => {
  const [storeId, setStoreId] = useState(DEMO_STORES[0].value);
  const [loading, setLoading] = useState(false);
  const [data,    setData]    = useState<WeightHistoryData | null>(null);
  const [error,   setError]   = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get('/api/v1/decisions/weight-history', {
        params: { store_id: storeId },
      });
      setData(res.data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || '数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className={styles.page}>

      {/* ── 页头 ── */}
      <div className={styles.header}>
        <div>
          <h2 className={styles.title}>决策权重演化</h2>
          <span className={styles.subtitle}>AI 在线策略梯度学习 · 权重随执行反馈自动校正</span>
        </div>
        <div className={styles.headerActions}>
          <ZSelect
            value={storeId}
            onChange={v => setStoreId(v as string)}
            options={DEMO_STORES}
            style={{ width: 140 }}
          />
          <ZButton size="sm" onClick={load} loading={loading}>刷新</ZButton>
        </div>
      </div>

      {loading && !data ? (
        <ZSkeleton rows={6} />
      ) : error ? (
        <ZEmpty description={error} />
      ) : !data ? (
        <ZEmpty description="暂无权重数据" />
      ) : (
        <div className={styles.body}>

          {/* ── 当前权重快照 KPI ── */}
          <div className={styles.kpiGrid}>
            {DIMS.map(dim => (
              <ZCard key={dim} className={styles.kpiCard}>
                <div className={styles.kpiDot} style={{ background: DIM_COLORS[dim] }} />
                <ZKpi
                  label={DIM_LABELS[dim]}
                  value={`${((data.current[dim] ?? 0) * 100).toFixed(1)}%`}
                  size="md"
                  color={DIM_COLORS[dim]}
                />
              </ZCard>
            ))}
          </div>

          {/* ── 权重演化折线图 ── */}
          <ZCard
            title={`权重演化趋势（已学习 ${data.sample_count} 条执行反馈）`}
          >
            {data.history.length < 2 ? (
              <ZEmpty description="反馈样本不足 2 条，暂无趋势图" />
            ) : (
              <ReactECharts
                option={buildChartOption(data.history)}
                style={{ height: 300 }}
                opts={{ renderer: 'canvas' }}
              />
            )}
          </ZCard>

          {/* ── 学习机制说明 ── */}
          <ZCard title="学习机制">
            <div className={styles.mechanism}>
              <div className={styles.mechItem}>
                <span className={styles.mechStep}>①</span>
                <span className={styles.mechText}>
                  执行决策后，店长填写「执行结果反馈」（节省¥ + 成功/部分/失败）
                </span>
              </div>
              <div className={styles.mechItem}>
                <span className={styles.mechStep}>②</span>
                <span className={styles.mechText}>
                  系统计算准确率比 = 实际节省 / 预期节省，超预期上限 2.0，失败归零
                </span>
              </div>
              <div className={styles.mechItem}>
                <span className={styles.mechStep}>③</span>
                <span className={styles.mechText}>
                  优势函数 = 准确率比 − 1；各维度梯度 = 优势 × 相对偏差，梯度之和 ≈ 0
                </span>
              </div>
              <div className={styles.mechItem}>
                <span className={styles.mechStep}>④</span>
                <span className={styles.mechText}>
                  迭代裁剪 + 归一化，保证每维权重在 [5%, 60%] 且总和 = 100%
                </span>
              </div>
            </div>
          </ZCard>

        </div>
      )}
    </div>
  );
};

export default WeightEvolutionPage;
