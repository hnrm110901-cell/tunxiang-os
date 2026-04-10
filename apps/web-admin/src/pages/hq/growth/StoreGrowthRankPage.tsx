/**
 * StoreGrowthRankPage — 门店增长排行
 * 路由: /hq/growth/store-ranking
 * Sprint G: 门店维度前端 — 对比各门店的增长表现
 */
import { useState, useMemo } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import {
  Card, Table, Tag, Space, Select, DatePicker, Spin,
} from 'antd';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { useApi } from '../../../hooks/useApi';
import type { StoreAttribution } from '../../../api/growthHubApi';

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

const { RangePicker } = DatePicker;

// ---- 颜色常量（深色主题）----
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
const GOLD = '#ffd700';
const SILVER = '#c0c0c0';
const BRONZE = '#cd7f32';

type SortMetric = 'second_visit_rate' | 'recall_rate' | 'stored_value_rate' | 'journey_roi';

const SORT_OPTIONS: { value: SortMetric; label: string }[] = [
  { value: 'second_visit_rate', label: '二访率' },
  { value: 'recall_rate', label: '召回率' },
  { value: 'stored_value_rate', label: '储值转化率' },
  { value: 'journey_roi', label: '旅程ROI' },
];

const BRAND_OPTIONS = ['全部品牌', '尝在一起', '最黔线', '尚宫厨'];

