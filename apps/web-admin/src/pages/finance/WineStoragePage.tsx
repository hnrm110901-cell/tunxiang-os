/**
 * 存酒管理页面 — Wine Storage Management
 * 功能: 门店存酒列表、取酒、续存、即将到期预警、统计卡片
 * API: GET /api/v1/wine-storage/store/{store_id}
 *      POST /api/v1/wine-storage/{id}/retrieve
 *      POST /api/v1/wine-storage/{id}/extend
 *      GET  /api/v1/wine-storage/report/expiring
 *      GET  /api/v1/wine-storage/report/summary
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
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
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  type WineStorageRecord,
  type WineStorageStatus,
  type WineSummaryReport,
  type WineExpiringItem,
  listWineByStore,
  retrieveWine,
  extendWine,
  getExpiringSoon,
  getWineSummary,
} from '../../api/wineStorageApi';
import { txFetchData } from '../../api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

// ─── 辅助类型 ────────────────────────────────────────────────────────────────

interface StoreOption {
  value: string;
  label: string;
}

// ─── 状态配置 ────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<WineStorageStatus, string> = {
  stored: '存储中',
  partially_retrieved: '部分取出',
  fully_retrieved: '已取出',
  expired: '已过期',
  transferred: '已转移',
  written_off: '已核销',
};

const STATUS_COLOR: Record<WineStorageStatus, string> = {
  stored: 'green',
  partially_retrieved: 'orange',
  fully_retrieved: 'default',
  expired: 'red',
  transferred: 'blue',
  written_off: 'default',
};

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'stored', label: '存储中' },
  { value: 'partially_retrieved', label: '部分取出' },
  { value: 'fully_retrieved', label: '已取出' },
  { value: 'expired', label: '已过期' },
];

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function WineStoragePage() {
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [records, setRecords] = useState<WineStorageRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<WineSummaryReport | null>(null);
  const [expiring, setExpiring] = useState<WineExpiringItem[]>([]);

  // 取酒 Modal
  const [retrieveVisible, setRetrieveVisible] = useState(false);
  const [retrieveTarget, setRetrieveTarget] = useState<WineStorageRecord | null>(null);
  const [retrieveQty, setRetrieveQty] = useState<number>(1);
  const [retrieveRemark, setRetrieveRemark] = useState('');
  const [retrieveLoading, setRetrieveLoading] = useState(false);

  // 续存 Modal
  const [extendVisible, setExtendVisible] = useState(false);
  const [extendTarget, setExtendTarget] = useState<WineStorageRecord | null>(null);
  const [extendDays, setExtendDays] = useState<number>(30);
  const [extendRemark, setExtendRemark] = useState('');
  const [extendLoading, setExtendLoading] = useState(false);

  const PAGE_SIZE = 20;

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((data) => {
        setStores((data.items ?? []).map((s) => ({ value: s.id, label: s.name })));
      })
      .catch(() => setStores([]));
  }, []);

  // 加载存酒列表
  const loadRecords = useCallback(
    async (sid: string, p: number, status: string) => {
      setLoading(true);
      try {
        const data = await listWineByStore(sid, {
          status: status || undefined,
          page: p,
          size: PAGE_SIZE,
        });
        setRecords(data.items);
        setTotal(data.total);
      } catch (err) {
        message.error(err instanceof Error ? err.message : '加载存酒列表失败');
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  // 加载统计数据
  const loadStats = useCallback(async (sid: string) => {
    try {
      const [summaryData, expiringData] = await Promise.all([
        getWineSummary(sid),
        getExpiringSoon(sid, 7),
      ]);
      setSummary(summaryData);
      setExpiring(expiringData.items);
    } catch {
      // 统计加载失败不阻断主流程
    }
  }, []);

  // 门店切换时重新加载
  useEffect(() => {
    if (!storeId) return;
    setPage(1);
    void loadRecords(storeId, 1, statusFilter);
    void loadStats(storeId);
  }, [storeId, statusFilter, loadRecords, loadStats]);

  // 分页切换
  const handlePageChange = (p: number) => {
    setPage(p);
    if (storeId) void loadRecords(storeId, p, statusFilter);
  };

  // 取酒操作
  const handleRetrieveOpen = (record: WineStorageRecord) => {
    setRetrieveTarget(record);
    setRetrieveQty(1);
    setRetrieveRemark('');
    setRetrieveVisible(true);
  };

  const handleRetrieveConfirm = async () => {
    if (!retrieveTarget) return;
    setRetrieveLoading(true);
    try {
      await retrieveWine(retrieveTarget.id, retrieveQty, retrieveRemark || undefined);
      message.success('取酒成功');
      setRetrieveVisible(false);
      if (storeId) {
        void loadRecords(storeId, page, statusFilter);
        void loadStats(storeId);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '取酒失败');
    } finally {
      setRetrieveLoading(false);
    }
  };

  // 续存操作
  const handleExtendOpen = (record: WineStorageRecord) => {
    setExtendTarget(record);
    setExtendDays(30);
    setExtendRemark('');
    setExtendVisible(true);
  };

  const handleExtendConfirm = async () => {
    if (!extendTarget) return;
    setExtendLoading(true);
    try {
      await extendWine(extendTarget.id, extendDays, extendRemark || undefined);
      message.success('续存成功');
      setExtendVisible(false);
      if (storeId) {
        void loadRecords(storeId, page, statusFilter);
        void loadStats(storeId);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '续存失败');
    } finally {
      setExtendLoading(false);
    }
  };

  // ─── 表格列定义 ───────────────────────────────────────────────────────────

  const columns: ColumnsType<WineStorageRecord> = [
    {
      title: '客户ID',
      dataIndex: 'customer_id',
      key: 'customer_id',
      width: 160,
      ellipsis: true,
    },
    {
      title: '酒品名称',
      dataIndex: 'wine_name',
      key: 'wine_name',
      width: 140,
    },
    {
      title: '酒类',
      dataIndex: 'wine_category',
      key: 'wine_category',
      width: 80,
    },
    {
      title: '总量',
      dataIndex: 'original_qty',
      key: 'original_qty',
      width: 80,
      render: (val: number, record: WineStorageRecord) =>
        `${val} ${record.unit}`,
    },
    {
      title: '剩余量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 80,
      render: (val: number, record: WineStorageRecord) => (
        <Text
          style={{
            color: val === 0 ? '#A32D2D' : val < (record.original_qty ?? val) ? '#BA7517' : '#0F6E56',
            fontWeight: 600,
          }}
        >
          {val} {record.unit}
        </Text>
      ),
    },
    {
      title: '存入日期',
      dataIndex: 'stored_at',
      key: 'stored_at',
      width: 120,
      render: (val: string) => val ? dayjs(val).format('YYYY-MM-DD') : '-',
    },
    {
      title: '到期日期',
      dataIndex: 'expires_at',
      key: 'expires_at',
      width: 120,
      render: (val: string | null) => {
        if (!val) return '-';
        const isExpiringSoon = dayjs(val).diff(dayjs(), 'day') <= 7;
        const isExpired = dayjs(val).isBefore(dayjs());
        return (
          <Text style={{ color: isExpired ? '#A32D2D' : isExpiringSoon ? '#BA7517' : '#2C2C2A' }}>
            {dayjs(val).format('YYYY-MM-DD')}
          </Text>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: WineStorageStatus) => (
        <Tag color={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Tag>
      ),
    },
    {
      title: '柜位',
      dataIndex: 'cabinet_position',
      key: 'cabinet_position',
      width: 80,
      render: (val: string | null) => val || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      fixed: 'right' as const,
      render: (_: unknown, record: WineStorageRecord) => (
        <Space size={8}>
          <Button
            size="small"
            type="primary"
            disabled={
              record.status !== 'stored' && record.status !== 'partially_retrieved'
            }
            onClick={() => handleRetrieveOpen(record)}
          >
            取酒
          </Button>
          <Button
            size="small"
            disabled={
              record.status === 'fully_retrieved' ||
              record.status === 'transferred' ||
              record.status === 'written_off'
            }
            onClick={() => handleExtendOpen(record)}
          >
            续存
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          存酒管理
        </Title>
        <Text style={{ color: '#5F5E5A', fontSize: 14 }}>
          管理门店客户寄存酒水，支持取酒、续存操作
        </Text>
      </div>

      {/* 即将到期预警 */}
      {expiring.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message={
            <span>
              <Text strong>{expiring.length}</Text> 瓶存酒将在 7 天内到期，请尽快联系客户取酒。
            </span>
          }
          style={{ marginBottom: 16 }}
          closable
        />
      )}

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
              void loadStats(storeId);
            }}
          >
            查询
          </Button>
        </Space>
      </Card>

      {/* 统计卡片 */}
      {summary && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card styles={{ body: { padding: '20px 24px' } }}>
              <Statistic
                title="存储中总量（瓶）"
                value={summary.total_quantity}
                valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card styles={{ body: { padding: '20px 24px' } }}>
              <Statistic
                title="存酒总数（条）"
                value={summary.total_count}
                valueStyle={{ color: '#185FA5', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card styles={{ body: { padding: '20px 24px' } }}>
              <Statistic
                title="即将到期（7天内）"
                value={expiring.length}
                valueStyle={{ color: expiring.length > 0 ? '#BA7517' : '#0F6E56', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card styles={{ body: { padding: '20px 24px' } }}>
              <Statistic
                title="估值总额（元）"
                value={(summary.total_estimated_value_fen / 100).toFixed(2)}
                prefix="¥"
                valueStyle={{ color: '#2C2C2A', fontWeight: 700 }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 主表格 */}
      <Card title="存酒记录">
        {!storeId && (
          <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
            请先选择门店以查看存酒记录
          </div>
        )}
        {storeId && (
          <Table<WineStorageRecord>
            columns={columns}
            dataSource={records}
            rowKey="id"
            loading={loading}
            scroll={{ x: 1200 }}
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
      </Card>

      {/* 取酒 Modal */}
      <Modal
        title={`取酒 — ${retrieveTarget?.wine_name ?? ''}`}
        open={retrieveVisible}
        onCancel={() => setRetrieveVisible(false)}
        onOk={handleRetrieveConfirm}
        confirmLoading={retrieveLoading}
        okText="确认取酒"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        width={480}
        destroyOnClose
      >
        {retrieveTarget && (
          <div>
            <div style={{ background: '#F8F7F5', borderRadius: 6, padding: '12px 16px', marginBottom: 16 }}>
              <div><Text type="secondary">酒品：</Text><Text strong>{retrieveTarget.wine_name}</Text></div>
              <div><Text type="secondary">类型：</Text><Text>{retrieveTarget.wine_category}</Text></div>
              <div>
                <Text type="secondary">当前剩余：</Text>
                <Text strong style={{ color: '#0F6E56' }}>
                  {retrieveTarget.quantity} {retrieveTarget.unit}
                </Text>
              </div>
            </div>
            <Form layout="vertical">
              <Form.Item label="取出数量" required>
                <InputNumber
                  min={0.1}
                  max={retrieveTarget.quantity}
                  step={0.1}
                  value={retrieveQty}
                  onChange={(val) => setRetrieveQty(val ?? 1)}
                  style={{ width: '100%' }}
                  addonAfter={retrieveTarget.unit}
                />
              </Form.Item>
              <Form.Item label="备注（可选）">
                <input
                  value={retrieveRemark}
                  onChange={(e) => setRetrieveRemark(e.target.value)}
                  placeholder="备注信息"
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

      {/* 续存 Modal */}
      <Modal
        title={`续存 — ${extendTarget?.wine_name ?? ''}`}
        open={extendVisible}
        onCancel={() => setExtendVisible(false)}
        onOk={handleExtendConfirm}
        confirmLoading={extendLoading}
        okText="确认续存"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        width={480}
        destroyOnClose
      >
        {extendTarget && (
          <div>
            <div style={{ background: '#F8F7F5', borderRadius: 6, padding: '12px 16px', marginBottom: 16 }}>
              <div><Text type="secondary">酒品：</Text><Text strong>{extendTarget.wine_name}</Text></div>
              <div>
                <Text type="secondary">当前到期日：</Text>
                <Text strong>
                  {extendTarget.expires_at
                    ? dayjs(extendTarget.expires_at).format('YYYY-MM-DD')
                    : '未设置'}
                </Text>
              </div>
            </div>
            <Form layout="vertical">
              <Form.Item label="延长天数" required>
                <InputNumber
                  min={1}
                  max={365}
                  value={extendDays}
                  onChange={(val) => setExtendDays(val ?? 30)}
                  style={{ width: '100%' }}
                  addonAfter="天"
                />
              </Form.Item>
              {extendTarget.expires_at && (
                <div style={{ color: '#5F5E5A', fontSize: 13, marginBottom: 12 }}>
                  续存后到期日：
                  <Text strong>
                    {dayjs(extendTarget.expires_at).add(extendDays, 'day').format('YYYY-MM-DD')}
                  </Text>
                </div>
              )}
              <Form.Item label="备注（可选）">
                <input
                  value={extendRemark}
                  onChange={(e) => setExtendRemark(e.target.value)}
                  placeholder="备注信息"
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
    </div>
  );
}
