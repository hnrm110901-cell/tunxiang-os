/**
 * Journey Orchestrator — 客户旅程编排器
 *
 * 可视化流程图（SVG手绘） + 右侧节点配置面板
 * 3个预置Journey模板：新客户Onboarding / 续约流程 / 流失挽回
 */
import { useState, useRef, useCallback, useEffect } from 'react';

// ── 颜色常量 ──
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

// ── 类型定义 ──

type NodeType = 'trigger' | 'action' | 'condition' | 'wait';
type NodeStatus = 'done' | 'running' | 'pending';

interface JourneyNode {
  id: string;
  type: NodeType;
  label: string;
  x: number;
  y: number;
  status: NodeStatus;
  config?: {
    playbook?: string;
    notifyTemplate?: string;
    assignee?: string;
    conditionExpr?: string;
    waitDuration?: string;
    waitUnit?: string;
    timeout?: string;
    fallback?: string;
  };
}

interface JourneyEdge {
  from: string;
  to: string;
  label?: string;
}

interface JourneyTemplate {
  id: string;
  name: string;
  description: string;
  nodes: JourneyNode[];
  edges: JourneyEdge[];
}

// ── 节点样式配置 ──

const NODE_STYLES: Record<NodeType, { fill: string; stroke: string; textColor: string; icon: string }> = {
  trigger:   { fill: C.blue + '22',    stroke: C.blue,   textColor: C.blue,   icon: '\u26A1' },
  action:    { fill: C.surface2,       stroke: C.border2, textColor: C.text,   icon: '\u25B6' },
  condition: { fill: C.orange + '22',  stroke: C.orange, textColor: C.orange, icon: '\u2753' },
  wait:      { fill: 'transparent',    stroke: C.text3,  textColor: C.text3,  icon: '\u23F3' },
};

const STATUS_COLORS: Record<NodeStatus, string> = {
  done: C.green,
  running: C.orange,
  pending: C.text3,
};

const STATUS_ICONS: Record<NodeStatus, string> = {
  done: '\u2713',
  running: '\u25CF',
  pending: '\u25CB',
};

// ── 节点尺寸 ──
const NODE_W = 160;
const NODE_H = 56;
const DIAMOND_SIZE = 70;

// ── 模板数据 ──

function makeOnboardingTemplate(): JourneyTemplate {
  return {
    id: 'tmpl-onboarding',
    name: '新客户Onboarding',
    description: '从签约完成到首月回访的全流程编排',
    nodes: [
      { id: 'n1',  type: 'trigger',   label: '触发: 签约完成',       x: 400, y: 30,   status: 'done' },
      { id: 'n2',  type: 'action',    label: '签约确认邮件',         x: 260, y: 130,  status: 'done' },
      { id: 'n3',  type: 'wait',      label: '等待1天',             x: 260, y: 220,  status: 'done', config: { waitDuration: '1', waitUnit: 'day' } },
      { id: 'n4',  type: 'action',    label: '实施启动会议',         x: 400, y: 310,  status: 'running' },
      { id: 'n5',  type: 'action',    label: '数据迁移',            x: 220, y: 420,  status: 'pending' },
      { id: 'n6',  type: 'action',    label: '培训排期',            x: 400, y: 420,  status: 'pending' },
      { id: 'n7',  type: 'action',    label: '设备发货',            x: 580, y: 420,  status: 'pending' },
      { id: 'n8',  type: 'action',    label: '系统上线+门店激活',    x: 400, y: 530,  status: 'pending' },
      { id: 'n9',  type: 'condition', label: '健康分>=80?',         x: 280, y: 640,  status: 'pending', config: { conditionExpr: 'health_score >= 80' } },
      { id: 'n10', type: 'condition', label: '健康分<80?',          x: 520, y: 640,  status: 'pending', config: { conditionExpr: 'health_score < 80' } },
      { id: 'n11', type: 'action',    label: '正常跟进30天',        x: 230, y: 760,  status: 'pending', config: { waitDuration: '30', waitUnit: 'day' } },
      { id: 'n12', type: 'action',    label: '紧急干预Playbook',    x: 570, y: 760,  status: 'pending', config: { playbook: 'pb-intervention' } },
      { id: 'n13', type: 'action',    label: '首月回访总结',         x: 400, y: 870,  status: 'pending' },
      { id: 'n14', type: 'action',    label: '进入季度检查循环',     x: 400, y: 960,  status: 'pending' },
    ],
    edges: [
      { from: 'n1',  to: 'n2' },
      { from: 'n2',  to: 'n3' },
      { from: 'n3',  to: 'n4',  label: '1天后' },
      { from: 'n4',  to: 'n5' },
      { from: 'n4',  to: 'n6' },
      { from: 'n4',  to: 'n7' },
      { from: 'n5',  to: 'n8' },
      { from: 'n6',  to: 'n8' },
      { from: 'n7',  to: 'n8' },
      { from: 'n8',  to: 'n9' },
      { from: 'n8',  to: 'n10' },
      { from: 'n9',  to: 'n11', label: 'Yes' },
      { from: 'n10', to: 'n12', label: 'Yes' },
      { from: 'n11', to: 'n13' },
      { from: 'n12', to: 'n13' },
      { from: 'n13', to: 'n14' },
    ],
  };
}

