/**
 * 日清日结页 — /store/manager/day-close
 *
 * 最能体现经营闭环能力的页面。
 * 不只是点"确认"，而是：看差异 → 理解原因 → 形成整改 → 完成签核
 *
 * Admin 终端（店长通过 POS 或浏览器访问）
 * 布局：左侧步骤区 + 中部核对区 + 右侧 Agent 解释区
 */
import { useState } from 'react';
import {
  Row, Col, Card, Typography, Descriptions, Tag, Table, Button, Space,
  Progress, Alert, Input, Divider, Badge, Result,
} from 'antd';
import {
  CheckCircleOutlined, ExclamationCircleOutlined, LockOutlined,
  FileAddOutlined,
} from '@ant-design/icons';
import { CloseDayStepper, CloseStep } from '../../components/agent/CloseDayStepper';
import { ShiftSummaryPanel } from '../../components/agent/ShiftSummaryPanel';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// ── 步骤定义 ────────────────────────────────────────────────────────────────
const INITIAL_STEPS: CloseStep[] = [
  { key: 'revenue', title: '营收核对', status: 'current', description: '核对今日营业额' },
  { key: 'payment', title: '支付核对', status: 'pending', description: '核对各支付渠道' },
  { key: 'refund', title: '退款核对', status: 'pending', anomalyCount: 2, description: '2项异常' },
  { key: 'invoice', title: '发票核对', status: 'pending' },
  { key: 'inventory', title: '库存抽检', status: 'pending' },
  { key: 'handover', title: '交班确认', status: 'pending' },
  { key: 'signoff', title: '店长签核', status: 'pending' },
];

// ── Mock 核对数据 ────────────────────────────────────────────────────────────
const REVENUE_DATA = [
  { item: '午市营收', system: 12800, manual: 12800, diff: 0 },
  { item: '晚市营收', system: 28600, manual: 28350, diff: -250 },
  { item: '外卖营收', system: 3200, manual: 3200, diff: 0 },
  { item: '今日总计', system: 44600, manual: 44350, diff: -250 },
];

const REFUND_ANOMALIES = [
  { id: '1', time: '14:32', amount: 580, reason: '客诉退菜', operator: '张三', status: '待核实' },
  { id: '2', time: '19:15', amount: 1200, reason: '整单退款', operator: '李四', status: '待核实' },
];

