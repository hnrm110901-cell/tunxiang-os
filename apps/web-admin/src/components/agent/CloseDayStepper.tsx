/**
 * CloseDayStepper — 日清日结步骤器
 *
 * 用于日清日结页，左侧步骤导航。
 * 步骤：营收核对 → 支付核对 → 退款核对 → 发票核对 → 库存抽检 → 交班确认 → 店长签核
 */
import { Steps, Badge, Typography } from 'antd';
import {
  DollarOutlined,
  CreditCardOutlined,
  RollbackOutlined,
  FileTextOutlined,
  ShoppingOutlined,
  SwapOutlined,
  SafetyOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

export type CloseStepStatus = 'pending' | 'current' | 'completed' | 'anomaly';

export interface CloseStep {
  key: string;
  title: string;
  status: CloseStepStatus;
  anomalyCount?: number;
  description?: string;
}

export interface CloseDayStepperProps {
  steps: CloseStep[];
  currentStep: number;
  onStepClick: (stepIndex: number) => void;
}

const STEP_ICONS: Record<string, React.ReactNode> = {
  revenue: <DollarOutlined />,
  payment: <CreditCardOutlined />,
  refund: <RollbackOutlined />,
  invoice: <FileTextOutlined />,
  inventory: <ShoppingOutlined />,
  handover: <SwapOutlined />,
  signoff: <SafetyOutlined />,
};

const DEFAULT_STEPS: CloseStep[] = [
  { key: 'revenue', title: '营收核对', status: 'pending' },
  { key: 'payment', title: '支付核对', status: 'pending' },
  { key: 'refund', title: '退款核对', status: 'pending' },
  { key: 'invoice', title: '发票核对', status: 'pending' },
  { key: 'inventory', title: '库存抽检', status: 'pending' },
  { key: 'handover', title: '交班确认', status: 'pending' },
  { key: 'signoff', title: '店长签核', status: 'pending' },
];

export function CloseDayStepper({
  steps = DEFAULT_STEPS,
  currentStep,
  onStepClick,
}: CloseDayStepperProps) {
  return (
    <Steps
      direction="vertical"
      current={currentStep}
      onChange={onStepClick}
      items={steps.map((step, index) => {
        const icon = STEP_ICONS[step.key] || <CheckCircleOutlined />;
        const isAnomaly = step.status === 'anomaly';
        const isCompleted = step.status === 'completed';

        return {
          title: (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Text strong={index === currentStep} style={{ fontSize: 13 }}>
                {step.title}
              </Text>
              {isAnomaly && step.anomalyCount !== undefined && step.anomalyCount > 0 && (
                <Badge count={step.anomalyCount} size="small" />
              )}
              {isCompleted && (
                <CheckCircleOutlined style={{ color: '#0F6E56', fontSize: 12 }} />
              )}
              {isAnomaly && (
                <ExclamationCircleOutlined style={{ color: '#A32D2D', fontSize: 12 }} />
              )}
            </div>
          ),
          description: step.description ? (
            <Text type="secondary" style={{ fontSize: 11 }}>{step.description}</Text>
          ) : undefined,
          icon,
          status: isCompleted ? 'finish' as const
            : isAnomaly ? 'error' as const
            : index === currentStep ? 'process' as const
            : 'wait' as const,
        };
      })}
      style={{ padding: '16px 0' }}
    />
  );
}