function makeRenewalTemplate(): JourneyTemplate {
  return {
    id: 'tmpl-renewal',
    name: '续约流程',
    description: '续约前90天到签约完成的全流程编排',
    nodes: [
      { id: 'r1', type: 'trigger',   label: '触发: 续约前90天',     x: 400, y: 30,   status: 'done' },
      { id: 'r2', type: 'action',    label: '通知CSM',             x: 400, y: 130,  status: 'done' },
      { id: 'r3', type: 'action',    label: '准备续约方案',         x: 400, y: 230,  status: 'running' },
      { id: 'r4', type: 'action',    label: '客户拜访',            x: 400, y: 330,  status: 'pending' },
      { id: 'r5', type: 'condition', label: '同意续约?',           x: 400, y: 440,  status: 'pending', config: { conditionExpr: 'renewal_agreed == true' } },
      { id: 'r6', type: 'action',    label: '签约办理',            x: 250, y: 560,  status: 'pending' },
      { id: 'r7', type: 'action',    label: '挽留方案',            x: 550, y: 560,  status: 'pending', config: { playbook: 'pb-retention' } },
      { id: 'r8', type: 'action',    label: '续约完成',            x: 400, y: 670,  status: 'pending' },
    ],
    edges: [
      { from: 'r1', to: 'r2' },
      { from: 'r2', to: 'r3' },
      { from: 'r3', to: 'r4' },
      { from: 'r4', to: 'r5' },
      { from: 'r5', to: 'r6', label: '同意' },
      { from: 'r5', to: 'r7', label: '拒绝' },
      { from: 'r6', to: 'r8' },
      { from: 'r7', to: 'r8' },
    ],
  };
}

function makeChurnTemplate(): JourneyTemplate {
  return {
    id: 'tmpl-churn',
    name: '流失挽回',
    description: '健康分低于60时触发的挽回流程',
    nodes: [
      { id: 'c1', type: 'trigger',   label: '触发: 健康分<60',     x: 400, y: 30,   status: 'done' },
      { id: 'c2', type: 'action',    label: '诊断分析',            x: 400, y: 130,  status: 'done' },
      { id: 'c3', type: 'action',    label: '制定方案',            x: 400, y: 230,  status: 'running' },
      { id: 'c4', type: 'action',    label: '执行干预',            x: 400, y: 330,  status: 'pending', config: { playbook: 'pb-intervention' } },
      { id: 'c5', type: 'wait',      label: '等待14天',            x: 400, y: 420,  status: 'pending', config: { waitDuration: '14', waitUnit: 'day' } },
      { id: 'c6', type: 'condition', label: '健康分回升?',         x: 400, y: 520,  status: 'pending', config: { conditionExpr: 'health_score >= 60' } },
      { id: 'c7', type: 'action',    label: '恢复正常跟进',        x: 250, y: 640,  status: 'pending' },
      { id: 'c8', type: 'action',    label: '升级到管理层',        x: 550, y: 640,  status: 'pending' },
    ],
    edges: [
      { from: 'c1', to: 'c2' },
      { from: 'c2', to: 'c3' },
      { from: 'c3', to: 'c4' },
      { from: 'c4', to: 'c5' },
      { from: 'c5', to: 'c6' },
      { from: 'c6', to: 'c7', label: '回升' },
      { from: 'c6', to: 'c8', label: '未回升' },
    ],
  };
}

