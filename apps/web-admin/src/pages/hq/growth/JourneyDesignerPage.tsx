/**
 * JourneyDesignerPage — 客户旅程编排
 * 路由: /hq/growth/journey-designer
 * 可视化设计自动化营销旅程：触发 → 等待 → 条件分支 → 动作 → 结束
 * 数据来源: GET/POST /api/v1/growth/journeys
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { txFetchData } from '../../../api/client';
import type { Journey, JourneyNode, JourneyStatus, NodeType } from '../../../api/couponBenefitApi';

// ---- 颜色常量 ----
const PRIMARY = '#FF6B35';
const SUCCESS = '#0F6E56';
const WARNING = '#BA7517';
const ERROR = '#A32D2D';
const INFO = '#185FA5';
const BG_PAGE = '#0d1b21';
const BG_CARD = '#112228';
const BG_INPUT = '#1a2a33';
const BORDER = '#1e3040';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

const STATUS_CFG: Record<JourneyStatus, { label: string; color: string }> = {
  draft: { label: '草稿', color: TEXT_4 },
  running: { label: '运行中', color: SUCCESS },
  paused: { label: '已暂停', color: WARNING },
  ended: { label: '已结束', color: ERROR },
};

const NODE_CFG: Record<NodeType, { label: string; color: string; icon: string }> = {
  trigger: { label: '触发', color: PRIMARY, icon: '⚡' },
  wait: { label: '等待', color: INFO, icon: '⏳' },
  condition: { label: '条件', color: WARNING, icon: '🔀' },
  action: { label: '动作', color: SUCCESS, icon: '🎯' },
  end: { label: '结束', color: TEXT_4, icon: '🏁' },
};

// 触发器选项
const TRIGGER_OPTIONS = [
  { key: 'new_member', label: '新会员注册' },
  { key: 'spend_over', label: '消费满N元' },
  { key: 'inactive_days', label: 'N天未消费' },
  { key: 'birthday', label: '生日' },
];

// 动作选项
const ACTION_OPTIONS = [
  { key: 'send_coupon', label: '发券' },
  { key: 'send_points', label: '发积分' },
  { key: 'push_message', label: '推送消息' },
  { key: 'add_tag', label: '加标签' },
];

// ---- 工具函数 ----
function formatDate(d: string): string {
  return new Date(d).toLocaleDateString('zh-CN');
}

function formatDateTime(d: string): string {
  const dt = new Date(d);
  return `${dt.toLocaleDateString('zh-CN')} ${dt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
}

// ---- 骨架屏 ----
function Skeleton({ w = '100%', h = 24 }: { w?: string | number; h?: number }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: 6,
      background: `linear-gradient(90deg, ${BG_INPUT} 25%, ${BORDER} 50%, ${BG_INPUT} 75%)`,
      backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite',
    }} />
  );
}

// ---- 错误提示 ----
function ErrorBanner({ msg, onRetry }: { msg: string; onRetry?: () => void }) {
  return (
    <div style={{
      padding: '12px 16px', borderRadius: 8, marginBottom: 12,
      background: ERROR + '18', borderLeft: `3px solid ${ERROR}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <span style={{ fontSize: 13, color: ERROR }}>{msg}</span>
      {onRetry && (
        <button onClick={onRetry} style={{
          padding: '4px 12px', borderRadius: 6, border: `1px solid ${ERROR}`,
          background: 'transparent', color: ERROR, fontSize: 12, cursor: 'pointer',
        }}>重试</button>
      )}
    </div>
  );
}

// ---- 按钮 ----
function Btn({ children, onClick, primary, small, danger, disabled, style: s }:
  { children: React.ReactNode; onClick?: () => void; primary?: boolean; small?: boolean; danger?: boolean; disabled?: boolean; style?: React.CSSProperties }) {
  const bg = danger ? ERROR : primary ? PRIMARY : 'transparent';
  const border = primary || danger ? 'none' : `1px solid ${BORDER}`;
  return (
    <button disabled={disabled} onClick={onClick} style={{
      padding: small ? '4px 12px' : '8px 20px',
      borderRadius: 6, border, background: bg,
      color: primary || danger ? '#fff' : TEXT_2,
      fontSize: small ? 12 : 13, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.5 : 1, ...s,
    }}>{children}</button>
  );
}

// ============================================================
// 旅程列表视图
// ============================================================

function JourneyListView({ onEdit, onCreate }: { onEdit: (j: Journey) => void; onCreate: () => void }) {
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await txFetchData<{ items: Journey[]; total: number }>('/api/v1/growth/journeys?page=1&size=50');
      setJourneys(res.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleStatusChange = async (j: Journey, status: JourneyStatus) => {
    try {
      await txFetchData<Journey>(`/api/v1/growth/journeys/${j.id}/status`, {
        method: 'PATCH', body: JSON.stringify({ status }),
      });
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '操作失败');
    }
  };

  if (error) return <ErrorBanner msg={error} onRetry={load} />;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>
          共 {loading ? '...' : journeys.length} 条旅程
        </div>
        <Btn primary onClick={onCreate}>+ 新建旅程</Btn>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 14 }}>
        {loading ? Array.from({ length: 4 }).map((_, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: 20, border: `1px solid ${BORDER}` }}>
            <Skeleton h={18} w="60%" /><div style={{ height: 12 }} />
            <Skeleton h={40} /><div style={{ height: 12 }} />
            <div style={{ display: 'flex', gap: 8 }}><Skeleton h={28} w={80} /><Skeleton h={28} w={80} /></div>
          </div>
        )) : journeys.length === 0 ? (
          <div style={{ gridColumn: '1/-1', padding: 60, textAlign: 'center', background: BG_CARD, borderRadius: 10, border: `1px solid ${BORDER}` }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>🗺️</div>
            <div style={{ fontSize: 15, color: TEXT_2, marginBottom: 4 }}>还没有旅程</div>
            <div style={{ fontSize: 13, color: TEXT_4, marginBottom: 16 }}>创建自动化营销旅程，触发精准会员运营</div>
            <Btn primary onClick={onCreate}>+ 新建旅程</Btn>
          </div>
        ) : journeys.map(j => {
          const st = STATUS_CFG[j.status];
          return (
            <div key={j.id} style={{
              background: BG_CARD, borderRadius: 10, padding: 20,
              border: `1px solid ${BORDER}`, cursor: 'pointer',
              transition: 'border-color 0.2s',
            }} onClick={() => onEdit(j)}
              onMouseEnter={e => (e.currentTarget.style.borderColor = PRIMARY + '66')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = BORDER)}
            >
              {/* 头部 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{j.name}</span>
                <span style={{
                  fontSize: 11, padding: '2px 10px', borderRadius: 4,
                  background: st.color + '22', color: st.color, fontWeight: 600,
                }}>{st.label}</span>
              </div>

              {/* 数据 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 14 }}>
                <div>
                  <div style={{ fontSize: 11, color: TEXT_3 }}>触发人数</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: TEXT_1 }}>{j.trigger_count.toLocaleString()}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: TEXT_3 }}>转化率</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: SUCCESS }}>{(j.conversion_rate * 100).toFixed(1)}%</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: TEXT_3 }}>节点数</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: TEXT_2 }}>{j.nodes.length}</div>
                </div>
              </div>

              {/* 节点预览 */}
              <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
                {j.nodes.slice(0, 5).map(n => {
                  const nc = NODE_CFG[n.type];
                  return (
                    <span key={n.id} style={{
                      fontSize: 10, padding: '2px 6px', borderRadius: 4,
                      background: nc.color + '22', color: nc.color,
                    }}>{nc.icon} {n.label}</span>
                  );
                })}
                {j.nodes.length > 5 && <span style={{ fontSize: 10, color: TEXT_4, alignSelf: 'center' }}>+{j.nodes.length - 5}</span>}
              </div>

              {/* 底部 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: TEXT_4 }}>创建于 {formatDate(j.created_at)}</span>
                <div style={{ display: 'flex', gap: 6 }} onClick={e => e.stopPropagation()}>
                  {j.status === 'draft' && <Btn small primary onClick={() => handleStatusChange(j, 'running')}>启动</Btn>}
                  {j.status === 'running' && <Btn small onClick={() => handleStatusChange(j, 'paused')}>暂停</Btn>}
                  {j.status === 'paused' && <Btn small primary onClick={() => handleStatusChange(j, 'running')}>恢复</Btn>}
                  {(j.status === 'running' || j.status === 'paused') && <Btn small danger onClick={() => handleStatusChange(j, 'ended')}>结束</Btn>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================
// 旅程设计器 — 节点组件
// ============================================================

function DesignerNode({
  node, isSelected, onClick, onUpdate,
}: {
  node: JourneyNode; isSelected: boolean; onClick: () => void;
  onUpdate: (node: JourneyNode) => void;
}) {
  const cfg = NODE_CFG[node.type];
  const borderColor = isSelected ? cfg.color : BORDER;

  return (
    <div
      onClick={onClick}
      style={{
        background: BG_CARD, borderRadius: 10, padding: '12px 16px',
        border: `2px solid ${borderColor}`,
        cursor: 'pointer', minWidth: 180, maxWidth: 240,
        transition: 'border-color 0.2s, box-shadow 0.2s',
        boxShadow: isSelected ? `0 0 12px ${cfg.color}33` : 'none',
        position: 'relative',
      }}
    >
      {/* 节点统计 */}
      {node.stats && (
        <div style={{
          position: 'absolute', top: -10, right: 10,
          fontSize: 10, padding: '1px 8px', borderRadius: 10,
          background: INFO, color: '#fff', fontWeight: 600,
        }}>
          {node.stats.entered} 人
        </div>
      )}

      {/* 类型标签 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ fontSize: 14 }}>{cfg.icon}</span>
        <span style={{
          fontSize: 10, padding: '1px 6px', borderRadius: 4,
          background: cfg.color + '22', color: cfg.color, fontWeight: 600,
        }}>{cfg.label}</span>
      </div>

      {/* 节点名 */}
      <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1, lineHeight: 1.3 }}>{node.label}</div>

      {/* 简要配置信息 */}
      {node.type === 'wait' && node.config.hours && (
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 4 }}>等待 {node.config.hours as number} 小时</div>
      )}
      {node.type === 'wait' && node.config.days && (
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 4 }}>等待 {node.config.days as number} 天</div>
      )}
      {node.type === 'condition' && node.config.field && (
        <div style={{ fontSize: 11, color: TEXT_3, marginTop: 4 }}>
          IF {node.config.field as string} {node.config.op as string} {String(node.config.value)}
        </div>
      )}
    </div>
  );
}

