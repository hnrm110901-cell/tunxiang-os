/**
 * RouteOptimizePage — 上菜路线优化（传菜员 Runner 工作站）
 *
 * 功能：
 *   - 按贪心算法对待送任务排序：score = wait_minutes * 2 + distance_penalty
 *   - 显示建议上菜顺序与原因说明
 *   - "已送达"确认后自动移除任务
 *   - 所有任务完成后显示庆祝界面
 *
 * Store-Crew 终端规范：
 *   - 纯内联样式，dark theme（背景 #0B1A20）
 *   - 主色 #FF6B35
 *   - 所有点击区域 ≥ 48px，最小字体 16px
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── Types ───

interface TablePosition {
  x: number;
  y: number;
}

interface PendingTask {
  id: string;
  table: string;
  dishes: string[];
  wait_minutes: number;
  pos: TablePosition;
}

interface ScoredTask extends PendingTask {
  score: number;
  priority: number;
  reason: string;
}

// ─── API ───

async function fetchPendingTasks(): Promise<PendingTask[]> {
  try {
    const resp = await fetch('/api/v1/runner/pending-tasks', {
      headers: { 'X-Tenant-ID': (window as any).__TENANT_ID__ || '' },
    });
    if (!resp.ok) throw new Error('non-ok');
    const data = await resp.json();
    return data?.data ?? data ?? [];
  } catch {
    return [];
  }
}

async function markDelivered(taskId: string): Promise<boolean> {
  try {
    const resp = await fetch('/api/v1/runner/deliver', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': (window as any).__TENANT_ID__ || '',
      },
      body: JSON.stringify({ task_id: taskId, delivered_at: new Date().toISOString() }),
    });
    return resp.ok;
  } catch {
    // 离线场景：乐观更新
    return true;
  }
}

// ─── 贪心路线优化算法 ───

/**
 * 距离惩罚：以第一个任务为起点，计算每个任务与"当前位置"的曼哈顿距离。
 * 首次排序用原点 (0,0) 作为出发点。
 * distance_penalty = manhattan_distance * 1.5（保证等待时间权重更高）
 */
function computeScores(tasks: PendingTask[], origin: TablePosition = { x: 0, y: 0 }): ScoredTask[] {
  if (tasks.length === 0) return [];

  const scored = tasks.map(task => {
    const dist = Math.abs(task.pos.x - origin.x) + Math.abs(task.pos.y - origin.y);
    const distancePenalty = dist * 1.5;
    const score = task.wait_minutes * 2 + distancePenalty;
    return { ...task, score, priority: 0, reason: '' };
  });

  // score 从高到低（最紧急优先）
  scored.sort((a, b) => b.score - a.score);

  // 分配优先级 & 生成原因说明
  return scored.map((task, idx) => {
    const reasons: string[] = [];
    if (task.wait_minutes >= 10) reasons.push(`${task.table}等待超${task.wait_minutes}分钟`);
    else if (task.wait_minutes > 0) reasons.push(`${task.table}等待${task.wait_minutes}分钟`);

    const dist = Math.abs(task.pos.x - origin.x) + Math.abs(task.pos.y - origin.y);
    if (idx > 0 && dist <= 2) reasons.push('顺路可送');

    // 检查后续任务是否顺路
    if (idx === 0 && scored.length > 1) {
      const next = scored[1];
      const nextDist = Math.abs(next.pos.x - task.pos.x) + Math.abs(next.pos.y - task.pos.y);
      if (nextDist <= 2) reasons.push(`${next.table}可顺路`);
    }

    const reason = reasons.length > 0 ? reasons.join('，') : `综合评分 ${task.score.toFixed(1)}`;

    return { ...task, priority: idx + 1, reason };
  });
}

// ─── 主组件 ───

