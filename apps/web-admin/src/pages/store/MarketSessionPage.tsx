/**
 * 营业市别配置 — 集团模板 + 门店覆盖
 * 路由: /store/market-sessions
 * API: tx-trade :8001
 *
 * 上部：集团市别模板（4个卡片：早市/午市/晚市/夜宵）
 * 下部：门店市别配置（选择门店 → 查看/编辑该门店的市别时间段）
 */
import { useState, useCallback } from 'react';
import {
  Button,
  Card,
  Col,
  ConfigProvider,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  TimePicker,
  Tooltip,
  Typography,
} from 'antd';
import {
  ClockCircleOutlined,
  EditOutlined,
  PlusOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useRequest } from 'ahooks';
import dayjs from 'dayjs';
import { txAdminTheme } from '../../theme/antd-theme';
import { getTenantId } from '../../api/client';

const { Title, Text } = Typography;

const API_BASE = '/api/v1/market-sessions';

const SESSION_COLOR: Record<string, string> = {
  breakfast: '#FA8C16',
  lunch:     '#52C41A',
  dinner:    '#1677FF',
  late_night: '#722ED1',
};

const SESSION_LABEL: Record<string, string> = {
  breakfast: '早市',
  lunch: '午市',
  dinner: '晚市',
  late_night: '夜宵',
};

// ─── API 调用 ─────────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
      ...(options?.headers ?? {}),
    },
    ...options,
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message ?? '请求失败');
  return json.data as T;
}

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface MarketSessionTemplate {
  id: string;
  name: string;
  code: string;
  display_order: number;
  start_time: string;
  end_time: string;
  brand_id: string | null;
  is_active: boolean;
  source: 'db' | 'default';
}

interface StoreMarketSession {
  id: string;
  name: string;
  start_time: string;
  end_time: string;
  template_id: string | null;
  menu_plan_id: string | null;
  is_active: boolean;
  created_at: string;
}

// ─── 市别时段卡片 ─────────────────────────────────────────────────────────────

