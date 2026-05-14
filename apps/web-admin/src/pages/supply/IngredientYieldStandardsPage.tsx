/**
 * 商品出料率标准库管理页 — 域D 供应链（PRD-06 / Tier 1 毛利底线）
 * 路由：/supply/ingredient-yield-standards
 *
 * 功能：
 *   1. 选择 ingredient，展示该 ingredient 的出料率标准列表
 *   2. 新建出料率标准（草稿态 — approved_by=NULL）
 *   3. 二级审批（不允许 self-approve）
 *   4. 软删
 *   5. BOM 反算购买量（输入净菜量 + 季节 → 输出毛菜采购量）
 *
 * API:
 *   GET    /api/v1/supply/ingredients/{id}/yield-standards?only_active=
 *   POST   /api/v1/supply/ingredients/{id}/yield-standards         — 新建草稿
 *   POST   /api/v1/supply/yield-standards/{std_id}/approve         — 二级审批
 *   DELETE /api/v1/supply/yield-standards/{std_id}                 — 软删
 *   POST   /api/v1/supply/yield-standards/calculate-purchase-qty   — BOM 反算
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
  Select,
  Space,
  Radio,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CalculatorOutlined,
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

interface YieldStandard {
  id: string;
  tenant_id: string;
  ingredient_id: string;
  process_id: string | null;
  yield_rate: string;
  season: string;
  effective_from: string;
  effective_to: string | null;
  tolerance_pct: string;
  approved_by: string | null;
  approved_at: string | null;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

const SEASON_OPTIONS = [
  { label: '春季', value: 'spring' },
  { label: '夏季', value: 'summer' },
  { label: '秋季', value: 'autumn' },
  { label: '冬季', value: 'winter' },
  { label: '通用（无季节差异）', value: 'all' },
];

function seasonLabel(v: string): string {
  return SEASON_OPTIONS.find((o) => o.value === v)?.label ?? v;
}

function statusTag(std: YieldStandard) {
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
        yield_rate: String(values['yield_rate']),
        season: values['season'],
        tolerance_pct: String(values['tolerance_pct'] ?? 5.0),
        effective_from: effectiveFrom,
        effective_to: effectiveToVal ? effectiveToVal.format('YYYY-MM-DD') : null,
        notes: (values['notes'] as string | undefined) ?? null,
      };

      await txFetchData(`/api/v1/supply/ingredients/${ingredientId}/yield-standards`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      message.success('出料率标准已创建（草稿态，需独立审批人审批生效）');
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
      title="新建出料率标准（草稿）"
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
        description="创建为草稿态，必须由非创建人独立审批后才参与 BOM 反算购买量。"
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          season: 'all',
          yield_rate: 0.6,
          tolerance_pct: 5.0,
          effective_from: dayjs(),
        }}
      >
        <Form.Item
          name="yield_rate"
          label="出料率"
          tooltip="净菜重量 / 毛菜重量，范围 (0, 1]，如 0.6 表示 100 斤毛菜出 60 斤净菜"
          rules={[{ required: true, message: '请输入出料率' }]}
        >
          <InputNumber
            min={0.01}
            max={1}
            step={0.01}
            style={{ width: '100%' }}
            addonAfter="(0, 1]"
          />
        </Form.Item>
        <Form.Item name="season" label="季节" rules={[{ required: true }]}>
          <Select options={SEASON_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="tolerance_pct"
          label="容忍偏差 (%)"
          tooltip="实测出料率与标准差超此值时触发 yield_anomaly 事件"
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
          <Input.TextArea rows={2} placeholder="如：徐记海鲜春菠菜出料率（毛 100 斤出净 65 斤）" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 审批 Modal ──────────────────────────────────────────────────────────────

interface ApproveModalProps {
  std: YieldStandard | null;
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
      message.error('不能审批自己创建的出料率标准（必须独立审批人签字）');
      return;
    }
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/supply/yield-standards/${std.id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ approver_id: currentUserId }),
      });
      message.success('审批通过，出料率标准已生效');
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
      title="二级审批出料率标准"
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
              message="不能审批自己创建的出料率标准"
              description={`您 (${currentUserId}) 是创建人，必须由其他人作为审批人独立签字。`}
            />
          )}
          <Text>
            <strong>出料率:</strong> {std.yield_rate}（{(Number(std.yield_rate) * 100).toFixed(1)}%）
          </Text>
          <Text>
            <strong>季节:</strong> {seasonLabel(std.season)}
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

// ─── 反算购买量 Modal ────────────────────────────────────────────────────────

interface CalcModalProps {
  ingredientId: string;
  open: boolean;
  onClose: () => void;
}

interface CalcResult {
  ingredient_id: string;
  required_net_qty_kg: string;
  purchase_qty_kg: string;
  standard_id: string | null;
  yield_rate: string | null;
  season_matched: string | null;
  anomaly_detected: boolean;
}

function CalcPurchaseQtyModal({ ingredientId, open, onClose }: CalcModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CalcResult | null>(null);

  const handleCalc = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    setResult(null);
    try {
      const body = {
        ingredient_id: ingredientId,
        required_net_qty_kg: String(values['required_net_qty_kg']),
        season: values['season'] ?? 'all',
      };
      const data = await txFetchData<CalcResult>(
        '/api/v1/supply/yield-standards/calculate-purchase-qty',
        { method: 'POST', body: JSON.stringify(body) },
      );
      setResult(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '反算失败';
      message.error(`反算失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="BOM 反算购买量"
      open={open}
      onCancel={() => { form.resetFields(); setResult(null); onClose(); }}
      onOk={handleCalc}
      okText="反算"
      cancelText="关闭"
      confirmLoading={submitting}
      destroyOnClose
      width={520}
    >
      <Form form={form} layout="vertical" initialValues={{ season: 'all' }}>
        <Form.Item
          name="required_net_qty_kg"
          label="所需净菜量 (kg)"
          rules={[{ required: true, message: '请输入净菜量' }]}
        >
          <InputNumber min={0.01} step={0.1} style={{ width: '100%' }} addonAfter="kg" />
        </Form.Item>
        <Form.Item name="season" label="季节" rules={[{ required: true }]}>
          <Select options={SEASON_OPTIONS} />
        </Form.Item>
      </Form>
      {result && (
        <Alert
          type={result.standard_id ? 'success' : 'warning'}
          showIcon
          style={{ marginTop: 16 }}
          message={
            result.standard_id
              ? `应采购毛菜量：${result.purchase_qty_kg} kg`
              : `无出料率标准（fallback 原值 ${result.purchase_qty_kg} kg）`
          }
          description={
            <Space direction="vertical" size={2}>
              <Text>所需净菜：{result.required_net_qty_kg} kg</Text>
              {result.yield_rate && (
                <Text>
                  应用出料率：{result.yield_rate}（季节：{seasonLabel(result.season_matched ?? 'all')}）
                </Text>
              )}
              {!result.standard_id && (
                <Text type="warning">无已审批 active 标准 — 请录入并审批后再反算</Text>
              )}
            </Space>
          }
        />
      )}
    </Modal>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function IngredientYieldStandardsPage() {
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [ingredientLoading, setIngredientLoading] = useState(false);
  const [selectedIngredientId, setSelectedIngredientId] = useState<string | null>(null);

  const [standards, setStandards] = useState<YieldStandard[]>([]);
  const [loading, setLoading] = useState(false);
  const [onlyActive, setOnlyActive] = useState<'all' | 'active'>('all');
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [calcOpen, setCalcOpen] = useState(false);
  const [approveTarget, setApproveTarget] = useState<YieldStandard | null>(null);

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
        const data = await txFetchData<{ items: YieldStandard[]; total: number }>(
          `/api/v1/supply/ingredients/${ingredientId}/yield-standards?${params.toString()}`,
        );
        setStandards(data.items ?? []);
      } catch (err) {
        const errObj = err as { code?: string; message?: string };
        const msg = errObj.message ?? String(err);
        setErrMsg(`加载出料率标准失败: ${msg}`);
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
    (std: YieldStandard) => {
      Modal.confirm({
        title: '确认删除出料率标准',
        icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
        content: `软删后「${seasonLabel(std.season)} 出料率 ${std.yield_rate}」不再参与 BOM 反算。确认删除？`,
        okText: '确认删除',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          try {
            await txFetchData(`/api/v1/supply/yield-standards/${std.id}`, { method: 'DELETE' });
            message.success('出料率标准已删除');
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
      title: '出料率',
      dataIndex: 'yield_rate',
      key: 'yield_rate',
      width: 130,
      render: (v: string) => (
        <Text strong>
          {v} <Text type="secondary" style={{ fontSize: 12 }}>({(Number(v) * 100).toFixed(1)}%)</Text>
        </Text>
      ),
    },
    {
      title: '季节',
      dataIndex: 'season',
      key: 'season',
      width: 130,
      render: (v: string) => <Tag color={v === 'all' ? 'default' : 'blue'}>{seasonLabel(v)}</Tag>,
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
      render: (_: unknown, r: YieldStandard) => (
        <Space direction="vertical" size={2}>
          <Text>{r.effective_from} ～ {r.effective_to ?? '永久'}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 110,
      render: (_: unknown, r: YieldStandard) => (
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
      render: (_: unknown, r: YieldStandard) => (
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
          商品出料率标准库
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
          <Button
            icon={<CalculatorOutlined />}
            disabled={!selectedIngredientId}
            onClick={() => setCalcOpen(true)}
          >
            BOM 反算购买量
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!selectedIngredientId}
            onClick={() => setCreateOpen(true)}
          >
            新建出料率标准
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
        <Table<YieldStandard>
          rowKey="id"
          dataSource={standards}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{ emptyText: '该食材暂无出料率标准 — 点击「新建出料率标准」录入' }}
        />
      </Card>

      {selectedIngredientId && (
        <>
          <CreateStandardModal
            ingredientId={selectedIngredientId}
            open={createOpen}
            onClose={() => setCreateOpen(false)}
            onSuccess={refresh}
          />
          <CalcPurchaseQtyModal
            ingredientId={selectedIngredientId}
            open={calcOpen}
            onClose={() => setCalcOpen(false)}
          />
        </>
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

export default IngredientYieldStandardsPage;
