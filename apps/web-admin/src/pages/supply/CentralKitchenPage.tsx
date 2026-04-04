/**
 * 中央厨房管理页面 — supply/CentralKitchenPage
 *
 * Tab1 今日总览   — 5指标卡 + 食材需求汇总 + 一键生成排产
 * Tab2 门店需求单 — 日期/状态筛选 + 审批 + 明细抽屉
 * Tab3 排产计划   — 日期筛选 + 状态推进 + 新建 ModalForm
 * Tab4 配送管理   — 状态流转 preparing→in_transit→delivered
 *
 * 后端：/api/v1/supply/central-kitchen/*
 */
import { useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Popover,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  CarOutlined,
  PlusOutlined,
  ReloadOutlined,
  ShopOutlined,
  UnorderedListOutlined,
  CalendarOutlined,
} from '@ant-design/icons';
import type { ProColumns } from '@ant-design/pro-components';
import { ProTable } from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

const TENANT_ID = localStorage.getItem('tx_tenant_id') || 'demo-tenant';

// ─── API 工具 ──────────────────────────────────────────────────────────────

async function txApi<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<{ ok: boolean; data: T }> {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
      ...options.headers,
    },
  });
  const json = await res.json();
  if (!res.ok || !json.ok) {
    throw new Error(json?.error?.message || json?.detail || '请求失败');
  }
  return json;
}

// ─── 类型定义 ──────────────────────────────────────────────────────────────

interface IngredientDemand {
  name: string;
  total_quantity: number;
  unit?: string;
}

interface OverviewData {
  pending_requisitions: number;
  approved_requisitions: number;
  stores_requesting: number;
  active_production_plans: number;
  todays_deliveries: number;
  ingredient_demand_summary: IngredientDemand[];
  _is_mock?: boolean;
}

interface ReqItem {
  ingredient_id: string;
  ingredient_name: string;
  quantity: number;
  unit: string;
}

interface Requisition {
  id: string;
  store_id: string;
  store_name: string;
  delivery_date: string;
  status: 'pending' | 'approved' | 'rejected';
  items: ReqItem[];
  notes?: string;
  created_at: string;
}

interface PlanItem {
  ingredient_id: string;
  ingredient_name: string;
  planned_quantity: number;
  unit: string;
  processing_type: string;
  actual_quantity?: number | null;
}

interface ProductionPlan {
  id: string;
  plan_date: string;
  shift: string;
  status: 'draft' | 'confirmed' | 'completed';
  items: PlanItem[];
  notes?: string;
  created_at: string;
}

interface DeliveryItem {
  ingredient_id: string;
  ingredient_name: string;
  quantity: number;
  unit: string;
}

interface DeliveryOrder {
  id: string;
  store_id: string;
  store_name: string;
  delivery_date: string;
  status: 'preparing' | 'in_transit' | 'delivered';
  driver_name?: string;
  vehicle_no?: string;
  items: DeliveryItem[];
  departed_at?: string;
  arrived_at?: string;
  created_at: string;
}

interface AggregatedItem {
  ingredient_id: string;
  ingredient_name: string;
  unit: string;
  total_quantity: number;
  store_breakdown: { store_name: string; quantity: number }[];
}

// ─── 常量配置 ──────────────────────────────────────────────────────────────

const REQ_STATUS_MAP: Record<string, { label: string; color: string; badge: 'default' | 'processing' | 'success' | 'error' | 'warning' }> = {
  pending:  { label: '待审核', color: 'default',   badge: 'default'    },
  approved: { label: '已审核', color: 'success',   badge: 'success'    },
  rejected: { label: '已拒绝', color: 'error',     badge: 'error'      },
};

const PLAN_STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft:     { label: '草稿',   color: 'default'    },
  confirmed: { label: '已确认', color: 'processing' },
  completed: { label: '已完成', color: 'success'    },
};

const SHIFT_MAP: Record<string, { label: string; color: string }> = {
  morning:   { label: '早班', color: 'gold'  },
  afternoon: { label: '午班', color: 'blue'  },
  evening:   { label: '晚班', color: 'purple' },
};

