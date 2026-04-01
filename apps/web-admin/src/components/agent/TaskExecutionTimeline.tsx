/**
 * TaskExecutionTimeline — Agent 任务分解执行时间线
 *
 * 用于总控 Agent 工作台页，展示：
 * - 任务分解步骤
 * - 当前执行位置
 * - 每步调用的工具
 * - 成功/失败/待确认状态
 */
import { Steps, Tag, Typography, Spin, Button } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  ToolOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

export type StepStatus = 'pending' | 'running' | 'success' | 'failed' | 'needs_confirmation';

export interface ExecutionStep {
  id: string;
  title: string;
  description: string;
  status: StepStatus;
  agentName?: string;
  toolsCalled?: string[];
  result?: string;
  error?: string;
  durationMs?: number;
  onRetry?: () => void;
  onConfirm?: () => void;
}

export interface TaskExecutionTimelineProps {
  steps: ExecutionStep[];
  currentStep: number;
}

const statusIcon: Record<StepStatus, React.ReactNode> = {
  pending: <ClockCircleOutlined style={{ color: '#B4B2A9' }} />,
  running: <LoadingOutlined style={{ color: '#FF6B35' }} />,
  success: <CheckCircleOutlined style={{ color: '#0F6E56' }} />,
  failed: <CloseCircleOutlined style={{ color: '#A32D2D' }} />,
  needs_confirmation: <ExclamationCircleOutlined style={{ color: '#BA7517' }} />,
};

const statusToAntd = (s: StepStatus) => {
  if (s === 'running') return 'process' as const;
  if (s === 'success') return 'finish' as const;
  if (s === 'failed') return 'error' as const;
  return 'wait' as const;
};

export function TaskExecutionTimeline({ steps, currentStep }: TaskExecutionTimelineProps) {
  return (
    <Steps
      direction="vertical"
      current={currentStep}
      items={steps.map((step) => ({
        title: (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text strong>{step.title}</Text>
            {step.agentName && <Tag color="blue" style={{ fontSize: 10 }}>{step.agentName}</Tag>}
            {step.durationMs !== undefined && step.status === 'success' && (
              <Text type="secondary" style={{ fontSize: 11 }}>{step.durationMs}ms</Text>
            )}
          </div>
        ),
        description: (
          <div>
            <Paragraph style={{ margin: '4px 0', fontSize: 12, color: '#5F5E5A' }}>
              {step.description}
            </Paragraph>
            {step.toolsCalled && step.toolsCalled.length > 0 && (
              <div style={{ margin: '4px 0' }}>
                <ToolOutlined style={{ fontSize: 11, color: '#B4B2A9', marginRight: 4 }} />
                {step.toolsCalled.map((t) => (
                  <Tag key={t} style={{ fontSize: 10, marginBottom: 2 }}>{t}</Tag>
                ))}
              </div>
            )}
            {step.result && step.status === 'success' && (
              <Paragraph style={{ fontSize: 12, color: '#0F6E56', margin: '4px 0' }}>
                {step.result}
              </Paragraph>
            )}
            {step.error && step.status === 'failed' && (
              <div>
                <Paragraph style={{ fontSize: 12, color: '#A32D2D', margin: '4px 0' }}>
                  {step.error}
                </Paragraph>
                {step.onRetry && (
                  <Button size="small" danger onClick={step.onRetry}>重试</Button>
                )}
              </div>
            )}
            {step.status === 'needs_confirmation' && step.onConfirm && (
              <Button size="small" type="primary" onClick={step.onConfirm} style={{ marginTop: 4 }}>
                确认执行
              </Button>
            )}
          </div>
        ),
        status: statusToAntd(step.status),
        icon: step.status === 'running' ? <Spin size="small" /> : statusIcon[step.status],
      }))}
    />
  );
}
