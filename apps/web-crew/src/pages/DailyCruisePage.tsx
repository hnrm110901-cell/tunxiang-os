/**
 * 日清日结巡航页 — E1-E8 八节点流程时间轴
 * 深色主题，手机端友好（字号>=16px，热区>=48px）
 */
import { useState } from 'react';

/* ---------- 类型 ---------- */
type NodeStatus = 'pending' | 'in_progress' | 'completed';

interface CheckItem {
  id: string;
  label: string;
  done: boolean;
}

interface CruiseNode {
  code: string;
  name: string;
  status: NodeStatus;
  checks: CheckItem[];
}

/* ---------- Mock 数据 ---------- */
const initialNodes: CruiseNode[] = [
  {
    code: 'E1', name: '开店准备', status: 'completed',
    checks: [
      { id: 'e1-1', label: '设备通电自检', done: true },
      { id: 'e1-2', label: '食材效期检查', done: true },
      { id: 'e1-3', label: '环境卫生确认', done: true },
    ],
  },
  {
    code: 'E2', name: '营业巡航', status: 'completed',
    checks: [
      { id: 'e2-1', label: '桌台翻台率监控', done: true },
      { id: 'e2-2', label: '出餐超时预警', done: true },
    ],
  },
  {
    code: 'E3', name: '异常处理', status: 'completed',
    checks: [
      { id: 'e3-1', label: '客诉处理闭环', done: true },
      { id: 'e3-2', label: '退菜原因记录', done: true },
      { id: 'e3-3', label: '设备故障上报', done: true },
    ],
  },
  {
    code: 'E4', name: '交接班', status: 'in_progress',
    checks: [
      { id: 'e4-1', label: '现金盘点', done: true },
      { id: 'e4-2', label: '库存交接', done: false },
      { id: 'e4-3', label: '待办事项交接', done: false },
    ],
  },
  {
    code: 'E5', name: '闭店检查', status: 'pending',
    checks: [
      { id: 'e5-1', label: '水电燃气关闭', done: false },
      { id: 'e5-2', label: '食材入库封存', done: false },
    ],
  },
  {
    code: 'E6', name: '日结对账', status: 'pending',
    checks: [
      { id: 'e6-1', label: '营收核对', done: false },
      { id: 'e6-2', label: '优惠核销统计', done: false },
      { id: 'e6-3', label: '差异说明填写', done: false },
    ],
  },
  {
    code: 'E7', name: '复盘归因', status: 'pending',
    checks: [
      { id: 'e7-1', label: '问题根因分析', done: false },
      { id: 'e7-2', label: 'TOP3 问题确认', done: false },
    ],
  },
  {
    code: 'E8', name: '整改跟踪', status: 'pending',
    checks: [
      { id: 'e8-1', label: '整改任务分配', done: false },
      { id: 'e8-2', label: '完成时限设定', done: false },
    ],
  },
];

/* ---------- 样式常量 ---------- */
const COLOR = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  yellow: '#facc15',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

/* ---------- 辅助 ---------- */
function statusColor(s: NodeStatus) {
  if (s === 'completed') return COLOR.green;
  if (s === 'in_progress') return COLOR.accent;
  return COLOR.muted;
}

function statusLabel(s: NodeStatus) {
  if (s === 'completed') return '已完成';
  if (s === 'in_progress') return '进行中';
  return '待处理';
}

