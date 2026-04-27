/**
 * Workspace: Agents -- Agent 监控（升级 v1 AgentMonitorPage）
 *
 * 左侧列表 + 右侧 Object Page (8 Tab)
 * 保留 Trace+Tab 范式，新增 Action 沙箱和决策可解释
 */
import { useState, useEffect, useMemo } from 'react';
import { hubGet } from '../api/hubApi';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

// ── 类型定义 ──

type AgentStatus = 'active' | 'idle' | 'abnormal' | 'disabled';
type Priority = 'P0' | 'P1' | 'P2';
type RunLocation = 'edge' | 'cloud' | 'hybrid';

interface ConstraintStats {
  name: string;
  passed: number;
  violated: number;
  blocked: number;
}

interface AgentAction {
  id: string;
  name: string;
  description: string;
  callCount: number;
  paramTemplate: string;
}

interface DecisionEvent {
  id: string;
  time: string;
  type: string;
  inputSummary: string;
  outputResult: string;
  confidence: number;
  constraintPass: boolean;
}

interface TraceSpan {
  id: string;
  name: string;
  type: 'llm' | 'tool' | 'db' | 'internal';
  durationMs: number;
  depth: number;
  tokens?: number;
  status: 'ok' | 'error';
}

interface TraceItem {
  traceId: string;
  startTime: string;
  durationMs: number;
  spanCount: number;
  status: 'success' | 'error' | 'timeout';
  spans: TraceSpan[];
}

interface Agent {
  id: string;
  name: string;
  priority: Priority;
  status: AgentStatus;
  runLocation: RunLocation;
  description: string;
  version: string;
  todayDecisions: number;
  successRate: number;
  avgResponseMs: number;
  constraintViolations: number;
  load: number;
  queueDepth: number;
  lastHeartbeat: string;
  constraints: ConstraintStats[];
  actions: AgentAction[];
  decisions: DecisionEvent[];
  traces: TraceItem[];
  relatedServices: string[];
  relatedStores: string[];
}

// ── Mock 数据 ──

function makeConstraints(violations: number): ConstraintStats[] {
  return [
    { name: '毛利底线', passed: 120 - violations, violated: violations, blocked: Math.floor(violations * 0.8) },
    { name: '食安合规', passed: 150, violated: 0, blocked: 0 },
    { name: '客户体验', passed: 98 - Math.floor(violations * 0.5), violated: Math.floor(violations * 0.5), blocked: Math.floor(violations * 0.3) },
  ];
}

function makeActions(agentName: string): AgentAction[] {
  const baseActions: Record<string, AgentAction[]> = {
    '折扣守护 Agent': [
      { id: 'a1', name: 'check_discount', description: '校验折扣是否超过毛利底线', callCount: 234, paramTemplate: '{"order_id": "", "discount_rate": 0}' },
      { id: 'a2', name: 'block_discount', description: '拦截违规折扣', callCount: 32, paramTemplate: '{"order_id": "", "reason": ""}' },
      { id: 'a3', name: 'alert_manager', description: '通知店长异常折扣', callCount: 15, paramTemplate: '{"store_id": "", "message": ""}' },
    ],
    '智能排菜 Agent': [
      { id: 'a1', name: 'analyze_inventory', description: '分析当前库存与菜品销量', callCount: 89, paramTemplate: '{"store_id": "", "date": ""}' },
      { id: 'a2', name: 'suggest_menu', description: '生成今日推荐菜单', callCount: 45, paramTemplate: '{"store_id": "", "meal_period": ""}' },
      { id: 'a3', name: 'adjust_priority', description: '调整菜品推荐优先级', callCount: 67, paramTemplate: '{"dish_id": "", "priority": 0}' },
    ],
  };
  return baseActions[agentName] || [
    { id: 'a1', name: 'execute', description: `${agentName}核心执行`, callCount: Math.floor(Math.random() * 100 + 20), paramTemplate: '{"target": ""}' },
    { id: 'a2', name: 'analyze', description: '数据分析', callCount: Math.floor(Math.random() * 50 + 10), paramTemplate: '{"scope": ""}' },
    { id: 'a3', name: 'notify', description: '通知相关人员', callCount: Math.floor(Math.random() * 30 + 5), paramTemplate: '{"channel": "", "message": ""}' },
  ];
}

