/**
 * ReviewCyclesPage -- 评审周期管理
 * 域F tx-org | v254 review_cycles
 *
 * 功能：
 *  - ProTable 展示评审周期列表（名称/类型/时间范围/状态/已评人数）
 *  - ModalForm 创建评审周期（名称+类型+时间+维度配置）
 *  - 状态流转按钮（draft->scoring->calibrating->completed）
 *
 * API:
 *   GET  /api/v1/org/performance/review-cycles
 *   POST /api/v1/org/performance/review-cycles
 *   GET  /api/v1/org/performance/review-cycles/:id
 *   PUT  /api/v1/org/performance/review-cycles/:id/status
 */

import { useRef, useState } from 'react';
import { Button, Tag, Typography, message, Space, Popconfirm, Card } from 'antd';
import { PlusOutlined, ArrowRightOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDateRangePicker,
  ProFormSelect,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────

interface ReviewCycle {
  id: string;
  cycle_name: string;
  cycle_type: string;
  start_date: string;
  end_date: string;
  scoring_deadline: string | null;
  status: string;
  scope_type: string;
  scored_employees?: number;
  total_scores?: number;
  created_at: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const STATUS_TAG: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '草稿' },
  scoring: { color: 'processing', label: '打分中' },
  calibrating: { color: 'warning', label: '校准中' },
  completed: { color: 'success', label: '已完成' },
  archived: { color: '', label: '已归档' },
};

const CYCLE_TYPE_MAP: Record<string, string> = {
  monthly: '月度',
  quarterly: '季度',
  semi_annual: '半年度',
  annual: '年度',
};

const STATUS_NEXT: Record<string, { next: string; label: string }> = {
  draft: { next: 'scoring', label: '开始打分' },
  scoring: { next: 'calibrating', label: '进入校准' },
  calibrating: { next: 'completed', label: '完成评审' },
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function ReviewCyclesPage() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [transitioning, setTransitioning] = useState<string | null>(null);

  const handleStatusTransition = async (cycleId: string, newStatus: string) => {
    setTransitioning(cycleId);
    try {
      await txFetchData(`/api/v1/org/performance/review-cycles/${cycleId}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: newStatus }),
      });
      messageApi.success('状态更新成功');
      actionRef.current?.reload();
    } catch {
      messageApi.error('状态更新失败');
    } finally {
      setTransitioning(null);
    }
  };

  const columns: ProColumns<ReviewCycle>[] = [
    { title: '周期名称', dataIndex: 'cycle_name', width: 200 },
    {
      title: '类型',
      dataIndex: 'cycle_type',
      width: 100,
      valueEnum: {
        monthly: { text: '月度' },
        quarterly: { text: '季度' },
        semi_annual: { text: '半年度' },
        annual: { text: '年度' },
      },
      render: (_, r) => CYCLE_TYPE_MAP[r.cycle_type] || r.cycle_type,
    },
    {
      title: '时间范围',
      width: 200,
      hideInSearch: true,
      render: (_, r) => `${r.start_date} ~ ${r.end_date}`,
    },
    {
      title: '打分截止',
      dataIndex: 'scoring_deadline',
      width: 120,
      hideInSearch: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueEnum: {
        draft: { text: '草稿' },
        scoring: { text: '打分中' },
        calibrating: { text: '校准中' },
        completed: { text: '已完成' },
        archived: { text: '已归档' },
      },
      render: (_, r) => {
        const t = STATUS_TAG[r.status] || { color: 'default', label: r.status };
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    { title: '创建时间', dataIndex: 'created_at', width: 170, hideInSearch: true, valueType: 'dateTime' },
    {
      title: '操作',
      width: 200,
      hideInSearch: true,
      render: (_, r) => {
        const transition = STATUS_NEXT[r.status];
        return (
          <Space>
            <a href={`#/hr/performance/online-scoring?cycle_id=${r.id}`}>打分</a>
            <a href={`#/hr/performance/review-summary?cycle_id=${r.id}`}>汇总</a>
            {transition && (
              <Popconfirm
                title={`确认${transition.label}？`}
                onConfirm={() => handleStatusTransition(r.id, transition.next)}
              >
                <Button
                  type="link"
                  size="small"
                  loading={transitioning === r.id}
                  icon={<ArrowRightOutlined />}
                >
                  {transition.label}
                </Button>
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>评审周期管理</Title>

      <ProTable<ReviewCycle>
        headerTitle="评审周期"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="创建评审周期"
            trigger={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
              >
                新建周期
              </Button>
            }
            onFinish={async (values: Record<string, unknown>) => {
              try {
                const dateRange = values.dateRange as [string, string];
                const payload = {
                  cycle_name: values.cycle_name,
                  cycle_type: values.cycle_type,
                  start_date: dateRange[0],
                  end_date: dateRange[1],
                  scoring_deadline: values.scoring_deadline || null,
                  dimensions: [
                    { name: '服务质量', weight: 25, max_score: 100 },
                    { name: '销售业绩', weight: 25, max_score: 100 },
                    { name: '出勤纪律', weight: 20, max_score: 100 },
                    { name: '技能成长', weight: 15, max_score: 100 },
                    { name: '团队协作', weight: 15, max_score: 100 },
                  ],
                };
                await txFetchData('/api/v1/org/performance/review-cycles', {
                  method: 'POST',
                  body: JSON.stringify(payload),
                });
                messageApi.success('评审周期创建成功');
                actionRef.current?.reload();
                return true;
              } catch {
                messageApi.error('创建失败');
                return false;
              }
            }}
            modalProps={{ destroyOnClose: true }}
          >
            <ProFormText
              name="cycle_name"
              label="周期名称"
              placeholder="例如：2026年Q2绩效评审"
              rules={[{ required: true, message: '请输入周期名称' }]}
            />
            <ProFormSelect
              name="cycle_type"
              label="周期类型"
              rules={[{ required: true, message: '请选择周期类型' }]}
              options={[
                { label: '月度', value: 'monthly' },
                { label: '季度', value: 'quarterly' },
                { label: '半年度', value: 'semi_annual' },
                { label: '年度', value: 'annual' },
              ]}
            />
            <ProFormDateRangePicker
              name="dateRange"
              label="评审时间范围"
              rules={[{ required: true, message: '请选择时间范围' }]}
            />
          </ModalForm>,
        ]}
        request={async (params) => {
          try {
            const query = new URLSearchParams();
            if (params.current) query.set('page', String(params.current));
            if (params.pageSize) query.set('size', String(params.pageSize));
            if (params.status) query.set('status', params.status);
            const res = (await txFetchData(
              `/api/v1/org/performance/review-cycles?${query.toString()}`
            )) as { items: ReviewCycle[]; total: number };
            return { data: res.items, total: res.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ defaultPageSize: 20 }}
      />
    </div>
  );
}
