/**
 * 商品扣秤标准库管理页 — 域D 供应链（PRD-02 / Tier 1 毛利底线）
 * 路由：/supply/ingredient-weight-standards
 *
 * 功能：
 *   1. 选择 ingredient，展示该 ingredient 的扣秤标准列表
 *   2. 新建扣秤标准（草稿态 — approved_by=NULL）
 *   3. 二级审批（不允许 self-approve）
 *   4. 软删
 *   5. 收货员手动触发净重计算（输入 gross_weight_kg）
 *
 * API:
 *   GET    /api/v1/supply/ingredients/{id}/weight-standards?only_active=
 *   POST   /api/v1/supply/ingredients/{id}/weight-standards         — 新建草稿
 *   POST   /api/v1/supply/weight-standards/{std_id}/approve         — 二级审批
 *   DELETE /api/v1/supply/weight-standards/{std_id}                 — 软删
 *
 * Ingredient 下拉 — Phase 2 沿用 SupplierCertificatesPage 同模式（size=100 客户端搜索）
 * server-side search 见 #626 follow-up（500+ SKU 客户必须）
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../api/client';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface Ingredient {
  id: string;
  name: string;
  category?: string;
}

interface WeightStandard {
  id: string;
  tenant_id: string;
  ingredient_id: string;
  deduct_type: string;
  deduct_method: string;
  deduct_value: string;
  tolerance_pct: string;
  effective_from: string;
  effective_to: string | null;
  approved_by: string | null;
  approved_at: string | null;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

const DEDUCT_TYPE_OPTIONS = [
  { label: '冰块', value: 'ice' },
  { label: '塑料袋/箱', value: 'packaging' },
  { label: '菜叶损耗', value: 'leaves' },
  { label: '茎梗损耗', value: 'stem' },
  { label: '其他', value: 'other' },
];

const DEDUCT_METHOD_OPTIONS = [
  { label: '按毛重百分比', value: 'percentage' },
  { label: '按固定 kg', value: 'fixed_kg' },
];

function deductTypeLabel(v: string): string {
  return DEDUCT_TYPE_OPTIONS.find((o) => o.value === v)?.label ?? v;
}

function deductMethodLabel(v: string): string {
  return DEDUCT_METHOD_OPTIONS.find((o) => o.value === v)?.label ?? v;
}

function statusTag(std: WeightStandard) {
  if (std.is_deleted) return <Tag color="default">已删除</Tag>;
  if (std.approved_by) return <Tag color="success">已审批</Tag>;
  return <Tag color="warning">待审批</Tag>;
}

// ─── 新建 Modal ──────────────────────────────────────────────────────────────

interface CreateModalProps {
  ingredientId: string;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function CreateStandardModal({ ingredientId, open, onClose, onSuccess }: CreateModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [method, setMethod] = useState<'percentage' | 'fixed_kg'>('percentage');

  const handleSubmit = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    try {
      const effectiveFrom = (values['effective_from'] as dayjs.Dayjs).format('YYYY-MM-DD');
      const effectiveToVal = values['effective_to'] as dayjs.Dayjs | undefined;
      const body: Record<string, unknown> = {
        deduct_type: values['deduct_type'],
        deduct_method: values['deduct_method'],
        deduct_value: String(values['deduct_value']),
        tolerance_pct: String(values['tolerance_pct'] ?? 2.0),
        effective_from: effectiveFrom,
        effective_to: effectiveToVal ? effectiveToVal.format('YYYY-MM-DD') : null,
        notes: (values['notes'] as string | undefined) ?? null,
      };

      await txFetchData(`/api/v1/supply/ingredients/${ingredientId}/weight-standards`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      message.success('扣秤标准已创建（草稿态，需独立审批人审批生效）');
      form.resetFields();
      onSuccess();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '创建失败';
      message.error(`创建失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="新建扣秤标准（草稿）"
      open={open}
      onCancel={() => { form.resetFields(); onClose(); }}
      onOk={handleSubmit}
      okText="创建草稿"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={560}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="二级审批必须"
        description="创建为草稿态，必须由非创建人独立审批后才生效阻断收货扣秤计算。"
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          deduct_type: 'ice',
          deduct_method: 'percentage',
          tolerance_pct: 2.0,
          effective_from: dayjs(),
        }}
      >
        <Form.Item name="deduct_type" label="扣秤类目" rules={[{ required: true }]}>
          <Select options={DEDUCT_TYPE_OPTIONS} />
        </Form.Item>
        <Form.Item name="deduct_method" label="扣秤方法" rules={[{ required: true }]}>
          <Select
            options={DEDUCT_METHOD_OPTIONS}
            onChange={(v) => setMethod(v as 'percentage' | 'fixed_kg')}
          />
        </Form.Item>
        <Form.Item
          name="deduct_value"
          label={method === 'percentage' ? '扣秤百分比 (%)' : '扣秤固定值 (kg)'}
          rules={[{ required: true, message: '请输入扣秤值' }]}
        >
          <InputNumber
            min={0}
            max={method === 'percentage' ? 100 : 9999}
            step={method === 'percentage' ? 0.5 : 0.1}
            style={{ width: '100%' }}
            addonAfter={method === 'percentage' ? '%' : 'kg'}
          />
        </Form.Item>
        <Form.Item
          name="tolerance_pct"
          label="容忍偏差 (%)"
          tooltip="实测扣秤与标准差超此值时触发 weight_deduction_anomaly 事件"
          rules={[{ required: true }]}
        >
          <InputNumber min={0} max={100} step={0.5} style={{ width: '100%' }} addonAfter="%" />
        </Form.Item>
        <Form.Item name="effective_from" label="生效日期" rules={[{ required: true }]}>
          <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
        </Form.Item>
        <Form.Item
          name="effective_to"
          label="失效日期（可选）"
          tooltip="留空表示永久生效"
          dependencies={['effective_from']}
          rules={[
            ({ getFieldValue }) => ({
              validator(_, value: dayjs.Dayjs | undefined) {
                const from = getFieldValue('effective_from') as dayjs.Dayjs | undefined;
                if (!value || !from) return Promise.resolve();
                if (value.isAfter(from, 'day')) return Promise.resolve();
                return Promise.reject(new Error('失效日期必须晚于生效日期'));
              },
            }),
          ]}
        >
          <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <Input.TextArea rows={2} placeholder="如：徐记海鲜鲜活类 SKU 通用扣秤" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 审批 Modal ──────────────────────────────────────────────────────────────

interface ApproveModalProps {
  std: WeightStandard | null;
  currentUserId: string;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function ApproveStandardModal({
  std,
  currentUserId,
  open,
  onClose,
  onSuccess,
}: ApproveModalProps) {
  const [submitting, setSubmitting] = useState(false);
  const isSelfApprove = !!std && std.created_by === currentUserId;

  const handleApprove = async () => {
    if (!std) return;
    if (isSelfApprove) {
      message.error('不能审批自己创建的扣秤标准（必须独立审批人签字）');
      return;
    }
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/supply/weight-standards/${std.id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ approver_id: currentUserId }),
      });
      message.success('审批通过，扣秤标准已生效');
      onSuccess();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '审批失败';
      message.error(`审批失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="二级审批扣秤标准"
      open={open}
      onCancel={onClose}
      onOk={handleApprove}
      okText="审批通过"
      okButtonProps={{ disabled: isSelfApprove }}
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={480}
    >
      {std && (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {isSelfApprove && (
            <Alert
              type="error"
              showIcon
              message="不能审批自己创建的扣秤标准"
              description={`您 (${currentUserId}) 是创建人，必须由其他人作为审批人独立签字。`}
            />
          )}
          <Text>
            <strong>扣秤类目:</strong> {deductTypeLabel(std.deduct_type)}
          </Text>
          <Text>
            <strong>扣秤方法:</strong> {deductMethodLabel(std.deduct_method)} {std.deduct_value}
            {std.deduct_method === 'percentage' ? '%' : ' kg'}
          </Text>
          <Text>
            <strong>容忍偏差:</strong> {std.tolerance_pct}%
          </Text>
          <Text>
            <strong>生效:</strong> {std.effective_from} ～ {std.effective_to ?? '永久'}
          </Text>
          <Text type="secondary">
            <strong>创建人:</strong> {std.created_by}
          </Text>
        </Space>
      )}
    </Modal>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function IngredientWeightStandardsPage() {
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [ingredientLoading, setIngredientLoading] = useState(false);
  const [selectedIngredientId, setSelectedIngredientId] = useState<string | null>(null);

  const [standards, setStandards] = useState<WeightStandard[]>([]);
  const [loading, setLoading] = useState(false);
  const [onlyActive, setOnlyActive] = useState<'all' | 'active'>('all');
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [approveTarget, setApproveTarget] = useState<WeightStandard | null>(null);

  // 当前操作员 ID — 实际场景从认证 SDK 取，此处简化用 header 注入
  const [currentUserId] = useState<string>(() => {
    return localStorage.getItem('tx_user_id') ?? 'admin';
  });

  const loadIngredients = useCallback(async () => {
    setIngredientLoading(true);
    try {
      const data = await txFetchData<{ items: Ingredient[]; total: number }>(
        '/api/v1/supply/ingredients?page=1&size=100',
      );
      const items = data.items ?? [];
      setIngredients(items);
      if (items.length > 0 && !selectedIngredientId) {
        setSelectedIngredientId(items[0].id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrMsg(`加载食材列表失败: ${msg}`);
    } finally {
      setIngredientLoading(false);
    }
  }, [selectedIngredientId]);

  useEffect(() => {
    void loadIngredients();
  }, []);

  const loadStandards = useCallback(
    async (ingredientId: string, mode: 'all' | 'active') => {
      setLoading(true);
      setErrMsg(null);
      try {
        const params = new URLSearchParams({
          only_active: mode === 'active' ? 'true' : 'false',
        });
        const data = await txFetchData<{ items: WeightStandard[]; total: number }>(
          `/api/v1/supply/ingredients/${ingredientId}/weight-standards?${params.toString()}`,
        );
        setStandards(data.items ?? []);
      } catch (err) {
        const errObj = err as { code?: string; message?: string };
        const msg = errObj.message ?? String(err);
        setErrMsg(`加载扣秤标准失败: ${msg}`);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (selectedIngredientId) {
      void loadStandards(selectedIngredientId, onlyActive);
    }
  }, [selectedIngredientId, onlyActive, loadStandards]);

  const refresh = useCallback(() => {
    if (selectedIngredientId) {
      void loadStandards(selectedIngredientId, onlyActive);
    }
  }, [selectedIngredientId, onlyActive, loadStandards]);

  const handleDelete = useCallback(
    (std: WeightStandard) => {
      Modal.confirm({
        title: '确认删除扣秤标准',
        icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
        content: `软删后「${deductTypeLabel(std.deduct_type)} ${std.deduct_value}${
          std.deduct_method === 'percentage' ? '%' : 'kg'
        }」不再参与收货扣秤计算。确认删除？`,
        okText: '确认删除',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          try {
            await txFetchData(`/api/v1/supply/weight-standards/${std.id}`, { method: 'DELETE' });
            message.success('扣秤标准已删除');
            refresh();
          } catch (err) {
            const msg = err instanceof Error ? err.message : '删除失败';
            message.error(`删除失败: ${msg}`);
          }
        },
      });
    },
    [refresh],
  );

  const columns = [
    {
      title: '扣秤类目',
      dataIndex: 'deduct_type',
      key: 'deduct_type',
      width: 110,
      render: (v: string) => <Text strong>{deductTypeLabel(v)}</Text>,
    },
    {
      title: '扣秤值',
      key: 'deduct_value',
      width: 160,
      render: (_: unknown, r: WeightStandard) => (
        <Text>
          {r.deduct_value}
          {r.deduct_method === 'percentage' ? '%' : ' kg'}{' '}
          <Text type="secondary" style={{ fontSize: 12 }}>
            ({deductMethodLabel(r.deduct_method)})
          </Text>
        </Text>
      ),
    },
    {
      title: '容忍偏差',
      dataIndex: 'tolerance_pct',
      key: 'tolerance_pct',
      width: 90,
      render: (v: string) => <Text>±{v}%</Text>,
    },
    {
      title: '生效窗口',
      key: 'effective',
      width: 200,
      render: (_: unknown, r: WeightStandard) => (
        <Space direction="vertical" size={2}>
          <Text>{r.effective_from} ～ {r.effective_to ?? '永久'}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 110,
      render: (_: unknown, r: WeightStandard) => (
        <Space direction="vertical" size={0}>
          {statusTag(r)}
          {r.approved_by && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {r.approved_at ? dayjs(r.approved_at).format('YYYY-MM-DD') : ''}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '创建人',
      dataIndex: 'created_by',
      key: 'created_by',
      width: 130,
      ellipsis: true,
      render: (v: string) => <Text type="secondary">{v}</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, r: WeightStandard) => (
        <Space>
          {!r.approved_by && !r.is_deleted && (
            <a style={{ color: '#52c41a' }} onClick={() => setApproveTarget(r)}>
              <CheckCircleOutlined /> 审批
            </a>
          )}
          {!r.is_deleted && (
            <a style={{ color: '#ff4d4f' }} onClick={() => handleDelete(r)}>
              删除
            </a>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>
          商品扣秤标准库
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!selectedIngredientId}
            onClick={() => setCreateOpen(true)}
          >
            新建扣秤标准
          </Button>
        </Space>
      </Space>

      {errMsg && (
        <Alert
          type="error"
          showIcon
          message="加载失败"
          description={errMsg}
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setErrMsg(null)}
        />
      )}

      <Card style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <Space>
            <Text type="secondary">食材：</Text>
            <Select
              style={{ width: 240 }}
              placeholder="请选择食材"
              loading={ingredientLoading}
              value={selectedIngredientId}
              onChange={(v) => setSelectedIngredientId(v)}
              options={ingredients.map((i) => ({ label: i.name, value: i.id }))}
              showSearch
              optionFilterProp="label"
            />
          </Space>
          <Space>
            <Text type="secondary">范围：</Text>
            <Radio.Group
              value={onlyActive}
              onChange={(e) => setOnlyActive(e.target.value as 'all' | 'active')}
              buttonStyle="solid"
              size="small"
            >
              <Radio.Button value="all">全部（含草稿/已删）</Radio.Button>
              <Radio.Button value="active">仅生效中</Radio.Button>
            </Radio.Group>
          </Space>
          <Space>
            <Text type="secondary">当前操作员：</Text>
            <Text code>{currentUserId}</Text>
          </Space>
        </Space>
      </Card>

      <Card>
        <Table<WeightStandard>
          rowKey="id"
          dataSource={standards}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{ emptyText: '该食材暂无扣秤标准 — 点击「新建扣秤标准」录入' }}
        />
      </Card>

      {selectedIngredientId && (
        <CreateStandardModal
          ingredientId={selectedIngredientId}
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onSuccess={refresh}
        />
      )}
      <ApproveStandardModal
        std={approveTarget}
        currentUserId={currentUserId}
        open={!!approveTarget}
        onClose={() => setApproveTarget(null)}
        onSuccess={refresh}
      />
    </div>
  );
}

export default IngredientWeightStandardsPage;
