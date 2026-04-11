/**
 * 带教与训练督导页 — MentorshipSupervisePage
 * 域: HR . 带教管理
 *
 * Section 1: 统计仪表板 (4个 StatisticCard)
 * Section 2: 带教排行榜 TOP10
 * Section 3: 带教关系列表 (ProTable + 筛选)
 * Section 4: 新建带教关系 (ModalForm)
 * Section 5: 完成带教 (Modal)
 * Section 6: 终止带教 (Modal)
 *
 * API: GET/POST/PUT/DELETE /api/v1/mentorships
 */

import { useEffect, useRef, useState } from 'react';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDatePicker,
  ProFormText,
  ProFormTextArea,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Button,
  Card,
  Col,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Row,
  Space,
  Table,
  Tag,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { txFetch } from '../../api/client';
import dayjs from 'dayjs';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型定义
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface Mentorship {
  id: string;
  mentor_id: string;
  mentee_id: string;
  store_id: string;
  status: string;
  start_date: string;
  end_date: string | null;
  mentor_score: number | null;
  mentee_pass_rate: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface StatisticsData {
  active_count: number;
  completed_count: number;
  avg_mentor_score: number | null;
  avg_mentee_pass_rate: number | null;
}

interface LeaderboardItem {
  mentor_id: string;
  completed_count: number;
  avg_score: number | null;
  avg_pass_rate: number | null;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  状态映射
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const statusColorMap: Record<string, string> = {
  active: 'green',
  completed: 'blue',
  terminated: 'red',
};

const statusTextMap: Record<string, string> = {
  active: '进行中',
  completed: '已完成',
  terminated: '已终止',
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function MentorshipSupervisePage() {
  const actionRef = useRef<ActionType>();
  const [stats, setStats] = useState<StatisticsData | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [leaderboard, setLeaderboard] = useState<LeaderboardItem[]>([]);
  const [leaderboardLoading, setLeaderboardLoading] = useState(false);
  const [createVisible, setCreateVisible] = useState(false);

  // 完成带教 Modal
  const [completeModal, setCompleteModal] = useState<{ visible: boolean; id: string }>({
    visible: false,
    id: '',
  });
  const [completeForm, setCompleteForm] = useState<{
    mentor_score: number | null;
    mentee_pass_rate: number | null;
    notes: string;
  }>({ mentor_score: null, mentee_pass_rate: null, notes: '' });

  // 终止带教 Modal
  const [terminateModal, setTerminateModal] = useState<{ visible: boolean; id: string }>({
    visible: false,
    id: '',
  });
  const [terminateNotes, setTerminateNotes] = useState('');

  // ━━━━ 加载统计数据 ━━━━
  const loadStats = async () => {
    setStatsLoading(true);
    try {
      const resp = await txFetch<StatisticsData>('/api/v1/mentorships/statistics');
      setStats(resp.data);
    } catch (err) {
      console.error('Failed to load statistics', err);
    } finally {
      setStatsLoading(false);
    }
  };

  // ━━━━ 加载排行榜 ━━━━
  const loadLeaderboard = async () => {
    setLeaderboardLoading(true);
    try {
      const resp = await txFetch<LeaderboardItem[]>('/api/v1/mentorships/leaderboard?top=10');
      setLeaderboard(resp.data ?? []);
    } catch (err) {
      console.error('Failed to load leaderboard', err);
    } finally {
      setLeaderboardLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
    loadLeaderboard();
  }, []);

  // ━━━━ 创建带教关系 ━━━━
  const handleCreate = async (values: Record<string, unknown>) => {
    try {
      await txFetch('/api/v1/mentorships', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('带教关系创建成功');
      setCreateVisible(false);
      actionRef.current?.reload();
      loadStats();
      loadLeaderboard();
      return true;
    } catch (err) {
      message.error('创建失败');
      console.error(err);
      return false;
    }
  };

  // ━━━━ 完成带教 ━━━━
  const handleComplete = async () => {
    try {
      await txFetch(`/api/v1/mentorships/${completeModal.id}/complete`, {
        method: 'PUT',
        body: JSON.stringify({
          mentor_score: completeForm.mentor_score,
          mentee_pass_rate: completeForm.mentee_pass_rate,
          notes: completeForm.notes || undefined,
        }),
      });
      message.success('带教已完成');
      setCompleteModal({ visible: false, id: '' });
      setCompleteForm({ mentor_score: null, mentee_pass_rate: null, notes: '' });
      actionRef.current?.reload();
      loadStats();
      loadLeaderboard();
    } catch (err) {
      message.error('操作失败');
      console.error(err);
    }
  };

  // ━━━━ 终止带教 ━━━━
  const handleTerminate = async () => {
    if (!terminateNotes.trim()) {
      message.warning('请填写终止原因');
      return;
    }
    try {
      await txFetch(`/api/v1/mentorships/${terminateModal.id}/terminate`, {
        method: 'PUT',
        body: JSON.stringify({ notes: terminateNotes.trim() }),
      });
      message.success('带教已终止');
      setTerminateModal({ visible: false, id: '' });
      setTerminateNotes('');
      actionRef.current?.reload();
      loadStats();
      loadLeaderboard();
    } catch (err) {
      message.error('操作失败');
      console.error(err);
    }
  };

  // ━━━━ 删除带教关系 ━━━━
  const handleDelete = async (id: string) => {
    try {
      await txFetch(`/api/v1/mentorships/${id}`, { method: 'DELETE' });
      message.success('带教关系已删除');
      actionRef.current?.reload();
      loadStats();
      loadLeaderboard();
    } catch (err) {
      message.error('删除失败');
      console.error(err);
    }
  };

  // ━━━━ 排行榜列定义 ━━━━
  const leaderboardColumns = [
    {
      title: '排名',
      key: 'rank',
      width: 60,
      render: (_: unknown, __: unknown, index: number) => index + 1,
    },
    {
      title: '师傅姓名',
      dataIndex: 'mentor_id',
      ellipsis: true,
      render: (val: string) => val?.slice(0, 8) ?? '-',
    },
    {
      title: '完成带教数',
      dataIndex: 'completed_count',
      width: 100,
    },
    {
      title: '平均评分',
      dataIndex: 'avg_score',
      width: 100,
      render: (val: number | null) => (val != null ? val.toFixed(1) : '-'),
    },
    {
      title: '平均通关率',
      dataIndex: 'avg_pass_rate',
      width: 100,
      render: (val: number | null) => (val != null ? `${val}%` : '-'),
    },
  ];

  // ━━━━ ProTable 列定义 ━━━━
  const columns: ProColumns<Mentorship>[] = [
    {
      title: '师傅ID',
      dataIndex: 'mentor_id',
      ellipsis: true,
      search: false,
    },
    {
      title: '学员ID',
      dataIndex: 'mentee_id',
      ellipsis: true,
      search: false,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: {
        active: { text: '进行中' },
        completed: { text: '已完成' },
        terminated: { text: '已终止' },
      },
      render: (_, record) => (
        <Tag color={statusColorMap[record.status] ?? 'default'}>
          {statusTextMap[record.status] ?? record.status}
        </Tag>
      ),
    },
    {
      title: '开始日期',
      dataIndex: 'start_date',
      search: false,
      width: 110,
      render: (_, record) => dayjs(record.start_date).format('YYYY-MM-DD'),
    },
    {
      title: '结束日期',
      dataIndex: 'end_date',
      search: false,
      width: 110,
      render: (_, record) => (record.end_date ? dayjs(record.end_date).format('YYYY-MM-DD') : '进行中'),
    },
    {
      title: '带教评分',
      dataIndex: 'mentor_score',
      search: false,
      width: 90,
      render: (_, record) => (record.mentor_score != null ? record.mentor_score : '-'),
    },
    {
      title: '学员通关率',
      dataIndex: 'mentee_pass_rate',
      search: false,
      width: 100,
      render: (_, record) => (record.mentee_pass_rate != null ? `${record.mentee_pass_rate}%` : '-'),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, record) => (
        <Space size="small">
          <a onClick={() => message.info(`详情: ${record.id}`)}>详情</a>
          {record.status === 'active' && (
            <>
              <a
                onClick={() => {
                  setCompleteModal({ visible: true, id: record.id });
                  setCompleteForm({ mentor_score: null, mentee_pass_rate: null, notes: '' });
                }}
              >
                完成
              </a>
              <a
                onClick={() => {
                  setTerminateModal({ visible: true, id: record.id });
                  setTerminateNotes('');
                }}
              >
                终止
              </a>
              <Popconfirm title="确认删除此带教关系？" onConfirm={() => handleDelete(record.id)}>
                <a style={{ color: '#ff4d4f' }}>删除</a>
              </Popconfirm>
            </>
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
              title: '活跃带教关系数',
              value: stats?.active_count ?? 0,
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={statsLoading}
            statistic={{
              title: '已完成带教数',
              value: stats?.completed_count ?? 0,
              valueStyle: { color: '#52c41a' },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={statsLoading}
            statistic={{
              title: '平均带教评分',
              value: stats?.avg_mentor_score != null ? stats.avg_mentor_score.toFixed(1) : '-',
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            loading={statsLoading}
            statistic={{
              title: '平均学员通关率',
              value: stats?.avg_mentee_pass_rate != null ? stats.avg_mentee_pass_rate : '-',
              suffix: stats?.avg_mentee_pass_rate != null ? '%' : '',
            }}
          />
        </Col>
      </Row>

      {/* ━━━━ Section 2: 带教排行榜 ━━━━ */}
      <Card title="带教排行榜TOP10" style={{ marginBottom: 16 }} size="small">
        <Table
          dataSource={leaderboard}
          columns={leaderboardColumns}
          loading={leaderboardLoading}
          rowKey="mentor_id"
          pagination={false}
          size="small"
        />
      </Card>

      {/* ━━━━ Section 3: 带教关系列表 ━━━━ */}
      <ProTable<Mentorship>
        actionRef={actionRef}
        headerTitle="带教关系列表"
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 'auto', defaultCollapsed: false }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateVisible(true)}
          >
            新增带教
          </Button>,
        ]}
        request={async (params) => {
          const { current, pageSize, status, store_id } = params;
          try {
            const res = await txFetch<{ items: Mentorship[]; total: number }>(
              `/api/v1/mentorships?page=${current}&size=${pageSize}${status ? '&status=' + status : ''}${store_id ? '&store_id=' + store_id : ''}`,
            );
            return {
              data: res.data?.items || [],
              total: res.data?.total || 0,
              success: true,
            };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
      />

      {/* ━━━━ Section 4: 新建带教关系 ModalForm ━━━━ */}
      <ModalForm
        title="新建带教关系"
        open={createVisible}
        onOpenChange={setCreateVisible}
        onFinish={handleCreate}
        modalProps={{ destroyOnClose: true }}
        width={520}
      >
        <ProFormText
          name="mentor_id"
          label="师傅ID"
          rules={[{ required: true, message: '请输入师傅ID' }]}
        />
        <ProFormText
          name="mentee_id"
          label="学员ID"
          rules={[{ required: true, message: '请输入学员ID' }]}
        />
        <ProFormText
          name="store_id"
          label="门店ID"
          rules={[{ required: true, message: '请输入门店ID' }]}
        />
        <ProFormDatePicker
          name="start_date"
          label="开始日期"
          rules={[{ required: true, message: '请选择开始日期' }]}
          width="md"
        />
        <ProFormTextArea
          name="notes"
          label="备注"
          fieldProps={{ rows: 3, maxLength: 500 }}
        />
      </ModalForm>

      {/* ━━━━ Section 5: 完成带教 Modal ━━━━ */}
      <Modal
        title="完成带教"
        open={completeModal.visible}
        onOk={handleComplete}
        onCancel={() => setCompleteModal({ visible: false, id: '' })}
        okText="确认完成"
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8 }}>带教评分（0-10）：</div>
          <InputNumber
            min={0}
            max={10}
            step={0.1}
            style={{ width: '100%' }}
            value={completeForm.mentor_score}
            onChange={(val) => setCompleteForm((prev) => ({ ...prev, mentor_score: val }))}
            placeholder="请输入评分"
          />
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8 }}>学员通关率（0-100%）：</div>
          <InputNumber
            min={0}
            max={100}
            step={0.01}
            style={{ width: '100%' }}
            value={completeForm.mentee_pass_rate}
            onChange={(val) => setCompleteForm((prev) => ({ ...prev, mentee_pass_rate: val }))}
            placeholder="请输入通关率"
            addonAfter="%"
          />
        </div>
        <div>
          <div style={{ marginBottom: 8 }}>备注：</div>
          <Input.TextArea
            rows={3}
            value={completeForm.notes}
            onChange={(e) => setCompleteForm((prev) => ({ ...prev, notes: e.target.value }))}
            placeholder="请输入备注"
            maxLength={500}
            showCount
          />
        </div>
      </Modal>

      {/* ━━━━ Section 6: 终止带教 Modal ━━━━ */}
      <Modal
        title="终止带教"
        open={terminateModal.visible}
        onOk={handleTerminate}
        onCancel={() => setTerminateModal({ visible: false, id: '' })}
        okText="确认终止"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginBottom: 8 }}>终止原因（必填）：</div>
        <Input.TextArea
          rows={4}
          value={terminateNotes}
          onChange={(e) => setTerminateNotes(e.target.value)}
          placeholder="请输入终止原因"
          maxLength={500}
          showCount
        />
      </Modal>
    </div>
  );
}
