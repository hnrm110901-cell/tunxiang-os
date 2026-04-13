/**
 * 成本管理页面 — CostManagePage
 *
 * Tabs：
 *   Tab1 成本总览  — 月份筛选 + 成本结构（Progress条） + 汇总卡片
 *   Tab2 成本明细  — 门店+日期筛选 + 成本明细表格 + 录入成本弹窗
 *   Tab3 财务配置  — 查看/设置门店成本目标比率和固定费用
 *
 * API：
 *   GET  /api/v1/finance/costs/summary   — 成本结构汇总
 *   GET  /api/v1/finance/costs           — 成本明细列表
 *   POST /api/v1/finance/costs           — 录入成本记录
 *   GET  /api/v1/finance/configs/{store} — 财务配置
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
  Progress,
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
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  COST_TYPE_COLOR,
  COST_TYPE_LABEL,
  type CostItem,
  type CostSummary,
  type CostType,
  type FinanceConfigItem,
  createCostItem,
  getCostItems,
  getCostSummary,
  getStoreFinanceConfigs,
} from '../../api/costApi';
import { txFetchData } from '../../api';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text, Paragraph } = Typography;

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function fenToWan(fen: number): string {
  return (fen / 1000000).toFixed(2);
}

// ─── 常量 ──────────────────────────────────────────────────────────────────────

const COST_TYPE_OPTIONS = Object.entries(COST_TYPE_LABEL).map(([value, label]) => ({
  value,
  label,
}));

const CONFIG_TYPE_LABELS: Record<string, string> = {
  labor_cost_pct: '人力成本目标比率',
  rent_monthly_fen: '月租金',
  utilities_daily_fen: '日水电预算',
  target_food_cost_pct: '食材成本目标比率',
  other_daily_opex_fen: '日其他运营费',
};

// ─── 子组件：成本结构卡片 ──────────────────────────────────────────────────────

function CostStructureCard({ summary, loading }: { summary: CostSummary | null; loading: boolean }) {
  if (loading) {
    return (
      <Card title="成本结构分布" style={{ marginBottom: 24 }}>
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin />
        </div>
      </Card>
    );
  }

  if (!summary || summary.breakdown.length === 0) {
    return (
      <Card title="成本结构分布" style={{ marginBottom: 24 }}>
        <Text type="secondary">暂无数据，请先选择门店和月份查询</Text>
      </Card>
    );
  }

  return (
    <Card title="成本结构分布" style={{ marginBottom: 24 }}>
      <Row gutter={[16, 16]}>
        {summary.breakdown.map((item) => (
          <Col span={24} key={item.cost_type}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
              <div style={{ width: 90, flexShrink: 0 }}>
                <Tag color={COST_TYPE_COLOR[item.cost_type as CostType] || 'default'} style={{ fontSize: 12 }}>
                  {COST_TYPE_LABEL[item.cost_type as CostType] || item.cost_type}
                </Tag>
              </div>
              <div style={{ flex: 1 }}>
                <Progress
                  percent={Math.round(item.ratio * 100)}
                  strokeColor={COST_TYPE_COLOR[item.cost_type as CostType] || '#999'}
                  format={() => `${(item.ratio * 100).toFixed(1)}%`}
                  size="small"
                />
              </div>
              <div style={{ width: 110, textAlign: 'right', flexShrink: 0 }}>
                <Text style={{ fontSize: 13 }}>¥{fenToYuan(item.amount_fen)}</Text>
              </div>
            </div>
          </Col>
        ))}
        <Col span={24}>
          <div style={{
            borderTop: '1px solid #E8E6E1',
            paddingTop: 12,
            marginTop: 8,
            display: 'flex',
            justifyContent: 'space-between',
          }}>
            <Text strong>总成本</Text>
            <Text strong style={{ color: '#FF6B35', fontSize: 16 }}>
              ¥{fenToYuan(summary.total_cost_fen)}
            </Text>
          </div>
        </Col>
      </Row>
    </Card>
  );
}

// ─── 子组件：成本总览汇总卡片 ─────────────────────────────────────────────────

function CostSummaryCards({
  summary,
  loading,
}: {
  summary: CostSummary | null;
  loading: boolean;
}) {
  if (!summary && !loading) return null;

  // 从 breakdown 中提取各类成本
  const getAmount = (type: CostType) =>
    summary?.breakdown.find((b) => b.cost_type === type)?.amount_fen ?? 0;

  const foodCost =
    getAmount('purchase') + getAmount('wastage') + getAmount('live_seafood_death');
  const laborCost = getAmount('labor');
  const rentCost = getAmount('rent');
  const utilitiesCost = getAmount('utilities');
  const otherCost = getAmount('other');
  const totalCost = summary?.total_cost_fen ?? 0;

  return (
    <Spin spinning={loading}>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card size="small" style={{ borderColor: '#E8E6E1' }}>
            <Statistic
              title="食材成本合计"
              value={foodCost / 100}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#FF6B35' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ borderColor: '#E8E6E1' }}>
            <Statistic
              title="人力成本"
              value={laborCost / 100}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#185FA5' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ borderColor: '#E8E6E1' }}>
            <Statistic
              title="房租 + 水电"
              value={(rentCost + utilitiesCost) / 100}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#0F6E56' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ borderColor: '#E8E6E1' }}>
            <Statistic
              title="其他成本"
              value={otherCost / 100}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#5F5E5A' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ background: '#F8F7F5', borderColor: '#FF6B35' }}>
            <Statistic
              title="总成本"
              value={totalCost / 100}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#FF6B35', fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ borderColor: '#E8E6E1' }}>
            <div style={{ fontSize: 12, color: '#5F5E5A', marginBottom: 4 }}>总成本（万元）</div>
            <div style={{ fontSize: 22, fontWeight: 600, color: '#2C2C2A' }}>
              {fenToWan(totalCost)} <span style={{ fontSize: 14, color: '#5F5E5A' }}>万</span>
            </div>
          </Card>
        </Col>
      </Row>
    </Spin>
  );
}

// ─── Tab1：成本总览 ────────────────────────────────────────────────────────────

function CostOverviewTab({
  stores,
}: {
  stores: Array<{ value: string; label: string }>;
}) {
  const [storeId, setStoreId] = useState<string | undefined>();
  const [month, setMonth] = useState<string>(dayjs().format('YYYY-MM'));
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleQuery = useCallback(async () => {
    if (!storeId) {
      setError('请先选择门店');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [year, mon] = month.split('-');
      const startDate = `${year}-${mon}-01`;
      const lastDay = dayjs(month).endOf('month').format('YYYY-MM-DD');
      const data = await getCostSummary({ storeId, startDate, endDate: lastDay });
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败，请重试');
    } finally {
      setLoading(false);
    }
  }, [storeId, month]);

  return (
    <div>
      {/* 筛选区 */}
      <Card style={{ marginBottom: 24 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12} wrap>
          <Select
            placeholder="选择门店"
            options={stores}
            value={storeId}
            onChange={setStoreId}
            style={{ width: 200 }}
            allowClear
          />
          <DatePicker
            picker="month"
            value={dayjs(month)}
            onChange={(_, dateStr) => setMonth(Array.isArray(dateStr) ? dateStr[0] : dateStr)}
            style={{ width: 160 }}
          />
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            onClick={handleQuery}
            loading={loading}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            查询
          </Button>
        </Space>
        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            style={{ marginTop: 12 }}
            closable
            onClose={() => setError(null)}
          />
        )}
      </Card>

      {/* 汇总卡片 */}
      <CostSummaryCards summary={summary} loading={loading} />

      {/* 成本结构饼图（Progress条） */}
      <CostStructureCard summary={summary} loading={loading} />
    </div>
  );
}

