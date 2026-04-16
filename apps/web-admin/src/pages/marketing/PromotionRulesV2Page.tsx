/**
 * 营销促销规则引擎 V2 — PromotionRulesV2Page
 * 路径: /marketing/promotions-v2
 *
 * 五类方案 + 互斥组/优先级/叠加开关 + 毛利底线硬约束
 *
 * API:
 *   GET    /api/v1/promotions/rules
 *   POST   /api/v1/promotions/rules
 *   PUT    /api/v1/promotions/rules/{id}
 *   DELETE /api/v1/promotions/rules/{id}
 *   POST   /api/v1/promotions/voucher/verify
 *   GET    /api/v1/promotions/effect-report
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Badge,
  Button,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
  TimePicker,
  Tooltip,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  GiftOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData, apiPost, apiGet } from '../../api/client';
import dayjs from 'dayjs';

// ─── Design Token ─────────────────────────────────────────────────────────────
const C = {
  primary:  '#FF6B35',
  success:  '#0F6E56',
  warning:  '#BA7517',
  danger:   '#A32D2D',
  info:     '#185FA5',
  cardBg:   '#1a2535',
  border:   '#2a3a4a',
  text:     '#e8eaf0',
  textSub:  '#adb5c4',
};

// ─── 类型定义 ─────────────────────────────────────────────────────────────────
type PromotionType =
  | 'TIME_DISCOUNT'
  | 'ITEM_DISCOUNT'
  | 'BUY_GIFT'
  | 'FULL_REDUCE'
  | 'VOUCHER_VERIFY';

interface PromotionRule {
  id: string;
  name: string;
  promotion_type: PromotionType;
  status: 'active' | 'inactive' | 'expired';
  exclusion_group: string | null;
  priority: number;
  stack_allowed: boolean;
  gross_margin_threshold_pct: number;
  discount_pct: number | null;
  time_start: string | null;
  time_end: string | null;
  weekdays: number[] | null;
  item_skus: string[] | null;
  item_price_fen: number | null;
  buy_sku: string | null;
  gift_sku: string | null;
  gift_qty: number | null;
  full_reduce_threshold_fen: number | null;
  full_reduce_amount_fen: number | null;
  voucher_platform: string | null;
  voucher_face_value_fen: number | null;
  valid_from: string | null;
  valid_to: string | null;
  description: string | null;
  created_at: string;
}

interface RuleListResp {
  items: PromotionRule[];
  total: number;
  page: number;
  size: number;
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────
const PROMO_TYPE_LABELS: Record<PromotionType, string> = {
  TIME_DISCOUNT:  '时段折扣',
  ITEM_DISCOUNT:  '品项折扣',
  BUY_GIFT:       '买赠',
  FULL_REDUCE:    '满减',
  VOUCHER_VERIFY: '团购券核销',
};

const PROMO_TYPE_COLORS: Record<PromotionType, string> = {
  TIME_DISCOUNT:  'blue',
  ITEM_DISCOUNT:  'purple',
  BUY_GIFT:       'green',
  FULL_REDUCE:    'orange',
  VOUCHER_VERIFY: 'cyan',
};

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

// ─── 组件 ─────────────────────────────────────────────────────────────────────
export default function PromotionRulesV2Page() {
  const [activeTab, setActiveTab] = useState<PromotionType | 'ALL'>('ALL');
  const [rules, setRules] = useState<PromotionRule[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<PromotionRule | null>(null);
  const [form] = Form.useForm();
  const [selectedType, setSelectedType] = useState<PromotionType>('TIME_DISCOUNT');
  const [saving, setSaving] = useState(false);

  // 券码核销状态
  const [voucherModalOpen, setVoucherModalOpen] = useState(false);
  const [voucherCode, setVoucherCode] = useState('');
  const [voucherResult, setVoucherResult] = useState<Record<string, unknown> | null>(null);
  const [voucherLoading, setVoucherLoading] = useState(false);

  const fetchRules = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(p), size: '20' });
      if (activeTab !== 'ALL') params.set('promotion_type', activeTab);
      const data = await apiGet<RuleListResp>(`/api/v1/promotions/rules?${params}`);
      setRules(data.items);
      setTotal(data.total);
      setPage(p);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '加载规则失败');
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  useEffect(() => { fetchRules(1); }, [fetchRules]);

  const openCreate = () => {
    setEditingRule(null);
    form.resetFields();
    setSelectedType('TIME_DISCOUNT');
    setModalOpen(true);
  };

  const openEdit = (rule: PromotionRule) => {
    setEditingRule(rule);
    setSelectedType(rule.promotion_type);
    form.setFieldsValue({
      ...rule,
      item_skus_str: rule.item_skus?.join(',') || '',
      weekdays: rule.weekdays || [],
      item_price_yuan: rule.item_price_fen != null ? rule.item_price_fen / 100 : undefined,
      full_reduce_threshold_yuan: rule.full_reduce_threshold_fen != null
        ? rule.full_reduce_threshold_fen / 100 : undefined,
      full_reduce_amount_yuan: rule.full_reduce_amount_fen != null
        ? rule.full_reduce_amount_fen / 100 : undefined,
      voucher_face_value_yuan: rule.voucher_face_value_fen != null
        ? rule.voucher_face_value_fen / 100 : undefined,
    });
    setModalOpen(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await txFetchData(`/api/v1/promotions/rules/${id}`, { method: 'DELETE' });
      message.success('规则已停用');
      fetchRules(page);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '停用失败');
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const payload: Record<string, unknown> = {
        name: values.name,
        promotion_type: values.promotion_type,
        exclusion_group: values.exclusion_group || null,
        priority: values.priority || 100,
        stack_allowed: values.stack_allowed || false,
        gross_margin_threshold_pct: values.gross_margin_threshold_pct ?? 20,
        description: values.description || null,
      };

      // 类型特定字段
      if (values.promotion_type === 'TIME_DISCOUNT') {
        payload.time_start = values.time_start
          ? (typeof values.time_start === 'string' ? values.time_start : values.time_start.format('HH:mm'))
          : null;
        payload.time_end = values.time_end
          ? (typeof values.time_end === 'string' ? values.time_end : values.time_end.format('HH:mm'))
          : null;
        payload.weekdays = values.weekdays?.length ? values.weekdays : null;
        payload.discount_pct = values.discount_pct;
      } else if (values.promotion_type === 'ITEM_DISCOUNT') {
        const skuStr: string = values.item_skus_str || '';
        payload.item_skus = skuStr.split(',').map((s: string) => s.trim()).filter(Boolean);
        payload.item_price_fen = values.item_price_yuan != null
          ? Math.round(values.item_price_yuan * 100) : null;
        payload.discount_pct = values.discount_pct ?? null;
      } else if (values.promotion_type === 'BUY_GIFT') {
        payload.buy_sku = values.buy_sku;
        payload.gift_sku = values.gift_sku;
        payload.gift_qty = values.gift_qty || 1;
      } else if (values.promotion_type === 'FULL_REDUCE') {
        payload.full_reduce_threshold_fen = values.full_reduce_threshold_yuan != null
          ? Math.round(values.full_reduce_threshold_yuan * 100) : null;
        payload.full_reduce_amount_fen = values.full_reduce_amount_yuan != null
          ? Math.round(values.full_reduce_amount_yuan * 100) : null;
      } else if (values.promotion_type === 'VOUCHER_VERIFY') {
        payload.voucher_platform = values.voucher_platform;
        payload.voucher_face_value_fen = values.voucher_face_value_yuan != null
          ? Math.round(values.voucher_face_value_yuan * 100) : null;
      }

      if (editingRule) {
        await txFetchData(`/api/v1/promotions/rules/${editingRule.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
          headers: { 'Content-Type': 'application/json' },
        });
        message.success('规则更新成功');
      } else {
        await apiPost('/api/v1/promotions/rules', payload);
        message.success('规则创建成功');
      }
      setModalOpen(false);
      fetchRules(page);
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleVoucherVerify = async () => {
    if (!voucherCode.trim()) { message.warning('请输入券码'); return; }
    setVoucherLoading(true);
    try {
      const result = await apiPost<Record<string, unknown>>(
        '/api/v1/promotions/voucher/verify',
        { voucher_code: voucherCode.trim() }
      );
      setVoucherResult(result);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '验证失败');
    } finally {
      setVoucherLoading(false);
    }
  };

  // ─── 表格列 ────────────────────────────────────────────────────────────────
  const columns: ColumnsType<PromotionRule> = [
    {
      title: '规则名称',
      dataIndex: 'name',
      width: 160,
      render: (v: string) => <span style={{ color: C.text, fontWeight: 500 }}>{v}</span>,
    },
    {
      title: '类型',
      dataIndex: 'promotion_type',
      width: 110,
      render: (v: PromotionType) => (
        <Tag color={PROMO_TYPE_COLORS[v]}>{PROMO_TYPE_LABELS[v]}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (v: string) => (
        <Badge
          status={v === 'active' ? 'success' : 'default'}
          text={v === 'active' ? '启用' : '停用'}
        />
      ),
    },
    {
      title: (
        <Space>
          优先级
          <Tooltip title="数字越小优先级越高"><QuestionCircleOutlined /></Tooltip>
        </Space>
      ),
      dataIndex: 'priority',
      width: 80,
      sorter: (a, b) => a.priority - b.priority,
    },
    {
      title: '互斥组',
      dataIndex: 'exclusion_group',
      width: 100,
      render: (v: string | null) => v ? <Tag>{v}</Tag> : <span style={{ color: '#666' }}>—</span>,
    },
    {
      title: '叠加',
      dataIndex: 'stack_allowed',
      width: 60,
      render: (v: boolean) => (
        <Tag color={v ? 'green' : 'red'}>{v ? '允许' : '互斥'}</Tag>
      ),
    },
    {
      title: '毛利底线',
      dataIndex: 'gross_margin_threshold_pct',
      width: 90,
      render: (v: number) => (
        <span style={{ color: C.warning }}>
          <SafetyOutlined /> {v}%
        </span>
      ),
    },
    {
      title: '规则摘要',
      key: 'summary',
      ellipsis: true,
      render: (_: unknown, r: PromotionRule) => {
        if (r.promotion_type === 'TIME_DISCOUNT') {
          return `${r.time_start}-${r.time_end} ${r.discount_pct ? `${r.discount_pct}折` : ''}`;
        }
        if (r.promotion_type === 'ITEM_DISCOUNT') {
          const skus = r.item_skus?.join(',') || '';
          return `SKU: ${skus.length > 20 ? skus.slice(0, 20) + '...' : skus}`;
        }
        if (r.promotion_type === 'BUY_GIFT') {
          return `买${r.buy_sku} 赠${r.gift_sku} x${r.gift_qty}`;
        }
        if (r.promotion_type === 'FULL_REDUCE') {
          const t = r.full_reduce_threshold_fen ? r.full_reduce_threshold_fen / 100 : 0;
          const a = r.full_reduce_amount_fen ? r.full_reduce_amount_fen / 100 : 0;
          return `满${t}元减${a}元`;
        }
        if (r.promotion_type === 'VOUCHER_VERIFY') {
          const fv = r.voucher_face_value_fen ? r.voucher_face_value_fen / 100 : 0;
          return `${r.voucher_platform || ''}券 面值${fv}元`;
        }
        return '—';
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, r: PromotionRule) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(r)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认停用此规则？"
            onConfirm={() => handleDelete(r.id)}
            okText="停用"
            cancelText="取消"
          >
            <Button type="link" danger size="small" icon={<DeleteOutlined />}>
              停用
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ─── 动态表单字段（根据规则类型渲染） ────────────────────────────────────
  const renderTypeFields = () => {
    if (selectedType === 'TIME_DISCOUNT') {
      return (
        <>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="开始时间" name="time_start" rules={[{ required: true, message: '请输入' }]}>
                <Input placeholder="11:00" maxLength={5} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="结束时间" name="time_end" rules={[{ required: true, message: '请输入' }]}>
                <Input placeholder="14:00" maxLength={5} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="适用星期" name="weekdays">
            <Select
              mode="multiple"
              placeholder="不选=每天"
              options={WEEKDAY_LABELS.map((l, i) => ({ label: l, value: i }))}
            />
          </Form.Item>
          <Form.Item label="折扣百分比" name="discount_pct" rules={[{ required: true, message: '请输入' }]}>
            <InputNumber min={1} max={100} addonAfter="%" placeholder="如85=8.5折" style={{ width: '100%' }} />
          </Form.Item>
        </>
      );
    }

    if (selectedType === 'ITEM_DISCOUNT') {
      return (
        <>
          <Form.Item
            label="适用SKU（逗号分隔）"
            name="item_skus_str"
            rules={[{ required: true, message: '请输入SKU' }]}
          >
            <Input.TextArea rows={2} placeholder="SKU001,SKU002,SKU003" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="指定特价（元）" name="item_price_yuan">
                <InputNumber min={0} precision={2} placeholder="留空=按折扣" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="折扣百分比" name="discount_pct">
                <InputNumber min={1} max={100} addonAfter="%" placeholder="如85=8.5折" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </>
      );
    }

    if (selectedType === 'BUY_GIFT') {
      return (
        <>
          <Form.Item label="主菜SKU" name="buy_sku" rules={[{ required: true, message: '请输入主菜SKU' }]}>
            <Input placeholder="如 DISH-001" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={16}>
              <Form.Item label="赠品SKU" name="gift_sku" rules={[{ required: true, message: '请输入赠品SKU' }]}>
                <Input placeholder="如 DISH-SIDE-001" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="赠送数量" name="gift_qty" initialValue={1}>
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </>
      );
    }

    if (selectedType === 'FULL_REDUCE') {
      return (
        <>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                label="满额门槛（元）"
                name="full_reduce_threshold_yuan"
                rules={[{ required: true, message: '请输入' }]}
              >
                <InputNumber min={0} precision={2} placeholder="如200" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="减免金额（元）"
                name="full_reduce_amount_yuan"
                rules={[{ required: true, message: '请输入' }]}
              >
                <InputNumber min={0} precision={2} placeholder="如30" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </>
      );
    }

    if (selectedType === 'VOUCHER_VERIFY') {
      return (
        <>
          <Form.Item label="券来源平台" name="voucher_platform">
            <Select
              placeholder="选择平台"
              options={[
                { label: '美团', value: 'meituan' },
                { label: '抖音', value: 'douyin' },
                { label: '饿了么', value: 'eleme' },
                { label: '自定义', value: 'custom' },
              ]}
            />
          </Form.Item>
          <Form.Item label="券面值（元）" name="voucher_face_value_yuan">
            <InputNumber min={0} precision={2} placeholder="如50" style={{ width: '100%' }} />
          </Form.Item>
        </>
      );
    }

    return null;
  };

  // ─── Tab 列表 ──────────────────────────────────────────────────────────────
  const tabItems = [
    { key: 'ALL', label: '全部' },
    ...Object.entries(PROMO_TYPE_LABELS).map(([k, v]) => ({ key: k, label: v })),
  ];

  // ─── 渲染 ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: 24, background: '#0d1b2a', minHeight: '100vh', color: C.text }}>
      {/* 页头 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 20 }}>
        <Col>
          <Space align="center">
            <GiftOutlined style={{ fontSize: 22, color: C.primary }} />
            <span style={{ fontSize: 20, fontWeight: 700, color: C.text }}>
              促销规则引擎 V2
            </span>
            <Tag color="orange" style={{ marginLeft: 8 }}>模块 2.5</Tag>
          </Space>
          <div style={{ color: C.textSub, fontSize: 13, marginTop: 4 }}>
            支持时段折扣 / 品项折扣 / 买赠 / 满减 / 团购券核销 · 毛利底线硬约束
          </div>
        </Col>
        <Col>
          <Space>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={() => { setVoucherCode(''); setVoucherResult(null); setVoucherModalOpen(true); }}
              style={{ borderColor: C.info, color: C.info }}
            >
              券码核销
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => fetchRules(1)}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={openCreate}
              style={{ background: C.primary, borderColor: C.primary }}
            >
              新建规则
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 分类 Tab */}
      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as PromotionType | 'ALL')}
        items={tabItems}
        style={{ marginBottom: 16 }}
      />

      {/* 规则表格 */}
      <div style={{
        background: C.cardBg,
        borderRadius: 8,
        border: `1px solid ${C.border}`,
        padding: '0 0 16px',
      }}>
        <Table<PromotionRule>
          columns={columns}
          dataSource={rules}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            onChange: fetchRules,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条规则`,
          }}
          size="small"
          style={{ background: 'transparent' }}
        />
      </div>

      {/* 创建/编辑规则 Modal */}
      <Modal
        title={editingRule ? '编辑促销规则' : '新建促销规则'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        width={600}
        okText={editingRule ? '保存' : '创建'}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ priority: 100, stack_allowed: false, gross_margin_threshold_pct: 20 }}
        >
          {/* 基础字段 */}
          <Form.Item label="规则名称" name="name" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="如：午市8.8折优惠" maxLength={100} />
          </Form.Item>

          <Form.Item label="方案类型" name="promotion_type" rules={[{ required: true }]}>
            <Select
              options={Object.entries(PROMO_TYPE_LABELS).map(([k, v]) => ({ label: v, value: k }))}
              onChange={(v) => setSelectedType(v as PromotionType)}
              placeholder="选择促销类型"
            />
          </Form.Item>

          <Divider dashed style={{ margin: '12px 0' }} />

          {/* 类型特定字段 */}
          {renderTypeFields()}

          <Divider dashed style={{ margin: '12px 0' }} />

          {/* 互斥/优先级/叠加 */}
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item
                label={
                  <Space>
                    优先级
                    <Tooltip title="数字越小优先级越高（1-9999）">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="priority"
              >
                <InputNumber min={1} max={9999} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label={
                  <Space>
                    互斥组
                    <Tooltip title="同组规则互斥，仅优先级最高的生效">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                name="exclusion_group"
              >
                <Input placeholder="如 group-A" maxLength={50} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="允许叠加" name="stack_allowed" valuePropName="checked">
                <Switch checkedChildren="允许" unCheckedChildren="互斥" />
              </Form.Item>
            </Col>
          </Row>

          {/* 毛利底线硬约束 */}
          <Form.Item
            label={
              <Space>
                <SafetyOutlined style={{ color: C.warning }} />
                毛利底线（折扣后毛利率不低于此值）
              </Space>
            }
            name="gross_margin_threshold_pct"
            rules={[{ required: true, message: '请设置毛利底线' }]}
          >
            <InputNumber
              min={0}
              max={100}
              addonAfter="%"
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item label="备注" name="description">
            <Input.TextArea rows={2} placeholder="可选备注" maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 券码核销 Modal */}
      <Modal
        title={
          <Space>
            <ThunderboltOutlined style={{ color: C.info }} />
            团购券核销验证
          </Space>
        }
        open={voucherModalOpen}
        onCancel={() => setVoucherModalOpen(false)}
        footer={null}
        width={420}
      >
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Input
            value={voucherCode}
            onChange={(e) => setVoucherCode(e.target.value)}
            placeholder="输入券码"
            onPressEnter={handleVoucherVerify}
            maxLength={64}
          />
          <Button
            type="primary"
            loading={voucherLoading}
            onClick={handleVoucherVerify}
            style={{ background: C.primary, borderColor: C.primary }}
          >
            核销验证
          </Button>
        </Space.Compact>

        {voucherResult && (
          <div style={{
            background: voucherResult.valid ? '#0a2a1a' : '#2a0a0a',
            border: `1px solid ${voucherResult.valid ? C.success : C.danger}`,
            borderRadius: 6,
            padding: 16,
          }}>
            <div style={{ fontWeight: 700, marginBottom: 8, color: voucherResult.valid ? '#4ade80' : '#f87171' }}>
              {voucherResult.valid ? '核销验证通过' : `验证失败：${voucherResult.reason}`}
            </div>
            {(voucherResult.valid as unknown as boolean) && (
              <>
                <div style={{ color: C.textSub }}>规则：{String(voucherResult.rule_name || '')}</div>
                <div style={{ color: C.textSub }}>平台：{String(voucherResult.platform || '—')}</div>
                <div style={{ color: '#fbbf24', fontSize: 18, fontWeight: 700, marginTop: 8 }}>
                  面值：¥{typeof voucherResult.face_value_yuan === 'number'
                    ? voucherResult.face_value_yuan.toFixed(2) : '0.00'}
                </div>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
