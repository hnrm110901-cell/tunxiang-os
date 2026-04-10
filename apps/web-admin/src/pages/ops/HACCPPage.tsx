/**
 * HACCP 食安检查管理页面
 * 路由：/ops/haccp
 * API：GET/POST /api/v1/ops/haccp/plans
 *      GET/POST /api/v1/ops/haccp/records
 *      GET      /api/v1/ops/haccp/stats
 *      GET      /api/v1/ops/haccp/overdue
 */

import { useState, useEffect, useRef } from 'react';
import {
  Card, Tabs, Table, Button, Modal, Form, Input, Select, Switch,
  DatePicker, Drawer, Tag, Alert, Spin, Row, Col, Statistic,
  Space, message, Badge, Descriptions, Typography, Divider,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  PlusOutlined, ExclamationCircleOutlined, CheckCircleOutlined,
  CloseCircleOutlined, CalendarOutlined, SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetch } from '../../api';

const { RangePicker } = DatePicker;
const { Text } = Typography;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type CheckType = 'temperature' | 'hygiene' | 'pest' | 'supplier' | 'equipment';
type Frequency = 'daily' | 'weekly' | 'monthly' | 'quarterly';

interface CheckItemDef {
  key: string;
  name: string;
  unit?: string;
  min_value?: number;
  max_value?: number;
}

interface HACCPPlan {
  id: string;
  name: string;
  check_type: CheckType;
  frequency: Frequency;
  responsible_role: string;
  is_enabled: boolean;
  check_items: CheckItemDef[];
  created_at: string;
}

interface CheckItemResult {
  key: string;
  name: string;
  passed: boolean;
  value?: string;
  note?: string;
}

interface HACCPRecord {
  id: string;
  plan_id: string;
  plan_name: string;
  check_date: string;
  operator: string;
  is_qualified: boolean;
  ccp_failure_count: number;
  results: CheckItemResult[];
  created_at: string;
}