function makeDecisions(agentName: string): DecisionEvent[] {
  const types = ['discount_check', 'menu_adjust', 'inventory_alert', 'dispatch_optimize', 'member_insight'];
  return Array.from({ length: 8 }, (_, i) => ({
    id: `dec-${i + 1}`,
    time: `2026-04-26 ${String(8 + Math.floor(i / 2)).padStart(2, '0')}:${String(i * 7 % 60).padStart(2, '0')}`,
    type: types[i % types.length],
    inputSummary: `${agentName} 输入: 门店数据快照 #${i + 1}`,
    outputResult: `决策 #${i + 1}: ${i % 3 === 0 ? '执行' : i % 3 === 1 ? '告警' : '跳过'}`,
    confidence: +(0.75 + Math.random() * 0.23).toFixed(2),
    constraintPass: i !== 3,
  }));
}

function makeTraces(): TraceItem[] {
  return Array.from({ length: 5 }, (_, i) => ({
    traceId: `trace-${String(i + 1).padStart(3, '0')}`,
    startTime: `2026-04-26 ${String(8 + i).padStart(2, '0')}:${String(i * 12 % 60).padStart(2, '0')}:00`,
    durationMs: 120 + Math.floor(Math.random() * 400),
    spanCount: 3 + Math.floor(Math.random() * 5),
    status: i === 2 ? 'error' : 'success',
    spans: [
      { id: `sp-${i}-1`, name: 'agent.execute', type: 'internal', durationMs: 5, depth: 0, status: 'ok' },
      { id: `sp-${i}-2`, name: 'llm.claude_call', type: 'llm', durationMs: 80 + Math.floor(Math.random() * 200), depth: 1, tokens: 450 + Math.floor(Math.random() * 300), status: 'ok' },
      { id: `sp-${i}-3`, name: 'db.query_orders', type: 'db', durationMs: 12 + Math.floor(Math.random() * 30), depth: 1, status: 'ok' },
      { id: `sp-${i}-4`, name: 'tool.check_constraint', type: 'tool', durationMs: 8 + Math.floor(Math.random() * 15), depth: 1, status: i === 2 ? 'error' : 'ok' },
      { id: `sp-${i}-5`, name: 'agent.respond', type: 'internal', durationMs: 3, depth: 0, status: 'ok' },
    ],
  }));
}

function makeAgent(
  id: string, name: string, priority: Priority, status: AgentStatus,
  runLocation: RunLocation, description: string,
  decisions: number, successRate: number, avgMs: number, violations: number,
): Agent {
  return {
    id, name, priority, status, runLocation, description,
    version: '1.2.0',
    todayDecisions: decisions, successRate, avgResponseMs: avgMs, constraintViolations: violations,
    load: Math.floor(Math.random() * 60 + 10),
    queueDepth: Math.floor(Math.random() * 5),
    lastHeartbeat: `${Math.floor(Math.random() * 30 + 1)}秒前`,
    constraints: makeConstraints(violations),
    actions: makeActions(name),
    decisions: makeDecisions(name),
    traces: makeTraces(),
    relatedServices: runLocation === 'edge' ? ['tx-agent', 'mac-station', 'coreml-bridge'] : runLocation === 'hybrid' ? ['tx-agent', 'tx-brain', 'mac-station'] : ['tx-agent', 'tx-brain'],
    relatedStores: ['长沙万达店', '广州天河店', '解放西店'].slice(0, Math.floor(Math.random() * 3 + 1)),
  };
}

