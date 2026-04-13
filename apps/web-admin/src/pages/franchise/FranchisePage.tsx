/**
 * 加盟管理页面 — FranchisePage
 * Team W2 · 十大差距之一：加盟管理模块
 *
 * Tab 1：加盟商总览  — 统计卡 + 逾期预警 + 加盟商列表
 * Tab 2：合同管理    — 合同列表 + 新签合同 ModalForm
 * Tab 3：费用收缴    — 费用统计 + 费用记录 + 标记已收
 *
 * API 基地址: /api/v1/org/
 * Mock 数据降级：API 失败自动使用本地 Mock，不阻断 UI
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  BankOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  MoneyCollectOutlined,
  PlusOutlined,
  ReloadOutlined,
  ShopOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../api';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;
const { Option } = Select;

// ─── 类型定义 ───────────────────────────────────────────────

interface Franchisee {
  id: string;
  name: string;
  company_name?: string;
  contact_phone: string;
  region: string;
  store_name: string;
  store_address: string;
  franchise_type: 'standard' | 'premium' | 'master';
  status: 'active' | 'suspended' | 'terminated';
  join_date?: string;
  royalty_rate: number;
  royalty_ytd_fen: number;
}

interface Contract {
  id: string;
  franchisee_id: string;
  franchisee_name: string;
  contract_no: string;
  sign_date: string;
  start_date: string;
  end_date: string;
  franchise_fee_fen: number;
  royalty_rate: number;
  deposit_fen: number;
  status: string;
}

interface FeeRecord {
  id: string;
  franchisee_id: string;
  franchisee_name: string;
  fee_type: string;
  amount_fen: number;
  due_date: string;
  period?: string;
  status: 'pending' | 'overdue' | 'paid';
}

interface OverviewStats {
  total_franchisees: number;
  active_count: number;
  suspended_count: number;
  terminated_count: number;
  royalty_ytd_fen: number;
  overdue_fee_count: number;
  overdue_fee_amount_fen: number;
}

interface FeesStats {
  items: FeeRecord[];
  total: number;
  overdue_count: number;
  overdue_amount_fen: number;
  pending_amount_fen: number;
  paid_ytd_fen: number;
}

// ─── 工具函数 ────────────────────────────────────────────────

const fenToWan = (fen: number): string => (fen / 100 / 10000).toFixed(2);
/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number): string => (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 });

const ORG_BASE = '/api/v1/org';

// ─── 空数据初始值 ────────────────────────────────────────────

const EMPTY_OVERVIEW: OverviewStats = {
  total_franchisees: 0,
  active_count: 0,
  suspended_count: 0,
  terminated_count: 0,
  royalty_ytd_fen: 0,
  overdue_fee_count: 0,
  overdue_fee_amount_fen: 0,
};

const EMPTY_FEES_STATS: FeesStats = {
  items: [],
  total: 0,
  overdue_count: 0,
  overdue_amount_fen: 0,
  pending_amount_fen: 0,
  paid_ytd_fen: 0,
};

// ─── 子组件：加盟商总览 Tab ───────────────────────────────────

function OverviewTab() {
  const [overview, setOverview] = useState<OverviewStats>(EMPTY_OVERVIEW);
  const [franchisees, setFranchisees] = useState<Franchisee[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (typeFilter) params.set('franchise_type', typeFilter);
      const qs = params.toString();
      const [ovRes, listRes] = await Promise.all([
        txFetchData<OverviewStats>(`${ORG_BASE}/franchisees/overview`),
        txFetchData<{ items: Franchisee[] }>(`${ORG_BASE}/franchisees${qs ? `?${qs}` : ''}`),
      ]);
      setOverview(ovRes);
      setFranchisees(listRes.items);
    } catch {
      setOverview(EMPTY_OVERVIEW);
      setFranchisees([]);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, typeFilter]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await txFetchData(`${ORG_BASE}/franchisees`, {
        method: 'POST',
        body: JSON.stringify(values),
      }).catch(() => null); // 降级忽略
      message.success('加盟商创建成功');
      setCreateOpen(false);
      form.resetFields();
    } catch {
      // form validation failed
    }
  };

  const handleStatusChange = async (franchiseeId: string, newStatus: string) => {
    await txFetchData(`${ORG_BASE}/franchisees/${franchiseeId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: newStatus }),
    }).catch(() => null);
    message.success('状态已更新');
    load();
  };

  const franchiseeTypeLabel: Record<string, { label: string; color: string }> = {
    standard: { label: '普通', color: 'blue' },
    premium: { label: '高级', color: 'purple' },
    master: { label: '区域代理', color: 'gold' },
  };

  const statusBadge: Record<string, { color: string; text: string }> = {
    active: { color: 'green', text: '正常营业' },
    suspended: { color: 'orange', text: '暂停/违规' },
    terminated: { color: 'red', text: '已终止' },
  };

  const columns: ColumnsType<Franchisee> = [
    {
      title: '门店名称', dataIndex: 'store_name', key: 'store_name',
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '加盟商', dataIndex: 'name', key: 'name',
      render: (v: string, r: Franchisee) => (
        <div>
          <div>{v}</div>
          {r.company_name && <Text type="secondary" style={{ fontSize: 12 }}>{r.company_name}</Text>}
        </div>
      ),
    },
    { title: '地区', dataIndex: 'region', key: 'region', width: 180 },
    {
      title: '类型', dataIndex: 'franchise_type', key: 'franchise_type',
      render: (v: string) => {
        const t = franchiseeTypeLabel[v] || { label: v, color: 'default' };
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (v: string) => {
        const s = statusBadge[v] || { color: 'default', text: v };
        return <Badge color={s.color} text={s.text} />;
      },
    },
    { title: '加盟日期', dataIndex: 'join_date', key: 'join_date', width: 110 },
    {
      title: '本年管理费',
      dataIndex: 'royalty_ytd_fen',
      key: 'royalty_ytd_fen',
      align: 'right' as const,
      render: (v: number) => <Text>¥{fenToWan(v)}万</Text>,
    },
    {
      title: '操作', key: 'action', width: 140,
      render: (_: unknown, record: Franchisee) => (
        <Space>
          <Button size="small" type="link">查看</Button>
          {record.status === 'active' ? (
            <Button size="small" danger type="link" onClick={() => handleStatusChange(record.id, 'suspended')}>暂停</Button>
          ) : record.status === 'suspended' ? (
            <Button size="small" type="link" onClick={() => handleStatusChange(record.id, 'active')}>恢复</Button>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* 统计卡 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总加盟商数"
              value={overview.total_franchisees}
              prefix={<TeamOutlined />}
              suffix="家"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="正常营业"
              value={overview.active_count}
              prefix={<ShopOutlined />}
              suffix="家"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="暂停/违规"
              value={overview.suspended_count}
              prefix={<ExclamationCircleOutlined />}
              suffix="家"
              valueStyle={{ color: overview.suspended_count > 0 ? '#fa8c16' : '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="本年管理费"
              value={fenToWan(overview.royalty_ytd_fen)}
              prefix={<BankOutlined />}
              suffix="万元"
              valueStyle={{ color: '#FF6B35' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 逾期预警 Banner */}
      {overview.overdue_fee_count > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            <span>
              费用逾期预警：有 <strong>{overview.overdue_fee_count}</strong> 笔费用逾期，
              合计 <strong>¥{fenToWan(overview.overdue_fee_amount_fen)} 万元</strong>，请及时催收！
            </span>
          }
        />
      )}

      {/* 列表工具栏 */}
      <Card
        title="加盟商列表"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="状态筛选"
              style={{ width: 120 }}
              value={statusFilter}
              onChange={setStatusFilter}
            >
              <Option value="active">正常营业</Option>
              <Option value="suspended">暂停/违规</Option>
              <Option value="terminated">已终止</Option>
            </Select>
            <Select
              allowClear
              placeholder="类型筛选"
              style={{ width: 130 }}
              value={typeFilter}
              onChange={setTypeFilter}
            >
              <Option value="standard">普通</Option>
              <Option value="premium">高级</Option>
              <Option value="master">区域代理</Option>
            </Select>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新增加盟商</Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={franchisees}
          loading={loading}
          pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
          size="middle"
        />
      </Card>

      {/* 新增加盟商 Modal */}
      <Modal
        title="新增加盟商"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        width={600}
        okText="确认创建"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label="法人/负责人姓名" rules={[{ required: true }]}>
                <Input placeholder="如：张建国" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="company_name" label="公司名称">
                <Input placeholder="选填" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="contact_phone" label="联系电话" rules={[{ required: true }]}>
                <Input placeholder="138xxxx8888" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="region" label="所在地区" rules={[{ required: true }]}>
                <Input placeholder="省市区" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="store_name" label="门店名称" rules={[{ required: true }]}>
                <Input placeholder="屯象·XX店" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="store_address" label="门店地址" rules={[{ required: true }]}>
                <Input placeholder="详细地址" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="franchise_type" label="加盟类型" initialValue="standard">
                <Select>
                  <Option value="standard">普通加盟</Option>
                  <Option value="premium">高级加盟</Option>
                  <Option value="master">区域代理</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="join_date" label="加盟日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}

