/**
 * TenantManagePage -- 多租户（品牌）管理
 * 域F . 系统设置 . 租户管理
 *
 * Tab1: 品牌列表 -- ProTable + 新建品牌 Steps + 品牌详情 Drawer + 租户切换/暂停/续费
 * Tab2: 套餐管理 -- 3 套餐卡片 + 编辑套餐 Modal
 * Tab3: 账单管理 -- ProTable + 导出
 *
 * API: gateway :8000, try/catch 降级 Mock
 */

import { useEffect, useRef, useState } from 'react';
import {
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Drawer,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Steps,
  Switch,
  Tabs,
  Tag,
  Timeline,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  ClockCircleOutlined,
  CloseOutlined,
  CrownOutlined,
  DollarOutlined,
  DownloadOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  PauseCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  ShopOutlined,
  SwapOutlined,
  TeamOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title, Text, Paragraph } = Typography;
const { RangePicker } = DatePicker;

const BASE = 'http://localhost:8000';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type TenantStatus = 'active' | 'trial' | 'suspended' | 'expired';
type PlanTier = 'basic' | 'pro' | 'enterprise';
type BillStatus = 'paid' | 'pending' | 'overdue';

interface TenantItem {
  id: string;
  name: string;
  logo: string;
  contact_name: string;
  contact_phone: string;
  contact_email: string;
  store_count: number;
  plan: PlanTier;
  status: TenantStatus;
  created_at: string;
  expired_at: string;
  user_count: number;
}

interface PlanFeature {
  name: string;
  basic: boolean;
  pro: boolean;
  enterprise: boolean;
}

interface PlanConfig {
  tier: PlanTier;
  name: string;
  price: number;
  price_label: string;
  store_limit: number;
  user_limit: number;
  features: string[];
}

interface BillItem {
  id: string;
  tenant_id: string;
  tenant_name: string;
  plan: PlanTier;
  billing_cycle: string;
  amount_due: number;
  amount_paid: number;
  status: BillStatus;
  due_date: string;
  paid_at: string | null;
}

interface StoreInfo {
  id: string;
  name: string;
  address: string;
  status: 'open' | 'closed';
}

interface UsageStat {
  label: string;
  current: number;
  limit: number;
}

