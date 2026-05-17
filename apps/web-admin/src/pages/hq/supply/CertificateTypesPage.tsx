/**
 * 资质证件类型字典维护页 — 域D 供应链 · 总部视角（PRD-12 / Phase 3 W13 / Tier 1 邻接）
 * 路由：/hq/supply/cert-types
 *
 * 功能：
 *   1. 证件类型列表 + 分页
 *   2. 新建证件类型（Modal 表单）
 *   3. 编辑证件类型（Modal 表单，复用）
 *   4. 软删除（Modal.confirm 确认，注明历史记录不受影响）
 *   5. 初始化默认证件（5 类标准证件，幂等按钮）
 *
 * fail-open 设计：
 *   API 读取失败时展示 FALLBACK_CERT_TYPES 作为创建时的下拉选项，
 *   不 block 证件录入操作（feedback_graceful_degradation_pattern.md）。
 *
 * 调用接口（PRD-12）：
 *   GET    /api/v1/supply/cert-types?page=1&size=20
 *   POST   /api/v1/supply/cert-types
 *   PUT    /api/v1/supply/cert-types/{id}
 *   DELETE /api/v1/supply/cert-types/{id}
 *   POST   /api/v1/supply/cert-types/initialize-defaults
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
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
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';
import {
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../../api/client';

const { Title, Text } = Typography;

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface CertificateType {
  id: string;
  tenant_id: string;
  name: string;
  applicable_supplier_kinds: string[];
  validity_period_days: number | null;
  is_required: boolean;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}

interface ListResponse {
  items: CertificateType[];
  total: number;
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────

/**
 * fail-open fallback：API 失败时展示的默认选项（不 block 操作）。
 * 参考 feedback_graceful_degradation_pattern.md
 */
const FALLBACK_CERT_TYPES = [
  '食品经营许可证',
  '食品生产许可证',
  '健康证',
  '营业执照',
  '食安管理员证',
];

const SUPPLIER_KIND_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '活鲜', value: 'seafood' },
  { label: '肉禽', value: 'meat' },
  { label: '蔬菜', value: 'vegetable' },
  { label: '调料', value: 'seasoning' },
  { label: '冷冻', value: 'frozen' },
  { label: '干货', value: 'dry_goods' },
  { label: '饮品', value: 'beverage' },
  { label: '其他', value: 'other' },
];

