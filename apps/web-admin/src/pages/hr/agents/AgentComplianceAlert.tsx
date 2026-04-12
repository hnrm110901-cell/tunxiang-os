/**
 * AgentComplianceAlert — 合规预警 Agent
 * 域H · Agent 中枢
 *
 * 功能：
 *  1. Agent信息卡（最近执行/建议总数/处理率）
 *  2. 建议列表ProTable（从agent_decision_logs筛选agent_id='compliance_alert'）
 *  3. 每条建议：时间/内容/状态/操作
 *  4. AI建议用info蓝色Tag标注
 *
 * API:
 *  GET /api/v1/compliance/alerts?page=&size=&severity=&category=
 *  POST /api/v1/compliance/alerts/{id}/acknowledge
 *  POST /api/v1/compliance/alerts/{id}/resolve
 */

import { useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  message,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface AlertRecord {
  id: string;
  alert_type: string;
  category: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  detail: string;
  employee_id: string;
  employee_name: string;
  store_id: string;
  store_name: string;
  status: 'open' | 'acknowledged' | 'resolved';
  created_at: string;
}

interface AlertListResp {
  items: AlertRecord[];
  total: number;
}

// ─── 枚举映射 ────────────────────────────────────────────────────────────────

const severityMap: Record<string, { text: string; color: string }> = {
  critical: { text: '紧急', color: 'red' },
  high: { text: '高', color: 'orange' },
  medium: { text: '中', color: 'gold' },
  low: { text: '低', color: 'default' },
};

const statusMap: Record<string, { text: string; color: string }> = {
  open: { text: '待处理', color: 'red' },
  acknowledged: { text: '已确认', color: 'blue' },
  resolved: { text: '已解决', color: 'green' },
};

const categoryMap: Record<string, string> = {
  document: '证件到期',
  performance: '低绩效',
  attendance: '考勤异常',
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function AgentComplianceAlert() {
  const actionRef = useRef<ActionType>();
  const [stats, setStats] = useState({ total: 0, open: 0, resolved: 0 });

  const columns: ProColumns<AlertRecord>[] = [
    {
      title: '严重程度',
      dataIndex: 'severity',
      width: 90,
      valueType: 'select',
      valueEnum: {
        critical: { text: '紧急' },
        high: { text: '高' },
        medium: { text: '中' },
        low: { text: '低' },
      },
      render: (_, r) => {
        const s = severityMap[r.severity] || severityMap.low;
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '类别',
      dataIndex: 'category',
      width: 100,
      valueType: 'select',
      valueEnum: {
        document: { text: '证件到期' },
        performance: { text: '低绩效' },
        attendance: { text: '考勤异常' },
      },
      render: (_, r) => categoryMap[r.category] || r.category,
    },
    {
      title: '预警内容',
      dataIndex: 'title',
      hideInSearch: true,
      render: (_, r) => (
        <div>
          <div>
            <Tag color="blue" style={{ marginRight: 6 }}>AI建议</Tag>
            <Text strong>{r.title}</Text>
          </div>
          <Text type="secondary" style={{ fontSize: 12 }}>{r.detail}</Text>
        </div>
      ),
    },
    {
      title: '员工',
      dataIndex: 'employee_name',
      hideInSearch: true,
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      valueType: 'select',
      valueEnum: {
        open: { text: '待处理' },
        acknowledged: { text: '已确认' },
        resolved: { text: '已解决' },
      },
      render: (_, r) => {
        const s = statusMap[r.status] || statusMap.open;
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      valueType: 'dateTime',
      hideInSearch: true,
      width: 160,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_, r) => (
        <Space>
          {r.status === 'open' && (
            <a
              onClick={async () => {
                try {
                  await txFetchData(`/api/v1/compliance/alerts/${r.id}/acknowledge`, {
                    method: 'POST',
                    body: JSON.stringify({ acknowledged_by: 'current_user', note: '' }),
                  });
                  message.success('已确认');
                  actionRef.current?.reload();
                } catch {
                  message.error('操作失败');
                }
              }}
            >
              确认
            </a>
          )}
          {(r.status === 'open' || r.status === 'acknowledged') && (
            <ModalForm
              title="解决预警"
              trigger={<a>解决</a>}
              width={400}
              onFinish={async (values) => {
                try {
                  await txFetchData(`/api/v1/compliance/alerts/${r.id}/resolve`, {
                    method: 'POST',
                    body: JSON.stringify({
                      resolved_by: 'current_user',
                      resolution_note: values.note || '',
                    }),
                  });
                  message.success('已解决');
                  actionRef.current?.reload();
                  return true;
                } catch {
                  message.error('操作失败');
                  return false;
                }
              }}
            >
              <ProFormTextArea
                name="note"
                label="解决说明"
                rules={[{ required: true, message: '请输入解决说明' }]}
              />
            </ModalForm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <AlertOutlined style={{ marginRight: 8, color: '#A32D2D' }} />
        合规预警 Agent
      </Title>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="预警总数" value={stats.total} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="待处理"
              value={stats.open}
              valueStyle={{ color: stats.open > 0 ? '#A32D2D' : undefined }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="处理率"
              value={stats.total > 0 ? ((stats.resolved / stats.total) * 100).toFixed(1) : 0}
              suffix="%"
              valueStyle={{ color: '#0F6E56' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 预警列表 */}
      <ProTable<AlertRecord>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query = new URLSearchParams();
          query.set('page', String(params.current || 1));
          query.set('size', String(params.pageSize || 20));
          if (params.severity) query.set('severity', params.severity);
          if (params.category) query.set('category', params.category);
          if (params.status) query.set('status', params.status);
          try {
            const data = await txFetchData<AlertListResp>(
              `/api/v1/compliance/alerts?${query.toString()}`,
            );
            const items = data.items || [];
            const total = data.total || 0;
            const open = items.filter((i) => i.status === 'open').length;
            const resolved = items.filter((i) => i.status === 'resolved').length;
            setStats({ total, open, resolved });
            return { data: items, total, success: true };
          } catch {
            return { data: [], total: 0, success: true };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <Button
            key="scan"
            type="primary"
            icon={<ReloadOutlined />}
            onClick={async () => {
              try {
                await txFetchData('/api/v1/compliance/scan', {
                  method: 'POST',
                  body: JSON.stringify({ scan_type: 'all' }),
                });
                message.success('扫描已触发');
                actionRef.current?.reload();
              } catch {
                message.error('扫描失败');
              }
            }}
          >
            触发全量扫描
          </Button>,
        ]}
      />
    </div>
  );
}
