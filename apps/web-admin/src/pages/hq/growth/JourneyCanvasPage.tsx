/**
 * JourneyCanvasPage — 客户旅程画布编辑器
 * 左侧节点库 + 中间画布 + 右侧配置面板
 */
import { useState, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

// ---- 颜色常量 ----
const BG_0 = '#0B1A20';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
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
  | 'wechat-work'
  | 'sms'
  | 'miniapp-msg'
  | 'benefit'
  | 'wait'
  | 'ab-test'
  | 'manual-task';

type JourneyStatus = '草稿' | '运行中' | '已暂停' | '已结束';

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
  children: string[]; // ids of next nodes
}

interface NodeConfig {
  // 触发器
  triggerType?: string;
  segment?: string;
  // 条件判断
  conditionField?: string;
  conditionOperator?: string;
  conditionValue?: string;
  // 企业微信/短信/小程序消息
  templateName?: string;
  content?: string;
  // 权益发放
  benefitType?: string;
  benefitValue?: string;
  // 等待
  waitDays?: number;
  waitHours?: number;
  // AB实验
  splitRatio?: number;
  // 人工任务
  taskDescription?: string;
  assignee?: string;
  [key: string]: unknown;
}

interface JourneyMeta {
  id: string;
  name: string;
  status: JourneyStatus;
  targetCount: number;
  executedCount: number;
  conversionRate: number;
  versions: { version: number; date: string; author: string }[];
}

// ---- 节点模板库 ----

const NODE_TEMPLATES: NodeTemplate[] = [
  { type: 'trigger', label: '触发器', icon: '\u26A1', color: BRAND, category: '入口' },
  { type: 'condition', label: '条件判断', icon: '\uD83D\uDD00', color: YELLOW, category: '逻辑' },
  { type: 'wechat-work', label: '企业微信', icon: '\uD83D\uDCAC', color: GREEN, category: '触达' },
  { type: 'sms', label: '短信', icon: '\uD83D\uDCE7', color: BLUE, category: '触达' },
  { type: 'miniapp-msg', label: '小程序消息', icon: '\uD83D\uDCF1', color: CYAN, category: '触达' },
  { type: 'benefit', label: '权益发放', icon: '\uD83C\uDF81', color: PURPLE, category: '动作' },
  { type: 'wait', label: '等待', icon: '\u23F3', color: TEXT_3, category: '逻辑' },
  { type: 'ab-test', label: 'AB实验', icon: '\uD83E\uDDEA', color: BRAND, category: '逻辑' },
  { type: 'manual-task', label: '人工任务', icon: '\uD83D\uDC64', color: YELLOW, category: '动作' },
];

// ---- Mock 旅程数据 ----

const MOCK_JOURNEY_META: Record<string, JourneyMeta> = {
  j1: {
    id: 'j1', name: '新客首单转复购旅程', status: '运行中',
    targetCount: 4231, executedCount: 3876, conversionRate: 18.4,
    versions: [
      { version: 3, date: '2026-03-25', author: '运营小王' },
      { version: 2, date: '2026-03-18', author: '运营小王' },
      { version: 1, date: '2026-03-10', author: '运营小李' },
    ],
  },
  j2: {
    id: 'j2', name: '沉睡客唤醒旅程', status: '运行中',
    targetCount: 8945, executedCount: 6234, conversionRate: 12.7,
    versions: [
      { version: 2, date: '2026-03-24', author: '运营小李' },
      { version: 1, date: '2026-03-05', author: '运营小李' },
    ],
  },
  new: {
    id: 'new', name: '未命名旅程', status: '草稿',
    targetCount: 0, executedCount: 0, conversionRate: 0,
    versions: [],
  },
};

