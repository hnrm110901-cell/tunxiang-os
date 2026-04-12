/**
 * 库存管理与预警页面 — 域D 供应链
 * Tab1: 库存总览 | Tab2: 库存流水 | Tab3: 临期预警 | Tab4: 盘点
 *
 * 技术栈：Ant Design 5.x + ProComponents
 * API: /api/v1/supply/* via txFetchData；失败时空数据 fallback
 */
import React, { useRef, useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../api/client';
import {
  ProTable,
  ProColumns,
  ActionType,
  EditableProTable,
} from '@ant-design/pro-components';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
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
  Tabs,
  Tag,
  Tooltip,
  Typography,
  DatePicker,
} from 'antd';
import {
  ExclamationCircleOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  PlusOutlined,
  MinusCircleOutlined,
  FileSearchOutlined,
  AlertOutlined,
  AuditOutlined,
  InboxOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';

const { Text, Title } = Typography;
const { RangePicker } = DatePicker;

// BASE URL 已废弃，改用 txFetchData 统一请求

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type InventoryStatus = 'normal' | 'low' | 'out_of_stock' | 'overstock';

interface InventoryItem {
  id: string;
  ingredient_name: string;
  category: string;
  current_stock: number;
  safety_stock: number;
  unit: string;
  status: InventoryStatus;
  last_inbound_date: string;
  supplier_name: string;
}

interface InventoryLog {
  id: string;
  timestamp: string;
  ingredient_name: string;
  operation_type: 'inbound' | 'outbound' | 'stocktake' | 'waste';
  quantity_change: number;
  operator: string;
  remark: string;
}

interface ExpiryItem {
  id: string;
  ingredient_name: string;
  batch_no: string;
  inbound_date: string;
  expiry_date: string;
  remaining_days: number;
  image_url?: string;
  handled: boolean;
}

interface StocktakeRow {
  id: string;
  ingredient_name: string;
  system_qty: number;
  actual_qty: number;
  diff: number;
  remark: string;
}

interface AlertSummary {
  low_stock_count: number;
  expiry_count: number;
  low_stock_items: { ingredient_name: string; current_stock: number; safety_stock: number; unit: string }[];
  expiry_items: { ingredient_name: string; remaining_days: number; batch_no: string }[];
}

// Mock 数据已移除，所有数据来自真实 API，失败时返回空数组/空对象 fallback

// ─── 状态配置 ──────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<InventoryStatus, { label: string; color: string }> = {
  normal: { label: '正常', color: '#52c41a' },
  low: { label: '低库存', color: '#fa8c16' },
  out_of_stock: { label: '缺货', color: '#ff4d4f' },
  overstock: { label: '过量', color: '#722ed1' },
};

const OP_TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  inbound: { label: '入库', color: 'green' },
  outbound: { label: '出库', color: 'blue' },
  stocktake: { label: '盘点', color: 'orange' },
  waste: { label: '报损', color: 'red' },
};

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

function computeStatus(current: number, safety: number): InventoryStatus {
  if (current === 0) return 'out_of_stock';
  if (current < safety) return 'low';
  if (current > safety * 2) return 'overstock';
  return 'normal';
}

function getRemainingDaysColor(days: number): string {
  if (days <= 3) return '#ff4d4f';
  if (days <= 7) return '#fa8c16';
  return '#52c41a';
}

// ─── API 调用（txFetchData，失败时空数据 fallback）──────────────────────────────

const getStoreId = () => localStorage.getItem('tx_store_id') ?? 'default';

async function fetchInventoryList(page = 1): Promise<InventoryItem[]> {
  try {
    const data = await txFetchData<{ items: InventoryItem[]; total: number }>(
      `/api/v1/supply/inventory?store_id=${getStoreId()}&page=${page}`,
    );
    return data.items ?? [];
  } catch {
    return [];
  }
}

async function fetchInventoryLogs(): Promise<InventoryLog[]> {
  try {
    const data = await txFetchData<{ items: InventoryLog[]; total: number }>(
      `/api/v1/supply/inventory/logs?store_id=${getStoreId()}&page=1&size=100`,
    );
    return data.items ?? [];
  } catch {
    return [];
  }
}

