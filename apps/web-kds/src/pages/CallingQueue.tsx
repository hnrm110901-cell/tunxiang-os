/**
 * CallingQueue — 等叫队列视图（Store 终端）
 *
 * 功能：
 *   - 展示所有 calling（等叫）状态的菜品，竖向列表
 *   - 每条记录显示：桌号、菜品名、已等待时间、楼层/区域（dept）
 *   - 等待 >5 分钟变黄，>10 分钟变红
 *   - 「确认上桌」大按钮（≥56px），点击后该行消失
 *   - 顶部数字角标：当前等叫数量
 *   - WebSocket 实时推送更新（task_called / task_served 事件）
 *
 * Store-KDS 终端规范：
 *   - 深色主题（背景 #0A0A0A）
 *   - 所有点击区域 ≥ 48×48px，关键操作 ≥ 56px
 *   - 最小字体 ≥ 16px
 *   - 触控反馈：按下 scale(0.97) + 200ms transition
 */
import { useState, useEffect, useRef, useCallback } from 'react';

// ─── 配置（从 localStorage 读取） ───

function getConfig() {
  try {
    return {
      host: localStorage.getItem('kds_mac_host') || '',
      storeId: localStorage.getItem('kds_store_id') || '',
      tenantId: localStorage.getItem('kds_tenant_id') || '',
    };
  } catch {
    return { host: '', storeId: '', tenantId: '' };
  }
}

// ─── Types ───

interface CallingTask {
  task_id: string;
  status: 'calling';
  dept_id: string | null;
  dept_name?: string;
  order_item_id: string;
  table_number?: string;
  dish_name?: string;
  floor_area?: string;   // 楼层/区域（可选，由后端扩展提供）
  called_at: string;     // ISO 字符串
  call_count: number;
}

type WaitLevel = 'normal' | 'warning' | 'danger';

// ─── 等待时间工具 ───

function waitMinutes(calledAt: string): number {
  return Math.floor((Date.now() - new Date(calledAt).getTime()) / 60000);
}

function getWaitLevel(calledAt: string): WaitLevel {
  const m = waitMinutes(calledAt);
  if (m >= 10) return 'danger';
  if (m >= 5)  return 'warning';
  return 'normal';
}

function formatWaitTime(calledAt: string): string {
  const total = Math.floor((Date.now() - new Date(calledAt).getTime()) / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

const WAIT_COLORS: Record<WaitLevel, { text: string; border: string; bg: string; badge: string }> = {
  normal:  { text: '#B0B0B0', border: '#333',    bg: '#111',    badge: '#222' },
  warning: { text: '#E0A020', border: '#BA7517', bg: '#1a1000', badge: '#BA7517' },
  danger:  { text: '#ff4d4f', border: '#A32D2D', bg: '#1a0505', badge: '#A32D2D' },
};

// ─── API ───

async function apiFetchCallingQueue(
  host: string,
  storeId: string,
  tenantId: string,
): Promise<CallingTask[]> {
  try {
    const resp = await fetch(
      `http://${host}/api/v1/kds-config/calling/${storeId}`,
      { headers: { 'X-Tenant-ID': tenantId } },
    );
    if (!resp.ok) return [];
    const data = await resp.json();
    return data?.data?.items ?? [];
  } catch {
    return [];
  }
}

async function apiConfirmServed(
  taskId: string,
  host: string,
  tenantId: string,
): Promise<boolean> {
  try {
    const resp = await fetch(
      `http://${host}/api/v1/kds-config/task/${taskId}/serve`,
      {
        method: 'POST',
        headers: {
          'X-Tenant-ID': tenantId,
          'Content-Type': 'application/json',
        },
      },
    );
    return resp.ok;
  } catch {
    return false;
  }
}

async function apiFetchStats(
  host: string,
  storeId: string,
  tenantId: string,
): Promise<{ calling_count: number; avg_waiting_minutes: number } | null> {
  try {
    const resp = await fetch(
      `http://${host}/api/v1/kds-config/calling/${storeId}/stats`,
      { headers: { 'X-Tenant-ID': tenantId } },
    );
    if (!resp.ok) return null;
    const data = await resp.json();
    return data?.data ?? null;
  } catch {
    return null;
  }
}

// ─── WebSocket Hook ───

function useCallingWebSocket(
  host: string,
  storeId: string,
  onTaskCalled: (task: CallingTask) => void,
  onTaskServed: (taskId: string) => void,
): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!host || !storeId || !mountedRef.current) return;

    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close();
      }
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let ws: WebSocket;
    try {
      ws = new WebSocket(
        `${protocol}//${host}/ws/kds/store/${encodeURIComponent(storeId)}`,
      );
    } catch {
      scheduleRetry();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      retryRef.current = 0;
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      if (event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data as string);

        if (msg.type === 'task_called' && msg.task_id) {
          onTaskCalled({
            task_id: msg.task_id,
            status: 'calling',
            dept_id: msg.dept_id ?? null,
            dept_name: msg.dept_name,
            order_item_id: msg.order_item_id ?? '',
            table_number: msg.table_number,
            dish_name: msg.dish_name,
            floor_area: msg.floor_area,
            called_at: msg.called_at ?? new Date().toISOString(),
            call_count: msg.call_count ?? 1,
          });
        } else if (msg.type === 'task_served' && msg.task_id) {
          onTaskServed(msg.task_id as string);
        }
      } catch {
        // 忽略非法消息
      }
    };

    ws.onerror = () => {
      // 错误将触发 onclose
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      scheduleRetry();
    };

    function scheduleRetry() {
      if (!mountedRef.current) return;
      const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30_000);
      retryRef.current += 1;
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    }
  }, [host, storeId, onTaskCalled, onTaskServed]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { connected };
}

