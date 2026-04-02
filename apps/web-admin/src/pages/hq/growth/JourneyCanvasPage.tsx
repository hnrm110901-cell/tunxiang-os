/**
 * JourneyCanvasPage — 客户旅程画布编辑器
 * 路由: /hq/growth/journeys/:journeyId/canvas
 * 左侧节点库 + 中间画布 + 右侧配置面板
 * 接入真实API：GET/PUT /api/v1/member/journeys/{id}/canvas
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
const BG_0 = '#0d1e28';
const BG_1 = '#1a2a33';
const BG_2 = '#223344';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const CYAN = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

type NodeType =
  | 'trigger'
  | 'condition'
  | 'action'
  | 'wait'
  | 'wechat-work'
  | 'sms'
  | 'miniapp-msg'
  | 'benefit'
  | 'ab-test'
  | 'manual-task';

type JourneyStatus = 'draft' | 'active' | 'paused' | 'ended';

interface NodeTemplate {
  type: NodeType;
  label: string;
  icon: string;
  color: string;
  category: string;
}

interface CanvasNode {
  id: string;
  type: NodeType;
  label: string;
  icon: string;
  color: string;
  config: NodeConfig;
  children: string[];
}

interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

interface NodeConfig {
  triggerType?: string;
  segment?: string;
  conditionField?: string;
  conditionOperator?: string;
  conditionValue?: string;
  templateName?: string;
  content?: string;
  benefitType?: string;
  benefitValue?: string;
  waitDays?: number;
  waitHours?: number;
  splitRatio?: number;
  taskDescription?: string;
  assignee?: string;
  [key: string]: unknown;
}

interface CanvasData {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

interface JourneySummary {
  id: string;
  name: string;
  status: JourneyStatus;
  target_count: number;
  executed_count: number;
  conversion_rate: number;
  versions?: { version: number; date: string; author: string }[];
}

// ---- 节点模板库 ----

const NODE_TEMPLATES: NodeTemplate[] = [
  { type: 'trigger', label: '触发器', icon: '⚡', color: BRAND, category: '入口' },
  { type: 'condition', label: '条件判断', icon: '🔀', color: YELLOW, category: '逻辑' },
  { type: 'wait', label: '等待', icon: '⏳', color: TEXT_3, category: '逻辑' },
  { type: 'ab-test', label: 'AB实验', icon: '🧪', color: CYAN, category: '逻辑' },
  { type: 'wechat-work', label: '企业微信', icon: '💬', color: GREEN, category: '触达' },
  { type: 'sms', label: '短信', icon: '📧', color: BLUE, category: '触达' },
  { type: 'miniapp-msg', label: '小程序消息', icon: '📱', color: CYAN, category: '触达' },
  { type: 'benefit', label: '权益发放', icon: '🎁', color: PURPLE, category: '动作' },
  { type: 'manual-task', label: '人工任务', icon: '👤', color: YELLOW, category: '动作' },
];

const NODE_COLOR_MAP: Partial<Record<NodeType, string>> = {
  trigger: BRAND,
  condition: YELLOW,
  action: BLUE,
  wait: TEXT_4,
  'wechat-work': GREEN,
  sms: BLUE,
  'miniapp-msg': CYAN,
  benefit: PURPLE,
  'ab-test': CYAN,
  'manual-task': YELLOW,
};

// ---- 工具函数：根据节点列表构建edges ----

function buildEdgesFromNodes(nodes: CanvasNode[]): CanvasEdge[] {
  const edges: CanvasEdge[] = [];
  for (const node of nodes) {
    for (let i = 0; i < node.children.length; i++) {
      const target = node.children[i];
      edges.push({
        id: `e-${node.id}-${target}`,
        source: node.id,
        target,
        label: node.type === 'condition' ? (i === 0 ? '是' : '否') :
          node.type === 'ab-test' ? (i === 0 ? 'A组' : 'B组') : undefined,
      });
    }
  }
  return edges;
}

// ---- 空画布引导 ----

function EmptyCanvasGuide({ onAddTrigger }: { onAddTrigger: () => void }) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      background: BG_0, borderRadius: 10, border: `1px dashed ${BG_2}`,
      minHeight: 400, gap: 16,
    }}>
      <div style={{ fontSize: 48 }}>🗺️</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: TEXT_2 }}>旅程画布为空</div>
      <div style={{ fontSize: 13, color: TEXT_4, textAlign: 'center', maxWidth: 280 }}>
        从左侧节点库拖拽节点到画布，或点击下方按钮添加触发器开始构建旅程
      </div>
      <button
        onClick={onAddTrigger}
        style={{
          padding: '10px 24px', borderRadius: 8, border: 'none',
          background: BRAND, color: '#fff', fontSize: 14, fontWeight: 700,
          cursor: 'pointer', marginTop: 8,
        }}
      >⚡ 添加触发器节点</button>
    </div>
  );
}

// ---- 节点库侧边栏 ----

function NodeLibrarySidebar({ onAddNode }: { onAddNode: (template: NodeTemplate) => void }) {
  const categories = ['入口', '逻辑', '触达', '动作'];
  return (
    <div style={{
      width: 200, minWidth: 200, background: BG_1, borderRadius: 10,
      border: `1px solid ${BG_2}`, padding: '12px 0', overflowY: 'auto',
    }}>
      <div style={{ padding: '4px 16px 12px', fontSize: 13, fontWeight: 700, color: TEXT_3 }}>节点库</div>
      {categories.map(cat => (
        <div key={cat}>
          <div style={{
            padding: '8px 16px 4px', fontSize: 10, fontWeight: 700,
            color: TEXT_4, letterSpacing: 1,
          }}>{cat.toUpperCase()}</div>
          {NODE_TEMPLATES.filter(t => t.category === cat).map(tmpl => (
            <div
              key={tmpl.type}
              onClick={() => onAddNode(tmpl)}
              title={`添加"${tmpl.label}"节点`}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 16px',
                cursor: 'pointer', transition: 'background .15s',
                borderLeft: '3px solid transparent',
              }}
              onMouseEnter={e => {
                const el = e.currentTarget as HTMLDivElement;
                el.style.background = BG_2;
                el.style.borderLeftColor = tmpl.color;
              }}
              onMouseLeave={e => {
                const el = e.currentTarget as HTMLDivElement;
                el.style.background = 'transparent';
                el.style.borderLeftColor = 'transparent';
              }}
            >
              <span style={{
                width: 28, height: 28, borderRadius: 6, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                background: tmpl.color + '22', fontSize: 14,
              }}>{tmpl.icon}</span>
              <span style={{ fontSize: 13, color: TEXT_2 }}>{tmpl.label}</span>
            </div>
          ))}
        </div>
      ))}
      <div style={{ padding: '16px', borderTop: `1px solid ${BG_2}`, marginTop: 8 }}>
        <div style={{ fontSize: 10, color: TEXT_4, lineHeight: 1.6 }}>
          点击节点添加到画布末尾。画布内点击节点进行配置。
        </div>
      </div>
    </div>
  );
}

// ---- 单个画布节点卡片 ----

function CanvasNodeCard({
  node,
  isSelected,
  onClick,
  branchLabel,
}: {
  node: CanvasNode;
  isSelected: boolean;
  onClick: () => void;
  branchLabel?: string;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      {branchLabel && (
        <div style={{
          fontSize: 10, color: TEXT_4, marginBottom: 4,
          padding: '2px 10px', borderRadius: 4,
          background: BG_2, border: `1px solid ${BG_2}`,
        }}>{branchLabel}</div>
      )}
      <div
        onClick={onClick}
        style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 18px', borderRadius: 10,
          background: isSelected ? node.color + '22' : BG_1,
          border: `2px solid ${isSelected ? node.color : BG_2}`,
          cursor: 'pointer', transition: 'all .15s',
          minWidth: 180, boxShadow: isSelected ? `0 0 0 3px ${node.color}33` : 'none',
        }}
      >
        <span style={{
          width: 32, height: 32, borderRadius: 8, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          background: node.color + '22', fontSize: 16, flexShrink: 0,
        }}>{node.icon}</span>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 13, fontWeight: 600, color: TEXT_1,
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>{node.label}</div>
          <div style={{ fontSize: 10, color: TEXT_4, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {node.type === 'trigger' && (node.config.segment || node.config.triggerType || '触发器')}
            {node.type === 'wait' && `${node.config.waitDays ?? 0}天 ${node.config.waitHours ?? 0}小时`}
            {node.type === 'condition' && `${node.config.conditionField ?? ''} ${node.config.conditionOperator ?? ''} ${node.config.conditionValue ?? ''}`}
            {(node.type === 'wechat-work' || node.type === 'sms' || node.type === 'miniapp-msg' || node.type === 'action') && (node.config.templateName || node.config.content || '消息节点')}
            {node.type === 'benefit' && (node.config.benefitValue || node.config.benefitType || '权益')}
            {node.type === 'ab-test' && `A组 ${node.config.splitRatio ?? 50}% / B组 ${100 - (node.config.splitRatio ?? 50)}%`}
            {node.type === 'manual-task' && (node.config.taskDescription || '人工任务')}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- 画布区域 ----

function CanvasArea({
  nodes,
  selectedId,
  onSelectNode,
}: {
  nodes: CanvasNode[];
  selectedId: string | null;
  onSelectNode: (id: string) => void;
}) {
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const rendered = new Set<string>();

  const renderNode = (nodeId: string, branchLabel?: string): React.ReactNode => {
    if (rendered.has(nodeId)) return null;
    rendered.add(nodeId);
    const node = nodeMap.get(nodeId);
    if (!node) return null;

    const isBranch = node.type === 'condition' || node.type === 'ab-test';

    return (
      <div key={node.id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <CanvasNodeCard
          node={node}
          isSelected={selectedId === node.id}
          onClick={() => onSelectNode(node.id)}
          branchLabel={branchLabel}
        />
        {node.children.length > 0 && (
          <>
            <div style={{ width: 2, height: 24, background: BG_2 }} />
            <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>▼</div>
            {isBranch && node.children.length > 1 ? (
              <div style={{ display: 'flex', gap: 32, alignItems: 'flex-start' }}>
                {node.children.map((childId, i) => (
                  <div key={childId} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    {renderNode(
                      childId,
                      i === 0
                        ? (node.type === 'condition' ? '是' : 'A组')
                        : (node.type === 'condition' ? '否' : 'B组'),
                    )}
                  </div>
                ))}
              </div>
            ) : (
              node.children.map(childId => renderNode(childId))
            )}
          </>
        )}
      </div>
    );
  };

  const allChildIds = new Set(nodes.flatMap(n => n.children));
  const rootNodes = nodes.filter(n => !allChildIds.has(n.id));
  const root = rootNodes[0];

  return (
    <div style={{
      flex: 1, background: BG_0, borderRadius: 10,
      border: `1px solid ${BG_2}`, padding: 30,
      overflowY: 'auto', minHeight: 500,
      display: 'flex', flexDirection: 'column', alignItems: 'center',
    }}>
      <div style={{
        padding: '6px 18px', borderRadius: 20, background: GREEN + '22',
        color: GREEN, fontSize: 12, fontWeight: 700, marginBottom: 8,
      }}>开始</div>
      <div style={{ width: 2, height: 16, background: BG_2 }} />
      <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>▼</div>

      {root ? renderNode(root.id) : (
        <div style={{ color: TEXT_4, fontSize: 14, marginTop: 40 }}>
          从左侧节点库添加第一个节点
        </div>
      )}

      <div style={{ width: 2, height: 16, background: BG_2, marginTop: 8 }} />
      <div style={{
        padding: '6px 18px', borderRadius: 20, background: RED + '22',
        color: RED, fontSize: 12, fontWeight: 700, marginTop: 4,
      }}>结束</div>
    </div>
  );
}

// ---- 节点配置面板 ----

function ConfigPanel({
  node,
  onUpdate,
  onDelete,
}: {
  node: CanvasNode | null;
  onUpdate: (id: string, config: NodeConfig, label?: string) => void;
  onDelete: (id: string) => void;
}) {
  if (!node) {
    return (
      <div style={{
        width: 280, minWidth: 280, background: BG_1, borderRadius: 10,
        border: `1px solid ${BG_2}`, padding: 20,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ textAlign: 'center', color: TEXT_4 }}>
          <div style={{ fontSize: 28, marginBottom: 8 }}>👈</div>
          <div style={{ fontSize: 13 }}>点击画布中的节点进行配置</div>
        </div>
      </div>
    );
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_1, padding: '8px 12px', fontSize: 13, outline: 'none',
    boxSizing: 'border-box',
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11, color: TEXT_3, marginBottom: 4, display: 'block', fontWeight: 600,
  };
  const fieldGap: React.CSSProperties = { marginBottom: 14 };

  const handleConfigChange = (key: string, value: unknown) => {
    onUpdate(node.id, { ...node.config, [key]: value });
  };

  const tmpl = NODE_TEMPLATES.find(t => t.type === node.type);

  return (
    <div style={{
      width: 280, minWidth: 280, background: BG_1, borderRadius: 10,
      border: `1px solid ${BG_2}`, padding: 16, overflowY: 'auto',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{
          width: 28, height: 28, borderRadius: 6, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          background: node.color + '22', fontSize: 14,
        }}>{node.icon}</span>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: TEXT_1 }}>节点配置</div>
          <div style={{ fontSize: 11, color: TEXT_4 }}>{tmpl?.label ?? node.type}</div>
        </div>
      </div>

      {/* 节点名称 */}
      <div style={fieldGap}>
        <span style={labelStyle}>节点名称</span>
        <input
          value={node.label}
          onChange={e => onUpdate(node.id, node.config, e.target.value)}
          style={inputStyle}
          placeholder="节点名称"
        />
      </div>

      {/* 触发器 */}
      {node.type === 'trigger' && (
        <>
          <div style={fieldGap}>
            <span style={labelStyle}>触发条件</span>
            <select
              value={node.config.triggerType ?? '人群进入'}
              onChange={e => handleConfigChange('triggerType', e.target.value)}
              style={inputStyle}
            >
              <option>人群进入</option>
              <option>事件触发</option>
              <option>定时触发</option>
              <option>API触发</option>
            </select>
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>人群选择</span>
            <select
              value={node.config.segment ?? ''}
              onChange={e => handleConfigChange('segment', e.target.value)}
              style={inputStyle}
            >
              <option value="">请选择人群</option>
              <option>全部人群</option>
              <option>新客</option>
              <option>首单未复购</option>
              <option>沉睡客</option>
              <option>高频复购</option>
              <option>高价值</option>
              <option>流失风险</option>
              <option>社交活跃</option>
              <option>券敏感型</option>
              <option>周末客群</option>
              <option>家庭客群</option>
            </select>
          </div>
        </>
      )}

      {/* 条件判断 */}
      {node.type === 'condition' && (
        <>
          <div style={fieldGap}>
            <span style={labelStyle}>判断字段</span>
            <select
              value={node.config.conditionField ?? ''}
              onChange={e => handleConfigChange('conditionField', e.target.value)}
              style={inputStyle}
            >
              <option value="">请选择字段</option>
              <option>消费次数</option>
              <option>累计消费金额</option>
              <option>最后消费天数</option>
              <option>券使用状态</option>
              <option>消息已读状态</option>
              <option>会员等级</option>
            </select>
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>运算符</span>
            <select
              value={node.config.conditionOperator ?? '大于等于'}
              onChange={e => handleConfigChange('conditionOperator', e.target.value)}
              style={inputStyle}
            >
              <option>大于等于</option>
              <option>小于</option>
              <option>等于</option>
              <option>不等于</option>
              <option>包含</option>
            </select>
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>比较值</span>
            <input
              value={node.config.conditionValue ?? ''}
              onChange={e => handleConfigChange('conditionValue', e.target.value)}
              style={inputStyle}
              placeholder="输入比较值"
            />
          </div>
        </>
      )}

      {/* 消息类节点：企业微信/短信/小程序/action */}
      {(node.type === 'wechat-work' || node.type === 'sms' || node.type === 'miniapp-msg' || node.type === 'action') && (
        <>
          <div style={fieldGap}>
            <span style={labelStyle}>内容模板</span>
            <select
              value={node.config.templateName ?? ''}
              onChange={e => handleConfigChange('templateName', e.target.value)}
              style={inputStyle}
            >
              <option value="">请选择模板</option>
              <option>复购感谢</option>
              <option>回归提醒</option>
              <option>新品推荐</option>
              <option>生日祝福</option>
              <option>活动邀请</option>
              <option>会员权益通知</option>
            </select>
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>消息内容</span>
            <textarea
              value={node.config.content ?? ''}
              onChange={e => handleConfigChange('content', e.target.value)}
              style={{ ...inputStyle, minHeight: 80, resize: 'vertical' }}
              placeholder="输入消息内容..."
            />
          </div>
        </>
      )}

      {/* 权益发放 */}
      {node.type === 'benefit' && (
        <>
          <div style={fieldGap}>
            <span style={labelStyle}>权益类型</span>
            <select
              value={node.config.benefitType ?? ''}
              onChange={e => handleConfigChange('benefitType', e.target.value)}
              style={inputStyle}
            >
              <option value="">请选择类型</option>
              <option>优惠券</option>
              <option>积分</option>
              <option>会员等级升级</option>
              <option>免费菜品</option>
              <option>抵扣券</option>
            </select>
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>权益内容</span>
            <input
              value={node.config.benefitValue ?? ''}
              onChange={e => handleConfigChange('benefitValue', e.target.value)}
              style={inputStyle}
              placeholder="如: 满80减15回归券"
            />
          </div>
        </>
      )}

      {/* 等待节点 */}
      {node.type === 'wait' && (
        <div style={{ display: 'flex', gap: 10, ...fieldGap }}>
          <div style={{ flex: 1 }}>
            <span style={labelStyle}>等待天数</span>
            <input
              type="number"
              min={0}
              value={node.config.waitDays ?? 0}
              onChange={e => handleConfigChange('waitDays', parseInt(e.target.value) || 0)}
              style={inputStyle}
            />
          </div>
          <div style={{ flex: 1 }}>
            <span style={labelStyle}>等待小时</span>
            <input
              type="number"
              min={0}
              max={23}
              value={node.config.waitHours ?? 0}
              onChange={e => handleConfigChange('waitHours', parseInt(e.target.value) || 0)}
              style={inputStyle}
            />
          </div>
        </div>
      )}

      {/* AB实验 */}
      {node.type === 'ab-test' && (
        <div style={fieldGap}>
          <span style={labelStyle}>A组流量占比 (%)</span>
          <input
            type="number"
            min={1}
            max={99}
            value={node.config.splitRatio ?? 50}
            onChange={e => handleConfigChange('splitRatio', parseInt(e.target.value) || 50)}
            style={inputStyle}
          />
          <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>
            B组占比: {100 - (typeof node.config.splitRatio === 'number' ? node.config.splitRatio : 50)}%
          </div>
        </div>
      )}

      {/* 人工任务 */}
      {node.type === 'manual-task' && (
        <>
          <div style={fieldGap}>
            <span style={labelStyle}>任务描述</span>
            <textarea
              value={node.config.taskDescription ?? ''}
              onChange={e => handleConfigChange('taskDescription', e.target.value)}
              style={{ ...inputStyle, minHeight: 60, resize: 'vertical' }}
              placeholder="描述人工任务内容..."
            />
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>指派人</span>
            <select
              value={node.config.assignee ?? ''}
              onChange={e => handleConfigChange('assignee', e.target.value)}
              style={inputStyle}
            >
              <option value="">请选择</option>
              <option>运营小王</option>
              <option>运营小李</option>
              <option>运营小张</option>
              <option>店长</option>
            </select>
          </div>
        </>
      )}

      {/* 删除 */}
      <div style={{ marginTop: 20, borderTop: `1px solid ${BG_2}`, paddingTop: 16 }}>
        <button
          onClick={() => onDelete(node.id)}
          style={{
            width: '100%', padding: '8px', borderRadius: 6,
            border: `1px solid ${RED}33`, background: RED + '11',
            color: RED, fontSize: 12, fontWeight: 600, cursor: 'pointer',
          }}
        >删除此节点</button>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function JourneyCanvasPage() {
  const navigate = useNavigate();
  const { journeyId } = useParams<{ journeyId: string }>();

  const [journey, setJourney] = useState<JourneySummary | null>(null);
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [edges, setEdges] = useState<CanvasEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [canvasLoading, setCanvasLoading] = useState(true);
  const [saveLoading, setSaveLoading] = useState(false);
  const [publishLoading, setPublishLoading] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [error, setError] = useState<string | null>(null);

  const selectedNode = nodes.find(n => n.id === selectedNodeId) ?? null;

  // 加载画布数据
  const loadCanvas = useCallback(async () => {
    if (!journeyId) return;
    setCanvasLoading(true);
    setError(null);
    try {
      const data = await txFetch<{ journey: JourneySummary; canvas: CanvasData }>(
        `/api/v1/member/journeys/${journeyId}/canvas`
      );
      if (data.journey) setJourney(data.journey);
      if (data.canvas && data.canvas.nodes && data.canvas.nodes.length > 0) {
        // 从API数据中恢复颜色/图标（如果缺少则从模板补充）
        const restoredNodes = data.canvas.nodes.map(n => {
          const tmpl = NODE_TEMPLATES.find(t => t.type === n.type);
          return {
            ...n,
            icon: n.icon || tmpl?.icon || '●',
            color: n.color || NODE_COLOR_MAP[n.type] || tmpl?.color || BLUE,
          };
        });
        setNodes(restoredNodes);
        setEdges(data.canvas.edges ?? buildEdgesFromNodes(restoredNodes));
      } else {
        // canvas为空 → 空画布，引导用户添加节点
        setNodes([]);
        setEdges([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载画布数据失败');
      setNodes([]);
      setEdges([]);
    } finally {
      setCanvasLoading(false);
    }
  }, [journeyId]);

  useEffect(() => {
    loadCanvas();
  }, [loadCanvas]);

  // 添加节点
  const handleAddNode = useCallback((template: NodeTemplate) => {
    const newId = `node-${Date.now()}`;
    const newNode: CanvasNode = {
      id: newId,
      type: template.type,
      label: template.label,
      icon: template.icon,
      color: template.color,
      config: {},
      children: [],
    };

    setNodes(prev => {
      const updated = [...prev];
      const leaves = updated.filter(n => n.children.length === 0);
      if (leaves.length > 0) {
        const lastLeaf = leaves[leaves.length - 1];
        const idx = updated.findIndex(n => n.id === lastLeaf.id);
        updated[idx] = { ...lastLeaf, children: [newId] };
      }
      const newNodes = [...updated, newNode];
      setEdges(buildEdgesFromNodes(newNodes));
      return newNodes;
    });
    setSelectedNodeId(newId);
  }, []);

  // 更新节点配置
  const handleUpdateNode = useCallback((id: string, config: NodeConfig, label?: string) => {
    setNodes(prev => prev.map(n =>
      n.id === id ? { ...n, config, ...(label !== undefined ? { label } : {}) } : n
    ));
  }, []);

  // 删除节点
  const handleDeleteNode = useCallback((id: string) => {
    setNodes(prev => {
      const node = prev.find(n => n.id === id);
      if (!node) return prev;
      const updated = prev
        .filter(n => n.id !== id)
        .map(n => {
          if (n.children.includes(id)) {
            return { ...n, children: [...n.children.filter(c => c !== id), ...node.children] };
          }
          return n;
        });
      setEdges(buildEdgesFromNodes(updated));
      return updated;
    });
    setSelectedNodeId(null);
  }, []);

  // 添加触发器（空画布引导）
  const handleAddTriggerNode = useCallback(() => {
    const triggerTemplate = NODE_TEMPLATES.find(t => t.type === 'trigger');
    if (triggerTemplate) handleAddNode(triggerTemplate);
  }, [handleAddNode]);

  // 保存草稿
  const handleSave = async () => {
    if (!journeyId || saveLoading) return;
    setSaveLoading(true);
    setError(null);
    try {
      await txFetch(`/api/v1/member/journeys/${journeyId}/canvas`, {
        method: 'PUT',
        body: JSON.stringify({ nodes, edges }),
      });
      setSaveMessage('草稿已保存 ✓');
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaveLoading(false);
      setTimeout(() => setSaveMessage(''), 3000);
    }
  };

  // 发布旅程
  const handlePublish = async () => {
    if (!journeyId || publishLoading) return;
    if (nodes.length === 0) {
      setSaveMessage('请先添加节点后再发布');
      setTimeout(() => setSaveMessage(''), 3000);
      return;
    }
    setPublishLoading(true);
    try {
      // 先保存画布
      await txFetch(`/api/v1/member/journeys/${journeyId}/canvas`, {
        method: 'PUT',
        body: JSON.stringify({ nodes, edges }),
      });
      // 再更新状态为激活
      await txFetch(`/api/v1/member/journeys/${journeyId}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'active' }),
      });
      setJourney(prev => prev ? { ...prev, status: 'active' } : prev);
      setSaveMessage('旅程已发布 ✓');
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : '发布失败');
    } finally {
      setPublishLoading(false);
      setTimeout(() => setSaveMessage(''), 3000);
    }
  };

  const statusColorMap: Record<JourneyStatus, string> = {
    draft: TEXT_4,
    active: GREEN,
    paused: YELLOW,
    ended: BLUE,
  };
  const statusLabelMap: Record<JourneyStatus, string> = {
    draft: '草稿',
    active: '运行中',
    paused: '已暂停',
    ended: '已结束',
  };

  const currentStatus = journey?.status ?? 'draft';
  const statusColor = statusColorMap[currentStatus] ?? TEXT_4;
  const statusLabel = statusLabelMap[currentStatus] ?? currentStatus;

  const isMsgError = saveMessage.includes('失败') || saveMessage.includes('Error');

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: 'calc(100vh - 80px)', maxWidth: 1600, margin: '0 auto',
      background: BG_0,
    }}>
      {/* 顶部栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 0', marginBottom: 8, flexWrap: 'wrap', gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => navigate(`/hq/growth/journeys/${journeyId}`)}
            style={{
              padding: '6px 12px', borderRadius: 6, border: `1px solid ${BG_2}`,
              background: BG_1, color: TEXT_2, fontSize: 13, cursor: 'pointer',
            }}
          >← 返回详情</button>
          <span style={{ fontSize: 18, fontWeight: 700, color: TEXT_1 }}>
            {canvasLoading ? '加载中...' : (journey?.name ?? '旅程画布')}
          </span>
          <span style={{
            fontSize: 10, padding: '2px 8px', borderRadius: 10, fontWeight: 600,
            background: statusColor + '22', color: statusColor,
          }}>{statusLabel}</span>
          {saveMessage && (
            <span style={{
              fontSize: 12, color: isMsgError ? RED : GREEN,
              padding: '3px 10px', borderRadius: 6, background: BG_1,
            }}>{saveMessage}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: TEXT_4 }}>节点: {nodes.length}</span>
          <button
            onClick={handleSave}
            disabled={saveLoading || canvasLoading}
            style={{
              padding: '6px 16px', borderRadius: 6, border: `1px solid ${BG_2}`,
              background: BG_1, color: saveLoading ? TEXT_4 : TEXT_2,
              fontSize: 13, fontWeight: 600,
              cursor: saveLoading ? 'wait' : 'pointer',
              opacity: canvasLoading ? 0.5 : 1,
            }}
          >{saveLoading ? '保存中...' : '保存草稿'}</button>
          <button
            onClick={handlePublish}
            disabled={publishLoading || canvasLoading}
            style={{
              padding: '6px 16px', borderRadius: 6, border: 'none',
              background: publishLoading ? BRAND + '88' : BRAND,
              color: '#fff', fontSize: 13, fontWeight: 700,
              cursor: publishLoading ? 'wait' : 'pointer',
              opacity: canvasLoading ? 0.5 : 1,
            }}
          >{publishLoading ? '发布中...' : '发布'}</button>
        </div>
      </div>

      {/* 错误横幅 */}
      {error && (
        <div style={{
          background: RED + '11', border: `1px solid ${RED}33`,
          borderRadius: 8, padding: '10px 16px', marginBottom: 8,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <span style={{ color: RED }}>⚠</span>
          <span style={{ color: RED, flex: 1, fontSize: 13 }}>{error}</span>
          <button
            onClick={loadCanvas}
            style={{
              padding: '4px 12px', borderRadius: 6, border: `1px solid ${RED}44`,
              background: 'transparent', color: RED, fontSize: 12, cursor: 'pointer',
            }}
          >重试</button>
        </div>
      )}

      {/* 主区域：三栏 */}
      {canvasLoading ? (
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: TEXT_4, fontSize: 14, gap: 12,
        }}>
          <div style={{
            width: 20, height: 20, borderRadius: '50%',
            border: `2px solid ${BG_2}`, borderTopColor: BRAND,
            animation: 'spin 1s linear infinite',
          }} />
          正在加载画布数据...
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <NodeLibrarySidebar onAddNode={handleAddNode} />
          {nodes.length === 0 ? (
            <EmptyCanvasGuide onAddTrigger={handleAddTriggerNode} />
          ) : (
            <CanvasArea
              nodes={nodes}
              selectedId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
            />
          )}
          <ConfigPanel
            node={selectedNode}
            onUpdate={handleUpdateNode}
            onDelete={handleDeleteNode}
          />
        </div>
      )}

      {/* 底部状态栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px', marginTop: 8,
        background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
        flexWrap: 'wrap', gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, fontSize: 13 }}>
          <span style={{ color: TEXT_3 }}>
            预计人群: <strong style={{ color: TEXT_1 }}>{(journey?.target_count ?? 0).toLocaleString()}</strong> 人
          </span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span style={{ color: TEXT_3 }}>
            已执行: <strong style={{ color: BRAND }}>{(journey?.executed_count ?? 0).toLocaleString()}</strong> 人
          </span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span style={{ color: TEXT_3 }}>
            转化率: <strong style={{ color: (journey?.conversion_rate ?? 0) >= 15 ? GREEN : YELLOW }}>
              {(journey?.conversion_rate ?? 0).toFixed(1)}%
            </strong>
          </span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span style={{ color: TEXT_3 }}>
            节点数: <strong style={{ color: TEXT_1 }}>{nodes.length}</strong>
          </span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span style={{ color: TEXT_3 }}>
            连线数: <strong style={{ color: TEXT_1 }}>{edges.length}</strong>
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: TEXT_4 }}>版本历史:</span>
          {journey?.versions && journey.versions.length > 0 ? (
            journey.versions.slice(0, 3).map(v => (
              <span key={v.version} style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: BG_2, color: TEXT_3,
              }}>v{v.version} ({v.date})</span>
            ))
          ) : (
            <span style={{ fontSize: 11, color: TEXT_4 }}>暂无历史版本</span>
          )}
        </div>
      </div>

      {/* 内联样式动画 */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
      `}</style>
    </div>
  );
}
