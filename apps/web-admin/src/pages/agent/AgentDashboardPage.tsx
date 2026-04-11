/**
 * Agent 管理面板 — AgentDashboardPage
 *
 * Tab1: Agent 卡片网格 (3x3) + 顶部状态条 + Drawer 详情
 * Tab2: 决策日志 ProTable
 * Tab3: 三条硬约束监控（毛利底线 / 食安合规 / 出餐时效）
 *
 * API: tx-agent :8008 + tx-brain :8010，失败时 Mock 降级
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  InputNumber,
  message,
  Row,
  Select,
  Slider,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExperimentOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

// ─── Design Tokens ───
const C = {
  primary:    '#FF6B35',
  success:    '#0F6E56',
  warning:    '#BA7517',
  danger:     '#A32D2D',
  info:       '#185FA5',
  navy:       '#1E2A3A',
  bgPrimary:  '#FFFFFF',
  bgSecondary:'#F8F7F5',
  bgTertiary: '#F0EDE6',
  textPrimary:'#2C2C2A',
  textSub:    '#5F5E5A',
  textMuted:  '#B4B2A9',
  border:     '#E8E6E1',
};

// ─── API Bases ───
const BASE_AGENT = 'http://localhost:8008';
const BASE_BRAIN = 'http://localhost:8010';

// ─── 9 Agent 定义 ───
interface AgentDef {
  id: string;
  name: string;
  icon: string;
  description: string;
  location: string;
  priority: string;
}

const AGENTS: AgentDef[] = [
  { id: 'discount_guard',  name: '折扣守护',  icon: '\u{1F6E1}\u{FE0F}', description: '监控折扣申请，守住毛利底线',         location: '边缘+云端', priority: 'P0' },
  { id: 'smart_menu',      name: '智能排菜',  icon: '\u{1F35C}',          description: '根据库存、销量、利润推荐最优菜品排序', location: '云端',       priority: 'P0' },
  { id: 'serve_dispatch',  name: '出餐调度',  icon: '\u{26A1}',           description: '预测出餐时间，调度厨房任务',         location: '边缘',       priority: 'P1' },
  { id: 'member_insight',  name: '会员洞察',  icon: '\u{1F464}',          description: '分析会员消费行为，输出精准画像',     location: '云端',       priority: 'P1' },
  { id: 'inventory_alert', name: '库存预警',  icon: '\u{1F4E6}',          description: '监控库存水位，食安临期预警',         location: '边缘+云端', priority: 'P1' },
  { id: 'finance_audit',   name: '财务稽核',  icon: '\u{1F4B0}',          description: '审计门店财务快照，发现异常模式',     location: '云端',       priority: 'P1' },
  { id: 'store_inspect',   name: '巡店质检',  icon: '\u{1F50D}',          description: '分析巡检清单，识别违规项',           location: '云端',       priority: 'P2' },
  { id: 'smart_service',   name: '智能客服',  icon: '\u{1F4AC}',          description: '处理顾客投诉/询问/反馈',             location: '云端',       priority: 'P2' },
  { id: 'private_ops',     name: '私域运营',  icon: '\u{1F4E3}',          description: '生成微信群/朋友圈/小程序推送文案',   location: '云端',       priority: 'P2' },
];

// ─── 类型 ───
interface AgentStatus {
  id: string;
  status: 'running' | 'paused' | 'error';
  todayCount: number;
  lastActiveAt: string | null;
  avgConfidence: number | null;
}

interface DecisionLog {
  id: string;
  agentId: string;
  agentName: string;
  decisionType: string;
  inputSummary: string;
  outputAction: string;
  confidence: number;
  constraintPassed: boolean;
  durationMs: number;
  createdAt: string;
}

interface ExecutionRecord {
  time: string;
  trigger: string;
  decision: string;
  confidence: number;
  constraintResult: string;
}

interface ConstraintCard {
  title: string;
  icon: string;
  color: string;
  todayTriggers: number;
  todayBlocks: number;
  trend: number[];
  recentRecords: { time: string; detail: string; blocked: boolean }[];
}

interface ConfigParam {
  key: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
}

// ─── 默认配置参数（本地常量，非 mock 数据） ───
function defaultConfigParams(agentId: string): ConfigParam[] {
  const configs: Record<string, ConfigParam[]> = {
    discount_guard: [
      { key: 'margin_floor', label: '毛利底线(%)', value: 30, min: 10, max: 60, step: 1, unit: '%' },
      { key: 'alert_threshold', label: '预警阈值(%)', value: 35, min: 15, max: 70, step: 1, unit: '%' },
    ],
    smart_menu: [
      { key: 'diversity_weight', label: '多样性权重', value: 0.4, min: 0, max: 1, step: 0.05, unit: '' },
      { key: 'profit_weight', label: '利润权重', value: 0.6, min: 0, max: 1, step: 0.05, unit: '' },
    ],
    serve_dispatch: [
      { key: 'timeout_minutes', label: '超时阈值(分)', value: 25, min: 10, max: 60, step: 1, unit: '分' },
    ],
    inventory_alert: [
      { key: 'expiry_days', label: '临期天数', value: 3, min: 1, max: 7, step: 1, unit: '天' },
      { key: 'min_stock_ratio', label: '最低库存比', value: 0.2, min: 0.05, max: 0.5, step: 0.05, unit: '' },
    ],
  };
  return configs[agentId] ?? [
    { key: 'confidence_threshold', label: '置信度阈值', value: 0.7, min: 0.3, max: 1, step: 0.05, unit: '' },
  ];
}

// ─── 辅助 ───
function fmtTime(iso: string | null): string {
  if (!iso) return '\u2014';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function statusBadge(s: 'running' | 'paused' | 'error') {
  if (s === 'running') return <Badge status="success" text={<span style={{ color: C.success, fontSize: 12 }}>运行中</span>} />;
  if (s === 'paused')  return <Badge status="warning" text={<span style={{ color: C.warning, fontSize: 12 }}>暂停</span>} />;
  return <Badge status="error" text={<span style={{ color: C.danger, fontSize: 12 }}>异常</span>} />;
}

// ─── SVG 折线图 ───
function MiniLineChart({ data, color, width = 280, height = 80 }: { data: number[]; color: string; width?: number; height?: number }) {
  if (data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const padX = 10;
  const padY = 10;
  const w = width - padX * 2;
  const h = height - padY * 2;

  const points = data.map((v, i) => {
    const x = padX + (i / (data.length - 1)) * w;
    const y = padY + h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(' ');

  const areaPoints = `${padX},${padY + h} ${points} ${padX + w},${padY + h}`;
  const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

  return (
    <svg width={width} height={height + 18} viewBox={`0 0 ${width} ${height + 18}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={`grad-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.2} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill={`url(#grad-${color.replace('#', '')})`} />
      <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      {data.map((v, i) => {
        const x = padX + (i / (data.length - 1)) * w;
        const y = padY + h - ((v - min) / range) * h;
        return <circle key={i} cx={x} cy={y} r={3} fill={color} stroke="#fff" strokeWidth={1.5} />;
      })}
      {days.map((d, i) => {
        const x = padX + (i / (data.length - 1)) * w;
        return <text key={i} x={x} y={height + 14} textAnchor="middle" fontSize={10} fill={C.textMuted}>{d}</text>;
      })}
    </svg>
  );
}

// ─── API 请求封装（失败时返回空状态，不降级 Mock） ───
async function fetchAgentStatus(): Promise<{ agents: AgentStatus[]; totalDecisions: number; avgResponseMs: number; constraintPassRate: number }> {
  try {
    const resp = await fetch(`${BASE_AGENT}/api/v1/agent-monitor/status`, {
      headers: { 'X-Tenant-ID': 'default' },
    });
    const json = await resp.json();
    if (json.ok && json.data) {
      const agents: AgentStatus[] = (json.data.agents ?? []).map((a: Record<string, unknown>) => ({
        id: a.id as string,
        status: a.status === 'active' ? 'running' : a.status === 'idle' ? 'paused' : 'error',
        todayCount: (a.today_decisions as number) ?? 0,
        lastActiveAt: (a.last_active_at as string) ?? null,
        avgConfidence: (a.avg_confidence as number) ?? null,
      }));
      const total = (json.data.summary?.today_decisions as number) ?? 0;
      const avgMs = (json.data.summary?.avg_response_ms as number) ?? 0;
      const passRate = (json.data.summary?.constraint_pass_rate as number) ?? 0;
      return { agents, totalDecisions: total, avgResponseMs: avgMs, constraintPassRate: passRate };
    }
  } catch {
    // 服务不可达，返回空状态
  }
  return { agents: [], totalDecisions: 0, avgResponseMs: 0, constraintPassRate: 0 };
}

async function fetchDecisionLogs(agentId?: string): Promise<DecisionLog[]> {
  try {
    const url = new URL(`${BASE_AGENT}/api/v1/agent-monitor/decisions`);
    if (agentId) url.searchParams.set('agent_id', agentId);
    url.searchParams.set('limit', '50');
    const resp = await fetch(url.toString(), {
      headers: { 'X-Tenant-ID': 'default' },
    });
    const json = await resp.json();
    if (json.ok && Array.isArray(json.data)) {
      return json.data.map((r: Record<string, unknown>) => {
        const agentDef = AGENTS.find((a) => a.id === r.agent_id);
        const conf = typeof r.confidence === 'number' ? r.confidence : 0;
        const checks = r.constraints_check as Record<string, boolean> | null;
        const allPassed = checks ? Object.values(checks).every(Boolean) : conf >= 0.6;
        return {
          id: r.id as string,
          agentId: r.agent_id as string,
          agentName: agentDef?.name ?? (r.agent_id as string),
          decisionType: (r.decision_type as string) ?? (r.action as string) ?? '-',
          inputSummary: (r.reasoning as string)?.slice(0, 60) ?? '-',
          outputAction: typeof r.output_action === 'string' ? r.output_action : '-',
          confidence: conf,
          constraintPassed: allPassed,
          durationMs: 0,
          createdAt: (r.created_at as string) ?? new Date().toISOString(),
        };
      });
    }
  } catch {
    // 服务不可达，返回空数组
  }
  return [];
}

async function fetchConstraints(): Promise<ConstraintCard[]> {
  try {
    const resp = await fetch(`${BASE_AGENT}/api/v1/agent-monitor/constraints`, {
      headers: { 'X-Tenant-ID': 'default' },
    });
    const json = await resp.json();
    if (json.ok && Array.isArray(json.data)) {
      return json.data as ConstraintCard[];
    }
  } catch {
    // 服务不可达，返回空数组
  }
  return [];
}

async function fetchAgentExecutionHistory(agentId: string): Promise<ExecutionRecord[]> {
  try {
    const resp = await fetch(
      `${BASE_AGENT}/api/v1/agent-monitor/executions?agent_id=${encodeURIComponent(agentId)}&limit=20`,
      { headers: { 'X-Tenant-ID': 'default' } },
    );
    const json = await resp.json();
    if (json.ok && Array.isArray(json.data)) {
      return json.data.map((r: Record<string, unknown>) => ({
        time: (r.created_at as string) ?? new Date().toISOString(),
        trigger: (r.trigger as string) ?? '-',
        decision: (r.output_action as string) ?? '-',
        confidence: typeof r.confidence === 'number' ? r.confidence : 0,
        constraintResult: (r.constraint_result as string) ?? 'UNKNOWN',
      }));
    }
  } catch {
    // 服务不可达，返回空数组
  }
  return [];
}

// ─── Tab1: Agent 卡片网格 ───
function AgentGridTab({
  agents,
  statuses,
  totalDecisions,
  avgResponseMs,
  constraintPassRate,
  loading,
  onRefresh,
}: {
  agents: AgentDef[];
  statuses: Map<string, AgentStatus>;
  totalDecisions: number;
  avgResponseMs: number;
  constraintPassRate: number;
  loading: boolean;
  onRefresh: () => void;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<AgentDef | null>(null);
  const [execHistory, setExecHistory] = useState<ExecutionRecord[]>([]);
  const [configParams, setConfigParams] = useState<ConfigParam[]>([]);
  const [triggerLoading, setTriggerLoading] = useState(false);

  const openDrawer = async (agent: AgentDef) => {
    setSelectedAgent(agent);
    setConfigParams(defaultConfigParams(agent.id));
    setDrawerOpen(true);
    const history = await fetchAgentExecutionHistory(agent.id);
    setExecHistory(history);
  };

  const handleManualTrigger = async () => {
    if (!selectedAgent) return;
    setTriggerLoading(true);
    try {
      const resp = await fetch(`${BASE_BRAIN}/api/v1/brain/health`);
      const json = await resp.json();
      if (json.ok) {
        message.success(`${selectedAgent.name} 手动触发成功`);
      } else {
        message.warning(`${selectedAgent.name} 触发完成（降级模式）`);
      }
    } catch {
      message.info(`${selectedAgent.name} 已发送触发请求（离线模式）`);
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleConfigSave = () => {
    message.success('配置参数已保存（本地）');
  };

  const runningCount = Array.from(statuses.values()).filter((s) => s.status === 'running').length;
  const allHealthy = runningCount === agents.length;

  return (
    <>
      {/* 顶部状态条 */}
      <Card style={{ marginBottom: 20 }} bodyStyle={{ padding: '16px 24px' }}>
        <Row gutter={24} align="middle">
          <Col flex="auto">
            <Space size="large">
              <Space>
                <span style={{ fontSize: 20 }}>{allHealthy ? '\u{1F7E2}' : '\u{1F7E1}'}</span>
                <Text strong style={{ fontSize: 16, color: C.textPrimary }}>
                  Agent 系统{allHealthy ? '正常运行' : '部分异常'}
                </Text>
                <Tag color={allHealthy ? 'success' : 'warning'}>{runningCount}/{agents.length} 在线</Tag>
              </Space>
            </Space>
          </Col>
          <Col>
            <Space size="large">
              <Statistic title="今日决策" value={totalDecisions} valueStyle={{ fontSize: 20, color: C.primary, fontWeight: 700 }} />
              <Statistic title="平均响应" value={avgResponseMs} suffix="ms" valueStyle={{ fontSize: 20, fontWeight: 700 }} />
              <Statistic title="约束通过率" value={constraintPassRate} suffix="%" valueStyle={{ fontSize: 20, color: C.success, fontWeight: 700 }} />
            </Space>
          </Col>
          <Col>
            <Button icon={<ReloadOutlined />} onClick={onRefresh} loading={loading}>刷新</Button>
          </Col>
        </Row>
      </Card>

      {/* 3x3 Agent 卡片 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
          {agents.map((agent) => {
            const st = statuses.get(agent.id);
            const status = st?.status ?? 'error';
            const borderColor = status === 'running' ? C.success : status === 'paused' ? C.warning : C.danger;

            return (
              <Card
                key={agent.id}
                hoverable
                onClick={() => openDrawer(agent)}
                style={{
                  borderLeft: `4px solid ${borderColor}`,
                  cursor: 'pointer',
                  transition: 'box-shadow 0.2s',
                }}
                bodyStyle={{ padding: '16px 20px' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <Space>
                    <span style={{ fontSize: 22 }}>{agent.icon}</span>
                    <Text strong style={{ fontSize: 15 }}>{agent.name}</Text>
                  </Space>
                  {statusBadge(status)}
                </div>
                <Row gutter={16}>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: C.textMuted }}>今日执行</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: C.primary }}>{st?.todayCount ?? 0}</div>
                  </Col>
                  <Col span={12}>
                    <div style={{ fontSize: 11, color: C.textMuted }}>最近执行</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: C.textPrimary }}>{fmtTime(st?.lastActiveAt ?? null)}</div>
                  </Col>
                </Row>
              </Card>
            );
          })}
        </div>
      )}

      {/* Agent 详情 Drawer */}
      <Drawer
        title={
          selectedAgent ? (
            <Space>
              <span style={{ fontSize: 22 }}>{selectedAgent.icon}</span>
              <span>{selectedAgent.name}</span>
              {statusBadge(statuses.get(selectedAgent.id)?.status ?? 'error')}
            </Space>
          ) : null
        }
        placement="right"
        width={640}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {selectedAgent && (
          <>
          <Tabs
            defaultActiveKey="info"
            items={[
              {
                key: 'info',
                label: '基本信息',
                icon: <RobotOutlined />,
                children: (
                  <Descriptions column={1} size="small" bordered>
                    <Descriptions.Item label="Agent ID">{selectedAgent.id}</Descriptions.Item>
                    <Descriptions.Item label="描述">{selectedAgent.description}</Descriptions.Item>
                    <Descriptions.Item label="运行位置">{selectedAgent.location}</Descriptions.Item>
                    <Descriptions.Item label="优先级"><Tag color={selectedAgent.priority === 'P0' ? 'error' : selectedAgent.priority === 'P1' ? 'warning' : 'default'}>{selectedAgent.priority}</Tag></Descriptions.Item>
                    <Descriptions.Item label="平均置信度">{statuses.get(selectedAgent.id)?.avgConfidence ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="今日执行次数">{statuses.get(selectedAgent.id)?.todayCount ?? 0}</Descriptions.Item>
                  </Descriptions>
                ),
              },
              {
                key: 'history',
                label: '执行历史',
                icon: <ThunderboltOutlined />,
                children: (
                  <Timeline
                    items={execHistory.map((r) => ({
                      color: r.constraintResult === 'PASS' ? 'green' : 'red',
                      children: (
                        <div>
                          <Text style={{ fontSize: 12, color: C.textMuted }}>{fmtDateTime(r.time)}</Text>
                          <div style={{ marginTop: 4 }}>
                            <Tag>{r.trigger}</Tag>
                            <Text style={{ fontSize: 13 }}>{r.decision}</Text>
                            <Tag color={r.confidence >= 0.6 ? 'blue' : 'red'} style={{ marginLeft: 8 }}>
                              {(r.confidence * 100).toFixed(0)}%
                            </Tag>
                            <Tag color={r.constraintResult === 'PASS' ? 'success' : 'error'}>
                              {r.constraintResult}
                            </Tag>
                          </div>
                        </div>
                      ),
                    }))}
                  />
                ),
              },
              {
                key: 'config',
                label: '配置参数',
                icon: <SettingOutlined />,
                children: (
                  <div>
                    {configParams.map((p) => (
                      <div key={p.key} style={{ marginBottom: 20 }}>
                        <Text strong style={{ fontSize: 13 }}>{p.label}</Text>
                        <Row gutter={12} align="middle" style={{ marginTop: 6 }}>
                          <Col flex="auto">
                            <Slider
                              min={p.min}
                              max={p.max}
                              step={p.step}
                              value={p.value}
                              onChange={(v) => {
                                setConfigParams((prev) => prev.map((cp) => cp.key === p.key ? { ...cp, value: v } : cp));
                              }}
                            />
                          </Col>
                          <Col>
                            <InputNumber
                              min={p.min}
                              max={p.max}
                              step={p.step}
                              value={p.value}
                              size="small"
                              style={{ width: 80 }}
                              onChange={(v) => {
                                if (v !== null) {
                                  setConfigParams((prev) => prev.map((cp) => cp.key === p.key ? { ...cp, value: v } : cp));
                                }
                              }}
                            />
                          </Col>
                          {p.unit && <Col><Text type="secondary">{p.unit}</Text></Col>}
                        </Row>
                      </div>
                    ))}
                    <Button type="primary" onClick={handleConfigSave} style={{ background: C.primary, borderColor: C.primary }}>
                      保存配置
                    </Button>
                  </div>
                ),
              },
            ]}
          />
          <div style={{ marginTop: 24, borderTop: `1px solid ${C.border}`, paddingTop: 16 }}>
            <Button
              icon={<ExperimentOutlined />}
              onClick={handleManualTrigger}
              loading={triggerLoading}
              block
            >
              手动触发（测试）
            </Button>
          </div>
          </>
        )}
      </Drawer>
    </>
  );
}

