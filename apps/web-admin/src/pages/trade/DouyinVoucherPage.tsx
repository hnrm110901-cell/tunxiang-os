/**
 * 抖音团购管理页面 — Y-I2
 *
 * Tab 1: 核销记录
 * Tab 2: 对账报表
 * Tab 3: 重试队列
 */
import { useState, useRef } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Form,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  RedoOutlined,
  ReloadOutlined,
  ShopOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import { getToken } from '../../api/client';

const { RangePicker } = DatePicker;
const { Title, Text } = Typography;

const TENANT_ID = localStorage.getItem('tenantId') || 'demo-tenant';

function authHeader() {
  return {
    'X-Tenant-ID': TENANT_ID,
    Authorization: `Bearer ${getToken() ?? ''}`,
    'Content-Type': 'application/json',
  };
}

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface VerifyRecord {
  voucher_code: string;
  order_id: string;
  product_name: string;
  amount_fen: number;
  status: 'success' | 'failed' | 'retrying';
  store_id: string;
  operator_id: string;
  verify_time: string;
  error_msg?: string;
  retry_task_id?: string;
}

interface RetryTask {
  task_id: string;
  voucher_code: string;
  store_id: string;
  operator_id: string;
  error: string;
  retry_count: number;
  last_retry_at: string | null;
  created_at: string;
  status: 'pending' | 'retrying' | 'failed';
}

interface ReconciliationReport {
  date_from: string;
  date_to: string;
  store_id: string | null;
  local_count: number;
  platform_count: number;
  matched: number;
  unmatched: number;
  discrepancy_amount_fen: number;
  unmatched_records: Array<{
    voucher_code: string;
    local_order_id: string | null;
    platform_status: string;
    amount_fen: number;
    issue: string;
  }>;
}

// ─── Mock 核销记录（前端展示用）──────────────────────────────────────────────

const MOCK_VERIFY_RECORDS: VerifyRecord[] = [
  {
    voucher_code: 'DY20260406ABC001',
    order_id: 'dy-order-abc001',
    product_name: '双人套餐',
    amount_fen: 15800,
    status: 'success',
    store_id: 'store-001',
    operator_id: 'op-001',
    verify_time: '2026-04-06T12:00:00+08:00',
  },
  {
    voucher_code: 'DY20260406ABC002',
    order_id: 'dy-order-abc002',
    product_name: '四人家庭套餐',
    amount_fen: 28800,
    status: 'success',
    store_id: 'store-001',
    operator_id: 'op-001',
    verify_time: '2026-04-06T13:30:00+08:00',
  },
  {
    voucher_code: 'DY_FAIL_XYZ003',
    order_id: '',
    product_name: '双人套餐',
    amount_fen: 15800,
    status: 'failed',
    store_id: 'store-002',
    operator_id: 'op-002',
    verify_time: '2026-04-06T14:00:00+08:00',
    error_msg: '平台暂时不可用',
    retry_task_id: 'retry-abc123',
  },
  {
    voucher_code: 'DY20260406ABC004',
    order_id: 'dy-order-abc004',
    product_name: '双人套餐',
    amount_fen: 15800,
    status: 'retrying',
    store_id: 'store-002',
    operator_id: 'op-002',
    verify_time: '2026-04-06T14:10:00+08:00',
    error_msg: '超时重试中',
    retry_task_id: 'retry-def456',
  },
];

// ─── Tab 1: 核销记录 ──────────────────────────────────────────────────────────

const statusColorMap: Record<string, string> = {
  success: 'success',
  failed: 'error',
  retrying: 'warning',
};

const statusLabelMap: Record<string, string> = {
  success: '核销成功',
  failed: '核销失败',
  retrying: '重试中',
};