const createDefaultNodes = (): CanvasNode[] => [
  {
    id: 'node-1', type: 'trigger', label: '进入旅程', icon: '\u26A1', color: BRAND,
    config: { triggerType: '人群进入', segment: '首单未复购' },
    children: ['node-2'],
  },
  {
    id: 'node-2', type: 'wait', label: '等待3天', icon: '\u23F3', color: TEXT_3,
    config: { waitDays: 3, waitHours: 0 },
    children: ['node-3'],
  },
  {
    id: 'node-3', type: 'condition', label: '是否已复购', icon: '\uD83D\uDD00', color: YELLOW,
    config: { conditionField: '消费次数', conditionOperator: '大于等于', conditionValue: '2' },
    children: ['node-4', 'node-5'],
  },
  {
    id: 'node-4', type: 'wechat-work', label: '发送关怀消息', icon: '\uD83D\uDCAC', color: GREEN,
    config: { templateName: '复购感谢', content: '感谢您再次光临！专属会员积分已到账~' },
    children: [],
  },
  {
    id: 'node-5', type: 'benefit', label: '发放回归券', icon: '\uD83C\uDF81', color: PURPLE,
    config: { benefitType: '优惠券', benefitValue: '满80减15回归券' },
    children: ['node-6'],
  },
  {
    id: 'node-6', type: 'wait', label: '等待7天', icon: '\u23F3', color: TEXT_3,
    config: { waitDays: 7, waitHours: 0 },
    children: ['node-7'],
  },
  {
    id: 'node-7', type: 'sms', label: '短信提醒', icon: '\uD83D\uDCE7', color: BLUE,
    config: { templateName: '回归提醒', content: '您有一张回归券即将到期，快来享用吧！' },
    children: [],
  },
];

// ---- 组件 ----

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
          <div style={{ padding: '8px 16px 4px', fontSize: 10, fontWeight: 700, color: TEXT_4, textTransform: 'uppercase' }}>
            {cat}
          </div>
          {NODE_TEMPLATES.filter(t => t.category === cat).map(tmpl => (
            <div
              key={tmpl.type}
              onClick={() => onAddNode(tmpl)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 16px',
                cursor: 'pointer', transition: 'background .15s',
                borderLeft: `3px solid transparent`,
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLDivElement).style.background = BG_2;
                (e.currentTarget as HTMLDivElement).style.borderLeftColor = tmpl.color;
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLDivElement).style.background = 'transparent';
                (e.currentTarget as HTMLDivElement).style.borderLeftColor = 'transparent';
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
        <div style={{ fontSize: 10, color: TEXT_4, lineHeight: 1.5 }}>
          点击节点添加到画布末尾。在画布中点击节点进行配置。
        </div>
      </div>
    </div>
  );
}

function CanvasNodeCard({ node, isSelected, onClick, branchLabel }: {
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
          padding: '1px 8px', borderRadius: 4, background: BG_2,
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
          minWidth: 180,
        }}
      >
        <span style={{
          width: 32, height: 32, borderRadius: 8, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          background: node.color + '22', fontSize: 16,
        }}>{node.icon}</span>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{node.label}</div>
          <div style={{ fontSize: 10, color: TEXT_4, marginTop: 2 }}>
            {node.type === 'trigger' && node.config.segment}
            {node.type === 'wait' && `${node.config.waitDays || 0}天${node.config.waitHours || 0}小时`}
            {node.type === 'condition' && `${node.config.conditionField} ${node.config.conditionOperator} ${node.config.conditionValue}`}
            {(node.type === 'wechat-work' || node.type === 'sms' || node.type === 'miniapp-msg') && node.config.templateName}
            {node.type === 'benefit' && node.config.benefitValue}
            {node.type === 'ab-test' && `${node.config.splitRatio || 50}/${100 - (node.config.splitRatio || 50)}`}
            {node.type === 'manual-task' && node.config.taskDescription}
          </div>
        </div>
      </div>
    </div>
  );
}

function CanvasArea({ nodes, selectedId, onSelectNode }: {
  nodes: CanvasNode[];
  selectedId: string | null;
  onSelectNode: (id: string) => void;
}) {
  // Build a simple linear + branch visualization
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const rendered = new Set<string>();

  const renderNode = (nodeId: string, depth: number = 0, branchLabel?: string): React.ReactNode => {
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
            {/* 连接线 */}
            <div style={{ width: 2, height: 24, background: BG_2 }} />
            <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 2 }}>\u25BC</div>

            {isBranch && node.children.length > 1 ? (
              // 分支显示
              <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
                {node.children.map((childId, i) => (
                  <div key={childId} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    {renderNode(childId, depth + 1, i === 0 ? (node.type === 'condition' ? '是' : 'A组') : (node.type === 'condition' ? '否' : 'B组'))}
                  </div>
                ))}
              </div>
            ) : (
              // 线性
              node.children.map(childId => renderNode(childId, depth + 1))
            )}
          </>
        )}
      </div>
    );
  };

  // Find root: node not referenced as child by any other
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
      {/* 开始标记 */}
      <div style={{
        padding: '6px 18px', borderRadius: 20, background: GREEN + '22',
        color: GREEN, fontSize: 12, fontWeight: 700, marginBottom: 8,
      }}>开始</div>
      <div style={{ width: 2, height: 16, background: BG_2 }} />
      <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>\u25BC</div>

      {root ? renderNode(root.id) : (
        <div style={{ color: TEXT_4, fontSize: 14, marginTop: 40 }}>
          从左侧节点库添加第一个节点
        </div>
      )}

      {/* 结束标记 */}
      <div style={{ width: 2, height: 16, background: BG_2, marginTop: 8 }} />
      <div style={{
        padding: '6px 18px', borderRadius: 20, background: RED + '22',
        color: RED, fontSize: 12, fontWeight: 700, marginTop: 4,
      }}>结束</div>
    </div>
  );
}

