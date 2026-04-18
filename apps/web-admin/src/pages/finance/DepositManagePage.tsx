/**
 * 押金管理页面 — Banquet Deposit Management
 * 路由: /finance/deposits
 *
 * 覆盖宴会定金全流程：收取、抵扣、退还、统计
 * API: POST   /api/v1/banquet/deposits
 *      GET    /api/v1/banquet/deposits/{session_id}
 *      POST   /api/v1/banquet/deposits/{session_id}/apply
 *      POST   /api/v1/banquet/deposits/{session_id}/refund
 *
 * 兼容原有门店通用押金：
 *      GET    /api/v1/deposits/store/{store_id}
 *      POST   /api/v1/deposits/{id}/refund
 *      POST   /api/v1/deposits/{id}/apply
 *      GET    /api/v1/deposits/report/ledger
 *      GET    /api/v1/deposits/report/aging
 *
 * 技术栈: Ant Design 5.x + ProComponents（Admin终端规范）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  DollarOutlined,
  ExclamationCircleOutlined,
  PlusOutlined,
  PrinterOutlined,
  ReloadOutlined,
  SwapOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormRadio,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import {
  type DepositRecord,
  type DepositStatus,
  listDepositsByStore,
  refundDeposit,
  applyDeposit,
  collectDeposit,
  getDepositLedger,
  getDepositAging,
  getDepositShiftSummary,
} from '../../api/depositApi';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 常量 ────────────────────────────────────────────────────────────────────

const TENANT_ID = localStorage.getItem('tenantId') ?? 'demo-tenant';
const OPERATOR_ID = localStorage.getItem('operatorId') ?? 'demo-operator';

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number): string => (fen / 100).toFixed(2);
const yuan2fen = (yuan: number): number => Math.round(yuan * 100);

// ─── 状态配置 ────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  collected: '待结算',
  partially_applied: '部分抵扣',
  fully_applied: '已抵扣',
  refunded: '已退还',
  converted: '已转收入',
  written_off: '已核销',
  active: '有效',
  applied: '已抵扣',
};

const STATUS_COLOR: Record<string, string> = {
  collected: 'blue',
  partially_applied: 'gold',
  fully_applied: 'green',
  refunded: 'default',
  converted: 'purple',
  written_off: 'default',
  active: 'blue',
  applied: 'green',
};

const PAYMENT_METHOD_LABEL: Record<string, string> = {
  cash: '现金',
  wechat: '微信',
  alipay: '支付宝',
  card: '银行卡',
  bank_transfer: '银行转账',
};

// ─── 宴会场次定金记录类型 ──────────────────────────────────────────────────────

interface BanquetDepositRecord {
  id: string;
  session_id: string;
  banquet_name?: string;
  contact_name?: string;
  amount_fen: number;
  balance_fen: number;
  payment_method: string;
  status: string;
  collected_at: string;
  applied_at?: string | null;
  notes?: string | null;
}

interface BanquetDepositSummary {
  session_id: string;
  contact_name: string;
  session_status: string;
  order_total_fen: number;
  total_collected_fen: number;
  total_balance_fen: number;
  remaining_payable_fen: number;
  records: BanquetDepositRecord[];
}

interface BanquetSession {
  id: string;
  contact_name: string;
  guest_count: number;
  status: string;
  tables?: string;
  event_date?: string;
}

interface StoreOption {
  value: string;
  label: string;
}

// ─── 统计卡片组件 ──────────────────────────────────────────────────────────────

interface StatCardProps {
  title: string;
  value: string | number;
  prefix?: string;
  suffix?: string;
  valueColor?: string;
  icon?: React.ReactNode;
  extra?: React.ReactNode;
  warning?: boolean;
}

function StatCard({ title, value, prefix, suffix, valueColor, icon, extra, warning }: StatCardProps) {
  return (
    <Card
      styles={{ body: { padding: '20px 24px' } }}
      style={{
        borderRadius: 8,
        border: warning ? '1px solid #A32D2D' : undefined,
        background: warning ? '#FFF5F5' : undefined,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Statistic
          title={<span style={{ color: '#5F5E5A', fontSize: 13 }}>{title}</span>}
          value={value}
          prefix={prefix}
          suffix={suffix}
          valueStyle={{
            color: valueColor ?? '#2C2C2A',
            fontWeight: 700,
            fontSize: 24,
          }}
        />
        {icon && (
          <div style={{
            width: 44,
            height: 44,
            borderRadius: 8,
            background: warning ? '#A32D2D' : '#FFF3ED',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: warning ? '#fff' : '#FF6B35',
            fontSize: 20,
          }}>
            {icon}
          </div>
        )}
      </div>
      {extra && <div style={{ marginTop: 8 }}>{extra}</div>}
    </Card>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function DepositManagePage() {
  const actionRef = useRef<ActionType>();

  // 筛选状态
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const [stores, setStores] = useState<StoreOption[]>([]);

  // 统计数据
  const [todayCount, setTodayCount] = useState(0);
  const [todayAmountFen, setTodayAmountFen] = useState(0);
  const [monthTotalFen, setMonthTotalFen] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [expiringCount, setExpiringCount] = useState(0);
  const [statsLoading, setStatsLoading] = useState(false);

  // 收取押金弹窗
  const [collectForm] = Form.useForm();
  const [collectVisible, setCollectVisible] = useState(false);
  const [collectLoading, setCollectLoading] = useState(false);
  const [sessions, setSessions] = useState<BanquetSession[]>([]);

  // 抵扣弹窗
  const [applyVisible, setApplyVisible] = useState(false);
  const [applyTarget, setApplyTarget] = useState<DepositRecord | null>(null);
  const [applyForm] = Form.useForm();
  const [applyLoading, setApplyLoading] = useState(false);

  // 退还弹窗
  const [refundVisible, setRefundVisible] = useState(false);
  const [refundTarget, setRefundTarget] = useState<DepositRecord | null>(null);
  const [refundForm] = Form.useForm();
  const [refundLoading, setRefundLoading] = useState(false);

  // 宴会场次定金弹窗（挂台/转押）
  const [banquetDepositVisible, setBanquetDepositVisible] = useState(false);
  const [banquetSummary, setBanquetSummary] = useState<BanquetDepositSummary | null>(null);
  const [banquetDepositLoading, setBanquetDepositLoading] = useState(false);

  // ─── 加载门店列表 ──────────────────────────────────────────────────────────

  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((data) => {
        const opts = (data.items ?? []).map((s) => ({ value: s.id, label: s.name }));
        setStores(opts);
        if (opts.length > 0 && !storeId) {
          setStoreId(opts[0].value);
        }
      })
      .catch(() => setStores([]));
  }, []);

  // ─── 加载统计数据 ──────────────────────────────────────────────────────────

  const loadStats = useCallback(async (sid: string) => {
    setStatsLoading(true);
    try {
      const today = dayjs().format('YYYY-MM-DD');
      const monthStart = dayjs().startOf('month').format('YYYY-MM-DD');
      const monthEnd = dayjs().format('YYYY-MM-DD');

      const [todayLedger, monthLedger, aging] = await Promise.all([
        getDepositLedger(sid, today, today).catch(() => null),
        getDepositLedger(sid, monthStart, monthEnd).catch(() => null),
        getDepositAging(sid).catch(() => null),
      ]);

      if (todayLedger) {
        setTodayCount(todayLedger.total_count);
        setTodayAmountFen(todayLedger.total_collected_fen);
      }
      if (monthLedger) {
        setMonthTotalFen(monthLedger.total_collected_fen);
        setPendingCount(
          monthLedger.total_count -
          Math.floor(monthLedger.total_refunded_fen / (monthLedger.total_collected_fen || 1) * monthLedger.total_count)
        );
      }
      if (aging) {
        setExpiringCount(aging.aging['31_90_days'].count + aging.aging['over_90_days'].count);
      }
    } catch {
      // ignore stats errors
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (storeId) void loadStats(storeId);
  }, [storeId, loadStats]);

  // ─── 加载宴会场次列表 ──────────────────────────────────────────────────────

  const loadSessions = useCallback(async () => {
    try {
      const data = await txFetchData<{ items: BanquetSession[] }>(
        '/api/v1/banquets/sessions?status=pending,confirmed&size=100'
      );
      setSessions(data.items ?? []);
    } catch {
      setSessions([]);
    }
  }, []);

  // ─── 收取押金提交 ──────────────────────────────────────────────────────────

  const handleCollectSubmit = async () => {
    try {
      const values = await collectForm.validateFields();
      setCollectLoading(true);

      if (values.deposit_type === 'banquet' && values.session_id) {
        // 宴会场次定金
        await txFetchData('/api/v1/banquet/deposits', {
          method: 'POST',
          body: JSON.stringify({
            session_id: values.session_id,
            amount_fen: yuan2fen(values.amount_yuan),
            payment_method: values.payment_method,
            operator_id: OPERATOR_ID,
            notes: values.notes,
          }),
        });
      } else {
        // 通用押金
        if (!storeId) throw new Error('请先选择门店');
        await collectDeposit({
          store_id: storeId,
          amount_fen: yuan2fen(values.amount_yuan),
          payment_method: values.payment_method,
          remark: values.notes,
          expires_days: values.expires_days,
        });
      }

      message.success('押金收取成功');
      setCollectVisible(false);
      collectForm.resetFields();
      actionRef.current?.reload();
      if (storeId) void loadStats(storeId);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '收取押金失败');
    } finally {
      setCollectLoading(false);
    }
  };

  // ─── 抵扣押金 ─────────────────────────────────────────────────────────────

  const handleApplyOpen = (record: DepositRecord) => {
    setApplyTarget(record);
    applyForm.setFieldsValue({
      apply_amount_yuan: fen2yuan(record.remaining_fen),
      order_id: '',
    });
    setApplyVisible(true);
  };

  const handleApplySubmit = async () => {
    if (!applyTarget) return;
    try {
      const values = await applyForm.validateFields();
      setApplyLoading(true);
      await applyDeposit(
        applyTarget.id,
        values.order_id || '',
        yuan2fen(values.apply_amount_yuan),
        values.notes,
      );
      message.success('押金抵扣成功');
      setApplyVisible(false);
      actionRef.current?.reload();
      if (storeId) void loadStats(storeId);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '抵扣失败');
    } finally {
      setApplyLoading(false);
    }
  };

  // ─── 退还押金 ─────────────────────────────────────────────────────────────

  const handleRefundOpen = (record: DepositRecord) => {
    setRefundTarget(record);
    refundForm.setFieldsValue({
      refund_amount_yuan: fen2yuan(record.remaining_fen),
      refund_method: record.payment_method,
      reason: '',
    });
    setRefundVisible(true);
  };

  const handleRefundSubmit = async () => {
    if (!refundTarget) return;
    try {
      const values = await refundForm.validateFields();
      setRefundLoading(true);
      const refundFen = yuan2fen(values.refund_amount_yuan);
      if (refundFen > refundTarget.remaining_fen) {
        message.warning(`退还金额不能超过可退余额 ¥${fen2yuan(refundTarget.remaining_fen)}`);
        return;
      }
      await refundDeposit(refundTarget.id, refundFen, values.reason);
      message.success('退还押金成功');
      setRefundVisible(false);
      actionRef.current?.reload();
      if (storeId) void loadStats(storeId);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '退还失败');
    } finally {
      setRefundLoading(false);
    }
  };

  // ─── 查看宴会场次定金详情 ─────────────────────────────────────────────────

  const handleViewBanquetDeposit = async (sessionId: string) => {
    setBanquetDepositLoading(true);
    setBanquetDepositVisible(true);
    try {
      const data = await txFetchData<BanquetDepositSummary>(
        `/api/v1/banquet/deposits/${sessionId}`
      );
      setBanquetSummary(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载定金信息失败');
      setBanquetDepositVisible(false);
    } finally {
      setBanquetDepositLoading(false);
    }
  };

  // ─── 列定义 ──────────────────────────────────────────────────────────────

  const columns: ProColumns<DepositRecord>[] = [
    {
      title: '收取时间',
      dataIndex: 'collected_at',
      key: 'collected_at',
      width: 140,
      search: false,
      render: (_, record) =>
        record.collected_at ? dayjs(record.collected_at).format('MM-DD HH:mm') : '-',
    },
    {
      title: '支付方式',
      dataIndex: 'payment_method',
      key: 'payment_method',
      width: 90,
      search: false,
      render: (_, record) => PAYMENT_METHOD_LABEL[record.payment_method] ?? record.payment_method,
    },
    {
      title: '存入金额',
      dataIndex: 'amount_fen',
      key: 'amount_fen',
      width: 110,
      search: false,
      render: (_, record) => (
        <Text strong style={{ color: '#0F6E56' }}>¥{fen2yuan(record.amount_fen)}</Text>
      ),
    },
    {
      title: '已抵扣',
      dataIndex: 'applied_amount_fen',
      key: 'applied_amount_fen',
      width: 100,
      search: false,
      render: (_, record) =>
        record.applied_amount_fen > 0 ? `¥${fen2yuan(record.applied_amount_fen)}` : '-',
    },
    {
      title: '已退还',
      dataIndex: 'refunded_amount_fen',
      key: 'refunded_amount_fen',
      width: 100,
      search: false,
      render: (_, record) =>
        record.refunded_amount_fen > 0 ? `¥${fen2yuan(record.refunded_amount_fen)}` : '-',
    },
    {
      title: '剩余金额',
      dataIndex: 'remaining_fen',
      key: 'remaining_fen',
      width: 110,
      search: false,
      render: (_, record) => (
        <Text
          strong
          style={{ color: record.remaining_fen > 0 ? '#BA7517' : '#B4B2A9' }}
        >
          ¥{fen2yuan(record.remaining_fen)}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      valueType: 'select',
      valueEnum: {
        '': { text: '全部状态' },
        collected: { text: '待结算', status: 'Processing' },
        partially_applied: { text: '部分抵扣', status: 'Warning' },
        fully_applied: { text: '已抵扣', status: 'Success' },
        refunded: { text: '已退还', status: 'Default' },
        converted: { text: '已转收入', status: 'Success' },
      },
      render: (_, record) => (
        <Tag color={STATUS_COLOR[record.status] ?? 'default'}>
          {STATUS_LABEL[record.status] ?? record.status}
        </Tag>
      ),
    },
    {
      title: '有效期',
      dataIndex: 'expires_at',
      key: 'expires_at',
      width: 110,
      search: false,
      render: (_, record) => {
        if (!record.expires_at) return '-';
        const expDate = dayjs(record.expires_at);
        const daysLeft = expDate.diff(dayjs(), 'day');
        if (daysLeft < 0) {
          return <Tag color="red">已过期</Tag>;
        } else if (daysLeft <= 7) {
          return (
            <Tooltip title={`${daysLeft} 天后过期`}>
              <Tag color="orange" icon={<WarningOutlined />}>{expDate.format('MM-DD')}</Tag>
            </Tooltip>
          );
        }
        return <span style={{ color: '#5F5E5A', fontSize: 12 }}>{expDate.format('MM-DD')}</span>;
      },
    },
    {
      title: '关联订单',
      dataIndex: 'order_id',
      key: 'order_id',
      width: 130,
      search: false,
      ellipsis: true,
      render: (_, record) =>
        record.order_id ? (
          <Text style={{ fontSize: 12, color: '#5F5E5A' }}>
            {record.order_id.slice(0, 8)}...
          </Text>
        ) : '-',
    },
    {
      title: '备注',
      dataIndex: 'remark',
      key: 'remark',
      ellipsis: true,
      search: false,
      render: (_, record) => record.remark || '-',
    },
    {
      title: '操作',
      key: 'action',
      valueType: 'option',
      width: 220,
      fixed: 'right',
      render: (_, record) => {
        const canOperate =
          record.remaining_fen > 0 &&
          record.status !== 'refunded' &&
          record.status !== 'converted' &&
          record.status !== 'written_off';
        return [
          <Button
            key="apply"
            size="small"
            type="primary"
            disabled={!canOperate}
            onClick={() => handleApplyOpen(record)}
          >
            抵扣
          </Button>,
          <Button
            key="refund"
            size="small"
            disabled={!canOperate}
            onClick={() => handleRefundOpen(record)}
          >
            退还
          </Button>,
          record.reservation_id ? (
            <Button
              key="banquet"
              size="small"
              type="link"
              icon={<SwapOutlined />}
              onClick={() => void handleViewBanquetDeposit(record.reservation_id!)}
            >
              挂台
            </Button>
          ) : null,
          <Button
            key="print"
            size="small"
            type="link"
            icon={<PrinterOutlined />}
            onClick={() => message.info('小票打印功能开发中')}
          >
            重打单
          </Button>,
        ].filter(Boolean);
      },
    },
  ];

  // ─── 渲染 ─────────────────────────────────────────────────────────────────

  return (
    <div style={{ maxWidth: 1600, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
            押金管理
          </Title>
          <Text style={{ color: '#5F5E5A', fontSize: 14 }}>
            管理宴会押金收取、抵扣与退还，支持多支付方式
          </Text>
        </div>
        <Space>
          <Select
            placeholder="选择门店"
            options={stores}
            value={storeId}
            onChange={(val) => setStoreId(val)}
            style={{ width: 200 }}
            allowClear={false}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            onClick={() => {
              void loadSessions();
              collectForm.resetFields();
              setCollectVisible(true);
            }}
          >
            收取押金
          </Button>
        </Space>
      </div>

      {/* 统计卡片行 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col flex="1">
          <StatCard
            title="今日收取押金数"
            value={todayCount}
            suffix="笔"
            valueColor="#2C2C2A"
            icon={<DollarOutlined />}
          />
        </Col>
        <Col flex="1">
          <StatCard
            title="今日押金金额"
            value={fen2yuan(todayAmountFen)}
            prefix="¥"
            valueColor="#0F6E56"
            icon={<CheckCircleOutlined />}
          />
        </Col>
        <Col flex="1">
          <StatCard
            title="本月押金总额"
            value={fen2yuan(monthTotalFen)}
            prefix="¥"
            valueColor="#185FA5"
            icon={<DollarOutlined />}
          />
        </Col>
        <Col flex="1">
          <StatCard
            title="待结押金数量"
            value={pendingCount}
            suffix="笔"
            valueColor="#BA7517"
            icon={<ClockCircleOutlined />}
          />
        </Col>
        <Col flex="1">
          <StatCard
            title="即将逾期"
            value={expiringCount}
            suffix="笔"
            valueColor={expiringCount > 0 ? '#A32D2D' : '#2C2C2A'}
            icon={<ExclamationCircleOutlined />}
            warning={expiringCount > 0}
            extra={
              expiringCount > 0 ? (
                <Text style={{ fontSize: 12, color: '#A32D2D' }}>
                  含30天以上未结 {expiringCount} 笔，请及时处理
                </Text>
              ) : null
            }
          />
        </Col>
      </Row>

      {/* 押金记录列表 */}
      <Card>
        <ProTable<DepositRecord>
          actionRef={actionRef}
          columns={columns}
          rowKey="id"
          scroll={{ x: 1400 }}
          request={async (params) => {
            if (!storeId) return { data: [], total: 0, success: true };
            try {
              const data = await listDepositsByStore(storeId, {
                status: (params.status as string) || statusFilter || undefined,
                page: params.current,
                size: params.pageSize,
              });
              return { data: data.items, total: data.total, success: true };
            } catch {
              return { data: [], total: 0, success: false };
            }
          }}
          search={{
            labelWidth: 'auto',
            filterType: 'light',
          }}
          pagination={{ defaultPageSize: 20, showTotal: (t) => `共 ${t} 条` }}
          toolBarRender={() => [
            <Button
              key="refresh"
              icon={<ReloadOutlined />}
              onClick={() => actionRef.current?.reload()}
            >
              刷新
            </Button>,
          ]}
          headerTitle="押金记录"
          size="middle"
        />
      </Card>

      {/* ─── 收取押金弹窗 ──────────────────────────────────────────────────── */}
      <Modal
        title="收取押金"
        open={collectVisible}
        onCancel={() => { setCollectVisible(false); collectForm.resetFields(); }}
        onOk={handleCollectSubmit}
        confirmLoading={collectLoading}
        okText="确认收取"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        width={560}
        destroyOnClose
      >
        <Form form={collectForm} layout="vertical" initialValues={{ deposit_type: 'banquet', payment_method: 'cash' }}>
          <Form.Item name="deposit_type" label="押金类型">
            <Select
              options={[
                { value: 'banquet', label: '宴会定金（关联场次）' },
                { value: 'general', label: '通用押金' },
              ]}
            />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) => prev.deposit_type !== cur.deposit_type}
          >
            {({ getFieldValue }) =>
              getFieldValue('deposit_type') === 'banquet' ? (
                <Form.Item
                  name="session_id"
                  label="关联宴会场次"
                  rules={[{ required: true, message: '请选择宴会场次' }]}
                >
                  <Select
                    placeholder="搜索宴会场次"
                    showSearch
                    filterOption={(input, option) =>
                      String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                    }
                    options={sessions.map((s) => ({
                      value: s.id,
                      label: `${s.contact_name} - ${s.tables ?? s.id.slice(0, 8)} (${s.guest_count}人)`,
                    }))}
                    notFoundContent="暂无进行中的宴席场次"
                  />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="amount_yuan"
                label="押金金额（元）"
                rules={[{ required: true, message: '请输入押金金额' }]}
              >
                <InputNumber
                  min={0.01}
                  step={100}
                  precision={2}
                  style={{ width: '100%' }}
                  addonBefore="¥"
                  placeholder="请输入金额"
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="payment_method"
                label="支付方式"
                rules={[{ required: true }]}
              >
                <Select
                  options={[
                    { value: 'cash', label: '现金' },
                    { value: 'wechat', label: '微信' },
                    { value: 'alipay', label: '支付宝' },
                    { value: 'card', label: '银行卡' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) => prev.deposit_type !== cur.deposit_type}
          >
            {({ getFieldValue }) =>
              getFieldValue('deposit_type') === 'general' ? (
                <Form.Item name="expires_days" label="有效天数（可选）">
                  <InputNumber min={1} max={365} style={{ width: '100%' }} addonAfter="天" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item name="notes" label="备注（可选）">
            <Input.TextArea rows={2} placeholder="填写收取说明" maxLength={200} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* ─── 抵扣押金弹窗 ──────────────────────────────────────────────────── */}
      <Modal
        title="抵扣押金"
        open={applyVisible}
        onCancel={() => { setApplyVisible(false); applyForm.resetFields(); }}
        onOk={handleApplySubmit}
        confirmLoading={applyLoading}
        okText="确认抵扣"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        width={480}
        destroyOnClose
      >
        {applyTarget && (
          <>
            <div style={{
              background: '#F8F7F5',
              borderRadius: 6,
              padding: '12px 16px',
              marginBottom: 16,
            }}>
              <Row gutter={16}>
                <Col span={12}>
                  <Text type="secondary" style={{ fontSize: 12 }}>存入金额</Text>
                  <div><Text strong>¥{fen2yuan(applyTarget.amount_fen)}</Text></div>
                </Col>
                <Col span={12}>
                  <Text type="secondary" style={{ fontSize: 12 }}>可抵扣余额</Text>
                  <div>
                    <Text strong style={{ color: '#BA7517', fontSize: 16 }}>
                      ¥{fen2yuan(applyTarget.remaining_fen)}
                    </Text>
                  </div>
                </Col>
              </Row>
            </div>
            <Form form={applyForm} layout="vertical">
              <Form.Item
                name="apply_amount_yuan"
                label="抵扣金额（元）"
                rules={[
                  { required: true, message: '请输入抵扣金额' },
                  {
                    validator: (_, val) => {
                      if (val > applyTarget.remaining_fen / 100) {
                        return Promise.reject(`不能超过可用余额 ¥${fen2yuan(applyTarget.remaining_fen)}`);
                      }
                      return Promise.resolve();
                    },
                  },
                ]}
              >
                <InputNumber
                  min={0.01}
                  max={applyTarget.remaining_fen / 100}
                  step={0.01}
                  precision={2}
                  style={{ width: '100%' }}
                  addonBefore="¥"
                />
              </Form.Item>
              <Form.Item name="order_id" label="关联订单号（可选）">
                <Input placeholder="填写关联订单号" />
              </Form.Item>
              <Form.Item name="notes" label="备注（可选）">
                <Input.TextArea rows={2} maxLength={100} />
              </Form.Item>
            </Form>
          </>
        )}
      </Modal>

      {/* ─── 退还押金弹窗 ──────────────────────────────────────────────────── */}
      <Modal
        title="退还押金"
        open={refundVisible}
        onCancel={() => { setRefundVisible(false); refundForm.resetFields(); }}
        onOk={handleRefundSubmit}
        confirmLoading={refundLoading}
        okText="确认退还"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        width={480}
        destroyOnClose
      >
        {refundTarget && (
          <>
            <div style={{
              background: '#F8F7F5',
              borderRadius: 6,
              padding: '12px 16px',
              marginBottom: 16,
            }}>
              <Row gutter={16}>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 12 }}>收取金额</Text>
                  <div><Text strong>¥{fen2yuan(refundTarget.amount_fen)}</Text></div>
                </Col>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 12 }}>已抵扣</Text>
                  <div><Text>¥{fen2yuan(refundTarget.applied_amount_fen)}</Text></div>
                </Col>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 12 }}>可退余额</Text>
                  <div>
                    <Text strong style={{ color: '#BA7517', fontSize: 16 }}>
                      ¥{fen2yuan(refundTarget.remaining_fen)}
                    </Text>
                  </div>
                </Col>
              </Row>
            </div>
            <Form form={refundForm} layout="vertical">
              <Form.Item
                name="refund_amount_yuan"
                label="退还金额（元）"
                help={`最多可退 ¥${fen2yuan(refundTarget.remaining_fen)}`}
                rules={[
                  { required: true, message: '请输入退还金额' },
                  {
                    validator: (_, val) => {
                      if (val > refundTarget.remaining_fen / 100) {
                        return Promise.reject(`不能超过可退余额 ¥${fen2yuan(refundTarget.remaining_fen)}`);
                      }
                      return Promise.resolve();
                    },
                  },
                ]}
              >
                <InputNumber
                  min={0.01}
                  max={refundTarget.remaining_fen / 100}
                  step={0.01}
                  precision={2}
                  style={{ width: '100%' }}
                  addonBefore="¥"
                />
              </Form.Item>
              <Form.Item
                name="refund_method"
                label="退还方式"
                rules={[{ required: true }]}
              >
                <Select
                  options={[
                    { value: 'cash', label: '现金' },
                    { value: 'wechat', label: '微信退款' },
                    { value: 'alipay', label: '支付宝退款' },
                    { value: 'card', label: '原卡退回' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="reason"
                label="退还原因"
                rules={[{ required: true, message: '请填写退还原因' }]}
              >
                <Input.TextArea rows={2} placeholder="请填写退还原因" maxLength={200} showCount />
              </Form.Item>
            </Form>
          </>
        )}
      </Modal>

      {/* ─── 宴会场次定金详情弹窗 ──────────────────────────────────────────── */}
      <Modal
        title="宴会场次定金详情"
        open={banquetDepositVisible}
        onCancel={() => setBanquetDepositVisible(false)}
        footer={null}
        width={600}
        loading={banquetDepositLoading}
        destroyOnClose
      >
        {banquetSummary && (
          <div>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Statistic
                  title="订单总额"
                  value={fen2yuan(banquetSummary.order_total_fen)}
                  prefix="¥"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="已收定金"
                  value={fen2yuan(banquetSummary.total_collected_fen)}
                  prefix="¥"
                  valueStyle={{ color: '#0F6E56' }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="剩余应付"
                  value={fen2yuan(banquetSummary.remaining_payable_fen)}
                  prefix="¥"
                  valueStyle={{ color: banquetSummary.remaining_payable_fen > 0 ? '#BA7517' : '#0F6E56' }}
                />
              </Col>
            </Row>
            <div style={{ marginTop: 8 }}>
              {banquetSummary.records.map((rec) => (
                <div
                  key={rec.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '8px 12px',
                    background: '#F8F7F5',
                    borderRadius: 6,
                    marginBottom: 8,
                  }}
                >
                  <Space>
                    <Tag color={STATUS_COLOR[rec.status] ?? 'default'}>
                      {STATUS_LABEL[rec.status] ?? rec.status}
                    </Tag>
                    <Text style={{ fontSize: 12, color: '#5F5E5A' }}>
                      {PAYMENT_METHOD_LABEL[rec.payment_method] ?? rec.payment_method}
                    </Text>
                    <Text style={{ fontSize: 12, color: '#B4B2A9' }}>
                      {dayjs(rec.collected_at).format('MM-DD HH:mm')}
                    </Text>
                  </Space>
                  <Space>
                    <Text>¥{fen2yuan(rec.amount_fen)}</Text>
                    <Text style={{ color: '#BA7517' }}>余¥{fen2yuan(rec.balance_fen)}</Text>
                  </Space>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
