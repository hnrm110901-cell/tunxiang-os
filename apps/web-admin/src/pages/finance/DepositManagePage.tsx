/**
 * 押金管理页面 — Deposit Management
 * 功能: 押金列表、退押金、转收入、台账报表、账龄分析
 * API: GET /api/v1/deposits/store/{store_id}
 *      POST /api/v1/deposits/{id}/refund
 *      POST /api/v1/deposits/{id}/convert
 *      GET  /api/v1/deposits/report/ledger
 *      GET  /api/v1/deposits/report/aging
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  type DepositRecord,
  type DepositStatus,
  type DepositLedgerItem,
  type DepositAgingItem,
  listDepositsByStore,
  refundDeposit,
  convertDeposit,
  getDepositLedger,
  getDepositAging,
  getDepositShiftSummary,
} from '../../api/depositApi';
import { txFetchData } from '../../api';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 辅助类型 ────────────────────────────────────────────────────────────────

interface StoreOption {
  value: string;
  label: string;
}

// ─── 状态配置 ────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<DepositStatus, string> = {
  collected: '待退',
  partially_applied: '部分抵扣',
  fully_applied: '已抵扣',
  refunded: '已退',
  converted: '已转收入',
  written_off: '已核销',
};

const STATUS_COLOR: Record<DepositStatus, string> = {
  collected: 'orange',
  partially_applied: 'gold',
  fully_applied: 'blue',
  refunded: 'green',
  converted: 'purple',
  written_off: 'default',
};

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'collected', label: '待退' },
  { value: 'partially_applied', label: '部分抵扣' },
  { value: 'fully_applied', label: '已抵扣' },
  { value: 'refunded', label: '已退' },
  { value: 'converted', label: '已转收入' },
];

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function DepositManagePage() {
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const [stores, setStores] = useState<StoreOption[]>([]);

  // 列表数据
  const [records, setRecords] = useState<DepositRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  // 台账数据
  const [ledger, setLedger] = useState<DepositLedgerItem | null>(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  // 账龄数据
  const [aging, setAging] = useState<DepositAgingItem | null>(null);
  const [agingLoading, setAgingLoading] = useState(false);

  // 结班汇总数据
  const [shiftSummary, setShiftSummary] = useState<{
    received_count: number;
    received_fen: number;
    refunded_count: number;
    refunded_fen: number;
    net_fen: number;
    shift_date: string;
  } | null>(null);
  const [shiftSummaryLoading, setShiftSummaryLoading] = useState(false);
  const [shiftDate, setShiftDate] = useState<Dayjs>(dayjs());

  // 退押金 Modal
  const [refundVisible, setRefundVisible] = useState(false);
  const [refundTarget, setRefundTarget] = useState<DepositRecord | null>(null);
  const [refundAmt, setRefundAmt] = useState<number>(0);
  const [refundRemark, setRefundRemark] = useState('');
  const [refundLoading, setRefundLoading] = useState(false);

  // 转收入 Modal
  const [convertVisible, setConvertVisible] = useState(false);
  const [convertTarget, setConvertTarget] = useState<DepositRecord | null>(null);
  const [convertLoading, setConvertLoading] = useState(false);

  const PAGE_SIZE = 20;

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((data) => {
        setStores((data.items ?? []).map((s) => ({ value: s.id, label: s.name })));
      })
      .catch(() => setStores([]));
  }, []);

  // 加载押金列表
  const loadRecords = useCallback(
    async (sid: string, p: number, status: string) => {
      setLoading(true);
      try {
        const data = await listDepositsByStore(sid, {
          status: status || undefined,
          page: p,
          size: PAGE_SIZE,
        });
        setRecords(data.items);
        setTotal(data.total);
      } catch (err) {
        message.error(err instanceof Error ? err.message : '加载押金列表失败');
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // 加载台账
  const loadLedger = useCallback(async (sid: string, start: string, end: string) => {
    setLedgerLoading(true);
    try {
      const data = await getDepositLedger(sid, start, end);
      setLedger(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载台账失败');
    } finally {
      setLedgerLoading(false);
    }
  }, []);

  // 加载结班汇总
  const loadShiftSummary = useCallback(async (sid: string, sdate: string) => {
    setShiftSummaryLoading(true);
    try {
      const data = await getDepositShiftSummary(sid, sdate);
      setShiftSummary(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载结班汇总失败');
    } finally {
      setShiftSummaryLoading(false);
    }
  }, []);

  // 加载账龄
  const loadAging = useCallback(async (sid: string) => {
    setAgingLoading(true);
    try {
      const data = await getDepositAging(sid);
      setAging(data);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载账龄失败');
    } finally {
      setAgingLoading(false);
    }
  }, []);

  // 门店切换时重新加载列表和账龄
  useEffect(() => {
    if (!storeId) return;
    setPage(1);
    void loadRecords(storeId, 1, statusFilter);
    void loadAging(storeId);
    void loadShiftSummary(storeId, dayjs().format('YYYY-MM-DD'));

    const end = dayjs().format('YYYY-MM-DD');
    const start = dayjs().subtract(30, 'day').format('YYYY-MM-DD');
    void loadLedger(storeId, start, end);
  }, [storeId, statusFilter, loadRecords, loadAging, loadLedger, loadShiftSummary]);

  const handlePageChange = (p: number) => {
    setPage(p);
    if (storeId) void loadRecords(storeId, p, statusFilter);
  };

  // 退押金
  const handleRefundOpen = (record: DepositRecord) => {
    setRefundTarget(record);
    setRefundAmt(record.remaining_fen / 100);
    setRefundRemark('');
    setRefundVisible(true);
  };

  const handleRefundConfirm = async () => {
    if (!refundTarget) return;
    const refundFen = Math.round(refundAmt * 100);
    if (refundFen <= 0) {
      message.warning('退还金额必须大于0');
      return;
    }
    if (refundFen > refundTarget.remaining_fen) {
      message.warning(`退还金额不能超过可退余额 ¥${fenToYuan(refundTarget.remaining_fen)}`);
      return;
    }
    setRefundLoading(true);
    try {
      await refundDeposit(refundTarget.id, refundFen, refundRemark || undefined);
      message.success('退押金成功');
      setRefundVisible(false);
      if (storeId) void loadRecords(storeId, page, statusFilter);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '退押金失败');
    } finally {
      setRefundLoading(false);
    }
  };

  // 押金转收入
  const handleConvertOpen = (record: DepositRecord) => {
    setConvertTarget(record);
    setConvertVisible(true);
  };

  const handleConvertConfirm = async () => {
    if (!convertTarget) return;
    setConvertLoading(true);
    try {
      await convertDeposit(convertTarget.id, '押金转收入');
      message.success('押金已转为收入');
      setConvertVisible(false);
      if (storeId) void loadRecords(storeId, page, statusFilter);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败');
    } finally {
      setConvertLoading(false);
    }
  };

  // ─── 列表列定义 ────────────────────────────────────────────────────────────

  const columns: ColumnsType<DepositRecord> = [
    {
      title: '收取时间',
      dataIndex: 'collected_at',
      key: 'collected_at',
      width: 160,
      render: (val: string) => val ? dayjs(val).format('MM-DD HH:mm') : '-',
    },
    {
      title: '支付方式',
      dataIndex: 'payment_method',
      key: 'payment_method',
      width: 90,
      render: (val: string) => {
        const labels: Record<string, string> = {
          wechat: '微信', alipay: '支付宝', cash: '现金', card: '刷卡',
        };
        return labels[val] ?? val;
      },
    },
    {
      title: '收取金额',
      dataIndex: 'amount_fen',
      key: 'amount_fen',
      width: 110,
      render: (val: number) => `¥${fenToYuan(val)}`,
    },
    {
      title: '已抵扣',
      dataIndex: 'applied_amount_fen',
      key: 'applied_amount_fen',
      width: 100,
      render: (val: number) => val > 0 ? `¥${fenToYuan(val)}` : '-',
    },
    {
      title: '已退还',
      dataIndex: 'refunded_amount_fen',
      key: 'refunded_amount_fen',
      width: 100,
      render: (val: number) => val > 0 ? `¥${fenToYuan(val)}` : '-',
    },
    {
      title: '可退余额',
      dataIndex: 'remaining_fen',
      key: 'remaining_fen',
      width: 110,
      render: (val: number) => (
        <Text strong style={{ color: val > 0 ? '#BA7517' : '#B4B2A9' }}>
          ¥{fenToYuan(val)}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: DepositStatus) => (
        <Tag color={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Tag>
      ),
    },
    {
      title: '关联订单',
      dataIndex: 'order_id',
      key: 'order_id',
      width: 160,
      ellipsis: true,
      render: (val: string | null) => val ? (
        <Text style={{ fontSize: 12, color: '#5F5E5A' }}>{val.slice(0, 8)}...</Text>
      ) : '-',
    },
    {
      title: '备注',
      dataIndex: 'remark',
      key: 'remark',
      ellipsis: true,
      render: (val: string | null) => val || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      fixed: 'right' as const,
      render: (_: unknown, record: DepositRecord) => (
        <Space size={8}>
          <Button
            size="small"
            type="primary"
            disabled={
              record.remaining_fen <= 0 ||
              record.status === 'refunded' ||
              record.status === 'converted' ||
              record.status === 'written_off'
            }
            onClick={() => handleRefundOpen(record)}
          >
            退押金
          </Button>
          <Button
            size="small"
            danger
            disabled={
              record.remaining_fen <= 0 ||
              record.status === 'refunded' ||
              record.status === 'converted' ||
              record.status === 'written_off'
            }
            onClick={() => handleConvertOpen(record)}
          >
            转收入
          </Button>
        </Space>
      ),
    },
  ];

  // ─── Tab 内容 ─────────────────────────────────────────────────────────────

  const tabItems = [
    {
      key: 'list',
      label: '押金列表',
      children: (
        <>
          {!storeId && (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
              请先选择门店
            </div>
          )}
          {storeId && (
            <Table<DepositRecord>
              columns={columns}
              dataSource={records}
              rowKey="id"
              loading={loading}
              scroll={{ x: 1300 }}
              pagination={{
                current: page,
                pageSize: PAGE_SIZE,
                total,
                showSizeChanger: false,
                showTotal: (t) => `共 ${t} 条`,
                onChange: handlePageChange,
              }}
              size="middle"
            />
          )}
        </>
      ),
    },
    {
      key: 'ledger',
      label: '押金台账',
      children: (
        <Spin spinning={ledgerLoading}>
          <div style={{ marginBottom: 16 }}>
            <Space>
              <RangePicker
                style={{ width: 260 }}
                onChange={(vals: [Dayjs | null, Dayjs | null] | null) => {
                  if (vals && vals[0] && vals[1]) {
                    const start = vals[0].format('YYYY-MM-DD');
                    const end = vals[1].format('YYYY-MM-DD');
                    setDateRange([start, end]);
                    if (storeId) void loadLedger(storeId, start, end);
                  }
                }}
              />
            </Space>
          </div>
          {ledger ? (
            <Row gutter={[16, 16]}>
              <Col span={8}>
                <Card styles={{ body: { padding: '16px 20px' } }}>
                  <Statistic
                    title="收取总额（元）"
                    value={fenToYuan(ledger.total_collected_fen)}
                    prefix="¥"
                    valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
                  />
                </Card>
              </Col>
              <Col span={8}>
                <Card styles={{ body: { padding: '16px 20px' } }}>
                  <Statistic
                    title="已退总额（元）"
                    value={fenToYuan(ledger.total_refunded_fen)}
                    prefix="¥"
                    valueStyle={{ color: '#185FA5', fontWeight: 700 }}
                  />
                </Card>
              </Col>
              <Col span={8}>
                <Card styles={{ body: { padding: '16px 20px' } }}>
                  <Statistic
                    title="待退余额（元）"
                    value={fenToYuan(ledger.total_outstanding_fen)}
                    prefix="¥"
                    valueStyle={{ color: '#BA7517', fontWeight: 700 }}
                  />
                </Card>
              </Col>
              <Col span={8}>
                <Card styles={{ body: { padding: '16px 20px' } }}>
                  <Statistic
                    title="已抵扣消费（元）"
                    value={fenToYuan(ledger.total_applied_fen)}
                    prefix="¥"
                  />
                </Card>
              </Col>
              <Col span={8}>
                <Card styles={{ body: { padding: '16px 20px' } }}>
                  <Statistic
                    title="已转收入（元）"
                    value={fenToYuan(ledger.total_converted_fen)}
                    prefix="¥"
                  />
                </Card>
              </Col>
              <Col span={8}>
                <Card styles={{ body: { padding: '16px 20px' } }}>
                  <Statistic
                    title="押金笔数"
                    value={ledger.total_count}
                  />
                </Card>
              </Col>
            </Row>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
              {storeId ? '请选择日期范围查看台账' : '请先选择门店'}
            </div>
          )}
        </Spin>
      ),
    },
    {
      key: 'shift',
      label: '结班汇总',
      children: (
        <Spin spinning={shiftSummaryLoading}>
          <div style={{ marginBottom: 16 }}>
            <Space>
              <DatePicker
                value={shiftDate}
                allowClear={false}
                onChange={(val) => {
                  if (val) {
                    setShiftDate(val);
                    if (storeId) void loadShiftSummary(storeId, val.format('YYYY-MM-DD'));
                  }
                }}
              />
              <Button
                type="primary"
                style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
                onClick={() => {
                  if (!storeId) { message.warning('请先选择门店'); return; }
                  void loadShiftSummary(storeId, shiftDate.format('YYYY-MM-DD'));
                }}
              >
                查询
              </Button>
            </Space>
          </div>
          {shiftSummary ? (
            <>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Card styles={{ body: { padding: '20px 24px' } }}>
                    <Statistic
                      title={`本班收押金（${shiftSummary.received_count} 笔）`}
                      value={fenToYuan(shiftSummary.received_fen)}
                      prefix="¥"
                      valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card styles={{ body: { padding: '20px 24px' } }}>
                    <Statistic
                      title={`本班退押金（${shiftSummary.refunded_count} 笔）`}
                      value={fenToYuan(shiftSummary.refunded_fen)}
                      prefix="¥"
                      valueStyle={{ color: '#185FA5', fontWeight: 700 }}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card styles={{ body: { padding: '20px 24px' } }}>
                    <Statistic
                      title="净留存"
                      value={fenToYuan(shiftSummary.net_fen)}
                      prefix="¥"
                      valueStyle={{
                        color: shiftSummary.net_fen >= 0 ? '#0F6E56' : '#A32D2D',
                        fontWeight: 700,
                      }}
                    />
                  </Card>
                </Col>
              </Row>
              <div style={{ color: '#B4B2A9', fontSize: 13 }}>
                统计范围：{shiftSummary.shift_date} 00:00 — 23:59（北京时间）
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
              {storeId ? '请选择日期查看结班汇总' : '请先选择门店'}
            </div>
          )}
        </Spin>
      ),
    },
    {
      key: 'aging',
      label: '账龄分析',
      children: (
        <Spin spinning={agingLoading}>
          {aging ? (
            <Table
              dataSource={[
                {
                  key: '0_7',
                  bucket: '0~7 天',
                  count: aging.aging['0_7_days'].count,
                  amount_fen: aging.aging['0_7_days'].amount_fen,
                  risk: '正常',
                  risk_color: 'green',
                },
                {
                  key: '8_30',
                  bucket: '8~30 天',
                  count: aging.aging['8_30_days'].count,
                  amount_fen: aging.aging['8_30_days'].amount_fen,
                  risk: '注意',
                  risk_color: 'gold',
                },
                {
                  key: '31_90',
                  bucket: '31~90 天',
                  count: aging.aging['31_90_days'].count,
                  amount_fen: aging.aging['31_90_days'].amount_fen,
                  risk: '警告',
                  risk_color: 'orange',
                },
                {
                  key: 'over_90',
                  bucket: '90 天以上',
                  count: aging.aging['over_90_days'].count,
                  amount_fen: aging.aging['over_90_days'].amount_fen,
                  risk: '高风险',
                  risk_color: 'red',
                },
              ]}
              columns={[
                { title: '账龄区间', dataIndex: 'bucket', key: 'bucket', width: 120 },
                { title: '笔数', dataIndex: 'count', key: 'count', width: 100 },
                {
                  title: '未结余额（元）',
                  dataIndex: 'amount_fen',
                  key: 'amount_fen',
                  render: (val: number) => `¥${fenToYuan(val)}`,
                },
                {
                  title: '风险等级',
                  dataIndex: 'risk',
                  key: 'risk',
                  width: 100,
                  render: (val: string, row: Record<string, unknown>) => (
                    <Tag color={row.risk_color as string}>{val}</Tag>
                  ),
                },
              ]}
              rowKey="key"
              pagination={false}
              size="middle"
            />
          ) : (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
              {storeId ? '暂无账龄数据' : '请先选择门店'}
            </div>
          )}
        </Spin>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          押金管理
        </Title>
        <Text style={{ color: '#5F5E5A', fontSize: 14 }}>
          管理门店收取的押金，支持退还、转收入操作
        </Text>
      </div>

      {/* 筛选栏 */}
      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12} wrap>
          <Select
            placeholder="选择门店"
            options={stores}
            value={storeId}
            onChange={(val) => { setStoreId(val); }}
            style={{ width: 220 }}
            allowClear
          />
          <Select
            placeholder="状态筛选"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={(val) => setStatusFilter(val)}
            style={{ width: 160 }}
          />
          <RangePicker
            style={{ width: 260 }}
            onChange={(vals: [Dayjs | null, Dayjs | null] | null) => {
              if (vals && vals[0] && vals[1]) {
                setDateRange([vals[0].format('YYYY-MM-DD'), vals[1].format('YYYY-MM-DD')]);
              } else {
                setDateRange(null);
              }
            }}
          />
          <Button
            type="primary"
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            onClick={() => {
              if (!storeId) {
                message.warning('请先选择门店');
                return;
              }
              setPage(1);
              void loadRecords(storeId, 1, statusFilter);
            }}
          >
            查询
          </Button>
        </Space>
      </Card>

      {/* 统计卡片 */}
      {storeId && ledger && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card styles={{ body: { padding: '20px 24px' } }}>
              <Statistic
                title="近30天收取总额"
                value={fenToYuan(ledger.total_collected_fen)}
                prefix="¥"
                valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card styles={{ body: { padding: '20px 24px' } }}>
              <Statistic
                title="待退余额"
                value={fenToYuan(ledger.total_outstanding_fen)}
                prefix="¥"
                valueStyle={{ color: '#BA7517', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card styles={{ body: { padding: '20px 24px' } }}>
              <Statistic
                title="已退总额"
                value={fenToYuan(ledger.total_refunded_fen)}
                prefix="¥"
                valueStyle={{ color: '#185FA5', fontWeight: 700 }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Tab 内容 */}
      <Card>
        <Tabs items={tabItems} defaultActiveKey="list" />
      </Card>

      {/* 退押金 Modal */}
      <Modal
        title="退押金"
        open={refundVisible}
        onCancel={() => setRefundVisible(false)}
        onOk={handleRefundConfirm}
        confirmLoading={refundLoading}
        okText="确认退还"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        width={480}
        destroyOnClose
      >
        {refundTarget && (
          <div>
            <div style={{ background: '#F8F7F5', borderRadius: 6, padding: '12px 16px', marginBottom: 16 }}>
              <div>
                <Text type="secondary">收取金额：</Text>
                <Text strong>¥{fenToYuan(refundTarget.amount_fen)}</Text>
              </div>
              <div>
                <Text type="secondary">已退还：</Text>
                <Text>¥{fenToYuan(refundTarget.refunded_amount_fen)}</Text>
              </div>
              <div>
                <Text type="secondary">可退余额：</Text>
                <Text strong style={{ color: '#BA7517' }}>
                  ¥{fenToYuan(refundTarget.remaining_fen)}
                </Text>
              </div>
            </div>
            <Form layout="vertical">
              <Form.Item
                label="退还金额（元）"
                required
                help={`最多可退 ¥${fenToYuan(refundTarget.remaining_fen)}`}
              >
                <InputNumber
                  min={0.01}
                  max={refundTarget.remaining_fen / 100}
                  step={0.01}
                  precision={2}
                  value={refundAmt}
                  onChange={(val) => setRefundAmt(val ?? 0)}
                  style={{ width: '100%' }}
                  addonBefore="¥"
                />
              </Form.Item>
              <Form.Item label="备注（可选）">
                <input
                  value={refundRemark}
                  onChange={(e) => setRefundRemark(e.target.value)}
                  placeholder="退押金原因"
                  style={{
                    width: '100%',
                    padding: '7px 11px',
                    border: '1px solid #E8E6E1',
                    borderRadius: 6,
                    fontSize: 14,
                  }}
                />
              </Form.Item>
            </Form>
          </div>
        )}
      </Modal>

      {/* 押金转收入 Modal */}
      <Modal
        title="押金转收入"
        open={convertVisible}
        onCancel={() => setConvertVisible(false)}
        onOk={handleConvertConfirm}
        confirmLoading={convertLoading}
        okText="确认转收入"
        okButtonProps={{ danger: true }}
        width={440}
        destroyOnClose
      >
        {convertTarget && (
          <div>
            <div style={{
              background: '#FFF3ED',
              border: '1px solid #FF6B35',
              borderRadius: 6,
              padding: '12px 16px',
              marginBottom: 16,
            }}>
              <Text style={{ color: '#FF6B35' }}>
                此操作不可撤销，押金余额将被计为门店收入。
              </Text>
            </div>
            <div>
              <Text type="secondary">可转金额：</Text>
              <Text strong style={{ fontSize: 18, color: '#A32D2D' }}>
                ¥{fenToYuan(convertTarget.remaining_fen)}
              </Text>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
