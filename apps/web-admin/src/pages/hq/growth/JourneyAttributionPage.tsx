/**
 * JourneyAttributionPage — 旅程归因分析
 * 路由: /hq/growth/journey-attribution
 * 日期筛选 + KPI卡 + 归因表 + 效果对比柱状图
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Table, Tag, Space, Row, Col, Statistic, Select, DatePicker,
  Spin, Tabs,
} from 'antd';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, PieChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { txFetch } from '../../../api';
import { useApi } from '../../../hooks/useApi';
import type { TouchExecution, MechanismAttribution, RepairEffectiveness } from '../../../api/growthHubApi';

echarts.use([BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

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

// ---- 机制类型中文映射 ----
const MECHANISM_LABELS: Record<string, string> = {
  hook: '钩子吸引',
  loss_aversion: '损失规避',
  repair: '服务修复',
  mixed: '混合机制',
  social_proof: '社会认同',
  scarcity: '稀缺效应',
  reciprocity: '互惠心理',
  authority: '权威背书',
  commitment: '承诺一致',
};

// ---- 组件 ----
export function JourneyAttributionPage() {
  const [loading, setLoading] = useState(false);
  const [executions, setExecutions] = useState<TouchExecution[]>([]);
  const [filterType, setFilterType] = useState<string | undefined>();
  const [activeTab, setActiveTab] = useState('overview');

  // 新增数据源
  const { data: mechData } = useApi<{ items: MechanismAttribution[]; days: number }>(
    '/api/v1/growth/attribution/by-mechanism?days=7',
    { cacheMs: 15_000 },
  );
  const { data: repairData } = useApi<RepairEffectiveness>(
    '/api/v1/growth/attribution/repair-effectiveness?days=30',
    { cacheMs: 15_000 },
  );

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

  // ---- 按机制归因Tab的列定义 ----
  const mechColumns = [
    {
      title: '机制类型', dataIndex: 'mechanism_type', key: 'mechanism_type', width: 140,
      render: (val: string) => (
        <Tag color={MECHANISM_COLORS[val] || 'default'}>{MECHANISM_LABELS[val] || val}</Tag>
      ),
    },
    {
      title: '触达数', dataIndex: 'total_touches', key: 'total_touches', width: 90,
      sorter: (a: MechanismAttribution, b: MechanismAttribution) => a.total_touches - b.total_touches,
      render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{val}</span>,
    },
    {
      title: '打开数', dataIndex: 'opened', key: 'opened', width: 90,
      sorter: (a: MechanismAttribution, b: MechanismAttribution) => a.opened - b.opened,
      render: (val: number) => <span style={{ color: SUCCESS_GREEN }}>{val}</span>,
    },
    {
      title: '打开率', dataIndex: 'open_rate', key: 'open_rate', width: 90,
      sorter: (a: MechanismAttribution, b: MechanismAttribution) => a.open_rate - b.open_rate,
      render: (val: number) => (
        <span style={{ color: val >= 20 ? SUCCESS_GREEN : val >= 10 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
          {val.toFixed(1)}%
        </span>
      ),
    },
    {
      title: '归因订单', dataIndex: 'attributed', key: 'attributed', width: 100,
      sorter: (a: MechanismAttribution, b: MechanismAttribution) => a.attributed - b.attributed,
      render: (val: number) => <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>{val}</span>,
    },
    {
      title: '归因率', dataIndex: 'attribution_rate', key: 'attribution_rate', width: 90,
      sorter: (a: MechanismAttribution, b: MechanismAttribution) => a.attribution_rate - b.attribution_rate,
      render: (val: number) => (
        <span style={{ color: val >= 5 ? SUCCESS_GREEN : val >= 2 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
          {val.toFixed(1)}%
        </span>
      ),
    },
    {
      title: '归因GMV', dataIndex: 'revenue_fen', key: 'revenue_fen', width: 120,
      sorter: (a: MechanismAttribution, b: MechanismAttribution) => a.revenue_fen - b.revenue_fen,
      render: (val: number) => (
        <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>
          ¥{(val / 100).toFixed(0)}
        </span>
      ),
    },
  ];

  // ---- 按机制归因的ECharts对比图 ----
  const mechChartOption = useMemo(() => {
    const items = mechData?.items || [];
    if (items.length === 0) return {};
    const sorted = [...items].sort((a, b) => b.revenue_fen - a.revenue_fen);
    return {
      tooltip: { trigger: 'axis' as const },
      grid: { left: 100, right: 40, top: 40, bottom: 40 },
      xAxis: {
        type: 'category' as const,
        data: sorted.map((r) => MECHANISM_LABELS[r.mechanism_type] || r.mechanism_type),
        axisLabel: { color: TEXT_SECONDARY, rotate: 15 },
        axisLine: { lineStyle: { color: BORDER } },
      },
      yAxis: [
        {
          type: 'value' as const, name: '打开率/归因率(%)',
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
        data: ['打开率', '归因率', '归因GMV'],
        textStyle: { color: TEXT_SECONDARY },
      },
      series: [
        {
          name: '打开率', type: 'bar', yAxisIndex: 0,
          data: sorted.map((r) => r.open_rate),
          itemStyle: { color: INFO_BLUE },
        },
        {
          name: '归因率', type: 'bar', yAxisIndex: 0,
          data: sorted.map((r) => r.attribution_rate),
          itemStyle: { color: SUCCESS_GREEN },
        },
        {
          name: '归因GMV', type: 'bar', yAxisIndex: 1,
          data: sorted.map((r) => r.revenue_fen),
          itemStyle: { color: BRAND_ORANGE },
        },
      ],
    };
  }, [mechData]);

  // ---- 修复效果饼图 ----
  const repairPieOption = useMemo(() => {
    if (!repairData) return {};
    return {
      tooltip: { trigger: 'item' as const, formatter: '{b}: {c} ({d}%)' },
      legend: {
        orient: 'vertical' as const, right: 20, top: 'center',
        textStyle: { color: TEXT_SECONDARY },
      },
      series: [{
        type: 'pie', radius: ['40%', '70%'], center: ['40%', '50%'],
        label: { color: TEXT_SECONDARY },
        data: [
          { value: repairData.recovered, name: '已修复', itemStyle: { color: SUCCESS_GREEN } },
          { value: repairData.failed, name: '失败', itemStyle: { color: DANGER_RED } },
          { value: repairData.in_progress, name: '进行中', itemStyle: { color: WARNING_ORANGE } },
          { value: repairData.closed, name: '已关闭', itemStyle: { color: TEXT_SECONDARY } },
        ].filter((d) => d.value > 0),
      }],
    };
  }, [repairData]);

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

      {/* Tabs: 总览 / 按机制归因 / 修复效果 */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        style={{ marginBottom: 16 }}
        items={[
          {
            key: 'overview',
            label: <span style={{ color: TEXT_PRIMARY }}>总览</span>,
            children: (
              <>
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
              </>
            ),
          },
          {
            key: 'by-mechanism',
            label: <span style={{ color: TEXT_PRIMARY }}>按机制归因</span>,
            children: (
              <>
                {/* 机制归因表格 */}
                <Card
                  title={<span style={{ color: TEXT_PRIMARY }}>按心理机制维度归因（近7天）</span>}
                  style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
                  styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                  bodyStyle={{ padding: 0 }}
                >
                  <Table
                    dataSource={mechData?.items || []}
                    columns={mechColumns}
                    rowKey="mechanism_type"
                    size="small"
                    pagination={false}
                    scroll={{ x: 800 }}
                    locale={{ emptyText: <span style={{ color: TEXT_SECONDARY }}>暂无机制归因数据</span> }}
                  />
                </Card>

                {/* 机制对比图：打开率 vs 归因率 vs GMV */}
                <Card
                  title={<span style={{ color: TEXT_PRIMARY }}>模板框架效果对比（打开率/归因率/GMV）</span>}
                  style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                  styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                >
                  {(mechData?.items || []).length > 0 ? (
                    <ReactEChartsCore echarts={echarts} option={mechChartOption} style={{ height: 380 }} />
                  ) : (
                    <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无数据</div>
                  )}
                </Card>
              </>
            ),
          },
          {
            key: 'repair',
            label: <span style={{ color: TEXT_PRIMARY }}>修复效果</span>,
            children: (
              <>
                {/* 修复KPI卡片 */}
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  {[
                    { title: '总案例数', value: repairData?.total_cases ?? '--', color: INFO_BLUE, suffix: '' },
                    { title: '修复率', value: repairData?.recovery_rate != null ? `${repairData.recovery_rate}` : '--', color: SUCCESS_GREEN, suffix: '%' },
                    { title: '平均修复时长', value: repairData?.avg_recovery_hours != null ? `${repairData.avg_recovery_hours}` : '--', color: WARNING_ORANGE, suffix: 'h' },
                    { title: '平均响应时长', value: repairData?.avg_ack_minutes != null ? `${repairData.avg_ack_minutes}` : '--', color: BRAND_ORANGE, suffix: 'min' },
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

                {/* 修复状态分布饼图 */}
                <Card
                  title={<span style={{ color: TEXT_PRIMARY }}>修复状态分布（近30天）</span>}
                  style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                  styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                >
                  {repairData && repairData.total_cases > 0 ? (
                    <ReactEChartsCore echarts={echarts} option={repairPieOption} style={{ height: 350 }} />
                  ) : (
                    <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无修复案例数据</div>
                  )}
                </Card>
              </>
            ),
          },
        ]}
      />
    </div>
  );
}