// ============================================================
// 旅程设计器 — 连接线
// ============================================================

function Connector({ label, branchSide }: { label?: string; branchSide?: 'left' | 'right' }) {
  const lineStyle: React.CSSProperties = {
    width: 2, height: 32, background: BORDER, margin: '0 auto',
  };

  if (branchSide) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: branchSide === 'left' ? 'flex-end' : 'flex-start', position: 'relative' }}>
        <div style={{ ...lineStyle, height: 24 }} />
        {label && (
          <span style={{
            position: 'absolute', top: 4,
            [branchSide === 'left' ? 'right' : 'left']: '50%',
            fontSize: 10, color: TEXT_4, whiteSpace: 'nowrap',
          }}>{label}</span>
        )}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div style={lineStyle} />
      {label && <span style={{ fontSize: 10, color: TEXT_4, marginTop: -4 }}>{label}</span>}
      <div style={{
        width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent',
        borderTop: `6px solid ${BORDER}`,
      }} />
    </div>
  );
}

// ============================================================
// 旅程设计器 — 节点配置面板
// ============================================================

function NodeConfigPanel({ node, onUpdate, onDelete }: {
  node: JourneyNode; onUpdate: (n: JourneyNode) => void; onDelete: () => void;
}) {
  const cfg = NODE_CFG[node.type];
  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px', borderRadius: 6,
    border: `1px solid ${BORDER}`, background: BG_INPUT, color: TEXT_1, fontSize: 13, outline: 'none',
  };
  const labelStyle: React.CSSProperties = { fontSize: 12, color: TEXT_3, marginBottom: 4, display: 'block' };

  return (
    <div style={{
      background: BG_CARD, borderRadius: 10, padding: 16,
      border: `1px solid ${cfg.color}44`, minWidth: 260,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{cfg.icon} {cfg.label}节点配置</span>
        {node.type !== 'trigger' && node.type !== 'end' && (
          <Btn small danger onClick={onDelete}>删除</Btn>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {/* 节点名称 */}
        <div>
          <label style={labelStyle}>节点名称</label>
          <input style={inputStyle} value={node.label}
            onChange={e => onUpdate({ ...node, label: e.target.value })} />
        </div>

        {/* 触发节点配置 */}
        {node.type === 'trigger' && (
          <div>
            <label style={labelStyle}>触发条件</label>
            <select style={inputStyle} value={(node.config.trigger_type as string) || ''}
              onChange={e => onUpdate({ ...node, config: { ...node.config, trigger_type: e.target.value } })}>
              <option value="">选择触发条件</option>
              {TRIGGER_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
            {(node.config.trigger_type === 'spend_over' || node.config.trigger_type === 'inactive_days') && (
              <div style={{ marginTop: 8 }}>
                <label style={labelStyle}>
                  {node.config.trigger_type === 'spend_over' ? '消费金额（元）' : '未消费天数'}
                </label>
                <input style={inputStyle} type="number" value={(node.config.threshold as number) || ''}
                  onChange={e => onUpdate({ ...node, config: { ...node.config, threshold: Number(e.target.value) } })} />
              </div>
            )}
          </div>
        )}

        {/* 等待节点配置 */}
        {node.type === 'wait' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <label style={labelStyle}>天数</label>
              <input style={inputStyle} type="number" value={(node.config.days as number) || ''}
                onChange={e => onUpdate({ ...node, config: { ...node.config, days: Number(e.target.value) } })} />
            </div>
            <div>
              <label style={labelStyle}>小时</label>
              <input style={inputStyle} type="number" value={(node.config.hours as number) || ''}
                onChange={e => onUpdate({ ...node, config: { ...node.config, hours: Number(e.target.value) } })} />
            </div>
          </div>
        )}

        {/* 条件节点配置 */}
        {node.type === 'condition' && (
          <>
            <div>
              <label style={labelStyle}>判断字段</label>
              <select style={inputStyle} value={(node.config.field as string) || ''}
                onChange={e => onUpdate({ ...node, config: { ...node.config, field: e.target.value } })}>
                <option value="">选择字段</option>
                <option value="total_spend_fen">消费金额</option>
                <option value="is_vip">是否VIP</option>
                <option value="coupon_opened">是否打开了券</option>
                <option value="member_level">会员等级</option>
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div>
                <label style={labelStyle}>运算符</label>
                <select style={inputStyle} value={(node.config.op as string) || ''}
                  onChange={e => onUpdate({ ...node, config: { ...node.config, op: e.target.value } })}>
                  <option value=">">&gt;</option>
                  <option value=">=">&gt;=</option>
                  <option value="==">=</option>
                  <option value="<">&lt;</option>
                </select>
              </div>
              <div>
                <label style={labelStyle}>值</label>
                <input style={inputStyle} value={(node.config.value as string) || ''}
                  onChange={e => onUpdate({ ...node, config: { ...node.config, value: e.target.value } })} />
              </div>
            </div>
          </>
        )}

        {/* 动作节点配置 */}
        {node.type === 'action' && (
          <>
            <div>
              <label style={labelStyle}>动作类型</label>
              <select style={inputStyle} value={(node.config.action_type as string) || ''}
                onChange={e => onUpdate({ ...node, config: { ...node.config, action_type: e.target.value } })}>
                <option value="">选择动作</option>
                {ACTION_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
              </select>
            </div>
            {(node.config.action_type === 'send_coupon' || node.config.action_type === 'send_points') && (
              <div>
                <label style={labelStyle}>
                  {node.config.action_type === 'send_coupon' ? '券ID' : '积分数量'}
                </label>
                <input style={inputStyle} value={(node.config.action_value as string) || ''}
                  onChange={e => onUpdate({ ...node, config: { ...node.config, action_value: e.target.value } })} />
              </div>
            )}
            {node.config.action_type === 'push_message' && (
              <div>
                <label style={labelStyle}>消息内容</label>
                <textarea style={{ ...inputStyle, minHeight: 60, resize: 'vertical' }}
                  value={(node.config.message as string) || ''}
                  onChange={e => onUpdate({ ...node, config: { ...node.config, message: e.target.value } })} />
              </div>
            )}
            {node.config.action_type === 'add_tag' && (
              <div>
                <label style={labelStyle}>标签名</label>
                <input style={inputStyle} value={(node.config.tag as string) || ''}
                  onChange={e => onUpdate({ ...node, config: { ...node.config, tag: e.target.value } })} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ============================================================
// 旅程设计器 — 画布
// ============================================================

let nodeCounter = 0;
function genId() { return `node_${Date.now()}_${++nodeCounter}`; }

function JourneyDesigner({ journey, onBack }: { journey: Journey | null; onBack: () => void }) {
  const defaultNodes: JourneyNode[] = [
    { id: genId(), type: 'trigger', label: '新会员注册', config: { trigger_type: 'new_member' }, next_ids: [] },
    { id: genId(), type: 'end', label: '结束', config: {}, next_ids: [] },
  ];

  const [name, setName] = useState(journey?.name || '新旅程');
  const [nodes, setNodes] = useState<JourneyNode[]>(journey?.nodes?.length ? journey.nodes : defaultNodes);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 确保首尾节点连接
  useEffect(() => {
    setNodes(prev => {
      const linked = prev.map((n, i) => {
        if (n.type === 'end') return { ...n, next_ids: [] };
        // 对条件节点，保持其两个分支；其他节点连到下一个
        if (n.type === 'condition') {
          if (n.next_ids.length < 2 && i + 1 < prev.length) {
            return { ...n, next_ids: [prev[i + 1]?.id, prev[i + 1]?.id].filter(Boolean) };
          }
          return n;
        }
        if (i + 1 < prev.length && (n.next_ids.length === 0 || n.next_ids[0] !== prev[i + 1].id)) {
          return { ...n, next_ids: [prev[i + 1].id] };
        }
        return n;
      });
      return linked;
    });
  }, [nodes.length]);

  const selectedNode = useMemo(() => nodes.find(n => n.id === selectedId) ?? null, [nodes, selectedId]);

  const addNodeBefore = (type: NodeType) => {
    const endIdx = nodes.findIndex(n => n.type === 'end');
    const insertAt = endIdx >= 0 ? endIdx : nodes.length;
    const labels: Record<NodeType, string> = {
      trigger: '触发', wait: '等待', condition: '条件判断', action: '执行动作', end: '结束',
    };
    const newNode: JourneyNode = {
      id: genId(), type, label: labels[type], config: {}, next_ids: [],
    };
    const updated = [...nodes];
    updated.splice(insertAt, 0, newNode);
    setNodes(updated);
    setSelectedId(newNode.id);
  };

  const updateNode = (updated: JourneyNode) => {
    setNodes(prev => prev.map(n => n.id === updated.id ? updated : n));
  };

  const deleteNode = (id: string) => {
    setNodes(prev => prev.filter(n => n.id !== id));
    if (selectedId === id) setSelectedId(null);
  };

  const handleSave = async () => {
    setSaving(true); setError(null);
    try {
      const payload = { name, nodes: nodes.map(n => ({ id: n.id, type: n.type, label: n.label, config: n.config, next_ids: n.next_ids })) };
      if (journey?.id) {
        await txFetchData<Journey>(`/api/v1/growth/journeys/${journey.id}`, {
          method: 'PATCH', body: JSON.stringify(payload),
        });
      } else {
        await txFetchData<Journey>('/api/v1/growth/journeys', {
          method: 'POST', body: JSON.stringify(payload),
        });
      }
      onBack();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally { setSaving(false); }
  };

  return (
    <div>
      {/* 顶部工具栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 0', marginBottom: 16, borderBottom: `1px solid ${BORDER}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={onBack} style={{
            background: 'none', border: 'none', color: TEXT_3, fontSize: 18, cursor: 'pointer', padding: '4px 8px',
          }}>←</button>
          <input
            value={name} onChange={e => setName(e.target.value)}
            style={{
              fontSize: 16, fontWeight: 700, color: TEXT_1, background: 'transparent',
              border: 'none', outline: 'none', borderBottom: `1px solid ${BORDER}`, padding: '4px 0', width: 280,
            }}
          />
          {journey && (
            <span style={{
              fontSize: 11, padding: '2px 10px', borderRadius: 4,
              background: STATUS_CFG[journey.status].color + '22',
              color: STATUS_CFG[journey.status].color, fontWeight: 600,
            }}>{STATUS_CFG[journey.status].label}</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn onClick={onBack}>取消</Btn>
          <Btn primary onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存旅程'}</Btn>
        </div>
      </div>

      {error && <ErrorBanner msg={error} />}

      {/* 添加节点按钮 */}
      <div style={{
        display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap',
        padding: '10px 16px', background: BG_CARD, borderRadius: 8, border: `1px solid ${BORDER}`,
      }}>
        <span style={{ fontSize: 12, color: TEXT_3, alignSelf: 'center', marginRight: 4 }}>添加节点：</span>
        {(['wait', 'condition', 'action'] as NodeType[]).map(t => {
          const c = NODE_CFG[t];
          return (
            <button key={t} onClick={() => addNodeBefore(t)} style={{
              padding: '5px 14px', borderRadius: 6, border: `1px solid ${c.color}44`,
              background: c.color + '11', color: c.color,
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}>{c.icon} {c.label}</button>
          );
        })}
      </div>

      {/* 主画布 */}
      <div style={{ display: 'flex', gap: 24 }}>
        {/* 流程图区域 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', paddingBottom: 40 }}>
          {nodes.map((node, i) => {
            const isCondition = node.type === 'condition';

            return (
              <div key={node.id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                {/* 连接线（非首节点） */}
                {i > 0 && <Connector />}

                {/* 条件节点特殊布局 */}
                {isCondition ? (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    <DesignerNode node={node} isSelected={selectedId === node.id}
                      onClick={() => setSelectedId(node.id)} onUpdate={updateNode} />
                    {/* 分叉标签 */}
                    <div style={{ display: 'flex', gap: 80, marginTop: 8 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <div style={{
                          width: 40, height: 2, background: SUCCESS,
                          position: 'relative',
                        }}>
                          <span style={{ position: 'absolute', top: -16, left: '50%', transform: 'translateX(-50%)', fontSize: 10, color: SUCCESS, whiteSpace: 'nowrap' }}>是 YES</span>
                        </div>
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <div style={{
                          width: 40, height: 2, background: ERROR,
                          position: 'relative',
                        }}>
                          <span style={{ position: 'absolute', top: -16, left: '50%', transform: 'translateX(-50%)', fontSize: 10, color: ERROR, whiteSpace: 'nowrap' }}>否 NO</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <DesignerNode node={node} isSelected={selectedId === node.id}
                    onClick={() => setSelectedId(node.id)} onUpdate={updateNode} />
                )}
              </div>
            );
          })}
        </div>

        {/* 右侧配置面板 */}
        <div style={{ width: 280, flexShrink: 0 }}>
          {selectedNode ? (
            <NodeConfigPanel node={selectedNode} onUpdate={updateNode} onDelete={() => deleteNode(selectedNode.id)} />
          ) : (
            <div style={{
              background: BG_CARD, borderRadius: 10, padding: 20,
              border: `1px solid ${BORDER}`, textAlign: 'center',
            }}>
              <div style={{ fontSize: 28, marginBottom: 8 }}>👆</div>
              <div style={{ fontSize: 13, color: TEXT_3 }}>点击节点查看配置</div>
            </div>
          )}

          {/* 旅程统计摘要 */}
          {journey && journey.trigger_count > 0 && (
            <div style={{
              background: BG_CARD, borderRadius: 10, padding: 16, marginTop: 14,
              border: `1px solid ${BORDER}`,
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1, marginBottom: 10 }}>转化漏斗</div>
              {nodes.filter(n => n.stats).map(n => {
                const pct = journey.trigger_count > 0 ? ((n.stats!.entered / journey.trigger_count) * 100) : 0;
                return (
                  <div key={n.id} style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_3, marginBottom: 3 }}>
                      <span>{n.label}</span>
                      <span>{n.stats!.entered} 人 ({pct.toFixed(0)}%)</span>
                    </div>
                    <div style={{ height: 6, borderRadius: 3, background: BG_INPUT }}>
                      <div style={{ height: '100%', borderRadius: 3, background: NODE_CFG[n.type].color, width: `${Math.min(pct, 100)}%`, transition: 'width 0.3s' }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================
// 主页面
// ============================================================

type ViewMode = 'list' | 'designer';

export default function JourneyDesignerPage() {
  const [view, setView] = useState<ViewMode>('list');
  const [editingJourney, setEditingJourney] = useState<Journey | null>(null);

  const handleEdit = (j: Journey) => {
    setEditingJourney(j);
    setView('designer');
  };

  const handleCreate = () => {
    setEditingJourney(null);
    setView('designer');
  };

  const handleBack = () => {
    setEditingJourney(null);
    setView('list');
  };

  return (
    <div style={{ minHeight: '100vh', background: BG_PAGE, padding: '20px 24px' }}>
      {/* shimmer keyframes */}
      <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>

      {/* 页头 */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: TEXT_1 }}>客户旅程编排</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: TEXT_3 }}>可视化设计自动化营销旅程，触发精准会员运营</p>
      </div>

      {view === 'list' ? (
        <JourneyListView onEdit={handleEdit} onCreate={handleCreate} />
      ) : (
        <JourneyDesigner journey={editingJourney} onBack={handleBack} />
      )}
    </div>
  );
}
