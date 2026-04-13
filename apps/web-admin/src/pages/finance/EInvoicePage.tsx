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

const { RangePicker } = DatePicker;
const { Title, Text } = Typography;

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

const STATUS_CONFIG: Record<
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

const TYPE_CONFIG: Record<EInvoice['invoice_type'], string> = {
  normal:     '增值税普票',
  red_note:   '红冲票',
  correction: '更正票',
};

function StatusTag({ status }: { status: EInvoice['status'] }) {
  const cfg = STATUS_CONFIG[status] ?? { label: status, color: 'default' };
  return (
    <Tag color={cfg.color} icon={cfg.icon}>
      {cfg.label}
    </Tag>
  );
}

// ── Tab 1：发票列表 ───────────────────────────────────────────────────────

function InvoiceListTab() {
  const actionRef = useRef<ActionType>();
  const [redNoteTarget, setRedNoteTarget] = useState<EInvoice | null>(null);

  const handleReissue = async (invoice: EInvoice) => {
    try {
      await apiFetch(`/${invoice.id}/reissue`, { method: 'POST' });
      message.success('已重新触发开票');
      actionRef.current?.reload();
    } catch (err) {
      message.error(`重开失败：${(err as Error).message}`);
    }
  };

  const handleRedNote = async (invoice: EInvoice, reason: string) => {
    try {
      await apiFetch(`/${invoice.id}/red-note`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      message.success('红冲申请已提交');
      setRedNoteTarget(null);
      actionRef.current?.reload();
    } catch (err) {
      message.error(`红冲失败：${(err as Error).message}`);
    }
  };

  const columns: ProColumns<EInvoice>[] = [
    {
      title: '发票号',
      dataIndex: 'invoice_no',
      width: 140,
      render: (_, r) => r.invoice_no ?? <Text type="secondary">—</Text>,
    },
    {
      title: '类型',
      dataIndex: 'invoice_type',
      width: 110,
      valueType: 'select',
      valueEnum: {
        normal:     { text: '增值税普票' },
        red_note:   { text: '红冲票' },
        correction: { text: '更正票' },
      },
      render: (_, r) => (
        <Tag color={r.invoice_type === 'red_note' ? 'volcano' : 'geekblue'}>
          {TYPE_CONFIG[r.invoice_type]}
        </Tag>
      ),
    },
    {
      title: '购方名称',
      dataIndex: 'buyer_name',
      ellipsis: true,
      render: (_, r) => r.buyer_name ?? <Text type="secondary">个人</Text>,
    },
    {
      title: '价税合计(元)',
      dataIndex: 'total_amount_fen',
      width: 120,
      search: false,
      render: (_, r) => (
        <Text strong>¥{fenToYuan(r.total_amount_fen)}</Text>
      ),
    },
    {
      title: '税额(元)',
      dataIndex: 'tax_amount_fen',
      width: 100,
      search: false,
      render: (_, r) => `¥${fenToYuan(r.tax_amount_fen)}`,
    },
    {
      title: '税率',
      dataIndex: 'tax_rate',
      width: 80,
      search: false,
      render: (_, r) => `${(Number(r.tax_rate) * 100).toFixed(0)}%`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_CONFIG).map(([k, v]) => [k, { text: v.label }])
      ),
      render: (_, r) => <StatusTag status={r.status} />,
    },
    {
      title: '开票时间',
      dataIndex: 'issue_time',
      valueType: 'dateTime',
      width: 160,
      search: false,
      render: (_, r) =>
        r.issue_time ? (
          new Date(r.issue_time).toLocaleString('zh-CN')
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '操作',
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
            下载PDF
          </a>
        ),
        record.status === 'issued' && (
          <a
            key="red-note"
            style={{ color: '#faad14' }}
            onClick={() => setRedNoteTarget(record)}
          >
            申请红冲
          </a>
        ),
        record.status === 'failed' && (
          <Popconfirm
            key="reissue"
            title="确认重新开票？"
            onConfirm={() => handleReissue(record)}
          >
            <a style={{ color: '#1677ff' }}>重开</a>
          </Popconfirm>
        ),
      ].filter(Boolean),
    },
  ];

  return (
    <>
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
                message.success('状态同步已触发（后台执行）');
                setTimeout(() => actionRef.current?.reload(), 2000);
              } catch (err) {
                message.error(`同步失败：${(err as Error).message}`);
              }
            }}
          >
            同步状态
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* 红冲确认弹窗 */}
      {redNoteTarget && (
        <ModalForm
          title={`申请红冲 — ${redNoteTarget.invoice_no ?? '待开发票'}`}
          open
          onOpenChange={(open) => { if (!open) setRedNoteTarget(null); }}
          onFinish={async (values) => {
            await handleRedNote(redNoteTarget, values.reason);
            return true;
          }}
        >
          <Alert
            type="warning"
            message="红冲操作不可撤销，将创建一张负数冲销发票"
            style={{ marginBottom: 16 }}
          />
          <ProFormText
            name="reason"
            label="红冲原因"
            rules={[{ required: true, message: '请填写红冲原因' }]}
            fieldProps={{ placeholder: '如：顾客要求作废、金额有误等' }}
          />
        </ModalForm>
      )}
    </>
  );
}

// ── Tab 2：开票申请 ───────────────────────────────────────────────────────

