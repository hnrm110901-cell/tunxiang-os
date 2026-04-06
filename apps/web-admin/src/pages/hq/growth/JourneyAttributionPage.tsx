/**
 * JourneyAttributionPage — 旅程归因分析
 * 路由: /hq/growth/journey-attribution
 * 日期筛选 + KPI卡 + 归因表 + 效果对比柱状图
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Table, Tag, Space, Row, Col, Statistic, Select, DatePicker,
  Spin,
} from 'antd';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { txFetch } from '../../../api';
import type { TouchExecution } from '../../../api/growthHubApi';

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

const { RangePicker } = DatePicker;

// ---- 颜色常量 ----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';
const BRAND_ORANGE = '#FF6B35';
const SUCCESS_GREEN = '#52c41a';
const WARNING_ORANGE = '#faad14';
const DANGER_RED = '#ff4d4f';
const INFO_BLUE = '#1890ff';

const MECHANISM_COLORS: Record<string, string> = {
  hook: 'cyan',
  loss_aversion: 'orange',
  repair: 'red',
  mixed: 'purple',
  social_proof: 'blue',
  scarcity: 'gold',
};

const JOURNEY_TYPE_LABELS: Record<string, string> = {
  first_to_second: '首转二',
  reactivation: '激活沉默',
  service_repair: '服务修复',
  retention: '留存维护',
  upsell: '提频升单',
  referral: '裂变拉新',
};

const JOURNEY_TYPE_COLORS: Record<string, string> = {
  first_to_second: 'green',
  reactivation: 'orange',
  service_repair: 'red',
  retention: 'blue',
  upsell: 'purple',
  referral: 'cyan',
};

// ---- 聚合类型 ----
interface AttributionRow {
  journey_name: string;
  journey_type: string;
  mechanism_family: string;
  touch_count: number;
  visit_count: number;
  repurchase_count: number;
  attributed_gmv_fen: number;
  roi: number;
}

// ---- 组件 ----
export function JourneyAttributionPage() {
  const [loading, setLoading] = useState(false);
  const [executions, setExecutions] = useState<TouchExecution[]>([]);
  const [filterType, setFilterType] = useState<string | undefined>();

  const fetchExecutions = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: '1', size: '200' };
      if (filterType) params.journey_type = filterType;
      const qs = new URLSearchParams(params).toString();
      const resp = await txFetch<{ items: TouchExecution[]; total: number }>(
        `/api/v1/growth/touch-executions?${qs}`
      );
      if (resp.data) setExecutions(resp.data.items);
    } catch (err) {
      console.error('fetch executions error', err);
    } finally {
      setLoading(false);
    }
  }, [filterType]);

  useEffect(() => { fetchExecutions(); }, [fetchExecutions]);

  // 前端聚合
  const aggregated = useMemo(() => {
    const map = new Map<string, AttributionRow>();
    executions.forEach((ex) => {
      const key = ex.mechanism_type || 'unknown';
      const existing = map.get(key) || {
        journey_name: key,
        journey_type: '',
        mechanism_family: ex.mechanism_type || 'unknown',
        touch_count: 0,
        visit_count: 0,
        repurchase_count: 0,
        attributed_gmv_fen: 0,
        roi: 0,
      };
      existing.touch_count += 1;
      if (ex.execution_state === 'opened' || ex.execution_state === 'clicked') existing.visit_count += 1;
      if (ex.attributed_revenue_fen && ex.attributed_revenue_fen > 0) {
        existing.repurchase_count += 1;
        existing.attributed_gmv_fen += ex.attributed_revenue_fen;
      }
      map.set(key, existing);
    });
    // 计算ROI
    return Array.from(map.values()).map((row) => ({
      ...row,
      roi: row.touch_count > 0 ? row.attributed_gmv_fen / (row.touch_count * 50) : 0, // 假设单次触达成本50分
    }));
  }, [executions]);

  // KPI
  const kpi = useMemo(() => {
    const totalTouch = executions.length;
    const visited = executions.filter((e) => e.execution_state === 'opened' || e.execution_state === 'clicked').length;
    const repurchased = executions.filter((e) => e.attributed_revenue_fen && e.attributed_revenue_fen > 0).length;
    const totalGmv = executions.reduce((sum, e) => sum + (e.attributed_revenue_fen || 0), 0);
    const totalCost = totalTouch * 50; // 假设单次触达成本50分
    return {
      totalTouch,
      visitRate: totalTouch > 0 ? (visited / totalTouch * 100).toFixed(1) : '0',
      repurchaseRate: totalTouch > 0 ? (repurchased / totalTouch * 100).toFixed(1) : '0',
      roi: totalCost > 0 ? (totalGmv / totalCost).toFixed(1) : '0',
    };
  }, [executions]);

  // 柱状图
  const chartOption = useMemo(() => {
    if (aggregated.length === 0) return {};
    const sorted = [...aggregated].sort((a, b) => b.attributed_gmv_fen - a.attributed_gmv_fen);
    return {
      tooltip: { trigger: 'axis' as const },
      grid: { left: 80, right: 40, top: 40, bottom: 40 },
      xAxis: {
        type: 'category' as const,
        data: sorted.map((r) => r.mechanism_family),
        axisLabel: { color: TEXT_SECONDARY, rotate: 15 },
        axisLine: { lineStyle: { color: BORDER } },
      },
      yAxis: [
        {
          type: 'value' as const, name: '触达人数',
          axisLabel: { color: TEXT_SECONDARY },
          splitLine: { lineStyle: { color: BORDER, type: 'dashed' as const } },
        },
        {
          type: 'value' as const, name: '归因GMV(元)',
          axisLabel: { color: TEXT_SECONDARY, formatter: (v: number) => `¥${(v / 100).toFixed(0)}` },
          splitLine: { show: false },
        },
      ],
      legend: {
        data: ['触达人数', '到店数', '归因GMV'],
        textStyle: { color: TEXT_SECONDARY },
      },
      series: [
        {
          name: '触达人数', type: 'bar', yAxisIndex: 0,
          data: sorted.map((r) => r.touch_count),
          itemStyle: { color: INFO_BLUE },
        },
        {
          name: '到店数', type: 'bar', yAxisIndex: 0,
          data: sorted.map((r) => r.visit_count),
          itemStyle: { color: SUCCESS_GREEN },
        },
        {
          name: '归因GMV', type: 'bar', yAxisIndex: 1,
          data: sorted.map((r) => r.attributed_gmv_fen),
          itemStyle: { color: BRAND_ORANGE },
        },
      ],
    };
  }, [aggregated]);

  const columns = [
    {
      title: '机制类型', dataIndex: 'mechanism_family', key: 'mechanism_family', width: 120,
      render: (val: string) => (
        <Tag color={MECHANISM_COLORS[val] || 'default'}>{val}</Tag>
      ),
    },
    {
      title: '触达人数', dataIndex: 'touch_count', key: 'touch_count', width: 100,
      sorter: (a: AttributionRow, b: AttributionRow) => a.touch_count - b.touch_count,
      render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{val}</span>,
    },
    {
      title: '到店数', dataIndex: 'visit_count', key: 'visit_count', width: 90,
      sorter: (a: AttributionRow, b: AttributionRow) => a.visit_count - b.visit_count,
      render: (val: number) => <span style={{ color: SUCCESS_GREEN }}>{val}</span>,
    },
    {
      title: '复购数', dataIndex: 'repurchase_count', key: 'repurchase_count', width: 90,
      sorter: (a: AttributionRow, b: AttributionRow) => a.repurchase_count - b.repurchase_count,
      render: (val: number) => <span style={{ color: BRAND_ORANGE }}>{val}</span>,
    },
    {
      title: '归因GMV', dataIndex: 'attributed_gmv_fen', key: 'attributed_gmv_fen', width: 120,
      sorter: (a: AttributionRow, b: AttributionRow) => a.attributed_gmv_fen - b.attributed_gmv_fen,
      render: (val: number) => (
        <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>
          ¥{(val / 100).toFixed(0)}
        </span>
      ),
    },
    {
      title: 'ROI', dataIndex: 'roi', key: 'roi', width: 90,
      sorter: (a: AttributionRow, b: AttributionRow) => a.roi - b.roi,
      render: (val: number) => (
        <span style={{
          color: val >= 2 ? SUCCESS_GREEN : val >= 1 ? WARNING_ORANGE : DANGER_RED,
          fontWeight: 600,
        }}>
          {val.toFixed(1)}x
        </span>
      ),
    },
    {
      title: '到店转化率', key: 'visitRate', width: 100,
      render: (_: unknown, record: AttributionRow) => {
        const rate = record.touch_count > 0 ? (record.visit_count / record.touch_count * 100) : 0;
        return (
          <span style={{ color: rate >= 20 ? SUCCESS_GREEN : rate >= 10 ? WARNING_ORANGE : DANGER_RED }}>
            {rate.toFixed(1)}%
          </span>
        );
      },
    },
  ];

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>旅程归因分析</h2>
        <Space>
          <RangePicker
            style={{ background: CARD_BG, borderColor: BORDER }}
            onChange={() => fetchExecutions()}
          />
          <Select
            placeholder="旅程类型"
            value={filterType}
            onChange={setFilterType}
            allowClear
            style={{ width: 150 }}
            options={Object.entries(JOURNEY_TYPE_LABELS).map(([k, v]) => ({ value: k, label: v }))}
          />
        </Space>
      </div>

      {/* KPI卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {[
          { title: '总触达数', value: kpi.totalTouch, color: INFO_BLUE, suffix: '' },
          { title: '到店转化率', value: kpi.visitRate, color: SUCCESS_GREEN, suffix: '%' },
          { title: '复购率', value: kpi.repurchaseRate, color: BRAND_ORANGE, suffix: '%' },
          { title: '旅程ROI', value: kpi.roi, color: WARNING_ORANGE, suffix: 'x' },
        ].map((item) => (
          <Col span={6} key={item.title}>
            <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}>
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>{item.title}</span>}
                value={item.value}
                suffix={item.suffix}
                valueStyle={{ color: item.color, fontSize: 28 }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 归因表 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>归因明细</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
        bodyStyle={{ padding: 0 }}
      >
        <Table
          loading={loading}
          dataSource={aggregated}
          columns={columns}
          rowKey="mechanism_family"
          size="small"
          pagination={false}
          scroll={{ x: 800 }}
        />
      </Card>

      {/* 效果对比图 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>按机制类型效果对比</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
      >
        {aggregated.length > 0 ? (
          <ReactEChartsCore echarts={echarts} option={chartOption} style={{ height: 350 }} />
        ) : (
          <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无数据</div>
        )}
      </Card>
    </div>
  );
}