const DELIVERY_STATUS_MAP: Record<string, { label: string; color: string }> = {
  preparing:  { label: '备货中',  color: 'default'    },
  in_transit: { label: '配送中',  color: 'processing' },
  delivered:  { label: '已到货',  color: 'success'    },
};

const PROCESSING_TYPE_MAP: Record<string, string> = {
  raw:    '生料',
  semi:   '半成品',
  cooked: '熟食',
};

const BASE_URL = '/api/v1/supply/central-kitchen';

// ═══════════════════════════════════════════════════════════════════════════════
// Tab1: 今日总览
// ═══════════════════════════════════════════════════════════════════════════════

function OverviewTab() {
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(false);
  const [genLoading, setGenLoading] = useState(false);
  const [genModal, setGenModal] = useState(false);
  const [aggregated, setAggregated] = useState<AggregatedItem[]>([]);
  const [form] = Form.useForm();

  const todayStr = dayjs().format('YYYY-MM-DD');

  const fetchOverview = async () => {
    setLoading(true);
    try {
      const res = await txApi<OverviewData>(`${BASE_URL}/overview`);
      setOverview(res.data);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取总览失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchAggregated = async (date: string) => {
    try {
      const res = await txApi<{ items: AggregatedItem[]; total_ingredients: number }>(
        `${BASE_URL}/aggregate-demand?delivery_date=${date}`,
      );
      setAggregated(res.data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '汇总需求失败');
    }
  };

  const handleGenPlan = async () => {
    try {
      const values = await form.validateFields();
      setGenLoading(true);
      // 先汇总需求
      const aggRes = await txApi<{ items: AggregatedItem[] }>(
        `${BASE_URL}/aggregate-demand?delivery_date=${values.plan_date}`,
      );
      // 自动构建排产计划 items
      const planItems = aggRes.data.items.map((item) => ({
        ingredient_id: item.ingredient_id,
        ingredient_name: item.ingredient_name,
        planned_quantity: item.total_quantity,
        unit: item.unit,
        processing_type: 'raw',
      }));
      await txApi(`${BASE_URL}/production-plans`, {
        method: 'POST',
        body: JSON.stringify({
          plan_date: values.plan_date,
          shift: values.shift,
          items: planItems,
          notes: '由需求汇总自动生成',
        }),
      });
      message.success(`排产计划已生成（${aggRes.data.items.length} 种食材）`);
      setGenModal(false);
      form.resetFields();
      fetchOverview();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '生成排产计划失败');
    } finally {
      setGenLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
    fetchAggregated(todayStr);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const demandColumns: ProColumns<IngredientDemand>[] = [
    { title: '食材名称', dataIndex: 'name', width: 160 },
    {
      title: '合计需求',
      dataIndex: 'total_quantity',
      width: 120,
      render: (v) => <Text strong>{Number(v).toFixed(1)}</Text>,
    },
    { title: '单位', dataIndex: 'unit', width: 80, render: (v) => v || '—' },
    {
      title: '门店明细',
      dataIndex: 'store_breakdown',
      render: (_v, record: IngredientDemand) => {
        // 在 overview 中 ingredient_demand_summary 没有 breakdown，aggregated 才有
        const agg = aggregated.find((a) => a.ingredient_name === record.name);
        if (!agg?.store_breakdown?.length) return <Text type="secondary">—</Text>;
        const content = (
          <div style={{ maxWidth: 260 }}>
            {agg.store_breakdown.map((b, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, padding: '2px 0' }}>
                <Text style={{ fontSize: 12 }}>{b.store_name}</Text>
                <Text style={{ fontSize: 12 }} type="secondary">{b.quantity} {agg.unit}</Text>
              </div>
            ))}
          </div>
        );
        return (
          <Popover title="各门店需求" content={content} placement="left">
            <Button type="link" size="small" style={{ padding: 0 }}>
              {agg.store_breakdown.length} 家门店
            </Button>
          </Popover>
        );
      },
    },
  ];

  return (
    <div>
      {/* 5 指标卡 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {[
          { title: '待审需求单', value: overview?.pending_requisitions ?? 0, color: '#BA7517', icon: <UnorderedListOutlined /> },
          { title: '已审核需求单', value: overview?.approved_requisitions ?? 0, color: '#0F6E56', icon: <CheckCircleOutlined /> },
          { title: '参与门店数', value: overview?.stores_requesting ?? 0, color: '#185FA5', icon: <ShopOutlined /> },
          { title: '今日排产计划', value: overview?.active_production_plans ?? 0, color: '#FF6B35', icon: <CalendarOutlined /> },
          { title: '今日配送单', value: overview?.todays_deliveries ?? 0, color: '#722ED1', icon: <CarOutlined /> },
        ].map((card) => (
          <Col span={4} key={card.title} style={{ minWidth: 160 }}>
            <Card size="small" loading={loading} style={{ borderTop: `3px solid ${card.color}` }}>
              <Statistic
                title={<span style={{ fontSize: 12, color: '#5F5E5A' }}>{card.title}</span>}
                value={card.value}
                valueStyle={{ color: card.color, fontSize: 28, fontWeight: 700 }}
                prefix={card.icon}
              />
            </Card>
          </Col>
        ))}
        <Col style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
          <Button icon={<ReloadOutlined />} onClick={fetchOverview} loading={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            onClick={() => setGenModal(true)}
          >
            一键生成排产计划
          </Button>
        </Col>
      </Row>

      {/* 食材需求汇总 */}
      <Card
        title={<span>今日食材需求汇总 <Text type="secondary" style={{ fontSize: 12 }}>（基于所有待审/已审需求单）</Text></span>}
        extra={overview?._is_mock && <Tag color="orange">Mock 数据</Tag>}
        size="small"
      >
        <ProTable<IngredientDemand>
          rowKey="name"
          dataSource={overview?.ingredient_demand_summary ?? []}
          columns={demandColumns}
          loading={loading}
          search={false}
          options={{ reload: false, density: false, setting: false }}
          pagination={false}
          size="small"
          toolBarRender={false}
        />
      </Card>

      {/* 一键生成排产计划 Modal */}
      <Modal
        title="一键生成排产计划"
        open={genModal}
        onOk={handleGenPlan}
        onCancel={() => { setGenModal(false); form.resetFields(); }}
        confirmLoading={genLoading}
        okText="生成"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="plan_date"
            label="计划日期"
            initialValue={todayStr}
            rules={[{ required: true, message: '请选择计划日期' }]}
          >
            <Input type="date" />
          </Form.Item>
          <Form.Item
            name="shift"
            label="班次"
            initialValue="morning"
            rules={[{ required: true, message: '请选择班次' }]}
          >
            <Select>
              <Select.Option value="morning">早班</Select.Option>
              <Select.Option value="afternoon">午班</Select.Option>
              <Select.Option value="evening">晚班</Select.Option>
            </Select>
          </Form.Item>
        </Form>
        <Text type="secondary" style={{ fontSize: 12 }}>
          将自动汇总指定日期所有门店需求单，按食材聚合生成排产计划草稿。
        </Text>
      </Modal>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab2: 门店需求单
// ═══════════════════════════════════════════════════════════════════════════════

function RequisitionsTab() {
  const [data, setData] = useState<Requisition[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterDate, setFilterDate] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailReq, setDetailReq] = useState<Requisition | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      let url = `${BASE_URL}/requisitions?`;
      if (filterDate) url += `delivery_date=${filterDate}&`;
      if (filterStatus) url += `status=${filterStatus}&`;
      const res = await txApi<{ items: Requisition[] }>(url);
      setData(res.data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取需求单失败');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (reqId: string) => {
    try {
      await txApi(`${BASE_URL}/requisitions/${reqId}/approve`, { method: 'POST' });
      message.success('审批成功');
      fetchData();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '审批失败');
    }
  };

  useEffect(() => { fetchData(); }, [filterDate, filterStatus]);

  const columns: ProColumns<Requisition>[] = [
    {
      title: '门店名称',
      dataIndex: 'store_name',
      width: 200,
      render: (v) => <Text strong>{v as string}</Text>,
    },
    {
      title: '配送日期',
      dataIndex: 'delivery_date',
      width: 120,
    },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
    },
    {
      title: '品项数',
      dataIndex: 'items',
      width: 80,
      render: (items) => <Badge count={(items as ReqItem[]).length} color="#FF6B35" />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s) => {
        const cfg = REQ_STATUS_MAP[s as string] ?? { label: s, badge: 'default' };
        return <Badge status={cfg.badge} text={cfg.label} />;
      },
    },
    {
      title: '备注',
      dataIndex: 'notes',
      ellipsis: true,
      render: (v) => v || <Text type="secondary">—</Text>,
    },
    {
      title: '操作',
      width: 160,
      render: (_, req: Requisition) => (
        <Space>
          <Button
            size="small"
            type="link"
            onClick={() => { setDetailReq(req); setDetailOpen(true); }}
          >
            查看明细
          </Button>
          {req.status === 'pending' && (
            <Popconfirm
              title="确认审批通过该需求单？"
              onConfirm={() => handleApprove(req.id)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" type="primary" ghost>
                审批
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      {/* 筛选栏 */}
      <Space style={{ marginBottom: 16 }}>
        <DatePicker
          placeholder="配送日期"
          format="YYYY-MM-DD"
          onChange={(v) => setFilterDate(v ? v.format('YYYY-MM-DD') : '')}
          style={{ width: 160 }}
        />
        <Select
          placeholder="状态筛选"
          allowClear
          style={{ width: 120 }}
          onChange={(v) => setFilterStatus(v ?? '')}
        >
          <Select.Option value="pending">待审核</Select.Option>
          <Select.Option value="approved">已审核</Select.Option>
          <Select.Option value="rejected">已拒绝</Select.Option>
        </Select>
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
          刷新
        </Button>
      </Space>

      <ProTable<Requisition>
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        search={false}
        options={{ reload: false }}
        pagination={{ pageSize: 20 }}
        size="small"
        toolBarRender={false}
      />

      {/* 需求单明细抽屉 */}
      <Drawer
        title={`需求单明细 — ${detailReq?.store_name ?? ''}`}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        width={520}
      >
        {detailReq && (
          <>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="门店">{detailReq.store_name}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Badge
                  status={REQ_STATUS_MAP[detailReq.status]?.badge ?? 'default'}
                  text={REQ_STATUS_MAP[detailReq.status]?.label ?? detailReq.status}
                />
              </Descriptions.Item>
              <Descriptions.Item label="配送日期">{detailReq.delivery_date}</Descriptions.Item>
              <Descriptions.Item label="提交时间">
                {dayjs(detailReq.created_at).format('YYYY-MM-DD HH:mm')}
              </Descriptions.Item>
              {detailReq.notes && (
                <Descriptions.Item label="备注" span={2}>{detailReq.notes}</Descriptions.Item>
              )}
            </Descriptions>

            <Table
              rowKey="ingredient_id"
              dataSource={detailReq.items}
              size="small"
              pagination={false}
              columns={[
                { title: '食材名称', dataIndex: 'ingredient_name' },
                { title: '需求量', dataIndex: 'quantity', width: 90, render: (v: number) => v.toFixed(1) },
                { title: '单位', dataIndex: 'unit', width: 60 },
              ]}
            />
          </>
        )}
      </Drawer>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab3: 排产计划
// ═══════════════════════════════════════════════════════════════════════════════

function ProductionPlansTab() {
  const [data, setData] = useState<ProductionPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterDate, setFilterDate] = useState<string>('');
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailPlan, setDetailPlan] = useState<ProductionPlan | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();
  const [planItems, setPlanItems] = useState<PlanItem[]>([]);

  const fetchData = async () => {
    setLoading(true);
    try {
      let url = `${BASE_URL}/production-plans?`;
      if (filterDate) url += `plan_date=${filterDate}&`;
      const res = await txApi<{ items: ProductionPlan[] }>(url);
      setData(res.data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取排产计划失败');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (planId: string) => {
    try {
      await txApi(`${BASE_URL}/production-plans/${planId}/confirm`, { method: 'POST' });
      message.success('计划已确认，开始排产');
      fetchData();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '确认失败');
    }
  };

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      if (!planItems.length) {
        message.warning('请至少添加一种食材');
        return;
      }
      await txApi(`${BASE_URL}/production-plans`, {
        method: 'POST',
        body: JSON.stringify({
          plan_date: values.plan_date,
          shift: values.shift,
          items: planItems,
          notes: values.notes,
        }),
      });
      message.success('排产计划已创建');
      setCreateOpen(false);
      form.resetFields();
      setPlanItems([]);
      fetchData();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '创建失败');
    }
  };

  const addPlanItem = () => {
    setPlanItems((prev) => [
      ...prev,
      {
        ingredient_id: `ing-${Date.now()}`,
        ingredient_name: '',
        planned_quantity: 0,
        unit: 'kg',
        processing_type: 'raw',
        actual_quantity: null,
      },
    ]);
  };

  const updatePlanItem = (idx: number, field: keyof PlanItem, value: unknown) => {
    setPlanItems((prev) => {
      const next = [...prev];
      (next[idx] as Record<string, unknown>)[field] = value;
      return next;
    });
  };

  useEffect(() => { fetchData(); }, [filterDate]);

  const columns: ProColumns<ProductionPlan>[] = [
    {
      title: '计划日期',
      dataIndex: 'plan_date',
      width: 120,
    },
    {
      title: '班次',
      dataIndex: 'shift',
      width: 90,
      render: (s) => {
        const cfg = SHIFT_MAP[s as string] ?? { label: s, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '品项数',
      dataIndex: 'items',
      width: 80,
      render: (items) => (items as PlanItem[]).length,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s) => {
        const cfg = PLAN_STATUS_MAP[s as string] ?? { label: s, color: 'default' };
        return <Badge status={cfg.color as Parameters<typeof Badge>[0]['status']} text={cfg.label} />;
      },
    },
    {
      title: '备注',
      dataIndex: 'notes',
      ellipsis: true,
      render: (v) => v || <Text type="secondary">—</Text>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 160,
      render: (_, plan: ProductionPlan) => (
        <Space>
          <Button
            size="small"
            type="link"
            onClick={() => { setDetailPlan(plan); setDetailOpen(true); }}
          >
            查看
          </Button>
          {plan.status === 'draft' && (
            <Popconfirm
              title="确认该排产计划，开始生产？"
              onConfirm={() => handleConfirm(plan.id)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" type="primary" ghost>
                确认排产
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <DatePicker
          placeholder="计划日期"
          format="YYYY-MM-DD"
          onChange={(v) => setFilterDate(v ? v.format('YYYY-MM-DD') : '')}
          style={{ width: 160 }}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          onClick={() => setCreateOpen(true)}
        >
          新建排产计划
        </Button>
      </Space>

      <ProTable<ProductionPlan>
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        search={false}
        options={{ reload: false }}
        pagination={{ pageSize: 20 }}
        size="small"
        toolBarRender={false}
      />

      {/* 计划明细抽屉 */}
      <Drawer
        title={`排产明细 — ${detailPlan?.plan_date ?? ''} ${SHIFT_MAP[detailPlan?.shift ?? '']?.label ?? ''}`}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        width={560}
      >
        {detailPlan && (
          <>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="计划日期">{detailPlan.plan_date}</Descriptions.Item>
              <Descriptions.Item label="班次">
                <Tag color={SHIFT_MAP[detailPlan.shift]?.color ?? 'default'}>
                  {SHIFT_MAP[detailPlan.shift]?.label ?? detailPlan.shift}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Badge
                  status={(PLAN_STATUS_MAP[detailPlan.status]?.color ?? 'default') as Parameters<typeof Badge>[0]['status']}
                  text={PLAN_STATUS_MAP[detailPlan.status]?.label ?? detailPlan.status}
                />
              </Descriptions.Item>
              {detailPlan.notes && (
                <Descriptions.Item label="备注" span={2}>{detailPlan.notes}</Descriptions.Item>
              )}
            </Descriptions>

            <Table
              rowKey="ingredient_id"
              dataSource={detailPlan.items}
              size="small"
              pagination={false}
              columns={[
                { title: '食材名称', dataIndex: 'ingredient_name' },
                {
                  title: '计划量', dataIndex: 'planned_quantity', width: 90,
                  render: (v: number) => v.toFixed(1),
                },
                { title: '单位', dataIndex: 'unit', width: 60 },
                {
                  title: '加工类型', dataIndex: 'processing_type', width: 90,
                  render: (v: string) => PROCESSING_TYPE_MAP[v] ?? v,
                },
                {
                  title: '实际量', dataIndex: 'actual_quantity', width: 80,
                  render: (v) => v != null ? Number(v).toFixed(1) : <Text type="secondary">—</Text>,
                },
              ]}
            />
          </>
        )}
      </Drawer>

      {/* 新建排产计划 Modal */}
      <Modal
        title="新建排产计划"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateOpen(false); form.resetFields(); setPlanItems([]); }}
        width={720}
        okText="创建"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="plan_date" label="计划日期" rules={[{ required: true }]}>
                <Input type="date" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="shift" label="班次" initialValue="morning" rules={[{ required: true }]}>
                <Select>
                  <Select.Option value="morning">早班</Select.Option>
                  <Select.Option value="afternoon">午班</Select.Option>
                  <Select.Option value="evening">晚班</Select.Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>

        <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text strong>食材明细</Text>
          <Button size="small" icon={<PlusOutlined />} onClick={addPlanItem}>
            添加食材
          </Button>
        </div>
        <Table
          rowKey="ingredient_id"
          dataSource={planItems}
          size="small"
          pagination={false}
          columns={[
            {
              title: '食材名称', dataIndex: 'ingredient_name', render: (_v, _r, idx) => (
                <Input
                  size="small"
                  value={planItems[idx].ingredient_name}
                  onChange={(e) => updatePlanItem(idx, 'ingredient_name', e.target.value)}
                  placeholder="食材名称"
                />
              ),
            },
            {
              title: '计划量', dataIndex: 'planned_quantity', width: 100, render: (_v, _r, idx) => (
                <Input
                  size="small"
                  type="number"
                  min={0}
                  value={planItems[idx].planned_quantity}
                  onChange={(e) => updatePlanItem(idx, 'planned_quantity', parseFloat(e.target.value) || 0)}
                />
              ),
            },
            {
              title: '单位', dataIndex: 'unit', width: 80, render: (_v, _r, idx) => (
                <Select
                  size="small"
                  value={planItems[idx].unit}
                  onChange={(v) => updatePlanItem(idx, 'unit', v)}
                  style={{ width: 72 }}
                >
                  {['kg', 'g', '个', '包', '件', '份'].map((u) => (
                    <Select.Option key={u} value={u}>{u}</Select.Option>
                  ))}
                </Select>
              ),
            },
            {
              title: '加工类型', dataIndex: 'processing_type', width: 100, render: (_v, _r, idx) => (
                <Select
                  size="small"
                  value={planItems[idx].processing_type}
                  onChange={(v) => updatePlanItem(idx, 'processing_type', v)}
                  style={{ width: 92 }}
                >
                  <Select.Option value="raw">生料</Select.Option>
                  <Select.Option value="semi">半成品</Select.Option>
                  <Select.Option value="cooked">熟食</Select.Option>
                </Select>
              ),
            },
            {
              title: '',
              width: 50,
              render: (_v, _r, idx) => (
                <Button
                  size="small"
                  danger
                  type="text"
                  onClick={() => setPlanItems((prev) => prev.filter((_, i) => i !== idx))}
                >
                  删除
                </Button>
              ),
            },
          ]}
        />
      </Modal>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab4: 配送管理
// ═══════════════════════════════════════════════════════════════════════════════

function DeliveryTab() {
  const [data, setData] = useState<DeliveryOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterDate, setFilterDate] = useState<string>('');
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailOrder, setDetailOrder] = useState<DeliveryOrder | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      let url = `${BASE_URL}/delivery-orders?`;
      if (filterDate) url += `delivery_date=${filterDate}&`;
      const res = await txApi<{ items: DeliveryOrder[] }>(url);
      setData(res.data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取配送单失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDispatch = async (deliveryId: string) => {
    try {
      await txApi(`${BASE_URL}/delivery-orders/${deliveryId}/dispatch`, { method: 'POST' });
      message.success('出车成功，配送中');
      fetchData();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '操作失败');
    }
  };

  const handleConfirmReceipt = async (deliveryId: string) => {
    try {
      await txApi(`${BASE_URL}/delivery-orders/${deliveryId}/confirm-receipt`, { method: 'POST' });
      message.success('已确认收货');
      fetchData();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '确认收货失败');
    }
  };

  useEffect(() => { fetchData(); }, [filterDate]);

  // 状态流程步骤条
  const StatusSteps = () => (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20,
      padding: '12px 16px', background: '#F8F7F5', borderRadius: 8,
    }}>
      {[
        { key: 'preparing',  label: '备货中', icon: '📦' },
        { label: '→' },
        { key: 'in_transit', label: '配送中', icon: '🚛' },
        { label: '→' },
        { key: 'delivered',  label: '已到货', icon: '✅' },
      ].map((step, i) => (
        <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {step.key ? (
            <>
              <span>{step.icon}</span>
              <Tag color={DELIVERY_STATUS_MAP[step.key]?.color ?? 'default'} style={{ margin: 0 }}>
                {step.label}
              </Tag>
            </>
          ) : (
            <Text type="secondary">{step.label}</Text>
          )}
        </span>
      ))}
      <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
        — 点击"出车"或"确认收货"推进状态
      </Text>
    </div>
  );

  const columns: ProColumns<DeliveryOrder>[] = [
    {
      title: '配送单号',
      dataIndex: 'id',
      width: 130,
      render: (v) => <Text code style={{ fontSize: 12 }}>{(v as string).slice(0, 8).toUpperCase()}</Text>,
    },
    {
      title: '目标门店',
      dataIndex: 'store_name',
      width: 180,
      render: (v) => <Text strong>{v as string}</Text>,
    },
    {
      title: '配送日期',
      dataIndex: 'delivery_date',
      width: 110,
    },
    {
      title: '品项数',
      dataIndex: 'items',
      width: 80,
      render: (items) => (items as DeliveryItem[]).length,
    },
    {
      title: '司机',
      dataIndex: 'driver_name',
      width: 90,
      render: (v) => v || <Text type="secondary">—</Text>,
    },
    {
      title: '车牌',
      dataIndex: 'vehicle_no',
      width: 110,
      render: (v) => v ? <Tag>{v as string}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s) => {
        const cfg = DELIVERY_STATUS_MAP[s as string] ?? { label: s, color: 'default' };
        return <Badge status={cfg.color as Parameters<typeof Badge>[0]['status']} text={cfg.label} />;
      },
    },
    {
      title: '操作',
      width: 180,
      render: (_, order: DeliveryOrder) => (
        <Space>
          <Button
            size="small"
            type="link"
            onClick={() => { setDetailOrder(order); setDetailOpen(true); }}
          >
            明细
          </Button>
          {order.status === 'preparing' && (
            <Popconfirm
              title="确认出车？货物已装车，即将发出。"
              onConfirm={() => handleDispatch(order.id)}
              okText="出车"
              cancelText="取消"
            >
              <Button size="small" type="primary" icon={<CarOutlined />}>
                出车
              </Button>
            </Popconfirm>
          )}
          {order.status === 'in_transit' && (
            <Popconfirm
              title="确认门店已收货？"
              onConfirm={() => handleConfirmReceipt(order.id)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" type="primary" style={{ background: '#0F6E56', borderColor: '#0F6E56' }} icon={<CheckCircleOutlined />}>
                确认收货
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <StatusSteps />

      <Space style={{ marginBottom: 16 }}>
        <DatePicker
          placeholder="配送日期"
          format="YYYY-MM-DD"
          onChange={(v) => setFilterDate(v ? v.format('YYYY-MM-DD') : '')}
          style={{ width: 160 }}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
          刷新
        </Button>
      </Space>

      <ProTable<DeliveryOrder>
        rowKey="id"
        dataSource={data}
        columns={columns}
        loading={loading}
        search={false}
        options={{ reload: false }}
        pagination={{ pageSize: 20 }}
        size="small"
        toolBarRender={false}
      />

      {/* 配送明细抽屉 */}
      <Drawer
        title={`配送明细 — ${detailOrder?.store_name ?? ''}`}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        width={500}
      >
        {detailOrder && (
          <>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="目标门店">{detailOrder.store_name}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Badge
                  status={(DELIVERY_STATUS_MAP[detailOrder.status]?.color ?? 'default') as Parameters<typeof Badge>[0]['status']}
                  text={DELIVERY_STATUS_MAP[detailOrder.status]?.label ?? detailOrder.status}
                />
              </Descriptions.Item>
              <Descriptions.Item label="配送日期">{detailOrder.delivery_date}</Descriptions.Item>
              {detailOrder.driver_name && (
                <Descriptions.Item label="司机">{detailOrder.driver_name}</Descriptions.Item>
              )}
              {detailOrder.vehicle_no && (
                <Descriptions.Item label="车牌">{detailOrder.vehicle_no}</Descriptions.Item>
              )}
              {detailOrder.departed_at && (
                <Descriptions.Item label="出发时间">
                  {dayjs(detailOrder.departed_at).format('HH:mm')}
                </Descriptions.Item>
              )}
              {detailOrder.arrived_at && (
                <Descriptions.Item label="到达时间">
                  {dayjs(detailOrder.arrived_at).format('HH:mm')}
                </Descriptions.Item>
              )}
            </Descriptions>

            <Table
              rowKey="ingredient_id"
              dataSource={detailOrder.items}
              size="small"
              pagination={false}
              columns={[
                { title: '食材名称', dataIndex: 'ingredient_name' },
                {
                  title: '数量', dataIndex: 'quantity', width: 90,
                  render: (v: number) => v.toFixed(1),
                },
                { title: '单位', dataIndex: 'unit', width: 60 },
              ]}
            />
          </>
        )}
      </Drawer>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════════════════════════

export function CentralKitchenPage() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#FF6B35',
          colorSuccess: '#0F6E56',
          colorWarning: '#BA7517',
          colorError: '#A32D2D',
          colorInfo: '#185FA5',
          borderRadius: 6,
        },
      }}
    >
      <div style={{ padding: 24, minWidth: 1280 }}>
        <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 12 }}>
          <Title level={4} style={{ margin: 0 }}>🏭 中央厨房管理</Title>
          <Tag color="orange" style={{ fontSize: 12 }}>域D · 供应链</Tag>
        </div>

        <Tabs
          defaultActiveKey="overview"
          type="card"
          items={[
            {
              key: 'overview',
              label: '📊 今日总览',
              children: <OverviewTab />,
            },
            {
              key: 'requisitions',
              label: '📋 门店需求单',
              children: <RequisitionsTab />,
            },
            {
              key: 'plans',
              label: '📅 排产计划',
              children: <ProductionPlansTab />,
            },
            {
              key: 'delivery',
              label: '🚛 配送管理',
              children: <DeliveryTab />,
            },
          ]}
        />
      </div>
    </ConfigProvider>
  );
}
