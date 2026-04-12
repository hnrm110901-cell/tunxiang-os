/**
 * AI 经营合伙人 — ChiefAgentPage
 *
 * 布局：
 *   左侧：对话式AI分析面板（聊天界面 + 预设快问）
 *   右侧上：3个关键Agent实时状态监控面板
 *   右侧下：最近5条Agent决策日志（Timeline）
 *
 * 数据：优先调用 /api/v1/brain/chat（tx-brain :8010）
 *       Agent状态调用 /api/v1/agent-monitor/status（tx-agent :8008）
 *       失败时降级到演示Mock响应
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Card, Input, Button, Tag, Space, Timeline, Badge, Typography,
  Spin, Divider, Row, Col,
} from 'antd';
import {
  SendOutlined, RobotOutlined, UserOutlined,
  ReloadOutlined, ThunderboltOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

// ─── Design Tokens ───
const C = {
  primary:   '#FF6B35',
  success:   '#0F6E56',
  warning:   '#BA7517',
  danger:    '#A32D2D',
  info:      '#185FA5',
  navy:      '#1E2A3A',
  bg:        '#F8F7F5',
  border:    '#E8E6E1',
  textSub:   '#5F5E5A',
  textMuted: '#B4B2A9',
};

// ─── API Bases ───
const BASE_AGENT = 'http://localhost:8008';
const BASE_BRAIN = 'http://localhost:8010';

// ─── 类型 ───

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  thinking?: boolean;
}

interface AgentMonitor {
  id: string;
  name: string;
  icon: string;
  status: 'running' | 'paused' | 'error';
  todayCount: number;
  todayBlocks?: number;
  lastActiveAt: string | null;
  statusLabel: string;
}

interface DecisionLogItem {
  id: string;
  agentName: string;
  action: string;
  confidence: number;
  passed: boolean;
  createdAt: string;
}

// ─── 预设快问 ───

const QUICK_QUESTIONS = [
  '今日营收异常分析',
  '本周最差门店',
  '推荐今日主推菜品',
  '下周备货建议',
];

// ─── Mock AI 回复（演示备用）───

const MOCK_RESPONSES: Record<string, string> = {
  '今日营收异常分析':
    '根据今日实时数据分析：\n\n**永安店**今日营收¥16,000，较昨日下降18%，连续2天低于目标。主要原因：\n1. 午市客流较少，翻台率仅1.2次（目标2.2次）\n2. 外卖订单受天气影响下降约30%\n\n**建议**：今日下午推送限时折扣（建议满100减15，控制在毛利35%以上），同时联系配送平台申请流量扶持。\n\n文化城店和浏小鲜表现正常，整体健康度评分79分。',
  '本周最差门店':
    '本周（2026-04-07至今）门店综合评分：\n\n🔴 **永安店** — 综合健康分71分\n- 营收完成率82%，低于目标\n- 客单价¥155，为3店中最低\n- 翻台率1.8次，未达标\n\n主要问题集中在**午市运营效率**和**菜品结构优化**。建议本周末安排店长复盘，重点查看11:30-13:30时段的接待能力和推荐菜执行情况。',
  '推荐今日主推菜品':
    '基于今日库存、历史销量和毛利分析，推荐以下主推菜品：\n\n**🌟 高毛利明星**\n1. **剁椒鱼头**（大份）— 毛利率52%，今日已售38份，库存充足，建议作为首推\n2. **湘西猪脚**— 毛利率47%，客户评分4.8，适合午市套餐捆绑\n\n**⚠️ 库存紧张（不建议主推）**\n- 鲜虾：浏小鲜库存仅1.2kg，预计18:00前售罄\n- 濑尿虾：永安店库存告急，建议今日下架\n\n**💡 AI建议**：今日午市可将剁椒鱼头和腊味合蒸组合为"湘味双拼套餐"，预计可提升客单价¥18-22。',
  '下周备货建议':
    '根据历史销售数据和下周天气预报（周末晴朗，预计客流+15%），建议备货计划：\n\n**需增加备货（+20%）**\n- 鲜活水产：鱼头、虾类、螃蟹\n- 时令蔬菜：苦瓜、空心菜\n- 调味品：剁椒酱（当前库存仅剩5天）\n\n**按需备货（维持原量）**\n- 猪肉类、禽类\n- 米面主食\n\n**可减少备货（-10%）**\n- 冷冻半成品（近期销量下降趋势）\n\n**总采购预算建议**：较本周增加约¥8,000-12,000，重点保障周末高峰。',
};

function getMockResponse(question: string): string {
  const exact = MOCK_RESPONSES[question];
  if (exact) return exact;
  return `我已收到您的问题："${question}"。\n\n根据当前经营数据分析，3家门店整体运营状况良好，今日合计营收约¥74,200，综合健康度评分79分。如需详细分析某一具体指标或门店，请进一步说明，我将为您提供精准洞察。`;
}

// ─── 工具函数 ───

function fmtTime(iso: string | null | Date): string {
  if (!iso) return '--';
  const d = typeof iso === 'string' ? new Date(iso) : iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function renderMarkdown(text: string): string {
  // Very simple markdown to HTML
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^(#{1,3})\s+(.+)$/gm, (_, hashes, content) => {
      const level = hashes.length;
      return `<h${level} style="margin:8px 0 4px;font-size:${14 - level + 1}px">${content}</h${level}>`;
    })
    .replace(/\n/g, '<br/>');
}

// ─── Mock Agent 监控数据 ───

const MOCK_AGENTS: AgentMonitor[] = [
  {
    id: 'discount_guard',
    name: '折扣守护',
    icon: '🛡️',
    status: 'running',
    todayCount: 23,
    todayBlocks: 2,
    lastActiveAt: new Date(Date.now() - 600_000).toISOString(),
    statusLabel: '正常防护中',
  },
  {
    id: 'inventory_alert',
    name: '库存预警',
    icon: '📦',
    status: 'running',
    todayCount: 8,
    lastActiveAt: new Date(Date.now() - 1_800_000).toISOString(),
    statusLabel: '今日触发8次',
  },
  {
    id: 'smart_menu',
    name: '智能排菜',
    icon: '🍜',
    status: 'running',
    todayCount: 15,
    lastActiveAt: new Date(Date.now() - 3_600_000).toISOString(),
    statusLabel: '今日推荐15条',
  },
];

const MOCK_DECISIONS: DecisionLogItem[] = [
  {
    id: 'dl001',
    agentName: '折扣守护',
    action: '拦截文化城店88折申请（毛利率将低于30%底线）',
    confidence: 0.97,
    passed: true,
    createdAt: new Date(Date.now() - 600_000).toISOString(),
  },
  {
    id: 'dl002',
    agentName: '智能排菜',
    action: '午市推荐「剁椒鱼头」为主推，预计提升客单价¥18',
    confidence: 0.91,
    passed: true,
    createdAt: new Date(Date.now() - 2_400_000).toISOString(),
  },
  {
    id: 'dl003',
    agentName: '库存预警',
    action: '浏小鲜鲜虾库存告急，触发补货工单推送至采购',
    confidence: 0.84,
    passed: true,
    createdAt: new Date(Date.now() - 5_400_000).toISOString(),
  },
  {
    id: 'dl004',
    agentName: '折扣守护',
    action: '永安店会员9折申请通过（毛利率35.2%，符合底线）',
    confidence: 0.88,
    passed: true,
    createdAt: new Date(Date.now() - 7_200_000).toISOString(),
  },
  {
    id: 'dl005',
    agentName: '智能排菜',
    action: '永安店「湘西猪脚」排入今日TOP3，基于高毛利+库存充足',
    confidence: 0.79,
    passed: true,
    createdAt: new Date(Date.now() - 10_800_000).toISOString(),
  },
];

// ─── API 调用 ───

async function callBrainChat(question: string): Promise<string> {
  try {
    const resp = await fetch(`${BASE_BRAIN}/api/v1/brain/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': localStorage.getItem('tx_tenant_id') || 'default',
        Authorization: `Bearer ${localStorage.getItem('tx_token') || ''}`,
      },
      body: JSON.stringify({ message: question, context: 'dashboard_chat' }),
    });
    const json = await resp.json();
    if (json.ok && json.data?.reply) {
      return json.data.reply as string;
    }
    if (json.ok && json.data?.content) {
      return json.data.content as string;
    }
  } catch {
    // fall through to mock
  }
  return getMockResponse(question);
}

async function loadAgentStatuses(): Promise<AgentMonitor[]> {
  try {
    const resp = await fetch(`${BASE_AGENT}/api/v1/agent-monitor/status`, {
      headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') || 'default' },
    });
    const json = await resp.json();
    if (json.ok && json.data?.agents) {
      const agentMap: Record<string, AgentMonitor> = {};
      MOCK_AGENTS.forEach((a) => { agentMap[a.id] = { ...a }; });
      for (const a of json.data.agents as Record<string, unknown>[]) {
        const id = a.id as string;
        if (agentMap[id]) {
          agentMap[id].status = a.status === 'active' ? 'running' : a.status === 'idle' ? 'paused' : 'error';
          agentMap[id].todayCount = (a.today_decisions as number) ?? agentMap[id].todayCount;
          agentMap[id].lastActiveAt = (a.last_active_at as string) ?? agentMap[id].lastActiveAt;
        }
      }
      return Object.values(agentMap);
    }
  } catch {
    // use mock
  }
  return MOCK_AGENTS;
}

async function loadDecisionLogs(): Promise<DecisionLogItem[]> {
  try {
    const resp = await fetch(`${BASE_AGENT}/api/v1/agent-monitor/decisions?limit=5`, {
      headers: { 'X-Tenant-ID': localStorage.getItem('tx_tenant_id') || 'default' },
    });
    const json = await resp.json();
    if (json.ok && Array.isArray(json.data) && json.data.length > 0) {
      return (json.data as Record<string, unknown>[]).map((r) => ({
        id: r.id as string,
        agentName: (r.agent_name as string) ?? (r.agent_id as string) ?? 'Agent',
        action: (r.output_action as string) ?? (r.action as string) ?? '-',
        confidence: typeof r.confidence === 'number' ? r.confidence : 0,
        passed: r.constraints_check
          ? Object.values(r.constraints_check as Record<string, boolean>).every(Boolean)
          : true,
        createdAt: (r.created_at as string) ?? new Date().toISOString(),
      }));
    }
  } catch {
    // use mock
  }
  return MOCK_DECISIONS;
}

// ─── 子组件：Agent 监控卡片 ───

function AgentMonitorCard({ agent }: { agent: AgentMonitor }) {
  const isRunning = agent.status === 'running';
  const borderColor = isRunning ? C.success : agent.status === 'paused' ? C.warning : C.danger;
  const statusDot = isRunning ? 'success' : agent.status === 'paused' ? 'warning' : 'error';

  return (
    <div style={{
      padding: '12px 14px',
      borderRadius: 8,
      background: '#fff',
      border: `1px solid ${C.border}`,
      borderLeft: `4px solid ${borderColor}`,
      marginBottom: 10,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Space size={6}>
          <span style={{ fontSize: 18 }}>{agent.icon}</span>
          <Text strong style={{ fontSize: 14 }}>{agent.name}</Text>
        </Space>
        <Badge status={statusDot} text={
          <span style={{ fontSize: 12, color: isRunning ? C.success : C.warning }}>
            {isRunning ? '运行中' : agent.status === 'paused' ? '暂停' : '异常'}
          </span>
        } />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 11, color: C.textMuted }}>今日执行</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.primary }}>{agent.todayCount}</div>
        </div>
        {agent.todayBlocks != null && (
          <div>
            <div style={{ fontSize: 11, color: C.textMuted }}>今日拦截</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: C.danger }}>{agent.todayBlocks}</div>
          </div>
        )}
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: C.textMuted }}>最近活跃</div>
          <div style={{ fontSize: 13, color: C.textSub }}>{fmtTime(agent.lastActiveAt)}</div>
        </div>
      </div>
      <div style={{ marginTop: 6, fontSize: 11, color: C.info }}>{agent.statusLabel}</div>
    </div>
  );
}

// ─── 主组件 ───

export function ChiefAgentPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '您好！我是屯象AI经营合伙人 🤖\n\n我实时监控尝在一起3家门店的经营数据，可以帮您分析营收异常、推荐菜品组合、预警库存风险、优化人员排班。\n\n请问今天有什么经营问题需要分析？',
      timestamp: new Date(),
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [agents, setAgents] = useState<AgentMonitor[]>(MOCK_AGENTS);
  const [decisions, setDecisions] = useState<DecisionLogItem[]>(MOCK_DECISIONS);
  const [agentLoading, setAgentLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const refreshAgentData = useCallback(async () => {
    setAgentLoading(true);
    const [agentData, decisionData] = await Promise.all([
      loadAgentStatuses(),
      loadDecisionLogs(),
    ]);
    setAgents(agentData);
    setDecisions(decisionData);
    setAgentLoading(false);
  }, []);

  useEffect(() => {
    refreshAgentData();
  }, [refreshAgentData]);

  const handleSend = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || chatLoading) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: q,
      timestamp: new Date(),
    };
    const thinkingMsg: ChatMessage = {
      id: `thinking-${Date.now()}`,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      thinking: true,
    };

    setMessages((prev) => [...prev, userMsg, thinkingMsg]);
    setInputValue('');
    setChatLoading(true);

    const reply = await callBrainChat(q);

    setMessages((prev) => {
      const filtered = prev.filter((m) => !m.thinking);
      return [
        ...filtered,
        {
          id: `a-${Date.now()}`,
          role: 'assistant' as const,
          content: reply,
          timestamp: new Date(),
        },
      ];
    });
    setChatLoading(false);
  }, [chatLoading]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(inputValue);
    }
  };

  return (
    <div style={{ padding: 24, minWidth: 1280 }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>
          AI 经营合伙人
        </h2>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: C.textSub }}>
          实时监控 · 智能分析 · 决策辅助 — 尝在一起 3家门店
        </p>
      </div>

      <Row gutter={16} style={{ minHeight: 640 }}>
        {/* ── 左侧：对话面板 ── */}
        <Col span={14}>
          <Card
            title={
              <Space>
                <RobotOutlined style={{ color: C.info }} />
                <span style={{ color: C.info }}>AI经营分析对话</span>
              </Space>
            }
            style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
            styles={{ body: { flex: 1, display: 'flex', flexDirection: 'column', padding: 0 } }}
          >
            {/* 消息区 */}
            <div style={{
              flex: 1,
              overflowY: 'auto',
              padding: '16px 20px',
              minHeight: 420,
              maxHeight: 480,
              background: '#fafaf9',
            }}>
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  style={{
                    display: 'flex',
                    justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    marginBottom: 14,
                    alignItems: 'flex-start',
                    gap: 8,
                  }}
                >
                  {msg.role === 'assistant' && (
                    <div style={{
                      width: 30, height: 30, borderRadius: '50%',
                      background: C.info, color: '#fff',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0, marginTop: 2, fontSize: 14,
                    }}>
                      <RobotOutlined />
                    </div>
                  )}
                  <div style={{
                    maxWidth: '75%',
                    padding: '10px 14px',
                    borderRadius: msg.role === 'user' ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
                    background: msg.role === 'user' ? C.primary : '#fff',
                    color: msg.role === 'user' ? '#fff' : '#2C2C2A',
                    border: msg.role === 'assistant' ? `1px solid ${C.border}` : 'none',
                    fontSize: 13,
                    lineHeight: 1.6,
                    boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
                  }}>
                    {msg.thinking ? (
                      <Space>
                        <Spin size="small" />
                        <span style={{ color: C.textMuted, fontSize: 12 }}>AI正在分析数据...</span>
                      </Space>
                    ) : msg.role === 'assistant' ? (
                      <div
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                        style={{ whiteSpace: 'pre-wrap' }}
                      />
                    ) : (
                      <span>{msg.content}</span>
                    )}
                    {!msg.thinking && (
                      <div style={{
                        fontSize: 10,
                        color: msg.role === 'user' ? 'rgba(255,255,255,0.7)' : C.textMuted,
                        marginTop: 4,
                        textAlign: 'right',
                      }}>
                        {fmtTime(msg.timestamp)}
                      </div>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <div style={{
                      width: 30, height: 30, borderRadius: '50%',
                      background: C.primary, color: '#fff',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0, marginTop: 2, fontSize: 14,
                    }}>
                      <UserOutlined />
                    </div>
                  )}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            <Divider style={{ margin: 0 }} />

            {/* 快问按钮 */}
            <div style={{ padding: '12px 20px 8px', background: '#fff' }}>
              <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 8 }}>快速提问：</div>
              <Space size={[6, 6]} wrap>
                {QUICK_QUESTIONS.map((q) => (
                  <Button
                    key={q}
                    size="small"
                    type="dashed"
                    style={{ fontSize: 12, borderColor: C.info, color: C.info }}
                    onClick={() => handleSend(q)}
                    disabled={chatLoading}
                  >
                    {q}
                  </Button>
                ))}
              </Space>
            </div>

            {/* 输入框 */}
            <div style={{ padding: '8px 20px 16px', background: '#fff' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                <Input.TextArea
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="问我任何经营问题...（Enter发送，Shift+Enter换行）"
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  style={{ borderColor: C.border, fontSize: 13 }}
                  disabled={chatLoading}
                />
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  onClick={() => handleSend(inputValue)}
                  loading={chatLoading}
                  style={{ background: C.primary, borderColor: C.primary, height: 'auto', minHeight: 32 }}
                >
                  发送
                </Button>
              </div>
            </div>
          </Card>
        </Col>

        {/* ── 右侧：Agent监控 + 决策日志 ── */}
        <Col span={10}>
          {/* Agent 状态监控 */}
          <Card
            title={
              <Space>
                <ThunderboltOutlined style={{ color: C.primary }} />
                <span>Agent 实时状态</span>
              </Space>
            }
            extra={
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={refreshAgentData}
                loading={agentLoading}
              >
                刷新
              </Button>
            }
            style={{ marginBottom: 16 }}
            styles={{ body: { padding: '12px 16px' } }}
          >
            {agentLoading
              ? <div style={{ padding: 20, textAlign: 'center' }}><Spin /></div>
              : agents.map((agent) => (
                  <AgentMonitorCard key={agent.id} agent={agent} />
                ))
            }
          </Card>

          {/* 最近决策日志 */}
          <Card
            title={
              <Space>
                <span>📋</span>
                <span>最近Agent决策日志</span>
              </Space>
            }
            styles={{ body: { padding: '12px 16px' } }}
          >
            {decisions.length > 0 ? (
              <Timeline
                items={decisions.slice(0, 5).map((d) => ({
                  color: d.passed ? 'green' : 'red',
                  children: (
                    <div style={{ paddingBottom: 4 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <Space size={4}>
                          <Tag color="purple" style={{ fontSize: 11, margin: 0 }}>{d.agentName}</Tag>
                          <Tag color={d.confidence >= 0.8 ? 'blue' : 'orange'} style={{ fontSize: 11, margin: 0 }}>
                            {(d.confidence * 100).toFixed(0)}%
                          </Tag>
                        </Space>
                        <Text style={{ fontSize: 11, color: C.textMuted }}>{fmtTime(d.createdAt)}</Text>
                      </div>
                      <Text style={{ fontSize: 12, color: '#2C2C2A', lineHeight: 1.5 }}>
                        {d.action}
                      </Text>
                    </div>
                  ),
                }))}
              />
            ) : (
              <div style={{ color: C.textMuted, fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
                暂无决策记录
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