function InvoiceRequestTab() {
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
      message.success('开票申请已提交，预计 5 分钟内完成');
    } catch (err) {
      message.error(`开票申请失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 560, paddingTop: 8 }}>
      <Alert
        type="info"
        message="开票申请提交后，系统将异步调用诺诺开票平台完成发票开具，完成后可在「发票列表」中查看进度。"
        style={{ marginBottom: 24 }}
      />
      <ModalForm
        title="申请开票"
        layout="vertical"
        submitter={false}
      >
        <ProFormText
          name="order_id"
          label="订单号（UUID）"
          rules={[
            { required: true, message: '请填写订单 ID' },
            {
              pattern: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
              message: '请输入有效的 UUID 格式订单号',
            },
          ]}
          fieldProps={{ placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' }}
        />
        <ProFormText
          name="buyer_name"
          label="购方名称（企业/个人）"
          fieldProps={{ placeholder: '如：北京示例科技有限公司，个人开票可留空' }}
        />
        <ProFormText
          name="buyer_tax_no"
          label="购方税号"
          fieldProps={{ placeholder: '企业税号（15/17/18/20位）' }}
        />
        <ProFormText
          name="buyer_email"
          label="发票接收邮箱"
          rules={[{ type: 'email', message: '请输入有效的邮箱地址' }]}
          fieldProps={{ placeholder: 'invoice@example.com' }}
        />
        <ProFormSelect
          name="tax_rate"
          label="税率"
          rules={[{ required: true, message: '请选择税率' }]}
          options={[
            { label: '6%（餐饮服务）', value: 0.06 },
            { label: '9%（部分货物）', value: 0.09 },
            { label: '13%（一般货物）', value: 0.13 },
            { label: '0%（免税）', value: 0.0 },
          ]}
          initialValue={0.06}
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
            tax_rate: 0.06,
          });
        }}
        style={{ marginTop: 8 }}
      >
        提交开票申请
      </Button>

      {result && (
        <Alert
          type="success"
          style={{ marginTop: 24 }}
          message="开票申请已提交"
          description={
            <Space direction="vertical" size={4}>
              <Text>发票 ID：<Text code>{result.invoice_id}</Text></Text>
              <Text>当前状态：<StatusTag status={result.status as EInvoice['status']} /></Text>
              <Text type="secondary">预计 5 分钟内完成，请在「发票列表」中查看进度。</Text>
            </Space>
          }
        />
      )}
    </div>
  );
}

// ── Tab 3：税务台账 ───────────────────────────────────────────────────────

function TaxLedgerTab() {
  const [ledger, setLedger] = useState<TaxLedger | null>(null);
  const [loading, setLoading] = useState(false);
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);

  const fetchLedger = async (from: string, to: string) => {
    setLoading(true);
    try {
      const res = await apiFetch<TaxLedger>(
        `/tax-ledger?date_from=${from}&date_to=${to}`
      );
      setLedger(res.data);
    } catch (err) {
      message.error(`台账加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const detailColumns = [
    { title: '税率', dataIndex: 'tax_rate', render: (v: number) => `${(v * 100).toFixed(0)}%` },
    { title: '开票笔数', dataIndex: 'count' },
    { title: '开票金额(元)', dataIndex: 'amount_fen', render: (v: number) => `¥${fenToYuan(v)}` },
    { title: '税额(元)', dataIndex: 'tax_fen', render: (v: number) => `¥${fenToYuan(v)}` },
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
          查询台账
        </Button>
      </Space>

      {ledger && (
        <>
          <Row gutter={16} style={{ marginBottom: 24 }}>
            <Col span={8}>
              <StatisticCard
                statistic={{
                  title: '开票总额',
                  value: fenToYuan(ledger.total_invoice_amount_fen),
                  prefix: '¥',
                  valueStyle: { color: '#0F6E56' },
                }}
              />
            </Col>
            <Col span={8}>
              <StatisticCard
                statistic={{
                  title: '销项税额',
                  value: fenToYuan(ledger.sales_tax_amount_fen),
                  prefix: '¥',
                  valueStyle: { color: '#BA7517' },
                }}
              />
            </Col>
            <Col span={8}>
              <StatisticCard
                statistic={{
                  title: '未开票订单数',
                  value: ledger.uninvoiced_order_count,
                  suffix: '笔',
                  valueStyle: {
                    color: ledger.uninvoiced_order_count > 0 ? '#A32D2D' : '#0F6E56',
                  },
                }}
              />
            </Col>
          </Row>

          <Divider orientation="left">按税率分组明细</Divider>
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

const TAB_ITEMS = [
  {
    key: 'list',
    label: (
      <span>
        <FileTextOutlined />
        发票列表
      </span>
    ),
    children: <InvoiceListTab />,
  },
  {
    key: 'request',
    label: (
      <span>
        <PlusOutlined />
        开票申请
      </span>
    ),
    children: <InvoiceRequestTab />,
  },
  {
    key: 'ledger',
    label: (
      <span>
        <RollbackOutlined />
        税务台账
      </span>
    ),
    children: <TaxLedgerTab />,
  },
];

export default function EInvoicePage() {
  return (
    <div style={{ padding: '0 4px' }}>
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          电子发票管理
        </Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          电子发票全链路 — 开票申请 / 红冲 / 重开 / 状态同步 / 税务台账
        </Text>
      </div>
      <Tabs defaultActiveKey="list" items={TAB_ITEMS} />
    </div>
  );
}
