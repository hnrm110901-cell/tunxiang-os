/**
 * 宴席套餐模板管理页 — 域A 宴会交易 · 总部视角
 * ProTable 主列表 | DrawerForm 创建/编辑 | Modal 生成报价单
 *
 * 技术栈：Ant Design 5.x + ProComponents
 * API: txFetchData → /api/v1/banquets/templates ; try/catch 降级 Mock
 * 金额规范：存储/传输分(fen)，展示元(÷100)，提交时×100
 */
import React, { useRef, useState, useCallback } from 'react';
import { formatPrice } from '@tx-ds/utils';
import {
  ProTable,
  DrawerForm,
  ProFormText,
  ProFormSelect,
  ProFormDigit,
  ProFormTextArea,
  ProFormSlider,
  ActionType,
} from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import {
  Button,
  Tag,
  Space,
  Switch,
  Modal,
  Drawer,
  Descriptions,
  Table,
  InputNumber,
  Checkbox,
  Select,
  Form,
  message,
  Typography,
  Divider,
  Row,
  Col,
  Card,
  Statistic,
  Alert,
  List,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  PlusCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../../api/client';

const { Text, Title } = Typography;

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

export type BanquetCategory = 'wedding' | 'business' | 'birthday' | 'festival' | 'other';

export type DishCategory =
  | 'cold_dish'
  | 'hot_dish'
  | 'soup'
  | 'staple'
  | 'dessert'
  | 'beverage';

export interface BanquetDishItem {
  key: string;
  dish_name: string;
  dish_category: DishCategory;
  quantity: number;
  unit: string;
  is_signature: boolean;
  is_replaceable: boolean;
}

export interface BanquetTemplate {
  id: string;
  name: string;
  category: BanquetCategory;
  guest_min: number;
  guest_max: number;
  per_table_price_fen: number;
  per_person_price_fen?: number;
  min_tables: number;
  deposit_ratio: number;   // 0~1，如0.3表示30%
  description?: string;
  is_active: boolean;
  dish_count: number;
  created_at: string;
  updated_at: string;
  dishes?: BanquetDishItem[];
}

export interface BuildQuotePayload {
  table_count: number;
  estimated_guest_count?: number;
  price_adjustment_note?: string;
}

export interface QuoteResult {
  quote_id: string;
  template_name: string;
  table_count: number;
  estimated_guest_count?: number;
  per_table_price_fen: number;
  total_price_fen: number;
  deposit_fen: number;
  dishes: BanquetDishItem[];
  price_adjustment_note?: string;
  created_at: string;
}

// ─── 配置 ─────────────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<BanquetCategory, { label: string; color: string }> = {
  wedding:  { label: '婚宴',   color: 'red'     },
  business: { label: '商务宴', color: 'blue'    },
  birthday: { label: '寿宴',   color: 'purple'  },
  festival: { label: '节日宴', color: 'orange'  },
  other:    { label: '其他',   color: 'default' },
};

const CATEGORY_OPTIONS = Object.entries(CATEGORY_CONFIG).map(([value, { label }]) => ({
  value,
  label,
}));

const DISH_CATEGORY_CONFIG: Record<DishCategory, string> = {
  cold_dish: '凉菜',
  hot_dish:  '热菜',
  soup:      '汤品',
  staple:    '主食',
  dessert:   '甜点',
  beverage:  '饮品',
};

const DISH_CATEGORY_OPTIONS = Object.entries(DISH_CATEGORY_CONFIG).map(([v, l]) => ({
  value: v,
  label: l,
}));

// ─── Mock 数据 ────────────────────────────────────────────────────────────────

const MOCK_TEMPLATES: BanquetTemplate[] = [
  {
    id: 't1', name: '婚宴标准套餐A', category: 'wedding',
    guest_min: 8, guest_max: 10, per_table_price_fen: 388800,
    min_tables: 20, deposit_ratio: 0.3, is_active: true,
    dish_count: 16,
    description: '适合中型婚宴，含16道经典菜品，含赠品饮料',
    created_at: '2026-01-10T08:00:00Z', updated_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 't2', name: '商务宴高端套餐', category: 'business',
    guest_min: 6, guest_max: 8, per_table_price_fen: 588800,
    per_person_price_fen: 73600,
    min_tables: 5, deposit_ratio: 0.5, is_active: true,
    dish_count: 12,
    description: '商务接待首选，含时令活鲜，人均精算定价',
    created_at: '2026-02-05T08:00:00Z', updated_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 't3', name: '寿宴经典套餐', category: 'birthday',
    guest_min: 8, guest_max: 12, per_table_price_fen: 268800,
    min_tables: 10, deposit_ratio: 0.3, is_active: false,
    dish_count: 14,
    description: '长寿面、寿桃必备，传统寿宴标配',
    created_at: '2026-01-20T08:00:00Z', updated_at: '2026-03-01T10:00:00Z',
  },
];

