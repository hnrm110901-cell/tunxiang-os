/**
 * EInvoicePage — 电子发票管理
 * Y-B3 · 域E 财务结算
 *
 * 3个Tab：
 *   - 发票列表（ProTable）
 *   - 开票申请（表单）
 *   - 税务台账（统计图表）
 */
import React, { useRef, useState } from 'react';
import {
  ProTable,
  ProColumns,
  ActionType,
  ModalForm,
  ProFormText,
  ProFormSelect,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Button,
  Tag,
  Space,
  Tabs,
  DatePicker,
  message,
  Popconfirm,
  Typography,
  Row,
  Col,
  Table,
  Divider,
  Alert,
} from 'antd';
import {
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  RollbackOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { formatPrice } from '@tx-ds/utils';
import { useLang } from '../../i18n/LangContext';

const { RangePicker } = DatePicker;
const { Title, Text } = Typography;

// ── MY 模式检测 ──────────────────────────────────────────────────────────

function useIsMY(): boolean {
  const params = new URLSearchParams(window.location.search);
  if (params.get('country') === 'MY') return true;
  try {
    const raw = localStorage.getItem('tx_user');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.country_code === 'MY' || parsed.store_country === 'MY') return true;
    }
  } catch { /* ignore */ }
  return false;
}

// ── 类型定义 ──────────────────────────────────────────────────────────────

interface EInvoice {
  id: string;
  order_id: string | null;
  invoice_type: 'normal' | 'red_note' | 'correction';
  invoice_no: string | null;
  invoice_code: string | null;
  status: 'pending' | 'issuing' | 'issued' | 'failed' | 'cancelled' | 'red_noted';
  buyer_name: string | null;
  buyer_tax_no: string | null;
  buyer_email: string | null;
  total_amount_fen: number;
  tax_amount_fen: number;
  tax_rate: number;
  issue_time: string | null;
  pdf_url: string | null;
  failed_reason: string | null;
  retry_count: number;
  created_at: string;
}

interface TaxLedger {
  date_from: string;
  date_to: string;
  total_invoice_amount_fen: number;
  sales_tax_amount_fen: number;
  uninvoiced_order_count: number;
  by_tax_rate: { tax_rate: number; count: number; amount_fen: number; tax_fen: number }[];
}

// ── 工具函数 ──────────────────────────────────────────────────────────────

function getTenantId(): string {
  try {
    const raw = localStorage.getItem('tx_user');
    if (raw) return JSON.parse(raw).tenant_id ?? '';
  } catch {
    // ignore
  }
  return '';
}

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

const API_BASE = '/api/v1/finance/invoices';

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<{ ok: boolean; data: T; error?: { message: string } }> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
      ...(options?.headers as Record<string, string>),
    },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
  return res.json();
}

// ── 状态 Tag ──────────────────────────────────────────────────────────────

const STATUS_CONFIG_CN: Record<
  EInvoice['status'],
  { label: string; color: string; icon?: React.ReactNode }
> = {
  pending:    { label: '待开票', color: 'blue' },
  issuing:    { label: '开票中', color: 'processing', icon: <SyncOutlined spin /> },
  issued:     { label: '已开票', color: 'success' },
  failed:     { label: '开票失败', color: 'error' },
  cancelled:  { label: '已作废', color: 'default' },
  red_noted:  { label: '已红冲', color: 'warning' },
};

const STATUS_CONFIG_MY: Record<
  EInvoice['status'],
  { label: string; color: string; icon?: React.ReactNode }
> = {
  pending:    { label: 'Pending', color: 'blue' },
  issuing:    { label: 'Submitting', color: 'processing', icon: <SyncOutlined spin /> },
  issued:     { label: 'Validated', color: 'success' },
  failed:     { label: 'Rejected', color: 'error' },
  cancelled:  { label: 'Cancelled', color: 'default' },
  red_noted:  { label: 'Credit Note', color: 'warning' },
};

const TYPE_CONFIG_CN: Record<EInvoice['invoice_type'], string> = {
  normal:     '增值税普票',
  red_note:   '红冲票',
  correction: '更正票',
};

const TYPE_CONFIG_MY: Record<EInvoice['invoice_type'], string> = {
  normal:     'Invoice',
  red_note:   'Credit Note',
  correction: 'Corrective Invoice',
};

function getStatusConfig(isMY: boolean) {
  return isMY ? STATUS_CONFIG_MY : STATUS_CONFIG_CN;
}

