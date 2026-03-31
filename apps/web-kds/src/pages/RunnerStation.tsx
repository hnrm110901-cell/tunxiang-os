/**
 * RunnerStation — 传菜员工作站
 *
 * 功能：
 *   - 按桌号聚合展示所有 ready 状态菜品
 *   - 每道菜显示：菜名、桌号、等待时间（出品后等待传菜的时间）
 *   - "领取"按钮 → delivering 状态
 *   - "已送达"按钮 → served 状态
 *   - 等待 >3 分钟变黄，>5 分钟变红
 *   - WebSocket 实时接收新的 ready 菜品
 *
 * Store-KDS 终端规范（store.md）：
 *   - 深色主题（背景 #0A0A0A）
 *   - 所有点击区域 ≥ 48×48px（关键操作 ≥ 72px）
 *   - 最小字体 ≥ 16px
 *   - 触控反馈：按下 scale(0.97) + 200ms transition
 *   - 不使用 Ant Design / hover-only 反馈
 */
import { useState, useEffect, useRef, useCallback } from 'react';

// ─── 配置（从 localStorage 读取） ───

function getConfig() {
  try {
    return {
      host: localStorage.getItem('kds_mac_host') || '',
      storeId: localStorage.getItem('runner_store_id') || '',
      tenantId: localStorage.getItem('runner_tenant_id') || '',
      soundEnabled: localStorage.getItem('kds_sound') !== 'off',
    };
  } catch {
    return { host: '', storeId: '', tenantId: '', soundEnabled: true };
  }
}

// ─── Types ───

interface RunnerDish {
  task_id: string;
  dish_name: string;
  table_number: string;
  order_id: string;
  status: 'ready' | 'delivering' | 'served';
  ready_at: string;    // ISO 字符串
  pickup_at?: string;
  runner_id?: string;
}

// 按桌号聚合的结构
interface TableGroup {
  table_number: string;
  dishes: RunnerDish[];
  earliest_ready_at: number;  // ms timestamp，用于排序
}

type WaitLevel = 'normal' | 'warning' | 'danger';

// ─── 等待时间计算 ───

function waitMinutes(readyAt: string): number {
  return Math.floor((Date.now() - new Date(readyAt).getTime()) / 60000);
}

function getWaitLevel(readyAt: string): WaitLevel {
  const m = waitMinutes(readyAt);
  if (m >= 5) return 'danger';
  if (m >= 3) return 'warning';
  return 'normal';
}

