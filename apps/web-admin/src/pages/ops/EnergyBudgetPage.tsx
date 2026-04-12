/**
 * 能耗预算和告警规则管理页面
 * 路由：/ops/energy-budget
 * API：GET/POST  /api/v1/ops/energy/budgets
 *      GET       /api/v1/ops/energy/budget-vs-actual
 *      GET/POST  /api/v1/ops/energy/alert-rules
 *      GET       /api/v1/org/stores
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Card, Tabs, Table, Button, Modal, Form, Input, Select, Switch,
  DatePicker, Tag, Alert, Spin, Row, Col, Statistic,
  Space, message, Typography, Progress, InputNumber,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  PlusOutlined, ThunderboltOutlined, AlertOutlined,
  HistoryOutlined, FireOutlined, DropboxOutlined,
  DollarOutlined, SettingOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../api';

const { Text, Title } = Typography;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type MetricType = 'electricity_kwh' | 'gas_m3' | 'water_ton' | 'cost_fen' | 'ratio';
type ThresholdType = 'absolute' | 'budget_pct' | 'yoy_pct';
type SeverityLevel = 'info' | 'warning' | 'critical';

interface Store {
  id: string;
  name: string;
}

interface BudgetVsActual {
  year: number;
  month: number;
  store_id: string;
  electricity_budget_kwh: number;
  electricity_actual_kwh: number;
  gas_budget_m3: number;
  gas_actual_m3: number;
  water_budget_ton: number;
  water_actual_ton: number;
  cost_budget_fen: number;
  cost_actual_fen: number;
  alert_triggered: boolean;
}

interface EnergyBudget {
  id: string;
  year: number;
  month: number;
  store_id: string;
  store_name?: string;
  electricity_budget_kwh: number;
  gas_budget_m3: number;
  water_budget_ton: number;
  cost_budget_fen: number;
  created_at: string;
}

interface AlertRule {
  id: string;
  name: string;
  metric: MetricType;
  threshold_type: ThresholdType;
  threshold_value: number;
  severity: SeverityLevel;
  is_enabled: boolean;
  created_at: string;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const METRIC_OPTIONS: { value: MetricType; label: string }[] = [
  { value: 'electricity_kwh', label: '电量 (kWh)' },
  { value: 'gas_m3', label: '燃气 (m³)' },
  { value: 'water_ton', label: '水量 (ton)' },
  { value: 'cost_fen', label: '总费用 (元)' },
  { value: 'ratio', label: '使用率 (%)' },
];

const METRIC_LABEL_MAP: Record<MetricType, string> = {
  electricity_kwh: '电量',
  gas_m3: '燃气',
  water_ton: '水量',
  cost_fen: '总费用',
  ratio: '使用率',
};

const THRESHOLD_TYPE_OPTIONS: { value: ThresholdType; label: string }[] = [
  { value: 'absolute', label: '绝对值' },
  { value: 'budget_pct', label: '预算百分比 (%)' },
  { value: 'yoy_pct', label: '同比增幅 (%)' },
];

const THRESHOLD_TYPE_LABEL: Record<ThresholdType, string> = {
  absolute: '绝对值',
  budget_pct: '预算百分比',
  yoy_pct: '同比增幅',
};

const SEVERITY_CONFIG: Record<SeverityLevel, { label: string; color: string }> = {
  info:     { label: '提示',   color: 'blue' },
  warning:  { label: '警告',   color: 'orange' },
  critical: { label: '严重',   color: 'red' },
};

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function calcPct(actual: number, budget: number): number {
  if (!budget || budget === 0) return 0;
  return Math.round((actual / budget) * 100);
}

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

// ─── Tab 1：预算管理 ──────────────────────────────────────────────────────────

interface BudgetTabProps {
  stores: Store[];
}

function BudgetTab({ stores }: BudgetTabProps) {
  const [year, setYear]       = useState<number>(dayjs().year());
  const [month, setMonth]     = useState<number>(dayjs().month() + 1);
  const [storeId, setStoreId] = useState<string>(stores[0]?.id ?? '');
  const [data, setData]       = useState<BudgetVsActual | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  // 设置预算 Modal
  const [modalOpen, setModalOpen]     = useState(false);
  const [submitting, setSubmitting]   = useState(false);
  const [form]                        = Form.useForm();

  const fetchData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ year: String(year), month: String(month), store_id: storeId });
      const json = await txFetchData<BudgetVsActual>(`/api/v1/ops/energy/budget-vs-actual?${params}`);
      setData(json ?? null);
    } catch {
      setError('加载预算对比数据失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [year, month, storeId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 门店列表加载后设默认值
  useEffect(() => {
    if (!storeId && stores.length > 0) {
      setStoreId(stores[0].id);
    }
  }, [stores, storeId]);

  const handleSetBudget = async (values: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/ops/energy/budgets', {
        method: 'POST',
        body: JSON.stringify({
          store_id: storeId,
          year,
          month,
          electricity_budget_kwh: values.electricity_budget_kwh,
          gas_budget_m3:          values.gas_budget_m3,
          water_budget_ton:       values.water_budget_ton,
          cost_budget_fen:        Math.round(Number(values.cost_budget_yuan) * 100),
        }),
      });
      message.success('预算设置成功');
      setModalOpen(false);
      form.resetFields();
      fetchData();
    } catch {
      message.error('保存失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  // 进度条卡片
  const renderMetricCard = (
    label: string,
    icon: React.ReactNode,
    budget: number,
    actual: number,
    unit: string,
    formatFn?: (v: number) => string,
  ) => {
    const pct    = calcPct(actual, budget);
    const over   = pct > 100;
    const fmt    = formatFn ?? ((v: number) => v.toLocaleString('zh-CN'));

    return (
      <Col span={12} key={label}>
        <Card size="small" className="mb-3">
          <div className="flex items-center gap-2 mb-2">
            {icon}
            <Text strong>{label}</Text>
            {over && (
              <Tag color="red" className="ml-auto">超预算 {pct - 100}%</Tag>
            )}
          </div>
          <Row gutter={16} className="mb-2">
            <Col span={12}>
              <div className="text-xs text-gray-500">预算</div>
              <div className="text-base font-medium">
                {budget > 0 ? `${fmt(budget)} ${unit}` : <Text type="secondary">未设置</Text>}
              </div>
            </Col>
            <Col span={12}>
              <div className="text-xs text-gray-500">实际</div>
              <div className="text-base font-medium">{fmt(actual)} {unit}</div>
            </Col>
          </Row>
          <Progress
            percent={Math.min(pct, 100)}
            status={over ? 'exception' : pct >= 80 ? 'active' : 'normal'}
            size="small"
            format={() => `${pct}%`}
            strokeColor={over ? '#A32D2D' : pct >= 80 ? '#BA7517' : '#0F6E56'}
          />
        </Card>
      </Col>
    );
  };

  return (
    <>
      {/* 筛选栏 */}
      <div className="flex flex-wrap gap-3 mb-4 items-center">
        <DatePicker
          picker="month"
          value={dayjs(`${year}-${String(month).padStart(2, '0')}-01`)}
          onChange={(date) => {
            if (date) {
              setYear(date.year());
              setMonth(date.month() + 1);
            }
          }}
          allowClear={false}
          style={{ width: 160 }}
        />
        <Select
          placeholder="选择门店"
          value={storeId || undefined}
          onChange={setStoreId}
          style={{ width: 200 }}
          options={stores.map(s => ({ value: s.id, label: s.name }))}
        />
        <div className="ml-auto">
          <Button
            type="primary"
            icon={<SettingOutlined />}
            onClick={() => setModalOpen(true)}
          >
            设置预算
          </Button>
        </div>
      </div>

      {error && <Alert type="error" message={error} className="mb-4" showIcon closable />}

      {/* 超预算告警横幅 */}
      {data?.alert_triggered && (
        <Alert
          type="error"
          message="能耗超预算告警"
          description="当前所选门店本月能耗已超出预算阈值，请及时排查并采取措施。"
          showIcon
          banner
          className="mb-4"
          style={{ borderLeft: '4px solid #A32D2D' }}
        />
      )}

      <Spin spinning={loading}>
        {data ? (
          <Row gutter={16}>
            {renderMetricCard(
              '电量', <ThunderboltOutlined style={{ color: '#BA7517' }} />,
              data.electricity_budget_kwh, data.electricity_actual_kwh, 'kWh',
            )}
            {renderMetricCard(
              '燃气', <FireOutlined style={{ color: '#A32D2D' }} />,
              data.gas_budget_m3, data.gas_actual_m3, 'm³',
            )}
            {renderMetricCard(
              '水量', <DropboxOutlined style={{ color: '#185FA5' }} />,
              data.water_budget_ton, data.water_actual_ton, 'ton',
            )}
            {renderMetricCard(
              '总费用', <DollarOutlined style={{ color: '#0F6E56' }} />,
              data.cost_budget_fen, data.cost_actual_fen, '元',
              fenToYuan,
            )}
          </Row>
        ) : (
          !loading && !error && (
            <div className="text-center py-12 text-gray-400">
              暂无预算数据，请先设置预算
            </div>
          )
        )}
      </Spin>

      {/* 设置预算 Modal */}
      <Modal
        title={`设置预算 · ${year}年${month}月`}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        footer={null}
        width={560}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleSetBudget}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="电量预算 (kWh)"
                name="electricity_budget_kwh"
                rules={[{ required: true, message: '请填写电量预算' }]}
              >
                <InputNumber min={0} style={{ width: '100%' }} placeholder="如：5000" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="燃气预算 (m³)"
                name="gas_budget_m3"
                rules={[{ required: true, message: '请填写燃气预算' }]}
              >
                <InputNumber min={0} style={{ width: '100%' }} placeholder="如：300" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="水量预算 (ton)"
                name="water_budget_ton"
                rules={[{ required: true, message: '请填写水量预算' }]}
              >
                <InputNumber min={0} style={{ width: '100%' }} placeholder="如：100" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="总费用预算 (元)"
                name="cost_budget_yuan"
                rules={[{ required: true, message: '请填写费用预算' }]}
              >
                <InputNumber min={0} style={{ width: '100%' }} placeholder="如：8000" precision={2} />
              </Form.Item>
            </Col>
          </Row>
          <div className="flex justify-end gap-2 mt-2">
            <Button onClick={() => { setModalOpen(false); form.resetFields(); }}>取消</Button>
            <Button type="primary" htmlType="submit" loading={submitting}>
              保存预算
            </Button>
          </div>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab 2：告警规则 ──────────────────────────────────────────────────────────