// ─── 主组件 ───

export function CallingQueue() {
  const config = getConfig();
  const [tasks, setTasks] = useState<CallingTask[]>([]);
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const [tick, setTick] = useState(0);
  const [avgWait, setAvgWait] = useState<number | null>(null);

  // 每秒刷新等待时间显示
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // 初始拉取 + 每 30 秒轮询
  const fetchQueue = useCallback(async () => {
    if (!config.host || !config.storeId || !config.tenantId) return;
    const [items, stats] = await Promise.all([
      apiFetchCallingQueue(config.host, config.storeId, config.tenantId),
      apiFetchStats(config.host, config.storeId, config.tenantId),
    ]);
    setTasks(items);
    if (stats) setAvgWait(stats.avg_waiting_minutes);
  }, [config.host, config.storeId, config.tenantId]);

  useEffect(() => {
    fetchQueue();
    const timer = setInterval(fetchQueue, 30_000);
    return () => clearInterval(timer);
  }, [fetchQueue]);

  // WebSocket 实时推送
  const handleTaskCalled = useCallback((task: CallingTask) => {
    setTasks(prev => {
      if (prev.some(t => t.task_id === task.task_id)) return prev;
      return [task, ...prev];
    });
  }, []);

  const handleTaskServed = useCallback((taskId: string) => {
    setTasks(prev => prev.filter(t => t.task_id !== taskId));
  }, []);

  const { connected } = useCallingWebSocket(
    config.host,
    config.storeId,
    handleTaskCalled,
    handleTaskServed,
  );

  // 确认上桌
  const handleServe = useCallback(async (taskId: string) => {
    if (loadingIds.has(taskId)) return;
    setLoadingIds(prev => new Set(prev).add(taskId));
    const ok = await apiConfirmServed(taskId, config.host, config.tenantId);
    if (ok) {
      setTasks(prev => prev.filter(t => t.task_id !== taskId));
    }
    setLoadingIds(prev => {
      const next = new Set(prev);
      next.delete(taskId);
      return next;
    });
  }, [loadingIds, config]);

  const noConfig = !config.host || !config.storeId || !config.tenantId;
  // 等待最久的排最前（called_at 升序）
  const sortedTasks = [...tasks].sort(
    (a, b) => new Date(a.called_at).getTime() - new Date(b.called_at).getTime(),
  );

  void tick; // suppress unused warning — triggers re-render for time display

  return (
    <div style={{
      background: '#0A0A0A',
      color: '#E0E0E0',
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
    }}>
      <style>{ANIMATIONS_CSS}</style>

      {/* ── 顶栏 ── */}
      <header style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 20px',
        background: '#111',
        borderBottom: '1px solid #222',
        minHeight: 64,
        flexShrink: 0,
      }}>
        {/* 左：标题 + 连接状态 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontSize: 26, fontWeight: 'bold', color: '#FF6B35' }}>
            等叫队列
          </span>

          {/* 数字角标：当前等叫数量 */}
          {tasks.length > 0 && (
            <span style={{
              background: tasks.some(t => getWaitLevel(t.called_at) === 'danger')
                ? '#A32D2D'
                : tasks.some(t => getWaitLevel(t.called_at) === 'warning')
                  ? '#BA7517'
                  : '#333',
              color: '#fff',
              fontWeight: 'bold',
              fontSize: 22,
              minWidth: 36,
              height: 36,
              borderRadius: 18,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 10px',
              fontFamily: 'JetBrains Mono, monospace',
            }}>
              {tasks.length}
            </span>
          )}

          {config.host && (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontSize: 16, color: connected ? '#0F6E56' : '#A32D2D',
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%',
                background: connected ? '#0F6E56' : '#A32D2D',
                display: 'inline-block',
                animation: connected ? undefined : 'calling-pulse 1.5s infinite',
              }} />
              {connected ? '已连接' : '断开重连中'}
            </span>
          )}

          {noConfig && (
            <span style={{ fontSize: 16, color: '#BA7517' }}>
              未配置（请设置 Mac mini 地址/门店/租户）
            </span>
          )}
        </div>

        {/* 右：平均等待时间 */}
        {avgWait !== null && tasks.length > 0 && (
          <div style={{ fontSize: 18, color: '#888' }}>
            平均等待{' '}
            <b style={{
              fontSize: 24,
              color: avgWait >= 10 ? '#ff4d4f' : avgWait >= 5 ? '#BA7517' : '#0F6E56',
              fontFamily: 'JetBrains Mono, monospace',
            }}>
              {avgWait.toFixed(1)}
            </b>
            {' '}分钟
          </div>
        )}
      </header>

      {/* ── 列表主体 ── */}
      <main style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        WebkitOverflowScrolling: 'touch',
      }}>
        {noConfig ? (
          <ConfigHint />
        ) : sortedTasks.length === 0 ? (
          <EmptyState />
        ) : (
          sortedTasks.map(task => (
            <CallingTaskCard
              key={task.task_id}
              task={task}
              loading={loadingIds.has(task.task_id)}
              onServe={handleServe}
            />
          ))
        )}
      </main>
    </div>
  );
}