const MOCK_AGENTS: Agent[] = [
  makeAgent('agent-001', '折扣守护 Agent', 'P0', 'active', 'hybrid', '实时监控所有折扣行为，拦截超过毛利底线的异常折扣', 234, 99.1, 12, 3),
  makeAgent('agent-002', '智能排菜 Agent', 'P0', 'active', 'cloud', '基于库存、销量、时段智能生成推荐菜单', 89, 97.5, 45, 0),
  makeAgent('agent-003', '出餐调度 Agent', 'P1', 'active', 'edge', '优化后厨出餐顺序，预测出餐时间', 156, 98.2, 23, 1),
  makeAgent('agent-004', '会员洞察 Agent', 'P1', 'active', 'cloud', 'VIP识别、消费偏好分析、个性化推荐', 67, 96.8, 120, 0),
  makeAgent('agent-005', '库存预警 Agent', 'P1', 'active', 'hybrid', '实时库存监控，缺货/过期预警，采购建议', 98, 98.5, 35, 1),
  makeAgent('agent-006', '财务稽核 Agent', 'P1', 'idle', 'cloud', '日结核销、成本异常检测、P&L分析', 45, 99.0, 89, 0),
  makeAgent('agent-007', '巡店质检 Agent', 'P2', 'active', 'cloud', '生成巡检清单、检查结果评分、整改追踪', 52, 97.2, 67, 0),
  makeAgent('agent-008', '智能客服 Agent', 'P2', 'active', 'cloud', '自动回复顾客咨询、投诉分类与升级', 23, 95.5, 150, 2),
  makeAgent('agent-009', '私域运营 Agent', 'P2', 'abnormal', 'cloud', '会员触达、活动策划、流失预警、回归营销', 38, 92.3, 210, 3),
];

// ── 样式 ──

const STATUS_COLOR: Record<AgentStatus, string> = {
  active: C.green, idle: C.yellow, abnormal: C.red, disabled: C.text3,
};
const STATUS_LABEL: Record<AgentStatus, string> = {
  active: '活跃', idle: '空闲', abnormal: '异常', disabled: '禁用',
};
const PRIORITY_COLOR: Record<Priority, string> = { P0: C.red, P1: C.orange, P2: C.blue };
const RUN_LABEL: Record<RunLocation, string> = { edge: '边缘', cloud: '云端', hybrid: '双层' };
const SPAN_TYPE_COLOR: Record<string, string> = { llm: C.purple, tool: C.orange, db: C.blue, internal: C.text3 };

type FilterKey = 'all' | AgentStatus;
type TabKey = 'overview' | 'timeline' | 'traces' | 'actions' | 'related' | 'cost' | 'logs' | 'playbooks';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'traces', label: 'Traces' },
  { key: 'actions', label: 'Actions' },
  { key: 'related', label: 'Related' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
  { key: 'playbooks', label: 'Playbooks' },
];

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '活跃' },
  { key: 'idle', label: '空闲' },
  { key: 'abnormal', label: '异常' },
  { key: 'disabled', label: '禁用' },
];

// ── Helpers ──

function Placeholder({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200, color: C.text3, fontSize: 14 }}>
      {label}
    </div>
  );
}

function KpiCard({ label, value, color, suffix }: { label: string; value: string | number; color: string; suffix?: string }) {
  return (
    <div style={{ flex: '1 1 140px', background: C.surface, borderRadius: 10, padding: '14px 16px', border: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 11, color: C.text3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>
        {value}{suffix && <span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2 }}>{suffix}</span>}
      </div>
    </div>
  );
}

function MetricBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: C.surface3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', borderRadius: 3, background: color, transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontSize: 12, color, fontWeight: 600, minWidth: 36, textAlign: 'right' }}>{value}%</span>
    </div>
  );
}

// ── Overview Tab ──