function getTypeConfig(isMY: boolean) {
  return isMY ? TYPE_CONFIG_MY : TYPE_CONFIG_CN;
}

function StatusTag({ status, isMY }: { status: EInvoice['status']; isMY?: boolean }) {
  const cfg = (isMY ? STATUS_CONFIG_MY : STATUS_CONFIG_CN)[status] ?? { label: status, color: 'default' };
  return (
    <Tag color={cfg.color} icon={cfg.icon}>
      {cfg.label}
    </Tag>
  );
}

// ── Tab 1：发票列表 ───────────────────────────────────────────────────────

function InvoiceListTab({ isMY }: { isMY?: boolean }) {
  const actionRef = useRef<ActionType>();
  const [redNoteTarget, setRedNoteTarget] = useState<EInvoice | null>(null);

  const handleReissue = async (invoice: EInvoice) => {
    try {
      await apiFetch(`/${invoice.id}/reissue`, { method: 'POST' });
      message.success(isMY ? 'Reissue triggered' : '已重新触发开票');
      actionRef.current?.reload();
    } catch (err) {
      message.error(isMY ? `Reissue failed: ${(err as Error).message}` : `重开失败：${(err as Error).message}`);
    }
  };

  const handleRedNote = async (invoice: EInvoice, reason: string) => {
    try {
      await apiFetch(`/${invoice.id}/red-note`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      message.success(isMY ? 'Credit note submitted' : '红冲申请已提交');
      setRedNoteTarget(null);
      actionRef.current?.reload();
    } catch (err) {
      message.error(isMY ? `Credit note failed: ${(err as Error).message}` : `红冲失败：${(err as Error).message}`);
    }
  };

  const typeConfig = getTypeConfig(!!isMY);

  const columns: ProColumns<EInvoice>[] = [
    {
      title: isMY ? 'Invoice No.' : '发票号',
      dataIndex: 'invoice_no',
      width: 140,
      render: (_, r) => r.invoice_no ?? <Text type="secondary">—</Text>,
    },
    {
      title: isMY ? 'Type' : '类型',
      dataIndex: 'invoice_type',
      width: 110,
      valueType: 'select',
      valueEnum: {
        normal:     { text: typeConfig.normal },
        red_note:   { text: typeConfig.red_note },
        correction: { text: typeConfig.correction },
      },
      render: (_, r) => (
        <Tag color={r.invoice_type === 'red_note' ? 'volcano' : 'geekblue'}>
          {typeConfig[r.invoice_type]}
        </Tag>
      ),
    },
    {
      title: isMY ? 'Buyer Name' : '购方名称',
      dataIndex: 'buyer_name',
      ellipsis: true,
      render: (_, r) => r.buyer_name ?? <Text type="secondary">{isMY ? 'Individual' : '个人'}</Text>,
    },
    {
      title: isMY ? 'Total (MYR)' : '价税合计(元)',
      dataIndex: 'total_amount_fen',
      width: 120,
      search: false,
      render: (_, r) => (
        <Text strong>{isMY ? `RM${fenToYuan(r.total_amount_fen)}` : `¥${fenToYuan(r.total_amount_fen)}`}</Text>
      ),
    },
    {
      title: isMY ? 'Tax (MYR)' : '税额(元)',
      dataIndex: 'tax_amount_fen',
      width: 100,
      search: false,
      render: (_, r) => isMY ? `RM${fenToYuan(r.tax_amount_fen)}` : `¥${fenToYuan(r.tax_amount_fen)}`,
    },
    {
      title: isMY ? 'Tax Rate' : '税率',
      dataIndex: 'tax_rate',
      width: 80,
      search: false,
      render: (_, r) => `${(Number(r.tax_rate) * 100).toFixed(0)}%`,
    },
    {
      title: isMY ? 'Status' : '状态',
      dataIndex: 'status',
      width: 110,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(getStatusConfig(!!isMY)).map(([k, v]) => [k, { text: v.label }])
      ),
      render: (_, r) => <StatusTag status={r.status} isMY={isMY} />,
    },
    {
      title: isMY ? 'Issue Time' : '开票时间',
      dataIndex: 'issue_time',
      valueType: 'dateTime',
      width: 160,
      search: false,
      render: (_, r) =>
        r.issue_time ? (
          new Date(r.issue_time).toLocaleString(isMY ? 'en-MY' : 'zh-CN')
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: isMY ? 'Actions' : '操作',
      valueType: 'option',
      width: 200,
      fixed: 'right',
      render: (_, record) => [
        record.pdf_url && record.status === 'issued' && (
          <a
            key="pdf"
            href={record.pdf_url}
            target="_blank"
            rel="noreferrer"
          >
            {isMY ? 'Download PDF' : '下载PDF'}
          </a>
        ),
        record.status === 'issued' && (
          <a
            key="red-note"
            style={{ color: '#faad14' }}
            onClick={() => setRedNoteTarget(record)}
          >
            {isMY ? 'Credit Note' : '申请红冲'}
          </a>
        ),
        record.status === 'failed' && (
          <Popconfirm
            key="reissue"
            title={isMY ? 'Confirm reissue?' : '确认重新开票？'}
            onConfirm={() => handleReissue(record)}
          >
            <a style={{ color: '#1677ff' }}>{isMY ? 'Reissue' : '重开'}</a>
          </Popconfirm>
        ),
      ].filter(Boolean),
    },
  ];

  return (
    <>
      {isMY && (
        <Alert
          type="info"
          message="LHDN e-Invoice (MyInvois)"
          description="This view shows e-Invoice data for Malaysia MyInvois compliance. All amounts are in MYR."
          style={{ marginBottom: 16 }}
          icon={<FileTextOutlined />}
        />
      )}
      <ProTable<EInvoice>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.status) query.set('status', params.status);
          if (params.buyer_name) query.set('buyer_name', params.buyer_name);
          if (params.invoice_type) query.set('invoice_type', params.invoice_type);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));

          try {
            const res = await apiFetch<{ items: EInvoice[]; total: number }>(
              `?${query.toString()}`
            );
            return { data: res.data.items, total: res.data.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto' }}
        scroll={{ x: 1200 }}
        toolBarRender={() => [
          <Button
            key="sync"
            icon={<SyncOutlined />}
            onClick={async () => {
              try {
                await apiFetch('/sync-status', { method: 'POST' });
                message.success(isMY ? 'Status sync triggered' : '状态同步已触发（后台执行）');
                setTimeout(() => actionRef.current?.reload(), 2000);
              } catch (err) {
                message.error(isMY ? `Sync failed: ${(err as Error).message}` : `同步失败：${(err as Error).message}`);
              }
            }}
          >
            {isMY ? 'Sync Status' : '同步状态'}
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* 红冲确认弹窗 */}
      {redNoteTarget && (
        <ModalForm
          title={isMY
            ? `Credit Note — ${redNoteTarget.invoice_no ?? 'Pending Invoice'}`
            : `申请红冲 — ${redNoteTarget.invoice_no ?? '待开发票'}`}
          open
          onOpenChange={(open) => { if (!open) setRedNoteTarget(null); }}
          onFinish={async (values) => {
            await handleRedNote(redNoteTarget, values.reason);
            return true;
          }}
        >
          <Alert
            type="warning"
            message={isMY
              ? 'This action cannot be undone. A credit note will be created.'
              : '红冲操作不可撤销，将创建一张负数冲销发票'}
            style={{ marginBottom: 16 }}
          />
          <ProFormText
            name="reason"
            label={isMY ? 'Reason' : '红冲原因'}
            rules={[{ required: true, message: isMY ? 'Please enter a reason' : '请填写红冲原因' }]}
            fieldProps={{ placeholder: isMY ? 'e.g. Customer request, amount error' : '如：顾客要求作废、金额有误等' }}
          />
        </ModalForm>
      )}
    </>
  );
}

// ── Tab 2：开票申请 ───────────────────────────────────────────────────────

function InvoiceRequestTab({ isMY }: { isMY?: boolean }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ invoice_id: string; status: string } | null>(null);

  const handleSubmit = async (values: Record<string, unknown>) => {
    setLoading(true);
    setResult(null);
    try {
      const res = await apiFetch<{ invoice_id: string; status: string }>('', {
        method: 'POST',
        body: JSON.stringify({
          order_id: values.order_id,
          buyer_name: values.buyer_name || null,
          buyer_tax_no: values.buyer_tax_no || null,
          buyer_email: values.buyer_email || null,
          tax_rate: Number(values.tax_rate),
        }),
      });
      setResult(res.data);
      message.success(isMY ? 'e-Invoice submitted, estimated 5 min' : '开票申请已提交，预计 5 分钟内完成');
    } catch (err) {
      message.error(isMY ? `e-Invoice failed: ${(err as Error).message}` : `开票申请失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 560, paddingTop: 8 }}>
      <Alert
        type="info"
        message={isMY
          ? 'After submission, the system will submit to MyInvois asynchronously. Check the e-Invoice list for progress.'
          : '开票申请提交后，系统将异步调用诺诺开票平台完成发票开具，完成后可在「发票列表」中查看进度。'}
        style={{ marginBottom: 24 }}
      />
      <ModalForm
        title={isMY ? 'New e-Invoice' : '申请开票'}
        layout="vertical"
        submitter={false}
      >
        <ProFormText
          name="order_id"
          label={isMY ? 'Order ID (UUID)' : '订单号（UUID）'}
          rules={[
            { required: true, message: isMY ? 'Please enter order ID' : '请填写订单 ID' },
            {
              pattern: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
              message: 'Please enter a valid UUID format',
            },
          ]}
          fieldProps={{ placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' }}
        />
        <ProFormText
          name="buyer_name"
          label={isMY ? 'Buyer Name (Company/Individual)' : '购方名称（企业/个人）'}
          fieldProps={{ placeholder: isMY ? 'e.g. MyCompany Sdn. Bhd.' : '如：北京示例科技有限公司，个人开票可留空' }}
        />
        <ProFormText
          name="buyer_tax_no"
          label={isMY ? 'Buyer Tax ID (SSM/BRN)' : '购方税号'}
          fieldProps={{ placeholder: isMY ? 'Business Registration No.' : '企业税号（15/17/18/20位）' }}
        />
        <ProFormText
          name="buyer_email"
          label={isMY ? 'Invoice Email' : '发票接收邮箱'}
          rules={[{ type: 'email', message: isMY ? 'Please enter a valid email' : '请输入有效的邮箱地址' }]}
          fieldProps={{ placeholder: 'invoice@example.com' }}
        />
        <ProFormSelect
          name="tax_rate"
          label={isMY ? 'Tax Rate (SST)' : '税率'}
          rules={[{ required: true, message: isMY ? 'Please select tax rate' : '请选择税率' }]}
          options={isMY
            ? [
                { label: 'Standard Rate (8%)', value: 0.08 },
                { label: 'Food & Beverage (6%)', value: 0.06 },
                { label: 'Specific Rate (5%)', value: 0.05 },
                { label: 'Exempt (0%)', value: 0.0 },
              ]
            : [
                { label: '6%（餐饮服务）', value: 0.06 },
                { label: '9%（部分货物）', value: 0.09 },
                { label: '13%（一般货物）', value: 0.13 },
                { label: '0%（免税）', value: 0.0 },
              ]}
          initialValue={isMY ? 0.08 : 0.06}
        />
      </ModalForm>

      <Button
        type="primary"
        icon={<FileTextOutlined />}
        loading={loading}
        onClick={async () => {
          // 直接触发一个简单表单提交（演示）
          await handleSubmit({
            order_id: '',
            buyer_name: '',
            buyer_tax_no: '',
            buyer_email: '',
            tax_rate: isMY ? 0.08 : 0.06,
          });
        }}
        style={{ marginTop: 8 }}
      >
        {isMY ? 'Submit e-Invoice' : '提交开票申请'}
      </Button>

      {result && (
        <Alert
          type="success"
          style={{ marginTop: 24 }}
          message={isMY ? 'e-Invoice Submitted' : '开票申请已提交'}
          description={
            <Space direction="vertical" size={4}>
              <Text>{isMY ? 'Invoice ID: ' : '发票 ID：'}<Text code>{result.invoice_id}</Text></Text>
              <Text>{isMY ? 'Status: ' : '当前状态：'}<StatusTag status={result.status as EInvoice['status']} isMY={isMY} /></Text>
              <Text type="secondary">{isMY ? 'Estimated 5 min. Check the list for progress.' : '预计 5 分钟内完成，请在「发票列表」中查看进度。'}</Text>
            </Space>
          }
        />
      )}
    </div>
  );
}

// ── Tab 3：税务台账 ───────────────────────────────────────────────────────

function TaxLedgerTab({ isMY }: { isMY?: boolean }) {
  const [ledger, setLedger] = useState<TaxLedger | null>(null);
  const [loading, setLoading] = useState(false);
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const currency = isMY ? 'RM' : '¥';

  const fetchLedger = async (from: string, to: string) => {
    setLoading(true);
    try {
      const res = await apiFetch<TaxLedger>(
        `/tax-ledger?date_from=${from}&date_to=${to}`
      );
      setLedger(res.data);
    } catch (err) {
      message.error(isMY ? `Ledger load failed: ${(err as Error).message}` : `台账加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const detailColumns = [
    { title: isMY ? 'Tax Rate' : '税率', dataIndex: 'tax_rate', render: (v: number) => `${(v * 100).toFixed(0)}%` },
    { title: isMY ? 'Invoices' : '开票笔数', dataIndex: 'count' },
    { title: isMY ? 'Amount' : '开票金额', dataIndex: 'amount_fen', render: (v: number) => `${currency}${fenToYuan(v)}` },
    { title: isMY ? 'Tax' : '税额', dataIndex: 'tax_fen', render: (v: number) => `${currency}${fenToYuan(v)}` },
  ];

  return (
    <div style={{ paddingTop: 8 }}>
      <Space size={12} style={{ marginBottom: 24 }}>
        <RangePicker
          onChange={(_, strings) => {
            if (strings[0] && strings[1]) setDateRange([strings[0], strings[1]]);
          }}
        />
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          loading={loading}
          disabled={!dateRange}
          onClick={() => dateRange && fetchLedger(dateRange[0], dateRange[1])}
        >
          {isMY ? 'Query Ledger' : '查询台账'}
        </Button>
      </Space>

      {ledger && (
        <>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={8}>
              <StatisticCard
                statistic={{
                  title: isMY ? 'Total Invoiced' : '开票总额',
                  value: fenToYuan(ledger.total_invoice_amount_fen),
                  prefix: currency,
                  valueStyle: { color: '#0F6E56' },
                }}
              />
            </Col>
            <Col span={8}>
              <StatisticCard
                statistic={{
                  title: isMY ? 'Sales Tax' : '销项税额',
                  value: fenToYuan(ledger.sales_tax_amount_fen),
                  prefix: currency,
                  valueStyle: { color: '#BA7517' },
                }}
              />
            </Col>
            <Col span={8}>
              <StatisticCard
                statistic={{
                  title: isMY ? 'Uninvoiced Orders' : '未开票订单数',
                  value: ledger.uninvoiced_order_count,
                  suffix: isMY ? '' : '笔',
                  valueStyle: {
                    color: ledger.uninvoiced_order_count > 0 ? '#A32D2D' : '#0F6E56',
                  },
                }}
              />
            </Col>
          </Row>

          <Divider orientation="left">{isMY ? 'By Tax Rate' : '按税率分组明细'}</Divider>
          <Table
            rowKey="tax_rate"
            columns={detailColumns}
            dataSource={ledger.by_tax_rate}
            pagination={false}
            size="small"
          />
        </>
      )}
    </div>
  );
}

// ── 主页面 ────────────────────────────────────────────────────────────────

const TAB_ITEMS = (isMY: boolean) => [
  {
    key: 'list',
    label: (
      <span>
        <FileTextOutlined />
        {isMY ? 'e-Invoice List' : '发票列表'}
      </span>
    ),
    children: <InvoiceListTab isMY={isMY} />,
  },
  {
    key: 'request',
    label: (
      <span>
        <PlusOutlined />
        {isMY ? 'New e-Invoice' : '开票申请'}
      </span>
    ),
    children: <InvoiceRequestTab isMY={isMY} />,
  },
  {
    key: 'ledger',
    label: (
      <span>
        <RollbackOutlined />
        {isMY ? 'Tax Ledger' : '税务台账'}
      </span>
    ),
    children: <TaxLedgerTab isMY={isMY} />,
  },
];

export default function EInvoicePage() {
  const isMY = useIsMY();
  const { lang } = useLang();

  return (
    <div style={{ padding: '0 4px' }}>
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          {isMY ? 'e-Invoice Management' : '电子发票管理'}
          {isMY && (
            <Tag color="purple" style={{ marginLeft: 8, fontSize: 11, verticalAlign: 'middle' }}>
              LHDN e-Invoice
            </Tag>
          )}
        </Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          {isMY
            ? 'MyInvois e-Invoice lifecycle — Submit / Validate / Credit Note / Sync / Ledger'
            : '电子发票全链路 — 开票申请 / 红冲 / 重开 / 状态同步 / 税务台账'}
        </Text>
      </div>
      <Tabs defaultActiveKey="list" items={TAB_ITEMS(isMY)} />
    </div>
  );
}