interface HACCPStats {
  monthly_qualified_rate: number;
  ccp_failure_count: number;
  overdue_count: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const CHECK_TYPE_MAP: Record<CheckType, { label: string; color: string }> = {
  temperature: { label: '温度检查', color: 'blue' },
  hygiene:     { label: '卫生检查', color: 'green' },
  pest:        { label: '虫害防治', color: 'orange' },
  supplier:    { label: '供应商审核', color: 'purple' },
  equipment:   { label: '设备检查', color: 'cyan' },
};

const FREQUENCY_MAP: Record<Frequency, string> = {
  daily:     '每日',
  weekly:    '每周',
  monthly:   '每月',
  quarterly: '每季度',
};

const CHECK_TYPE_OPTIONS = Object.entries(CHECK_TYPE_MAP).map(([v, c]) => ({
  value: v, label: c.label,
}));

const FREQUENCY_OPTIONS = Object.entries(FREQUENCY_MAP).map(([v, l]) => ({
  value: v, label: l,
}));

const ROLE_OPTIONS = [
  { value: '食安专员', label: '食安专员' },
  { value: '厨师长', label: '厨师长' },
  { value: '店长', label: '店长' },
  { value: '采购员', label: '采购员' },
  { value: '设备管理员', label: '设备管理员' },
];

// ─── 统计卡片 ────────────────────────────────────────────────────────────────

interface StatsCardsProps {
  stats: HACCPStats | null;
  loading: boolean;
}

function StatsCards({ stats, loading }: StatsCardsProps) {
  return (
    <Row gutter={16} className="mb-4">
      <Col span={8}>
        <Card>
          <Statistic
            title={
              <Space>
                <SafetyCertificateOutlined style={{ color: '#0F6E56' }} />
                <span>本月合格率</span>
              </Space>
            }
            value={stats ? (stats.monthly_qualified_rate * 100).toFixed(1) : '--'}
            suffix="%"
            loading={loading}
            valueStyle={{
              color: stats && stats.monthly_qualified_rate >= 0.9
                ? '#0F6E56'
                : stats && stats.monthly_qualified_rate >= 0.7
                  ? '#BA7517'
                  : '#A32D2D',
            }}
          />
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Statistic
            title={
              <Space>
                <ExclamationCircleOutlined style={{ color: '#BA7517' }} />
                <span>关键失控次数</span>
              </Space>
            }
            value={stats?.ccp_failure_count ?? '--'}
            loading={loading}
            valueStyle={{
              color: stats && stats.ccp_failure_count > 0 ? '#A32D2D' : '#0F6E56',
            }}
          />
        </Card>
      </Col>
      <Col span={8}>
        <Card>
          <Statistic
            title={
              <Space>
                <WarningOutlined style={{ color: '#A32D2D' }} />
                <span>逾期未完成检查</span>
              </Space>
            }
            value={stats?.overdue_count ?? '--'}
            loading={loading}
            valueStyle={{
              color: stats && stats.overdue_count > 0 ? '#A32D2D' : '#0F6E56',
            }}
            suffix={
              stats && stats.overdue_count > 0
                ? <Badge status="error" style={{ marginLeft: 4 }} />
                : null
            }
          />
        </Card>
      </Col>
    </Row>
  );
}

// ─── 检查计划 Tab ─────────────────────────────────────────────────────────────

interface PlansTabProps {
  plans: HACCPPlan[];
  loading: boolean;
  onRefresh: () => void;
}

function PlansTab({ plans, loading, onRefresh }: PlansTabProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();
  const [checkItems, setCheckItems] = useState<CheckItemDef[]>([{ key: '1', name: '' }]);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const handleAddItem = () => {
    setCheckItems(prev => [
      ...prev,
      { key: String(Date.now()), name: '' },
    ]);
  };

  const handleRemoveItem = (key: string) => {
    setCheckItems(prev => prev.filter(i => i.key !== key));
  };

  const handleItemChange = (key: string, field: keyof CheckItemDef, value: string) => {
    setCheckItems(prev => prev.map(i => i.key === key ? { ...i, [field]: value } : i));
  };

  const handleCreate = async (values: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/haccp/plans', {
        method: 'POST',
        body: JSON.stringify({
          ...values,
          check_items: checkItems.filter(i => i.name.trim()),
        }),
      });
      message.success('检查计划创建成功');
      setModalOpen(false);
      form.resetFields();
      setCheckItems([{ key: '1', name: '' }]);
      onRefresh();
    } catch {
      message.error('创建失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggle = async (plan: HACCPPlan, enabled: boolean) => {
    setTogglingId(plan.id);
    try {
      await txFetch(`/api/v1/ops/haccp/plans/${plan.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_enabled: enabled }),
      });
      message.success(enabled ? '计划已启用' : '计划已停用');
      onRefresh();
    } catch {
      message.error('操作失败，请稍后重试');
    } finally {
      setTogglingId(null);
    }
  };

  const columns: ColumnsType<HACCPPlan> = [
    {
      title: '计划名称',
      dataIndex: 'name',
      width: 200,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '检查类型',
      dataIndex: 'check_type',
      width: 130,
      render: (type: CheckType) => (
        <Tag color={CHECK_TYPE_MAP[type]?.color}>
          {CHECK_TYPE_MAP[type]?.label ?? type}
        </Tag>
      ),
    },
    {
      title: '频次',
      dataIndex: 'frequency',
      width: 100,
      render: (freq: Frequency) => FREQUENCY_MAP[freq] ?? freq,
    },
    {
      title: '负责角色',
      dataIndex: 'responsible_role',
      width: 120,
    },
    {
      title: '检查项数',
      dataIndex: 'check_items',
      width: 100,
      render: (items: CheckItemDef[]) => `${items?.length ?? 0} 项`,
    },
    {
      title: '启用状态',
      dataIndex: 'is_enabled',
      width: 100,
      render: (enabled: boolean, record: HACCPPlan) => (
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
          新建计划
        </Button>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={plans}
        loading={loading}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 900 }}
      />

      {/* 新建计划 Modal */}
      <Modal
        title="新建检查计划"
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
          setCheckItems([{ key: '1', name: '' }]);
        }}
        footer={null}
        width={640}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreate}
          initialValues={{ is_enabled: true }}
        >
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item
                label="计划名称"
                name="name"
                rules={[{ required: true, message: '请填写计划名称' }]}
              >
                <Input placeholder="例：每日食材温度检查" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="检查类型"
                name="check_type"
                rules={[{ required: true, message: '请选择检查类型' }]}
              >
                <Select options={CHECK_TYPE_OPTIONS} placeholder="请选择" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="检查频次"
                name="frequency"
                rules={[{ required: true, message: '请选择频次' }]}
              >
                <Select options={FREQUENCY_OPTIONS} placeholder="请选择" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="负责角色"
                name="responsible_role"
                rules={[{ required: true, message: '请选择负责角色' }]}
              >
                <Select options={ROLE_OPTIONS} placeholder="请选择" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="默认启用" name="is_enabled" valuePropName="checked">
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>
            </Col>
          </Row>

          <Divider orientation="left" plain>检查项列表</Divider>

          <div className="space-y-2 mb-3">
            {checkItems.map((item, idx) => (
              <Row gutter={8} key={item.key} align="middle">
                <Col flex="auto">
                  <Input
                    placeholder={`检查项 ${idx + 1}（例：冷藏柜温度）`}
                    value={item.name}
                    onChange={(e) => handleItemChange(item.key, 'name', e.target.value)}
                  />
                </Col>
                <Col flex="120px">
                  <Input
                    placeholder="单位（如：℃）"
                    value={item.unit}
                    onChange={(e) => handleItemChange(item.key, 'unit', e.target.value)}
                  />
                </Col>
                <Col flex="none">
                  <Button
                    type="text"
                    danger
                    disabled={checkItems.length === 1}
                    onClick={() => handleRemoveItem(item.key)}
                  >
                    删除
                  </Button>
                </Col>
              </Row>
            ))}
          </div>
          <Button type="dashed" block icon={<PlusOutlined />} onClick={handleAddItem}>
            添加检查项
          </Button>

          <div className="flex justify-end gap-2 mt-4">
            <Button onClick={() => setModalOpen(false)}>取消</Button>
            <Button type="primary" htmlType="submit" loading={submitting}>
              创建计划
            </Button>
          </div>
        </Form>
      </Modal>
    </>
  );
}

// ─── 执行记录 Tab ─────────────────────────────────────────────────────────────

interface RecordsTabProps {
  plans: HACCPPlan[];
}

function RecordsTab({ plans }: RecordsTabProps) {
  const [records, setRecords] = useState<HACCPRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const [qualifiedFilter, setQualifiedFilter] = useState<boolean | null>(null);

  // 详情 Drawer
  const [drawerRecord, setDrawerRecord] = useState<HACCPRecord | null>(null);

  // 新建记录 Modal
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<HACCPPlan | null>(null);
  const [resultForm, setResultForm] = useState<CheckItemResult[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [createForm] = Form.useForm();

  const fetchRecords = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (dateRange) {
        params.set('start_date', dateRange[0]);
        params.set('end_date', dateRange[1]);
      }
      if (qualifiedFilter !== null) {
        params.set('is_qualified', String(qualifiedFilter));
      }
      const res = await txFetch(`/api/v1/ops/haccp/records?${params.toString()}`);
      const data = await res.json();
      setRecords(data.items ?? data ?? []);
    } catch {
      setError('加载执行记录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRecords();
  }, [dateRange, qualifiedFilter]);

  const handlePlanSelect = (planId: string) => {
    const plan = plans.find(p => p.id === planId) ?? null;
    setSelectedPlan(plan);
    if (plan) {
      setResultForm(
        plan.check_items.map(item => ({
          key: item.key,
          name: item.name,
          passed: true,
          value: '',
          note: '',
        }))
      );
    }
  };

  const handleResultChange = (
    key: string,
    field: keyof CheckItemResult,
    value: boolean | string
  ) => {
    setResultForm(prev =>
      prev.map(r => r.key === key ? { ...r, [field]: value } : r)
    );
  };

  const handleCreateRecord = async (values: Record<string, unknown>) => {
    if (!selectedPlan) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/ops/haccp/records', {
        method: 'POST',
        body: JSON.stringify({
          plan_id: selectedPlan.id,
          check_date: (values.check_date as dayjs.Dayjs).format('YYYY-MM-DD'),
          operator: values.operator,
          results: resultForm,
        }),
      });
      message.success('检查记录提交成功');
      setCreateModalOpen(false);
      createForm.resetFields();
      setSelectedPlan(null);
      setResultForm([]);
      fetchRecords();
    } catch {
      message.error('提交失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnsType<HACCPRecord> = [
    {
      title: '计划名称',
      dataIndex: 'plan_name',
      width: 180,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '检查日期',
      dataIndex: 'check_date',
      width: 120,
      render: (d: string) => dayjs(d).format('YYYY-MM-DD'),
    },
    {
      title: '操作人',
      dataIndex: 'operator',
      width: 100,
    },
    {
      title: '检查结果',
      dataIndex: 'is_qualified',
      width: 110,
      render: (ok: boolean) =>
        ok
          ? <Tag icon={<CheckCircleOutlined />} color="success">合格</Tag>
          : <Tag icon={<CloseCircleOutlined />} color="error">不合格</Tag>,
    },
    {
      title: '关键失控点数',
      dataIndex: 'ccp_failure_count',
      width: 120,
      render: (count: number) => (
        count > 0
          ? <Text type="danger" strong>{count} 个</Text>
          : <Text type="secondary">—</Text>
      ),
    },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      width: 160,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 80,
      render: (_: unknown, record: HACCPRecord) => (
        <Button type="link" size="small" onClick={() => setDrawerRecord(record)}>
          查看详情
        </Button>
      ),
    },
  ];

  return (
    <>
      {/* 筛选栏 */}
      <div className="flex flex-wrap gap-3 mb-4 items-center">
        <RangePicker
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) {
              setDateRange([
                dates[0].format('YYYY-MM-DD'),
                dates[1].format('YYYY-MM-DD'),
              ]);
            } else {
              setDateRange(null);
            }
          }}
          placeholder={['开始日期', '结束日期']}
        />
        <Select
          placeholder="合格状态"
          allowClear
          style={{ width: 140 }}
          onChange={(val) => setQualifiedFilter(val ?? null)}
          options={[
            { value: true, label: '合格' },
            { value: false, label: '不合格' },
          ]}
        />
        <div className="ml-auto">
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateModalOpen(true)}
          >
            新建记录
          </Button>
        </div>
      </div>

      {error && (
        <Alert type="error" message={error} className="mb-3" showIcon />
      )}

      <Table
        rowKey="id"
        columns={columns}
        dataSource={records}
        loading={loading}
        pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }}
        scroll={{ x: 900 }}
        onRow={(record) => ({
          onClick: () => setDrawerRecord(record),
          style: { cursor: 'pointer' },
        })}
      />

      {/* 详情 Drawer */}
      <Drawer
        title={
          <Space>
            <CalendarOutlined />
            <span>{drawerRecord?.plan_name} · 检查详情</span>
          </Space>
        }
        open={!!drawerRecord}
        onClose={() => setDrawerRecord(null)}
        width={540}
      >
        {drawerRecord && (
          <>
            <Descriptions column={2} size="small" bordered className="mb-4">
              <Descriptions.Item label="检查日期">
                {dayjs(drawerRecord.check_date).format('YYYY-MM-DD')}
              </Descriptions.Item>
              <Descriptions.Item label="操作人">
                {drawerRecord.operator}
              </Descriptions.Item>
              <Descriptions.Item label="检查结果">
                {drawerRecord.is_qualified
                  ? <Tag color="success" icon={<CheckCircleOutlined />}>合格</Tag>
                  : <Tag color="error" icon={<CloseCircleOutlined />}>不合格</Tag>
                }
              </Descriptions.Item>
              <Descriptions.Item label="关键失控点数">
                {drawerRecord.ccp_failure_count > 0
                  ? <Text type="danger" strong>{drawerRecord.ccp_failure_count} 个</Text>
                  : '无'
                }
              </Descriptions.Item>
            </Descriptions>

            <Divider orientation="left" plain>逐项检查结果</Divider>

            <div className="space-y-2">
              {(drawerRecord.results ?? []).map((item) => (
                <Card
                  key={item.key}
                  size="small"
                  className={item.passed ? '' : 'border-red-300'}
                  styles={{ body: { padding: '8px 12px' } }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        {item.passed
                          ? <CheckCircleOutlined style={{ color: '#0F6E56' }} />
                          : <CloseCircleOutlined style={{ color: '#A32D2D' }} />
                        }
                        <Text strong className="text-sm">{item.name}</Text>
                      </div>
                      {item.value && (
                        <div className="text-xs text-gray-500">
                          记录值：<Text code>{item.value}</Text>
                        </div>
                      )}
                      {item.note && (
                        <div className="text-xs text-gray-500 mt-1">
                          备注：{item.note}
                        </div>
                      )}
                    </div>
                    <Tag color={item.passed ? 'success' : 'error'} className="shrink-0">
                      {item.passed ? '通过' : '未通过'}
                    </Tag>
                  </div>
                </Card>
              ))}
            </div>
          </>
        )}
      </Drawer>

      {/* 新建记录 Modal */}
      <Modal
        title="新建检查记录"
        open={createModalOpen}
        onCancel={() => {
          setCreateModalOpen(false);
          createForm.resetFields();
          setSelectedPlan(null);
          setResultForm([]);
        }}
        footer={null}
        width={680}
        destroyOnClose
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreateRecord}
          initialValues={{ check_date: dayjs() }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="选择检查计划"
                name="plan_id"
                rules={[{ required: true, message: '请选择检查计划' }]}
              >
                <Select
                  placeholder="请选择"
                  onChange={handlePlanSelect}
                  options={plans
                    .filter(p => p.is_enabled)
                    .map(p => ({ value: p.id, label: p.name }))
                  }
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="检查日期"
                name="check_date"
                rules={[{ required: true, message: '请选择日期' }]}
              >
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="操作人"
                name="operator"
                rules={[{ required: true, message: '请填写操作人' }]}
              >
                <Input placeholder="请填写操作人姓名" />
              </Form.Item>
            </Col>
          </Row>

          {selectedPlan && resultForm.length > 0 && (
            <>
              <Divider orientation="left" plain>逐项填写结果</Divider>
              <div className="space-y-3 mb-4">
                {resultForm.map((item) => (
                  <Card key={item.key} size="small">
                    <div className="font-medium mb-2">{item.name}</div>
                    <Row gutter={12}>
                      <Col span={6}>
                        <div className="text-xs text-gray-500 mb-1">是否通过</div>
                        <Select
                          value={item.passed}
                          onChange={(val) => handleResultChange(item.key, 'passed', val)}
                          style={{ width: '100%' }}
                          options={[
                            { value: true, label: '通过' },
                            { value: false, label: '未通过' },
                          ]}
                        />
                      </Col>
                      <Col span={8}>
                        <div className="text-xs text-gray-500 mb-1">记录值（选填）</div>
                        <Input
                          value={item.value}
                          onChange={(e) => handleResultChange(item.key, 'value', e.target.value)}
                          placeholder="如：4.2℃"
                        />
                      </Col>
                      <Col span={10}>
                        <div className="text-xs text-gray-500 mb-1">备注（选填）</div>
                        <Input
                          value={item.note}
                          onChange={(e) => handleResultChange(item.key, 'note', e.target.value)}
                          placeholder="异常说明等"
                        />
                      </Col>
                    </Row>
                  </Card>
                ))}
              </div>
            </>
          )}

          <div className="flex justify-end gap-2">
            <Button onClick={() => setCreateModalOpen(false)}>取消</Button>
            <Button
              type="primary"
              htmlType="submit"
              loading={submitting}
              disabled={!selectedPlan}
            >
              提交记录
            </Button>
          </div>
        </Form>
      </Modal>
    </>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function HACCPPage() {
  const [stats, setStats] = useState<HACCPStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);

  const [plans, setPlans] = useState<HACCPPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [plansError, setPlansError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState('plans');

  // ── 统计数据 ──
  const fetchStats = async () => {
    setStatsLoading(true);
    setStatsError(null);
    try {
      const res = await txFetch('/api/v1/ops/haccp/stats');
      const data = await res.json();
      setStats(data);
    } catch {
      setStatsError('加载统计数据失败');
    } finally {
      setStatsLoading(false);
    }
  };

  // ── 检查计划 ──
  const fetchPlans = async () => {
    setPlansLoading(true);
    setPlansError(null);
    try {
      const res = await txFetch('/api/v1/ops/haccp/plans');
      const data = await res.json();
      setPlans(data.items ?? data ?? []);
    } catch {
      setPlansError('加载检查计划失败，请稍后重试');
    } finally {
      setPlansLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    fetchPlans();
  }, []);

  return (
    <div className="p-4">
      {/* 页面标题 */}
      <div className="mb-4">
        <h2 className="text-xl font-bold text-gray-800 m-0">HACCP 食安检查</h2>
        <p className="text-sm text-gray-500 mt-1 mb-0">
          危害分析和关键控制点管理 · 确保食品安全合规
        </p>
      </div>

      {/* 统计卡片 */}
      {statsError && (
        <Alert type="error" message={statsError} className="mb-4" showIcon closable />
      )}
      <StatsCards stats={stats} loading={statsLoading} />

      {/* Tab 区域 */}
      <Card>
        {plansError && (
          <Alert type="error" message={plansError} className="mb-3" showIcon closable />
        )}
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'plans',
              label: (
                <Space>
                  <SafetyCertificateOutlined />
                  检查计划
                </Space>
              ),
              children: (
                <PlansTab
                  plans={plans}
                  loading={plansLoading}
                  onRefresh={fetchPlans}
                />
              ),
            },
            {
              key: 'records',
              label: (
                <Space>
                  <CalendarOutlined />
                  执行记录
                </Space>
              ),
              children: <RecordsTab plans={plans} />,
            },
          ]}
        />
      </Card>
    </div>
  );
}