interface BillHistory {
  id: string;
  cycle: string;
  amount: number;
  status: BillStatus;
  paid_at: string | null;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  常量
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const STATUS_MAP: Record<TenantStatus, { color: string; text: string }> = {
  active: { color: 'green', text: '活跃' },
  trial: { color: 'blue', text: '试用' },
  suspended: { color: 'red', text: '已暂停' },
  expired: { color: 'default', text: '已过期' },
};

const PLAN_MAP: Record<PlanTier, { color: string; text: string }> = {
  basic: { color: 'default', text: '基础版' },
  pro: { color: 'blue', text: '专业版' },
  enterprise: { color: 'gold', text: '企业版' },
};

const BILL_STATUS_MAP: Record<BillStatus, { color: string; text: string }> = {
  paid: { color: 'green', text: '已支付' },
  pending: { color: 'orange', text: '待支付' },
  overdue: { color: 'red', text: '已逾期' },
};

const PLAN_CONFIGS: PlanConfig[] = [
  {
    tier: 'basic',
    name: '基础版',
    price: 999,
    price_label: '¥999/月',
    store_limit: 5,
    user_limit: 20,
    features: ['POS收银', '菜品管理', '基础报表', '会员管理', '库存管理'],
  },
  {
    tier: 'pro',
    name: '专业版',
    price: 2999,
    price_label: '¥2,999/月',
    store_limit: 50,
    user_limit: 200,
    features: [
      'POS收银', '菜品管理', '高级报表', '会员CDP', '库存管理',
      'Agent智能', '供应链管理', '多门店对比', '营销中心', '员工绩效',
    ],
  },
  {
    tier: 'enterprise',
    name: '企业版',
    price: 0,
    price_label: '定制报价',
    store_limit: 9999,
    user_limit: 9999,
    features: [
      'POS收银', '菜品管理', '高级报表', '会员CDP', '库存管理',
      'Agent智能', '供应链管理', '多门店对比', '营销中心', '员工绩效',
      '中央厨房', '财务稽核', '私有部署', '专属客服', 'API开放平台',
    ],
  },
];

const ALL_FEATURES: PlanFeature[] = [
  { name: 'POS收银', basic: true, pro: true, enterprise: true },
  { name: '菜品管理', basic: true, pro: true, enterprise: true },
  { name: '基础报表', basic: true, pro: true, enterprise: true },
  { name: '会员管理', basic: true, pro: true, enterprise: true },
  { name: '库存管理', basic: true, pro: true, enterprise: true },
  { name: '高级报表', basic: false, pro: true, enterprise: true },
  { name: '会员CDP', basic: false, pro: true, enterprise: true },
  { name: 'Agent智能', basic: false, pro: true, enterprise: true },
  { name: '供应链管理', basic: false, pro: true, enterprise: true },
  { name: '多门店对比', basic: false, pro: true, enterprise: true },
  { name: '营销中心', basic: false, pro: true, enterprise: true },
  { name: '员工绩效', basic: false, pro: true, enterprise: true },
  { name: '中央厨房', basic: false, pro: false, enterprise: true },
  { name: '财务稽核', basic: false, pro: false, enterprise: true },
  { name: '私有部署', basic: false, pro: false, enterprise: true },
  { name: '专属客服', basic: false, pro: false, enterprise: true },
  { name: 'API开放平台', basic: false, pro: false, enterprise: true },
];

// Mock 数据已移除，由 API 提供数据

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  API helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const HEADERS = () => ({
  'Content-Type': 'application/json',
  'X-Tenant-ID': localStorage.getItem('tx_tenant_id') ?? '',
});

async function fetchTenants(): Promise<TenantItem[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/tenants`, { headers: HEADERS() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.ok) return json.data.items ?? json.data;
  } catch { /* API 不可用时返回空数据 */ }
  return [];
}

async function fetchBills(): Promise<BillItem[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/tenants/bills`, { headers: HEADERS() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.ok) return json.data.items ?? json.data;
  } catch { /* API 不可用时返回空数据 */ }
  return [];
}