export function StoreGrowthRankPage() {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(7, 'day'), dayjs()]);
  const [brand, setBrand] = useState<string>('全部品牌');
  const [sortMetric, setSortMetric] = useState<SortMetric>('second_visit_rate');

  const days = useMemo(() => Math.max(1, dateRange[1].diff(dateRange[0], 'day')), [dateRange]);

  const { data, loading } = useApi<{ items: StoreAttribution[]; days: number }>(
    `/api/v1/growth/attribution/by-store?days=${days}`,
    { cacheMs: 15_000 },
  );

  const items = useMemo(() => {
    const raw = data?.items || [];
    // brand filter (if not "全部品牌")
    const filtered = brand === '全部品牌' ? raw : raw.filter(s => s.brand_name === brand);
    // sort by selected metric desc
    return [...filtered].sort((a, b) => {
      const va = (a as Record<string, unknown>)[sortMetric] as number ?? 0;
      const vb = (b as Record<string, unknown>)[sortMetric] as number ?? 0;
      return vb - va;
    });
  }, [data, brand, sortMetric]);

  // Top 10 chart
  const chartOption = useMemo(() => {
    const top10 = items.slice(0, 10);
    if (top10.length === 0) return {};
    const metricLabel = SORT_OPTIONS.find(o => o.value === sortMetric)?.label || sortMetric;
    return {
      tooltip: { trigger: 'axis' as const },
      grid: { left: 120, right: 40, top: 40, bottom: 30 },
      xAxis: {
        type: 'value' as const,
        axisLabel: { color: TEXT_SECONDARY },
        splitLine: { lineStyle: { color: BORDER, type: 'dashed' as const } },
      },
      yAxis: {
        type: 'category' as const,
        data: [...top10].reverse().map(s => s.store_name || s.store_id.slice(0, 8)),
        axisLabel: { color: TEXT_SECONDARY, fontSize: 11 },
        axisLine: { lineStyle: { color: BORDER } },
      },
      series: [{
        name: metricLabel,
        type: 'bar',
        data: [...top10].reverse().map(s => {
          const val = (s as Record<string, unknown>)[sortMetric] as number ?? 0;
          return typeof val === 'number' ? +val.toFixed(2) : 0;
        }),
        itemStyle: { color: BRAND_ORANGE },
        label: { show: true, position: 'right', color: TEXT_SECONDARY, fontSize: 11 },
      }],
    };
  }, [items, sortMetric]);

  const rankMedalColor = (idx: number) => {
    if (idx === 0) return GOLD;
    if (idx === 1) return SILVER;
    if (idx === 2) return BRONZE;
    return undefined;
  };

  const isBottom3 = (idx: number) => items.length >= 6 && idx >= items.length - 3;

  const columns = [
    {
      title: '排名', key: 'rank', width: 70,
      render: (_: unknown, __: StoreAttribution, idx: number) => {
        const medal = rankMedalColor(idx);
        const bottom = isBottom3(idx);
        return (
          <span style={{
            fontWeight: 700,
            fontSize: medal ? 16 : 14,
            color: medal || (bottom ? DANGER_RED : TEXT_PRIMARY),
          }}>
            {medal ? ['🥇', '🥈', '🥉'][idx] : `#${idx + 1}`}
          </span>
        );
      },
    },
    {
      title: '门店名称', dataIndex: 'store_name', key: 'store_name', width: 140,
      render: (val: string, _: StoreAttribution, idx: number) => (
        <span style={{ color: isBottom3(idx) ? DANGER_RED : TEXT_PRIMARY, fontWeight: 500 }}>
          {val || '--'}
        </span>
      ),
    },
    {
      title: '品牌', dataIndex: 'brand_name', key: 'brand_name', width: 100,
      render: (val: string) => <Tag>{val || '--'}</Tag>,
    },
    {
      title: '活跃旅程数', dataIndex: 'active_journeys', key: 'active_journeys', width: 100,
      render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{val ?? 0}</span>,
    },
    {
      title: '触达数(7d)', dataIndex: 'total_touches', key: 'total_touches', width: 100,
      sorter: (a: StoreAttribution, b: StoreAttribution) => (a.total_touches ?? 0) - (b.total_touches ?? 0),
      render: (val: number) => <span style={{ color: INFO_BLUE }}>{val ?? 0}</span>,
    },
    {
      title: '打开率', dataIndex: 'open_rate', key: 'open_rate', width: 80,
      sorter: (a: StoreAttribution, b: StoreAttribution) => (a.open_rate ?? 0) - (b.open_rate ?? 0),
      render: (val: number) => (
        <span style={{ color: (val ?? 0) >= 20 ? SUCCESS_GREEN : (val ?? 0) >= 10 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
          {(val ?? 0).toFixed(1)}%
        </span>
      ),
    },
    {
      title: '归因订单', dataIndex: 'attributed_orders', key: 'attributed_orders', width: 90,
      sorter: (a: StoreAttribution, b: StoreAttribution) => (a.attributed_orders ?? 0) - (b.attributed_orders ?? 0),
      render: (val: number) => <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>{val ?? 0}</span>,
    },
    {
      title: '归因GMV', dataIndex: 'attributed_gmv_fen', key: 'attributed_gmv_fen', width: 110,
      sorter: (a: StoreAttribution, b: StoreAttribution) => (a.attributed_gmv_fen ?? 0) - (b.attributed_gmv_fen ?? 0),
      render: (val: number) => (
        <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>
          ¥{((val ?? 0) / 100).toFixed(0)}
        </span>
      ),
    },
    {
      title: '二访率', dataIndex: 'second_visit_rate', key: 'second_visit_rate', width: 80,
      sorter: (a: StoreAttribution, b: StoreAttribution) => (a.second_visit_rate ?? 0) - (b.second_visit_rate ?? 0),
      render: (val: number) => (
        <span style={{ color: (val ?? 0) >= 30 ? SUCCESS_GREEN : (val ?? 0) >= 15 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
          {(val ?? 0).toFixed(1)}%
        </span>
      ),
    },
    {
      title: '召回率', dataIndex: 'recall_rate', key: 'recall_rate', width: 80,
      sorter: (a: StoreAttribution, b: StoreAttribution) => (a.recall_rate ?? 0) - (b.recall_rate ?? 0),
      render: (val: number) => (
        <span style={{ color: (val ?? 0) >= 10 ? SUCCESS_GREEN : (val ?? 0) >= 5 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
          {(val ?? 0).toFixed(1)}%
        </span>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      {/* 顶部标题 + 筛选 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>门店增长排行</h2>
        <Space>
          <RangePicker
            style={{ background: CARD_BG, borderColor: BORDER }}
            value={dateRange}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) setDateRange([dates[0], dates[1]]);
            }}
          />
          <Select
            value={brand}
            onChange={setBrand}
            style={{ width: 140 }}
            options={BRAND_OPTIONS.map(b => ({ value: b, label: b }))}
          />
          <Select
            value={sortMetric}
            onChange={setSortMetric}
            style={{ width: 140 }}
            options={SORT_OPTIONS}
          />
        </Space>
      </div>

      {/* 排行榜表格 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>门店增长排行榜（近{days}天）</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
        bodyStyle={{ padding: 0 }}
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : (
          <Table
            dataSource={items}
            columns={columns}
            rowKey="store_id"
            size="small"
            pagination={false}
            scroll={{ x: 1000 }}
            locale={{ emptyText: <span style={{ color: TEXT_SECONDARY }}>暂无门店数据</span> }}
            rowClassName={(_, idx) => isBottom3(idx) ? 'store-rank-bottom' : ''}
          />
        )}
      </Card>

      {/* Top 10 对比柱状图 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>Top 10 门店对比 — {SORT_OPTIONS.find(o => o.value === sortMetric)?.label}</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
      >
        {items.length > 0 ? (
          <ReactEChartsCore echarts={echarts} option={chartOption} style={{ height: 400 }} />
        ) : (
          <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无数据</div>
        )}
      </Card>
    </div>
  );
}
