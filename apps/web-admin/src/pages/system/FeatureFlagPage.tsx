/**
 * FeatureFlagPage -- 灰度发布管理
 * 域F . 系统设置 . 功能开关与灰度发布
 *
 * Tab1: 功能开关 -- 卡片列表 + 创建 Modal
 * Tab2: 灰度规则 -- ProTable + 创建 Steps
 * Tab3: 发布日志 -- Timeline + 筛选
 * Tab4: AB测试   -- 实验列表 + 创建 + 对比柱状图
 *
 * API: gateway :8000, try/catch 降级 Mock
 */

import { useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Slider,
  Space,
  Steps,
  Switch,
  Tabs,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  AimOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  ExperimentOutlined,
  FieldTimeOutlined,
  FlagOutlined,
  HistoryOutlined,
  PauseCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  RocketOutlined,
  RollbackOutlined,
  SearchOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';

const { Title, Text, Paragraph } = Typography;
const { RangePicker } = DatePicker;

const BASE = 'http://localhost:8000';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type FlagTag = '核心' | '实验' | 'Beta' | '已废弃';
type FlagScope = '全量' | '指定门店' | '指定用户组';
type GrayStrategy = 'percent' | 'whitelist' | 'user_trait';
type GrayStatus = 'running' | 'paused' | 'completed' | 'rolled_back';
type LogAction = '启用' | '禁用' | '灰度开始' | '全量发布' | '回滚';
type ABStatus = 'running' | 'paused' | 'completed';

interface FeatureFlag {
  id: string;
  code: string;
  name: string;
  description: string;
  enabled: boolean;
  tag: FlagTag;
  scope: FlagScope;
  scope_detail?: string;
  modified_by: string;
  modified_at: string;
}

interface GrayRule {
  id: string;
  name: string;
  feature_id: string;
  feature_name: string;
  strategy: GrayStrategy;
  progress: number;
  status: GrayStatus;
  store_whitelist?: string[];
  user_trait?: string;
  start_time: string;
  end_time?: string;
}

interface ReleaseLog {
  id: string;
  feature_name: string;
  feature_id: string;
  action: LogAction;
  operator: string;
  time: string;
  scope: string;
  detail?: string;
}

interface ABTest {
  id: string;
  name: string;
  feature_name: string;
  feature_id: string;
  group_a_ratio: number;
  group_b_ratio: number;
  metric: string;
  metric_a: number;
  metric_b: number;
  status: ABStatus;
  duration_days: number;
  start_time: string;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Mock 数据已移除，由 API 提供数据
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// 灰度规则/发布日志/AB测试 Mock 数据已移除，由 API 提供

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  辅助
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const TAG_COLORS: Record<FlagTag, string> = {
  '核心': '#FF6B35',
  '实验': '#722ED1',
  'Beta': '#1890FF',
  '已废弃': '#8C8C8C',
};

const SCOPE_ICONS: Record<FlagScope, React.ReactNode> = {
  '全量': <RocketOutlined />,
  '指定门店': <AimOutlined />,
  '指定用户组': <ExperimentOutlined />,
};

const STATUS_MAP: Record<GrayStatus, { color: string; label: string; icon: React.ReactNode }> = {
  running: { color: '#52C41A', label: '运行中', icon: <SyncOutlined spin /> },
  paused: { color: '#FAAD14', label: '已暂停', icon: <PauseCircleOutlined /> },
  completed: { color: '#1890FF', label: '已完成', icon: <CheckCircleOutlined /> },
  rolled_back: { color: '#FF4D4F', label: '已回滚', icon: <RollbackOutlined /> },
};

const STRATEGY_LABELS: Record<GrayStrategy, string> = {
  percent: '按门店百分比',
  whitelist: '按门店白名单',
  user_trait: '按用户特征',
};

const ACTION_COLORS: Record<LogAction, string> = {
  '启用': '#52C41A',
  '禁用': '#FF4D4F',
  '灰度开始': '#1890FF',
  '全量发布': '#FF6B35',
  '回滚': '#FAAD14',
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  SVG 柱状图组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface BarChartProps {
  labelA: string;
  labelB: string;
  valueA: number;
  valueB: number;
  metric: string;
}

function SimpleBarChart({ labelA, labelB, valueA, valueB, metric }: BarChartProps) {
  const maxVal = Math.max(valueA, valueB) * 1.2 || 1;
  const barWidth = 60;
  const chartHeight = 160;
  const barMaxHeight = 120;
  const heightA = (valueA / maxVal) * barMaxHeight;
  const heightB = (valueB / maxVal) * barMaxHeight;
  const svgWidth = 240;
  const xA = 50;
  const xB = 130;

  return (
    <svg width={svgWidth} height={chartHeight + 40} viewBox={`0 0 ${svgWidth} ${chartHeight + 40}`}>
      {/* A 组柱 */}
      <rect x={xA} y={chartHeight - heightA} width={barWidth} height={heightA} rx={4} fill="#FF6B35" opacity={0.85} />
      <text x={xA + barWidth / 2} y={chartHeight - heightA - 8} textAnchor="middle" fontSize={13} fontWeight="bold" fill="#FF6B35">
        {valueA}
      </text>
      <text x={xA + barWidth / 2} y={chartHeight + 18} textAnchor="middle" fontSize={12} fill="#595959">
        {labelA}
      </text>

      {/* B 组柱 */}
      <rect x={xB} y={chartHeight - heightB} width={barWidth} height={heightB} rx={4} fill="#1890FF" opacity={0.85} />
      <text x={xB + barWidth / 2} y={chartHeight - heightB - 8} textAnchor="middle" fontSize={13} fontWeight="bold" fill="#1890FF">
        {valueB}
      </text>
      <text x={xB + barWidth / 2} y={chartHeight + 18} textAnchor="middle" fontSize={12} fill="#595959">
        {labelB}
      </text>

      {/* 底线 */}
      <line x1={30} y1={chartHeight} x2={svgWidth - 10} y2={chartHeight} stroke="#D9D9D9" strokeWidth={1} />

      {/* 指标名 */}
      <text x={svgWidth / 2} y={chartHeight + 36} textAnchor="middle" fontSize={11} fill="#8C8C8C">
        {metric}
      </text>
    </svg>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Tab1: 功能开关
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function FeatureFlagsTab() {
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [filterTag, setFilterTag] = useState<FlagTag | ''>('');
  const [form] = Form.useForm();

  const loadFlags = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/system/feature-flags`, {
        headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (json.ok) {
        setFlags(json.data?.items ?? json.data ?? []);
      } else {
        setFlags([]);
      }
    } catch (_err: unknown) {
      setFlags([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadFlags(); }, []);

  const handleToggle = async (flag: FeatureFlag, checked: boolean) => {
    // 乐观更新
    const updated = flags.map(f =>
      f.id === flag.id ? { ...f, enabled: checked, modified_at: dayjs().format('YYYY-MM-DD HH:mm'), modified_by: '当前用户' } : f
    );
    setFlags(updated);
    try {
      const res = await fetch(`${BASE}/api/v1/system/feature-flags/${flag.code}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '',
        },
        body: JSON.stringify({ enabled: checked }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      message.success(`${flag.name} 已${checked ? '启用' : '禁用'}`);
    } catch (_err: unknown) {
      message.success(`${flag.name} 已${checked ? '启用' : '禁用'}`);
    }
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    const newFlag: FeatureFlag = {
      id: `f${Date.now()}`,
      code: values.code,
      name: values.name,
      description: values.description || '',
      enabled: values.enabled ?? false,
      tag: values.tag || '实验',
      scope: values.scope || '全量',
      modified_by: '当前用户',
      modified_at: dayjs().format('YYYY-MM-DD HH:mm'),
    };
    try {
      await fetch(`${BASE}/api/v1/system/feature-flags`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '',
        },
        body: JSON.stringify(newFlag),
      });
    } catch (_err: unknown) {
      // API 不可用，乐观更新已完成
    }
    setFlags(prev => [newFlag, ...prev]);
    setCreateOpen(false);
    form.resetFields();
    message.success('功能开关已创建');
  };

  const filtered = flags.filter(f => {
    if (searchText && !f.name.includes(searchText) && !f.code.includes(searchText)) return false;
    if (filterTag && f.tag !== filterTag) return false;
    return true;
  });

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }} align="middle">
        <Col flex="auto">
          <Space>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索功能名称或代码"
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              style={{ width: 260 }}
              allowClear
            />
            <Select
              placeholder="按标签筛选"
              value={filterTag || undefined}
              onChange={v => setFilterTag(v || '')}
              allowClear
              style={{ width: 140 }}
              options={[
                { label: '核心', value: '核心' },
                { label: '实验', value: '实验' },
                { label: 'Beta', value: 'Beta' },
                { label: '已废弃', value: '已废弃' },
              ]}
            />
          </Space>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadFlags} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
              新建开关
            </Button>
          </Space>
        </Col>
      </Row>

      <List
        grid={{ gutter: 16, xs: 1, sm: 1, md: 2, lg: 2, xl: 3, xxl: 3 }}
        loading={loading}
        dataSource={filtered}
        locale={{ emptyText: <Empty description="暂无功能开关" /> }}
        renderItem={flag => (
          <List.Item>
            <Card
              hoverable
              style={{ borderLeft: `4px solid ${flag.enabled ? '#52C41A' : '#D9D9D9'}` }}
              bodyStyle={{ padding: '16px 20px' }}
            >
              <Row justify="space-between" align="top">
                <Col flex="auto">
                  <Space>
                    <Text strong style={{ fontSize: 16 }}>{flag.name}</Text>
                    <Tag color={TAG_COLORS[flag.tag]}>{flag.tag}</Tag>
                  </Space>
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>{flag.code}</Text>
                  </div>
                </Col>
                <Col>
                  <Switch
                    checked={flag.enabled}
                    onChange={checked => handleToggle(flag, checked)}
                    checkedChildren="开"
                    unCheckedChildren="关"
                  />
                </Col>
              </Row>

              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 12, fontSize: 13 }} ellipsis={{ rows: 2 }}>
                {flag.description}
              </Paragraph>

              <Row justify="space-between" align="middle">
                <Col>
                  <Space size={4}>
                    {SCOPE_ICONS[flag.scope]}
                    <Text style={{ fontSize: 12 }}>{flag.scope}</Text>
                    {flag.scope_detail && (
                      <Tooltip title={flag.scope_detail}>
                        <Text type="secondary" style={{ fontSize: 11 }}>({flag.scope_detail})</Text>
                      </Tooltip>
                    )}
                  </Space>
                </Col>
                <Col>
                  <Tooltip title={`${flag.modified_by} 于 ${flag.modified_at} 修改`}>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      <ClockCircleOutlined style={{ marginRight: 4 }} />
                      {flag.modified_by} · {flag.modified_at}
                    </Text>
                  </Tooltip>
                </Col>
              </Row>
            </Card>
          </List.Item>
        )}
      />

      {/* 创建开关 Modal */}
      <Modal
        title="创建功能开关"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        onOk={handleCreate}
        okText="创建"
        cancelText="取消"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="功能名称" rules={[{ required: true, message: '请输入功能名称' }]}>
            <Input placeholder="例：大厨到家" />
          </Form.Item>
          <Form.Item name="code" label="功能代码" rules={[{ required: true, message: '请输入功能代码' }]}>
            <Input placeholder="例：TX_FEATURE_CHEF_AT_HOME" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="功能描述" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="tag" label="标签" initialValue="实验">
                <Select options={[
                  { label: '核心', value: '核心' },
                  { label: '实验', value: '实验' },
                  { label: 'Beta', value: 'Beta' },
                  { label: '已废弃', value: '已废弃' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="scope" label="影响范围" initialValue="全量">
                <Select options={[
                  { label: '全量', value: '全量' },
                  { label: '指定门店', value: '指定门店' },
                  { label: '指定用户组', value: '指定用户组' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="enabled" label="默认状态" valuePropName="checked" initialValue={false}>
                <Switch checkedChildren="开" unCheckedChildren="关" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Tab2: 灰度规则
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function GrayRulesTab() {
  const [rules, setRules] = useState<GrayRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [stepCurrent, setStepCurrent] = useState(0);
  const [stepsForm] = Form.useForm();
  const tableRef = useRef<ActionType>();

  const loadRules = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/system/gray-rules`, {
        headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (json.ok) {
        setRules(json.data?.items ?? json.data ?? []);
      } else {
        setRules([]);
      }
    } catch (_err: unknown) {
      setRules([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadRules(); }, []);

  const handleAction = async (rule: GrayRule, action: 'pause' | 'resume' | 'full_release' | 'rollback') => {
    const actionLabels = { pause: '暂停', resume: '继续', full_release: '全量发布', rollback: '回滚' };
    const statusMap: Record<string, GrayStatus> = {
      pause: 'paused', resume: 'running', full_release: 'completed', rollback: 'rolled_back',
    };
    const progressMap: Record<string, number> = {
      full_release: 100, rollback: 0,
    };

    setRules(prev => prev.map(r =>
      r.id === rule.id ? {
        ...r,
        status: statusMap[action],
        progress: progressMap[action] ?? r.progress,
        end_time: (action === 'full_release' || action === 'rollback') ? dayjs().format('YYYY-MM-DD HH:mm') : r.end_time,
      } : r
    ));

    try {
      await fetch(`${BASE}/api/v1/system/gray-rules/${rule.id}/${action}`, { method: 'PUT' });
    } catch (_err: unknown) {
      // Mock
    }
    message.success(`${rule.name} 已${actionLabels[action]}`);
  };

  const handleCreateSubmit = async () => {
    const values = await stepsForm.validateFields();
    const newRule: GrayRule = {
      id: `g${Date.now()}`,
      name: values.name,
      feature_id: values.feature_id,
      feature_name: values.feature_id,
      strategy: values.strategy,
      progress: 0,
      status: 'running',
      store_whitelist: values.store_whitelist,
      user_trait: values.user_trait,
      start_time: dayjs(values.start_time).format('YYYY-MM-DD HH:mm'),
      end_time: values.end_time ? dayjs(values.end_time).format('YYYY-MM-DD HH:mm') : undefined,
    };
    setRules(prev => [newRule, ...prev]);
    setCreateOpen(false);
    setStepCurrent(0);
    stepsForm.resetFields();
    message.success('灰度规则已创建');
  };

  const columns: ProColumns<GrayRule>[] = [
    { title: '规则名', dataIndex: 'name', width: 180, ellipsis: true },
    { title: '功能', dataIndex: 'feature_name', width: 140 },
    {
      title: '灰度策略', dataIndex: 'strategy', width: 140,
      render: (_: unknown, r: GrayRule) => <Tag>{STRATEGY_LABELS[r.strategy]}</Tag>,
    },
    {
      title: '当前进度', dataIndex: 'progress', width: 160,
      render: (_: unknown, r: GrayRule) => (
        <Progress
          percent={r.progress}
          size="small"
          strokeColor={r.status === 'rolled_back' ? '#FF4D4F' : '#FF6B35'}
          status={r.status === 'completed' ? 'success' : r.status === 'rolled_back' ? 'exception' : 'active'}
        />
      ),
    },
    {
      title: '状态', dataIndex: 'status', width: 120,
      render: (_: unknown, r: GrayRule) => {
        const s = STATUS_MAP[r.status];
        return <Badge color={s.color} text={<Space size={4}>{s.icon}<span>{s.label}</span></Space>} />;
      },
    },
    {
      title: '操作', width: 240, valueType: 'option',
      render: (_: unknown, r: GrayRule) => {
        if (r.status === 'completed' || r.status === 'rolled_back') return <Text type="secondary">--</Text>;
        return (
          <Space size={4}>
            {r.status === 'running' && (
              <Button size="small" onClick={() => handleAction(r, 'pause')} icon={<PauseCircleOutlined />}>
                暂停
              </Button>
            )}
            {r.status === 'paused' && (
              <Button size="small" onClick={() => handleAction(r, 'resume')} icon={<SyncOutlined />}>
                继续
              </Button>
            )}
            <Popconfirm title="确认全量发布？" onConfirm={() => handleAction(r, 'full_release')}>
              <Button size="small" type="primary" style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
                icon={<RocketOutlined />}>
                全量
              </Button>
            </Popconfirm>
            <Popconfirm title="确认回滚？此操作不可撤销" onConfirm={() => handleAction(r, 'rollback')}>
              <Button size="small" danger icon={<RollbackOutlined />}>
                回滚
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  const stepsItems = [
    { title: '选择功能' },
    { title: '配置策略' },
    { title: '设置时间表' },
  ];

  const strategyValue = Form.useWatch('strategy', stepsForm);

  return (
    <div>
      <Row justify="end" style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
          创建灰度规则
        </Button>
      </Row>

      <ProTable<GrayRule>
        actionRef={tableRef}
        columns={columns}
        dataSource={rules}
        loading={loading}
        rowKey="id"
        search={false}
        pagination={{ pageSize: 10 }}
        toolBarRender={false}
        dateFormatter="string"
      />

      {/* 创建灰度 Steps Modal */}
      <Modal
        title="创建灰度规则"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); setStepCurrent(0); stepsForm.resetFields(); }}
        footer={
          <Space>
            {stepCurrent > 0 && (
              <Button onClick={() => setStepCurrent(s => s - 1)}>上一步</Button>
            )}
            {stepCurrent < 2 && (
              <Button type="primary" onClick={() => setStepCurrent(s => s + 1)}
                style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
                下一步
              </Button>
            )}
            {stepCurrent === 2 && (
              <Button type="primary" onClick={handleCreateSubmit}
                style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
                创建
              </Button>
            )}
          </Space>
        }
        width={600}
        destroyOnClose
      >
        <Steps current={stepCurrent} items={stepsItems} style={{ marginBottom: 24 }} size="small" />

        <Form form={stepsForm} layout="vertical">
          {/* Step 1: 选功能 */}
          <div style={{ display: stepCurrent === 0 ? 'block' : 'none' }}>
            <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
              <Input placeholder="例：AI推荐灰度-华中区域" />
            </Form.Item>
            <Form.Item name="feature_id" label="选择功能" rules={[{ required: true, message: '请选择功能' }]}>
              <Select
                placeholder="选择要灰度的功能"
                options={[]}
              />
            </Form.Item>
          </div>

          {/* Step 2: 配置策略 */}
          <div style={{ display: stepCurrent === 1 ? 'block' : 'none' }}>
            <Form.Item name="strategy" label="灰度策略" rules={[{ required: true, message: '请选择灰度策略' }]}>
              <Radio.Group>
                <Radio.Button value="percent">按门店百分比</Radio.Button>
                <Radio.Button value="whitelist">按门店白名单</Radio.Button>
                <Radio.Button value="user_trait">按用户特征</Radio.Button>
              </Radio.Group>
            </Form.Item>

            {strategyValue === 'percent' && (
              <Form.Item name="percent" label="灰度比例 (%)" initialValue={10}>
                <Slider min={1} max={100} marks={{ 1: '1%', 25: '25%', 50: '50%', 75: '75%', 100: '100%' }} />
              </Form.Item>
            )}
            {strategyValue === 'whitelist' && (
              <Form.Item name="store_whitelist" label="指定门店">
                <Select mode="tags" placeholder="输入门店名称，回车添加" />
              </Form.Item>
            )}
            {strategyValue === 'user_trait' && (
              <Form.Item name="user_trait" label="用户特征条件">
                <Select placeholder="选择用户特征" options={[
                  { label: '金卡及以上会员', value: '金卡及以上' },
                  { label: '注册超过1年', value: '注册超过1年' },
                  { label: '月消费超过500元', value: '月消费超过500元' },
                  { label: '近30天活跃用户', value: '近30天活跃用户' },
                ]} />
              </Form.Item>
            )}
          </div>

          {/* Step 3: 时间表 */}
          <div style={{ display: stepCurrent === 2 ? 'block' : 'none' }}>
            <Form.Item name="start_time" label="开始时间" rules={[{ required: true, message: '请选择开始时间' }]}>
              <DatePicker showTime style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="end_time" label="结束时间（可选）">
              <DatePicker showTime style={{ width: '100%' }} />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Tab3: 发布日志
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ReleaseLogsTab() {
  const [logs, setLogs] = useState<ReleaseLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterFeature, setFilterFeature] = useState<string>('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);

  const loadLogs = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/system/release-logs`, {
        headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (json.ok) {
        setLogs(json.data?.items ?? json.data ?? []);
      } else {
        setLogs([]);
      }
    } catch (_err: unknown) {
      setLogs([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadLogs(); }, []);

  const filtered = logs.filter(log => {
    if (filterFeature && log.feature_id !== filterFeature) return false;
    if (dateRange && dateRange[0] && dateRange[1]) {
      const logTime = dayjs(log.time);
      if (logTime.isBefore(dateRange[0], 'day') || logTime.isAfter(dateRange[1], 'day')) return false;
    }
    return true;
  });

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col>
          <Select
            placeholder="按功能筛选"
            value={filterFeature || undefined}
            onChange={v => setFilterFeature(v || '')}
            allowClear
            style={{ width: 200 }}
            options={logs.map(l => ({ label: l.feature_name, value: l.feature_id })).filter((v, i, arr) => arr.findIndex(x => x.value === v.value) === i)}
          />
        </Col>
        <Col>
          <RangePicker
            onChange={values => setDateRange(values as [Dayjs | null, Dayjs | null] | null)}
            placeholder={['开始日期', '结束日期']}
          />
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={loadLogs} loading={loading}>
            刷新
          </Button>
        </Col>
      </Row>

      {filtered.length === 0 ? (
        <Empty description="暂无发布日志" />
      ) : (
        <Timeline
          items={filtered.map(log => ({
            key: log.id,
            color: ACTION_COLORS[log.action],
            dot: log.action === '回滚' ? <WarningOutlined style={{ color: ACTION_COLORS['回滚'] }} /> : undefined,
            children: (
              <div>
                <Row align="middle" gutter={8}>
                  <Col>
                    <Tag color={ACTION_COLORS[log.action]}>{log.action}</Tag>
                  </Col>
                  <Col>
                    <Text strong>{log.feature_name}</Text>
                  </Col>
                </Row>
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    <ClockCircleOutlined style={{ marginRight: 4 }} />
                    {log.time}
                    <Divider type="vertical" />
                    操作人：{log.operator}
                    <Divider type="vertical" />
                    影响范围：{log.scope}
                  </Text>
                </div>
                {log.detail && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12, fontStyle: 'italic' }}>
                      {log.detail}
                    </Text>
                  </div>
                )}
              </div>
            ),
          }))}
        />
      )}
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Tab4: AB测试
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ABTestTab() {
  const [tests, setTests] = useState<ABTest[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const loadTests = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BASE}/api/v1/system/ab-tests`, {
        headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (json.ok) {
        setTests(json.data?.items ?? json.data ?? []);
      } else {
        setTests([]);
      }
    } catch (_err: unknown) {
      setTests([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadTests(); }, []);

  const handleCreate = async () => {
    const values = await form.validateFields();
    const newTest: ABTest = {
      id: `ab${Date.now()}`,
      name: values.name,
      feature_id: values.feature_id,
      feature_name: values.feature_id,
      group_a_ratio: values.group_a_ratio ?? 50,
      group_b_ratio: values.group_b_ratio ?? 50,
      metric: values.metric,
      metric_a: 0,
      metric_b: 0,
      status: 'running',
      duration_days: values.duration_days ?? 14,
      start_time: dayjs().format('YYYY-MM-DD HH:mm'),
    };
    setTests(prev => [newTest, ...prev]);
    setCreateOpen(false);
    form.resetFields();
    message.success('AB测试实验已创建');
  };

  const statusTagMap: Record<ABStatus, { color: string; label: string }> = {
    running: { color: 'processing', label: '运行中' },
    paused: { color: 'warning', label: '已暂停' },
    completed: { color: 'success', label: '已完成' },
  };

  const groupARatio = Form.useWatch('group_a_ratio', form);

  return (
    <div>
      <Row justify="end" style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}>
          创建实验
        </Button>
      </Row>

      <List
        loading={loading}
        dataSource={tests}
        locale={{ emptyText: <Empty description="暂无AB测试" /> }}
        renderItem={test => (
          <Card style={{ marginBottom: 16 }} bodyStyle={{ padding: '16px 24px' }}>
            <Row gutter={24} align="middle">
              <Col flex="1">
                <Space direction="vertical" size={4}>
                  <Space>
                    <Text strong style={{ fontSize: 15 }}>{test.name}</Text>
                    <Tag color={statusTagMap[test.status].color}>{statusTagMap[test.status].label}</Tag>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    功能：{test.feature_name}
                    <Divider type="vertical" />
                    A组 {test.group_a_ratio}% / B组 {test.group_b_ratio}%
                    <Divider type="vertical" />
                    观测指标：{test.metric}
                    <Divider type="vertical" />
                    时长：{test.duration_days}天
                  </Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    开始时间：{test.start_time}
                  </Text>
                </Space>
              </Col>
              <Col>
                <div style={{ textAlign: 'center' }}>
                  <SimpleBarChart
                    labelA="A组"
                    labelB="B组"
                    valueA={test.metric_a}
                    valueB={test.metric_b}
                    metric={test.metric}
                  />
                  {test.metric_a > 0 || test.metric_b > 0 ? (
                    <div style={{ marginTop: 4 }}>
                      {test.metric_b > test.metric_a ? (
                        <Text style={{ fontSize: 12, color: '#52C41A' }}>
                          B组领先 +{((test.metric_b - test.metric_a) / test.metric_a * 100).toFixed(1)}%
                        </Text>
                      ) : test.metric_a > test.metric_b ? (
                        <Text style={{ fontSize: 12, color: '#FF6B35' }}>
                          A组领先 +{((test.metric_a - test.metric_b) / test.metric_b * 100).toFixed(1)}%
                        </Text>
                      ) : (
                        <Text style={{ fontSize: 12, color: '#8C8C8C' }}>持平</Text>
                      )}
                    </div>
                  ) : (
                    <Text type="secondary" style={{ fontSize: 12 }}>等待数据收集</Text>
                  )}
                </div>
              </Col>
            </Row>
          </Card>
        )}
      />

      {/* 创建实验 Modal */}
      <Modal
        title="创建AB测试实验"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        onOk={handleCreate}
        okText="创建实验"
        cancelText="取消"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="实验名称" rules={[{ required: true, message: '请输入实验名称' }]}>
            <Input placeholder="例：AI推荐算法V2 vs V1" />
          </Form.Item>
          <Form.Item name="feature_id" label="关联功能" rules={[{ required: true, message: '请选择功能' }]}>
            <Select
              placeholder="选择功能"
              options={tests.map(t => ({ label: t.feature_name, value: t.feature_id })).filter((v, i, arr) => arr.findIndex(x => x.value === v.value) === i)}
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="group_a_ratio" label="A组比例 (%)" initialValue={50}>
                <InputNumber min={1} max={99} style={{ width: '100%' }} onChange={() => {
                  const aVal = form.getFieldValue('group_a_ratio');
                  if (typeof aVal === 'number') {
                    form.setFieldValue('group_b_ratio', 100 - aVal);
                  }
                }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="group_b_ratio" label="B组比例 (%)">
                <InputNumber disabled value={typeof groupARatio === 'number' ? 100 - groupARatio : 50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="metric" label="观测指标" rules={[{ required: true, message: '请选择观测指标' }]}>
            <Select placeholder="选择指标" options={[
              { label: '转化率', value: '转化率' },
              { label: '客单价', value: '客单价' },
              { label: '复购率', value: '复购率' },
              { label: '使用率', value: '使用率' },
              { label: '满意度评分', value: '满意度评分' },
            ]} />
          </Form.Item>
          <Form.Item name="duration_days" label="实验时长（天）" initialValue={14}>
            <InputNumber min={1} max={90} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主页面
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function FeatureFlagPage() {
  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>
      <Space align="center" style={{ marginBottom: 20 }}>
        <FlagOutlined style={{ fontSize: 24, color: '#FF6B35' }} />
        <Title level={3} style={{ margin: 0 }}>灰度发布管理</Title>
      </Space>

      <Tabs
        defaultActiveKey="flags"
        type="card"
        items={[
          {
            key: 'flags',
            label: (
              <span><ThunderboltOutlined /> 功能开关</span>
            ),
            children: <FeatureFlagsTab />,
          },
          {
            key: 'gray',
            label: (
              <span><BranchesOutlined /> 灰度规则</span>
            ),
            children: <GrayRulesTab />,
          },
          {
            key: 'logs',
            label: (
              <span><HistoryOutlined /> 发布日志</span>
            ),
            children: <ReleaseLogsTab />,
          },
          {
            key: 'ab',
            label: (
              <span><ExperimentOutlined /> AB测试</span>
            ),
            children: <ABTestTab />,
          },
        ]}
      />
    </div>
  );
}

export default FeatureFlagPage;