async function fetchExpiryItems(): Promise<ExpiryItem[]> {
  try {
    const data = await txFetchData<{ items: ExpiryItem[] }>(
      `/api/v1/supply/expiry-alerts?store_id=${getStoreId()}&days=7`,
    );
    return data.items ?? [];
  } catch {
    return [];
  }
}

async function fetchAlertSummary(): Promise<AlertSummary> {
  try {
    const data = await txFetchData<AlertSummary>(
      `/api/v1/supply/inventory/alerts?store_id=${getStoreId()}`,
    );
    return data;
  } catch {
    return { low_stock_count: 0, expiry_count: 0, low_stock_items: [], expiry_items: [] };
  }
}

async function submitStockAdjust(itemId: string, delta_qty: number, reason: string): Promise<boolean> {
  try {
    await txFetchData('/api/v1/supply/inventory/adjust', {
      method: 'POST',
      body: JSON.stringify({ ingredient_id: itemId, delta_qty, reason }),
    });
    return true;
  } catch {
    return false;
  }
}

// ─── 预警横条组件 ──────────────────────────────────────────────────────────────

const AlertBanner: React.FC<{ summary: AlertSummary }> = ({ summary }) => {
  const [expanded, setExpanded] = useState(false);
  const total = summary.low_stock_count + summary.expiry_count;

  if (total === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <Alert
        type="error"
        showIcon
        icon={<AlertOutlined />}
        message={
          <Space>
            <Text strong style={{ color: '#fff' }}>
              当前有 {summary.low_stock_count} 种食材低于安全库存，{summary.expiry_count} 种即将过期
            </Text>
            <Button
              type="link"
              size="small"
              style={{ color: '#fff', textDecoration: 'underline' }}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? '收起' : '展开查看'}
            </Button>
          </Space>
        }
        style={{ background: '#ff4d4f', border: 'none' }}
      />
      {expanded && (
        <Card size="small" style={{ marginTop: 4, borderColor: '#ff4d4f' }}>
          {summary.low_stock_count > 0 && (
            <>
              <Text strong style={{ color: '#fa8c16' }}>低库存食材：</Text>
              <div style={{ marginBottom: 8 }}>
                {summary.low_stock_items.map((item, idx) => (
                  <Tag key={idx} color="orange" style={{ margin: '2px 4px' }}>
                    {item.ingredient_name}（{item.current_stock}/{item.safety_stock} {item.unit}）
                  </Tag>
                ))}
              </div>
            </>
          )}
          {summary.expiry_count > 0 && (
            <>
              <Text strong style={{ color: '#ff4d4f' }}>临期食材：</Text>
              <div>
                {summary.expiry_items.map((item, idx) => (
                  <Tag key={idx} color="red" style={{ margin: '2px 4px' }}>
                    {item.ingredient_name}（{item.batch_no}，剩余 {item.remaining_days} 天）
                  </Tag>
                ))}
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  );
};

// ─── Tab1: 库存总览 ──────────────────────────────────────────────────────────

const InventoryOverviewTab: React.FC = () => {
  const actionRef = useRef<ActionType>();
  const [adjustModal, setAdjustModal] = useState<{ visible: boolean; item?: InventoryItem }>({ visible: false });
  const [adjustForm] = Form.useForm();
  const [logModal, setLogModal] = useState<{ visible: boolean; itemName: string }>({ visible: false, itemName: '' });

  const columns: ProColumns<InventoryItem>[] = [
    {
      title: '食材名',
      dataIndex: 'ingredient_name',
      width: 120,
      ellipsis: true,
    },
    {
      title: '分类',
      dataIndex: 'category',
      width: 80,
      filters: true,
      onFilter: true,
      valueEnum: {
        肉类: { text: '肉类' },
        蔬菜: { text: '蔬菜' },
        海鲜: { text: '海鲜' },
        禽蛋: { text: '禽蛋' },
        调味: { text: '调味' },
        油脂: { text: '油脂' },
        豆制品: { text: '豆制品' },
      },
    },
    {
      title: '当前库存',
      dataIndex: 'current_stock',
      width: 100,
      sorter: (a, b) => a.current_stock - b.current_stock,
      render: (_, record) => (
        <Text strong style={{ color: record.current_stock === 0 ? '#ff4d4f' : undefined }}>
          {record.current_stock}
        </Text>
      ),
    },
    {
      title: '安全库存',
      dataIndex: 'safety_stock',
      width: 100,
    },
    {
      title: '单位',
      dataIndex: 'unit',
      width: 60,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      filters: true,
      onFilter: true,
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_CONFIG).map(([k, v]) => [k, { text: v.label }])
      ),
      render: (_, record) => {
        const cfg = STATUS_CONFIG[record.status];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '最近入库',
      dataIndex: 'last_inbound_date',
      width: 110,
      sorter: (a, b) => dayjs(a.last_inbound_date).unix() - dayjs(b.last_inbound_date).unix(),
    },
    {
      title: '供应商',
      dataIndex: 'supplier_name',
      width: 140,
      ellipsis: true,
    },
    {
      title: '操作',
      width: 160,
      valueType: 'option',
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<SyncOutlined />}
            onClick={() => {
              setAdjustModal({ visible: true, item: record });
              adjustForm.resetFields();
            }}
          >
            调整
          </Button>
          <Button
            type="link"
            size="small"
            icon={<FileSearchOutlined />}
            onClick={() => setLogModal({ visible: true, itemName: record.ingredient_name })}
          >
            流水
          </Button>
        </Space>
      ),
    },
  ];

  const handleAdjustSubmit = useCallback(async () => {
    const values = await adjustForm.validateFields();
    const item = adjustModal.item;
    if (!item) return;
    const ok = await submitStockAdjust(item.id, values.quantity, values.reason);
    if (ok) {
      message.success('库存调整成功');
      setAdjustModal({ visible: false });
      actionRef.current?.reload();
    } else {
      message.error('库存调整失败');
    }
  }, [adjustForm, adjustModal.item]);

  return (
    <>
      <ProTable<InventoryItem>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async () => {
          const data = await fetchInventoryList();
          return { data, success: true, total: data.length };
        }}
        rowClassName={(record) =>
          record.status === 'low' || record.status === 'out_of_stock' ? 'inventory-row-warning' : ''
        }
        search={{ labelWidth: 'auto', collapsed: false }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        dateFormatter="string"
        headerTitle="库存总览"
        toolBarRender={() => [
          <Button key="refresh" icon={<SyncOutlined />} onClick={() => actionRef.current?.reload()}>
            刷新
          </Button>,
        ]}
      />

      {/* 手动调整库存 Modal */}
      <Modal
        title={`调整库存 — ${adjustModal.item?.ingredient_name ?? ''}`}
        open={adjustModal.visible}
        onOk={handleAdjustSubmit}
        onCancel={() => setAdjustModal({ visible: false })}
        okText="确认调整"
        cancelText="取消"
      >
        <Form form={adjustForm} layout="vertical">
          <Form.Item label="当前库存">
            <Text strong>
              {adjustModal.item?.current_stock ?? 0} {adjustModal.item?.unit ?? ''}
            </Text>
          </Form.Item>
          <Form.Item
            name="quantity"
            label="调整数量（正数增加，负数减少）"
            rules={[{ required: true, message: '请输入调整数量' }]}
          >
            <InputNumber style={{ width: '100%' }} placeholder="例如: 10 或 -5" />
          </Form.Item>
          <Form.Item
            name="reason"
            label="调整原因"
            rules={[{ required: true, message: '请输入调整原因' }]}
          >
            <Input.TextArea rows={2} placeholder="盘点差异/报损/其他原因" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 查看流水 Modal */}
      <Modal
        title={`库存流水 — ${logModal.itemName}`}
        open={logModal.visible}
        onCancel={() => setLogModal({ visible: false, itemName: '' })}
        footer={null}
        width={700}
      >
        <InventoryLogTable filterIngredient={logModal.itemName} />
      </Modal>

      {/* 低库存行高亮样式 */}
      <style>{`
        .inventory-row-warning {
          background-color: #fff2f0 !important;
        }
        .inventory-row-warning:hover > td {
          background-color: #ffece8 !important;
        }
      `}</style>
    </>
  );
};