function VerifyRecordsTab() {
  const actionRef = useRef<ActionType>();

  const columns: ProColumns<VerifyRecord>[] = [
    {
      title: '核销时间',
      dataIndex: 'verify_time',
      valueType: 'dateTime',
      search: false,
      render: (_, r) => dayjs(r.verify_time).format('YYYY-MM-DD HH:mm:ss'),
      width: 160,
    },
    {
      title: '券码',
      dataIndex: 'voucher_code',
      ellipsis: true,
      copyable: true,
      width: 180,
    },
    {
      title: '产品名',
      dataIndex: 'product_name',
      search: false,
    },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      search: false,
      render: (_, r) =>
        r.amount_fen > 0 ? (
          <Text strong>¥{(r.amount_fen / 100).toFixed(2)}</Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: {
        success: { text: '核销成功' },
        failed: { text: '核销失败' },
        retrying: { text: '重试中' },
      },
      render: (_, r) => (
        <Tag color={statusColorMap[r.status] ?? 'default'}>
          {statusLabelMap[r.status] ?? r.status}
        </Tag>
      ),
      width: 100,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      search: false,
      width: 120,
    },
    {
      title: '操作员',
      dataIndex: 'operator_id',
      search: false,
      width: 100,
    },
    {
      title: '失败原因',
      dataIndex: 'error_msg',
      search: false,
      render: (_, r) =>
        r.error_msg ? (
          <Tooltip title={r.error_msg}>
            <Text type="danger" ellipsis style={{ maxWidth: 120 }}>
              {r.error_msg}
            </Text>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, r) =>
        r.retry_task_id
          ? [
              <a
                key="retry"
                onClick={() => message.info(`已触发重试：${r.retry_task_id}`)}
              >
                重试
              </a>,
            ]
          : [],
    },
  ];

  return (
    <ProTable<VerifyRecord>
      actionRef={actionRef}
      columns={columns}
      rowKey="voucher_code"
      request={async (params) => {
        // 生产环境接入后端 API，此处使用 mock 数据
        const items = MOCK_VERIFY_RECORDS.filter((r) => {
          if (params.status && r.status !== params.status) return false;
          if (params.voucher_code && !r.voucher_code.includes(params.voucher_code)) return false;
          return true;
        });
        return { data: items, total: items.length, success: true };
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
      summary={(data) => {
        const totalAmount = data.reduce((s, r) => s + (r.amount_fen || 0), 0);
        const successCount = data.filter((r) => r.status === 'success').length;
        return (
          <Table.Summary.Row>
            <Table.Summary.Cell index={0} colSpan={3}>
              <Text strong>本页合计</Text>
            </Table.Summary.Cell>
            <Table.Summary.Cell index={3}>
              <Text strong type="success">
                ¥{(totalAmount / 100).toFixed(2)}
              </Text>
            </Table.Summary.Cell>
            <Table.Summary.Cell index={4}>
              <Text type="secondary">
                成功 {successCount}/{data.length}
              </Text>
            </Table.Summary.Cell>
            <Table.Summary.Cell index={5} colSpan={4} />
          </Table.Summary.Row>
        );
      }}
    />
  );
}

// ─── Tab 2: 对账报表 ──────────────────────────────────────────────────────────

function ReconciliationTab() {
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<ReconciliationReport | null>(null);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(7, 'day'),
    dayjs(),
  ]);
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [expandUnmatched, setExpandUnmatched] = useState(false);

  const fetchReport = async () => {
    if (!dateRange) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({
        date_from: dateRange[0].format('YYYY-MM-DD'),
        date_to: dateRange[1].format('YYYY-MM-DD'),
      });
      if (storeId) params.append('store_id', storeId);

      const res = await fetch(
        `/api/v1/trade/douyin-voucher/reconciliation?${params.toString()}`,
        { headers: authHeader() },
      );
      const json = await res.json();
      if (json.ok) {
        setReport(json.data);
      } else {
        message.error(json.error?.message ?? '查询失败');
      }
    } catch {
      message.error('网络请求失败');
    } finally {
      setLoading(false);
    }
  };

  const unmatchedColumns = [
    { title: '券码', dataIndex: 'voucher_code', ellipsis: true, copyable: true },
    { title: '本地订单ID', dataIndex: 'local_order_id', render: (v: string | null) => v ?? '—' },
    { title: '平台状态', dataIndex: 'platform_status' },
    {
      title: '金额',
      dataIndex: 'amount_fen',
      render: (v: number) => `¥${(v / 100).toFixed(2)}`,
    },
    {
      title: '异常描述',
      dataIndex: 'issue',
      render: (v: string) => <Text type="danger">{v}</Text>,
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {/* 筛选条件 */}
      <Card size="small">
        <Form layout="inline">
          <Form.Item label="日期范围">
            <RangePicker
              value={dateRange as [dayjs.Dayjs, dayjs.Dayjs]}
              onChange={(v) => {
                if (v && v[0] && v[1]) setDateRange([v[0], v[1]]);
              }}
            />
          </Form.Item>
          <Form.Item label="门店">
            <Select
              allowClear
              placeholder="全部门店"
              style={{ width: 150 }}
              value={storeId}
              onChange={setStoreId}
              options={[
                { value: 'store-001', label: '芙蓉旗舰店' },
                { value: 'store-002', label: '天心广场店' },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" loading={loading} onClick={fetchReport}>
              生成报表
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* 汇总指标 */}
      {report && (
        <>
          <Row gutter={16}>
            <Col span={6}>
              <Card>
                <Statistic title="本地记录数" value={report.local_count} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="平台记录数" value={report.platform_count} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="匹配数"
                  value={report.matched}
                  valueStyle={{ color: '#0F6E56' }}
                  prefix={<CheckCircleOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="差异数"
                  value={report.unmatched}
                  valueStyle={{ color: report.unmatched > 0 ? '#A32D2D' : '#0F6E56' }}
                  prefix={report.unmatched > 0 ? <CloseCircleOutlined /> : <CheckCircleOutlined />}
                  suffix={
                    report.unmatched > 0 ? (
                      <Text type="danger" style={{ fontSize: 12 }}>
                        {' '}
                        差异 ¥{(report.discrepancy_amount_fen / 100).toFixed(2)}
                      </Text>
                    ) : null
                  }
                />
              </Card>
            </Col>
          </Row>

          {report.unmatched > 0 && (
            <Card
              title={
                <Space>
                  <ExclamationCircleOutlined style={{ color: '#BA7517' }} />
                  <span>差异记录明细</span>
                  <Badge count={report.unmatched} color="#BA7517" />
                </Space>
              }
              extra={
                <Button
                  size="small"
                  onClick={() => setExpandUnmatched(!expandUnmatched)}
                >
                  {expandUnmatched ? '收起' : '展开'}
                </Button>
              }
            >
              {expandUnmatched && (
                <Table
                  size="small"
                  rowKey="voucher_code"
                  columns={unmatchedColumns}
                  dataSource={report.unmatched_records}
                  pagination={false}
                />
              )}
            </Card>
          )}

          {report.unmatched === 0 && (
            <Alert
              type="success"
              message="对账无差异"
              description={`本地记录与抖音平台记录完全匹配（${report.matched} 条）`}
              showIcon
            />
          )}
        </>
      )}

      {!report && !loading && (
        <Card>
          <div style={{ textAlign: 'center', padding: 40, color: '#B4B2A9' }}>
            请选择日期范围并点击"生成报表"
          </div>
        </Card>
      )}
    </Space>
  );
}

// ─── Tab 3: 重试队列 ──────────────────────────────────────────────────────────

function RetryQueueTab() {
  const [tasks, setTasks] = useState<RetryTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [autoRetrying, setAutoRetrying] = useState(false);

  const fetchQueue = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/trade/douyin-voucher/retry-queue', {
        headers: authHeader(),
      });
      const json = await res.json();
      if (json.ok) setTasks(json.data.items);
    } catch {
      message.error('获取重试队列失败');
    } finally {
      setLoading(false);
    }
  };

  const handleManualRetry = async (taskId: string) => {
    try {
      const res = await fetch(
        `/api/v1/trade/douyin-voucher/retry-queue/${taskId}/retry`,
        { method: 'POST', headers: authHeader() },
      );
      const json = await res.json();
      if (json.ok) {
        message.success('重试成功，券已核销');
        setTasks((prev) => prev.filter((t) => t.task_id !== taskId));
      } else {
        message.warning(json.data?.error ?? '重试失败');
        fetchQueue();
      }
    } catch {
      message.error('重试请求失败');
    }
  };

  const handleAutoRetry = async () => {
    setAutoRetrying(true);
    try {
      const res = await fetch(
        '/api/v1/trade/douyin-voucher/retry-queue/auto-retry',
        { method: 'POST', headers: authHeader() },
      );
      const json = await res.json();
      if (json.ok) {
        message.success(`批量重试已触发，共 ${json.data.pending_count} 条`);
        setTimeout(fetchQueue, 1500);
      }
    } catch {
      message.error('批量重试请求失败');
    } finally {
      setAutoRetrying(false);
    }
  };

  const columns = [
    {
      title: '券码',
      dataIndex: 'voucher_code',
      ellipsis: true,
      width: 180,
    },
    {
      title: '失败原因',
      dataIndex: 'error',
      render: (v: string) => <Text type="danger">{v}</Text>,
    },
    {
      title: '重试次数',
      dataIndex: 'retry_count',
      width: 90,
      render: (v: number) => (
        <Tag color={v >= 3 ? 'red' : v >= 2 ? 'orange' : 'default'}>
          {v}/3
        </Tag>
      ),
    },
    {
      title: '最后重试时间',
      dataIndex: 'last_retry_at',
      width: 160,
      render: (v: string | null) =>
        v ? dayjs(v).format('MM-DD HH:mm:ss') : '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const cfg: Record<string, { color: string; label: string }> = {
          pending: { color: 'blue', label: '待重试' },
          retrying: { color: 'orange', label: '重试中' },
          failed: { color: 'red', label: '已放弃' },
        };
        const c = cfg[v] ?? { color: 'default', label: v };
        return <Tag color={c.color}>{c.label}</Tag>;
      },
    },
    {
      title: '操作',
      width: 100,
      render: (_: unknown, r: RetryTask) =>
        r.status !== 'failed' ? (
          <Button
            size="small"
            icon={<RedoOutlined />}
            onClick={() => handleManualRetry(r.task_id)}
          >
            重试
          </Button>
        ) : (
          <Tooltip title="已超过最大重试次数，需人工处理">
            <Tag color="red">需人工</Tag>
          </Tooltip>
        ),
    },
  ];

  const pendingCount = tasks.filter((t) => t.status === 'pending').length;
  const failedCount = tasks.filter((t) => t.status === 'failed').length;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Row gutter={16} align="middle">
        <Col>
          <Space>
            <Badge count={pendingCount} color="#FF6B35">
              <Tag>待重试</Tag>
            </Badge>
            <Badge count={failedCount} color="#A32D2D">
              <Tag>已放弃</Tag>
            </Badge>
          </Space>
        </Col>
        <Col flex="auto" />
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchQueue} loading={loading}>
              刷新
            </Button>
            <Button
              type="primary"
              danger={pendingCount === 0}
              icon={<SyncOutlined />}
              loading={autoRetrying}
              disabled={pendingCount === 0}
              onClick={handleAutoRetry}
            >
              一键批量重试（{pendingCount}）
            </Button>
          </Space>
        </Col>
      </Row>

      <Table<RetryTask>
        rowKey="task_id"
        columns={columns}
        dataSource={tasks}
        loading={loading}
        pagination={{ pageSize: 20 }}
        locale={{ emptyText: '暂无失败任务' }}
      />
    </Space>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function DouyinVoucherPage() {
  const [activeTab, setActiveTab] = useState('records');

  const tabItems = [
    {
      key: 'records',
      label: (
        <Space>
          <CheckCircleOutlined />
          核销记录
        </Space>
      ),
      children: (
        <div style={{ paddingTop: 16 }}>
          <VerifyRecordsTab />
        </div>
      ),
    },
    {
      key: 'reconciliation',
      label: (
        <Space>
          <ExclamationCircleOutlined />
          对账报表
        </Space>
      ),
      children: (
        <div style={{ paddingTop: 16 }}>
          <ReconciliationTab />
        </div>
      ),
    },
    {
      key: 'retry',
      label: (
        <Space>
          <RedoOutlined />
          重试队列
        </Space>
      ),
      children: (
        <div style={{ paddingTop: 16 }}>
          <RetryQueueTab />
        </div>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>
          <ShopOutlined style={{ marginRight: 8, color: '#FF6B35' }} />
          抖音团购管理
        </Title>
        <Text type="secondary">
          管理抖音团购券核销、对账差异分析和失败重试 · Y-I2
        </Text>
      </div>

      <Divider style={{ margin: '12px 0 0 0' }} />

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        destroyInactiveTabPane={false}
      />
    </div>
  );
}
