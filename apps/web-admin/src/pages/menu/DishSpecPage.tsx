/**
 * DishSpecPage — 菜品规格管理
 * 域B：规格组管理（容量/份量/温度等维度），各规格加价配置
 * 技术栈：Ant Design 5.x + ProComponents
 */
import { useRef, useState, useEffect } from 'react';
import { txFetchData } from '../../api';
import {
  ProTable,
  ModalForm,
  ProFormText,
  ProFormSwitch,
  ActionType,
  ProColumns,
} from '@ant-design/pro-components';
import {
  Button,
  Tag,
  Space,
  Popconfirm,
  message,
  Form,
  Input,
  InputNumber,
  Typography,
  Badge,
} from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusCircleOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

// ─── 类型定义 ───────────────────────────────────────────────

interface SpecOption {
  name: string;
  price_delta_fen: number;
}

interface DishSpec {
  id: string;
  dish_id: string;
  dish_name: string;
  spec_group: string;
  options: SpecOption[];
  is_required: boolean;
}

// ─── API 函数 ───────────────────────────────────────────────

async function fetchDishSpecs(dishId: string): Promise<DishSpec[]> {
  try {
    const res = await txFetchData<{ items: DishSpec[] }>(`/api/v1/menu/dishes/${dishId}/specs`);
    return res?.items ?? [];
  } catch (err) {
    console.error('[DishSpecPage] fetchDishSpecs 失败:', err);
    return [];
  }
}

async function fetchAllSpecs(params: { dish_name?: string; spec_group?: string; current?: number; pageSize?: number }): Promise<{ data: DishSpec[]; total: number; success: boolean }> {
  try {
    const query = new URLSearchParams();
    if (params.dish_name) query.set('dish_name', params.dish_name);
    if (params.spec_group) query.set('spec_group', params.spec_group);
    query.set('page', String(params.current ?? 1));
    query.set('size', String(params.pageSize ?? 10));
    const res = await txFetchData<{ items: DishSpec[]; total: number }>(`/api/v1/menu/specs?${query.toString()}`);
    return { data: res?.items ?? [], total: res?.total ?? 0, success: true };
  } catch (err) {
    console.error('[DishSpecPage] fetchAllSpecs 失败:', err);
    return { data: [], total: 0, success: false };
  }
}

