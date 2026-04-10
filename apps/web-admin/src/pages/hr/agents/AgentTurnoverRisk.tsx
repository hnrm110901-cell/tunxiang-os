/**
 * AgentTurnoverRisk — 离职风险 Agent
 * 域H · Agent 中枢
 *
 * 功能：
 *  1. 高风险员工 ProTable（姓名/门店/风险评分/原因/建议干预）
 *  2. 风险评分颜色：>80红，60-80橙，<60灰
 *  3. 干预操作：标记已沟通/安排培训/调岗建议
 *  4. 风险分布 Pie 图
 *
 * API:
 *  POST /api/v1/agent/turnover_risk/calculate_risk_score
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Dropdown,
  message,
  Progress,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import {
  WarningOutlined,
  ReloadOutlined,
  MessageOutlined,
  BookOutlined,
  SwapOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface DimensionScore {
  score: number;
  detail: string;
}

interface RiskEmployee {
  employee_id: string;
  emp_name: string;
  store_id: string;
  store_name?: string;
  risk_score: number;
  risk_level: 'critical' | 'high' | 'medium' | 'low';
  risk_color: string;
  dimensions: Record<string, DimensionScore>;
  interventions: string[];
}

interface RiskResp {
  employees: RiskEmployee[];
  total_scanned: number;
  high_risk_count: number;
}

// ─── 辅助 ────────────────────────────────────────────────────────────────────

const riskColor = (score: number): string => {
  if (score >= 80) return '#A32D2D';
  if (score >= 60) return '#BA7517';
  return '#999';
};

const riskTag = (level: string): React.ReactNode => {
  const map: Record<string, { text: string; color: string }> = {
    critical: { text: '极高', color: 'red' },
    high: { text: '高', color: 'orange' },
    medium: { text: '中', color: 'gold' },
    low: { text: '低', color: 'default' },
  };
  const m = map[level] || map.low;
  return <Tag color={m.color}>{m.text}</Tag>;
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function AgentTurnoverRisk() {
  const actionRef = useRef<ActionType>();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<RiskResp | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const resp = await txFetch<{ data: RiskResp }>(
        '/api/v1/agent/turnover_risk/calculate_risk_score',
        { method: 'POST', body: JSON.stringify({}) },
      );
      setData(resp.data || resp as unknown as RiskResp);
    } catch {
      message.error('获取离职风险数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const employees = data?.employees || [];

  // 风险分布统计
  const distCritical = employees.filter((e) => e.risk_score >= 80).length;
  const distHigh = employees.filter((e) => e.risk_score >= 60 && e.risk_score < 80).length;
  const distMedium = employees.filter((e) => e.risk_score >= 40 && e.risk_score < 60).length;
  const distLow = employees.filter((e) => e.risk_score < 40).length;

  const columns: ProColumns<RiskEmployee>[] = [
    {
      title: '员工',
      dataIndex: 'emp_name',
      width: 120,
      render: (_, r) => (
        <div>
          <Tag color="blue" style={{ marginRight: 4 }}>AI建议</Tag>
          <Text strong>{r.emp_name}</Text>
        </div>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      width: 140,
      render: (_, r) => r.store_name || r.store_id,
    },
    {
      title: '风险评分',
      dataIndex: 'risk_score',
      width: 140,
      sorter: (a, b) => a.risk_score - b.risk_score,
      defaultSortOrder: 'descend',
      render: (_, r) => (
        <Space>
          <Progress
            type="circle"
            size={40}
            percent={r.risk_score}
            strokeColor={riskColor(r.risk_score)}
            format={() => <Text style={{ fontSize: 12, color: riskColor(r.risk_score) }}>{r.risk_score}</Text>}
          />
          {riskTag(r.risk_level)}
        </Space>
      ),
    },
    {
      title: '风险因子',
      dataIndex: 'dimensions',
      hideInSearch: true,
      render: (_, r) => (
        <Space direction="vertical" size={2}>
          {Object.entries(r.dimensions || {}).map(([key, dim]) => (
            dim.score >= 50 && (
              <Text key={key} style={{ fontSize: 12 }}>
                <Tag
                  color={dim.score >= 70 ? 'red' : dim.score >= 50 ? 'orange' : 'default'}
                  style={{ fontSize: 11, lineHeight: '18px' }}
                >
                  {dim.score}
                </Tag>
                {dim.detail}
              </Text>
            )
          ))}
        </Space>
      ),
    },
    {
      title: '建议干预',
      dataIndex: 'interventions',
      hideInSearch: true,
      width: 200,
      render: (_, r) => (
        <Space direction="vertical" size={2}>
          {(r.interventions || []).slice(0, 2).map((s, i) => (
            <Text key={i} type="secondary" style={{ fontSize: 12 }}>{s}</Text>
          ))}
        </Space>
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, r) => (
        <Dropdown
          menu={{
            items: [
              {
                key: 'talk',
                icon: <MessageOutlined />,
                label: '标记已沟通',
                onClick: () => {
                  message.success(`已标记与${r.emp_name}沟通`);
                },
              },
              {
                key: 'train',
                icon: <BookOutlined />,
                label: '安排培训',
                onClick: () => {
                  message.success(`已为${r.emp_name}安排培训`);
                },
              },
              {
                key: 'transfer',
                icon: <SwapOutlined />,
                label: '调岗建议',
                onClick: () => {
                  message.success(`已为${r.emp_name}提交调岗建议`);
                },
              },
            ],
          }}
        >
          <Button type="link" size="small">干预</Button>
        </Dropdown>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <WarningOutlined style={{ marginRight: 8, color: '#A32D2D' }} />
          离职风险 Agent
        </Title>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          重新扫描
        </Button>
      </div>

      {/* 风险分布统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="极高风险"
              value={distCritical}
              suffix="人"
              valueStyle={{ color: '#A32D2D' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="高风险"
              value={distHigh}
              suffix="人"
              valueStyle={{ color: '#BA7517' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="中风险" value={distMedium} suffix="人" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总扫描"
              value={data?.total_scanned || 0}
              suffix="人"
              valueStyle={{ color: '#0F6E56' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 风险分布色带 */}
      <Card style={{ marginBottom: 16 }}>
        <Text strong style={{ marginBottom: 8, display: 'block' }}>风险分布</Text>
        <div style={{ display: 'flex', height: 24, borderRadius: 4, overflow: 'hidden' }}>
          {distCritical > 0 && (
            <div
              style={{
                flex: distCritical,
                background: '#A32D2D',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ color: '#fff', fontSize: 11 }}>{distCritical}</Text>
            </div>
          )}
          {distHigh > 0 && (
            <div
              style={{
                flex: distHigh,
                background: '#BA7517',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ color: '#fff', fontSize: 11 }}>{distHigh}</Text>
            </div>
          )}
          {distMedium > 0 && (
            <div
              style={{
                flex: distMedium,
                background: '#EAC76C',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ fontSize: 11 }}>{distMedium}</Text>
            </div>
          )}
          {distLow > 0 && (
            <div
              style={{
                flex: distLow,
                background: '#e8e8e8',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ fontSize: 11 }}>{distLow}</Text>
            </div>
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <Text style={{ fontSize: 11, color: '#A32D2D' }}>极高 (80+)</Text>
          <Text style={{ fontSize: 11, color: '#BA7517' }}>高 (60-79)</Text>
          <Text style={{ fontSize: 11, color: '#999' }}>中 (40-59)</Text>
          <Text style={{ fontSize: 11, color: '#999' }}>低 (&lt;40)</Text>
        </div>
      </Card>

      {/* 员工风险表 */}
      <ProTable<RiskEmployee>
        actionRef={actionRef}
        columns={columns}
        dataSource={employees}
        rowKey="employee_id"
        loading={loading}
        search={false}
        pagination={{ defaultPageSize: 20 }}
        headerTitle="高风险员工列表"
      />
    </div>
  );
}