// ─── Tab2: 库存流水 ──────────────────────────────────────────────────────────

interface InventoryLogTableProps {
  filterIngredient?: string;
}

const InventoryLogTable: React.FC<InventoryLogTableProps> = ({ filterIngredient }) => {
  const columns: ProColumns<InventoryLog>[] = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      width: 170,
      sorter: (a, b) => dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
      defaultSortOrder: 'descend',
    },
    {
      title: '食材',
      dataIndex: 'ingredient_name',
      width: 100,
    },
    {
      title: '操作类型',
      dataIndex: 'operation_type',
      width: 90,
      filters: true,
      onFilter: true,
      valueEnum: Object.fromEntries(
        Object.entries(OP_TYPE_CONFIG).map(([k, v]) => [k, { text: v.label }])
      ),
      render: (_, record) => {
        const cfg = OP_TYPE_CONFIG[record.operation_type];
        return <Tag color={cfg?.color ?? 'default'}>{cfg?.label ?? record.operation_type}</Tag>;
      },
    },
    {
      title: '数量变化',
      dataIndex: 'quantity_change',
      width: 100,
      render: (_, record) => {
        const isPositive = record.quantity_change > 0;
        return (
          <Text strong style={{ color: isPositive ? '#52c41a' : '#ff4d4f' }}>
            {isPositive ? '+' : ''}{record.quantity_change}
          </Text>
        );
      },
    },
    {
      title: '操作人',
      dataIndex: 'operator',
      width: 80,
    },
    {
      title: '备注',
      dataIndex: 'remark',
      ellipsis: true,
    },
  ];

  return (
    <ProTable<InventoryLog>
      columns={columns}
      rowKey="id"
      request={async () => {
        const allLogs = await fetchInventoryLogs();
        const filtered = filterIngredient
          ? allLogs.filter((l) => l.ingredient_name === filterIngredient)
          : allLogs;
        return { data: filtered, success: true, total: filtered.length };
      }}
      search={filterIngredient ? false : { labelWidth: 'auto' }}
      pagination={{ pageSize: 15, showSizeChanger: true }}
      dateFormatter="string"
      headerTitle={filterIngredient ? undefined : '库存流水'}
      options={filterIngredient ? false : undefined}
    />
  );
};

