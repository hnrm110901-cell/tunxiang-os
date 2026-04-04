/**
 * 采购管理页面 — 域D 供应链
 * Tab1: 采购订单 | Tab2: 供应商管理 | Tab3: 价格记录
 *
 * 技术栈：Ant Design 5.x + ProComponents
 * API: txFetch → /api/v1/supply/* ; try/catch 降级 Mock
 * 金额规范：存储/传输用分（fen），展示用元（÷100），提交时×100
 */
import React, { useRef, useState, useEffect, useCallback } from 'react';
import {
  ProTable,
  ProColumns,
  ActionType,
} from '@ant-design/pro-components';
import {
  Button,
  Tag,
  Space,
  Alert,
  Drawer,
  Descriptions,
  Table,
  Form,
  InputNumber,
  DatePicker,
  message,
  Popconfirm,
  Typography,
  Divider,
  Tabs,
  Row,
  Col,
  Card,
  Statistic,
  Input,
  Select,
  Modal,
  Badge,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  MinusCircleOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  ShoppingCartOutlined,
  DollarOutlined,
  InboxOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetch, txFetchData } from '../../api/client';

const { Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type POStatus = 'pending' | 'confirmed' | 'shipped' | 'received' | 'cancelled' | 'partial';

interface PurchaseOrderItem {
  id?: string;
  ingredient_name: string;
  spec?: string;
  quantity: number;
  unit: string;
  unit_price_fen: number;
  subtotal_fen: number;
  received_quantity?: number;
  notes?: string;
}

interface PurchaseOrder {
  id: string;
  tenant_id?: string;
  store_id?: string;
  store_name?: string;
  supplier_id?: string;
  supplier_name?: string;
  po_number: string;
  status: POStatus;
  total_amount_fen: number;
  item_count?: number;
  expected_delivery_date?: string;
  actual_delivery_date?: string;
  approved_by?: string;
  approved_at?: string;
  received_at?: string;
  notes?: string;
  created_at: string;
  items?: PurchaseOrderItem[];
}

interface PurchaseStats {
  month_order_count: number;
  month_amount_fen: number;
  pending_receive_count: number;
  exception_count: number;
}

type SupplierStatus = 'active' | 'inactive' | 'suspended';

interface Supplier {
  id: string;
  name: string;
  contact_name?: string;
  contact_phone?: string;
  category?: string;
  status: SupplierStatus;
  score?: number;
  created_at?: string;
}

interface PriceRecord {
  id: string;
  ingredient_name: string;
  supplier_name: string;
  latest_price_fen: number;
  prev_price_fen: number;
  price_change_pct: number;
  updated_at: string;
  history?: number[];
}

interface CreatePOFormValues {
  supplier_id?: string;
  store_id?: string;
  expected_delivery_date?: string;
  notes?: string;
  items: {
    ingredient_name: string;
    spec?: string;
    quantity: number;
    unit: string;
    unit_price_yuan: number;
  }[];
}

// Mock 数据已移除，所有数据来自真实 API，失败时返回空数据 fallback

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number): string => (fen / 100).toFixed(2);
const fenToWan = (fen: number): string => (fen / 1000000).toFixed(2);

// ─── 状态 Badge 配置 ──────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<POStatus, { label: string; color: string; status: 'default' | 'processing' | 'success' | 'error' | 'warning' }> = {
  pending:   { label: '待确认', color: 'default',  status: 'default'    },
  confirmed: { label: '已确认', color: 'blue',     status: 'processing' },
  shipped:   { label: '运输中', color: 'orange',   status: 'warning'    },
  received:  { label: '已收货', color: 'green',    status: 'success'    },
  cancelled: { label: '已取消', color: 'red',      status: 'error'      },
  partial:   { label: '部分收', color: 'purple',   status: 'warning'    },
};

const StatusBadge = ({ status }: { status: POStatus }) => {
  const cfg = STATUS_CONFIG[status] ?? { label: status, color: 'default', status: 'default' };
  return <Badge status={cfg.status} text={<Tag color={cfg.color}>{cfg.label}</Tag>} />;
};

// ─── 评分星级（CSS，不用 Rate 组件）─────────────────────────────────────────────

