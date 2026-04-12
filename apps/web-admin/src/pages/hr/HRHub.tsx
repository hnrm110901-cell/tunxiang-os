/**
 * HRHub — 人力中枢首页 (P0入口)
 * Sprint 6 · 路由 /hr
 *
 * API: GET /api/v1/hr/dashboard
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Col, List, Row, Space, Tag, Typography, message } from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import { Line } from '@ant-design/charts';
import {
  AlertOutlined,
  AuditOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  DollarOutlined,
  RobotOutlined,
  TeamOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface HRDashboardData {
  total_active: number;
  today_expected: number;
  today_present: number;
  today_absent: number;
  pending_leave: number;
  schedule_conflicts: number;
  compliance_alerts: number;
  pending_payroll: number;
  labor_cost_rate: number;
  revenue_per_capita: number;
  attendance_trend: { date: string; rate: number }[];
  agent_suggestions: { id: string; agent: string; title: string; summary: string; severity: 'info' | 'warning' | 'critical' }[];
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function HRHub() {
  const navigate = useNavigate();
  const [data, setData] = useState<HRDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    txFetchData<HRDashboardData>('/api/v1/hr/dashboard')
      .then((resp) => setData(resp.data))
      .catch(() => message.error('加载人力中枢数据失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading || !data) return <Card loading />;

  return (
    <div>
      {/* 第一行：4个大指标 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '在职总人数',
              value: data.total_active,
              prefix: <TeamOutlined style={{ color: '#FF6B35' }} />,
            }}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate('/hr/employees')}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '今日应到',
              value: data.today_expected,
              prefix: <CalendarOutlined style={{ color: '#185FA5' }} />,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '今日实到',
              value: data.today_present,
              prefix: <ClockCircleOutlined style={{ color: '#0F6E56' }} />,
            }}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate('/hr/attendance')}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '缺岗数',
              value: data.today_absent,
              prefix: <WarningOutlined style={{ color: data.today_absent > 0 ? '#A32D2D' : '#999' }} />,
            }}
          />
        </Col>
      </Row>

      {/* 第二行：4个小指标 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <StatisticCard
            statistic={{ title: '待处理请假', value: data.pending_leave }}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate('/hr/leave')}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{ title: '排班冲突', value: data.schedule_conflicts }}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate('/hr/schedules')}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '合规预警',
              value: data.compliance_alerts,
              prefix: <AlertOutlined style={{ color: data.compliance_alerts > 0 ? '#A32D2D' : undefined }} />,
            }}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate('/hr/compliance')}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '待审核薪资',
              value: data.pending_payroll,
              prefix: <DollarOutlined />,
            }}
            style={{ cursor: 'pointer' }}
            onClick={() => navigate('/hr/payroll')}
          />
        </Col>
      </Row>

      {/* 中间行 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card title="人效指标">
            <StatisticCard.Group direction="column">
              <StatisticCard
                statistic={{
                  title: '人工成本率',
                  value: data.labor_cost_rate,
                  suffix: '%',
                  prefix: <AuditOutlined />,
                }}
              />
              <StatisticCard
                statistic={{
                  title: '人均产出(元/月)',
                  value: data.revenue_per_capita,
                  prefix: '¥',
                }}
              />
            </StatisticCard.Group>
          </Card>
        </Col>
        <Col span={16}>
          <Card title="出勤率趋势">
            <Line
              data={data.attendance_trend}
              xField="date"
              yField="rate"
              height={200}
              yAxis={{ label: { formatter: (v: string) => `${v}%` } }}
              point={{ size: 3 }}
              color="#FF6B35"
            />
          </Card>
        </Col>
      </Row>

      {/* Agent 建议 */}
      <Card
        title={
          <Space>
            <RobotOutlined style={{ color: '#185FA5' }} />
            <span>Agent 智能建议</span>
          </Space>
        }
      >
        <List
          dataSource={data.agent_suggestions}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Space>
                    <Tag color="blue">AI建议</Tag>
                    <Tag color={
                      item.severity === 'critical' ? 'red' : item.severity === 'warning' ? 'orange' : 'blue'
                    }>
                      {item.agent}
                    </Tag>
                    <Text strong>{item.title}</Text>
                  </Space>
                }
                description={item.summary}
              />
            </List.Item>
          )}
          locale={{ emptyText: '暂无 Agent 建议' }}
        />
      </Card>
    </div>
  );
}