export default function DayClosePage() {
  const [currentStep, setCurrentStep] = useState(0);
  const [steps, setSteps] = useState<CloseStep[]>(INITIAL_STEPS);
  const [remark, setRemark] = useState('');

  const handleConfirmStep = () => {
    const updated = [...steps];
    updated[currentStep] = { ...updated[currentStep], status: 'completed' };
    if (currentStep + 1 < updated.length) {
      updated[currentStep + 1] = { ...updated[currentStep + 1], status: 'current' };
    }
    setSteps(updated);
    setCurrentStep(Math.min(currentStep + 1, steps.length - 1));
  };

  const completedCount = steps.filter((s) => s.status === 'completed').length;
  const progress = Math.round((completedCount / steps.length) * 100);

  return (
    <div>
      {/* 顶部状态条 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle">
          <Space size={24}>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>营业日</Text>
              <Title level={5} style={{ margin: 0 }}>2026-04-01</Title>
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>闭店进度</Text>
              <Progress percent={progress} size="small" style={{ width: 120, margin: '4px 0 0' }} />
            </div>
            <Descriptions size="small">
              <Descriptions.Item label="待核对">{steps.length - completedCount} 项</Descriptions.Item>
              <Descriptions.Item label="异常">
                <Badge count={2} size="small" />
              </Descriptions.Item>
            </Descriptions>
          </Space>
          {completedCount === steps.length && (
            <Tag icon={<LockOutlined />} color="green" style={{ fontSize: 14, padding: '4px 12px' }}>
              已锁账
            </Tag>
          )}
        </Row>
      </Card>

      <Row gutter={16}>
        {/* 左侧步骤区 */}
        <Col span={5}>
          <Card size="small" title="日结步骤">
            <CloseDayStepper
              steps={steps}
              currentStep={currentStep}
              onStepClick={setCurrentStep}
            />
          </Card>
        </Col>

        {/* 中部核对区 */}
        <Col span={12}>
          <Card
            size="small"
            title={steps[currentStep]?.title || '核对'}
            extra={
              <Space>
                <Button size="small" onClick={() => setCurrentStep(Math.max(0, currentStep - 1))}>
                  上一步
                </Button>
                <Button size="small" type="primary" onClick={handleConfirmStep}>
                  {currentStep === steps.length - 1 ? '完成签核' : '确认并下一步'}
                </Button>
              </Space>
            }
          >
            {/* 营收核对步骤 */}
            {currentStep === 0 && (
              <div>
                <Table
                  dataSource={REVENUE_DATA}
                  rowKey="item"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '项目', dataIndex: 'item', width: 120 },
                    {
                      title: '系统值 (¥)', dataIndex: 'system', width: 120,
                      render: (v) => `¥${v.toLocaleString()}`,
                    },
                    {
                      title: '人工值 (¥)', dataIndex: 'manual', width: 120,
                      render: (v) => `¥${v.toLocaleString()}`,
                    },
                    {
                      title: '差异', dataIndex: 'diff', width: 100,
                      render: (v) => (
                        <Text style={{ color: v !== 0 ? '#A32D2D' : '#0F6E56', fontWeight: 600 }}>
                          {v === 0 ? '✓ 一致' : `¥${v}`}
                        </Text>
                      ),
                    },
                  ]}
                />
                {REVENUE_DATA.some((r) => r.diff !== 0) && (
                  <Alert
                    message="发现差异"
                    description="晚市营收存在 ¥250 差异，请核实并填写原因"
                    type="warning"
                    showIcon
                    style={{ marginTop: 12 }}
                  />
                )}
                <div style={{ marginTop: 12 }}>
                  <Text strong style={{ fontSize: 12 }}>差异说明</Text>
                  <TextArea
                    value={remark}
                    onChange={(e) => setRemark(e.target.value)}
                    placeholder="请说明差异原因..."
                    rows={2}
                    style={{ marginTop: 4 }}
                  />
                </div>
              </div>
            )}

            {/* 退款核对步骤 */}
            {currentStep === 2 && (
              <div>
                <Alert
                  message="2 笔退款需要核实"
                  type="error"
                  showIcon
                  style={{ marginBottom: 12 }}
                />
                <Table
                  dataSource={REFUND_ANOMALIES}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '时间', dataIndex: 'time', width: 80 },
                    { title: '金额', dataIndex: 'amount', width: 100,
                      render: (v) => <Text style={{ color: '#A32D2D', fontWeight: 600 }}>¥{v}</Text>,
                    },
                    { title: '原因', dataIndex: 'reason', width: 120 },
                    { title: '操作人', dataIndex: 'operator', width: 80 },
                    { title: '状态', dataIndex: 'status', width: 80,
                      render: (s) => <Tag color="orange">{s}</Tag>,
                    },
                    { title: '操作', width: 120,
                      render: () => (
                        <Space>
                          <Button size="small" type="link">确认</Button>
                          <Button size="small" type="link" danger>标记异常</Button>
                        </Space>
                      ),
                    },
                  ]}
                />
              </div>
            )}

            {/* 签核步骤 */}
            {currentStep === steps.length - 1 && completedCount === steps.length - 1 && (
              <Result
                icon={<LockOutlined style={{ color: '#FF6B35' }} />}
                title="准备签核"
                subTitle="所有核对项已完成，确认签核后将锁定今日账目"
              />
            )}

            {/* 其他步骤占位 */}
            {![0, 2, steps.length - 1].includes(currentStep) && (
              <div style={{ padding: 40, textAlign: 'center', color: '#B4B2A9' }}>
                {steps[currentStep]?.title} — 核对数据加载中...
              </div>
            )}
          </Card>
        </Col>

        {/* 右侧 Agent 解释区 */}
        <Col span={7}>
          <ShiftSummaryPanel
            shiftName="今日"
            summary="今日整体经营正常，晚市营收存在小幅差异，退款率偏高需关注。"
            metrics={[
              { label: '今日营收', value: '¥44,600', changeRate: 0.05 },
              { label: '客流', value: '186人', changeRate: -0.02 },
              { label: '客单价', value: '¥240', changeRate: 0.08 },
              { label: '退款率', value: '4.0%', changeRate: 0.15, isAnomaly: true },
            ]}
            anomalies={[
              { title: '退款率偏高', description: '今日退款率 4.0%，高于基准 1.5%。主要集中在晚市，疑似出餐超时导致。', severity: 'critical' },
              { title: '晚市营收差异', description: '系统值与人工核对存在 ¥250 差异，可能为手动折扣未录入。', severity: 'warning' },
            ]}
            improvements={[
              '排查晚市退款集中时段，调整厨房出品节奏',
              '补录手动折扣记录，完善折扣审批流程',
              '明日班前会重点提醒出餐超时管控',
            ]}
          />

          <Card size="small" title="快捷动作" style={{ marginTop: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button block icon={<FileAddOutlined />}>生成整改任务</Button>
              <Button block>推送区域经理</Button>
              <Button block>导出日结报告</Button>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