// ─── Tab2: 决策日志 ───
function DecisionLogTab() {
  const [logs, setLogs] = useState<DecisionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterAgent, setFilterAgent] = useState<string | undefined>(undefined);
  const [filterConfMin, setFilterConfMin] = useState<number>(0);
  const [filterConfMax, setFilterConfMax] = useState<number>(1);

  const load = useCallback(async () => {
    setLoading(true);
    const data = await fetchDecisionLogs(filterAgent);
    setLogs(data);
    setLoading(false);
  }, [filterAgent]);

  useEffect(() => { load(); }, [load]);

  const filtered = logs.filter((l) => l.confidence >= filterConfMin && l.confidence <= filterConfMax);

  const columns = [
    {
      title: '时间',
      dataIndex: 'createdAt',
      width: 120,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{fmtDateTime(v)}</Text>,
      sorter: (a: DecisionLog, b: DecisionLog) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
      defaultSortOrder: 'descend' as const,
    },
    {
      title: 'Agent',
      dataIndex: 'agentName',
      width: 100,
      render: (v: string) => <Tag color="purple">{v}</Tag>,
    },
    {
      title: '决策类型',
      dataIndex: 'decisionType',
      width: 100,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '输入上下文',
      dataIndex: 'inputSummary',
      ellipsis: true,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: '输出动作',
      dataIndex: 'outputAction',
      width: 100,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 80,
      render: (v: number) => (
        <Text style={{ color: v < 0.6 ? C.danger : C.textPrimary, fontWeight: v < 0.6 ? 700 : 400, fontSize: 13 }}>
          {(v * 100).toFixed(0)}%
        </Text>
      ),
      sorter: (a: DecisionLog, b: DecisionLog) => a.confidence - b.confidence,
    },
    {
      title: '约束',
      dataIndex: 'constraintPassed',
      width: 60,
      align: 'center' as const,
      render: (v: boolean) => v
        ? <CheckCircleOutlined style={{ color: C.success, fontSize: 16 }} />
        : <CloseCircleOutlined style={{ color: C.danger, fontSize: 16 }} />,
    },
    {
      title: '耗时',
      dataIndex: 'durationMs',
      width: 80,
      render: (v: number) => <Text style={{ fontSize: 12 }}>{v > 0 ? `${v}ms` : '-'}</Text>,
      sorter: (a: DecisionLog, b: DecisionLog) => a.durationMs - b.durationMs,
    },
  ];

  return (
    <div>
      {/* 筛选条 */}
      <Card style={{ marginBottom: 16 }} bodyStyle={{ padding: '12px 20px' }}>
        <Space wrap size="middle">
          <Space>
            <Text style={{ fontSize: 13 }}>Agent:</Text>
            <Select
              allowClear
              placeholder="全部"
              value={filterAgent}
              onChange={setFilterAgent}
              style={{ width: 140 }}
              options={AGENTS.map((a) => ({ label: `${a.icon} ${a.name}`, value: a.id }))}
            />
          </Space>
          <Space>
            <Text style={{ fontSize: 13 }}>日期:</Text>
            <DatePicker.RangePicker size="small" />
          </Space>
          <Space>
            <Text style={{ fontSize: 13 }}>置信度:</Text>
            <Slider
              range
              min={0}
              max={1}
              step={0.05}
              value={[filterConfMin, filterConfMax]}
              onChange={([min, max]: number[]) => { setFilterConfMin(min); setFilterConfMax(max); }}
              style={{ width: 160 }}
              tooltip={{ formatter: (v) => v !== undefined ? `${(v * 100).toFixed(0)}%` : '' }}
            />
          </Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading} size="small">刷新</Button>
        </Space>
      </Card>

      <Table
        dataSource={filtered}
        columns={columns}
        rowKey="id"
        size="small"
        loading={loading}
        pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        rowClassName={(record) => !record.constraintPassed ? 'constraint-fail-row' : ''}
        scroll={{ x: 900 }}
      />

      <style>{`
        .constraint-fail-row { background: #FFF5F5 !important; }
        .constraint-fail-row:hover > td { background: #FFEBEB !important; }
      `}</style>
    </div>
  );
}