// ─── Tab2：成本明细 ────────────────────────────────────────────────────────────

function CostDetailTab({
  stores,
}: {
  stores: Array<{ value: string; label: string }>;
}) {
  const [storeId, setStoreId] = useState<string | undefined>();
  const [date, setDate] = useState<string>(dayjs().format('YYYY-MM-DD'));
  const [costType, setCostType] = useState<CostType | undefined>();
  const [items, setItems] = useState<CostItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const loadItems = useCallback(async (p = 1) => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getCostItems({ storeId, date, costType, page: p, size: 20 });
      setItems(res.items);
      setTotal(res.total);
      setPage(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId, date, costType]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      await createCostItem({
        store_id: storeId!,
        cost_date: date,
        cost_type: values.cost_type,
        description: values.description,
        amount_fen: Math.round(values.amount_yuan * 100),
        quantity: values.quantity,
        unit: values.unit,
      });
      message.success('录入成功');
      form.resetFields();
      setModalOpen(false);
      void loadItems(1);
    } catch (err) {
      if (err instanceof Error) message.error(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnsType<CostItem> = [
    {
      title: '日期',
      dataIndex: 'cost_date',
      width: 110,
    },
    {
      title: '成本类型',
      dataIndex: 'cost_type',
      width: 110,
      render: (type: CostType) => (
        <Tag color={COST_TYPE_COLOR[type] || 'default'} style={{ fontSize: 12 }}>
          {COST_TYPE_LABEL[type] || type}
        </Tag>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      render: (val: string | null) => val ?? '-',
    },
    {
      title: '金额（元）',
      dataIndex: 'amount_fen',
      width: 120,
      align: 'right',
      sorter: (a, b) => a.amount_fen - b.amount_fen,
      render: (val: number) => <Text strong>¥{fenToYuan(val)}</Text>,
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      width: 80,
      render: (val: number | null, record) =>
        val != null ? `${val}${record.unit ?? ''}` : '-',
    },
    {
      title: '单位成本',
      dataIndex: 'unit_cost_fen',
      width: 110,
      render: (val: number | null) => (val != null ? `¥${fenToYuan(val)}` : '-'),
    },
    {
      title: '录入时间',
      dataIndex: 'created_at',
      width: 160,
      render: (val: string) => val.slice(0, 16).replace('T', ' '),
    },
  ];

  return (
    <div>
      {/* 筛选区 */}
      <Card style={{ marginBottom: 24 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12} wrap>
          <Select
            placeholder="选择门店"
            options={stores}
            value={storeId}
            onChange={(v) => setStoreId(v)}
            style={{ width: 200 }}
            allowClear
          />
          <DatePicker
            value={dayjs(date)}
            onChange={(_, dateStr) => setDate(Array.isArray(dateStr) ? dateStr[0] : dateStr)}
            style={{ width: 160 }}
          />
          <Select
            placeholder="成本类型（全部）"
            options={[{ value: '', label: '全部类型' }, ...COST_TYPE_OPTIONS]}
            value={costType ?? ''}
            onChange={(v) => setCostType((v || undefined) as CostType | undefined)}
            style={{ width: 160 }}
          />
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            onClick={() => void loadItems(1)}
            loading={loading}
            disabled={!storeId}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            查询
          </Button>
          <Button
            icon={<PlusOutlined />}
            onClick={() => {
              if (!storeId) { message.warning('请先选择门店'); return; }
              setModalOpen(true);
            }}
          >
            录入成本
          </Button>
        </Space>
        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            style={{ marginTop: 12 }}
            closable
            onClose={() => setError(null)}
          />
        )}
      </Card>

      {/* 明细表格 */}
      <Card>
        <Table<CostItem>
          columns={columns}
          dataSource={items}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize: 20,
            total,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => void loadItems(p),
          }}
          size="small"
          locale={{ emptyText: storeId ? '暂无数据' : '请先选择门店并点击查询' }}
        />
      </Card>

      {/* 录入成本 Modal */}
      <Modal
        title="录入成本记录"
        open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText="确认录入"
        cancelText="取消"
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="cost_type" label="成本类型" rules={[{ required: true }]}>
            <Select options={COST_TYPE_OPTIONS} placeholder="选择成本类型" />
          </Form.Item>
          <Form.Item name="amount_yuan" label="金额（元）" rules={[{ required: true, message: '请输入金额' }]}>
            <InputNumber
              min={0}
              precision={2}
              style={{ width: '100%' }}
              placeholder="输入成本金额（元）"
              prefix="¥"
            />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="quantity" label="数量（可选）">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="如 50" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="unit" label="单位（可选）">
                <Select
                  options={[
                    { value: 'kg', label: 'kg' },
                    { value: 'g', label: 'g' },
                    { value: '个', label: '个' },
                    { value: '份', label: '份' },
                    { value: '箱', label: '箱' },
                    { value: '次', label: '次' },
                  ]}
                  allowClear
                  placeholder="单位"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="description" label="描述（可选）">
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[]}
              maxCount={1}
              placeholder="输入简短描述，如：2026-03月租"
              onChange={(vals: string[]) => form.setFieldValue('description', vals[0] ?? '')}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ─── Tab3：财务配置 ────────────────────────────────────────────────────────────

function FinanceConfigTab({
  stores,
}: {
  stores: Array<{ value: string; label: string }>;
}) {
  const [storeId, setStoreId] = useState<string | undefined>();
  const [configs, setConfigs] = useState<FinanceConfigItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadConfigs = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getStoreFinanceConfigs(storeId);
      setConfigs(data.configs);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  const columns: ColumnsType<FinanceConfigItem> = [
    {
      title: '配置项',
      dataIndex: 'config_type',
      render: (type: string) => CONFIG_TYPE_LABELS[type] ?? type,
    },
    {
      title: '金额值（元）',
      dataIndex: 'value_fen',
      render: (val: number | null) => (val != null ? `¥${fenToYuan(val)}` : '-'),
    },
    {
      title: '比率值',
      dataIndex: 'value_pct',
      render: (val: number | null) => (val != null ? `${val}%` : '-'),
    },
    {
      title: '生效日期',
      dataIndex: 'effective_from',
      render: (val: string | null) => val ?? '长期有效',
    },
    {
      title: '失效日期',
      dataIndex: 'effective_until',
      render: (val: string | null) => val ?? '-',
    },
    {
      title: '范围',
      dataIndex: 'scope',
      render: (scope: string) => (
        <Tag color={scope === 'store' ? 'blue' : 'default'}>
          {scope === 'store' ? '门店专属' : '集团通用'}
        </Tag>
      ),
    },
  ];

  return (
    <div>
      <Card style={{ marginBottom: 24 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12}>
          <Select
            placeholder="选择门店"
            options={stores}
            value={storeId}
            onChange={(v) => setStoreId(v)}
            style={{ width: 200 }}
            allowClear
          />
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            onClick={loadConfigs}
            loading={loading}
            disabled={!storeId}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            查询配置
          </Button>
        </Space>
        {error && (
          <Alert type="error" message={error} showIcon style={{ marginTop: 12 }} closable onClose={() => setError(null)} />
        )}
      </Card>

      <Card>
        <Table<FinanceConfigItem>
          columns={columns}
          dataSource={configs}
          rowKey="id"
          loading={loading}
          pagination={false}
          size="small"
          locale={{ emptyText: storeId ? '暂无配置数据' : '请先选择门店' }}
        />
      </Card>
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function CostManagePage() {
  const [stores, setStores] = useState<Array<{ value: string; label: string }>>([]);

  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((data) => setStores((data.items ?? []).map((s) => ({ value: s.id, label: s.name }))))
      .catch(() => setStores([]));
  }, []);

  const tabItems = [
    {
      key: 'overview',
      label: '成本总览',
      children: <CostOverviewTab stores={stores} />,
    },
    {
      key: 'detail',
      label: '成本明细',
      children: <CostDetailTab stores={stores} />,
    },
    {
      key: 'config',
      label: '财务配置',
      children: <FinanceConfigTab stores={stores} />,
    },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          成本管理
        </Title>
        <Paragraph style={{ color: '#5F5E5A', margin: '8px 0 0', fontSize: 14 }}>
          门店成本结构分析、明细录入与财务配置管理。金额单位为元，底层存储为分（×100）。
        </Paragraph>
      </div>

      <Tabs
        defaultActiveKey="overview"
        items={tabItems}
        style={{ background: '#fff', padding: '0 24px 24px', borderRadius: 6 }}
      />
    </div>
  );
}