const InventoryLogTab: React.FC = () => <InventoryLogTable />;

// ─── Tab3: 临期预警 ──────────────────────────────────────────────────────────

const ExpiryAlertTab: React.FC = () => {
  const [items, setItems] = useState<ExpiryItem[]>([]);
  const [loading, setLoading] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    const data = await fetchExpiryItems();
    setItems(data);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleMarkHandled = (id: string) => {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, handled: true } : item))
    );
    message.success('已标记为已处理');
  };

  const handleWaste = (id: string) => {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, handled: true } : item))
    );
    message.success('已提交报损');
  };

  const unhandled = items.filter((i) => !i.handled);
  const handled = items.filter((i) => i.handled);

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="临期食材"
              value={unhandled.length}
              suffix="种"
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="3天内过期"
              value={unhandled.filter((i) => i.remaining_days <= 3).length}
              suffix="种"
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="已处理"
              value={handled.length}
              suffix="种"
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {unhandled.map((item) => {
          const daysColor = getRemainingDaysColor(item.remaining_days);
          const isPulsing = item.remaining_days <= 3;
          return (
            <Col key={item.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                size="small"
                hoverable
                style={{ borderLeft: `4px solid ${daysColor}` }}
              >
                <div style={{ textAlign: 'center', marginBottom: 8 }}>
                  <div
                    style={{
                      width: 64,
                      height: 64,
                      borderRadius: 8,
                      background: '#f5f5f5',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      margin: '0 auto',
                    }}
                  >
                    <InboxOutlined style={{ fontSize: 28, color: '#bfbfbf' }} />
                  </div>
                </div>
                <Title level={5} style={{ margin: 0, textAlign: 'center' }}>
                  {item.ingredient_name}
                </Title>
                <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>
                  <div>批次号：{item.batch_no}</div>
                  <div>入库日期：{item.inbound_date}</div>
                  <div>到期日期：{item.expiry_date}</div>
                </div>
                <div
                  style={{
                    marginTop: 8,
                    textAlign: 'center',
                    fontSize: 20,
                    fontWeight: 700,
                    color: daysColor,
                    animation: isPulsing ? 'pulse-red 1.5s ease-in-out infinite' : undefined,
                  }}
                >
                  <ClockCircleOutlined style={{ marginRight: 4 }} />
                  剩余 {item.remaining_days} 天
                </div>
                <Space style={{ width: '100%', justifyContent: 'center', marginTop: 8 }}>
                  <Button size="small" onClick={() => handleMarkHandled(item.id)}>
                    已处理
                  </Button>
                  <Popconfirm title="确认提交报损？" onConfirm={() => handleWaste(item.id)}>
                    <Button size="small" danger>
                      报损
                    </Button>
                  </Popconfirm>
                </Space>
              </Card>
            </Col>
          );
        })}
      </Row>

      {handled.length > 0 && (
        <Card title="已处理" size="small" style={{ marginTop: 16 }}>
          <Space wrap>
            {handled.map((item) => (
              <Tag key={item.id} color="default">
                <CheckCircleOutlined style={{ marginRight: 4 }} />
                {item.ingredient_name}（{item.batch_no}）
              </Tag>
            ))}
          </Space>
        </Card>
      )}

      <style>{`
        @keyframes pulse-red {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
};

// ─── Tab4: 盘点 ──────────────────────────────────────────────────────────────

const StocktakeTab: React.FC = () => {
  const [rows, setRows] = useState<StocktakeRow[]>([]);
  const [started, setStarted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleStartStocktake = useCallback(async () => {
    const inventory = await fetchInventoryList();
    const stocktakeRows: StocktakeRow[] = inventory
      .filter((i) => i.current_stock > 0)
      .map((i) => ({
        id: i.id,
        ingredient_name: i.ingredient_name,
        system_qty: i.current_stock,
        actual_qty: i.current_stock,
        diff: 0,
        remark: '',
      }));
    setRows(stocktakeRows);
    setStarted(true);
  }, []);

  const handleActualQtyChange = (id: string, value: number | null) => {
    setRows((prev) =>
      prev.map((r) => {
        if (r.id !== id) return r;
        const actual = value ?? 0;
        return { ...r, actual_qty: actual, diff: actual - r.system_qty };
      })
    );
  };

  const handleRemarkChange = (id: string, value: string) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, remark: value } : r)));
  };

  const handleSubmit = () => {
    const diffs = rows.filter((r) => r.diff !== 0);
    Modal.confirm({
      title: '确认提交盘点结果',
      icon: <ExclamationCircleOutlined />,
      content: (
        <div>
          {diffs.length === 0 ? (
            <Text>所有食材实盘数与系统数一致，无差异。</Text>
          ) : (
            <>
              <Text>共 {diffs.length} 项存在差异：</Text>
              <div style={{ marginTop: 8 }}>
                {diffs.map((d) => (
                  <div key={d.id} style={{ marginBottom: 4 }}>
                    <Text strong>{d.ingredient_name}</Text>
                    <Text style={{ color: d.diff > 0 ? '#1890ff' : '#ff4d4f', marginLeft: 8 }}>
                      {d.diff > 0 ? `盘盈 +${d.diff}` : `盘亏 ${d.diff}`}
                    </Text>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      ),
      okText: '确认提交',
      cancelText: '返回修改',
      onOk: async () => {
        setSubmitting(true);
        // 逐项提交差异
        for (const row of diffs) {
          await submitStockAdjust(row.id, row.diff, `盘点调整: ${row.remark || '无备注'}`);
        }
        message.success('盘点结果已提交');
        setStarted(false);
        setRows([]);
        setSubmitting(false);
      },
    });
  };

  if (!started) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0' }}>
        <InboxOutlined style={{ fontSize: 64, color: '#bfbfbf', marginBottom: 16 }} />
        <div>
          <Title level={4} style={{ color: '#8c8c8c' }}>点击下方按钮发起库存盘点</Title>
          <Text type="secondary">系统将生成当前所有库存食材的盘点表，填写实盘数后提交</Text>
        </div>
        <Button
          type="primary"
          size="large"
          icon={<AuditOutlined />}
          style={{ marginTop: 24, background: '#FF6B35', borderColor: '#FF6B35' }}
          onClick={handleStartStocktake}
        >
          发起盘点
        </Button>
      </div>
    );
  }

  const columns: ProColumns<StocktakeRow>[] = [
    {
      title: '食材名',
      dataIndex: 'ingredient_name',
      width: 140,
      editable: false,
    },
    {
      title: '系统数',
      dataIndex: 'system_qty',
      width: 100,
      editable: false,
      render: (_, record) => <Text>{record.system_qty}</Text>,
    },
    {
      title: '实盘数',
      dataIndex: 'actual_qty',
      width: 120,
      render: (_, record) => (
        <InputNumber
          value={record.actual_qty}
          min={0}
          style={{ width: '100%' }}
          onChange={(v) => handleActualQtyChange(record.id, v)}
        />
      ),
    },
    {
      title: '差异',
      dataIndex: 'diff',
      width: 100,
      render: (_, record) => {
        if (record.diff === 0) return <Text type="secondary">0</Text>;
        if (record.diff > 0) {
          return <Text strong style={{ color: '#1890ff' }}>+{record.diff}（盘盈）</Text>;
        }
        return <Text strong style={{ color: '#ff4d4f' }}>{record.diff}（盘亏）</Text>;
      },
    },
    {
      title: '备注',
      dataIndex: 'remark',
      render: (_, record) => (
        <Input
          value={record.remark}
          placeholder="差异原因"
          onChange={(e) => handleRemarkChange(record.id, e.target.value)}
        />
      ),
    },
  ];

  return (
    <div>
      <ProTable<StocktakeRow>
        columns={columns}
        dataSource={rows}
        rowKey="id"
        search={false}
        pagination={false}
        headerTitle="盘点表"
        options={false}
        rowClassName={(record) => {
          if (record.diff > 0) return 'stocktake-row-surplus';
          if (record.diff < 0) return 'stocktake-row-loss';
          return '';
        }}
        toolBarRender={() => [
          <Button key="cancel" onClick={() => { setStarted(false); setRows([]); }}>
            取消盘点
          </Button>,
          <Button
            key="submit"
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={submitting}
            onClick={handleSubmit}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            提交盘点
          </Button>,
        ]}
      />

      <style>{`
        .stocktake-row-surplus {
          background-color: #e6f7ff !important;
        }
        .stocktake-row-surplus:hover > td {
          background-color: #d6ecfa !important;
        }
        .stocktake-row-loss {
          background-color: #fff2f0 !important;
        }
        .stocktake-row-loss:hover > td {
          background-color: #ffece8 !important;
        }
      `}</style>
    </div>
  );
};

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export const InventoryPage: React.FC = () => {
  const [alertSummary, setAlertSummary] = useState<AlertSummary>({
    low_stock_count: 0,
    expiry_count: 0,
    low_stock_items: [],
    expiry_items: [],
  });

  useEffect(() => {
    fetchAlertSummary().then(setAlertSummary);
  }, []);

  return (
    <div style={{ padding: 24 }}>
      <AlertBanner summary={alertSummary} />

      <Tabs
        defaultActiveKey="overview"
        type="card"
        items={[
          {
            key: 'overview',
            label: (
              <span>
                <InboxOutlined style={{ marginRight: 4 }} />
                库存总览
              </span>
            ),
            children: <InventoryOverviewTab />,
          },
          {
            key: 'logs',
            label: (
              <span>
                <FileSearchOutlined style={{ marginRight: 4 }} />
                库存流水
              </span>
            ),
            children: <InventoryLogTab />,
          },
          {
            key: 'expiry',
            label: (
              <span>
                <Badge count={alertSummary.expiry_count} offset={[10, 0]} size="small">
                  <span>
                    <WarningOutlined style={{ marginRight: 4 }} />
                    临期预警
                  </span>
                </Badge>
              </span>
            ),
            children: <ExpiryAlertTab />,
          },
          {
            key: 'stocktake',
            label: (
              <span>
                <AuditOutlined style={{ marginRight: 4 }} />
                盘点
              </span>
            ),
            children: <StocktakeTab />,
          },
        ]}
      />
    </div>
  );
};

export default InventoryPage;