function SessionTemplateCard({
  item,
  onEdit,
  onToggle,
}: {
  item: MarketSessionTemplate;
  onEdit: (item: MarketSessionTemplate) => void;
  onToggle: (id: string, active: boolean) => Promise<void>;
}) {
  const color = SESSION_COLOR[item.code] ?? '#FF6B35';
  return (
    <Card
      size="small"
      style={{
        borderTop: `4px solid ${color}`,
        opacity: item.is_active ? 1 : 0.5,
        transition: 'opacity 0.2s',
      }}
      actions={[
        <Tooltip title="编辑" key="edit">
          <Button
            type="text"
            icon={<EditOutlined />}
            size="small"
            onClick={() => onEdit(item)}
          />
        </Tooltip>,
        <Tooltip title={item.is_active ? '禁用' : '启用'} key="toggle">
          <Popconfirm
            title={`确认${item.is_active ? '禁用' : '启用'}「${item.name}」？`}
            onConfirm={() => onToggle(item.id, !item.is_active)}
            okText="确认"
            cancelText="取消"
          >
            <Button
              type="text"
              icon={<StopOutlined />}
              size="small"
              danger={item.is_active}
            />
          </Popconfirm>
        </Tooltip>,
      ]}
    >
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Space>
          <Tag color={color} style={{ fontWeight: 600, fontSize: 14 }}>
            {item.name}
          </Tag>
          {item.source === 'default' && (
            <Tag color="default" style={{ fontSize: 11 }}>默认</Tag>
          )}
          {!item.is_active && <Tag color="red">已禁用</Tag>}
        </Space>
        <Space>
          <ClockCircleOutlined style={{ color: '#8C8C8C' }} />
          <Text style={{ fontSize: 16, fontWeight: 500 }}>
            {item.start_time.slice(0, 5)} — {item.end_time.slice(0, 5)}
          </Text>
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>
          代码：{item.code}
        </Text>
      </Space>
    </Card>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function MarketSessionPage() {
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<MarketSessionTemplate | null>(null);
  const [storeSessionModalOpen, setStoreSessionModalOpen] = useState(false);
  const [selectedStoreId, setSelectedStoreId] = useState<string>('');
  const [templateForm] = Form.useForm();
  const [storeSessionForm] = Form.useForm();

  // ── 加载集团模板 ──
  const {
    data: templatesData,
    loading: templatesLoading,
    refresh: refreshTemplates,
  } = useRequest(
    () => apiFetch<{ items: MarketSessionTemplate[] }>(`${API_BASE}/templates`),
    { refreshDeps: [] }
  );

  // ── 加载门店市别 ──
  const {
    data: storeSessionsData,
    loading: storeSessionsLoading,
    refresh: refreshStoreSessions,
  } = useRequest(
    () =>
      selectedStoreId
        ? apiFetch<{ items: StoreMarketSession[] }>(`${API_BASE}/store/${selectedStoreId}`)
        : Promise.resolve({ items: [] }),
    { refreshDeps: [selectedStoreId] }
  );

  // ── 保存集团模板 ──
  const handleSaveTemplate = useCallback(async () => {
    const values = await templateForm.validateFields();
    const payload = {
      ...values,
      start_time: values.time_range?.[0]?.format('HH:mm') ?? values.start_time,
      end_time: values.time_range?.[1]?.format('HH:mm') ?? values.end_time,
    };
    delete payload.time_range;

    if (editingTemplate && editingTemplate.source === 'db') {
      await apiFetch(`${API_BASE}/templates/${editingTemplate.id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      message.success('市别模板已更新');
    } else {
      await apiFetch(`${API_BASE}/templates`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      message.success('市别模板已创建');
    }
    setTemplateModalOpen(false);
    setEditingTemplate(null);
    templateForm.resetFields();
    refreshTemplates();
  }, [editingTemplate, templateForm, refreshTemplates]);

  // ── 禁用/启用集团模板 ──
  const handleToggleTemplate = useCallback(
    async (id: string, active: boolean) => {
      await apiFetch(`${API_BASE}/templates/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_active: active }),
      });
      message.success(active ? '已启用' : '已禁用');
      refreshTemplates();
    },
    [refreshTemplates]
  );

  // ── 编辑模板打开弹窗 ──
  const handleEditTemplate = useCallback(
    (item: MarketSessionTemplate) => {
      setEditingTemplate(item);
      templateForm.setFieldsValue({
        name: item.name,
        code: item.code,
        display_order: item.display_order,
        time_range: [
          dayjs(item.start_time, 'HH:mm:ss'),
          dayjs(item.end_time, 'HH:mm:ss'),
        ],
        is_active: item.is_active,
      });
      setTemplateModalOpen(true);
    },
    [templateForm]
  );

  // ── 新建门店市别 ──
  const handleSaveStoreSession = useCallback(async () => {
    if (!selectedStoreId) { message.warning('请先选择门店'); return; }
    const values = await storeSessionForm.validateFields();
    const payload = {
      ...values,
      start_time: values.time_range?.[0]?.format('HH:mm') ?? values.start_time,
      end_time: values.time_range?.[1]?.format('HH:mm') ?? values.end_time,
    };
    delete payload.time_range;
    await apiFetch(`${API_BASE}/store/${selectedStoreId}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    message.success('门店市别配置已添加');
    setStoreSessionModalOpen(false);
    storeSessionForm.resetFields();
    refreshStoreSessions();
  }, [selectedStoreId, storeSessionForm, refreshStoreSessions]);

  // ── 删除门店市别 ──
  const handleDeleteStoreSession = useCallback(
    async (id: string) => {
      await apiFetch(`${API_BASE}/${id}`, { method: 'DELETE' });
      message.success('已禁用');
      refreshStoreSessions();
    },
    [refreshStoreSessions]
  );

  const templates = templatesData?.items ?? [];
  const storeSessions = storeSessionsData?.items ?? [];

  // 门店市别表格列
  const storeSessionColumns = [
    {
      title: '市别名称',
      dataIndex: 'name',
      render: (name: string) => (
        <Text style={{ fontWeight: 500 }}>{name}</Text>
      ),
    },
    {
      title: '时间段',
      render: (_: unknown, r: StoreMarketSession) => (
        <Space>
          <ClockCircleOutlined />
          <Text>
            {r.start_time.slice(0, 5)} — {r.end_time.slice(0, 5)}
          </Text>
        </Space>
      ),
    },
    {
      title: '来源',
      render: (_: unknown, r: StoreMarketSession) =>
        r.template_id ? (
          <Tag color="blue">引用模板</Tag>
        ) : (
          <Tag color="orange">门店自定义</Tag>
        ),
    },
    {
      title: '绑定菜谱',
      render: (_: unknown, r: StoreMarketSession) =>
        r.menu_plan_id ? (
          <Tag color="green">已绑定</Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      render: (v: boolean) => (
        <Switch checked={v} size="small" disabled />
      ),
    },
    {
      title: '操作',
      render: (_: unknown, r: StoreMarketSession) => (
        <Popconfirm
          title={`确认禁用「${r.name}」？`}
          onConfirm={() => handleDeleteStoreSession(r.id)}
          okText="确认"
          cancelText="取消"
        >
          <Button type="link" danger size="small">
            禁用
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <ConfigProvider theme={txAdminTheme}>
      <div style={{ padding: 24 }}>
        {/* ── 标题栏 ── */}
        <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
          <Col>
            <Title level={4} style={{ margin: 0 }}>营业市别管理</Title>
            <Text type="secondary">配置早市/午市/晚市/夜宵的营业时段，开台时自动关联</Text>
          </Col>
        </Row>

        {/* ══════════════════════ 上部：集团市别模板 ══════════════════════ */}
        <Card
          title={
            <Space>
              <ClockCircleOutlined style={{ color: '#FF6B35' }} />
              <span>集团市别模板</span>
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                （定义全集团通用的营业时段，门店可基于此覆盖）
              </Text>
            </Space>
          }
          extra={
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditingTemplate(null);
                templateForm.resetFields();
                setTemplateModalOpen(true);
              }}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              新增市别模板
            </Button>
          }
          style={{ marginBottom: 24 }}
          loading={templatesLoading}
        >
          <Row gutter={[16, 16]}>
            {templates.length === 0 ? (
              <Col span={24}>
                <Text type="secondary">暂无模板，点击右上角新增</Text>
              </Col>
            ) : (
              templates.map((item) => (
                <Col xs={24} sm={12} md={6} key={item.id}>
                  <SessionTemplateCard
                    item={item}
                    onEdit={handleEditTemplate}
                    onToggle={handleToggleTemplate}
                  />
                </Col>
              ))
            )}
          </Row>
        </Card>

        {/* ══════════════════════ 下部：门店市别配置 ══════════════════════ */}
        <Card
          title={
            <Space>
              <span>门店市别配置</span>
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
                （可为单个门店覆盖集团模板时间段）
              </Text>
            </Space>
          }
          extra={
            <Space>
              <Select
                placeholder="选择门店"
                style={{ width: 200 }}
                allowClear
                onChange={(v) => setSelectedStoreId(v ?? '')}
                // 实际项目中通过 API 加载门店列表，此处用占位数据
                options={[
                  { label: '徐记海鲜·五一广场店', value: 'store-001' },
                  { label: '徐记海鲜·梅溪湖店', value: 'store-002' },
                ]}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                disabled={!selectedStoreId}
                onClick={() => setStoreSessionModalOpen(true)}
                style={selectedStoreId ? { background: '#FF6B35', borderColor: '#FF6B35' } : {}}
              >
                添加门店市别
              </Button>
            </Space>
          }
        >
          {!selectedStoreId ? (
            <div style={{ textAlign: 'center', padding: '32px 0', color: '#B4B2A9' }}>
              请先选择门店
            </div>
          ) : (
            <Table
              columns={storeSessionColumns}
              dataSource={storeSessions}
              rowKey="id"
              loading={storeSessionsLoading}
              pagination={false}
              size="middle"
              locale={{ emptyText: '该门店暂无自定义市别配置，将使用集团模板' }}
            />
          )}
        </Card>

        {/* ── 集团模板 新增/编辑 弹窗 ── */}
        <Modal
          title={editingTemplate ? `编辑市别：${editingTemplate.name}` : '新增市别模板'}
          open={templateModalOpen}
          onOk={handleSaveTemplate}
          onCancel={() => {
            setTemplateModalOpen(false);
            setEditingTemplate(null);
            templateForm.resetFields();
          }}
          okText="保存"
          cancelText="取消"
          okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
          destroyOnClose
        >
          <Form form={templateForm} layout="vertical" style={{ marginTop: 16 }}>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="name"
                  label="市别名称"
                  rules={[{ required: true, message: '请输入名称' }]}
                >
                  <Input placeholder="如：早市" maxLength={50} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="code"
                  label="代码"
                  rules={[{ required: true, message: '请选择代码' }]}
                >
                  <Select
                    placeholder="选择代码"
                    options={Object.entries(SESSION_LABEL).map(([v, l]) => ({
                      value: v,
                      label: `${l}（${v}）`,
                    }))}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item
              name="time_range"
              label="营业时段"
              rules={[{ required: true, message: '请选择时段' }]}
              extra="夜宵可设置跨夜时段，如 21:00 — 次日 02:00"
            >
              <TimePicker.RangePicker
                format="HH:mm"
                style={{ width: '100%' }}
                placeholder={['开始时间', '结束时间']}
              />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="display_order" label="排列顺序" initialValue={0}>
                  <Input type="number" min={0} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="is_active" label="是否启用" valuePropName="checked" initialValue>
                  <Switch />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Modal>

        {/* ── 门店市别 新增 弹窗 ── */}
        <Modal
          title="添加门店市别配置"
          open={storeSessionModalOpen}
          onOk={handleSaveStoreSession}
          onCancel={() => {
            setStoreSessionModalOpen(false);
            storeSessionForm.resetFields();
          }}
          okText="保存"
          cancelText="取消"
          okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
          destroyOnClose
        >
          <Form form={storeSessionForm} layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item
              name="name"
              label="市别名称"
              rules={[{ required: true, message: '请输入名称' }]}
            >
              <Input placeholder="如：午市（徐记版）" maxLength={50} />
            </Form.Item>
            <Form.Item
              name="time_range"
              label="营业时段"
              rules={[{ required: true, message: '请选择时段' }]}
              extra="覆盖集团模板时间，仅对本门店生效"
            >
              <TimePicker.RangePicker
                format="HH:mm"
                style={{ width: '100%' }}
                placeholder={['开始时间', '结束时间']}
              />
            </Form.Item>
            <Form.Item name="template_id" label="引用集团模板（可选）">
              <Select
                allowClear
                placeholder="不引用则视为门店自定义"
                options={(templatesData?.items ?? []).map((t) => ({
                  value: t.id,
                  label: `${t.name}（${t.start_time.slice(0, 5)}–${t.end_time.slice(0, 5)}）`,
                }))}
              />
            </Form.Item>
            <Form.Item name="is_active" label="是否启用" valuePropName="checked" initialValue>
              <Switch />
            </Form.Item>
          </Form>
        </Modal>
      </div>
    </ConfigProvider>
  );
}

export default MarketSessionPage;