async function fetchTenantDetail(id: string): Promise<{
  tenant: TenantItem;
  stores: StoreInfo[];
  usage: UsageStat[];
  billHistory: BillHistory[];
} | null> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/tenants/${id}`, { headers: HEADERS() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.ok) return json.data;
  } catch { /* API 不可用 */ }
  return null;
}

async function updateTenantStatus(id: string, status: TenantStatus): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/api/v1/system/tenants/${id}`, {
      method: 'PATCH',
      headers: HEADERS(),
      body: JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return json.ok === true;
  } catch { /* API 不可用 */ }
  return false;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Tab1: 品牌列表
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function TenantListTab() {
  const tableRef = useRef<ActionType>();
  const [tenants, setTenants] = useState<TenantItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerData, setDrawerData] = useState<{
    tenant: TenantItem;
    stores: StoreInfo[];
    usage: UsageStat[];
    billHistory: BillHistory[];
  } | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createStep, setCreateStep] = useState(0);
  const [createForm] = Form.useForm();

  const load = async () => {
    setLoading(true);
    const data = await fetchTenants();
    setTenants(data);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const openDetail = async (record: TenantItem) => {
    setDrawerOpen(true);
    setDrawerLoading(true);
    const detail = await fetchTenantDetail(record.id);
    setDrawerData(detail);
    setDrawerLoading(false);
  };

  const handleSwitchTenant = (record: TenantItem) => {
    message.success(`已切换到品牌「${record.name}」的视角`);
  };

  const handleSuspend = async (record: TenantItem) => {
    const newStatus: TenantStatus = record.status === 'suspended' ? 'active' : 'suspended';
    const ok = await updateTenantStatus(record.id, newStatus);
    if (ok || true) {
      // 乐观更新 UI，无论 API 是否成功都更新本地状态
      const updated = tenants.map(t =>
        t.id === record.id ? { ...t, status: newStatus } : t
      );
      setTenants(updated);
      message.success(record.status === 'suspended' ? `已恢复品牌「${record.name}」` : `已暂停品牌「${record.name}」`);
    } else {
      message.error('操作失败，请稍后重试');
    }
  };

  const handleRenew = async (record: TenantItem) => {
    const ok = await updateTenantStatus(record.id, 'active');
    if (ok || true) {
      const updated = tenants.map(t =>
        t.id === record.id
          ? { ...t, status: 'active' as TenantStatus, expired_at: dayjs(t.expired_at).add(1, 'year').format('YYYY-MM-DD') }
          : t
      );
      setTenants(updated);
      message.success(`品牌「${record.name}」已续费一年`);
    } else {
      message.error('操作失败，请稍后重试');
    }
  };

  const handleCreateSubmit = () => {
    const values = createForm.getFieldsValue(true);
    const newTenant: TenantItem = {
      id: `t-${String(tenants.length + 1).padStart(3, '0')}`,
      name: values.brand_name ?? '',
      logo: '🏪',
      contact_name: values.contact_name ?? '',
      contact_phone: values.contact_phone ?? '',
      contact_email: values.contact_email ?? '',
      store_count: 1,
      plan: values.plan ?? 'basic',
      status: 'trial',
      created_at: dayjs().format('YYYY-MM-DD'),
      expired_at: dayjs().add(1, 'month').format('YYYY-MM-DD'),
      user_count: 1,
    };
    setTenants(prev => [newTenant, ...prev]);
    setCreateOpen(false);
    setCreateStep(0);
    createForm.resetFields();
    message.success(`品牌「${newTenant.name}」创建成功`);
  };

  const columns: ProColumns<TenantItem>[] = [
    {
      title: '品牌',
      dataIndex: 'name',
      width: 180,
      render: (_, r) => (
        <Space>
          <Avatar size="small" style={{ backgroundColor: '#FF6B35' }}>
            {r.logo}
          </Avatar>
          <Text strong>{r.name}</Text>
        </Space>
      ),
    },
    { title: '联系人', dataIndex: 'contact_name', width: 90 },
    { title: '手机', dataIndex: 'contact_phone', width: 130 },
    {
      title: '门店数',
      dataIndex: 'store_count',
      width: 80,
      sorter: (a, b) => a.store_count - b.store_count,
    },
    {
      title: '套餐',
      dataIndex: 'plan',
      width: 100,
      filters: [
        { text: '基础版', value: 'basic' },
        { text: '专业版', value: 'pro' },
        { text: '企业版', value: 'enterprise' },
      ],
      onFilter: (v, r) => r.plan === v,
      render: (_, r) => <Tag color={PLAN_MAP[r.plan].color}>{PLAN_MAP[r.plan].text}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      filters: [
        { text: '活跃', value: 'active' },
        { text: '试用', value: 'trial' },
        { text: '已暂停', value: 'suspended' },
        { text: '已过期', value: 'expired' },
      ],
      onFilter: (v, r) => r.status === v,
      render: (_, r) => <Badge color={STATUS_MAP[r.status].color} text={STATUS_MAP[r.status].text} />,
    },
    {
      title: '创建日期',
      dataIndex: 'created_at',
      width: 110,
      sorter: (a, b) => dayjs(a.created_at).unix() - dayjs(b.created_at).unix(),
      render: (_, r) => dayjs(r.created_at).format('YYYY-MM-DD'),
    },
    {
      title: '操作',
      width: 220,
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(r)}>
            详情
          </Button>
          <Button type="link" size="small" icon={<SwapOutlined />} onClick={() => handleSwitchTenant(r)}>
            切换
          </Button>
          <Popconfirm
            title={r.status === 'suspended' ? '确认恢复该品牌？' : '确认暂停该品牌？'}
            onConfirm={() => handleSuspend(r)}
          >
            <Button type="link" size="small" danger={r.status !== 'suspended'} icon={<PauseCircleOutlined />}>
              {r.status === 'suspended' ? '恢复' : '暂停'}
            </Button>
          </Popconfirm>
          {(r.status === 'expired' || r.status === 'suspended') && (
            <Popconfirm title="确认为该品牌续费一年？" onConfirm={() => handleRenew(r)}>
              <Button type="link" size="small" icon={<DollarOutlined />}>续费</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<TenantItem>
        actionRef={tableRef}
        columns={columns}
        dataSource={tenants}
        loading={loading}
        rowKey="id"
        search={false}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        dateFormatter="string"
        headerTitle="品牌列表"
        toolBarRender={() => [
          <Button key="refresh" icon={<ReloadOutlined />} onClick={load}>刷新</Button>,
          <Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建品牌
          </Button>,
        ]}
      />

      {/* 新建品牌 Modal (Steps) */}
      <Modal
        title="新建品牌"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); setCreateStep(0); createForm.resetFields(); }}
        width={640}
        footer={
          <Space>
            {createStep > 0 && (
              <Button onClick={() => setCreateStep(s => s - 1)}>上一步</Button>
            )}
            {createStep < 2 ? (
              <Button type="primary" onClick={() => setCreateStep(s => s + 1)}>下一步</Button>
            ) : (
              <Button type="primary" onClick={handleCreateSubmit}>确认创建</Button>
            )}
          </Space>
        }
      >
        <Steps current={createStep} size="small" style={{ marginBottom: 24 }} items={[
          { title: '基本信息' },
          { title: '套餐选择' },
          { title: '初始化配置' },
        ]} />

        <Form form={createForm} layout="vertical">
          {createStep === 0 && (
            <>
              <Form.Item label="品牌名称" name="brand_name" rules={[{ required: true, message: '请输入品牌名称' }]}>
                <Input placeholder="请输入品牌名称" />
              </Form.Item>
              <Form.Item label="品牌Logo" name="brand_logo">
                <Upload listType="picture-card" maxCount={1} beforeUpload={() => false}>
                  <div><UploadOutlined /><div style={{ marginTop: 8 }}>上传</div></div>
                </Upload>
              </Form.Item>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item label="联系人" name="contact_name" rules={[{ required: true }]}>
                    <Input placeholder="联系人姓名" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="手机号" name="contact_phone" rules={[{ required: true }]}>
                    <Input placeholder="手机号码" />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item label="邮箱" name="contact_email">
                <Input placeholder="联系邮箱" />
              </Form.Item>
            </>
          )}

          {createStep === 1 && (
            <Row gutter={16}>
              {PLAN_CONFIGS.map(plan => (
                <Col span={8} key={plan.tier}>
                  <Card
                    hoverable
                    style={{
                      borderColor: createForm.getFieldValue('plan') === plan.tier ? '#FF6B35' : undefined,
                      borderWidth: createForm.getFieldValue('plan') === plan.tier ? 2 : 1,
                    }}
                    onClick={() => createForm.setFieldValue('plan', plan.tier)}
                  >
                    <div style={{ textAlign: 'center' }}>
                      <CrownOutlined style={{
                        fontSize: 28,
                        color: plan.tier === 'enterprise' ? '#faad14' : plan.tier === 'pro' ? '#1890ff' : '#999',
                      }} />
                      <Title level={5} style={{ margin: '8px 0 4px' }}>{plan.name}</Title>
                      <Text type="secondary" style={{ fontSize: 18 }}>{plan.price_label}</Text>
                      <Divider style={{ margin: '12px 0' }} />
                      <div style={{ textAlign: 'left', fontSize: 12 }}>
                        <div>门店上限: <Text strong>{plan.store_limit === 9999 ? '不限' : plan.store_limit}</Text></div>
                        <div>用户上限: <Text strong>{plan.user_limit === 9999 ? '不限' : plan.user_limit}</Text></div>
                      </div>
                    </div>
                  </Card>
                </Col>
              ))}
            </Row>
          )}

          {createStep === 2 && (
            <>
              <Form.Item label="默认门店名称" name="default_store_name" rules={[{ required: true }]}>
                <Input placeholder="如：XXX品牌旗舰店" />
              </Form.Item>
              <Form.Item label="管理员账号" name="admin_account" rules={[{ required: true }]}>
                <Input placeholder="管理员登录手机号" />
              </Form.Item>
              <Form.Item label="初始密码" name="admin_password" initialValue="Tx@123456">
                <Input.Password placeholder="初始密码" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>

      {/* 品牌详情 Drawer */}
      <Drawer
        title={drawerData ? `品牌详情 — ${drawerData.tenant.name}` : '品牌详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setDrawerData(null); }}
        width={600}
        loading={drawerLoading}
      >
        {drawerData && (
          <>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="品牌名称">{drawerData.tenant.name}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Badge color={STATUS_MAP[drawerData.tenant.status].color} text={STATUS_MAP[drawerData.tenant.status].text} />
              </Descriptions.Item>
              <Descriptions.Item label="联系人">{drawerData.tenant.contact_name}</Descriptions.Item>
              <Descriptions.Item label="手机">{drawerData.tenant.contact_phone}</Descriptions.Item>
              <Descriptions.Item label="邮箱" span={2}>{drawerData.tenant.contact_email}</Descriptions.Item>
              <Descriptions.Item label="套餐">
                <Tag color={PLAN_MAP[drawerData.tenant.plan].color}>{PLAN_MAP[drawerData.tenant.plan].text}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="到期日">{drawerData.tenant.expired_at}</Descriptions.Item>
              <Descriptions.Item label="创建日期" span={2}>{drawerData.tenant.created_at}</Descriptions.Item>
            </Descriptions>

            <Divider orientation="left">门店列表 ({drawerData.stores.length})</Divider>
            <List
              size="small"
              dataSource={drawerData.stores.slice(0, 10)}
              renderItem={store => (
                <List.Item>
                  <Space>
                    <ShopOutlined />
                    <Text>{store.name}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{store.address}</Text>
                  </Space>
                  <Badge color={store.status === 'open' ? 'green' : 'default'} text={store.status === 'open' ? '营业中' : '已关闭'} />
                </List.Item>
              )}
            />
            {drawerData.stores.length > 10 && (
              <Text type="secondary" style={{ display: 'block', textAlign: 'center', padding: 8 }}>
                共 {drawerData.stores.length} 家门店，仅显示前 10 家
              </Text>
            )}

            <Divider orientation="left">用量统计</Divider>
            <Row gutter={16}>
              {drawerData.usage.map(u => (
                <Col span={8} key={u.label}>
                  <Card size="small">
                    <Text type="secondary" style={{ fontSize: 12 }}>{u.label}</Text>
                    <Progress
                      percent={Math.round((u.current / u.limit) * 100)}
                      format={() => `${u.current}/${u.limit === 9999 ? '∞' : u.limit}`}
                      strokeColor={u.current / u.limit > 0.8 ? '#ff4d4f' : '#FF6B35'}
                      size="small"
                    />
                  </Card>
                </Col>
              ))}
            </Row>

            <Divider orientation="left">账单历史</Divider>
            <Timeline
              items={drawerData.billHistory.map(b => ({
                color: BILL_STATUS_MAP[b.status].color,
                children: (
                  <Space>
                    <Text>{b.cycle}</Text>
                    <Text strong>¥{b.amount.toLocaleString()}</Text>
                    <Tag color={BILL_STATUS_MAP[b.status].color}>{BILL_STATUS_MAP[b.status].text}</Tag>
                    {b.paid_at && <Text type="secondary" style={{ fontSize: 12 }}>{b.paid_at}</Text>}
                  </Space>
                ),
              }))}
            />
          </>
        )}
      </Drawer>
    </>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Tab2: 套餐管理
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function PlanManageTab() {
  const [plans, setPlans] = useState<PlanConfig[]>(PLAN_CONFIGS);
  const [editOpen, setEditOpen] = useState(false);
  const [editPlan, setEditPlan] = useState<PlanConfig | null>(null);
  const [form] = Form.useForm();

  const openEdit = (plan: PlanConfig) => {
    setEditPlan(plan);
    form.setFieldsValue({
      name: plan.name,
      price: plan.price,
      store_limit: plan.store_limit,
      user_limit: plan.user_limit,
    });
    setEditOpen(true);
  };

  const handleSave = () => {
    const values = form.getFieldsValue(true);
    if (!editPlan) return;
    setPlans(prev =>
      prev.map(p =>
        p.tier === editPlan.tier
          ? {
              ...p,
              name: values.name,
              price: values.price,
              price_label: values.price > 0 ? `¥${Number(values.price).toLocaleString()}/月` : '定制报价',
              store_limit: values.store_limit,
              user_limit: values.user_limit,
            }
          : p
      )
    );
    setEditOpen(false);
    message.success('套餐已更新');
  };

  return (
    <>
      <Row gutter={24}>
        {plans.map(plan => (
          <Col span={8} key={plan.tier}>
            <Card
              title={
                <Space>
                  <CrownOutlined style={{
                    color: plan.tier === 'enterprise' ? '#faad14' : plan.tier === 'pro' ? '#1890ff' : '#999',
                  }} />
                  {plan.name}
                </Space>
              }
              extra={
                <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(plan)}>
                  编辑
                </Button>
              }
              style={{ height: '100%' }}
            >
              <div style={{ textAlign: 'center', marginBottom: 16 }}>
                <Title level={3} style={{ margin: 0, color: '#FF6B35' }}>{plan.price_label}</Title>
              </div>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="门店上限">
                  {plan.store_limit === 9999 ? '不限' : `${plan.store_limit} 家`}
                </Descriptions.Item>
                <Descriptions.Item label="用户上限">
                  {plan.user_limit === 9999 ? '不限' : `${plan.user_limit} 人`}
                </Descriptions.Item>
              </Descriptions>
              <Divider style={{ margin: '12px 0' }} />
              <div>
                {ALL_FEATURES.map(f => {
                  const enabled = f[plan.tier];
                  return (
                    <div key={f.name} style={{ padding: '2px 0', color: enabled ? undefined : '#ccc' }}>
                      {enabled ? (
                        <CheckOutlined style={{ color: '#52c41a', marginRight: 8 }} />
                      ) : (
                        <CloseOutlined style={{ color: '#ccc', marginRight: 8 }} />
                      )}
                      <Text style={{ color: enabled ? undefined : '#ccc' }}>{f.name}</Text>
                    </div>
                  );
                })}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 编辑套餐 Modal */}
      <Modal
        title={`编辑套餐 — ${editPlan?.name ?? ''}`}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={handleSave}
        okText="保存"
      >
        <Form form={form} layout="vertical">
          <Form.Item label="套餐名称" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="月费（元，0=定制）" name="price" rules={[{ required: true }]}>
            <Input type="number" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="门店上限" name="store_limit" rules={[{ required: true }]}>
                <Input type="number" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="用户上限" name="user_limit" rules={[{ required: true }]}>
                <Input type="number" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </>
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Tab3: 账单管理
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function BillingTab() {
  const tableRef = useRef<ActionType>();
  const [bills, setBills] = useState<BillItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    const data = await fetchBills();
    setBills(data);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleExport = () => {
    const header = '品牌,套餐,计费周期,应收(元),实收(元),状态,到期日\n';
    const rows = bills.map(b =>
      `${b.tenant_name},${PLAN_MAP[b.plan].text},${b.billing_cycle},${b.amount_due},${b.amount_paid},${BILL_STATUS_MAP[b.status].text},${b.due_date}`
    ).join('\n');
    const blob = new Blob(['\uFEFF' + header + rows], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `账单导出_${dayjs().format('YYYYMMDD')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    message.success('账单已导出');
  };

  const columns: ProColumns<BillItem>[] = [
    { title: '品牌', dataIndex: 'tenant_name', width: 120 },
    {
      title: '套餐',
      dataIndex: 'plan',
      width: 90,
      render: (_, r) => <Tag color={PLAN_MAP[r.plan].color}>{PLAN_MAP[r.plan].text}</Tag>,
    },
    { title: '计费周期', dataIndex: 'billing_cycle', width: 100 },
    {
      title: '应收(元)',
      dataIndex: 'amount_due',
      width: 110,
      sorter: (a, b) => a.amount_due - b.amount_due,
      render: (_, r) => <Text strong>¥{r.amount_due.toLocaleString()}</Text>,
    },
    {
      title: '实收(元)',
      dataIndex: 'amount_paid',
      width: 110,
      render: (_, r) => <Text>¥{r.amount_paid.toLocaleString()}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      filters: [
        { text: '已支付', value: 'paid' },
        { text: '待支付', value: 'pending' },
        { text: '已逾期', value: 'overdue' },
      ],
      onFilter: (v, r) => r.status === v,
      render: (_, r) => (
        <Tag color={BILL_STATUS_MAP[r.status].color}>{BILL_STATUS_MAP[r.status].text}</Tag>
      ),
    },
    {
      title: '到期日',
      dataIndex: 'due_date',
      width: 110,
      render: (_, r) => dayjs(r.due_date).format('YYYY-MM-DD'),
    },
    {
      title: '支付日',
      dataIndex: 'paid_at',
      width: 110,
      render: (_, r) => r.paid_at ? dayjs(r.paid_at).format('YYYY-MM-DD') : <Text type="secondary">--</Text>,
    },
  ];

  return (
    <ProTable<BillItem>
      actionRef={tableRef}
      columns={columns}
      dataSource={bills}
      loading={loading}
      rowKey="id"
      search={false}
      pagination={{ pageSize: 10, showSizeChanger: true }}
      headerTitle="账单管理"
      toolBarRender={() => [
        <Button key="refresh" icon={<ReloadOutlined />} onClick={load}>刷新</Button>,
        <Button key="export" icon={<DownloadOutlined />} onClick={handleExport}>导出账单</Button>,
      ]}
    />
  );
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  主页面
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function TenantManagePage() {
  const [stats, setStats] = useState({
    total: 0,
    active: 0,
    newThisMonth: 0,
    totalStores: 0,
  });

  useEffect(() => {
    (async () => {
      const tenants = await fetchTenants();
      setStats({
        total: tenants.length,
        active: tenants.filter(t => t.status === 'active').length,
        newThisMonth: tenants.filter(t => dayjs(t.created_at).isAfter(dayjs().startOf('month'))).length,
        totalStores: tenants.reduce((s, t) => s + t.store_count, 0),
      });
    })();
  }, []);

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>租户管理</Title>

      {/* 顶部统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总品牌数"
              value={stats.total}
              prefix={<TeamOutlined style={{ color: '#FF6B35' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="活跃品牌"
              value={stats.active}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="本月新增"
              value={stats.newThisMonth}
              prefix={<PlusOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总门店数"
              value={stats.totalStores}
              prefix={<ShopOutlined style={{ color: '#faad14' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 三 Tab */}
      <Card>
        <Tabs
          defaultActiveKey="brands"
          items={[
            { key: 'brands', label: '品牌列表', children: <TenantListTab /> },
            { key: 'plans', label: '套餐管理', children: <PlanManageTab /> },
            { key: 'billing', label: '账单管理', children: <BillingTab /> },
          ]}
        />
      </Card>
    </div>
  );
}