const StarScore = ({ score }: { score: number }) => {
  const full = Math.floor(score);
  const half = score - full >= 0.5;
  return (
    <span style={{ color: '#FA8C16', letterSpacing: 2, fontSize: 13 }}>
      {'★'.repeat(full)}
      {half ? '½' : ''}
      {'☆'.repeat(5 - full - (half ? 1 : 0))}
      <Text type="secondary" style={{ marginLeft: 4, fontSize: 12 }}>{score.toFixed(1)}</Text>
    </span>
  );
};

// ─── 价格变化列 ───────────────────────────────────────────────────────────────

const PriceChange = ({ pct }: { pct: number }) => {
  if (pct === 0) return <Text type="secondary">0%</Text>;
  if (pct > 0) return (
    <Text style={{ color: '#A32D2D' }}>
      <ArrowUpOutlined /> +{pct.toFixed(1)}%
    </Text>
  );
  return (
    <Text style={{ color: '#0F6E56' }}>
      <ArrowDownOutlined /> {pct.toFixed(1)}%
    </Text>
  );
};

// ─── SVG 折线图（近30天价格走势）────────────────────────────────────────────────

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
}

function Sparkline({ data, width = 320, height = 60 }: SparklineProps) {
  if (!data || data.length === 0) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 4;
  const w = width - pad * 2;
  const h = height - pad * 2;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * w;
    const y = pad + h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(' ');

  const lastY = pad + h - ((data[data.length - 1] - min) / range) * h;
  const lastX = pad + w;

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline
        points={points}
        fill="none"
        stroke="#FF6B35"
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      <circle cx={lastX} cy={lastY} r={3} fill="#FF6B35" />
      <text x={lastX + 4} y={lastY + 4} fontSize={9} fill="#FF6B35">
        ¥{(data[data.length - 1] / 100).toFixed(2)}
      </text>
    </svg>
  );
}

// ─── API 层（txFetch + Mock 降级）────────────────────────────────────────────

const API_PO = '/api/v1/supply/purchase-orders';
const API_SUPPLIERS = '/api/v1/suppliers';

const getStoreId = () => localStorage.getItem('tx_store_id') ?? 'default';

async function fetchPurchaseStats(): Promise<PurchaseStats> {
  try {
    return await txFetchData<PurchaseStats>('/api/v1/supply/purchase-stats');
  } catch {
    return { month_order_count: 0, month_amount_fen: 0, pending_receive_count: 0, exception_count: 0 };
  }
}

async function fetchPurchaseOrders(params: {
  page?: number;
  size?: number;
  status?: string;
  supplier_id?: string;
  start_date?: string;
  end_date?: string;
  keyword?: string;
}): Promise<{ items: PurchaseOrder[]; total: number }> {
  try {
    const q = new URLSearchParams();
    const storeId = getStoreId();
    q.set('store_id', storeId);
    if (params.page) q.set('page', String(params.page));
    if (params.size) q.set('size', String(params.size));
    if (params.status) q.set('status', params.status);
    if (params.supplier_id) q.set('supplier_id', params.supplier_id);
    if (params.start_date) q.set('start_date', params.start_date);
    if (params.end_date) q.set('end_date', params.end_date);
    if (params.keyword) q.set('keyword', params.keyword);
    return await txFetchData<{ items: PurchaseOrder[]; total: number }>(`${API_PO}?${q.toString()}`);
  } catch {
    return { items: [], total: 0 };
  }
}

async function fetchPODetail(id: string): Promise<PurchaseOrder | null> {
  try {
    return await txFetchData<PurchaseOrder>(`${API_PO}/${id}`);
  } catch {
    return null;
  }
}

async function createPurchaseOrder(payload: unknown): Promise<void> {
  await txFetch(API_PO, { method: 'POST', body: JSON.stringify(payload) });
}

