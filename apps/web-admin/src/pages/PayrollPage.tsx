/**
 * 薪资管理页面 — PayrollPage
 *
 * Tab1: 月度薪资 — 月份选择 + 员工薪资表（计件/提成/绩效/扣款/总计）
 *   - 底部合计行（sticky）
 *   - 状态 Tag：draft=default / confirmed=processing / paid=success
 *   - 操作：查看工资条 / 批量计算 / 批量确认
 *
 * Tab2: 薪资配置 — 各角色薪资方案（可编辑 Modal）
 *
 * 金额显示：分 → 元（/100，保留 2 位小数）
 * API 请求：使用分
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Form,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tabs,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { txFetch } from '../api';

const { Title, Text } = Typography;

// ─── 常量 ───────────────────────────────────────────────────────────────────

const MOCK_STORE_ID = 'store-001';
const ROLE_LABEL: Record<string, string> = {
  waiter: '服务员',
  chef: '厨师',
  cashier: '收银员',
  manager: '店长',
};

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface PayrollSummaryRow {
  id: string;
  employee_id: string;
  employee_name: string;
  employee_role: string;
  store_id: string;
  period_year: number;
  period_month: number;
  base_salary_fen: number;
  piece_count: number;
  piece_amount_fen: number;
  commission_base_fen: number;
  commission_amount_fen: number;
  perf_score: number | null;
  perf_bonus_fen: number;
  deductions_fen: number;
  total_salary_fen: number;
  status: 'draft' | 'confirmed' | 'paid';
  breakdown?: Record<string, { label: string; fen: number; detail?: string }>;
}

interface PayrollConfig {
  id: string;
  employee_role: string;
  base_salary_fen: number;
  piece_rate_enabled: boolean;
  piece_rate_fen: number;
  commission_rate: number;
  commission_base: string;
  perf_bonus_enabled: boolean;
  perf_bonus_cap_fen: number;
  effective_from: string;
}

interface BatchCalcResult {
  store_id: string;
  year: number;
  month: number;
  employee_count: number;
  total_salary_fen: number;
  total_salary_yuan: number;
  records: PayrollSummaryRow[];
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function yuanCell(fen: number): React.ReactNode {
  return <Text>¥ {fenToYuan(fen)}</Text>;
}

const STATUS_TAG: Record<string, React.ReactNode> = {
  draft: <Tag>草稿</Tag>,
  confirmed: <Tag color="processing">已确认</Tag>,
  paid: <Tag color="success">已发放</Tag>,
};

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function PayrollPage() {
  const [activeTab, setActiveTab] = useState('monthly');
  const [selectedMonth, setSelectedMonth] = useState(dayjs());
  const [summaries, setSummaries] = useState<PayrollSummaryRow[]>([]);
  const [configs, setConfigs] = useState<PayrollConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [calcLoading, setCalcLoading] = useState(false);
  const [batchResult, setBatchResult] = useState<BatchCalcResult | null>(null);
  const [payslipVisible, setPayslipVisible] = useState(false);
  const [payslipData, setPayslipData] = useState<PayrollSummaryRow | null>(null);
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<PayrollConfig | null>(null);
  const [configForm] = Form.useForm();
  const [messageApi, contextHolder] = message.useMessage();

  // ── 加载薪资汇总 ────────────────────────────────────────────────────────────
  const loadSummaries = useCallback(async () => {
    setLoading(true);
    try {
      const year = selectedMonth.year();
      const month = selectedMonth.month() + 1;
      // TODO: 真实 SQL:
      // SELECT ps.*, e.name as employee_name FROM payroll_summaries ps
      // JOIN employees e ON ps.employee_id = e.id
      // WHERE ps.tenant_id = :tid AND ps.period_year = :year AND ps.period_month = :month
      // AND ps.store_id = :store_id AND ps.is_deleted = false ORDER BY e.name
      const data = await txFetch<{ items: PayrollSummaryRow[]; total: number }>(
        `/api/v1/org/payroll/summaries?year=${year}&month=${month}&store_id=${MOCK_STORE_ID}`,
      );
      setSummaries(data.items);
    } catch {
      // 初次加载无数据是正常的，不报错
      setSummaries([]);
    } finally {
      setLoading(false);
    }
  }, [selectedMonth]);

  // ── 加载薪资配置 ────────────────────────────────────────────────────────────
  const loadConfigs = useCallback(async () => {
    try {
      // TODO: SELECT * FROM payroll_configs WHERE tenant_id = :tid
      //       AND store_id = :store_id AND is_deleted = false ORDER BY employee_role
      const data = await txFetch<{ items: PayrollConfig[]; total: number }>(
        `/api/v1/org/payroll/config?store_id=${MOCK_STORE_ID}`,
      );
      setConfigs(data.items);
    } catch {
      setConfigs([]);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'monthly') loadSummaries();
    if (activeTab === 'config') loadConfigs();
  }, [activeTab, loadSummaries, loadConfigs]);

  // ── 批量计算 ────────────────────────────────────────────────────────────────
  const handleBatchCalculate = async () => {
    setCalcLoading(true);
    try {
      const year = selectedMonth.year();
      const month = selectedMonth.month() + 1;
      // TODO: 遍历 employees 表所有在职员工，调用薪资引擎计算，写入 payroll_summaries 表
      const result = await txFetch<BatchCalcResult>('/api/v1/org/payroll/calculate-batch', {
        method: 'POST',
        body: JSON.stringify({ store_id: MOCK_STORE_ID, year, month }),
      });
      setBatchResult(result);
      setSummaries(result.records);
      messageApi.success(`已计算 ${result.employee_count} 名员工薪资，门店合计 ¥${result.total_salary_yuan}`);
    } catch (err: unknown) {
      messageApi.error(`批量计算失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setCalcLoading(false);
    }
  };

  // ── 批量确认 ────────────────────────────────────────────────────────────────
  const handleBatchConfirm = async () => {
    const draftItems = summaries.filter(s => s.status === 'draft');
    if (draftItems.length === 0) {
      messageApi.info('没有草稿状态的薪资单需要确认');
      return;
    }
    try {
      // TODO: 批量 UPDATE payroll_summaries SET status='confirmed' WHERE status='draft'
      //       AND tenant_id=:tid AND store_id=:store_id AND period_year=:year AND period_month=:month
      for (const item of draftItems) {
        if (!item.id) continue;
        await txFetch(`/api/v1/org/payroll/summaries/${item.id}/confirm`, { method: 'POST' });
      }
      messageApi.success(`已确认 ${draftItems.length} 条薪资单`);
      loadSummaries();
    } catch (err: unknown) {
      messageApi.error(`批量确认失败: ${err instanceof Error ? err.message : '未知错误'}`);
    }
  };

  // ── 查看工资条 ──────────────────────────────────────────────────────────────
  const handleViewPayslip = (record: PayrollSummaryRow) => {
    setPayslipData(record);
    setPayslipVisible(true);
  };

  // ── 编辑薪资配置 ────────────────────────────────────────────────────────────
  const handleEditConfig = (config: PayrollConfig) => {
    setEditingConfig(config);
    configForm.setFieldsValue({
      ...config,
      base_salary_yuan: config.base_salary_fen / 100,
      piece_rate_yuan: config.piece_rate_fen / 100,
      perf_bonus_cap_yuan: config.perf_bonus_cap_fen / 100,
      commission_rate_pct: config.commission_rate * 100,
    });
    setConfigModalVisible(true);
  };

  const handleConfigSave = async () => {
    try {
      const values = await configForm.validateFields();
      if (!editingConfig) return;
      // TODO: UPSERT INTO payroll_configs SET ... WHERE tenant_id=:tid AND store_id=:store_id
      //       AND employee_role=:role AND effective_from=:date
      await txFetch('/api/v1/org/payroll/config', {
        method: 'POST',
        body: JSON.stringify({
          store_id: MOCK_STORE_ID,
          employee_role: editingConfig.employee_role,
          base_salary_fen: Math.round(values.base_salary_yuan * 100),
          piece_rate_enabled: values.piece_rate_enabled,
          piece_rate_fen: Math.round(values.piece_rate_yuan * 100),
          commission_rate: values.commission_rate_pct / 100,
          commission_base: values.commission_base,
          perf_bonus_enabled: values.perf_bonus_enabled,
          perf_bonus_cap_fen: Math.round(values.perf_bonus_cap_yuan * 100),
          effective_from: editingConfig.effective_from,
        }),
      });
      messageApi.success('薪资配置已保存');
      setConfigModalVisible(false);
      loadConfigs();
    } catch (err: unknown) {
      if (err instanceof Error) {
        messageApi.error(`保存失败: ${err.message}`);
      }
    }
  };

  // ── 月度薪资表格列 ──────────────────────────────────────────────────────────
  const monthlyColumns: ColumnsType<PayrollSummaryRow> = [
    {
      title: '姓名',
      dataIndex: 'employee_name',
      fixed: 'left',
      width: 90,
    },
    {
      title: '角色',
      dataIndex: 'employee_role',
      width: 80,
      render: (role: string) => ROLE_LABEL[role] ?? role,
    },
    {
      title: '底薪 (元)',
      dataIndex: 'base_salary_fen',
      width: 100,
      align: 'right',
      render: (v: number) => yuanCell(v),
    },
    {
      title: '计件',
      children: [
        {
          title: '件数',
          dataIndex: 'piece_count',
          width: 70,
          align: 'right',
        },
        {
          title: '计件金额 (元)',
          dataIndex: 'piece_amount_fen',
          width: 110,
          align: 'right',
          render: (v: number) => yuanCell(v),
        },
      ],
    },
    {
      title: '提成 (元)',
      dataIndex: 'commission_amount_fen',
      width: 100,
      align: 'right',
      render: (v: number) => yuanCell(v),
    },
    {
      title: '绩效',
      children: [
        {
          title: '评分',
          dataIndex: 'perf_score',
          width: 70,
          align: 'right',
          render: (v: number | null) => v != null ? v.toFixed(1) : '—',
        },
        {
          title: '绩效奖金 (元)',
          dataIndex: 'perf_bonus_fen',
          width: 110,
          align: 'right',
          render: (v: number) => yuanCell(v),
        },
      ],
    },
    {
      title: '扣款 (元)',
      dataIndex: 'deductions_fen',
      width: 90,
      align: 'right',
      render: (v: number) => (
        <Text type={v > 0 ? 'danger' : undefined}>-¥{fenToYuan(v)}</Text>
      ),
    },
    {
      title: '实发合计 (元)',
      dataIndex: 'total_salary_fen',
      width: 120,
      align: 'right',
      fixed: 'right',
      render: (v: number) => (
        <Text strong style={{ color: '#1677ff' }}>¥{fenToYuan(v)}</Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      align: 'center',
      render: (s: string) => STATUS_TAG[s] ?? <Tag>{s}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 90,
      render: (_: unknown, record: PayrollSummaryRow) => (
        <Button size="small" type="link" onClick={() => handleViewPayslip(record)}>
          工资条
        </Button>
      ),
    },
  ];

  // ── 汇总行（sticky 底部） ───────────────────────────────────────────────────
  const totalRow: PayrollSummaryRow | null =
    summaries.length > 0
      ? {
          id: '__total__',
          employee_id: '__total__',
          employee_name: '合计',
          employee_role: '',
          store_id: MOCK_STORE_ID,
          period_year: selectedMonth.year(),
          period_month: selectedMonth.month() + 1,
          base_salary_fen: summaries.reduce((s, r) => s + r.base_salary_fen, 0),
          piece_count: summaries.reduce((s, r) => s + r.piece_count, 0),
          piece_amount_fen: summaries.reduce((s, r) => s + r.piece_amount_fen, 0),
          commission_base_fen: summaries.reduce((s, r) => s + r.commission_base_fen, 0),
          commission_amount_fen: summaries.reduce((s, r) => s + r.commission_amount_fen, 0),
          perf_score: null,
          perf_bonus_fen: summaries.reduce((s, r) => s + r.perf_bonus_fen, 0),
          deductions_fen: summaries.reduce((s, r) => s + r.deductions_fen, 0),
          total_salary_fen: summaries.reduce((s, r) => s + r.total_salary_fen, 0),
          status: 'draft',
        }
      : null;

  // ── 薪资配置表格列 ──────────────────────────────────────────────────────────
  const configColumns: ColumnsType<PayrollConfig> = [
    {
      title: '角色',
      dataIndex: 'employee_role',
      render: (r: string) => <Tag color="blue">{ROLE_LABEL[r] ?? r}</Tag>,
    },
    {
      title: '底薪 (元/月)',
      dataIndex: 'base_salary_fen',
      align: 'right',
      render: (v: number) => `¥${fenToYuan(v)}`,
    },
    {
      title: '计件单价 (元/单)',
      dataIndex: 'piece_rate_fen',
      align: 'right',
      render: (v: number, row: PayrollConfig) =>
        row.piece_rate_enabled ? `¥${fenToYuan(v)}` : <Text type="secondary">未启用</Text>,
    },
    {
      title: '提成比例',
      dataIndex: 'commission_rate',
      align: 'right',
      render: (v: number) =>
        v > 0 ? `${(v * 100).toFixed(2)}%` : <Text type="secondary">无提成</Text>,
    },
    {
      title: '绩效奖金上限 (元)',
      dataIndex: 'perf_bonus_cap_fen',
      align: 'right',
      render: (v: number, row: PayrollConfig) =>
        row.perf_bonus_enabled ? `¥${fenToYuan(v)}` : <Text type="secondary">未启用</Text>,
    },
    {
      title: '生效日期',
      dataIndex: 'effective_from',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: PayrollConfig) => (
        <Button size="small" type="link" onClick={() => handleEditConfig(record)}>
          编辑
        </Button>
      ),
    },
  ];

  // ── 渲染 ────────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4} style={{ marginBottom: 16 }}>
        薪资管理
      </Title>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'monthly',
            label: '月度薪资',
            children: (
              <div>
                {/* 工具栏 */}
                <Row gutter={12} align="middle" style={{ marginBottom: 16 }}>
                  <Col>
                    <Text style={{ marginRight: 8 }}>选择月份：</Text>
                    <DatePicker
                      picker="month"
                      value={selectedMonth}
                      onChange={v => {
                        if (v) {
                          setSelectedMonth(v);
                          setSummaries([]);
                          setBatchResult(null);
                        }
                      }}
                      allowClear={false}
                    />
                  </Col>
                  <Col flex="auto" />
                  <Col>
                    <Space>
                      <Button
                        type="primary"
                        loading={calcLoading}
                        onClick={handleBatchCalculate}
                      >
                        批量计算
                      </Button>
                      <Button onClick={handleBatchConfirm} disabled={summaries.length === 0}>
                        批量确认
                      </Button>
                    </Space>
                  </Col>
                </Row>

                {/* 批量计算结果统计 */}
                {batchResult && (
                  <Alert
                    style={{ marginBottom: 16 }}
                    type="info"
                    message={
                      <Space split={<Divider type="vertical" />}>
                        <span>计算人数：<strong>{batchResult.employee_count}</strong> 人</span>
                        <span>门店薪资合计：<strong>¥{batchResult.total_salary_yuan}</strong></span>
                        <span>
                          {batchResult.year} 年 {batchResult.month} 月
                        </span>
                      </Space>
                    }
                    closable
                    onClose={() => setBatchResult(null)}
                  />
                )}

                {/* 薪资表格 */}
                <Table<PayrollSummaryRow>
                  rowKey={r => r.id || r.employee_id}
                  columns={monthlyColumns}
                  dataSource={summaries}
                  loading={loading}
                  scroll={{ x: 1200 }}
                  pagination={false}
                  size="small"
                  bordered
                  summary={() =>
                    totalRow ? (
                      <Table.Summary fixed="bottom">
                        <Table.Summary.Row style={{ background: '#fafafa', fontWeight: 600 }}>
                          <Table.Summary.Cell index={0} colSpan={2}>
                            合计（{summaries.length} 人）
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={2} align="right">
                            ¥{fenToYuan(totalRow.base_salary_fen)}
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={3} align="right">
                            {totalRow.piece_count}
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={4} align="right">
                            ¥{fenToYuan(totalRow.piece_amount_fen)}
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={5} align="right">
                            ¥{fenToYuan(totalRow.commission_amount_fen)}
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={6} align="right">—</Table.Summary.Cell>
                          <Table.Summary.Cell index={7} align="right">
                            ¥{fenToYuan(totalRow.perf_bonus_fen)}
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={8} align="right">
                            -¥{fenToYuan(totalRow.deductions_fen)}
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={9} align="right">
                            <Text strong style={{ color: '#1677ff' }}>
                              ¥{fenToYuan(totalRow.total_salary_fen)}
                            </Text>
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={10} />
                          <Table.Summary.Cell index={11} />
                        </Table.Summary.Row>
                      </Table.Summary>
                    ) : null
                  }
                />
              </div>
            ),
          },
          {
            key: 'config',
            label: '薪资配置',
            children: (
              <Table<PayrollConfig>
                rowKey="id"
                columns={configColumns}
                dataSource={configs}
                pagination={false}
                size="small"
                bordered
              />
            ),
          },
        ]}
      />

      {/* 工资条 Modal */}
      <Modal
        title="工资条"
        open={payslipVisible}
        onCancel={() => setPayslipVisible(false)}
        footer={[
          <Button key="close" onClick={() => setPayslipVisible(false)}>
            关闭
          </Button>,
        ]}
        width={560}
      >
        {payslipData && (
          <>
            <Descriptions
              bordered
              column={2}
              size="small"
              title={
                <Text>
                  {payslipData.employee_name}
                  <Badge
                    style={{ marginLeft: 8 }}
                    status={
                      payslipData.status === 'paid'
                        ? 'success'
                        : payslipData.status === 'confirmed'
                        ? 'processing'
                        : 'default'
                    }
                    text={STATUS_TAG[payslipData.status]}
                  />
                </Text>
              }
            >
              <Descriptions.Item label="月份" span={2}>
                {payslipData.period_year} 年 {payslipData.period_month} 月
              </Descriptions.Item>
              <Descriptions.Item label="角色">
                {ROLE_LABEL[payslipData.employee_role] ?? payslipData.employee_role}
              </Descriptions.Item>
              <Descriptions.Item label="底薪">
                ¥{fenToYuan(payslipData.base_salary_fen)}
              </Descriptions.Item>
              <Descriptions.Item label="计件数量">
                {payslipData.piece_count} 单
              </Descriptions.Item>
              <Descriptions.Item label="计件金额">
                ¥{fenToYuan(payslipData.piece_amount_fen)}
              </Descriptions.Item>
              <Descriptions.Item label="提成基数">
                ¥{fenToYuan(payslipData.commission_base_fen)}
              </Descriptions.Item>
              <Descriptions.Item label="提成金额">
                ¥{fenToYuan(payslipData.commission_amount_fen)}
              </Descriptions.Item>
              <Descriptions.Item label="绩效评分">
                {payslipData.perf_score != null ? payslipData.perf_score.toFixed(1) : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="绩效奖金">
                ¥{fenToYuan(payslipData.perf_bonus_fen)}
              </Descriptions.Item>
              <Descriptions.Item label="扣款" span={2}>
                <Text type="danger">-¥{fenToYuan(payslipData.deductions_fen)}</Text>
              </Descriptions.Item>
            </Descriptions>
            <Divider />
            <Row justify="end">
              <Col>
                <Text style={{ fontSize: 18 }}>
                  实发合计：
                  <Text strong style={{ fontSize: 22, color: '#1677ff' }}>
                    ¥{fenToYuan(payslipData.total_salary_fen)}
                  </Text>
                </Text>
              </Col>
            </Row>
          </>
        )}
      </Modal>

      {/* 薪资配置编辑 Modal */}
      <Modal
        title={`编辑薪资配置 — ${editingConfig ? (ROLE_LABEL[editingConfig.employee_role] ?? editingConfig.employee_role) : ''}`}
        open={configModalVisible}
        onOk={handleConfigSave}
        onCancel={() => setConfigModalVisible(false)}
        okText="保存"
        cancelText="取消"
        width={520}
      >
        <Form form={configForm} layout="vertical" size="small">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                label="底薪（元/月）"
                name="base_salary_yuan"
                rules={[{ required: true, message: '请输入底薪' }]}
              >
                <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="启用计件" name="piece_rate_enabled" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="计件单价（元/单）" name="piece_rate_yuan">
                <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="提成比例（%）" name="commission_rate_pct">
                <InputNumber min={0} max={100} precision={2} style={{ width: '100%' }} suffix="%" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="提成基数" name="commission_base">
                <Select
                  options={[
                    { value: 'revenue', label: '营业额' },
                    { value: 'profit', label: '利润' },
                    { value: 'dishes', label: '出餐量' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="启用绩效奖金" name="perf_bonus_enabled" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="绩效奖金上限（元）" name="perf_bonus_cap_yuan">
                <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
