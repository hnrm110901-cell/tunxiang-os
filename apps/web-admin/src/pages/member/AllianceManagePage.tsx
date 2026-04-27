/**
 * AllianceManagePage — 跨品牌联盟忠诚度管理
 * 合作伙伴列表 / CRUD / 激活暂停 / 兑换历史 / 联盟仪表盘
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Col,
  Row,
  Tag,
  Button,
  Table,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  DatePicker,
  Typography,
  Space,
  Statistic,
  Spin,
  message,
  Tooltip,
  Popconfirm,
  Tabs,
  Descriptions,
} from 'antd';
import {
  GlobalOutlined,
  PlusOutlined,
  EditOutlined,
  SwapOutlined,
  CheckCircleOutlined,
  PauseCircleOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  TeamOutlined,
  ReloadOutlined,
  BankOutlined,
  ShoppingOutlined,
  SmileOutlined,
  ThunderboltOutlined,
  HomeOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 类型 ───────────────────────────────────────────────────────────────────

interface Partner {
  id: string;
  tenant_id: string;
  partner_name: string;
  partner_type: string;
  partner_brand_logo: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  exchange_rate_out: number;
  exchange_rate_in: number;
  daily_exchange_limit: number;
  status: string;
  contract_start: string | null;
  contract_end: string | null;
  total_points_exchanged_out: number;
  total_points_exchanged_in: number;
  created_at: string;
  updated_at: string;
}

interface Transaction {
  id: string;
  partner_id: string;
  partner_name: string;
  customer_id: string;
  direction: string;
  points_amount: number;
  converted_points: number;
  exchange_rate: number;
  coupon_id: string | null;
  coupon_name: string | null;
  status: string;
  failure_reason: string | null;
  completed_at: string | null;
  created_at: string;
}

interface DashboardStats {
  total_partners: number;
  active_partners: number;
  pending_partners: number;
  suspended_partners: number;
  total_points_out: number;
  total_points_in: number;
  top_partners: Array<{
    id: string;
    partner_name: string;
    partner_type: string;
    status: string;
    total_points_exchanged_out: number;
    total_points_exchanged_in: number;
    total_volume: number;
  }>;
}

// ─── 常量 ───────────────────────────────────────────────────────────────────

const PARTNER_TYPES = [
  { value: 'restaurant', label: '餐饮', icon: <SmileOutlined /> },
  { value: 'retail', label: '零售', icon: <ShoppingOutlined /> },
  { value: 'entertainment', label: '娱乐', icon: <ThunderboltOutlined /> },
  { value: 'fitness', label: '健身', icon: <TeamOutlined /> },
  { value: 'hotel', label: '酒店', icon: <HomeOutlined /> },
  { value: 'other', label: '其他', icon: <AppstoreOutlined /> },
];

const STATUS_MAP: Record<string, { text: string; color: string }> = {
  pending: { text: '待审核', color: 'default' },
  active: { text: '活跃', color: 'success' },
  suspended: { text: '已暂停', color: 'warning' },
  terminated: { text: '已终止', color: 'error' },
};

const TYPE_COLOR_MAP: Record<string, string> = {
  restaurant: 'orange',
  retail: 'blue',
  entertainment: 'purple',
  fitness: 'green',
  hotel: 'cyan',
  other: 'default',
};

const getTypeLabel = (type: string) => {
  const found = PARTNER_TYPES.find((t) => t.value === type);
  return found?.label || type;
};

// ─── 组件 ───────────────────────────────────────────────────────────────────

export default function AllianceManagePage() {
  const [partners, setPartners] = useState<Partner[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingPartner, setEditingPartner] = useState<Partner | null>(null);
  const [filterStatus, setFilterStatus] = useState<string | undefined>();
  const [filterType, setFilterType] = useState<string | undefined>();
  const [form] = Form.useForm();

  // 交易历史
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [txLoading, setTxLoading] = useState(false);
  const [txCustomerId, setTxCustomerId] = useState('');

  // 仪表盘
  const [dashboard, setDashboard] = useState<DashboardStats | null>(null);
  const [dashLoading, setDashLoading] = useState(false);

  const [activeTab, setActiveTab] = useState('partners');

  // ── 加载合作伙伴列表 ──

  const fetchPartners = useCallback(async () => {
    setLoading(true);
    try {
      const params: string[] = ['size=100'];
      if (filterStatus) params.push(`status=${filterStatus}`);
      if (filterType) params.push(`type=${filterType}`);
      const res = await txFetchData(`/api/v1/member/alliance/partners?${params.join('&')}`);
      if (res?.ok) {
        setPartners(res.data.items || []);
      }
    } catch {
      message.error('加载合作伙伴失败');
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterType]);

  // ── 加载仪表盘 ──

  const fetchDashboard = useCallback(async () => {
    setDashLoading(true);
    try {
      const res = await txFetchData('/api/v1/member/alliance/dashboard');
      if (res?.ok) {
        setDashboard(res.data);
      }
    } catch {
      message.error('加载仪表盘失败');
    } finally {
      setDashLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'partners') fetchPartners();
    if (activeTab === 'dashboard') fetchDashboard();
  }, [activeTab, fetchPartners, fetchDashboard]);

  // ── 创建/编辑 ──

  const openCreate = () => {
    setEditingPartner(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (partner: Partner) => {
    setEditingPartner(partner);
    form.setFieldsValue({
      partner_name: partner.partner_name,
      partner_type: partner.partner_type,
      partner_brand_logo: partner.partner_brand_logo,
      contact_name: partner.contact_name,
      contact_phone: partner.contact_phone,
      contact_email: partner.contact_email,
      exchange_rate_out: partner.exchange_rate_out,
      exchange_rate_in: partner.exchange_rate_in,
      daily_exchange_limit: partner.daily_exchange_limit,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const payload = {
        partner_name: values.partner_name,
        partner_type: values.partner_type,
        partner_brand_logo: values.partner_brand_logo || null,
        contact_name: values.contact_name || null,
        contact_phone: values.contact_phone || null,
        contact_email: values.contact_email || null,
        exchange_rate_out: values.exchange_rate_out ?? 1.0,
        exchange_rate_in: values.exchange_rate_in ?? 1.0,
        daily_exchange_limit: values.daily_exchange_limit ?? 1000,
        contract_start: values.contract_range?.[0]?.format('YYYY-MM-DD') || null,
        contract_end: values.contract_range?.[1]?.format('YYYY-MM-DD') || null,
        terms_summary: values.terms_summary || null,
      };

      if (editingPartner) {
        const res = await txFetchData(`/api/v1/member/alliance/partners/${editingPartner.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        if (res?.ok) message.success('更新成功');
      } else {
        const res = await txFetchData('/api/v1/member/alliance/partners', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        if (res?.ok) message.success('创建成功');
      }
      setModalOpen(false);
      fetchPartners();
    } catch {
      // form validation error
    }
  };

  // ── 激活/暂停 ──

  const handleActivate = async (id: string) => {
    const res = await txFetchData(`/api/v1/member/alliance/partners/${id}/activate`, {
      method: 'PUT',
    });
    if (res?.ok) {
      message.success('已激活');
      fetchPartners();
    } else {
      message.error(res?.error?.message || '操作失败');
    }
  };

  const handleSuspend = async (id: string) => {
    const res = await txFetchData(`/api/v1/member/alliance/partners/${id}/suspend`, {
      method: 'PUT',
    });
    if (res?.ok) {
      message.success('已暂停');
      fetchPartners();
    } else {
      message.error(res?.error?.message || '操作失败');
    }
  };

  // ── 交易查询 ──

  const fetchTransactions = async (customerId?: string) => {
    if (!customerId) return;
    setTxLoading(true);
    try {
      const res = await txFetchData(
        `/api/v1/member/alliance/transactions?customer_id=${customerId}&size=50`
      );
      if (res?.ok) {
        setTransactions(res.data.items || []);
      }
    } catch {
      message.error('加载交易记录失败');
    } finally {
      setTxLoading(false);
    }
  };

  // ── 合作伙伴表格列 ──

  const partnerColumns = [
    {
      title: '合作伙伴',
      dataIndex: 'partner_name',
      key: 'partner_name',
      render: (name: string, record: Partner) => (
        <Space>
          <BankOutlined />
          <Text strong>{name}</Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'partner_type',
      key: 'partner_type',
      render: (type: string) => (
        <Tag color={TYPE_COLOR_MAP[type] || 'default'}>{getTypeLabel(type)}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const info = STATUS_MAP[status] || { text: status, color: 'default' };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '兑出率',
      dataIndex: 'exchange_rate_out',
      key: 'exchange_rate_out',
      render: (rate: number) => (
        <Tooltip title="1 我方积分 = X 对方积分">
          <Text>1 : {rate}</Text>
        </Tooltip>
      ),
    },
    {
      title: '兑入率',
      dataIndex: 'exchange_rate_in',
      key: 'exchange_rate_in',
      render: (rate: number) => (
        <Tooltip title="1 对方积分 = X 我方积分">
          <Text>1 : {rate}</Text>
        </Tooltip>
      ),
    },
    {
      title: '每日限额',
      dataIndex: 'daily_exchange_limit',
      key: 'daily_exchange_limit',
      render: (limit: number) => <Text>{limit.toLocaleString()}</Text>,
    },
    {
      title: '累计兑出',
      dataIndex: 'total_points_exchanged_out',
      key: 'total_points_exchanged_out',
      render: (val: number) => (
        <Space>
          <ArrowUpOutlined style={{ color: '#f5222d' }} />
          <Text>{(val || 0).toLocaleString()}</Text>
        </Space>
      ),
    },
    {
      title: '累计兑入',
      dataIndex: 'total_points_exchanged_in',
      key: 'total_points_exchanged_in',
      render: (val: number) => (
        <Space>
          <ArrowDownOutlined style={{ color: '#52c41a' }} />
          <Text>{(val || 0).toLocaleString()}</Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: Partner) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          {record.status === 'pending' && (
            <Popconfirm title="确认激活该合作伙伴？" onConfirm={() => handleActivate(record.id)}>
              <Button size="small" type="primary" icon={<CheckCircleOutlined />}>
                激活
              </Button>
            </Popconfirm>
          )}
          {record.status === 'active' && (
            <Popconfirm title="确认暂停该合作伙伴？" onConfirm={() => handleSuspend(record.id)}>
              <Button size="small" danger icon={<PauseCircleOutlined />}>
                暂停
              </Button>
            </Popconfirm>
          )}
          {record.status === 'suspended' && (
            <Popconfirm title="确认重新激活？" onConfirm={() => handleActivate(record.id)}>
              <Button size="small" type="primary" ghost icon={<CheckCircleOutlined />}>
                重新激活
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ── 交易表格列 ──

  const txColumns = [
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      render: (dir: string) =>
        dir === 'outbound' ? (
          <Tag icon={<ArrowUpOutlined />} color="red">
            兑出
          </Tag>
        ) : (
          <Tag icon={<ArrowDownOutlined />} color="green">
            兑入
          </Tag>
        ),
    },
    {
      title: '合作伙伴',
      dataIndex: 'partner_name',
      key: 'partner_name',
    },
    {
      title: '原始积分',
      dataIndex: 'points_amount',
      key: 'points_amount',
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '转换积分',
      dataIndex: 'converted_points',
      key: 'converted_points',
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: '兑换率',
      dataIndex: 'exchange_rate',
      key: 'exchange_rate',
    },
    {
      title: '优惠券',
      dataIndex: 'coupon_name',
      key: 'coupon_name',
      render: (name: string | null) => name || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const map: Record<string, { text: string; color: string }> = {
          pending: { text: '处理中', color: 'processing' },
          completed: { text: '已完成', color: 'success' },
          failed: { text: '失败', color: 'error' },
          reversed: { text: '已撤销', color: 'warning' },
        };
        const info = map[status] || { text: status, color: 'default' };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => (val ? new Date(val).toLocaleString('zh-CN') : '-'),
    },
  ];

  // ── 渲染 ──

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <GlobalOutlined /> 跨品牌联盟管理
      </Title>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'partners',
            label: '合作伙伴',
            children: (
              <>
                {/* 筛选栏 */}
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Space wrap>
                    <Select
                      placeholder="状态筛选"
                      allowClear
                      style={{ width: 140 }}
                      value={filterStatus}
                      onChange={setFilterStatus}
                      options={[
                        { value: 'pending', label: '待审核' },
                        { value: 'active', label: '活跃' },
                        { value: 'suspended', label: '已暂停' },
                        { value: 'terminated', label: '已终止' },
                      ]}
                    />
                    <Select
                      placeholder="类型筛选"
                      allowClear
                      style={{ width: 140 }}
                      value={filterType}
                      onChange={setFilterType}
                      options={PARTNER_TYPES.map((t) => ({ value: t.value, label: t.label }))}
                    />
                    <Button icon={<ReloadOutlined />} onClick={fetchPartners}>
                      刷新
                    </Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                      新增合作伙伴
                    </Button>
                  </Space>
                </Card>

                {/* 合作伙伴表格 */}
                <Table
                  loading={loading}
                  dataSource={partners}
                  columns={partnerColumns}
                  rowKey="id"
                  pagination={{ pageSize: 20 }}
                  size="middle"
                />
              </>
            ),
          },
          {
            key: 'transactions',
            label: '兑换历史',
            children: (
              <>
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Space>
                    <Input
                      placeholder="输入客户ID查询"
                      value={txCustomerId}
                      onChange={(e) => setTxCustomerId(e.target.value)}
                      style={{ width: 320 }}
                    />
                    <Button
                      type="primary"
                      icon={<SwapOutlined />}
                      onClick={() => fetchTransactions(txCustomerId)}
                    >
                      查询
                    </Button>
                  </Space>
                </Card>

                <Table
                  loading={txLoading}
                  dataSource={transactions}
                  columns={txColumns}
                  rowKey="id"
                  pagination={{ pageSize: 20 }}
                  size="middle"
                />
              </>
            ),
          },
          {
            key: 'dashboard',
            label: '联盟仪表盘',
            children: (
              <Spin spinning={dashLoading}>
                {dashboard && (
                  <>
                    {/* 统计卡片 */}
                    <Row gutter={16} style={{ marginBottom: 24 }}>
                      <Col span={6}>
                        <Card>
                          <Statistic
                            title="合作伙伴总数"
                            value={dashboard.total_partners}
                            prefix={<TeamOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card>
                          <Statistic
                            title="活跃伙伴"
                            value={dashboard.active_partners}
                            prefix={<CheckCircleOutlined />}
                            valueStyle={{ color: '#52c41a' }}
                          />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card>
                          <Statistic
                            title="积分兑出总量"
                            value={dashboard.total_points_out}
                            prefix={<ArrowUpOutlined />}
                            valueStyle={{ color: '#f5222d' }}
                          />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card>
                          <Statistic
                            title="积分兑入总量"
                            value={dashboard.total_points_in}
                            prefix={<ArrowDownOutlined />}
                            valueStyle={{ color: '#52c41a' }}
                          />
                        </Card>
                      </Col>
                    </Row>

                    {/* 兑换量排名 */}
                    <Card title="合作伙伴兑换量排名 (Top 10)">
                      <Table
                        dataSource={dashboard.top_partners}
                        rowKey="id"
                        pagination={false}
                        size="small"
                        columns={[
                          {
                            title: '合作伙伴',
                            dataIndex: 'partner_name',
                            key: 'partner_name',
                            render: (name: string) => <Text strong>{name}</Text>,
                          },
                          {
                            title: '类型',
                            dataIndex: 'partner_type',
                            key: 'partner_type',
                            render: (type: string) => (
                              <Tag color={TYPE_COLOR_MAP[type] || 'default'}>
                                {getTypeLabel(type)}
                              </Tag>
                            ),
                          },
                          {
                            title: '状态',
                            dataIndex: 'status',
                            key: 'status',
                            render: (s: string) => {
                              const info = STATUS_MAP[s] || { text: s, color: 'default' };
                              return <Tag color={info.color}>{info.text}</Tag>;
                            },
                          },
                          {
                            title: '兑出',
                            dataIndex: 'total_points_exchanged_out',
                            key: 'out',
                            render: (v: number) => (v || 0).toLocaleString(),
                          },
                          {
                            title: '兑入',
                            dataIndex: 'total_points_exchanged_in',
                            key: 'in',
                            render: (v: number) => (v || 0).toLocaleString(),
                          },
                          {
                            title: '总量',
                            dataIndex: 'total_volume',
                            key: 'total_volume',
                            render: (v: number) => <Text strong>{(v || 0).toLocaleString()}</Text>,
                          },
                        ]}
                      />
                    </Card>
                  </>
                )}
              </Spin>
            ),
          },
        ]}
      />

      {/* 创建/编辑 Modal */}
      <Modal
        title={editingPartner ? '编辑合作伙伴' : '新增合作伙伴'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="partner_name"
                label="合作伙伴名称"
                rules={[{ required: true, message: '请输入名称' }]}
              >
                <Input maxLength={200} placeholder="例如：星巴克" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="partner_type"
                label="类型"
                rules={[{ required: true, message: '请选择类型' }]}
              >
                <Select
                  options={PARTNER_TYPES.map((t) => ({ value: t.value, label: t.label }))}
                  placeholder="选择合作类型"
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="contact_name" label="联系人">
                <Input maxLength={100} placeholder="联系人姓名" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="contact_phone" label="联系电话">
                <Input maxLength={30} placeholder="手机号" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="contact_email" label="邮箱">
                <Input maxLength={200} placeholder="email" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="exchange_rate_out" label="兑出率 (1我方=X对方)">
                <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="exchange_rate_in" label="兑入率 (1对方=X我方)">
                <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="daily_exchange_limit" label="每日兑换限额">
                <InputNumber min={1} step={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="partner_brand_logo" label="品牌Logo URL">
            <Input maxLength={500} placeholder="https://..." />
          </Form.Item>
          <Form.Item name="contract_range" label="合同期限">
            <RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="terms_summary" label="合作条款摘要">
            <Input.TextArea rows={3} placeholder="简要描述合作条款..." />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