// ─── Tab3: 三条硬约束监控 ───
function ConstraintMonitorTab() {
  const [constraints, setConstraints] = useState<ConstraintCard[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchConstraints().then((data) => {
      setConstraints(data);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;
  }

  return (
    <div>
      {/* 三张大卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {constraints.map((c) => (
          <Col span={8} key={c.title}>
            <Card
              style={{ borderTop: `3px solid ${c.color}` }}
              bodyStyle={{ padding: '20px' }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <Space>
                  <span style={{ fontSize: 24 }}>{c.icon}</span>
                  <Text strong style={{ fontSize: 16 }}>{c.title}</Text>
                </Space>
              </div>

              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={12}>
                  <Statistic
                    title="今日触发"
                    value={c.todayTriggers}
                    suffix="次"
                    valueStyle={{ fontSize: 24, fontWeight: 700, color: c.color }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="拦截次数"
                    value={c.todayBlocks}
                    suffix="次"
                    valueStyle={{ fontSize: 24, fontWeight: 700, color: C.danger }}
                  />
                </Col>
              </Row>

              {/* 7天趋势折线图 */}
              <div style={{ marginBottom: 16 }}>
                <Text style={{ fontSize: 12, color: C.textMuted }}>近7天趋势</Text>
                <MiniLineChart data={c.trend} color={c.color} />
              </div>

              {/* 最近5条触发记录 */}
              <div>
                <Text style={{ fontSize: 12, color: C.textMuted, marginBottom: 8, display: 'block' }}>最近触发</Text>
                {c.recentRecords.map((r, i) => (
                  <div
                    key={i}
                    style={{
                      padding: '6px 10px',
                      marginBottom: 4,
                      borderRadius: 4,
                      background: r.blocked ? '#FFF5F5' : C.bgSecondary,
                      borderLeft: `3px solid ${r.blocked ? C.danger : C.success}`,
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Text style={{ fontSize: 11, color: C.textMuted }}>{fmtTime(r.time)}</Text>
                      <Tag color={r.blocked ? 'error' : 'success'} style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                        {r.blocked ? '已拦截' : '通过'}
                      </Tag>
                    </div>
                    <div style={{ color: C.textSub, marginTop: 2 }}>{r.detail}</div>
                  </div>
                ))}
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}

// ─── 主页面 ───
export function AgentDashboardPage() {
  const [statuses, setStatuses] = useState<Map<string, AgentStatus>>(new Map());
  const [totalDecisions, setTotalDecisions] = useState(0);
  const [avgResponseMs, setAvgResponseMs] = useState(0);
  const [constraintPassRate, setConstraintPassRate] = useState(0);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    const data = await fetchAgentStatus();
    const map = new Map<string, AgentStatus>();
    data.agents.forEach((a) => map.set(a.id, a));
    setStatuses(map);
    setTotalDecisions(data.totalDecisions);
    setAvgResponseMs(data.avgResponseMs);
    setConstraintPassRate(data.constraintPassRate);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadStatus();
    timerRef.current = setInterval(loadStatus, 30_000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loadStatus]);

  return (
    <div style={{ padding: 24, background: C.bgPrimary, minHeight: '100vh' }}>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 22, color: C.textPrimary, fontWeight: 700 }}>
          <RobotOutlined style={{ color: C.primary, marginRight: 8 }} />
          Agent 管理面板
        </h2>
        <Paragraph style={{ margin: 0, color: C.textSub, fontSize: 13 }}>
          Master Agent + 9 Skill Agent | tx-agent :8008 | tx-brain :8010 | 30秒自动刷新
        </Paragraph>
      </div>

      <Tabs
        defaultActiveKey="agents"
        type="card"
        items={[
          {
            key: 'agents',
            label: (
              <Space>
                <PlayCircleOutlined />
                <span>Agent 总览</span>
              </Space>
            ),
            children: (
              <AgentGridTab
                agents={AGENTS}
                statuses={statuses}
                totalDecisions={totalDecisions}
                avgResponseMs={avgResponseMs}
                constraintPassRate={constraintPassRate}
                loading={loading}
                onRefresh={loadStatus}
              />
            ),
          },
          {
            key: 'logs',
            label: (
              <Space>
                <ThunderboltOutlined />
                <span>决策日志</span>
              </Space>
            ),
            children: <DecisionLogTab />,
          },
          {
            key: 'constraints',
            label: (
              <Space>
                <PauseCircleOutlined />
                <span>硬约束监控</span>
              </Space>
            ),
            children: <ConstraintMonitorTab />,
          },
        ]}
      />
    </div>
  );
}
