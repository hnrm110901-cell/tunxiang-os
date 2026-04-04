/**
 * 催菜页面 — 当前桌台出餐进度 + 一键催菜
 * 状态: 待制作/制作中/已出品
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { txFetch } from '../api/index';

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

/* ---------- 桌台任务类型 ---------- */
type TableWithTasks = { tableNo: string; orderId: string; tasks: RushTask[] };

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
  const storeId = (window as any).__STORE_ID__ || 'store_001';

  const [tables, setTables] = useState<TableWithTasks[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const url = filterTable
      ? `/api/v1/kds/tasks?store_id=${encodeURIComponent(storeId)}&table_no=${encodeURIComponent(filterTable)}&status=pending,cooking`
      : `/api/v1/kds/tasks?store_id=${encodeURIComponent(storeId)}&status=pending,cooking`;

    txFetch<{ items: Array<{ task_id: string; order_id: string; table_no: string; dish_name: string; quantity: number; spec?: string; status: string; created_at: string }> }>(url)
      .then(res => {
        // 按桌台分组
        const grouped: Record<string, TableWithTasks> = {};
        for (const item of res.items) {
          if (!grouped[item.table_no]) {
            grouped[item.table_no] = { tableNo: item.table_no, orderId: item.order_id, tasks: [] };
          }
          const elapsedMin = Math.floor((Date.now() - new Date(item.created_at).getTime()) / 60000);
          grouped[item.table_no].tasks.push({
            id: item.task_id,
            dishName: item.dish_name,
            qty: item.quantity,
            spec: item.spec,
            status: item.status as TaskStatus,
            elapsedMin,
            rushed: false,
          });
        }
        setTables(Object.values(grouped));
      })
      .catch(() => { /* API不可用，显示空态 */ })
      .finally(() => setLoading(false));
  }, [storeId, filterTable]);

  const displayed = filterTable
    ? tables.filter(t => t.tableNo === filterTable)
    : tables;

  const handleRushTask = async (tableIdx: number, taskId: string) => {
    // 乐观更新
    setTables(prev => prev.map((table, tIdx) => {
      if (tIdx !== tableIdx) return table;
      return {
        ...table,
        tasks: table.tasks.map(task =>
          task.id === taskId ? { ...task, rushed: true } : task
        ),
      };
    }));
    try {
      await txFetch(`/api/v1/kds/tasks/${encodeURIComponent(taskId)}/rush`, { method: 'POST' });
    } catch {
      // 催菜失败静默处理，UI已更新不回滚（避免闪烁）
    }
  };

  const handleRushAll = async (tableIdx: number) => {
    const table = tables[tableIdx];
    setTables(prev => prev.map((t, tIdx) => {
      if (tIdx !== tableIdx) return t;
      return {
        ...t,
        tasks: t.tasks.map(task =>
          task.status !== 'done' ? { ...task, rushed: true } : task
        ),
      };
    }));
    // 并行催所有未完成任务
    const pending = table.tasks.filter(t => t.status !== 'done' && !t.rushed);
    await Promise.allSettled(
      pending.map(t => txFetch(`/api/v1/kds/tasks/${encodeURIComponent(t.id)}/rush`, { method: 'POST' }))
    );
  };

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 4px' }}>
        催菜
      </h1>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 16px' }}>
        查看出餐进度，一键催菜
      </p>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>加载中...</div>
      ) : displayed.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          暂无进行中的订单
        </div>
      ) : null}

      {displayed.map((table, _tIdx) => {
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
