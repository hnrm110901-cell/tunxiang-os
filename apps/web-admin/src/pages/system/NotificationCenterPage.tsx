/**
 * NotificationCenterPage -- 通知中心
 * 域F . 系统设置 . 通知中心
 *
 * Tab1: 消息列表 -- 分类筛选 + 消息列表 + 详情展开 + 批量操作
 * Tab2: 发送通知 -- 模板选择 + 目标选择 + 渠道选择 + 预览发送
 * Tab3: 模板管理 -- ProTable + 编辑模板 ModalForm
 *
 * API: tx-ops :8005, try/catch 降级 Mock
 */

import { useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Menu,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  BellOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  MailOutlined,
  MobileOutlined,
  PlusOutlined,
  ReadOutlined,
  ReloadOutlined,
  SearchOutlined,
  SendOutlined,
  WechatOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

const BASE = 'http://localhost:8005';

// ─── 类型定义 ───

interface Notification {
  id: string;
  target_type: string;
  target_id: string | null;
  channel: string;
  title: string;
  content: string;
  category: string;
  priority: string;
  status: string;
  sent_at: string | null;
  read_at: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

interface NotificationTemplate {
  id: string;
  name: string;
  code: string;
  channel: string;
  category: string;
  title_template: string;
  content_template: string;
  variables: TemplateVariable[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface TemplateVariable {
  name: string;
  type: string;
  required: boolean;
  default?: string;
}

// ─── 常量 ───

const CATEGORY_OPTIONS = [
  { label: '全部', value: '' },
  { label: '订单', value: 'order' },
  { label: '营销', value: 'promotion' },
  { label: '系统', value: 'system' },
  { label: '预警', value: 'alert' },
  { label: '提醒', value: 'reminder' },
];

const CATEGORY_MAP: Record<string, { label: string; color: string }> = {
  order: { label: '订单', color: 'blue' },
  promotion: { label: '营销', color: 'green' },
  system: { label: '系统', color: 'default' },
  alert: { label: '预警', color: 'orange' },
  reminder: { label: '提醒', color: 'purple' },
};

const PRIORITY_MAP: Record<string, { label: string; color: string }> = {
  low: { label: '低', color: 'default' },
  normal: { label: '普通', color: 'blue' },
  high: { label: '高', color: 'orange' },
  urgent: { label: '紧急', color: 'red' },
};

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: '待发送', color: 'default' },
  sent: { label: '已发送', color: 'blue' },
  delivered: { label: '已送达', color: 'cyan' },
  read: { label: '已读', color: 'green' },
  failed: { label: '失败', color: 'red' },
};

const CHANNEL_MAP: Record<string, { label: string; icon: React.ReactNode }> = {
  wechat: { label: '微信模板消息', icon: <WechatOutlined /> },
  sms: { label: '短信', icon: <MobileOutlined /> },
  push: { label: 'APP推送', icon: <BellOutlined /> },
  in_app: { label: '站内信', icon: <MailOutlined /> },
};

const TENANT_HEADER = { 'X-Tenant-ID': 'demo-tenant-001' };

// ─── API 辅助 ───

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...TENANT_HEADER, ...init?.headers },
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.detail || '请求失败');
  return json.data as T;
}

// ─── Tab1: 消息列表 ───