// ─── 任务卡片 ───

function CallingTaskCard({
  task,
  loading,
  onServe,
}: {
  task: CallingTask;
  loading: boolean;
  onServe: (taskId: string) => void;
}) {
  const level = getWaitLevel(task.called_at);
  const colors = WAIT_COLORS[level];
  const isOverWarn = level === 'warning';
  const isDanger = level === 'danger';

  return (
    <div style={{
      background: colors.bg,
      borderRadius: 12,
      padding: '16px 20px',
      borderLeft: `6px solid ${colors.border}`,
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      animation: isDanger ? 'calling-border-flash 1.5s infinite' : undefined,
    }}>
      {/* 等待时间色块 */}
      <div style={{
        flexShrink: 0,
        minWidth: 80,
        textAlign: 'center',
        background: colors.badge,
        borderRadius: 8,
        padding: '8px 12px',
      }}>
        <div style={{
          fontSize: 22,
          fontWeight: 'bold',
          color: colors.text,
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          {formatWaitTime(task.called_at)}
        </div>
        <div style={{ fontSize: 14, color: '#888', marginTop: 2 }}>
          {isDanger ? '超时!' : isOverWarn ? '较久' : '等叫'}
        </div>
      </div>

      {/* 任务信息 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* 桌号 */}
        {task.table_number && (
          <div style={{
            fontSize: 28,
            fontWeight: 'bold',
            color: '#fff',
            lineHeight: 1.2,
          }}>
            {task.table_number} 桌
          </div>
        )}

        {/* 菜品名 */}
        {task.dish_name && (
          <div style={{
            fontSize: 20,
            color: '#E0E0E0',
            marginTop: 4,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {task.dish_name}
          </div>
        )}

        {/* 楼层/区域 */}
        {task.floor_area && (
          <div style={{ fontSize: 16, color: '#666', marginTop: 4 }}>
            {task.floor_area}
          </div>
        )}

        {/* 档口 */}
        {task.dept_name && (
          <div style={{ fontSize: 16, color: '#555', marginTop: 2 }}>
            档口：{task.dept_name}
          </div>
        )}
      </div>

      {/* 确认上桌按钮 */}
      <button
        onClick={() => onServe(task.task_id)}
        disabled={loading}
        style={{
          flexShrink: 0,
          minWidth: 110,
          minHeight: 56,
          padding: '0 20px',
          background: loading ? '#333' : '#0F6E56',
          color: '#fff',
          border: 'none',
          borderRadius: 10,
          fontSize: 18,
          fontWeight: 'bold',
          cursor: loading ? 'not-allowed' : 'pointer',
          transition: 'transform 200ms ease',
          opacity: loading ? 0.6 : 1,
          lineHeight: 1.3,
        }}
        onTouchStart={e => {
          if (!loading) e.currentTarget.style.transform = 'scale(0.97)';
        }}
        onTouchEnd={e => {
          e.currentTarget.style.transform = 'scale(1)';
        }}
      >
        {loading ? '处理中...' : '确认上桌'}
      </button>
    </div>
  );
}

// ─── 空状态 ───

function EmptyState() {
  return (
    <div style={{
      textAlign: 'center',
      color: '#444',
      fontSize: 20,
      marginTop: 80,
      lineHeight: 2,
    }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>🍽</div>
      <div>暂无等叫菜品</div>
      <div style={{ fontSize: 16, color: '#333', marginTop: 8 }}>
        厨师出菜后将在此处显示
      </div>
    </div>
  );
}

// ─── 未配置提示 ───

function ConfigHint() {
  return (
    <div style={{
      textAlign: 'center',
      color: '#BA7517',
      fontSize: 18,
      marginTop: 80,
      lineHeight: 2,
    }}>
      <div>请先在配置页设置：</div>
      <div style={{ fontSize: 16, color: '#555', marginTop: 8 }}>
        Mac mini 地址 / 门店 ID / 租户 ID
      </div>
      <div style={{ fontSize: 14, color: '#444', marginTop: 4 }}>
        （存储在 localStorage：kds_mac_host / kds_store_id / kds_tenant_id）
      </div>
    </div>
  );
}

// ─── 动画 CSS ───

const ANIMATIONS_CSS = `
  @keyframes calling-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
  @keyframes calling-border-flash {
    0%, 100% { border-color: #A32D2D; }
    50% { border-color: #ff4d4f; }
  }
`;
