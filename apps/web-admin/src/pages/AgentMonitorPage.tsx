/**
 * Agent 监控页 — 9 个 Skill Agent 状态概览 + 决策日志
 * 接入真实 API：/api/v1/agent-monitor/status | /decisions
 * 30 秒自动刷新
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Col,
  Progress,
  Row,
  Skeleton,
  Tag,
  Timeline,
  Tooltip,
  Typography,
} from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import { txFetch } from '../api';

const { Text, Paragraph } = Typography;

// ─── Design Token 常量（屯象 tokens.md）───
const C = {
  primary:   '#FF6B35',
  success:   '#0F6E56',
  warning:   '#BA7517',
  danger:    '#A32D2D',
  info:      '#185FA5',
  navy:      '#1E2A3A',
  bgCard:    '#112228',
  bgInner:   '#0B1A20',
  bgRow:     '#1a2a33',
  textMuted: '#999',
  textSub:   '#666',
  border:    '#E8E6E1',
};

// ─── 优先级颜色 ───
const PRIORITY_COLOR: Record<string, string> = {
  P0: C.danger,
  P1: C.warning,
  P2: C.info,
};

// ─── 三条硬约束定义 ───
const HARD_CONSTRAINTS = [
  { key: 'margin',    name: '毛利底线', desc: '折扣/赠送不可使毛利低于阈值' },
  { key: 'food_safe', name: '食安合规', desc: '临期/过期食材不可用于出品' },
  { key: 'serve_sla', name: '客户体验', desc: '出餐时间不可超过门店上限' },
];

// ─── 类型定义 ───
interface AgentStat {
  id: string;
  name: string;
  emoji: string;
  priority: 'P0' | 'P1' | 'P2';
  status: 'active' | 'idle';
  today_decisions: number;
  avg_confidence: number | null;
  last_active_at: string | null;
  high_confidence_count: number;
}

interface AgentStatusData {
  agents: AgentStat[];
  summary: {
    total_agents: number;
    active_count: number;
    today_decisions: number;
    generated_at: string;
  };
}

interface DecisionRecord {
  id: string;
  agent_id: string;
  action: string;
  decision_type: string | null;
  confidence: number | null;
  reasoning: string | null;
  constraints_check: Record<string, boolean> | null;
  created_at: string | null;
}

// ─── 置信度颜色 ───
function confidenceColor(v: number | null): string {
  if (v === null) return C.textSub;
  if (v >= 0.8) return C.success;
  if (v >= 0.5) return C.warning;
  return C.danger;
}

// ─── 时间格式化 ───
function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtRelative(iso: string | null): string {
  if (!iso) return '未激活';
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}秒前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  return `${Math.floor(diff / 3600)}小时前`;
}

// ─── 硬约束通过率计算（从决策列表） ───
function calcConstraintPassRate(decisions: DecisionRecord[]): Record<string, number> {
  const counts: Record<string, { pass: number; total: number }> = {};
  HARD_CONSTRAINTS.forEach(({ key }) => { counts[key] = { pass: 0, total: 0 }; });

  for (const d of decisions) {
    if (!d.constraints_check) continue;
    for (const key of Object.keys(counts)) {
      const val = d.constraints_check[key];
      if (val !== undefined) {
        counts[key].total += 1;
        if (val) counts[key].pass += 1;
      }
    }
  }
  const result: Record<string, number> = {};
  for (const key of Object.keys(counts)) {
    const { pass, total } = counts[key];
    result[key] = total === 0 ? 100 : Math.round((pass / total) * 100);
  }
  return result;
}

// ─── 展开/折叠 reasoning ───
function ReasoningText({ text }: { text: string | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return <Text style={{ color: C.textSub, fontSize: 12 }}>—</Text>;
  const short = text.length > 80;
  return (
    <div style={{ fontSize: 12, color: C.textMuted, marginTop: 4 }}>
      {short && !expanded ? `${text.slice(0, 80)}…` : text}
      {short && (
        <span
          onClick={() => setExpanded(!expanded)}
          style={{ color: C.primary, cursor: 'pointer', marginLeft: 4 }}
        >
          {expanded ? '收起' : '展开'}
        </span>
      )}
    </div>
  );
}

// ─── 单条决策记录 ───
function DecisionItem({ record }: { record: DecisionRecord }) {
  const conf = record.confidence;
  const color = confidenceColor(conf);
  const cc = record.constraints_check;

  return (
    <div style={{ background: C.bgInner, borderRadius: 6, padding: '10px 14px', marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{record.action || '—'}</span>
        <span style={{ fontSize: 11, color: C.textSub }}>{fmtTime(record.created_at)}</span>
      </div>

      {/* 置信度进度条 */}
      {conf !== null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: C.textSub, width: 50 }}>置信度</span>
          <Progress
            percent={Math.round(conf * 100)}
            size="small"
            showInfo={false}
            strokeColor={color}
            trailColor={C.bgRow}
            style={{ flex: 1, margin: 0 }}
          />
          <span style={{ fontSize: 11, color, width: 36, textAlign: 'right' }}>
            {Math.round(conf * 100)}%
          </span>
        </div>
      )}

      {/* 推理文字 */}
      <ReasoningText text={record.reasoning} />

      {/* 三条硬约束校验 */}
      {cc && (
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          {HARD_CONSTRAINTS.map(({ key, name }) => {
            const passed = cc[key];
            if (passed === undefined) return null;
            return (
              <Tooltip key={key} title={passed ? `${name}：通过` : `${name}：未通过`}>
                <span style={{ fontSize: 11, color: passed ? C.success : C.danger }}>
                  {passed ? '✅' : '❌'} {name}
                </span>
              </Tooltip>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───
export function AgentMonitorPage() {
  const [statusData, setStatusData] = useState<AgentStatusData | null>(null);
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [decLoading, setDecLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 拉取 Agent 状态
  const fetchStatus = useCallback(async () => {
    try {
      const data = await txFetch<AgentStatusData>('/api/v1/agent-monitor/status');
      setStatusData(data);
    } catch (err) {
      // 静默失败，保留上次数据
    } finally {
      setLoading(false);
    }
  }, []);

  // 拉取决策日志（带 agent_id 过滤）
  const fetchDecisions = useCallback(async (agentId: string | null) => {
    setDecLoading(true);
    try {
      const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}&limit=20` : '?limit=20';
      const data = await txFetch<DecisionRecord[]>(`/api/v1/agent-monitor/decisions${qs}`);
      setDecisions(data);
    } catch {
      setDecisions([]);
    } finally {
      setDecLoading(false);
    }
  }, []);

  // 首次加载 + 30s 定时刷新
  useEffect(() => {
    fetchStatus();
    fetchDecisions(null);

    timerRef.current = setInterval(() => {
      fetchStatus();
      fetchDecisions(selectedAgentId);
    }, 30_000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 切换选中 Agent 时重拉决策
  const handleSelectAgent = (agentId: string) => {
    const next = selectedAgentId === agentId ? null : agentId;
    setSelectedAgentId(next);
    fetchDecisions(next);
  };

  // 汇总数据
  const summary = statusData?.summary;
  const agents  = statusData?.agents ?? [];
  const constraintRates = calcConstraintPassRate(decisions);
  const overallPassRate = HARD_CONSTRAINTS.length === 0 ? 100
    : Math.round(
        Object.values(constraintRates).reduce((s, v) => s + v, 0) / HARD_CONSTRAINTS.length
      );

  // Timeline items（Ant Design 5.x 新 API）
  const timelineItems = decisions.map((d) => ({
    key: d.id,
    color: confidenceColor(d.confidence),
    children: <DecisionItem record={d} />,
  }));

  return (
    <div style={{ padding: 24, background: '#0D1B22', minHeight: '100vh' }}>
      <h2 style={{ marginBottom: 4, color: '#fff' }}>Agent OS 监控</h2>
      <p style={{ color: C.textMuted, marginBottom: 20 }}>
        1 Master + 9 Skill Agent · 30秒自动刷新
        {summary && (
          <span style={{ marginLeft: 12, color: C.textSub }}>
            最后更新：{new Date(summary.generated_at).toLocaleTimeString('zh-CN')}
          </span>
        )}
      </p>

      {/* ── 顶部汇总栏 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <StatisticCard
            style={{ background: C.bgCard, border: 'none', borderRadius: 8 }}
            statistic={{
              title: <span style={{ color: C.textMuted }}>今日总决策</span>,
              value: loading ? '—' : (summary?.today_decisions ?? 0),
              valueStyle: { color: C.primary, fontSize: 28 },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            style={{ background: C.bgCard, border: 'none', borderRadius: 8 }}
            statistic={{
              title: <span style={{ color: C.textMuted }}>活跃 Agent</span>,
              value: loading ? '—' : `${summary?.active_count ?? 0} / ${summary?.total_agents ?? 9}`,
              valueStyle: { color: C.success, fontSize: 28 },
            }}
          />
        </Col>
        <Col span={12}>
          <div style={{ background: C.bgCard, borderRadius: 8, padding: '16px 20px', height: '100%' }}>
            <div style={{ color: C.textMuted, fontSize: 12, marginBottom: 10 }}>
              三条硬约束总通过率
              <Tag color={overallPassRate === 100 ? 'success' : overallPassRate >= 80 ? 'warning' : 'error'}
                   style={{ marginLeft: 8 }}>
                {overallPassRate}%
              </Tag>
            </div>
            <Row gutter={16}>
              {HARD_CONSTRAINTS.map(({ key, name }) => (
                <Col span={8} key={key}>
                  <div style={{ fontSize: 12, color: C.textSub, marginBottom: 4 }}>{name}</div>
                  <Progress
                    percent={constraintRates[key] ?? 100}
                    size="small"
                    strokeColor={
                      (constraintRates[key] ?? 100) === 100 ? C.success :
                      (constraintRates[key] ?? 100) >= 80   ? C.warning : C.danger
                    }
                    trailColor={C.bgRow}
                  />
                </Col>
              ))}
            </Row>
          </div>
        </Col>
      </Row>

      {/* ── 主体：左侧卡片网格 + 右侧决策日志 ── */}
      <Row gutter={20}>
        {/* Agent 卡片网格 */}
        <Col span={14}>
          {loading ? (
            <Skeleton active paragraph={{ rows: 8 }} />
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
              {agents.map((agent) => {
                const isSelected = selectedAgentId === agent.id;
                const priColor = PRIORITY_COLOR[agent.priority];
                const isActive = agent.status === 'active';

                return (
                  <div
                    key={agent.id}
                    onClick={() => handleSelectAgent(agent.id)}
                    style={{
                      background: isSelected ? C.navyLight ?? '#2C3E50' : C.bgCard,
                      borderRadius: 8,
                      padding: '16px 18px',
                      cursor: 'pointer',
                      border: isSelected ? `1.5px solid ${C.primary}` : '1.5px solid transparent',
                      transition: 'border-color 0.2s, background 0.2s',
                    }}
                  >
                    {/* 标题行 */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: 15, fontWeight: 700, color: '#fff' }}>
                        {agent.emoji} {agent.name}
                      </span>
                      <Tag
                        style={{
                          padding: '1px 7px', borderRadius: 10, fontSize: 11, border: 'none',
                          background: priColor + '22', color: priColor,
                        }}
                      >
                        {agent.priority}
                      </Tag>
                    </div>

                    {/* 今日决策次数 */}
                    <div style={{ fontSize: 22, fontWeight: 700, color: isActive ? C.primary : C.textSub, marginBottom: 4 }}>
                      {agent.today_decisions}
                      <span style={{ fontSize: 11, fontWeight: 400, color: C.textMuted, marginLeft: 4 }}>次决策</span>
                    </div>

                    {/* 平均置信度 */}
                    {agent.avg_confidence !== null ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                        <span style={{ fontSize: 11, color: C.textSub, width: 52 }}>平均置信</span>
                        <Progress
                          percent={Math.round(agent.avg_confidence * 100)}
                          size="small"
                          showInfo={false}
                          strokeColor={confidenceColor(agent.avg_confidence)}
                          trailColor={C.bgRow}
                          style={{ flex: 1, margin: 0 }}
                        />
                        <span style={{ fontSize: 11, color: confidenceColor(agent.avg_confidence), width: 32, textAlign: 'right' }}>
                          {Math.round(agent.avg_confidence * 100)}%
                        </span>
                      </div>
                    ) : (
                      <div style={{ height: 24 }} />
                    )}

                    {/* 状态 + 最后活跃 */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>
                        <Badge
                          status={isActive ? 'success' : 'default'}
                          text={
                            <span style={{ fontSize: 11, color: isActive ? C.success : C.textSub }}>
                              {isActive ? '运行中' : '空闲'}
                            </span>
                          }
                        />
                      </span>
                      <span style={{ fontSize: 11, color: C.textSub }}>
                        {fmtRelative(agent.last_active_at)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 三条硬约束卡片 */}
          <div style={{ background: C.bgCard, borderRadius: 8, padding: 20, marginTop: 20 }}>
            <h3 style={{ margin: '0 0 14px', fontSize: 15, color: '#fff' }}>三条硬约束</h3>
            <div style={{ display: 'flex', gap: 16 }}>
              {HARD_CONSTRAINTS.map((c) => {
                const rate = constraintRates[c.key] ?? 100;
                const color = rate === 100 ? C.success : rate >= 80 ? C.warning : C.danger;
                return (
                  <div key={c.key} style={{ flex: 1, padding: 14, background: C.bgInner, borderRadius: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                      <span style={{ color, fontSize: 14 }}>{rate === 100 ? '✓' : '!'}</span>
                      <span style={{ fontWeight: 700, fontSize: 13, color: '#fff' }}>{c.name}</span>
                    </div>
                    <div style={{ fontSize: 11, color: C.textSub, marginBottom: 8 }}>{c.desc}</div>
                    <Progress
                      percent={rate}
                      size="small"
                      strokeColor={color}
                      trailColor={C.bgRow}
                      format={(p) => <span style={{ color, fontSize: 11 }}>{p}%</span>}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </Col>

        {/* 决策日志面板 */}
        <Col span={10}>
          <div style={{ background: C.bgCard, borderRadius: 8, padding: 20, minHeight: 500 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 15, color: '#fff' }}>
                {selectedAgentId
                  ? `${agents.find((a) => a.id === selectedAgentId)?.emoji ?? ''} ${agents.find((a) => a.id === selectedAgentId)?.name ?? ''} 决策日志`
                  : '全部 Agent 决策日志'}
              </h3>
              {selectedAgentId && (
                <span
                  onClick={() => { setSelectedAgentId(null); fetchDecisions(null); }}
                  style={{ fontSize: 12, color: C.primary, cursor: 'pointer' }}
                >
                  查看全部
                </span>
              )}
            </div>

            {decLoading ? (
              <Skeleton active paragraph={{ rows: 6 }} />
            ) : decisions.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: C.textSub }}>
                今日暂无决策记录
              </div>
            ) : (
              <Timeline
                items={timelineItems}
                style={{ paddingTop: 8 }}
              />
            )}
          </div>
        </Col>
      </Row>
    </div>
  );
}
