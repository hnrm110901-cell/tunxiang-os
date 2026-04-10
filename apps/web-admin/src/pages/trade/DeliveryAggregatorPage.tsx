/**
 * Y-A5 外卖聚合深度 — 多平台聚合订单管理页
 *
 * 三个 Tab：
 *   1. 聚合订单 — ProTable，美团/饿了么/抖音统一视图
 *   2. 平台状态 — 连接卡片 + 今日订单量 + 成功率
 *   3. 对账管理 — 差异列表 + 手动触发对账
 *
 * 技术栈：React 18 + TypeScript + Ant Design 5.x + ProComponents
 */
import React, { useCallback, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  message,
  Modal,
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
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { Option } = Select;

// ──────────────────────────────────────────────────────────────────────────────
// Design Token（屯象主题）
// ──────────────────────────────────────────────────────────────────────────────

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
    Table: { headerBg: '#F8F7F5' },
  },
};

// ──────────────────────────────────────────────────────────────────────────────
// 常量与类型
// ──────────────────────────────────────────────────────────────────────────────

const TENANT_ID = localStorage.getItem('tenantId') || 'demo-tenant';

const BASE_URL = '/api/v1/trade/aggregator';
const RECONCILE_BASE_URL = '/api/v1/trade/aggregator-reconcile';

const PLATFORM_CONFIG: Record<string, { label: string; color: string }> = {
  meituan: { label: '美团外卖', color: 'orange' },
  eleme: { label: '饿了么', color: 'blue' },
  douyin: { label: '抖音外卖', color: 'red' },
};

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  new: { label: '新单', color: 'processing' },
  accepted: { label: '已接单', color: 'blue' },
  ready: { label: '备餐完成', color: 'cyan' },
  delivering: { label: '配送中', color: 'geekblue' },
  completed: { label: '已完成', color: 'success' },
  cancelled: { label: '已取消', color: 'default' },
};

const DISCREPANCY_TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  local_only: { label: '本地有/平台无', color: 'orange' },
  platform_only: { label: '平台有/本地无', color: 'red' },
  amount_mismatch: { label: '金额不符', color: 'volcano' },
};

interface AggregatorOrder {
  id: string;
  platform: string;
  platform_label: string;
  platform_color: string;
  platform_order_id: string;
  store_id: string;
  status: string;
  total_fen: number;
  items_count: number;
  customer_phone_masked?: string;
  estimated_delivery_at?: string;
  created_at: string;
  updated_at: string;
}

interface PlatformStatus {
  platform: string;
  label: string;
  color: string;
  online: boolean;
  today_order_count: number;
  today_success_rate: number;
}

interface Discrepancy {
  id: string;
  platform: string;
  reconcile_date: string;
  discrepancy_type: string;
  platform_order_id: string;
  local_amount_fen?: number;
  platform_amount_fen?: number;
  discrepancy_amount_fen: number;
  resolved: boolean;
  resolution?: string;
  resolved_by?: string;
  resolved_at?: string;
  created_at: string;
}

// ──────────────────────────────────────────────────────────────────────────────
// API 调用层
// ──────────────────────────────────────────────────────────────────────────────

const headers = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
};

async function fetchPlatformsStatus(): Promise<PlatformStatus[]> {
  const res = await fetch(`${BASE_URL}/platforms/status`, { headers });
  const json = await res.json();
  return json.data?.platforms ?? [];
}

