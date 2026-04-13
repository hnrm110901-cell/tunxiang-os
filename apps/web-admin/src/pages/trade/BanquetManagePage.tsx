/**
 * Y-A8 宴席管理页 — 定金/尾款支付闭环
 *
 * Tab 1: 预订台账 (ProTable)
 * Tab 2: 支付流水
 * Tab 3: 月度统计
 *
 * 遵循 Admin 终端规范：
 *   - Ant Design 5.x + ProComponents
 *   - ConfigProvider 注入屯象主题
 *   - ProTable 列表 + ModalForm 操作弹窗
 *   - 最小支持 1280px
 */
import React, { useRef, useState } from 'react';
import {
  Button,
  Col,
  ConfigProvider,
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
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DollarOutlined,
  FileTextOutlined,
  LoadingOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDatePicker,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTimePicker,
  ProTable,
} from '@ant-design/pro-components';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

// ─── 屯象主题 Token ──────────────────────────────────────────────────────────

const txAdminTheme = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Layout: { headerBg: '#1E2A3A', siderBg: '#1E2A3A' },
    Menu: { darkItemBg: '#1E2A3A', darkItemSelectedBg: '#FF6B35' },
    Table: { headerBg: '#F8F7F5' },
  },
};

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface BanquetOrder {
  id: string;
  tenant_id: string;
  store_id: string;
  contact_name: string;
  contact_phone: string;
  banquet_date: string;
  banquet_time: string;
  guest_count: number;
  total_fen: number;
  deposit_fen: number;
  balance_fen: number;
  deposit_rate: string;
  deposit_status: 'unpaid' | 'paid';
  balance_status: 'unpaid' | 'paid';
  payment_status: 'unpaid' | 'deposit_paid' | 'fully_paid' | 'refunded';
  status: 'pending' | 'confirmed' | 'in_progress' | 'completed' | 'cancelled';
  notes: string;
  cancel_reason?: string;
  cancelled_at?: string;
  payments?: PaymentRecord[];
}

interface PaymentRecord {
  id: string;
  banquet_order_id: string;
  payment_stage: 'deposit' | 'balance' | 'full';
  amount_fen: number;
  payment_method: string;
  payment_status: 'pending' | 'paid' | 'refunding' | 'refunded' | 'failed';
  transaction_id?: string;
  paid_at?: string;
  refund_amount_fen: number;
  refunded_at?: string;
  notes: string;
}

interface MonthStats {
  year: number;
  month: number;
  total_count: number;
  cancelled_count: number;
  cancel_rate: number;
  deposit_paid_count: number;
  fully_paid_count: number;
  unpaid_count: number;
  deposit_income_fen: number;
  balance_income_fen: number;
  total_income_fen: number;
}

// ─── 辅助函数 ────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;

const getPaymentStatusTag = (status: BanquetOrder['payment_status']) => {
  const map: Record<string, { color: string; label: string }> = {
    unpaid: { color: 'default', label: '未支付' },
    deposit_paid: { color: 'processing', label: '已付定金' },
    fully_paid: { color: 'success', label: '已全额付清' },
    refunded: { color: 'error', label: '已退款' },
  };
  const item = map[status] ?? { color: 'default', label: status };
  return <Tag color={item.color}>{item.label}</Tag>;
};

const getOrderStatusTag = (status: BanquetOrder['status']) => {
  const map: Record<string, { color: string; label: string }> = {
    pending: { color: 'default', label: '待确认' },
    confirmed: { color: 'processing', label: '已确认' },
    in_progress: { color: 'warning', label: '进行中' },
    completed: { color: 'success', label: '已完成' },
    cancelled: { color: 'error', label: '已取消' },
  };
  const item = map[status] ?? { color: 'default', label: status };
  return <Tag color={item.color}>{item.label}</Tag>;
};

const payMethodLabel: Record<string, string> = {
  wechat: '微信支付',
  alipay: '支付宝',
  cash: '现金',
  card: '刷卡',
  transfer: '对公转账',
};

// ─── API 调用层（mock / 真实可替换） ────────────────────────────────────────

const TENANT_ID = localStorage.getItem('tenantId') ?? 't-demo-001';
const BASE = '/api/v1/trade/banquet';

