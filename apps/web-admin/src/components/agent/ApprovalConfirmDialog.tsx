/**
 * ApprovalConfirmDialog — 审批确认弹窗
 *
 * 高风险 Agent 动作的二次确认：
 * - 显示动作详情
 * - 显示影响范围
 * - 必须填写审批备注
 * - 支持通过/驳回
 */
import { useState } from 'react';
import { Modal, Input, Descriptions, Tag, Typography, Alert, Space } from 'antd';
import { ExclamationCircleFilled } from '@ant-design/icons';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

export interface ApprovalItem {
  label: string;
  value: string;
}

export interface ApprovalConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  riskLevel: 'low' | 'medium' | 'high';
  agentName: string;
  impactItems: ApprovalItem[];
  onApprove: (remark: string) => void;
  onReject: (remark: string) => void;
  onCancel: () => void;
}

export function ApprovalConfirmDialog({
  open,
  title,
  description,
  riskLevel,
  agentName,
  impactItems,
  onApprove,
  onReject,
  onCancel,
}: ApprovalConfirmDialogProps) {
  const [remark, setRemark] = useState('');

  const riskColor = riskLevel === 'high' ? 'red' : riskLevel === 'medium' ? 'orange' : 'blue';
  const riskLabel = riskLevel === 'high' ? '高风险' : riskLevel === 'medium' ? '中风险' : '低风险';

  const handleApprove = () => {
    onApprove(remark);
    setRemark('');
  };

  const handleReject = () => {
    onReject(remark);
    setRemark('');
  };

  return (
    <Modal
      open={open}
      title={
        <Space>
          <ExclamationCircleFilled style={{ color: riskLevel === 'high' ? '#A32D2D' : '#BA7517' }} />
          <span>{title}</span>
        </Space>
      }
      onCancel={onCancel}
      footer={[
        <Space key="actions">
          <button
            key="reject"
            onClick={handleReject}
            style={{
              padding: '6px 16px', borderRadius: 6, cursor: 'pointer',
              border: '1px solid #A32D2D', background: 'white', color: '#A32D2D',
            }}
          >
            驳回
          </button>
          <button
            key="approve"
            onClick={handleApprove}
            disabled={riskLevel === 'high' && !remark.trim()}
            style={{
              padding: '6px 16px', borderRadius: 6, cursor: 'pointer',
              border: 'none', background: '#FF6B35', color: 'white',
              opacity: riskLevel === 'high' && !remark.trim() ? 0.5 : 1,
            }}
          >
            确认通过
          </button>
        </Space>,
      ]}
      width={520}
    >
      {riskLevel === 'high' && (
        <Alert
          message="此操作为高风险动作，请仔细确认"
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Paragraph>{description}</Paragraph>

      <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="发起 Agent">
          <Tag color="blue">{agentName}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="风险等级">
          <Tag color={riskColor}>{riskLabel}</Tag>
        </Descriptions.Item>
        {impactItems.map((item) => (
          <Descriptions.Item key={item.label} label={item.label}>
            {item.value}
          </Descriptions.Item>
        ))}
      </Descriptions>

      <Text strong style={{ fontSize: 13 }}>审批备注{riskLevel === 'high' && ' (必填)'}</Text>
      <TextArea
        value={remark}
        onChange={(e) => setRemark(e.target.value)}
        placeholder="请输入审批备注..."
        rows={3}
        style={{ marginTop: 8 }}
      />
    </Modal>
  );
}