export function RouteOptimizePage() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<ScoredTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [deliveringIds, setDeliveringIds] = useState<Set<string>>(new Set());
  const [allDone, setAllDone] = useState(false);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    const raw = await fetchPendingTasks();
    const scored = computeScores(raw);
    setTasks(scored);
    setAllDone(scored.length === 0);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const handleDeliver = useCallback(async (taskId: string) => {
    if (deliveringIds.has(taskId)) return;
    setDeliveringIds(prev => new Set(prev).add(taskId));

    const ok = await markDelivered(taskId);
    if (ok) {
      setTasks(prev => {
        const next = prev.filter(t => t.id !== taskId);
        // 移除后重新计算优先级
        const rescored = computeScores(next);
        if (rescored.length === 0) setAllDone(true);
        return rescored;
      });
    }

    setDeliveringIds(prev => {
      const next = new Set(prev);
      next.delete(taskId);
      return next;
    });
  }, [deliveringIds]);

  // ─── 庆祝界面 ───
  if (allDone && !loading) {
    return (
      <div style={{
        background: '#0B1A20',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
        padding: 24,
        gap: 24,
      }}>
        <div style={{ fontSize: 64 }}>✓</div>
        <div style={{
          fontSize: 28,
          fontWeight: 'bold',
          color: '#FF6B35',
          textAlign: 'center',
        }}>
          全部上菜完成
        </div>
        <div style={{ fontSize: 18, color: '#8fa8b3', textAlign: 'center' }}>
          太棒了！所有桌的菜都已送达
        </div>
        <button
          onClick={() => navigate(-1)}
          style={{
            marginTop: 16,
            padding: '14px 40px',
            minHeight: 52,
            background: '#FF6B35',
            color: '#fff',
            border: 'none',
            borderRadius: 12,
            fontSize: 18,
            fontWeight: 'bold',
            cursor: 'pointer',
          }}
        >
          返回
        </button>
      </div>
    );
  }

  // ─── 主界面 ───
  return (
    <div style={{
      background: '#0B1A20',
      minHeight: '100vh',
      color: '#E8EDF0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
      display: 'flex',
      flexDirection: 'column',
    }}>

      {/* 顶部区域 */}
      <header style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 16px',
        background: '#0e2229',
        borderBottom: '1px solid #1a3340',
        minHeight: 60,
        flexShrink: 0,
        gap: 12,
      }}>
        {/* 返回 + 标题 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => navigate(-1)}
            style={{
              minWidth: 48,
              minHeight: 48,
              background: 'transparent',
              border: 'none',
              color: '#8fa8b3',
              fontSize: 22,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 8,
              padding: 0,
            }}
            onTouchStart={e => (e.currentTarget.style.background = 'rgba(255,107,53,0.12)')}
            onTouchEnd={e => (e.currentTarget.style.background = 'transparent')}
          >
            ‹
          </button>
          <span style={{ fontSize: 22, fontWeight: 'bold', color: '#fff' }}>
            上菜路线
          </span>
          {/* 待送菜品数量 badge */}
          {tasks.length > 0 && (
            <span style={{
              background: '#FF6B35',
              color: '#fff',
              borderRadius: 12,
              padding: '2px 10px',
              fontSize: 16,
              fontWeight: 'bold',
              minWidth: 28,
              textAlign: 'center',
            }}>
              {tasks.length}
            </span>
          )}
        </div>

        {/* 刷新按钮 */}
        <button
          onClick={loadTasks}
          disabled={loading}
          style={{
            minWidth: 80,
            minHeight: 48,
            background: loading ? '#1a3340' : 'rgba(255,107,53,0.15)',
            color: loading ? '#8fa8b3' : '#FF6B35',
            border: `1px solid ${loading ? '#1a3340' : '#FF6B35'}`,
            borderRadius: 10,
            fontSize: 16,
            fontWeight: 'bold',
            cursor: loading ? 'not-allowed' : 'pointer',
            transition: 'opacity 200ms',
          }}
          onTouchStart={e => !loading && (e.currentTarget.style.opacity = '0.7')}
          onTouchEnd={e => (e.currentTarget.style.opacity = '1')}
        >
          {loading ? '加载中' : '刷新'}
        </button>
      </header>

      {/* 主体内容 */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>

        {/* 骨架屏 */}
        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[1, 2, 3].map(i => (
              <div key={i} style={{
                background: '#0e2229',
                borderRadius: 12,
                padding: 16,
                height: 120,
                opacity: 0.5 + i * 0.1,
              }} />
            ))}
          </div>
        )}

        {/* 无任务提示 */}
        {!loading && tasks.length === 0 && !allDone && (
          <div style={{
            textAlign: 'center',
            color: '#8fa8b3',
            fontSize: 18,
            marginTop: 60,
          }}>
            暂无待送任务
          </div>
        )}

        {/* 待送任务卡片列表 */}
        {!loading && tasks.map(task => (
          <TaskCard
            key={task.id}
            task={task}
            delivering={deliveringIds.has(task.id)}
            onDeliver={handleDeliver}
          />
        ))}

        {/* 路线优化说明区域 */}
        {!loading && tasks.length > 0 && (
          <RouteHintPanel tasks={tasks} />
        )}

        {/* 底部留白，防止内容被遮挡 */}
        <div style={{ height: 32 }} />
      </div>
    </div>
  );
}

// ─── 任务卡片 ───

