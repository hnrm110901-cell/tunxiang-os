/**
 * 中央厨房管理页面
 *
 * Tab1 配方管理  — 配方列表 + 原料明细抽屉 + 新建ModalForm
 * Tab2 生产计划  — 计划列表 + 状态推进 + 原料清单预览
 * Tab3 调拨单    — 调拨单列表 + 确认收货 + 打印
 */
import { useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface RecipeIngredient {
  id: string;
  ingredient_name: string;
  ingredient_id?: string;
  qty: number;
  unit: string;
  loss_rate: number;
}

interface Recipe {
  id: string;
  dish_id: string;
  version: number;
  is_active: boolean;
  yield_qty: number;
  yield_unit: string;
  notes?: string;
  ingredient_count?: number;
  created_at: string;
  ingredients?: RecipeIngredient[];
}

interface PlanItem {
  id: string;
  dish_id: string;
  recipe_id?: string;
  planned_qty: number;
  actual_qty?: number;
  unit: string;
  status: string;
}

interface ProductionPlan {
  id: string;
  plan_date: string;
  status: string;
  store_id?: string;
  created_by?: string;
  notes?: string;
  item_count?: number;
  created_at: string;
  items?: PlanItem[];
}

interface DispatchItem {
  id: string;
  dish_id: string;
  planned_qty: number;
  actual_qty?: number;
  unit: string;
  variance_note?: string;
}

interface DispatchOrder {
  id: string;
  dispatch_no: string;
  plan_id?: string;
  from_store_id?: string;
  to_store_id: string;
  dispatch_date: string;
  status: string;
  driver_name?: string;
  vehicle_no?: string;
  receiver_name?: string;
  received_at?: string;
  created_at: string;
  items?: DispatchItem[];
}

interface MaterialItem {
  ingredient_name: string;
  ingredient_id?: string;
  unit: string;
  total_qty: number;
}

// ─── 常量：状态标签 ──────────────────────────────────────────────────────────

const PLAN_STATUS: Record<string, { label: string; color: string }> = {
  draft:       { label: '草稿',   color: 'default' },
  confirmed:   { label: '已确认', color: 'processing' },
  in_progress: { label: '生产中', color: 'warning' },
  done:        { label: '已完成', color: 'success' },
};

const DISPATCH_STATUS: Record<string, { label: string; color: string }> = {
  pending:    { label: '待发出', color: 'default' },
  dispatched: { label: '配送中', color: 'processing' },
  received:   { label: '已收货', color: 'success' },
  rejected:   { label: '已拒收', color: 'error' },
};

const PLAN_STATUS_NEXT: Record<string, string> = {
  draft:       'confirmed',
  confirmed:   'in_progress',
  in_progress: 'done',
};

const TENANT_ID = localStorage.getItem('tx_tenant_id') || 'demo-tenant';

// ─── API 工具函数 ────────────────────────────────────────────────────────────

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

// ═══════════════════════════════════════════════════════════════════════════════
// Tab1: 配方管理
// ═══════════════════════════════════════════════════════════════════════════════

function RecipesTab() {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [loading, setLoading] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailRecipe, setDetailRecipe] = useState<Recipe | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();
  const [ingredientRows, setIngredientRows] = useState<RecipeIngredient[]>([]);

  const fetchRecipes = async () => {
    setLoading(true);
    try {
      const res = await txApi<{ items: Recipe[] }>('/api/v1/supply/recipes');
      setRecipes(res.data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取配方列表失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchDetail = async (recipeId: string) => {
    try {
      const res = await txApi<Recipe>(`/api/v1/supply/recipes/${recipeId}`);
      setDetailRecipe(res.data);
      setDetailOpen(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取配方详情失败');
    }
  };

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await txApi('/api/v1/supply/recipes', {
        method: 'POST',
        body: JSON.stringify({
          dish_id: values.dish_id,
          yield_qty: values.yield_qty,
          yield_unit: values.yield_unit,
          notes: values.notes,
          ingredients: ingredientRows.map((r) => ({
            ingredient_name: r.ingredient_name,
            qty: r.qty,
            unit: r.unit,
            loss_rate: r.loss_rate,
          })),
        }),
      });
      message.success('配方创建成功');
      setCreateOpen(false);
      form.resetFields();
      setIngredientRows([]);
      fetchRecipes();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '创建失败');
    }
  };

  const addIngredientRow = () => {
    setIngredientRows((prev) => [
      ...prev,
      { id: String(Date.now()), ingredient_name: '', qty: 0, unit: 'g', loss_rate: 0 },
    ]);
  };

  const updateIngredientRow = (idx: number, field: keyof RecipeIngredient, value: unknown) => {
    setIngredientRows((prev) => {
      const next = [...prev];
      (next[idx] as unknown as Record<string, unknown>)[field] = value;
      return next;
    });
  };

  useEffect(() => { fetchRecipes(); }, []);

  const columns = [
    { title: '菜品ID', dataIndex: 'dish_id', ellipsis: true, width: 180 },
    { title: '版本',   dataIndex: 'version',         width: 60 },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '激活' : '停用'}</Tag>,
    },
    {
      title: '产出',
      render: (_: unknown, r: Recipe) => `${r.yield_qty} ${r.yield_unit}`,
      width: 100,
    },
    { title: '原料数', dataIndex: 'ingredient_count', width: 80 },
    { title: '备注',   dataIndex: 'notes', ellipsis: true },
    {
      title: '操作',
      width: 100,
      render: (_: unknown, r: Recipe) => (
        <Button size="small" type="link" onClick={() => fetchDetail(r.id)}>
          查看原料
        </Button>
      ),
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Title level={5} style={{ margin: 0 }}>配方列表</Title>
        <Button type="primary" onClick={() => setCreateOpen(true)}>
          新建配方
        </Button>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={recipes}
        columns={columns}
        size="small"
        pagination={{ pageSize: 20 }}
      />

      {/* 原料明细抽屉 */}
      <Drawer
        title={`配方原料明细 — v${detailRecipe?.version ?? ''}`}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        width={560}
      >
        {detailRecipe && (
          <>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="菜品ID">{detailRecipe.dish_id}</Descriptions.Item>
              <Descriptions.Item label="版本">{detailRecipe.version}</Descriptions.Item>
              <Descriptions.Item label="产出量">
                {detailRecipe.yield_qty} {detailRecipe.yield_unit}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={detailRecipe.is_active ? 'success' : 'default'}>
                  {detailRecipe.is_active ? '激活' : '停用'}
                </Tag>
              </Descriptions.Item>
              {detailRecipe.notes && (
                <Descriptions.Item label="备注" span={2}>{detailRecipe.notes}</Descriptions.Item>
              )}
            </Descriptions>

            <Table
              rowKey="id"
              dataSource={detailRecipe.ingredients ?? []}
              size="small"
              pagination={false}
              columns={[
                { title: '原料名称', dataIndex: 'ingredient_name' },
                { title: '用量',     dataIndex: 'qty', width: 80 },
                { title: '单位',     dataIndex: 'unit', width: 60 },
                {
                  title: '损耗率',
                  dataIndex: 'loss_rate',
                  width: 80,
                  render: (v: number) => `${(v * 100).toFixed(1)}%`,
                },
              ]}
            />
          </>
        )}
      </Drawer>

      {/* 新建配方 Modal */}
      <Modal
        title="新建配方"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateOpen(false); form.resetFields(); setIngredientRows([]); }}
        width={680}
        okText="保存"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="dish_id" label="菜品ID" rules={[{ required: true }]}>
            <Input placeholder="输入菜品UUID" />
          </Form.Item>
          <Space>
            <Form.Item name="yield_qty" label="产出量" initialValue={1}>
              <InputNumber min={0.001} step={0.5} />
            </Form.Item>
            <Form.Item name="yield_unit" label="产出单位" initialValue="portion">
              <Select style={{ width: 120 }}>
                <Select.Option value="portion">份</Select.Option>
                <Select.Option value="kg">kg</Select.Option>
                <Select.Option value="g">g</Select.Option>
                <Select.Option value="L">L</Select.Option>
              </Select>
            </Form.Item>
          </Space>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>

        <div style={{ marginBottom: 8 }}>
          <Text strong>原料明细</Text>
          <Button size="small" style={{ marginLeft: 8 }} onClick={addIngredientRow}>
            + 添加原料
          </Button>
        </div>
        <Table
          rowKey="id"
          dataSource={ingredientRows}
          size="small"
          pagination={false}
          columns={[
            {
              title: '原料名称', dataIndex: 'ingredient_name', render: (_v, _r, idx) => (
                <Input
                  size="small"
                  value={ingredientRows[idx].ingredient_name}
                  onChange={(e) => updateIngredientRow(idx, 'ingredient_name', e.target.value)}
                />
              ),
            },
            {
              title: '用量', dataIndex: 'qty', width: 80, render: (_v, _r, idx) => (
                <InputNumber
                  size="small"
                  min={0}
                  value={ingredientRows[idx].qty}
                  onChange={(v) => updateIngredientRow(idx, 'qty', v ?? 0)}
                />
              ),
            },
            {
              title: '单位', dataIndex: 'unit', width: 80, render: (_v, _r, idx) => (
                <Select
                  size="small"
                  value={ingredientRows[idx].unit}
                  onChange={(v) => updateIngredientRow(idx, 'unit', v)}
                  style={{ width: 70 }}
                >
                  {['g', 'kg', 'ml', 'L', '个', '片', '份'].map((u) => (
                    <Select.Option key={u} value={u}>{u}</Select.Option>
                  ))}
                </Select>
              ),
            },
            {
              title: '损耗率', dataIndex: 'loss_rate', width: 90, render: (_v, _r, idx) => (
                <InputNumber
                  size="small"
                  min={0}
                  max={1}
                  step={0.01}
                  value={ingredientRows[idx].loss_rate}
                  onChange={(v) => updateIngredientRow(idx, 'loss_rate', v ?? 0)}
                  formatter={(v) => `${((v ?? 0) * 100).toFixed(0)}%`}
                  parser={(v) => parseFloat((v ?? '0').replace('%', '')) / 100}
                />
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
                  onClick={() => setIngredientRows((prev) => prev.filter((_, i) => i !== idx))}
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
// Tab2: 生产计划
// ═══════════════════════════════════════════════════════════════════════════════

function PlansTab() {
  const [plans, setPlans] = useState<ProductionPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [materialOpen, setMaterialOpen] = useState(false);
  const [materialList, setMaterialList] = useState<MaterialItem[]>([]);
  const [materialPlanDate, setMaterialPlanDate] = useState('');

  const fetchPlans = async () => {
    setLoading(true);
    try {
      const res = await txApi<{ items: ProductionPlan[] }>('/api/v1/supply/ck/plans');
      setPlans(res.data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取生产计划失败');
    } finally {
      setLoading(false);
    }
  };

  const advanceStatus = async (plan: ProductionPlan) => {
    const nextStatus = PLAN_STATUS_NEXT[plan.status];
    if (!nextStatus) {
      message.info('计划已完成，无法继续推进');
      return;
    }
    try {
      await txApi(`/api/v1/supply/ck/plans/${plan.id}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: nextStatus }),
      });
      message.success(`计划状态已更新为：${PLAN_STATUS[nextStatus]?.label}`);
      fetchPlans();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '状态更新失败');
    }
  };

  const showMaterialList = async (plan: ProductionPlan) => {
    try {
      const res = await txApi<{ items: MaterialItem[]; plan_date: string }>(
        `/api/v1/supply/ck/plans/${plan.id}/material-list`,
      );
      setMaterialList(res.data.items);
      setMaterialPlanDate(res.data.plan_date);
      setMaterialOpen(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取原料清单失败');
    }
  };

  useEffect(() => { fetchPlans(); }, []);

  const columns = [
    { title: '计划日期', dataIndex: 'plan_date', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const cfg = PLAN_STATUS[s] ?? { label: s, color: 'default' };
        return <Badge status={cfg.color as Parameters<typeof Badge>[0]['status']} text={cfg.label} />;
      },
    },
    {
      title: '目标门店',
      dataIndex: 'store_id',
      render: (v?: string) => v ? <Text code>{v.slice(0, 8)}…</Text> : <Text type="secondary">多门店</Text>,
    },
    { title: '菜品数', dataIndex: 'item_count', width: 80 },
    { title: '创建人', dataIndex: 'created_by', width: 100 },
    { title: '备注',   dataIndex: 'notes', ellipsis: true },
    {
      title: '操作',
      width: 180,
      render: (_: unknown, plan: ProductionPlan) => (
        <Space>
          {PLAN_STATUS_NEXT[plan.status] && (
            <Button size="small" type="primary" onClick={() => advanceStatus(plan)}>
              推进状态
            </Button>
          )}
          <Button size="small" onClick={() => showMaterialList(plan)}>
            原料清单
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0 }}>生产计划</Title>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={plans}
        columns={columns}
        size="small"
        pagination={{ pageSize: 20 }}
      />

      <Drawer
        title={`原料汇总清单 — ${materialPlanDate}`}
        open={materialOpen}
        onClose={() => setMaterialOpen(false)}
        width={500}
      >
        <Table
          rowKey="ingredient_name"
          dataSource={materialList}
          size="small"
          pagination={false}
          columns={[
            { title: '原料名称', dataIndex: 'ingredient_name' },
            {
              title: '需求量',
              dataIndex: 'total_qty',
              width: 100,
              render: (v: number) => v.toFixed(3),
            },
            { title: '单位', dataIndex: 'unit', width: 60 },
          ]}
        />
      </Drawer>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tab3: 调拨单
// ═══════════════════════════════════════════════════════════════════════════════

function DispatchTab() {
  const [orders, setOrders] = useState<DispatchOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [receiveOpen, setReceiveOpen] = useState(false);
  const [currentOrder, setCurrentOrder] = useState<DispatchOrder | null>(null);
  const [receiveForm] = Form.useForm();
  const receiveItemsRef = useRef<Record<string, number>>({});

  const fetchOrders = async () => {
    setLoading(true);
    try {
      const res = await txApi<{ items: DispatchOrder[] }>('/api/v1/supply/ck/dispatch');
      setOrders(res.data.items);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取调拨单失败');
    } finally {
      setLoading(false);
    }
  };

  const openReceive = async (order: DispatchOrder) => {
    // 获取调拨单明细
    try {
      const res = await txApi<DispatchOrder>(`/api/v1/supply/ck/dispatch/${order.id}/print`);
      // 用打印数据中的 dispatch_no 来确认订单，实际应从 detail 接口取明细
      setCurrentOrder(order);
      receiveItemsRef.current = {};
      setReceiveOpen(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取调拨单详情失败');
    }
  };

  const handleReceive = async () => {
    if (!currentOrder) return;
    try {
      const values = await receiveForm.validateFields();
      const items = (currentOrder.items ?? []).map((item) => ({
        dish_id: item.dish_id,
        actual_qty: receiveItemsRef.current[item.dish_id] ?? item.planned_qty,
      }));
      await txApi(`/api/v1/supply/ck/dispatch/${currentOrder.id}/receive`, {
        method: 'PUT',
        body: JSON.stringify({
          receiver_name: values.receiver_name,
          items,
        }),
      });
      message.success('收货确认成功');
      setReceiveOpen(false);
      receiveForm.resetFields();
      fetchOrders();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '确认收货失败');
    }
  };

  const printOrder = async (order: DispatchOrder) => {
    try {
      const res = await txApi<{ dispatch_no: string; print_blocks: unknown[] }>(
        `/api/v1/supply/ck/dispatch/${order.id}/print`,
      );
      if (window.TXBridge) {
        // 安卓 POS 环境：通过 JS Bridge 调用商米打印 SDK
        window.TXBridge.print(JSON.stringify(res.data.print_blocks));
      } else {
        // 浏览器环境：弹窗预览
        Modal.info({
          title: `调拨单打印预览 — ${res.data.dispatch_no}`,
          content: (
            <pre style={{ fontSize: 12, maxHeight: 400, overflow: 'auto' }}>
              {JSON.stringify(res.data.print_blocks, null, 2)}
            </pre>
          ),
          width: 600,
        });
      }
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '获取打印数据失败');
    }
  };

  useEffect(() => { fetchOrders(); }, []);

  const columns = [
    { title: '单号',     dataIndex: 'dispatch_no', width: 180, render: (v: string) => <Text code>{v}</Text> },
    {
      title: '来源→目标',
      render: (_: unknown, o: DispatchOrder) => (
        <span>
          <Text type="secondary">{o.from_store_id ? o.from_store_id.slice(0, 6) + '…' : '总厂'}</Text>
          {' → '}
          <Text strong>{o.to_store_id.slice(0, 6)}…</Text>
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const cfg = DISPATCH_STATUS[s] ?? { label: s, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    { title: '调拨日期', dataIndex: 'dispatch_date', width: 110 },
    { title: '司机',     dataIndex: 'driver_name',  width: 90 },
    {
      title: '操作',
      width: 160,
      render: (_: unknown, order: DispatchOrder) => (
        <Space>
          {order.status === 'dispatched' && (
            <Button size="small" type="primary" onClick={() => openReceive(order)}>
              确认收货
            </Button>
          )}
          <Button size="small" onClick={() => printOrder(order)}>
            打印
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0 }}>调拨单</Title>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={orders}
        columns={columns}
        size="small"
        pagination={{ pageSize: 20 }}
      />

      {/* 确认收货 Modal */}
      <Modal
        title={`确认收货 — ${currentOrder?.dispatch_no ?? ''}`}
        open={receiveOpen}
        onOk={handleReceive}
        onCancel={() => { setReceiveOpen(false); receiveForm.resetFields(); }}
        okText="确认收货"
        width={560}
      >
        <Form form={receiveForm} layout="vertical">
          <Form.Item name="receiver_name" label="收货人姓名">
            <Input placeholder="请输入收货人" />
          </Form.Item>
        </Form>

        {currentOrder?.items && currentOrder.items.length > 0 && (
          <Table
            rowKey="dish_id"
            dataSource={currentOrder.items}
            size="small"
            pagination={false}
            columns={[
              { title: '菜品ID', dataIndex: 'dish_id', ellipsis: true },
              { title: '计划量', dataIndex: 'planned_qty', width: 80 },
              { title: '单位',   dataIndex: 'unit', width: 60 },
              {
                title: '实收量',
                width: 100,
                render: (_v, item: DispatchItem) => (
                  <InputNumber
                    size="small"
                    min={0}
                    defaultValue={item.planned_qty}
                    onChange={(v) => {
                      receiveItemsRef.current[item.dish_id] = v ?? 0;
                    }}
                  />
                ),
              },
            ]}
          />
        )}
        {(!currentOrder?.items || currentOrder.items.length === 0) && (
          <Text type="secondary">暂无明细数据，将提交默认实收量</Text>
        )}
      </Modal>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════════════════════════

export function CentralKitchenPage() {
  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        中央厨房管理
      </Title>

      <Tabs defaultActiveKey="recipes" type="card">
        <TabPane tab="配方管理" key="recipes">
          <RecipesTab />
        </TabPane>
        <TabPane tab="生产计划" key="plans">
          <PlansTab />
        </TabPane>
        <TabPane tab="调拨单" key="dispatch">
          <DispatchTab />
        </TabPane>
      </Tabs>
    </div>
  );
}

// TXBridge 类型已在 bridge/TXBridge.ts 中声明
