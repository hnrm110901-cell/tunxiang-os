/**
 * PeakGuardPage — 高峰保障指挥页
 *
 * 功能：
 *  1. 高峰保障总览仪表板 (5张统计卡片)
 *  2. 覆盖度预警 (Alert + 迷你Table)
 *  3. 未来7天高峰排期 (Timeline)
 *  4. 高峰记录列表 (ProTable + 筛选)
 *  5. 新建高峰记录 (ModalForm)
 *  6. 详情Drawer (Descriptions + 缺岗Table + 行动Timeline + 追加行动 + 事后评估)
 *  7. 事后评估Modal
 *
 * API:
 *  GET  /api/v1/peak-guard/dashboard
 *  GET  /api/v1/peak-guard/alerts
 *  GET  /api/v1/peak-guard/upcoming
 *  GET  /api/v1/peak-guard?page=X&size=Y&...
 *  POST /api/v1/peak-guard
 *  POST /api/v1/peak-guard/{id}/actions
 *  PUT  /api/v1/peak-guard/{id}/evaluate
 */

import { useEffect, useRef, useState } from 'react';
import {
  ModalForm,
  ProFormDatePicker,
  ProFormDigit,
  ProFormList,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Progress,
  Row,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../api/client';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface RiskPosition {
  position: string;
  required: number;
  actual: number;
  gap: number;
}

interface ActionTaken {
  action: string;
  executor: string;
  result: string;
  timestamp: string;
}

