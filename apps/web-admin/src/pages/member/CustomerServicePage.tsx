/**
 * CustomerServicePage — 客服工单管理页
 * 调用 POST /api/v1/brain/customer-service/handle
 * 支持 AI 分析生成回复 + 工单历史（localStorage）
 */
import { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Input,
  List,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CustomerServiceOutlined,
  ExclamationCircleOutlined,
  RobotOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { Option } = Select;

// ─── 类型定义 ───

interface CSHandlePayload {
  channel: string;
  message: string;
  message_type: string;
  customer_tier: string;
}

interface CSHandleResult {
  intent: string;
  sentiment: 'positive' | 'neutral' | 'negative' | 'angry';
  suggested_reply: string;
  action_suggestions: string[];
  escalate_to_human: boolean;
}

interface WorkOrder {
  id: string;
  created_at: string;
  channel: string;
  intent: string;
  sentiment: 'positive' | 'neutral' | 'negative' | 'angry';
  escalated: boolean;
  reply_sent: boolean;
  payload: CSHandlePayload;
  result: CSHandleResult;
}

// ─── 常量 ───

const CHANNELS = [
  { value: 'wechat_oa', label: '微信公众号' },
  { value: 'miniapp', label: '小程序' },
  { value: 'dianping', label: '大众点评' },
  { value: 'phone', label: '电话' },
  { value: 'dine_in', label: '堂食' },
];

const MESSAGE_TYPES = [
  { value: 'complaint', label: '投诉' },
  { value: 'inquiry', label: '咨询' },
  { value: 'feedback', label: '反馈' },
  { value: 'praise', label: '表扬' },
];

const CUSTOMER_TIERS = [
  { value: 'vip', label: 'VIP' },
  { value: 'regular', label: '普通会员' },
  { value: 'new', label: '新客' },
];

const INTENT_LABELS: Record<string, { label: string; color: string }> = {
  food_quality:    { label: '食品质量', color: '#A32D2D' },
  wait_time:       { label: '等待时间', color: '#BA7517' },
  wrong_dish:      { label: '上错菜',   color: '#E55A28' },
  price:           { label: '价格',     color: '#185FA5' },
  service:         { label: '服务',     color: '#0F6E56' },
  other:           { label: '其他',     color: '#5F5E5A' },
};

const SENTIMENT_CONFIG: Record<string, { label: string; color: string }> = {
  positive: { label: '正面', color: '#0F6E56' },
  neutral:  { label: '中性', color: '#B4B2A9' },
  negative: { label: '负面', color: '#BA7517' },
  angry:    { label: '愤怒', color: '#A32D2D' },
};

const CHANNEL_LABEL: Record<string, string> = {
  wechat_oa: '微信公众号',
  miniapp:   '小程序',
  dianping:  '大众点评',
  phone:     '电话',
  dine_in:   '堂食',
};

const LS_KEY = 'tx_cs_work_orders';
const MAX_ORDERS = 100;


function loadOrders(): WorkOrder[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as WorkOrder[]) : [];
  } catch {
    return [];
  }
}

function saveOrders(orders: WorkOrder[]) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(orders.slice(0, MAX_ORDERS)));
  } catch {
    // ignore storage errors
  }
}

// ─── AI 分析面板 ───

