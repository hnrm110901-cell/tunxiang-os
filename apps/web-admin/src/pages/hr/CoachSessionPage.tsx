/**
 * 店长教练Agent — CoachSessionPage
 * 域: HR . 教练会话
 *
 * Section 1: 教练总览仪表板 (5个 StatisticCard)
 * Section 2: 教练有效性分析 (Table)
 * Section 3: 教练会话列表 (ProTable + 筛选)
 * Section 4: 新建教练会话 (ModalForm)
 * Section 5: 会话详情 (Drawer)
 *
 * API: GET/POST/PUT /api/v1/coach-sessions
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
  ProFormDigit,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Space,
  Table,
  Tag,
  Timeline,
} from 'antd';
import { PlusOutlined, CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { txFetchData } from '../../api/client';
import dayjs from 'dayjs';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型定义
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface Suggestion {
  category: string;
  content: string;
  priority: string;
  accepted: boolean;
}

interface ActionTaken {
  action: string;
  result: string | null;
  completed_at: string | null;
}

interface FocusEmployee {
  employee_id: string;
  reason: string;
  action: string;
}

interface CoachSession {
  id: string;
  store_id: string;
  manager_id: string;
  session_date: string;
  session_type: string;
  suggestions: Suggestion[];
  actions_taken: ActionTaken[];
  focus_employees: FocusEmployee[];
  readiness_before: number | null;
  readiness_after: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface DashboardData {
  this_week_count: number;
  this_month_count: number;
  acceptance_rate: number;
  avg_readiness_lift: number;
  top_managers: { manager_id: string; count: number }[];
}

interface EffectivenessItem {
  session_type: string;
  count: number;
  avg_readiness_lift: number;
  lift_rate: number;
}

interface EffectivenessData {
  items: EffectivenessItem[];
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  映射
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const sessionTypeTextMap: Record<string, string> = {
  daily: '日常',
  weekly: '周会',
  monthly: '月度',
  incident: '事件',
};

const sessionTypeColorMap: Record<string, string> = {
  daily: 'blue',
  weekly: 'green',
  monthly: 'purple',
  incident: 'red',
};

const priorityColorMap: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'default',
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function CoachSessionPage() {
  const actionRef = useRef<ActionType>();

  // Dashboard
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashLoading, setDashLoading] = useState(false);

  // Effectiveness
  const [effectiveness, setEffectiveness] = useState<EffectivenessItem[]>([]);
  const [effLoading, setEffLoading] = useState(false);

  // Create modal
  const [createVisible, setCreateVisible] = useState(false);

  // Detail drawer
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [currentSession, setCurrentSession] = useState<CoachSession | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 完成行动 Modal
  const [completeActionModal, setCompleteActionModal] = useState<{
    visible: boolean;
    sessionId: string;
    actionIdx: number;
  }>({ visible: false, sessionId: '', actionIdx: -1 });
  const [completeResult, setCompleteResult] = useState('');

  // 更新就绪度 Modal
  const [readinessModal, setReadinessModal] = useState<{
    visible: boolean;
    sessionId: string;
  }>({ visible: false, sessionId: '' });
  const [readinessAfter, setReadinessAfter] = useState<number | null>(null);

  // 追加行动
  const [newAction, setNewAction] = useState('');

  // ━━━━ 加载仪表板 ━━━━
  const loadDashboard = async () => {
    setDashLoading(true);
    try {
      const resp = await txFetchData<DashboardData>('/api/v1/coach-sessions/dashboard');
      setDashboard(resp.data);
    } catch (err) {
      console.error('Failed to load dashboard', err);
    } finally {
      setDashLoading(false);
    }
  };

  // ━━━━ 加载有效性分析 ━━━━
  const loadEffectiveness = async () => {
    setEffLoading(true);
    try {
      const resp = await txFetchData<EffectivenessData>('/api/v1/coach-sessions/effectiveness');
      setEffectiveness(resp.data?.items ?? []);
    } catch (err) {
      console.error('Failed to load effectiveness', err);
    } finally {
      setEffLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
    loadEffectiveness();
  }, []);

  // ━━━━ 创建教练会话 ━━━━
  const handleCreate = async (values: Record<string, unknown>) => {
    try {
      await txFetchData('/api/v1/coach-sessions', {
        method: 'POST',
        body: JSON.stringify({
          ...values,
          session_date: values.session_date
            ? dayjs(values.session_date as string).format('YYYY-MM-DD')
            : dayjs().format('YYYY-MM-DD'),
        }),
      });
      message.success('教练会话创建成功');
      setCreateVisible(false);
      actionRef.current?.reload();
      loadDashboard();
      loadEffectiveness();
      return true;
    } catch (err) {
      message.error('创建失败');
      return false;
    }
  };

  // ━━━━ 删除教练会话 ━━━━
  const handleDelete = async (id: string) => {
    try {
      await txFetchData(`/api/v1/coach-sessions/${id}`, { method: 'DELETE' });
      message.success('已删除');
      actionRef.current?.reload();
      loadDashboard();
      loadEffectiveness();
    } catch (err) {
      message.error('删除失败');
    }
  };

  // ━━━━ 查看详情 ━━━━
  const openDetail = async (record: CoachSession) => {
    setDrawerVisible(true);
    setDetailLoading(true);
    try {
      const resp = await txFetchData<CoachSession>(`/api/v1/coach-sessions/${record.id}`);
      setCurrentSession(resp.data);
    } catch (err) {
      message.error('加载详情失败');
      setCurrentSession(record);
    } finally {
      setDetailLoading(false);
    }
  };

  // ━━━━ 采纳建议 ━━━━
  const handleAcceptSuggestion = async (sessionId: string, idx: number) => {
    try {
      await txFetchData(`/api/v1/coach-sessions/${sessionId}/accept/${idx}`, { method: 'PUT' });
      message.success('已采纳');
      // 刷新详情
      const resp = await txFetchData<CoachSession>(`/api/v1/coach-sessions/${sessionId}`);
      setCurrentSession(resp.data);
      actionRef.current?.reload();
      loadDashboard();
    } catch (err) {
      message.error('采纳失败');
    }
  };

  // ━━━━ 追加行动 ━━━━
  const handleAddAction = async (sessionId: string) => {
    if (!newAction.trim()) return;
    try {
      await txFetchData(`/api/v1/coach-sessions/${sessionId}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action: newAction.trim() }),
      });
      message.success('行动已追加');
      setNewAction('');
      const resp = await txFetchData<CoachSession>(`/api/v1/coach-sessions/${sessionId}`);
      setCurrentSession(resp.data);
      actionRef.current?.reload();
    } catch (err) {
      message.error('追加失败');
    }
  };

  // ━━━━ 完成行动 ━━━━
  const handleCompleteAction = async () => {
    const { sessionId, actionIdx } = completeActionModal;
    if (!completeResult.trim()) {
      message.warning('请输入执行结果');
      return;
    }
    try {
      await txFetchData(`/api/v1/coach-sessions/${sessionId}/actions/${actionIdx}/complete`, {
        method: 'PUT',
        body: JSON.stringify({ result: completeResult.trim() }),
      });
      message.success('行动已完成');
      setCompleteActionModal({ visible: false, sessionId: '', actionIdx: -1 });
      setCompleteResult('');
      const resp = await txFetchData<CoachSession>(`/api/v1/coach-sessions/${sessionId}`);
      setCurrentSession(resp.data);
      actionRef.current?.reload();
    } catch (err) {
      message.error('操作失败');
    }
  };

  // ━━━━ 更新就绪度 ━━━━
  const handleUpdateReadiness = async () => {
    const { sessionId } = readinessModal;
    if (readinessAfter === null) {
      message.warning('请输入就绪度');
      return;
    }
    try {
      await txFetchData(`/api/v1/coach-sessions/${sessionId}`, {
        method: 'PUT',
        body: JSON.stringify({ readiness_after: readinessAfter }),
      });
      message.success('就绪度已更新');
      setReadinessModal({ visible: false, sessionId: '' });
      setReadinessAfter(null);
      const resp = await txFetchData<CoachSession>(`/api/v1/coach-sessions/${sessionId}`);
      setCurrentSession(resp.data);
      actionRef.current?.reload();
      loadDashboard();
    } catch (err) {
      message.error('更新失败');
    }
  };

  // ━━━━ ProTable Columns ━━━━
  const columns: ProColumns<CoachSession>[] = [
    {
      title: '门店',
      dataIndex: 'store_id',
      ellipsis: true,
      fieldProps: { placeholder: '门店ID' },
    },
    {
      title: '店长',
      dataIndex: 'manager_id',
      ellipsis: true,
      fieldProps: { placeholder: '店长ID' },
    },
    {
      title: '日期',
      dataIndex: 'session_date',
      valueType: 'date',
      hideInSearch: true,
    },
    {
      title: '类型',
      dataIndex: 'session_type',
      valueType: 'select',
      valueEnum: {
        daily: { text: '日常' },
        weekly: { text: '周会' },
        monthly: { text: '月度' },
        incident: { text: '事件' },
      },
      render: (_, record) => (
        <Tag color={sessionTypeColorMap[record.session_type] ?? 'default'}>
          {sessionTypeTextMap[record.session_type] ?? record.session_type}
        </Tag>
      ),
    },
    {
      title: '建议',
      dataIndex: 'suggestions',
      hideInSearch: true,
      render: (_, record) => `建议${record.suggestions?.length ?? 0}条`,
    },
    {
      title: '采纳',
      hideInSearch: true,
      render: (_, record) => {
        const total = record.suggestions?.length ?? 0;
        const accepted = record.suggestions?.filter((s) => s.accepted).length ?? 0;
        return `${accepted}/${total}`;
      },
    },
    {
      title: '就绪度',
      hideInSearch: true,
      render: (_, record) => {
        const before = record.readiness_before;
        const after = record.readiness_after;
        if (before === null && after === null) return '-';
        const beforeStr = before !== null ? before.toFixed(1) : '-';
        const afterStr = after !== null ? after.toFixed(1) : '-';
        const lifted = before !== null && after !== null && after > before;
        return (
          <span>
            {beforeStr} → <span style={lifted ? { color: '#52c41a', fontWeight: 500 } : {}}>{afterStr}</span>
          </span>
        );
      },
    },
    {
      title: '已执行',
      hideInSearch: true,
      render: (_, record) => `已执行${record.actions_taken?.length ?? 0}项`,
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, record) => (
        <Space>
          <a onClick={() => openDetail(record)}>详情</a>
          <Popconfirm title="确认删除此教练会话？" onConfirm={() => handleDelete(record.id)}>
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ━━━━ 有效性分析表格列 ━━━━
  const effColumns = [
    {
      title: '会话类型',
      dataIndex: 'session_type',
      key: 'session_type',
      render: (val: string) => sessionTypeTextMap[val] ?? val,
    },
    { title: '会话数', dataIndex: 'count', key: 'count' },
    {
      title: '平均就绪提升',
      dataIndex: 'avg_readiness_lift',
      key: 'avg_readiness_lift',
      render: (val: number) => (val !== null ? val.toFixed(1) : '-'),
    },
    {
      title: '提升率',
      dataIndex: 'lift_rate',
      key: 'lift_rate',
      render: (val: number) => (val !== null ? `${(val * 100).toFixed(1)}%` : '-'),
    },
  ];

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  渲染
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* ━━━━ Section 1: 教练总览仪表板 ━━━━ */}
      <Row gutter={16}>
        <Col span={4}>
          <StatisticCard
            loading={dashLoading}
            statistic={{ title: '本周会话数', value: dashboard?.this_week_count ?? 0 }}
          />
        </Col>
        <Col span={5}>
          <StatisticCard
            loading={dashLoading}
            statistic={{ title: '本月会话数', value: dashboard?.this_month_count ?? 0 }}
          />
        </Col>
        <Col span={5}>
          <StatisticCard
            loading={dashLoading}
            statistic={{
              title: '建议采纳率',
              value: dashboard?.acceptance_rate ?? 0,
              suffix: '%',
            }}
          />
        </Col>
        <Col span={5}>
          <StatisticCard
            loading={dashLoading}
            statistic={{
              title: '平均就绪度提升',
              value:
                dashboard?.avg_readiness_lift !== undefined && dashboard?.avg_readiness_lift !== null
                  ? `${dashboard.avg_readiness_lift > 0 ? '+' : ''}${dashboard.avg_readiness_lift.toFixed(1)}`
                  : '-',
            }}
          />
        </Col>
        <Col span={5}>
          <StatisticCard
            loading={dashLoading}
            statistic={{
              title: '活跃店长数',
              value: dashboard?.top_managers?.length ?? 0,
            }}
          />
        </Col>
      </Row>

      {/* ━━━━ Section 2: 教练有效性分析 ━━━━ */}
      <Card title="教练有效性分析" size="small">
        <Table
          dataSource={effectiveness}
          columns={effColumns}
          loading={effLoading}
          rowKey="session_type"
          pagination={false}
          size="small"
        />
      </Card>

      {/* ━━━━ Section 3: 教练会话列表 ━━━━ */}
      <ProTable<CoachSession>
        headerTitle="教练会话列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 'auto' }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateVisible(true)}
          >
            新建教练会话
          </Button>,
        ]}
        request={async (params) => {
          const { current = 1, pageSize = 20, store_id, manager_id, session_type } = params;
          const query = new URLSearchParams();
          query.set('page', String(current));
          query.set('size', String(pageSize));
          if (store_id) query.set('store_id', store_id);
          if (manager_id) query.set('manager_id', manager_id);
          if (session_type) query.set('session_type', session_type);
          const resp = await txFetchData<{ items: CoachSession[]; total: number }>(
            `/api/v1/coach-sessions?${query.toString()}`
          );
          return {
            data: resp.data?.items ?? [],
            total: resp.data?.total ?? 0,
            success: true,
          };
        }}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* ━━━━ Section 4: 新建教练会话 (ModalForm) ━━━━ */}
      <ModalForm
        title="新建教练会话"
        open={createVisible}
        onOpenChange={setCreateVisible}
        onFinish={handleCreate}
        modalProps={{ destroyOnClose: true }}
      >
        <ProFormText name="store_id" label="门店ID" rules={[{ required: true, message: '请输入门店ID' }]} />
        <ProFormText name="manager_id" label="店长ID" rules={[{ required: true, message: '请输入店长ID' }]} />
        <ProFormDatePicker
          name="session_date"
          label="会话日期"
          rules={[{ required: true, message: '请选择日期' }]}
          initialValue={dayjs()}
        />
        <ProFormSelect
          name="session_type"
          label="会话类型"
          options={[
            { label: '日常', value: 'daily' },
            { label: '周会', value: 'weekly' },
            { label: '月度', value: 'monthly' },
            { label: '事件', value: 'incident' },
          ]}
          rules={[{ required: true, message: '请选择类型' }]}
        />
        <ProFormDigit
          name="readiness_before"
          label="当前就绪度"
          min={0}
          max={100}
          fieldProps={{ precision: 1 }}
        />
        <ProFormTextArea name="notes" label="备注" />
      </ModalForm>

      {/* ━━━━ Section 5: 会话详情 (Drawer) ━━━━ */}
      <Drawer
        title="教练会话详情"
        width={720}
        open={drawerVisible}
        onClose={() => {
          setDrawerVisible(false);
          setCurrentSession(null);
          setNewAction('');
        }}
        loading={detailLoading}
      >
        {currentSession && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            {/* 基本信息 */}
            <Descriptions title="基本信息" column={2} bordered size="small">
              <Descriptions.Item label="门店">{currentSession.store_id}</Descriptions.Item>
              <Descriptions.Item label="店长">{currentSession.manager_id}</Descriptions.Item>
              <Descriptions.Item label="日期">{currentSession.session_date}</Descriptions.Item>
              <Descriptions.Item label="类型">
                <Tag color={sessionTypeColorMap[currentSession.session_type]}>
                  {sessionTypeTextMap[currentSession.session_type] ?? currentSession.session_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="就绪度变化">
                {currentSession.readiness_before !== null
                  ? currentSession.readiness_before.toFixed(1)
                  : '-'}{' '}
                →{' '}
                <span style={{ color: '#52c41a', fontWeight: 500 }}>
                  {currentSession.readiness_after !== null
                    ? currentSession.readiness_after.toFixed(1)
                    : '-'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="备注">{currentSession.notes ?? '-'}</Descriptions.Item>
            </Descriptions>

            {/* AI建议列表 */}
            <Card title="AI 建议" size="small">
              {currentSession.suggestions?.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {currentSession.suggestions.map((s, idx) => (
                    <Card
                      key={idx}
                      size="small"
                      type="inner"
                      title={
                        <Space>
                          <Tag>{s.category}</Tag>
                          <Tag color={priorityColorMap[s.priority] ?? 'default'}>{s.priority}</Tag>
                        </Space>
                      }
                      extra={
                        s.accepted ? (
                          <Checkbox checked disabled>
                            已采纳
                          </Checkbox>
                        ) : (
                          <Button
                            size="small"
                            type="link"
                            onClick={() => handleAcceptSuggestion(currentSession.id, idx)}
                          >
                            采纳
                          </Button>
                        )
                      }
                    >
                      {s.content}
                    </Card>
                  ))}
                </div>
              ) : (
                <span style={{ color: '#999' }}>暂无建议</span>
              )}
            </Card>

            {/* 行动记录 */}
            <Card title="行动记录" size="small">
              {currentSession.actions_taken?.length > 0 ? (
                <Timeline
                  items={currentSession.actions_taken.map((a, idx) => ({
                    color: a.completed_at ? 'green' : 'gray',
                    dot: a.completed_at ? (
                      <CheckCircleOutlined style={{ fontSize: 16 }} />
                    ) : (
                      <ClockCircleOutlined style={{ fontSize: 16 }} />
                    ),
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>{a.action}</div>
                        {a.completed_at ? (
                          <div style={{ color: '#52c41a', fontSize: 12 }}>
                            {a.result} &middot; {dayjs(a.completed_at).format('YYYY-MM-DD HH:mm')}
                          </div>
                        ) : (
                          <Button
                            size="small"
                            type="link"
                            onClick={() => {
                              setCompleteActionModal({
                                visible: true,
                                sessionId: currentSession.id,
                                actionIdx: idx,
                              });
                              setCompleteResult('');
                            }}
                          >
                            完成
                          </Button>
                        )}
                      </div>
                    ),
                  }))}
                />
              ) : (
                <span style={{ color: '#999' }}>暂无行动记录</span>
              )}
            </Card>

            {/* 重点关注员工 */}
            {currentSession.focus_employees?.length > 0 && (
              <Card title="重点关注员工" size="small">
                <Table
                  dataSource={currentSession.focus_employees}
                  rowKey="employee_id"
                  pagination={false}
                  size="small"
                  columns={[
                    { title: '员工ID', dataIndex: 'employee_id', key: 'employee_id' },
                    { title: '关注原因', dataIndex: 'reason', key: 'reason' },
                    { title: '行动方案', dataIndex: 'action', key: 'action' },
                  ]}
                />
              </Card>
            )}

            {/* 底部操作 */}
            <Card size="small" title="追加行动">
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="输入新行动项..."
                  value={newAction}
                  onChange={(e) => setNewAction(e.target.value)}
                  onPressEnter={() => handleAddAction(currentSession.id)}
                />
                <Button type="primary" onClick={() => handleAddAction(currentSession.id)}>
                  追加
                </Button>
              </Space.Compact>
            </Card>

            <Button
              type="default"
              block
              onClick={() => {
                setReadinessModal({ visible: true, sessionId: currentSession.id });
                setReadinessAfter(currentSession.readiness_after);
              }}
            >
              更新就绪度
            </Button>
          </div>
        )}
      </Drawer>

      {/* ━━━━ 完成行动 Modal ━━━━ */}
      <Modal
        title="完成行动"
        open={completeActionModal.visible}
        onOk={handleCompleteAction}
        onCancel={() => {
          setCompleteActionModal({ visible: false, sessionId: '', actionIdx: -1 });
          setCompleteResult('');
        }}
        destroyOnClose
      >
        <Input.TextArea
          rows={3}
          placeholder="请输入执行结果..."
          value={completeResult}
          onChange={(e) => setCompleteResult(e.target.value)}
        />
      </Modal>

      {/* ━━━━ 更新就绪度 Modal ━━━━ */}
      <Modal
        title="更新就绪度"
        open={readinessModal.visible}
        onOk={handleUpdateReadiness}
        onCancel={() => {
          setReadinessModal({ visible: false, sessionId: '' });
          setReadinessAfter(null);
        }}
        destroyOnClose
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>就绪度 (0-100):</span>
          <Input
            type="number"
            min={0}
            max={100}
            step={0.1}
            style={{ width: 120 }}
            value={readinessAfter ?? ''}
            onChange={(e) => setReadinessAfter(e.target.value ? Number(e.target.value) : null)}
          />
        </div>
      </Modal>
    </div>
  );
}
