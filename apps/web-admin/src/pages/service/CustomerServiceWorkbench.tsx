/**
 * CustomerServiceWorkbench -- 客户服务工作台
 * 左右分栏IM式客服界面 + 工单管理 + 客诉统计
 * API: tx-member :8003, try/catch 降级 Mock
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { txFetchData } from '../../api';
import {
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Dropdown,
  Empty,
  Input,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CloseCircleOutlined,
  CustomerServiceOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PictureOutlined,
  PlusOutlined,
  SearchOutlined,
  SendOutlined,
  SwapOutlined,
  ThunderboltOutlined,
  UpCircleOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

const { Text, Title } = Typography;
const { TextArea } = Input;

// ============================================================
// 类型定义
// ============================================================

type ConversationStatus = 'pending' | 'active' | 'closed';
type CustomerTag = 'VIP' | '投诉' | '咨询';
type MessageSender = 'customer' | 'agent';
type MessageKind = 'text' | 'image';
type TicketType = '咨询' | '投诉' | '退款' | '建议';
type TicketPriority = '低' | '中' | '高' | '紧急';
type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed';

interface ChatMessage {
  id: string;
  sender: MessageSender;
  kind: MessageKind;
  content: string;
  time: string;
}

interface Conversation {
  id: string;
  customerName: string;
  customerAvatar: string;
  lastMessage: string;
  lastTime: string;
  unread: number;
  tags: CustomerTag[];
  status: ConversationStatus;
  messages: ChatMessage[];
  memberLevel: string;
  totalSpend: number;
  lastOrderNo: string;
  historyTickets: number;
}

interface Ticket {
  id: string;
  conversationId: string;
  customerName: string;
  type: TicketType;
  priority: TicketPriority;
  status: TicketStatus;
  description: string;
  orderNo: string;
  handler: string;
  createdAt: string;
  updatedAt: string;
}

interface DailyTicketTrend {
  date: string;
  count: number;
}

interface TypeDist {
  type: TicketType;
  count: number;
}

interface HandlerRank {
  name: string;
  resolved: number;
  avgMinutes: number;
}

// ============================================================
// ============================================================
// API helpers（失败时返回空数组，不降级为 MOCK 数据）
// ============================================================

const QUICK_REPLIES = [
  '您好，很高兴为您服务，请问有什么可以帮助您？',
  '非常抱歉给您带来不好的体验，我们会尽快处理。',
  '请您提供一下订单编号，方便我们查询。',
  '您的退款已在处理中，预计1-3个工作日到账。',
  '感谢您的反馈，我们会持续改进。',
  '请稍等，我帮您查询一下。',
  '您的会员卡余额为：',
  '我们门店营业时间是10:30-21:30。',
  '已为您记录此问题，会尽快安排处理。',
  '如需进一步帮助，请随时联系我们。',
];

async function apiFetch<T>(path: string): Promise<T | null> {
  try {
    const res = await txFetchData<T>(path);
    return res.data ?? null;
  } catch {
    return null;
  }
}

async function apiPatch<T>(path: string, body: Record<string, unknown>): Promise<T | null> {
  try {
    const res = await txFetchData<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
    return res.data ?? null;
  } catch {
    return null;
  }
}

async function apiPost<T>(path: string, body: Record<string, unknown>): Promise<T | null> {
  try {
    const res = await txFetchData<T>(path, { method: 'POST', body: JSON.stringify(body) });
    return res.data ?? null;
  } catch {
    return null;
  }
}

// ============================================================
// 颜色 / 配置
// ============================================================

const PRIMARY = '#FF6B35';

const TAG_COLORS: Record<CustomerTag, string> = {
  VIP: '#FF6B35',
  '投诉': '#f5222d',
  '咨询': '#1890ff',
};

const PRIORITY_COLOR: Record<TicketPriority, string> = {
  '紧急': '#f5222d',
  '高': '#fa8c16',
  '中': '#1890ff',
  '低': '#8c8c8c',
};

const STATUS_COLOR: Record<TicketStatus, string> = {
  open: '#fa8c16',
  in_progress: '#1890ff',
  resolved: '#52c41a',
  closed: '#8c8c8c',
};

const STATUS_LABEL: Record<TicketStatus, string> = {
  open: '待处理',
  in_progress: '处理中',
  resolved: '已解决',
  closed: '已关闭',
};

// ============================================================
// Tab1: 客服工作台 (IM)
// ============================================================

function IMWorkbench() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [activeConvId, setActiveConvId] = useState<string>('');
  const [filterTab, setFilterTab] = useState<'all' | 'pending' | 'active' | 'closed'>('all');
  const [searchText, setSearchText] = useState('');
  const [inputText, setInputText] = useState('');
  const [showCustomerInfo, setShowCustomerInfo] = useState(true);
  const [createTicketOpen, setCreateTicketOpen] = useState(false);
  const [newTicket, setNewTicket] = useState<{
    type: TicketType;
    priority: TicketPriority;
    description: string;
    orderNo: string;
  }>({ type: '咨询', priority: '中', description: '', orderNo: '' });

  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiFetch<Conversation[]>('/api/v1/ops/service-conversations?status=open')
      .then((data) => setConversations(data ?? []));
    apiFetch<Ticket[]>('/api/v1/ops/service-tickets?status=open')
      .then((data) => setTickets(data ?? []));
  }, []);

  const activeConv = useMemo(
    () => conversations.find((c) => c.id === activeConvId) ?? null,
    [conversations, activeConvId],
  );

  const filteredConversations = useMemo(() => {
    let list = conversations;
    if (filterTab !== 'all') {
      list = list.filter((c) => c.status === filterTab);
    }
    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      list = list.filter(
        (c) =>
          c.customerName.toLowerCase().includes(q) ||
          c.lastMessage.toLowerCase().includes(q),
      );
    }
    return list;
  }, [conversations, filterTab, searchText]);

  const pendingCount = useMemo(
    () => conversations.filter((c) => c.status === 'pending').length,
    [conversations],
  );

  const scrollToBottom = useCallback(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
  }, []);

  useEffect(() => {
    if (activeConv) scrollToBottom();
  }, [activeConv, scrollToBottom]);

  const handleSelectConv = (id: string) => {
    setActiveConvId(id);
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, unread: 0 } : c)),
    );
  };

  const handleSend = () => {
    const text = inputText.trim();
    if (!text || !activeConvId) return;
    const msg: ChatMessage = {
      id: `msg_${Date.now()}`,
      sender: 'agent',
      kind: 'text',
      content: text,
      time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeConvId
          ? { ...c, messages: [...c.messages, msg], lastMessage: text, lastTime: msg.time, status: 'active' as ConversationStatus }
          : c,
      ),
    );
    setInputText('');
    scrollToBottom();
  };

  const handleQuickReply = (text: string) => {
    setInputText(text);
  };

  const handleCreateTicket = () => {
    if (!activeConv) return;
    const ticket: Ticket = {
      id: `T${Date.now()}`,
      conversationId: activeConv.id,
      customerName: activeConv.customerName,
      type: newTicket.type,
      priority: newTicket.priority,
      status: 'open',
      description: newTicket.description,
      orderNo: newTicket.orderNo || activeConv.lastOrderNo,
      handler: '当前客服',
      createdAt: new Date().toLocaleString('zh-CN'),
      updatedAt: new Date().toLocaleString('zh-CN'),
    };
    setTickets((prev) => [ticket, ...prev]);
    setCreateTicketOpen(false);
    setNewTicket({ type: '咨询', priority: '中', description: '', orderNo: '' });
    message.success('工单创建成功');
  };

  const handleTicketAction = async (ticketId: string, action: 'accept' | 'transfer' | 'escalate' | 'close') => {
    const statusMap: Record<string, TicketStatus> = {
      accept: 'in_progress',
      transfer: 'in_progress',
      escalate: 'in_progress',
      close: 'closed',
    };
    const actionLabel: Record<string, string> = {
      accept: '已接单',
      transfer: '已转派',
      escalate: '已升级',
      close: '已关闭',
    };
    const newStatus = statusMap[action];
    // 乐观更新 UI
    setTickets((prev) =>
      prev.map((t) =>
        t.id === ticketId
          ? { ...t, status: newStatus, updatedAt: new Date().toLocaleString('zh-CN') }
          : t,
      ),
    );
    await apiPatch(`/api/v1/ops/service-tickets/${ticketId}`, { status: newStatus });
    message.success(actionLabel[action]);
  };

  const currentTickets = useMemo(
    () => (activeConv ? tickets.filter((t) => t.conversationId === activeConv.id) : []),
    [tickets, activeConv],
  );

  // --- 渲染 ---

  return (
    <Row gutter={0} style={{ height: 'calc(100vh - 180px)', minHeight: 600 }}>
      {/* 左侧 40%: 对话列表 */}
      <Col span={10} style={{ borderRight: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column', height: '100%' }}>
        <div style={{ padding: '12px 12px 0' }}>
          <Input
            placeholder="搜索客户名称/消息"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            allowClear
            style={{ marginBottom: 8 }}
          />
          <Tabs
            activeKey={filterTab}
            onChange={(k) => setFilterTab(k as typeof filterTab)}
            size="small"
            items={[
              { key: 'all', label: '全部' },
              { key: 'pending', label: <Badge count={pendingCount} offset={[10, 0]} size="small">待处理</Badge> },
              { key: 'active', label: '处理中' },
              { key: 'closed', label: '已关闭' },
            ]}
            style={{ marginBottom: 0 }}
          />
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: '0 4px' }}>
          {filteredConversations.length === 0 && (
            <Empty description="暂无对话" style={{ marginTop: 60 }} />
          )}
          {filteredConversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => handleSelectConv(conv.id)}
              style={{
                padding: '10px 12px',
                cursor: 'pointer',
                borderRadius: 6,
                background: conv.id === activeConvId ? '#FFF5F0' : 'transparent',
                borderLeft: conv.id === activeConvId ? `3px solid ${PRIMARY}` : '3px solid transparent',
                marginBottom: 2,
                transition: 'background 0.15s',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Badge count={conv.unread} size="small" offset={[-2, 2]}>
                  <Avatar
                    icon={<UserOutlined />}
                    src={conv.customerAvatar || undefined}
                    style={{ background: PRIMARY, flexShrink: 0 }}
                    size={36}
                  />
                </Badge>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text strong style={{ fontSize: 13 }}>{conv.customerName}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>{conv.lastTime}</Text>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 }}>
                    <Text
                      type="secondary"
                      ellipsis
                      style={{ fontSize: 12, flex: 1, marginRight: 8 }}
                    >
                      {conv.lastMessage}
                    </Text>
                    <Space size={2}>
                      {conv.tags.map((tag) => (
                        <Tag
                          key={tag}
                          color={TAG_COLORS[tag]}
                          style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}
                        >
                          {tag}
                        </Tag>
                      ))}
                    </Space>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Col>

      {/* 右侧 60%: 聊天 + 工单 */}
      <Col span={14} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {!activeConv ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Empty description="请选择一个对话" />
          </div>
        ) : (
          <>
            {/* 顶栏 */}
            <div style={{ padding: '8px 16px', borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Space>
                <Text strong>{activeConv.customerName}</Text>
                {activeConv.tags.map((t) => (
                  <Tag key={t} color={TAG_COLORS[t]} style={{ fontSize: 10 }}>{t}</Tag>
                ))}
              </Space>
              <Tooltip title={showCustomerInfo ? '收起客户信息' : '展开客户信息'}>
                <Button
                  type="text"
                  icon={showCustomerInfo ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}
                  onClick={() => setShowCustomerInfo(!showCustomerInfo)}
                />
              </Tooltip>
            </div>

            {/* 聊天 + 客户信息 */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
              {/* 聊天区域 */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                {/* 消息列表 */}
                <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px', background: '#FAFAF8' }}>
                  {activeConv.messages.map((msg) => {
                    const isAgent = msg.sender === 'agent';
                    return (
                      <div
                        key={msg.id}
                        style={{
                          display: 'flex',
                          justifyContent: isAgent ? 'flex-end' : 'flex-start',
                          marginBottom: 12,
                        }}
                      >
                        {!isAgent && (
                          <Avatar
                            icon={<UserOutlined />}
                            size={28}
                            style={{ background: '#d9d9d9', marginRight: 8, flexShrink: 0, marginTop: 2 }}
                          />
                        )}
                        <div style={{ maxWidth: '65%' }}>
                          {msg.kind === 'image' ? (
                            <img
                              src={msg.content}
                              alt="图片消息"
                              style={{
                                maxWidth: '100%',
                                borderRadius: 8,
                                border: '1px solid #f0f0f0',
                              }}
                            />
                          ) : (
                            <div
                              style={{
                                padding: '8px 12px',
                                borderRadius: isAgent ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                                background: isAgent ? PRIMARY : '#fff',
                                color: isAgent ? '#fff' : '#333',
                                boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
                                fontSize: 13,
                                lineHeight: 1.6,
                              }}
                            >
                              {msg.content}
                            </div>
                          )}
                          <div style={{ fontSize: 10, color: '#999', marginTop: 2, textAlign: isAgent ? 'right' : 'left' }}>
                            {msg.time}
                          </div>
                        </div>
                        {isAgent && (
                          <Avatar
                            icon={<CustomerServiceOutlined />}
                            size={28}
                            style={{ background: PRIMARY, marginLeft: 8, flexShrink: 0, marginTop: 2 }}
                          />
                        )}
                      </div>
                    );
                  })}
                  <div ref={chatEndRef} />
                </div>

                {/* 快捷回复 */}
                <div style={{ padding: '6px 12px', borderTop: '1px solid #f0f0f0', background: '#fff' }}>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {QUICK_REPLIES.map((qr, idx) => (
                      <Button
                        key={idx}
                        size="small"
                        type="dashed"
                        style={{ fontSize: 11, maxWidth: 180 }}
                        onClick={() => handleQuickReply(qr)}
                      >
                        <Text ellipsis style={{ maxWidth: 150, fontSize: 11 }}>{qr}</Text>
                      </Button>
                    ))}
                  </div>
                </div>

                {/* 输入区域 */}
                <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', display: 'flex', gap: 8, background: '#fff' }}>
                  <TextArea
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    placeholder="输入回复内容..."
                    autoSize={{ minRows: 2, maxRows: 4 }}
                    style={{ flex: 1, resize: 'none' }}
                    onPressEnter={(e) => {
                      if (!e.shiftKey) {
                        e.preventDefault();
                        handleSend();
                      }
                    }}
                  />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <Tooltip title="发送图片">
                      <Button icon={<PictureOutlined />} size="small" />
                    </Tooltip>
                    <Button
                      type="primary"
                      icon={<SendOutlined />}
                      onClick={handleSend}
                      style={{ background: PRIMARY, borderColor: PRIMARY }}
                    >
                      发送
                    </Button>
                  </div>
                </div>
              </div>

              {/* 客户信息侧栏 */}
              {showCustomerInfo && (
                <div style={{ width: 200, borderLeft: '1px solid #f0f0f0', padding: 12, overflow: 'auto', background: '#FAFAF8' }}>
                  <Text strong style={{ fontSize: 13 }}>客户信息</Text>
                  <Divider style={{ margin: '8px 0' }} />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>会员等级</Text>
                      <div><Tag color={PRIMARY}>{activeConv.memberLevel}</Tag></div>
                    </div>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>总消费</Text>
                      <div><Text strong style={{ color: PRIMARY }}>{activeConv.totalSpend.toLocaleString()}</Text> 元</div>
                    </div>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>最近订单</Text>
                      <div><Text copyable style={{ fontSize: 12 }}>{activeConv.lastOrderNo}</Text></div>
                    </div>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>历史工单</Text>
                      <div><Text>{activeConv.historyTickets} 条</Text></div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 工单面板 */}
            <div style={{ borderTop: '1px solid #f0f0f0', maxHeight: 220, overflow: 'auto', padding: '8px 16px', background: '#fff' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <Text strong style={{ fontSize: 13 }}>
                  <FileTextOutlined style={{ marginRight: 4 }} />
                  工单记录 ({currentTickets.length})
                </Text>
                <Button
                  size="small"
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => setCreateTicketOpen(true)}
                  style={{ background: PRIMARY, borderColor: PRIMARY }}
                >
                  创建工单
                </Button>
              </div>
              {currentTickets.length === 0 ? (
                <Text type="secondary" style={{ fontSize: 12 }}>暂无关联工单</Text>
              ) : (
                <Timeline
                  items={currentTickets.map((t) => ({
                    color: STATUS_COLOR[t.status],
                    children: (
                      <div style={{ fontSize: 12 }}>
                        <Space size={4}>
                          <Tag color={PRIORITY_COLOR[t.priority]} style={{ fontSize: 10 }}>{t.priority}</Tag>
                          <Tag style={{ fontSize: 10 }}>{t.type}</Tag>
                          <Tag color={STATUS_COLOR[t.status]} style={{ fontSize: 10 }}>{STATUS_LABEL[t.status]}</Tag>
                        </Space>
                        <div style={{ marginTop: 2 }}>{t.description}</div>
                        <div style={{ color: '#999', marginTop: 2 }}>
                          {t.createdAt}
                          {t.handler && <span> | {t.handler}</span>}
                        </div>
                        <Space size={4} style={{ marginTop: 4 }}>
                          {t.status === 'open' && (
                            <Button size="small" type="link" onClick={() => handleTicketAction(t.id, 'accept')}>
                              接单
                            </Button>
                          )}
                          {(t.status === 'open' || t.status === 'in_progress') && (
                            <>
                              <Button size="small" type="link" icon={<SwapOutlined />} onClick={() => handleTicketAction(t.id, 'transfer')}>
                                转派
                              </Button>
                              <Button size="small" type="link" icon={<UpCircleOutlined />} onClick={() => handleTicketAction(t.id, 'escalate')}>
                                升级
                              </Button>
                              <Button size="small" type="link" danger icon={<CloseCircleOutlined />} onClick={() => handleTicketAction(t.id, 'close')}>
                                关闭
                              </Button>
                            </>
                          )}
                        </Space>
                      </div>
                    ),
                  }))}
                />
              )}
            </div>

            {/* 创建工单 Modal */}
            <Modal
              title="创建工单"
              open={createTicketOpen}
              onCancel={() => setCreateTicketOpen(false)}
              onOk={handleCreateTicket}
              okText="创建"
              okButtonProps={{ style: { background: PRIMARY, borderColor: PRIMARY } }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>类型</Text>
                  <Radio.Group
                    value={newTicket.type}
                    onChange={(e) => setNewTicket((p) => ({ ...p, type: e.target.value }))}
                    style={{ display: 'block', marginTop: 4 }}
                  >
                    {(['咨询', '投诉', '退款', '建议'] as TicketType[]).map((t) => (
                      <Radio.Button key={t} value={t}>{t}</Radio.Button>
                    ))}
                  </Radio.Group>
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>优先级</Text>
                  <Radio.Group
                    value={newTicket.priority}
                    onChange={(e) => setNewTicket((p) => ({ ...p, priority: e.target.value }))}
                    style={{ display: 'block', marginTop: 4 }}
                  >
                    {(['低', '中', '高', '紧急'] as TicketPriority[]).map((p) => (
                      <Radio.Button key={p} value={p}>{p}</Radio.Button>
                    ))}
                  </Radio.Group>
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>描述</Text>
                  <TextArea
                    rows={3}
                    value={newTicket.description}
                    onChange={(e) => setNewTicket((p) => ({ ...p, description: e.target.value }))}
                    placeholder="描述客户问题..."
                    style={{ marginTop: 4 }}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>关联订单号</Text>
                  <Input
                    value={newTicket.orderNo}
                    onChange={(e) => setNewTicket((p) => ({ ...p, orderNo: e.target.value }))}
                    placeholder={activeConv?.lastOrderNo || '可选'}
                    style={{ marginTop: 4 }}
                  />
                </div>
              </div>
            </Modal>
          </>
        )}
      </Col>
    </Row>
  );
}

// ============================================================
// Tab2: 工单管理
// ============================================================

function TicketManageTab() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);

  useEffect(() => {
    apiFetch<Ticket[]>('/api/v1/ops/service-tickets')
      .then((data) => setTickets(data ?? []));
  }, []);

  const handleBatchAssign = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请选择工单');
      return;
    }
    setTickets((prev) =>
      prev.map((t) =>
        selectedRowKeys.includes(t.id)
          ? { ...t, handler: '当前客服', status: 'in_progress' as TicketStatus, updatedAt: new Date().toLocaleString('zh-CN') }
          : t,
      ),
    );
    setSelectedRowKeys([]);
    message.success(`已分配 ${selectedRowKeys.length} 条工单`);
  };

  const columns: ProColumns<Ticket>[] = [
    { title: '工单号', dataIndex: 'id', width: 150, copyable: true },
    { title: '客户', dataIndex: 'customerName', width: 80 },
    {
      title: '类型',
      dataIndex: 'type',
      width: 80,
      render: (_: unknown, row: Ticket) => <Tag>{row.type}</Tag>,
      filters: true,
      valueEnum: { '咨询': { text: '咨询' }, '投诉': { text: '投诉' }, '退款': { text: '退款' }, '建议': { text: '建议' } },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
      render: (_: unknown, row: Ticket) => (
        <Tag color={PRIORITY_COLOR[row.priority]}>{row.priority}</Tag>
      ),
      filters: true,
      valueEnum: { '低': { text: '低' }, '中': { text: '中' }, '高': { text: '高' }, '紧急': { text: '紧急' } },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_: unknown, row: Ticket) => (
        <Tag color={STATUS_COLOR[row.status]}>{STATUS_LABEL[row.status]}</Tag>
      ),
      filters: true,
      valueEnum: {
        open: { text: '待处理' },
        in_progress: { text: '处理中' },
        resolved: { text: '已解决' },
        closed: { text: '已关闭' },
      },
    },
    { title: '创建时间', dataIndex: 'createdAt', width: 150 },
    { title: '处理人', dataIndex: 'handler', width: 90, render: (_: unknown, row: Ticket) => row.handler || <Text type="secondary">未分配</Text> },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_: unknown, row: Ticket) => {
        const items = [];
        if (row.status === 'open') {
          items.push(
            <a
              key="accept"
              onClick={() => {
                setTickets((prev) =>
                  prev.map((t) =>
                    t.id === row.id
                      ? { ...t, status: 'in_progress' as TicketStatus, handler: '当前客服', updatedAt: new Date().toLocaleString('zh-CN') }
                      : t,
                  ),
                );
                message.success('已接单');
              }}
            >
              接单
            </a>,
          );
        }
        if (row.status !== 'closed') {
          items.push(
            <a
              key="close"
              style={{ color: '#f5222d' }}
              onClick={() => {
                setTickets((prev) =>
                  prev.map((t) =>
                    t.id === row.id
                      ? { ...t, status: 'closed' as TicketStatus, updatedAt: new Date().toLocaleString('zh-CN') }
                      : t,
                  ),
                );
                message.success('已关闭');
              }}
            >
              关闭
            </a>,
          );
        }
        return <Space>{items}</Space>;
      },
    },
  ];

  return (
    <ProTable<Ticket>
      columns={columns}
      dataSource={tickets}
      rowKey="id"
      search={false}
      pagination={{ pageSize: 10 }}
      rowSelection={{
        selectedRowKeys,
        onChange: (keys) => setSelectedRowKeys(keys as string[]),
      }}
      toolBarRender={() => [
        <Button
          key="batch"
          type="primary"
          onClick={handleBatchAssign}
          disabled={selectedRowKeys.length === 0}
          style={{ background: PRIMARY, borderColor: PRIMARY }}
        >
          批量分配 ({selectedRowKeys.length})
        </Button>,
      ]}
      headerTitle="全部工单"
    />
  );
}