const headers: Record<string, string> = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
};

async function apiFetch<T = unknown>(
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!json.ok) {
    throw new Error(json.error?.message ?? '请求失败');
  }
  return json.data as T;
}

// ─── 主页面组件 ──────────────────────────────────────────────────────────────

export default function BanquetManagePage() {
  const tableRef = useRef<ActionType>();
  const [activeTab, setActiveTab] = useState('ledger');
  const [selectedOrder, setSelectedOrder] = useState<BanquetOrder | null>(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [payDepositVisible, setPayDepositVisible] = useState(false);
  const [payBalanceVisible, setPayBalanceVisible] = useState(false);
  const [stats, setStats] = useState<MonthStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [allPayments, setAllPayments] = useState<PaymentRecord[]>([]);
  const [paymentsLoading, setPaymentsLoading] = useState(false);

  const [payDepositForm] = Form.useForm();
  const [payBalanceForm] = Form.useForm();

  // ─── 加载月度统计 ─────────────────────────────────────────────────────────
  const loadStats = async () => {
    setStatsLoading(true);
    try {
      const data = await apiFetch<MonthStats>('/stats?year=2026&month=4');
      setStats(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`统计加载失败：${msg}`);
    } finally {
      setStatsLoading(false);
    }
  };

  // ─── 加载所有支付流水 ─────────────────────────────────────────────────────
  const loadAllPayments = async () => {
    setPaymentsLoading(true);
    try {
      const data = await apiFetch<{ items: BanquetOrder[]; total: number }>('/orders?size=100');
      const payments: PaymentRecord[] = [];
      for (const order of data.items) {
        const detail = await apiFetch<BanquetOrder & { payments: PaymentRecord[] }>(
          `/orders/${order.id}`,
        );
        (detail.payments ?? []).forEach((p) => payments.push(p));
      }
      setAllPayments(payments);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`流水加载失败：${msg}`);
    } finally {
      setPaymentsLoading(false);
    }
  };

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    if (key === 'stats' && !stats) loadStats();
    if (key === 'payments' && allPayments.length === 0) loadAllPayments();
  };

  // ─── 打开订单详情 ─────────────────────────────────────────────────────────
  const openDetail = async (order: BanquetOrder) => {
    try {
      const detail = await apiFetch<BanquetOrder & { payments: PaymentRecord[] }>(
        `/orders/${order.id}`,
      );
      setSelectedOrder({ ...detail, payments: detail.payments ?? [] });
      setDetailVisible(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(msg);
    }
  };

  // ─── 支付定金 ─────────────────────────────────────────────────────────────
  const handlePayDeposit = async () => {
    if (!selectedOrder) return;
    try {
      const values = await payDepositForm.validateFields();
      await apiFetch(`/orders/${selectedOrder.id}/pay-deposit`, 'POST', {
        payment_method: values.payment_method,
        amount_fen: Math.round(values.amount_yuan * 100),
        transaction_id: values.transaction_id || undefined,
        notes: values.notes || '',
      });
      message.success('定金收取成功');
      setPayDepositVisible(false);
      setDetailVisible(false);
      payDepositForm.resetFields();
      tableRef.current?.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '操作失败';
      message.error(msg);
    }
  };

  // ─── 支付尾款 ─────────────────────────────────────────────────────────────
  const handlePayBalance = async () => {
    if (!selectedOrder) return;
    try {
      const values = await payBalanceForm.validateFields();
      await apiFetch(`/orders/${selectedOrder.id}/pay-balance`, 'POST', {
        payment_method: values.payment_method,
        amount_fen: Math.round(values.amount_yuan * 100),
        transaction_id: values.transaction_id || undefined,
        notes: values.notes || '',
      });
      message.success('尾款收取成功');
      setPayBalanceVisible(false);
      setDetailVisible(false);
      payBalanceForm.resetFields();
      tableRef.current?.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '操作失败';
      message.error(msg);
    }
  };

  // ─── ProTable 列定义 ──────────────────────────────────────────────────────
  const columns: ProColumns<BanquetOrder>[] = [
    {
      title: '预订人',
      dataIndex: 'contact_name',
      valueType: 'text',
      width: 120,
    },
    {
      title: '联系电话',
      dataIndex: 'contact_phone',
      valueType: 'text',
      width: 130,
      hideInSearch: true,
    },
    {
      title: '宴席日期',
      dataIndex: 'banquet_date',
      valueType: 'date',
      width: 120,
      sorter: true,
    },
    {
      title: '宴席时间',
      dataIndex: 'banquet_time',
      valueType: 'text',
      width: 90,
      hideInSearch: true,
    },
    {
      title: '宾客人数',
      dataIndex: 'guest_count',
      valueType: 'digit',
      width: 90,
      hideInSearch: true,
    },
    {
      title: '总金额',
      dataIndex: 'total_fen',
      width: 120,
      hideInSearch: true,
      render: (_, r) => (
        <Text strong>{fenToYuan(r.total_fen)}</Text>
      ),
    },
    {
      title: '应付定金',
      dataIndex: 'deposit_fen',
      width: 120,
      hideInSearch: true,
      render: (_, r) => (
        <span style={{ color: '#BA7517' }}>{fenToYuan(r.deposit_fen)}</span>
      ),
    },
    {
      title: '应付尾款',
      dataIndex: 'balance_fen',
      width: 120,
      hideInSearch: true,
      render: (_, r) => fenToYuan(r.balance_fen),
    },
    {
      title: '订单状态',
      dataIndex: 'status',
      width: 100,
      hideInSearch: true,
      render: (_, r) => getOrderStatusTag(r.status),
    },
    {
      title: '支付状态',
      dataIndex: 'payment_status',
      width: 120,
      valueType: 'select',
      valueEnum: {
        unpaid: { text: '未支付', status: 'Default' },
        deposit_paid: { text: '已付定金', status: 'Processing' },
        fully_paid: { text: '已全额付清', status: 'Success' },
        refunded: { text: '已退款', status: 'Error' },
      },
      render: (_, r) => getPaymentStatusTag(r.payment_status),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, record) => {
        const actions = [
          <a key="detail" onClick={() => openDetail(record)}>
            详情
          </a>,
        ];
        if (record.deposit_status === 'unpaid' && record.status !== 'cancelled') {
          actions.push(
            <a
              key="deposit"
              style={{ color: '#FF6B35' }}
              onClick={() => {
                setSelectedOrder(record);
                payDepositForm.setFieldsValue({
                  amount_yuan: record.deposit_fen / 100,
                  payment_method: 'wechat',
                });
                setPayDepositVisible(true);
              }}
            >
              收定金
            </a>,
          );
        }
        if (
          record.deposit_status === 'paid' &&
          record.balance_status === 'unpaid' &&
          record.status !== 'cancelled'
        ) {
          actions.push(
            <a
              key="balance"
              style={{ color: '#0F6E56' }}
              onClick={() => {
                setSelectedOrder(record);
                payBalanceForm.setFieldsValue({
                  amount_yuan: record.balance_fen / 100,
                  payment_method: 'wechat',
                });
                setPayBalanceVisible(true);
              }}
            >
              收尾款
            </a>,
          );
        }
        return <Space size={8}>{actions}</Space>;
      },
    },
  ];

  // ─── 支付流水列 ───────────────────────────────────────────────────────────
  const paymentColumns: ProColumns<PaymentRecord>[] = [
    {
      title: '订单编号',
      dataIndex: 'banquet_order_id',
      width: 140,
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'payment_stage',
      width: 90,
      render: (_, r) => {
        const map = { deposit: '定金', balance: '尾款', full: '全额' };
        const label = map[r.payment_stage] ?? r.payment_stage;
        const color = r.payment_stage === 'deposit' ? 'orange' : r.payment_stage === 'balance' ? 'green' : 'blue';
        return <Tag color={color}>{label}</Tag>;
      },
    },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      width: 110,
      render: (_, r) => <Text strong>{fenToYuan(r.amount_fen)}</Text>,
    },
    {
      title: '支付方式',
      dataIndex: 'payment_method',
      width: 110,
      render: (_, r) => payMethodLabel[r.payment_method] ?? r.payment_method,
    },
    {
      title: '状态',
      dataIndex: 'payment_status',
      width: 90,
      render: (_, r) => {
        const map: Record<string, string> = {
          paid: 'success',
          pending: 'default',
          refunded: 'error',
          failed: 'error',
          refunding: 'warning',
        };
        const labelMap: Record<string, string> = {
          paid: '已支付',
          pending: '待支付',
          refunded: '已退款',
          failed: '失败',
          refunding: '退款中',
        };
        return (
          <Tag color={map[r.payment_status] ?? 'default'}>
            {labelMap[r.payment_status] ?? r.payment_status}
          </Tag>
        );
      },
    },
    {
      title: '流水号',
      dataIndex: 'transaction_id',
      width: 160,
      ellipsis: true,
      render: (v) => v ?? '—',
    },
    {
      title: '支付时间',
      dataIndex: 'paid_at',
      width: 160,
      render: (v) => (v ? String(v).replace('T', ' ').slice(0, 19) : '—'),
    },
    {
      title: '备注',
      dataIndex: 'notes',
      ellipsis: true,
      render: (v) => v || '—',
    },
  ];

  // ─── Tab 1: 预订台账 ──────────────────────────────────────────────────────
  const renderLedger = () => (
    <ProTable<BanquetOrder>
      actionRef={tableRef}
      rowKey="id"
      columns={columns}
      request={async (params) => {
        try {
          const qs = new URLSearchParams({
            page: String(params.current ?? 1),
            size: String(params.pageSize ?? 20),
          });
          if (params.payment_status) qs.set('payment_status', params.payment_status);
          if (params.banquet_date) qs.set('banquet_date', params.banquet_date);
          const data = await apiFetch<{ items: BanquetOrder[]; total: number }>(
            `/orders?${qs.toString()}`,
          );
          return { data: data.items, total: data.total, success: true };
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : '加载失败';
          message.error(msg);
          return { data: [], total: 0, success: false };
        }
      }}
      search={{ labelWidth: 'auto' }}
      pagination={{ defaultPageSize: 20 }}
      toolBarRender={() => [
        <ModalForm<{
          store_id: string;
          contact_name: string;
          contact_phone: string;
          banquet_date: string;
          banquet_time: string;
          guest_count: number;
          total_fen_yuan: number;
          deposit_rate: number;
          notes?: string;
        }>
          key="create"
          title="新建宴席预订"
          trigger={
            <Button type="primary" icon={<PlusOutlined />}>
              新建预订
            </Button>
          }
          onFinish={async (values) => {
            try {
              await apiFetch('/orders', 'POST', {
                store_id: values.store_id,
                contact_name: values.contact_name,
                contact_phone: values.contact_phone,
                banquet_date: values.banquet_date,
                banquet_time: values.banquet_time,
                guest_count: values.guest_count,
                total_fen: Math.round(values.total_fen_yuan * 100),
                deposit_rate: values.deposit_rate / 100,
                notes: values.notes ?? '',
              });
              message.success('预订创建成功');
              tableRef.current?.reload();
              return true;
            } catch (err: unknown) {
              const msg = err instanceof Error ? err.message : '创建失败';
              message.error(msg);
              return false;
            }
          }}
        >
          <ProFormText name="store_id" label="门店ID" initialValue="s-demo-001" rules={[{ required: true }]} />
          <ProFormText name="contact_name" label="预订人姓名" rules={[{ required: true }]} />
          <ProFormText name="contact_phone" label="联系电话" rules={[{ required: true }]} />
          <Row gutter={16}>
            <Col span={12}>
              <ProFormDatePicker name="banquet_date" label="宴席日期" rules={[{ required: true }]} />
            </Col>
            <Col span={12}>
              <ProFormTimePicker name="banquet_time" label="宴席时间" fieldProps={{ format: 'HH:mm' }} rules={[{ required: true }]} />
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <ProFormDigit name="guest_count" label="宾客人数" min={1} rules={[{ required: true }]} />
            </Col>
            <Col span={8}>
              <ProFormDigit name="total_fen_yuan" label="宴席总额（元）" min={0.01} rules={[{ required: true }]} />
            </Col>
            <Col span={8}>
              <ProFormDigit
                name="deposit_rate"
                label="定金比例（%）"
                min={1}
                max={100}
                initialValue={30}
                fieldProps={{ formatter: (v) => `${v}%`, parser: (v) => Number(v?.replace('%', '')) }}
              />
            </Col>
          </Row>
          <ProFormText name="notes" label="备注" />
        </ModalForm>,
      ]}
      scroll={{ x: 1400 }}
    />
  );

  // ─── Tab 2: 支付流水 ──────────────────────────────────────────────────────
  const renderPayments = () => (
    <ProTable<PaymentRecord>
      rowKey="id"
      columns={paymentColumns}
      loading={paymentsLoading}
      dataSource={allPayments}
      search={false}
      pagination={{ defaultPageSize: 20 }}
      toolBarRender={() => [
        <Button key="refresh" onClick={loadAllPayments} loading={paymentsLoading}>
          刷新
        </Button>,
      ]}
      scroll={{ x: 1100 }}
    />
  );

  // ─── Tab 3: 月度统计 ──────────────────────────────────────────────────────
  const renderStats = () => {
    if (statsLoading) {
      return (
        <div style={{ textAlign: 'center', padding: 80 }}>
          <LoadingOutlined style={{ fontSize: 32, color: '#FF6B35' }} />
          <div style={{ marginTop: 16 }}>加载中…</div>
        </div>
      );
    }
    if (!stats) {
      return (
        <div style={{ textAlign: 'center', padding: 80 }}>
          <Button type="primary" onClick={loadStats}>加载月度统计</Button>
        </div>
      );
    }

    const distributionItems = [
      { label: '未支付', count: stats.unpaid_count, color: '#B4B2A9' },
      { label: '已付定金', count: stats.deposit_paid_count - stats.fully_paid_count, color: '#FF6B35' },
      { label: '已全额付清', count: stats.fully_paid_count, color: '#0F6E56' },
      { label: '已取消', count: stats.cancelled_count, color: '#A32D2D' },
    ];
    const total = distributionItems.reduce((s, i) => s + Math.max(0, i.count), 0) || 1;

    return (
      <div style={{ padding: 24 }}>
        <Title level={4} style={{ marginBottom: 24 }}>
          {stats.year}年{stats.month}月 宴席经营概览
        </Title>

        {/* 4个指标卡片 */}
        <Row gutter={16} style={{ marginBottom: 32 }}>
          <Col span={6}>
            <div style={{
              background: '#fff',
              border: '1px solid #E8E6E1',
              borderRadius: 8,
              padding: 24,
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            }}>
              <Statistic
                title="本月预订数"
                value={stats.total_count}
                suffix="单"
                prefix={<FileTextOutlined style={{ color: '#185FA5' }} />}
                valueStyle={{ color: '#185FA5' }}
              />
            </div>
          </Col>
          <Col span={6}>
            <div style={{
              background: '#fff',
              border: '1px solid #E8E6E1',
              borderRadius: 8,
              padding: 24,
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            }}>
              <Statistic
                title="定金收入"
                value={(stats.deposit_income_fen / 100).toFixed(2)}
                prefix={<DollarOutlined style={{ color: '#FF6B35' }} />}
                valueStyle={{ color: '#FF6B35' }}
              />
            </div>
          </Col>
          <Col span={6}>
            <div style={{
              background: '#fff',
              border: '1px solid #E8E6E1',
              borderRadius: 8,
              padding: 24,
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            }}>
              <Statistic
                title="尾款收入"
                value={(stats.balance_income_fen / 100).toFixed(2)}
                prefix={<CheckCircleOutlined style={{ color: '#0F6E56' }} />}
                valueStyle={{ color: '#0F6E56' }}
              />
            </div>
          </Col>
          <Col span={6}>
            <div style={{
              background: '#fff',
              border: '1px solid #E8E6E1',
              borderRadius: 8,
              padding: 24,
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            }}>
              <Statistic
                title="取消数"
                value={stats.cancelled_count}
                suffix={`单（${(stats.cancel_rate * 100).toFixed(1)}%）`}
                prefix={<CloseCircleOutlined style={{ color: '#A32D2D' }} />}
                valueStyle={{ color: '#A32D2D' }}
              />
            </div>
          </Col>
        </Row>

        {/* 状态分布条 */}
        <div style={{
          background: '#fff',
          border: '1px solid #E8E6E1',
          borderRadius: 8,
          padding: 24,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <Title level={5} style={{ marginBottom: 16 }}>支付状态分布</Title>
          <div style={{ display: 'flex', height: 32, borderRadius: 6, overflow: 'hidden', marginBottom: 16 }}>
            {distributionItems.map((item) => {
              const pct = (Math.max(0, item.count) / total) * 100;
              if (pct < 0.5) return null;
              return (
                <div
                  key={item.label}
                  title={`${item.label}: ${item.count}单 (${pct.toFixed(1)}%)`}
                  style={{
                    width: `${pct}%`,
                    background: item.color,
                    transition: 'width 0.4s ease',
                  }}
                />
              );
            })}
          </div>
          <Row gutter={16}>
            {distributionItems.map((item) => (
              <Col key={item.label} span={6}>
                <Space>
                  <span style={{
                    display: 'inline-block',
                    width: 12,
                    height: 12,
                    borderRadius: 3,
                    background: item.color,
                  }} />
                  <Text type="secondary">{item.label}</Text>
                  <Text strong>{Math.max(0, item.count)}单</Text>
                </Space>
              </Col>
            ))}
          </Row>

          {/* 收入汇总 */}
          <div style={{ marginTop: 24, borderTop: '1px solid #E8E6E1', paddingTop: 16 }}>
            <Row gutter={16}>
              <Col span={8}>
                <Text type="secondary">本月总收入：</Text>
                <Text strong style={{ fontSize: 16, color: '#0F6E56' }}>
                  {fenToYuan(stats.total_income_fen)}
                </Text>
              </Col>
              <Col span={8}>
                <Text type="secondary">其中定金：</Text>
                <Text strong style={{ color: '#FF6B35' }}>
                  {fenToYuan(stats.deposit_income_fen)}
                </Text>
              </Col>
              <Col span={8}>
                <Text type="secondary">其中尾款：</Text>
                <Text strong style={{ color: '#0F6E56' }}>
                  {fenToYuan(stats.balance_income_fen)}
                </Text>
              </Col>
            </Row>
          </div>
        </div>
      </div>
    );
  };

  // ─── 订单详情 Modal ───────────────────────────────────────────────────────
  const renderDetailModal = () => {
    if (!selectedOrder) return null;
    const pays = selectedOrder.payments ?? [];
    return (
      <Modal
        title={`宴席详情 — ${selectedOrder.contact_name}`}
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={720}
      >
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <Text type="secondary">预订人：</Text>
            <Text strong>{selectedOrder.contact_name}</Text>
          </Col>
          <Col span={12}>
            <Text type="secondary">联系电话：</Text>
            <Text>{selectedOrder.contact_phone}</Text>
          </Col>
          <Col span={12} style={{ marginTop: 8 }}>
            <Text type="secondary">宴席日期：</Text>
            <Text>{selectedOrder.banquet_date} {selectedOrder.banquet_time}</Text>
          </Col>
          <Col span={12} style={{ marginTop: 8 }}>
            <Text type="secondary">宾客人数：</Text>
            <Text>{selectedOrder.guest_count} 人</Text>
          </Col>
          <Col span={12} style={{ marginTop: 8 }}>
            <Text type="secondary">总金额：</Text>
            <Text strong>{fenToYuan(selectedOrder.total_fen)}</Text>
          </Col>
          <Col span={12} style={{ marginTop: 8 }}>
            <Text type="secondary">定金比例：</Text>
            <Text>{(parseFloat(selectedOrder.deposit_rate) * 100).toFixed(0)}%（{fenToYuan(selectedOrder.deposit_fen)}）</Text>
          </Col>
          <Col span={12} style={{ marginTop: 8 }}>
            <Text type="secondary">支付状态：</Text>
            {getPaymentStatusTag(selectedOrder.payment_status)}
          </Col>
          <Col span={12} style={{ marginTop: 8 }}>
            <Text type="secondary">订单状态：</Text>
            {getOrderStatusTag(selectedOrder.status)}
          </Col>
          {selectedOrder.notes && (
            <Col span={24} style={{ marginTop: 8 }}>
              <Text type="secondary">备注：</Text>
              <Text>{selectedOrder.notes}</Text>
            </Col>
          )}
        </Row>

        <Title level={5} style={{ marginTop: 16, marginBottom: 8 }}>支付记录</Title>
        {pays.length === 0 ? (
          <Text type="secondary">暂无支付记录</Text>
        ) : (
          <div>
            {pays.map((p) => (
              <div
                key={p.id}
                style={{
                  border: '1px solid #E8E6E1',
                  borderRadius: 6,
                  padding: 12,
                  marginBottom: 8,
                  background: '#F8F7F5',
                }}
              >
                <Row gutter={8}>
                  <Col span={6}>
                    <Tag color={p.payment_stage === 'deposit' ? 'orange' : 'green'}>
                      {p.payment_stage === 'deposit' ? '定金' : p.payment_stage === 'balance' ? '尾款' : '全额'}
                    </Tag>
                  </Col>
                  <Col span={6}>
                    <Text strong style={{ color: '#FF6B35' }}>{fenToYuan(p.amount_fen)}</Text>
                  </Col>
                  <Col span={6}>
                    <Text type="secondary">{payMethodLabel[p.payment_method] ?? p.payment_method}</Text>
                  </Col>
                  <Col span={6}>
                    <Tag color={p.payment_status === 'paid' ? 'success' : 'error'}>
                      {p.payment_status === 'paid' ? '已支付' : p.payment_status}
                    </Tag>
                  </Col>
                </Row>
                {p.transaction_id && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>流水号：{p.transaction_id}</Text>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {selectedOrder.deposit_status === 'unpaid' && selectedOrder.status !== 'cancelled' && (
            <Button
              type="primary"
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
              onClick={() => {
                setDetailVisible(false);
                payDepositForm.setFieldsValue({
                  amount_yuan: selectedOrder.deposit_fen / 100,
                  payment_method: 'wechat',
                });
                setPayDepositVisible(true);
              }}
            >
              收定金
            </Button>
          )}
          {selectedOrder.deposit_status === 'paid' &&
            selectedOrder.balance_status === 'unpaid' &&
            selectedOrder.status !== 'cancelled' && (
              <Button
                type="primary"
                style={{ background: '#0F6E56', borderColor: '#0F6E56' }}
                onClick={() => {
                  setDetailVisible(false);
                  payBalanceForm.setFieldsValue({
                    amount_yuan: selectedOrder.balance_fen / 100,
                    payment_method: 'wechat',
                  });
                  setPayBalanceVisible(true);
                }}
              >
                收尾款
              </Button>
            )}
          <Button onClick={() => setDetailVisible(false)}>关闭</Button>
        </div>
      </Modal>
    );
  };

  // ─── 收定金 Modal ─────────────────────────────────────────────────────────
  const renderPayDepositModal = () => (
    <Modal
      title={`收定金 — ${selectedOrder?.contact_name ?? ''}`}
      open={payDepositVisible}
      onOk={handlePayDeposit}
      onCancel={() => {
        setPayDepositVisible(false);
        payDepositForm.resetFields();
      }}
      okText="确认收款"
      okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
    >
      {selectedOrder && (
        <div style={{ marginBottom: 12, padding: 12, background: '#FFF3ED', borderRadius: 6 }}>
          <Text>
            应付定金：<Text strong style={{ color: '#FF6B35' }}>
              {fenToYuan(selectedOrder.deposit_fen)}
            </Text>
            （总额 {fenToYuan(selectedOrder.total_fen)} × {(parseFloat(selectedOrder.deposit_rate) * 100).toFixed(0)}%）
          </Text>
        </div>
      )}
      <Form form={payDepositForm} layout="vertical">
        <Form.Item
          name="amount_yuan"
          label="实收金额（元）"
          rules={[
            { required: true, message: '请输入金额' },
            {
              validator: (_, v) => {
                if (!selectedOrder) return Promise.resolve();
                const minYuan = selectedOrder.deposit_fen / 100;
                if (v < minYuan) {
                  return Promise.reject(new Error(`不得少于应付定金 ¥${minYuan.toFixed(2)}`));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" />
        </Form.Item>
        <Form.Item
          name="payment_method"
          label="支付方式"
          rules={[{ required: true }]}
        >
          <Select>
            <Select.Option value="wechat">微信支付</Select.Option>
            <Select.Option value="alipay">支付宝</Select.Option>
            <Select.Option value="cash">现金</Select.Option>
            <Select.Option value="card">刷卡</Select.Option>
            <Select.Option value="transfer">对公转账</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="transaction_id" label="流水号（可选）">
          <Form.Item name="transaction_id" noStyle>
            <input
              style={{
                width: '100%',
                border: '1px solid #d9d9d9',
                borderRadius: 6,
                padding: '4px 11px',
                fontSize: 14,
                outline: 'none',
              }}
              placeholder="第三方支付流水号"
            />
          </Form.Item>
        </Form.Item>
      </Form>
    </Modal>
  );

  // ─── 收尾款 Modal ─────────────────────────────────────────────────────────
  const renderPayBalanceModal = () => (
    <Modal
      title={`收尾款 — ${selectedOrder?.contact_name ?? ''}`}
      open={payBalanceVisible}
      onOk={handlePayBalance}
      onCancel={() => {
        setPayBalanceVisible(false);
        payBalanceForm.resetFields();
      }}
      okText="确认收款"
      okButtonProps={{ style: { background: '#0F6E56', borderColor: '#0F6E56' } }}
    >
      {selectedOrder && (
        <div style={{ marginBottom: 12, padding: 12, background: '#F0FDF4', borderRadius: 6 }}>
          <Text>
            应付尾款：<Text strong style={{ color: '#0F6E56' }}>
              {fenToYuan(selectedOrder.balance_fen)}
            </Text>
            （总额 {fenToYuan(selectedOrder.total_fen)} − 已付定金 {fenToYuan(selectedOrder.deposit_fen)}）
          </Text>
        </div>
      )}
      <Form form={payBalanceForm} layout="vertical">
        <Form.Item
          name="amount_yuan"
          label="实收金额（元）"
          rules={[
            { required: true, message: '请输入金额' },
            {
              validator: (_, v) => {
                if (!selectedOrder) return Promise.resolve();
                const minYuan = selectedOrder.balance_fen / 100;
                if (v < minYuan) {
                  return Promise.reject(new Error(`不得少于应付尾款 ¥${minYuan.toFixed(2)}`));
                }
                return Promise.resolve();
              },
            },
          ]}
        >
          <InputNumber style={{ width: '100%' }} min={0.01} precision={2} prefix="¥" />
        </Form.Item>
        <Form.Item name="payment_method" label="支付方式" rules={[{ required: true }]}>
          <Select>
            <Select.Option value="wechat">微信支付</Select.Option>
            <Select.Option value="alipay">支付宝</Select.Option>
            <Select.Option value="cash">现金</Select.Option>
            <Select.Option value="card">刷卡</Select.Option>
            <Select.Option value="transfer">对公转账</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="transaction_id" label="流水号（可选）">
          <Form.Item name="transaction_id" noStyle>
            <input
              style={{
                width: '100%',
                border: '1px solid #d9d9d9',
                borderRadius: 6,
                padding: '4px 11px',
                fontSize: 14,
                outline: 'none',
              }}
              placeholder="第三方支付流水号"
            />
          </Form.Item>
        </Form.Item>
      </Form>
    </Modal>
  );

  // ─── 渲染 ─────────────────────────────────────────────────────────────────
  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ padding: 24, minWidth: 1280 }}>
        <Title level={3} style={{ marginBottom: 16, color: '#1E2A3A' }}>
          宴席管理
        </Title>

        <Tabs activeKey={activeTab} onChange={handleTabChange}>
          <TabPane tab="预订台账" key="ledger">
            {renderLedger()}
          </TabPane>
          <TabPane tab="支付流水" key="payments">
            {renderPayments()}
          </TabPane>
          <TabPane tab="月度统计" key="stats">
            {renderStats()}
          </TabPane>
        </Tabs>

        {renderDetailModal()}
        {renderPayDepositModal()}
        {renderPayBalanceModal()}
      </div>
    </ConfigProvider>
  );
}