async function actionPO(id: string, action: string, body?: unknown): Promise<void> {
  await txFetch(`${API_PO}/${id}/${action}`, {
    method: 'PATCH',
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function fetchSuppliers(): Promise<{ items: Supplier[]; total: number }> {
  try {
    return await txFetchData<{ items: Supplier[]; total: number }>(`${API_SUPPLIERS}?page=1&size=100`);
  } catch {
    return { items: [], total: 0 };
  }
}

async function createOrUpdateSupplier(payload: unknown, id?: string): Promise<void> {
  const url = id ? `${API_SUPPLIERS}/${id}` : API_SUPPLIERS;
  const method = id ? 'PUT' : 'POST';
  await txFetch(url, { method, body: JSON.stringify(payload) });
}

async function fetchPriceRecords(): Promise<PriceRecord[]> {
  try {
    return await txFetchData<PriceRecord[]>('/api/v1/supply/price-records');
  } catch {
    return [];
  }
}

// ─── 组件：统计卡 ─────────────────────────────────────────────────────────────

interface StatsCardsProps {
  stats: PurchaseStats;
}

function StatsCards({ stats }: StatsCardsProps) {
  return (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      <Col span={6}>
        <Card bordered={false} style={{ borderRadius: 8, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
          <Statistic
            title="本月采购单数"
            value={stats.month_order_count}
            suffix="单"
            prefix={<ShoppingCartOutlined style={{ color: '#FF6B35', marginRight: 4 }} />}
            valueStyle={{ color: '#FF6B35' }}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card bordered={false} style={{ borderRadius: 8, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
          <Statistic
            title="本月采购金额"
            value={fenToWan(stats.month_amount_fen)}
            suffix="万元"
            prefix={<DollarOutlined style={{ color: '#185FA5', marginRight: 4 }} />}
            valueStyle={{ color: '#185FA5' }}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card bordered={false} style={{ borderRadius: 8, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
          <Statistic
            title="待收货"
            value={stats.pending_receive_count}
            suffix="单"
            prefix={<InboxOutlined style={{ color: '#BA7517', marginRight: 4 }} />}
            valueStyle={{ color: '#BA7517' }}
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card
          bordered={false}
          style={{
            borderRadius: 8,
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            background: stats.exception_count > 0 ? '#FFF1F0' : undefined,
          }}
        >
          <Statistic
            title="异常单数"
            value={stats.exception_count}
            suffix="单"
            prefix={<WarningOutlined style={{ color: '#A32D2D', marginRight: 4 }} />}
            valueStyle={{ color: '#A32D2D', fontWeight: 700 }}
          />
        </Card>
      </Col>
    </Row>
  );
}

// ─── 组件：采购单详情抽屉 ──────────────────────────────────────────────────────

interface DetailDrawerProps {
  po: PurchaseOrder | null;
  open: boolean;
  onClose: () => void;
}

function DetailDrawer({ po, open, onClose }: DetailDrawerProps) {
  const [detailData, setDetailData] = useState<PurchaseOrder | null>(po);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && po) {
      setDetailData(po); // 先显示列表行数据，再刷新完整详情
      setLoading(true);
      fetchPODetail(po.id)
        .then((data) => { if (data) setDetailData(data); })
        .finally(() => setLoading(false));
    }
  }, [open, po]);

  if (!detailData) return null;
  const d = detailData;
  return (
    <Drawer
      title={`采购单详情 — ${d.po_number}`}
      open={open}
      onClose={onClose}
      width={720}
      loading={loading}
    >
      <Descriptions bordered column={2} size="small">
        <Descriptions.Item label="采购单号">{d.po_number}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <StatusBadge status={d.status} />
        </Descriptions.Item>
        <Descriptions.Item label="门店">{d.store_name ?? d.store_id ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="供应商">{d.supplier_name ?? '自采'}</Descriptions.Item>
        <Descriptions.Item label="总金额">
          <Text strong style={{ color: '#FF6B35' }}>¥{fenToYuan(d.total_amount_fen)}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="商品数">{d.item_count ?? (d.items?.length ?? '—')}</Descriptions.Item>
        <Descriptions.Item label="下单时间">
          {dayjs(d.created_at).format('YYYY-MM-DD HH:mm')}
        </Descriptions.Item>
        <Descriptions.Item label="预计到货">
          {d.expected_delivery_date ?? '—'}
        </Descriptions.Item>
        <Descriptions.Item label="实际到货">
          {d.actual_delivery_date ?? '—'}
        </Descriptions.Item>
        <Descriptions.Item label="收货时间">
          {d.received_at ? dayjs(d.received_at).format('YYYY-MM-DD HH:mm') : '—'}
        </Descriptions.Item>
        {d.notes && (
          <Descriptions.Item label="备注" span={2}>{d.notes}</Descriptions.Item>
        )}
      </Descriptions>

      <Divider>采购明细</Divider>
      <Table<PurchaseOrderItem>
        dataSource={d.items ?? []}
        rowKey={(r, idx) => r.id ?? `item-${idx}`}
        size="small"
        pagination={false}
        columns={[
          { title: '商品名称', dataIndex: 'ingredient_name' },
          { title: '规格', dataIndex: 'spec', render: (v) => v ?? '—' },
          { title: '单价', render: (_, r) => `¥${fenToYuan(r.unit_price_fen)}` },
          { title: '数量', render: (_, r) => `${r.quantity} ${r.unit}` },
          { title: '小计', render: (_, r) => <Text strong>¥{fenToYuan(r.subtotal_fen)}</Text> },
          {
            title: '实收数量',
            render: (_, r) => r.received_quantity != null
              ? <Text style={{ color: '#0F6E56' }}>{r.received_quantity} {r.unit}</Text>
              : <Text type="secondary">—</Text>,
          },
        ]}
      />
    </Drawer>
  );
}

// ─── 组件：新建采购单 Modal ───────────────────────────────────────────────────

interface CreatePOModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  suppliers: Supplier[];
}

function CreatePOModal({ open, onClose, onSuccess, suppliers }: CreatePOModalProps) {
  const [form] = Form.useForm<CreatePOFormValues>();
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recalcTotal = useCallback(() => {
    const items: CreatePOFormValues['items'] = form.getFieldValue('items') ?? [];
    const sum = items.reduce((acc, item) => acc + (item?.quantity ?? 0) * (item?.unit_price_yuan ?? 0), 0);
    setTotal(sum);
  }, [form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      setError(null);
      const payload = {
        supplier_id: values.supplier_id,
        store_id: values.store_id,
        expected_delivery_date: values.expected_delivery_date
          ? dayjs(values.expected_delivery_date).format('YYYY-MM-DD')
          : undefined,
        notes: values.notes,
        items: values.items.map((item) => ({
          ingredient_name: item.ingredient_name,
          spec: item.spec,
          quantity: item.quantity,
          unit: item.unit,
          unit_price_fen: Math.round((item.unit_price_yuan ?? 0) * 100),
          subtotal_fen: Math.round(item.quantity * (item.unit_price_yuan ?? 0) * 100),
        })),
      };
      await createPurchaseOrder(payload);
      message.success('采购单创建成功');
      form.resetFields();
      setTotal(0);
      onSuccess();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '创建失败，请重试';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="新建采购单"
      open={open}
      onCancel={onClose}
      width={800}
      footer={
        <Space>
          <Text type="secondary">合计：</Text>
          <Text strong style={{ fontSize: 16, color: '#FF6B35' }}>¥{total.toFixed(2)}</Text>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={loading} onClick={handleSubmit}>
            创建采购单
          </Button>
        </Space>
      }
    >
      {error && (
        <Alert type="error" message={error} closable onClose={() => setError(null)} style={{ marginBottom: 16 }} />
      )}
      <Form
        form={form}
        layout="vertical"
        onValuesChange={recalcTotal}
        initialValues={{ items: [{ unit: 'kg' }] }}
      >
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="supplier_id" label="供应商">
              <Select placeholder="选择供应商（空=自采）" allowClear>
                {suppliers.filter((s) => s.status === 'active').map((s) => (
                  <Select.Option key={s.id} value={s.id}>{s.name}</Select.Option>
                ))}
              </Select>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="store_id" label="仓库/门店" rules={[{ required: true, message: '请选择门店' }]}>
              <Select placeholder="选择门店">
                <Select.Option value="store-001">芙蓉路店</Select.Option>
                <Select.Option value="store-002">五一广场店</Select.Option>
                <Select.Option value="store-003">开福区店</Select.Option>
                <Select.Option value="store-004">天心区店</Select.Option>
              </Select>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="expected_delivery_date" label="预计到货日期">
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="notes" label="备注">
              <Input placeholder="选填" />
            </Form.Item>
          </Col>
        </Row>

        <Divider>采购明细</Divider>

        <Form.List name="items">
          {(fields, { add, remove }) => (
            <>
              <Table
                dataSource={fields}
                rowKey="key"
                pagination={false}
                size="small"
                columns={[
                  {
                    title: '商品名称',
                    render: (_, field) => (
                      <Form.Item name={[field.name, 'ingredient_name']} rules={[{ required: true, message: '必填' }]} noStyle>
                        <Input placeholder="商品名称" style={{ width: 110 }} />
                      </Form.Item>
                    ),
                  },
                  {
                    title: '规格',
                    render: (_, field) => (
                      <Form.Item name={[field.name, 'spec']} noStyle>
                        <Input placeholder="选填" style={{ width: 80 }} />
                      </Form.Item>
                    ),
                  },
                  {
                    title: '单价(元)',
                    render: (_, field) => (
                      <Form.Item name={[field.name, 'unit_price_yuan']} rules={[{ required: true, message: '必填' }]} noStyle>
                        <InputNumber min={0} precision={2} prefix="¥" style={{ width: 90 }} />
                      </Form.Item>
                    ),
                  },
                  {
                    title: '数量',
                    render: (_, field) => (
                      <Form.Item name={[field.name, 'quantity']} rules={[{ required: true, message: '必填' }]} noStyle>
                        <InputNumber min={0.001} precision={3} style={{ width: 80 }} />
                      </Form.Item>
                    ),
                  },
                  {
                    title: '单位',
                    render: (_, field) => (
                      <Form.Item name={[field.name, 'unit']} noStyle>
                        <Select style={{ width: 68 }}>
                          <Select.Option value="kg">kg</Select.Option>
                          <Select.Option value="件">件</Select.Option>
                          <Select.Option value="箱">箱</Select.Option>
                          <Select.Option value="包">包</Select.Option>
                          <Select.Option value="瓶">瓶</Select.Option>
                          <Select.Option value="袋">袋</Select.Option>
                        </Select>
                      </Form.Item>
                    ),
                  },
                  {
                    title: '',
                    width: 32,
                    render: (_, field) => fields.length > 1 ? (
                      <MinusCircleOutlined
                        style={{ color: '#A32D2D', cursor: 'pointer', fontSize: 16 }}
                        onClick={() => remove(field.name)}
                      />
                    ) : null,
                  },
                ]}
              />
              <Button
                type="dashed"
                onClick={() => add({ unit: 'kg' })}
                icon={<PlusOutlined />}
                style={{ width: '100%', marginTop: 8 }}
              >
                添加明细行
              </Button>
            </>
          )}
        </Form.List>
      </Form>
    </Modal>
  );
}

// ─── Tab1：采购订单 ───────────────────────────────────────────────────────────

interface PurchaseOrderTabProps {
  suppliers: Supplier[];
}

function PurchaseOrderTab({ suppliers }: PurchaseOrderTabProps) {
  const actionRef = useRef<ActionType>();
  const [createOpen, setCreateOpen] = useState(false);
  const [detailPO, setDetailPO] = useState<PurchaseOrder | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);

  // 筛选状态（顶部自定义筛选栏）
  const [filterDateRange, setFilterDateRange] = useState<[string, string] | null>(null);
  const [filterSupplier, setFilterSupplier] = useState<string | undefined>();
  const [filterStatus, setFilterStatus] = useState<string | undefined>();
  const [filterKeyword, setFilterKeyword] = useState('');

  const handleAction = async (action: string, po: PurchaseOrder, successMsg: string) => {
    try {
      await actionPO(po.id, action);
      message.success(successMsg);
      actionRef.current?.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '操作失败，请重试';
      setGlobalError(msg);
    }
  };

  const columns: ProColumns<PurchaseOrder>[] = [
    {
      title: '单号',
      dataIndex: 'po_number',
      width: 180,
      hideInSearch: true,
      render: (_, r) => (
        <a
          style={{ color: '#185FA5', fontFamily: 'monospace', fontSize: 12 }}
          onClick={() => setDetailPO(r)}
        >
          {r.po_number}
        </a>
      ),
    },
    {
      title: '供应商',
      dataIndex: 'supplier_name',
      hideInSearch: true,
      render: (_, r) => r.supplier_name ?? <Text type="secondary">自采</Text>,
    },
    {
      title: '仓库/门店',
      dataIndex: 'store_name',
      hideInSearch: true,
      render: (_, r) => r.store_name ?? r.store_id ?? '—',
    },
    {
      title: '下单时间',
      dataIndex: 'created_at',
      hideInSearch: true,
      render: (_, r) => dayjs(r.created_at).format('MM-DD HH:mm'),
    },
    {
      title: '预计到货',
      dataIndex: 'expected_delivery_date',
      hideInSearch: true,
      render: (_, r) => {
        if (!r.expected_delivery_date) return '—';
        const isLate = dayjs(r.expected_delivery_date).isBefore(dayjs(), 'day')
          && r.status !== 'received' && r.status !== 'cancelled';
        return (
          <Text style={isLate ? { color: '#A32D2D', fontWeight: 600 } : undefined}>
            {r.expected_delivery_date}
          </Text>
        );
      },
    },
    {
      title: '金额',
      dataIndex: 'total_amount_fen',
      hideInSearch: true,
      render: (_, r) => <Text strong>¥{fenToYuan(r.total_amount_fen)}</Text>,
    },
    {
      title: '商品数',
      dataIndex: 'item_count',
      hideInSearch: true,
      render: (_, r) => r.item_count ?? (r.items?.length ?? '—'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      hideInSearch: true,
      render: (_, r) => <StatusBadge status={r.status} />,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, r) => {
        const btns: React.ReactNode[] = [
          <a key="detail" style={{ color: '#666' }} onClick={() => setDetailPO(r)}>查看详情</a>,
        ];
        if (r.status === 'confirmed' || r.status === 'shipped' || r.status === 'partial') {
          btns.unshift(
            <Popconfirm
              key="receive"
              title="确认收货？"
              description="确认后将更新库存并标记为已收货"
              onConfirm={() => handleAction('receive', r, '收货确认成功')}
              okText="确认收货"
              cancelText="取消"
            >
              <a style={{ color: '#0F6E56' }}>确认收货</a>
            </Popconfirm>,
          );
        }
        if (r.status === 'pending') {
          btns.unshift(
            <Popconfirm
              key="approve"
              title="确认审批通过该采购单？"
              onConfirm={() => handleAction('approve', r, '采购单已审批通过')}
              okText="确认审批"
              cancelText="取消"
            >
              <a style={{ color: '#0F6E56' }}>审批</a>
            </Popconfirm>,
            <Popconfirm
              key="reject"
              title="确认拒绝该采购单？"
              onConfirm={() => handleAction('reject', r, '采购单已拒绝')}
              okText="确认拒绝"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <a style={{ color: '#A32D2D' }}>拒绝</a>
            </Popconfirm>,
          );
        }
        return <Space size="middle">{btns}</Space>;
      },
    },
  ];

  return (
    <>
      {globalError && (
        <Alert
          type="error"
          message={globalError}
          closable
          onClose={() => setGlobalError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 顶部筛选栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <RangePicker
          style={{ width: 240 }}
          onChange={(_, s) => setFilterDateRange(s[0] && s[1] ? [s[0], s[1]] : null)}
        />
        <Select
          style={{ width: 160 }}
          placeholder="供应商"
          allowClear
          onChange={(v) => setFilterSupplier(v)}
        >
          {suppliers.map((s) => (
            <Select.Option key={s.id} value={s.id}>{s.name}</Select.Option>
          ))}
        </Select>
        <Select
          style={{ width: 120 }}
          placeholder="状态"
          allowClear
          onChange={(v) => setFilterStatus(v)}
        >
          {Object.entries(STATUS_CONFIG).map(([k, v]) => (
            <Select.Option key={k} value={k}>{v.label}</Select.Option>
          ))}
        </Select>
        <Input.Search
          style={{ width: 200 }}
          placeholder="单号/供应商"
          onSearch={(v) => {
            setFilterKeyword(v);
            actionRef.current?.reload();
          }}
          allowClear
        />
        <Button
          type="default"
          onClick={() => {
            setFilterDateRange(null);
            setFilterSupplier(undefined);
            setFilterStatus(undefined);
            setFilterKeyword('');
            actionRef.current?.reload();
          }}
        >
          重置
        </Button>
      </div>

      <ProTable<PurchaseOrder>
        headerTitle="采购订单列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={false}
        request={async (params) => {
          const data = await fetchPurchaseOrders({
            page: params.current ?? 1,
            size: params.pageSize ?? 20,
            status: filterStatus,
            supplier_id: filterSupplier,
            start_date: filterDateRange?.[0],
            end_date: filterDateRange?.[1],
            keyword: filterKeyword,
          });
          return { data: data.items, total: data.total, success: true };
        }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新建采购单
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
      />

      <CreatePOModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSuccess={() => actionRef.current?.reload()}
        suppliers={suppliers}
      />
      <DetailDrawer
        po={detailPO}
        open={!!detailPO}
        onClose={() => setDetailPO(null)}
      />
    </>
  );
}

// ─── Tab2：供应商管理 ──────────────────────────────────────────────────────────

const SUPPLIER_STATUS_CONFIG: Record<SupplierStatus, { label: string; color: string }> = {
  active:    { label: '合作中', color: 'green'   },
  inactive:  { label: '暂停',   color: 'default' },
  suspended: { label: '已终止', color: 'red'     },
};

interface SupplierFormValues {
  name: string;
  contact_name?: string;
  contact_phone?: string;
  category?: string;
  status: SupplierStatus;
}

function SupplierTab() {
  const actionRef = useRef<ActionType>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Supplier | null>(null);
  const [form] = Form.useForm<SupplierFormValues>();
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await createOrUpdateSupplier(values, editTarget?.id);
      message.success(editTarget ? '供应商更新成功' : '供应商新增成功');
      setModalOpen(false);
      setEditTarget(null);
      form.resetFields();
      actionRef.current?.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '操作失败';
      message.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (s: Supplier) => {
    setEditTarget(s);
    form.setFieldsValue({
      name: s.name,
      contact_name: s.contact_name,
      contact_phone: s.contact_phone,
      category: s.category,
      status: s.status,
    });
    setModalOpen(true);
  };

  const columns: ProColumns<Supplier>[] = [
    { title: '名称', dataIndex: 'name', width: 180 },
    { title: '联系人', dataIndex: 'contact_name', hideInSearch: true, render: (_, r) => r.contact_name ?? '—' },
    { title: '电话', dataIndex: 'contact_phone', hideInSearch: true, render: (_, r) => r.contact_phone ?? '—' },
    { title: '品类', dataIndex: 'category', hideInSearch: true, render: (_, r) => r.category ?? '—' },
    {
      title: '合作状态',
      dataIndex: 'status',
      hideInSearch: true,
      render: (_, r) => {
        const cfg = SUPPLIER_STATUS_CONFIG[r.status] ?? { label: r.status, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '评分',
      dataIndex: 'score',
      hideInSearch: true,
      render: (_, r) => r.score != null ? <StarScore score={r.score} /> : <Text type="secondary">—</Text>,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, r) => (
        <Space size="middle">
          <a style={{ color: '#185FA5' }} onClick={() => openEdit(r)}>查看/编辑</a>
          {r.status === 'active' && (
            <Popconfirm
              title="确认停用该供应商？"
              onConfirm={async () => {
                await createOrUpdateSupplier({ ...r, status: 'inactive' }, r.id);
                message.success('已停用');
                actionRef.current?.reload();
              }}
              okText="停用"
              okButtonProps={{ danger: true }}
            >
              <a style={{ color: '#A32D2D' }}>停用</a>
            </Popconfirm>
          )}
          {r.status === 'inactive' && (
            <a
              style={{ color: '#0F6E56' }}
              onClick={async () => {
                await createOrUpdateSupplier({ ...r, status: 'active' }, r.id);
                message.success('已恢复合作');
                actionRef.current?.reload();
              }}
            >
              恢复合作
            </a>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<Supplier>
        headerTitle="供应商列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={false}
        request={async () => {
          const data = await fetchSuppliers();
          return { data: data.items, total: data.total, success: true };
        }}
        toolBarRender={() => [
          <Button
            key="add"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditTarget(null);
              form.resetFields();
              setModalOpen(true);
            }}
          >
            新增供应商
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
      />

      <Modal
        title={editTarget ? '编辑供应商' : '新增供应商'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          setEditTarget(null);
          form.resetFields();
        }}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="供应商名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="请输入供应商名称" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="contact_name" label="联系人">
                <Input placeholder="选填" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="contact_phone" label="联系电话">
                <Input placeholder="选填" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="category" label="品类">
                <Select placeholder="选填" allowClear>
                  {['蔬菜', '肉类/冷冻', '海鲜', '调料', '粮油', '其他'].map((c) => (
                    <Select.Option key={c} value={c}>{c}</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="status" label="合作状态" rules={[{ required: true }]} initialValue="active">
                <Select>
                  {Object.entries(SUPPLIER_STATUS_CONFIG).map(([k, v]) => (
                    <Select.Option key={k} value={k}>{v.label}</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab3：价格记录 ────────────────────────────────────────────────────────────

function PriceRecordTab() {
  const [records, setRecords] = useState<PriceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  useEffect(() => {
    fetchPriceRecords().then((data) => {
      setRecords(data);
      setLoading(false);
    });
  }, []);

  const columns: ProColumns<PriceRecord>[] = [
    { title: '食材名称', dataIndex: 'ingredient_name', width: 150 },
    { title: '供应商', dataIndex: 'supplier_name', width: 160 },
    {
      title: '最近价格',
      dataIndex: 'latest_price_fen',
      hideInSearch: true,
      render: (_, r) => <Text strong>¥{fenToYuan(r.latest_price_fen)}</Text>,
    },
    {
      title: '上期价格',
      dataIndex: 'prev_price_fen',
      hideInSearch: true,
      render: (_, r) => <Text type="secondary">¥{fenToYuan(r.prev_price_fen)}</Text>,
    },
    {
      title: '价格变化',
      dataIndex: 'price_change_pct',
      hideInSearch: true,
      render: (_, r) => <PriceChange pct={r.price_change_pct} />,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      hideInSearch: true,
      render: (_, r) => dayjs(r.updated_at).format('MM-DD HH:mm'),
    },
    {
      title: '近30天走势',
      valueType: 'option',
      width: 100,
      render: (_, r) => (
        <Tooltip title="点击展开/收起价格走势图">
          <a
            style={{ color: '#185FA5' }}
            onClick={() => setExpandedRowId(expandedRowId === r.id ? null : r.id)}
          >
            {expandedRowId === r.id ? '收起' : '展开'}
          </a>
        </Tooltip>
      ),
    },
  ];

  return (
    <ProTable<PriceRecord>
      headerTitle="食材价格记录"
      rowKey="id"
      columns={columns}
      dataSource={records}
      loading={loading}
      search={false}
      pagination={{ defaultPageSize: 20 }}
      expandable={{
        expandedRowKeys: expandedRowId ? [expandedRowId] : [],
        expandedRowRender: (r) => (
          <div style={{ padding: '8px 16px', background: '#F8F7F5', borderRadius: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {r.ingredient_name} · 近30天价格走势（单位: 元/kg）
            </Text>
            <div style={{ marginTop: 8 }}>
              {r.history && r.history.length > 0
                ? <Sparkline data={r.history} width={360} height={64} />
                : <Text type="secondary">暂无历史数据</Text>
              }
            </div>
          </div>
        ),
        onExpand: (expanded, r) => setExpandedRowId(expanded ? r.id : null),
        showExpandColumn: false,
      }}
    />
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function PurchaseOrderPage() {
  const [stats, setStats] = useState<PurchaseStats>({ month_order_count: 0, month_amount_fen: 0, pending_receive_count: 0, exception_count: 0 });
  const [statsLoading, setStatsLoading] = useState(true);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [activeTab, setActiveTab] = useState('orders');

  useEffect(() => {
    fetchPurchaseStats().then((s) => {
      setStats(s);
      setStatsLoading(false);
    });
    fetchSuppliers().then((d) => setSuppliers(d.items));
  }, []);

  const tabItems = [
    {
      key: 'orders',
      label: '采购订单',
      children: <PurchaseOrderTab suppliers={suppliers} />,
    },
    {
      key: 'suppliers',
      label: '供应商管理',
      children: <SupplierTab />,
    },
    {
      key: 'prices',
      label: '价格记录',
      children: <PriceRecordTab />,
    },
  ];

  return (
    <div style={{ padding: '24px 24px 0' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 16 }}>
        <Text style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>采购管理</Text>
        <Text type="secondary" style={{ marginLeft: 12, fontSize: 13 }}>
          域D · 供应链 · tx-supply:8006
        </Text>
      </div>

      {/* 顶部统计卡 */}
      {!statsLoading && <StatsCards stats={stats} />}

      {/* Tab 内容区 */}
      <Card
        bordered={false}
        style={{ borderRadius: 8, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}
        bodyStyle={{ padding: '0 24px 24px' }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          size="large"
          tabBarStyle={{ marginBottom: 16 }}
        />
      </Card>
    </div>
  );
}

export default PurchaseOrderPage;
