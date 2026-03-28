/**
 * 门店工作台首页 — KPI + 待办 + Agent建议 + 快捷入口
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- Mock Data ---------- */
const mockKPI = [
  { label: '今日营收', value: '12,680', unit: '元', trend: '+8.2%', color: '#52c41a' },
  { label: '订单数', value: '86', unit: '单', trend: '+12', color: '#1890ff' },
  { label: '客单价', value: '147.4', unit: '元', trend: '-2.1%', color: '#faad14' },
  { label: '翻台率', value: '2.3', unit: '次', trend: '+0.3', color: '#722ed1' },
];

const mockTodos = [
  { id: 1, type: '预订确认', content: '18:00 王先生 6人包厢', urgent: true },
  { id: 2, type: '缺料预警', content: '剁椒酱库存不足，预计今晚用完', urgent: true },
  { id: 3, type: '客诉处理', content: 'A03桌反馈上菜慢（等待32分钟）', urgent: false },
  { id: 4, type: '预订确认', content: '19:30 李女士 4人大厅', urgent: false },
];

const mockAgentSuggestion = {
  title: 'Agent 建议：今日主推剁椒鱼头',
  content: '根据库存分析，鲈鱼到货充足（+40%），建议今日主推剁椒鱼头套餐，预计可提升客单价 8元/桌。同时减少外婆鸡推荐（鸡肉库存偏低）。',
  confidence: 0.87,
};

const shortcuts = [
  { label: '开台', path: '/tables', icon: '[ ]', color: '#1890ff' },
  { label: '预订', path: '/reservations', icon: '[R]', color: '#722ed1' },
  { label: '交班', path: '/shift', icon: '[S]', color: '#faad14' },
  { label: '异常', path: '/exceptions', icon: '[!]', color: '#ff4d4f' },
  { label: '反结账', path: '/reverse-settle', icon: '[↺]', color: '#A32D2D' },
  { label: '排队', path: '/queue', icon: '[Q]', color: '#13c2c2' },
  { label: '报表', path: '/reports', icon: '[G]', color: '#52c41a' },
  { label: '设置', path: '/settings', icon: '[⚙]', color: '#8899A6' },
];

const typeColor: Record<string, string> = {
  '预订确认': '#1890ff',
  '缺料预警': '#faad14',
  '客诉处理': '#ff4d4f',
};

/* ---------- Component ---------- */
export function POSDashboardPage() {
  const navigate = useNavigate();
  const [todos, setTodos] = useState(mockTodos);

  const handleTodoDone = (id: number) => {
    setTodos(prev => prev.filter(t => t.id !== id));
  };

  return (
    <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0', fontFamily: 'Noto Sans SC, sans-serif', padding: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 22, color: '#fff' }}>门店工作台</h1>
        <span style={{ color: '#666', fontSize: 13 }}>尝在一起 - 河西万达店</span>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        {mockKPI.map(kpi => (
          <div key={kpi.label} style={{
            background: '#112B36', borderRadius: 10, padding: 16,
            borderLeft: `4px solid ${kpi.color}`,
          }}>
            <div style={{ fontSize: 12, color: '#8899A6', marginBottom: 6 }}>{kpi.label}</div>
            <div style={{ fontSize: 28, fontWeight: 'bold', color: '#fff' }}>
              {kpi.value}
              <span style={{ fontSize: 12, color: '#8899A6', marginLeft: 4 }}>{kpi.unit}</span>
            </div>
            <div style={{ fontSize: 12, color: kpi.color, marginTop: 4 }}>{kpi.trend} 较昨日</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        {/* Todo List */}
        <div style={{ background: '#112B36', borderRadius: 10, padding: 16 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15, color: '#fff' }}>
            今日待办 <span style={{ fontSize: 12, color: '#8899A6' }}>({todos.length})</span>
          </h3>
          {todos.length === 0 && <div style={{ color: '#555', textAlign: 'center', padding: 20 }}>暂无待办</div>}
          {todos.map(todo => (
            <div key={todo.id} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 0', borderBottom: '1px solid #1A3A48',
            }}>
              <div style={{ flex: 1 }}>
                <span style={{
                  display: 'inline-block', fontSize: 11, padding: '2px 8px', borderRadius: 4,
                  background: typeColor[todo.type] || '#555', color: '#fff', marginRight: 8,
                }}>
                  {todo.type}
                </span>
                <span style={{ fontSize: 13 }}>{todo.content}</span>
                {todo.urgent && <span style={{ color: '#ff4d4f', fontSize: 11, marginLeft: 6 }}>紧急</span>}
              </div>
              <button onClick={() => handleTodoDone(todo.id)} style={{
                padding: '4px 12px', background: '#1A3A48', color: '#52c41a',
                border: '1px solid #52c41a', borderRadius: 4, cursor: 'pointer', fontSize: 12,
              }}>
                处理
              </button>
            </div>
          ))}
        </div>

        {/* Agent Suggestion */}
        <div style={{ background: '#112B36', borderRadius: 10, padding: 16, borderTop: '3px solid #722ed1' }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15, color: '#fff' }}>
            AI 决策推荐
            <span style={{ fontSize: 11, color: '#722ed1', marginLeft: 8 }}>
              置信度 {(mockAgentSuggestion.confidence * 100).toFixed(0)}%
            </span>
          </h3>
          <div style={{ fontSize: 14, fontWeight: 'bold', color: '#E0C97F', marginBottom: 8 }}>
            {mockAgentSuggestion.title}
          </div>
          <div style={{ fontSize: 13, color: '#aaa', lineHeight: 1.6 }}>
            {mockAgentSuggestion.content}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            <button style={{
              flex: 1, padding: '8px 0', background: '#722ed1', color: '#fff',
              border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 'bold',
            }}>
              采纳建议
            </button>
            <button style={{
              flex: 1, padding: '8px 0', background: 'transparent', color: '#666',
              border: '1px solid #333', borderRadius: 6, cursor: 'pointer', fontSize: 13,
            }}>
              忽略
            </button>
          </div>
        </div>
      </div>

      {/* Shortcuts */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {shortcuts.map(s => (
          <button key={s.label} onClick={() => navigate(s.path)} style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            gap: 8, padding: 20, background: '#112B36', borderRadius: 10,
            border: `1px solid ${s.color}33`, color: '#fff', cursor: 'pointer', fontSize: 15, fontWeight: 'bold',
          }}>
            <span style={{ fontSize: 24, color: s.color }}>{s.icon}</span>
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