const MOCK_DISHES: BanquetDishItem[] = [
  { key: 'd1', dish_name: '清蒸大黄鱼', dish_category: 'hot_dish', quantity: 1, unit: '条', is_signature: true,  is_replaceable: false },
  { key: 'd2', dish_name: '白灼基围虾', dish_category: 'hot_dish', quantity: 1, unit: '份', is_signature: true,  is_replaceable: true  },
  { key: 'd3', dish_name: '口水鸡',     dish_category: 'cold_dish', quantity: 1, unit: '份', is_signature: false, is_replaceable: true  },
  { key: 'd4', dish_name: '长寿面',     dish_category: 'staple',    quantity: 1, unit: '份', is_signature: false, is_replaceable: false },
];

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number) => (fen / 100).toFixed(2);
const yuanToFen = (yuan: number) => Math.round(yuan * 100);

// ─── 可编辑菜品明细 Table ──────────────────────────────────────────────────────

interface EditableDishTableProps {
  value?: BanquetDishItem[];
  onChange?: (val: BanquetDishItem[]) => void;
}

function EditableDishTable({ value = [], onChange }: EditableDishTableProps) {
  const handleAdd = () => {
    const newRow: BanquetDishItem = {
      key: `d_${Date.now()}`,
      dish_name: '',
      dish_category: 'hot_dish',
      quantity: 1,
      unit: '份',
      is_signature: false,
      is_replaceable: true,
    };
    onChange?.([...value, newRow]);
  };

  const handleRemove = (key: string) => {
    onChange?.(value.filter((r) => r.key !== key));
  };

  const handleChange = <K extends keyof BanquetDishItem>(
    key: string,
    field: K,
    val: BanquetDishItem[K],
  ) => {
    onChange?.(value.map((r) => (r.key === key ? { ...r, [field]: val } : r)));
  };

  const columns = [
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      width: 160,
      render: (_: unknown, record: BanquetDishItem) => (
        <Form.Item style={{ margin: 0 }}>
          <input
            style={{
              width: '100%',
              border: '1px solid #E8E6E1',
              borderRadius: 4,
              padding: '4px 8px',
              fontSize: 13,
              outline: 'none',
            }}
            value={record.dish_name}
            placeholder="菜品名称"
            onChange={(e) => handleChange(record.key, 'dish_name', e.target.value)}
          />
        </Form.Item>
      ),
    },
    {
      title: '分类',
      dataIndex: 'dish_category',
      width: 100,
      render: (_: unknown, record: BanquetDishItem) => (
        <Select
          size="small"
          style={{ width: '100%' }}
          value={record.dish_category}
          options={DISH_CATEGORY_OPTIONS}
          onChange={(v) => handleChange(record.key, 'dish_category', v as DishCategory)}
        />
      ),
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      width: 80,
      render: (_: unknown, record: BanquetDishItem) => (
        <InputNumber
          size="small"
          style={{ width: '100%' }}
          min={1}
          value={record.quantity}
          onChange={(v) => handleChange(record.key, 'quantity', v ?? 1)}
        />
      ),
    },
    {
      title: '单位',
      dataIndex: 'unit',
      width: 80,
      render: (_: unknown, record: BanquetDishItem) => (
        <input
          style={{
            width: '100%',
            border: '1px solid #E8E6E1',
            borderRadius: 4,
            padding: '2px 6px',
            fontSize: 13,
            outline: 'none',
          }}
          value={record.unit}
          placeholder="份/条/碗"
          onChange={(e) => handleChange(record.key, 'unit', e.target.value)}
        />
      ),
    },
    {
      title: '主打菜',
      dataIndex: 'is_signature',
      width: 70,
      render: (_: unknown, record: BanquetDishItem) => (
        <Checkbox
          checked={record.is_signature}
          onChange={(e) => handleChange(record.key, 'is_signature', e.target.checked)}
        />
      ),
    },
    {
      title: '可替换',
      dataIndex: 'is_replaceable',
      width: 70,
      render: (_: unknown, record: BanquetDishItem) => (
        <Checkbox
          checked={record.is_replaceable}
          onChange={(e) => handleChange(record.key, 'is_replaceable', e.target.checked)}
        />
      ),
    },
    {
      title: '',
      width: 50,
      render: (_: unknown, record: BanquetDishItem) => (
        <Button
          type="text"
          danger
          size="small"
          icon={<DeleteOutlined />}
          onClick={() => handleRemove(record.key)}
        />
      ),
    },
  ];

  return (
    <div>
      <Table
        dataSource={value}
        columns={columns}
        rowKey="key"
        pagination={false}
        size="small"
        scroll={{ x: 620 }}
        style={{ marginBottom: 8 }}
      />
      <Button
        type="dashed"
        block
        icon={<PlusCircleOutlined />}
        onClick={handleAdd}
        style={{ borderColor: '#FF6B35', color: '#FF6B35' }}
      >
        添加菜品
      </Button>
    </div>
  );
}