async function createSpec(dishId: string, payload: { name: string; options: SpecOption[]; is_required: boolean }): Promise<void> {
  await txFetchData<DishSpec>(`/api/v1/menu/dishes/${dishId}/specs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

async function updateSpec(dishId: string, specId: string, payload: Partial<{ name: string; options: SpecOption[]; is_required: boolean }>): Promise<void> {
  await txFetchData<DishSpec>(`/api/v1/menu/dishes/${dishId}/specs/${specId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

async function deleteSpec(dishId: string, specId: string): Promise<void> {
  await txFetchData<void>(`/api/v1/menu/dishes/${dishId}/specs/${specId}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_deleted: true }),
  });
}

// ─── 工具函数 ────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  const yuan = fen / 100;
  return yuan >= 0 ? `+¥${yuan.toFixed(2)}` : `-¥${Math.abs(yuan).toFixed(2)}`;
}

function formatDeltaTag(fen: number) {
  if (fen === 0) return <Tag color="default">基准价</Tag>;
  if (fen > 0) return <Tag color="orange">+¥{(fen / 100).toFixed(2)}</Tag>;
  return <Tag color="blue">-¥{(Math.abs(fen) / 100).toFixed(2)}</Tag>;
}

// ─── 规格选项内联编辑子组件 ──────────────────────────────────

interface SpecOptionsEditorProps {
  value?: SpecOption[];
  onChange?: (v: SpecOption[]) => void;
}

function SpecOptionsEditor({ value = [], onChange }: SpecOptionsEditorProps) {
  const options = value;

  const handleAdd = () => {
    onChange?.([...options, { name: '', price_delta_fen: 0 }]);
  };

  const handleRemove = (idx: number) => {
    onChange?.(options.filter((_, i) => i !== idx));
  };

  const handleChange = (idx: number, field: keyof SpecOption, val: string | number) => {
    const next = options.map((opt, i) =>
      i === idx ? { ...opt, [field]: val } : opt
    );
    onChange?.(next);
  };

  return (
    <div>
      {options.map((opt, idx) => (
        <div
          key={idx}
          style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}
        >
          <Input
            placeholder="选项名称（如：大杯）"
            value={opt.name}
            onChange={(e) => handleChange(idx, 'name', e.target.value)}
            style={{ flex: 2 }}
          />
          <InputNumber
            placeholder="加价（分）"
            value={opt.price_delta_fen}
            onChange={(v) => handleChange(idx, 'price_delta_fen', v ?? 0)}
            addonBefore="¥"
            formatter={(v) => `${(Number(v) / 100).toFixed(2)}`}
            parser={(v) => Math.round(parseFloat(v?.replace('¥', '') ?? '0') * 100)}
            style={{ flex: 1 }}
          />
          <Text type="secondary" style={{ fontSize: 12, minWidth: 60 }}>
            {fenToYuan(opt.price_delta_fen)}
          </Text>
          <Button
            type="text"
            danger
            icon={<MinusCircleOutlined />}
            onClick={() => handleRemove(idx)}
            disabled={options.length <= 1}
          />
        </div>
      ))}
      <Button
        type="dashed"
        icon={<PlusCircleOutlined />}
        onClick={handleAdd}
        block
        style={{ marginTop: 4 }}
      >
        添加选项
      </Button>
    </div>
  );
}

// ─── 主组件 ─────────────────────────────────────────────────

export function DishSpecPage() {
  const actionRef = useRef<ActionType>();
  const [editSpec, setEditSpec] = useState<DishSpec | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  // 新建时选择菜品ID（真实环境应从菜品列表选择）
  const [createDishId, setCreateDishId] = useState('');
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();

  // 用 useEffect 避免 import 警告
  useEffect(() => { /* 组件挂载后 actionRef 已可用 */ }, []);

  // ── 列定义 ──
  const columns: ProColumns<DishSpec>[] = [
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      width: 120,
      render: (_, r) => <Text strong>{r.dish_name}</Text>,
    },
    {
      title: '规格组名',
      dataIndex: 'spec_group',
      width: 100,
      render: (_, r) => (
        <Tag color="purple" style={{ fontWeight: 600 }}>
          {r.spec_group}
        </Tag>
      ),
    },
    {
      title: '必选',
      dataIndex: 'is_required',
      width: 70,
      render: (_, r) =>
        r.is_required ? (
          <Badge status="error" text="必选" />
        ) : (
          <Badge status="default" text="可选" />
        ),
    },
    {
      title: '规格选项',
      dataIndex: 'options',
      search: false,
      render: (_, r) => (
        <Space wrap size={4}>
          {r.options.map((opt) => (
            <Tag
              key={opt.name}
              style={{ marginBottom: 2 }}
              color={opt.price_delta_fen === 0 ? 'default' : opt.price_delta_fen > 0 ? 'orange' : 'geekblue'}
            >
              {opt.name}
              {opt.price_delta_fen !== 0 && (
                <Text
                  style={{
                    marginLeft: 4,
                    fontSize: 11,
                    color: opt.price_delta_fen > 0 ? '#d46b08' : '#1d39c4',
                  }}
                >
                  {opt.price_delta_fen > 0
                    ? `+¥${(opt.price_delta_fen / 100).toFixed(2)}`
                    : `-¥${(Math.abs(opt.price_delta_fen) / 100).toFixed(2)}`}
                </Text>
              )}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '价差范围',
      width: 140,
      search: false,
      render: (_, r) => {
        const deltas = r.options.map((o) => o.price_delta_fen);
        const min = Math.min(...deltas);
        const max = Math.max(...deltas);
        if (min === max && min === 0) return <Text type="secondary">等价规格</Text>;
        return (
          <Text>
            {min !== 0 && formatDeltaTag(min)} 至 {formatDeltaTag(max)}
          </Text>
        );
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 120,
      render: (_, record) => [
        <Button
          key="edit"
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            setEditSpec(record);
            editForm.setFieldsValue({
              dish_name: record.dish_name,
              spec_group: record.spec_group,
              is_required: record.is_required,
              options: record.options,
            });
            setEditOpen(true);
          }}
        >
          编辑
        </Button>,
        <Popconfirm
          key="delete"
          title="确认删除该规格组？"
          description="删除后关联菜品的规格选项将一并移除。"
          onConfirm={() => handleDelete(record)}
          okText="确认删除"
          cancelText="取消"
          okType="danger"
        >
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>,
      ],
    },
  ];

  // ── 新增规格组表单 ──
  const handleCreate = async (values: {
    dish_id: string;
    spec_group: string;
    is_required: boolean;
    options: SpecOption[];
  }) => {
    const targetDishId = values.dish_id?.trim() || createDishId;
    if (!targetDishId) {
      message.error('请输入菜品 ID');
      return false;
    }
    try {
      await createSpec(targetDishId, {
        name: values.spec_group,
        options: values.options,
        is_required: values.is_required,
      });
      setCreateDishId(targetDishId);
      message.success(`规格组「${values.spec_group}」创建成功`);
      actionRef.current?.reload();
      return true;
    } catch {
      message.error('创建失败，请重试');
      return false;
    }
  };

  // ── 编辑规格组表单 ──
  const handleEdit = async (values: {
    dish_name: string;
    spec_group: string;
    is_required: boolean;
    options: SpecOption[];
  }) => {
    if (!editSpec) return false;
    try {
      await updateSpec(editSpec.dish_id, editSpec.id, {
        name: values.spec_group,
        options: values.options,
        is_required: values.is_required,
      });
      message.success(`规格组「${values.spec_group}」更新成功`);
      actionRef.current?.reload();
      return true;
    } catch {
      message.error('更新失败，请重试');
      return false;
    }
  };

  // ── 删除规格组 ──
  const handleDelete = async (record: DishSpec) => {
    try {
      await deleteSpec(record.dish_id, record.id);
      message.success(`规格组「${record.spec_group}」已删除`);
      actionRef.current?.reload();
    } catch {
      message.error('删除失败，请重试');
    }
  };

  return (
    <div style={{ padding: 0 }}>
      {/* 新增规格组 ModalForm */}
      <ModalForm
        title="新增规格组"
        open={createOpen}
        onOpenChange={(v) => {
          setCreateOpen(v);
          if (!v) form.resetFields();
        }}
        form={form}
        onFinish={handleCreate}
        modalProps={{ destroyOnClose: true, width: 600 }}
        initialValues={{ is_required: false, options: [{ name: '', price_delta_fen: 0 }] }}
      >
        <ProFormText
          name="dish_id"
          label="菜品 ID"
          placeholder="请输入菜品 ID（如：dish_001）"
          rules={[{ required: true, message: '请输入菜品 ID' }]}
        />
        <ProFormText
          name="spec_group"
          label="规格组名称"
          placeholder="如：容量、份量、辣度、温度"
          rules={[{ required: true, message: '请输入规格组名称' }]}
        />
        <ProFormSwitch
          name="is_required"
          label="是否必选"
          fieldProps={{ checkedChildren: '必选', unCheckedChildren: '可选' }}
        />
        <Form.Item
          name="options"
          label="规格选项"
          rules={[
            {
              validator: (_, v: SpecOption[]) => {
                if (!v || v.length === 0) return Promise.reject('至少添加一个规格选项');
                if (v.some((o) => !o.name.trim())) return Promise.reject('选项名称不能为空');
                return Promise.resolve();
              },
            },
          ]}
        >
          <SpecOptionsEditor />
        </Form.Item>
      </ModalForm>

      {/* 编辑规格组 ModalForm */}
      <ModalForm
        title={`编辑规格组 — ${editSpec?.dish_name} · ${editSpec?.spec_group}`}
        open={editOpen}
        onOpenChange={(v) => {
          setEditOpen(v);
          if (!v) {
            setEditSpec(null);
            editForm.resetFields();
          }
        }}
        form={editForm}
        onFinish={handleEdit}
        modalProps={{ destroyOnClose: true, width: 600 }}
      >
        <ProFormText
          name="dish_name"
          label="菜品名称"
          rules={[{ required: true, message: '请输入菜品名称' }]}
        />
        <ProFormText
          name="spec_group"
          label="规格组名称"
          rules={[{ required: true, message: '请输入规格组名称' }]}
        />
        <ProFormSwitch
          name="is_required"
          label="是否必选"
          fieldProps={{ checkedChildren: '必选', unCheckedChildren: '可选' }}
        />
        <Form.Item
          name="options"
          label="规格选项"
          rules={[
            {
              validator: (_, v: SpecOption[]) => {
                if (!v || v.length === 0) return Promise.reject('至少添加一个规格选项');
                if (v.some((o) => !o.name.trim())) return Promise.reject('选项名称不能为空');
                return Promise.resolve();
              },
            },
          ]}
        >
          <SpecOptionsEditor />
        </Form.Item>
      </ModalForm>

      {/* ProTable 主列表 */}
      <ProTable<DishSpec>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        headerTitle="菜品规格管理"
        request={async (params) => fetchAllSpecs(params)}
        search={{
          labelWidth: 'auto',
          filterType: 'light',
        }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新增规格组
          </Button>,
        ]}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        cardBordered
        scroll={{ x: 900 }}
      />
    </div>
  );
}
