/**
 * 催菜页面 — 当前桌台出餐进度 + 一键催菜
 * 状态: 待制作/制作中/已出品
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

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
  danger: '#A32D2D',
  warning: '#BA7517',
};

/* ---------- 类型 ---------- */
type TaskStatus = 'pending' | 'cooking' | 'done';

interface RushTask {
  id: string;
  dishName: string;
  qty: number;
  spec?: string;
  status: TaskStatus;
  elapsedMin: number;
  rushed: boolean;
}

/* ---------- Mock 数据 ---------- */
const MOCK_TABLES_WITH_TASKS: { tableNo: string; orderId: string; tasks: RushTask[] }[] = [
  {
    tableNo: 'A01', orderId: 'ord-001',
    tasks: [
      { id: 't1', dishName: '剁椒鱼头', qty: 1, spec: '双色', status: 'cooking', elapsedMin: 18, rushed: false },
      { id: 't2', dishName: '小炒黄牛肉', qty: 1, status: 'pending', elapsedMin: 18, rushed: false },
      { id: 't3', dishName: '凉拌黄瓜', qty: 1, status: 'done', elapsedMin: 18, rushed: false },
      { id: 't4', dishName: '米饭', qty: 3, status: 'done', elapsedMin: 18, rushed: false },
    ],
  },
  {
    tableNo: 'A03', orderId: 'ord-002',
    tasks: [
      { id: 't5', dishName: '酸菜鱼', qty: 1, spec: '黑鱼', status: 'cooking', elapsedMin: 25, rushed: true },
      { id: 't6', dishName: '红烧肉', qty: 1, status: 'pending', elapsedMin: 25, rushed: false },
      { id: 't7', dishName: '蒜蓉蒸虾', qty: 1, status: 'pending', elapsedMin: 25, rushed: false },
      { id: 't8', dishName: '老鸭汤', qty: 1, status: 'done', elapsedMin: 25, rushed: false },
      { id: 't9', dishName: '酸梅汤', qty: 2, status: 'done', elapsedMin: 25, rushed: false },
    ],
  },
  {
    tableNo: 'B01', orderId: 'ord-003',
    tasks: [
      { id: 't10', dishName: '波士顿龙虾', qty: 1, spec: '蒜蓉蒸', status: 'cooking', elapsedMin: 35, rushed: false },
      { id: 't11', dishName: '剁椒鱼头', qty: 2, spec: '红剁椒', status: 'pending', elapsedMin: 35, rushed: false },
    ],
  },
];

function statusLabel(s: TaskStatus): string {
  const map: Record<TaskStatus, string> = { pending: '待制作', cooking: '制作中', done: '已出品' };
  return map[s];
}

function statusColor(s: TaskStatus): string {
  const map: Record<TaskStatus, string> = { pending: C.warning, cooking: C.accent, done: C.green };
  return map[s];
}

/* ---------- 组件 ---------- */
export function RushPage() {
  const [params] = useSearchParams();
  const filterTable = params.get('table') || '';

  const [tables, setTables] = useState(MOCK_TABLES_WITH_TASKS);

  const displayed = filterTable
    ? tables.filter(t => t.tableNo === filterTable)
    : tables;

  const handleRushTask = (tableIdx: number, taskId: string) => {
    setTables(prev => prev.map((table, tIdx) => {
      if (tIdx !== tableIdx) return table;
      return {
        ...table,
        tasks: table.tasks.map(task =>
          task.id === taskId ? { ...task, rushed: true } : task
        ),
      };
    }));
  };

  const handleRushAll = (tableIdx: number) => {
    setTables(prev => prev.map((table, tIdx) => {
      if (tIdx !== tableIdx) return table;
      return {
        ...table,
        tasks: table.tasks.map(task =>
          task.status !== 'done' ? { ...task, rushed: true } : task
        ),
      };
    }));
  };

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 4px' }}>
        催菜
      </h1>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 16px' }}>
        查看出餐进度，一键催菜
      </p>

      {displayed.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          暂无进行中的订单
        </div>
      )}

      {displayed.map((table, tIdx) => {
        const realIdx = tables.indexOf(table);
        const pendingCount = table.tasks.filter(t => t.status !== 'done').length;
        const doneCount = table.tasks.filter(t => t.status === 'done').length;

        return (
          <div key={table.tableNo} style={{
            background: C.card, borderRadius: 12, padding: 16, marginBottom: 12,
            border: `1px solid ${C.border}`,
          }}>
            {/* 桌头 */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div>
                <span style={{ fontSize: 20, fontWeight: 700, color: C.white }}>{table.tableNo} 桌</span>
                <span style={{ fontSize: 16, color: C.muted, marginLeft: 8 }}>
                  {doneCount}/{table.tasks.length} 已出
                </span>
              </div>
              <span style={{
                fontSize: 16,
                color: table.tasks[0].elapsedMin > 20 ? '#ff4d4f' : C.muted,
              }}>
                {table.tasks[0].elapsedMin}分钟
              </span>
            </div>

            {/* 菜品出餐列表 */}
            {table.tasks.map(task => (
              <div key={task.id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 0', borderBottom: `1px solid ${C.border}`,
                minHeight: 48,
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 16, color: task.status === 'done' ? C.muted : C.white }}>
                    {task.dishName} {'\u00D7'}{task.qty}
                    {task.spec && <span style={{ color: C.muted }}> ({task.spec})</span>}
                  </div>
                  <span style={{
                    fontSize: 16, padding: '1px 6px', borderRadius: 4,
                    background: `${statusColor(task.status)}22`,
                    color: statusColor(task.status),
                  }}>
                    {statusLabel(task.status)}
                  </span>
                </div>
                {task.status !== 'done' && (
                  <button
                    onClick={() => handleRushTask(realIdx, task.id)}
                    disabled={task.rushed}
                    style={{
                      minWidth: 64, minHeight: 48, padding: '8px 12px',
                      borderRadius: 8,
                      background: task.rushed ? `${C.muted}22` : `${C.accent}22`,
                      border: `1px solid ${task.rushed ? C.muted : C.accent}`,
                      color: task.rushed ? C.muted : C.accent,
                      fontSize: 16, fontWeight: 600, cursor: task.rushed ? 'default' : 'pointer',
                    }}
                  >
                    {task.rushed ? '已催' : '催'}
                  </button>
                )}
              </div>
            ))}

            {/* 一键催全部 */}
            {pendingCount > 0 && (
              <button
                onClick={() => handleRushAll(realIdx)}
                style={{
                  width: '100%', minHeight: 48, marginTop: 12, borderRadius: 12,
                  background: `${C.accent}22`, border: `1px solid ${C.accent}`,
                  color: C.accent, fontSize: 16, fontWeight: 700, cursor: 'pointer',
                }}
              >
                一键催全部未出菜品 ({pendingCount})
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
