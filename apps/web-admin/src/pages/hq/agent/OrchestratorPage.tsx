/**
 * 总控 Agent 工作台 — /hub/agent/orchestrator
 *
 * 最能体现"AI-Native"的页面。不是聊天页，而是：
 * - 输入目标（自然语言 / 模板 / 上下文带入）
 * - 看 Agent 拆解任务（步骤流）
 * - 看调用了哪些工具
 * - 看输出结果
 * - 审批/执行动作
 *
 * Admin 终端：Ant Design 5.x
 * 布局：左导航 + 中央任务区 + 右侧执行区
 */
import { useState } from 'react';
import {
  Input, Button, Card, Row, Col, Typography, Tag, Space, Divider,
  Tabs, Empty, Spin, Alert, List, Result,
} from 'antd';
import {
  SendOutlined, ThunderboltOutlined, HistoryOutlined,
  FileAddOutlined, MessageOutlined, AuditOutlined,
  RobotOutlined, BulbOutlined,
} from '@ant-design/icons';
import { TaskExecutionTimeline, ExecutionStep } from '../../components/agent/TaskExecutionTimeline';
import { ApprovalConfirmDialog } from '../../components/agent/ApprovalConfirmDialog';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// ── 任务模板 ────────────────────────────────────────────────────────────────
const TASK_TEMPLATES = [
  { label: '找出今日异常门店并生成整改方案', icon: <ThunderboltOutlined /> },
  { label: '分析本周营收下降原因', icon: <BulbOutlined /> },
  { label: '生成本周经营周报草稿', icon: <FileAddOutlined /> },
  { label: '哪些门店午市翻台率低于基准', icon: <AuditOutlined /> },
];

// ── Mock 执行步骤 ────────────────────────────────────────────────────────────
const MOCK_STEPS: ExecutionStep[] = [
  {
    id: '1', title: '拉取经营数据', description: '获取全品牌今日销售、客流、翻台数据',
    status: 'success', agentName: '总控Agent', toolsCalled: ['query_sales_summary', 'query_kpi_dashboard'],
    result: '已获取 23 家门店数据', durationMs: 1200,
  },
  {
    id: '2', title: '调用经营分析 Agent', description: '识别异常指标和可能原因',
    status: 'success', agentName: '总部分析Agent', toolsCalled: ['compare_stores', 'query_kpi_dashboard'],
    result: '发现 3 家门店存在异常', durationMs: 3400,
  },
  {
    id: '3', title: '生成整改方案', description: '基于异常原因生成具体整改任务',
    status: 'needs_confirmation', agentName: '总部分析Agent', toolsCalled: ['create_task'],
    onConfirm: () => {},
  },
  {
    id: '4', title: '推送通知', description: '将整改任务推送给区域经理',
    status: 'pending', agentName: '总控Agent', toolsCalled: ['send_notification'],
  },
];

// ── Mock 结果 ────────────────────────────────────────────────────────────────
const MOCK_RESULTS = [
  { store: '长沙万达店', anomaly: '午市营收同比-25%', cause: '新商圈竞对开业分流', action: '加强午市套餐活动' },
  { store: '株洲天元店', anomaly: '翻台率2.1（基准3.0）', cause: '等位流失率偏高', action: '优化等位安抚流程' },
  { store: '湘潭河西店', anomaly: '退款率4.2%（基准1.5%）', cause: '出餐超时导致客诉', action: '调整厨房排班' },
];

type PageState = 'empty' | 'running' | 'done' | 'error';

