/**
 * LeaveDetail — 请假详情
 * 域F · 组织人事 · 请假管理
 *
 * 功能：
 *  1. 请假信息卡片（申请人/类型/时间/理由）
 *  2. 审批流程Timeline
 *  3. 操作按钮（审批/拒绝/取消）
 *
 * API:
 *  GET  /api/v1/leave-requests/{leave_id}
 *  POST /api/v1/leave-requests/{leave_id}/approve
 *  POST /api/v1/leave-requests/{leave_id}/reject
 *  POST /api/v1/leave-requests/{leave_id}/cancel
 */

import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  message,
  Result,
  Row,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormTextArea,
} from '@ant-design/pro-components';
import {
  CalendarOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_DANGER  = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface LeaveDetailData {
  id: string;
  employee_id: string;
  employee_name: string;
  leave_type: string;
  leave_type_label: string;
  start_time: string;
  end_time: string;
  duration_hours: number;
  reason: string;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  created_at: string;
  approval_flow: ApprovalStep[];
}

interface ApprovalStep {
  step: number;
  approver_name: string;
  action: 'pending' | 'approved' | 'rejected';
  comment: string | null;
  acted_at: string | null;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending:   { label: '待审批', color: 'orange' },
  approved:  { label: '已通过', color: 'green' },
  rejected:  { label: '已拒绝', color: 'red' },
  cancelled: { label: '已取消', color: 'default' },
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function LeaveDetail({ leaveId }: { leaveId?: string }) {
  const [data, setData] = useState<LeaveDetailData | null>(null);
  const [loading, setLoading] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  // 从URL参数或props获取leaveId
  const id = leaveId || new URLSearchParams(window.location.search).get('id') || '';

  const load = async () => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await txFetchData<LeaveDetailData>(`/api/v1/leave-requests/${id}`);
      setData(res.data);
    } catch {
      message.error('加载请假详情失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [id]);

  if (!id) {
    return <Result status="warning" title="缺少请假记录ID" />;
  }

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!data) {
    return <Result status="404" title="请假记录不存在" />;
  }

  const statusInfo = STATUS_MAP[data.status];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <CalendarOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
        请假详情
      </Title>

      {/* 请假信息卡片 */}
      <Card style={{ marginBottom: 16 }}>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="申请人">{data.employee_name}</Descriptions.Item>
          <Descriptions.Item label="请假类型">{data.leave_type_label}</Descriptions.Item>
          <Descriptions.Item label="开始时间">{data.start_time}</Descriptions.Item>
          <Descriptions.Item label="结束时间">{data.end_time}</Descriptions.Item>
          <Descriptions.Item label="时长">{data.duration_hours.toFixed(1)} 小时</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={statusInfo?.color}>{statusInfo?.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="请假理由" span={2}>
            {data.reason}
          </Descriptions.Item>
          <Descriptions.Item label="申请时间">{data.created_at}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 审批流程Timeline */}
      <Card title="审批流程" style={{ marginBottom: 16 }}>
        <Timeline
          items={data.approval_flow.map((step) => ({
            color:
              step.action === 'approved'
                ? 'green'
                : step.action === 'rejected'
                  ? 'red'
                  : 'gray',
            dot:
              step.action === 'approved' ? (
                <CheckCircleOutlined style={{ color: TX_SUCCESS }} />
              ) : step.action === 'rejected' ? (
                <CloseCircleOutlined style={{ color: TX_DANGER }} />
              ) : (
                <ClockCircleOutlined style={{ color: '#999' }} />
              ),
            children: (
              <div>
                <Text strong>
                  第{step.step}级审批 — {step.approver_name}
                </Text>
                <br />
                {step.action === 'pending' ? (
                  <Text type="secondary">待审批</Text>
                ) : (
                  <>
                    <Tag color={step.action === 'approved' ? 'green' : 'red'}>
                      {step.action === 'approved' ? '已通过' : '已拒绝'}
                    </Tag>
                    <Text type="secondary">{step.acted_at}</Text>
                    {step.comment && (
                      <div style={{ marginTop: 4 }}>
                        <Text type="secondary">意见：</Text>
                        {step.comment}
                      </div>
                    )}
                  </>
                )}
              </div>
            ),
          }))}
        />
      </Card>

      {/* 操作按钮 */}
      {data.status === 'pending' && (
        <Card>
          <Space>
            <Button type="primary" onClick={() => setApproveOpen(true)}>
              审批通过
            </Button>
            <Button danger onClick={() => setRejectOpen(true)}>
              拒绝
            </Button>
            <Button
              onClick={async () => {
                try {
                  await txFetchData(`/api/v1/leave-requests/${id}/cancel`, { method: 'POST' });
                  message.success('已取消');
                  load();
                } catch {
                  message.error('取消失败');
                }
              }}
            >
              取消
            </Button>
          </Space>
        </Card>
      )}

      {/* 审批弹窗 */}
      <ModalForm
        title="审批通过"
        open={approveOpen}
        onOpenChange={setApproveOpen}
        onFinish={async (values) => {
          try {
            await txFetchData(`/api/v1/leave-requests/${id}/approve`, {
              method: 'POST',
              body: JSON.stringify({ comment: values.comment }),
            });
            message.success('审批通过');
            setApproveOpen(false);
            load();
            return true;
          } catch {
            message.error('审批失败');
            return false;
          }
        }}
        width={420}
      >
        <ProFormTextArea name="comment" label="审批意见" placeholder="可选填写审批意见" />
      </ModalForm>

      {/* 拒绝弹窗 */}
      <ModalForm
        title="拒绝"
        open={rejectOpen}
        onOpenChange={setRejectOpen}
        onFinish={async (values) => {
          try {
            await txFetchData(`/api/v1/leave-requests/${id}/reject`, {
              method: 'POST',
              body: JSON.stringify({ comment: values.comment }),
            });
            message.success('已拒绝');
            setRejectOpen(false);
            load();
            return true;
          } catch {
            message.error('拒绝失败');
            return false;
          }
        }}
        width={420}
      >
        <ProFormTextArea
          name="comment"
          label="拒绝原因"
          rules={[{ required: true, message: '请输入拒绝原因' }]}
        />
      </ModalForm>
    </div>
  );
}
