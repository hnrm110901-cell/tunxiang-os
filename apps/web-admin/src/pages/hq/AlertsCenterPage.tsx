/**
 * 预警中心 — /hub/alerts
 *
 * 总部发现问题的主入口。
 * 预警识别 + Agent解释 + 任务派发
 *
 * 布局：主列表 + 右侧详情/Agent区
 * Admin 终端：Ant Design 5.x + ProTable
 */
import { useRef, useState } from 'react';
import { ProTable, ProColumns, ActionType } from '@ant-design/pro-components';
import {
  Row, Col, Card, Tag, Button, Space, Typography, Descriptions,
  List, Drawer, Empty, Divider, Popconfirm, Input, Badge, message,
} from 'antd';
import {
  EyeOutlined, FileAddOutlined, SendOutlined, DeleteOutlined,
  RobotOutlined, BulbOutlined, HistoryOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type {
  AlertListItem, AlertDetail, AlertLevel, AlertStatus, AlertCategory,
} from '../../../../shared/api-types/p0-pages';
import { StatusTag } from '../../components/agent/StatusTag';

const { Text, Title, Paragraph } = Typography;

// ── Mock 数据 ────────────────────────────────────────────────────────────────

const MOCK_ALERTS: AlertListItem[] = [
  {
    alert_id: 'ALT001', alert_code: 'REV-DROP-001', alert_type: 'revenue_drop',
    alert_category: 'operation', alert_level: 'p1',
    brand_id: 'B1', brand_name: '尝在一起', region_id: 'R1', region_name: '湖南',
    store_id: 'S001', store_name: '长沙万达店',
    metric_name: '午市营收', metric_value: '¥9,600', baseline_value: '¥12,800',
    deviation_rate: -0.25, first_trigger_time: '2026-04-01T14:00:00Z',
    latest_trigger_time: '2026-04-01T14:30:00Z',
    alert_status: 'new', source_type: 'auto', has_agent_analysis: true, task_count: 0,
  },
  {
    alert_id: 'ALT002', alert_code: 'TURN-DROP-002', alert_type: 'table_turn_drop',
    alert_category: 'operation', alert_level: 'p2',
    brand_id: 'B1', brand_name: '尝在一起', region_id: 'R1', region_name: '湖南',
    store_id: 'S002', store_name: '株洲天元店',
    metric_name: '翻台率', metric_value: '2.1', baseline_value: '3.0',
    deviation_rate: -0.30, first_trigger_time: '2026-04-01T13:00:00Z',
    latest_trigger_time: '2026-04-01T14:00:00Z',
    alert_status: 'pending', owner_user_name: '张三', source_type: 'auto',
    has_agent_analysis: true, task_count: 1,
  },
  {
    alert_id: 'ALT003', alert_code: 'REFUND-SPIKE-003', alert_type: 'refund_spike',
    alert_category: 'cashier', alert_level: 'p1',
    brand_id: 'B1', brand_name: '尝在一起', region_id: 'R1', region_name: '湖南',
    store_id: 'S003', store_name: '湘潭河西店',
    metric_name: '退款率', metric_value: '4.2%', baseline_value: '1.5%',
    deviation_rate: 1.80, first_trigger_time: '2026-04-01T19:00:00Z',
    latest_trigger_time: '2026-04-01T20:00:00Z',
    alert_status: 'new', source_type: 'auto', has_agent_analysis: false, task_count: 0,
  },
  {
    alert_id: 'ALT004', alert_code: 'KIT-TO-004', alert_type: 'kitchen_timeout',
    alert_category: 'kitchen', alert_level: 'p2',
    brand_id: 'B1', brand_name: '尝在一起', region_id: 'R2', region_name: '江西',
    store_id: 'S004', store_name: '南昌红谷滩店',
    metric_name: '出餐超时率', metric_value: '18%', baseline_value: '5%',
    deviation_rate: 2.60, first_trigger_time: '2026-04-01T18:30:00Z',
    latest_trigger_time: '2026-04-01T19:30:00Z',
    alert_status: 'processing', owner_user_name: '李四', source_type: 'auto',
    has_agent_analysis: true, task_count: 2,
  },
];

const MOCK_DETAIL: AlertDetail = {
  alert_id: 'ALT001',
  event_summary: '长沙万达店午市营收同比下降25%，低于基准线¥12,800',
  impact_scope: '午市11:00-14:00，影响客流约40人次',
  business_shift: '午市',
  business_date: '2026-04-01',
  root_cause_candidates: [
    { cause_label: '竞对分流', confidence_score: 0.72, explanation: '万达广场新开2家竞品餐厅，分流效应明显' },
    { cause_label: '等位流失', confidence_score: 0.45, explanation: '午市等位流失率17%，高于常规8%' },
  ],
  recommended_actions: [
    { action_type: 'campaign', action_label: '推出午市限时套餐活动', target_role: '营销经理', priority: 'p1' },
    { action_type: 'rectification', action_label: '优化等位安抚流程', target_role: '店长', priority: 'p2' },
    { action_type: 'investigation', action_label: '调查竞对开业影响', target_role: '区域经理', priority: 'p2' },
  ],
  similar_cases: [
    { case_id: 'CASE-088', case_title: '2025年11月 衡阳店遭遇竞对开业分流', resolution_summary: '推出99元午市双人套餐，2周内营收恢复85%' },
  ],
  related_tasks: [],
};

// ── 页面组件 ─────────────────────────────────────────────────────────────────

export default function AlertsCenterPage() {
  const actionRef = useRef<ActionType>();
  const [selectedAlert, setSelectedAlert] = useState<AlertListItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const columns: ProColumns<AlertListItem>[] = [
    {
      title: '严重级', dataIndex: 'alert_level', width: 90,
      valueType: 'select',
      valueEnum: { p1: { text: 'P1', status: 'Error' }, p2: { text: 'P2', status: 'Warning' }, p3: { text: 'P3', status: 'Processing' } },
      render: (_, r) => <StatusTag status={r.alert_level} />,
    },
    { title: '门店', dataIndex: 'store_name', width: 130 },
    {
      title: '类型', dataIndex: 'alert_category', width: 80,
      valueType: 'select',
      valueEnum: {
        operation: '经营', service: '服务', kitchen: '厨房',
        cashier: '收银', member: '会员', risk: '风险',
      },
      render: (_, r) => <Tag>{r.alert_category === 'operation' ? '经营' : r.alert_category === 'kitchen' ? '厨房' : r.alert_category === 'cashier' ? '收银' : r.alert_category}</Tag>,
    },
    { title: '指标', dataIndex: 'metric_name', width: 100, search: false },
    {
      title: '当前值', dataIndex: 'metric_value', width: 90, search: false,
      render: (_, r) => <Text strong style={{ color: '#A32D2D' }}>{r.metric_value}</Text>,
    },
    { title: '基准', dataIndex: 'baseline_value', width: 90, search: false },
    {
      title: '偏离', dataIndex: 'deviation_rate', width: 80, search: false,
      render: (_, r) => (
        <Text style={{ color: Math.abs(r.deviation_rate) > 0.5 ? '#A32D2D' : '#BA7517' }}>
          {r.deviation_rate > 0 ? '+' : ''}{(r.deviation_rate * 100).toFixed(0)}%
        </Text>
      ),
    },
    {
      title: '状态', dataIndex: 'alert_status', width: 90,
      valueType: 'select',
      valueEnum: {
        new: { text: '新告警', status: 'Error' }, pending: { text: '待处理', status: 'Warning' },
        processing: { text: '处理中', status: 'Processing' }, closed: { text: '已闭环', status: 'Success' },
        ignored: { text: '已忽略', status: 'Default' },
      },
      render: (_, r) => <StatusTag status={r.alert_status} />,
    },
    { title: '责任人', dataIndex: 'owner_user_name', width: 80, search: false },
    {
      title: 'Agent', dataIndex: 'has_agent_analysis', width: 70, search: false,
      render: (_, r) => r.has_agent_analysis
        ? <Tag icon={<RobotOutlined />} color="blue">已分析</Tag>
        : <Tag>待分析</Tag>,
    },
    {
      title: '操作', valueType: 'option', width: 140, fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EyeOutlined />}
            onClick={() => { setSelectedAlert(record); setDetailOpen(true); }}>
            详情
          </Button>
          <Button type="link" size="small" icon={<FileAddOutlined />}>建任务</Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ height: '100%' }}>
      <Row gutter={16} style={{ height: '100%' }}>
        {/* 主列表区 */}
        <Col span={detailOpen ? 15 : 24}>
          <ProTable<AlertListItem>
            headerTitle="预警中心"
            columns={columns}
            actionRef={actionRef}
            dataSource={MOCK_ALERTS}
            rowKey="alert_id"
            search={{ labelWidth: 'auto', defaultCollapsed: false }}
            rowSelection={{}}
            tableAlertOptionRender={({ selectedRowKeys, onCleanSelected }) => (
              <Space>
                <Button size="small" icon={<SendOutlined />}>批量指派</Button>
                <Button size="small" icon={<FileAddOutlined />}>批量建任务</Button>
                <Button size="small" icon={<ThunderboltOutlined />}>发送至Agent工作台</Button>
                <Popconfirm title="确认批量忽略？">
                  <Button size="small" danger icon={<DeleteOutlined />}>批量忽略</Button>
                </Popconfirm>
                <Button size="small" type="link" onClick={onCleanSelected}>取消</Button>
              </Space>
            )}
            toolBarRender={() => [
              <Button key="agent" type="primary" icon={<RobotOutlined />}
                onClick={() => message.info('跳转总控Agent工作台')}>
                Agent 处置
              </Button>,
            ]}
            scroll={{ x: 1200 }}
            pagination={{ defaultPageSize: 20 }}
          />
        </Col>

        {/* 右侧详情区 */}
        {detailOpen && selectedAlert && (
          <Col span={9}>
            <Card
              size="small"
              title={
                <Space>
                  <StatusTag status={selectedAlert.alert_level} />
                  <Text strong>{selectedAlert.store_name} — {selectedAlert.metric_name}</Text>
                </Space>
              }
              extra={<Button type="text" size="small" onClick={() => setDetailOpen(false)}>关闭</Button>}
              style={{ height: '100%', overflow: 'auto' }}
            >
              {/* 事件摘要 */}
              <Card size="small" style={{ marginBottom: 12, background: '#F8F7F5' }}>
                <Paragraph style={{ margin: 0, fontSize: 13 }}>{MOCK_DETAIL.event_summary}</Paragraph>
              </Card>

              <Descriptions column={1} size="small">
                <Descriptions.Item label="影响范围">{MOCK_DETAIL.impact_scope}</Descriptions.Item>
                <Descriptions.Item label="班次">{MOCK_DETAIL.business_shift}</Descriptions.Item>
                <Descriptions.Item label="营业日">{MOCK_DETAIL.business_date}</Descriptions.Item>
              </Descriptions>

              {/* 原因分析 */}
              <Divider style={{ margin: '12px 0' }} />
              <Title level={5} style={{ fontSize: 13 }}>
                <BulbOutlined style={{ color: '#185FA5', marginRight: 6 }} />
                Agent 原因分析
              </Title>
              <List
                size="small"
                dataSource={MOCK_DETAIL.root_cause_candidates}
                renderItem={(c) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Space>
                          <Text strong>{c.cause_label}</Text>
                          <Tag color="blue">置信度 {(c.confidence_score * 100).toFixed(0)}%</Tag>
                        </Space>
                      }
                      description={<Text style={{ fontSize: 12 }}>{c.explanation}</Text>}
                    />
                  </List.Item>
                )}
              />

              {/* 建议动作 */}
              <Divider style={{ margin: '12px 0' }} />
              <Title level={5} style={{ fontSize: 13 }}>
                <ThunderboltOutlined style={{ color: '#FF6B35', marginRight: 6 }} />
                推荐动作
              </Title>
              <Space direction="vertical" style={{ width: '100%' }}>
                {MOCK_DETAIL.recommended_actions.map((a, i) => (
                  <Button key={i} block style={{ textAlign: 'left', height: 'auto', padding: '8px 12px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                      <Text>{a.action_label}</Text>
                      <Space>
                        <Tag style={{ fontSize: 10 }}>{a.target_role}</Tag>
                        <StatusTag status={a.priority} />
                      </Space>
                    </div>
                  </Button>
                ))}
              </Space>

              {/* 历史相似案例 */}
              {MOCK_DETAIL.similar_cases.length > 0 && (
                <>
                  <Divider style={{ margin: '12px 0' }} />
                  <Title level={5} style={{ fontSize: 13 }}>
                    <HistoryOutlined style={{ marginRight: 6 }} />
                    历史相似案例
                  </Title>
                  {MOCK_DETAIL.similar_cases.map((c) => (
                    <Card key={c.case_id} size="small" style={{ marginBottom: 8 }}>
                      <Text strong style={{ fontSize: 12 }}>{c.case_title}</Text>
                      <Paragraph style={{ margin: '4px 0 0', fontSize: 12, color: '#5F5E5A' }}>
                        {c.resolution_summary}
                      </Paragraph>
                    </Card>
                  ))}
                </>
              )}

              {/* 底部动作栏 */}
              <Divider style={{ margin: '12px 0' }} />
              <Space style={{ width: '100%' }} direction="vertical">
                <Button type="primary" block icon={<RobotOutlined />}>
                  发送至 Agent 工作台生成处置方案
                </Button>
                <Button block icon={<SendOutlined />}>指派责任人</Button>
                <Button block icon={<FileAddOutlined />}>直接生成整改任务</Button>
              </Space>
            </Card>
          </Col>
        )}
      </Row>
    </div>
  );
}
