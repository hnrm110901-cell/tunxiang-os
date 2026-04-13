/**
 * 员工培训管理页 — OR-02
 * 培训记录 / 证书预警 / 培训统计
 * Admin终端 · Ant Design 5.x + ProTable
 */
import { useRef, useState, useEffect } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  InputNumber,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Tabs,
  Typography,
  Progress,
  Tooltip,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { ProTable, ProColumns, ActionType, ModalForm, ProFormText, ProFormSelect, ProFormTextArea, ProFormDigit } from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

// ── API 基础路径 ─────────────────────────────────────────────

const TENANT_ID = localStorage.getItem('tenantId') || 'default-tenant';
const BASE = '/api/v1/org/training';

const headers = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
};

// ── 类型定义 ─────────────────────────────────────────────────

interface TrainingRecord {
  id: string;
  employee_id: string;
  employee_name?: string;
  training_type: string;
  training_name: string;
  training_date: string;
  duration_hours: number;
  location?: string;
  score?: number;
  passed?: boolean;
  certificate_no?: string;
  certificate_expires_at?: string;
  cert_days_remaining?: number;
  cert_status?: 'ok' | 'warning' | 'critical' | 'expired';
  status: string;
  notes?: string;
}

interface ExpiringCert {
  record_id: string;
  employee_id: string;
  training_type: string;
  training_name: string;
  certificate_no?: string;
  certificate_expires_at: string;
  days_remaining: number;
  cert_status: string;
  risk_level: 'high' | 'medium' | 'low';
  action: string;
}

interface TrainingStats {
  month: string;
  monthly_count: number;
  pass_rate: number;
  cert_holders: number;
  expiring_30_days: number;
  by_type: Array<{ training_type: string; total: number; passed: number; pass_rate: number }>;
}

// ── 常量映射 ─────────────────────────────────────────────────

const TRAINING_TYPE_LABELS: Record<string, string> = {
  onboarding: '入职培训',
  food_safety: '食品安全',
  service: '服务礼仪',
  skills: '技能提升',
  compliance: '合规/消防',
  other: '其他',
};

const TRAINING_TYPE_COLORS: Record<string, string> = {
  onboarding: 'blue',
  food_safety: 'red',
  service: 'green',
  skills: 'purple',
  compliance: 'orange',
  other: 'default',
};

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  scheduled: { label: '待开始', color: 'default' },
  in_progress: { label: '进行中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  failed: { label: '未通过', color: 'error' },
};

// ── 证书有效期颜色工具 ────────────────────────────────────────

function getCertColor(days?: number): string {
  if (days === undefined || days === null) return 'default';
  if (days < 0) return 'red';
  if (days < 7) return 'red';
  if (days <= 30) return 'orange';
  return 'green';
}

function getCertIcon(days?: number) {
  if (days === undefined || days === null) return null;
  if (days < 7) return <WarningOutlined style={{ color: '#A32D2D' }} />;
  if (days <= 30) return <ClockCircleOutlined style={{ color: '#BA7517' }} />;
  return <CheckCircleOutlined style={{ color: '#0F6E56' }} />;
}

// ── Tab 1: 培训记录 ──────────────────────────────────────────