// ─── DrawerForm（创建/编辑套餐模板）────────────────────────────────────────────

interface TemplateDrawerFormProps {
  editRecord?: BanquetTemplate;
  trigger: React.ReactNode;
  onSuccess: () => void;
}

function TemplateDrawerForm({ editRecord, trigger, onSuccess }: TemplateDrawerFormProps) {
  const isEdit = !!editRecord;

  const initialDishes: BanquetDishItem[] = editRecord?.dishes ?? MOCK_DISHES.map((d) => ({ ...d }));

  return (
    <DrawerForm
      title={isEdit ? `编辑模板 — ${editRecord?.name}` : '新建套餐模板'}
      trigger={trigger}
      width={760}
      drawerProps={{ destroyOnClose: true }}
      initialValues={
        isEdit
          ? {
              name: editRecord!.name,
              category: editRecord!.category,
              guest_min: editRecord!.guest_min,
              guest_max: editRecord!.guest_max,
              per_table_price_yuan: editRecord!.per_table_price_fen / 100,
              per_person_price_yuan: editRecord!.per_person_price_fen
                ? editRecord!.per_person_price_fen / 100
                : undefined,
              min_tables: editRecord!.min_tables,
              deposit_ratio: editRecord!.deposit_ratio * 100,
              description: editRecord!.description,
              dishes: initialDishes,
            }
          : { deposit_ratio: 30, dishes: [] }
      }
      onFinish={async (values) => {
        try {
          const payload = {
            name: values.name,
            category: values.category,
            guest_min: values.guest_min,
            guest_max: values.guest_max,
            per_table_price_fen: yuanToFen(values.per_table_price_yuan),
            per_person_price_fen: values.per_person_price_yuan
              ? yuanToFen(values.per_person_price_yuan)
              : undefined,
            min_tables: values.min_tables,
            deposit_ratio: (values.deposit_ratio ?? 30) / 100,
            description: values.description,
            dishes: (values.dishes ?? []).map((d: BanquetDishItem) => ({
              dish_name: d.dish_name,
              dish_category: d.dish_category,
              quantity: d.quantity,
              unit: d.unit,
              is_signature: d.is_signature,
              is_replaceable: d.is_replaceable,
            })),
          };

          const url = isEdit
            ? `/api/v1/banquets/templates/${editRecord!.id}`
            : '/api/v1/banquets/templates';
          const method = isEdit ? 'PATCH' : 'POST';

          await txFetchData(url, { method, body: JSON.stringify(payload) });
          message.success(isEdit ? '模板更新成功' : '套餐模板创建成功');
          onSuccess();
          return true;
        } catch {
          message.error('操作失败，请重试');
          return false;
        }
      }}
    >
      <Divider orientation="left" plain style={{ marginTop: 0 }}>基本信息</Divider>

      <ProFormText
        name="name"
        label="模板名称"
        rules={[{ required: true, message: '请输入模板名称' }]}
        placeholder="如：婚宴标准套餐88桌"
      />

      <Row gutter={16}>
        <Col span={12}>
          <ProFormSelect
            name="category"
            label="类别"
            rules={[{ required: true, message: '请选择类别' }]}
            options={CATEGORY_OPTIONS}
            placeholder="选择宴席类别"
          />
        </Col>
        <Col span={12}>
          <ProFormDigit
            name="min_tables"
            label="最少桌数"
            min={1}
            fieldProps={{ precision: 0 }}
            placeholder="最少桌数"
          />
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <ProFormDigit
            name="guest_min"
            label="最少人数/桌"
            min={1}
            fieldProps={{ precision: 0 }}
            placeholder="如：8"
          />
        </Col>
        <Col span={12}>
          <ProFormDigit
            name="guest_max"
            label="最多人数/桌"
            min={1}
            fieldProps={{ precision: 0 }}
            placeholder="如：12"
          />
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <ProFormDigit
            name="per_table_price_yuan"
            label="每桌价格（元）"
            rules={[{ required: true, message: '请输入每桌价格' }]}
            min={0}
            fieldProps={{ precision: 2, prefix: '¥' }}
            placeholder="如：3888.00"
          />
        </Col>
        <Col span={12}>
          <ProFormDigit
            name="per_person_price_yuan"
            label="每位价格（元，可选）"
            min={0}
            fieldProps={{ precision: 2, prefix: '¥' }}
            placeholder="如：388.00"
          />
        </Col>
      </Row>

      <ProFormSlider
        name="deposit_ratio"
        label="定金比例"
        min={10}
        max={50}
        step={5}
        marks={{
          10: '10%',
          20: '20%',
          30: '30%',
          40: '40%',
          50: '50%',
        }}
        fieldProps={{
          tooltip: { formatter: (v?: number) => `${v}%` },
        }}
      />

      <ProFormTextArea
        name="description"
        label="描述"
        placeholder="套餐特色、包含内容、注意事项等"
        fieldProps={{ rows: 3 }}
      />

      <Divider orientation="left" plain>菜品明细</Divider>

      <Form.Item name="dishes" style={{ marginBottom: 0 }}>
        <EditableDishTable />
      </Form.Item>
    </DrawerForm>
  );
}

