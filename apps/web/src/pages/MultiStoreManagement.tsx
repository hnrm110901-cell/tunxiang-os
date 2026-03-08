import React, { useEffect, useState, useCallback } from 'react';
import { Card, Col, Row, Table, Statistic, Spin, Select, Tag, Space, Empty } from 'antd';
import {
  ShopOutlined,
  RiseOutlined,
  FallOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { apiClient } from '../services/api';
import { handleApiError } from '../utils/message';

interface StoreItem {
  id: string;
  name: string;
  region: string;
}

interface ComparisonMetrics {
  revenue: number;
  orders: number;
  customers: number;
  avg_order_value: number;
}

interface ComparisonStore {
  id: string;
  name: string;
  metrics: ComparisonMetrics;
}

interface ComparisonResponse {
  stores: ComparisonStore[];
}

interface RegionalSummaryItem {
  region: string;
  total_revenue: number;
  store_count: number;
  total_orders: number;
  total_customers: number;
}

interface PerformanceRankingItem {
  rank: number;
  store_id: string;
  store_name: string;
  region: string;
  value: number;
  growth_rate: number;
}

const MultiStoreManagement: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [stores, setStores] = useState<StoreItem[]>([]);
  const [selectedStores, setSelectedStores] = useState<string[]>([]);
  const [comparisonData, setComparisonData] = useState<ComparisonResponse | null>(null);
  const [regionalSummary, setRegionalSummary] = useState<RegionalSummaryItem[]>([]);
  const [performanceRanking, setPerformanceRanking] = useState<PerformanceRankingItem[]>([]);

  const loadComparisonData = useCallback(async (storeIds: string[]) => {
    if (storeIds.length < 2) {
      setComparisonData(null);
      return;
    }

    try {
      const response = await apiClient.post('/api/v1/multi-store/compare', {
        store_ids: storeIds,
        start_date: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
        end_date: new Date().toISOString().split('T')[0],
      }) as ComparisonResponse;
      setComparisonData(response);
    } catch (err: unknown) {
      handleApiError(err, '加载对比数据失败');
    }
  }, []);

  const loadStores = useCallback(async () => {
    try {
      const response = await apiClient.get('/api/v1/multi-store/stores') as { stores?: StoreItem[] };
      const storeList = response.stores || [];
      setStores(storeList);

      if (storeList.length >= 2) {
        const defaults = [storeList[0].id, storeList[1].id];
        setSelectedStores(defaults);
        await loadComparisonData(defaults);
      }
    } catch (err: unknown) {
      handleApiError(err, '加载门店列表失败');
    }
  }, [loadComparisonData]);

  const loadRegionalSummary = useCallback(async () => {
    try {
      const response = await apiClient.get('/api/v1/multi-store/regional-summary') as { regions?: RegionalSummaryItem[] };
      setRegionalSummary(response.regions || []);
    } catch (err: unknown) {
      handleApiError(err, '加载区域汇总失败');
    }
  }, []);

  const loadPerformanceRanking = useCallback(async () => {
    try {
      const response = await apiClient.get('/api/v1/multi-store/performance-ranking?metric=revenue&limit=10') as {
        ranking?: PerformanceRankingItem[];
      };
      setPerformanceRanking(response.ranking || []);
    } catch (err: unknown) {
      handleApiError(err, '加载绩效排名失败');
    }
  }, []);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([
        loadStores(),
        loadRegionalSummary(),
        loadPerformanceRanking(),
      ]);
      setLoading(false);
    };

    loadData();
  }, [loadStores, loadRegionalSummary, loadPerformanceRanking]);

  const handleStoreSelectionChange = async (values: string[]) => {
    setSelectedStores(values);
    await loadComparisonData(values);
  };

  const comparisonChartOption = {
    title: { text: '门店对比分析', left: 'center' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    legend: {
      data: comparisonData?.stores?.map((s) => s.name) || [],
      bottom: 10,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '15%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: ['营收', '订单数', '客流量', '客单价'],
    },
    yAxis: { type: 'value' },
    series: comparisonData?.stores?.map((store) => ({
      name: store.name,
      type: 'bar',
      data: [
        store.metrics.revenue / 100,
        store.metrics.orders,
        store.metrics.customers,
        store.metrics.avg_order_value / 100,
      ],
    })) || [],
  };

  const regionalChartOption = {
    title: {
      text: '区域营收分布',
      left: 'center',
    },
    tooltip: {
      trigger: 'item',
      formatter: '{a} <br/>{b}: ¥{c} ({d}%)',
    },
    legend: {
      orient: 'vertical',
      left: 'left',
    },
    series: [
      {
        name: '区域营收',
        type: 'pie',
        radius: '50%',
        data: regionalSummary.map((region) => ({
          value: region.total_revenue / 100,
          name: region.region,
        })),
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowOffsetX: 0,
            shadowColor: 'rgba(0, 0, 0, 0.5)',
          },
        },
      },
    ],
  };

  const rankingColumns = [
    {
      title: '排名',
      dataIndex: 'rank',
      key: 'rank',
      width: 80,
      render: (rank: number) => {
        if (rank === 1) return <Tag color="gold">🥇 {rank}</Tag>;
        if (rank === 2) return <Tag color="silver">🥈 {rank}</Tag>;
        if (rank === 3) return <Tag color="bronze">🥉 {rank}</Tag>;
        return <Tag>{rank}</Tag>;
      },
    },
    {
      title: '门店名称',
      dataIndex: 'store_name',
      key: 'store_name',
    },
    {
      title: '区域',
      dataIndex: 'region',
      key: 'region',
    },
    {
      title: '营收（元）',
      dataIndex: 'value',
      key: 'value',
      render: (value: number) => `¥${(value / 100).toFixed(2)}`,
    },
    {
      title: '环比',
      dataIndex: 'growth_rate',
      key: 'growth_rate',
      render: (rate: number) => {
        const isPositive = rate >= 0;
        return (
          <Tag color={isPositive ? 'green' : 'red'} icon={isPositive ? <RiseOutlined /> : <FallOutlined />}>
            {isPositive ? '+' : ''}{rate.toFixed(1)}%
          </Tag>
        );
      },
    },
  ];

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  return (
    <div style={{ padding: '24px', background: '#f0f2f5', minHeight: '100vh' }}>
      <h1 style={{ marginBottom: '24px' }}>
        <ShopOutlined /> 多门店管理
      </h1>

      <Row gutter={[16, 16]} style={{ marginBottom: '24px' }}>
        {regionalSummary.map((region) => (
          <Col xs={24} sm={12} md={6} key={region.region}>
            <Card>
              <Statistic
                title={region.region}
                value={region.total_revenue / 100}
                precision={2}
                prefix="¥"
                suffix={`/ ${region.store_count}店`}
              />
              <div style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
                订单: {region.total_orders} | 客流: {region.total_customers}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Card title="门店对比分析" style={{ marginBottom: '24px' }}>
        <Space style={{ marginBottom: '16px' }}>
          <span>选择门店:</span>
          <Select
            mode="multiple"
            style={{ width: 400 }}
            placeholder="请选择要对比的门店"
            value={selectedStores}
            onChange={handleStoreSelectionChange}
            maxTagCount={2}
            options={stores.map((store) => ({
              label: `${store.name} (${store.region})`,
              value: store.id,
            }))}
          />
        </Space>
        {selectedStores.length < 2 ? (
          <Empty description="请至少选择两个门店进行对比" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : comparisonData ? (
          <ReactECharts option={comparisonChartOption} style={{ height: '400px' }} />
        ) : (
          <Empty description="暂无对比数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="区域营收分布">
            <ReactECharts option={regionalChartOption} style={{ height: '400px' }} />
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="门店绩效排名（按营收）">
            <Table
              columns={rankingColumns}
              dataSource={performanceRanking}
              rowKey="store_id"
              pagination={{ pageSize: 10, showSizeChanger: false }}
              size="small"
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default MultiStoreManagement;