function ConfigPanel({ node, onUpdate, onDelete }: {
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
          <div style={{ fontSize: 28, marginBottom: 8 }}>\uD83D\uDC48</div>
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
          <div style={{ fontSize: 11, color: TEXT_4 }}>{NODE_TEMPLATES.find(t => t.type === node.type)?.label}</div>
        </div>
      </div>

      {/* 通用: 节点名称 */}
      <div style={fieldGap}>
        <span style={labelStyle}>节点名称</span>
        <input
          value={node.label}
          onChange={e => onUpdate(node.id, node.config, e.target.value)}
          style={inputStyle}
        />
      </div>

      {/* 触发器配置 */}
      {node.type === 'trigger' && (
        <>
          <div style={fieldGap}>
            <span style={labelStyle}>触发条件</span>
            <select
              value={node.config.triggerType || '人群进入'}
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
              value={node.config.segment || ''}
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
              value={node.config.conditionField || ''}
              onChange={e => handleConfigChange('conditionField', e.target.value)}
              style={inputStyle}
            >
              <option value="">请选择字段</option>
              <option>消费次数</option>
              <option>累计消费金额</option>
              <option>最后消费天数</option>
              <option>券使用状态</option>
              <option>消息已读状态</option>
            </select>
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>运算符</span>
            <select
              value={node.config.conditionOperator || ''}
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
              value={node.config.conditionValue || ''}
              onChange={e => handleConfigChange('conditionValue', e.target.value)}
              style={inputStyle}
              placeholder="输入比较值"
            />
          </div>
        </>
      )}

      {/* 企业微信/短信/小程序 */}
      {(node.type === 'wechat-work' || node.type === 'sms' || node.type === 'miniapp-msg') && (
        <>
          <div style={fieldGap}>
            <span style={labelStyle}>内容模板</span>
            <select
              value={node.config.templateName || ''}
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
              value={node.config.content || ''}
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
              value={node.config.benefitType || ''}
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
              value={node.config.benefitValue || ''}
              onChange={e => handleConfigChange('benefitValue', e.target.value)}
              style={inputStyle}
              placeholder="如: 满80减15回归券"
            />
          </div>
        </>
      )}

      {/* 等待 */}
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
              value={node.config.taskDescription || ''}
              onChange={e => handleConfigChange('taskDescription', e.target.value)}
              style={{ ...inputStyle, minHeight: 60, resize: 'vertical' }}
              placeholder="描述人工任务内容..."
            />
          </div>
          <div style={fieldGap}>
            <span style={labelStyle}>指派人</span>
            <select
              value={node.config.assignee || ''}
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

      {/* 删除按钮 */}
      <div style={{ marginTop: 20, borderTop: `1px solid ${BG_2}`, paddingTop: 16 }}>
        <button
          onClick={() => onDelete(node.id)}
          style={{
            width: '100%', padding: '8px', borderRadius: 6, border: `1px solid ${RED}33`,
            background: RED + '11', color: RED, fontSize: 12, fontWeight: 600,
            cursor: 'pointer',
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
  const meta = MOCK_JOURNEY_META[journeyId || 'new'] || MOCK_JOURNEY_META['new'];

  const [journeyName, setJourneyName] = useState(meta.name);
  const [status, setStatus] = useState<JourneyStatus>(meta.status);
  const [nodes, setNodes] = useState<CanvasNode[]>(createDefaultNodes);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState('');

  const selectedNode = nodes.find(n => n.id === selectedNodeId) || null;

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
      // Find the last leaf node (no children) and attach new node to it
      const updated = [...prev];
      const leaves = updated.filter(n => n.children.length === 0);
      if (leaves.length > 0) {
        const lastLeaf = leaves[leaves.length - 1];
        const idx = updated.findIndex(n => n.id === lastLeaf.id);
        updated[idx] = { ...lastLeaf, children: [newId] };
      }
      return [...updated, newNode];
    });
    setSelectedNodeId(newId);
  }, []);

  const handleUpdateNode = useCallback((id: string, config: NodeConfig, label?: string) => {
    setNodes(prev => prev.map(n =>
      n.id === id ? { ...n, config, ...(label !== undefined ? { label } : {}) } : n
    ));
  }, []);

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
      return updated;
    });
    setSelectedNodeId(null);
  }, []);

  const handleSave = () => {
    setSaveMessage('草稿已保存');
    setTimeout(() => setSaveMessage(''), 2000);
  };

  const handlePublish = () => {
    setStatus('运行中');
    setSaveMessage('旅程已发布');
    setTimeout(() => setSaveMessage(''), 2000);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 80px)', maxWidth: 1600, margin: '0 auto' }}>
      {/* 顶部栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 0', marginBottom: 8, flexWrap: 'wrap', gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => navigate('/hq/growth/journeys')}
            style={{
              padding: '6px 12px', borderRadius: 6, border: `1px solid ${BG_2}`,
              background: BG_1, color: TEXT_2, fontSize: 13, cursor: 'pointer',
            }}
          >\u2190 返回</button>
          <input
            value={journeyName}
            onChange={e => setJourneyName(e.target.value)}
            style={{
              background: 'transparent', border: 'none', color: TEXT_1,
              fontSize: 18, fontWeight: 700, outline: 'none', width: 280,
            }}
          />
          <span style={{
            fontSize: 10, padding: '2px 8px', borderRadius: 10, fontWeight: 600,
            background: (status === '运行中' ? GREEN : status === '草稿' ? TEXT_4 : status === '已暂停' ? YELLOW : BLUE) + '22',
            color: status === '运行中' ? GREEN : status === '草稿' ? TEXT_4 : status === '已暂停' ? YELLOW : BLUE,
          }}>{status}</span>
          {saveMessage && (
            <span style={{ fontSize: 12, color: GREEN, fontWeight: 500 }}>{saveMessage}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button onClick={handleSave} style={{
            padding: '6px 16px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: BG_1, color: TEXT_2, fontSize: 13, fontWeight: 600, cursor: 'pointer',
          }}>保存草稿</button>
          <button onClick={handlePublish} style={{
            padding: '6px 16px', borderRadius: 6, border: 'none',
            background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer',
          }}>发布</button>
        </div>
      </div>

      {/* 主区域: 三栏 */}
      <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <NodeLibrarySidebar onAddNode={handleAddNode} />
        <CanvasArea nodes={nodes} selectedId={selectedNodeId} onSelectNode={setSelectedNodeId} />
        <ConfigPanel node={selectedNode} onUpdate={handleUpdateNode} onDelete={handleDeleteNode} />
      </div>

      {/* 底部统计栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px', marginTop: 8,
        background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
        flexWrap: 'wrap', gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, fontSize: 13 }}>
          <span style={{ color: TEXT_3 }}>
            预计人群: <strong style={{ color: TEXT_1 }}>{meta.targetCount.toLocaleString()}</strong> 人
          </span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span style={{ color: TEXT_3 }}>
            已执行: <strong style={{ color: BRAND }}>{meta.executedCount.toLocaleString()}</strong> 人
          </span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span style={{ color: TEXT_3 }}>
            转化率: <strong style={{ color: meta.conversionRate >= 15 ? GREEN : YELLOW }}>{meta.conversionRate}%</strong>
          </span>
          <span style={{ color: TEXT_4 }}>|</span>
          <span style={{ color: TEXT_3 }}>
            节点数: <strong style={{ color: TEXT_1 }}>{nodes.length}</strong>
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: TEXT_4 }}>版本记录:</span>
          {meta.versions.length > 0 ? (
            meta.versions.slice(0, 3).map(v => (
              <span key={v.version} style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: BG_2, color: TEXT_3,
              }}>v{v.version} ({v.date})</span>
            ))
          ) : (
            <span style={{ fontSize: 11, color: TEXT_4 }}>暂无版本</span>
          )}
        </div>
      </div>
    </div>
  );
}
