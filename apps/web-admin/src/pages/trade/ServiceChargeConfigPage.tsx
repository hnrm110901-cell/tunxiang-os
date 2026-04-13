/**
 * 服务费配置页面
 * 域A — 交易履约 → 服务费配置
 *
 * 功能：
 * - 多门店配置服务费（百分比/固定/人头费）
 * - 适用时段、星期、会员等级豁免
 * - 最低消费规则
 * - 模板管理（新建、下发）
 * - 实时预览计算
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tag,
  TimePicker,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, SendOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../api';
import {
  calculateServiceCharge,
  createTemplate,
  getChargeConfig,
  publishTemplate,
  setChargeConfig,
} from '../../api/serviceChargeApi';
import type { ServiceChargeConfig, ServiceChargeTemplate } from '../../api/serviceChargeApi';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;

// ─── 常量 ───

const WEEK_DAYS = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 0 },
];

const CHARGE_TYPE_OPTIONS = [
  { label: '按百分比', value: 'percentage' },
  { label: '固定金额', value: 'fixed' },
  { label: '按人头', value: 'per_person' },
];

const TIME_MODE_OPTIONS = [
  { label: '全天', value: 'all' },
  { label: '仅午市', value: 'lunch' },
  { label: '仅晚市', value: 'dinner' },
  { label: '自定义时段', value: 'custom' },
];

const TIME_PRESETS: Record<string, { start: string; end: string } | null> = {
  all: null,
  lunch: { start: '10:00', end: '14:30' },
  dinner: { start: '17:00', end: '22:00' },
  custom: null,
};

// 会员等级（实际项目中可从 API 加载）
const MEMBER_LEVELS = [
  { label: '普通会员', value: 'normal' },
  { label: '银卡', value: 'silver' },
  { label: '金卡', value: 'gold' },
  { label: '铂金', value: 'platinum' },
  { label: 'VIP', value: 'vip' },
];

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function yuanToFen(yuan: number): number {
  return Math.round(yuan * 100);
}

// ─── 配置表单区 ───

interface ConfigFormValues {
  enabled: boolean;
  charge_type: 'percentage' | 'fixed' | 'per_person';
  rate: number;
  fixed_amount_yuan: number;
  per_person_yuan: number;
  time_mode: string;
  custom_start: dayjs.Dayjs | null;
  custom_end: dayjs.Dayjs | null;
  applicable_days: number[];
  exempt_member_levels: string[];
  min_amount_enabled: boolean;
  min_amount_yuan: number;
}

// ─── 模板管理弹窗 ───

function PublishTemplateModal({
  open,
  template,
  stores,
  onClose,
  onPublished,
}: {
  open: boolean;
  template: ServiceChargeTemplate | null;
  stores: Array<{ value: string; label: string }>;
  onClose: () => void;
  onPublished: () => void;
}) {
  const [selectedStores, setSelectedStores] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const handlePublish = async () => {
    if (!template || selectedStores.length === 0) {
      message.warning('请选择至少一个门店');
      return;
    }
    setLoading(true);
    try {
      const result = await publishTemplate(template.id, selectedStores);
      message.success(`已成功下发到 ${result.published_count} 家门店`);
      if (result.failed_stores?.length) {
        message.warning(`${result.failed_stores.length} 家门店下发失败`);
      }
      onPublished();
      onClose();
    } catch {
      message.error('模板下发失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`下发模板 — ${template?.name ?? ''}`}
      open={open}
      onCancel={onClose}
      onOk={handlePublish}
      confirmLoading={loading}
      okText="确认下发"
      width={480}
    >
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary">选择要下发的门店（支持多选）</Text>
      </div>
      <Select
        mode="multiple"
        options={stores}
        value={selectedStores}
        onChange={setSelectedStores}
        placeholder="请选择门店"
        style={{ width: '100%' }}
        filterOption={(input, opt) =>
          (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
        }
      />
    </Modal>
  );
}

// ─── 主页面 ───

export function ServiceChargeConfigPage() {
  const [stores, setStores] = useState<Array<{ value: string; label: string }>>([]);
  const [selectedStoreId, setSelectedStoreId] = useState<string | undefined>();
  const [configLoading, setConfigLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);

  // 表单
  const [form] = Form.useForm<ConfigFormValues>();
  const chargeType = Form.useWatch('charge_type', form);
  const timeMode = Form.useWatch('time_mode', form);
  const minAmountEnabled = Form.useWatch('min_amount_enabled', form);
  const enabled = Form.useWatch('enabled', form);

  // 实时预览
  const [previewOrderYuan, setPreviewOrderYuan] = useState<number>(0);
  const [previewGuests, setPreviewGuests] = useState<number>(1);
  const [previewFee, setPreviewFee] = useState<number | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // 模板
  const [templates, setTemplates] = useState<ServiceChargeTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [newTemplateOpen, setNewTemplateOpen] = useState(false);
  const [newTemplateName, setNewTemplateName] = useState('');
  const [publishTarget, setPublishTarget] = useState<ServiceChargeTemplate | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>(
      '/api/v1/org/stores?status=active',
    )
      .then((data) => {
        const list = (data.items ?? []).map((s) => ({ value: s.id, label: s.name }));
        setStores(list);
        if (list.length > 0 && !selectedStoreId) {
          setSelectedStoreId(list[0].value);
        }
      })
      .catch(() => setStores([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 加载配置
  const loadConfig = useCallback(async (storeId: string) => {
    setConfigLoading(true);
    try {
      const config = await getChargeConfig(storeId);
      const timeMode = (() => {
        if (!config.applicable_hours) return 'all';
        const { start, end } = config.applicable_hours;
        if (start === '10:00' && end === '14:30') return 'lunch';
        if (start === '17:00' && end === '22:00') return 'dinner';
        return 'custom';
      })();

      form.setFieldsValue({
        enabled: config.enabled ?? true,
        charge_type: config.charge_type ?? 'percentage',
        rate: config.rate ?? 10,
        fixed_amount_yuan: config.fixed_amount_fen ? config.fixed_amount_fen / 100 : 0,
        per_person_yuan: config.per_person_fen ? config.per_person_fen / 100 : 0,
        time_mode: timeMode,
        custom_start: config.applicable_hours
          ? dayjs(config.applicable_hours.start, 'HH:mm')
          : null,
        custom_end: config.applicable_hours
          ? dayjs(config.applicable_hours.end, 'HH:mm')
          : null,
        applicable_days: config.applicable_days ?? [0, 1, 2, 3, 4, 5, 6],
        exempt_member_levels: config.exempt_member_levels ?? [],
        min_amount_enabled: (config.min_amount_fen ?? 0) > 0,
        min_amount_yuan: config.min_amount_fen ? config.min_amount_fen / 100 : 0,
      });
    } catch {
      // 配置不存在时使用默认值
      form.setFieldsValue({
        enabled: true,
        charge_type: 'percentage',
        rate: 10,
        time_mode: 'all',
        applicable_days: [0, 1, 2, 3, 4, 5, 6],
        exempt_member_levels: [],
        min_amount_enabled: false,
        min_amount_yuan: 0,
      });
    } finally {
      setConfigLoading(false);
    }
  }, [form]);

  useEffect(() => {
    if (selectedStoreId) {
      void loadConfig(selectedStoreId);
    }
  }, [selectedStoreId, loadConfig]);

  // 保存配置
  const handleSave = async () => {
    if (!selectedStoreId) {
      message.warning('请选择门店');
      return;
    }
    const values = await form.validateFields();
    setSaveLoading(true);

    const preset = TIME_PRESETS[values.time_mode];
    let applicable_hours: { start: string; end: string } | null = null;
    if (values.time_mode === 'custom' && values.custom_start && values.custom_end) {
      applicable_hours = {
        start: values.custom_start.format('HH:mm'),
        end: values.custom_end.format('HH:mm'),
      };
    } else if (preset) {
      applicable_hours = preset;
    }

    const config: Omit<ServiceChargeConfig, 'store_id'> = {
      enabled: values.enabled,
      charge_type: values.charge_type,
      rate: values.charge_type === 'percentage' ? values.rate : undefined,
      fixed_amount_fen:
        values.charge_type === 'fixed' ? yuanToFen(values.fixed_amount_yuan) : undefined,
      per_person_fen:
        values.charge_type === 'per_person' ? yuanToFen(values.per_person_yuan) : undefined,
      applicable_hours,
      applicable_days: values.applicable_days,
      exempt_member_levels: values.exempt_member_levels,
      min_amount_fen: values.min_amount_enabled ? yuanToFen(values.min_amount_yuan) : 0,
    };

    try {
      await setChargeConfig(selectedStoreId, config);
      message.success('服务费配置保存成功');
    } catch {
      message.error('保存失败，请重试');
    } finally {
      setSaveLoading(false);
    }
  };

  // 实时预览
  const handlePreview = async () => {
    if (!selectedStoreId || previewOrderYuan <= 0) {
      message.warning('请先选择门店并输入订单金额');
      return;
    }
    setPreviewLoading(true);
    try {
      const result = await calculateServiceCharge(
        selectedStoreId,
        yuanToFen(previewOrderYuan),
        previewGuests,
      );
      setPreviewFee(result.charge_fen);
    } catch {
      message.error('预览计算失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  // 新建模板
  const handleCreateTemplate = async () => {
    if (!newTemplateName.trim()) {
      message.warning('请输入模板名称');
      return;
    }
    const values = form.getFieldsValue();
    const preset = TIME_PRESETS[values.time_mode];
    let applicable_hours: { start: string; end: string } | null = null;
    if (values.time_mode === 'custom' && values.custom_start && values.custom_end) {
      applicable_hours = {
        start: values.custom_start.format('HH:mm'),
        end: values.custom_end.format('HH:mm'),
      };
    } else if (preset) {
      applicable_hours = preset;
    }

    try {
      const tpl = await createTemplate({
        name: newTemplateName,
        rules: {
          enabled: values.enabled,
          charge_type: values.charge_type,
          rate: values.rate,
          fixed_amount_fen: values.fixed_amount_yuan ? yuanToFen(values.fixed_amount_yuan) : 0,
          per_person_fen: values.per_person_yuan ? yuanToFen(values.per_person_yuan) : 0,
          applicable_hours,
          applicable_days: values.applicable_days,
          exempt_member_levels: values.exempt_member_levels,
          min_amount_fen: values.min_amount_enabled ? yuanToFen(values.min_amount_yuan) : 0,
        },
      });
      message.success('模板创建成功');
      setTemplates((prev) => [tpl, ...prev]);
      setNewTemplateOpen(false);
      setNewTemplateName('');
    } catch {
      message.error('模板创建失败');
    }
  };

  const templateColumns: ColumnsType<ServiceChargeTemplate> = [
    { title: '模板名称', dataIndex: 'name', key: 'name' },
    {
      title: '收费类型',
      key: 'type',
      render: (_, r) => {
        const t = r.rules?.charge_type;
        return t === 'percentage'
          ? <Tag color="blue">百分比</Tag>
          : t === 'fixed'
          ? <Tag color="green">固定金额</Tag>
          : <Tag color="orange">按人头</Tag>;
      },
      width: 100,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (v: string) => v?.slice(0, 10) ?? '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, r) => (
        <Button
          type="link"
          icon={<SendOutlined />}
          size="small"
          onClick={() => { setPublishTarget(r); setPublishOpen(true); }}
        >
          下发
        </Button>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          服务费配置
        </Title>
        <Text style={{ color: '#5F5E5A', fontSize: 14 }}>
          配置各门店服务费规则，支持按百分比、固定金额或按人头收取
        </Text>
      </div>

      <Row gutter={24}>
        {/* 左侧：配置区 */}
        <Col span={16}>
          {/* 门店选择 */}
          <Card style={{ marginBottom: 16 }} styles={{ body: { padding: '16px 24px' } }}>
            <Space size={12} align="center">
              <Text strong>当前配置门店：</Text>
              <Select
                placeholder="选择门店"
                options={stores}
                value={selectedStoreId}
                onChange={setSelectedStoreId}
                showSearch
                filterOption={(input, opt) =>
                  (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
                }
                style={{ width: 240 }}
              />
              {selectedStoreId && (
                <Tag color="blue" style={{ fontSize: 12 }}>
                  {stores.find((s) => s.value === selectedStoreId)?.label}
                </Tag>
              )}
            </Space>
          </Card>

          {/* 配置表单 */}
          <Card title="服务费配置">
            <Spin spinning={configLoading}>
              <Form
                form={form}
                layout="vertical"
                initialValues={{
                  enabled: true,
                  charge_type: 'percentage',
                  rate: 10,
                  time_mode: 'all',
                  applicable_days: [0, 1, 2, 3, 4, 5, 6],
                  exempt_member_levels: [],
                  min_amount_enabled: false,
                  min_amount_yuan: 0,
                }}
              >
                {/* 启用开关 */}
                <Form.Item name="enabled" valuePropName="checked" label="启用服务费">
                  <Switch
                    checkedChildren="开启"
                    unCheckedChildren="关闭"
                  />
                </Form.Item>

                {enabled !== false && (
                  <>
                    <Divider style={{ margin: '8px 0 16px' }} />

                    {/* 收费类型 */}
                    <Form.Item
                      name="charge_type"
                      label="服务费类型"
                      rules={[{ required: true }]}
                    >
                      <Radio.Group options={CHARGE_TYPE_OPTIONS} optionType="button" buttonStyle="solid" />
                    </Form.Item>

                    {/* 费率输入 — 按类型变化 */}
                    {chargeType === 'percentage' && (
                      <Form.Item
                        name="rate"
                        label="服务费率（%）"
                        rules={[{ required: true, message: '请输入费率' }]}
                      >
                        <InputNumber min={0} max={100} precision={1} suffix="%" style={{ width: 160 }} />
                      </Form.Item>
                    )}
                    {chargeType === 'fixed' && (
                      <Form.Item
                        name="fixed_amount_yuan"
                        label="固定服务费（元/单）"
                        rules={[{ required: true, message: '请输入金额' }]}
                      >
                        <InputNumber min={0} precision={2} prefix="¥" style={{ width: 160 }} />
                      </Form.Item>
                    )}
                    {chargeType === 'per_person' && (
                      <Form.Item
                        name="per_person_yuan"
                        label="人头费（元/人）"
                        rules={[{ required: true, message: '请输入人头费' }]}
                      >
                        <InputNumber min={0} precision={2} prefix="¥" style={{ width: 160 }} />
                      </Form.Item>
                    )}

                    <Divider orientation="left" style={{ fontSize: 13, color: '#5F5E5A' }}>
                      适用规则
                    </Divider>

                    {/* 适用时段 */}
                    <Form.Item name="time_mode" label="适用时段">
                      <Radio.Group options={TIME_MODE_OPTIONS} />
                    </Form.Item>
                    {timeMode === 'custom' && (
                      <Form.Item label="自定义时段">
                        <Space>
                          <Form.Item name="custom_start" noStyle>
                            <TimePicker format="HH:mm" placeholder="开始时间" />
                          </Form.Item>
                          <Text>至</Text>
                          <Form.Item name="custom_end" noStyle>
                            <TimePicker format="HH:mm" placeholder="结束时间" />
                          </Form.Item>
                        </Space>
                      </Form.Item>
                    )}

                    {/* 适用星期 */}
                    <Form.Item name="applicable_days" label="适用星期">
                      <Checkbox.Group>
                        <Row>
                          {WEEK_DAYS.map((d) => (
                            <Col key={d.value} style={{ marginRight: 12 }}>
                              <Checkbox value={d.value}>{d.label}</Checkbox>
                            </Col>
                          ))}
                        </Row>
                      </Checkbox.Group>
                    </Form.Item>

                    {/* 免收服务费会员等级 */}
                    <Form.Item name="exempt_member_levels" label="免收服务费会员等级">
                      <Select
                        mode="multiple"
                        options={MEMBER_LEVELS}
                        placeholder="选择免收等级（不选则全部收取）"
                        style={{ maxWidth: 400 }}
                      />
                    </Form.Item>

                    <Divider orientation="left" style={{ fontSize: 13, color: '#5F5E5A' }}>
                      最低消费
                    </Divider>

                    {/* 最低消费 */}
                    <Form.Item name="min_amount_enabled" valuePropName="checked" label="启用最低消费">
                      <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                    </Form.Item>
                    {minAmountEnabled && (
                      <Form.Item
                        name="min_amount_yuan"
                        label="最低消费金额（元）"
                        rules={[{ required: true, message: '请输入最低消费金额' }]}
                      >
                        <InputNumber min={0} precision={2} prefix="¥" style={{ width: 160 }} />
                      </Form.Item>
                    )}
                  </>
                )}

                {/* 保存按钮 */}
                <Divider style={{ margin: '16px 0' }} />
                <Space>
                  <Button
                    type="primary"
                    onClick={handleSave}
                    loading={saveLoading}
                    style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
                    disabled={!selectedStoreId}
                  >
                    保存配置
                  </Button>
                  <Button
                    icon={<PlusOutlined />}
                    onClick={() => setNewTemplateOpen(true)}
                    disabled={!selectedStoreId}
                  >
                    另存为模板
                  </Button>
                </Space>
              </Form>
            </Spin>
          </Card>
        </Col>

        {/* 右侧：实时预览 */}
        <Col span={8}>
          <Card title="实时预览" style={{ marginBottom: 16, position: 'sticky', top: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <div>
                <Text style={{ display: 'block', marginBottom: 4 }}>订单金额（元）</Text>
                <InputNumber
                  min={0}
                  precision={2}
                  prefix="¥"
                  value={previewOrderYuan}
                  onChange={(v) => setPreviewOrderYuan(v ?? 0)}
                  style={{ width: '100%' }}
                  placeholder="如：200.00"
                />
              </div>
              <div>
                <Text style={{ display: 'block', marginBottom: 4 }}>就餐人数</Text>
                <InputNumber
                  min={1}
                  max={100}
                  value={previewGuests}
                  onChange={(v) => setPreviewGuests(v ?? 1)}
                  suffix="人"
                  style={{ width: '100%' }}
                />
              </div>
              <Button
                block
                type="default"
                onClick={handlePreview}
                loading={previewLoading}
                disabled={!selectedStoreId}
              >
                计算服务费
              </Button>

              {previewFee !== null && (
                <Card
                  style={{ background: '#FFF3ED', borderColor: '#FF6B35' }}
                  styles={{ body: { padding: '16px 20px' } }}
                >
                  <Statistic
                    title="预计服务费"
                    value={fenToYuan(previewFee)}
                    prefix="¥"
                    valueStyle={{ color: '#FF6B35', fontSize: 28 }}
                  />
                  {previewOrderYuan > 0 && previewFee > 0 && (
                    <Text style={{ color: '#5F5E5A', fontSize: 12 }}>
                      约占订单金额{((previewFee / yuanToFen(previewOrderYuan)) * 100).toFixed(1)}%
                    </Text>
                  )}
                </Card>
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 模板管理 */}
      <Card
        title="模板管理"
        style={{ marginTop: 24 }}
        extra={
          <Button
            icon={<PlusOutlined />}
            type="primary"
            size="small"
            onClick={() => setNewTemplateOpen(true)}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            新建模板
          </Button>
        }
      >
        <Spin spinning={templatesLoading}>
          {templates.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '32px 0', color: '#B4B2A9' }}>
              暂无模板，可将当前配置另存为模板
            </div>
          ) : (
            <Table<ServiceChargeTemplate>
              columns={templateColumns}
              dataSource={templates}
              rowKey="id"
              pagination={false}
              size="small"
            />
          )}
        </Spin>
      </Card>

      {/* 新建模板 Modal */}
      <Modal
        title="另存为模板"
        open={newTemplateOpen}
        onCancel={() => { setNewTemplateOpen(false); setNewTemplateName(''); }}
        onOk={handleCreateTemplate}
        okText="创建模板"
        width={400}
      >
        <div style={{ marginBottom: 8 }}>
          <Text type="secondary">将当前配置保存为可复用的模板</Text>
        </div>
        <Input
          placeholder="输入模板名称，如：节假日服务费"
          value={newTemplateName}
          onChange={(e) => setNewTemplateName(e.target.value)}
        />
      </Modal>

      {/* 下发模板 Modal */}
      <PublishTemplateModal
        open={publishOpen}
        template={publishTarget}
        stores={stores}
        onClose={() => setPublishOpen(false)}
        onPublished={() => {
          message.success('模板下发成功');
        }}
      />
    </div>
  );
}