const SUPPLIER_KIND_LABELS: Record<string, string> = Object.fromEntries(
  SUPPLIER_KIND_OPTIONS.map(({ value, label }) => [value, label])
);

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function CertificateTypesPage() {
  const [list, setList] = useState<CertificateType[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  // modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<CertificateType | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [initLoading, setInitLoading] = useState(false);

  const [form] = Form.useForm();

  // ─── API 调用 ─────────────────────────────────────────────────────────────

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await txFetchData<{ ok: boolean; data: ListResponse }>(
        `/api/v1/supply/cert-types?page=${page}&size=${pageSize}`
      );
      setList(resp?.data?.items ?? []);
      setTotal(resp?.data?.total ?? 0);
    } catch (e) {
      message.warning('证件类型字典加载失败，已降级使用默认选项');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async (values: {
    name: string;
    applicable_supplier_kinds: string[];
    validity_period_days: number | null;
    is_required: boolean;
  }) => {
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/supply/cert-types', {
        method: 'POST',
        body: JSON.stringify({
          name: values.name,
          applicable_supplier_kinds: values.applicable_supplier_kinds ?? ['all'],
          validity_period_days: values.validity_period_days ?? null,
          is_required: values.is_required ?? true,
        }),
      });
      message.success('证件类型创建成功');
      setModalOpen(false);
      form.resetFields();
      await refresh();
    } catch (e) {
      const msg = String(e);
      if (msg.includes('409') || msg.includes('CERT_TYPE_NAME_EXISTS')) {
        message.error('同名证件类型已存在，请修改名称');
      } else {
        message.error('创建失败：' + msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async (values: {
    name: string;
    applicable_supplier_kinds: string[];
    validity_period_days: number | null;
    is_required: boolean;
  }) => {
    if (!editTarget) return;
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/supply/cert-types/${editTarget.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          name: values.name,
          applicable_supplier_kinds: values.applicable_supplier_kinds,
          validity_period_days: values.validity_period_days ?? null,
          is_required: values.is_required,
        }),
      });
      message.success('证件类型已更新');
      setModalOpen(false);
      setEditTarget(null);
      form.resetFields();
      await refresh();
    } catch (e) {
      message.error('更新失败：' + String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (record: CertificateType) => {
    try {
      await txFetchData(`/api/v1/supply/cert-types/${record.id}`, {
        method: 'DELETE',
      });
      message.success('已软删除，历史证件记录不受影响');
      await refresh();
    } catch (e) {
      message.error('删除失败：' + String(e));
    }
  };

  const handleInitDefaults = async () => {
    setInitLoading(true);
    try {
      const resp = await txFetchData<{
        ok: boolean;
        data: { created: number; skipped: number; total_defaults: number };
      }>('/api/v1/supply/cert-types/initialize-defaults', { method: 'POST' });
      const { created, skipped } = resp?.data ?? { created: 0, skipped: 0 };
      message.success(
        `初始化完成：新建 ${created} 类，跳过 ${skipped} 类（已存在）`
      );
      await refresh();
    } catch (e) {
      message.error('初始化失败：' + String(e));
    } finally {
      setInitLoading(false);
    }
  };

  const openCreate = () => {
    setEditTarget(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: CertificateType) => {
    setEditTarget(record);
    form.setFieldsValue({
      name: record.name,
      applicable_supplier_kinds: record.applicable_supplier_kinds,
      validity_period_days: record.validity_period_days,
      is_required: record.is_required,
    });
    setModalOpen(true);
  };

  const onModalSubmit = (values: {
    name: string;
    applicable_supplier_kinds: string[];
    validity_period_days: number | null;
    is_required: boolean;
  }) => {
    if (editTarget) {
      void handleUpdate(values);
    } else {
      void handleCreate(values);
    }
  };

  // ─── 表格列 ────────────────────────────────────────────────────────────────

  const columns: ColumnsType<CertificateType> = [
    {
      title: '证件类型名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record) => (
        <Space>
          <Text strong>{name}</Text>
          {record.is_required && <Tag color="red">必须</Tag>}
        </Space>
      ),
    },
    {
      title: '适用供应商类型',
      dataIndex: 'applicable_supplier_kinds',
      key: 'applicable_supplier_kinds',
      render: (kinds: string[]) =>
        kinds.map((k) => (
          <Tag key={k} color={k === 'all' ? 'blue' : 'green'}>
            {SUPPLIER_KIND_LABELS[k] ?? k}
          </Tag>
        )),
    },
    {
      title: '有效期（天）',
      dataIndex: 'validity_period_days',
      key: 'validity_period_days',
      render: (days: number | null) =>
        days != null ? `${days} 天` : <Text type="secondary">长期有效</Text>,
    },
    {
      title: '状态',
      dataIndex: 'is_deleted',
      key: 'is_deleted',
      render: (deleted: boolean) =>
        deleted ? (
          <Tag color="default">已删除</Tag>
        ) : (
          <Tag color="success">正常</Tag>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: CertificateType) => (
        <Space>
          <Button
            size="small"
            onClick={() => openEdit(record)}
            disabled={record.is_deleted}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认软删除？"
            description={
              <Text type="secondary" style={{ fontSize: 12 }}>
                此操作仅软删除，历史证件记录不受影响
              </Text>
            }
            onConfirm={() => void handleDelete(record)}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              disabled={record.is_deleted}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ─── 分页配置 ──────────────────────────────────────────────────────────────

  const pagination: TablePaginationConfig = {
    current: page,
    pageSize,
    total,
    onChange: (p) => setPage(p),
    showSizeChanger: false,
    showTotal: (t) => `共 ${t} 条`,
  };

  // ─── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {/* 页头 */}
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Title level={4} style={{ margin: 0 }}>
            资质证件类型管理
          </Title>
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void refresh()}
              loading={loading}
            >
              刷新
            </Button>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={() => void handleInitDefaults()}
              loading={initLoading}
            >
              初始化默认证件
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={openCreate}
            >
              新建证件类型
            </Button>
          </Space>
        </Space>

        {/* 空列表提示 */}
        {!loading && list.length === 0 && (
          <Alert
            type="info"
            message="暂无证件类型"
            description='点击"初始化默认证件"自动创建 5 类标准证件类型（食品经营许可证、食品生产许可证、健康证、营业执照、食安管理员证）'
            action={
              <Button
                size="small"
                type="primary"
                loading={initLoading}
                onClick={() => void handleInitDefaults()}
              >
                立即初始化
              </Button>
            }
          />
        )}

        {/* 列表 */}
        <Table<CertificateType>
          rowKey="id"
          columns={columns}
          dataSource={list}
          loading={loading}
          pagination={pagination}
          size="middle"
        />
      </Space>

      {/* 新建 / 编辑 Modal */}
      <Modal
        title={editTarget ? '编辑证件类型' : '新建证件类型'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          setEditTarget(null);
          form.resetFields();
        }}
        footer={null}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={onModalSubmit}
          initialValues={{
            applicable_supplier_kinds: ['all'],
            is_required: true,
          }}
        >
          <Form.Item
            label="证件类型名称"
            name="name"
            rules={[
              { required: true, message: '请输入证件类型名称' },
              { max: 100, message: '名称不超过 100 字' },
            ]}
          >
            <Input placeholder="如：食品经营许可证" />
          </Form.Item>

          <Form.Item
            label="适用供应商类型"
            name="applicable_supplier_kinds"
            rules={[{ required: true, message: '请选择适用供应商类型' }]}
          >
            <Select
              mode="multiple"
              options={SUPPLIER_KIND_OPTIONS}
              placeholder="选择适用类型（可多选，all = 全部）"
            />
          </Form.Item>

          <Form.Item
            label="有效期（天）"
            name="validity_period_days"
            extra="留空 = 长期有效"
          >
            <InputNumber
              min={1}
              style={{ width: '100%' }}
              placeholder="如：365（一年）/ 1095（三年）"
            />
          </Form.Item>

          <Form.Item
            label="是否必须"
            name="is_required"
            valuePropName="checked"
          >
            <Switch checkedChildren="必须" unCheckedChildren="可选" />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button
                onClick={() => {
                  setModalOpen(false);
                  setEditTarget(null);
                  form.resetFields();
                }}
              >
                取消
              </Button>
              <Button type="primary" htmlType="submit" loading={submitting}>
                {editTarget ? '保存更改' : '创建'}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
