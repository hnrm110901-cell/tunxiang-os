/**
 * OnboardingPathPage -- 新员工训练路径管理
 * 域F . 组织人事 . 训练路径
 *
 * 功能：
 *   1. 训练总览仪表板（5个指标卡片）
 *   2. ProTable 训练路径列表（筛选/推进/完成/终止）
 *   3. ModalForm 创建训练路径
 *   4. Drawer 路径详情（任务Timeline + 操作按钮）
 *   5. 推进训练日（Popconfirm）
 *   6. 终止训练（Modal + notes）
 *
 * API: tx-org :8012
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Button,
  Col,
  Descriptions,
  Drawer,
  Input,
  message,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Space,
  Tag,
  Timeline,
} from 'antd';
import { PlusOutlined, CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { txFetch } from '../../api/client';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface OnboardingPath {
  id: string;
  employee_id: string;
  store_id: string;
  template_name: string;
  start_date: string;
  target_days: number;
  current_day: number;
  tasks: TaskItem[];
  progress_pct: number;
  mentor_id: string | null;
  readiness_score: number;
  status: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface TaskItem {
  day: number;
  task: string;
  type: string;
  required: boolean;
  completed: boolean;
  completed_at?: string;
}

interface DashboardData {
  total: number;
  in_progress: number;
  completed: number;
  overdue: number;
  terminated: number;
  avg_completion_days: number;
  by_store: { store_id: string; count: number }[];
  by_target_days: { target_days: number; count: number }[];
}

interface ListResult {
  items: OnboardingPath[];
  total: number;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  枚举
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const statusEnum: Record<string, { text: string; color: string }> = {
  in_progress: { text: '训练中', color: 'processing' },
  completed: { text: '已完成', color: 'success' },
  overdue: { text: '已逾期', color: 'error' },
  terminated: { text: '已终止', color: 'default' },
};

const targetDaysOptions = [
  { label: '7天', value: 7 },
  { label: '14天', value: 14 },
  { label: '30天', value: 30 },
];

const targetDaysColor: Record<number, string> = {
  7: 'green',
  14: 'blue',
  30: 'orange',
};

const taskTypeColor: Record<string, string> = {
  theory: 'blue',
  practice: 'green',
  exam: 'orange',
};

const taskTypeText: Record<string, string> = {
  theory: '理论',
  practice: '实操',
  exam: '考核',
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function OnboardingPathPage() {
  const tableRef = useRef<ActionType>();

  // ── 仪表板 ──
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);

  const fetchDashboard = useCallback(async () => {
    try {
      const data = await txFetch<DashboardData>('/api/v1/onboarding-paths/dashboard');
      setDashboard(data);
    } catch {
      message.error('加载仪表板失败');
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  // ── 详情 Drawer ──
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detail, setDetail] = useState<OnboardingPath | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const openDetail = async (id: string) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const data = await txFetch<OnboardingPath>(`/api/v1/onboarding-paths/${id}`);
      setDetail(data);
    } catch {
      message.error('加载详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const refreshDetail = async () => {
    if (!detail) return;
    try {
      const data = await txFetch<OnboardingPath>(`/api/v1/onboarding-paths/${detail.id}`);
      setDetail(data);
    } catch {
      message.error('刷新详情失败');
    }
  };

  const closeDrawerAndReload = () => {
    setDrawerOpen(false);
    setDetail(null);
    tableRef.current?.reload();
    fetchDashboard();
  };

  // ── 完成单个任务 ──
  const handleCompleteTask = async (pathId: string, taskIdx: number) => {
    try {
      await txFetch(`/api/v1/onboarding-paths/${pathId}/task/${taskIdx}`, { method: 'PUT' });
      message.success('任务已完成');
      await refreshDetail();
    } catch {
      message.error('完成任务失败');
    }
  };

  // ── 推进训练日 ──
  const handleAdvanceDay = async (id: string) => {
    try {
      await txFetch(`/api/v1/onboarding-paths/${id}/advance-day`, { method: 'PUT' });
      message.success('已推进到下一天');
      closeDrawerAndReload();
    } catch {
      message.error('推进失败');
    }
  };

  // ── 完成训练 ──
  const handleComplete = async (id: string) => {
    try {
      await txFetch(`/api/v1/onboarding-paths/${id}/complete`, { method: 'PUT' });
      message.success('训练已完成');
      closeDrawerAndReload();
    } catch {
      message.error('完成训练失败');
    }
  };

  // ── 终止训练 ──
  const [terminateId, setTerminateId] = useState<string | null>(null);
  const [terminateNotes, setTerminateNotes] = useState('');

  const handleTerminate = async () => {
    if (!terminateId || !terminateNotes.trim()) {
      message.warning('请填写终止原因');
      return;
    }
    try {
      await txFetch(`/api/v1/onboarding-paths/${terminateId}/terminate`, {
        method: 'PUT',
        body: JSON.stringify({ notes: terminateNotes }),
      });
      message.success('训练已终止');
      setTerminateId(null);
      setTerminateNotes('');
      closeDrawerAndReload();
    } catch {
      message.error('终止训练失败');
    }
  };

  // ── 表格列 ──
  const columns: ProColumns<OnboardingPath>[] = [
    {
      title: '员工ID',
      dataIndex: 'employee_id',
      ellipsis: true,
      width: 120,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      ellipsis: true,
      width: 120,
    },
    {
      title: '路径模板',
      dataIndex: 'template_name',
      hideInSearch: true,
      width: 140,
    },
    {
      title: '训练周期',
      dataIndex: 'target_days',
      valueType: 'select',
      fieldProps: { options: targetDaysOptions },
      width: 100,
      render: (_: unknown, record: OnboardingPath) => (
        <Tag color={targetDaysColor[record.target_days] ?? 'default'}>
          {record.target_days}天
        </Tag>
      ),
    },
    {
      title: '进度天数',
      dataIndex: 'current_day',
      hideInSearch: true,
      width: 100,
      render: (_: unknown, record: OnboardingPath) => (
        <span>{record.current_day}/{record.target_days}</span>
      ),
    },
    {
      title: '完成率',
      dataIndex: 'progress_pct',
      hideInSearch: true,
      width: 160,
      render: (_: unknown, record: OnboardingPath) => (
        <Progress percent={record.progress_pct} size="small" />
      ),
    },
    {
      title: '上岗准备度',
      dataIndex: 'readiness_score',
      hideInSearch: true,
      width: 100,
      render: (_: unknown, record: OnboardingPath) => (
        <span>{record.readiness_score}/10</span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: {
        in_progress: { text: '训练中', status: 'Processing' },
        completed: { text: '已完成', status: 'Success' },
        overdue: { text: '已逾期', status: 'Error' },
        terminated: { text: '已终止', status: 'Default' },
      },
      width: 100,
      render: (_: unknown, record: OnboardingPath) => {
        const s = statusEnum[record.status];
        return <Tag color={s?.color ?? 'default'}>{s?.text ?? record.status}</Tag>;
      },
    },
    {
      title: '带教师傅',
      dataIndex: 'mentor_id',
      hideInSearch: true,
      ellipsis: true,
      width: 120,
      render: (_: unknown, record: OnboardingPath) => record.mentor_id || '-',
    },
    {
      title: '操作',
      valueType: 'option',
      width: 220,
      render: (_: unknown, record: OnboardingPath) => {
        const isActive = record.status === 'in_progress';
        const canTerminate = record.status === 'in_progress' || record.status === 'overdue';
        return (
          <Space size={4}>
            <a key="detail" onClick={() => openDetail(record.id)}>详情</a>
            {isActive && (
              <Popconfirm
                title={`确认推进到第${record.current_day + 1}天？`}
                onConfirm={() => handleAdvanceDay(record.id)}
              >
                <a key="advance">推进</a>
              </Popconfirm>
            )}
            {isActive && (
              <Popconfirm title="确认完成训练？" onConfirm={() => handleComplete(record.id)}>
                <a key="complete">完成</a>
              </Popconfirm>
            )}
            {canTerminate && (
              <a key="terminate" style={{ color: '#A32D2D' }} onClick={() => setTerminateId(record.id)}>
                终止
              </a>
            )}
          </Space>
        );
      },
    },
  ];

  // ── 渲染 ──
  return (
    <div style={{ padding: 24 }}>
      {/* Section 1: 仪表板 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <StatisticCard
            statistic={{
              title: '训练中',
              value: dashboard?.in_progress ?? 0,
              valueStyle: { color: '#185FA5' },
            }}
          />
        </Col>
        <Col span={4}>
          <StatisticCard
            statistic={{
              title: '已完成',
              value: dashboard?.completed ?? 0,
              valueStyle: { color: '#0F6E56' },
            }}
          />
        </Col>
        <Col span={4}>
          <StatisticCard
            statistic={{
              title: '已逾期',
              value: dashboard?.overdue ?? 0,
              valueStyle: { color: '#A32D2D' },
            }}
          />
        </Col>
        <Col span={4}>
          <StatisticCard
            statistic={{
              title: '已终止',
              value: dashboard?.terminated ?? 0,
              valueStyle: { color: '#999' },
            }}
          />
        </Col>
        <Col span={4}>
          <StatisticCard
            statistic={{
              title: '平均完成天数',
              value: dashboard?.avg_completion_days ?? 0,
              suffix: '天',
            }}
          />
        </Col>
      </Row>

      {/* Section 2 & 3: ProTable + 创建按钮 */}
      <ProTable<OnboardingPath>
        actionRef={tableRef}
        columns={columns}
        rowKey="id"
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        request={async (params) => {
          const { current = 1, pageSize = 20, status, store_id, target_days } = params;
          let filters = '';
          if (status) filters += `&status=${status}`;
          if (store_id) filters += `&store_id=${store_id}`;
          if (target_days) filters += `&target_days=${target_days}`;
          try {
            const res = await txFetch<ListResult>(
              `/api/v1/onboarding-paths?page=${current}&size=${pageSize}${filters}`,
            );
            return { data: res.items, total: res.total, success: true };
          } catch {
            message.error('加载列表失败');
            return { data: [], total: 0, success: false };
          }
        }}
        toolBarRender={() => [
          <ModalForm<{
            employee_id: string;
            store_id: string;
            template_name?: string;
            target_days: number;
            start_date: string;
            mentor_id?: string;
          }>
            key="create"
            title="创建训练路径"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                创建训练路径
              </Button>
            }
            autoFocusFirstInput
            modalProps={{ destroyOnClose: true }}
            onFinish={async (values) => {
              try {
                await txFetch('/api/v1/onboarding-paths', {
                  method: 'POST',
                  body: JSON.stringify(values),
                });
                message.success('创建成功');
                tableRef.current?.reload();
                fetchDashboard();
                return true;
              } catch {
                message.error('创建失败');
                return false;
              }
            }}
          >
            <ProFormText
              name="employee_id"
              label="员工ID"
              rules={[{ required: true, message: '请输入员工ID' }]}
            />
            <ProFormText
              name="store_id"
              label="门店ID"
              rules={[{ required: true, message: '请输入门店ID' }]}
            />
            <ProFormText name="template_name" label="路径模板" />
            <ProFormSelect
              name="target_days"
              label="训练周期"
              options={targetDaysOptions}
              rules={[{ required: true, message: '请选择训练周期' }]}
            />
            <ProFormDatePicker
              name="start_date"
              label="开始日期"
              rules={[{ required: true, message: '请选择开始日期' }]}
            />
            <ProFormText name="mentor_id" label="带教师傅ID" />
          </ModalForm>,
        ]}
      />

      {/* Section 4: 详情 Drawer */}
      <Drawer
        title="训练路径详情"
        width={640}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setDetail(null); }}
        loading={detailLoading}
        footer={
          detail && (detail.status === 'in_progress' || detail.status === 'overdue') ? (
            <Space>
              {detail.status === 'in_progress' && (
                <Popconfirm
                  title={`确认推进到第${detail.current_day + 1}天？`}
                  onConfirm={() => handleAdvanceDay(detail.id)}
                >
                  <Button>推进训练日</Button>
                </Popconfirm>
              )}
              {detail.status === 'in_progress' && (
                <Popconfirm title="确认完成训练？" onConfirm={() => handleComplete(detail.id)}>
                  <Button type="primary">完成训练</Button>
                </Popconfirm>
              )}
              <Button danger onClick={() => setTerminateId(detail.id)}>
                终止训练
              </Button>
            </Space>
          ) : null
        }
      >
        {detail && (
          <>
            <Descriptions column={2} bordered size="small" style={{ marginBottom: 24 }}>
              <Descriptions.Item label="员工ID">{detail.employee_id}</Descriptions.Item>
              <Descriptions.Item label="门店">{detail.store_id}</Descriptions.Item>
              <Descriptions.Item label="路径模板">{detail.template_name}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusEnum[detail.status]?.color ?? 'default'}>
                  {statusEnum[detail.status]?.text ?? detail.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="进度">
                {detail.current_day}/{detail.target_days}天
                （<Progress percent={detail.progress_pct} size="small" style={{ width: 100, display: 'inline-flex' }} />）
              </Descriptions.Item>
              <Descriptions.Item label="上岗准备度">{detail.readiness_score}/10</Descriptions.Item>
              <Descriptions.Item label="带教师傅">{detail.mentor_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="开始日期">{detail.start_date}</Descriptions.Item>
            </Descriptions>

            <h4 style={{ marginBottom: 12 }}>任务列表</h4>
            <Timeline
              items={detail.tasks.map((t, idx) => ({
                key: idx,
                color: t.completed ? 'green' : 'gray',
                dot: t.completed ? <CheckCircleOutlined /> : <ClockCircleOutlined />,
                children: (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Tag>Day {t.day}</Tag>
                    <span>{t.task}</span>
                    <Tag color={taskTypeColor[t.type] ?? 'default'}>
                      {taskTypeText[t.type] ?? t.type}
                    </Tag>
                    {t.completed && t.completed_at && (
                      <span style={{ color: '#999', fontSize: 12 }}>{t.completed_at}</span>
                    )}
                    {!t.completed && (
                      <Popconfirm
                        title={`完成任务「${t.task}」？`}
                        onConfirm={() => handleCompleteTask(detail.id, idx)}
                      >
                        <Button size="small" type="link">完成</Button>
                      </Popconfirm>
                    )}
                  </div>
                ),
              }))}
            />
          </>
        )}
      </Drawer>

      {/* Section 6: 终止训练 Modal */}
      <Modal
        title="终止训练"
        open={!!terminateId}
        onOk={handleTerminate}
        onCancel={() => { setTerminateId(null); setTerminateNotes(''); }}
        okText="确认终止"
        okButtonProps={{ danger: true, disabled: !terminateNotes.trim() }}
      >
        <p>请填写终止原因：</p>
        <Input.TextArea
          rows={4}
          value={terminateNotes}
          onChange={(e) => setTerminateNotes(e.target.value)}
          placeholder="终止原因（必填）"
        />
      </Modal>
    </div>
  );
}
