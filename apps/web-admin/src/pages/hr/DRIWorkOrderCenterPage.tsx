/**
 * DRI工单中心 — DRIWorkOrderCenterPage
 * 域: HR . DRI工单管理
 *
 * Section 1: 统计仪表板 (StatisticCards + 类型分布 Tags)
 * Section 2: 工单列表 (ProTable + 筛选 + 新建)
 * Section 3: 新建/编辑工单 (ModalForm)
 * Section 4: 工单详情 (Drawer + 状态流转 + 行动项)
 *
 * API: GET/POST/PUT/DELETE /api/v1/dri-workorders
 */

import { useEffect, useRef, useState } from 'react';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Space,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import { ExclamationCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { txFetchData } from '../../api/client';
import dayjs from 'dayjs';

const { Text } = Typography;

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型定义
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface DRIWorkOrder {
  id: string;
  order_no: string;
  order_type: string;
  store_id: string;
  store_name?: string;
  title: string;
  description: string | null;
  severity: string;
  status: string;
  dri_user_id: string | null;
  dri_user_name?: string;
  collaborators: { user_id: string; role: string }[];
  actions: {
    action: string;
    assigned_to: string;
    due_date: string;
    status: string;
    result?: string;
    completed_at?: string;
  }[];
  due_date: string | null;
  completed_at: string | null;
  resolution: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

interface Statistics {
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  overdue_count: number;
  avg_resolution_days: number | null;
}

interface PagedResult {
  items: DRIWorkOrder[];
  total: number;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  枚举映射
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const orderTypeMap: Record<string, { text: string; color: string }> = {
  recruit: { text: '招聘补岗', color: 'blue' },
  fill_gap: { text: '缺岗救火', color: 'red' },
  training: { text: '训练补课', color: 'green' },
  retention: { text: '留存挽救', color: 'orange' },
  reform: { text: '问题店整改', color: 'purple' },
  new_store: { text: '新店筹开', color: 'cyan' },
};

const severityMap: Record<string, { text: string; color: string }> = {
  critical: { text: '紧急', color: 'red' },
  high: { text: '高', color: 'orange' },
  medium: { text: '中', color: 'blue' },
  low: { text: '低', color: 'default' },
};

const statusMap: Record<string, { text: string; status: 'default' | 'processing' | 'success' | 'error' }> = {
  draft: { text: '草稿', status: 'default' },
  assigned: { text: '已分配', status: 'processing' },
  in_progress: { text: '处理中', status: 'processing' },
  completed: { text: '已完成', status: 'success' },
  closed: { text: '已关闭', status: 'default' },
  cancelled: { text: '已取消', status: 'error' },
};

const VALID_TRANSITIONS: Record<string, string[]> = {
  draft: ['assigned'],
  assigned: ['in_progress', 'draft'],
  in_progress: ['completed', 'assigned', 'cancelled'],
  completed: ['closed'],
};

const transitionLabel: Record<string, string> = {
  assigned: '分配',
  in_progress: '开始处理',
  completed: '完成',
  closed: '关闭',
  draft: '退回',
  cancelled: '取消',
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function DRIWorkOrderCenterPage() {
  const actionRef = useRef<ActionType>();
  const [stats, setStats] = useState<Statistics | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [createVisible, setCreateVisible] = useState(false);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [currentOrder, setCurrentOrder] = useState<DRIWorkOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 行动项表单
  const [actionFormVisible, setActionFormVisible] = useState(false);
  const [newAction, setNewAction] = useState({ action: '', assigned_to: '', due_date: '' });

  // 流转 modal
  const [transitionModal, setTransitionModal] = useState<{
    visible: boolean;
    targetStatus: string;
    needsInput: boolean;
    inputLabel: string;
    fieldName: string;
  }>({
    visible: false,
    targetStatus: '',
    needsInput: false,
    inputLabel: '',
    fieldName: '',
  });
  const [transitionInput, setTransitionInput] = useState('');

  // ━━━━ 加载统计数据 ━━━━
  const loadStats = async () => {
    setStatsLoading(true);
    try {
      const resp = await txFetchData<Statistics>('/api/v1/dri-workorders/statistics');
      setStats(resp.data);
    } catch (err) {
      // 统计加载失败不阻塞页面
      console.error('Failed to load statistics', err);
    } finally {
      setStatsLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  // ━━━━ 加载工单详情 ━━━━
  const loadDetail = async (id: string) => {
    setDetailLoading(true);
    try {
      const resp = await txFetchData<DRIWorkOrder>(`/api/v1/dri-workorders/${id}`);
      setCurrentOrder(resp.data);
      setDrawerVisible(true);
    } catch (err) {
      message.error('加载工单详情失败');
      console.error(err);
    } finally {
      setDetailLoading(false);
    }
  };

  // ━━━━ 创建工单 ━━━━
  const handleCreate = async (values: Record<string, unknown>) => {
    try {
      await txFetchData('/api/v1/dri-workorders', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('工单创建成功');
      setCreateVisible(false);
      actionRef.current?.reload();
      loadStats();
      return true;
    } catch (err) {
      message.error('创建失败');
      console.error(err);
      return false;
    }
  };

  // ━━━━ 删除工单（仅草稿） ━━━━
  const handleDelete = async (id: string) => {
    try {
      await txFetchData(`/api/v1/dri-workorders/${id}`, { method: 'DELETE' });
      message.success('工单已删除');
      actionRef.current?.reload();
      loadStats();
    } catch (err) {
      message.error('删除失败');
      console.error(err);
    }
  };

  // ━━━━ 状态流转 ━━━━
  const handleTransition = async (targetStatus: string) => {
    if (!currentOrder) return;

    // completed 需要 resolution, cancelled 需要 reason
    if (targetStatus === 'completed') {
      setTransitionModal({
        visible: true,
        targetStatus,
        needsInput: true,
        inputLabel: '处理结果',
        fieldName: 'resolution',
      });
      setTransitionInput('');
      return;
    }
    if (targetStatus === 'cancelled') {
      setTransitionModal({
        visible: true,
        targetStatus,
        needsInput: true,
        inputLabel: '取消原因',
        fieldName: 'reason',
      });
      setTransitionInput('');
      return;
    }

    await doTransition(targetStatus);
  };

  const doTransition = async (targetStatus: string, extraBody?: Record<string, string>) => {
    if (!currentOrder) return;
    try {
      const body: Record<string, string> = { target_status: targetStatus, ...extraBody };
      const resp = await txFetchData<DRIWorkOrder>(`/api/v1/dri-workorders/${currentOrder.id}/transition`, {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      message.success(`工单已${transitionLabel[targetStatus] ?? '流转'}`);
      setCurrentOrder(resp.data);
      actionRef.current?.reload();
      loadStats();
      setTransitionModal((prev) => ({ ...prev, visible: false }));
    } catch (err) {
      message.error('状态流转失败');
      console.error(err);
    }
  };

  const confirmTransition = () => {
    const { targetStatus, fieldName } = transitionModal;
    if (!transitionInput.trim()) {
      message.warning('请填写必填内容');
      return;
    }
    doTransition(targetStatus, { [fieldName]: transitionInput.trim() });
  };

  // ━━━━ 添加行动项 ━━━━
  const handleAddAction = async () => {
    if (!currentOrder) return;
    if (!newAction.action.trim() || !newAction.assigned_to.trim() || !newAction.due_date) {
      message.warning('请填写完整行动项信息');
      return;
    }
    try {
      const resp = await txFetchData<DRIWorkOrder>(`/api/v1/dri-workorders/${currentOrder.id}/actions`, {
        method: 'POST',
        body: JSON.stringify(newAction),
      });
      message.success('行动项已添加');
      setCurrentOrder(resp.data);
      setActionFormVisible(false);
      setNewAction({ action: '', assigned_to: '', due_date: '' });
    } catch (err) {
      message.error('添加行动项失败');
      console.error(err);
    }
  };

  // ━━━━ 完成行动项 ━━━━
  const handleCompleteAction = async (index: number) => {
    if (!currentOrder) return;
    try {
      const resp = await txFetchData<DRIWorkOrder>(
        `/api/v1/dri-workorders/${currentOrder.id}/actions/${index}/complete`,
        { method: 'PUT' },
      );
      message.success('行动项已完成');
      setCurrentOrder(resp.data);
    } catch (err) {
      message.error('操作失败');
      console.error(err);
    }
  };

  // ━━━━ 判断是否逾期 ━━━━
  const isOverdue = (order: DRIWorkOrder) => {
    if (!order.due_date) return false;
    const terminalStatuses = ['completed', 'closed', 'cancelled'];
    if (terminalStatuses.includes(order.status)) return false;
    return dayjs(order.due_date).isBefore(dayjs(), 'day');
  };

  // ━━━━ 统计卡片区 ━━━━
  const pendingCount = stats
    ? (stats.by_status['draft'] ?? 0) + (stats.by_status['assigned'] ?? 0) + (stats.by_status['in_progress'] ?? 0)
    : 0;
  const completedCount = stats?.by_status['completed'] ?? 0;

  // ━━━━ ProTable 列定义 ━━━━
  const columns: ProColumns<DRIWorkOrder>[] = [
    {
      title: '工单号',
      dataIndex: 'order_no',
      width: 140,
      fixed: 'left',
      copyable: true,
      search: false,
    },
    {
      title: '类型',
      dataIndex: 'order_type',
      width: 110,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(orderTypeMap).map(([k, v]) => [k, { text: v.text }]),
      ),
      render: (_, record) => {
        const cfg = orderTypeMap[record.order_type];
        return cfg ? <Tag color={cfg.color}>{cfg.text}</Tag> : record.order_type;
      },
    },
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      search: false,
      render: (_, record) => (
        <a onClick={() => loadDetail(record.id)}>{record.title}</a>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      search: false,
      width: 120,
      ellipsis: true,
    },
    {
      title: '严重程度',
      dataIndex: 'severity',
      width: 90,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(severityMap).map(([k, v]) => [k, { text: v.text }]),
      ),
      render: (_, record) => {
        const cfg = severityMap[record.severity];
        return cfg ? <Tag color={cfg.color}>{cfg.text}</Tag> : record.severity;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueType: 'select',
      fieldProps: { mode: 'multiple' },
      valueEnum: Object.fromEntries(
        Object.entries(statusMap).map(([k, v]) => [k, { text: v.text }]),
      ),
      render: (_, record) => {
        const cfg = statusMap[record.status];
        return cfg ? <Badge status={cfg.status} text={cfg.text} /> : record.status;
      },
    },
    {
      title: 'DRI负责人',
      dataIndex: 'dri_user_name',
      search: false,
      width: 100,
      ellipsis: true,
    },
    {
      title: '截止日期',
      dataIndex: 'due_date',
      search: false,
      width: 110,
      render: (_, record) => {
        if (!record.due_date) return '-';
        const overdue = isOverdue(record);
        return (
          <Text type={overdue ? 'danger' : undefined} strong={overdue}>
            {dayjs(record.due_date).format('YYYY-MM-DD')}
            {overdue && ' (逾期)'}
          </Text>
        );
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      search: false,
      width: 160,
      render: (_, record) => dayjs(record.created_at).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '关键字',
      dataIndex: 'keyword',
      hideInTable: true,
      fieldProps: { placeholder: '搜索标题' },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <a onClick={() => loadDetail(record.id)}>详情</a>
          {VALID_TRANSITIONS[record.status]?.length ? (
            <a
              onClick={() => {
                loadDetail(record.id);
              }}
            >
              流转
            </a>
          ) : null}
          {record.status === 'draft' && (
            <Popconfirm title="确认删除此草稿工单？" onConfirm={() => handleDelete(record.id)}>
              <a style={{ color: '#ff4d4f' }}>删除</a>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  渲染
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  return (
    <div style={{ padding: 24 }}>
      {/* ━━━━ Section 1: 统计仪表板 ━━━━ */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <StatisticCard
            loading={statsLoading}
            statistic={{
              title: '待处理工单',
              value: pendingCount,
              suffix: '单',
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={statsLoading}
            statistic={{
              title: '已逾期',
              value: stats?.overdue_count ?? 0,
              suffix: '单',
              valueStyle: { color: '#ff4d4f' },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={statsLoading}
            statistic={{
              title: '本月完成',
              value: completedCount,
              suffix: '单',
              valueStyle: { color: '#52c41a' },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={statsLoading}
            statistic={{
              title: '平均处理天数',
              value: stats?.avg_resolution_days ?? '-',
              suffix: stats?.avg_resolution_days != null ? '天' : '',
            }}
          />
        </Col>
      </Row>

      {/* 类型分布 */}
      {stats?.by_type && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <Text strong>类型分布：</Text>
            {Object.entries(stats.by_type).map(([type, count]) => {
              const cfg = orderTypeMap[type];
              return (
                <Tag key={type} color={cfg?.color ?? 'default'}>
                  {cfg?.text ?? type}: {count}
                </Tag>
              );
            })}
          </Space>
        </Card>
      )}

      {/* ━━━━ Section 2: 工单列表 ━━━━ */}
      <ProTable<DRIWorkOrder>
        actionRef={actionRef}
        headerTitle="DRI工单列表"
        rowKey="id"
        columns={columns}
        scroll={{ x: 1200 }}
        search={{ labelWidth: 'auto', defaultCollapsed: false }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateVisible(true)}
          >
            新建工单
          </Button>,
        ]}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.order_type) query.set('order_type', params.order_type);
          if (params.severity) query.set('severity', params.severity);
          if (params.keyword) query.set('keyword', params.keyword);
          if (params.status) {
            // 支持多选
            const statusVal = Array.isArray(params.status) ? params.status.join(',') : params.status;
            query.set('status', statusVal);
          }
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));

          try {
            const resp = await txFetchData<PagedResult>(
              `/api/v1/dri-workorders?${query.toString()}`,
            );
            return {
              data: resp.data?.items ?? [],
              total: resp.data?.total ?? 0,
              success: true,
            };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
      />

      {/* ━━━━ Section 3: 新建工单 ModalForm ━━━━ */}
      <ModalForm
        title="新建DRI工单"
        open={createVisible}
        onOpenChange={setCreateVisible}
        onFinish={handleCreate}
        modalProps={{ destroyOnClose: true }}
        width={600}
      >
        <ProFormSelect
          name="order_type"
          label="工单类型"
          rules={[{ required: true, message: '请选择工单类型' }]}
          options={Object.entries(orderTypeMap).map(([value, { text }]) => ({
            label: text,
            value,
          }))}
        />
        <ProFormSelect
          name="severity"
          label="严重程度"
          rules={[{ required: true, message: '请选择严重程度' }]}
          options={Object.entries(severityMap).map(([value, { text }]) => ({
            label: text,
            value,
          }))}
        />
        <ProFormSelect
          name="store_id"
          label="关联门店"
          rules={[{ required: true, message: '请选择门店' }]}
          request={async () => {
            try {
              const resp = await txFetchData<{ id: string; name: string }[]>('/api/v1/stores?size=200');
              const items = (resp.data as unknown as { items?: { id: string; name: string }[] })?.items ?? resp.data ?? [];
              return (Array.isArray(items) ? items : []).map((s) => ({
                label: s.name,
                value: s.id,
              }));
            } catch {
              return [];
            }
          }}
          showSearch
          fieldProps={{ placeholder: '搜索门店名称' }}
        />
        <ProFormSelect
          name="dri_user_id"
          label="DRI负责人"
          request={async () => {
            try {
              const resp = await txFetchData<{ id: string; name: string }[]>('/api/v1/employees?size=200');
              const items = (resp.data as unknown as { items?: { id: string; name: string }[] })?.items ?? resp.data ?? [];
              return (Array.isArray(items) ? items : []).map((e) => ({
                label: e.name,
                value: e.id,
              }));
            } catch {
              return [];
            }
          }}
          showSearch
          fieldProps={{ placeholder: '搜索员工姓名' }}
        />
        <ProFormText
          name="title"
          label="工单标题"
          rules={[{ required: true, message: '请输入标题' }]}
          fieldProps={{ maxLength: 100 }}
        />
        <ProFormTextArea
          name="description"
          label="工单描述"
          fieldProps={{ rows: 4, maxLength: 2000 }}
        />
        <ProFormDatePicker
          name="due_date"
          label="截止日期"
          width="md"
        />
      </ModalForm>

      {/* ━━━━ Section 4: 工单详情 Drawer ━━━━ */}
      <Drawer
        title="工单详情"
        open={drawerVisible}
        onClose={() => {
          setDrawerVisible(false);
          setCurrentOrder(null);
          setActionFormVisible(false);
        }}
        width={640}
        loading={detailLoading}
        footer={
          currentOrder && VALID_TRANSITIONS[currentOrder.status]?.length ? (
            <Space>
              {VALID_TRANSITIONS[currentOrder.status].map((target) => (
                <Button
                  key={target}
                  type={target === 'completed' || target === 'closed' ? 'primary' : 'default'}
                  danger={target === 'cancelled' || target === 'draft'}
                  onClick={() => handleTransition(target)}
                >
                  {transitionLabel[target] ?? target}
                </Button>
              ))}
            </Space>
          ) : null
        }
      >
        {currentOrder && (
          <>
            {/* 顶部信息 */}
            <Space wrap style={{ marginBottom: 16 }}>
              <Text strong copyable>{currentOrder.order_no}</Text>
              <Badge
                status={statusMap[currentOrder.status]?.status ?? 'default'}
                text={statusMap[currentOrder.status]?.text ?? currentOrder.status}
              />
              <Tag color={severityMap[currentOrder.severity]?.color ?? 'default'}>
                {severityMap[currentOrder.severity]?.text ?? currentOrder.severity}
              </Tag>
              <Tag color={orderTypeMap[currentOrder.order_type]?.color ?? 'default'}>
                {orderTypeMap[currentOrder.order_type]?.text ?? currentOrder.order_type}
              </Tag>
            </Space>

            {/* 基本信息 */}
            <Descriptions
              column={2}
              size="small"
              bordered
              style={{ marginBottom: 16 }}
            >
              <Descriptions.Item label="门店">{currentOrder.store_name ?? currentOrder.store_id}</Descriptions.Item>
              <Descriptions.Item label="DRI负责人">{currentOrder.dri_user_name ?? currentOrder.dri_user_id ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="来源">
                {{ manual: '手动创建', ai_alert: 'AI预警', system: '系统生成' }[currentOrder.source] ?? currentOrder.source}
              </Descriptions.Item>
              <Descriptions.Item label="截止日期">
                {currentOrder.due_date ? (
                  <Text type={isOverdue(currentOrder) ? 'danger' : undefined}>
                    {dayjs(currentOrder.due_date).format('YYYY-MM-DD')}
                    {isOverdue(currentOrder) && ' (已逾期)'}
                  </Text>
                ) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">{dayjs(currentOrder.created_at).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
              <Descriptions.Item label="更新时间">{dayjs(currentOrder.updated_at).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
              {currentOrder.completed_at && (
                <Descriptions.Item label="完成时间" span={2}>
                  {dayjs(currentOrder.completed_at).format('YYYY-MM-DD HH:mm')}
                </Descriptions.Item>
              )}
            </Descriptions>

            {/* 描述 */}
            {currentOrder.description && (
              <Card size="small" title="工单描述" style={{ marginBottom: 16 }}>
                <Text style={{ whiteSpace: 'pre-wrap' }}>{currentOrder.description}</Text>
              </Card>
            )}

            {/* 行动项 */}
            <Card
              size="small"
              title="行动项"
              style={{ marginBottom: 16 }}
              extra={
                !['completed', 'closed', 'cancelled'].includes(currentOrder.status) && (
                  <Button
                    type="link"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => setActionFormVisible(true)}
                  >
                    添加行动项
                  </Button>
                )
              }
            >
              {currentOrder.actions.length > 0 ? (
                <Timeline>
                  {currentOrder.actions.map((item, index) => (
                    <Timeline.Item
                      key={index}
                      color={item.status === 'done' ? 'green' : 'blue'}
                    >
                      <div style={{ marginBottom: 4 }}>
                        <Text strong>{item.action}</Text>
                        <Tag
                          color={item.status === 'done' ? 'success' : 'processing'}
                          style={{ marginLeft: 8 }}
                        >
                          {item.status === 'done' ? '已完成' : '待处理'}
                        </Tag>
                      </div>
                      <div style={{ fontSize: 12, color: '#999' }}>
                        <Space split={<span>|</span>}>
                          <span>负责人: {item.assigned_to}</span>
                          <span>截止: {dayjs(item.due_date).format('YYYY-MM-DD')}</span>
                          {item.completed_at && (
                            <span>完成: {dayjs(item.completed_at).format('YYYY-MM-DD HH:mm')}</span>
                          )}
                        </Space>
                      </div>
                      {item.result && (
                        <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
                          结果: {item.result}
                        </div>
                      )}
                      {item.status !== 'done' && !['completed', 'closed', 'cancelled'].includes(currentOrder.status) && (
                        <Button
                          type="link"
                          size="small"
                          style={{ padding: 0, marginTop: 4 }}
                          onClick={() => handleCompleteAction(index)}
                        >
                          标记完成
                        </Button>
                      )}
                    </Timeline.Item>
                  ))}
                </Timeline>
              ) : (
                <Text type="secondary">暂无行动项</Text>
              )}

              {/* 添加行动项 inline form */}
              {actionFormVisible && (
                <Card size="small" style={{ marginTop: 12, background: '#fafafa' }}>
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Input
                      placeholder="行动项内容"
                      value={newAction.action}
                      onChange={(e) => setNewAction((prev) => ({ ...prev, action: e.target.value }))}
                    />
                    <Input
                      placeholder="负责人"
                      value={newAction.assigned_to}
                      onChange={(e) => setNewAction((prev) => ({ ...prev, assigned_to: e.target.value }))}
                    />
                    <Input
                      type="date"
                      placeholder="截止日期"
                      value={newAction.due_date}
                      onChange={(e) => setNewAction((prev) => ({ ...prev, due_date: e.target.value }))}
                    />
                    <Space>
                      <Button type="primary" size="small" onClick={handleAddAction}>
                        确认添加
                      </Button>
                      <Button
                        size="small"
                        onClick={() => {
                          setActionFormVisible(false);
                          setNewAction({ action: '', assigned_to: '', due_date: '' });
                        }}
                      >
                        取消
                      </Button>
                    </Space>
                  </Space>
                </Card>
              )}
            </Card>

            {/* 处理结果 */}
            {currentOrder.resolution && (
              <Card size="small" title="处理结果" style={{ marginBottom: 16 }}>
                <Text style={{ whiteSpace: 'pre-wrap' }}>{currentOrder.resolution}</Text>
              </Card>
            )}
          </>
        )}
      </Drawer>

      {/* ━━━━ 流转确认 Modal (完成/取消需要输入) ━━━━ */}
      <Modal
        title={
          <Space>
            <ExclamationCircleOutlined style={{ color: '#faad14' }} />
            <span>确认{transitionLabel[transitionModal.targetStatus] ?? '流转'}</span>
          </Space>
        }
        open={transitionModal.visible}
        onOk={confirmTransition}
        onCancel={() => setTransitionModal((prev) => ({ ...prev, visible: false }))}
        okText="确认"
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginBottom: 8 }}>
          <Text>{transitionModal.inputLabel}（必填）：</Text>
        </div>
        <Input.TextArea
          rows={4}
          placeholder={`请输入${transitionModal.inputLabel}`}
          value={transitionInput}
          onChange={(e) => setTransitionInput(e.target.value)}
          maxLength={2000}
          showCount
        />
      </Modal>
    </div>
  );
}