export default function OrchestratorPage() {
  const [taskInput, setTaskInput] = useState('');
  const [pageState, setPageState] = useState<PageState>('empty');
  const [approvalOpen, setApprovalOpen] = useState(false);

  const handleSubmit = () => {
    if (!taskInput.trim()) return;
    setPageState('running');
    // 模拟执行
    setTimeout(() => setPageState('done'), 2000);
  };

  const handleTemplate = (template: string) => {
    setTaskInput(template);
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <RobotOutlined style={{ fontSize: 24, color: '#FF6B35' }} />
        <div>
          <Title level={4} style={{ margin: 0 }}>总控 Agent 工作台</Title>
          <Text type="secondary" style={{ fontSize: 12 }}>输入目标 → Agent 拆解执行 → 审批结果</Text>
        </div>
      </div>

      <Row gutter={16} style={{ flex: 1, minHeight: 0 }}>
        {/* 中央任务区 */}
        <Col span={16} style={{ display: 'flex', flexDirection: 'column' }}>
          {/* 任务输入框 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space.Compact style={{ width: '100%' }}>
              <TextArea
                value={taskInput}
                onChange={(e) => setTaskInput(e.target.value)}
                placeholder="输入任务目标，如：找出今天午市异常的3家门店并生成整改方案"
                autoSize={{ minRows: 2, maxRows: 4 }}
                style={{ flex: 1 }}
              />
            </Space.Compact>
            <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between' }}>
              <Space wrap>
                {TASK_TEMPLATES.map((t) => (
                  <Button
                    key={t.label}
                    size="small"
                    icon={t.icon}
                    onClick={() => handleTemplate(t.label)}
                  >
                    {t.label.length > 15 ? t.label.slice(0, 15) + '...' : t.label}
                  </Button>
                ))}
              </Space>
              <Button type="primary" icon={<SendOutlined />} onClick={handleSubmit}>
                执行
              </Button>
            </div>
          </Card>

          {/* 任务执行区域 */}
          <Card
            size="small"
            style={{ flex: 1, overflow: 'auto' }}
            title={pageState !== 'empty' ? '任务执行' : undefined}
          >
            {pageState === 'empty' && (
              <Result
                icon={<RobotOutlined style={{ color: '#B4B2A9' }} />}
                title="输入任务目标开始"
                subTitle="选择上方模板或自由输入，Agent 将自动拆解并执行"
              />
            )}

            {pageState === 'running' && (
              <div>
                <Alert
                  message="任务执行中..."
                  description={taskInput}
                  type="info"
                  showIcon
                  icon={<Spin size="small" />}
                  style={{ marginBottom: 16 }}
                />
                <TaskExecutionTimeline steps={MOCK_STEPS} currentStep={2} />
              </div>
            )}

            {pageState === 'done' && (
              <div>
                <Alert
                  message="任务完成"
                  description={taskInput}
                  type="success"
                  showIcon
                  style={{ marginBottom: 16 }}
                />

                {/* 一句话结论 */}
                <Card size="small" style={{ marginBottom: 12, background: '#F8F7F5' }}>
                  <Paragraph strong style={{ margin: 0, fontSize: 14 }}>
                    发现 3 家门店经营异常，已生成整改方案待审批
                  </Paragraph>
                </Card>

                {/* 步骤流 */}
                <TaskExecutionTimeline steps={MOCK_STEPS} currentStep={3} />

                <Divider />

                {/* 结果列表 */}
                <Title level={5}>异常门店详情</Title>
                <List
                  bordered
                  dataSource={MOCK_RESULTS}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button size="small" type="primary" onClick={() => setApprovalOpen(true)}>
                          生成任务
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space>
                            <Text strong>{item.store}</Text>
                            <Tag color="red">{item.anomaly}</Tag>
                          </Space>
                        }
                        description={
                          <>
                            <Text type="secondary">原因：{item.cause}</Text>
                            <br />
                            <Text style={{ color: '#185FA5' }}>建议：{item.action}</Text>
                          </>
                        }
                      />
                    </List.Item>
                  )}
                />
              </div>
            )}
          </Card>
        </Col>

        {/* 右侧执行上下文 */}
        <Col span={8}>
          <Card size="small" title="当前上下文" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: '100%', fontSize: 12 }}>
              <div><Text type="secondary">品牌</Text>：尝在一起</div>
              <div><Text type="secondary">区域</Text>：湖南省全部</div>
              <div><Text type="secondary">日期</Text>：2026-04-01</div>
              <div><Text type="secondary">角色</Text>：COO</div>
            </Space>
          </Card>

          <Card size="small" title="快捷动作" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button block icon={<FileAddOutlined />}>生成整改任务包</Button>
              <Button block icon={<MessageOutlined />}>通知区域经理</Button>
              <Button block icon={<HistoryOutlined />}>查看历史任务</Button>
            </Space>
          </Card>

          <Card size="small" title="调用日志" extra={<Tag>4 次</Tag>}>
            <div style={{ fontSize: 11, color: '#5F5E5A' }}>
              <div>14:25 query_sales_summary → 1.2s ✓</div>
              <div>14:26 query_kpi_dashboard → 0.8s ✓</div>
              <div>14:27 compare_stores → 3.4s ✓</div>
              <div>14:28 create_task → 待确认</div>
            </div>
          </Card>
        </Col>
      </Row>

      {/* 审批弹窗 */}
      <ApprovalConfirmDialog
        open={approvalOpen}
        title="确认生成整改任务"
        description="Agent 将为 3 家异常门店各生成 1 项整改任务，并推送给区域经理。"
        riskLevel="medium"
        agentName="总部分析 Agent"
        impactItems={[
          { label: '影响门店', value: '长沙万达店、株洲天元店、湘潭河西店' },
          { label: '任务数量', value: '3 项' },
          { label: '通知人员', value: '区域经理 张三' },
        ]}
        onApprove={() => setApprovalOpen(false)}
        onReject={() => setApprovalOpen(false)}
        onCancel={() => setApprovalOpen(false)}
      />
    </div>
  );
}