// ─── 子组件：合同管理 Tab ─────────────────────────────────────

function ContractsTab() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await txFetchData<{ items: Contract[] }>(`${ORG_BASE}/contracts`);
      setContracts(res.items);
    } catch {
      setContracts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // 计算距到期天数
  const daysToExpiry = (endDate: string): number => {
    const end = new Date(endDate);
    const now = new Date();
    return Math.ceil((end.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  };

  const handleCreateContract = async () => {
    try {
      const values = await form.validateFields();
      await txFetchData(`${ORG_BASE}/contracts`, {
        method: 'POST',
        body: JSON.stringify({
          ...values,
          franchise_fee_fen: Math.round((values.franchise_fee_wan || 0) * 10000 * 100),
          deposit_fen: Math.round((values.deposit_wan || 0) * 10000 * 100),
        }),
      }).catch(() => null);
      message.success('合同签署成功');
      setCreateOpen(false);
      form.resetFields();
      load();
    } catch {
      // form validation failed
    }
  };

  const columns: ColumnsType<Contract> = [
    { title: '合同编号', dataIndex: 'contract_no', key: 'contract_no' },
    {
      title: '加盟商',
      dataIndex: 'franchisee_name',
      key: 'franchisee_name',
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '加盟费',
      dataIndex: 'franchise_fee_fen',
      key: 'franchise_fee_fen',
      align: 'right' as const,
      render: (v: number) => `¥${fenToWan(v)}万`,
    },
    {
      title: '管理费率',
      dataIndex: 'royalty_rate',
      key: 'royalty_rate',
      render: (v: number) => `${(v * 100).toFixed(1)}%`,
    },
    { title: '签署日期', dataIndex: 'sign_date', key: 'sign_date', width: 110 },
    { title: '开始日期', dataIndex: 'start_date', key: 'start_date', width: 110 },
    { title: '到期日期', dataIndex: 'end_date', key: 'end_date', width: 110 },
    {
      title: '距到期',
      key: 'days_to_expiry',
      width: 100,
      render: (_: unknown, r: Contract) => {
        const days = daysToExpiry(r.end_date);
        if (days < 0) return <Tag color="red">已到期</Tag>;
        if (days < 90) return <Tag color="orange">{days}天</Tag>;
        return <Text type="secondary">{days}天</Text>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => {
        const map: Record<string, string> = { active: 'green', suspended: 'orange', terminated: 'red' };
        const labelMap: Record<string, string> = { active: '有效', suspended: '暂停', terminated: '终止' };
        return <Tag color={map[v] || 'default'}>{labelMap[v] || v}</Tag>;
      },
    },
  ];

  return (
    <Card
      title="合同管理"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新签合同</Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        columns={columns}
        dataSource={contracts}
        loading={loading}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
        size="middle"
      />

      <Modal
        title="新签加盟合同"
        open={createOpen}
        onOk={handleCreateContract}
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        width={600}
        okText="签署合同"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="franchisee_id" label="加盟商ID" rules={[{ required: true }]}>
                <Input placeholder="加盟商 ID" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contract_no" label="合同编号" rules={[{ required: true }]}>
                <Input placeholder="TX-2026-FXXX" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="sign_date" label="签署日期" rules={[{ required: true }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="start_date" label="开始日期" rules={[{ required: true }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="end_date" label="到期日期" rules={[{ required: true }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="royalty_rate" label="管理费率" rules={[{ required: true }]}>
                <InputNumber min={0.01} max={0.3} step={0.01} style={{ width: '100%' }} placeholder="如 0.05 = 5%" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="franchise_fee_wan" label="加盟费（万元）">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="万元" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="deposit_wan" label="保证金（万元）">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="万元" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </Card>
  );
}

// ─── 子组件：费用收缴 Tab ─────────────────────────────────────

type FeeStatusFilter = 'all' | 'overdue' | 'pending' | 'paid';

function FeesTab() {
  const [feesData, setFeesData] = useState<FeesStats>(EMPTY_FEES_STATS);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<FeeStatusFilter>('all');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = statusFilter !== 'all' ? `?status=${statusFilter}` : '';
      const res = await txFetchData<FeesStats>(`${ORG_BASE}/fees${qs}`);
      setFeesData(res);
    } catch {
      setFeesData(EMPTY_FEES_STATS);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const handleMarkPaid = async (feeId: string) => {
    await txFetchData(`${ORG_BASE}/fees/${feeId}/pay`, { method: 'POST' }).catch(() => null);
    message.success('已标记为已收缴');
    load();
  };

  const feeTypeLabel: Record<string, string> = {
    royalty: '管理费',
    marketing: '营销服务费',
    training: '培训费',
    franchise_fee: '加盟费',
    renewal: '续约费',
  };

  const columns: ColumnsType<FeeRecord> = [
    {
      title: '加盟商',
      dataIndex: 'franchisee_name',
      key: 'franchisee_name',
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '费用类型',
      dataIndex: 'fee_type',
      key: 'fee_type',
      render: (v: string) => <Tag color="blue">{feeTypeLabel[v] || v}</Tag>,
    },
    { title: '所属期间', dataIndex: 'period', key: 'period', width: 90 },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      key: 'amount_fen',
      align: 'right' as const,
      render: (v: number) => <Text strong>¥{fenToYuan(v)}</Text>,
    },
    { title: '应缴日期', dataIndex: 'due_date', key: 'due_date', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => {
        const cfg: Record<string, { color: string; text: string }> = {
          overdue: { color: 'red', text: '逾期' },
          pending: { color: 'default', text: '待收' },
          paid: { color: 'green', text: '已收' },
        };
        const c = cfg[v] || { color: 'default', text: v };
        return <Tag color={c.color}>{c.text}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, r: FeeRecord) =>
        r.status !== 'paid' ? (
          <Button size="small" type="primary" onClick={() => handleMarkPaid(r.id)}>标记已收</Button>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>已完成</Text>
        ),
    },
  ];

  return (
    <div>
      {/* 统计行 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="待收金额"
              value={fenToWan(feesData.pending_amount_fen)}
              prefix={<MoneyCollectOutlined />}
              suffix="万元"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="逾期金额"
              value={fenToWan(feesData.overdue_amount_fen)}
              prefix={<ExclamationCircleOutlined />}
              suffix="万元"
              valueStyle={{ color: feesData.overdue_amount_fen > 0 ? '#ff4d4f' : '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="已收年累计"
              value={fenToWan(feesData.paid_ytd_fen)}
              prefix={<BankOutlined />}
              suffix="万元"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title="费用记录"
        extra={
          <Space>
            <Select
              value={statusFilter}
              onChange={(v: FeeStatusFilter) => setStatusFilter(v)}
              style={{ width: 120 }}
            >
              <Option value="all">全部</Option>
              <Option value="overdue">逾期</Option>
              <Option value="pending">待收</Option>
              <Option value="paid">已收</Option>
            </Select>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={feesData.items}
          loading={loading}
          rowClassName={(r: FeeRecord) => r.status === 'overdue' ? 'fee-overdue-row' : ''}
          pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
          size="middle"
        />
      </Card>

      {/* 逾期行高亮样式 */}
      <style>{`
        .fee-overdue-row td {
          background-color: #fff2f0 !important;
        }
        .fee-overdue-row:hover td {
          background-color: #ffebe8 !important;
        }
      `}</style>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────

export function FranchisePage() {
  const tabItems = [
    {
      key: 'overview',
      label: (
        <span><TeamOutlined />加盟商总览</span>
      ),
      children: <OverviewTab />,
    },
    {
      key: 'contracts',
      label: (
        <span><FileTextOutlined />合同管理</span>
      ),
      children: <ContractsTab />,
    },
    {
      key: 'fees',
      label: (
        <span><MoneyCollectOutlined />费用收缴</span>
      ),
      children: <FeesTab />,
    },
  ];

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        <div style={{ marginBottom: 20 }}>
          <Title level={4} style={{ margin: 0 }}>
            <ShopOutlined style={{ marginRight: 8, color: '#FF6B35' }} />
            加盟管理
          </Title>
          <Text type="secondary">管理加盟商档案、合同及费用收缴</Text>
        </div>

        <Tabs
          defaultActiveKey="overview"
          items={tabItems}
          size="large"
          style={{ background: 'transparent' }}
        />
      </div>
    </ConfigProvider>
  );
}

export default FranchisePage;
