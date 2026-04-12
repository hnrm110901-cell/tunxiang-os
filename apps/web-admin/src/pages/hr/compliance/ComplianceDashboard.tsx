/**
 * ComplianceDashboard — 合规总览
 * Sprint 5 · 合规中心
 *
 * API: GET /api/v1/compliance/dashboard
 */

import { useEffect, useState } from 'react';
import { Card, Col, Row, message } from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import { Column, Line, Pie, Bar } from '@ant-design/charts';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface DashboardData {
  total: number;
  open: number;
  critical: number;
  resolved_this_month: number;
  by_type: { type: string; count: number }[];
  by_severity: { severity: string; count: number }[];
  store_ranking: { store_name: string; count: number }[];
  trend_7d: { date: string; count: number }[];
}

// ─── 颜色 ────────────────────────────────────────────────────────────────────

const severityColor: Record<string, string> = {
  critical: '#A32D2D',
  warning: '#BA7517',
  info: '#185FA5',
};

const typeColor = ['#FF6B35', '#185FA5', '#0F6E56', '#BA7517'];

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function ComplianceDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    txFetchData<DashboardData>('/api/v1/compliance/dashboard')
      .then((resp) => setData(resp.data))
      .catch(() => message.error('加载合规总览失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading || !data) return <Card loading />;

  return (
    <div>
      {/* 顶部4指标 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <StatisticCard
            statistic={{ title: '预警总数', value: data.total, prefix: <AlertOutlined /> }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '待处理',
              value: data.open,
              prefix: <ExclamationCircleOutlined style={{ color: '#BA7517' }} />,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '严重预警',
              value: data.critical,
              prefix: <WarningOutlined style={{ color: '#A32D2D' }} />,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '本月已解决',
              value: data.resolved_this_month,
              prefix: <CheckCircleOutlined style={{ color: '#0F6E56' }} />,
            }}
          />
        </Col>
      </Row>

      {/* 中部图表 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card title="按类型分布">
            <Pie
              data={data.by_type}
              angleField="count"
              colorField="type"
              radius={0.8}
              innerRadius={0.5}
              height={260}
              color={typeColor}
              label={{ type: 'spider', content: '{name}: {value}' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="按严重度分布">
            <Column
              data={data.by_severity}
              xField="severity"
              yField="count"
              height={260}
              color={({ severity }: { severity: string }) => severityColor[severity] ?? '#999'}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card title="门店预警排名">
            <Bar
              data={data.store_ranking.slice(0, 10)}
              xField="count"
              yField="store_name"
              height={260}
              color="#FF6B35"
            />
          </Card>
        </Col>
      </Row>

      {/* 趋势 */}
      <Card title="近7天趋势">
        <Line
          data={data.trend_7d}
          xField="date"
          yField="count"
          height={240}
          point={{ size: 4 }}
          color="#FF6B35"
        />
      </Card>
    </div>
  );
}
