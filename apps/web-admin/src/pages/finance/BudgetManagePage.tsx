/**
 * 预算管理页面 — BudgetManagePage
 *
 * Tabs：
 *   Tab1 预算计划  — 年度12个月预算列表 + 新建/编辑 Modal
 *   Tab2 执行对比  — 月份选择 + 预算vs实际对比表（含Progress完成率）
 *   Tab3 批量下发  — 复制源门店预算 → 下发到多个目标门店
 *
 * API：
 *   GET  /api/v1/finance/budget              — 年度预算列表
 *   POST /api/v1/finance/budget              — 创建/更新月度预算
 *   GET  /api/v1/finance/budget/execution    — 预算执行情况
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
import { EditOutlined, PlusOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  EXECUTION_STATUS_COLOR,
  EXECUTION_STATUS_LABEL,
  type BudgetExecution,
  type MonthlyBudget,
  createOrUpdateMonthlyBudget,
  getBudgetExecution,
  listAnnualBudgets,
} from '../../api/budgetApi';
import { txFetchData } from '../../api';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text, Paragraph } = Typography;

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number | null | undefined): string {
  if (fen == null) return '-';
  return (fen / 100).toFixed(2);
}

function yuanToFen(yuan: number): number {
  return Math.round(yuan * 100);
}

const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

// ─── Tab1：预算计划 ────────────────────────────────────────────────────────────

function BudgetPlanTab({
  stores,
}: {
  stores: Array<{ value: string; label: string }>;
}) {
  const [storeId, setStoreId] = useState<string | undefined>();
  const [year, setYear] = useState(dayjs().year());
  const [budgets, setBudgets] = useState<MonthlyBudget[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingMonth, setEditingMonth] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  // 将列表数据转为按月索引的 map
  const budgetMap: Record<string, MonthlyBudget> = {};
  budgets.forEach((b) => {
    budgetMap[b.period] = b;
  });

  const loadBudgets = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listAnnualBudgets({ storeId, year });
      setBudgets(res.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId, year]);

  const openEdit = (month: number) => {
    const period = `${year}-${String(month).padStart(2, '0')}`;
    const existing = budgetMap[period];
    setEditingMonth(month);
    form.setFieldsValue({
      revenue_target_yuan: existing?.revenue_target_fen != null
        ? existing.revenue_target_fen / 100 : undefined,
      cost_budget_yuan: existing?.cost_budget_fen != null
        ? existing.cost_budget_fen / 100 : undefined,
      labor_budget_yuan: existing?.labor_budget_fen != null
        ? existing.labor_budget_fen / 100 : undefined,
      note: '',
    });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    if (!storeId || editingMonth == null) return;
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      await createOrUpdateMonthlyBudget({
        store_id: storeId,
        year,
        month: editingMonth,
        revenue_target_fen: yuanToFen(values.revenue_target_yuan),
        cost_budget_fen: yuanToFen(values.cost_budget_yuan),
        labor_budget_fen: yuanToFen(values.labor_budget_yuan),
        note: values.note,
      });
      message.success(`${year}年${editingMonth}月预算已保存`);
      setModalOpen(false);
      form.resetFields();
      void loadBudgets();
    } catch (err) {
      if (err instanceof Error) message.error(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  // 计算年度合计
  const totalRevenue = budgets.reduce((s, b) => s + (b.revenue_target_fen ?? 0), 0);
  const totalCost = budgets.reduce((s, b) => s + (b.cost_budget_fen ?? 0), 0);
  const totalLabor = budgets.reduce((s, b) => s + (b.labor_budget_fen ?? 0), 0);

  // 构造12行表格数据（无预算的月份也显示）
  interface MonthRow extends MonthlyBudget { month: number; }
  const tableData: MonthRow[] = MONTHS.map((m) => {
    const period = `${year}-${String(m).padStart(2, '0')}`;
    return { month: m, period, ...(budgetMap[period] ?? { revenue_target_fen: null, cost_budget_fen: null, labor_budget_fen: null, status: null }) };
  });

  const columns: ColumnsType<MonthRow> = [
    {
      title: '月份',
      dataIndex: 'month',
      width: 60,
      render: (m: number) => <Text strong>{m}月</Text>,
    },
    {
      title: '营收目标（元）',
      dataIndex: 'revenue_target_fen',
      align: 'right',
      render: (val: number | null) =>
        val != null ? <Text>¥{fenToYuan(val)}</Text> : <Text type="secondary">未设置</Text>,
    },
    {
      title: '食材成本预算（元）',
      dataIndex: 'cost_budget_fen',
      align: 'right',
      render: (val: number | null) =>
        val != null ? <Text>¥{fenToYuan(val)}</Text> : <Text type="secondary">未设置</Text>,
    },
    {
      title: '人力成本预算（元）',
      dataIndex: 'labor_budget_fen',
      align: 'right',
      render: (val: number | null) =>
        val != null ? <Text>¥{fenToYuan(val)}</Text> : <Text type="secondary">未设置</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string | null) => {
        if (!status) return <Tag color="default">未设置</Tag>;
        const colorMap: Record<string, string> = {
          draft: 'default',
          approved: 'green',
          published: 'blue',
        };
        return <Tag color={colorMap[status] ?? 'default'}>{status}</Tag>;
      },
    },
    {
      title: '操作',
      width: 80,
      render: (_, record) => (
        <Button
          size="small"
          type="link"
          icon={<EditOutlined />}
          onClick={() => {
            if (!storeId) { message.warning('请先选择门店'); return; }
            openEdit(record.month);
          }}
        >
          {record.revenue_target_fen != null ? '编辑' : '设置'}
        </Button>
      ),
    },
  ];

  // 合计行
  const summaryRow = (): React.ReactNode => (
    <Table.Summary fixed>
      <Table.Summary.Row style={{ background: '#F8F7F5', fontWeight: 600 }}>
        <Table.Summary.Cell index={0}>年度合计</Table.Summary.Cell>
        <Table.Summary.Cell index={1} align="right">
          <Text strong style={{ color: '#FF6B35' }}>¥{fenToYuan(totalRevenue)}</Text>
        </Table.Summary.Cell>
        <Table.Summary.Cell index={2} align="right">
          <Text strong>¥{fenToYuan(totalCost)}</Text>
        </Table.Summary.Cell>
        <Table.Summary.Cell index={3} align="right">
          <Text strong>¥{fenToYuan(totalLabor)}</Text>
        </Table.Summary.Cell>
        <Table.Summary.Cell index={4} />
        <Table.Summary.Cell index={5} />
      </Table.Summary.Row>
    </Table.Summary>
  );

  return (
    <div>
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
            picker="year"
            value={dayjs(String(year))}
            onChange={(_, dateStr) => setYear(Number(Array.isArray(dateStr) ? dateStr[0] : dateStr))}
            style={{ width: 120 }}
          />
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            onClick={loadBudgets}
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
              openEdit(dayjs().month() + 1);
            }}
          >
            新建预算
          </Button>
        </Space>
        {error && (
          <Alert type="error" message={error} showIcon style={{ marginTop: 12 }} closable onClose={() => setError(null)} />
        )}
      </Card>

      <Card>
        <Table<MonthRow>
          columns={columns}
          dataSource={tableData}
          rowKey="month"
          loading={loading}
          pagination={false}
          size="small"
          summary={summaryRow}
          locale={{ emptyText: '请先选择门店并点击查询' }}
        />
      </Card>

      <Modal
        title={`${year}年${editingMonth}月预算设置`}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText="保存预算"
        cancelText="取消"
        width={480}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="revenue_target_yuan"
            label="营收目标（元）"
            rules={[{ required: true, message: '请输入营收目标' }]}
          >
            <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" placeholder="如 500000.00" />
          </Form.Item>
          <Form.Item
            name="cost_budget_yuan"
            label="食材成本预算（元）"
            rules={[{ required: true, message: '请输入食材成本预算' }]}
          >
            <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" placeholder="如 150000.00" />
          </Form.Item>
          <Form.Item
            name="labor_budget_yuan"
            label="人力成本预算（元）"
            rules={[{ required: true, message: '请输入人力成本预算' }]}
          >
            <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" placeholder="如 80000.00" />
          </Form.Item>
          <Form.Item name="note" label="备注（可选）">
            <Select
              mode="tags"
              open={false}
              maxCount={1}
              tokenSeparators={[]}
              placeholder="输入备注说明"
              onChange={(vals: string[]) => form.setFieldValue('note', vals[0] ?? '')}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ─── Tab2：执行对比 ────────────────────────────────────────────────────────────

interface ExecutionRow {
  storeId: string;
  storeName: string;
  execution: BudgetExecution | null;
  loading: boolean;
  error: string | null;
}

function BudgetExecutionTab({
  stores,
}: {
  stores: Array<{ value: string; label: string }>;
}) {
  const [selectedStores, setSelectedStores] = useState<string[]>([]);
  const [year, setYear] = useState(dayjs().year());
  const [month, setMonth] = useState(dayjs().month() + 1);
  const [rows, setRows] = useState<ExecutionRow[]>([]);
  const [querying, setQuerying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleQuery = useCallback(async () => {
    if (selectedStores.length === 0) {
      setError('请选择至少一家门店');
      return;
    }
    setQuerying(true);
    setError(null);

    const initRows: ExecutionRow[] = selectedStores.map((sid) => ({
      storeId: sid,
      storeName: stores.find((s) => s.value === sid)?.label ?? sid,
      execution: null,
      loading: true,
      error: null,
    }));
    setRows(initRows);

    await Promise.all(
      selectedStores.map(async (sid, idx) => {
        try {
          const data = await getBudgetExecution({ storeId: sid, year, month });
          setRows((prev) => prev.map((r, i) => i === idx ? { ...r, execution: data, loading: false } : r));
        } catch (err) {
          setRows((prev) =>
            prev.map((r, i) =>
              i === idx
                ? { ...r, loading: false, error: err instanceof Error ? err.message : '加载失败' }
                : r,
            ),
          );
        }
      }),
    );

    setQuerying(false);
  }, [selectedStores, year, month, stores]);

  // 完成率颜色
  const rateColor = (rate: number) => {
    if (rate >= 1.0) return '#0F6E56';   // ≥100% 绿
    if (rate >= 0.8) return '#185FA5';   // 80-100% 蓝
    return '#A32D2D';                    // <80% 红
  };

  const rateStrokeColor = (rate: number) => {
    if (rate >= 1.0) return '#0F6E56';
    if (rate >= 0.8) return '#185FA5';
    return '#A32D2D';
  };

  const columns: ColumnsType<ExecutionRow> = [
    {
      title: '门店',
      dataIndex: 'storeName',
      width: 150,
      render: (name: string, record) => (
        record.loading ? <Spin size="small" /> : <Text strong>{name}</Text>
      ),
    },
    {
      title: '营收目标（元）',
      align: 'right',
      render: (_, record) =>
        record.execution ? `¥${fenToYuan(record.execution.budget.revenue_target_fen)}` : '-',
    },
    {
      title: '实际营收（元）',
      align: 'right',
      render: (_, record) =>
        record.execution ? `¥${fenToYuan(record.execution.actual.revenue_fen)}` : '-',
    },
    {
      title: '营收完成率',
      width: 180,
      render: (_, record) => {
        if (!record.execution) return '-';
        const rate = record.execution.execution_rate;
        const pct = Math.round(rate * 100);
        return (
          <div style={{ minWidth: 140 }}>
            <Progress
              percent={Math.min(pct, 100)}
              strokeColor={rateStrokeColor(rate)}
              format={() => (
                <span style={{ color: rateColor(rate), fontWeight: 600, fontSize: 12 }}>
                  {pct}%
                </span>
              )}
              size="small"
            />
          </div>
        );
      },
    },
    {
      title: '食材成本预算（元）',
      align: 'right',
      render: (_, record) =>
        record.execution ? `¥${fenToYuan(record.execution.budget.cost_budget_fen)}` : '-',
    },
    {
      title: '实际食材成本（元）',
      align: 'right',
      render: (_, record) => {
        if (!record.execution) return '-';
        const over = record.execution.variance.cost_over_budget;
        return (
          <Text style={{ color: over ? '#A32D2D' : '#0F6E56' }}>
            ¥{fenToYuan(record.execution.actual.food_cost_fen)}
            {over && <Tag color="red" style={{ marginLeft: 6, fontSize: 11 }}>超预算</Tag>}
          </Text>
        );
      },
    },
    {
      title: '执行状态',
      width: 100,
      render: (_, record) => {
        if (!record.execution) return '-';
        const { execution_status } = record.execution;
        return (
          <Tag color={EXECUTION_STATUS_COLOR[execution_status]}>
            {EXECUTION_STATUS_LABEL[execution_status]}
          </Tag>
        );
      },
    },
    {
      title: '异常提示',
      render: (_, record) => {
        if (record.error) return <Text type="danger">{record.error}</Text>;
        if (!record.execution) return '-';
        const { variance } = record.execution;
        const warnings = [];
        if (variance.cost_over_budget) warnings.push('食材超预算');
        if (variance.labor_over_budget) warnings.push('人力超预算');
        if (warnings.length === 0) return <Text style={{ color: '#0F6E56' }}>正常</Text>;
        return warnings.map((w) => <Tag key={w} color="orange">{w}</Tag>);
      },
    },
  ];

  return (
    <div>
      <Card style={{ marginBottom: 24 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12} wrap>
          <Select
            mode="multiple"
            placeholder="选择对比门店（可多选）"
            options={stores}
            value={selectedStores}
            onChange={setSelectedStores}
            style={{ minWidth: 280 }}
            maxTagCount={3}
          />
          <DatePicker
            picker="year"
            value={dayjs(String(year))}
            onChange={(_, dateStr) => setYear(Number(Array.isArray(dateStr) ? dateStr[0] : dateStr))}
            style={{ width: 120 }}
          />
          <Select
            value={month}
            onChange={setMonth}
            style={{ width: 100 }}
            options={MONTHS.map((m) => ({ value: m, label: `${m}月` }))}
          />
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            onClick={handleQuery}
            loading={querying}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            对比查询
          </Button>
        </Space>
        {error && (
          <Alert type="error" message={error} showIcon style={{ marginTop: 12 }} closable onClose={() => setError(null)} />
        )}
      </Card>

      {rows.length > 0 && (
        <Card>
          <Table<ExecutionRow>
            columns={columns}
            dataSource={rows}
            rowKey="storeId"
            pagination={false}
            size="small"
          />
        </Card>
      )}

      {rows.length === 0 && (
        <Card>
          <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
            请选择门店并点击「对比查询」
          </div>
        </Card>
      )}
    </div>
  );
}

// ─── Tab3：批量下发 ────────────────────────────────────────────────────────────

function BudgetDispatchTab({
  stores,
}: {
  stores: Array<{ value: string; label: string }>;
}) {
  const [sourceStoreId, setSourceStoreId] = useState<string | undefined>();
  const [targetStoreIds, setTargetStoreIds] = useState<string[]>([]);
  const [year, setYear] = useState(dayjs().year());
  const [sourcebudgets, setSourceBudgets] = useState<MonthlyBudget[]>([]);
  const [loadingSource, setLoadingSource] = useState(false);
  const [dispatching, setDispatching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const loadSourceBudgets = useCallback(async () => {
    if (!sourceStoreId) return;
    setLoadingSource(true);
    setError(null);
    try {
      const res = await listAnnualBudgets({ storeId: sourceStoreId, year });
      setSourceBudgets(res.items.filter((b) => b.revenue_target_fen != null));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载源预算失败');
    } finally {
      setLoadingSource(false);
    }
  }, [sourceStoreId, year]);

  const handleDispatch = async () => {
    if (!sourceStoreId || targetStoreIds.length === 0) {
      setError('请选择源门店和目标门店');
      return;
    }
    if (sourcebudgets.length === 0) {
      setError('源门店暂无预算数据，请先查询');
      return;
    }

    setDispatching(true);
    setError(null);
    let successCount = 0;
    let failCount = 0;

    try {
      for (const targetId of targetStoreIds) {
        for (const budget of sourcebudgets) {
          const [yr, mon] = budget.period.split('-');
          try {
            await createOrUpdateMonthlyBudget({
              store_id: targetId,
              year: Number(yr),
              month: Number(mon),
              revenue_target_fen: budget.revenue_target_fen ?? 0,
              cost_budget_fen: budget.cost_budget_fen ?? 0,
              labor_budget_fen: budget.labor_budget_fen ?? 0,
            });
            successCount++;
          } catch {
            failCount++;
          }
        }
      }

      if (failCount === 0) {
        message.success(`已成功向 ${targetStoreIds.length} 家门店下发 ${sourcebudgets.length} 个月度预算`);
      } else {
        message.warning(`下发完成，成功 ${successCount} 条，失败 ${failCount} 条`);
      }
      setPreviewOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '下发失败');
    } finally {
      setDispatching(false);
    }
  };

  const previewColumns: ColumnsType<MonthlyBudget> = [
    { title: '月份', dataIndex: 'period', width: 100 },
    {
      title: '营收目标（元）',
      dataIndex: 'revenue_target_fen',
      align: 'right',
      render: (val: number | null) => (val != null ? `¥${fenToYuan(val)}` : '-'),
    },
    {
      title: '食材成本预算（元）',
      dataIndex: 'cost_budget_fen',
      align: 'right',
      render: (val: number | null) => (val != null ? `¥${fenToYuan(val)}` : '-'),
    },
    {
      title: '人力成本预算（元）',
      dataIndex: 'labor_budget_fen',
      align: 'right',
      render: (val: number | null) => (val != null ? `¥${fenToYuan(val)}` : '-'),
    },
  ];

  const targetStoreNames = targetStoreIds
    .map((id) => stores.find((s) => s.value === id)?.label ?? id)
    .join('、');

  return (
    <div>
      <Card style={{ marginBottom: 24 }} styles={{ body: { padding: '20px 24px' } }}>
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <Alert
              type="info"
              message="批量下发预算：将源门店的预算方案复制到多家目标门店，已有预算将被覆盖。"
              showIcon
              style={{ marginBottom: 16 }}
            />
          </Col>
          <Col span={24}>
            <Space size={12} wrap>
              <div>
                <div style={{ fontSize: 12, color: '#5F5E5A', marginBottom: 4 }}>① 选择源门店</div>
                <Select
                  placeholder="选择预算来源门店"
                  options={stores}
                  value={sourceStoreId}
                  onChange={(v) => { setSourceStoreId(v); setSourceBudgets([]); }}
                  style={{ width: 200 }}
                  allowClear
                />
              </div>
              <div>
                <div style={{ fontSize: 12, color: '#5F5E5A', marginBottom: 4 }}>② 选择年份</div>
                <DatePicker
                  picker="year"
                  value={dayjs(String(year))}
                  onChange={(_, dateStr) => setYear(Number(Array.isArray(dateStr) ? dateStr[0] : dateStr))}
                  style={{ width: 120 }}
                />
              </div>
              <div style={{ alignSelf: 'flex-end' }}>
                <Button
                  icon={<ReloadOutlined />}
                  onClick={loadSourceBudgets}
                  loading={loadingSource}
                  disabled={!sourceStoreId}
                >
                  读取预算
                </Button>
              </div>
            </Space>
          </Col>

          {sourcebudgets.length > 0 && (
            <Col span={24}>
              <Card
                size="small"
                title={`${stores.find((s) => s.value === sourceStoreId)?.label ?? '源门店'} · ${year}年预算（共${sourcebudgets.length}个月）`}
                style={{ background: '#F8F7F5', marginBottom: 16 }}
              >
                <Table<MonthlyBudget>
                  columns={previewColumns}
                  dataSource={sourcebudgets}
                  rowKey="period"
                  pagination={false}
                  size="small"
                />
              </Card>
            </Col>
          )}

          <Col span={24}>
            <div style={{ fontSize: 12, color: '#5F5E5A', marginBottom: 4 }}>③ 选择目标门店（可多选）</div>
            <Select
              mode="multiple"
              placeholder="选择要下发到的目标门店"
              options={stores.filter((s) => s.value !== sourceStoreId)}
              value={targetStoreIds}
              onChange={setTargetStoreIds}
              style={{ width: '100%', maxWidth: 600 }}
            />
          </Col>

          <Col span={24}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              disabled={!sourceStoreId || targetStoreIds.length === 0 || sourcebudgets.length === 0}
              onClick={() => setPreviewOpen(true)}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              预览并下发
            </Button>
          </Col>
        </Row>

        {error && (
          <Alert type="error" message={error} showIcon style={{ marginTop: 12 }} closable onClose={() => setError(null)} />
        )}
      </Card>

      {/* 下发确认 Modal */}
      <Modal
        title="确认批量下发预算"
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        onOk={handleDispatch}
        confirmLoading={dispatching}
        okText="确认下发"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        cancelText="取消"
        width={680}
      >
        <Alert
          type="warning"
          message={`将向以下 ${targetStoreIds.length} 家门店下发 ${sourcebudgets.length} 个月度预算，已有预算将被覆盖：`}
          description={<Text strong>{targetStoreNames}</Text>}
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Table<MonthlyBudget>
          columns={previewColumns}
          dataSource={sourcebudgets}
          rowKey="period"
          pagination={false}
          size="small"
        />
      </Modal>
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function BudgetManagePage() {
  const [stores, setStores] = useState<Array<{ value: string; label: string }>>([]);

  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((data) => setStores((data.items ?? []).map((s) => ({ value: s.id, label: s.name }))))
      .catch(() => setStores([]));
  }, []);

  const tabItems = [
    {
      key: 'plan',
      label: '预算计划',
      children: <BudgetPlanTab stores={stores} />,
    },
    {
      key: 'execution',
      label: '执行对比',
      children: <BudgetExecutionTab stores={stores} />,
    },
    {
      key: 'dispatch',
      label: '批量下发',
      children: <BudgetDispatchTab stores={stores} />,
    },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          预算管理
        </Title>
        <Paragraph style={{ color: '#5F5E5A', margin: '8px 0 0', fontSize: 14 }}>
          年度预算计划编制、执行情况对比分析与多门店批量下发。
        </Paragraph>
      </div>

      <Tabs
        defaultActiveKey="plan"
        items={tabItems}
        style={{ background: '#fff', padding: '0 24px 24px', borderRadius: 6 }}
      />
    </div>
  );
}