function AlertRulesTab() {
  const [rules, setRules]       = useState<AlertRule[]>([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [modalOpen, setModalOpen]   = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [form] = Form.useForm();

  const fetchRules = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await txFetchData<{ items?: AlertRule[] } | AlertRule[]>('/api/v1/ops/energy/alert-rules');
      setRules((Array.isArray(data) ? data : (data as { items?: AlertRule[] }).items) ?? []);
    } catch {
      setError('加载告警规则失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchRules(); }, []);

  const handleCreate = async (values: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/ops/energy/alert-rules', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      message.success('告警规则创建成功');
      setModalOpen(false);
      form.resetFields();
      fetchRules();
    } catch {
      message.error('创建失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggle = async (rule: AlertRule, enabled: boolean) => {
    setTogglingId(rule.id);
    try {
      await txFetchData(`/api/v1/ops/energy/alert-rules/${rule.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_enabled: enabled }),
      });
      message.success(enabled ? '规则已启用' : '规则已停用');
      fetchRules();
    } catch {
      message.error('操作失败，请稍后重试');
    } finally {
      setTogglingId(null);
    }
  };

  const columns: ColumnsType<AlertRule> = [
    {
      title: '规则名称',
      dataIndex: 'name',
      width: 180,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '监控指标',
      dataIndex: 'metric',
      width: 130,
      render: (metric: MetricType) => METRIC_LABEL_MAP[metric] ?? metric,
    },
    {
      title: '阈值类型',
      dataIndex: 'threshold_type',
      width: 130,
      render: (t: ThresholdType) => THRESHOLD_TYPE_LABEL[t] ?? t,
    },
    {
      title: '阈值',
      dataIndex: 'threshold_value',
      width: 100,
      render: (val: number, record: AlertRule) => {
        const suffix = record.threshold_type === 'absolute' ? '' : '%';
        return <Text>{val}{suffix}</Text>;
      },
    },
    {
      title: '严重等级',
      dataIndex: 'severity',
      width: 110,
      render: (severity: SeverityLevel) => (
        <Tag color={SEVERITY_CONFIG[severity]?.color}>
          {SEVERITY_CONFIG[severity]?.label ?? severity}
        </Tag>
      ),
    },
    {
      title: '启用状态',
      dataIndex: 'is_enabled',
      width: 110,
      render: (enabled: boolean, record: AlertRule) => (
        <Switch
          checked={enabled}
          loading={togglingId === record.id}
          onChange={(val) => handleToggle(record, val)}
          checkedChildren="启用"
          unCheckedChildren="停用"
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
  ];

  return (
    <>
      <div className="flex justify-end mb-3">
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setModalOpen(true)}
        >
          新建规则
        </Button>
      </div>

      {error && <Alert type="error" message={error} className="mb-3" showIcon closable />}

      <Table
        rowKey="id"
        columns={columns}
        dataSource={rules}
        loading={loading}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 920 }}
      />

      {/* 新建规则 Modal */}
      <Modal
        title="新建告警规则"
        open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        footer={null}
        width={560}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreate}
          initialValues={{ severity: 'warning', threshold_type: 'budget_pct' }}
        >
          <Form.Item
            label="规则名称"
            name="name"
            rules={[{ required: true, message: '请填写规则名称' }]}
          >
            <Input placeholder="例：电量超预算 110% 告警" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="监控指标"
                name="metric"
                rules={[{ required: true, message: '请选择监控指标' }]}
              >
                <Select options={METRIC_OPTIONS} placeholder="请选择" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="阈值类型"
                name="threshold_type"
                rules={[{ required: true, message: '请选择阈值类型' }]}
              >
                <Select options={THRESHOLD_TYPE_OPTIONS} placeholder="请选择" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="阈值"
                name="threshold_value"
                rules={[{ required: true, message: '请填写阈值' }]}
              >
                <InputNumber min={0} style={{ width: '100%' }} placeholder="如：110" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="严重等级"
                name="severity"
                rules={[{ required: true, message: '请选择严重等级' }]}
              >
                <Select
                  options={Object.entries(SEVERITY_CONFIG).map(([v, c]) => ({
                    value: v,
                    label: (
                      <Tag color={c.color} style={{ marginRight: 0 }}>{c.label}</Tag>
                    ),
                  }))}
                  placeholder="请选择"
                />
              </Form.Item>
            </Col>
          </Row>
          <div className="flex justify-end gap-2 mt-2">
            <Button onClick={() => { setModalOpen(false); form.resetFields(); }}>取消</Button>
            <Button type="primary" htmlType="submit" loading={submitting}>
              创建规则
            </Button>
          </div>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab 3：历史预算 ──────────────────────────────────────────────────────────

interface HistoryTabProps {
  stores: Store[];
}

function HistoryTab({ stores }: HistoryTabProps) {
  const [budgets, setBudgets]   = useState<EnergyBudget[]>([]);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [queryYear, setQueryYear] = useState<number>(dayjs().year());
  const [storeId, setStoreId]   = useState<string>(stores[0]?.id ?? '');

  const fetchBudgets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ year: String(queryYear) });
      if (storeId) params.set('store_id', storeId);
      const data = await txFetchData<{ items?: EnergyBudget[] } | EnergyBudget[]>(`/api/v1/ops/energy/budgets?${params}`);
      setBudgets((Array.isArray(data) ? data : (data as { items?: EnergyBudget[] }).items) ?? []);
    } catch {
      setError('加载历史预算失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [queryYear, storeId]);

  useEffect(() => { fetchBudgets(); }, [fetchBudgets]);

  useEffect(() => {
    if (!storeId && stores.length > 0) setStoreId(stores[0].id);
  }, [stores, storeId]);

  const columns: ColumnsType<EnergyBudget> = [
    {
      title: '年月',
      key: 'period',
      width: 120,
      render: (_: unknown, r: EnergyBudget) => (
        <Text strong>{r.year}年{String(r.month).padStart(2, '0')}月</Text>
      ),
    },
    {
      title: '电量预算 (kWh)',
      dataIndex: 'electricity_budget_kwh',
      width: 150,
      render: (v: number) => v.toLocaleString('zh-CN'),
    },
    {
      title: '燃气预算 (m³)',
      dataIndex: 'gas_budget_m3',
      width: 140,
      render: (v: number) => v.toLocaleString('zh-CN'),
    },
    {
      title: '水量预算 (ton)',
      dataIndex: 'water_budget_ton',
      width: 140,
      render: (v: number) => v.toLocaleString('zh-CN'),
    },
    {
      title: '总费用预算 (元)',
      dataIndex: 'cost_budget_fen',
      width: 150,
      render: (v: number) => `¥${fenToYuan(v)}`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
  ];

  return (
    <>
      <div className="flex flex-wrap gap-3 mb-4 items-center">
        <DatePicker
          picker="year"
          value={dayjs(`${queryYear}-01-01`)}
          onChange={(date) => { if (date) setQueryYear(date.year()); }}
          allowClear={false}
          style={{ width: 120 }}
        />
        <Select
          placeholder="选择门店"
          value={storeId || undefined}
          onChange={setStoreId}
          allowClear
          style={{ width: 200 }}
          options={stores.map(s => ({ value: s.id, label: s.name }))}
        />
      </div>

      {error && <Alert type="error" message={error} className="mb-3" showIcon closable />}

      <Table
        rowKey="id"
        columns={columns}
        dataSource={budgets}
        loading={loading}
        pagination={{ pageSize: 12, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 860 }}
      />
    </>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function EnergyBudgetPage() {
  const [stores, setStores]         = useState<Store[]>([]);
  const [storesLoading, setStoresLoading] = useState(false);
  const [activeTab, setActiveTab]   = useState('budget');

  const fetchStores = async () => {
    setStoresLoading(true);
    try {
      const data = await txFetchData<{ items?: Store[] } | Store[]>('/api/v1/org/stores');
      setStores((Array.isArray(data) ? data : (data as { items?: Store[] }).items) ?? []);
    } catch {
      message.warning('门店列表加载失败，部分功能可能受限');
    } finally {
      setStoresLoading(false);
    }
  };

  useEffect(() => { fetchStores(); }, []);

  return (
    <div className="p-4">
      {/* 页面标题 */}
      <div className="mb-4">
        <h2 className="text-xl font-bold text-gray-800 m-0">能耗预算 & 告警规则</h2>
        <p className="text-sm text-gray-500 mt-1 mb-0">
          管理门店能耗预算目标、查看用能进度、配置超标告警规则
        </p>
      </div>

      {/* 顶部指标概览 */}
      <Row gutter={16} className="mb-4">
        <Col span={8}>
          <Card>
            <Statistic
              title={
                <Space>
                  <ThunderboltOutlined style={{ color: '#BA7517' }} />
                  <span>电量监控</span>
                </Space>
              }
              value="实时监控中"
              valueStyle={{ fontSize: 16, color: '#0F6E56' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title={
                <Space>
                  <AlertOutlined style={{ color: '#A32D2D' }} />
                  <span>告警规则</span>
                </Space>
              }
              value="已配置告警"
              valueStyle={{ fontSize: 16, color: '#185FA5' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title={
                <Space>
                  <HistoryOutlined style={{ color: '#5F5E5A' }} />
                  <span>历史追溯</span>
                </Space>
              }
              value="近12个月"
              valueStyle={{ fontSize: 16, color: '#2C2C2A' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Tab 区域 */}
      <Card>
        <Spin spinning={storesLoading} tip="加载门店列表...">
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={[
              {
                key: 'budget',
                label: (
                  <Space>
                    <ThunderboltOutlined />
                    预算管理
                  </Space>
                ),
                children: <BudgetTab stores={stores} />,
              },
              {
                key: 'alert-rules',
                label: (
                  <Space>
                    <AlertOutlined />
                    告警规则
                  </Space>
                ),
                children: <AlertRulesTab />,
              },
              {
                key: 'history',
                label: (
                  <Space>
                    <HistoryOutlined />
                    历史预算
                  </Space>
                ),
                children: <HistoryTab stores={stores} />,
              },
            ]}
          />
        </Spin>
      </Card>
    </div>
  );
}