async function fetchMetrics(): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE_URL}/metrics`, { headers });
  const json = await res.json();
  return json.data ?? {};
}

async function runReconcile(
  platform: string,
  date: string,
): Promise<{ task_id: string }> {
  const res = await fetch(`${RECONCILE_BASE_URL}/run`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ platform, date }),
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message ?? '触发对账失败');
  return json.data;
}

async function resolveDiscrepancy(
  id: string,
  resolution: string,
): Promise<void> {
  const res = await fetch(`${RECONCILE_BASE_URL}/discrepancies/${id}/resolve`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ resolution, resolved_by: TENANT_ID }),
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message ?? '处理失败');
}

async function orderAction(
  orderId: string,
  action: 'accept' | 'ready' | 'cancel',
): Promise<void> {
  const res = await fetch(`${BASE_URL}/orders/${orderId}/${action}`, {
    method: 'POST',
    headers,
    body: JSON.stringify({}),
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message ?? '操作失败');
}

// ──────────────────────────────────────────────────────────────────────────────
// Tab 1：聚合订单列表
// ──────────────────────────────────────────────────────────────────────────────

const OrdersTab: React.FC = () => {
  const actionRef = useRef<ActionType>();
  const [detailOrder, setDetailOrder] = useState<AggregatorOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const handleViewDetail = useCallback(async (record: AggregatorOrder) => {
    setDetailLoading(true);
    try {
      const res = await fetch(`${BASE_URL}/orders/${record.id}`, { headers });
      const json = await res.json();
      setDetailOrder(json.data);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleAction = useCallback(
    async (record: AggregatorOrder, action: 'accept' | 'ready' | 'cancel') => {
      const actionLabels = { accept: '接单', ready: '备餐完成', cancel: '取消' };
      Modal.confirm({
        title: `确认${actionLabels[action]}？`,
        content: `订单：${record.platform_order_id}`,
        onOk: async () => {
          try {
            await orderAction(record.id, action);
            message.success(`${actionLabels[action]}成功`);
            actionRef.current?.reload();
          } catch (err: unknown) {
            message.error(err instanceof Error ? err.message : '操作失败');
          }
        },
      });
    },
    [],
  );

  const columns: ProColumns<AggregatorOrder>[] = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 120,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(PLATFORM_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, record) => (
        <Tag color={PLATFORM_CONFIG[record.platform]?.color ?? 'default'}>
          {PLATFORM_CONFIG[record.platform]?.label ?? record.platform}
        </Tag>
      ),
    },
    {
      title: '平台单号',
      dataIndex: 'platform_order_id',
      copyable: true,
      ellipsis: true,
      width: 180,
      search: false,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      width: 120,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, record) => {
        const cfg = STATUS_CONFIG[record.status] ?? { label: record.status, color: 'default' };
        return <Badge status={cfg.color as never} text={cfg.label} />;
      },
    },
    {
      title: '订单金额',
      dataIndex: 'total_fen',
      search: false,
      width: 110,
      render: (_, record) => (
        <Text strong>¥{(record.total_fen / 100).toFixed(2)}</Text>
      ),
    },
    {
      title: '品项数',
      dataIndex: 'items_count',
      search: false,
      width: 80,
    },
    {
      title: '顾客手机',
      dataIndex: 'customer_phone_masked',
      search: false,
      width: 130,
      render: (v) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: '预计送达',
      dataIndex: 'estimated_delivery_at',
      search: false,
      width: 160,
      render: (v) =>
        v ? (
          <Text>{dayjs(v as string).format('MM-DD HH:mm')}</Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '下单时间',
      dataIndex: 'created_at',
      search: false,
      width: 160,
      render: (v) => dayjs(v as string).format('MM-DD HH:mm:ss'),
      sorter: true,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, record) => [
        <a key="detail" onClick={() => handleViewDetail(record)}>
          详情
        </a>,
        record.status === 'new' && (
          <a key="accept" onClick={() => handleAction(record, 'accept')}>
            接单
          </a>
        ),
        record.status === 'accepted' && (
          <a key="ready" onClick={() => handleAction(record, 'ready')}>
            备餐完成
          </a>
        ),
        (record.status === 'new' || record.status === 'accepted') && (
          <a
            key="cancel"
            style={{ color: '#A32D2D' }}
            onClick={() => handleAction(record, 'cancel')}
          >
            取消
          </a>
        ),
      ],
    },
  ];

  return (
    <>
      <ProTable<AggregatorOrder>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query = new URLSearchParams({
            page: String(params.current ?? 1),
            size: String(params.pageSize ?? 20),
            ...(params.platform ? { platform: params.platform } : {}),
            ...(params.status ? { status: params.status } : {}),
          });
          const res = await fetch(`${BASE_URL}/orders?${query}`, { headers });
          const json = await res.json();
          return {
            data: json.data?.items ?? [],
            total: json.data?.total ?? 0,
            success: json.ok,
          };
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <Button
            key="refresh"
            icon={<ReloadOutlined />}
            onClick={() => actionRef.current?.reload()}
          >
            刷新
          </Button>,
        ]}
        scroll={{ x: 1200 }}
      />

      <Drawer
        title="聚合订单详情"
        open={!!detailOrder}
        onClose={() => setDetailOrder(null)}
        width={520}
        loading={detailLoading}
      >
        {detailOrder && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="聚合订单ID">
              <Text copyable>{detailOrder.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="平台">
              <Tag color={PLATFORM_CONFIG[detailOrder.platform]?.color}>
                {PLATFORM_CONFIG[detailOrder.platform]?.label ?? detailOrder.platform}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="平台单号">
              <Text copyable>{detailOrder.platform_order_id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Badge
                status={(STATUS_CONFIG[detailOrder.status]?.color as never) ?? 'default'}
                text={STATUS_CONFIG[detailOrder.status]?.label ?? detailOrder.status}
              />
            </Descriptions.Item>
            <Descriptions.Item label="订单金额">
              <Text strong style={{ color: '#FF6B35', fontSize: 16 }}>
                ¥{(detailOrder.total_fen / 100).toFixed(2)}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="门店">
              {detailOrder.store_id}
            </Descriptions.Item>
            <Descriptions.Item label="顾客手机">
              {detailOrder.customer_phone_masked ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="预计送达">
              {detailOrder.estimated_delivery_at
                ? dayjs(detailOrder.estimated_delivery_at).format('YYYY-MM-DD HH:mm')
                : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="下单时间">
              {dayjs(detailOrder.created_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {dayjs(detailOrder.updated_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </>
  );
};

// ──────────────────────────────────────────────────────────────────────────────
// Tab 2：平台状态
// ──────────────────────────────────────────────────────────────────────────────

const PlatformsStatusTab: React.FC = () => {
  const [platforms, setPlatforms] = useState<PlatformStatus[]>([]);
  const [metrics, setMetrics] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [p, m] = await Promise.all([fetchPlatformsStatus(), fetchMetrics()]);
      setPlatforms(p);
      setMetrics(m);
    } catch {
      message.error('获取平台状态失败');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const globalMetrics = metrics as {
    total_requests?: number;
    success_rate?: number;
    avg_latency_ms?: number;
    p99_latency_ms?: number;
    by_platform?: Record<string, {
      label: string;
      total_requests: number;
      success_rate: number;
      avg_latency_ms: number;
      p99_latency_ms: number;
    }>;
  };

  return (
    <Space direction="vertical" size={24} style={{ width: '100%' }}>
      {/* 全局指标卡 */}
      <Card
        title="全局 Webhook 处理指标"
        extra={
          <Button icon={<ReloadOutlined />} loading={loading} onClick={refresh}>
            刷新
          </Button>
        }
      >
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="请求总量"
              value={globalMetrics.total_requests ?? 0}
              suffix="次"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="成功率"
              value={((globalMetrics.success_rate ?? 1) * 100).toFixed(2)}
              suffix="%"
              valueStyle={{
                color:
                  (globalMetrics.success_rate ?? 1) >= 0.99
                    ? '#0F6E56'
                    : (globalMetrics.success_rate ?? 1) >= 0.95
                      ? '#BA7517'
                      : '#A32D2D',
              }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="平均延迟"
              value={(globalMetrics.avg_latency_ms ?? 0).toFixed(1)}
              suffix="ms"
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="P99 延迟"
              value={(globalMetrics.p99_latency_ms ?? 0).toFixed(1)}
              suffix="ms"
              valueStyle={{
                color: (globalMetrics.p99_latency_ms ?? 0) > 1000 ? '#A32D2D' : undefined,
              }}
            />
          </Col>
        </Row>
      </Card>

      {/* 平台连接卡片 */}
      <Row gutter={16}>
        {platforms.length === 0
          ? ['meituan', 'eleme', 'douyin'].map((pid) => (
              <Col span={8} key={pid}>
                <Card loading={loading}>
                  <Statistic title={PLATFORM_CONFIG[pid].label} value="—" />
                </Card>
              </Col>
            ))
          : platforms.map((p) => {
              const byPlatform = globalMetrics.by_platform?.[p.platform];
              const successRatePct = (p.today_success_rate * 100).toFixed(1);
              const isOnline = p.online;

              return (
                <Col span={8} key={p.platform}>
                  <Card
                    title={
                      <Space>
                        <Badge
                          status={isOnline ? 'success' : 'error'}
                          text={
                            <Text strong>
                              {PLATFORM_CONFIG[p.platform]?.label ?? p.platform}
                            </Text>
                          }
                        />
                        <Tag color={isOnline ? 'success' : 'error'}>
                          {isOnline ? '在线' : '离线'}
                        </Tag>
                      </Space>
                    }
                    bordered
                    style={{
                      borderTop: `3px solid ${
                        p.platform === 'meituan'
                          ? '#FF6B35'
                          : p.platform === 'eleme'
                            ? '#185FA5'
                            : '#A32D2D'
                      }`,
                    }}
                  >
                    <Row gutter={8}>
                      <Col span={12}>
                        <Statistic
                          title="今日订单"
                          value={p.today_order_count}
                          suffix="单"
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title="成功率"
                          value={successRatePct}
                          suffix="%"
                          valueStyle={{
                            color:
                              p.today_success_rate >= 0.99
                                ? '#0F6E56'
                                : p.today_success_rate >= 0.95
                                  ? '#BA7517'
                                  : '#A32D2D',
                          }}
                        />
                      </Col>
                    </Row>
                    {byPlatform && (
                      <Row gutter={8} style={{ marginTop: 12 }}>
                        <Col span={12}>
                          <Statistic
                            title="Webhook 请求"
                            value={byPlatform.total_requests}
                            suffix="次"
                            valueStyle={{ fontSize: 14 }}
                          />
                        </Col>
                        <Col span={12}>
                          <Statistic
                            title="平均延迟"
                            value={byPlatform.avg_latency_ms.toFixed(1)}
                            suffix="ms"
                            valueStyle={{ fontSize: 14 }}
                          />
                        </Col>
                      </Row>
                    )}
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        数据来源：mock，生产接入平台心跳 API
                      </Text>
                    </div>
                  </Card>
                </Col>
              );
            })}
      </Row>

      {/* 无数据提示 */}
      {!loading && platforms.length === 0 && (
        <Alert
          type="info"
          message="暂无平台 Webhook 数据"
          description="先通过 POST /api/v1/trade/aggregator/webhook/{platform} 推送测试订单，平台状态将自动更新。"
        />
      )}
    </Space>
  );
};

// ──────────────────────────────────────────────────────────────────────────────
// Tab 3：对账管理
// ──────────────────────────────────────────────────────────────────────────────

const ReconcileTab: React.FC = () => {
  const actionRef = useRef<ActionType>();
  const [runLoading, setRunLoading] = useState(false);
  const [runForm] = Form.useForm();
  const [resolveModalOpen, setResolveModalOpen] = useState(false);
  const [resolveTarget, setResolveTarget] = useState<Discrepancy | null>(null);
  const [resolveForm] = Form.useForm();
  const [resolveLoading, setResolveLoading] = useState(false);

  const handleRunReconcile = useCallback(async () => {
    try {
      const values = await runForm.validateFields();
      setRunLoading(true);
      const result = await runReconcile(
        values.platform,
        dayjs(values.date).format('YYYY-MM-DD'),
      );
      message.success(`对账任务已提交，Task ID：${result.task_id}`);
      actionRef.current?.reload();
    } catch (err: unknown) {
      if (err instanceof Error) {
        message.error(err.message);
      }
    } finally {
      setRunLoading(false);
    }
  }, [runForm]);

  const handleResolve = useCallback(async () => {
    if (!resolveTarget) return;
    try {
      const values = await resolveForm.validateFields();
      setResolveLoading(true);
      await resolveDiscrepancy(resolveTarget.id, values.resolution);
      message.success('差异已标记为处理完成');
      setResolveModalOpen(false);
      resolveForm.resetFields();
      actionRef.current?.reload();
    } catch (err: unknown) {
      if (err instanceof Error) {
        message.error(err.message);
      }
    } finally {
      setResolveLoading(false);
    }
  }, [resolveTarget, resolveForm]);

  const columns: ProColumns<Discrepancy>[] = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 120,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(PLATFORM_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, record) => (
        <Tag color={PLATFORM_CONFIG[record.platform]?.color ?? 'default'}>
          {PLATFORM_CONFIG[record.platform]?.label ?? record.platform}
        </Tag>
      ),
    },
    {
      title: '对账日期',
      dataIndex: 'reconcile_date',
      search: false,
      width: 120,
    },
    {
      title: '差异类型',
      dataIndex: 'discrepancy_type',
      width: 140,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(DISCREPANCY_TYPE_CONFIG).map(([k, v]) => [
          k,
          { text: v.label },
        ]),
      ),
      render: (_, record) => {
        const cfg = DISCREPANCY_TYPE_CONFIG[record.discrepancy_type] ?? {
          label: record.discrepancy_type,
          color: 'default',
        };
        return (
          <Tag color={cfg.color} icon={<WarningOutlined />}>
            {cfg.label}
          </Tag>
        );
      },
    },
    {
      title: '平台单号',
      dataIndex: 'platform_order_id',
      copyable: true,
      ellipsis: true,
      width: 180,
      search: false,
    },
    {
      title: '本地金额',
      dataIndex: 'local_amount_fen',
      search: false,
      width: 110,
      render: (_, record) =>
        record.local_amount_fen != null ? (
          <Text>¥{(record.local_amount_fen / 100).toFixed(2)}</Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '平台金额',
      dataIndex: 'platform_amount_fen',
      search: false,
      width: 110,
      render: (_, record) =>
        record.platform_amount_fen != null ? (
          <Text>¥{(record.platform_amount_fen / 100).toFixed(2)}</Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '差异金额',
      dataIndex: 'discrepancy_amount_fen',
      search: false,
      width: 120,
      render: (_, record) => (
        <Text strong style={{ color: '#A32D2D' }}>
          ¥{(record.discrepancy_amount_fen / 100).toFixed(2)}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'resolved',
      width: 100,
      valueType: 'select',
      valueEnum: {
        true: { text: '已处理', status: 'Success' },
        false: { text: '待处理', status: 'Error' },
      },
      render: (_, record) =>
        record.resolved ? (
          <Tag icon={<CheckCircleOutlined />} color="success">
            已处理
          </Tag>
        ) : (
          <Tag icon={<CloseCircleOutlined />} color="error">
            待处理
          </Tag>
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, record) => [
        !record.resolved && (
          <Tooltip key="resolve" title="标记为已处理">
            <a
              onClick={() => {
                setResolveTarget(record);
                setResolveModalOpen(true);
              }}
            >
              处理
            </a>
          </Tooltip>
        ),
      ],
    },
  ];

  return (
    <>
      {/* 触发对账区域 */}
      <Card
        title={
          <Space>
            <ExclamationCircleOutlined style={{ color: '#BA7517' }} />
            手动触发对账
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Form form={runForm} layout="inline">
          <Form.Item
            name="platform"
            label="平台"
            rules={[{ required: true, message: '请选择平台' }]}
          >
            <Select style={{ width: 140 }} placeholder="选择平台">
              {Object.entries(PLATFORM_CONFIG).map(([k, v]) => (
                <Option key={k} value={k}>
                  {v.label}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="date"
            label="对账日期"
            rules={[{ required: true, message: '请选择日期' }]}
            initialValue={dayjs()}
          >
            <DatePicker
              format="YYYY-MM-DD"
              disabledDate={(d) => d.isAfter(dayjs())}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              loading={runLoading}
              onClick={handleRunReconcile}
              icon={<ReloadOutlined />}
            >
              开始对账
            </Button>
          </Form.Item>
        </Form>
        <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: 'block' }}>
          对账任务在后台异步执行，完成后差异单自动出现在下方列表。
        </Text>
      </Card>

      {/* 差异单列表 */}
      <ProTable<Discrepancy>
        actionRef={actionRef}
        headerTitle="差异单列表"
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query = new URLSearchParams({
            page: String(params.current ?? 1),
            size: String(params.pageSize ?? 20),
            ...(params.platform ? { platform: params.platform } : {}),
            ...(params.discrepancy_type
              ? { discrepancy_type: params.discrepancy_type }
              : {}),
            ...(params.resolved !== undefined
              ? { resolved: String(params.resolved) }
              : {}),
          });
          const res = await fetch(
            `${RECONCILE_BASE_URL}/discrepancies?${query}`,
            { headers },
          );
          const json = await res.json();
          return {
            data: json.data?.items ?? [],
            total: json.data?.total ?? 0,
            success: json.ok,
          };
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <Button
            key="refresh"
            icon={<ReloadOutlined />}
            onClick={() => actionRef.current?.reload()}
          >
            刷新
          </Button>,
        ]}
        scroll={{ x: 1100 }}
        rowClassName={(record) =>
          record.resolved ? '' : 'ant-table-row-highlight'
        }
      />

      {/* 处理差异弹窗 */}
      <Modal
        title={
          <Space>
            <WarningOutlined style={{ color: '#BA7517' }} />
            处理差异单
          </Space>
        }
        open={resolveModalOpen}
        onOk={handleResolve}
        onCancel={() => {
          setResolveModalOpen(false);
          resolveForm.resetFields();
        }}
        confirmLoading={resolveLoading}
        okText="确认处理"
        cancelText="取消"
      >
        {resolveTarget && (
          <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="差异类型">
              <Tag
                color={
                  DISCREPANCY_TYPE_CONFIG[resolveTarget.discrepancy_type]
                    ?.color ?? 'default'
                }
              >
                {DISCREPANCY_TYPE_CONFIG[resolveTarget.discrepancy_type]
                  ?.label ?? resolveTarget.discrepancy_type}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="平台单号">
              {resolveTarget.platform_order_id}
            </Descriptions.Item>
            <Descriptions.Item label="差异金额">
              <Text strong style={{ color: '#A32D2D' }}>
                ¥{(resolveTarget.discrepancy_amount_fen / 100).toFixed(2)}
              </Text>
            </Descriptions.Item>
          </Descriptions>
        )}
        <Form form={resolveForm} layout="vertical">
          <Form.Item
            name="resolution"
            label="处理说明"
            rules={[
              { required: true, message: '请填写处理说明' },
              { min: 5, message: '处理说明至少5个字' },
            ]}
          >
            <Form.Item name="resolution" noStyle>
              <textarea
                style={{
                  width: '100%',
                  minHeight: 80,
                  padding: 8,
                  border: '1px solid #E8E6E1',
                  borderRadius: 6,
                  fontSize: 14,
                  resize: 'vertical',
                }}
                placeholder="请填写处理说明，如：已与平台核实，确认为系统延迟导致的重复推送..."
              />
            </Form.Item>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
};

// ──────────────────────────────────────────────────────────────────────────────
// 主页面
// ──────────────────────────────────────────────────────────────────────────────

const DeliveryAggregatorPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState('orders');

  const tabItems = [
    {
      key: 'orders',
      label: (
        <Space>
          <span>聚合订单</span>
        </Space>
      ),
      children: <OrdersTab />,
    },
    {
      key: 'platforms',
      label: (
        <Space>
          <span>平台状态</span>
        </Space>
      ),
      children: <PlatformsStatusTab />,
    },
    {
      key: 'reconcile',
      label: (
        <Space>
          <span>对账管理</span>
        </Space>
      ),
      children: <ReconcileTab />,
    },
  ];

  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ padding: 24, minHeight: '100vh', background: '#F8F7F5' }}>
        {/* 页面标题 */}
        <div style={{ marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
            外卖聚合管理
          </Title>
          <Text type="secondary">
            美团外卖 / 饿了么 / 抖音外卖 — 聚合订单落库 · 异常补偿 · 对账核销
          </Text>
        </div>

        <Card bodyStyle={{ padding: 0 }}>
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={tabItems}
            style={{ padding: '0 16px' }}
            tabBarStyle={{ marginBottom: 0 }}
          />
        </Card>
      </div>
    </ConfigProvider>
  );
};

export default DeliveryAggregatorPage;