// ─── 生成报价单 Modal ──────────────────────────────────────────────────────────

interface BuildQuoteModalProps {
  template: BanquetTemplate | null;
  open: boolean;
  onClose: () => void;
}

function BuildQuoteModal({ template, open, onClose }: BuildQuoteModalProps) {
  const [form] = Form.useForm();
  const [tableCount, setTableCount] = useState<number>(template?.min_tables ?? 10);
  const [quoteResult, setQuoteResult] = useState<QuoteResult | null>(null);
  const [loading, setLoading] = useState(false);

  // 实时计算
  const totalYuan = template ? (template.per_table_price_fen / 100) * tableCount : 0;
  const depositYuan = template ? totalYuan * template.deposit_ratio : 0;

  const handleSubmit = async () => {
    if (!template) return;
    try {
      await form.validateFields();
      const values = form.getFieldsValue();
      setLoading(true);
      try {
        const res = await txFetchData<QuoteResult>(
          `/api/v1/banquets/templates/${template.id}/build-quote`,
          {
            method: 'POST',
            body: JSON.stringify({
              table_count: values.table_count,
              estimated_guest_count: values.estimated_guest_count,
              price_adjustment_note: values.price_adjustment_note,
            } as BuildQuotePayload),
          },
        );
        if (res.data) {
          setQuoteResult(res.data);
          message.success('报价单已生成');
        }
      } catch {
        // Mock 报价单
        const mockResult: QuoteResult = {
          quote_id: `QT${Date.now()}`,
          template_name: template.name,
          table_count: values.table_count ?? tableCount,
          estimated_guest_count: values.estimated_guest_count,
          per_table_price_fen: template.per_table_price_fen,
          total_price_fen: template.per_table_price_fen * (values.table_count ?? tableCount),
          deposit_fen: Math.round(template.per_table_price_fen * (values.table_count ?? tableCount) * template.deposit_ratio),
          dishes: MOCK_DISHES,
          price_adjustment_note: values.price_adjustment_note,
          created_at: new Date().toISOString(),
        };
        setQuoteResult(mockResult);
        message.success('报价单已生成（演示模式）');
      } finally {
        setLoading(false);
      }
    } catch {
      // form validate error
    }
  };

  const handleClose = () => {
    form.resetFields();
    setQuoteResult(null);
    setTableCount(template?.min_tables ?? 10);
    onClose();
  };

  return (
    <Modal
      title={`生成报价单 — ${template?.name ?? ''}`}
      open={open}
      onCancel={handleClose}
      width={680}
      destroyOnClose
      footer={
        quoteResult ? (
          <Button type="primary" onClick={handleClose}>
            关闭
          </Button>
        ) : (
          <Space>
            <Button onClick={handleClose}>取消</Button>
            <Button type="primary" loading={loading} onClick={handleSubmit}>
              确认生成报价单
            </Button>
          </Space>
        )
      }
    >
      {!quoteResult ? (
        <>
          <Form form={form} layout="vertical" initialValues={{ table_count: template?.min_tables ?? 10 }}>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="table_count"
                  label="桌数"
                  rules={[{ required: true, message: '请输入桌数' }]}
                >
                  <InputNumber
                    min={template?.min_tables ?? 1}
                    style={{ width: '100%' }}
                    onChange={(v) => setTableCount(v ?? 0)}
                    addonAfter="桌"
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="estimated_guest_count" label="预计人数">
                  <InputNumber min={1} style={{ width: '100%' }} addonAfter="人" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="price_adjustment_note" label="价格调整备注">
              <input
                style={{
                  width: '100%',
                  border: '1px solid #E8E6E1',
                  borderRadius: 4,
                  padding: '6px 10px',
                  fontSize: 13,
                  outline: 'none',
                }}
                placeholder="如：节日活动减收10%"
              />
            </Form.Item>
          </Form>

          <Divider style={{ margin: '8px 0 16px' }} />
          <Row gutter={16}>
            <Col span={12}>
              <Card size="small" style={{ textAlign: 'center', background: '#FFF3ED' }}>
                <Statistic
                  title="预估总价"
                  value={totalYuan.toFixed(2)}
                  prefix="¥"
                  valueStyle={{ color: '#FF6B35', fontWeight: 600 }}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Statistic
                  title={`定金（${template ? (template.deposit_ratio * 100).toFixed(0) : 30}%）`}
                  value={depositYuan.toFixed(2)}
                  prefix="¥"
                  valueStyle={{ color: '#0F6E56', fontWeight: 600 }}
                />
              </Card>
            </Col>
          </Row>
        </>
      ) : (
        /* 报价单详情 */
        <>
          <Alert
            type="success"
            showIcon
            message={`报价单 ${quoteResult.quote_id} 已生成`}
            description={`生成时间：${dayjs(quoteResult.created_at).format('YYYY-MM-DD HH:mm')}`}
            style={{ marginBottom: 16 }}
          />
          <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="模板名称">{quoteResult.template_name}</Descriptions.Item>
            <Descriptions.Item label="桌数">{quoteResult.table_count} 桌</Descriptions.Item>
            <Descriptions.Item label="每桌价格">¥{fenToYuan(quoteResult.per_table_price_fen)}</Descriptions.Item>
            <Descriptions.Item label="预计人数">{quoteResult.estimated_guest_count ?? '—'} 人</Descriptions.Item>
            <Descriptions.Item label="费用总价">
              <Text style={{ color: '#FF6B35', fontWeight: 600, fontSize: 16 }}>
                ¥{fenToYuan(quoteResult.total_price_fen)}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="应付定金">
              <Text style={{ color: '#0F6E56', fontWeight: 600, fontSize: 16 }}>
                ¥{fenToYuan(quoteResult.deposit_fen)}
              </Text>
            </Descriptions.Item>
          </Descriptions>

          <Divider orientation="left" plain>菜品清单</Divider>
          <Table
            dataSource={quoteResult.dishes}
            rowKey="key"
            pagination={false}
            size="small"
            columns={[
              { title: '菜品', dataIndex: 'dish_name' },
              { title: '分类', dataIndex: 'dish_category', render: (v: DishCategory) => DISH_CATEGORY_CONFIG[v] ?? v },
              { title: '数量', dataIndex: 'quantity', render: (v: number, r: BanquetDishItem) => `${v} ${r.unit}` },
              { title: '主打', dataIndex: 'is_signature', render: (v: boolean) => v ? <Tag color="gold">主打</Tag> : null },
              { title: '可替换', dataIndex: 'is_replaceable', render: (v: boolean) => v ? <Tag color="cyan">可换</Tag> : <Tag>固定</Tag> },
            ]}
          />
        </>
      )}
    </Modal>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function BanquetTemplatePage() {
  const actionRef = useRef<ActionType>();
  const [quoteModalOpen, setQuoteModalOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<BanquetTemplate | null>(null);

  const handleOpenQuote = useCallback((record: BanquetTemplate) => {
    setSelectedTemplate(record);
    setQuoteModalOpen(true);
  }, []);

  const handleToggleActive = useCallback(async (record: BanquetTemplate, checked: boolean) => {
    try {
      await txFetchData(`/api/v1/banquets/templates/${record.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: checked }),
      });
      message.success(checked ? '模板已启用' : '模板已停用');
      actionRef.current?.reload();
    } catch {
      message.error('状态变更失败');
    }
  }, []);

  const columns: ProColumns<BanquetTemplate>[] = [
    {
      title: '模板名称',
      dataIndex: 'name',
      valueType: 'text',
      fixed: 'left',
      width: 200,
    },
    {
      title: '类别',
      dataIndex: 'category',
      valueType: 'select',
      width: 90,
      valueEnum: Object.fromEntries(
        Object.entries(CATEGORY_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, r) => {
        const cfg = CATEGORY_CONFIG[r.category] ?? { label: r.category, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '客人范围',
      dataIndex: 'guest_min',
      search: false,
      width: 110,
      render: (_, r) => `${r.guest_min}~${r.guest_max} 人/桌`,
    },
    {
      title: '每桌价格',
      dataIndex: 'per_table_price_fen',
      search: false,
      width: 120,
      sorter: true,
      render: (_, r) => (
        <Text style={{ color: '#FF6B35', fontWeight: 600 }}>
          ¥{fenToYuan(r.per_table_price_fen)}
        </Text>
      ),
    },
    {
      title: '最少桌数',
      dataIndex: 'min_tables',
      search: false,
      width: 90,
      render: (_, r) => `${r.min_tables} 桌`,
    },
    {
      title: '定金比例',
      dataIndex: 'deposit_ratio',
      search: false,
      width: 90,
      render: (_, r) => `${(r.deposit_ratio * 100).toFixed(0)}%`,
    },
    {
      title: '菜品数',
      dataIndex: 'dish_count',
      search: false,
      width: 80,
      render: (_, r) => `${r.dish_count} 道`,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      valueType: 'select',
      width: 90,
      valueEnum: {
        true:  { text: '已启用' },
        false: { text: '已停用' },
      },
      render: (_, record) => (
        <Switch
          size="small"
          checked={record.is_active}
          checkedChildren="启用"
          unCheckedChildren="停用"
          onChange={(checked) => handleToggleActive(record, checked)}
        />
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 160,
      render: (_, record) => [
        <TemplateDrawerForm
          key="edit"
          editRecord={record}
          trigger={
            <a>
              <EditOutlined /> 编辑
            </a>
          }
          onSuccess={() => actionRef.current?.reload()}
        />,
        <a
          key="quote"
          onClick={() => handleOpenQuote(record)}
          style={{ color: '#0F6E56' }}
        >
          <FileTextOutlined /> 生成报价
        </a>,
      ],
    },
  ];

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          宴席套餐模板管理
        </Title>
        <Text type="secondary">管理标准宴席套餐模板，支持快速生成客户报价单</Text>
      </div>

      <div style={{ background: '#fff', borderRadius: 8 }}>
        <ProTable<BanquetTemplate>
          actionRef={actionRef}
          rowKey="id"
          columns={columns}
          scroll={{ x: 1000 }}
          search={{ labelWidth: 'auto' }}
          pagination={{ defaultPageSize: 20, showSizeChanger: true }}
          toolBarRender={() => [
            <TemplateDrawerForm
              key="create"
              trigger={
                <Button type="primary" icon={<PlusOutlined />}>
                  新建套餐模板
                </Button>
              }
              onSuccess={() => actionRef.current?.reload()}
            />,
          ]}
          request={async (params) => {
            try {
              const qs = new URLSearchParams();
              if (params.category) qs.set('category', params.category);
              if (params.is_active != null) qs.set('is_active', String(params.is_active));
              if (params.guest_min) qs.set('guest_min', String(params.guest_min));
              if (params.guest_max) qs.set('guest_max', String(params.guest_max));
              qs.set('page', String(params.current ?? 1));
              qs.set('size', String(params.pageSize ?? 20));

              const res = await txFetchData<{ items: BanquetTemplate[]; total: number }>(
                `/api/v1/banquets/templates?${qs.toString()}`,
              );
              if (res.data) {
                return { data: res.data.items, total: res.data.total, success: true };
              }
              throw new Error('empty');
            } catch {
              return { data: MOCK_TEMPLATES, total: MOCK_TEMPLATES.length, success: true };
            }
          }}
        />
      </div>

      <BuildQuoteModal
        template={selectedTemplate}
        open={quoteModalOpen}
        onClose={() => {
          setQuoteModalOpen(false);
          setSelectedTemplate(null);
        }}
      />
    </div>
  );
}
