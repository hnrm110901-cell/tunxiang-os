/**
 * 预警规则配置中心 — 管理员可视化设定预警规则和阈值
 * 五大域分组Tab + 规则列表 + 编辑Modal + 规则测试 + 修改历史
 * 调用 /api/v1/ops/alert-rules/*
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Tabs, Table, Tag, Switch, Button, Modal, Form, Input, InputNumber, Select,
  Space, message, Tooltip, Badge, Descriptions, Timeline, Card, Row, Col,
  Divider, Typography, Result,
} from 'antd';
import {
  PlusOutlined, EditOutlined, ExperimentOutlined, HistoryOutlined,
  BellOutlined, MessageOutlined, MailOutlined, MobileOutlined,
  CheckCircleOutlined, WarningOutlined, CloseCircleOutlined,
} from '@ant-design/icons';
import type {
  AlertRule, RuleDomain, NotifyChannel, TriggerOp,
  AlertRuleCreatePayload, AlertRuleTestResult, AlertRuleHistoryItem,
} from '../../../api/alertRuleApi';
import {
  fetchAlertRules, createAlertRule, updateAlertRule,
  toggleAlertRule, testAlertRule, fetchAlertRuleHistory,
} from '../../../api/alertRuleApi';

const { Text } = Typography;

// ─── 域配置 ───

const DOMAIN_CONFIG: Record<RuleDomain, { label: string; icon: string; metrics: { value: string; label: string }[] }> = {
  revenue: {
    label: '营收预警', icon: '💰', metrics: [
      { value: 'revenue_rate', label: '营收达成率' },
      { value: 'avg_ticket', label: '客单价' },
      { value: 'table_turnover', label: '翻台率' },
    ],
  },
  inventory: {
    label: '库存预警', icon: '📦', metrics: [
      { value: 'turnover_days', label: '库存周转天数' },
      { value: 'expiry_count', label: '临期食材数量' },
      { value: 'waste_rate', label: '损耗率' },
    ],
  },
  quality: {
    label: '出品预警', icon: '🍽️', metrics: [
      { value: 'slow_dish_rate', label: '慢菜率' },
      { value: 'return_rate', label: '退菜率' },
      { value: 'complaint_rate', label: '客诉率' },
    ],
  },
  labor: {
    label: '人效预警', icon: '👥', metrics: [
      { value: 'labor_efficiency', label: '人效(元/人)' },
      { value: 'attendance_rate', label: '到岗率' },
      { value: 'overtime_hours', label: '加班时长' },
    ],
  },
  safety: {
    label: '食安预警', icon: '🛡️', metrics: [
      { value: 'temperature', label: '冷链温度' },
      { value: 'inspection_pass', label: '巡检通过率' },
      { value: 'cert_expiry', label: '证件过期数' },
    ],
  },
};

const TRIGGER_OP_OPTIONS: { value: TriggerOp; label: string }[] = [
  { value: 'gt', label: '大于 (>)' },
  { value: 'gte', label: '大于等于 (>=)' },
  { value: 'lt', label: '小于 (<)' },
  { value: 'lte', label: '小于等于 (<=)' },
  { value: 'eq', label: '等于 (=)' },
  { value: 'consecutive_days', label: '连续N天' },
];

const TRIGGER_OP_LABELS: Record<TriggerOp, string> = {
  gt: '>', gte: '>=', lt: '<', lte: '<=', eq: '=', consecutive_days: '连续天数',
};

const NOTIFY_CHANNEL_CONFIG: Record<NotifyChannel, { label: string; icon: React.ReactNode }> = {
  wecom: { label: '企业微信', icon: <MessageOutlined /> },
  sms: { label: '短信', icon: <MobileOutlined /> },
  push: { label: 'App推送', icon: <BellOutlined /> },
  email: { label: '邮件', icon: <MailOutlined /> },
};

const SCOPE_OPTIONS = [
  { value: 'all', label: '全部门店' },
  { value: 'region', label: '指定区域' },
  { value: 'store', label: '指定门店' },
];

const ROLE_OPTIONS = [
  { value: 'store_manager', label: '店长' },
  { value: 'region_manager', label: '区域经理' },
  { value: 'hq', label: '总部' },
];

// ─── 主页面组件 ───

export function AlertRuleConfigPage() {
  const [activeDomain, setActiveDomain] = useState<RuleDomain>('revenue');
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(false);

  // 编辑Modal状态
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [editForm] = Form.useForm();
  const [saving, setSaving] = useState(false);

  // 测试Modal状态
  const [testModalOpen, setTestModalOpen] = useState(false);
  const [testingRule, setTestingRule] = useState<AlertRule | null>(null);
  const [testValue, setTestValue] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<AlertRuleTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  // 历史Modal状态
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [historyRule, setHistoryRule] = useState<AlertRule | null>(null);
  const [historyItems, setHistoryItems] = useState<AlertRuleHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // scope 联动
  const [scopeType, setScopeType] = useState<'all' | 'region' | 'store'>('all');

  // ─── 数据加载 ───

  const loadRules = useCallback(async (domain: RuleDomain) => {
    setLoading(true);
    try {
      const data = await fetchAlertRules(domain);
      setRules(data);
    } catch {
      setRules([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRules(activeDomain);
  }, [activeDomain, loadRules]);

  // ─── 启用/禁用 ───

  const handleToggle = async (rule: AlertRule) => {
    try {
      const updated = await toggleAlertRule(rule.id, !rule.enabled);
      setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      message.success(`已${updated.enabled ? '启用' : '禁用'}规则「${rule.name}」`);
    } catch {
      message.error('操作失败');
    }
  };

  // ─── 编辑/新建 ───

  const handleOpenEdit = (rule?: AlertRule) => {
    if (rule) {
      setEditingRule(rule);
      setScopeType(rule.scope);
      editForm.setFieldsValue({
        name: rule.name,
        metric: rule.metric,
        trigger_op: rule.trigger_op,
        trigger_value: rule.trigger_value,
        threshold_green: rule.thresholds.green,
        threshold_yellow: rule.thresholds.yellow,
        threshold_red: rule.thresholds.red,
        scope: rule.scope,
        scope_ids: rule.scope_ids,
        notify_channels: rule.notify_channels,
        notify_roles: rule.notify_roles,
        enabled: rule.enabled,
      });
    } else {
      setEditingRule(null);
      setScopeType('all');
      editForm.resetFields();
      editForm.setFieldsValue({ enabled: true, scope: 'all', notify_channels: ['wecom'] });
    }
    setEditModalOpen(true);
  };

  const handleSaveRule = async () => {
    try {
      const values = await editForm.validateFields();
      setSaving(true);

      const metricOption = DOMAIN_CONFIG[activeDomain].metrics.find((m) => m.value === values.metric);

      const payload: AlertRuleCreatePayload = {
        name: values.name,
        domain: activeDomain,
        metric: values.metric,
        metric_label: metricOption?.label || values.metric,
        trigger_op: values.trigger_op,
        trigger_value: values.trigger_value,
        thresholds: {
          green: values.threshold_green,
          yellow: values.threshold_yellow,
          red: values.threshold_red,
        },
        scope: values.scope,
        scope_ids: values.scope === 'all' ? [] : (values.scope_ids || []),
        notify_channels: values.notify_channels,
        notify_roles: values.notify_roles,
        enabled: values.enabled ?? true,
      };

      if (editingRule) {
        const updated = await updateAlertRule(editingRule.id, payload);
        setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
        message.success('规则已更新');
      } else {
        const created = await createAlertRule(payload);
        setRules((prev) => [...prev, created]);
        message.success('规则已创建');
      }
      setEditModalOpen(false);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return; // 表单校验失败
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  // ─── 规则测试 ───

  const handleOpenTest = (rule: AlertRule) => {
    setTestingRule(rule);
    setTestValue(null);
    setTestResult(null);
    setTestModalOpen(true);
  };

  const handleRunTest = async () => {
    if (!testingRule || testValue === null) return;
    setTesting(true);
    try {
      const result = await testAlertRule(testingRule.id, { metric_value: testValue });
      setTestResult(result);
    } catch {
      message.error('测试失败');
    } finally {
      setTesting(false);
    }
  };

  // ─── 修改历史 ───

  const handleOpenHistory = async (rule: AlertRule) => {
    setHistoryRule(rule);
    setHistoryModalOpen(true);
    setHistoryLoading(true);
    try {
      const items = await fetchAlertRuleHistory(rule.id);
      setHistoryItems(items);
    } catch {
      setHistoryItems([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  // ─── 表格列定义 ───

  const columns = [
    {
      title: '规则名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      render: (name: string, record: AlertRule) => (
        <div>
          <Text strong>{name}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>{record.metric_label}</Text>
        </div>
      ),
    },
    {
      title: '触发条件',
      key: 'trigger',
      width: 160,
      render: (_: unknown, record: AlertRule) => (
        <Tag>
          {record.metric_label} {TRIGGER_OP_LABELS[record.trigger_op]} {record.trigger_value}
        </Tag>
      ),
    },
    {
      title: '阈值',
      key: 'thresholds',
      width: 220,
      render: (_: unknown, record: AlertRule) => (
        <Space size={4}>
          <Tag color="#0F6E56" style={{ minWidth: 56, textAlign: 'center' }}>
            绿 {record.thresholds.green}
          </Tag>
          <Tag color="#BA7517" style={{ minWidth: 56, textAlign: 'center' }}>
            黄 {record.thresholds.yellow}
          </Tag>
          <Tag color="#A32D2D" style={{ minWidth: 56, textAlign: 'center' }}>
            红 {record.thresholds.red}
          </Tag>
        </Space>
      ),
    },
    {
      title: '适用范围',
      key: 'scope',
      width: 140,
      render: (_: unknown, record: AlertRule) => {
        if (record.scope === 'all') return <Tag>全部门店</Tag>;
        return (
          <Tooltip title={record.scope_names.join('、')}>
            <Tag color="#185FA5">
              {record.scope === 'region' ? '区域' : '门店'}: {record.scope_names.length}个
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '通知渠道',
      key: 'notify_channels',
      width: 120,
      render: (_: unknown, record: AlertRule) => (
        <Space size={4}>
          {record.notify_channels.map((ch) => (
            <Tooltip key={ch} title={NOTIFY_CHANNEL_CONFIG[ch].label}>
              <span style={{ fontSize: 16 }}>{NOTIFY_CHANNEL_CONFIG[ch].icon}</span>
            </Tooltip>
          ))}
        </Space>
      ),
    },
    {
      title: '7日触发',
      dataIndex: 'trigger_count_7d',
      key: 'trigger_count_7d',
      width: 90,
      align: 'center' as const,
      render: (count: number) => (
        <Badge count={count} showZero style={{ backgroundColor: count > 0 ? '#A32D2D' : '#d9d9d9' }} />
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      align: 'center' as const,
      render: (enabled: boolean, record: AlertRule) => (
        <Switch
          checked={enabled}
          onChange={() => handleToggle(record)}
          size="small"
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, record: AlertRule) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleOpenEdit(record)}>
            编辑
          </Button>
          <Button type="link" size="small" icon={<ExperimentOutlined />} onClick={() => handleOpenTest(record)}>
            测试
          </Button>
          <Button type="link" size="small" icon={<HistoryOutlined />} onClick={() => handleOpenHistory(record)}>
            历史
          </Button>
        </Space>
      ),
    },
  ];

  // ─── 渲染 ───

  const domainTabs = (Object.keys(DOMAIN_CONFIG) as RuleDomain[]).map((key) => ({
    key,
    label: (
      <span>
        {DOMAIN_CONFIG[key].icon} {DOMAIN_CONFIG[key].label}
      </span>
    ),
  }));

  return (
    <div style={{ padding: 24 }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>预警规则配置中心</h2>
          <Text type="secondary" style={{ fontSize: 13 }}>
            管理各业务域的预警规则、阈值和通知策略
          </Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => handleOpenEdit()}
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
        >
          新建规则
        </Button>
      </div>

      {/* 统计概览卡片 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card size="small" style={{ borderLeft: '3px solid #FF6B35' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#FF6B35' }}>{rules.length}</div>
            <Text type="secondary" style={{ fontSize: 12 }}>当前域规则总数</Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderLeft: '3px solid #0F6E56' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#0F6E56' }}>
              {rules.filter((r) => r.enabled).length}
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>已启用</Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderLeft: '3px solid #A32D2D' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#A32D2D' }}>
              {rules.reduce((sum, r) => sum + r.trigger_count_7d, 0)}
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>近7日触发次数</Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderLeft: '3px solid #BA7517' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#BA7517' }}>
              {rules.filter((r) => !r.enabled).length}
            </div>
            <Text type="secondary" style={{ fontSize: 12 }}>已禁用</Text>
          </Card>
        </Col>
      </Row>

      {/* 域分组Tab + 规则列表 */}
      <Card>
        <Tabs
          activeKey={activeDomain}
          onChange={(key) => setActiveDomain(key as RuleDomain)}
          items={domainTabs}
          style={{ marginBottom: 0 }}
        />
        <Table<AlertRule>
          columns={columns}
          dataSource={rules}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条规则` }}
          size="middle"
          locale={{ emptyText: '暂无规则，点击右上角「新建规则」开始配置' }}
        />
      </Card>

      {/* ────── 规则编辑 Modal ────── */}
      <Modal
        title={editingRule ? `编辑规则：${editingRule.name}` : `新建${DOMAIN_CONFIG[activeDomain].label}规则`}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={handleSaveRule}
        confirmLoading={saving}
        width={680}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="例如：营收达成率低于80%预警" maxLength={50} />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="metric" label="监控指标" rules={[{ required: true, message: '请选择指标' }]}>
                <Select
                  placeholder="选择指标"
                  options={DOMAIN_CONFIG[activeDomain].metrics.map((m) => ({ value: m.value, label: m.label }))}
                />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="trigger_op" label="触发条件" rules={[{ required: true, message: '请选择' }]}>
                <Select placeholder="条件" options={TRIGGER_OP_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="trigger_value" label="触发值" rules={[{ required: true, message: '请输入' }]}>
                <InputNumber style={{ width: '100%' }} placeholder="值" />
              </Form.Item>
            </Col>
          </Row>

          <Divider style={{ margin: '8px 0 16px' }}>三级阈值</Divider>

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="threshold_green"
                label={<span style={{ color: '#0F6E56', fontWeight: 600 }}>绿 (正常)</span>}
                rules={[{ required: true, message: '请输入' }]}
              >
                <InputNumber
                  style={{ width: '100%', borderColor: '#0F6E56' }}
                  placeholder="正常阈值"
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="threshold_yellow"
                label={<span style={{ color: '#BA7517', fontWeight: 600 }}>黄 (预警)</span>}
                rules={[{ required: true, message: '请输入' }]}
              >
                <InputNumber
                  style={{ width: '100%', borderColor: '#BA7517' }}
                  placeholder="预警阈值"
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="threshold_red"
                label={<span style={{ color: '#A32D2D', fontWeight: 600 }}>红 (严重)</span>}
                rules={[{ required: true, message: '请输入' }]}
              >
                <InputNumber
                  style={{ width: '100%', borderColor: '#A32D2D' }}
                  placeholder="严重阈值"
                />
              </Form.Item>
            </Col>
          </Row>

          <Divider style={{ margin: '8px 0 16px' }}>适用范围</Divider>

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="scope" label="范围类型" rules={[{ required: true }]}>
                <Select
                  options={SCOPE_OPTIONS}
                  onChange={(val) => setScopeType(val)}
                />
              </Form.Item>
            </Col>
            {scopeType !== 'all' && (
              <Col span={16}>
                <Form.Item
                  name="scope_ids"
                  label={scopeType === 'region' ? '选择区域' : '选择门店'}
                  rules={[{ required: true, message: '请选择适用范围' }]}
                >
                  <Select
                    mode="multiple"
                    placeholder={scopeType === 'region' ? '搜索并选择区域' : '搜索并选择门店'}
                    showSearch
                    filterOption={(input, option) =>
                      ((option as { label?: string } | undefined)?.label || '').toLowerCase().includes(input.toLowerCase())
                    }
                    options={[]}
                    notFoundContent="暂无数据，请先在组织架构中配置"
                  />
                </Form.Item>
              </Col>
            )}
          </Row>

          <Divider style={{ margin: '8px 0 16px' }}>通知配置</Divider>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="notify_channels"
                label="通知渠道"
                rules={[{ required: true, message: '请选择至少一个通知渠道' }]}
              >
                <Select
                  mode="multiple"
                  placeholder="选择通知渠道"
                  options={(Object.keys(NOTIFY_CHANNEL_CONFIG) as NotifyChannel[]).map((ch) => ({
                    value: ch,
                    label: NOTIFY_CHANNEL_CONFIG[ch].label,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="notify_roles"
                label="通知对象"
                rules={[{ required: true, message: '请选择通知对象' }]}
              >
                <Select mode="multiple" placeholder="选择通知角色" options={ROLE_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="enabled" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ────── 规则测试 Modal ────── */}
      <Modal
        title={testingRule ? `测试规则：${testingRule.name}` : '规则测试'}
        open={testModalOpen}
        onCancel={() => { setTestModalOpen(false); setTestResult(null); }}
        footer={null}
        width={520}
        destroyOnClose
      >
        {testingRule && (
          <div style={{ padding: '8px 0' }}>
            <Descriptions size="small" column={1} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="监控指标">{testingRule.metric_label}</Descriptions.Item>
              <Descriptions.Item label="触发条件">
                {TRIGGER_OP_LABELS[testingRule.trigger_op]} {testingRule.trigger_value}
              </Descriptions.Item>
              <Descriptions.Item label="阈值">
                <Space size={4}>
                  <Tag color="#0F6E56">绿 {testingRule.thresholds.green}</Tag>
                  <Tag color="#BA7517">黄 {testingRule.thresholds.yellow}</Tag>
                  <Tag color="#A32D2D">红 {testingRule.thresholds.red}</Tag>
                </Space>
              </Descriptions.Item>
            </Descriptions>

            <Divider style={{ margin: '12px 0' }} />

            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 20 }}>
              <div style={{ flex: 1 }}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                  输入模拟指标值
                </Text>
                <InputNumber
                  style={{ width: '100%' }}
                  placeholder={`输入${testingRule.metric_label}模拟值`}
                  value={testValue}
                  onChange={(v) => setTestValue(v)}
                  size="large"
                />
              </div>
              <Button
                type="primary"
                icon={<ExperimentOutlined />}
                onClick={handleRunTest}
                loading={testing}
                disabled={testValue === null}
                style={{ background: '#FF6B35', borderColor: '#FF6B35', height: 40 }}
              >
                执行测试
              </Button>
            </div>

            {testResult && (
              <Card
                size="small"
                style={{
                  borderColor: testResult.level === 'green' ? '#0F6E56'
                    : testResult.level === 'yellow' ? '#BA7517' : '#A32D2D',
                  borderWidth: 2,
                }}
              >
                <Result
                  icon={
                    testResult.level === 'green' ? <CheckCircleOutlined style={{ color: '#0F6E56' }} />
                      : testResult.level === 'yellow' ? <WarningOutlined style={{ color: '#BA7517' }} />
                        : <CloseCircleOutlined style={{ color: '#A32D2D' }} />
                  }
                  title={
                    <span style={{
                      color: testResult.level === 'green' ? '#0F6E56'
                        : testResult.level === 'yellow' ? '#BA7517' : '#A32D2D',
                    }}>
                      {testResult.triggered ? '触发预警' : '未触发'}
                      {' — '}
                      {testResult.level === 'green' ? '正常' : testResult.level === 'yellow' ? '预警' : '严重'}
                    </span>
                  }
                  subTitle={testResult.message}
                  style={{ padding: '16px 0' }}
                />
              </Card>
            )}
          </div>
        )}
      </Modal>

      {/* ────── 修改历史 Modal ────── */}
      <Modal
        title={historyRule ? `修改历史：${historyRule.name}` : '修改历史'}
        open={historyModalOpen}
        onCancel={() => setHistoryModalOpen(false)}
        footer={null}
        width={600}
        destroyOnClose
      >
        {historyLoading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>加载中...</div>
        ) : historyItems.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>暂无修改记录</div>
        ) : (
          <Timeline
            style={{ marginTop: 16, paddingTop: 8 }}
            items={historyItems.map((item) => ({
              color: item.action === '创建' ? '#0F6E56' : '#FF6B35',
              children: (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <Text strong>{item.action}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{item.created_at}</Text>
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>操作人: {item.operator}</Text>
                  {Object.keys(item.diff).length > 0 && (
                    <div style={{ marginTop: 6, padding: '6px 10px', background: '#fafafa', borderRadius: 4, fontSize: 12 }}>
                      {Object.entries(item.diff).map(([field, changes]) => (
                        <div key={field}>
                          <Text type="secondary">{field}: </Text>
                          <Text delete style={{ color: '#A32D2D' }}>{String(changes.before)}</Text>
                          <Text> → </Text>
                          <Text style={{ color: '#0F6E56' }}>{String(changes.after)}</Text>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ),
            }))}
          />
        )}
      </Modal>
    </div>
  );
}
