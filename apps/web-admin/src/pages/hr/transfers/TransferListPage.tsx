/**
 * TransferListPage — 借调管理列表
 * 域F · 组织人事 · 借调管理
 *
 * 功能：
 *  1. 顶部统计：进行中N / 已完成N / 待审批N
 *  2. ProTable列表：员工姓名/原门店/目标门店/类型/起止日期/状态/操作
 *  3. 新建借调ModalForm
 *  4. 审批/完成/取消操作按钮
 *
 * API:
 *  GET  /api/v1/transfers?store_id=xxx&status=pending&page=1&size=20
 *  POST /api/v1/transfers
 *  PUT  /api/v1/transfers/{id}/approve
 *  PUT  /api/v1/transfers/{id}/complete
 *  PUT  /api/v1/transfers/{id}/cancel
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormDateRangePicker,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { PlusOutlined, SwapOutlined } from '@ant-design/icons';
import { txFetchData } from '../../../api';
import type { TransferOrder } from '../../../api/transferApi';
import {
  approveTransfer,
  cancelTransfer,
  completeTransfer,
  createTransfer,
  fetchTransfers,
} from '../../../api/transferApi';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── 枚举 ───────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending:   { label: '待审批', color: 'gold' },
  approved:  { label: '已审批', color: 'blue' },
  active:    { label: '进行中', color: 'green' },
  completed: { label: '已完成', color: 'default' },
  cancelled: { label: '已取消', color: 'red' },
};

const TYPE_MAP: Record<string, string> = {
  temporary:  '临时借调',
  permanent:  '长期借调',
  emergency:  '紧急支援',
};

const STATUS_TABS = [
  { key: 'all',       label: '全部' },
  { key: 'pending',   label: '待审批' },
  { key: 'active',    label: '进行中' },
  { key: 'completed', label: '已完成' },
  { key: 'cancelled', label: '已取消' },
];

// ─── 主组件 ──────────────────────────────────────────────

export default function TransferListPage() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [stats, setStats] = useState({ pending: 0, active: 0, completed: 0 });

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetchData<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res ?? [];
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

  const loadStats = async () => {
    try {
      const [p, a, c] = await Promise.all([
        fetchTransfers({ store_id: storeId || undefined, status: 'pending', size: 1 }),
        fetchTransfers({ store_id: storeId || undefined, status: 'active', size: 1 }),
        fetchTransfers({ store_id: storeId || undefined, status: 'completed', size: 1 }),
      ]);
      setStats({ pending: p.total, active: a.total, completed: c.total });
    } catch {
      // stats are optional
    }
  };

  useEffect(() => {
    if (storeId) loadStats();
  }, [storeId]);

  const handleApprove = async (record: TransferOrder) => {
    Modal.confirm({
      title: '确认审批通过',
      content: `确定批准 ${record.employee_name} 从 ${record.from_store_name} 借调至 ${record.to_store_name}？`,
      onOk: async () => {
        try {
          await approveTransfer(record.id, 'current_user');
          message.success('审批通过');
          actionRef.current?.reload();
          loadStats();
        } catch {
          message.error('审批失败');
        }
      },
    });
  };

  const handleComplete = async (record: TransferOrder) => {
    Modal.confirm({
      title: '确认完成借调',
      content: `确定完成 ${record.employee_name} 的借调？`,
      onOk: async () => {
        try {
          await completeTransfer(record.id);
          message.success('借调已完成');
          actionRef.current?.reload();
          loadStats();
        } catch {
          message.error('操作失败');
        }
      },
    });
  };

  const handleCancel = async (record: TransferOrder) => {
    Modal.confirm({
      title: '确认取消借调',
      content: `确定取消 ${record.employee_name} 的借调单？`,
      okType: 'danger',
      onOk: async () => {
        try {
          await cancelTransfer(record.id);
          message.success('借调已取消');
          actionRef.current?.reload();
          loadStats();
        } catch {
          message.error('取消失败');
        }
      },
    });
  };

  const handleCreate = async (values: Record<string, unknown>) => {
    try {
      const dates = values.date_range as [string, string];
      const fromStore = stores.find((s) => s.store_id === values.from_store_id);
      const toStore = stores.find((s) => s.store_id === values.to_store_id);
      await createTransfer({
        employee_id: values.employee_id as string,
        employee_name: values.employee_name as string,
        from_store_id: values.from_store_id as string,
        from_store_name: fromStore?.store_name ?? '',
        to_store_id: values.to_store_id as string,
        to_store_name: toStore?.store_name ?? '',
        start_date: dates[0],
        end_date: dates[1],
        transfer_type: (values.transfer_type as string) || 'temporary',
        reason: (values.reason as string) || '',
      });
      message.success('借调单已创建');
      setCreateOpen(false);
      actionRef.current?.reload();
      loadStats();
      return true;
    } catch {
      message.error('创建失败');
      return false;
    }
  };

  const columns: ProColumns<TransferOrder>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 90 },
    { title: '原门店', dataIndex: 'from_store_name', width: 120, ellipsis: true },
    { title: '目标门店', dataIndex: 'to_store_name', width: 120, ellipsis: true },
    {
      title: '类型',
      dataIndex: 'transfer_type',
      width: 100,
      render: (_, r) => TYPE_MAP[r.transfer_type] ?? r.transfer_type,
    },
    { title: '开始日期', dataIndex: 'start_date', width: 110 },
    { title: '结束日期', dataIndex: 'end_date', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
    { title: '原因', dataIndex: 'reason', width: 140, ellipsis: true },
    { title: '创建时间', dataIndex: 'created_at', width: 140, ellipsis: true },
    {
      title: '操作',
      width: 200,
      render: (_, r) => (
        <Space>
          {r.status === 'pending' && (
            <>
              <Button type="link" size="small" onClick={() => handleApprove(r)}>
                审批
              </Button>
              <Button type="link" size="small" danger onClick={() => handleCancel(r)}>
                取消
              </Button>
            </>
          )}
          {(r.status === 'approved' || r.status === 'active') && (
            <Button type="link" size="small" onClick={() => handleComplete(r)}>
              完成
            </Button>
          )}
          {r.status === 'approved' && (
            <Button type="link" size="small" danger onClick={() => handleCancel(r)}>
              取消
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <SwapOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            借调管理
          </Title>
        </Col>
        <Col>
          <Space>
            <Select
              value={storeId}
              onChange={setStoreId}
              style={{ width: 200 }}
              placeholder="选择门店"
              allowClear
              options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建借调
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="待审批" value={stats.pending} valueStyle={{ color: '#faad14' }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="进行中" value={stats.active} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="已完成" value={stats.completed} />
          </Card>
        </Col>
      </Row>

      {/* 列表 */}
      <Card
        tabList={STATUS_TABS.map((t) => ({ key: t.key, tab: t.label }))}
        activeTabKey={statusFilter}
        onTabChange={setStatusFilter}
      >
        <ProTable<TransferOrder>
          actionRef={actionRef}
          columns={columns}
          request={async (params) => {
            const res = await fetchTransfers({
              store_id: storeId || undefined,
              status: statusFilter !== 'all' ? statusFilter : undefined,
              page: params.current ?? 1,
              size: params.pageSize ?? 20,
            });
            return {
              data: res?.items ?? [],
              total: res?.total ?? 0,
              success: true,
            };
          }}
          rowKey="id"
          search={false}
          options={{ reload: true }}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 新建借调弹窗 */}
      <ModalForm
        title="新建借调单"
        open={createOpen}
        onOpenChange={setCreateOpen}
        onFinish={handleCreate}
        width={560}
      >
        <ProFormText name="employee_id" label="员工ID" rules={[{ required: true }]} />
        <ProFormText name="employee_name" label="员工姓名" rules={[{ required: true }]} />
        <ProFormSelect
          name="from_store_id"
          label="原门店"
          rules={[{ required: true }]}
          options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
        />
        <ProFormSelect
          name="to_store_id"
          label="目标门店"
          rules={[{ required: true }]}
          options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
        />
        <ProFormDateRangePicker
          name="date_range"
          label="借调日期范围"
          rules={[{ required: true }]}
        />
        <ProFormSelect
          name="transfer_type"
          label="借调类型"
          initialValue="temporary"
          options={[
            { label: '临时借调', value: 'temporary' },
            { label: '长期借调', value: 'permanent' },
            { label: '紧急支援', value: 'emergency' },
          ]}
        />
        <ProFormTextArea name="reason" label="借调原因" placeholder="请输入借调原因" />
      </ModalForm>
    </div>
  );
}
