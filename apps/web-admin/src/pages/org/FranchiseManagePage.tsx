/**
 * 加盟商管理闭环 — FranchiseManagePage（模块3.2）
 *
 * Tab1  加盟商档案  — 列表 + 新建 Modal + 合同详情 Drawer
 * Tab2  费用收缴    — 应收列表，逾期标红，收款按钮 + 批量生成本月应收
 * Tab3  公共代码    — 编码列表 + 新增 Modal + 同步按钮
 * Tab4  对账报表    — 营业额汇总 / 费用收缴汇总 双表格
 *
 * API base: /api/v1/franchise（franchise_v5_routes.py）
 * 路由：/org/franchise
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  BankOutlined,
  CheckCircleOutlined,
  CloudSyncOutlined,
  PlusOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface Franchisee {
  id: string;
  name: string;
  company_name?: string;
  contact_phone: string;
  contact_email?: string;
  region: string;
  store_name: string;
  store_address: string;
  franchise_type: string;
  status: string;
  join_date?: string;
  contract_start_date?: string;
  contract_end_date?: string;
  contract_file_url?: string;
  created_at: string;
}

interface FranchiseFee {
  id: string;
  franchisee_id: string;
  franchisee_name?: string;
  store_name?: string;
  fee_type: string;
  amount_fen: number;
  paid_amount_fen?: number;
  due_date: string;
  status: string;
  overdue_days?: number;
  payment_method?: string;
  receipt_no?: string;
}

interface CommonCode {
  id: string;
  code_type: string;
  code_no: string;
  name: string;
  description?: string;
  unit?: string;
  price_fen?: number;
  applicable_stores: string[];
  is_synced: boolean;
  status: string;
}

interface RevenueItem {
  franchisee_id: string;
  franchisee_name: string;
  store_name: string;
  region: string;
  order_count: number;
  revenue_fen: number;
}

interface FeeSummaryItem {
  franchisee_id: string;
  franchisee_name: string;
  store_name: string;
  receivable_fen: number;
  collected_fen: number;
  overdue_fen: number;
  overdue_count: number;
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number): string =>
  (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 });

const statusColor: Record<string, string> = {
  active: 'green',
  suspended: 'orange',
  terminated: 'red',
};

const feeStatusColor: Record<string, string> = {
  pending: 'blue',
  paid: 'green',
  overdue: 'red',
};

const feeTypeLabel: Record<string, string> = {
  royalty: '管理费',
  management: '运营服务费',
  brand: '品牌使用费',
  training: '培训费',
};

const codeTypeLabel: Record<string, string> = {
  material: '物料编码',
  dish: '菜品编码',
  price: '价格编码',
};

// ─── Tab1：加盟商档案 ─────────────────────────────────────────────────────────

function FranchiseeTab() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<Franchisee[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [createVisible, setCreateVisible] = useState(false);
  const [contractDrawer, setContractDrawer] = useState<{ open: boolean; data: Partial<Franchisee> }>({ open: false, data: {} });
  const [createForm] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(p), size: '20' });
      if (statusFilter) params.set('status', statusFilter);
      if (keyword) params.set('keyword', keyword);
      const res = await txFetchData(`/api/v1/franchise/franchisees?${params}`) as any;
      if (res?.data) {
        setItems(res.data.items || []);
        setTotal(res.data.total || 0);
        setPage(p);
      }
    } catch (e) {
      message.error('加载失败');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, keyword]);

  useEffect(() => { load(1); }, [load]);

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/franchise/franchisees', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('加盟商创建成功');
      setCreateVisible(false);
      createForm.resetFields();
      load(1);
    } catch {
      message.error('创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const viewContract = async (record: Franchisee) => {
    try {
      const res = await txFetchData(`/api/v1/franchise/franchisees/${record.id}/contract`) as any;
      setContractDrawer({ open: true, data: res?.data || record });
    } catch {
      setContractDrawer({ open: true, data: record });
    }
  };

  const columns: ColumnsType<Franchisee> = [
    { title: '加盟商名称', dataIndex: 'name', width: 140 },
    { title: '门店名称', dataIndex: 'store_name', width: 140 },
    { title: '区域', dataIndex: 'region', width: 100 },
    { title: '联系电话', dataIndex: 'contact_phone', width: 130 },
    {
      title: '加盟类型',
      dataIndex: 'franchise_type',
      width: 100,
      render: (v: string) => ({ standard: '标准加盟', premium: '高级加盟', master: '区域代理' }[v as 'standard' | 'premium' | 'master'] || v),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v) => <Tag color={statusColor[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '合同到期',
      dataIndex: 'contract_end_date',
      width: 110,
      render: (v) => {
        if (!v) return <Text type="secondary">未设置</Text>;
        const expired = new Date(v) < new Date();
        return <Text type={expired ? 'danger' : undefined}>{v}</Text>;
      },
    },
    {
      title: '操作',
      width: 130,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => viewContract(record)}>查看合同</Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card bordered={false} bodyStyle={{ padding: '12px 0' }}>
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            allowClear
            placeholder="状态筛选"
            style={{ width: 120 }}
            onChange={setStatusFilter}
            options={[
              { label: '正常', value: 'active' },
              { label: '暂停', value: 'suspended' },
              { label: '终止', value: 'terminated' },
            ]}
          />
          <Input.Search
            placeholder="名称/手机/门店"
            style={{ width: 200 }}
            onSearch={setKeyword}
            allowClear
          />
          <Button icon={<ReloadOutlined />} onClick={() => load(1)}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateVisible(true)}>
            新建加盟商
          </Button>
        </Space>

        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          columns={columns}
          pagination={{ current: page, total, pageSize: 20, onChange: load }}
          scroll={{ x: 900 }}
          size="small"
        />
      </Card>

      {/* 新建 Modal */}
      <Modal
        title="新建加盟商档案"
        open={createVisible}
        onCancel={() => { setCreateVisible(false); createForm.resetFields(); }}
        onOk={handleCreate}
        confirmLoading={submitting}
        width={640}
      >
        <Form form={createForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label="加盟商姓名/品牌名" rules={[{ required: true }]}>
                <Input placeholder="请输入" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="company_name" label="公司名称">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contact_phone" label="联系电话" rules={[{ required: true }]}>
                <Input placeholder="138..." />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contact_email" label="邮箱">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="store_name" label="门店名称" rules={[{ required: true }]}>
                <Input placeholder="XX门店" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="region" label="省市区" rules={[{ required: true }]}>
                <Input placeholder="湖南省长沙市" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="store_address" label="门店地址" rules={[{ required: true }]}>
                <Input placeholder="详细地址" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="franchise_type" label="加盟类型" initialValue="standard">
                <Select options={[
                  { label: '标准加盟', value: 'standard' },
                  { label: '高级加盟', value: 'premium' },
                  { label: '区域代理', value: 'master' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="join_date" label="加盟日期">
                <Input placeholder="YYYY-MM-DD" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contract_start_date" label="合同开始日期">
                <Input placeholder="YYYY-MM-DD" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contract_end_date" label="合同结束日期">
                <Input placeholder="YYYY-MM-DD" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="notes" label="备注">
                <Input.TextArea rows={2} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 合同详情 Drawer */}
      <Drawer
        title="合同详情"
        open={contractDrawer.open}
        onClose={() => setContractDrawer({ open: false, data: {} })}
        width={480}
      >
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="加盟商">{contractDrawer.data.name}</Descriptions.Item>
          <Descriptions.Item label="门店">{contractDrawer.data.store_name}</Descriptions.Item>
          <Descriptions.Item label="合同开始">{contractDrawer.data.contract_start_date || '—'}</Descriptions.Item>
          <Descriptions.Item label="合同结束">
            {contractDrawer.data.contract_end_date ? (
              <Text type={new Date(contractDrawer.data.contract_end_date) < new Date() ? 'danger' : undefined}>
                {contractDrawer.data.contract_end_date}
              </Text>
            ) : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="加盟类型">{contractDrawer.data.franchise_type}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={statusColor[contractDrawer.data.status || ''] || 'default'}>
              {contractDrawer.data.status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="合同文件">
            {contractDrawer.data.contract_file_url
              ? <a href={contractDrawer.data.contract_file_url} target="_blank" rel="noreferrer">查看文件</a>
              : <Text type="secondary">暂无上传（占位）</Text>}
          </Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 16 }}>
          <Button type="dashed" block icon={<CloudSyncOutlined />} disabled>
            上传合同文件（功能占位）
          </Button>
        </div>
      </Drawer>
    </>
  );
}

// ─── Tab2：费用收缴 ───────────────────────────────────────────────────────────

function FeeTab() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<FranchiseFee[]>([]);
  const [stats, setStats] = useState({ receivable_fen: 0, collected_fen: 0, overdue_count: 0, overdue_fen: 0 });
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [collectModal, setCollectModal] = useState<{ open: boolean; fee: FranchiseFee | null }>({ open: false, fee: null });
  const [collectForm] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [genModal, setGenModal] = useState(false);
  const [genForm] = Form.useForm();

  const load = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(p), size: '20' });
      if (overdueOnly) params.set('overdue_only', 'true');
      const res = await txFetchData(`/api/v1/franchise/fees?${params}`) as any;
      if (res?.data) {
        setItems(res.data.items || []);
        setTotal(res.data.total || 0);
        setPage(p);
        setStats({
          receivable_fen: res.data.receivable_fen || 0,
          collected_fen: res.data.collected_fen || 0,
          overdue_count: res.data.overdue_count || 0,
          overdue_fen: res.data.overdue_fen || 0,
        });
      }
    } catch {
      message.error('加载费用列表失败');
    } finally {
      setLoading(false);
    }
  }, [overdueOnly]);

  useEffect(() => { load(1); }, [load]);

  const handleCollect = async () => {
    if (!collectModal.fee) return;
    const values = await collectForm.validateFields();
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/franchise/fees/${collectModal.fee.id}/collect`, {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('收款登记成功');
      setCollectModal({ open: false, fee: null });
      collectForm.resetFields();
      load(page);
    } catch {
      message.error('收款失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleGenerateMonthly = async () => {
    const values = await genForm.validateFields();
    setSubmitting(true);
    try {
      const res = await txFetchData('/api/v1/franchise/fees/generate-monthly', {
        method: 'POST',
        body: JSON.stringify(values),
      }) as any;
      const d = res?.data;
      message.success(`已生成 ${d?.generated || 0} 条，跳过 ${d?.skipped || 0} 条（已存在）`);
      setGenModal(false);
      genForm.resetFields();
      load(1);
    } catch {
      message.error('生成失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnsType<FranchiseFee> = [
    { title: '加盟商', dataIndex: 'franchisee_name', width: 130 },
    { title: '门店', dataIndex: 'store_name', width: 130 },
    {
      title: '费用类型',
      dataIndex: 'fee_type',
      width: 110,
      render: (v) => feeTypeLabel[v] || v,
    },
    {
      title: '应收金额',
      dataIndex: 'amount_fen',
      width: 120,
      render: (v) => `¥${fenToYuan(v)}`,
    },
    { title: '应缴日期', dataIndex: 'due_date', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v, record) => {
        const isOverdue = v !== 'paid' && record.overdue_days && record.overdue_days > 0;
        return (
          <Space>
            <Tag color={feeStatusColor[v] || 'default'}>{v}</Tag>
            {isOverdue && <Text type="danger" style={{ fontSize: 12 }}>逾期{record.overdue_days}天</Text>}
          </Space>
        );
      },
    },
    {
      title: '操作',
      width: 100,
      render: (_, record) =>
        record.status !== 'paid' ? (
          <Button
            size="small"
            type="primary"
            icon={<CheckCircleOutlined />}
            onClick={() => { setCollectModal({ open: true, fee: record }); }}
          >
            收款
          </Button>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>已收款</Text>
        ),
    },
  ];

  return (
    <>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="应收总额" value={fenToYuan(stats.receivable_fen)} prefix="¥" />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="已收总额" value={fenToYuan(stats.collected_fen)} prefix="¥" valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="逾期笔数" value={stats.overdue_count} suffix="笔" valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="逾期金额" value={fenToYuan(stats.overdue_fen)} prefix="¥" valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
      </Row>

      <Card bordered={false} bodyStyle={{ padding: '12px 0' }}>
        <Space style={{ marginBottom: 12 }} wrap>
          <Button
            type={overdueOnly ? 'primary' : 'default'}
            danger={overdueOnly}
            icon={<WarningOutlined />}
            onClick={() => setOverdueOnly(!overdueOnly)}
          >
            {overdueOnly ? '仅看逾期中' : '显示全部'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => load(1)}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setGenModal(true)}>
            生成本月应收
          </Button>
        </Space>

        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          columns={columns}
          pagination={{ current: page, total, pageSize: 20, onChange: load }}
          rowClassName={(r) => (r.status !== 'paid' && r.overdue_days && r.overdue_days > 0 ? 'ant-table-row-danger' : '')}
          scroll={{ x: 800 }}
          size="small"
        />
      </Card>

      {/* 收款 Modal */}
      <Modal
        title={`登记收款 — ${collectModal.fee?.franchisee_name || ''}`}
        open={collectModal.open}
        onCancel={() => { setCollectModal({ open: false, fee: null }); collectForm.resetFields(); }}
        onOk={handleCollect}
        confirmLoading={submitting}
      >
        {collectModal.fee && (
          <div style={{ marginBottom: 12 }}>
            <Text>应收金额：<Text strong>¥{fenToYuan(collectModal.fee.amount_fen)}</Text></Text>
          </div>
        )}
        <Form form={collectForm} layout="vertical">
          <Form.Item
            name="paid_amount_fen"
            label="实收金额（分）"
            rules={[{ required: true, message: '请输入实收金额' }]}
            initialValue={collectModal.fee?.amount_fen}
          >
            <InputNumber style={{ width: '100%' }} min={1} placeholder="单位：分（100=1元）" />
          </Form.Item>
          <Form.Item name="payment_method" label="收款方式" initialValue="transfer">
            <Select options={[
              { label: '银行转账', value: 'transfer' },
              { label: '现金', value: 'cash' },
              { label: '微信支付', value: 'wechat' },
              { label: '支付宝', value: 'alipay' },
            ]} />
          </Form.Item>
          <Form.Item name="receipt_no" label="收款单号（可选）">
            <Input placeholder="银行流水号或凭证号" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 生成本月应收 Modal */}
      <Modal
        title="批量生成本月应收费用"
        open={genModal}
        onCancel={() => { setGenModal(false); genForm.resetFields(); }}
        onOk={handleGenerateMonthly}
        confirmLoading={submitting}
      >
        <Form form={genForm} layout="vertical">
          <Form.Item name="year_month" label="目标月份" rules={[{ required: true, message: '请输入月份' }]}>
            <Input placeholder="YYYY-MM，如 2026-04" />
          </Form.Item>
          <Form.Item name="fee_type" label="费用类型" initialValue="royalty">
            <Select options={Object.entries(feeTypeLabel).map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
          <Form.Item name="amount_fen" label="每家应收金额（分）" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} min={1} placeholder="如 500000 = 5000元" />
          </Form.Item>
          <Form.Item name="due_day" label="截止日（当月几号）" initialValue={15}>
            <InputNumber style={{ width: '100%' }} min={1} max={28} />
          </Form.Item>
          <Form.Item name="notes" label="备注（可选）">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab3：公共代码 ───────────────────────────────────────────────────────────

function CommonCodeTab() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<CommonCode[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [createVisible, setCreateVisible] = useState(false);
  const [createForm] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [syncModal, setSyncModal] = useState<{ open: boolean; selectedIds: string[] }>({ open: false, selectedIds: [] });
  const [syncForm] = Form.useForm();
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);

  const load = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(p), size: '20' });
      if (typeFilter) params.set('code_type', typeFilter);
      const res = await txFetchData(`/api/v1/franchise/common-codes?${params}`) as any;
      if (res?.data) {
        setItems(res.data.items || []);
        setTotal(res.data.total || 0);
        setPage(p);
      }
    } catch {
      message.error('加载公共代码失败');
    } finally {
      setLoading(false);
    }
  }, [typeFilter]);

  useEffect(() => { load(1); }, [load]);

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/franchise/common-codes', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('公共代码创建成功');
      setCreateVisible(false);
      createForm.resetFields();
      load(1);
    } catch {
      message.error('创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSync = async () => {
    const values = await syncForm.validateFields();
    const storeIds: string[] = (values.target_stores as string).split(',').map((s: string) => s.trim()).filter(Boolean);
    setSubmitting(true);
    try {
      const res = await txFetchData('/api/v1/franchise/common-codes/sync', {
        method: 'POST',
        body: JSON.stringify({ code_ids: syncModal.selectedIds, target_store_ids: storeIds }),
      }) as any;
      message.success(`已同步 ${res?.data?.synced_count || 0} 条编码到 ${storeIds.length} 家门店`);
      setSyncModal({ open: false, selectedIds: [] });
      syncForm.resetFields();
      setSelectedRowKeys([]);
      load(page);
    } catch {
      message.error('同步失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnsType<CommonCode> = [
    {
      title: '类型',
      dataIndex: 'code_type',
      width: 100,
      render: (v) => <Tag>{codeTypeLabel[v] || v}</Tag>,
    },
    { title: '编码编号', dataIndex: 'code_no', width: 130 },
    { title: '名称', dataIndex: 'name', width: 160 },
    { title: '单位', dataIndex: 'unit', width: 70 },
    {
      title: '参考价',
      dataIndex: 'price_fen',
      width: 100,
      render: (v) => v != null ? `¥${fenToYuan(v)}` : '—',
    },
    {
      title: '已同步',
      dataIndex: 'is_synced',
      width: 80,
      render: (v) => v ? <Tag color="green">已同步</Tag> : <Tag color="default">未同步</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (v) => <Tag color={v === 'active' ? 'green' : 'default'}>{v}</Tag>,
    },
  ];

  return (
    <>
      <Card bordered={false} bodyStyle={{ padding: '12px 0' }}>
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            allowClear
            placeholder="编码类型"
            style={{ width: 140 }}
            onChange={setTypeFilter}
            options={Object.entries(codeTypeLabel).map(([v, l]) => ({ value: v, label: l }))}
          />
          <Button icon={<ReloadOutlined />} onClick={() => load(1)}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateVisible(true)}>
            新增编码
          </Button>
          <Button
            icon={<CloudSyncOutlined />}
            disabled={selectedRowKeys.length === 0}
            onClick={() => setSyncModal({ open: true, selectedIds: selectedRowKeys })}
          >
            同步到门店（已选 {selectedRowKeys.length}）
          </Button>
        </Space>

        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          columns={columns}
          rowSelection={{ selectedRowKeys, onChange: (keys) => setSelectedRowKeys(keys as string[]) }}
          pagination={{ current: page, total, pageSize: 20, onChange: load }}
          scroll={{ x: 750 }}
          size="small"
        />
      </Card>

      {/* 新增 Modal */}
      <Modal
        title="新增公共代码"
        open={createVisible}
        onCancel={() => { setCreateVisible(false); createForm.resetFields(); }}
        onOk={handleCreate}
        confirmLoading={submitting}
        width={540}
      >
        <Form form={createForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="code_type" label="编码类型" rules={[{ required: true }]}>
                <Select options={Object.entries(codeTypeLabel).map(([v, l]) => ({ value: v, label: l }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="code_no" label="编码编号" rules={[{ required: true }]}>
                <Input placeholder="MAT-001" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="unit" label="单位">
                <Input placeholder="kg/个/份" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="price_fen" label="参考价（分）">
                <InputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="description" label="说明">
                <Input.TextArea rows={2} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 同步 Modal */}
      <Modal
        title={`同步 ${syncModal.selectedIds.length} 条编码到门店`}
        open={syncModal.open}
        onCancel={() => { setSyncModal({ open: false, selectedIds: [] }); syncForm.resetFields(); }}
        onOk={handleSync}
        confirmLoading={submitting}
      >
        <Form form={syncForm} layout="vertical">
          <Form.Item
            name="target_stores"
            label="目标门店ID（逗号分隔）"
            rules={[{ required: true, message: '请输入门店ID' }]}
          >
            <Input.TextArea rows={3} placeholder="store-id-1, store-id-2, ..." />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab4：对账报表 ───────────────────────────────────────────────────────────

function ReportTab() {
  const [revenueLoading, setRevenueLoading] = useState(false);
  const [feeLoading, setFeeLoading] = useState(false);
  const [revenueItems, setRevenueItems] = useState<RevenueItem[]>([]);
  const [feeSummaryItems, setFeeSummaryItems] = useState<FeeSummaryItem[]>([]);
  const [revenueMeta, setRevenueMeta] = useState({ total_revenue_fen: 0 });
  const [feeMeta, setFeeMeta] = useState({ grand_receivable_fen: 0, grand_collected_fen: 0, grand_overdue_fen: 0, collection_rate: 0 });
  const [yearMonth, setYearMonth] = useState('');

  const loadRevenue = useCallback(async () => {
    setRevenueLoading(true);
    try {
      const params = new URLSearchParams();
      if (yearMonth) params.set('year_month', yearMonth);
      const res = await txFetchData(`/api/v1/franchise/report/revenue?${params}`) as any;
      if (res?.data) {
        setRevenueItems(res.data.items || []);
        setRevenueMeta({ total_revenue_fen: res.data.total_revenue_fen || 0 });
      }
    } catch {
      message.error('加载营业额报表失败');
    } finally {
      setRevenueLoading(false);
    }
  }, [yearMonth]);

  const loadFees = useCallback(async () => {
    setFeeLoading(true);
    try {
      const params = new URLSearchParams();
      if (yearMonth) params.set('year_month', yearMonth);
      const res = await txFetchData(`/api/v1/franchise/report/fees-summary?${params}`) as any;
      if (res?.data) {
        setFeeSummaryItems(res.data.items || []);
        setFeeMeta({
          grand_receivable_fen: res.data.grand_receivable_fen || 0,
          grand_collected_fen: res.data.grand_collected_fen || 0,
          grand_overdue_fen: res.data.grand_overdue_fen || 0,
          collection_rate: res.data.collection_rate || 0,
        });
      }
    } catch {
      message.error('加载费用汇总失败');
    } finally {
      setFeeLoading(false);
    }
  }, [yearMonth]);

  useEffect(() => { loadRevenue(); loadFees(); }, [loadRevenue, loadFees]);

  const revenueColumns: ColumnsType<RevenueItem> = [
    { title: '加盟商', dataIndex: 'franchisee_name', width: 130 },
    { title: '门店', dataIndex: 'store_name', width: 130 },
    { title: '区域', dataIndex: 'region', width: 100 },
    { title: '订单数', dataIndex: 'order_count', width: 90, align: 'right' },
    {
      title: '营业额',
      dataIndex: 'revenue_fen',
      width: 130,
      align: 'right',
      render: (v) => `¥${fenToYuan(v)}`,
      sorter: (a, b) => a.revenue_fen - b.revenue_fen,
    },
  ];

  const feeColumns: ColumnsType<FeeSummaryItem> = [
    { title: '加盟商', dataIndex: 'franchisee_name', width: 130 },
    { title: '门店', dataIndex: 'store_name', width: 130 },
    {
      title: '应收',
      dataIndex: 'receivable_fen',
      width: 120,
      align: 'right',
      render: (v) => `¥${fenToYuan(v)}`,
    },
    {
      title: '实收',
      dataIndex: 'collected_fen',
      width: 120,
      align: 'right',
      render: (v) => <Text style={{ color: '#52c41a' }}>¥{fenToYuan(v)}</Text>,
    },
    {
      title: '逾期金额',
      dataIndex: 'overdue_fen',
      width: 120,
      align: 'right',
      render: (v) => v > 0 ? <Text type="danger">¥{fenToYuan(v)}</Text> : '—',
      sorter: (a, b) => a.overdue_fen - b.overdue_fen,
    },
    {
      title: '逾期笔数',
      dataIndex: 'overdue_count',
      width: 90,
      align: 'right',
      render: (v) => v > 0 ? <Badge count={v} /> : '0',
    },
  ];

  return (
    <>
      <Card bordered={false} style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text strong>月份筛选：</Text>
          <Input
            placeholder="YYYY-MM（空=全部）"
            style={{ width: 160 }}
            value={yearMonth}
            onChange={(e) => setYearMonth(e.target.value)}
          />
          <Button type="primary" onClick={() => { loadRevenue(); loadFees(); }}>查询</Button>
          <Button onClick={() => { setYearMonth(''); }}>清空</Button>
        </Space>
      </Card>

      {/* 营业额汇总 */}
      <Card
        title={
          <Space>
            <BankOutlined />
            各加盟店营业额汇总
            <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
              合计：¥{fenToYuan(revenueMeta.total_revenue_fen)}
            </Text>
          </Space>
        }
        style={{ marginBottom: 16 }}
        size="small"
      >
        <Table
          rowKey="franchisee_id"
          loading={revenueLoading}
          dataSource={revenueItems}
          columns={revenueColumns}
          pagination={false}
          scroll={{ x: 600 }}
          size="small"
        />
      </Card>

      {/* 费用收缴汇总 */}
      <Card
        title={
          <Space>
            <BankOutlined />
            费用收缴汇总
            <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
              应收：¥{fenToYuan(feeMeta.grand_receivable_fen)}
              ｜实收：¥{fenToYuan(feeMeta.grand_collected_fen)}
              ｜收缴率：{(feeMeta.collection_rate * 100).toFixed(1)}%
              {feeMeta.grand_overdue_fen > 0 && (
                <Text type="danger">｜逾期：¥{fenToYuan(feeMeta.grand_overdue_fen)}</Text>
              )}
            </Text>
          </Space>
        }
        size="small"
      >
        <Table
          rowKey="franchisee_id"
          loading={feeLoading}
          dataSource={feeSummaryItems}
          columns={feeColumns}
          pagination={false}
          scroll={{ x: 680 }}
          size="small"
        />
      </Card>
    </>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function FranchiseManagePage() {
  return (
    <div style={{ padding: '16px 24px' }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        加盟商管理
      </Title>
      <Tabs defaultActiveKey="franchisees" destroyInactiveTabPane={false}>
        <TabPane tab="加盟商档案" key="franchisees">
          <FranchiseeTab />
        </TabPane>
        <TabPane tab="费用收缴" key="fees">
          <FeeTab />
        </TabPane>
        <TabPane tab="公共代码" key="common-codes">
          <CommonCodeTab />
        </TabPane>
        <TabPane tab="对账报表" key="report">
          <ReportTab />
        </TabPane>
      </Tabs>
    </div>
  );
}
