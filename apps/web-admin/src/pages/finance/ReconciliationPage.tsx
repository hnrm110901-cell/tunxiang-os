/**
 * 财务对账中心 — Reconciliation Center
 * 路由: /finance/reconciliation
 * 四大 Tab: 支付对账 / 外卖平台对账 / 储值卡对账 / 对账报告
 *
 * 金额单位: 分(fen)，显示时 ÷100
 * API: http://localhost:8007  (tx-finance :8007)
 * 降级: API 失败时使用内嵌 Mock 数据
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import dayjs from 'dayjs';
import {
  Button,
  Card,
  Col,
  Collapse,
  ConfigProvider,
  DatePicker,
  Descriptions,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
  Input,
  Table,
} from 'antd';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { ProTable, ModalForm, ProFormTextArea } from '@ant-design/pro-components';
import { txFetchData } from '../../api';
import {
  CheckCircleOutlined,
  DollarOutlined,
  ExclamationCircleOutlined,
  PercentageOutlined,
  SwapOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

/** 分转元，保留两位小数 */
/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number): string => (fen / 100).toFixed(2);

/** 分转元数字 */
const fen2yuanNum = (fen: number): number => fen / 100;

/** 格式化金额显示 */
const formatMoney = (fen: number): string => {
  const yuan = fen / 100;
  return yuan.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

type ReconcileStatus = 'matched' | 'unmatched' | 'pending' | 'manual';

interface PaymentReconcileRow {
  id: string;
  date: string;
  store_name: string;
  channel: '微信' | '支付宝' | '银行卡';
  system_amount_fen: number;
  channel_amount_fen: number;
  diff_fen: number;
  status: ReconcileStatus;
}

/** 支付渠道对账汇总行 */
interface ChannelSummaryRow {
  channel: string;
  channel_name: string;
  transaction_count: number;
  total_amount_fen: number;
  fee_fen: number;
  net_amount_fen: number;
}

/** 收银员收款统计行 */
interface CashierReceiptRow {
  cashier_id: string;
  cashier_name: string;
  shift_count: number;
  total_amount_fen: number;
  order_count: number;
  channel_breakdown: Record<string, number>;
}

interface DeliveryReconcileRow {
  id: string;
  date: string;
  platform: '美团' | '饿了么' | '抖音';
  order_count: number;
  platform_bill_fen: number;
  system_record_fen: number;
  commission_fen: number;
  actual_income_fen: number;
  diff_fen: number;
  details: DeliveryOrderDetail[];
}

interface DeliveryOrderDetail {
  order_id: string;
  platform_amount_fen: number;
  system_amount_fen: number;
  commission_fen: number;
  status: string;
}

interface StoredValueSummary {
  recharge_total_fen: number;
  consume_total_fen: number;
  refund_total_fen: number;
  balance_total_fen: number;
  anomalies: StoredValueAnomaly[];
}

interface StoredValueAnomaly {
  card_id: string;
  member_name: string;
  phone: string;
  expected_balance_fen: number;
  actual_balance_fen: number;
  diff_fen: number;
}

interface ReconcileSummary {
  today_income_fen: number;
  pending_amount_fen: number;
  diff_amount_fen: number;
  completion_rate: number;
}

interface MonthlyReportData {
  month: string;
  income_sources: { name: string; amount_fen: number; color: string }[];
  diff_trend: { date: string; diff_fen: number }[];
}

// ─── 空数据初始值 ──────────────────────────────────────────────────────────────

const EMPTY_SUMMARY: ReconcileSummary = {
  today_income_fen: 0,
  pending_amount_fen: 0,
  diff_amount_fen: 0,
  completion_rate: 0,
};

const EMPTY_STORED_VALUE: StoredValueSummary = {
  recharge_total_fen: 0,
  consume_total_fen: 0,
  refund_total_fen: 0,
  balance_total_fen: 0,
  anomalies: [],
};

// ─── API 请求 ──────────────────────────────────────────────────────────────────

/** 获取对账汇总 */
async function fetchSummary(date?: string, storeId?: string): Promise<ReconcileSummary> {
  try {
    const params = new URLSearchParams();
    if (date) params.set('date', date);
    if (storeId && storeId !== 'all') params.set('store_id', storeId);
    const data = await txFetchData<ReconcileSummary>(
      `/api/v1/analytics/reconciliation?${params.toString()}`,
    );
    return data;
  } catch (_e: unknown) { /* 降级空数据 */ }
  return EMPTY_SUMMARY;
}

/** 确认对账 */
async function confirmReconciliation(payload: {
  date: string;
  store_id: string;
  notes?: string;
}): Promise<void> {
  await txFetchData('/api/v1/analytics/reconciliation/confirm', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function fetchPaymentRows(date?: string, storeId?: string): Promise<PaymentReconcileRow[]> {
  try {
    const params = new URLSearchParams({ type: 'payment' });
    if (date) params.set('date', date);
    if (storeId && storeId !== 'all') params.set('store_id', storeId);
    const data = await txFetchData<{ items: PaymentReconcileRow[] }>(
      `/api/v1/analytics/reconciliation?${params.toString()}`,
    );
    return data.items ?? [];
  } catch (_e: unknown) { /* 降级空数组 */ }
  return [];
}

/** 获取支付渠道汇总对账（真实 API） */
async function fetchChannelSummary(
  startDate: string,
  endDate: string,
  storeId?: string,
): Promise<ChannelSummaryRow[]> {
  try {
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    if (storeId && storeId !== 'all') params.set('store_id', storeId);
    const data = await txFetchData<{ channels: ChannelSummaryRow[] }>(
      `/api/v1/finance/payment-reconciliation?${params.toString()}`,
    );
    return data.channels ?? [];
  } catch (_e: unknown) { /* 降级空数组 */ }
  return [];
}

/** 获取收银员收款统计（真实 API） */
async function fetchCashierReceipts(
  startDate: string,
  endDate: string,
  storeId?: string,
): Promise<CashierReceiptRow[]> {
  try {
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    if (storeId && storeId !== 'all') params.set('store_id', storeId);
    const data = await txFetchData<{ cashiers: CashierReceiptRow[] }>(
      `/api/v1/finance/cashier-receipts?${params.toString()}`,
    );
    return data.cashiers ?? [];
  } catch (_e: unknown) { /* 降级空数组 */ }
  return [];
}

async function fetchDeliveryRows(date?: string, storeId?: string): Promise<DeliveryReconcileRow[]> {
  try {
    const params = new URLSearchParams({ type: 'delivery' });
    if (date) params.set('date', date);
    if (storeId && storeId !== 'all') params.set('store_id', storeId);
    const data = await txFetchData<{ items: DeliveryReconcileRow[] }>(
      `/api/v1/analytics/reconciliation?${params.toString()}`,
    );
    return data.items ?? [];
  } catch (_e: unknown) { /* 降级空数组 */ }
  return [];
}

async function fetchStoredValue(date?: string, storeId?: string): Promise<StoredValueSummary> {
  try {
    const params = new URLSearchParams({ type: 'stored_value' });
    if (date) params.set('date', date);
    if (storeId && storeId !== 'all') params.set('store_id', storeId);
    const data = await txFetchData<StoredValueSummary>(
      `/api/v1/analytics/reconciliation?${params.toString()}`,
    );
    return data;
  } catch (_e: unknown) { /* 降级空数据 */ }
  return EMPTY_STORED_VALUE;
}

async function fetchReportData(month: string, storeId?: string): Promise<MonthlyReportData> {
  try {
    const params = new URLSearchParams({ type: 'report', month });
    if (storeId && storeId !== 'all') params.set('store_id', storeId);
    const data = await txFetchData<MonthlyReportData>(
      `/api/v1/analytics/reconciliation?${params.toString()}`,
    );
    return data;
  } catch (_e: unknown) { /* 降级空数据 */ }
  return { month, income_sources: [], diff_trend: [] };
}

// ─── SVG 图表组件 ──────────────────────────────────────────────────────────────

/** 饼图：收入来源 */
function IncomePieChart({ sources }: { sources: MonthlyReportData['income_sources'] }) {
  const total = sources.reduce((s, v) => s + v.amount_fen, 0);
  if (total === 0) return null;

  const cx = 150;
  const cy = 150;
  const r = 120;
  let cumAngle = -Math.PI / 2;

  const arcs = sources.map((src) => {
    const fraction = src.amount_fen / total;
    const startAngle = cumAngle;
    const endAngle = cumAngle + fraction * 2 * Math.PI;
    cumAngle = endAngle;

    const largeArc = fraction > 0.5 ? 1 : 0;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);

    return (
      <path
        key={src.name}
        d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${largeArc},1 ${x2},${y2} Z`}
        fill={src.color}
        stroke="#fff"
        strokeWidth={2}
      >
        <title>{src.name}: {formatMoney(src.amount_fen)}元 ({(fraction * 100).toFixed(1)}%)</title>
      </path>
    );
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 32 }}>
      <svg width={300} height={300} viewBox="0 0 300 300">
        {arcs}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sources.map((src) => (
          <div key={src.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 12, height: 12, borderRadius: 2, background: src.color }} />
            <Text>{src.name}</Text>
            <Text type="secondary">{formatMoney(src.amount_fen)}元</Text>
            <Text type="secondary">({(src.amount_fen / total * 100).toFixed(1)}%)</Text>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 折线图：对账差异趋势 */
function DiffTrendChart({ data }: { data: MonthlyReportData['diff_trend'] }) {
  if (data.length === 0) return null;

  const W = 600;
  const H = 200;
  const PAD = { top: 20, right: 40, bottom: 40, left: 60 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const values = data.map((d) => d.diff_fen);
  const maxAbs = Math.max(...values.map(Math.abs), 1);
  const yMax = maxAbs * 1.2;
  const yMin = -yMax;

  const xScale = (i: number) => PAD.left + (i / (data.length - 1)) * plotW;
  const yScale = (v: number) => PAD.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  const zeroY = yScale(0);
  const polyline = data.map((d, i) => `${xScale(i)},${yScale(d.diff_fen)}`).join(' ');

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      {/* 零线 */}
      <line x1={PAD.left} y1={zeroY} x2={W - PAD.right} y2={zeroY} stroke="#d9d9d9" strokeDasharray="4,4" />
      {/* Y轴标签 */}
      <text x={PAD.left - 8} y={yScale(yMax * 0.8)} textAnchor="end" fontSize={10} fill="#999">+{fen2yuan(Math.round(yMax * 0.8))}</text>
      <text x={PAD.left - 8} y={zeroY + 4} textAnchor="end" fontSize={10} fill="#999">0</text>
      <text x={PAD.left - 8} y={yScale(yMin * 0.8)} textAnchor="end" fontSize={10} fill="#999">-{fen2yuan(Math.round(yMax * 0.8))}</text>
      {/* 折线 */}
      <polyline points={polyline} fill="none" stroke="#FF6B35" strokeWidth={2} />
      {/* 数据点 + X轴标签 */}
      {data.map((d, i) => (
        <g key={d.date}>
          <circle cx={xScale(i)} cy={yScale(d.diff_fen)} r={4} fill={d.diff_fen >= 0 ? '#52c41a' : '#ff4d4f'} />
          <text x={xScale(i)} y={H - 8} textAnchor="middle" fontSize={10} fill="#666">{d.date}</text>
          <title>{d.date}: {d.diff_fen >= 0 ? '+' : ''}{fen2yuan(d.diff_fen)}元</title>
        </g>
      ))}
    </svg>
  );
}

// ─── 状态 Tag ──────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<ReconcileStatus, { color: string; label: string }> = {
  matched: { color: 'green', label: '已对账' },
  unmatched: { color: 'red', label: '未对账' },
  pending: { color: 'orange', label: '待处理' },
  manual: { color: 'blue', label: '手动对账' },
};

function StatusTag({ status }: { status: ReconcileStatus }) {
  const cfg = STATUS_CONFIG[status];
  return <Tag color={cfg.color}>{cfg.label}</Tag>;
}

// ─── 差异显示 ──────────────────────────────────────────────────────────────────

function DiffDisplay({ diff_fen }: { diff_fen: number }) {
  if (diff_fen > 0) return <Text style={{ color: '#52c41a' }}>+{fen2yuan(diff_fen)}</Text>;
  if (diff_fen < 0) return <Text style={{ color: '#ff4d4f' }}>{fen2yuan(diff_fen)}</Text>;
  return <Text type="secondary">0.00</Text>;
}

// ─── CSV 导出工具 ──────────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function exportCSV(data: any[], filename?: string) {
  if (!data || data.length === 0) {
    message.warning('暂无数据可导出');
    return;
  }
  const csv = [
    Object.keys(data[0]).join(','),
    ...data.map((row) =>
      Object.values(row)
        .map((v) => (typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')))
        .join(','),
    ),
  ].join('\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename ?? `支付对账_${dayjs().format('YYYYMMDD')}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── 收银员收款明细子面板 ──────────────────────────────────────────────────────

function CashierReceiptsPanel({
  startDate,
  endDate,
  storeId,
}: {
  startDate: string;
  endDate: string;
  storeId?: string;
}) {
  const [cashiers, setCashiers] = useState<CashierReceiptRow[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchCashierReceipts(startDate, endDate, storeId);
      setCashiers(data);
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate, storeId]);

  useEffect(() => {
    load();
  }, [load]);

  const cashierColumns = [
    { title: '收银员', dataIndex: 'cashier_name', key: 'cashier_name', width: 100 },
    { title: '工号', dataIndex: 'cashier_id', key: 'cashier_id', width: 120 },
    { title: '班次数', dataIndex: 'shift_count', key: 'shift_count', width: 80 },
    { title: '收款总额(元)', dataIndex: 'total_amount_fen', key: 'total_amount_fen', width: 130,
      render: (_: unknown, r: CashierReceiptRow) => <Text strong>{formatMoney(r.total_amount_fen)}</Text> },
    { title: '订单数', dataIndex: 'order_count', key: 'order_count', width: 80 },
    { title: '微信(元)', key: 'wechat', width: 110,
      render: (_: unknown, r: CashierReceiptRow) => formatMoney(r.channel_breakdown.wechat ?? 0) },
    { title: '支付宝(元)', key: 'alipay', width: 110,
      render: (_: unknown, r: CashierReceiptRow) => formatMoney(r.channel_breakdown.alipay ?? 0) },
    { title: '现金(元)', key: 'cash', width: 100,
      render: (_: unknown, r: CashierReceiptRow) => formatMoney(r.channel_breakdown.cash ?? 0) },
    { title: '银行卡(元)', key: 'card', width: 110,
      render: (_: unknown, r: CashierReceiptRow) => formatMoney(r.channel_breakdown.card ?? 0) },
    { title: '会员卡(元)', key: 'member_card', width: 110,
      render: (_: unknown, r: CashierReceiptRow) => formatMoney(r.channel_breakdown.member_card ?? 0) },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
        <Button
          size="small"
          icon={<DownloadOutlined />}
          onClick={() => exportCSV(cashiers, `收银员统计_${dayjs().format('YYYYMMDD')}.csv`)}
        >
          导出 CSV
        </Button>
      </div>
      <Table<CashierReceiptRow>
        columns={cashierColumns}
        dataSource={cashiers}
        rowKey="cashier_id"
        loading={loading}
        pagination={{ pageSize: 10 }}
        size="small"
        scroll={{ x: 900 }}
      />
    </div>
  );
}

// ─── Tab1: 支付对账 ────────────────────────────────────────────────────────────

function PaymentReconcileTab() {
  const actionRef = useRef<ActionType>();
  const [selectedRows, setSelectedRows] = useState<PaymentReconcileRow[]>([]);
  const [manualModalOpen, setManualModalOpen] = useState(false);
  const [channelSummaries, setChannelSummaries] = useState<ChannelSummaryRow[]>([]);

  // 默认日期范围：本月 1 日 ~ 今天
  const today = dayjs().format('YYYY-MM-DD');
  const monthStart = dayjs().startOf('month').format('YYYY-MM-DD');

  useEffect(() => {
    fetchChannelSummary(monthStart, today).then(setChannelSummaries);
  }, [monthStart, today]);

  const columns: ProColumns<PaymentReconcileRow>[] = [
    { title: '日期', dataIndex: 'date', valueType: 'date', width: 110 },
    { title: '门店', dataIndex: 'store_name', width: 180, onFilter: (value, record) => record.store_name === value },
    {
      title: '支付渠道', dataIndex: 'channel', width: 100,
      filters: [
        { text: '微信', value: '微信' },
        { text: '支付宝', value: '支付宝' },
        { text: '银行卡', value: '银行卡' },
      ],
      onFilter: (value, record) => record.channel === value,
      render: (_, r) => {
        const colorMap: Record<string, string> = { '微信': '#07C160', '支付宝': '#1677FF', '银行卡': '#722ED1' };
        return <Tag color={colorMap[r.channel]}>{r.channel}</Tag>;
      },
    },
    { title: '系统金额(元)', dataIndex: 'system_amount_fen', width: 130, sorter: (a, b) => a.system_amount_fen - b.system_amount_fen, render: (_, r) => formatMoney(r.system_amount_fen) },
    { title: '渠道金额(元)', dataIndex: 'channel_amount_fen', width: 130, render: (_, r) => formatMoney(r.channel_amount_fen) },
    { title: '差异(元)', dataIndex: 'diff_fen', width: 110, sorter: (a, b) => a.diff_fen - b.diff_fen, render: (_, r) => <DiffDisplay diff_fen={r.diff_fen} /> },
    { title: '状态', dataIndex: 'status', width: 100, filters: Object.entries(STATUS_CONFIG).map(([k, v]) => ({ text: v.label, value: k })), onFilter: (value, record) => record.status === value, render: (_, r) => <StatusTag status={r.status} /> },
  ];

  const channelColumns = [
    { title: '渠道', dataIndex: 'channel_name', key: 'channel_name', width: 100 },
    { title: '笔数', dataIndex: 'transaction_count', key: 'transaction_count', width: 80 },
    { title: '总金额(元)', dataIndex: 'total_amount_fen', key: 'total_amount_fen', width: 130,
      render: (_: unknown, r: ChannelSummaryRow) => <Text strong>{formatMoney(r.total_amount_fen)}</Text> },
    { title: '手续费(元)', dataIndex: 'fee_fen', key: 'fee_fen', width: 120,
      render: (_: unknown, r: ChannelSummaryRow) => <Text type="warning">{formatMoney(r.fee_fen)}</Text> },
    { title: '净收(元)', dataIndex: 'net_amount_fen', key: 'net_amount_fen', width: 120,
      render: (_: unknown, r: ChannelSummaryRow) => <Text style={{ color: '#52c41a' }}>{formatMoney(r.net_amount_fen)}</Text> },
  ];

  const handleManualReconcile = async (values: { reason: string }) => {
    message.success(`已手动对账 ${selectedRows.length} 条记录，原因: ${values.reason}`);
    setSelectedRows([]);
    setManualModalOpen(false);
    actionRef.current?.reload();
    return true;
  };

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 渠道汇总统计卡片 */}
      <Card
        title="本月支付渠道汇总"
        size="small"
        extra={
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => exportCSV(channelSummaries, `渠道汇总_${dayjs().format('YYYYMMDD')}.csv`)}
          >
            导出 CSV
          </Button>
        }
      >
        <Table<ChannelSummaryRow>
          columns={channelColumns}
          dataSource={channelSummaries}
          rowKey="channel"
          pagination={false}
          size="small"
        />
      </Card>

      {/* 逐笔明细 ProTable */}
      <ProTable<PaymentReconcileRow>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async () => {
          const data = await fetchPaymentRows();
          return { data, success: true, total: data.length };
        }}
        rowSelection={{
          selectedRowKeys: selectedRows.map((r) => r.id),
          onChange: (_, rows) => setSelectedRows(rows),
        }}
        toolbar={{
          actions: [
            <Button
              key="export"
              icon={<DownloadOutlined />}
              onClick={async () => {
                const data = await fetchPaymentRows();
                exportCSV(data, `支付对账明细_${dayjs().format('YYYYMMDD')}.csv`);
              }}
            >
              导出 CSV
            </Button>,
            <Button
              key="manual"
              type="primary"
              disabled={selectedRows.filter((r) => r.status !== 'matched').length === 0}
              onClick={() => setManualModalOpen(true)}
            >
              手动对账 ({selectedRows.filter((r) => r.status !== 'matched').length})
            </Button>,
          ],
        }}
        search={false}
        pagination={{ pageSize: 10 }}
        dateFormatter="string"
        headerTitle="支付对账明细"
      />

      {/* 收银员收款明细折叠面板 */}
      <Collapse
        items={[
          {
            key: 'cashier',
            label: '收银员收款明细',
            children: (
              <CashierReceiptsPanel
                startDate={monthStart}
                endDate={today}
              />
            ),
          },
        ]}
      />

      <ModalForm
        title="手动对账"
        open={manualModalOpen}
        onOpenChange={setManualModalOpen}
        onFinish={handleManualReconcile}
        modalProps={{ destroyOnClose: true }}
      >
        <div style={{ marginBottom: 16 }}>
          <Text>选中 <Text strong>{selectedRows.filter((r) => r.status !== 'matched').length}</Text> 条差异记录</Text>
        </div>
        <ProFormTextArea
          name="reason"
          label="对账说明"
          placeholder="请填写手动对账原因"
          rules={[{ required: true, message: '请填写对账原因' }]}
          fieldProps={{ rows: 3 }}
        />
      </ModalForm>
    </Space>
  );
}

// ─── Tab2: 外卖平台对账 ───────────────────────────────────────────────────────

function DeliveryReconcileTab() {
  const columns: ProColumns<DeliveryReconcileRow>[] = [
    { title: '日期', dataIndex: 'date', valueType: 'date', width: 110 },
    {
      title: '平台', dataIndex: 'platform', width: 100,
      filters: [
        { text: '美团', value: '美团' },
        { text: '饿了么', value: '饿了么' },
        { text: '抖音', value: '抖音' },
      ],
      onFilter: (value, record) => record.platform === value,
      render: (_, r) => {
        const colorMap: Record<string, string> = { '美团': '#FAAD14', '饿了么': '#2F54EB', '抖音': '#000000' };
        return <Tag color={colorMap[r.platform]}>{r.platform}</Tag>;
      },
    },
    { title: '订单数', dataIndex: 'order_count', width: 80 },
    { title: '平台账单(元)', dataIndex: 'platform_bill_fen', width: 130, render: (_, r) => formatMoney(r.platform_bill_fen) },
    { title: '系统记录(元)', dataIndex: 'system_record_fen', width: 130, render: (_, r) => formatMoney(r.system_record_fen) },
    { title: '佣金(元)', dataIndex: 'commission_fen', width: 110, render: (_, r) => <Text type="warning">{formatMoney(r.commission_fen)}</Text> },
    { title: '实收(元)', dataIndex: 'actual_income_fen', width: 120, render: (_, r) => <Text strong>{formatMoney(r.actual_income_fen)}</Text> },
    { title: '差异(元)', dataIndex: 'diff_fen', width: 110, sorter: (a, b) => a.diff_fen - b.diff_fen, render: (_, r) => <DiffDisplay diff_fen={r.diff_fen} /> },
  ];

  const detailColumns = [
    { title: '订单号', dataIndex: 'order_id', key: 'order_id' },
    { title: '平台金额(元)', dataIndex: 'platform_amount_fen', key: 'platform_amount_fen', render: (_: unknown, r: DeliveryOrderDetail) => fen2yuan(r.platform_amount_fen) },
    { title: '系统金额(元)', dataIndex: 'system_amount_fen', key: 'system_amount_fen', render: (_: unknown, r: DeliveryOrderDetail) => fen2yuan(r.system_amount_fen) },
    { title: '佣金(元)', dataIndex: 'commission_fen', key: 'commission_fen', render: (_: unknown, r: DeliveryOrderDetail) => fen2yuan(r.commission_fen) },
    { title: '状态', dataIndex: 'status', key: 'status', render: (_: unknown, r: DeliveryOrderDetail) => <Tag color={r.status === '已完成' ? 'green' : 'red'}>{r.status}</Tag> },
  ];

  return (
    <ProTable<DeliveryReconcileRow>
      columns={columns}
      rowKey="id"
      request={async () => {
        const data = await fetchDeliveryRows();
        return { data, success: true, total: data.length };
      }}
      expandable={{
        expandedRowRender: (record) => (
          record.details.length > 0 ? (
            <Table
              columns={detailColumns}
              dataSource={record.details}
              rowKey="order_id"
              pagination={false}
              size="small"
            />
          ) : (
            <Text type="secondary">暂无订单级明细</Text>
          )
        ),
      }}
      search={false}
      pagination={{ pageSize: 10 }}
      headerTitle="外卖平台对账"
    />
  );
}

// ─── Tab3: 储值卡对账 ──────────────────────────────────────────────────────────

function StoredValueTab() {
  const [data, setData] = useState<StoredValueSummary | null>(null);

  useEffect(() => {
    fetchStoredValue().then(setData);
  }, []);

  if (!data) return null;

  const anomalyColumns: ProColumns<StoredValueAnomaly>[] = [
    { title: '卡号', dataIndex: 'card_id', width: 100 },
    { title: '会员', dataIndex: 'member_name', width: 80 },
    { title: '手机号', dataIndex: 'phone', width: 130 },
    { title: '预期余额(元)', dataIndex: 'expected_balance_fen', width: 130, render: (_, r) => formatMoney(r.expected_balance_fen) },
    { title: '实际余额(元)', dataIndex: 'actual_balance_fen', width: 130, render: (_, r) => formatMoney(r.actual_balance_fen) },
    { title: '差异(元)', dataIndex: 'diff_fen', width: 110, render: (_, r) => <DiffDisplay diff_fen={r.diff_fen} /> },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="充值汇总" value={fen2yuanNum(data.recharge_total_fen)} prefix="¥" precision={2} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="消费汇总" value={fen2yuanNum(data.consume_total_fen)} prefix="¥" precision={2} valueStyle={{ color: '#FF6B35' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="退款汇总" value={fen2yuanNum(data.refund_total_fen)} prefix="¥" precision={2} valueStyle={{ color: '#faad14' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="当前余额总计" value={fen2yuanNum(data.balance_total_fen)} prefix="¥" precision={2} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
      </Row>
      <Card
        title={<Text strong>余额异常列表 ({data.anomalies.length})</Text>}
        extra={<Tag color="red">余额不一致</Tag>}
      >
        <ProTable<StoredValueAnomaly>
          columns={anomalyColumns}
          dataSource={data.anomalies}
          rowKey="card_id"
          search={false}
          pagination={false}
          options={false}
        />
      </Card>
    </Space>
  );
}

// ─── Tab4: 对账报告 ────────────────────────────────────────────────────────────

function ReportTab() {
  const [reportData, setReportData] = useState<MonthlyReportData | null>(null);
  const [month, setMonth] = useState('2026-03');

  const loadReport = useCallback(async (m: string) => {
    const data = await fetchReportData(m);
    setReportData(data);
  }, []);

  useEffect(() => {
    loadReport(month);
  }, [month, loadReport]);

  const handleExportPDF = () => {
    message.success('PDF 导出已加入队列（模拟）');
  };

  if (!reportData) return null;

  const total = reportData.income_sources.reduce((s, v) => s + v.amount_fen, 0);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row justify="space-between" align="middle">
        <Space>
          <Text strong>月份:</Text>
          <DatePicker
            picker="month"
            onChange={(_, dateStr) => {
              if (typeof dateStr === 'string' && dateStr) setMonth(dateStr);
            }}
            style={{ width: 160 }}
          />
        </Space>
        <Button icon={<DownloadOutlined />} onClick={handleExportPDF}>导出 PDF</Button>
      </Row>

      <Card title={`${reportData.month} 收入来源分布 (总计: ¥${formatMoney(total)})`}>
        <IncomePieChart sources={reportData.income_sources} />
      </Card>

      <Card title={`${reportData.month} 对账差异趋势`}>
        <DiffTrendChart data={reportData.diff_trend} />
      </Card>
    </Space>
  );
}

// ─── 主组件 ────────────────────────────────────────────────────────────────────

export function ReconciliationPage() {
  const [summary, setSummary] = useState<ReconcileSummary>(EMPTY_SUMMARY);
  const [selectedDate, setSelectedDate] = useState<string>(
    new Date().toISOString().slice(0, 10),
  );
  const [selectedStore, setSelectedStore] = useState<string>('all');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmNotes, setConfirmNotes] = useState('');
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [storeOptions, setStoreOptions] = useState<Array<{ value: string; label: string }>>([
    { value: 'all', label: '全部门店' },
  ]);

  // 一次性加载门店列表
  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((data) => {
        const opts = [
          { value: 'all', label: '全部门店' },
          ...(data.items ?? []).map((s) => ({ value: s.id, label: s.name })),
        ];
        setStoreOptions(opts);
      })
      .catch(() => {
        // API 失败时保持默认"全部门店"选项
      });
  }, []);

  useEffect(() => {
    fetchSummary(selectedDate, selectedStore).then(setSummary);
  }, [selectedDate, selectedStore]);

  const handleConfirm = async () => {
    if (selectedStore === 'all') {
      message.warning('请先选择具体门店再确认对账');
      return;
    }
    setConfirmLoading(true);
    try {
      await confirmReconciliation({
        date: selectedDate,
        store_id: selectedStore,
        notes: confirmNotes,
      });
      message.success('对账已确认');
      setConfirmOpen(false);
      setConfirmNotes('');
      fetchSummary(selectedDate, selectedStore).then(setSummary);
    } catch (err) {
      console.error('[ReconciliationPage] confirm error', err);
      message.error('确认对账失败，请重试');
    } finally {
      setConfirmLoading(false);
    }
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <Space direction="vertical" size={16} style={{ width: '100%', padding: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title level={3} style={{ margin: 0 }}>财务对账中心</Title>
          <Space>
            <Select
              value={selectedStore}
              onChange={setSelectedStore}
              options={storeOptions}
              style={{ width: 200 }}
            />
            <DatePicker
              value={selectedDate ? dayjs(selectedDate) : undefined}
              onChange={(_, dateStr) => {
                if (typeof dateStr === 'string' && dateStr) setSelectedDate(dateStr);
              }}
              style={{ width: 140 }}
            />
            <Button
              type="primary"
              onClick={() => setConfirmOpen(true)}
            >
              确认对账
            </Button>
          </Space>
        </div>

        {/* 确认对账 Modal */}
        <Modal
          title="确认对账"
          open={confirmOpen}
          onOk={handleConfirm}
          onCancel={() => setConfirmOpen(false)}
          confirmLoading={confirmLoading}
          okText="确认提交"
        >
          <div style={{ marginBottom: 12 }}>
            <Text>门店：{storeOptions.find(s => s.value === selectedStore)?.label ?? selectedStore}</Text>
            <br />
            <Text>日期：{selectedDate}</Text>
          </div>
          <Input.TextArea
            rows={3}
            placeholder="备注说明（选填）"
            value={confirmNotes}
            onChange={(e) => setConfirmNotes(e.target.value)}
          />
        </Modal>

        {/* 顶部汇总卡片 */}
        <Row gutter={16}>
          <Col span={6}>
            <Card>
              <Statistic
                title="今日收入总计"
                value={fen2yuanNum(summary.today_income_fen)}
                prefix={<DollarOutlined />}
                suffix="元"
                precision={2}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="待对账金额"
                value={fen2yuanNum(summary.pending_amount_fen)}
                prefix={<SwapOutlined />}
                suffix="元"
                precision={2}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="差异金额"
                value={fen2yuanNum(summary.diff_amount_fen)}
                prefix={<ExclamationCircleOutlined />}
                suffix="元"
                precision={2}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="对账完成率"
                value={summary.completion_rate}
                prefix={<CheckCircleOutlined />}
                suffix="%"
                precision={1}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
        </Row>

        {/* Tab 区域 */}
        <Card>
          <Tabs
            defaultActiveKey="payment"
            items={[
              { key: 'payment', label: '支付对账', children: <PaymentReconcileTab /> },
              { key: 'delivery', label: '外卖平台对账', children: <DeliveryReconcileTab /> },
              { key: 'stored-value', label: '储值卡对账', children: <StoredValueTab /> },
              { key: 'report', label: '对账报告', children: <ReportTab /> },
            ]}
          />
        </Card>
      </Space>
    </ConfigProvider>
  );
}

export default ReconciliationPage;