function formatWaitTime(readyAt: string): string {
  const total = Math.floor((Date.now() - new Date(readyAt).getTime()) / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

const WAIT_COLORS: Record<WaitLevel, { text: string; border: string; bg: string }> = {
  normal:  { text: '#0F6E56', border: '#0F6E56', bg: '#001a0d' },
  warning: { text: '#BA7517', border: '#BA7517', bg: '#1a1000' },
  danger:  { text: '#ff4d4f', border: '#A32D2D', bg: '#1a0505' },
};

// ─── API 调用 ───

async function apiPickup(taskId: string, host: string, storeId: string, tenantId: string): Promise<boolean> {
  try {
    const resp = await fetch(
      `http://${host}/api/v1/runner/task/${taskId}/pickup`,
      {
        method: 'POST',
        headers: {
          'X-Tenant-ID': tenantId,
          'X-Operator-ID': storeId || 'runner',
          'Content-Type': 'application/json',
        },
      },
    );
    return resp.ok;
  } catch {
    return false;
  }
}

async function apiServed(taskId: string, host: string, storeId: string, tenantId: string): Promise<boolean> {
  try {
    const resp = await fetch(
      `http://${host}/api/v1/runner/task/${taskId}/served`,
      {
        method: 'POST',
        headers: {
          'X-Tenant-ID': tenantId,
          'X-Operator-ID': storeId || 'runner',
          'Content-Type': 'application/json',
        },
      },
    );
    return resp.ok;
  } catch {
    return false;
  }
}

async function apiFetchQueue(host: string, storeId: string, tenantId: string): Promise<RunnerDish[]> {
  try {
    const resp = await fetch(
      `http://${host}/api/v1/runner/${storeId}/queue`,
      { headers: { 'X-Tenant-ID': tenantId } },
    );
    if (!resp.ok) return [];
    const data = await resp.json();
    return data?.data?.items ?? [];
  } catch {
    return [];
  }
}

// ─── 按桌号聚合 ───

function groupByTable(dishes: RunnerDish[]): TableGroup[] {
  const map = new Map<string, RunnerDish[]>();
  for (const d of dishes) {
    if (!map.has(d.table_number)) map.set(d.table_number, []);
    map.get(d.table_number)!.push(d);
  }
  const groups: TableGroup[] = [];
  for (const [table_number, items] of map.entries()) {
    groups.push({
      table_number,
      dishes: items,
      earliest_ready_at: Math.min(
        ...items.map(i => new Date(i.ready_at).getTime()),
      ),
    });
  }
  // 等待最久的桌优先
  groups.sort((a, b) => a.earliest_ready_at - b.earliest_ready_at);
  return groups;
}

// ─── WebSocket Hook ───

function useRunnerWebSocket(
  host: string,
  storeId: string,
  onNewDish: (dish: RunnerDish) => void,
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
      ws = new WebSocket(`${protocol}//${host}/ws/runner/${encodeURIComponent(storeId)}`);
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
        const msg = JSON.parse(event.data);
        if (msg.type === 'dish_ready' && msg.task_id) {
          onNewDish({
            task_id: msg.task_id,
            dish_name: msg.dish_name || '未知菜品',
            table_number: msg.table_number || '',
            order_id: msg.order_id || '',
            status: 'ready',
            ready_at: msg.ready_at || new Date().toISOString(),
          });
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
  }, [host, storeId, onNewDish]);

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

export function RunnerStation() {
  const config = getConfig();
  const [dishes, setDishes] = useState<RunnerDish[]>([]);
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const [tick, setTick] = useState(0);
  const [lastFetch, setLastFetch] = useState(0);

  // 每秒刷新等待时间显示
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // 初始拉取队列 + 每 30 秒轮询补偿
  const fetchQueue = useCallback(async () => {
    if (!config.host || !config.storeId || !config.tenantId) return;
    const items = await apiFetchQueue(config.host, config.storeId, config.tenantId);
    setDishes(items);
    setLastFetch(Date.now());
  }, [config.host, config.storeId, config.tenantId]);

  useEffect(() => {
    fetchQueue();
    const timer = setInterval(fetchQueue, 30_000);
    return () => clearInterval(timer);
  }, [fetchQueue]);

  // WebSocket 实时接收新 ready 菜品
  const handleNewDish = useCallback((dish: RunnerDish) => {
    setDishes(prev => {
      if (prev.some(d => d.task_id === dish.task_id)) return prev;
      return [dish, ...prev];
    });
  }, []);

  const { connected } = useRunnerWebSocket(
    config.host,
    config.storeId,
    handleNewDish,
  );

  // 领取
  const handlePickup = useCallback(async (taskId: string) => {
    if (loadingIds.has(taskId)) return;
    setLoadingIds(prev => new Set(prev).add(taskId));
    const ok = await apiPickup(taskId, config.host, config.storeId, config.tenantId);
    if (ok) {
      setDishes(prev =>
        prev.map(d => d.task_id === taskId ? { ...d, status: 'delivering' as const } : d),
      );
    }
    setLoadingIds(prev => {
      const next = new Set(prev);
      next.delete(taskId);
      return next;
    });
  }, [loadingIds, config]);

  // 送达确认
  const handleServed = useCallback(async (taskId: string) => {
    if (loadingIds.has(taskId)) return;
    setLoadingIds(prev => new Set(prev).add(taskId));
    const ok = await apiServed(taskId, config.host, config.storeId, config.tenantId);
    if (ok) {
      // 送达后从列表移除
      setDishes(prev => prev.filter(d => d.task_id !== taskId));
    }
    setLoadingIds(prev => {
      const next = new Set(prev);
      next.delete(taskId);
      return next;
    });
  }, [loadingIds, config]);

  const readyDishes = dishes.filter(d => d.status === 'ready');
  const deliveringDishes = dishes.filter(d => d.status === 'delivering');
  const readyGroups = groupByTable(readyDishes);

  const noConfig = !config.host || !config.storeId || !config.tenantId;

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

      {/* 顶栏 */}
      <header style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 20px',
        background: '#111',
        borderBottom: '1px solid #222',
        minHeight: 60,
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontSize: 26, fontWeight: 'bold', color: '#FF6B35' }}>
            传菜站
          </span>
          {config.host && (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontSize: 16, color: connected ? '#0F6E56' : '#A32D2D',
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%',
                background: connected ? '#0F6E56' : '#A32D2D',
                display: 'inline-block',
                animation: connected ? undefined : 'runner-pulse 1.5s infinite',
              }} />
              {connected ? '已连接' : '断开'}
            </span>
          )}
          {noConfig && (
            <span style={{ fontSize: 16, color: '#BA7517' }}>
              未配置（请设置 Mac mini 地址/门店/租户）
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, fontSize: 18 }}>
          <span>
            待取菜{' '}
            <b style={{ color: '#BA7517', fontSize: 28, fontFamily: 'JetBrains Mono, monospace' }}>
              {readyDishes.length}
            </b>
          </span>
          <span>
            传菜中{' '}
            <b style={{ color: '#1890ff', fontSize: 28, fontFamily: 'JetBrains Mono, monospace' }}>
              {deliveringDishes.length}
            </b>
          </span>
          {/* 路线优化入口：跳转到服务员端 PWA */}
          <a
            href="/route-optimize"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: 100,
              minHeight: 48,
              padding: '0 18px',
              background: 'rgba(255,107,53,0.15)',
              color: '#FF6B35',
              border: '1px solid #FF6B35',
              borderRadius: 10,
              fontSize: 16,
              fontWeight: 'bold',
              textDecoration: 'none',
              whiteSpace: 'nowrap',
              transition: 'opacity 200ms',
            }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.8')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          >
            路线优化
          </a>
        </div>
      </header>

      {/* 主体：两列布局 */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* 左列：待取菜（ready） */}
        <section style={{
          flex: 3,
          display: 'flex',
          flexDirection: 'column',
          borderRight: '2px solid #222',
          overflow: 'hidden',
        }}>
          <div style={{
            textAlign: 'center',
            padding: '10px 0',
            fontSize: 20,
            fontWeight: 'bold',
            color: '#BA7517',
            borderBottom: '3px solid #BA7517',
            background: '#1a1000',
            flexShrink: 0,
          }}>
            待取菜 ({readyDishes.length})
          </div>
          <div style={{
            flex: 1,
            overflowY: 'auto',
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            WebkitOverflowScrolling: 'touch',
          }}>
            {readyGroups.length === 0 ? (
              <div style={{
                textAlign: 'center',
                color: '#444',
                fontSize: 20,
                marginTop: 60,
              }}>
                暂无待取菜品
              </div>
            ) : (
              readyGroups.map(group => (
                <TableGroupCard
                  key={group.table_number}
                  group={group}
                  tick={tick}
                  loadingIds={loadingIds}
                  onPickup={handlePickup}
                />
              ))
            )}
          </div>
        </section>

        {/* 右列：传菜中（delivering） */}
        <section style={{
          flex: 2,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <div style={{
            textAlign: 'center',
            padding: '10px 0',
            fontSize: 20,
            fontWeight: 'bold',
            color: '#1890ff',
            borderBottom: '3px solid #1890ff',
            background: '#001020',
            flexShrink: 0,
          }}>
            传菜中 ({deliveringDishes.length})
          </div>
          <div style={{
            flex: 1,
            overflowY: 'auto',
            padding: 12,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
            WebkitOverflowScrolling: 'touch',
          }}>
            {deliveringDishes.length === 0 ? (
              <div style={{
                textAlign: 'center',
                color: '#444',
                fontSize: 20,
                marginTop: 60,
              }}>
                无传菜中菜品
              </div>
            ) : (
              deliveringDishes.map(dish => (
                <DeliveringCard
                  key={dish.task_id}
                  dish={dish}
                  tick={tick}
                  loading={loadingIds.has(dish.task_id)}
                  onServed={handleServed}
                />
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

// ─── 桌号分组卡片（ready 状态） ───

function TableGroupCard({ group, tick: _tick, loadingIds, onPickup }: {
  group: TableGroup;
  tick: number;
  loadingIds: Set<string>;
  onPickup: (taskId: string) => void;
}) {
  // 整桌中等待最久的那道菜决定颜色
  const worstLevel = group.dishes.reduce<WaitLevel>((worst, d) => {
    const level = getWaitLevel(d.ready_at);
    if (level === 'danger') return 'danger';
    if (level === 'warning' && worst === 'normal') return 'warning';
    return worst;
  }, 'normal');

  const colors = WAIT_COLORS[worstLevel];

  return (
    <div style={{
      background: colors.bg,
      borderRadius: 12,
      padding: 14,
      borderLeft: `6px solid ${colors.border}`,
      animation: worstLevel === 'danger' ? 'runner-border-flash 1.5s infinite' : undefined,
    }}>
      {/* 桌号标题 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 10,
      }}>
        <span style={{ fontSize: 28, fontWeight: 'bold', color: '#fff' }}>
          {group.table_number} 桌
        </span>
        <span style={{
          fontSize: 16,
          color: colors.text,
          background: 'rgba(0,0,0,0.3)',
          padding: '4px 12px',
          borderRadius: 8,
        }}>
          {group.dishes.length} 道菜
        </span>
      </div>

      {/* 菜品列表 */}
      {group.dishes.map(dish => {
        const level = getWaitLevel(dish.ready_at);
        const dc = WAIT_COLORS[level];
        const isLoading = loadingIds.has(dish.task_id);

        return (
          <div key={dish.task_id} style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '8px 0',
            borderBottom: '1px solid #222',
          }}>
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 20, fontWeight: 'bold', color: '#E0E0E0' }}>
                {dish.dish_name}
              </span>
              <span style={{
                fontSize: 16,
                color: dc.text,
                marginLeft: 12,
                fontFamily: 'JetBrains Mono, monospace',
              }}>
                等待 {formatWaitTime(dish.ready_at)}
                {level === 'warning' && ' ⚠'}
                {level === 'danger' && ' 超时!'}
              </span>
            </div>

            {/* 领取按钮 */}
            <button
              onClick={() => onPickup(dish.task_id)}
              disabled={isLoading}
              style={{
                minWidth: 88,
                minHeight: 56,
                padding: '0 20px',
                background: isLoading ? '#333' : '#1890ff',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                fontSize: 18,
                fontWeight: 'bold',
                cursor: isLoading ? 'not-allowed' : 'pointer',
                transition: 'transform 200ms ease',
                opacity: isLoading ? 0.6 : 1,
              }}
              onTouchStart={e => !isLoading && (e.currentTarget.style.transform = 'scale(0.97)')}
              onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
            >
              {isLoading ? '处理中' : '领取'}
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ─── 传菜中卡片（delivering 状态） ───

function DeliveringCard({ dish, tick: _tick, loading, onServed }: {
  dish: RunnerDish;
  tick: number;
  loading: boolean;
  onServed: (taskId: string) => void;
}) {
  const waitMin = waitMinutes(dish.ready_at);

  return (
    <div style={{
      background: '#001020',
      borderRadius: 12,
      padding: 14,
      borderLeft: '6px solid #1890ff',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: 10,
      }}>
        <div>
          <div style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>
            {dish.table_number} 桌
          </div>
          <div style={{ fontSize: 20, color: '#E0E0E0', marginTop: 4 }}>
            {dish.dish_name}
          </div>
        </div>
        <div style={{
          fontSize: 16,
          color: '#888',
          textAlign: 'right',
        }}>
          <div>等待 {waitMin} 分钟</div>
          {dish.runner_id && (
            <div style={{ fontSize: 16, color: '#666', marginTop: 4 }}>
              传菜员: {dish.runner_id}
            </div>
          )}
        </div>
      </div>

      {/* 送达确认按钮 */}
      <button
        onClick={() => onServed(dish.task_id)}
        disabled={loading}
        style={{
          width: '100%',
          minHeight: 72,
          background: loading ? '#333' : '#0F6E56',
          color: '#fff',
          border: 'none',
          borderRadius: 10,
          fontSize: 22,
          fontWeight: 'bold',
          cursor: loading ? 'not-allowed' : 'pointer',
          transition: 'transform 200ms ease',
          opacity: loading ? 0.6 : 1,
        }}
        onTouchStart={e => !loading && (e.currentTarget.style.transform = 'scale(0.97)')}
        onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
      >
        {loading ? '处理中...' : '已送达'}
      </button>
    </div>
  );
}

// ─── 动画 CSS ───

const ANIMATIONS_CSS = `
  @keyframes runner-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }
  @keyframes runner-border-flash {
    0%, 100% { border-color: #A32D2D; }
    50% { border-color: #ff4d4f; }
  }
`;
