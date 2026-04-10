/**
 * ScheduleGaps — 缺岗补位
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable缺口列表（日期/岗位/时段/紧急度/状态）
 *  - urgency颜色编码（critical红/urgent橙/normal绿）
 *  - 操作列：指派（弹出候选人列表）/认领
 *
 * API: GET  /api/v1/schedules/gaps?store_id=&date=
 *      POST /api/v1/schedules/gaps/{id}/fill
 */

import { useRef, useState } from 'react';
import { Button, Modal, Space, Table, Tag, Typography, message } from 'antd';
import { UserAddOutlined, CheckOutlined } from '@ant-design/icons';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { txFetch } from '../../../api';

const { Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────

type Urgency = 'critical' | 'urgent' | 'normal';
type GapStatus = 'open' | 'filled' | 'cancelled';

interface GapItem {
  id: string;
  date: string;
  role: string;
  time_slot: string;
  urgency: Urgency;
  status: GapStatus;
  store_name: string;
  store_id: string;
}

interface Candidate {
  employee_id: string;
  employee_name: string;
  role: string;
  available: boolean;
}

const URGENCY_TAG: Record<Urgency, { color: string; label: string }> = {
  critical: { color: 'error', label: '紧急' },
  urgent: { color: 'warning', label: '较急' },
  normal: { color: 'success', label: '一般' },
};

const STATUS_TAG: Record<GapStatus, { color: string; label: string }> = {
  open: { color: 'warning', label: '待补' },
  filled: { color: 'success', label: '已补' },
  cancelled: { color: 'default', label: '取消' },
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function ScheduleGaps() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [candidateModal, setCandidateModal] = useState(false);
  const [currentGapId, setCurrentGapId] = useState<string>('');
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [candidateLoading, setCandidateLoading] = useState(false);

  // ─── 加载候选人 ──────────────────────────────────────────────────────────

  const openCandidateModal = async (gap: GapItem) => {
    setCurrentGapId(gap.id);
    setCandidateLoading(true);
    setCandidateModal(true);
    try {
      const res = await txFetch(
        `/api/v1/schedules/gaps/${gap.id}/candidates?store_id=${gap.store_id}`,
      ) as { ok: boolean; data: { items: Candidate[] } };
      if (res.ok) {
        setCandidates(res.data.items ?? []);
      }
    } catch { /* empty */ }
    setCandidateLoading(false);
  };

  const handleFill = async (employeeId: string) => {
    try {
      const res = await txFetch(`/api/v1/schedules/gaps/${currentGapId}/fill`, {
        method: 'POST',
        body: JSON.stringify({ employee_id: employeeId }),
      }) as { ok: boolean };
      if (res.ok) {
        messageApi.success('指派成功');
        setCandidateModal(false);
        actionRef.current?.reload();
      }
    } catch {
      messageApi.error('指派失败');
    }
  };

  const columns: ProColumns<GapItem>[] = [
    { title: '门店', dataIndex: 'store_name', width: 140, hideInSearch: true },
    { title: '日期', dataIndex: 'date', width: 120, hideInSearch: true },
    { title: '岗位', dataIndex: 'role', width: 100, hideInSearch: true },
    { title: '时段', dataIndex: 'time_slot', width: 140, hideInSearch: true },
    {
      title: '紧急度',
      dataIndex: 'urgency',
      width: 100,
      valueEnum: { critical: { text: '紧急' }, urgent: { text: '较急' }, normal: { text: '一般' } },
      render: (_, r) => {
        const t = URGENCY_TAG[r.urgency];
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueEnum: { open: { text: '待补' }, filled: { text: '已补' }, cancelled: { text: '取消' } },
      render: (_, r) => {
        const t = STATUS_TAG[r.status];
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
    {
      title: '日期',
      dataIndex: 'filter_date',
      valueType: 'date',
      hideInTable: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      hideInSearch: true,
      render: (_, r) =>
        r.status === 'open' ? (
          <Space>
            <Button
              type="link"
              size="small"
              icon={<UserAddOutlined />}
              onClick={() => openCandidateModal(r)}
            >
              指派
            </Button>
            <Button
              type="link"
              size="small"
              icon={<CheckOutlined />}
              onClick={() => {
                setCurrentGapId(r.id);
                handleFill('self');
              }}
            >
              认领
            </Button>
          </Space>
        ) : (
          <span style={{ color: '#999' }}>--</span>
        ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>缺岗补位</Title>

      <ProTable<GapItem>
        headerTitle="缺口列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.store_id) query.set('store_id', params.store_id);
          if (params.filter_date) query.set('date', params.filter_date);
          if (params.urgency) query.set('urgency', params.urgency);
          if (params.status) query.set('status', params.status);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetch(`/api/v1/schedules/gaps?${query}`) as {
              ok: boolean;
              data: { items: GapItem[]; total: number };
            };
            if (res.ok) {
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* ── 候选人弹窗 ── */}
      <Modal
        title="选择候选人"
        open={candidateModal}
        onCancel={() => setCandidateModal(false)}
        footer={null}
        width={500}
      >
        <Table
          dataSource={candidates}
          loading={candidateLoading}
          rowKey="employee_id"
          columns={[
            { title: '姓名', dataIndex: 'employee_name', width: 100 },
            { title: '岗位', dataIndex: 'role', width: 100 },
            {
              title: '可用',
              dataIndex: 'available',
              width: 80,
              render: (v: boolean) =>
                v ? <Tag color="success">空闲</Tag> : <Tag color="default">繁忙</Tag>,
            },
            {
              title: '操作',
              key: 'action',
              width: 80,
              render: (_: unknown, r: Candidate) => (
                <Button
                  type="primary"
                  size="small"
                  disabled={!r.available}
                  onClick={() => handleFill(r.employee_id)}
                  style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
                >
                  指派
                </Button>
              ),
            },
          ]}
          pagination={false}
          size="small"
        />
      </Modal>
    </div>
  );
}