function OverviewTab({ agent }: { agent: Agent }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Agent 信息 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>Agent 信息</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          {([
            ['名称', agent.name],
            ['优先级', agent.priority],
            ['运行位置', RUN_LABEL[agent.runLocation]],
            ['版本', agent.version],
            ['状态', STATUS_LABEL[agent.status]],
            ['描述', agent.description],
          ] as const).map(([label, val]) => (
            <div key={label} style={label === '描述' ? { gridColumn: '1 / -1' } : undefined}>
              <div style={{ color: C.text3, fontSize: 11, marginBottom: 2 }}>{label}</div>
              <div style={{
                color: label === '优先级' ? PRIORITY_COLOR[val as Priority] || C.text
                  : label === '状态' ? STATUS_COLOR[agent.status]
                  : C.text,
                fontWeight: (label === '优先级' || label === '状态') ? 600 : 400,
              }}>{val}</div>
            </div>
          ))}
        </div>
      </div>

      {/* KPI */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <KpiCard label="今日决策数" value={agent.todayDecisions} color={C.orange} />
        <KpiCard label="成功率" value={`${agent.successRate}%`} color={C.green} />
        <KpiCard label="平均响应时间" value={agent.avgResponseMs} color={C.blue} suffix="ms" />
        <KpiCard label="约束违规数" value={agent.constraintViolations} color={agent.constraintViolations > 0 ? C.red : C.green} />
      </div>

      {/* 运行状态 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>运行状态</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px 24px', fontSize: 13 }}>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>在线状态</div>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: STATUS_COLOR[agent.status] }} />
              <span style={{ color: STATUS_COLOR[agent.status], fontWeight: 600 }}>{STATUS_LABEL[agent.status]}</span>
            </span>
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>负载</div>
            <MetricBar value={agent.load} max={100} color={agent.load > 80 ? C.red : agent.load > 50 ? C.yellow : C.green} />
          </div>
          <div>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>队列深度</div>
            <div style={{ color: agent.queueDepth > 3 ? C.yellow : C.text, fontSize: 13, fontWeight: 600 }}>{agent.queueDepth}</div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={{ color: C.text3, fontSize: 11, marginBottom: 4 }}>最近心跳</div>
            <div style={{ color: C.text, fontSize: 13 }}>{agent.lastHeartbeat}</div>
          </div>
        </div>
      </div>

      {/* 三条硬约束校验 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>三条硬约束校验统计</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {agent.constraints.map(c => (
            <div key={c.name} style={{ background: C.surface2, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 8 }}>{c.name}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: C.text3 }}>通过</span>
                  <span style={{ color: C.green, fontWeight: 600 }}>{c.passed}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: C.text3 }}>违规</span>
                  <span style={{ color: c.violated > 0 ? C.red : C.text3, fontWeight: 600 }}>{c.violated}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: C.text3 }}>拦截</span>
                  <span style={{ color: c.blocked > 0 ? C.orange : C.text3, fontWeight: 600 }}>{c.blocked}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Actions 注册表 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>Actions 注册表</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: `1px solid ${C.border}`, color: C.text3, fontSize: 12, fontWeight: 600 }}>名称</th>
              <th style={{ textAlign: 'left', padding: '8px 10px', borderBottom: `1px solid ${C.border}`, color: C.text3, fontSize: 12, fontWeight: 600 }}>描述</th>
              <th style={{ textAlign: 'right', padding: '8px 10px', borderBottom: `1px solid ${C.border}`, color: C.text3, fontSize: 12, fontWeight: 600 }}>调用次数</th>
            </tr>
          </thead>
          <tbody>
            {agent.actions.map(a => (
              <tr key={a.id}>
                <td style={{ padding: '8px 10px', borderBottom: `1px solid ${C.border}`, fontFamily: 'monospace', color: C.orange }}>{a.name}</td>
                <td style={{ padding: '8px 10px', borderBottom: `1px solid ${C.border}`, color: C.text2 }}>{a.description}</td>
                <td style={{ padding: '8px 10px', borderBottom: `1px solid ${C.border}`, color: C.text, fontWeight: 600, textAlign: 'right' }}>{a.callCount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Timeline Tab ──

function TimelineTab({ agent }: { agent: Agent }) {
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 16 }}>决策事件流</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {agent.decisions.map((dec, i) => {
          const confPct = Math.round(dec.confidence * 100);
          const confColor = confPct >= 90 ? C.green : confPct >= 75 ? C.yellow : C.red;
          return (
            <div key={dec.id} style={{
              background: C.surface, borderRadius: 8, padding: 14, border: `1px solid ${C.border}`,
              marginBottom: i < agent.decisions.length - 1 ? 8 : 0,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 11, color: C.text3, fontFamily: 'monospace' }}>{dec.time}</span>
                  <span style={{
                    fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                    background: C.blue + '22', color: C.blue,
                  }}>{dec.type}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {/* 置信度条 */}
                  <div style={{ width: 60, height: 5, borderRadius: 3, background: C.surface3, overflow: 'hidden' }}>
                    <div style={{ width: `${confPct}%`, height: '100%', borderRadius: 3, background: confColor }} />
                  </div>
                  <span style={{ fontSize: 11, color: confColor, fontWeight: 600 }}>{confPct}%</span>
                  {/* 约束校验 */}
                  <span style={{
                    fontSize: 12, fontWeight: 600,
                    color: dec.constraintPass ? C.green : C.red,
                  }}>{dec.constraintPass ? '\u2713' : '\u2717'}</span>
                </div>
              </div>
              <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>{dec.inputSummary}</div>
              <div style={{ fontSize: 13, color: C.text, fontWeight: 500 }}>{dec.outputResult}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Traces Tab ──

function TracesTab({ agent }: { agent: Agent }) {
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);

  const statusColor: Record<string, string> = { success: C.green, error: C.red, timeout: C.yellow };

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 16 }}>Trace 列表</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {agent.traces.map(trace => {
          const isExpanded = expandedTrace === trace.traceId;
          const maxSpanDuration = Math.max(...trace.spans.map(s => s.durationMs), 1);
          return (
            <div key={trace.traceId} style={{ background: C.surface, borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
              {/* Trace header */}
              <div
                onClick={() => setExpandedTrace(isExpanded ? null : trace.traceId)}
                style={{ padding: 14, cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace' }}>{trace.traceId}</span>
                  <span style={{ fontSize: 11, color: C.text3 }}>{trace.startTime}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 12, color: C.text2 }}>{trace.durationMs}ms</span>
                  <span style={{ fontSize: 11, color: C.text3 }}>{trace.spanCount} spans</span>
                  <span style={{
                    fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                    background: (statusColor[trace.status] || C.text3) + '22',
                    color: statusColor[trace.status] || C.text3,
                  }}>{trace.status}</span>
                  <span style={{ color: C.text3, fontSize: 12 }}>{isExpanded ? '\u25B2' : '\u25BC'}</span>
                </div>
              </div>

              {/* Expanded: Span waterfall */}
              {isExpanded && (
                <div style={{ borderTop: `1px solid ${C.border}`, padding: 14 }}>
                  {trace.spans.map(span => {
                    const barWidth = Math.max(5, (span.durationMs / maxSpanDuration) * 100);
                    const typeColor = SPAN_TYPE_COLOR[span.type] || C.text3;
                    return (
                      <div key={span.id} style={{
                        display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0',
                        paddingLeft: span.depth * 24,
                      }}>
                        {/* Span name */}
                        <span style={{ fontSize: 12, color: C.text, fontFamily: 'monospace', minWidth: 160 }}>{span.name}</span>
                        {/* Type badge */}
                        <span style={{
                          fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 3,
                          background: typeColor + '22', color: typeColor, minWidth: 40, textAlign: 'center',
                        }}>{span.type.toUpperCase()}</span>
                        {/* Duration bar */}
                        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6 }}>
                          <div style={{ width: `${barWidth}%`, height: 8, borderRadius: 4, background: typeColor, minWidth: 4, transition: 'width 0.3s' }} />
                          <span style={{ fontSize: 11, color: C.text3, whiteSpace: 'nowrap' }}>{span.durationMs}ms</span>
                        </div>
                        {/* Token count for LLM spans */}
                        {span.tokens != null && (
                          <span style={{ fontSize: 10, color: C.purple, fontWeight: 600 }}>{span.tokens} tok</span>
                        )}
                        {/* Status */}
                        <span style={{ fontSize: 11, color: span.status === 'ok' ? C.green : C.red, fontWeight: 600 }}>
                          {span.status === 'ok' ? '\u2713' : '\u2717'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Actions Tab (Sandbox) ──

function ActionsTab({ agent }: { agent: Agent }) {
  const [selectedAction, setSelectedAction] = useState<AgentAction | null>(null);
  const [params, setParams] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const handleDryRun = () => {
    if (!selectedAction) return;
    setRunning(true);
    setResult(null);
    // Simulate sandbox execution
    setTimeout(() => {
      setResult(JSON.stringify({
        action: selectedAction.name,
        input: (() => { try { return JSON.parse(params); } catch { return params; } })(),
        output: { status: 'success', message: `[沙箱] ${selectedAction.name} 执行完成`, side_effects: [] },
        duration_ms: Math.floor(Math.random() * 100 + 20),
        sandbox: true,
      }, null, 2));
      setRunning(false);
    }, 800);
  };

  return (
    <div>
      {/* Sandbox badge */}
      <div style={{
        background: C.yellow + '15', border: `1px solid ${C.yellow}44`, borderRadius: 8,
        padding: '10px 16px', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ fontSize: 16 }}>&#x1F6E1;</span>
        <span style={{ fontSize: 13, color: C.yellow, fontWeight: 600 }}>沙箱模式</span>
        <span style={{ fontSize: 12, color: C.text3 }}>- 不影响生产环境</span>
      </div>

      {/* Action cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
        {agent.actions.map(a => {
          const isSelected = selectedAction?.id === a.id;
          return (
            <div
              key={a.id}
              onClick={() => { setSelectedAction(a); setParams(a.paramTemplate); setResult(null); }}
              style={{
                background: isSelected ? C.orange + '15' : C.surface,
                border: `1px solid ${isSelected ? C.orange : C.border}`,
                borderRadius: 8, padding: 12, cursor: 'pointer', transition: 'all 0.15s',
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, color: C.orange, fontFamily: 'monospace', marginBottom: 4 }}>{a.name}</div>
              <div style={{ fontSize: 11, color: C.text3, marginBottom: 6 }}>{a.description}</div>
              <div style={{ fontSize: 11, color: C.text3 }}>调用 {a.callCount} 次</div>
            </div>
          );
        })}
      </div>

      {/* Dry run panel */}
      {selectedAction && (
        <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>
            试跑: <span style={{ color: C.orange, fontFamily: 'monospace' }}>{selectedAction.name}</span>
          </div>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>测试参数 (JSON)</div>
            <textarea
              value={params}
              onChange={e => setParams(e.target.value)}
              style={{
                width: '100%', minHeight: 80, background: C.surface2, color: C.text, border: `1px solid ${C.border}`,
                borderRadius: 6, padding: '8px 12px', fontSize: 12, fontFamily: 'monospace', outline: 'none', resize: 'vertical',
                boxSizing: 'border-box',
              }}
            />
          </div>
          <button
            onClick={handleDryRun}
            disabled={running}
            style={{
              background: running ? C.surface3 : C.orange, color: '#fff', border: 'none', borderRadius: 6,
              padding: '8px 20px', fontSize: 13, fontWeight: 600, cursor: running ? 'wait' : 'pointer',
            }}
          >{running ? '执行中...' : '试跑'}</button>

          {result && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>执行结果</div>
              <pre style={{
                background: C.surface2, color: C.green, border: `1px solid ${C.border}`, borderRadius: 6,
                padding: 12, fontSize: 12, fontFamily: 'monospace', overflow: 'auto', maxHeight: 300,
                whiteSpace: 'pre-wrap', margin: 0,
              }}>{result}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Related Tab ──

function RelatedTab({ agent }: { agent: Agent }) {
  const mockIncidents = [
    { id: 'INC-012', title: '折扣守护Agent误拦截正常折扣', status: '已解决', time: '2026-04-20' },
    { id: 'INC-018', title: 'Agent响应超时（>5s）', status: '已解决', time: '2026-04-22' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 关联服务 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>关联服务</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {agent.relatedServices.map(svc => (
            <div key={svc} style={{
              background: C.surface2, borderRadius: 6, padding: '8px 14px', border: `1px solid ${C.border}`,
              fontSize: 13, color: C.text, fontFamily: 'monospace',
            }}>{svc}</div>
          ))}
        </div>
      </div>

      {/* 关联门店 */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>部署此 Agent 的门店</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {agent.relatedStores.map(store => (
            <div key={store} style={{
              background: C.surface2, borderRadius: 6, padding: '8px 14px', border: `1px solid ${C.border}`,
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ fontSize: 13, color: C.text }}>{store}</span>
              <span style={{ fontSize: 11, color: C.orange, cursor: 'pointer' }}>查看</span>
            </div>
          ))}
        </div>
      </div>

      {/* 最近 Incident */}
      <div style={{ background: C.surface, borderRadius: 10, padding: 16, border: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>最近 Incident</div>
        {mockIncidents.map(inc => (
          <div key={inc.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${C.border}` }}>
            <div>
              <span style={{ fontSize: 12, color: C.text3, fontFamily: 'monospace', marginRight: 8 }}>{inc.id}</span>
              <span style={{ fontSize: 13, color: C.text }}>{inc.title}</span>
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: C.text3 }}>{inc.time}</span>
              <span style={{
                fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                background: C.green + '22', color: C.green,
              }}>{inc.status}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Export ──

export function AgentsWorkspace() {
  const [agents, setAgents] = useState<Agent[]>(MOCK_AGENTS);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [tab, setTab] = useState<TabKey>('overview');

  // 尝试从 API 加载
  useEffect(() => {
    hubGet<Agent[]>('/agents')
      .then(data => { if (Array.isArray(data) && data.length > 0) setAgents(data); })
      .catch(() => { /* 使用 Mock */ });
  }, []);

  const filtered = useMemo(() => {
    if (filter === 'all') return agents;
    return agents.filter(a => a.status === filter);
  }, [agents, filter]);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: agents.length };
    for (const a of agents) m[a.status] = (m[a.status] || 0) + 1;
    return m;
  }, [agents]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      {/* 顶部栏 */}
      <div style={{ fontSize: 20, fontWeight: 700, color: C.text, marginBottom: 16 }}>Agent</div>

      <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>
        {/* 左侧列表 */}
        <div style={{ width: 380, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          {/* 筛选 chips */}
          <div style={{ padding: '12px 14px', borderBottom: `1px solid ${C.border}`, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {FILTERS.map(f => (
              <button key={f.key} onClick={() => setFilter(f.key)} style={{
                background: filter === f.key ? C.orange + '22' : 'transparent',
                color: filter === f.key ? C.orange : C.text3,
                border: `1px solid ${filter === f.key ? C.orange : C.border}`,
                borderRadius: 20, padding: '3px 10px', fontSize: 11, cursor: 'pointer',
              }}>
                {f.label} {counts[f.key] ?? 0}
              </button>
            ))}
          </div>
          {/* 列表项 */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filtered.map(agent => {
              const isActive = selected?.id === agent.id;
              return (
                <div key={agent.id} onClick={() => { setSelected(agent); setTab('overview'); }} style={{
                  padding: '10px 14px', cursor: 'pointer',
                  borderLeft: isActive ? `3px solid ${C.orange}` : '3px solid transparent',
                  background: isActive ? C.orange + '0D' : 'transparent',
                  borderBottom: `1px solid ${C.border}`,
                  transition: 'background 0.15s',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 4, background: STATUS_COLOR[agent.status], flexShrink: 0 }} />
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{agent.name}</span>
                    <span style={{
                      fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3, marginLeft: 'auto',
                      background: PRIORITY_COLOR[agent.priority] + '22',
                      color: PRIORITY_COLOR[agent.priority],
                    }}>{agent.priority}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingLeft: 16 }}>
                    <span style={{ fontSize: 12, color: C.text2 }}>
                      今日 {agent.todayDecisions} 决策
                    </span>
                    <span style={{ fontSize: 11, color: agent.successRate >= 98 ? C.green : agent.successRate >= 95 ? C.yellow : C.red, fontWeight: 600 }}>
                      {agent.successRate}%
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 右侧 Object Page */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!selected ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.text3, fontSize: 14 }}>
              选择一个 Agent 查看详情
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{ width: 10, height: 10, borderRadius: 5, background: STATUS_COLOR[selected.status] }} />
                <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{selected.name}</span>
                <span style={{
                  fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                  background: PRIORITY_COLOR[selected.priority] + '22',
                  color: PRIORITY_COLOR[selected.priority],
                }}>{selected.priority}</span>
                <span style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 4,
                  background: C.surface2, color: C.text3, border: `1px solid ${C.border}`,
                }}>{RUN_LABEL[selected.runLocation]}</span>
              </div>
              {/* Tab bar */}
              <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${C.border}`, marginBottom: 16 }}>
                {TABS.map(t => (
                  <button key={t.key} onClick={() => setTab(t.key)} style={{
                    padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    color: tab === t.key ? C.orange : C.text3,
                    borderBottom: tab === t.key ? `2px solid ${C.orange}` : '2px solid transparent',
                    background: 'transparent', border: 'none', borderBottomStyle: 'solid' as const,
                  }}>{t.label}</button>
                ))}
              </div>
              {/* Tab content */}
              <div style={{ flex: 1, overflowY: 'auto' }}>
                {tab === 'overview' && <OverviewTab agent={selected} />}
                {tab === 'timeline' && <TimelineTab agent={selected} />}
                {tab === 'traces' && <TracesTab agent={selected} />}
                {tab === 'actions' && <ActionsTab agent={selected} />}
                {tab === 'related' && <RelatedTab agent={selected} />}
                {tab === 'cost' && <Placeholder label="成本数据接入中" />}
                {tab === 'logs' && <Placeholder label="日志接入中" />}
                {tab === 'playbooks' && <Placeholder label="关联剧本列表" />}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
