/**
 * LeaveRequests — 请假管理
 * 域F · 组织人事 · 请假管理
 *
 * 功能：
 *  1. ProTable列表（员工/类型/起止时间/时长/状态/审批人）
 *  2. 状态筛选Tab：全部/待审批/已通过/已拒绝/已取消
 *  3. 操作列：审批/拒绝/详情
 *  4. 审批弹出ModalForm（审批意见）
 *
 * API:
 *  GET  /api/v1/leave-requests?store_id=xxx&status=pending
 *  POST /api/v1/leave-requests/{id}/approve
 *  POST /api/v1/leave-requests/{id}/reject
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  message,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { CalendarOutlined } from '@ant-design/icons';
import { txFetch } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface LeaveRequest {
  id: string;
  employee_id: string;
  employee_name: string;
  leave_type: 'annual' | 'personal' | 'sick' | 'compensatory' | 'maternity' | 'other';
  start_time: string;
  end_time: string;
  duration_hours: number;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  approver_name: string | null;
  reason: string;
  created_at: string;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const LEAVE_TYPE_MAP: Record<string, { label: string; color: string }> = {
  annual:       { label: '年假',   color: 'blue' },
  personal:     { label: '事假',   color: 'default' },
  sick:         { label: '病假',   color: 'orange' },
  compensatory: { label: '调休',   color: 'cyan' },
  maternity:    { label: '产假',   color: 'purple' },
  other:        { label: '其他',   color: 'default' },
};

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending:   { label: '待审批', color: 'orange' },
  approved:  { label: '已通过', color: 'green' },
  rejected:  { label: '已拒绝', color: 'red' },
  cancelled: { label: '已取消', color: 'default' },
};

const STATUS_TABS = [
  { key: 'all',       label: '全部' },
  { key: 'pending',   label: '待审批' },
  { key: 'approved',  label: '已通过' },
  { key: 'rejected',  label: '已拒绝' },
  { key: 'cancelled', label: '已取消' },
];

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function LeaveRequests() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [approveTarget, setApproveTarget] = useState<LeaveRequest | null>(null);
  const [rejectTarget, setRejectTarget] = useState<LeaveRequest | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetch<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res.data ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  useEffect(() => {
    actionRef.current?.reload();
  }, [storeId, statusFilter]);

  const handleApprove = async (values: Record<string, unknown>) => {
    if (!approveTarget) return false;
    try {
      await txFetch(`/api/v1/leave-requests/${approveTarget.id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ comment: values.comment }),
      });
      message.success('审批通过');
      setApproveTarget(null);
      actionRef.current?.reload();
      return true;
    } catch {
      message.error('审批失败');
      return false;
    }
  };

  const handleReject = async (values: Record<string, unknown>) => {
    if (!rejectTarget) return false;
    try {
      await txFetch(`/api/v1/leave-requests/${rejectTarget.id}/reject`, {
        method: 'POST',
        body: JSON.stringify({ comment: values.comment }),
      });
      message.success('已拒绝');
      setRejectTarget(null);
      actionRef.current?.reload();
      return true;
    } catch {
      message.error('拒绝失败');
      return false;
    }
  };

  const columns: ProColumns<LeaveRequest>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 90 },
    {
      title: '类型',
      dataIndex: 'leave_type',
      width: 80,
      render: (_, r) => {
        const t = LEAVE_TYPE_MAP[r.leave_type];
        return <Tag color={t?.color}>{t?.label}</Tag>;
      },
    },
    { title: '开始时间', dataIndex: 'start_time', width: 140 },
    { title: '结束时间', dataIndex: 'end_time', width: 140 },
    {
      title: '时长(h)',
      dataIndex: 'duration_hours',
      width: 80,
      render: (_, r) => r.duration_hours.toFixed(1),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
    { title: '审批人', dataIndex: 'approver_name', width: 90, render: (_, r) => r.approver_name ?? '-' },
    { title: '申请时间', dataIndex: 'created_at', width: 140 },
    {
      title: '操作',
      width: 180,
      render: (_, r) => (
        <Space>
          {r.status === 'pending' && (
            <>
              <Button type="link" size="small" onClick={() => setApproveTarget(r)}>
                通过
              </Button>
              <Button type="link" size="small" danger onClick={() => setRejectTarget(r)}>
                拒绝
              </Button>
            </>
          )}
          <Button type="link" size="small">
            详情
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <CalendarOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            请假管理
          </Title>
        </Col>
        <Col>
          <Select
            value={storeId}
            onChange={setStoreId}
            style={{ width: 200 }}
            placeholder="选择门店"
            options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
          />
        </Col>
      </Row>

      <Card
        tabList={STATUS_TABS.map((t) => ({ key: t.key, tab: t.label }))}
        activeTabKey={statusFilter}
        onTabChange={setStatusFilter}
      >
        <ProTable<LeaveRequest>
          actionRef={actionRef}
          columns={columns}
          request={async (params) => {
            if (!storeId) return { data: [], total: 0, success: true };
            const query = new URLSearchParams({
              store_id: storeId,
              ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
              page: String(params.current ?? 1),
              size: String(params.pageSize ?? 20),
            });
            const res = await txFetch<{ items: LeaveRequest[]; total: number }>(
              `/api/v1/leave-requests?${query.toString()}`,
            );
            return {
              data: res.data?.items ?? [],
              total: res.data?.total ?? 0,
              success: true,
            };
          }}
          rowKey="id"
          search={false}
          options={{ reload: true }}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 审批通过弹窗 */}
      <ModalForm
        title={`审批通过 — ${approveTarget?.employee_name}`}
        open={!!approveTarget}
        onOpenChange={(open) => {
          if (!open) setApproveTarget(null);
        }}
        onFinish={handleApprove}
        width={420}
      >
        <ProFormTextArea name="comment" label="审批意见" placeholder="可选填写审批意见" />
      </ModalForm>

      {/* 拒绝弹窗 */}
      <ModalForm
        title={`拒绝 — ${rejectTarget?.employee_name}`}
        open={!!rejectTarget}
        onOpenChange={(open) => {
          if (!open) setRejectTarget(null);
        }}
        onFinish={handleReject}
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
