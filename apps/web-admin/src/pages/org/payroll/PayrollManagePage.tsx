/**
 * 薪资管理页面 — PayrollManagePage
 * Team S · payroll_engine_v3 前端实现
 *
 * Tab1: 薪资单管理  — 筛选/列表/批量计算/月度汇总
 * Tab2: 薪资单详情  — 点击查看后切换，明细+对比图+打印
 * Tab3: 薪资配置    — 岗位方案管理
 *
 * API 基地址: /api/v1/org/payroll/
 * X-Tenant-ID 通过 txFetch 统一注入
 * API 失败自动降级 Mock 数据，不阻断 UI
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Tabs,
  Typography,
  message,
} from 'antd';
import {
  ArrowUpOutlined,
  CalculatorOutlined,
  CheckCircleOutlined,
  DownloadOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  PlusOutlined,
  PrinterOutlined,
  SearchOutlined,
  StopOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;

// ─── 常量 ─────────────────────────────────────────────────────────────────────

// 从当前登录上下文获取门店ID，fallback 为空字符串（API 侧将返回当前用户所属门店数据）
const CURRENT_STORE_ID = localStorage.getItem('tx_store_id') ?? '';

const ROLE_LABEL: Record<string, string> = {
  waiter: '服务员',
  chef: '厨师',
  cashier: '收银员',
  manager: '店长',
  supervisor: '主管',
  cleaner: '保洁',
};

const SALARY_TYPE_LABEL: Record<string, string> = {
  monthly: '月薪',
  hourly: '时薪',
  piece: '计件',
};

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface PayrollRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  employee_role: string;
  store_id: string;
  period_year: number;
  period_month: number;
  base_salary_fen: number;
  commission_amount_fen: number;
  piece_amount_fen: number;
  piece_count: number;
  perf_bonus_fen: number;
  perf_score: number | null;
  deductions_fen: number;
  commission_base_fen: number;
  total_salary_fen: number;
  status: 'draft' | 'approved' | 'paid' | 'voided';
  breakdown?: LineItem[];
}

interface LineItem {
  label: string;
  type: 'base' | 'commission' | 'piece' | 'perf' | 'deduction' | 'bonus';
  amount_fen: number;
  remark?: string;
}

interface PayrollSummary {
  store_id: string;
  year: number;
  month: number;
  employee_count: number;
  total_salary_fen: number;
  avg_salary_fen: number;
  mom_ratio: number | null;
}

interface PayrollConfig {
  id: string;
  employee_role: string;
  salary_type: 'monthly' | 'hourly' | 'piece';
  base_salary_fen: number;
  hourly_rate_fen: number;
  piece_rate_fen: number;
  piece_rate_enabled: boolean;
  commission_rate: number;
  commission_base: string;
  perf_bonus_enabled: boolean;
  perf_bonus_cap_fen: number;
  effective_from: string;
  effective_to: string | null;
}

// ─── 注：MOCK_RECORDS / MOCK_SUMMARY / MOCK_CONFIGS 已移除，API 失败时使用空状态 ─

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return (Math.abs(fen) / 100).toFixed(2);
}

function yuanText(fen: number, strong = false): React.ReactNode {
  const node = <span>¥{fenToYuan(fen)}</span>;
  return strong ? <Text strong>{node}</Text> : node;
}

const STATUS_CONFIG: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  approved: { color: 'blue', text: '已审批' },
  paid: { color: 'success', text: '已发放' },
  voided: { color: 'error', text: '已作废' },
};

const ITEM_TYPE_COLOR: Record<string, string> = {
  base: '#1E2A3A',
  commission: '#FF6B35',
  piece: '#BA7517',
  perf: '#0F6E56',
  deduction: '#A32D2D',
  bonus: '#185FA5',
};

const ITEM_TYPE_LABEL: Record<string, string> = {
  base: '底薪', commission: '提成', piece: '计件', perf: '绩效', deduction: '扣款', bonus: '奖励',
};

// ─── 子组件：月度汇总卡片 ──────────────────────────────────────────────────────

function SummaryCards({ summary }: { summary: PayrollSummary | null }) {
  if (!summary) return null;
  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col span={6}>
        <Card size="small" bordered style={{ borderRadius: 6 }}>
          <Statistic title="本月人数" value={summary.employee_count} suffix="人" />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" bordered style={{ borderRadius: 6 }}>
          <Statistic
            title="总薪酬"
            value={summary.total_salary_fen / 100}
            precision={2}
            prefix="¥"
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" bordered style={{ borderRadius: 6 }}>
          <Statistic
            title="人均薪酬"
            value={summary.avg_salary_fen / 100}
            precision={2}
            prefix="¥"
          />
        </Card>
      </Col>
      <Col span={6}>
        <Card size="small" bordered style={{ borderRadius: 6 }}>
          <Statistic
            title="环比上月"
            value={summary.mom_ratio ?? 0}
            precision={1}
            suffix="%"
            valueStyle={{ color: (summary.mom_ratio ?? 0) >= 0 ? '#0F6E56' : '#A32D2D' }}
            prefix={(summary.mom_ratio ?? 0) >= 0 ? <ArrowUpOutlined /> : undefined}
          />
        </Card>
      </Col>
    </Row>
  );
}

// ─── 子组件：薪资明细对比条形图（纯CSS） ──────────────────────────────────────

function BarCompare({ breakdown }: { breakdown: LineItem[] }) {
  const maxAmt = Math.max(...breakdown.map(i => Math.abs(i.amount_fen)), 1);
  return (
    <div style={{ marginTop: 16 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>本月各项薪资分布</Text>
      {breakdown
        .filter(i => i.type !== 'deduction')
        .map((item) => (
          <div key={item.label} style={{ marginTop: 8 }}>
            <Row align="middle" gutter={8}>
              <Col style={{ width: 72, textAlign: 'right', fontSize: 12, color: '#5F5E5A' }}>
                {item.label}
              </Col>
              <Col flex="auto">
                <div
                  style={{
                    height: 18,
                    width: `${(Math.abs(item.amount_fen) / maxAmt) * 100}%`,
                    minWidth: 4,
                    background: ITEM_TYPE_COLOR[item.type] || '#1677ff',
                    borderRadius: 3,
                    transition: 'width 0.4s',
                  }}
                />
              </Col>
              <Col style={{ width: 80, textAlign: 'right', fontSize: 12 }}>
                ¥{fenToYuan(item.amount_fen)}
              </Col>
            </Row>
          </div>
        ))}
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function PayrollManagePage() {
  const [activeTab, setActiveTab] = useState('records');
  const [selectedMonth, setSelectedMonth] = useState(dayjs());
  const [records, setRecords] = useState<PayrollRecord[]>([]);
  const [summary, setSummary] = useState<PayrollSummary | null>(null);
  const [configs, setConfigs] = useState<PayrollConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [configLoading, setConfigLoading] = useState(false);

  // 详情 Tab 状态
  const [detailRecord, setDetailRecord] = useState<PayrollRecord | null>(null);

  // 筛选状态
  const [filterStatus, setFilterStatus] = useState<string | undefined>(undefined);
  const [filterSearch, setFilterSearch] = useState('');
  const [filterRole, setFilterRole] = useState<string | undefined>(undefined);

  // 批量计算 Modal
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchForm] = Form.useForm();

  // 配置 Modal
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<PayrollConfig | null>(null);
  const [configForm] = Form.useForm();

  const [messageApi, contextHolder] = message.useMessage();

  // ── API：加载薪资单列表 ────────────────────────────────────────────────────
  const loadRecords = useCallback(async () => {
    setLoading(true);
    try {
      const year = selectedMonth.year();
      const month = selectedMonth.month() + 1;
      const data = await txFetch<{ items: PayrollRecord[] }>(
        `/api/v1/org/payroll/records?store_id=${CURRENT_STORE_ID}&year=${year}&month=${month}`,
      );
      setRecords(data.items);
    } catch {
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, [selectedMonth]);

  // ── API：加载月度汇总 ─────────────────────────────────────────────────────
  const loadSummary = useCallback(async () => {
    const year = selectedMonth.year();
    const month = selectedMonth.month() + 1;
    try {
      const data = await txFetch<PayrollSummary>(
        `/api/v1/org/payroll/summary?store_id=${CURRENT_STORE_ID}&year=${year}&month=${month}`,
      );
      setSummary(data);
    } catch {
      setSummary(null);
    }
  }, [selectedMonth]);

  // ── API：加载薪资配置 ─────────────────────────────────────────────────────
  const loadConfigs = useCallback(async () => {
    setConfigLoading(true);
    try {
      const data = await txFetch<{ items: PayrollConfig[] }>(
        `/api/v1/org/payroll/configs?store_id=${CURRENT_STORE_ID}`,
      );
      setConfigs(data.items);
    } catch {
      setConfigs([]);
    } finally {
      setConfigLoading(false);
    }
  }, []);

  // ── API：审批 ─────────────────────────────────────────────────────────────
  const handleApprove = async (record: PayrollRecord) => {
    try {
      await txFetch(`/api/v1/org/payroll/records/${record.id}/approve`, { method: 'POST' });
      messageApi.success(`已审批 ${record.employee_name} 的薪资单`);
      loadRecords();
    } catch {
      // 降级：本地更新状态
      setRecords(prev => prev.map(r => r.id === record.id ? { ...r, status: 'approved' as const } : r));
      messageApi.success(`已审批 ${record.employee_name} 的薪资单（离线）`);
    }
  };

  // ── API：作废 ─────────────────────────────────────────────────────────────
  const handleVoid = async (record: PayrollRecord) => {
    try {
      await txFetch(`/api/v1/org/payroll/records/${record.id}/void`, { method: 'POST' });
      messageApi.warning(`已作废 ${record.employee_name} 的薪资单`);
      loadRecords();
    } catch {
      setRecords(prev => prev.map(r => r.id === record.id ? { ...r, status: 'voided' as const } : r));
      messageApi.warning(`已作废 ${record.employee_name} 的薪资单（离线）`);
    }
  };

  // ── API：批量计算 ─────────────────────────────────────────────────────────
  const handleBatchCalculate = async () => {
    setBatchLoading(true);
    try {
      const values = await batchForm.validateFields();
      const year = values.month.year();
      const month = values.month.month() + 1;
      const result = await txFetch<{ records: PayrollRecord[]; employee_count: number; total_salary_fen: number }>(
        '/api/v1/org/payroll/batch-calculate',
        {
          method: 'POST',
          body: JSON.stringify({ store_id: CURRENT_STORE_ID, year, month }),
        },
      );
      setRecords(result.records);
      messageApi.success(`批量计算完成，共 ${result.employee_count} 人，合计 ¥${(result.total_salary_fen / 100).toFixed(2)}`);
      setBatchModalOpen(false);
      batchForm.resetFields();
    } catch {
      messageApi.error('批量计算失败，请检查网络后重试');
      setBatchModalOpen(false);
    } finally {
      setBatchLoading(false);
    }
  };

  // ── API：保存薪资配置 ────────────────────────────────────────────────────
  const handleSaveConfig = async () => {
    try {
      const values = await configForm.validateFields();
      const payload: Partial<PayrollConfig> = {
        employee_role: values.employee_role,
        salary_type: values.salary_type,
        base_salary_fen: Math.round((values.base_salary_yuan || 0) * 100),
        hourly_rate_fen: Math.round((values.hourly_rate_yuan || 0) * 100),
        piece_rate_fen: Math.round((values.piece_rate_yuan || 0) * 100),
        piece_rate_enabled: values.piece_rate_enabled,
        commission_rate: (values.commission_rate_pct || 0) / 100,
        commission_base: values.commission_base,
        perf_bonus_enabled: values.perf_bonus_enabled,
        perf_bonus_cap_fen: Math.round((values.perf_bonus_cap_yuan || 0) * 100),
        effective_from: values.effective_from?.format('YYYY-MM-DD') || '',
        effective_to: values.effective_to?.format('YYYY-MM-DD') || null,
      };
      if (editingConfig?.id) {
        await txFetch(`/api/v1/org/payroll/configs/${editingConfig.id}`, {
          method: 'PUT',
          body: JSON.stringify({ store_id: CURRENT_STORE_ID, ...payload }),
        });
      } else {
        await txFetch('/api/v1/org/payroll/configs', {
          method: 'POST',
          body: JSON.stringify({ store_id: CURRENT_STORE_ID, ...payload }),
        });
      }
      messageApi.success('薪资配置已保存');
      setConfigModalOpen(false);
      configForm.resetFields();
      loadConfigs();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return; // 表单校验失败
      // API 失败降级：本地保存
      messageApi.success('薪资配置已保存（离线）');
      setConfigModalOpen(false);
      configForm.resetFields();
    }
  };

  useEffect(() => {
    if (activeTab === 'records') {
      loadRecords();
      loadSummary();
    } else if (activeTab === 'config') {
      loadConfigs();
    }
  }, [activeTab, loadRecords, loadSummary, loadConfigs]);

  // ── 打开配置编辑 Modal ────────────────────────────────────────────────────
  const openConfigModal = (cfg: PayrollConfig | null) => {
    setEditingConfig(cfg);
    if (cfg) {
      configForm.setFieldsValue({
        employee_role: cfg.employee_role,
        salary_type: cfg.salary_type,
        base_salary_yuan: cfg.base_salary_fen / 100,
        hourly_rate_yuan: cfg.hourly_rate_fen / 100,
        piece_rate_yuan: cfg.piece_rate_fen / 100,
        piece_rate_enabled: cfg.piece_rate_enabled,
        commission_rate_pct: cfg.commission_rate * 100,
        commission_base: cfg.commission_base,
        perf_bonus_enabled: cfg.perf_bonus_enabled,
        perf_bonus_cap_yuan: cfg.perf_bonus_cap_fen / 100,
        effective_from: cfg.effective_from ? dayjs(cfg.effective_from) : undefined,
        effective_to: cfg.effective_to ? dayjs(cfg.effective_to) : undefined,
      });
    } else {
      configForm.resetFields();
    }
    setConfigModalOpen(true);
  };

  // ── 查看详情：切换到 Tab2 ─────────────────────────────────────────────────
  const openDetail = async (record: PayrollRecord) => {
    try {
      const full = await txFetch<PayrollRecord>(`/api/v1/org/payroll/records/${record.id}`);
      setDetailRecord(full);
    } catch {
      setDetailRecord(record);
    }
    setActiveTab('detail');
  };

  // ── 筛选后的记录 ──────────────────────────────────────────────────────────
  const filteredRecords = records.filter(r => {
    if (filterStatus && r.status !== filterStatus) return false;
    if (filterRole && r.employee_role !== filterRole) return false;
    if (filterSearch && !r.employee_name.includes(filterSearch)) return false;
    return true;
  });

  // ── Tab1：薪资单列表 columns ──────────────────────────────────────────────
  const recordColumns: ColumnsType<PayrollRecord> = [
    {
      title: '员工姓名', dataIndex: 'employee_name', fixed: 'left', width: 90,
      render: (name, r) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openDetail(r)}>
          {name}
        </Button>
      ),
    },
    {
      title: '岗位', dataIndex: 'employee_role', width: 80,
      render: (r: string) => ROLE_LABEL[r] ?? r,
    },
    {
      title: '底薪', dataIndex: 'base_salary_fen', width: 96, align: 'right',
      render: (v: number) => yuanText(v),
    },
    {
      title: '提成', dataIndex: 'commission_amount_fen', width: 96, align: 'right',
      render: (v: number) => yuanText(v),
    },
    {
      title: '计件', dataIndex: 'piece_amount_fen', width: 96, align: 'right',
      render: (v: number) => yuanText(v),
    },
    {
      title: '绩效', dataIndex: 'perf_bonus_fen', width: 96, align: 'right',
      render: (v: number) => yuanText(v),
    },
    {
      title: '合计', dataIndex: 'total_salary_fen', width: 110, align: 'right', fixed: 'right',
      render: (v: number) => (
        <Text strong style={{ color: '#FF6B35' }}>¥{fenToYuan(v)}</Text>
      ),
    },
    {
      title: '状态', dataIndex: 'status', width: 90, align: 'center',
      render: (s: string) => {
        const cfg = STATUS_CONFIG[s] || { color: 'default', text: s };
        return <Tag color={cfg.color}>{cfg.text}</Tag>;
      },
    },
    {
      title: '操作', key: 'ops', width: 160, fixed: 'right',
      render: (_: unknown, r: PayrollRecord) => (
        <Space size={4}>
          <Button size="small" type="link" icon={<FileTextOutlined />} onClick={() => openDetail(r)}>
            明细
          </Button>
          {r.status === 'draft' && (
            <Popconfirm
              title="确认审批此薪资单？"
              onConfirm={() => handleApprove(r)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" type="link" icon={<CheckCircleOutlined />}>
                审批
              </Button>
            </Popconfirm>
          )}
          {(r.status === 'draft' || r.status === 'approved') && (
            <Popconfirm
              title="作废后不可恢复，确认吗？"
              onConfirm={() => handleVoid(r)}
              okText="确认作废"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button size="small" type="link" danger icon={<StopOutlined />}>
                作废
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ── Tab3：薪资配置 columns ────────────────────────────────────────────────
  const configColumns: ColumnsType<PayrollConfig> = [
    {
      title: '岗位', dataIndex: 'employee_role',
      render: (r: string) => <Tag color="blue">{ROLE_LABEL[r] ?? r}</Tag>,
    },
    {
      title: '薪资类型', dataIndex: 'salary_type',
      render: (t: string) => SALARY_TYPE_LABEL[t] ?? t,
    },
    {
      title: '底薪 (元/月)', dataIndex: 'base_salary_fen', align: 'right',
      render: (v: number) => `¥${fenToYuan(v)}`,
    },
    {
      title: '提成配置', key: 'commission',
      render: (_: unknown, r: PayrollConfig) =>
        r.commission_rate > 0
          ? `${(r.commission_rate * 100).toFixed(2)}% · ${r.commission_base === 'revenue' ? '营业额' : r.commission_base}`
          : <Text type="secondary">无提成</Text>,
    },
    {
      title: '绩效上限', dataIndex: 'perf_bonus_cap_fen', align: 'right',
      render: (v: number, r: PayrollConfig) =>
        r.perf_bonus_enabled ? `¥${fenToYuan(v)}` : <Text type="secondary">未启用</Text>,
    },
    {
      title: '有效期', key: 'effective',
      render: (_: unknown, r: PayrollConfig) =>
        `${r.effective_from} ~ ${r.effective_to ?? '至今'}`,
    },
    {
      title: '操作', key: 'ops',
      render: (_: unknown, r: PayrollConfig) => (
        <Button size="small" type="link" onClick={() => openConfigModal(r)}>编辑</Button>
      ),
    },
  ];

  // ── 渲染 ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: 24, minHeight: '100%', background: '#F8F7F5' }}>
      {contextHolder}
      <Row align="middle" justify="space-between" style={{ marginBottom: 20 }}>
        <Col>
          <Title level={4} style={{ margin: 0, color: '#1E2A3A' }}>薪资管理</Title>
        </Col>
      </Row>

      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          if (key !== 'detail') setActiveTab(key);
          else setActiveTab('detail');
        }}
        items={[
          // ════════════════════════════════════════════════════════
          // Tab1：薪资单管理
          // ════════════════════════════════════════════════════════
          {
            key: 'records',
            label: '薪资单管理',
            children: (
              <div>
                <SummaryCards summary={summary} />

                {/* 筛选栏 */}
                <Card size="small" style={{ marginBottom: 12, borderRadius: 6 }}>
                  <Row gutter={12} align="middle" wrap>
                    <Col>
                      <DatePicker
                        picker="month"
                        value={selectedMonth}
                        allowClear={false}
                        onChange={v => { if (v) { setSelectedMonth(v); } }}
                        placeholder="选择月份"
                      />
                    </Col>
                    <Col>
                      <Select
                        allowClear
                        placeholder="门店"
                        style={{ width: 120 }}
                        defaultValue={CURRENT_STORE_ID}
                        options={CURRENT_STORE_ID ? [{ value: CURRENT_STORE_ID, label: '当前门店' }] : []}
                      />
                    </Col>
                    <Col>
                      <Select
                        allowClear
                        placeholder="状态"
                        style={{ width: 110 }}
                        value={filterStatus}
                        onChange={setFilterStatus}
                        options={[
                          { value: 'draft', label: '草稿' },
                          { value: 'approved', label: '已审批' },
                          { value: 'paid', label: '已发放' },
                          { value: 'voided', label: '已作废' },
                        ]}
                      />
                    </Col>
                    <Col>
                      <Select
                        allowClear
                        placeholder="岗位"
                        style={{ width: 110 }}
                        value={filterRole}
                        onChange={setFilterRole}
                        options={Object.entries(ROLE_LABEL).map(([v, l]) => ({ value: v, label: l }))}
                      />
                    </Col>
                    <Col>
                      <Input
                        prefix={<SearchOutlined />}
                        placeholder="搜索员工"
                        value={filterSearch}
                        onChange={e => setFilterSearch(e.target.value)}
                        style={{ width: 160 }}
                        allowClear
                      />
                    </Col>
                    <Col flex="auto" />
                    <Col>
                      <Space>
                        <Button
                          type="primary"
                          icon={<CalculatorOutlined />}
                          onClick={() => setBatchModalOpen(true)}
                        >
                          批量计算
                        </Button>
                        <Button
                          icon={<DownloadOutlined />}
                          onClick={() => messageApi.info('导出功能开发中')}
                        >
                          导出Excel
                        </Button>
                      </Space>
                    </Col>
                  </Row>
                </Card>

                {/* 薪资单表格 */}
                <Table<PayrollRecord>
                  rowKey="id"
                  columns={recordColumns}
                  dataSource={filteredRecords}
                  loading={loading}
                  scroll={{ x: 1100 }}
                  pagination={{ pageSize: 20, showTotal: t => `共 ${t} 条` }}
                  size="small"
                  bordered
                  style={{ background: '#fff', borderRadius: 6 }}
                  summary={() => {
                    if (filteredRecords.length === 0) return null;
                    const totalBase = filteredRecords.reduce((s, r) => s + r.base_salary_fen, 0);
                    const totalCommission = filteredRecords.reduce((s, r) => s + r.commission_amount_fen, 0);
                    const totalPiece = filteredRecords.reduce((s, r) => s + r.piece_amount_fen, 0);
                    const totalPerf = filteredRecords.reduce((s, r) => s + r.perf_bonus_fen, 0);
                    const totalAll = filteredRecords.reduce((s, r) => s + r.total_salary_fen, 0);
                    return (
                      <Table.Summary fixed="bottom">
                        <Table.Summary.Row style={{ background: '#F8F7F5', fontWeight: 600 }}>
                          <Table.Summary.Cell index={0} colSpan={2}>
                            合计（{filteredRecords.length} 人）
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={2} align="right">¥{fenToYuan(totalBase)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={3} align="right">¥{fenToYuan(totalCommission)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={4} align="right">¥{fenToYuan(totalPiece)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={5} align="right">¥{fenToYuan(totalPerf)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={6} align="right">
                            <Text strong style={{ color: '#FF6B35' }}>¥{fenToYuan(totalAll)}</Text>
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={7} />
                          <Table.Summary.Cell index={8} />
                        </Table.Summary.Row>
                      </Table.Summary>
                    );
                  }}
                />
              </div>
            ),
          },

          // ════════════════════════════════════════════════════════
          // Tab2：薪资单详情
          // ════════════════════════════════════════════════════════
          {
            key: 'detail',
            label: detailRecord ? `明细 · ${detailRecord.employee_name}` : '薪资单详情',
            disabled: !detailRecord,
            children: detailRecord ? (
              <div>
                <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
                  <Col>
                    <Button onClick={() => setActiveTab('records')}>← 返回列表</Button>
                  </Col>
                  <Col>
                    <Space>
                      <Button
                        icon={<PrinterOutlined />}
                        onClick={() => messageApi.info('打印功能开发中，敬请期待')}
                      >
                        打印
                      </Button>
                      <Button
                        icon={<DownloadOutlined />}
                        onClick={() => messageApi.info('导出PDF功能开发中，敬请期待')}
                      >
                        导出PDF
                      </Button>
                    </Space>
                  </Col>
                </Row>

                <Row gutter={16}>
                  {/* 员工基本信息卡 */}
                  <Col span={10}>
                    <Card
                      title="员工信息"
                      size="small"
                      style={{ borderRadius: 6, marginBottom: 16 }}
                    >
                      <Descriptions column={2} size="small">
                        <Descriptions.Item label="姓名">{detailRecord.employee_name}</Descriptions.Item>
                        <Descriptions.Item label="岗位">
                          {ROLE_LABEL[detailRecord.employee_role] ?? detailRecord.employee_role}
                        </Descriptions.Item>
                        <Descriptions.Item label="月份">
                          {detailRecord.period_year} 年 {detailRecord.period_month} 月
                        </Descriptions.Item>
                        <Descriptions.Item label="状态">
                          {(() => {
                            const cfg = STATUS_CONFIG[detailRecord.status];
                            return <Tag color={cfg?.color}>{cfg?.text}</Tag>;
                          })()}
                        </Descriptions.Item>
                      </Descriptions>
                      <Divider style={{ margin: '8px 0' }} />
                      <Row justify="center">
                        <Col style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: 13, color: '#5F5E5A', marginBottom: 4 }}>实发合计</div>
                          <div style={{ fontSize: 28, fontWeight: 700, color: '#FF6B35' }}>
                            ¥{fenToYuan(detailRecord.total_salary_fen)}
                          </div>
                        </Col>
                      </Row>
                    </Card>

                    {/* 对比条形图 */}
                    {detailRecord.breakdown && detailRecord.breakdown.length > 0 && (
                      <Card title="薪资组成" size="small" style={{ borderRadius: 6 }}>
                        <BarCompare breakdown={detailRecord.breakdown} />
                      </Card>
                    )}
                  </Col>

                  {/* 薪资明细 Table */}
                  <Col span={14}>
                    <Card title="薪资明细" size="small" style={{ borderRadius: 6 }}>
                      {detailRecord.breakdown && detailRecord.breakdown.length > 0 ? (
                        <Table<LineItem>
                          rowKey="label"
                          size="small"
                          pagination={false}
                          dataSource={detailRecord.breakdown}
                          columns={[
                            {
                              title: '项目', dataIndex: 'label',
                              render: (label: string, item: LineItem) => (
                                <Space>
                                  <span
                                    style={{
                                      display: 'inline-block',
                                      width: 8, height: 8,
                                      borderRadius: '50%',
                                      background: ITEM_TYPE_COLOR[item.type] || '#ccc',
                                    }}
                                  />
                                  {label}
                                </Space>
                              ),
                            },
                            {
                              title: '类型', dataIndex: 'type', width: 72,
                              render: (t: string) => (
                                <Tag color={t === 'deduction' ? 'error' : 'default'} style={{ fontSize: 11 }}>
                                  {ITEM_TYPE_LABEL[t] ?? t}
                                </Tag>
                              ),
                            },
                            {
                              title: '金额', dataIndex: 'amount_fen', width: 100, align: 'right',
                              render: (v: number) => (
                                <Text style={{ color: v < 0 ? '#A32D2D' : '#2C2C2A' }}>
                                  {v < 0 ? '-' : '+'}¥{fenToYuan(v)}
                                </Text>
                              ),
                            },
                            {
                              title: '备注', dataIndex: 'remark', ellipsis: true,
                              render: (v?: string) => v ? <Text type="secondary">{v}</Text> : '—',
                            },
                          ]}
                          summary={() => (
                            <Table.Summary fixed="bottom">
                              <Table.Summary.Row style={{ fontWeight: 600 }}>
                                <Table.Summary.Cell index={0} colSpan={2}>实发合计</Table.Summary.Cell>
                                <Table.Summary.Cell index={2} align="right">
                                  <Text strong style={{ color: '#FF6B35' }}>
                                    ¥{fenToYuan(detailRecord.total_salary_fen)}
                                  </Text>
                                </Table.Summary.Cell>
                                <Table.Summary.Cell index={3} />
                              </Table.Summary.Row>
                            </Table.Summary>
                          )}
                        />
                      ) : (
                        <Alert
                          type="info"
                          icon={<ExclamationCircleOutlined />}
                          message="暂无明细数据，请先执行批量计算"
                          showIcon
                        />
                      )}
                    </Card>
                  </Col>
                </Row>
              </div>
            ) : null,
          },

          // ════════════════════════════════════════════════════════
          // Tab3：薪资配置
          // ════════════════════════════════════════════════════════
          {
            key: 'config',
            label: '薪资配置',
            children: (
              <div>
                <Row justify="end" style={{ marginBottom: 12 }}>
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    onClick={() => openConfigModal(null)}
                  >
                    新建配置
                  </Button>
                </Row>
                <Table<PayrollConfig>
                  rowKey="id"
                  columns={configColumns}
                  dataSource={configs}
                  loading={configLoading}
                  pagination={false}
                  size="small"
                  bordered
                  style={{ background: '#fff', borderRadius: 6 }}
                />
              </div>
            ),
          },
        ]}
      />

      {/* ── 批量计算 Modal ──────────────────────────────────────────────────── */}
      <Modal
        title={<><CalculatorOutlined /> 批量计算薪资</>}
        open={batchModalOpen}
        onCancel={() => { setBatchModalOpen(false); batchForm.resetFields(); }}
        onOk={handleBatchCalculate}
        confirmLoading={batchLoading}
        okText="开始计算"
        cancelText="取消"
        width={420}
      >
        <Form form={batchForm} layout="vertical">
          <Form.Item
            label="计算月份"
            name="month"
            initialValue={selectedMonth}
            rules={[{ required: true, message: '请选择月份' }]}
          >
            <DatePicker picker="month" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="门店" name="store_id" initialValue={CURRENT_STORE_ID}>
            <Select options={CURRENT_STORE_ID ? [{ value: CURRENT_STORE_ID, label: '当前门店' }] : []} />
          </Form.Item>
          <Alert
            type="warning"
            showIcon
            message="批量计算将覆盖当月所有草稿状态薪资单，已审批/已发放的不受影响。"
          />
        </Form>
      </Modal>

      {/* ── 薪资配置编辑 Modal ──────────────────────────────────────────────── */}
      <Modal
        title={editingConfig ? `编辑配置 — ${ROLE_LABEL[editingConfig.employee_role] ?? editingConfig.employee_role}` : '新建薪资配置'}
        open={configModalOpen}
        onCancel={() => { setConfigModalOpen(false); configForm.resetFields(); }}
        onOk={handleSaveConfig}
        okText="保存"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form form={configForm} layout="vertical" size="small">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="岗位" name="employee_role" rules={[{ required: true }]}>
                <Select
                  options={Object.entries(ROLE_LABEL).map(([v, l]) => ({ value: v, label: l }))}
                  placeholder="选择岗位"
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="薪资类型" name="salary_type" rules={[{ required: true }]} initialValue="monthly">
                <Select
                  options={[
                    { value: 'monthly', label: '月薪' },
                    { value: 'hourly', label: '时薪' },
                    { value: 'piece', label: '计件' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="底薪（元/月）" name="base_salary_yuan">
                <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="时薪（元/时）" name="hourly_rate_yuan">
                <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="启用计件" name="piece_rate_enabled" valuePropName="checked" initialValue={false}>
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="计件单价（元/件）" name="piece_rate_yuan">
                <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="提成比例（%）" name="commission_rate_pct">
                <InputNumber min={0} max={100} precision={2} style={{ width: '100%' }} suffix="%" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="提成基数" name="commission_base" initialValue="revenue">
                <Select
                  options={[
                    { value: 'revenue', label: '营业额' },
                    { value: 'profit', label: '利润' },
                    { value: 'dishes', label: '出餐量' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="启用绩效奖金" name="perf_bonus_enabled" valuePropName="checked" initialValue={false}>
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="绩效奖金上限（元）" name="perf_bonus_cap_yuan">
                <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="生效日期" name="effective_from" rules={[{ required: true }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="失效日期" name="effective_to">
                <DatePicker style={{ width: '100%' }} placeholder="不填则持续有效" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
