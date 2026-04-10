/**
 * ScheduleAdjustments — 调班换班
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable展示调班申请（申请人/原班次/目标/原因/状态）
 *  - 操作列：批准/拒绝
 *
 * API: GET  /api/v1/schedules/swap-requests?store_id=
 *      POST /api/v1/schedules/swap-requests/{id}/approve
 */

import { useRef } from 'react';
import { Button, Popconfirm, Space, Tag, Typography, message } from 'antd';
import { CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { txFetch } from '../../../api';

const { Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────

type SwapStatus = 'pending' | 'approved' | 'rejected';

interface SwapRequest {
  id: string;
  applicant_name: string;
  applicant_id: string;
  original_date: string;
  original_shift: string;
  target_date: string;
  target_shift: string;
  target_employee_name?: string;
  reason: string;
  status: SwapStatus;
  created_at: string;
  store_name: string;
}

const STATUS_TAG: Record<SwapStatus, { color: string; label: string }> = {
  pending: { color: 'warning', label: '待审批' },
  approved: { color: 'success', label: '已批准' },
  rejected: { color: 'error', label: '已拒绝' },
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function ScheduleAdjustments() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();

  const handleAction = async (id: string, action: 'approve' | 'reject') => {
    try {
      const res = await txFetch(`/api/v1/schedules/swap-requests/${id}/${action}`, {
        method: 'POST',
      }) as { ok: boolean };
      if (res.ok) {
        messageApi.success(action === 'approve' ? '已批准' : '已拒绝');
        actionRef.current?.reload();
      }
    } catch {
      messageApi.error('操作失败');
    }
  };

  const columns: ProColumns<SwapRequest>[] = [
    { title: '申请人', dataIndex: 'applicant_name', width: 100 },
    { title: '门店', dataIndex: 'store_name', width: 140, hideInSearch: true },
    {
      title: '原班次',
      key: 'original',
      width: 160,
      hideInSearch: true,
      render: (_, r) => `${r.original_date} ${r.original_shift}`,
    },
    {
      title: '目标班次',
      key: 'target',
      width: 160,
      hideInSearch: true,
      render: (_, r) => `${r.target_date} ${r.target_shift}`,
    },
    { title: '换班对象', dataIndex: 'target_employee_name', width: 100, hideInSearch: true },
    { title: '原因', dataIndex: 'reason', width: 180, hideInSearch: true, ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueEnum: {
        pending: { text: '待审批', status: 'Warning' },
        approved: { text: '已批准', status: 'Success' },
        rejected: { text: '已拒绝', status: 'Error' },
      },
      render: (_, r) => {
        const t = STATUS_TAG[r.status];
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    { title: '申请时间', dataIndex: 'created_at', width: 160, hideInSearch: true },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      hideInSearch: true,
      render: (_, r) =>
        r.status === 'pending' ? (
          <Space>
            <Popconfirm title="确认批准此调班申请？" onConfirm={() => handleAction(r.id, 'approve')}>
              <Button type="link" size="small" icon={<CheckOutlined />} style={{ color: '#52c41a' }}>
                批准
              </Button>
            </Popconfirm>
            <Popconfirm title="确认拒绝此调班申请？" onConfirm={() => handleAction(r.id, 'reject')}>
              <Button type="link" size="small" icon={<CloseOutlined />} danger>
                拒绝
              </Button>
            </Popconfirm>
          </Space>
        ) : (
          <span style={{ color: '#999' }}>--</span>
        ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>调班换班</Title>

      <ProTable<SwapRequest>
        headerTitle="调班申请列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.store_id) query.set('store_id', params.store_id);
          if (params.status) query.set('status', params.status);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetch(`/api/v1/schedules/swap-requests?${query}`) as {
              ok: boolean;
              data: { items: SwapRequest[]; total: number };
            };
            if (res.ok) {
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />
    </div>
  );
}