function AIAnalysisPanel({ onOrderCreated }: { onOrderCreated: (order: WorkOrder) => void }) {
  const [form, setForm] = useState<CSHandlePayload>({
    channel: 'wechat_oa',
    message: '',
    message_type: 'complaint',
    customer_tier: 'regular',
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CSHandleResult | null>(null);
  const [editedReply, setEditedReply] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async () => {
    if (!form.message.trim()) {
      message.warning('请输入顾客消息');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await txFetchData<CSHandleResult>('/api/v1/brain/customer-service/handle', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      setResult(data);
      setEditedReply(data.suggested_reply);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'AI 分析失败，请重试';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleMarkSent = () => {
    if (!result) return;
    const order: WorkOrder = {
      id: `cs_${Date.now()}`,
      created_at: new Date().toISOString(),
      channel: form.channel,
      intent: result.intent,
      sentiment: result.sentiment,
      escalated: result.escalate_to_human,
      reply_sent: true,
      payload: { ...form },
      result: { ...result, suggested_reply: editedReply },
    };
    const existing = loadOrders();
    const updated = [order, ...existing];
    saveOrders(updated);
    onOrderCreated(order);
    message.success('工单已记录，回复已标记为已发送');
    setResult(null);
    setEditedReply('');
    setForm({ channel: 'wechat_oa', message: '', message_type: 'complaint', customer_tier: 'regular' });
  };

  const intentCfg = result ? (INTENT_LABELS[result.intent] ?? INTENT_LABELS.other) : null;
  const sentimentCfg = result ? (SENTIMENT_CONFIG[result.sentiment] ?? SENTIMENT_CONFIG.neutral) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 输入表单 */}
      <Card size="small" title="发起 AI 客服分析" style={{ borderRadius: 6 }}>
        <Row gutter={[12, 12]}>
          <Col xs={24} sm={8}>
            <div style={{ marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>渠道</Text>
            </div>
            <Select
              value={form.channel}
              onChange={(v) => setForm((f) => ({ ...f, channel: v }))}
              style={{ width: '100%' }}
            >
              {CHANNELS.map(({ value, label }) => (
                <Option key={value} value={value}>{label}</Option>
              ))}
            </Select>
          </Col>
          <Col xs={24} sm={8}>
            <div style={{ marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>消息类型</Text>
            </div>
            <Select
              value={form.message_type}
              onChange={(v) => setForm((f) => ({ ...f, message_type: v }))}
              style={{ width: '100%' }}
            >
              {MESSAGE_TYPES.map(({ value, label }) => (
                <Option key={value} value={value}>{label}</Option>
              ))}
            </Select>
          </Col>
          <Col xs={24} sm={8}>
            <div style={{ marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>顾客等级</Text>
            </div>
            <Select
              value={form.customer_tier}
              onChange={(v) => setForm((f) => ({ ...f, customer_tier: v }))}
              style={{ width: '100%' }}
            >
              {CUSTOMER_TIERS.map(({ value, label }) => (
                <Option key={value} value={value}>{label}</Option>
              ))}
            </Select>
          </Col>
          <Col span={24}>
            <div style={{ marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>顾客消息</Text>
            </div>
            <TextArea
              rows={4}
              placeholder="粘贴或输入顾客的投诉/咨询/反馈内容..."
              value={form.message}
              onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))}
            />
          </Col>
          <Col span={24}>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={loading}
              onClick={handleAnalyze}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              AI 分析并生成回复
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 错误提示 */}
      {error && (
        <Alert
          type="error"
          message="分析失败"
          description={error}
          showIcon
          closable
          onClose={() => setError(null)}
        />
      )}

      {/* AI 分析结果 */}
      {result && (
        <Card
          size="small"
          title={
            <Space>
              <RobotOutlined style={{ color: '#185FA5' }} />
              <span>AI 分析结果</span>
            </Space>
          }
          style={{ borderRadius: 6 }}
        >
          {/* 升级人工处理警告 */}
          {result.escalate_to_human && (
            <Alert
              type="error"
              message="需要人工介入"
              description="此工单情绪激烈或问题复杂，建议立即转交人工客服处理，避免顾客体验进一步恶化。"
              showIcon
              icon={<ExclamationCircleOutlined />}
              style={{ marginBottom: 12, borderRadius: 6 }}
            />
          )}

          <Row gutter={[12, 12]}>
            {/* 意图 + 情绪 */}
            <Col xs={24} sm={12}>
              <Card size="small" title="意图识别" style={{ borderRadius: 6, background: '#F8F7F5' }}>
                {intentCfg && (
                  <Tag
                    color={intentCfg.color}
                    style={{ fontSize: 14, padding: '4px 12px', borderRadius: 4 }}
                  >
                    {intentCfg.label}
                  </Tag>
                )}
              </Card>
            </Col>
            <Col xs={24} sm={12}>
              <Card size="small" title="情绪状态" style={{ borderRadius: 6, background: '#F8F7F5' }}>
                {sentimentCfg && (
                  <Tag
                    color={sentimentCfg.color}
                    style={{ fontSize: 14, padding: '4px 12px', borderRadius: 4 }}
                  >
                    {sentimentCfg.label}
                  </Tag>
                )}
              </Card>
            </Col>

            {/* 建议回复 */}
            <Col span={24}>
              <Card
                size="small"
                title="建议回复（可编辑后发送给顾客）"
                style={{ borderRadius: 6 }}
              >
                <TextArea
                  rows={5}
                  value={editedReply}
                  onChange={(e) => setEditedReply(e.target.value)}
                />
              </Card>
            </Col>

            {/* 行动建议 */}
            <Col span={24}>
              <Card size="small" title="行动建议" style={{ borderRadius: 6, background: '#F8F7F5' }}>
                <List
                  size="small"
                  dataSource={result.action_suggestions}
                  renderItem={(item) => (
                    <List.Item>
                      <Text>{item}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>

            {/* 操作按钮 */}
            <Col span={24}>
              <Space>
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  onClick={handleMarkSent}
                  style={{ background: '#0F6E56', borderColor: '#0F6E56' }}
                >
                  标记为已回复并存档
                </Button>
                <Button
                  onClick={() => {
                    setResult(null);
                    setEditedReply('');
                  }}
                >
                  放弃
                </Button>
              </Space>
            </Col>
          </Row>
        </Card>
      )}
    </div>
  );
}

// ─── 工单历史 ───

function WorkOrderHistoryPanel({ orders, onRefresh }: { orders: WorkOrder[]; onRefresh: () => void }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState<WorkOrder | null>(null);

  const columns: ProColumns<WorkOrder>[] = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 160,
      render: (val: unknown) => (
        <Text style={{ fontSize: 12 }}>
          {new Date(String(val)).toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
          })}
        </Text>
      ),
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 100,
      render: (val: unknown) => <Tag>{CHANNEL_LABEL[String(val)] ?? String(val)}</Tag>,
    },
    {
      title: '意图',
      dataIndex: 'intent',
      width: 100,
      render: (val: unknown) => {
        const cfg = INTENT_LABELS[String(val)] ?? INTENT_LABELS.other;
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '情绪',
      dataIndex: 'sentiment',
      width: 80,
      render: (val: unknown) => {
        const cfg = SENTIMENT_CONFIG[String(val)] ?? SENTIMENT_CONFIG.neutral;
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '是否升级',
      dataIndex: 'escalated',
      width: 80,
      render: (val: unknown) =>
        val ? <Tag color="red">已升级</Tag> : <Tag color="default">否</Tag>,
    },
    {
      title: '回复状态',
      dataIndex: 'reply_sent',
      width: 90,
      render: (val: unknown) =>
        val ? <Tag color="green">已回复</Tag> : <Tag color="orange">待回复</Tag>,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 80,
      render: (_: unknown, row: WorkOrder) => [
        <a
          key="detail"
          onClick={() => {
            setSelected(row);
            setDrawerOpen(true);
          }}
        >
          详情
        </a>,
      ],
    },
  ];

  return (
    <>
      <Card
        size="small"
        title={`工单历史（共 ${orders.length} 条）`}
        extra={
          <Button size="small" onClick={onRefresh}>
            刷新
          </Button>
        }
        style={{ borderRadius: 6 }}
      >
        <ProTable<WorkOrder>
          dataSource={orders}
          columns={columns}
          rowKey="id"
          search={false}
          pagination={{ pageSize: 10 }}
          toolBarRender={false}
          size="small"
        />
      </Card>

      <Drawer
        title="工单详情"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={480}
      >
        {selected && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Card size="small" title="基本信息" style={{ borderRadius: 6 }}>
              <Row gutter={[8, 8]}>
                <Col span={12}>
                  <Text type="secondary">渠道</Text>
                  <div>
                    <Tag>{CHANNEL_LABEL[selected.channel] ?? selected.channel}</Tag>
                  </div>
                </Col>
                <Col span={12}>
                  <Text type="secondary">顾客等级</Text>
                  <div>{selected.payload.customer_tier}</div>
                </Col>
                <Col span={12}>
                  <Text type="secondary">消息类型</Text>
                  <div>{selected.payload.message_type}</div>
                </Col>
                <Col span={12}>
                  <Text type="secondary">时间</Text>
                  <div>{new Date(selected.created_at).toLocaleString('zh-CN')}</div>
                </Col>
              </Row>
            </Card>

            <Card size="small" title="顾客原始消息" style={{ borderRadius: 6 }}>
              <Text>{selected.payload.message}</Text>
            </Card>

            <Card size="small" title="AI 分析" style={{ borderRadius: 6 }}>
              <Space wrap>
                <span>意图：</span>
                {(() => {
                  const cfg = INTENT_LABELS[selected.intent] ?? INTENT_LABELS.other;
                  return <Tag color={cfg.color}>{cfg.label}</Tag>;
                })()}
                <span>情绪：</span>
                {(() => {
                  const cfg = SENTIMENT_CONFIG[selected.sentiment] ?? SENTIMENT_CONFIG.neutral;
                  return <Tag color={cfg.color}>{cfg.label}</Tag>;
                })()}
              </Space>
            </Card>

            {selected.result.escalate_to_human && (
              <Alert
                type="error"
                message="此工单已标记为需要人工介入"
                showIcon
                style={{ borderRadius: 6 }}
              />
            )}

            <Card size="small" title="回复内容" style={{ borderRadius: 6 }}>
              <Text>{selected.result.suggested_reply}</Text>
            </Card>

            <Card size="small" title="行动建议" style={{ borderRadius: 6 }}>
              <List
                size="small"
                dataSource={selected.result.action_suggestions}
                renderItem={(item) => <List.Item>{item}</List.Item>}
              />
            </Card>
          </div>
        )}
      </Drawer>
    </>
  );
}

// ─── 主页面 ───

export function CustomerServicePage() {
  const [orders, setOrders] = useState<WorkOrder[]>(loadOrders);

  const handleOrderCreated = (order: WorkOrder) => {
    setOrders((prev) => {
      const updated = [order, ...prev].slice(0, MAX_ORDERS);
      return updated;
    });
  };

  const handleRefresh = () => {
    setOrders(loadOrders());
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          客服工单管理
        </Title>
        <Tag color="#185FA5" style={{ fontSize: 11 }}>
          Brain Agent
        </Tag>
        <CustomerServiceOutlined style={{ color: '#5F5E5A', fontSize: 16 }} />
      </div>

      {/* AI 分析 + 历史并排 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <AIAnalysisPanel onOrderCreated={handleOrderCreated} />
        </Col>
        <Col xs={24} xl={12}>
          <WorkOrderHistoryPanel orders={orders} onRefresh={handleRefresh} />
        </Col>
      </Row>
    </div>
  );
}

