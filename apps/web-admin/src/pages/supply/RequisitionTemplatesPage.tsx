/**
 * 申购模板管理页 — 域D 供应链（PRD-07 / Phase 2 W10 / T2）
 * 路由：/supply/requisition-templates
 *
 * 功能：
 *   1. 模板列表 + 分类过滤 + 启用/禁用切换
 *   2. 新建模板（含明细 items 动态行）
 *   3. 仓库绑定（一个模板绑多个仓库 + cron 自动触发）
 *   4. 一键发起申购（基于模板生成草稿 + AI 推荐量）
 *
 * 调用接口（PRD-07）：
 *   POST   /api/v1/supply/requisition-templates
 *   GET    /api/v1/supply/requisition-templates?category=&only_active=
 *   GET    /api/v1/supply/requisition-templates/{id}
 *   PATCH  /api/v1/supply/requisition-templates/{id}
 *   DELETE /api/v1/supply/requisition-templates/{id}
 *   POST   /api/v1/supply/requisition-templates/{id}/bindings
 *   GET    /api/v1/supply/requisition-templates/warehouses/{warehouse_id}/bindings
 *   DELETE /api/v1/supply/requisition-templates/bindings/{binding_id}
 *   POST   /api/v1/supply/requisition-templates/{id}/generate
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

type TemplateCategory =
  | 'seafood'
  | 'meat'
  | 'vegetable'
  | 'seasoning'
  | 'beverage'
  | 'dry_goods'
  | 'frozen'
  | 'other';

type QtyMethod = 'fixed' | 'ai_predicted' | 'last_order' | 'par_level';

interface Template {
  id: string;
  tenant_id: string;
  name: string;
  category: TemplateCategory;
  is_active: boolean;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

interface TemplateItem {
  id: string;
  template_id: string;
  ingredient_id: string;
  default_qty: string | null;
  qty_method: QtyMethod;
  qty_unit: string | null;
  sort_order: number;
  notes: string | null;
}

interface TemplateDetail extends Template {
  items: TemplateItem[];
}

interface Binding {
  id: string;
  warehouse_id: string;
  template_id: string;
  auto_trigger_cron: string | null;
  priority: number;
  created_at: string;
  template_name?: string;
  template_category?: string;
  template_is_active?: boolean;
}

interface GeneratedItem {
  ingredient_id: string;
  suggested_qty: string | null;
  qty_method: string;
  qty_unit: string | null;
  qty_source: string;
  notes: string | null;
}

interface GeneratedDraft {
  template_id: string;
  template_name: string;
  store_id: string | null;
  items: GeneratedItem[];
  notes: string | null;
}

interface Ingredient {
  id: string;
  name: string;
  category?: string;
}

interface Store {
  id: string;
  name: string;
}

const CATEGORY_OPTIONS: { value: TemplateCategory | ''; label: string }[] = [
  { value: '', label: '全部品类' },
  { value: 'seafood', label: '海鲜' },
  { value: 'meat', label: '肉类' },
  { value: 'vegetable', label: '蔬菜' },
  { value: 'seasoning', label: '调料' },
  { value: 'beverage', label: '酒水/饮料' },
  { value: 'dry_goods', label: '干货' },
  { value: 'frozen', label: '冻品' },
  { value: 'other', label: '其他' },
];

const QTY_METHOD_OPTIONS: { value: QtyMethod; label: string; tip: string }[] = [
  { value: 'fixed', label: '固定数量', tip: '直接使用模板默认数量' },
  { value: 'ai_predicted', label: 'AI 推荐', tip: '调智能补货引擎按门店阈值推荐' },
  { value: 'last_order', label: '上次申购量', tip: '查近一次 approved 申购同 SKU 数量' },
  { value: 'par_level', label: '库存补齐', tip: '按库存阈值 target_stock - current 补齐' },
];

function categoryLabel(c: string): string {
  return CATEGORY_OPTIONS.find((o) => o.value === c)?.label ?? c;
}

function qtyMethodLabel(m: string): string {
  return QTY_METHOD_OPTIONS.find((o) => o.value === m)?.label ?? m;
}

// ─── 创建模板 Modal ──────────────────────────────────────────────────────────

interface CreateModalProps {
  open: boolean;
  ingredients: Ingredient[];
  onClose: () => void;
  onSuccess: () => void;
}

function CreateTemplateModal({ open, ingredients, onClose, onSuccess }: CreateModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    try {
      const items = (values['items'] as Array<{
        ingredient_id: string;
        qty_method: QtyMethod;
        default_qty?: number;
        qty_unit?: string;
        sort_order?: number;
        notes?: string;
      }>).map((it, idx) => ({
        ingredient_id: it.ingredient_id,
        qty_method: it.qty_method,
        default_qty:
          it.qty_method === 'fixed' && it.default_qty != null
            ? String(it.default_qty)
            : null,
        qty_unit: it.qty_unit ?? null,
        sort_order: it.sort_order ?? idx,
        notes: it.notes ?? null,
      }));
      await txFetchData('/api/v1/supply/requisition-templates', {
        method: 'POST',
        body: JSON.stringify({
          name: values['name'],
          category: values['category'],
          notes: (values['notes'] as string | undefined) ?? null,
          items,
        }),
      });
      message.success('模板已创建');
      form.resetFields();
      onSuccess();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '创建失败';
      message.error(`创建失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="新建申购模板"
      open={open}
      onCancel={() => { form.resetFields(); onClose(); }}
      onOk={handleSubmit}
      okText="创建"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={820}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="模板用途"
        description="总部预设标准 SKU 清单，门店一键发起申购自动填充。AI 推荐项可留空 default_qty — 一键发起时调智能补货引擎填充。"
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          category: 'seafood',
          items: [{ qty_method: 'fixed' }],
        }}
      >
        <Space style={{ width: '100%' }} size="middle">
          <Form.Item
            name="name"
            label="模板名称"
            rules={[{ required: true, message: '请输入模板名称' }]}
            style={{ flex: 2 }}
          >
            <Input placeholder="如：徐记海鲜大店 — 海鲜标准模板" maxLength={120} />
          </Form.Item>
          <Form.Item
            name="category"
            label="品类"
            rules={[{ required: true }]}
            style={{ minWidth: 160 }}
          >
            <Select options={CATEGORY_OPTIONS.filter((o) => o.value !== '')} />
          </Form.Item>
        </Space>

        <Form.Item label="模板明细（SKU 清单）" required>
          <Form.List name="items" rules={[{
            validator: async (_, items: unknown[]) => {
              if (!items || items.length < 1) {
                return Promise.reject(new Error('至少添加 1 个 SKU'));
              }
            },
          }]}>
            {(fields, { add, remove }, { errors }) => (
              <>
                {fields.map(({ key, name }) => (
                  <Space key={key} align="start" style={{ display: 'flex', marginBottom: 8 }}>
                    <Form.Item
                      name={[name, 'ingredient_id']}
                      rules={[{ required: true, message: '选择食材' }]}
                      style={{ minWidth: 200, marginBottom: 0 }}
                    >
                      <Select
                        placeholder="食材"
                        options={ingredients.map((i) => ({ value: i.id, label: i.name }))}
                        showSearch
                        optionFilterProp="label"
                      />
                    </Form.Item>
                    <Form.Item
                      name={[name, 'qty_method']}
                      rules={[{ required: true }]}
                      style={{ minWidth: 130, marginBottom: 0 }}
                    >
                      <Select
                        options={QTY_METHOD_OPTIONS.map((o) => ({
                          value: o.value,
                          label: o.label,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item
                      name={[name, 'default_qty']}
                      dependencies={[['items', name, 'qty_method']]}
                      rules={[
                        ({ getFieldValue }) => ({
                          validator(_, value) {
                            const method = getFieldValue(['items', name, 'qty_method']);
                            if (method === 'fixed' && (value == null || value <= 0)) {
                              return Promise.reject(new Error('固定数量必填 > 0'));
                            }
                            return Promise.resolve();
                          },
                        }),
                      ]}
                      style={{ marginBottom: 0 }}
                    >
                      <InputNumber min={0.01} step={1} placeholder="数量" style={{ width: 110 }} />
                    </Form.Item>
                    <Form.Item name={[name, 'qty_unit']} style={{ marginBottom: 0 }}>
                      <Input placeholder="单位" maxLength={16} style={{ width: 90 }} />
                    </Form.Item>
                    <Form.Item name={[name, 'notes']} style={{ flex: 1, marginBottom: 0 }}>
                      <Input placeholder="备注（可选）" />
                    </Form.Item>
                    <Button type="text" danger onClick={() => remove(name)}>删除</Button>
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add({ qty_method: 'fixed' })} icon={<PlusOutlined />} block>
                  添加 SKU
                </Button>
                <Form.ErrorList errors={errors} />
              </>
            )}
          </Form.List>
        </Form.Item>

        <Form.Item name="notes" label="备注">
          <Input.TextArea rows={2} placeholder="如：徐记海鲜大店标准；不含活鲜（活鲜走 specie 子模板）" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 仓库绑定 Drawer ────────────────────────────────────────────────────────

function BindingDrawer({
  template,
  open,
  onClose,
}: {
  template: TemplateDetail | null;
  open: boolean;
  onClose: () => void;
}) {
  const [warehouseId, setWarehouseId] = useState('');
  const [cron, setCron] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!template) return null;

  const handleSubmit = async () => {
    if (!warehouseId.trim()) {
      message.error('请输入仓库 UUID');
      return;
    }
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/supply/requisition-templates/${template.id}/bindings`, {
        method: 'POST',
        body: JSON.stringify({
          warehouse_id: warehouseId.trim(),
          template_id: template.id,
          auto_trigger_cron: cron.trim() || null,
          priority: 0,
        }),
      });
      message.success('已绑定');
      setWarehouseId('');
      setCron('');
    } catch (err) {
      const msg = err instanceof Error ? err.message : '绑定失败';
      message.error(`绑定失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer title={`绑定仓库 — ${template.name}`} open={open} onClose={onClose} width={520} destroyOnClose>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="仓库绑定说明"
        description="一个仓库可绑定多个模板（按 priority 排序）。auto_trigger_cron 留空 = 手动触发；填 cron 表达式 = 自动定期发起申购草稿。"
      />
      <Form layout="vertical">
        <Form.Item label="仓库 UUID" required>
          <Input
            placeholder="warehouse_id (UUID)"
            value={warehouseId}
            onChange={(e) => setWarehouseId(e.target.value)}
          />
        </Form.Item>
        <Form.Item label="自动触发 cron（留空 = 手动）">
          <Input
            placeholder="如 '0 6 * * *' (每天 6 点)"
            value={cron}
            onChange={(e) => setCron(e.target.value)}
            maxLength={64}
          />
        </Form.Item>
        <Button type="primary" loading={submitting} onClick={handleSubmit} block>
          创建绑定
        </Button>
      </Form>
    </Drawer>
  );
}

// ─── 一键发起申购 Modal ─────────────────────────────────────────────────────

function GenerateModal({
  template,
  open,
  stores,
  onClose,
}: {
  template: TemplateDetail | null;
  open: boolean;
  stores: Store[];
  onClose: () => void;
}) {
  const [storeId, setStoreId] = useState<string | undefined>();
  const [draft, setDraft] = useState<GeneratedDraft | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) {
      setDraft(null);
      setStoreId(undefined);
    }
  }, [open]);

  const handleGenerate = async () => {
    if (!template) return;
    setLoading(true);
    try {
      const result = await txFetchData<GeneratedDraft>(
        `/api/v1/supply/requisition-templates/${template.id}/generate`,
        {
          method: 'POST',
          body: JSON.stringify({
            store_id: storeId ?? null,
            notes: null,
          }),
        },
      );
      setDraft(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '生成失败';
      message.error(`生成失败：${msg}`);
    } finally {
      setLoading(false);
    }
  };

  if (!template) return null;

  return (
    <Modal
      title={<><ThunderboltOutlined /> 一键发起申购 — {template.name}</>}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnClose
      width={760}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Alert
          type="info"
          showIcon
          message="一键生成草稿"
          description="生成草稿后可在前端预览修改，确认后调申购接口入库走审批流。AI 推荐量调智能补货引擎，失败时 fail-open (留空待手动填)。"
        />
        <Space style={{ width: '100%' }}>
          <Select
            placeholder="选门店 (AI 推荐 / par_level 需要)"
            value={storeId}
            onChange={setStoreId}
            options={stores.map((s) => ({ value: s.id, label: s.name }))}
            style={{ minWidth: 280 }}
            allowClear
            showSearch
            optionFilterProp="label"
          />
          <Button type="primary" icon={<ThunderboltOutlined />} loading={loading} onClick={handleGenerate}>
            生成草稿
          </Button>
        </Space>

        {draft && (
          <Table
            rowKey="ingredient_id"
            size="small"
            dataSource={draft.items}
            pagination={false}
            columns={[
              {
                title: '食材',
                dataIndex: 'ingredient_id',
                render: (v: string) => <code>{v.slice(0, 8)}…</code>,
              },
              {
                title: '建议数量',
                dataIndex: 'suggested_qty',
                render: (v: string | null) =>
                  v ? <Text strong>{v}</Text> : <Text type="warning">待手动填</Text>,
              },
              { title: '单位', dataIndex: 'qty_unit', render: (v) => v ?? '—' },
              {
                title: '数量来源',
                dataIndex: 'qty_source',
                render: (s: string) => {
                  if (s === 'AI 推荐') return <Tag color="gold">{s}</Tag>;
                  if (s === '模板默认') return <Tag color="blue">{s}</Tag>;
                  if (s.includes('fail-open') || s === '未填') return <Tag color="warning">{s}</Tag>;
                  return <Tag>{s}</Tag>;
                },
              },
              { title: '备注', dataIndex: 'notes', ellipsis: true, render: (v) => v ?? '—' },
            ]}
          />
        )}
      </Space>
    </Modal>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function RequisitionTemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<TemplateCategory | ''>('');
  const [onlyActive, setOnlyActive] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailTpl, setDetailTpl] = useState<TemplateDetail | null>(null);
  const [bindingOpen, setBindingOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [stores, setStores] = useState<Store[]>([]);

  const ingredientsById = useMemo(
    () => new Map(ingredients.map((i) => [i.id, i])),
    [ingredients],
  );

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        only_active: String(onlyActive),
        limit: '100',
        offset: '0',
      });
      if (categoryFilter) params.set('category', categoryFilter);
      const data = await txFetchData<Template[]>(
        `/api/v1/supply/requisition-templates?${params.toString()}`,
      );
      setTemplates(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`加载模板失败：${msg}`);
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, onlyActive]);

  const fetchOptions = useCallback(async () => {
    try {
      const ingData = await txFetchData<{ items: Ingredient[] } | Ingredient[]>(
        '/api/v1/supply/ingredients?page=1&size=200',
      );
      const items = Array.isArray(ingData) ? ingData : ingData.items;
      setIngredients(items ?? []);
    } catch {
      // 优雅降级
    }
    try {
      const storeData = await txFetchData<{ items: Store[] } | Store[]>(
        '/api/v1/stores?page=1&size=200',
      );
      const items = Array.isArray(storeData) ? storeData : storeData.items;
      setStores(items ?? []);
    } catch {
      // 优雅降级 — 门店选项可空
    }
  }, []);

  const fetchDetail = useCallback(async (templateId: string) => {
    try {
      const data = await txFetchData<TemplateDetail>(
        `/api/v1/supply/requisition-templates/${templateId}`,
      );
      setDetailTpl(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`加载详情失败：${msg}`);
    }
  }, []);

  useEffect(() => {
    void fetchTemplates();
  }, [fetchTemplates]);

  useEffect(() => {
    void fetchOptions();
  }, [fetchOptions]);

  const handleToggleActive = async (tpl: Template) => {
    try {
      await txFetchData(`/api/v1/supply/requisition-templates/${tpl.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !tpl.is_active }),
      });
      message.success(tpl.is_active ? '已禁用' : '已启用');
      void fetchTemplates();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '操作失败';
      message.error(`操作失败：${msg}`);
    }
  };

  const handleDelete = async (tpl: Template) => {
    try {
      await txFetchData(`/api/v1/supply/requisition-templates/${tpl.id}`, {
        method: 'DELETE',
      });
      message.success('已删除');
      void fetchTemplates();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '删除失败';
      message.error(`删除失败：${msg}`);
    }
  };

  const columns: ColumnsType<Template> = [
    { title: '模板名称', dataIndex: 'name', ellipsis: true },
    {
      title: '品类',
      dataIndex: 'category',
      render: (c: string) => <Tag>{categoryLabel(c)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      render: (active: boolean, r) => (
        <Switch checked={active} onChange={() => handleToggleActive(r)} size="small" />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (d: string) => new Date(d).toLocaleString('zh-CN'),
    },
    { title: '备注', dataIndex: 'notes', ellipsis: true, render: (v) => v ?? '—' },
    {
      title: '操作',
      render: (_, r) => (
        <Space>
          <Button type="link" onClick={() => fetchDetail(r.id)}>
            详情/明细
          </Button>
          <Button
            type="link"
            icon={<ThunderboltOutlined />}
            onClick={async () => {
              await fetchDetail(r.id);
              setGenerateOpen(true);
            }}
          >
            一键发起
          </Button>
          <Popconfirm
            title="删除模板？"
            description="软删（is_deleted=TRUE），不可在 UI 恢复。"
            onConfirm={() => handleDelete(r)}
            okText="删除"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title level={3} style={{ margin: 0 }}>
            申购模板管理（PRD-07 / 一键发起 + AI 推荐量）
          </Title>
          <Space>
            <Select
              style={{ width: 160 }}
              value={categoryFilter}
              options={CATEGORY_OPTIONS}
              onChange={(v) => setCategoryFilter(v as TemplateCategory | '')}
            />
            <Space>
              <Text>只看启用</Text>
              <Switch checked={onlyActive} onChange={setOnlyActive} size="small" />
            </Space>
            <Button icon={<ReloadOutlined />} onClick={fetchTemplates} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建模板
            </Button>
          </Space>
        </div>

        <Alert
          type="info"
          showIcon
          message="使用流程"
          description="总部建模板（含 SKU 清单 + 数量计算方式）→ 模板绑定仓库（可设 cron 自动触发）→ 门店一键发起申购 → 草稿走 existing 申购审批流。"
        />

        <Table
          rowKey="id"
          loading={loading}
          dataSource={templates}
          columns={columns}
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Space>

      <CreateTemplateModal
        open={createOpen}
        ingredients={ingredients}
        onClose={() => setCreateOpen(false)}
        onSuccess={fetchTemplates}
      />

      <Drawer
        title={detailTpl ? `模板详情 — ${detailTpl.name}` : ''}
        open={!!detailTpl && !generateOpen}
        onClose={() => setDetailTpl(null)}
        width={760}
        destroyOnClose
        extra={
          detailTpl && (
            <Space>
              <Button onClick={() => setBindingOpen(true)}>绑定仓库</Button>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={() => setGenerateOpen(true)}
              >
                一键发起申购
              </Button>
            </Space>
          )
        }
      >
        {detailTpl && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Card size="small" title="基本信息">
              <Paragraph>品类：<Tag>{categoryLabel(detailTpl.category)}</Tag></Paragraph>
              <Paragraph>状态：{detailTpl.is_active ? '✓ 启用' : '× 禁用'}</Paragraph>
              <Paragraph>备注：{detailTpl.notes || <Text type="secondary">（无）</Text>}</Paragraph>
            </Card>

            <Card size="small" title={`模板明细 (${detailTpl.items.length} 行)`}>
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={detailTpl.items}
                columns={[
                  {
                    title: '食材',
                    dataIndex: 'ingredient_id',
                    render: (id: string) =>
                      ingredientsById.get(id)?.name ?? <code>{id.slice(0, 8)}…</code>,
                  },
                  {
                    title: '数量计算',
                    dataIndex: 'qty_method',
                    render: (m: string) => <Tag>{qtyMethodLabel(m)}</Tag>,
                  },
                  {
                    title: '默认数量',
                    dataIndex: 'default_qty',
                    render: (v: string | null) => v ?? <Text type="secondary">（按方式计算）</Text>,
                  },
                  { title: '单位', dataIndex: 'qty_unit', render: (v) => v ?? '—' },
                  { title: '备注', dataIndex: 'notes', ellipsis: true, render: (v) => v ?? '—' },
                ]}
              />
            </Card>
          </Space>
        )}
      </Drawer>

      <BindingDrawer
        template={detailTpl}
        open={bindingOpen}
        onClose={() => setBindingOpen(false)}
      />

      <GenerateModal
        template={detailTpl}
        open={generateOpen}
        stores={stores}
        onClose={() => setGenerateOpen(false)}
      />
    </div>
  );
}

export default RequisitionTemplatesPage;