const TEMPLATES: JourneyTemplate[] = [
  makeOnboardingTemplate(),
  makeRenewalTemplate(),
  makeChurnTemplate(),
];

// ── SVG 辅助函数 ──

function getNodeCenter(node: JourneyNode): { cx: number; cy: number } {
  if (node.type === 'condition') {
    return { cx: node.x + DIAMOND_SIZE / 2, cy: node.y + DIAMOND_SIZE / 2 };
  }
  return { cx: node.x + NODE_W / 2, cy: node.y + NODE_H / 2 };
}

function getNodeBottom(node: JourneyNode): { x: number; y: number } {
  if (node.type === 'condition') {
    return { x: node.x + DIAMOND_SIZE / 2, y: node.y + DIAMOND_SIZE };
  }
  return { x: node.x + NODE_W / 2, y: node.y + NODE_H };
}

function getNodeTop(node: JourneyNode): { x: number; y: number } {
  if (node.type === 'condition') {
    return { x: node.x + DIAMOND_SIZE / 2, y: node.y };
  }
  return { x: node.x + NODE_W / 2, y: node.y };
}

// ── SVG 节点渲染 ──

function SvgNode({ node, selected, onClick }: {
  node: JourneyNode; selected: boolean; onClick: () => void;
}) {
  const style = NODE_STYLES[node.type];
  const statusColor = STATUS_COLORS[node.status];
  const isRunning = node.status === 'running';

  if (node.type === 'condition') {
    const cx = node.x + DIAMOND_SIZE / 2;
    const cy = node.y + DIAMOND_SIZE / 2;
    const points = `${cx},${node.y} ${node.x + DIAMOND_SIZE},${cy} ${cx},${node.y + DIAMOND_SIZE} ${node.x},${cy}`;
    return (
      <g onClick={onClick} style={{ cursor: 'pointer' }}>
        {isRunning && (
          <polygon
            points={points}
            fill="none"
            stroke={C.orange}
            strokeWidth={3}
            opacity={0.5}
          >
            <animate attributeName="opacity" values="0.5;0.15;0.5" dur="1.5s" repeatCount="indefinite" />
          </polygon>
        )}
        <polygon
          points={points}
          fill={style.fill}
          stroke={selected ? C.orange : style.stroke}
          strokeWidth={selected ? 2.5 : 1.5}
        />
        <text x={cx} y={cy - 6} textAnchor="middle" fill={style.textColor} fontSize={10} fontWeight={600}>
          {style.icon}
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" fill={style.textColor} fontSize={9} fontWeight={500}>
          {node.label.length > 10 ? node.label.slice(0, 10) + '..' : node.label}
        </text>
        {/* Status badge */}
        <circle cx={node.x + DIAMOND_SIZE - 4} cy={node.y + 4} r={6} fill={C.surface} stroke={statusColor} strokeWidth={1.5} />
        <text x={node.x + DIAMOND_SIZE - 4} y={node.y + 7.5} textAnchor="middle" fill={statusColor} fontSize={8}>
          {STATUS_ICONS[node.status]}
        </text>
      </g>
    );
  }

  // rect-based nodes (trigger, action, wait)
  const isDashed = node.type === 'wait';
  return (
    <g onClick={onClick} style={{ cursor: 'pointer' }}>
      {isRunning && (
        <rect
          x={node.x - 3} y={node.y - 3}
          width={NODE_W + 6} height={NODE_H + 6}
          rx={12} ry={12}
          fill="none"
          stroke={C.orange}
          strokeWidth={2}
          opacity={0.5}
        >
          <animate attributeName="opacity" values="0.5;0.15;0.5" dur="1.5s" repeatCount="indefinite" />
        </rect>
      )}
      <rect
        x={node.x} y={node.y}
        width={NODE_W} height={NODE_H}
        rx={8} ry={8}
        fill={style.fill}
        stroke={selected ? C.orange : style.stroke}
        strokeWidth={selected ? 2.5 : 1.5}
        strokeDasharray={isDashed ? '6,3' : undefined}
      />
      {/* Icon */}
      <text x={node.x + 14} y={node.y + NODE_H / 2 + 1} textAnchor="middle" fill={style.textColor} fontSize={13}>
        {style.icon}
      </text>
      {/* Label */}
      <text x={node.x + 28} y={node.y + NODE_H / 2 + 4} fill={style.textColor} fontSize={12} fontWeight={500}>
        {node.label.length > 14 ? node.label.slice(0, 14) + '..' : node.label}
      </text>
      {/* Status badge */}
      <circle cx={node.x + NODE_W - 12} cy={node.y + 12} r={7} fill={C.surface} stroke={statusColor} strokeWidth={1.5} />
      <text x={node.x + NODE_W - 12} y={node.y + 15.5} textAnchor="middle" fill={statusColor} fontSize={9} fontWeight={700}>
        {STATUS_ICONS[node.status]}
      </text>
    </g>
  );
}

