/**
 * JourneyAttributionPage — 旅程归因分析
 * 路由: /hq/growth/journey-attribution
 * 日期筛选 + KPI卡 + 归因表 + 效果对比柱状图
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import {
  Card, Table, Tag, Space, Row, Col, Statistic, Select, DatePicker,
  Spin, Tabs, Drawer, Collapse,
} from 'antd';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, PieChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { txFetchData } from '../../../api';
import { useApi } from '../../../hooks/useApi';
import type { TouchExecution, MechanismAttribution, RepairEffectiveness, JourneyTemplateAttribution, JourneyEnrollmentDetail, StoreAttribution } from '../../../api/growthHubApi';

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

  // 缺口3: 日期范围状态
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(7, 'day'), dayjs()]);
  const days = useMemo(() => Math.max(1, dateRange[1].diff(dateRange[0], 'day')), [dateRange]);

  // 缺口4: 下钻Drawer状态
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTemplateId, setDrawerTemplateId] = useState<string | null>(null);
  const [drawerData, setDrawerData] = useState<JourneyEnrollmentDetail[]>([]);
  const [drawerLoading, setDrawerLoading] = useState(false);

  // 数据源 — 使用days驱动刷新
  const { data: mechData } = useApi<{ items: MechanismAttribution[]; days: number }>(
    `/api/v1/growth/attribution/by-mechanism?days=${days}`,
    { cacheMs: 15_000 },
  );
  const { data: repairData } = useApi<RepairEffectiveness>(
    `/api/v1/growth/attribution/repair-effectiveness?days=${Math.max(days, 30)}`,
    { cacheMs: 15_000 },
  );

  // 缺口1: 模板框架归因Tab数据
  const { data: templateAttrData } = useApi<{ items: JourneyTemplateAttribution[]; days: number }>(
    `/api/v1/growth/attribution/by-journey-template?days=${days}`,
    { cacheMs: 15_000 },
  );

  // Sprint G: 门店归因Tab数据
  const { data: storeAttrData } = useApi<{ items: StoreAttribution[]; days: number }>(
    `/api/v1/growth/attribution/by-store?days=${days}`,
    { cacheMs: 15_000 },
  );

  const fetchExecutions = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: '1', size: '200' };
      if (filterType) params.journey_type = filterType;
      const qs = new URLSearchParams(params).toString();
      const resp = await txFetchData<{ items: TouchExecution[]; total: number }>(
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

  // 缺口4: 打开下钻drawer
  const openEnrollmentDrawer = useCallback(async (templateId: string) => {
    setDrawerTemplateId(templateId);
    setDrawerOpen(true);
    setDrawerLoading(true);
    try {
      const resp = await txFetchData<{ items: JourneyEnrollmentDetail[]; total: number }>(
        `/api/v1/growth/journey-enrollments?journey_template_id=${templateId}&size=20`
      );
      if (resp.data) setDrawerData(resp.data.items);
    } catch (err) {
      console.error('fetch enrollment detail error', err);
      setDrawerData([]);
    } finally {
      setDrawerLoading(false);
    }
  }, []);

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
    {
      title: '操作', key: 'action', width: 90,
      render: (_: unknown, record: AttributionRow) => (
        <a
          style={{ color: INFO_BLUE, cursor: 'pointer', fontSize: 12 }}
          onClick={() => openEnrollmentDrawer(record.mechanism_family)}
        >
          查看详情
        </a>
      ),
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
            value={dateRange}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setDateRange([dates[0], dates[1]]);
                fetchExecutions();
              }
            }}
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

                {/* 缺口5: P1客户分层归因折叠区域 */}
                <Collapse
                  style={{ marginTop: 16, background: CARD_BG, border: `1px solid ${BORDER}` }}
                  items={[{
                    key: 'p1-segmentation',
                    label: <span style={{ color: TEXT_PRIMARY }}>按客户分层交叉分析</span>,
                    children: (() => {
                      const mechItems = mechData?.items || [];
                      if (mechItems.length === 0) return <div style={{ color: TEXT_SECONDARY, padding: 16 }}>暂无机制归因数据</div>;
                      const psychLevels = ['near', 'habit_break', 'fading', 'abstracted', 'lost'];
                      const psychLabels: Record<string, string> = { near: '亲近', habit_break: '习惯断裂', fading: '淡化', abstracted: '疏远', lost: '失联' };
                      return (
                        <div style={{ overflowX: 'auto' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                            <thead>
                              <tr>
                                <th style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_SECONDARY, borderBottom: `1px solid ${BORDER}` }}>心理距离 \ 机制</th>
                                {mechItems.map(m => (
                                  <th key={m.mechanism_type} style={{ textAlign: 'center', padding: '8px 6px', color: TEXT_SECONDARY, borderBottom: `1px solid ${BORDER}` }}>
                                    {MECHANISM_LABELS[m.mechanism_type] || m.mechanism_type}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {psychLevels.map(level => (
                                <tr key={level}>
                                  <td style={{ padding: '6px 10px', color: TEXT_PRIMARY, borderBottom: `1px solid ${BORDER}` }}>
                                    {psychLabels[level]}
                                  </td>
                                  {mechItems.map(m => (
                                    <td key={m.mechanism_type} style={{ textAlign: 'center', padding: '6px', color: TEXT_SECONDARY, borderBottom: `1px solid ${BORDER}` }}>
                                      <span style={{ color: INFO_BLUE, fontSize: 11 }}>P2</span>
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <div style={{ marginTop: 12, padding: '10px 12px', background: `${INFO_BLUE}11`, borderRadius: 6, fontSize: 11, color: TEXT_SECONDARY }}>
                            交叉分析将在 P2 阶段接入后端聚合端点，当前为结构占位。
                            预期可回答 &quot;哪种机制对 fading 客户最有效&quot; 等问题。
                          </div>
                        </div>
                      );
                    })(),
                  }]}
                />
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
          {
            key: 'by-template',
            label: <span style={{ color: TEXT_PRIMARY }}>按模板框架归因</span>,
            children: (() => {
              const items = templateAttrData?.items || [];
              const templateColumns = [
                { title: '模板名称', dataIndex: 'template_name', key: 'template_name', width: 160,
                  render: (val: string) => <span style={{ color: TEXT_PRIMARY, fontWeight: 500 }}>{val}</span> },
                { title: '旅程类型', dataIndex: 'journey_type', key: 'journey_type', width: 100,
                  render: (val: string) => <Tag color={JOURNEY_TYPE_COLORS[val] || 'default'}>{JOURNEY_TYPE_LABELS[val] || val}</Tag> },
                { title: '机制框架', dataIndex: 'mechanism_family', key: 'mechanism_family', width: 100,
                  render: (val: string) => <Tag color={MECHANISM_COLORS[val] || 'default'}>{MECHANISM_LABELS[val] || val}</Tag> },
                { title: 'enrollment数', dataIndex: 'total_enrollments', key: 'total_enrollments', width: 100,
                  sorter: (a: JourneyTemplateAttribution, b: JourneyTemplateAttribution) => a.total_enrollments - b.total_enrollments,
                  render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{val}</span> },
                { title: '完成率', dataIndex: 'completion_rate', key: 'completion_rate', width: 80,
                  sorter: (a: JourneyTemplateAttribution, b: JourneyTemplateAttribution) => a.completion_rate - b.completion_rate,
                  render: (val: number) => <span style={{ color: val >= 30 ? SUCCESS_GREEN : val >= 15 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>{val.toFixed(1)}%</span> },
                { title: '触达数', dataIndex: 'total_touches', key: 'total_touches', width: 80,
                  render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{val}</span> },
                { title: '打开数', dataIndex: 'opened', key: 'opened', width: 80,
                  render: (val: number) => <span style={{ color: SUCCESS_GREEN }}>{val}</span> },
                { title: '归因订单', dataIndex: 'attributed', key: 'attributed', width: 80,
                  sorter: (a: JourneyTemplateAttribution, b: JourneyTemplateAttribution) => a.attributed - b.attributed,
                  render: (val: number) => <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>{val}</span> },
                { title: '归因GMV', dataIndex: 'revenue_fen', key: 'revenue_fen', width: 100,
                  sorter: (a: JourneyTemplateAttribution, b: JourneyTemplateAttribution) => a.revenue_fen - b.revenue_fen,
                  render: (val: number) => <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>¥{(val / 100).toFixed(0)}</span> },
              ];

              const templateChartOption = (() => {
                if (items.length === 0) return {};
                const sorted = [...items].sort((a, b) => b.revenue_fen - a.revenue_fen).slice(0, 10);
                return {
                  tooltip: { trigger: 'axis' as const },
                  grid: { left: 100, right: 40, top: 40, bottom: 60 },
                  xAxis: {
                    type: 'category' as const,
                    data: sorted.map(r => r.template_name.length > 8 ? r.template_name.slice(0, 8) + '..' : r.template_name),
                    axisLabel: { color: TEXT_SECONDARY, rotate: 20 },
                    axisLine: { lineStyle: { color: BORDER } },
                  },
                  yAxis: {
                    type: 'value' as const, name: '百分比(%)',
                    axisLabel: { color: TEXT_SECONDARY },
                    splitLine: { lineStyle: { color: BORDER, type: 'dashed' as const } },
                  },
                  legend: {
                    data: ['完成率', '打开率', '归因率'],
                    textStyle: { color: TEXT_SECONDARY },
                  },
                  series: [
                    { name: '完成率', type: 'bar', data: sorted.map(r => r.completion_rate), itemStyle: { color: INFO_BLUE } },
                    { name: '打开率', type: 'bar', data: sorted.map(r => r.total_touches > 0 ? +(r.opened / r.total_touches * 100).toFixed(1) : 0), itemStyle: { color: SUCCESS_GREEN } },
                    { name: '归因率', type: 'bar', data: sorted.map(r => r.total_touches > 0 ? +(r.attributed / r.total_touches * 100).toFixed(1) : 0), itemStyle: { color: BRAND_ORANGE } },
                  ],
                };
              })();

              return (
                <>
                  <Card
                    title={<span style={{ color: TEXT_PRIMARY }}>按模板框架归因明细（近{days}天）</span>}
                    style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
                    styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                    bodyStyle={{ padding: 0 }}
                  >
                    <Table
                      dataSource={items}
                      columns={templateColumns}
                      rowKey="template_name"
                      size="small"
                      pagination={false}
                      scroll={{ x: 900 }}
                      locale={{ emptyText: <span style={{ color: TEXT_SECONDARY }}>暂无模板归因数据</span> }}
                    />
                  </Card>
                  <Card
                    title={<span style={{ color: TEXT_PRIMARY }}>模板框架效果对比（完成率/打开率/归因率）</span>}
                    style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                    styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                  >
                    {items.length > 0 ? (
                      <ReactEChartsCore echarts={echarts} option={templateChartOption} style={{ height: 380 }} />
                    ) : (
                      <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无数据</div>
                    )}
                  </Card>
                </>
              );
            })(),
          },
          {
            key: 'recall-comparison',
            label: <span style={{ color: TEXT_PRIMARY }}>召回框架对比</span>,
            children: (() => {
              const mechItems = mechData?.items || [];
              const recallMechanisms: Record<string, { label: string; color: string }> = {
                loss_aversion: { label: '权益到期型', color: WARNING_ORANGE },
                relationship_warmup: { label: '关系唤醒型', color: INFO_BLUE },
                minimal_action: { label: '最小行动型', color: SUCCESS_GREEN },
              };
              // Filter reactivation-related mechanisms; fallback to all loss_aversion type items
              const recallKeys = Object.keys(recallMechanisms);
              const recallItems = mechItems.filter(m => recallKeys.includes(m.mechanism_type));
              // If no exact matches, show the first 3 mechanisms as fallback
              const displayItems = recallItems.length > 0 ? recallItems : mechItems.slice(0, 3);

              return (
                <Row gutter={16}>
                  {displayItems.map((m) => {
                    const cfg = recallMechanisms[m.mechanism_type] || { label: MECHANISM_LABELS[m.mechanism_type] || m.mechanism_type, color: TEXT_SECONDARY };
                    const openRate = m.total_touches > 0 ? (m.opened / m.total_touches * 100) : 0;
                    const attrRate = m.total_touches > 0 ? (m.attributed / m.total_touches * 100) : 0;
                    return (
                      <Col span={8} key={m.mechanism_type}>
                        <Card
                          style={{ background: CARD_BG, border: `1px solid ${BORDER}`, borderTop: `3px solid ${cfg.color}` }}
                          styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                          title={<span style={{ color: cfg.color, fontWeight: 700 }}>{cfg.label}</span>}
                        >
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: TEXT_SECONDARY, fontSize: 13 }}>触达数</span>
                              <span style={{ color: TEXT_PRIMARY, fontSize: 16, fontWeight: 700 }}>{m.total_touches}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: TEXT_SECONDARY, fontSize: 13 }}>打开率</span>
                              <span style={{ color: openRate >= 20 ? SUCCESS_GREEN : openRate >= 10 ? WARNING_ORANGE : DANGER_RED, fontSize: 16, fontWeight: 700 }}>{openRate.toFixed(1)}%</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: TEXT_SECONDARY, fontSize: 13 }}>归因到店率</span>
                              <span style={{ color: attrRate >= 5 ? SUCCESS_GREEN : attrRate >= 2 ? WARNING_ORANGE : DANGER_RED, fontSize: 16, fontWeight: 700 }}>{attrRate.toFixed(1)}%</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <span style={{ color: TEXT_SECONDARY, fontSize: 13 }}>归因GMV</span>
                              <span style={{ color: BRAND_ORANGE, fontSize: 16, fontWeight: 700 }}>¥{(m.revenue_fen / 100).toFixed(0)}</span>
                            </div>
                          </div>
                        </Card>
                      </Col>
                    );
                  })}
                  {displayItems.length === 0 && (
                    <Col span={24}>
                      <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无召回机制归因数据</div>
                    </Col>
                  )}
                </Row>
              );
            })(),
          },
          {
            key: 'by-store',
            label: <span style={{ color: TEXT_PRIMARY }}>门店归因</span>,
            children: (() => {
              const storeItems = storeAttrData?.items || [];
              const storeColumns = [
                { title: '门店', dataIndex: 'store_name', key: 'store_name', width: 140,
                  render: (val: string, record: StoreAttribution) => <span style={{ color: TEXT_PRIMARY, fontWeight: 500 }}>{val || (record.store_id ? record.store_id.slice(0, 10) : '--')}</span> },
                { title: '触达数', dataIndex: 'total_touches', key: 'total_touches', width: 90,
                  sorter: (a: StoreAttribution, b: StoreAttribution) => (a.total_touches ?? 0) - (b.total_touches ?? 0),
                  render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{val ?? 0}</span> },
                { title: '打开数', dataIndex: 'opened', key: 'opened', width: 90,
                  sorter: (a: StoreAttribution, b: StoreAttribution) => (a.opened ?? 0) - (b.opened ?? 0),
                  render: (val: number) => <span style={{ color: SUCCESS_GREEN }}>{val ?? 0}</span> },
                { title: '打开率', dataIndex: 'open_rate', key: 'open_rate', width: 80,
                  sorter: (a: StoreAttribution, b: StoreAttribution) => (a.open_rate ?? 0) - (b.open_rate ?? 0),
                  render: (val: number) => (
                    <span style={{ color: (val ?? 0) >= 20 ? SUCCESS_GREEN : (val ?? 0) >= 10 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
                      {(val ?? 0).toFixed(1)}%
                    </span>
                  ) },
                { title: '归因订单', dataIndex: 'attributed_orders', key: 'attributed_orders', width: 90,
                  sorter: (a: StoreAttribution, b: StoreAttribution) => (a.attributed_orders ?? 0) - (b.attributed_orders ?? 0),
                  render: (val: number) => <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>{val ?? 0}</span> },
                { title: '归因率', dataIndex: 'attribution_rate', key: 'attribution_rate', width: 80,
                  sorter: (a: StoreAttribution, b: StoreAttribution) => (a.attribution_rate ?? 0) - (b.attribution_rate ?? 0),
                  render: (val: number) => (
                    <span style={{ color: (val ?? 0) >= 5 ? SUCCESS_GREEN : (val ?? 0) >= 2 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
                      {(val ?? 0).toFixed(1)}%
                    </span>
                  ) },
                { title: '归因GMV', dataIndex: 'attributed_gmv_fen', key: 'attributed_gmv_fen', width: 110,
                  sorter: (a: StoreAttribution, b: StoreAttribution) => (a.attributed_gmv_fen ?? 0) - (b.attributed_gmv_fen ?? 0),
                  render: (val: number) => <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>¥{((val ?? 0) / 100).toFixed(0)}</span> },
              ];

              const storeChartOption = (() => {
                if (storeItems.length === 0) return {};
                const sorted = [...storeItems]
                  .sort((a, b) => (b.attributed_gmv_fen ?? 0) - (a.attributed_gmv_fen ?? 0))
                  .slice(0, 10);
                return {
                  tooltip: { trigger: 'axis' as const },
                  grid: { left: 120, right: 40, top: 40, bottom: 30 },
                  xAxis: {
                    type: 'value' as const,
                    name: '归因GMV(元)',
                    axisLabel: { color: TEXT_SECONDARY, formatter: (v: number) => `¥${(v / 100).toFixed(0)}` },
                    splitLine: { lineStyle: { color: BORDER, type: 'dashed' as const } },
                  },
                  yAxis: {
                    type: 'category' as const,
                    data: [...sorted].reverse().map(s => s.store_name || (s.store_id ? s.store_id.slice(0, 8) : '--')),
                    axisLabel: { color: TEXT_SECONDARY, fontSize: 11 },
                    axisLine: { lineStyle: { color: BORDER } },
                  },
                  series: [{
                    name: '归因GMV',
                    type: 'bar',
                    data: [...sorted].reverse().map(s => s.attributed_gmv_fen ?? 0),
                    itemStyle: { color: BRAND_ORANGE },
                    label: {
                      show: true, position: 'right', color: TEXT_SECONDARY, fontSize: 11,
                      formatter: (p: { value: number }) => `¥${(p.value / 100).toFixed(0)}`,
                    },
                  }],
                };
              })();

              return (
                <>
                  <Card
                    title={<span style={{ color: TEXT_PRIMARY }}>按门店归因明细（近{days}天）</span>}
                    style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
                    styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                    bodyStyle={{ padding: 0 }}
                  >
                    <Table
                      dataSource={storeItems}
                      columns={storeColumns}
                      rowKey="store_id"
                      size="small"
                      pagination={false}
                      scroll={{ x: 700 }}
                      locale={{ emptyText: <span style={{ color: TEXT_SECONDARY }}>暂无门店归因数据</span> }}
                    />
                  </Card>
                  <Card
                    title={<span style={{ color: TEXT_PRIMARY }}>Top 10 门店归因GMV排名</span>}
                    style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
                    styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
                  >
                    {storeItems.length > 0 ? (
                      <ReactEChartsCore echarts={echarts} option={storeChartOption} style={{ height: 400 }} />
                    ) : (
                      <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无门店数据</div>
                    )}
                  </Card>
                </>
              );
            })(),
          },
        ]}
      />

      {/* 缺口4: 个体客户旅程下钻Drawer */}
      <Drawer
        title={<span style={{ color: TEXT_PRIMARY }}>旅程enrollment详情</span>}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setDrawerData([]); setDrawerTemplateId(null); }}
        width={700}
        styles={{
          header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}` },
          body: { background: PAGE_BG, padding: 16 },
        }}
      >
        {drawerTemplateId && (
          <div style={{ marginBottom: 12, fontSize: 12, color: TEXT_SECONDARY }}>
            模板/机制: <Tag color="blue">{drawerTemplateId}</Tag>
          </div>
        )}
        {drawerLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : (
          <Table
            dataSource={drawerData}
            rowKey="id"
            size="small"
            pagination={false}
            scroll={{ x: 600 }}
            locale={{ emptyText: <span style={{ color: TEXT_SECONDARY }}>暂无enrollment数据</span> }}
            columns={[
              { title: '客户ID', dataIndex: 'customer_id', key: 'customer_id', width: 140,
                render: (val: string) => <span style={{ color: TEXT_PRIMARY, fontSize: 11 }}>{val.slice(0, 12)}...</span> },
              { title: '状态', dataIndex: 'journey_state', key: 'journey_state', width: 80,
                render: (val: string) => {
                  const stateColors: Record<string, string> = { active: 'green', completed: 'blue', paused: 'orange', exited: 'red', observing: 'cyan' };
                  return <Tag color={stateColors[val] || 'default'}>{val}</Tag>;
                }},
              { title: '当前步骤', dataIndex: 'current_step_no', key: 'current_step_no', width: 80,
                render: (val: number | null) => <span style={{ color: TEXT_PRIMARY }}>{val ?? '--'}</span> },
              { title: '进入时间', dataIndex: 'entered_at', key: 'entered_at', width: 140,
                render: (val: string) => <span style={{ color: TEXT_SECONDARY, fontSize: 11 }}>{val ? dayjs(val).format('YYYY-MM-DD HH:mm') : '--'}</span> },
              { title: '完成/退出时间', key: 'end_time', width: 140,
                render: (_: unknown, record: JourneyEnrollmentDetail) => {
                  const t = record.completed_at || record.exited_at;
                  return <span style={{ color: TEXT_SECONDARY, fontSize: 11 }}>{t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '--'}</span>;
                }},
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