// ============================================================
// Tab3: 客诉统计
// ============================================================

// --- SVG 折线图 ---
function TrendLineChart({ data }: { data: DailyTicketTrend[] }) {
  if (data.length === 0) return null;
  const W = 480;
  const H = 200;
  const PX = 50;
  const PY = 20;
  const maxVal = Math.max(...data.map((d) => d.count), 1);
  const stepX = (W - PX * 2) / Math.max(data.length - 1, 1);
  const scaleY = (v: number) => H - PY - ((v / maxVal) * (H - PY * 2));

  const points = data.map((d, i) => `${PX + i * stepX},${scaleY(d.count)}`).join(' ');
  const areaPath = `M${PX},${H - PY} ` + data.map((d, i) => `L${PX + i * stepX},${scaleY(d.count)}`).join(' ') + ` L${PX + (data.length - 1) * stepX},${H - PY} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W }}>
      {/* Y axis gridlines */}
      {[0, 0.25, 0.5, 0.75, 1].map((r) => {
        const y = scaleY(r * maxVal);
        return (
          <g key={r}>
            <line x1={PX} y1={y} x2={W - PX} y2={y} stroke="#f0f0f0" strokeDasharray="3,3" />
            <text x={PX - 6} y={y + 4} textAnchor="end" fontSize={10} fill="#999">
              {Math.round(r * maxVal)}
            </text>
          </g>
        );
      })}
      {/* Area */}
      <path d={areaPath} fill={PRIMARY} opacity={0.1} />
      {/* Line */}
      <polyline points={points} fill="none" stroke={PRIMARY} strokeWidth={2} />
      {/* Dots + labels */}
      {data.map((d, i) => (
        <g key={d.date}>
          <circle cx={PX + i * stepX} cy={scaleY(d.count)} r={4} fill={PRIMARY} />
          <text x={PX + i * stepX} y={H - 4} textAnchor="middle" fontSize={10} fill="#666">
            {d.date.slice(5)}
          </text>
        </g>
      ))}
    </svg>
  );
}

// --- SVG 饼图 (arc) ---
function TypePieChart({ data }: { data: TypeDist[] }) {
  const total = data.reduce((s, d) => s + d.count, 0);
  if (total === 0) return null;
  const colors = ['#FF6B35', '#1890ff', '#f5222d', '#52c41a', '#fa8c16', '#722ed1'];
  const CX = 100;
  const CY = 100;
  const R = 80;
  let cumAngle = -Math.PI / 2;

  const arcs = data.map((d, i) => {
    const angle = (d.count / total) * 2 * Math.PI;
    const startX = CX + R * Math.cos(cumAngle);
    const startY = CY + R * Math.sin(cumAngle);
    cumAngle += angle;
    const endX = CX + R * Math.cos(cumAngle);
    const endY = CY + R * Math.sin(cumAngle);
    const largeArc = angle > Math.PI ? 1 : 0;
    const pathD = `M${CX},${CY} L${startX},${startY} A${R},${R} 0 ${largeArc} 1 ${endX},${endY} Z`;
    return <path key={d.type} d={pathD} fill={colors[i % colors.length]} opacity={0.85} />;
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <svg viewBox="0 0 200 200" style={{ width: 160, height: 160 }}>
        {arcs}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {data.map((d, i) => (
          <Space key={d.type} size={4}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: colors[i % colors.length] }} />
            <Text style={{ fontSize: 12 }}>{d.type}: {d.count} ({Math.round((d.count / total) * 100)}%)</Text>
          </Space>
        ))}
      </div>
    </div>
  );
}

interface StatsData {
  trend: DailyTicketTrend[];
  type_dist: TypeDist[];
  handler_rank: HandlerRank[];
}

function StatsTab() {
  const [trendData, setTrendData] = useState<DailyTicketTrend[]>([]);
  const [typeDist, setTypeDist] = useState<TypeDist[]>([]);
  const [rankData, setRankData] = useState<HandlerRank[]>([]);

  useEffect(() => {
    apiFetch<StatsData>('/api/v1/ops/service-tickets/stats', {
      trend: [], type_dist: [], handler_rank: [],
    }).then((d) => {
      setTrendData(d.trend ?? []);
      setTypeDist(d.type_dist ?? []);
      setRankData(d.handler_rank ?? []);
    });
  }, []);

  const rankColumns: ProColumns<HandlerRank>[] = [
    {
      title: '排名',
      width: 60,
      render: (_: unknown, __: HandlerRank, idx: number) => (
        <Text strong style={{ color: idx < 3 ? PRIMARY : '#666' }}>#{idx + 1}</Text>
      ),
    },
    { title: '客服', dataIndex: 'name', width: 100 },
    { title: '已处理', dataIndex: 'resolved', width: 80, render: (v: unknown) => <Text strong>{String(v)}</Text> },
    { title: '平均响应(分钟)', dataIndex: 'avgMinutes', width: 120 },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 四统计卡 */}
      <Row gutter={16}>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 8 }}>
            <Statistic
              title="今日新增"
              value={14}
              prefix={<ExclamationCircleOutlined style={{ color: PRIMARY }} />}
              valueStyle={{ color: PRIMARY }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 8 }}>
            <Statistic
              title="处理中"
              value={6}
              prefix={<ThunderboltOutlined style={{ color: '#1890ff' }} />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 8 }}>
            <Statistic
              title="平均响应时长"
              value={15}
              suffix="分钟"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 8 }}>
            <Statistic
              title="客户满意度"
              value={92.5}
              suffix="%"
              precision={1}
              valueStyle={{ color: '#FF6B35' }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        {/* 折线图 */}
        <Col span={14}>
          <Card size="small" title="近7天工单趋势" style={{ borderRadius: 8 }}>
            <TrendLineChart data={trendData} />
          </Card>
        </Col>
        {/* 饼图 */}
        <Col span={10}>
          <Card size="small" title="工单类型分布" style={{ borderRadius: 8 }}>
            <TypePieChart data={typeDist} />
          </Card>
        </Col>
      </Row>

      {/* 处理效率排名 */}
      <Card size="small" title="处理效率排名" style={{ borderRadius: 8 }}>
        <ProTable<HandlerRank>
          columns={rankColumns}
          dataSource={rankData}
          rowKey="name"
          search={false}
          pagination={false}
          toolBarRender={false}
          size="small"
        />
      </Card>
    </div>
  );
}

// ============================================================
// 主页面
// ============================================================

export function CustomerServiceWorkbench() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          客户服务工作台
        </Title>
        <Tag color={PRIMARY} style={{ fontSize: 11 }}>Service Desk</Tag>
        <CustomerServiceOutlined style={{ color: '#5F5E5A', fontSize: 16 }} />
      </div>

      <Tabs
        type="card"
        items={[
          {
            key: 'im',
            label: (
              <Space>
                <CustomerServiceOutlined />
                <span>客服工作台</span>
              </Space>
            ),
            children: <IMWorkbench />,
          },
          {
            key: 'tickets',
            label: (
              <Space>
                <FileTextOutlined />
                <span>工单管理</span>
              </Space>
            ),
            children: <TicketManageTab />,
          },
          {
            key: 'stats',
            label: (
              <Space>
                <ThunderboltOutlined />
                <span>客诉统计</span>
              </Space>
            ),
            children: <StatsTab />,
          },
        ]}
      />
    </div>
  );
}