interface PeakGuardRecord {
  id: string;
  store_id: string;
  guard_date: string;
  peak_type: string;
  expected_traffic: number;
  coverage_score: number;
  risk_positions: RiskPosition[];
  actions_taken: ActionTaken[];
  result_score: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface DashboardData {
  today_count: number;
  week_count: number;
  avg_coverage: number;
  low_coverage_count: number;
  low_coverage_stores: PeakGuardRecord[];
  by_peak_type: { peak_type: string; count: number }[];
  avg_result_score: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const PEAK_TYPE_LABEL: Record<string, string> = {
  lunch: '午高峰',
  dinner: '晚高峰',
  weekend: '周末',
  holiday: '节假日',
  event: '活动',
};

const PEAK_TYPE_COLOR: Record<string, string> = {
  lunch: 'blue',
  dinner: 'orange',
  weekend: 'purple',
  holiday: 'red',
  event: 'cyan',
};

const PEAK_TYPE_OPTIONS = Object.entries(PEAK_TYPE_LABEL).map(([value, label]) => ({
  value,
  label,
}));

function coverageColor(score: number): string {
  if (score < 60) return '#A32D2D';
  if (score < 80) return '#BA7517';
  return '#0F6E56';
}

function coverageStatus(score: number): 'exception' | 'normal' | 'success' {
  if (score < 60) return 'exception';
  if (score < 80) return 'normal';
  return 'success';
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function PeakGuardPage() {
  const tableRef = useRef<ActionType>();

  // Dashboard
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashLoading, setDashLoading] = useState(false);

  // Alerts
  const [alerts, setAlerts] = useState<PeakGuardRecord[]>([]);

  // Upcoming
  const [upcoming, setUpcoming] = useState<PeakGuardRecord[]>([]);

  // Detail drawer
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailRecord, setDetailRecord] = useState<PeakGuardRecord | null>(null);
  const [actionForm] = Form.useForm();
  const [actionSubmitting, setActionSubmitting] = useState(false);

  // Evaluate modal
  const [evalVisible, setEvalVisible] = useState(false);
  const [evalRecord, setEvalRecord] = useState<PeakGuardRecord | null>(null);
  const [evalScore, setEvalScore] = useState<number | null>(null);
  const [evalNotes, setEvalNotes] = useState('');
  const [evalSubmitting, setEvalSubmitting] = useState(false);
  const [evalResult, setEvalResult] = useState<{ effectiveness: number } | null>(null);

  // ─── 数据加载 ───────────────────────────────────────────────────────────

  const loadDashboard = async () => {
    setDashLoading(true);
    try {
      const res = await txFetchData<DashboardData>('/api/v1/peak-guard/dashboard');
      if (res) setDashboard(res);
    } catch {
      message.error('加载仪表板失败');
    } finally {
      setDashLoading(false);
    }
  };

  const loadAlerts = async () => {
    try {
      const res = await txFetchData<{ items: PeakGuardRecord[] }>('/api/v1/peak-guard/alerts');
      if (res) setAlerts(res.items);
    } catch {
      /* silent */
    }
  };

  const loadUpcoming = async () => {
    try {
      const res = await txFetchData<{ items: PeakGuardRecord[] }>('/api/v1/peak-guard/upcoming');
      if (res) setUpcoming(res.items);
    } catch {
      /* silent */
    }
  };

  useEffect(() => {
    loadDashboard();
    loadAlerts();
    loadUpcoming();
  }, []);

  const refreshAll = () => {
    loadDashboard();
    loadAlerts();
    loadUpcoming();
    tableRef.current?.reload();
  };

  // ─── 详情加载 ───────────────────────────────────────────────────────────

  const openDetail = async (record: PeakGuardRecord) => {
    try {
      const res = await txFetchData<PeakGuardRecord>(`/api/v1/peak-guard/${record.id}`);
      setDetailRecord(res ?? record);
    } catch {
      setDetailRecord(record);
    }
    setDetailVisible(true);
  };

  const handleAddAction = async () => {
    if (!detailRecord) return;
    try {
      const values = await actionForm.validateFields();
      setActionSubmitting(true);
      await txFetchData(`/api/v1/peak-guard/${detailRecord.id}/actions`, {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('行动已追加');
      actionForm.resetFields();
      // 刷新详情
      const res = await txFetchData<PeakGuardRecord>(`/api/v1/peak-guard/${detailRecord.id}`);
      if (res) setDetailRecord(res);
      refreshAll();
    } catch {
      message.error('追加行动失败');
    } finally {
      setActionSubmitting(false);
    }
  };

  // ─── 事后评估 ───────────────────────────────────────────────────────────

  const openEval = (record: PeakGuardRecord) => {
    setEvalRecord(record);
    setEvalScore(null);
    setEvalNotes('');
    setEvalResult(null);
    setEvalVisible(true);
  };

  const handleEvaluate = async () => {
    if (!evalRecord || evalScore === null) return;
    setEvalSubmitting(true);
    try {
      const res = await txFetchData<{ effectiveness: number }>(
        `/api/v1/peak-guard/${evalRecord.id}/evaluate`,
        {
          method: 'PUT',
          body: JSON.stringify({ result_score: evalScore, notes: evalNotes }),
        },
      );
      message.success('评估完成');
      if (res) setEvalResult(res);
      refreshAll();
      // 刷新详情（如果打开中）
      if (detailRecord?.id === evalRecord.id) {
        const detailRes = await txFetchData<PeakGuardRecord>(`/api/v1/peak-guard/${evalRecord.id}`);
        if (detailRes) setDetailRecord(detailRes);
      }
    } catch {
      message.error('评估提交失败');
    } finally {
      setEvalSubmitting(false);
    }
  };

  // ─── 删除 ──────────────────────────────────────────────────────────────

  const handleDelete = (record: PeakGuardRecord) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定删除 ${record.store_id} ${record.guard_date} 的高峰记录？`,
      okText: '删除',
      okType: 'danger',
      onOk: async () => {
        try {
          await txFetchData(`/api/v1/peak-guard/${record.id}`, { method: 'DELETE' });
          message.success('已删除');
          refreshAll();
        } catch {
          message.error('删除失败');
        }
      },
    });
  };

  // ─── Section 1: 仪表板 ─────────────────────────────────────────────────

  const renderDashboard = () => (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      <Col span={4} xs={12} sm={8} md={4}>
        <StatisticCard
          loading={dashLoading}
          statistic={{ title: '今日高峰数', value: dashboard?.today_count ?? 0 }}
        />
      </Col>
      <Col span={5} xs={12} sm={8} md={5}>
        <StatisticCard
          loading={dashLoading}
          statistic={{ title: '本周高峰数', value: dashboard?.week_count ?? 0 }}
        />
      </Col>
      <Col span={5} xs={12} sm={8} md={5}>
        <StatisticCard
          loading={dashLoading}
          statistic={{
            title: '平均覆盖度',
            value: dashboard?.avg_coverage?.toFixed(1) ?? '0.0',
            suffix: '%',
          }}
        />
      </Col>
      <Col span={5} xs={12} sm={8} md={5}>
        <StatisticCard
          loading={dashLoading}
          statistic={{
            title: '覆盖不足门店',
            value: dashboard?.low_coverage_count ?? 0,
            valueStyle: { color: '#A32D2D' },
          }}
        />
      </Col>
      <Col span={5} xs={12} sm={8} md={5}>
        <StatisticCard
          loading={dashLoading}
          statistic={{
            title: '平均保障评分',
            value: dashboard?.avg_result_score?.toFixed(1) ?? '0.0',
          }}
        />
      </Col>
    </Row>
  );

  // ─── Section 2: 覆盖度预警 ─────────────────────────────────────────────

  const alertColumns = [
    { title: '门店', dataIndex: 'store_id', key: 'store_id' },
    { title: '日期', dataIndex: 'guard_date', key: 'guard_date' },
    {
      title: '高峰类型',
      dataIndex: 'peak_type',
      key: 'peak_type',
      render: (v: string) => (
        <Tag color={PEAK_TYPE_COLOR[v]}>{PEAK_TYPE_LABEL[v] ?? v}</Tag>
      ),
    },
    {
      title: '覆盖度',
      dataIndex: 'coverage_score',
      key: 'coverage_score',
      render: (v: number) => (
        <Text style={{ color: coverageColor(v) }}>{v.toFixed(1)}%</Text>
      ),
    },
    {
      title: '缺岗详情',
      dataIndex: 'risk_positions',
      key: 'risk_positions',
      render: (positions: RiskPosition[]) =>
        positions?.map((p) => `${p.position}(缺${p.gap})`).join('、') || '-',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: PeakGuardRecord) => (
        <Button type="link" size="small" onClick={() => openDetail(record)}>
          查看详情
        </Button>
      ),
    },
  ];

  const renderAlerts = () => {
    if (!alerts.length) return null;
    return (
      <div style={{ marginBottom: 24 }}>
        <Alert
          type="error"
          message="人力覆盖度不足预警"
          icon={<WarningOutlined />}
          showIcon
          style={{ marginBottom: 12 }}
        />
        <Table
          dataSource={alerts.slice(0, 5)}
          columns={alertColumns}
          rowKey="id"
          size="small"
          pagination={false}
        />
      </div>
    );
  };

  // ─── Section 3: 即将到来的高峰 ─────────────────────────────────────────

  const renderUpcoming = () => {
    if (!upcoming.length) return null;

    // 按日期分组
    const byDate = upcoming.reduce<Record<string, PeakGuardRecord[]>>((acc, r) => {
      const d = r.guard_date;
      if (!acc[d]) acc[d] = [];
      acc[d].push(r);
      return acc;
    }, {});

    const sortedDates = Object.keys(byDate).sort();

    return (
      <Card title="未来7天高峰排期" style={{ marginBottom: 24 }}>
        <Timeline>
          {sortedDates.map((date) => (
            <Timeline.Item key={date}>
              <Text strong>{dayjs(date).format('MM-DD (ddd)')}</Text>
              {byDate[date].map((r) => (
                <div
                  key={r.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    marginTop: 8,
                    flexWrap: 'wrap',
                  }}
                >
                  <Text>{r.store_id}</Text>
                  <Tag color={PEAK_TYPE_COLOR[r.peak_type]}>
                    {PEAK_TYPE_LABEL[r.peak_type] ?? r.peak_type}
                  </Tag>
                  <Text type="secondary">预计客流: {r.expected_traffic}</Text>
                  <Progress
                    percent={r.coverage_score}
                    size="small"
                    style={{ width: 120 }}
                    strokeColor={coverageColor(r.coverage_score)}
                    status={coverageStatus(r.coverage_score)}
                    format={(p) => `${p?.toFixed(0)}%`}
                  />
                </div>
              ))}
            </Timeline.Item>
          ))}
        </Timeline>
      </Card>
    );
  };

  // ─── Section 4: 高峰记录列表 ───────────────────────────────────────────

  const columns: ProColumns<PeakGuardRecord>[] = [
    {
      title: '门店',
      dataIndex: 'store_id',
      valueType: 'text',
      ellipsis: true,
    },
    {
      title: '日期',
      dataIndex: 'guard_date',
      valueType: 'date',
    },
    {
      title: '高峰类型',
      dataIndex: 'peak_type',
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(PEAK_TYPE_LABEL).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, r) => (
        <Tag color={PEAK_TYPE_COLOR[r.peak_type]}>
          {PEAK_TYPE_LABEL[r.peak_type] ?? r.peak_type}
        </Tag>
      ),
    },
    {
      title: '预计客流',
      dataIndex: 'expected_traffic',
      hideInSearch: true,
    },
    {
      title: '覆盖度',
      dataIndex: 'coverage_score',
      hideInSearch: true,
      render: (_, r) => (
        <Progress
          percent={r.coverage_score}
          size="small"
          strokeColor={coverageColor(r.coverage_score)}
          status={coverageStatus(r.coverage_score)}
          format={(p) => `${p?.toFixed(1)}%`}
        />
      ),
    },
    {
      title: '实际评分',
      dataIndex: 'result_score',
      hideInSearch: true,
      render: (_, r) =>
        r.result_score !== null && r.result_score !== undefined ? r.result_score : (
          <Text type="secondary">待评</Text>
        ),
    },
    {
      title: '缺岗数',
      dataIndex: 'risk_positions',
      hideInSearch: true,
      render: (_, r) => r.risk_positions?.length ?? 0,
    },
    {
      title: '已执行行动',
      dataIndex: 'actions_taken',
      hideInSearch: true,
      render: (_, r) => r.actions_taken?.length ?? 0,
    },
    {
      title: '覆盖度低于',
      dataIndex: 'coverage_below',
      hideInTable: true,
      renderFormItem: () => <InputNumber placeholder="如: 80" min={0} max={100} style={{ width: '100%' }} />,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, r) => [
        <Button
          key="detail"
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => openDetail(r)}
        >
          详情
        </Button>,
        r.result_score === null || r.result_score === undefined ? (
          <Button
            key="eval"
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEval(r)}
          >
            评估
          </Button>
        ) : null,
        <Button
          key="delete"
          type="link"
          size="small"
          danger
          icon={<DeleteOutlined />}
          onClick={() => handleDelete(r)}
        >
          删除
        </Button>,
      ],
    },
  ];

  // ─── Section 5: 新建高峰记录 ModalForm ─────────────────────────────────

  const renderCreateForm = () => (
    <ModalForm
      title="新增高峰保障"
      trigger={
        <Button type="primary" icon={<PlusOutlined />}>
          新增高峰保障
        </Button>
      }
      autoFocusFirstInput
      modalProps={{ destroyOnClose: true }}
      onFinish={async (values: Record<string, unknown>) => {
        try {
          await txFetchData('/api/v1/peak-guard', {
            method: 'POST',
            body: JSON.stringify(values),
          });
          message.success('创建成功');
          refreshAll();
          return true;
        } catch {
          message.error('创建失败');
          return false;
        }
      }}
    >
      <ProFormText name="store_id" label="门店" rules={[{ required: true, message: '请输入门店' }]} />
      <ProFormDatePicker
        name="guard_date"
        label="日期"
        rules={[{ required: true, message: '请选择日期' }]}
        fieldProps={{ style: { width: '100%' } }}
      />
      <ProFormSelect
        name="peak_type"
        label="高峰类型"
        options={PEAK_TYPE_OPTIONS}
        rules={[{ required: true, message: '请选择高峰类型' }]}
      />
      <ProFormDigit name="expected_traffic" label="预计客流" min={0} />
      <ProFormList
        name="risk_positions"
        label="缺岗详情"
        creatorButtonProps={{ creatorButtonText: '添加岗位' }}
      >
        <Space align="baseline" style={{ display: 'flex' }}>
          <ProFormText name="position" label="岗位" rules={[{ required: true }]} />
          <ProFormDigit name="required" label="需求人数" min={0} rules={[{ required: true }]} />
          <ProFormDigit name="actual" label="实际人数" min={0} rules={[{ required: true }]} />
        </Space>
      </ProFormList>
      <ProFormTextArea name="notes" label="备注" />
    </ModalForm>
  );

  // ─── Section 6: 详情 Drawer ─────────────────────────────────────────────

  const renderDetailDrawer = () => {
    if (!detailRecord) return null;
    const r = detailRecord;

    return (
      <Drawer
        title="高峰保障详情"
        width={640}
        open={detailVisible}
        onClose={() => setDetailVisible(false)}
      >
        {/* 基本信息 */}
        <Descriptions bordered size="small" column={2} style={{ marginBottom: 24 }}>
          <Descriptions.Item label="门店">{r.store_id}</Descriptions.Item>
          <Descriptions.Item label="日期">{r.guard_date}</Descriptions.Item>
          <Descriptions.Item label="高峰类型">
            <Tag color={PEAK_TYPE_COLOR[r.peak_type]}>
              {PEAK_TYPE_LABEL[r.peak_type] ?? r.peak_type}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="预计客流">{r.expected_traffic}</Descriptions.Item>
          <Descriptions.Item label="覆盖度">
            <Text style={{ color: coverageColor(r.coverage_score) }}>
              {r.coverage_score.toFixed(1)}%
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="实际评分">
            {r.result_score !== null && r.result_score !== undefined
              ? r.result_score
              : '待评'}
          </Descriptions.Item>
        </Descriptions>

        {/* 缺岗详情 */}
        <Title level={5}>缺岗详情</Title>
        <Table
          dataSource={r.risk_positions ?? []}
          rowKey="position"
          size="small"
          pagination={false}
          style={{ marginBottom: 24 }}
          columns={[
            { title: '岗位', dataIndex: 'position' },
            { title: '需求', dataIndex: 'required' },
            { title: '实际', dataIndex: 'actual' },
            {
              title: '缺口',
              dataIndex: 'gap',
              render: (v: number) => (
                <Text style={{ color: v > 0 ? '#A32D2D' : undefined }}>
                  {v > 0 ? `-${v}` : v}
                </Text>
              ),
            },
          ]}
        />

        {/* 保障行动 */}
        <Title level={5}>保障行动</Title>
        {r.actions_taken?.length ? (
          <Timeline style={{ marginBottom: 24 }}>
            {r.actions_taken.map((a, i) => (
              <Timeline.Item key={i}>
                <div>
                  <Text strong>{a.action}</Text>
                </div>
                <div>
                  <Text type="secondary">执行人: {a.executor}</Text>
                  {a.result && (
                    <Text type="secondary" style={{ marginLeft: 12 }}>
                      结果: {a.result}
                    </Text>
                  )}
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {dayjs(a.timestamp).format('YYYY-MM-DD HH:mm')}
                  </Text>
                </div>
              </Timeline.Item>
            ))}
          </Timeline>
        ) : (
          <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
            暂无行动记录
          </Text>
        )}

        {/* 追加行动表单 */}
        <Card title="追加行动" size="small" style={{ marginBottom: 24 }}>
          <Form form={actionForm} layout="inline" style={{ flexWrap: 'wrap', gap: 8 }}>
            <Form.Item name="action" rules={[{ required: true, message: '请输入行动' }]}>
              <Input placeholder="行动内容" />
            </Form.Item>
            <Form.Item name="executor" rules={[{ required: true, message: '请输入执行人' }]}>
              <Input placeholder="执行人" />
            </Form.Item>
            <Form.Item name="result">
              <Input placeholder="结果(可选)" />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                loading={actionSubmitting}
                onClick={handleAddAction}
              >
                提交
              </Button>
            </Form.Item>
          </Form>
        </Card>

        {/* 事后评估按钮 */}
        {(r.result_score === null || r.result_score === undefined) && (
          <Button type="primary" block onClick={() => openEval(r)}>
            事后评估
          </Button>
        )}
      </Drawer>
    );
  };

  // ─── Section 7: 事后评估 Modal ─────────────────────────────────────────

  const renderEvalModal = () => (
    <Modal
      title="事后评估"
      open={evalVisible}
      onCancel={() => setEvalVisible(false)}
      onOk={handleEvaluate}
      confirmLoading={evalSubmitting}
      okText="提交评估"
      destroyOnClose
    >
      <div style={{ marginBottom: 16 }}>
        <Text>评分 (0-100)</Text>
        <InputNumber
          min={0}
          max={100}
          value={evalScore}
          onChange={(v) => setEvalScore(v)}
          style={{ width: '100%', marginTop: 8 }}
          placeholder="请输入实际评分"
        />
      </div>
      <div style={{ marginBottom: 16 }}>
        <Text>备注</Text>
        <Input.TextArea
          value={evalNotes}
          onChange={(e) => setEvalNotes(e.target.value)}
          rows={3}
          placeholder="评估备注"
          style={{ marginTop: 8 }}
        />
      </div>
      {evalResult && (
        <div style={{ marginTop: 16 }}>
          <Text>
            保障效果:{' '}
            <Text
              strong
              style={{ color: evalResult.effectiveness >= 0 ? '#0F6E56' : '#A32D2D' }}
            >
              {evalResult.effectiveness >= 0 ? '超预期' : '低于预期'}
              {' '}({evalResult.effectiveness > 0 ? '+' : ''}
              {evalResult.effectiveness})
            </Text>
          </Text>
        </div>
      )}
    </Modal>
  );

  // ─── 渲染 ──────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>
          高峰保障指挥
        </Title>
        <Button icon={<ReloadOutlined />} onClick={refreshAll}>
          刷新
        </Button>
      </div>

      {/* Section 1: 仪表板 */}
      {renderDashboard()}

      {/* Section 2: 预警 */}
      {renderAlerts()}

      {/* Section 3: 即将到来 */}
      {renderUpcoming()}

      {/* Section 4: 高峰记录列表 */}
      <ProTable<PeakGuardRecord>
        actionRef={tableRef}
        columns={columns}
        rowKey="id"
        headerTitle="高峰保障记录"
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [renderCreateForm()]}
        request={async (params) => {
          const { current, pageSize, store_id, peak_type, guard_date, coverage_below, ...rest } =
            params;
          const query = new URLSearchParams();
          query.set('page', String(current ?? 1));
          query.set('size', String(pageSize ?? 20));
          if (store_id) query.set('store_id', store_id);
          if (peak_type) query.set('peak_type', peak_type);
          if (guard_date) query.set('guard_date', guard_date);
          if (coverage_below !== undefined && coverage_below !== null)
            query.set('coverage_below', String(coverage_below));

          try {
            const res = await txFetchData<{ items: PeakGuardRecord[]; total: number }>(
              `/api/v1/peak-guard?${query.toString()}`,
            );
            return {
              data: res?.items ?? [],
              total: res?.total ?? 0,
              success: true,
            };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
      />

      {/* Section 6: 详情 Drawer */}
      {renderDetailDrawer()}

      {/* Section 7: 评估 Modal */}
      {renderEvalModal()}
    </div>
  );
}