function TaskCard({ task, delivering, onDeliver }: {
  task: ScoredTask;
  delivering: boolean;
  onDeliver: (id: string) => void;
}) {
  const isOverdue = task.wait_minutes >= 10;
  const isWarning = task.wait_minutes >= 5 && task.wait_minutes < 10;

  const waitColor = isOverdue ? '#ff4d4f' : isWarning ? '#faad14' : '#8fa8b3';
  const borderColor = isOverdue ? '#7f1d1d' : isWarning ? '#713f12' : '#1a3340';
  const bgColor = isOverdue ? '#1a0808' : isWarning ? '#1a1000' : '#0e2229';

  return (
    <div style={{
      background: bgColor,
      borderRadius: 12,
      borderLeft: `5px solid ${isOverdue ? '#ff4d4f' : isWarning ? '#faad14' : '#1a3340'}`,
      border: `1px solid ${borderColor}`,
      borderLeftWidth: 5,
      padding: 16,
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
    }}>
      {/* 第一行：优先级 + 桌号 + 等待时长 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {/* 优先级圆形 badge */}
        <div style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: task.priority === 1 ? '#FF6B35' : task.priority === 2 ? '#fa8c16' : '#334e5a',
          color: '#fff',
          fontSize: 16,
          fontWeight: 'bold',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          {task.priority}
        </div>

        {/* 桌号 */}
        <span style={{ fontSize: 22, fontWeight: 'bold', color: '#fff', flex: 1 }}>
          {task.table} 桌
        </span>

        {/* 等待时长 */}
        <span style={{
          fontSize: 16,
          fontWeight: 'bold',
          color: waitColor,
          background: `${waitColor}18`,
          padding: '3px 10px',
          borderRadius: 8,
        }}>
          {isOverdue ? '⚠ ' : ''}{task.wait_minutes} 分钟
        </span>
      </div>

      {/* 第二行：菜品列表 */}
      <div style={{
        fontSize: 16,
        color: '#c5d4db',
        lineHeight: 1.6,
        paddingLeft: 44,
      }}>
        {task.dishes.join('　·　')}
      </div>

      {/* 第三行：已送达按钮 */}
      <div style={{ paddingLeft: 44 }}>
        <button
          onClick={() => onDeliver(task.id)}
          disabled={delivering}
          style={{
            width: '100%',
            minHeight: 52,
            background: delivering ? '#1a3340' : '#FF6B35',
            color: delivering ? '#8fa8b3' : '#fff',
            border: 'none',
            borderRadius: 10,
            fontSize: 18,
            fontWeight: 'bold',
            cursor: delivering ? 'not-allowed' : 'pointer',
            transition: 'transform 200ms ease, opacity 200ms',
            opacity: delivering ? 0.6 : 1,
          }}
          onTouchStart={e => !delivering && (e.currentTarget.style.transform = 'scale(0.97)')}
          onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          {delivering ? '处理中...' : '已送达'}
        </button>
      </div>
    </div>
  );
}

// ─── 路线优化说明面板 ───

function RouteHintPanel({ tasks }: { tasks: ScoredTask[] }) {
  if (tasks.length === 0) return null;

  const first = tasks[0];
  const restNearby = tasks.slice(1).filter(t => {
    const dist = Math.abs(t.pos.x - first.pos.x) + Math.abs(t.pos.y - first.pos.y);
    return dist <= 2;
  });

  return (
    <div style={{
      background: '#0e2229',
      borderRadius: 12,
      border: '1px solid #1a3340',
      padding: 16,
      marginTop: 4,
    }}>
      {/* 标题 */}
      <div style={{
        fontSize: 16,
        fontWeight: 'bold',
        color: '#FF6B35',
        marginBottom: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <span>⟳</span>
        <span>路线优化建议</span>
      </div>

      {/* 建议顺序说明 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {tasks.map(task => (
          <div key={task.id} style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
            fontSize: 16,
            color: '#c5d4db',
          }}>
            <span style={{
              minWidth: 24,
              height: 24,
              borderRadius: '50%',
              background: task.priority === 1 ? '#FF6B35' : '#334e5a',
              color: '#fff',
              fontSize: 14,
              fontWeight: 'bold',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              marginTop: 1,
            }}>
              {task.priority}
            </span>
            <span>
              <b style={{ color: '#fff' }}>{task.table}</b>
              <span style={{ color: '#8fa8b3', marginLeft: 6 }}>— {task.reason}</span>
            </span>
          </div>
        ))}
      </div>

      {/* 小提示 */}
      <div style={{
        marginTop: 14,
        padding: '10px 12px',
        background: 'rgba(255,107,53,0.07)',
        borderRadius: 8,
        fontSize: 16,
        color: '#8fa8b3',
        lineHeight: 1.6,
      }}>
        <span style={{ color: '#FF6B35', fontWeight: 'bold' }}>提示：</span>
        {restNearby.length > 0
          ? `先送 ${first.table}，再顺路送 ${restNearby.map(t => t.table).join('、')}，可减少折返。`
          : `优先送 ${first.table}，该桌等待时间最长。`
        }
      </div>

      {/* 算法说明 */}
      <div style={{
        marginTop: 10,
        fontSize: 14,
        color: '#4a6070',
        textAlign: 'right',
      }}>
        算法：等待时长 × 2 + 距离系数
      </div>
    </div>
  );
}
