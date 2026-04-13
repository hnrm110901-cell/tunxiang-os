/**
 * 企业客户管理（团餐/B2B）
 * Y-A9
 *
 * Tab 1: 企业档案 — ProTable（公司名/授信额度/已用额/折扣率/状态）+ 授信进度条
 * Tab 2: 订单台账 — 按企业过滤的团餐订单 + 批量出账
 */
import { useCallback, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Form,
  InputNumber,
  message,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Tabs,
  Tooltip,
  Typography,
} from 'antd';
import {
  BankOutlined,
  CheckCircleOutlined,
  DollarOutlined,
  ExportOutlined,
  FileTextOutlined,
  PlusOutlined,
  TeamOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components';
import type { Dayjs } from 'dayjs';
import { formatPrice } from '@tx-ds/utils';

const { Text, Title } = Typography;
const { RangePicker } = DatePicker;

// ─── 类型定义 ──────────────────────────────────────────────────────────────

interface CorporateCustomer {
  id: string;
  company_name: string;
  company_code?: string;
  contact_name?: string;
  contact_phone?: string;
  billing_type: 'monthly' | 'weekly' | 'immediate';
  credit_limit_fen: number;
  used_credit_fen: number;
  available_credit_fen: number;
  tax_no?: string;
  invoice_title?: string;
  discount_rate: number;
  approved_menu_ids: string[];
  status: 'active' | 'inactive';
  created_at: string;
}

interface CorporateOrder {
  id: string;
  corporate_customer_id: string;
  company_name: string;
  store_id: string;
  original_amount_fen: number;
  discount_rate: number;
  discounted_amount_fen: number;
  billing_status: 'unbilled' | 'billed';
  created_at: string;
}

const TENANT_ID = localStorage.getItem('tenantId') || 'demo-tenant';
const API_BASE = '/api/v1/trade/corporate';

const fetchJson = async (url: string, options?: RequestInit) => {
  const resp = await fetch(url, {
    ...options,
    headers: { 'X-Tenant-ID': TENANT_ID, 'Content-Type': 'application/json', ...(options?.headers || {}) },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
    throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
  }
  return resp.json();
};

// ─── 工具函数 ──────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number) => (fen / 100).toLocaleString('zh-CN', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

const BILLING_TYPE_MAP: Record<string, { label: string; color: string }> = {
  monthly:   { label: '月结', color: 'blue' },
  weekly:    { label: '周结', color: 'cyan' },
  immediate: { label: '即结', color: 'green' },
};

// ─── 授信进度条组件 ────────────────────────────────────────────────────────

const CreditProgressBar = ({
  used,
  limit,
}: {
  used: number;
  limit: number;
}) => {
  if (limit === 0) return <Text type="secondary">无授信</Text>;
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const color = pct >= 90 ? '#A32D2D' : pct >= 70 ? '#BA7517' : '#0F6E56';
  return (
    <Tooltip title={`已用 ¥${fenToYuan(used)} / 额度 ¥${fenToYuan(limit)}`}>
      <Progress percent={pct} strokeColor={color} showInfo size="small" style={{ minWidth: 120 }} />
    </Tooltip>
  );
};

// ─── Tab 1: 企业档案 ───────────────────────────────────────────────────────

const CustomerArchive = () => {
  const actionRef = useRef<ActionType>();
  const [editCustomer, setEditCustomer] = useState<CorporateCustomer | null>(null);
  const [creditModal, setCreditModal] = useState<{ visible: boolean; customer?: CorporateCustomer }>({
    visible: false,
  });

  const columns: ProColumns<CorporateCustomer>[] = [
    {
      title: '企业名称',
      dataIndex: 'company_name',
      width: 160,
      render: (_, r) => (
        <Space>
          <BankOutlined style={{ color: '#FF6B35' }} />
          <Text strong>{r.company_name}</Text>
          {r.company_code && <Text type="secondary" style={{ fontSize: 12 }}>({r.company_code})</Text>}
        </Space>
      ),
    },
    {
      title: '联系人',
      dataIndex: 'contact_name',
      width: 100,
      search: false,
      render: (_, r) => (
        <div>
          <div>{r.contact_name || '-'}</div>
          {r.contact_phone && (
            <Text type="secondary" style={{ fontSize: 12 }}>{r.contact_phone}</Text>
          )}
        </div>
      ),
    },
    {
      title: '结算方式',
      dataIndex: 'billing_type',
      width: 80,
      valueType: 'select',
      valueEnum: {
        monthly:   { text: '月结' },
        weekly:    { text: '周结' },
        immediate: { text: '即结' },
      },
      render: (_, r) => {
        const cfg = BILLING_TYPE_MAP[r.billing_type] || BILLING_TYPE_MAP.monthly;
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '授信额度',
      dataIndex: 'credit_limit_fen',
      search: false,
      width: 120,
      render: (_, r) => (
        <Text>¥{fenToYuan(r.credit_limit_fen)}</Text>
      ),
    },
    {
      title: '授信使用情况',
      dataIndex: 'used_credit_fen',
      search: false,
      width: 180,
      render: (_, r) => (
        <CreditProgressBar used={r.used_credit_fen} limit={r.credit_limit_fen} />
      ),
    },
    {
      title: '可用授信',
      dataIndex: 'available_credit_fen',
      search: false,
      width: 110,
      render: (_, r) => {
        const pct = r.credit_limit_fen > 0 ? r.available_credit_fen / r.credit_limit_fen : 1;
        return (
          <Text style={{ color: pct < 0.1 ? '#A32D2D' : pct < 0.3 ? '#BA7517' : '#0F6E56' }}>
            ¥{fenToYuan(r.available_credit_fen)}
          </Text>
        );
      },
    },
    {
      title: '企业折扣',
      dataIndex: 'discount_rate',
      search: false,
      width: 80,
      render: (_, r) => {
        const pct = (r.discount_rate * 10).toFixed(1);
        const isFullPrice = r.discount_rate >= 1;
        return (
          <Tag color={isFullPrice ? 'default' : 'orange'}>
            {isFullPrice ? '无折扣' : `${pct}折`}
          </Tag>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      valueType: 'select',
      valueEnum: {
        active:   { text: '正常', status: 'Success' },
        inactive: { text: '停用', status: 'Error' },
      },
      render: (_, r) => (
        <Badge
          status={r.status === 'active' ? 'success' : 'error'}
          text={r.status === 'active' ? '正常' : '停用'}
        />
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 180,
      render: (_, r) => [
        <a
          key="credit"
          onClick={() => setCreditModal({ visible: true, customer: r })}
          style={{ color: '#185FA5' }}
        >
          授信详情
        </a>,
        <Divider type="vertical" key="d1" />,
        <a
          key="edit"
          onClick={() => setEditCustomer(r)}
          style={{ color: '#FF6B35' }}
        >
          编辑
        </a>,
      ],
    },
  ];

  const handleCreate = async (values: Record<string, unknown>) => {
    await fetchJson(`${API_BASE}/customers`, {
      method: 'POST',
      body: JSON.stringify({
        ...values,
        credit_limit_fen: Math.round((values.credit_limit_yuan as number) * 100),
        discount_rate: (values.discount_rate as number) / 100,
      }),
    });
    message.success('企业客户创建成功');
    actionRef.current?.reload();
    return true;
  };

  const handleUpdate = async (values: Record<string, unknown>) => {
    if (!editCustomer) return false;
    await fetchJson(`${API_BASE}/customers/${editCustomer.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        ...values,
        ...(values.credit_limit_yuan !== undefined
          ? { credit_limit_fen: Math.round((values.credit_limit_yuan as number) * 100) }
          : {}),
        ...(values.discount_rate !== undefined
          ? { discount_rate: (values.discount_rate as number) / 100 }
          : {}),
      }),
    });
    message.success('更新成功');
    setEditCustomer(null);
    actionRef.current?.reload();
    return true;
  };

  return (
    <>
      <ProTable<CorporateCustomer>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query = new URLSearchParams({
            page: String(params.current || 1),
            size: String(params.pageSize || 20),
            ...(params.company_name ? { keyword: params.company_name } : {}),
            ...(params.status ? { status: params.status } : {}),
            ...(params.billing_type ? { billing_type: params.billing_type } : {}),
          });
          try {
            const res = await fetchJson(`${API_BASE}/customers?${query}`);
            return { data: res.data?.items || [], total: res.data?.total || 0, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto', defaultCollapsed: false }}
        pagination={{ defaultPageSize: 20, showQuickJumper: true }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="新增企业客户"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}
                style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}>
                新增企业客户
              </Button>
            }
            onFinish={handleCreate}
            modalProps={{ destroyOnClose: true }}
          >
            <Row gutter={16}>
              <Col span={12}>
                <ProFormText name="company_name" label="企业名称" rules={[{ required: true }]} />
              </Col>
              <Col span={12}>
                <ProFormText name="company_code" label="企业编码" />
              </Col>
              <Col span={12}>
                <ProFormText name="contact_name" label="联系人" />
              </Col>
              <Col span={12}>
                <ProFormText name="contact_phone" label="联系电话" />
              </Col>
              <Col span={12}>
                <ProFormSelect
                  name="billing_type"
                  label="结算方式"
                  initialValue="monthly"
                  options={[
                    { label: '月结', value: 'monthly' },
                    { label: '周结', value: 'weekly' },
                    { label: '即结', value: 'immediate' },
                  ]}
                />
              </Col>
              <Col span={12}>
                <ProFormDigit name="credit_limit_yuan" label="授信额度（元）" min={0} />
              </Col>
              <Col span={12}>
                <ProFormDigit
                  name="discount_rate"
                  label="折扣率（%，如95=九五折）"
                  min={1} max={100} initialValue={100}
                />
              </Col>
              <Col span={12}>
                <ProFormText name="tax_no" label="开票税号" />
              </Col>
              <Col span={24}>
                <ProFormText name="invoice_title" label="发票抬头" />
              </Col>
            </Row>
          </ModalForm>,
        ]}
      />

      {/* 编辑弹窗 */}
      {editCustomer && (
        <ModalForm
          title={`编辑企业客户：${editCustomer.company_name}`}
          open
          onOpenChange={(v) => { if (!v) setEditCustomer(null); }}
          onFinish={handleUpdate}
          initialValues={{
            contact_name: editCustomer.contact_name,
            contact_phone: editCustomer.contact_phone,
            billing_type: editCustomer.billing_type,
            credit_limit_yuan: editCustomer.credit_limit_fen / 100,
            discount_rate: Math.round(editCustomer.discount_rate * 100),
            tax_no: editCustomer.tax_no,
            invoice_title: editCustomer.invoice_title,
            status: editCustomer.status,
          }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <ProFormText name="contact_name" label="联系人" />
            </Col>
            <Col span={12}>
              <ProFormText name="contact_phone" label="联系电话" />
            </Col>
            <Col span={12}>
              <ProFormSelect
                name="billing_type"
                label="结算方式"
                options={[
                  { label: '月结', value: 'monthly' },
                  { label: '周结', value: 'weekly' },
                  { label: '即结', value: 'immediate' },
                ]}
              />
            </Col>
            <Col span={12}>
              <ProFormDigit name="credit_limit_yuan" label="授信额度（元）" min={0} />
            </Col>
            <Col span={12}>
              <ProFormDigit name="discount_rate" label="折扣率（%）" min={1} max={100} />
            </Col>
            <Col span={12}>
              <ProFormSelect
                name="status"
                label="状态"
                options={[
                  { label: '正常', value: 'active' },
                  { label: '停用', value: 'inactive' },
                ]}
              />
            </Col>
            <Col span={12}>
              <ProFormText name="tax_no" label="开票税号" />
            </Col>
            <Col span={12}>
              <ProFormText name="invoice_title" label="发票抬头" />
            </Col>
          </Row>
        </ModalForm>
      )}

      {/* 授信详情弹窗 */}
      <Modal
        title="授信额度详情"
        open={creditModal.visible}
        onCancel={() => setCreditModal({ visible: false })}
        footer={null}
        width={480}
      >
        {creditModal.customer && (() => {
          const c = creditModal.customer!;
          const pct = c.credit_limit_fen > 0
            ? Math.round((c.used_credit_fen / c.credit_limit_fen) * 100) : 0;
          return (
            <Space direction="vertical" style={{ width: '100%' }}>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="企业名称">{c.company_name}</Descriptions.Item>
                <Descriptions.Item label="结算方式">
                  <Tag color={BILLING_TYPE_MAP[c.billing_type]?.color}>
                    {BILLING_TYPE_MAP[c.billing_type]?.label}
                  </Tag>
                </Descriptions.Item>
              </Descriptions>
              <Divider style={{ margin: '8px 0' }} />
              <Row gutter={16}>
                <Col span={8}>
                  <Statistic title="授信额度" value={fenToYuan(c.credit_limit_fen)} prefix="¥" />
                </Col>
                <Col span={8}>
                  <Statistic title="已用授信" value={fenToYuan(c.used_credit_fen)} prefix="¥"
                    valueStyle={{ color: pct >= 90 ? '#A32D2D' : '#2C2C2A' }} />
                </Col>
                <Col span={8}>
                  <Statistic title="可用授信" value={fenToYuan(c.available_credit_fen)} prefix="¥"
                    valueStyle={{ color: pct >= 90 ? '#A32D2D' : '#0F6E56' }} />
                </Col>
              </Row>
              <Progress
                percent={pct}
                strokeColor={pct >= 90 ? '#A32D2D' : pct >= 70 ? '#BA7517' : '#0F6E56'}
                format={p => `${p}%`}
              />
              {pct >= 90 && (
                <Space style={{ color: '#A32D2D' }}>
                  <WarningOutlined />
                  <Text type="danger">授信使用率 ≥ 90%，请及时结算或提高额度</Text>
                </Space>
              )}
            </Space>
          );
        })()}
      </Modal>
    </>
  );
};

// ─── Tab 2: 订单台账 ───────────────────────────────────────────────────────

const OrderLedger = () => {
  const actionRef = useRef<ActionType>();
  const [selectedCustomerId, setSelectedCustomerId] = useState<string>('');
  const [customers, setCustomers] = useState<CorporateCustomer[]>([]);
  const [bulkBillModal, setBulkBillModal] = useState(false);
  const [bulkBillForm] = Form.useForm();
  const [exporting, setExporting] = useState(false);

  // 加载企业列表供过滤
  const loadCustomers = useCallback(async () => {
    try {
      const res = await fetchJson(`${API_BASE}/customers?size=100&status=active`);
      setCustomers(res.data?.items || []);
    } catch {
      setCustomers([]);
    }
  }, []);

  // 导出CSV
  const handleExport = async () => {
    if (!selectedCustomerId) {
      message.warning('请先选择企业客户');
      return;
    }
    setExporting(true);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const monthStart = today.slice(0, 7) + '-01';
      const url = `${API_BASE}/export?corporate_customer_id=${selectedCustomerId}&date_from=${monthStart}&date_to=${today}&format=csv`;
      const resp = await fetch(url, { headers: { 'X-Tenant-ID': TENANT_ID } });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `corporate_bill_${selectedCustomerId}_${monthStart}_${today}.csv`;
      a.click();
      message.success('导出成功');
    } catch {
      message.error('导出失败，请重试');
    } finally {
      setExporting(false);
    }
  };

  // 批量出账
  const handleBulkBill = async (values: { customer_id: string; period: [Dayjs, Dayjs] }) => {
    await fetchJson(`${API_BASE}/orders/bulk-bill`, {
      method: 'POST',
      body: JSON.stringify({
        corporate_customer_id: values.customer_id,
        billing_period_start: values.period[0].format('YYYY-MM-DD'),
        billing_period_end: values.period[1].format('YYYY-MM-DD'),
      }),
    });
    message.success('批量出账成功');
    setBulkBillModal(false);
    bulkBillForm.resetFields();
    actionRef.current?.reload();
    return true;
  };

  const columns: ProColumns<CorporateOrder>[] = [
    {
      title: '订单号',
      dataIndex: 'id',
      width: 200,
      copyable: true,
      render: (_, r) => <Text code style={{ fontSize: 12 }}>{r.id}</Text>,
    },
    {
      title: '企业',
      dataIndex: 'company_name',
      width: 140,
      search: false,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      width: 120,
      search: false,
      render: (_, r) => <Text type="secondary">{r.store_id}</Text>,
    },
    {
      title: '原始金额',
      dataIndex: 'original_amount_fen',
      search: false,
      width: 110,
      render: (_, r) => <Text>¥{fenToYuan(r.original_amount_fen)}</Text>,
    },
    {
      title: '折扣率',
      dataIndex: 'discount_rate',
      search: false,
      width: 80,
      render: (_, r) => (
        <Tag color={r.discount_rate < 1 ? 'orange' : 'default'}>
          {r.discount_rate < 1 ? `${(r.discount_rate * 10).toFixed(1)}折` : '无折扣'}
        </Tag>
      ),
    },
    {
      title: '实际金额',
      dataIndex: 'discounted_amount_fen',
      search: false,
      width: 110,
      render: (_, r) => (
        <Text strong style={{ color: '#FF6B35' }}>
          ¥{fenToYuan(r.discounted_amount_fen)}
        </Text>
      ),
    },
    {
      title: '账单状态',
      dataIndex: 'billing_status',
      width: 100,
      valueType: 'select',
      valueEnum: {
        unbilled: { text: '未出账', status: 'Warning' },
        billed:   { text: '已出账', status: 'Success' },
      },
      render: (_, r) => (
        <Badge
          status={r.billing_status === 'billed' ? 'success' : 'warning'}
          text={r.billing_status === 'billed' ? '已出账' : '未出账'}
        />
      ),
    },
    {
      title: '下单时间',
      dataIndex: 'created_at',
      search: false,
      width: 160,
      valueType: 'dateTime',
      render: (_, r) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {r.created_at.replace('T', ' ').slice(0, 19)}
        </Text>
      ),
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <Text strong>企业过滤：</Text>
        <Select
          style={{ minWidth: 200 }}
          placeholder="选择企业客户"
          allowClear
          showSearch
          filterOption={(input, option) =>
            String(option?.label || '').toLowerCase().includes(input.toLowerCase())
          }
          options={customers.map(c => ({ label: c.company_name, value: c.id }))}
          value={selectedCustomerId || undefined}
          onChange={v => setSelectedCustomerId(v || '')}
          onFocus={loadCustomers}
        />
      </div>

      <ProTable<CorporateOrder>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query = new URLSearchParams({
            page: String(params.current || 1),
            size: String(params.pageSize || 20),
            ...(selectedCustomerId ? { corporate_customer_id: selectedCustomerId } : {}),
            ...(params.billing_status ? { billing_status: params.billing_status } : {}),
          });
          try {
            const res = await fetchJson(`${API_BASE}/orders?${query}`);
            return { data: res.data?.items || [], total: res.data?.total || 0, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <Button
            key="export"
            icon={<ExportOutlined />}
            onClick={handleExport}
            loading={exporting}
            disabled={!selectedCustomerId}
          >
            导出CSV
          </Button>,
          <Button
            key="bulkbill"
            type="primary"
            icon={<FileTextOutlined />}
            onClick={() => setBulkBillModal(true)}
            style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
          >
            批量出账
          </Button>,
        ]}
      />

      {/* 批量出账弹窗 */}
      <Modal
        title="批量账单生成"
        open={bulkBillModal}
        onCancel={() => { setBulkBillModal(false); bulkBillForm.resetFields(); }}
        onOk={() => bulkBillForm.submit()}
        okText="确认出账"
        okButtonProps={{ style: { backgroundColor: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form
          form={bulkBillForm}
          layout="vertical"
          onFinish={handleBulkBill}
        >
          <Form.Item
            name="customer_id"
            label="选择企业客户"
            rules={[{ required: true, message: '请选择企业客户' }]}
            initialValue={selectedCustomerId || undefined}
          >
            <Select
              placeholder="请选择企业客户"
              showSearch
              filterOption={(input, option) =>
                String(option?.label || '').toLowerCase().includes(input.toLowerCase())
              }
              options={customers.map(c => ({ label: c.company_name, value: c.id }))}
              onFocus={loadCustomers}
            />
          </Form.Item>
          <Form.Item
            name="period"
            label="账期范围"
            rules={[{ required: true, message: '请选择账期范围' }]}
          >
            <RangePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
        <Card size="small" style={{ marginTop: 8, backgroundColor: '#FFF3ED' }}>
          <Space>
            <CheckCircleOutlined style={{ color: '#FF6B35' }} />
            <Text style={{ fontSize: 12 }}>
              出账后，该企业在账期内所有"未出账"订单将标记为"已出账"，
              并生成账单PDF文本。账单生成后不可撤销，请确认账期无误。
            </Text>
          </Space>
        </Card>
      </Modal>
    </>
  );
};

// ─── 主页面 ────────────────────────────────────────────────────────────────

export default function CorporateCustomerPage() {
  const [activeTab, setActiveTab] = useState('archive');

  return (
    <div style={{ padding: 24, minWidth: 1280 }}>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <TeamOutlined style={{ fontSize: 20, color: '#FF6B35' }} />
        <Title level={4} style={{ margin: 0 }}>企业客户管理</Title>
        <Tag color="orange" icon={<BankOutlined />}>Y-A9 团餐</Tag>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'archive',
            label: (
              <Space>
                <BankOutlined />
                企业档案
              </Space>
            ),
            children: <CustomerArchive />,
          },
          {
            key: 'orders',
            label: (
              <Space>
                <DollarOutlined />
                订单台账
              </Space>
            ),
            children: <OrderLedger />,
          },
        ]}
      />
    </div>
  );
}