function TrainingRecordsTab() {
  const actionRef = useRef<ActionType>();
  const [createOpen, setCreateOpen] = useState(false);
  const [updateRecord, setUpdateRecord] = useState<TrainingRecord | null>(null);
  const [updateForm] = Form.useForm();

  const columns: ProColumns<TrainingRecord>[] = [
    {
      title: '员工姓名',
      dataIndex: 'employee_name',
      width: 100,
      render: (_, r) => r.employee_name || r.employee_id.slice(0, 8),
    },
    {
      title: '培训类型',
      dataIndex: 'training_type',
      width: 100,
      valueEnum: Object.fromEntries(
        Object.entries(TRAINING_TYPE_LABELS).map(([k, v]) => [k, { text: v }])
      ),
      render: (_, r) => (
        <Tag color={TRAINING_TYPE_COLORS[r.training_type] || 'default'}>
          {TRAINING_TYPE_LABELS[r.training_type] || r.training_type}
        </Tag>
      ),
    },
    {
      title: '培训名称',
      dataIndex: 'training_name',
      ellipsis: true,
    },
    {
      title: '培训日期',
      dataIndex: 'training_date',
      width: 110,
      valueType: 'date',
      search: false,
    },
    {
      title: '时长(h)',
      dataIndex: 'duration_hours',
      width: 80,
      search: false,
      render: (_, r) => r.duration_hours ? `${r.duration_hours}h` : '-',
    },
    {
      title: '成绩',
      dataIndex: 'score',
      width: 80,
      search: false,
      render: (_, r) => {
        if (r.score === undefined || r.score === null) return '-';
        const color = r.score >= 90 ? '#0F6E56' : r.score >= 60 ? '#BA7517' : '#A32D2D';
        return <Text strong style={{ color }}>{r.score}</Text>;
      },
    },
    {
      title: '结果',
      dataIndex: 'passed',
      width: 80,
      search: false,
      render: (_, r) => {
        if (r.passed === null || r.passed === undefined) return '-';
        return r.passed
          ? <Tag color="success">通过</Tag>
          : <Tag color="error">未通过</Tag>;
      },
    },
    {
      title: '证书编号',
      dataIndex: 'certificate_no',
      width: 130,
      search: false,
      render: (_, r) => r.certificate_no || '-',
    },
    {
      title: '证书有效期',
      dataIndex: 'certificate_expires_at',
      width: 140,
      search: false,
      render: (_, r) => {
        if (!r.certificate_expires_at) return '-';
        const days = r.cert_days_remaining;
        return (
          <Tooltip title={days !== undefined ? `剩余 ${days} 天` : ''}>
            <Space size={4}>
              {getCertIcon(days)}
              <Text style={{ color: getCertColor(days) === 'red' ? '#A32D2D' : getCertColor(days) === 'orange' ? '#BA7517' : '#0F6E56' }}>
                {r.certificate_expires_at}
              </Text>
            </Space>
          </Tooltip>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      search: false,
      render: (_, r) => {
        const s = STATUS_LABELS[r.status] || { label: r.status, color: 'default' };
        return <Badge status={s.color as any} text={s.label} />;
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 120,
      render: (_, r) => [
        <a key="update" onClick={() => {
          setUpdateRecord(r);
          updateForm.setFieldsValue({
            score: r.score,
            passed: r.passed,
            certificate_no: r.certificate_no,
            certificate_expires_at: r.certificate_expires_at
              ? dayjs(r.certificate_expires_at) : undefined,
            notes: r.notes,
          });
        }}>
          更新成绩
        </a>,
      ],
    },
  ];

  async function handleCreate(values: Record<string, any>) {
    const payload = {
      ...values,
      training_date: values.training_date?.format('YYYY-MM-DD'),
      certificate_expires_at: values.certificate_expires_at?.format('YYYY-MM-DD'),
    };
    const res = await fetch(`${BASE}/records`, {
      method: 'POST', headers, body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      message.error(data.error?.message || '创建失败');
      return false;
    }
    message.success('培训记录已新增');
    actionRef.current?.reload();
    return true;
  }

  async function handleUpdate() {
    if (!updateRecord) return;
    const values = await updateForm.validateFields();
    const payload = {
      ...values,
      certificate_expires_at: values.certificate_expires_at?.format('YYYY-MM-DD'),
    };
    const res = await fetch(`${BASE}/records/${updateRecord.id}`, {
      method: 'PUT', headers, body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      message.error(data.error?.message || '更新失败');
      return;
    }
    message.success('培训记录已更新');
    setUpdateRecord(null);
    actionRef.current?.reload();
  }

  return (
    <>
      <ProTable<TrainingRecord>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async (params) => {
          const qs = new URLSearchParams();
          if (params.training_type) qs.set('training_type', params.training_type);
          if (params.employee_id) qs.set('employee_id', params.employee_id);
          qs.set('page', String(params.current || 1));
          qs.set('size', String(params.pageSize || 20));

          const res = await fetch(`${BASE}/records?${qs}`, { headers });
          const data = await res.json();
          return {
            data: data.data?.items || [],
            total: data.data?.total || 0,
            success: data.ok,
          };
        }}
        search={{ labelWidth: 'auto' }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="新增培训记录"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                新增记录
              </Button>
            }
            onFinish={handleCreate}
            modalProps={{ destroyOnClose: true }}
          >
            <Row gutter={16}>
              <Col span={12}>
                <ProFormText
                  name="employee_id"
                  label="员工ID"
                  rules={[{ required: true }]}
                />
              </Col>
              <Col span={12}>
                <ProFormSelect
                  name="training_type"
                  label="培训类型"
                  options={Object.entries(TRAINING_TYPE_LABELS).map(([k, v]) => ({
                    label: v, value: k,
                  }))}
                  rules={[{ required: true }]}
                />
              </Col>
              <Col span={12}>
                <ProFormText
                  name="training_name"
                  label="培训名称"
                  rules={[{ required: true }]}
                />
              </Col>
              <Col span={12}>
                <Form.Item name="training_date" label="培训日期" rules={[{ required: true }]}>
                  <DatePicker style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <ProFormDigit name="duration_hours" label="时长(小时)" min={0} max={999} />
              </Col>
              <Col span={12}>
                <ProFormText name="location" label="培训地点" />
              </Col>
              <Col span={12}>
                <ProFormDigit name="score" label="考核分数" min={0} max={100} />
              </Col>
              <Col span={12}>
                <ProFormSelect
                  name="passed"
                  label="是否通过"
                  options={[{ label: '通过', value: true }, { label: '未通过', value: false }]}
                />
              </Col>
              <Col span={12}>
                <ProFormText name="certificate_no" label="证书编号" />
              </Col>
              <Col span={12}>
                <Form.Item name="certificate_expires_at" label="证书有效期">
                  <DatePicker style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={24}>
                <ProFormTextArea name="notes" label="备注" />
              </Col>
            </Row>
          </ModalForm>,
        ]}
        pagination={{ defaultPageSize: 20 }}
        scroll={{ x: 1200 }}
      />

      {/* 更新成绩 Modal */}
      <Modal
        title="更新培训记录"
        open={!!updateRecord}
        onCancel={() => setUpdateRecord(null)}
        onOk={handleUpdate}
        destroyOnClose
      >
        <Form form={updateForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="score" label="考核分数">
                <InputNumber min={0} max={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="passed" label="是否通过">
                <Select options={[{ label: '通过', value: true }, { label: '未通过', value: false }]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="certificate_no" label="证书编号">
                <Form.Item name="certificate_no" noStyle>
                  <Select
                    allowClear
                    showSearch
                    placeholder="输入证书编号"
                    notFoundContent={null}
                    filterOption={false}
                  />
                </Form.Item>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="certificate_expires_at" label="证书有效期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="notes" label="备注">
                <Select.Option value="">备注</Select.Option>
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </>
  );
}

// ── Tab 2: 证书预警 ──────────────────────────────────────────

function CertificateAlertTab() {
  const [items, setItems] = useState<ExpiringCert[]>([]);
  const [loading, setLoading] = useState(false);
  const [queryDays, setQueryDays] = useState(30);

  async function load(days: number) {
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/records/expiring-certs?days=${days}`, { headers });
      const data = await res.json();
      if (data.ok) setItems(data.data.items || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(queryDays); }, [queryDays]);

  const highRisk = items.filter(i => i.risk_level === 'high');
  const medRisk = items.filter(i => i.risk_level === 'medium');

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 横幅预警 */}
      {items.length > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<ExclamationCircleOutlined />}
          message={
            <Space>
              <Text strong>{items.length} 份证书将在 {queryDays} 天内到期</Text>
              {highRisk.length > 0 && (
                <Tag color="red">食品安全高风险 {highRisk.length} 份</Tag>
              )}
              {medRisk.length > 0 && (
                <Tag color="orange">中风险 {medRisk.length} 份</Tag>
              )}
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      <Space style={{ marginBottom: 16 }}>
        <Text>预警范围：</Text>
        <Select
          value={queryDays}
          onChange={setQueryDays}
          options={[
            { label: '7天内', value: 7 },
            { label: '30天内', value: 30 },
            { label: '60天内', value: 60 },
            { label: '90天内', value: 90 },
          ]}
          style={{ width: 120 }}
        />
      </Space>

      {items.length === 0 && !loading ? (
        <Card>
          <div style={{ textAlign: 'center', padding: 48 }}>
            <SafetyCertificateOutlined style={{ fontSize: 48, color: '#0F6E56' }} />
            <div style={{ marginTop: 16 }}>
              <Text type="secondary">{queryDays} 天内无即将到期证书</Text>
            </div>
          </div>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {items.map(item => (
            <Col xs={24} sm={12} lg={8} key={item.record_id}>
              <Card
                size="small"
                style={{
                  borderLeft: `4px solid ${item.risk_level === 'high' ? '#A32D2D' : item.risk_level === 'medium' ? '#BA7517' : '#185FA5'}`,
                }}
                actions={[
                  <Button
                    key="action"
                    type="primary"
                    size="small"
                    danger={item.risk_level === 'high'}
                    style={item.risk_level !== 'high' ? { backgroundColor: '#BA7517', borderColor: '#BA7517' } : {}}
                  >
                    {item.action}
                  </Button>,
                ]}
              >
                <Space direction="vertical" style={{ width: '100%' }} size={4}>
                  <Space>
                    <Tag color={item.risk_level === 'high' ? 'red' : item.risk_level === 'medium' ? 'orange' : 'blue'}>
                      {item.risk_level === 'high' ? '高风险' : item.risk_level === 'medium' ? '中风险' : '低风险'}
                    </Tag>
                    <Tag color={TRAINING_TYPE_COLORS[item.training_type] || 'default'}>
                      {TRAINING_TYPE_LABELS[item.training_type] || item.training_type}
                    </Tag>
                  </Space>
                  <Text strong>{item.training_name}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    员工ID：{item.employee_id.slice(0, 8)}...
                  </Text>
                  {item.certificate_no && (
                    <Text style={{ fontSize: 12 }}>证书：{item.certificate_no}</Text>
                  )}
                  <Space>
                    <Text type="danger">到期日：{item.certificate_expires_at}</Text>
                    <Tag color={item.days_remaining < 7 ? 'red' : 'orange'}>
                      剩余 {item.days_remaining} 天
                    </Tag>
                  </Space>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
}

// ── Tab 3: 培训统计 ──────────────────────────────────────────

function TrainingStatsTab() {
  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/stats`, { headers });
      const data = await res.json();
      if (data.ok) setStats(data.data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  if (!stats && !loading) return null;

  return (
    <div>
      {/* 4 个统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="本月培训人次"
              value={stats?.monthly_count ?? '-'}
              prefix={<CheckCircleOutlined style={{ color: '#0F6E56' }} />}
              valueStyle={{ color: '#0F6E56' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="通过率"
              value={stats?.pass_rate ?? '-'}
              suffix="%"
              valueStyle={{ color: (stats?.pass_rate ?? 0) >= 80 ? '#0F6E56' : '#BA7517' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="证书持有人数"
              value={stats?.cert_holders ?? '-'}
              prefix={<SafetyCertificateOutlined style={{ color: '#185FA5' }} />}
              valueStyle={{ color: '#185FA5' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card>
            <Statistic
              title="30天内到期证书"
              value={stats?.expiring_30_days ?? '-'}
              valueStyle={{ color: (stats?.expiring_30_days ?? 0) > 0 ? '#A32D2D' : '#0F6E56' }}
              prefix={
                (stats?.expiring_30_days ?? 0) > 0
                  ? <WarningOutlined style={{ color: '#A32D2D' }} />
                  : <CheckCircleOutlined style={{ color: '#0F6E56' }} />
              }
            />
          </Card>
        </Col>
      </Row>

      {/* 按培训类型完成率条形图（div模拟） */}
      <Card title="各培训类型完成率" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {(stats?.by_type || []).map(item => (
            <div key={item.training_type}>
              <Row justify="space-between" style={{ marginBottom: 4 }}>
                <Col>
                  <Tag color={TRAINING_TYPE_COLORS[item.training_type] || 'default'}>
                    {TRAINING_TYPE_LABELS[item.training_type] || item.training_type}
                  </Tag>
                  <Text type="secondary" style={{ marginLeft: 8 }}>
                    {item.passed}/{item.total} 人
                  </Text>
                </Col>
                <Col>
                  <Text strong style={{
                    color: item.pass_rate >= 80 ? '#0F6E56' : item.pass_rate >= 60 ? '#BA7517' : '#A32D2D'
                  }}>
                    {item.pass_rate}%
                  </Text>
                </Col>
              </Row>
              <Progress
                percent={item.pass_rate}
                showInfo={false}
                strokeColor={
                  item.pass_rate >= 80 ? '#0F6E56'
                  : item.pass_rate >= 60 ? '#BA7517'
                  : '#A32D2D'
                }
                trailColor="#F0EDE6"
                size="small"
              />
            </div>
          ))}
          {(!stats?.by_type || stats.by_type.length === 0) && (
            <Text type="secondary">暂无数据</Text>
          )}
        </Space>
      </Card>
    </div>
  );
}

// ── 主页面 ───────────────────────────────────────────────────

export default function EmployeeTrainingPage() {
  const [expiringCount, setExpiringCount] = useState(0);

  useEffect(() => {
    fetch(`${BASE}/records/expiring-certs?days=30`, { headers })
      .then(r => r.json())
      .then(data => {
        if (data.ok) setExpiringCount(data.data.total || 0);
      })
      .catch(() => {});
  }, []);

  const tabItems = [
    {
      key: 'records',
      label: '培训记录',
      children: <TrainingRecordsTab />,
    },
    {
      key: 'certs',
      label: (
        <Badge count={expiringCount} offset={[10, 0]}>
          证书预警
        </Badge>
      ),
      children: <CertificateAlertTab />,
    },
    {
      key: 'stats',
      label: '培训统计',
      children: <TrainingStatsTab />,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>员工培训管理</Title>
        <Text type="secondary">培训记录持久化 · 证书有效期预警 · 培训完成率统计</Text>
      </div>
      <Card bodyStyle={{ padding: '0 24px 24px' }}>
        <Tabs defaultActiveKey="records" items={tabItems} />
      </Card>
    </div>
  );
}
