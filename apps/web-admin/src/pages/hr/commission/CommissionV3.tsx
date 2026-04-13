/**
 * CommissionV3 — 计件提成3.0（对标天财计件提成3.0，模块2.6）
 * 域F · 组织人事 · HR Admin
 *
 * Tab1：方案列表       — 新建/复制/停用绩效方案
 * Tab2：提成规则配置   — 选方案 → 配置4类提成维度
 * Tab3：员工提成查询   — 日期范围+员工搜索 → 明细表格
 * Tab4：月度结算       — 一键批量结算 → 报表下载
 *
 * API prefix: /api/v1/commission
 */

import { useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  PlusOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const { TabPane } = Tabs;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface CommissionScheme {
  id: string;
  name: string;
  applicable_stores: string[];
  effective_date: string | null;
  expiry_date: string | null;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

interface CommissionRule {
  id: string;
  scheme_id: string;
  rule_type: 'dish' | 'table' | 'time_slot' | 'revenue_tier';
  params: Record<string, unknown>;
  amount_fen: number;
  description: string | null;
  created_at: string;
}

interface CommissionRecord {
  id: string;
  employee_id: string;
  store_id: string;
  year_month: string;
  total_commission_fen: number;
  breakdown: unknown[];
  status: 'pending' | 'settled' | 'voided';
  settled_at: string | null;
}

interface StaffDetail {
  employee_id: string;
  year_month: string;
  records: CommissionRecord[];
  total_commission_fen: number;
}

interface MonthlyReport {
  year_month: string;
  page: number;
  size: number;
  total: number;
  grand_total_commission_fen: number;
  items: CommissionRecord[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const RULE_TYPE_LABELS: Record<string, string> = {
  dish: '品项提成',
  table: '桌型提成',
  time_slot: '时段提成',
  revenue_tier: '营收阶梯',
};

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  pending: { text: '待结算', color: 'orange' },
  settled: { text: '已结算', color: 'green' },
  voided: { text: '已作废', color: 'red' },
};

// ─── Tab1: 方案列表 ──────────────────────────────────────────────────────────

function SchemesTab() {
  const actionRef = useRef<ActionType>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [copyModalOpen, setCopyModalOpen] = useState(false);
  const [copyTarget, setCopyTarget] = useState<CommissionScheme | null>(null);
  const [form] = Form.useForm();
  const [copyForm] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload = {
        name: values.name,
        applicable_stores: values.applicable_stores
          ? values.applicable_stores.split(',').map((s: string) => s.trim()).filter(Boolean)
          : [],
        effective_date: values.effective_date
          ? dayjs(values.effective_date).format('YYYY-MM-DD')
          : null,
        expiry_date: values.expiry_date
          ? dayjs(values.expiry_date).format('YYYY-MM-DD')
          : null,
        description: values.description || null,
      };
      await txFetchData('/api/v1/commission/schemes', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      message.success('方案创建成功');
      form.resetFields();
      setCreateModalOpen(false);
      actionRef.current?.reload();
    } catch (err: unknown) {
      if (err instanceof Error) message.error(`创建失败：${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeactivate = async (id: string) => {
    try {
      await txFetchData(`/api/v1/commission/schemes/${id}`, { method: 'DELETE' });
      message.success('方案已停用');
      actionRef.current?.reload();
    } catch (err: unknown) {
      if (err instanceof Error) message.error(`停用失败：${err.message}`);
    }
  };

  const handleCopySubmit = async () => {
    if (!copyTarget) return;
    try {
      const values = await copyForm.validateFields();
      setSubmitting(true);
      const payload = {
        target_stores: values.target_stores
          ? values.target_stores.split(',').map((s: string) => s.trim()).filter(Boolean)
          : [],
        new_name: values.new_name || undefined,
        effective_date: values.effective_date
          ? dayjs(values.effective_date).format('YYYY-MM-DD')
          : undefined,
      };
      const resp = await txFetchData(
        `/api/v1/commission/schemes/${copyTarget.id}/copy`,
        { method: 'POST', body: JSON.stringify(payload) },
      );
      message.success(`复制成功，新方案ID：${resp?.data?.id}`);
      copyForm.resetFields();
      setCopyModalOpen(false);
      setCopyTarget(null);
      actionRef.current?.reload();
    } catch (err: unknown) {
      if (err instanceof Error) message.error(`复制失败：${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ProColumns<CommissionScheme>[] = [
    { title: '方案名称', dataIndex: 'name', width: 180 },
    {
      title: '适用门店',
      dataIndex: 'applicable_stores',
      width: 140,
      hideInSearch: true,
      renderText: (v: string[]) =>
        v && v.length > 0 ? `${v.length} 家门店` : '全部门店',
    },
    {
      title: '生效日期',
      dataIndex: 'effective_date',
      width: 120,
      hideInSearch: true,
      renderText: (v: string | null) => v || '-',
    },
    {
      title: '失效日期',
      dataIndex: 'expiry_date',
      width: 120,
      hideInSearch: true,
      renderText: (v: string | null) => v || '长期有效',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      hideInSearch: true,
      render: (v: boolean) => (
        <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
      ),
    },
    {
      title: '操作',
      width: 180,
      hideInSearch: true,
      render: (_: unknown, record: CommissionScheme) => (
        <Space>
          <Tooltip title="复制到其他门店">
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => {
                setCopyTarget(record);
                setCopyModalOpen(true);
              }}
            >
              复制
            </Button>
          </Tooltip>
          {record.is_active && (
            <Popconfirm
              title="确认停用该方案？"
              onConfirm={() => handleDeactivate(record.id)}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>
                停用
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<CommissionScheme>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            onClick={() => setCreateModalOpen(true)}
          >
            新建方案
          </Button>,
        ]}
        request={async (params) => {
          const resp = await txFetchData(
            `/api/v1/commission/schemes?is_active=${params.is_active ?? true}`,
          );
          return {
            data: resp?.data?.items ?? [],
            total: resp?.data?.total ?? 0,
            success: true,
          };
        }}
        pagination={{ pageSize: 20 }}
        search={false}
      />

      {/* 新建方案 Modal */}
      <Modal
        title="新建绩效提成方案"
        open={createModalOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateModalOpen(false); form.resetFields(); }}
        confirmLoading={submitting}
        okText="创建"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="方案名称" rules={[{ required: true }]}>
            <Input placeholder="如：厨师计件提成2026Q2" maxLength={100} />
          </Form.Item>
          <Form.Item
            name="applicable_stores"
            label="适用门店ID（逗号分隔，留空=全部门店）"
          >
            <Input placeholder="store-uuid-1, store-uuid-2" />
          </Form.Item>
          <Form.Item name="effective_date" label="生效日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="expiry_date" label="失效日期（不填=长期有效）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 复制方案 Modal */}
      <Modal
        title={`复制方案：${copyTarget?.name}`}
        open={copyModalOpen}
        onOk={handleCopySubmit}
        onCancel={() => { setCopyModalOpen(false); copyForm.resetFields(); }}
        confirmLoading={submitting}
        okText="确认复制"
      >
        <Form form={copyForm} layout="vertical">
          <Form.Item name="new_name" label="新方案名称（留空自动加[副本]后缀）">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            name="target_stores"
            label="目标门店ID（逗号分隔）"
            rules={[{ required: true, message: '请填写目标门店' }]}
          >
            <Input placeholder="store-uuid-1, store-uuid-2" />
          </Form.Item>
          <Form.Item name="effective_date" label="生效日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab2: 提成规则配置 ──────────────────────────────────────────────────────

function RulesTab() {
  const [schemes, setSchemes] = useState<CommissionScheme[]>([]);
  const [selectedSchemeId, setSelectedSchemeId] = useState<string | null>(null);
  const [rules, setRules] = useState<CommissionRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [ruleModalOpen, setRuleModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const loadSchemes = async () => {
    const resp = await txFetchData('/api/v1/commission/schemes?is_active=true');
    setSchemes(resp?.data?.items ?? []);
  };

  const loadRules = async (schemeId: string) => {
    setLoading(true);
    try {
      const resp = await txFetchData(`/api/v1/commission/schemes/${schemeId}/rules`);
      setRules(resp?.data?.items ?? []);
    } finally {
      setLoading(false);
    }
  };

  const handleSchemeChange = (value: string) => {
    setSelectedSchemeId(value);
    loadRules(value);
  };

  const handleAddRule = async () => {
    if (!selectedSchemeId) return;
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      let params: Record<string, unknown> = {};
      if (values.rule_type === 'dish') {
        params = {
          dish_id: values.dish_id || null,
          dish_name: values.dish_name || null,
          min_qty: Number(values.min_qty) || 1,
        };
      } else if (values.rule_type === 'table') {
        params = { table_type: values.table_type || null };
      } else if (values.rule_type === 'time_slot') {
        params = {
          start_time: values.start_time || null,
          end_time: values.end_time || null,
          multiplier: Number(values.multiplier) || 1,
        };
      } else if (values.rule_type === 'revenue_tier') {
        try {
          params = { tiers: JSON.parse(values.tiers_json || '[]') };
        } catch {
          message.error('营收阶梯JSON格式有误');
          setSubmitting(false);
          return;
        }
      }
      const payload = {
        rule_type: values.rule_type,
        params,
        amount_fen: Math.round((Number(values.amount_yuan) || 0) * 100),
        description: values.description || null,
      };
      await txFetchData(
        `/api/v1/commission/schemes/${selectedSchemeId}/rules`,
        { method: 'POST', body: JSON.stringify(payload) },
      );
      message.success('规则添加成功');
      form.resetFields();
      setRuleModalOpen(false);
      loadRules(selectedSchemeId);
    } catch (err: unknown) {
      if (err instanceof Error) message.error(`添加失败：${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const ruleColumns = [
    {
      title: '规则类型',
      dataIndex: 'rule_type',
      width: 120,
      render: (v: string) => (
        <Tag color="blue">{RULE_TYPE_LABELS[v] ?? v}</Tag>
      ),
    },
    {
      title: '基础金额',
      dataIndex: 'amount_fen',
      width: 120,
      render: (v: number) => fenToYuan(v),
    },
    {
      title: '规则参数',
      dataIndex: 'params',
      render: (v: Record<string, unknown>) => (
        <Text code style={{ fontSize: 12 }}>
          {JSON.stringify(v)}
        </Text>
      ),
    },
    { title: '备注', dataIndex: 'description', width: 160 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
  ];

  return (
    <Card>
      <Space style={{ marginBottom: 16 }} wrap>
        <Text strong>选择方案：</Text>
        <Select
          style={{ width: 280 }}
          placeholder="选择绩效方案"
          onFocus={loadSchemes}
          onChange={handleSchemeChange}
          options={schemes.map((s) => ({ label: s.name, value: s.id }))}
        />
        {selectedSchemeId && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            onClick={() => setRuleModalOpen(true)}
          >
            添加提成规则
          </Button>
        )}
      </Space>

      <Table
        rowKey="id"
        columns={ruleColumns}
        dataSource={rules}
        loading={loading}
        pagination={{ pageSize: 20 }}
        locale={{ emptyText: selectedSchemeId ? '暂无规则，点击添加' : '请先选择方案' }}
      />

      <Modal
        title="添加提成规则"
        open={ruleModalOpen}
        onOk={handleAddRule}
        onCancel={() => { setRuleModalOpen(false); form.resetFields(); }}
        confirmLoading={submitting}
        okText="保存规则"
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="rule_type"
            label="规则类型"
            rules={[{ required: true }]}
          >
            <Select
              options={Object.entries(RULE_TYPE_LABELS).map(([k, v]) => ({
                label: v,
                value: k,
              }))}
              placeholder="选择提成维度"
            />
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) => prev.rule_type !== cur.rule_type}
          >
            {({ getFieldValue }) => {
              const rt = getFieldValue('rule_type');
              if (rt === 'dish') {
                return (
                  <>
                    <Form.Item name="dish_id" label="菜品ID（可选）">
                      <Input placeholder="菜品UUID" />
                    </Form.Item>
                    <Form.Item name="dish_name" label="菜品名称">
                      <Input placeholder="如：红烧肉" />
                    </Form.Item>
                    <Form.Item name="min_qty" label="最低起算件数" initialValue={1}>
                      <Input type="number" min={1} />
                    </Form.Item>
                  </>
                );
              }
              if (rt === 'table') {
                return (
                  <Form.Item name="table_type" label="桌型">
                    <Input placeholder="如：大桌/包厢/散台" />
                  </Form.Item>
                );
              }
              if (rt === 'time_slot') {
                return (
                  <>
                    <Form.Item name="start_time" label="开始时间（HH:mm）">
                      <Input placeholder="11:00" />
                    </Form.Item>
                    <Form.Item name="end_time" label="结束时间（HH:mm）">
                      <Input placeholder="14:00" />
                    </Form.Item>
                    <Form.Item name="multiplier" label="倍率" initialValue={1}>
                      <Input type="number" min={0.1} step={0.1} />
                    </Form.Item>
                  </>
                );
              }
              if (rt === 'revenue_tier') {
                return (
                  <Form.Item
                    name="tiers_json"
                    label='阶梯配置（JSON格式，金额单位：分）'
                    rules={[{ required: true }]}
                  >
                    <Input.TextArea
                      rows={4}
                      placeholder='[{"min_fen":0,"max_fen":100000,"rate_bps":100},{"min_fen":100000,"max_fen":null,"rate_bps":150}]'
                    />
                  </Form.Item>
                );
              }
              return null;
            }}
          </Form.Item>

          <Form.Item
            name="amount_yuan"
            label="基础金额（元）"
            initialValue={0}
          >
            <Input type="number" min={0} step={0.01} placeholder="0.00" />
          </Form.Item>
          <Form.Item name="description" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

// ─── Tab3: 员工提成查询 ──────────────────────────────────────────────────────

function StaffQueryTab() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<StaffDetail | null>(null);
  const [form] = Form.useForm();

  const handleSearch = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const yearMonth = dayjs(values.year_month).format('YYYY-MM');
      const resp = await txFetchData(
        `/api/v1/commission/staff/${values.employee_id}/detail?year_month=${yearMonth}`,
      );
      setResult(resp?.data ?? null);
    } catch (err: unknown) {
      if (err instanceof Error) message.error(`查询失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const detailColumns = [
    { title: '门店ID', dataIndex: 'store_id', width: 280 },
    { title: '月份', dataIndex: 'year_month', width: 100 },
    {
      title: '提成总额',
      dataIndex: 'total_commission_fen',
      width: 120,
      render: (v: number) => (
        <Text strong style={{ color: TX_PRIMARY }}>{fenToYuan(v)}</Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => {
        const s = STATUS_LABELS[v] ?? { text: v, color: 'default' };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '结算时间',
      dataIndex: 'settled_at',
      width: 180,
      render: (v: string | null) =>
        v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '明细',
      dataIndex: 'breakdown',
      render: (v: unknown[]) => (
        <Tooltip title={<pre style={{ maxWidth: 400 }}>{JSON.stringify(v, null, 2)}</pre>}>
          <Button type="link" size="small">{v?.length ?? 0} 条</Button>
        </Tooltip>
      ),
    },
  ];

  return (
    <Card>
      <Form form={form} layout="inline" style={{ marginBottom: 16 }}>
        <Form.Item
          name="employee_id"
          label="员工ID"
          rules={[{ required: true, message: '请输入员工UUID' }]}
        >
          <Input
            prefix={<UserOutlined />}
            placeholder="员工UUID"
            style={{ width: 280 }}
          />
        </Form.Item>
        <Form.Item
          name="year_month"
          label="月份"
          rules={[{ required: true }]}
          initialValue={dayjs()}
        >
          <DatePicker picker="month" />
        </Form.Item>
        <Form.Item>
          <Button
            type="primary"
            loading={loading}
            onClick={handleSearch}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            查询
          </Button>
        </Form.Item>
      </Form>

      {result && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="本月提成总额"
                  value={fenToYuan(result.total_commission_fen)}
                  valueStyle={{ color: TX_PRIMARY, fontWeight: 'bold' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="记录数"
                  value={result.records.length}
                  suffix="条"
                />
              </Card>
            </Col>
          </Row>
          <Table
            rowKey="id"
            columns={detailColumns}
            dataSource={result.records}
            pagination={false}
          />
        </>
      )}
    </Card>
  );
}

// ─── Tab4: 月度结算 ──────────────────────────────────────────────────────────

function MonthlySettleTab() {
  const actionRef = useRef<ActionType>(null);
  const [settling, setSettling] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [report, setReport] = useState<MonthlyReport | null>(null);
  const [settleForm] = Form.useForm();
  const [filterMonth, setFilterMonth] = useState(dayjs().format('YYYY-MM'));

  const handleSettle = async () => {
    try {
      const values = await settleForm.validateFields();
      setSettling(true);
      const yearMonth = dayjs(values.year_month).format('YYYY-MM');
      const payload = {
        year_month: yearMonth,
        store_ids: values.store_ids
          ? values.store_ids.split(',').map((s: string) => s.trim()).filter(Boolean)
          : [],
      };
      const resp = await txFetchData('/api/v1/commission/monthly-settle', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      const data = resp?.data;
      message.success(
        `结算完成：处理 ${data?.total_processed} 人，成功 ${data?.settled_count} 人，跳过 ${data?.skipped_count} 人`,
      );
      // 自动加载报表
      const month = yearMonth;
      setFilterMonth(month);
      loadReport(month);
    } catch (err: unknown) {
      if (err instanceof Error) message.error(`结算失败：${err.message}`);
    } finally {
      setSettling(false);
    }
  };

  const loadReport = async (month: string) => {
    setReportLoading(true);
    try {
      const resp = await txFetchData(
        `/api/v1/commission/monthly-report?year_month=${month}&page=1&size=50`,
      );
      setReport(resp?.data ?? null);
    } catch (err: unknown) {
      if (err instanceof Error) message.error(`加载报表失败：${err.message}`);
    } finally {
      setReportLoading(false);
    }
  };

  const handleDownload = () => {
    if (!report) return;
    const rows = [
      ['员工ID', '门店ID', '月份', '提成总额(元)', '状态', '结算时间'],
      ...report.items.map((r) => [
        r.employee_id,
        r.store_id,
        r.year_month,
        (r.total_commission_fen / 100).toFixed(2),
        STATUS_LABELS[r.status]?.text ?? r.status,
        r.settled_at ? dayjs(r.settled_at).format('YYYY-MM-DD HH:mm') : '',
      ]),
    ];
    const csv = rows.map((r) => r.join(',')).join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `commission-report-${filterMonth}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const reportColumns = [
    { title: '员工ID', dataIndex: 'employee_id', width: 280, ellipsis: true },
    { title: '门店ID', dataIndex: 'store_id', width: 280, ellipsis: true },
    { title: '月份', dataIndex: 'year_month', width: 100 },
    {
      title: '提成总额',
      dataIndex: 'total_commission_fen',
      width: 120,
      render: (v: number) => (
        <Text strong style={{ color: TX_PRIMARY }}>{fenToYuan(v)}</Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => {
        const s = STATUS_LABELS[v] ?? { text: v, color: 'default' };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '结算时间',
      dataIndex: 'settled_at',
      width: 180,
      render: (v: string | null) =>
        v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
  ];

  return (
    <Card>
      <Row gutter={24}>
        <Col span={12}>
          <Card size="small" title="一键月度结算" style={{ marginBottom: 16 }}>
            <Form form={settleForm} layout="inline">
              <Form.Item
                name="year_month"
                label="结算月份"
                rules={[{ required: true }]}
                initialValue={dayjs().subtract(1, 'month')}
              >
                <DatePicker picker="month" />
              </Form.Item>
              <Form.Item name="store_ids" label="门店（留空=全部）">
                <Input placeholder="逗号分隔的门店ID" style={{ width: 200 }} />
              </Form.Item>
              <Form.Item>
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  loading={settling}
                  onClick={handleSettle}
                  style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
                >
                  执行结算
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="查询月报" style={{ marginBottom: 16 }}>
            <Space>
              <DatePicker
                picker="month"
                value={dayjs(filterMonth)}
                onChange={(v) => {
                  if (v) {
                    const m = v.format('YYYY-MM');
                    setFilterMonth(m);
                    loadReport(m);
                  }
                }}
              />
              <Button
                loading={reportLoading}
                onClick={() => loadReport(filterMonth)}
              >
                刷新
              </Button>
              {report && (
                <Button
                  icon={<DownloadOutlined />}
                  onClick={handleDownload}
                >
                  下载CSV
                </Button>
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      {report && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title={`${report.year_month} 提成总发放`}
                  value={fenToYuan(report.grand_total_commission_fen)}
                  valueStyle={{ color: TX_PRIMARY, fontWeight: 'bold' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="结算人数" value={report.total} suffix="人" />
              </Card>
            </Col>
          </Row>

          <Table
            rowKey="id"
            columns={reportColumns}
            dataSource={report.items}
            loading={reportLoading}
            pagination={{ pageSize: 20 }}
          />
        </>
      )}
    </Card>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function CommissionV3() {
  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <SettingOutlined style={{ marginRight: 8, color: TX_PRIMARY }} />
        计件提成3.0
        <Text
          type="secondary"
          style={{ fontSize: 13, fontWeight: 'normal', marginLeft: 12 }}
        >
          对标天财计件提成3.0 — 模块2.6
        </Text>
      </Title>

      <Tabs defaultActiveKey="schemes">
        <TabPane tab="方案列表" key="schemes">
          <SchemesTab />
        </TabPane>
        <TabPane tab="提成规则配置" key="rules">
          <RulesTab />
        </TabPane>
        <TabPane tab="员工提成查询" key="staff">
          <StaffQueryTab />
        </TabPane>
        <TabPane tab="月度结算" key="settle">
          <MonthlySettleTab />
        </TabPane>
      </Tabs>
    </div>
  );
}