/* ---------- 组件 ---------- */
export function DailyCruisePage() {
  const [nodes] = useState<CruiseNode[]>(initialNodes);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  const completedCount = nodes.filter(n => n.status === 'completed').length;
  const totalCount = nodes.length;
  const progressPct = Math.round((completedCount / totalCount) * 100);

  const toggle = (code: string) => {
    setExpandedCode(prev => (prev === code ? null : code));
  };

  return (
    <div style={{ padding: '16px 12px 120px', background: COLOR.bg, minHeight: '100vh' }}>
      {/* 页头 */}
      <h1 style={{ fontSize: 20, fontWeight: 700, color: COLOR.white, margin: '0 0 4px' }}>
        日清日结巡航
      </h1>
      <p style={{ fontSize: 14, color: COLOR.muted, margin: '0 0 20px' }}>
        {completedCount}/{totalCount} 节点已完成
      </p>

      {/* 时间轴 */}
      <div style={{ position: 'relative', paddingLeft: 28 }}>
        {/* 竖线 */}
        <div style={{
          position: 'absolute', left: 11, top: 0, bottom: 0,
          width: 2, background: COLOR.border,
        }} />

        {nodes.map((node) => {
          const isActive = node.status === 'in_progress';
          const isDone = node.status === 'completed';
          const isExpanded = expandedCode === node.code;
          const doneChecks = node.checks.filter(c => c.done).length;

          return (
            <div key={node.code} style={{ marginBottom: 12 }}>
              {/* 节点头（可点击，热区>=48px） */}
              <button
                onClick={() => toggle(node.code)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  width: '100%', minHeight: 52,
                  background: isActive ? 'rgba(255,107,44,0.08)' : 'transparent',
                  border: 'none', borderRadius: 10, padding: '8px 12px',
                  cursor: 'pointer', textAlign: 'left',
                  outline: isActive ? `1.5px solid ${COLOR.accent}` : 'none',
                }}
              >
                {/* 圆点 / 打勾 */}
                <span style={{
                  position: 'absolute', left: -17,
                  width: 22, height: 22, borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 13, fontWeight: 700,
                  background: isDone ? COLOR.green : isActive ? COLOR.accent : COLOR.border,
                  color: COLOR.white,
                  boxShadow: isActive ? `0 0 8px ${COLOR.accent}` : 'none',
                }}>
                  {isDone ? '\u2713' : ''}
                </span>

                {/* 文字区 */}
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: 16, fontWeight: isActive ? 700 : 500,
                    color: isDone ? COLOR.green : isActive ? COLOR.accent : COLOR.text,
                  }}>
                    {node.code} {node.name}
                  </div>
                  <div style={{ fontSize: 13, color: COLOR.muted, marginTop: 2 }}>
                    <span style={{
                      display: 'inline-block', padding: '1px 6px',
                      borderRadius: 4, fontSize: 11,
                      background: `${statusColor(node.status)}22`,
                      color: statusColor(node.status),
                      marginRight: 8,
                    }}>
                      {statusLabel(node.status)}
                    </span>
                    {doneChecks}/{node.checks.length} 项
                  </div>
                </div>

                {/* 展开箭头 */}
                <span style={{
                  fontSize: 14, color: COLOR.muted,
                  transform: isExpanded ? 'rotate(90deg)' : 'rotate(0)',
                  transition: 'transform .2s',
                }}>
                  {'\u25B6'}
                </span>
              </button>

              {/* 展开的检查项列表 */}
              {isExpanded && (
                <div style={{
                  marginTop: 4, marginLeft: 12, padding: '8px 12px',
                  background: COLOR.card, borderRadius: 8,
                  border: `1px solid ${COLOR.border}`,
                }}>
                  {node.checks.map(ck => (
                    <div key={ck.id} style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      minHeight: 40, fontSize: 15,
                      color: ck.done ? COLOR.green : COLOR.text,
                      borderBottom: `1px solid ${COLOR.border}`,
                      padding: '6px 0',
                    }}>
                      <span style={{
                        width: 20, height: 20, borderRadius: 4,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 13,
                        background: ck.done ? COLOR.green : 'transparent',
                        border: ck.done ? 'none' : `1.5px solid ${COLOR.muted}`,
                        color: COLOR.white,
                      }}>
                        {ck.done ? '\u2713' : ''}
                      </span>
                      <span style={{ textDecoration: ck.done ? 'line-through' : 'none', opacity: ck.done ? 0.6 : 1 }}>
                        {ck.label}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 底部进度条 */}
      <div style={{
        position: 'fixed', bottom: 56, left: 0, right: 0,
        padding: '10px 16px 8px', background: COLOR.bg,
        borderTop: `1px solid ${COLOR.border}`,
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between',
          fontSize: 13, color: COLOR.muted, marginBottom: 6,
        }}>
          <span>今日进度</span>
          <span>{progressPct}%（{completedCount}/{totalCount}）</span>
        </div>
        <div style={{
          height: 8, borderRadius: 4, background: COLOR.border, overflow: 'hidden',
        }}>
          <div style={{
            height: '100%', borderRadius: 4,
            width: `${progressPct}%`,
            background: `linear-gradient(90deg, ${COLOR.accent}, ${COLOR.green})`,
            transition: 'width .4s ease',
          }} />
        </div>
      </div>
    </div>
  );
}
