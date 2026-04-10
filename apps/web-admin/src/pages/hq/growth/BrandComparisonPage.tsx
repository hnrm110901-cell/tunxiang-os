/**
 * BrandComparisonPage — 集团增长驾驶舱（品牌间对比）
 * 路由: /hq/growth/brand-comparison
 * Sprint H: 全集团驾驶舱 — 品牌KPI对比 + 雷达图 + 门店排行速览 + 跨品牌机会发现
 */
import { useState, useMemo } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import {
  Card, Table, Tag, Space, Row, Col, DatePicker, Spin, Progress,
} from 'antd';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, RadarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, RadarComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { useApi } from '../../../hooks/useApi';
import type { BrandDashboardStats, StoreAttribution } from '../../../api/growthHubApi';

echarts.use([BarChart, RadarChart, GridComponent, TooltipComponent, LegendComponent, RadarComponent, CanvasRenderer]);

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
const TEAL = '#13c2c2';
const PURPLE = '#722ed1';

const BRAND_COLORS = [BRAND_ORANGE, INFO_BLUE, SUCCESS_GREEN, TEAL, PURPLE, WARNING_ORANGE];

export function BrandComparisonPage() {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(7, 'day'), dayjs()]);
  const days = useMemo(() => Math.max(1, dateRange[1].diff(dateRange[0], 'day')), [dateRange]);

  const { data: brandData, loading: brandLoading } = useApi<{ items: BrandDashboardStats[]; days: number }>(
    `/api/v1/growth/dashboard-stats/by-brand?days=${days}`,
    { cacheMs: 15_000 },
  );

  const { data: storeData, loading: storeLoading } = useApi<{ items: StoreAttribution[]; days: number }>(
    `/api/v1/growth/attribution/by-store?days=7`,
    { cacheMs: 15_000 },
  );

  const brands = brandData?.items || [];
  const stores = storeData?.items || [];

  // Top5 & Bottom5 stores
  const sortedStores = useMemo(() => {
    return [...stores].sort((a, b) => (b.attributed_gmv_fen ?? 0) - (a.attributed_gmv_fen ?? 0));
  }, [stores]);
  const top5 = sortedStores.slice(0, 5);
  const bottom5 = sortedStores.length > 5 ? sortedStores.slice(-5).reverse() : [];

  // Radar chart
  const radarOption = useMemo(() => {
    if (brands.length === 0) return {};
    // 5 dimensions: 二访率 / 召回率 / 触达打开率 / 归因转化率 / 客户活跃率
    const indicator = [
      { name: '二访率', max: 100 },
      { name: '召回率', max: 100 },
      { name: '触达打开率', max: 100 },
      { name: '归因转化率', max: 100 },
      { name: '客户活跃率', max: 100 },
    ];

    const series = brands.map((b, i) => ({
      name: b.brand_name,
      type: 'radar' as const,
      data: [{
        value: [
          b.second_visit_rate ?? 0,
          b.recall_rate ?? 0,
          b.open_rate ?? 0,
          b.attribution_rate ?? 0,
          b.active_rate ?? 0,
        ],
        name: b.brand_name,
        lineStyle: { color: BRAND_COLORS[i % BRAND_COLORS.length] },
        itemStyle: { color: BRAND_COLORS[i % BRAND_COLORS.length] },
        areaStyle: { color: BRAND_COLORS[i % BRAND_COLORS.length], opacity: 0.1 },
      }],
    }));

    return {
      tooltip: {},
      legend: {
        data: brands.map(b => b.brand_name),
        textStyle: { color: TEXT_SECONDARY },
        bottom: 0,
      },
      radar: {
        indicator,
        shape: 'polygon' as const,
        splitArea: { areaStyle: { color: ['transparent'] } },
        splitLine: { lineStyle: { color: BORDER } },
        axisLine: { lineStyle: { color: BORDER } },
        axisName: { color: TEXT_SECONDARY, fontSize: 11 },
      },
      series,
    };
  }, [brands]);

  // Cross-brand opportunity discovery
  const opportunities = useMemo(() => {
    if (brands.length < 2) return [];
    const msgs: string[] = [];

    // Compare recall_rate
    const byRecall = [...brands].sort((a, b) => (b.recall_rate ?? 0) - (a.recall_rate ?? 0));
    if (byRecall.length >= 2 && (byRecall[0].recall_rate ?? 0) > (byRecall[byRecall.length - 1].recall_rate ?? 0) * 1.5) {
      msgs.push(`${byRecall[0].brand_name}的召回率(${(byRecall[0].recall_rate ?? 0).toFixed(1)}%)显著高于${byRecall[byRecall.length - 1].brand_name}(${(byRecall[byRecall.length - 1].recall_rate ?? 0).toFixed(1)}%)，建议${byRecall[byRecall.length - 1].brand_name}参考${byRecall[0].brand_name}的召回策略`);
    }

    // Compare open_rate
    const byOpen = [...brands].sort((a, b) => (b.open_rate ?? 0) - (a.open_rate ?? 0));
    if (byOpen.length >= 2 && (byOpen[0].open_rate ?? 0) > (byOpen[byOpen.length - 1].open_rate ?? 0) * 1.3) {
      msgs.push(`${byOpen[0].brand_name}的触达打开率(${(byOpen[0].open_rate ?? 0).toFixed(1)}%)领先，${byOpen[byOpen.length - 1].brand_name}可优化触达内容`);
    }

    // Compare second_visit_rate
    const bySecond = [...brands].sort((a, b) => (b.second_visit_rate ?? 0) - (a.second_visit_rate ?? 0));
    if (bySecond.length >= 2 && (bySecond[0].second_visit_rate ?? 0) > (bySecond[bySecond.length - 1].second_visit_rate ?? 0) * 1.5) {
      msgs.push(`${bySecond[0].brand_name}的二访率(${(bySecond[0].second_visit_rate ?? 0).toFixed(1)}%)显著优于${bySecond[bySecond.length - 1].brand_name}，建议推广首转二策略`);
    }

    if (msgs.length === 0) {
      msgs.push('各品牌增长指标差异较小，暂无显著跨品牌优化机会');
    }

    return msgs;
  }, [brands]);

  // Brand KPI columns
  const brandColumns = [
    {
      title: '品牌', dataIndex: 'brand_name', key: 'brand_name', width: 120,
      render: (val: string) => <span style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>{val}</span>,
    },
    {
      title: '总客户数', dataIndex: 'total_customers', key: 'total_customers', width: 100,
      render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{(val ?? 0).toLocaleString()}</span>,
    },
    {
      title: '活跃旅程', dataIndex: 'active_journeys', key: 'active_journeys', width: 90,
      render: (val: number) => <span style={{ color: INFO_BLUE }}>{val ?? 0}</span>,
    },
    {
      title: '7日触达', dataIndex: 'touches_7d', key: 'touches_7d', width: 90,
      render: (val: number) => <span style={{ color: TEXT_PRIMARY }}>{val ?? 0}</span>,
    },
    {
      title: '打开率', dataIndex: 'open_rate', key: 'open_rate', width: 90,
      render: (val: number) => {
        const v = val ?? 0;
        return (
          <Space>
            <span style={{ color: v >= 20 ? SUCCESS_GREEN : v >= 10 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
              {v.toFixed(1)}%
            </span>
            <Progress percent={Math.min(v, 100)} showInfo={false} size="small" strokeColor={v >= 20 ? SUCCESS_GREEN : WARNING_ORANGE} trailColor={BORDER} style={{ width: 40 }} />
          </Space>
        );
      },
    },
    {
      title: '归因率', dataIndex: 'attribution_rate', key: 'attribution_rate', width: 90,
      render: (val: number) => {
        const v = val ?? 0;
        return (
          <Space>
            <span style={{ color: v >= 5 ? SUCCESS_GREEN : v >= 2 ? WARNING_ORANGE : DANGER_RED, fontWeight: 600 }}>
              {v.toFixed(1)}%
            </span>
            <Progress percent={Math.min(v * 5, 100)} showInfo={false} size="small" strokeColor={BRAND_ORANGE} trailColor={BORDER} style={{ width: 40 }} />
          </Space>
        );
      },
    },
    {
      title: '稳定复购客', dataIndex: 'stable_repurchase', key: 'stable_repurchase', width: 100,
      render: (val: number) => <span style={{ color: SUCCESS_GREEN }}>{(val ?? 0).toLocaleString()}</span>,
    },
    {
      title: '高优先召回', dataIndex: 'high_priority_recall', key: 'high_priority_recall', width: 100,
      render: (val: number) => (
        <Tag color={(val ?? 0) > 100 ? 'red' : 'orange'}>{(val ?? 0).toLocaleString()}</Tag>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      {/* 标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>集团增长驾驶舱</h2>
        <RangePicker
          style={{ background: CARD_BG, borderColor: BORDER }}
          value={dateRange}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) setDateRange([dates[0], dates[1]]);
          }}
        />
      </div>

      {/* 区域1: 品牌KPI对比表 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>品牌KPI对比</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
        bodyStyle={{ padding: 0 }}
      >
        {brandLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : (
          <Table
            dataSource={brands}
            columns={brandColumns}
            rowKey="brand_name"
            size="small"
            pagination={false}
            scroll={{ x: 900 }}
            locale={{ emptyText: <span style={{ color: TEXT_SECONDARY }}>暂无品牌数据</span> }}
          />
        )}
      </Card>

      {/* 区域2: 品牌间雷达图对比 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>品牌间雷达图对比</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
      >
        {brands.length > 0 ? (
          <ReactEChartsCore echarts={echarts} option={radarOption} style={{ height: 400 }} />
        ) : (
          <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>暂无品牌数据</div>
        )}
      </Card>

      {/* 区域3: 门店排行速览 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>门店排行速览（近7天）</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
      >
        {storeLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : (
          <Row gutter={24}>
            {/* Top 5 */}
            <Col span={12}>
              <div style={{ marginBottom: 12, fontWeight: 600, color: SUCCESS_GREEN, fontSize: 14 }}>
                Top 5 表现最佳
              </div>
              {top5.map((s, i) => (
                <div
                  key={s.store_id}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 12px', marginBottom: 4, borderRadius: 6,
                    background: `${SUCCESS_GREEN}08`, borderLeft: `3px solid ${SUCCESS_GREEN}`,
                  }}
                >
                  <Space>
                    <span style={{ color: SUCCESS_GREEN, fontWeight: 700, width: 24, textAlign: 'center' }}>
                      #{i + 1}
                    </span>
                    <span style={{ color: TEXT_PRIMARY }}>{s.store_name || s.store_id.slice(0, 8)}</span>
                    <Tag style={{ fontSize: 10 }}>{s.brand_name}</Tag>
                  </Space>
                  <span style={{ color: BRAND_ORANGE, fontWeight: 600 }}>
                    ¥{((s.attributed_gmv_fen ?? 0) / 100).toFixed(0)}
                  </span>
                </div>
              ))}
              {top5.length === 0 && <div style={{ color: TEXT_SECONDARY, padding: 20 }}>暂无数据</div>}
            </Col>

            {/* Bottom 5 */}
            <Col span={12}>
              <div style={{ marginBottom: 12, fontWeight: 600, color: DANGER_RED, fontSize: 14 }}>
                Bottom 5 需关注
              </div>
              {bottom5.map((s, i) => (
                <div
                  key={s.store_id}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 12px', marginBottom: 4, borderRadius: 6,
                    background: `${DANGER_RED}08`, borderLeft: `3px solid ${DANGER_RED}`,
                  }}
                >
                  <Space>
                    <span style={{ color: DANGER_RED, fontWeight: 700, width: 24, textAlign: 'center' }}>
                      #{sortedStores.length - bottom5.length + i + 1}
                    </span>
                    <span style={{ color: TEXT_PRIMARY }}>{s.store_name || s.store_id.slice(0, 8)}</span>
                    <Tag style={{ fontSize: 10 }}>{s.brand_name}</Tag>
                  </Space>
                  <span style={{ color: DANGER_RED, fontWeight: 600 }}>
                    ¥{((s.attributed_gmv_fen ?? 0) / 100).toFixed(0)}
                  </span>
                </div>
              ))}
              {bottom5.length === 0 && <div style={{ color: TEXT_SECONDARY, padding: 20 }}>门店数不足，无法显示Bottom 5</div>}
            </Col>
          </Row>
        )}
      </Card>

      {/* 区域4: 跨品牌机会发现 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>跨品牌机会发现</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {opportunities.map((msg, i) => (
            <div
              key={i}
              style={{
                padding: '12px 16px', borderRadius: 8,
                background: `${INFO_BLUE}0a`, border: `1px solid ${INFO_BLUE}33`,
                color: TEXT_PRIMARY, fontSize: 13, lineHeight: 1.6,
              }}
            >
              <span style={{ color: WARNING_ORANGE, marginRight: 8 }}>&#9672;</span>
              {msg}
            </div>
          ))}
          <div style={{
            padding: '10px 16px', borderRadius: 8,
            background: `${TEXT_SECONDARY}08`, fontSize: 11, color: TEXT_SECONDARY,
          }}>
            深度跨品牌分析（含策略自动迁移建议）将在 V2.3 上线。当前为基础规则比较。
          </div>
        </div>
      </Card>
    </div>
  );
}
