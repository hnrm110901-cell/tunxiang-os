/**
 * 复盘整改页 — Top3 问题 + Agent 建议 + 整改任务列表
 */
import { useState } from 'react';

/* ---------- 类型 ---------- */
interface TopIssue {
  id: string;
  rank: number;
  title: string;
  detail: string;
  agentSuggestion: string;
}

interface Task {
  id: string;
  title: string;
  assignee: string;
  done: boolean;
}

/* ---------- Mock 数据 ---------- */
const topIssues: TopIssue[] = [
  {
    id: 'i1', rank: 1,
    title: '午高峰出餐超时 12 单',
    detail: '11:30-13:00 时段，热菜档口平均出餐 18 分钟，超标准 5 分钟',
    agentSuggestion: 'Agent 建议：增加 1 名热菜备份岗位；将 3 道高耗时菜品移至预制流程',
  },
  {
    id: 'i2', rank: 2,
    title: '退菜率 3.2%（目标 <2%）',
    detail: '主要集中在"酸菜鱼"和"剁椒鱼头"，原因：口味偏咸',
    agentSuggestion: 'Agent 建议：通知后厨调整调味配方；本周内安排口味盲测复核',
  },
  {
    id: 'i3', rank: 3,
    title: '收银差异 +38 元',
    detail: '实收 vs 系统差额 38 元，疑似找零误差',
    agentSuggestion: 'Agent 建议：启用零钱盘点双人复核制度；考虑推动无现金收银比例至 95%',
  },
];

const initialTasks: Task[] = [
  { id: 't1', title: '热菜档口增加备份岗位排班', assignee: '张店长', done: false },
  { id: 't2', title: '酸菜鱼/剁椒鱼头调味配方调整', assignee: '王厨师长', done: false },
  { id: 't3', title: '收银零钱盘点流程更新', assignee: '李收银', done: true },
  { id: 't4', title: '口味盲测安排（本周五前）', assignee: '张店长', done: false },
];

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  yellow: '#facc15',
};

/* ---------- 数据卡片数据 ---------- */
const stats = [
  { label: '今日营收', value: '\u00A512,860', trend: '+8%' },
  { label: '客单价', value: '\u00A568.2', trend: '+3%' },
  { label: '翻台率', value: '3.1 次', trend: '-0.2' },
  { label: '好评率', value: '96%', trend: '+1%' },
];

/* ---------- 组件 ---------- */
export function ReviewPage() {
  const [tasks, setTasks] = useState<Task[]>(initialTasks);

  const toggleTask = (id: string) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, done: !t.done } : t));
  };

  const pendingTasks = tasks.filter(t => !t.done);
  const doneTasks = tasks.filter(t => t.done);

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      {/* 页头 */}
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 16px' }}>
        复盘整改
      </h1>

      {/* 数据卡片 */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 20,
      }}>
        {stats.map(s => (
          <div key={s.label} style={{
            background: C.card, borderRadius: 10, padding: '12px 14px',
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontSize: 13, color: C.muted }}>{s.label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginTop: 4 }}>
              {s.value}
            </div>
            <div style={{
              fontSize: 12, marginTop: 2,
              color: s.trend.startsWith('+') ? C.green : C.accent,
            }}>
              {s.trend}
            </div>
          </div>
        ))}
      </div>

      {/* Top 3 问题 */}
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '0 0 10px' }}>
        今日 Top 3 问题
      </h2>
      {topIssues.map(issue => (
        <div key={issue.id} style={{
          background: C.card, borderRadius: 10, padding: 14, marginBottom: 10,
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{
              width: 24, height: 24, borderRadius: '50%', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              fontSize: 13, fontWeight: 700,
              background: issue.rank === 1 ? C.accent : issue.rank === 2 ? C.yellow : C.muted,
              color: issue.rank === 2 ? '#000' : C.white,
            }}>
              {issue.rank}
            </span>
            <span style={{ fontSize: 16, fontWeight: 600, color: C.white }}>
              {issue.title}
            </span>
          </div>
          <p style={{ fontSize: 14, color: C.muted, margin: '0 0 8px', lineHeight: 1.5 }}>
            {issue.detail}
          </p>
          <div style={{
            fontSize: 14, color: C.green, lineHeight: 1.5,
            padding: '8px 10px', borderRadius: 6,
            background: 'rgba(34,197,94,0.08)',
          }}>
            {issue.agentSuggestion}
          </div>
        </div>
      ))}

      {/* 整改任务列表 */}
      <h2 style={{ fontSize: 17, fontWeight: 600, color: C.white, margin: '20px 0 10px' }}>
        整改任务
      </h2>

      {/* 待办 */}
      {pendingTasks.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 6 }}>
            待办（{pendingTasks.length}）
          </div>
          {pendingTasks.map(t => (
            <button
              key={t.id}
              onClick={() => toggleTask(t.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                width: '100%', minHeight: 52, padding: '10px 12px',
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 8, marginBottom: 6, cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <span style={{
                width: 22, height: 22, borderRadius: 4,
                border: `1.5px solid ${C.muted}`,
                flexShrink: 0,
              }} />
              <div>
                <div style={{ fontSize: 15, color: C.text }}>{t.title}</div>
                <div style={{ fontSize: 12, color: C.muted }}>{t.assignee}</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* 已完成 */}
      {doneTasks.length > 0 && (
        <div>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 6 }}>
            已完成（{doneTasks.length}）
          </div>
          {doneTasks.map(t => (
            <button
              key={t.id}
              onClick={() => toggleTask(t.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                width: '100%', minHeight: 52, padding: '10px 12px',
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 8, marginBottom: 6, cursor: 'pointer',
                textAlign: 'left', opacity: 0.6,
              }}
            >
              <span style={{
                width: 22, height: 22, borderRadius: 4,
                background: C.green, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                fontSize: 13, color: C.white, flexShrink: 0,
              }}>
                {'\u2713'}
              </span>
              <div>
                <div style={{ fontSize: 15, color: C.text, textDecoration: 'line-through' }}>{t.title}</div>
                <div style={{ fontSize: 12, color: C.muted }}>{t.assignee}</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