// ── SVG 连线渲染 ──

function SvgEdge({ edge, nodes }: { edge: JourneyEdge; nodes: JourneyNode[] }) {
  const fromNode = nodes.find(n => n.id === edge.from);
  const toNode = nodes.find(n => n.id === edge.to);
  if (!fromNode || !toNode) return null;

  const start = getNodeBottom(fromNode);
  const end = getNodeTop(toNode);

  // Simple path with a small curve
  const midY = (start.y + end.y) / 2;
  const d = `M ${start.x} ${start.y} C ${start.x} ${midY}, ${end.x} ${midY}, ${end.x} ${end.y}`;

  return (
    <g>
      <path
        d={d}
        fill="none"
        stroke={C.border2}
        strokeWidth={1.5}
        markerEnd="url(#arrowhead)"
      />
      {edge.label && (
        <text
          x={(start.x + end.x) / 2 + (start.x !== end.x ? 8 : 14)}
          y={(start.y + end.y) / 2 - 2}
          fill={C.text3}
          fontSize={9}
          fontWeight={500}
        >
          {edge.label}
        </text>
      )}
    </g>
  );
}

// ── 右侧配置面板 ──

function ConfigPanel({ node, onClose, onUpdate }: {
  node: JourneyNode;
  onClose: () => void;
  onUpdate: (id: string, updates: Partial<JourneyNode>) => void;
}) {
  const style = NODE_STYLES[node.type];
  const typeLabels: Record<NodeType, string> = {
    trigger: '触发节点', action: '动作节点', condition: '条件节点', wait: '等待节点',
  };

  const [label, setLabel] = useState(node.label);
  const [config, setConfig] = useState(node.config || {});

  useEffect(() => {
    setLabel(node.label);
    setConfig(node.config || {});
  }, [node.id, node.label, node.config]);

  const handleSaveLabel = () => {
    onUpdate(node.id, { label });
  };

  const fieldStyle: React.CSSProperties = {
    width: '100%', padding: '8px 10px', borderRadius: 6,
    border: `1px solid ${C.border2}`, background: C.surface2,
    color: C.text, fontSize: 12, outline: 'none', boxSizing: 'border-box',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 11, color: C.text3, marginBottom: 4, display: 'block',
  };

  return (
    <div style={{
      width: 320, background: C.surface, borderLeft: `1px solid ${C.border}`,
      display: 'flex', flexDirection: 'column', overflow: 'auto',
    }}>
      {/* Header */}
      <div style={{
        padding: '16px 16px 12px', borderBottom: `1px solid ${C.border}`,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            width: 28, height: 28, borderRadius: 6,
            background: style.fill, border: `1px solid ${style.stroke}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14,
          }}>
            {style.icon}
          </span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>{node.label}</div>
            <div style={{ fontSize: 11, color: style.textColor }}>{typeLabels[node.type]}</div>
          </div>
        </div>
        <button onClick={onClose} style={{
          background: 'transparent', border: 'none', color: C.text3,
          fontSize: 18, cursor: 'pointer', padding: '0 4px',
        }}>
          \u2715
        </button>
      </div>

      {/* Status */}
      <div style={{ padding: '12px 16px', borderBottom: `1px solid ${C.border}` }}>
        <span style={labelStyle}>执行状态</span>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          padding: '4px 10px', borderRadius: 12,
          background: STATUS_COLORS[node.status] + '22',
          color: STATUS_COLORS[node.status], fontSize: 12, fontWeight: 600,
        }}>
          {STATUS_ICONS[node.status]} {{ done: '已完成', running: '进行中', pending: '待执行' }[node.status]}
        </div>
      </div>

      {/* Editable fields */}
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        {/* Name */}
        <div>
          <span style={labelStyle}>节点名称</span>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={label}
              onChange={e => setLabel(e.target.value)}
              style={{ ...fieldStyle, flex: 1 }}
            />
            <button onClick={handleSaveLabel} style={{
              background: C.orange, color: '#fff', border: 'none', borderRadius: 6,
              padding: '6px 12px', fontSize: 11, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
            }}>
              保存
            </button>
          </div>
        </div>

        {/* Node type */}
        <div>
          <span style={labelStyle}>节点类型</span>
          <div style={{ ...fieldStyle, background: C.surface3, color: C.text2, cursor: 'default' }}>
            {typeLabels[node.type]}
          </div>
        </div>

        {/* Type-specific config */}
        {node.type === 'action' && (
          <>
            <div>
              <span style={labelStyle}>执行 Playbook</span>
              <select
                value={config.playbook || ''}
                onChange={e => setConfig({ ...config, playbook: e.target.value })}
                style={fieldStyle}
              >
                <option value="">无</option>
                <option value="pb-onboarding">新客户上线 Playbook</option>
                <option value="pb-intervention">紧急干预 Playbook</option>
                <option value="pb-retention">客户挽留 Playbook</option>
                <option value="pb-review">季度回访 Playbook</option>
              </select>
            </div>
            <div>
              <span style={labelStyle}>通知模板</span>
              <select
                value={config.notifyTemplate || ''}
                onChange={e => setConfig({ ...config, notifyTemplate: e.target.value })}
                style={fieldStyle}
              >
                <option value="">不发送</option>
                <option value="email-welcome">欢迎邮件</option>
                <option value="email-kickoff">启动会议通知</option>
                <option value="wecom-alert">企微提醒</option>
              </select>
            </div>
            <div>
              <span style={labelStyle}>负责人</span>
              <input
                value={config.assignee || ''}
                onChange={e => setConfig({ ...config, assignee: e.target.value })}
                placeholder="CSM 姓名"
                style={fieldStyle}
              />
            </div>
          </>
        )}

        {node.type === 'condition' && (
          <div>
            <span style={labelStyle}>条件表达式</span>
            <input
              value={config.conditionExpr || ''}
              onChange={e => setConfig({ ...config, conditionExpr: e.target.value })}
              placeholder="health_score >= 80"
              style={{ ...fieldStyle, fontFamily: 'monospace' }}
            />
          </div>
        )}

        {node.type === 'wait' && (
          <div>
            <span style={labelStyle}>等待时间</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type="number"
                value={config.waitDuration || ''}
                onChange={e => setConfig({ ...config, waitDuration: e.target.value })}
                style={{ ...fieldStyle, flex: 1 }}
              />
              <select
                value={config.waitUnit || 'day'}
                onChange={e => setConfig({ ...config, waitUnit: e.target.value })}
                style={{ ...fieldStyle, flex: 1 }}
              >
                <option value="hour">小时</option>
                <option value="day">天</option>
                <option value="week">周</option>
              </select>
            </div>
          </div>
        )}

        {/* Common: Timeout */}
        <div>
          <span style={labelStyle}>超时设置</span>
          <input
            value={config.timeout || ''}
            onChange={e => setConfig({ ...config, timeout: e.target.value })}
            placeholder="如: 48h / 7d"
            style={fieldStyle}
          />
        </div>

        {/* Common: Fallback */}
        <div>
          <span style={labelStyle}>失败回退策略</span>
          <select
            value={config.fallback || ''}
            onChange={e => setConfig({ ...config, fallback: e.target.value })}
            style={fieldStyle}
          >
            <option value="">默认（跳过）</option>
            <option value="retry">重试3次</option>
            <option value="notify">通知管理员</option>
            <option value="escalate">升级处理</option>
            <option value="abort">终止Journey</option>
          </select>
        </div>
      </div>
    </div>
  );
}

// ── 主组件 ──

export function JourneyPage() {
  const [activeTemplateId, setActiveTemplateId] = useState(TEMPLATES[0].id);
  const [templates, setTemplates] = useState<JourneyTemplate[]>(TEMPLATES);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);

  // SVG pan state
  const svgRef = useRef<SVGSVGElement>(null);
  const [viewBox, setViewBox] = useState({ x: 0, y: 0, w: 900, h: 1100 });
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, vx: 0, vy: 0 });

  const activeTemplate = templates.find(t => t.id === activeTemplateId) || templates[0];
  const selectedNode = selectedNodeId ? activeTemplate.nodes.find(n => n.id === selectedNodeId) : null;

  // Compute viewBox based on template
  useEffect(() => {
    const nodes = activeTemplate.nodes;
    if (nodes.length === 0) return;
    const minX = Math.min(...nodes.map(n => n.x)) - 60;
    const minY = Math.min(...nodes.map(n => n.y)) - 40;
    const maxX = Math.max(...nodes.map(n => n.x + (n.type === 'condition' ? DIAMOND_SIZE : NODE_W))) + 60;
    const maxY = Math.max(...nodes.map(n => n.y + (n.type === 'condition' ? DIAMOND_SIZE : NODE_H))) + 60;
    setViewBox({ x: minX, y: minY, w: maxX - minX, h: maxY - minY });
    setSelectedNodeId(null);
  }, [activeTemplateId]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as SVGElement).tagName === 'svg' || (e.target as SVGElement).closest('svg') === svgRef.current) {
      setIsPanning(true);
      panStart.current = { x: e.clientX, y: e.clientY, vx: viewBox.x, vy: viewBox.y };
    }
  }, [viewBox]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning) return;
    const dx = (e.clientX - panStart.current.x) * (viewBox.w / (svgRef.current?.clientWidth || 900));
    const dy = (e.clientY - panStart.current.y) * (viewBox.h / (svgRef.current?.clientHeight || 1100));
    setViewBox(v => ({ ...v, x: panStart.current.vx - dx, y: panStart.current.vy - dy }));
  }, [isPanning, viewBox.w, viewBox.h]);

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const handleNodeUpdate = useCallback((id: string, updates: Partial<JourneyNode>) => {
    setTemplates(prev => prev.map(t => {
      if (t.id !== activeTemplateId) return t;
      return {
        ...t,
        nodes: t.nodes.map(n => n.id === id ? { ...n, ...updates } : n),
      };
    }));
  }, [activeTemplateId]);

  // Stats
  const totalNodes = activeTemplate.nodes.length;
  const doneNodes = activeTemplate.nodes.filter(n => n.status === 'done').length;
  const runningNodes = activeTemplate.nodes.filter(n => n.status === 'running').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', color: C.text }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 16,
      }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>
            Journey Orchestrator
            <span style={{ fontSize: 13, fontWeight: 400, color: C.text3, marginLeft: 10 }}>
              &#xB7; 客户旅程编排
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Template selector */}
          <select
            value={activeTemplateId}
            onChange={e => setActiveTemplateId(e.target.value)}
            style={{
              padding: '7px 12px', borderRadius: 6,
              border: `1px solid ${C.border2}`, background: C.surface2,
              color: C.text, fontSize: 13, outline: 'none', cursor: 'pointer',
            }}
          >
            {TEMPLATES.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <button
            onClick={() => setIsEditing(!isEditing)}
            style={{
              padding: '7px 14px', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
              background: isEditing ? C.orange + '22' : 'transparent',
              color: isEditing ? C.orange : C.text2,
              border: `1px solid ${isEditing ? C.orange : C.border2}`,
            }}
          >
            {isEditing ? '编辑中' : '编辑'}
          </button>
          <button style={{
            padding: '7px 14px', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            background: C.green + '22', color: C.green, border: `1px solid ${C.green}`,
          }}>
            保存
          </button>
          <button style={{
            padding: '7px 14px', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            background: C.blue + '22', color: C.blue, border: `1px solid ${C.blue}`,
          }}>
            预览
          </button>
        </div>
      </div>

      {/* Stats bar */}
      <div style={{
        display: 'flex', gap: 16, marginBottom: 12, padding: '10px 16px',
        background: C.surface, borderRadius: 8, border: `1px solid ${C.border}`,
      }}>
        <div style={{ fontSize: 12, color: C.text2 }}>
          模板: <span style={{ color: C.text, fontWeight: 600 }}>{activeTemplate.name}</span>
        </div>
        <div style={{ fontSize: 12, color: C.text2 }}>
          节点: <span style={{ color: C.text, fontWeight: 600 }}>{totalNodes}</span>
        </div>
        <div style={{ fontSize: 12, color: C.text2 }}>
          已完成: <span style={{ color: C.green, fontWeight: 600 }}>{doneNodes}</span>
        </div>
        <div style={{ fontSize: 12, color: C.text2 }}>
          进行中: <span style={{ color: C.orange, fontWeight: 600 }}>{runningNodes}</span>
        </div>
        <div style={{ fontSize: 12, color: C.text2 }}>
          待执行: <span style={{ color: C.text3, fontWeight: 600 }}>{totalNodes - doneNodes - runningNodes}</span>
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 11, color: C.text3 }}>
          {activeTemplate.description}
        </div>
      </div>

      {/* Main area: SVG + Config Panel */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0, gap: 0 }}>
        {/* SVG Canvas */}
        <div style={{
          flex: 1, background: C.surface, borderRadius: 10,
          border: `1px solid ${C.border}`, overflow: 'hidden', position: 'relative',
        }}>
          <svg
            ref={svgRef}
            width="100%"
            height="100%"
            viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            style={{ cursor: isPanning ? 'grabbing' : 'grab', display: 'block' }}
          >
            <defs>
              <marker
                id="arrowhead"
                markerWidth="8"
                markerHeight="6"
                refX="7"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill={C.border2} />
              </marker>
            </defs>

            {/* Grid pattern (subtle) */}
            <defs>
              <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke={C.border} strokeWidth={0.3} />
              </pattern>
            </defs>
            <rect x={viewBox.x - 100} y={viewBox.y - 100} width={viewBox.w + 200} height={viewBox.h + 200} fill="url(#grid)" />

            {/* Edges */}
            {activeTemplate.edges.map((edge, i) => (
              <SvgEdge key={`e-${i}`} edge={edge} nodes={activeTemplate.nodes} />
            ))}

            {/* Nodes */}
            {activeTemplate.nodes.map(node => (
              <SvgNode
                key={node.id}
                node={node}
                selected={selectedNodeId === node.id}
                onClick={() => setSelectedNodeId(selectedNodeId === node.id ? null : node.id)}
              />
            ))}
          </svg>

          {/* Legend */}
          <div style={{
            position: 'absolute', bottom: 12, left: 12,
            display: 'flex', gap: 14, padding: '6px 12px',
            background: C.surface + 'ee', borderRadius: 6, border: `1px solid ${C.border}`,
            fontSize: 10, color: C.text3,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 12, borderRadius: 3, background: C.blue + '22', border: `1px solid ${C.blue}`, display: 'inline-block' }} />
              触发
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 12, borderRadius: 3, background: C.surface2, border: `1px solid ${C.border2}`, display: 'inline-block' }} />
              动作
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 12, borderRadius: 1, background: C.orange + '22', border: `1px solid ${C.orange}`, transform: 'rotate(45deg)', display: 'inline-block' }} />
              条件
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 12, borderRadius: 3, border: `1px dashed ${C.text3}`, display: 'inline-block' }} />
              等待
            </div>
            <div style={{ width: 1, background: C.border, margin: '0 4px' }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: C.green }}>{STATUS_ICONS.done}</span> 完成
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: C.orange }}>{STATUS_ICONS.running}</span> 进行中
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: C.text3 }}>{STATUS_ICONS.pending}</span> 待执行
            </div>
          </div>
        </div>

        {/* Config Panel */}
        {selectedNode && (
          <ConfigPanel
            node={selectedNode}
            onClose={() => setSelectedNodeId(null)}
            onUpdate={handleNodeUpdate}
          />
        )}
      </div>

      {/* Pulse animation */}
      <style>{`
        @keyframes journeyPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
