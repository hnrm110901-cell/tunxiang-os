/**
 * GovernanceDashboard — 总部人力驾驶舱
 * Sprint 6 · 总部治理台
 *
 * API: GET /api/v1/hr/governance/dashboard
 */

import { useEffect, useState } from 'react';
import { Card, Col, Row, Segmented, Table, Tag, Typography, message } from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import { Bar } from '@ant-design/charts';
import {
  DollarOutlined,
  GlobalOutlined,
  ShopOutlined,
  TeamOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../../api';

const { Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface GovernanceData {
  total_employees: number;
  brand_distribution: { brand: string; count: number }[];
  region_distribution: { region: string; count: number }[];
  revenue_per_capita: number;
  labor_cost_rate: number;
  store_efficiency: { store_name: string; efficiency: number; cost_rate: number }[];
  cost_heatmap: { store_name: string; cost_rate: number }[];
}

// ─── 工具 ────────────────────────────────────────────────────────────────────

function costColor(rate: number): string {
  if (rate > 35) return '#A32D2D';
  if (rate > 28) return '#BA7517';
  return '#0F6E56';
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function GovernanceDashboard() {
  const [data, setData] = useState<GovernanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [dimension, setDimension] = useState<string>('brand');

  useEffect(() => {
    txFetchData<GovernanceData>('/api/v1/hr/governance/dashboard')
      .then((resp) => setData(resp))
      .catch(() => message.error('加载驾驶舱数据失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading || !data) return <Card loading />;

  const distributionData =
    dimension === 'brand'
      ? data.brand_distribution.map((b) => ({ name: b.brand, count: b.count }))
      : data.region_distribution.map((r) => ({ name: r.region, count: r.count }));

  return (
    <div>
      {/* KPI 卡片组 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={5}>
          <StatisticCard
            statistic={{ title: '总人数', value: data.total_employees, prefix: <TeamOutlined style={{ color: '#FF6B35' }} /> }}
          />
        </Col>
        <Col span={5}>
          <StatisticCard
            statistic={{ title: '品牌数', value: data.brand_distribution.length, prefix: <ShopOutlined /> }}
          />
        </Col>
        <Col span={5}>
          <StatisticCard
            statistic={{ title: '区域数', value: data.region_distribution.length, prefix: <GlobalOutlined /> }}
          />
        </Col>
        <Col span={5}>
          <StatisticCard
            statistic={{ title: '人均产出', value: data.revenue_per_capita, prefix: '¥', suffix: '/月' }}
          />
        </Col>
        <Col span={4}>
          <StatisticCard
            statistic={{
              title: '成本率',
              value: data.labor_cost_rate,
              suffix: '%',
              prefix: <DollarOutlined style={{ color: costColor(data.labor_cost_rate) }} />,
            }}
          />
        </Col>
      </Row>

      {/* 品牌/区域切换 */}
      <Card
        title="人员分布"
        extra={
          <Segmented
            options={[
              { label: '按品牌', value: 'brand' },
              { label: '按区域', value: 'region' },
            ]}
            value={dimension}
            onChange={(v) => setDimension(v as string)}
          />
        }
        style={{ marginBottom: 16 }}
      >
        <Bar
          data={distributionData}
          xField="count"
          yField="name"
          height={Math.max(200, distributionData.length * 36)}
          color="#FF6B35"
          label={{ position: 'right' }}
        />
      </Card>

      <Row gutter={16}>
        {/* 门店人效排名 */}
        <Col span={12}>
          <Card title="门店人效排名">
            <Bar
              data={data.store_efficiency.slice(0, 15)}
              xField="efficiency"
              yField="store_name"
              height={400}
              color="#185FA5"
              label={{ position: 'right', formatter: (d: { efficiency?: number }) => `¥${d.efficiency?.toLocaleString() ?? ''}` }}
            />
          </Card>
        </Col>

        {/* 成本率热力列表 */}
        <Col span={12}>
          <Card title="各门店人工成本率">
            <Table
              dataSource={data.cost_heatmap}
              rowKey="store_name"
              pagination={{ pageSize: 15 }}
              size="small"
              columns={[
                { title: '门店', dataIndex: 'store_name' },
                {
                  title: '成本率',
                  dataIndex: 'cost_rate',
                  sorter: (a, b) => a.cost_rate - b.cost_rate,
                  render: (v: number) => (
                    <Tag
                      color={costColor(v)}
                      style={{
                        minWidth: 60,
                        textAlign: 'center',
                        background: costColor(v),
                        color: '#fff',
                        border: 'none',
                      }}
                    >
                      {v.toFixed(1)}%
                    </Tag>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
