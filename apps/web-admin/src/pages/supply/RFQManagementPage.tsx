/**
 * 询价单管理页 — 域D 供应链（PRD-04 sub-C / Phase 2 W9-W10 / T2 normal）
 * 路由：/supply/rfqs
 *
 * 功能：
 *   1. RFQ 列表（按状态过滤 + deadline 倒序）
 *   2. 创建草稿 RFQ（含 items + invitees + deadline）
 *   3. 状态机操作：publish / close / cancel
 *   4. 比价表 + AI 推荐（最低价 heuristic）
 *   5. 二级审批 award（Tier 1 资金路径前置）
 *
 * 调用接口（PRD-04 sub-C）：
 *   POST   /api/v1/supply/rfqs                    创建草稿
 *   GET    /api/v1/supply/rfqs?status=&limit=     列表
 *   GET    /api/v1/supply/rfqs/{id}               详情
 *   GET    /api/v1/supply/rfqs/{id}/comparison    比价表 + AI 推荐
 *   POST   /api/v1/supply/rfqs/{id}/publish       draft → published
 *   POST   /api/v1/supply/rfqs/{id}/close         quoting → comparing
 *   POST   /api/v1/supply/rfqs/{id}/cancel        非终态 → cancelled (reason 必填)
 *   POST   /api/v1/supply/rfqs/{id}/award         Tier 1 中标 + 二级审批 (sub-B)
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
  StopOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData, getTokenPayload } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

type RFQStatus = 'draft' | 'published' | 'quoting' | 'comparing' | 'awarded' | 'cancelled';

interface RFQ {
  id: string;
  tenant_id: string;
  rfq_number: string | null;
  initiator_id: string;
  deadline: string;
  status: RFQStatus;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

interface RFQItem {
  id: string;
  ingredient_id: string;
  qty_required: string;
  qty_unit: string | null;
  spec_notes: string | null;
}

interface RFQQuote {
  quote_id: string;
  supplier_id: string;
  ingredient_id: string;
  unit_price_fen: number;
  qty_offered: string | null;
  valid_until: string | null;
  notes: string | null;
  submitted_at: string;
}

interface RFQComparisonItem extends RFQItem {
  quotes: RFQQuote[];
  ai_recommended_quote_id: string | null;
  ai_recommendation_reason: string;
}

interface RFQComparison {
  rfq: RFQ;
  items: RFQComparisonItem[];
}

interface Ingredient {
  id: string;
  name: string;
  category?: string;
}

interface Supplier {
  id: string;
  name: string;
  category?: string;
}

const STATUS_OPTIONS: { value: RFQStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'quoting', label: '收报价中' },
  { value: 'comparing', label: '比价审核' },
  { value: 'awarded', label: '已中标' },
  { value: 'cancelled', label: '已取消' },
];

function statusTag(status: RFQStatus) {
  const cfg: Record<RFQStatus, { color: string; text: string }> = {
    draft: { color: 'default', text: '草稿' },
    published: { color: 'processing', text: '已发布' },
    quoting: { color: 'cyan', text: '收报价中' },
    comparing: { color: 'gold', text: '比价审核' },
    awarded: { color: 'success', text: '已中标' },
    cancelled: { color: 'error', text: '已取消' },
  };
  const c = cfg[status] ?? { color: 'default', text: status };
  return <Tag color={c.color}>{c.text}</Tag>;
}

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

// ─── 创建 Modal ──────────────────────────────────────────────────────────────

interface CreateModalProps {
  open: boolean;
  ingredients: Ingredient[];
  suppliers: Supplier[];
  onClose: () => void;
  onSuccess: () => void;
}

function CreateRFQModal({ open, ingredients, suppliers, onClose, onSuccess }: CreateModalProps) {
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
      const deadline = (values['deadline'] as dayjs.Dayjs).toISOString();
      const items = (values['items'] as Array<{
        ingredient_id: string;
        qty_required: number;
        qty_unit?: string;
        spec_notes?: string;
      }>).map((it) => ({
        ingredient_id: it.ingredient_id,
        qty_required: String(it.qty_required),
        qty_unit: it.qty_unit ?? null,
        spec_notes: it.spec_notes ?? null,
      }));
      const body = {
        deadline,
        notes: (values['notes'] as string | undefined) ?? null,
        items,
        invited_supplier_ids: values['invited_supplier_ids'] as string[],
      };
      await txFetchData('/api/v1/supply/rfqs', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      message.success('询价单已创建（草稿态，下一步：点"发布"邀请供应商）');
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
      title="新建询价单（草稿）"
      open={open}
      onCancel={() => { form.resetFields(); onClose(); }}
      onOk={handleSubmit}
      okText="创建草稿"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={760}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="询价流程"
        description="创建为草稿态 → 点"发布"通知被邀供应商 → 供应商门户提交报价 → 截止后点"收尾比价" → 比价表选定供应商 → 二级审批中标。"
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          deadline: dayjs().add(7, 'day'),
          items: [{}],
          invited_supplier_ids: [],
        }}
      >
        <Form.Item
          name="deadline"
          label="截止时间"
          tooltip="供应商必须在此时间前完成报价；可手动提前 close"
          rules={[{ required: true, message: '请选择截止时间' }]}
        >
          <DatePicker showTime style={{ width: '100%' }} format="YYYY-MM-DD HH:mm" />
        </Form.Item>

        <Form.Item
          name="invited_supplier_ids"
          label="邀请供应商"
          tooltip="仅被邀供应商可在报价门户看到本询价单并提交报价"
          rules={[{ required: true, message: '请至少选择 1 家供应商' }]}
        >
          <Select
            mode="multiple"
            placeholder="选择供应商"
            options={suppliers.map((s) => ({ value: s.id, label: s.name }))}
            showSearch
            optionFilterProp="label"
          />
        </Form.Item>

        <Form.Item label="询价明细（SKU 清单）" required>
          <Form.List
            name="items"
            rules={[{
              validator: async (_, items: unknown[]) => {
                if (!items || items.length < 1) {
                  return Promise.reject(new Error('至少添加 1 个 SKU 行'));
                }
              },
            }]}
          >
            {(fields, { add, remove }, { errors }) => (
              <>
                {fields.map(({ key, name }) => (
                  <Space key={key} align="start" style={{ display: 'flex', marginBottom: 8 }}>
                    <Form.Item
                      name={[name, 'ingredient_id']}
                      rules={[{ required: true, message: '选择食材' }]}
                      style={{ minWidth: 220, marginBottom: 0 }}
                    >
                      <Select
                        placeholder="食材"
                        options={ingredients.map((i) => ({ value: i.id, label: i.name }))}
                        showSearch
                        optionFilterProp="label"
                      />
                    </Form.Item>
                    <Form.Item
                      name={[name, 'qty_required']}
                      rules={[{ required: true, message: '数量 > 0' }, { type: 'number', min: 0.01 }]}
                      style={{ marginBottom: 0 }}
                    >
                      <InputNumber placeholder="数量" min={0.01} step={1} style={{ width: 120 }} />
                    </Form.Item>
                    <Form.Item name={[name, 'qty_unit']} style={{ marginBottom: 0 }}>
                      <Input placeholder="单位 (如 kg)" style={{ width: 100 }} maxLength={16} />
                    </Form.Item>
                    <Form.Item name={[name, 'spec_notes']} style={{ marginBottom: 0, flex: 1 }}>
                      <Input placeholder="规格备注（可选）" />
                    </Form.Item>
                    <Button type="text" danger onClick={() => remove(name)}>
                      删除
                    </Button>
                  </Space>
                ))}
                <Button type="dashed" onClick={() => add({})} icon={<PlusOutlined />} block>
                  添加 SKU 行
                </Button>
                <Form.ErrorList errors={errors} />
              </>
            )}
          </Form.List>
        </Form.Item>

        <Form.Item name="notes" label="备注">
          <Input.TextArea rows={2} placeholder="如：徐记海鲜春节备货龙虾询价" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 取消 Modal ──────────────────────────────────────────────────────────────

function CancelRFQModal({
  rfq,
  open,
  onClose,
  onSuccess,
}: {
  rfq: RFQ | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) setReason('');
  }, [open]);

  const handleSubmit = async () => {
    if (!rfq) return;
    if (!reason.trim()) {
      message.error('取消原因必填（合规审计）');
      return;
    }
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/supply/rfqs/${rfq.id}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason: reason.trim() }),
      });
      message.success('询价单已取消');
      onSuccess();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '取消失败';
      message.error(`取消失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="取消询价单"
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      okText="确认取消"
      okButtonProps={{ danger: true }}
      cancelText="返回"
      confirmLoading={submitting}
      destroyOnClose
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="取消后不可恢复"
        description="询价单进入终态。取消原因将记入合规审计日志。"
      />
      <Form layout="vertical">
        <Form.Item label="取消原因" required>
          <Input.TextArea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            placeholder="如：SKU 录错 / 业务方向调整 / 截止后无供应商响应"
            showCount
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── Award Drawer (比价表 + AI 推荐 + 二级审批) ──────────────────────────────

function AwardSection({
  rfq,
  comparison,
  currentUserId,
  onAwardSuccess,
  selectedQuoteId,
}: {
  rfq: RFQ;
  comparison: RFQComparison | null;
  currentUserId: string;
  onAwardSuccess: () => void;
  /** §19 round-1 P0-1: selectedQuoteId 由父 RFQDetailDrawer 管理 —
   *  以前 AwardSection 内部独立 state 与 Drawer Table rowSelection 双 state 断路。
   */
  selectedQuoteId: string | null;
}) {
  const [aiFollowed, setAiFollowed] = useState<boolean | null>(null);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const isSelfApprove = rfq.created_by === currentUserId;
  const canAward = rfq.status === 'comparing' || rfq.status === 'quoting';
  const aiRecommendedIds = new Set(
    comparison?.items.map((it) => it.ai_recommended_quote_id).filter(Boolean) ?? [],
  );

  const handleAward = async () => {
    if (!selectedQuoteId) {
      message.error('请先选定一条报价');
      return;
    }
    if (!reason.trim()) {
      message.error('中标理由必填（合规审计）');
      return;
    }
    if (aiFollowed === null) {
      message.error('请标注是否采纳 AI 推荐（RLHF 训练信号）');
      return;
    }
    if (isSelfApprove) {
      message.error('不能审批自己创建的询价单（二级审批必须独立签字）');
      return;
    }
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/supply/rfqs/${rfq.id}/award`, {
        method: 'POST',
        body: JSON.stringify({
          selected_quote_id: selectedQuoteId,
          reason: reason.trim(),
          ai_recommendation_followed: aiFollowed,
        }),
      });
      message.success('中标确认，询价单已进入终态');
      onAwardSuccess();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '中标失败';
      message.error(`中标失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (!canAward) {
    return (
      <Alert
        type="info"
        message={`当前状态 "${rfq.status}" — 仅 quoting / comparing 可执行中标`}
        showIcon
      />
    );
  }

  return (
    <Card title={<><TrophyOutlined /> 中标确认（二级审批）</>} size="small">
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {isSelfApprove && (
          <Alert
            type="error"
            showIcon
            message="二级审批冲突"
            description={`您 (${currentUserId}) 是询价单创建人，不能审批自己创建的单。必须由其他人作为审批人签字。`}
          />
        )}
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          在下方比价表中点击一行 quote 选定中标对象。被 AI 推荐的报价已用 🏆 标记。
        </Paragraph>
        <div>
          <Text strong>已选定 quote_id:</Text>{' '}
          {selectedQuoteId ? (
            <>
              <code>{selectedQuoteId.slice(0, 8)}…</code>
              {aiRecommendedIds.has(selectedQuoteId) && (
                <Tag color="gold" style={{ marginLeft: 8 }}>🏆 AI 推荐</Tag>
              )}
            </>
          ) : (
            <Text type="warning">尚未选定</Text>
          )}
        </div>
        <Form layout="vertical">
          <Form.Item label="中标理由（合规审计）" required>
            <Input.TextArea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
              placeholder="如：A 家单价最低 + 历史交付准点率 95% + 配送时间窗匹配"
              showCount
            />
          </Form.Item>
          <Form.Item
            label="是否采纳 AI 推荐？"
            tooltip="RLHF 训练信号 — 用户与 AI 推荐的偏差是供应链 AI 自动议价的核心数据资产"
            required
          >
            <Radio.Group
              value={aiFollowed}
              onChange={(e) => setAiFollowed(e.target.value)}
            >
              <Radio value={true}>✓ 是（采纳推荐）</Radio>
              <Radio value={false}>✗ 否（选了其他）</Radio>
            </Radio.Group>
          </Form.Item>
        </Form>
        <Button
          type="primary"
          icon={<TrophyOutlined />}
          onClick={handleAward}
          loading={submitting}
          disabled={isSelfApprove || !selectedQuoteId}
          block
        >
          确认中标（不可回退）
        </Button>
      </Space>
    </Card>
  );
}

interface DetailDrawerProps {
  rfq: RFQ | null;
  open: boolean;
  currentUserId: string;
  ingredientsById: Map<string, Ingredient>;
  suppliersById: Map<string, Supplier>;
  onClose: () => void;
  onActionSuccess: () => void;
}

function RFQDetailDrawer({
  rfq,
  open,
  currentUserId,
  ingredientsById,
  suppliersById,
  onClose,
  onActionSuccess,
}: DetailDrawerProps) {
  const [comparison, setComparison] = useState<RFQComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedQuoteId, setSelectedQuoteId] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);

  const fetchComparison = useCallback(async () => {
    if (!rfq) return;
    setLoading(true);
    try {
      const data = await txFetchData<RFQComparison>(
        `/api/v1/supply/rfqs/${rfq.id}/comparison`,
      );
      setComparison(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`加载比价表失败：${msg}`);
    } finally {
      setLoading(false);
    }
  }, [rfq]);

  useEffect(() => {
    if (open && rfq) {
      void fetchComparison();
      setSelectedQuoteId(null);
    }
  }, [open, rfq, fetchComparison]);

  const handlePublish = async () => {
    if (!rfq) return;
    try {
      await txFetchData(`/api/v1/supply/rfqs/${rfq.id}/publish`, { method: 'POST' });
      message.success('询价单已发布，被邀供应商已可看到');
      onActionSuccess();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '发布失败';
      message.error(`发布失败：${msg}`);
    }
  };

  const handleClose = async () => {
    if (!rfq) return;
    try {
      await txFetchData(`/api/v1/supply/rfqs/${rfq.id}/close`, { method: 'POST' });
      message.success('已截止收报价，进入比价审核');
      onActionSuccess();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '截止失败';
      message.error(`截止失败：${msg}`);
    }
  };

  if (!rfq) return null;

  return (
    <Drawer
      title={
        <Space>
          <span>询价单详情</span>
          {statusTag(rfq.status)}
          <Text type="secondary" style={{ fontSize: 12 }}>
            {rfq.rfq_number ?? rfq.id.slice(0, 8)}
          </Text>
        </Space>
      }
      open={open}
      onClose={() => {
        // §19 round-1 P1-3: 关闭 Drawer 时清空内部子 modal/state, 避免再次打开 Drawer
        // 时 cancelOpen 残留 true 导致取消 Modal 立即弹出。
        setCancelOpen(false);
        setSelectedQuoteId(null);
        onClose();
      }}
      width={960}
      destroyOnClose
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchComparison} loading={loading}>
            刷新
          </Button>
          {rfq.status === 'draft' && (
            <Popconfirm
              title="发布询价单？"
              description="发布后被邀供应商可见，无法回退至草稿。"
              onConfirm={handlePublish}
              okText="确认发布"
            >
              <Button type="primary" icon={<SendOutlined />}>
                发布
              </Button>
            </Popconfirm>
          )}
          {rfq.status === 'quoting' && (
            <Popconfirm
              title="截止收报价？"
              description="进入比价审核，供应商无法再修改报价。"
              onConfirm={handleClose}
              okText="确认截止"
            >
              <Button icon={<CheckCircleOutlined />}>截止收报价</Button>
            </Popconfirm>
          )}
          {!['awarded', 'cancelled'].includes(rfq.status) && (
            <Button danger icon={<StopOutlined />} onClick={() => setCancelOpen(true)}>
              取消
            </Button>
          )}
        </Space>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Card size="small" title="基本信息">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>截止时间：{dayjs(rfq.deadline).format('YYYY-MM-DD HH:mm')}</Text>
            <Text>创建人：{rfq.created_by}</Text>
            <Text>备注：{rfq.notes || <Text type="secondary">（无）</Text>}</Text>
          </Space>
        </Card>

        <Card size="small" title={<><TrophyOutlined /> 比价表 + AI 推荐</>} loading={loading}>
          {comparison?.items.length ? (
            comparison.items.map((it) => {
              const ingName = ingredientsById.get(it.ingredient_id)?.name ?? it.ingredient_id.slice(0, 8);
              return (
                <Card key={it.id} type="inner" size="small" style={{ marginBottom: 12 }}
                  title={
                    <Space>
                      <Text strong>{ingName}</Text>
                      <Tag>需求：{it.qty_required} {it.qty_unit ?? ''}</Tag>
                    </Space>
                  }
                >
                  <Paragraph type="secondary" style={{ marginBottom: 8 }}>
                    🤖 AI 推荐：{it.ai_recommendation_reason}
                  </Paragraph>
                  {it.quotes.length > 0 ? (
                    <Table
                      size="small"
                      pagination={false}
                      rowKey="quote_id"
                      dataSource={it.quotes}
                      rowSelection={{
                        type: 'radio',
                        selectedRowKeys: selectedQuoteId ? [selectedQuoteId] : [],
                        onChange: (keys) => setSelectedQuoteId((keys[0] as string) ?? null),
                      }}
                      columns={[
                        {
                          title: '供应商',
                          dataIndex: 'supplier_id',
                          render: (id: string) =>
                            suppliersById.get(id)?.name ?? id.slice(0, 8),
                        },
                        {
                          title: '单价 (元)',
                          dataIndex: 'unit_price_fen',
                          render: (fen: number) => <Text strong>¥{fenToYuan(fen)}</Text>,
                          sorter: (a, b) => a.unit_price_fen - b.unit_price_fen,
                        },
                        { title: '供货量', dataIndex: 'qty_offered', render: (v) => v ?? '—' },
                        {
                          title: '有效期',
                          dataIndex: 'valid_until',
                          render: (d) => (d ? dayjs(d).format('YYYY-MM-DD') : '—'),
                        },
                        {
                          title: 'AI 推荐',
                          dataIndex: 'quote_id',
                          render: (qid: string) =>
                            qid === it.ai_recommended_quote_id ? (
                              <Tag color="gold" icon={<TrophyOutlined />}>推荐</Tag>
                            ) : null,
                        },
                      ]}
                    />
                  ) : (
                    <Text type="secondary">尚无报价</Text>
                  )}
                </Card>
              );
            })
          ) : (
            <Text type="secondary">询价单暂无明细</Text>
          )}
        </Card>

        <AwardSection
          rfq={rfq}
          comparison={comparison}
          currentUserId={currentUserId}
          selectedQuoteId={selectedQuoteId}
          onAwardSuccess={() => {
            setSelectedQuoteId(null);
            void fetchComparison();
            onActionSuccess();
          }}
        />

        <CancelRFQModal
          rfq={rfq}
          open={cancelOpen}
          onClose={() => setCancelOpen(false)}
          onSuccess={() => {
            setCancelOpen(false);
            onActionSuccess();
          }}
        />
      </Space>
    </Drawer>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function RFQManagementPage() {
  const [rfqs, setRfqs] = useState<RFQ[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<RFQStatus | ''>('');
  const [createOpen, setCreateOpen] = useState(false);
  const [detailRfq, setDetailRfq] = useState<RFQ | null>(null);
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);

  const currentUserId = useMemo(() => getTokenPayload()?.user_id ?? '', []);

  const ingredientsById = useMemo(
    () => new Map(ingredients.map((i) => [i.id, i])),
    [ingredients],
  );
  const suppliersById = useMemo(
    () => new Map(suppliers.map((s) => [s.id, s])),
    [suppliers],
  );

  const fetchRfqs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '100', offset: '0' });
      if (statusFilter) params.set('status', statusFilter);
      const data = await txFetchData<RFQ[]>(
        `/api/v1/supply/rfqs?${params.toString()}`,
      );
      setRfqs(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`加载询价单失败：${msg}`);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const fetchOptions = useCallback(async () => {
    try {
      const ingData = await txFetchData<{ items: Ingredient[] } | Ingredient[]>(
        '/api/v1/supply/ingredients?page=1&size=200',
      );
      const items = Array.isArray(ingData) ? ingData : ingData.items;
      setIngredients(items ?? []);
    } catch {
      // 优雅降级 — 食材选项可空
    }
    try {
      const supData = await txFetchData<{ items: Supplier[] } | Supplier[]>(
        '/api/v1/suppliers?page=1&size=200',
      );
      const items = Array.isArray(supData) ? supData : supData.items;
      setSuppliers(items ?? []);
    } catch {
      // 优雅降级 — 供应商选项可空
    }
  }, []);

  useEffect(() => {
    void fetchRfqs();
  }, [fetchRfqs]);

  useEffect(() => {
    void fetchOptions();
  }, [fetchOptions]);

  const columns: ColumnsType<RFQ> = [
    {
      title: '编号',
      dataIndex: 'rfq_number',
      render: (n: string | null, r) => n ?? <code>{r.id.slice(0, 8)}…</code>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (s: RFQStatus) => statusTag(s),
      filters: STATUS_OPTIONS.filter((o) => o.value !== '').map((o) => ({
        text: o.label,
        value: o.value,
      })),
      onFilter: (value, record) => record.status === value,
    },
    {
      title: '截止时间',
      dataIndex: 'deadline',
      render: (d: string) => dayjs(d).format('YYYY-MM-DD HH:mm'),
      sorter: (a, b) => dayjs(a.deadline).valueOf() - dayjs(b.deadline).valueOf(),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (d: string) => dayjs(d).format('YYYY-MM-DD HH:mm'),
    },
    { title: '备注', dataIndex: 'notes', ellipsis: true },
    {
      title: '操作',
      render: (_, r) => (
        <Button type="link" onClick={() => setDetailRfq(r)}>
          详情 / 比价
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title level={3} style={{ margin: 0 }}>
            询价单管理（PRD-04 / 比价 + AI 推荐 + 二级审批）
          </Title>
          <Space>
            <Select
              style={{ width: 180 }}
              value={statusFilter}
              options={STATUS_OPTIONS}
              onChange={(v) => setStatusFilter(v as RFQStatus | '')}
            />
            <Button icon={<ReloadOutlined />} onClick={fetchRfqs} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建询价
            </Button>
          </Space>
        </div>

        <Alert
          type="info"
          showIcon
          icon={<CloseCircleOutlined style={{ display: 'none' }} />}
          message="状态机：draft → published → quoting → comparing → awarded / cancelled"
          description="创建（草稿） → 发布（通知供应商） → 收报价 → 截止比价 → 二级审批中标。任何非终态可取消。中标后不可回退（Tier 1 资金路径）。"
        />

        <Table
          rowKey="id"
          loading={loading}
          dataSource={rfqs}
          columns={columns}
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Space>

      <CreateRFQModal
        open={createOpen}
        ingredients={ingredients}
        suppliers={suppliers}
        onClose={() => setCreateOpen(false)}
        onSuccess={fetchRfqs}
      />

      <RFQDetailDrawer
        rfq={detailRfq}
        open={!!detailRfq}
        currentUserId={currentUserId}
        ingredientsById={ingredientsById}
        suppliersById={suppliersById}
        onClose={() => setDetailRfq(null)}
        onActionSuccess={() => {
          void fetchRfqs();
          // 重新打开 detail (刷新最新 status)
          if (detailRfq) {
            const fresh = rfqs.find((r) => r.id === detailRfq.id);
            setDetailRfq(fresh ?? null);
          }
        }}
      />
    </div>
  );
}

export default RFQManagementPage;
