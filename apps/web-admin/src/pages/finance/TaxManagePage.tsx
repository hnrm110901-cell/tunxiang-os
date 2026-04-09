/**
 * TaxManagePage — Y-F9 税务管理
 *
 * Tab 1: 销项台账  — 月份选择 + ProTable + 月度汇总 Statistic 卡片
 * Tab 2: 进项台账  — ProTable + 批量标记抵扣
 * Tab 3: 科目映射  — 可编辑 Table（税收分类编码 → P&L 科目）
 *
 * Admin 终端规范：Ant Design 5.x + ProComponents + 1280px 最小宽度
 */
import React, { useCallback, useRef, useState } from 'react';
import {
  Button,
  Col,
  DatePicker,
  Form,
  Input,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { StatisticCard } from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';

const { Title, Text } = Typography;
const { TabPane } = require('antd').Tabs ?? {};

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface VatOutputRecord {
  id: string;
  period_month: string;
  tax_code: string;
  tax_rate: string;
  amount_excl_tax_fen: number;
  tax_amount_fen: number;
  amount_incl_tax_fen: number;
  buyer_name: string | null;
  buyer_tax_id: string | null;
  invoice_date: string;
  status: 'normal' | 'voided' | 'red_correction';
  nuonuo_order_id: string | null;
}

interface VatInputRecord {
  id: string;
  period_month: string;
  tax_code: string;
  tax_rate: string;
  amount_excl_tax_fen: number;
  tax_amount_fen: number;
  amount_incl_tax_fen: number;
  seller_name: string | null;
  invoice_code: string | null;
  invoice_number: string | null;
  invoice_date: string;
  deduction_status: 'pending' | 'deducted' | 'rejected';
  pl_account_code: string | null;
}

interface VatMonthlySummary {
  period_month: string;
  output_tax_fen: number;
  input_tax_fen: number;
  net_payable_fen: number;
  output_count: number;
  input_count: number;
  pl_summary: Array<{
    pl_account_code: string;
    pl_account_name: string;
    account_type: string;
    amount_excl_tax_fen: number;
    tax_amount_fen: number;
  }>;
}

interface PlAccountMapping {
  id: string;
  tax_code: string;
  pl_account_code: string;
  pl_account_name: string;
  account_type: 'revenue' | 'cost' | 'tax_payable';
  is_active: boolean;
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number): string => (fen / 100).toFixed(2);

const getTenantId = (): string =>
  localStorage.getItem('tx_tenant_id') ?? '';

const apiRequest = async <T,>(
  path: string,
  options: RequestInit = {},
): Promise<T> => {
  const resp = await fetch(`/api/v1/finance/vat${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
      ...options.headers,
    },
  });
  const json = await resp.json();
  if (!json.ok) {
    throw new Error(json.error?.message ?? '请求失败');
  }
  return json.data as T;
};

const statusTagMap: Record<string, { color: string; label: string }> = {
  normal: { color: 'green', label: '正常' },
  voided: { color: 'default', label: '已作废' },
  red_correction: { color: 'red', label: '红冲' },
};

const deductionTagMap: Record<string, { color: string; label: string }> = {
  pending: { color: 'orange', label: '待抵扣' },
  deducted: { color: 'green', label: '已抵扣' },
  rejected: { color: 'red', label: '已拒绝' },
};

const accountTypeLabel: Record<string, string> = {
  revenue: '收入',
  cost: '成本',
  tax_payable: '应交税金',
};

// ── Tab 1: 销项台账 ────────────────────────────────────────────────────────────

const OutputLedgerTab: React.FC = () => {
  const [periodMonth, setPeriodMonth] = useState<string>(
    dayjs().format('YYYY-MM'),
  );
  const [summary, setSummary] = useState<VatMonthlySummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const actionRef = useRef<ActionType>();

  const loadSummary = useCallback(async (month: string) => {
    setSummaryLoading(true);
    try {
      const data = await apiRequest<VatMonthlySummary>(`/summary/${month}`);
      setSummary(data);
    } catch (err: unknown) {
      message.error((err as Error).message ?? '加载月度汇总失败');
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  const handleMonthChange = (value: Dayjs | null) => {
    if (!value) return;
    const month = value.format('YYYY-MM');
    setPeriodMonth(month);
    loadSummary(month);
    actionRef.current?.reload();
  };

  // 初始加载
  React.useEffect(() => {
    loadSummary(periodMonth);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const columns: ProColumns<VatOutputRecord>[] = [
    {
      title: '发票日期',
      dataIndex: 'invoice_date',
      valueType: 'date',
      width: 110,
      search: false,
    },
    {
      title: '税收分类编码',
      dataIndex: 'tax_code',
      width: 130,
      copyable: true,
    },
    {
      title: '税率',
      dataIndex: 'tax_rate',
      width: 80,
      search: false,
      render: (_, r) => `${(Number(r.tax_rate) * 100).toFixed(0)}%`,
    },
    {
      title: '不含税金额',
      dataIndex: 'amount_excl_tax_fen',
      valueType: 'money',
      search: false,
      render: (_, r) => `¥${fenToYuan(r.amount_excl_tax_fen)}`,
    },
    {
      title: '税额',
      dataIndex: 'tax_amount_fen',
      search: false,
      render: (_, r) => `¥${fenToYuan(r.tax_amount_fen)}`,
    },
    {
      title: '含税金额',
      dataIndex: 'amount_incl_tax_fen',
      search: false,
      render: (_, r) => `¥${fenToYuan(r.amount_incl_tax_fen)}`,
    },
    {
      title: '买方名称',
      dataIndex: 'buyer_name',
      ellipsis: true,
    },
    {
      title: '买方税号',
      dataIndex: 'buyer_tax_id',
      width: 160,
      copyable: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      valueType: 'select',
      valueEnum: {
        normal: { text: '正常', status: 'Success' },
        voided: { text: '已作废', status: 'Default' },
        red_correction: { text: '红冲', status: 'Error' },
      },
      render: (_, r) => {
        const cfg = statusTagMap[r.status] ?? { color: 'default', label: r.status };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '诺诺流水号',
      dataIndex: 'nuonuo_order_id',
      width: 160,
      search: false,
      copyable: true,
      render: (_, r) =>
        r.nuonuo_order_id ? (
          <Text code style={{ fontSize: 12 }}>
            {r.nuonuo_order_id}
          </Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
  ];

  return (
    <div>
      {/* 月度汇总 Statistic 卡片 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={24}>
          <StatisticCard.Group
            loading={summaryLoading}
            style={{ background: '#F8F7F5', borderRadius: 8, padding: '16px 16px 4px' }}
          >
            <StatisticCard
              statistic={{
                title: '销项税额',
                value: summary ? fenToYuan(summary.output_tax_fen) : '—',
                prefix: '¥',
                suffix: '元',
              }}
            />
            <StatisticCard.Divider />
            <StatisticCard
              statistic={{
                title: '进项税额（已抵扣）',
                value: summary ? fenToYuan(summary.input_tax_fen) : '—',
                prefix: '¥',
                suffix: '元',
              }}
            />
            <StatisticCard.Divider />
            <StatisticCard
              statistic={{
                title: '应缴增值税',
                value: summary ? fenToYuan(summary.net_payable_fen) : '—',
                prefix: '¥',
                suffix: '元',
                valueStyle: {
                  color: summary && summary.net_payable_fen > 0 ? '#A32D2D' : '#0F6E56',
                  fontWeight: 700,
                  fontSize: 24,
                },
              }}
            />
            <StatisticCard.Divider />
            <StatisticCard
              statistic={{
                title: '销项单数',
                value: summary?.output_count ?? '—',
              }}
            />
            <StatisticCard
              statistic={{
                title: '进项单数',
                value: summary?.input_count ?? '—',
              }}
            />
          </StatisticCard.Group>
        </Col>
      </Row>

      <ProTable<VatOutputRecord>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        toolBarRender={() => [
          <DatePicker.MonthPicker
            key="month"
            value={dayjs(periodMonth, 'YYYY-MM')}
            onChange={handleMonthChange}
            format="YYYY-MM"
            allowClear={false}
          />,
        ]}
        request={async (params) => {
          try {
            const qs = new URLSearchParams({
              period_month: periodMonth,
              page: String(params.current ?? 1),
              size: String(params.pageSize ?? 20),
            });
            const data = await apiRequest<{
              items: VatOutputRecord[];
              total: number;
            }>(`/output?${qs}`);
            return { data: data.items, total: data.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        scroll={{ x: 1100 }}
      />
    </div>
  );
};

// ── Tab 2: 进项台账 ────────────────────────────────────────────────────────────

const InputLedgerTab: React.FC = () => {
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [deductLoading, setDeductLoading] = useState(false);
  const actionRef = useRef<ActionType>();

  const handleBatchDeduct = async () => {
    if (selectedKeys.length === 0) {
      message.warning('请先选择要标记抵扣的记录');
      return;
    }
    Modal.confirm({
      title: `确认标记 ${selectedKeys.length} 条记录为已抵扣？`,
      icon: <ExclamationCircleOutlined />,
      content: '操作后记录将进入已抵扣状态，不可撤销。',
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { danger: false },
      onOk: async () => {
        setDeductLoading(true);
        let successCount = 0;
        for (const id of selectedKeys) {
          try {
            await apiRequest(`/input/${id}/deduct`, { method: 'PUT' });
            successCount++;
          } catch {
            // 单条失败不中断批处理
          }
        }
        setDeductLoading(false);
        message.success(`成功标记 ${successCount} 条记录为已抵扣`);
        setSelectedKeys([]);
        actionRef.current?.reload();
      },
    });
  };

  const columns: ProColumns<VatInputRecord>[] = [
    {
      title: '发票日期',
      dataIndex: 'invoice_date',
      valueType: 'date',
      width: 110,
      search: false,
    },
    {
      title: '税收分类编码',
      dataIndex: 'tax_code',
      width: 130,
    },
    {
      title: '税率',
      dataIndex: 'tax_rate',
      width: 80,
      search: false,
      render: (_, r) => `${(Number(r.tax_rate) * 100).toFixed(0)}%`,
    },
    {
      title: '税额',
      dataIndex: 'tax_amount_fen',
      search: false,
      render: (_, r) => `¥${fenToYuan(r.tax_amount_fen)}`,
    },
    {
      title: '含税金额',
      dataIndex: 'amount_incl_tax_fen',
      search: false,
      render: (_, r) => `¥${fenToYuan(r.amount_incl_tax_fen)}`,
    },
    {
      title: '卖方名称',
      dataIndex: 'seller_name',
      ellipsis: true,
    },
    {
      title: '发票代码',
      dataIndex: 'invoice_code',
      width: 130,
      copyable: true,
    },
    {
      title: 'P&L 科目',
      dataIndex: 'pl_account_code',
      width: 100,
      search: false,
      render: (_, r) =>
        r.pl_account_code ? (
          <Tag color="blue">{r.pl_account_code}</Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '抵扣状态',
      dataIndex: 'deduction_status',
      width: 100,
      valueType: 'select',
      valueEnum: {
        pending: { text: '待抵扣', status: 'Warning' },
        deducted: { text: '已抵扣', status: 'Success' },
        rejected: { text: '已拒绝', status: 'Error' },
      },
      render: (_, r) => {
        const cfg = deductionTagMap[r.deduction_status] ?? { color: 'default', label: r.deduction_status };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
  ];

  return (
    <ProTable<VatInputRecord>
      actionRef={actionRef}
      rowKey="id"
      columns={columns}
      rowSelection={{
        selectedRowKeys: selectedKeys,
        onChange: (keys) => setSelectedKeys(keys as string[]),
        getCheckboxProps: (record) => ({
          disabled: record.deduction_status !== 'pending',
        }),
      }}
      toolBarRender={() => [
        <Button
          key="deduct"
          type="primary"
          icon={<CheckCircleOutlined />}
          loading={deductLoading}
          disabled={selectedKeys.length === 0}
          onClick={handleBatchDeduct}
        >
          批量标记抵扣（{selectedKeys.length}）
        </Button>,
      ]}
      request={async (params) => {
        try {
          const qs = new URLSearchParams({
            page: String(params.current ?? 1),
            size: String(params.pageSize ?? 20),
          });
          if (params.deduction_status) {
            qs.set('deduction_status', params.deduction_status);
          }
          const data = await apiRequest<{
            items: VatInputRecord[];
            total: number;
          }>(`/input?${qs}`);
          return { data: data.items, total: data.total, success: true };
        } catch {
          return { data: [], total: 0, success: false };
        }
      }}
      search={{ labelWidth: 'auto' }}
      pagination={{ defaultPageSize: 20 }}
      scroll={{ x: 1100 }}
    />
  );
};

// ── Tab 3: 科目映射 ────────────────────────────────────────────────────────────

const PlAccountsTab: React.FC = () => {
  const [accounts, setAccounts] = useState<PlAccountMapping[]>([]);
  const [loading, setLoading] = useState(false);
  const [editingRow, setEditingRow] = useState<PlAccountMapping | null>(null);
  const [form] = Form.useForm();

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiRequest<{ items: PlAccountMapping[]; total: number }>('/pl-accounts');
      setAccounts(data.items);
    } catch (err: unknown) {
      message.error((err as Error).message ?? '加载科目映射失败');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  const handleEdit = (record: PlAccountMapping) => {
    setEditingRow(record);
    form.setFieldsValue(record);
  };

  const handleSave = async () => {
    if (!editingRow) return;
    try {
      const values = await form.validateFields();
      await apiRequest(`/pl-accounts/${editingRow.tax_code}`, {
        method: 'PUT',
        body: JSON.stringify(values),
      });
      message.success('科目映射已更新');
      setEditingRow(null);
      loadAccounts();
    } catch (err: unknown) {
      message.error((err as Error).message ?? '更新失败');
    }
  };

  return (
    <div>
      <Row justify="end" style={{ marginBottom: 12 }}>
        <Button icon={<SyncOutlined />} onClick={loadAccounts} loading={loading}>
          刷新
        </Button>
      </Row>

      <ProTable<PlAccountMapping>
        loading={loading}
        dataSource={accounts}
        rowKey="id"
        search={false}
        pagination={false}
        toolBarRender={false}
        columns={[
          {
            title: '税收分类编码',
            dataIndex: 'tax_code',
            width: 150,
            copyable: true,
          },
          {
            title: 'P&L 科目代码',
            dataIndex: 'pl_account_code',
            width: 130,
          },
          {
            title: 'P&L 科目名称',
            dataIndex: 'pl_account_name',
            ellipsis: true,
          },
          {
            title: '科目类型',
            dataIndex: 'account_type',
            width: 110,
            render: (_, r) => (
              <Tag
                color={
                  r.account_type === 'revenue'
                    ? 'green'
                    : r.account_type === 'cost'
                    ? 'orange'
                    : 'blue'
                }
              >
                {accountTypeLabel[r.account_type] ?? r.account_type}
              </Tag>
            ),
          },
          {
            title: '启用',
            dataIndex: 'is_active',
            width: 80,
            render: (_, r) => (
              <Switch checked={r.is_active} size="small" disabled />
            ),
          },
          {
            title: '操作',
            valueType: 'option',
            width: 80,
            render: (_, r) => [
              <a key="edit" onClick={() => handleEdit(r)}>
                编辑
              </a>,
            ],
          },
        ]}
      />

      {/* 编辑弹窗 */}
      <Modal
        title={`编辑科目映射 — ${editingRow?.tax_code ?? ''}`}
        open={!!editingRow}
        onOk={handleSave}
        onCancel={() => setEditingRow(null)}
        okText="保存"
        cancelText="取消"
        width={480}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="pl_account_code"
            label="P&L 科目代码"
            rules={[{ required: true, message: '请输入科目代码' }]}
          >
            <Input placeholder="如 6001" maxLength={20} />
          </Form.Item>
          <Form.Item
            name="pl_account_name"
            label="P&L 科目名称"
            rules={[{ required: true, message: '请输入科目名称' }]}
          >
            <Input placeholder="如 主营业务收入" maxLength={100} />
          </Form.Item>
          <Form.Item
            name="account_type"
            label="科目类型"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: 'revenue', label: '收入' },
                { value: 'cost', label: '成本' },
                { value: 'tax_payable', label: '应交税金' },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

// ── 主页面 ─────────────────────────────────────────────────────────────────────

const TaxManagePage: React.FC = () => {
  const [activeTab, setActiveTab] = useState('output');

  const tabs = [
    { key: 'output', label: '销项台账', children: <OutputLedgerTab /> },
    { key: 'input', label: '进项台账', children: <InputLedgerTab /> },
    { key: 'pl_accounts', label: '科目映射', children: <PlAccountsTab /> },
  ];

  return (
    <div style={{ padding: '24px', minWidth: 1280, background: '#F8F7F5', minHeight: '100vh' }}>
      <Row align="middle" style={{ marginBottom: 20 }}>
        <Col flex="auto">
          <Title level={3} style={{ margin: 0, color: '#1E2A3A' }}>
            税务管理
          </Title>
          <Text type="secondary">增值税销项/进项台账 · P&amp;L 科目映射</Text>
        </Col>
      </Row>

      {/* Tabs */}
      <div style={{ background: '#fff', borderRadius: 8, padding: '0 24px' }}>
        <div
          style={{
            display: 'flex',
            borderBottom: '1px solid #E8E6E1',
            marginBottom: 0,
          }}
        >
          {tabs.map((tab) => (
            <div
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: '14px 20px',
                cursor: 'pointer',
                color: activeTab === tab.key ? '#FF6B35' : '#5F5E5A',
                borderBottom: activeTab === tab.key ? '2px solid #FF6B35' : '2px solid transparent',
                fontWeight: activeTab === tab.key ? 600 : 400,
                fontSize: 14,
                userSelect: 'none',
              }}
            >
              {tab.label}
            </div>
          ))}
        </div>

        <div style={{ padding: '20px 0' }}>
          {tabs.find((t) => t.key === activeTab)?.children}
        </div>
      </div>
    </div>
  );
};

export default TaxManagePage;
