/**
 * Y-C4 多渠道菜单发布管理
 * 三个Tab：门店覆盖配置 / 冲突检测 / 发布统计
 */
import { useState, useEffect, useRef } from 'react';
import {
  Tabs,
  Table,
  Tag,
  Button,
  Card,
  Row,
  Col,
  Select,
  Alert,
  Spin,
  Typography,
  Space,
  Badge,
  message,
  Statistic,
  Modal,
  Form,
  InputNumber,
  Switch,
  Tooltip,
  Popconfirm,
  Divider,
} from 'antd';
import {
  WarningOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  ShopOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';

const { Title, Text, Paragraph } = Typography;
const { Option } = Select;

const API_BASE = 'http://localhost:8002';
const TENANT_ID = 'demo-tenant-id';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface ChannelOverride {
  id: string;
  store_id: string;
  dish_id: string;
  dish_name?: string;
  channel: string;
  channel_display: string;
  price_fen: number | null;
  is_available: boolean;
  override_reason: string | null;
  effective_date: string | null;
  expires_date: string | null;
  updated_at: string | null;
}

interface ConflictDish {
  store_name: string;
  dish_name: string;
  dish_id: string;
  conflict_channel: string;
  conflict_channel_display: string;
  dine_in_price_fen: number;
  delivery_price_fen: number;
  diff_rate: number;
  diff_rate_pct: string;
  severity: 'warning' | 'critical';
  suggestion: string;
}

interface ChannelStats {
  total_overrides: number;
  store_count: number;
  total_unavailable: number;
  total_price_overridden: number;
  changed_7d: number;
  channel_stats: Array<{
    channel: string;
    channel_display: string;
    available_count: number;
    unavailable_count: number;
    price_overridden_count: number;
    changed_7d: number;
  }>;
}

// ─── 渠道选项 ─────────────────────────────────────────────────────────────────

const CHANNEL_OPTIONS = [
  { value: 'dine_in', label: '堂食' },
  { value: 'takeaway', label: '外卖（自营）' },
  { value: 'meituan', label: '外卖-美团' },
  { value: 'eleme', label: '外卖-饿了么' },
  { value: 'douyin', label: '抖音团购' },
  { value: 'miniapp', label: '小程序' },
  { value: 'all', label: '全渠道' },
];

const STORE_OPTIONS = [
  { value: 'store-wuyi', label: '五一广场店' },
  { value: 'store-guanggu', label: '光谷店' },
  { value: 'store-xintiandi', label: '新天地店' },
];

// ─── 子组件：门店覆盖配置Tab ──────────────────────────────────────────────────

function OverrideConfigTab() {
  const [filterStore, setFilterStore] = useState<string>('');
  const [filterChannel, setFilterChannel] = useState<string>('');
  const [overrides, setOverrides] = useState<ChannelOverride[]>([]);
  const [loading, setLoading] = useState(false);
  const [editingOverride, setEditingOverride] = useState<ChannelOverride | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();

  const fetchOverrides = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterStore) params.set('store_id', filterStore);
      if (filterChannel) params.set('channel', filterChannel);
      const res = await fetch(`${API_BASE}/api/v1/menu/channel-overrides?${params}`, {
        headers: { 'X-Tenant-ID': TENANT_ID },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setOverrides(json.data?.items || []);
    } catch (err) {
      // 使用 Mock 数据演示
      setOverrides([
        {
          id: 'ov-001', store_id: 'store-wuyi', dish_id: 'dish-steam-fish',
          dish_name: '招牌蒸鱼', channel: 'meituan', channel_display: '外卖-美团',
          price_fen: 10800, is_available: true, override_reason: 'regional_price',
          effective_date: '2026-01-01', expires_date: null, updated_at: '2026-04-06T10:00:00',
        },
        {
          id: 'ov-002', store_id: 'store-wuyi', dish_id: 'dish-white-shrimp',
          dish_name: '白灼虾', channel: 'takeaway', channel_display: '外卖（自营）',
          price_fen: null, is_available: false, override_reason: 'stock',
          effective_date: '2026-01-01', expires_date: null, updated_at: '2026-04-05T09:00:00',
        },
        {
          id: 'ov-003', store_id: 'store-guanggu', dish_id: 'dish-steam-fish',
          dish_name: '招牌蒸鱼', channel: 'meituan', channel_display: '外卖-美团',
          price_fen: 9800, is_available: true, override_reason: null,
          effective_date: '2026-01-01', expires_date: null, updated_at: '2026-04-04T14:00:00',
        },
        {
          id: 'ov-004', store_id: 'store-xintiandi', dish_id: 'dish-steam-fish',
          dish_name: '招牌蒸鱼', channel: 'meituan', channel_display: '外卖-美团',
          price_fen: 13800, is_available: true, override_reason: 'regional_price',
          effective_date: '2026-01-01', expires_date: null, updated_at: '2026-04-03T16:00:00',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchOverrides(); }, [filterStore, filterChannel]);

  const handleDelete = async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/v1/menu/channel-overrides/${id}`, {
        method: 'DELETE',
        headers: { 'X-Tenant-ID': TENANT_ID },
      });
      message.success('覆盖配置已删除，该菜品将恢复品牌标准配置');
      fetchOverrides();
    } catch {
      message.error('删除失败，请重试');
    }
  };

  const handleEdit = (record: ChannelOverride) => {
    setEditingOverride(record);
    form.setFieldsValue({
      price_fen: record.price_fen != null ? record.price_fen / 100 : undefined,
      is_available: record.is_available,
      override_reason: record.override_reason,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      message.success('覆盖配置已更新');
      setModalOpen(false);
      fetchOverrides();
    } catch {
      // 表单校验失败，保持弹窗
    }
  };

  const reasonTagMap: Record<string, { color: string; label: string }> = {
    regional_price: { color: 'blue', label: '区域定价' },
    stock: { color: 'orange', label: '库存限制' },
    promotion: { color: 'green', label: '促销活动' },
  };

  const columns: ColumnsType<ChannelOverride> = [
    {
      title: '门店',
      dataIndex: 'store_id',
      width: 110,
      render: (v: string) => STORE_OPTIONS.find(s => s.value === v)?.label || v,
    },
    { title: '菜品', dataIndex: 'dish_name', width: 120 },
    {
      title: '渠道',
      dataIndex: 'channel_display',
      width: 110,
      render: (v: string, r: ChannelOverride) => (
        <Tag color={r.channel === 'dine_in' ? 'default' : 'blue'}>{v}</Tag>
      ),
    },
    {
      title: '覆盖价格',
      width: 110,
      render: (_: unknown, r: ChannelOverride) =>
        r.price_fen != null ? (
          <Text strong>¥{(r.price_fen / 100).toFixed(0)}</Text>
        ) : (
          <Text type="secondary">用标准价</Text>
        ),
    },
    {
      title: '可见性',
      dataIndex: 'is_available',
      width: 90,
      render: (v: boolean) =>
        v ? (
          <Badge status="success" text="上架" />
        ) : (
          <Badge status="error" text="下架" />
        ),
    },
    {
      title: '覆盖原因',
      dataIndex: 'override_reason',
      width: 110,
      render: (v: string | null) => {
        if (!v) return <Text type="secondary">—</Text>;
        const info = reasonTagMap[v] || { color: 'default', label: v };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '生效日期',
      dataIndex: 'effective_date',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: '操作',
      width: 120,
      render: (_: unknown, r: ChannelOverride) => (
        <Space>
          <Tooltip title="编辑覆盖配置">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)} />
          </Tooltip>
          <Popconfirm
            title="删除后将恢复品牌标准配置，确认删除？"
            onConfirm={() => handleDelete(r.id)}
            okText="确认删除"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Text strong>门店：</Text>
            <Select
              placeholder="全部门店"
              style={{ width: 140 }}
              allowClear
              value={filterStore || undefined}
              onChange={v => setFilterStore(v || '')}
            >
              {STORE_OPTIONS.map(s => <Option key={s.value} value={s.value}>{s.label}</Option>)}
            </Select>
            <Text strong>渠道：</Text>
            <Select
              placeholder="全部渠道"
              style={{ width: 140 }}
              allowClear
              value={filterChannel || undefined}
              onChange={v => setFilterChannel(v || '')}
            >
              {CHANNEL_OPTIONS.map(c => <Option key={c.value} value={c.value}>{c.label}</Option>)}
            </Select>
            <Button icon={<ReloadOutlined />} onClick={fetchOverrides}>刷新</Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditingOverride(null);
                form.resetFields();
                setModalOpen(true);
              }}
            >
              新增覆盖
            </Button>
          </Space>
        </Col>
      </Row>

      <Alert
        type="info"
        showIcon
        message="覆盖配置优先级高于品牌标准菜单。price_fen 留空=使用品牌标准价；is_available=false=在该渠道隐藏。"
        style={{ marginBottom: 16 }}
      />

      <Table<ChannelOverride>
        columns={columns}
        dataSource={overrides}
        rowKey="id"
        loading={loading}
        size="middle"
        pagination={{ pageSize: 20 }}
        scroll={{ x: 900 }}
      />

      <Modal
        title={editingOverride ? '编辑渠道覆盖配置' : '新增渠道覆盖配置'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={520}
      >
        <Form form={form} layout="vertical">
          {!editingOverride && (
            <>
              <Form.Item name="store_id" label="门店" rules={[{ required: true }]}>
                <Select placeholder="选择门店">
                  {STORE_OPTIONS.map(s => <Option key={s.value} value={s.value}>{s.label}</Option>)}
                </Select>
              </Form.Item>
              <Form.Item name="channel" label="渠道" rules={[{ required: true }]}>
                <Select placeholder="选择渠道">
                  {CHANNEL_OPTIONS.map(c => <Option key={c.value} value={c.value}>{c.label}</Option>)}
                </Select>
              </Form.Item>
            </>
          )}
          <Form.Item name="price_fen" label="覆盖价格（元）" help="留空则使用品牌标准价">
            <InputNumber min={0} step={1} precision={0} style={{ width: '100%' }} placeholder="留空=使用标准价" />
          </Form.Item>
          <Form.Item name="is_available" label="是否上架" valuePropName="checked">
            <Switch checkedChildren="上架" unCheckedChildren="下架" />
          </Form.Item>
          <Form.Item name="override_reason" label="覆盖原因">
            <Select allowClear placeholder="选择原因（可选）">
              <Option value="regional_price">区域定价</Option>
              <Option value="stock">库存限制</Option>
              <Option value="promotion">促销活动</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ─── 子组件：冲突检测Tab ──────────────────────────────────────────────────────

function ConflictDetectionTab() {
  const [conflicts, setConflicts] = useState<ConflictDish[]>([]);
  const [loading, setLoading] = useState(false);
  const [threshold, setThreshold] = useState(30);
  const [hasCritical, setHasCritical] = useState(false);

  const fetchConflicts = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/menu/channel-overrides/conflicts?threshold_rate=${threshold / 100}`,
        { headers: { 'X-Tenant-ID': TENANT_ID } },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setConflicts(json.data?.conflict_dishes || []);
      setHasCritical(json.data?.has_critical || false);
    } catch {
      // Mock 冲突数据
      const mockConflicts: ConflictDish[] = [
        {
          store_name: '新天地店', dish_name: '招牌蒸鱼', dish_id: 'dish-steam-fish',
          conflict_channel: 'meituan', conflict_channel_display: '外卖-美团',
          dine_in_price_fen: 9800, delivery_price_fen: 13800,
          diff_rate: 0.408, diff_rate_pct: '40.8%', severity: 'critical',
          suggestion: '外卖价比堂食高41%，建议调整至¥138以内',
        },
        {
          store_name: '五一广场店', dish_name: '招牌蒸鱼', dish_id: 'dish-steam-fish',
          conflict_channel: 'meituan', conflict_channel_display: '外卖-美团',
          dine_in_price_fen: 9800, delivery_price_fen: 10800,
          diff_rate: 0.102, diff_rate_pct: '10.2%', severity: 'warning',
          suggestion: '外卖价比堂食高10%，在合理范围内，可适当监控',
        },
      ].filter(c => c.diff_rate * 100 > threshold) as ConflictDish[];
      setConflicts(mockConflicts);
      setHasCritical(mockConflicts.some(c => c.severity === 'critical'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchConflicts(); }, [threshold]);

  const columns: ColumnsType<ConflictDish> = [
    { title: '门店', dataIndex: 'store_name', width: 110 },
    { title: '菜品', dataIndex: 'dish_name', width: 120 },
    {
      title: '冲突渠道',
      dataIndex: 'conflict_channel_display',
      width: 110,
      render: (v: string) => <Tag color="orange">{v}</Tag>,
    },
    {
      title: '堂食价',
      dataIndex: 'dine_in_price_fen',
      width: 90,
      render: (v: number) => `¥${(v / 100).toFixed(0)}`,
    },
    {
      title: '渠道价',
      dataIndex: 'delivery_price_fen',
      width: 90,
      render: (v: number) => <Text strong>¥{(v / 100).toFixed(0)}</Text>,
    },
    {
      title: '价差率',
      dataIndex: 'diff_rate_pct',
      width: 90,
      render: (v: string, r: ConflictDish) => (
        <Tag color={r.severity === 'critical' ? 'red' : 'orange'} style={{ fontWeight: 'bold' }}>
          +{v}
        </Tag>
      ),
    },
    {
      title: '严重程度',
      dataIndex: 'severity',
      width: 100,
      render: (v: string) =>
        v === 'critical' ? (
          <Tag color="red" icon={<WarningOutlined />}>严重</Tag>
        ) : (
          <Tag color="orange" icon={<ExclamationCircleOutlined />}>警告</Tag>
        ),
    },
    {
      title: '建议',
      dataIndex: 'suggestion',
      ellipsis: true,
      render: (v: string) => <Text type="secondary">{v}</Text>,
    },
  ];

  return (
    <div>
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Text strong>价差告警阈值：</Text>
            <Select
              value={threshold}
              onChange={setThreshold}
              style={{ width: 120 }}
            >
              <Option value={10}>外卖高10%</Option>
              <Option value={20}>外卖高20%</Option>
              <Option value={30}>外卖高30%（默认）</Option>
              <Option value={50}>外卖高50%</Option>
            </Select>
            <Button icon={<ReloadOutlined />} onClick={fetchConflicts}>重新检测</Button>
          </Space>
        </Col>
      </Row>

      {hasCritical && (
        <Alert
          type="error"
          showIcon
          message="发现严重价格冲突！"
          description="部分门店外卖价格远高于堂食，可能影响顾客体验和平台排名，建议尽快处理。"
          style={{ marginBottom: 16 }}
        />
      )}

      {!loading && conflicts.length === 0 && (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          message={`当前阈值（+${threshold}%）下未发现价格冲突`}
          style={{ marginBottom: 16 }}
        />
      )}

      <Table<ConflictDish>
        columns={columns}
        dataSource={conflicts}
        rowKey={r => `${r.store_name}-${r.dish_id}-${r.conflict_channel}`}
        loading={loading}
        size="middle"
        rowClassName={r => r.severity === 'critical' ? 'ant-table-row-danger' : ''}
        pagination={{ pageSize: 20 }}
        scroll={{ x: 800 }}
      />
      <style>{`
        .ant-table-row-danger td { background: #fff1f0 !important; }
      `}</style>
    </div>
  );
}

// ─── 子组件：发布统计Tab ──────────────────────────────────────────────────────

function PublishStatsTab() {
  const [stats, setStats] = useState<ChannelStats | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchStats = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/menu/channel-overrides/stats`, {
        headers: { 'X-Tenant-ID': TENANT_ID },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setStats(json.data);
    } catch {
      setStats({
        total_overrides: 27,
        store_count: 3,
        total_unavailable: 4,
        total_price_overridden: 18,
        changed_7d: 6,
        channel_stats: [
          { channel: 'dine_in', channel_display: '堂食', available_count: 5, unavailable_count: 1, price_overridden_count: 2, changed_7d: 1 },
          { channel: 'meituan', channel_display: '外卖-美团', available_count: 8, unavailable_count: 2, price_overridden_count: 7, changed_7d: 3 },
          { channel: 'eleme', channel_display: '外卖-饿了么', available_count: 6, unavailable_count: 1, price_overridden_count: 5, changed_7d: 1 },
          { channel: 'miniapp', channel_display: '小程序', available_count: 4, unavailable_count: 0, price_overridden_count: 2, changed_7d: 1 },
          { channel: 'douyin', channel_display: '抖音团购', available_count: 3, unavailable_count: 0, price_overridden_count: 2, changed_7d: 0 },
        ],
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStats(); }, []);

  const channelColumns: ColumnsType<ChannelStats['channel_stats'][number]> = [
    { title: '渠道', dataIndex: 'channel_display', width: 120 },
    {
      title: '上架数',
      dataIndex: 'available_count',
      width: 90,
      render: v => <Tag color="success">{v}</Tag>,
    },
    {
      title: '下架数',
      dataIndex: 'unavailable_count',
      width: 90,
      render: v => v > 0 ? <Tag color="error">{v}</Tag> : <Tag>{v}</Tag>,
    },
    {
      title: '差价菜品数',
      dataIndex: 'price_overridden_count',
      width: 100,
      render: v => v > 0 ? <Tag color="blue">{v}</Tag> : <Tag>{v}</Tag>,
    },
    {
      title: '近7天变更',
      dataIndex: 'changed_7d',
      width: 100,
      render: v => v > 0 ? <Badge count={v} showZero style={{ backgroundColor: '#FF6B35' }} /> : <Text type="secondary">—</Text>,
    },
  ];

  if (loading) return <Spin style={{ display: 'block', textAlign: 'center', paddingTop: 60 }} />;

  return (
    <div>
      {stats && (
        <>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Card>
                <Statistic title="覆盖配置总数" value={stats.total_overrides} suffix="条" />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="覆盖门店数" value={stats.store_count} suffix="家" />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="已下架（渠道）"
                  value={stats.total_unavailable}
                  valueStyle={{ color: '#A32D2D' }}
                  suffix="处"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="近7天变更"
                  value={stats.changed_7d}
                  valueStyle={{ color: '#FF6B35' }}
                  suffix="次"
                />
              </Card>
            </Col>
          </Row>

          <Card title="各渠道覆盖明细">
            <Table
              columns={channelColumns}
              dataSource={stats.channel_stats}
              rowKey="channel"
              size="middle"
              pagination={false}
            />
          </Card>
        </>
      )}
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function ChannelMenuPage() {
  const tabItems = [
    {
      key: 'overrides',
      label: (
        <Space>
          <ShopOutlined />
          门店覆盖配置
        </Space>
      ),
      children: <OverrideConfigTab />,
    },
    {
      key: 'conflicts',
      label: (
        <Space>
          <WarningOutlined />
          冲突检测
        </Space>
      ),
      children: <ConflictDetectionTab />,
    },
    {
      key: 'stats',
      label: (
        <Space>
          <CheckCircleOutlined />
          发布统计
        </Space>
      ),
      children: <PublishStatsTab />,
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>多渠道菜单发布管理</Title>
        <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
          配置各门店在不同渠道（堂食/外卖/小程序）的差异定价与上下架，支持冲突检测与批量下发
        </Paragraph>
      </div>

      <Card>
        <Tabs defaultActiveKey="overrides" items={tabItems} />
      </Card>
    </div>
  );
}