function MessageListTab() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState('');
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [detailDrawer, setDetailDrawer] = useState<Notification | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);

  const fetchNotifications = async (cat?: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: '1', size: '50' });
      if (cat) params.set('category', cat);
      const data = await apiFetch<{ items: Notification[]; total: number }>(
        `/api/v1/ops/notifications?${params}`
      );
      setNotifications(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载通知列表失败，使用本地数据');
    } finally {
      setLoading(false);
    }
  };

  const fetchUnreadCount = async () => {
    try {
      const data = await apiFetch<{ unread_count: number }>(
        '/api/v1/ops/notifications/unread-count'
      );
      setUnreadCount(data.unread_count);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    fetchNotifications();
    fetchUnreadCount();
  }, []);

  const handleCategoryChange = (cat: string) => {
    setCategory(cat);
    fetchNotifications(cat || undefined);
  };

  const handleMarkRead = async (id: string) => {
    try {
      await apiFetch(`/api/v1/ops/notifications/${id}/read`, { method: 'PATCH' });
      message.success('已标记为已读');
      fetchNotifications(category || undefined);
      fetchUnreadCount();
    } catch {
      message.error('操作失败');
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await apiFetch('/api/v1/ops/notifications/mark-all-read', { method: 'POST' });
      message.success('已全部标记为已读');
      fetchNotifications(category || undefined);
      fetchUnreadCount();
    } catch {
      message.error('操作失败');
    }
  };

  const isUnread = (n: Notification) => n.status !== 'read' && !n.read_at;

  return (
    <Row gutter={16}>
      {/* 左侧分类筛选 */}
      <Col span={5}>
        <Card size="small" title="消息分类" styles={{ body: { padding: 0 } }}>
          <Menu
            mode="inline"
            selectedKeys={[category || '']}
            onClick={({ key }) => handleCategoryChange(key)}
            items={CATEGORY_OPTIONS.map((opt) => ({
              key: opt.value,
              label: (
                <Space>
                  {opt.label}
                  {opt.value === '' && unreadCount > 0 && (
                    <Badge count={unreadCount} size="small" />
                  )}
                </Space>
              ),
            }))}
          />
        </Card>
      </Col>

      {/* 右侧消息列表 */}
      <Col span={19}>
        <Card
          size="small"
          title={
            <Space>
              <BellOutlined />
              消息列表
              <Text type="secondary">共 {total} 条</Text>
            </Space>
          }
          extra={
            <Space>
              <Button
                icon={<CheckOutlined />}
                onClick={handleMarkAllRead}
                disabled={unreadCount === 0}
              >
                全部已读
              </Button>
              <Button
                icon={<DeleteOutlined />}
                danger
                disabled={selectedKeys.length === 0}
                onClick={() => message.info('Mock: 删除选中通知')}
              >
                删除选中
              </Button>
              <Button
                icon={<ReloadOutlined />}
                onClick={() => fetchNotifications(category || undefined)}
              />
            </Space>
          }
        >
          <List
            loading={loading}
            dataSource={notifications}
            locale={{ emptyText: <Empty description="暂无通知" /> }}
            renderItem={(item) => (
              <List.Item
                key={item.id}
                style={{
                  background: isUnread(item) ? '#f6ffed' : undefined,
                  padding: '12px 16px',
                  cursor: 'pointer',
                  borderLeft: isUnread(item) ? '3px solid #1677ff' : '3px solid transparent',
                }}
                onClick={() => setDetailDrawer(item)}
                actions={[
                  isUnread(item) ? (
                    <Button
                      key="read"
                      type="link"
                      size="small"
                      icon={<ReadOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleMarkRead(item.id);
                      }}
                    >
                      标记已读
                    </Button>
                  ) : (
                    <Tag key="read-tag" color="green" icon={<CheckCircleOutlined />}>
                      已读
                    </Tag>
                  ),
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      {isUnread(item) && (
                        <Badge status="processing" />
                      )}
                      <Text strong={isUnread(item)}>{item.title}</Text>
                      {PRIORITY_MAP[item.priority]?.color !== 'default' &&
                        PRIORITY_MAP[item.priority]?.color !== 'blue' && (
                          <Tag color={PRIORITY_MAP[item.priority]?.color}>
                            {PRIORITY_MAP[item.priority]?.label}
                          </Tag>
                        )}
                      <Tag>{CATEGORY_MAP[item.category]?.label || item.category}</Tag>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={0}>
                      <Text type="secondary" ellipsis style={{ maxWidth: 600 }}>
                        {item.content}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {CHANNEL_MAP[item.channel]?.icon}{' '}
                        {CHANNEL_MAP[item.channel]?.label || item.channel}
                        {' | '}
                        {item.sent_at
                          ? dayjs(item.sent_at).format('YYYY-MM-DD HH:mm')
                          : dayjs(item.created_at).format('YYYY-MM-DD HH:mm')}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        </Card>

        {/* 详情抽屉 */}
        <Drawer
          title="通知详情"
          open={!!detailDrawer}
          onClose={() => setDetailDrawer(null)}
          width={480}
        >
          {detailDrawer && (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="标题">
                  <Text strong>{detailDrawer.title}</Text>
                </Descriptions.Item>
                <Descriptions.Item label="分类">
                  <Tag color={CATEGORY_MAP[detailDrawer.category]?.color}>
                    {CATEGORY_MAP[detailDrawer.category]?.label || detailDrawer.category}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="优先级">
                  <Tag color={PRIORITY_MAP[detailDrawer.priority]?.color}>
                    {PRIORITY_MAP[detailDrawer.priority]?.label}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={STATUS_MAP[detailDrawer.status]?.color}>
                    {STATUS_MAP[detailDrawer.status]?.label || detailDrawer.status}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="渠道">
                  <Space>
                    {CHANNEL_MAP[detailDrawer.channel]?.icon}
                    {CHANNEL_MAP[detailDrawer.channel]?.label || detailDrawer.channel}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="目标类型">
                  {detailDrawer.target_type}
                </Descriptions.Item>
                <Descriptions.Item label="发送时间">
                  {detailDrawer.sent_at
                    ? dayjs(detailDrawer.sent_at).format('YYYY-MM-DD HH:mm:ss')
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="阅读时间">
                  {detailDrawer.read_at
                    ? dayjs(detailDrawer.read_at).format('YYYY-MM-DD HH:mm:ss')
                    : '-'}
                </Descriptions.Item>
              </Descriptions>
              <Card size="small" title="通知内容">
                <Paragraph>{detailDrawer.content}</Paragraph>
              </Card>
              {detailDrawer.metadata && (
                <Card size="small" title="扩展信息">
                  <pre style={{ fontSize: 12, margin: 0 }}>
                    {JSON.stringify(detailDrawer.metadata, null, 2)}
                  </pre>
                </Card>
              )}
              {isUnread(detailDrawer) && (
                <Button
                  type="primary"
                  icon={<ReadOutlined />}
                  block
                  onClick={() => {
                    handleMarkRead(detailDrawer.id);
                    setDetailDrawer(null);
                  }}
                >
                  标记为已读
                </Button>
              )}
            </Space>
          )}
        </Drawer>
      </Col>
    </Row>
  );
}

// ─── Tab2: 发送通知 ───

function SendNotificationTab() {
  const [templates, setTemplates] = useState<NotificationTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<NotificationTemplate | null>(null);
  const [targetType, setTargetType] = useState<string>('all');
  const [targetId, setTargetId] = useState('');
  const [channel, setChannel] = useState<string>('wechat');
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [previewVisible, setPreviewVisible] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const data = await apiFetch<{ items: NotificationTemplate[] }>(
          '/api/v1/ops/notification-templates?size=100'
        );
        setTemplates(data.items.filter((t) => t.is_active));
      } catch {
        message.error('加载模板列表失败');
      }
    })();
  }, []);

  const handleTemplateSelect = (code: string) => {
    const tpl = templates.find((t) => t.code === code) || null;
    setSelectedTemplate(tpl);
    if (tpl) {
      setChannel(tpl.channel);
      // 重置变量
      const vars: Record<string, string> = {};
      tpl.variables.forEach((v) => {
        vars[v.name] = v.default || '';
      });
      setVariables(vars);
    }
  };

  const renderPreview = (): { title: string; content: string } => {
    if (!selectedTemplate) return { title: '', content: '' };
    let title = selectedTemplate.title_template;
    let content = selectedTemplate.content_template;
    Object.entries(variables).forEach(([key, value]) => {
      title = title.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), value || `{{${key}}}`);
      content = content.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), value || `{{${key}}}`);
    });
    return { title, content };
  };

  const handleSend = async () => {
    if (!selectedTemplate) {
      message.warning('请先选择模板');
      return;
    }
    setSending(true);
    try {
      const result = await apiFetch<Record<string, unknown>>(
        '/api/v1/ops/notifications/send',
        {
          method: 'POST',
          body: JSON.stringify({
            template_code: selectedTemplate.code,
            target_type: targetType,
            target_id: targetType === 'all' ? null : targetId || null,
            channel,
            variables,
          }),
        }
      );
      message.success(`通知已发送，ID: ${result.id}`);
      setPreviewVisible(false);
    } catch {
      message.error('发送失败');
    } finally {
      setSending(false);
    }
  };

  const preview = renderPreview();

  return (
    <Row gutter={24}>
      <Col span={14}>
        <Card title="编辑通知" size="small">
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {/* 模板选择 */}
            <div>
              <Text strong>选择模板</Text>
              <Select
                style={{ width: '100%', marginTop: 8 }}
                placeholder="请选择通知模板"
                value={selectedTemplate?.code}
                onChange={handleTemplateSelect}
                options={templates.map((t) => ({
                  label: (
                    <Space>
                      {t.name}
                      <Tag>{CATEGORY_MAP[t.category]?.label || t.category}</Tag>
                      <Tag>{CHANNEL_MAP[t.channel]?.label || t.channel}</Tag>
                    </Space>
                  ),
                  value: t.code,
                }))}
              />
            </div>

            {/* 目标选择 */}
            <div>
              <Text strong>发送目标</Text>
              <div style={{ marginTop: 8 }}>
                <Radio.Group
                  value={targetType}
                  onChange={(e) => {
                    setTargetType(e.target.value);
                    setTargetId('');
                  }}
                >
                  <Radio.Button value="all">全部客户</Radio.Button>
                  <Radio.Button value="store">指定门店</Radio.Button>
                  <Radio.Button value="customer">指定客户</Radio.Button>
                  <Radio.Button value="employee">指定员工</Radio.Button>
                </Radio.Group>
              </div>
              {targetType !== 'all' && (
                <Input
                  style={{ marginTop: 8 }}
                  placeholder={`请输入${
                    targetType === 'store' ? '门店' : targetType === 'customer' ? '客户' : '员工'
                  }ID`}
                  value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}
                />
              )}
            </div>

            {/* 渠道选择 */}
            <div>
              <Text strong>发送渠道</Text>
              <div style={{ marginTop: 8 }}>
                <Radio.Group value={channel} onChange={(e) => setChannel(e.target.value)}>
                  <Radio.Button value="wechat">
                    <WechatOutlined /> 微信模板消息
                  </Radio.Button>
                  <Radio.Button value="sms">
                    <MobileOutlined /> 短信
                  </Radio.Button>
                  <Radio.Button value="push">
                    <BellOutlined /> APP推送
                  </Radio.Button>
                  <Radio.Button value="in_app">
                    <MailOutlined /> 站内信
                  </Radio.Button>
                </Radio.Group>
              </div>
            </div>

            {/* 模板变量 */}
            {selectedTemplate && selectedTemplate.variables.length > 0 && (
              <div>
                <Text strong>模板变量</Text>
                <div style={{ marginTop: 8 }}>
                  {selectedTemplate.variables.map((v) => (
                    <div key={v.name} style={{ marginBottom: 8 }}>
                      <Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                        {v.name}
                        {v.required && <Tag color="red" style={{ marginLeft: 4 }}>必填</Tag>}
                      </Text>
                      <Input
                        placeholder={v.default || `请输入 ${v.name}`}
                        value={variables[v.name] || ''}
                        onChange={(e) =>
                          setVariables((prev) => ({ ...prev, [v.name]: e.target.value }))
                        }
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <Space>
              <Button
                type="primary"
                icon={<EyeOutlined />}
                disabled={!selectedTemplate}
                onClick={() => setPreviewVisible(true)}
              >
                预览并发送
              </Button>
            </Space>
          </Space>
        </Card>
      </Col>

      {/* 右侧实时预览 */}
      <Col span={10}>
        <Card title="实时预览" size="small">
          {selectedTemplate ? (
            <Space direction="vertical" style={{ width: '100%' }}>
              <div>
                <Text type="secondary">标题</Text>
                <Title level={5} style={{ margin: '4px 0 12px' }}>
                  {preview.title}
                </Title>
              </div>
              <div>
                <Text type="secondary">内容</Text>
                <Paragraph style={{ marginTop: 4, padding: 12, background: '#fafafa', borderRadius: 6 }}>
                  {preview.content}
                </Paragraph>
              </div>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="渠道">
                  <Space>
                    {CHANNEL_MAP[channel]?.icon}
                    {CHANNEL_MAP[channel]?.label}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="目标">
                  {targetType === 'all' ? '全部' : `${targetType}: ${targetId || '未指定'}`}
                </Descriptions.Item>
                <Descriptions.Item label="分类">
                  <Tag color={CATEGORY_MAP[selectedTemplate.category]?.color}>
                    {CATEGORY_MAP[selectedTemplate.category]?.label}
                  </Tag>
                </Descriptions.Item>
              </Descriptions>
            </Space>
          ) : (
            <Empty description="请先选择模板" />
          )}
        </Card>
      </Col>

      {/* 发送确认弹窗 */}
      <Modal
        title="确认发送通知"
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        onOk={handleSend}
        confirmLoading={sending}
        okText="确认发送"
        cancelText="取消"
        width={520}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Card size="small">
            <Title level={5}>{preview.title}</Title>
            <Paragraph>{preview.content}</Paragraph>
          </Card>
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="渠道">
              {CHANNEL_MAP[channel]?.label}
            </Descriptions.Item>
            <Descriptions.Item label="目标">
              {targetType === 'all' ? '全部客户' : `${targetType}: ${targetId}`}
            </Descriptions.Item>
          </Descriptions>
        </Space>
      </Modal>
    </Row>
  );
}

// ─── Tab3: 模板管理 ───

function TemplateManageTab() {
  const actionRef = useRef<ActionType>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<NotificationTemplate | null>(null);

  const columns: ProColumns<NotificationTemplate>[] = [
    {
      title: '模板名称',
      dataIndex: 'name',
      width: 160,
      ellipsis: true,
    },
    {
      title: '模板代码',
      dataIndex: 'code',
      width: 140,
      copyable: true,
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 120,
      render: (_, r) => (
        <Space>
          {CHANNEL_MAP[r.channel]?.icon}
          {CHANNEL_MAP[r.channel]?.label || r.channel}
        </Space>
      ),
      valueEnum: {
        wechat: { text: '微信' },
        sms: { text: '短信' },
        push: { text: '推送' },
        in_app: { text: '站内信' },
      },
    },
    {
      title: '分类',
      dataIndex: 'category',
      width: 80,
      render: (_, r) => (
        <Tag color={CATEGORY_MAP[r.category]?.color}>
          {CATEGORY_MAP[r.category]?.label || r.category}
        </Tag>
      ),
      valueEnum: {
        order: { text: '订单' },
        promotion: { text: '营销' },
        system: { text: '系统' },
        alert: { text: '预警' },
        reminder: { text: '提醒' },
      },
    },
    {
      title: '变量数',
      dataIndex: 'variables',
      width: 70,
      search: false,
      render: (_, r) => <Tag>{r.variables?.length || 0}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (_, r) =>
        r.is_active ? (
          <Badge status="success" text="启用" />
        ) : (
          <Badge status="default" text="停用" />
        ),
      valueEnum: {
        true: { text: '启用' },
        false: { text: '停用' },
      },
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 150,
      search: false,
      render: (_, r) => dayjs(r.updated_at).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, record) => [
        <Button
          key="edit"
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            setEditingTemplate(record);
            setEditModalOpen(true);
          }}
        >
          编辑
        </Button>,
      ],
    },
  ];

  return (
    <>
      <ProTable<NotificationTemplate>
        columns={columns}
        actionRef={actionRef}
        rowKey="id"
        headerTitle="通知模板"
        search={{ labelWidth: 'auto' }}
        request={async (params) => {
          try {
            const qs = new URLSearchParams({
              page: String(params.current || 1),
              size: String(params.pageSize || 20),
            });
            if (params.channel) qs.set('channel', params.channel);
            if (params.category) qs.set('category', params.category);
            const data = await apiFetch<{ items: NotificationTemplate[]; total: number }>(
              `/api/v1/ops/notification-templates?${qs}`
            );
            return { data: data.items, total: data.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ defaultPageSize: 20 }}
      />

      <ModalForm
        title={editingTemplate ? '编辑模板' : '新建模板'}
        open={editModalOpen}
        onOpenChange={(open) => {
          setEditModalOpen(open);
          if (!open) setEditingTemplate(null);
        }}
        initialValues={
          editingTemplate
            ? {
                name: editingTemplate.name,
                code: editingTemplate.code,
                channel: editingTemplate.channel,
                category: editingTemplate.category,
                title_template: editingTemplate.title_template,
                content_template: editingTemplate.content_template,
                is_active: editingTemplate.is_active,
              }
            : { is_active: true }
        }
        onFinish={async (values) => {
          try {
            if (editingTemplate) {
              await apiFetch(`/api/v1/ops/notification-templates/${editingTemplate.id}`, {
                method: 'PUT',
                body: JSON.stringify(values),
              });
              message.success('模板已更新');
            } else {
              message.success('Mock: 模板已创建');
            }
            actionRef.current?.reload();
            return true;
          } catch {
            message.error('操作失败');
            return false;
          }
        }}
        width={640}
      >
        <ProFormText
          name="name"
          label="模板名称"
          rules={[{ required: true, message: '请输入模板名称' }]}
        />
        <ProFormText
          name="code"
          label="模板代码"
          rules={[{ required: true, message: '请输入模板代码' }]}
          disabled={!!editingTemplate}
        />
        <ProFormSelect
          name="channel"
          label="渠道"
          rules={[{ required: true }]}
          options={[
            { label: '微信模板消息', value: 'wechat' },
            { label: '短信', value: 'sms' },
            { label: 'APP推送', value: 'push' },
            { label: '站内信', value: 'in_app' },
          ]}
        />
        <ProFormSelect
          name="category"
          label="分类"
          rules={[{ required: true }]}
          options={[
            { label: '订单', value: 'order' },
            { label: '营销', value: 'promotion' },
            { label: '系统', value: 'system' },
            { label: '预警', value: 'alert' },
            { label: '提醒', value: 'reminder' },
          ]}
        />
        <ProFormText
          name="title_template"
          label="标题模板"
          rules={[{ required: true }]}
          tooltip="支持 {{variable}} 变量"
        />
        <ProFormTextArea
          name="content_template"
          label="内容模板"
          rules={[{ required: true }]}
          fieldProps={{ rows: 4 }}
          tooltip="支持 {{variable}} 变量"
        />
        <ProFormSwitch name="is_active" label="启用状态" />
      </ModalForm>
    </>
  );
}

// ─── 主组件 ───

export function NotificationCenterPage() {
  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <BellOutlined /> 通知中心
      </Title>
      <Tabs
        defaultActiveKey="messages"
        items={[
          {
            key: 'messages',
            label: (
              <span>
                <MailOutlined /> 消息列表
              </span>
            ),
            children: <MessageListTab />,
          },
          {
            key: 'send',
            label: (
              <span>
                <SendOutlined /> 发送通知
              </span>
            ),
            children: <SendNotificationTab />,
          },
          {
            key: 'templates',
            label: (
              <span>
                <EditOutlined /> 模板管理
              </span>
            ),
            children: <TemplateManageTab />,
          },
        ]}
      />
    </div>
  );
}
