/**
 * BrandOverview — HQ 总部多品牌总览页
 *
 * 终端：Admin（总部管理后台）
 * 域G：经营分析 → HQ总部看板
 * 路由：/analytics/hq/overview
 *
 * 布局：
 *   1. 顶部 Segmented 日期选择（今日/本周/本月）
 *   2. 品牌 KPI 卡片区：三品牌横排 StatisticCard
 *   3. 中部：七日营收趋势折线图（@ant-design/charts Line）
 *   4. 底部：跨品牌门店快速排名 ProTable（前10条）
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  ConfigProvider,
  Segmented,
  Row,
  Col,
  Card,
  Statistic,
  Tag,
  Badge,
  Skeleton,
  message,
  Space,
  Typography,
  Tooltip,
} from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Line } from '@ant-design/charts';

import { formatPrice } from '@tx-ds/utils';
import { fenToYuan, pctDisplay } from '../../../utils/format';
import {
  getBrandsOverview,
  type BrandKpiCard,
  type BrandRevenueTrendPoint,
  type CrossBrandStoreRankItem,
  type HQDateParams,
} from '../../../api/hqAnalyticsApi';

const { Title, Text } = Typography;

// ─── 主题 Token（通过 ConfigProvider 注入，不硬编码颜色） ─────────────────────
const txAdminTheme = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
  },
  components: {
    Table: { headerBg: '#F8F7F5' },
  },
} as const;

// ─── 日期周期选项 ────────────────────────────────────────────────────────────

type PeriodKey = 'today' | 'week' | 'month';

const PERIOD_OPTIONS = [
  { label: '今日', value: 'today' },
  { label: '本周', value: 'week' },
  { label: '本月', value: 'month' },
];

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function healthBadgeStatus(score: number): 'success' | 'warning' | 'error' {
  if (score >= 80) return 'success';
  if (score >= 60) return 'warning';
  return 'error';
}

function targetRateColor(rate: number): string {
  if (rate >= 1) return 'green';
  if (rate >= 0.8) return 'orange';
  return 'red';
}

function trendIcon(ratio: number) {
  if (ratio > 0) {
    return <ArrowUpOutlined style={{ color: '#0F6E56' }} />;
  }
  if (ratio < 0) {
    return <ArrowDownOutlined style={{ color: '#A32D2D' }} />;
  }
  return null;
}

// ─── 品牌 KPI 卡片 ────────────────────────────────────────────────────────────

interface BrandKpiCardProps {
  data: BrandKpiCard;
  loading: boolean;
}

function BrandKpiCardItem({ data, loading }: BrandKpiCardProps) {
  if (loading) {
    return (
      <Card size="small" style={{ height: 180 }}>
        <Skeleton active paragraph={{ rows: 4 }} />
      </Card>
    );
  }

  const ratioLabel = `${data.revenue_ratio >= 0 ? '+' : ''}${(data.revenue_ratio * 100).toFixed(1)}%`;
  const healthStatus = healthBadgeStatus(data.health_score);

  return (
    <Card
      size="small"
      title={
        <Space>
          <Text strong style={{ fontSize: 15 }}>{data.brand_name}</Text>
          <Badge status={healthStatus} text={
            <Text style={{
              color: healthStatus === 'success' ? '#0F6E56'
                : healthStatus === 'warning' ? '#BA7517' : '#A32D2D',
              fontSize: 12,
            }}>
              健康分 {data.health_score}
            </Text>
          } />
        </Space>
      }
      style={{ height: '100%' }}
    >
      <Row gutter={[12, 12]}>
        <Col span={12}>
          <Statistic
            title="营收"
            value={fenToYuan(data.revenue_fen)}
            valueStyle={{ fontSize: 18, color: '#FF6B35' }}
          />
          <Space size={4} style={{ marginTop: 4 }}>
            {trendIcon(data.revenue_ratio)}
            <Text
              style={{
                fontSize: 12,
                color: data.revenue_ratio >= 0 ? '#0F6E56' : '#A32D2D',
              }}
            >
              环比 {ratioLabel}
            </Text>
          </Space>
        </Col>
        <Col span={12}>
          <Statistic
            title="订单数"
            value={data.order_count}
            suffix="单"
            valueStyle={{ fontSize: 16 }}
          />
        </Col>
        <Col span={12}>
          <Statistic
            title="客单价"
            value={fenToYuan(data.avg_ticket_fen)}
            valueStyle={{ fontSize: 16 }}
          />
        </Col>
        <Col span={12}>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>健康分</Text>
            <div style={{ marginTop: 2 }}>
              <Tag color={healthStatus === 'success' ? 'green' : healthStatus === 'warning' ? 'orange' : 'red'}>
                {data.health_score} 分
              </Tag>
            </div>
          </div>
        </Col>
      </Row>
    </Card>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function BrandOverview() {
  const [period, setPeriod] = useState<PeriodKey>('today');
  const [loading, setLoading] = useState(false);
  const [brands, setBrands] = useState<BrandKpiCard[]>([]);
  const [trendData, setTrendData] = useState<BrandRevenueTrendPoint[]>([]);
  const [storeRank, setStoreRank] = useState<CrossBrandStoreRankItem[]>([]);

  const loadData = useCallback(async (p: PeriodKey) => {
    setLoading(true);
    try {
      const params: HQDateParams = { period: p };
      const res = await getBrandsOverview(params);
      setBrands(res.brands ?? []);
      setTrendData(res.revenue_trend ?? []);
      setStoreRank((res.store_rank ?? []).slice(0, 10));
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`HQ总览数据加载失败：${msg}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(period);
  }, [loadData, period]);

  // ─── 趋势图配置 ───────────────────────────────────────────────────────────

  const chartData = trendData.map((pt) => ({
    ...pt,
    revenue_yuan: pt.revenue_fen / 100,
  }));

  const lineConfig = {
    data: chartData,
    xField: 'date' as const,
    yField: 'revenue_yuan' as const,
    seriesField: 'brand_name' as const,
    smooth: true,
    legend: { position: 'top-right' as const },
    tooltip: {
      formatter: (datum: { brand_name: string; revenue_yuan: number }) => ({
        name: datum.brand_name,
        value: `¥${datum.revenue_yuan.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
      }),
    },
    yAxis: {
      label: {
        formatter: (v: string) => `¥${Number(v).toLocaleString('zh-CN')}`,
      },
    },
    color: ['#FF6B35', '#0F6E56', '#185FA5'],
  };

  // ─── ProTable 列配置 ──────────────────────────────────────────────────────

  const rankColumns: ProColumns<CrossBrandStoreRankItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 56,
      align: 'center',
      render: (_, record) => (
        <Text strong style={{ color: record.rank <= 3 ? '#FF6B35' : undefined }}>
          {record.rank}
        </Text>
      ),
    },
    {
      title: '品牌',
      dataIndex: 'brand_name',
      width: 100,
      render: (_, record) => <Tag color="orange">{record.brand_name}</Tag>,
    },
    {
      title: '门店名',
      dataIndex: 'store_name',
      ellipsis: true,
    },
    {
      title: '城市',
      dataIndex: 'city',
      width: 80,
    },
    {
      title: '今日营收',
      dataIndex: 'today_revenue_fen',
      width: 120,
      sorter: true,
      render: (_, record) => (
        <Text strong style={{ color: '#FF6B35' }}>
          {fenToYuan(record.today_revenue_fen)}
        </Text>
      ),
    },
    {
      title: '目标达成率',
      dataIndex: 'target_rate',
      width: 110,
      render: (_, record) => (
        <Tag color={targetRateColor(record.target_rate)}>
          {pctDisplay(record.target_rate)}
        </Tag>
      ),
    },
    {
      title: '健康分',
      dataIndex: 'health_score',
      width: 90,
      render: (_, record) => (
        <Tag color={healthBadgeStatus(record.health_score) === 'success' ? 'green'
          : healthBadgeStatus(record.health_score) === 'warning' ? 'orange' : 'red'}>
          {record.health_score}
        </Tag>
      ),
    },
    {
      title: '预警数',
      dataIndex: 'alert_count',
      width: 80,
      render: (_, record) =>
        record.alert_count > 0 ? (
          <Badge count={record.alert_count} color={record.alert_count >= 3 ? 'red' : 'orange'} />
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
  ];

  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ minWidth: 1280, padding: '0 4px' }}>
        {/* 页头 + 日期切换 */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 20,
        }}>
          <Title level={4} style={{ margin: 0 }}>HQ 多品牌总览</Title>
          <Segmented
            options={PERIOD_OPTIONS}
            value={period}
            onChange={(val) => setPeriod(val as PeriodKey)}
          />
        </div>

        {/* 品牌 KPI 卡片区 */}
        <Row gutter={16} style={{ marginBottom: 20 }}>
          {loading
            ? [0, 1, 2].map((i) => (
                <Col key={i} xs={24} md={8}>
                  <BrandKpiCardItem data={{} as BrandKpiCard} loading />
                </Col>
              ))
            : brands.length > 0
            ? brands.map((b) => (
                <Col key={b.brand_id} xs={24} md={8}>
                  <BrandKpiCardItem data={b} loading={false} />
                </Col>
              ))
            : (
                <Col span={24}>
                  <Card>
                    <Text type="secondary">暂无品牌数据</Text>
                  </Card>
                </Col>
              )}
        </Row>

        {/* 七日营收趋势折线图 */}
        <Card
          title="七日营收趋势"
          style={{ marginBottom: 20 }}
          extra={<Text type="secondary" style={{ fontSize: 12 }}>单位：元</Text>}
        >
          {chartData.length > 0 ? (
            <Line {...lineConfig} height={260} />
          ) : (
            <Skeleton active paragraph={{ rows: 5 }} />
          )}
        </Card>

        {/* 跨品牌门店快速排名 */}
        <Card title="跨品牌门店快速排名（前10）">
          <ProTable<CrossBrandStoreRankItem>
            columns={rankColumns}
            dataSource={storeRank}
            rowKey="store_id"
            loading={loading}
            search={false}
            options={{ reload: () => loadData(period), density: false, setting: true }}
            pagination={false}
            size="small"
            toolBarRender={false}
          />
        </Card>
      </div>
    </ConfigProvider>
  );
}
