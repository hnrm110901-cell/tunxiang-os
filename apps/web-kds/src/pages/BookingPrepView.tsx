/**
 * BookingPrepView — 预订备餐视图（Store 终端 KDS 屏）
 *
 * 布局:
 *   顶部看板: 今日/本周预订数（大数字卡片）
 *   菜品需求列表 TOP10: 菜名 + 数量 + 进度条（已备/需备）
 *   备餐任务卡片: 预订时间 / 就餐时间 / 桌台 / 菜品清单 / 操作按钮 / 倒计时
 *   Tab切换: 预备任务 | 已完成
 *   按档口过滤下拉
 *
 * 深色主题，所有按钮 ≥56px，字体 ≥16px
 */
import { useState, useEffect, useCallback } from 'react';

// ─── 类型定义 ───

interface DishSummary {
  dish_name: string;
  total_qty: number;
  booking_count: number;
}

interface TodaySummary {
  today_count: number;
  week_count: number;
  top_dishes: DishSummary[];
}

interface PrepTask {
  id: string;
  booking_id: string;
  store_id: string;
  dish_id: string;
  dish_name: string;
  quantity: number;
  dept_id: string;
  prep_start_at: string | null;
  status: 'pending' | 'started' | 'done';
  created_at: string;
  // 前端附加字段（从预订数据填充）
  table_no?: string;
  dining_at?: string; // ISO8601
  booking_time?: string;
}

// ─── 档口配置 ───

const DEPT_OPTIONS = [
  { id: 'all',    label: '全部档口' },
  { id: 'wok',    label: '炒锅' },
  { id: 'roast',  label: '烤制' },
  { id: 'steam',  label: '蒸制' },
  { id: 'cold',   label: '切配' },
  { id: 'stew',   label: '炖煨' },
  { id: 'soup',   label: '汤锅' },
  { id: 'hotpot', label: '火锅' },
];

// ─── 配置读取 ───

function getApiBase(): string {
  return localStorage.getItem('kds_mac_host') || '';
}

function getTenantId(): string {
  return localStorage.getItem('kds_tenant_id') || '';
}

function getStoreId(): string {
  return localStorage.getItem('kds_store_id') || '';
}

// ─── API 工具 ───

async function apiGet<T>(path: string): Promise<T | null> {
  const base = getApiBase();
  const tenantId = getTenantId();
  if (!base || !tenantId) return null;
  try {
    const res = await fetch(`${base}${path}`, {
      headers: { 'X-Tenant-ID': tenantId },
    });
    if (!res.ok) return null;
    const json = await res.json();
    return json.ok ? (json.data as T) : null;
  } catch {
    return null;
  }
}

async function apiPost<T>(path: string): Promise<T | null> {
  const base = getApiBase();
  const tenantId = getTenantId();
  if (!base || !tenantId) return null;
  try {
    const res = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'X-Tenant-ID': tenantId, 'Content-Type': 'application/json' },
    });
    if (!res.ok) return null;
    const json = await res.json();
    return json.ok ? (json.data as T) : null;
  } catch {
    return null;
  }
}

// ─── 倒计时工具 ───

function getCountdown(diningAt: string | undefined): { text: string; isUrgent: boolean } {
  if (!diningAt) return { text: '—', isUrgent: false };
  const diff = new Date(diningAt).getTime() - Date.now();
  if (diff <= 0) return { text: '已到时间', isUrgent: true };
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  const isUrgent = diff < 2 * 3600000; // <2小时变红
  const text = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}分钟`;
  return { text, isUrgent };
}

function formatTime(iso: string | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

// ─── 空初始状态 ───

const EMPTY_SUMMARY: TodaySummary = {
  today_count: 0,
  week_count: 0,
  top_dishes: [],
};

// ─── 主组件 ───

export function BookingPrepView() {
  const storeId = getStoreId();
  const isOffline = !getApiBase() || !getTenantId();

  const [summary, setSummary] = useState<TodaySummary>(EMPTY_SUMMARY);
  const [allTasks, setAllTasks] = useState<PrepTask[]>([]);
  const [tab, setTab] = useState<'pending' | 'done'>('pending');
  const [deptFilter, setDeptFilter] = useState<string>('all');
  const [tick, setTick] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 每秒刷新倒计时
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // 轮询数据（每30秒）
  const fetchData = useCallback(async () => {
    if (isOffline) {
      setLoading(false);
      setError('未配置 Mac mini 地址或租户信息');
      return;
    }
    setLoading(true);
    try {
      const [s, t] = await Promise.all([
        apiGet<TodaySummary>(`/api/v1/booking-prep/today-summary/${storeId}`),
        apiGet<{ items: PrepTask[] }>(`/api/v1/booking-prep/pending/${storeId}`),
      ]);
      if (s) setSummary(s);
      if (t) setAllTasks(t.items);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [isOffline, storeId]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 30000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // 操作处理
  const handleStart = useCallback(async (taskId: string) => {
    if (isOffline) return;
    const result = await apiPost<PrepTask>(`/api/v1/booking-prep/task/${taskId}/start`);
    if (result) {
      setAllTasks(prev => prev.map(t => t.id === taskId ? { ...t, ...result } : t));
    }
  }, [isOffline]);

  const handleDone = useCallback(async (taskId: string) => {
    if (isOffline) return;
    const result = await apiPost<PrepTask>(`/api/v1/booking-prep/task/${taskId}/done`);
    if (result) {
      setAllTasks(prev => prev.map(t => t.id === taskId ? { ...t, ...result } : t));
    }
  }, [isOffline]);

  // 过滤逻辑
  const pendingTasks = allTasks.filter(t =>
    (t.status === 'pending' || t.status === 'started') &&
    (deptFilter === 'all' || t.dept_id === deptFilter)
  );
  const doneTasks = allTasks.filter(t =>
    t.status === 'done' &&
    (deptFilter === 'all' || t.dept_id === deptFilter)
  );
  const displayTasks = tab === 'pending' ? pendingTasks : doneTasks;

  // 每桌任务分组（按 booking_id）
  const taskGroups = displayTasks.reduce<Record<string, PrepTask[]>>((acc, t) => {
    const key = t.booking_id;
    if (!acc[key]) acc[key] = [];
    acc[key].push(t);
    return acc;
  }, {});

  const maxDishQty = summary.top_dishes[0]?.total_qty || 1;

  return (
    <div style={{
      background: '#0A0A0A', color: '#E0E0E0', minHeight: '100vh',
      display: 'flex', flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      fontSize: 16,
    }}>
      {/* 顶栏 */}
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 20px', background: '#111', borderBottom: '1px solid #222',
        minHeight: 56,
      }}>
        <span style={{ fontWeight: 'bold', fontSize: 24, color: '#FF6B35' }}>预订备餐</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {loading && <span style={{ fontSize: 16, color: '#666' }}>更新中…</span>}
          {error && (
            <span style={{ fontSize: 16, color: '#A32D2D' }}>{error}</span>
          )}
          {isOffline && (
            <span style={{ fontSize: 16, color: '#BA7517' }}>未连接</span>
          )}
        </div>
      </header>

      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* 统计卡片 */}
        <div style={{
          display: 'flex', gap: 16, padding: '16px 20px',
          borderBottom: '1px solid #1a1a1a',
        }}>
          <StatCard label="今日预订" value={summary.today_count} unit="桌" color="#FF6B35" />
          <StatCard label="本周预订" value={summary.week_count} unit="桌" color="#1890ff" />
        </div>

        {/* 菜品需求 TOP10 */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #1a1a1a' }}>
          <div style={{ fontSize: 18, fontWeight: 'bold', color: '#aaa', marginBottom: 12 }}>
            本周菜品需求 TOP10
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {summary.top_dishes.map((d, i) => {
              const doneQty = allTasks
                .filter(t => t.dish_name === d.dish_name && t.status === 'done')
                .reduce((sum, t) => sum + t.quantity, 0);
              const pct = Math.min((d.total_qty / maxDishQty) * 100, 100);
              const donePct = Math.min((doneQty / d.total_qty) * 100, 100);

              return (
                <div key={d.dish_name} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{
                    width: 24, textAlign: 'center', fontSize: 16,
                    color: i < 3 ? '#FF6B35' : '#555', fontWeight: 'bold',
                  }}>{i + 1}</span>
                  <span style={{ width: 120, fontSize: 18, color: '#ddd', flexShrink: 0 }}>
                    {d.dish_name}
                  </span>
                  {/* 进度条 */}
                  <div style={{
                    flex: 1, height: 20, background: '#222', borderRadius: 10,
                    position: 'relative', overflow: 'hidden',
                  }}>
                    {/* 总需求条 */}
                    <div style={{
                      position: 'absolute', left: 0, top: 0, height: '100%',
                      width: `${pct}%`, background: '#1a3a1a', borderRadius: 10,
                    }} />
                    {/* 已完成条 */}
                    <div style={{
                      position: 'absolute', left: 0, top: 0, height: '100%',
                      width: `${donePct}%`, background: '#0F6E56', borderRadius: 10,
                      transition: 'width 0.4s ease',
                    }} />
                  </div>
                  <span style={{ fontSize: 18, color: '#0F6E56', minWidth: 60, textAlign: 'right' }}>
                    {doneQty}/{d.total_qty}
                  </span>
                  <span style={{ fontSize: 16, color: '#555', minWidth: 50, textAlign: 'right' }}>
                    {d.booking_count}桌
                  </span>
                </div>
              );
            })}
            {summary.top_dishes.length === 0 && (
              <div style={{ color: '#444', fontSize: 16, textAlign: 'center', padding: 16 }}>
                本周暂无预订菜品数据
              </div>
            )}
          </div>
        </div>

        {/* 控制栏：Tab + 档口过滤 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 20px', background: '#111', position: 'sticky', top: 0, zIndex: 10,
          borderBottom: '1px solid #222',
        }}>
          {/* Tab */}
          <div style={{ display: 'flex', gap: 8 }}>
            <TabButton label={`预备任务 (${pendingTasks.length})`} active={tab === 'pending'} onClick={() => setTab('pending')} color="#BA7517" />
            <TabButton label={`已完成 (${doneTasks.length})`} active={tab === 'done'} onClick={() => setTab('done')} color="#0F6E56" />
          </div>

          {/* 档口过滤 */}
          <select
            value={deptFilter}
            onChange={e => setDeptFilter(e.target.value)}
            style={{
              background: '#222', color: '#ddd', border: '1px solid #333',
              borderRadius: 8, padding: '8px 12px', fontSize: 16,
              minHeight: 48, cursor: 'pointer',
            }}
          >
            {DEPT_OPTIONS.map(d => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
        </div>

        {/* 备餐任务卡片列表（按预订分组） */}
        <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {Object.entries(taskGroups).map(([bookingId, tasks]) => (
            <BookingTaskGroup
              key={bookingId}
              bookingId={bookingId}
              tasks={tasks}
              tab={tab}
              tick={tick}
              onStart={handleStart}
              onDone={handleDone}
            />
          ))}
          {Object.keys(taskGroups).length === 0 && (
            <div style={{ color: '#444', fontSize: 18, textAlign: 'center', padding: 40 }}>
              {tab === 'pending' ? '暂无待备餐任务' : '暂无已完成任务'}
            </div>
          )}
        </div>
      </div>

      {/* 动画 CSS */}
      <style>{`
        @keyframes bp-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
        @keyframes bp-urgent-flash {
          0%, 100% { border-color: #A32D2D; }
          50% { border-color: #ff4d4f; }
        }
      `}</style>
    </div>
  );
}

// ─── 统计卡片 ───

function StatCard({ label, value, unit, color }: {
  label: string; value: number; unit: string; color: string;
}) {
  return (
    <div style={{
      flex: 1, background: '#111', borderRadius: 12, padding: '16px 20px',
      border: `1px solid #222`, textAlign: 'center',
    }}>
      <div style={{ fontSize: 16, color: '#888', marginBottom: 6 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 4 }}>
        <span style={{
          fontSize: 52, fontWeight: 'bold', color,
          fontFamily: 'JetBrains Mono, "SF Mono", monospace',
          lineHeight: 1.1,
        }}>{value}</span>
        <span style={{ fontSize: 20, color: '#888' }}>{unit}</span>
      </div>
    </div>
  );
}

// ─── Tab 按钮 ───

function TabButton({ label, active, onClick, color }: {
  label: string; active: boolean; onClick: () => void; color: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '10px 20px', minHeight: 48, fontSize: 17,
        fontWeight: active ? 'bold' : 'normal',
        color: active ? '#fff' : '#888',
        background: active ? color : '#222',
        border: 'none', borderRadius: 8, cursor: 'pointer',
        transition: 'all 200ms ease',
      }}
      onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
      onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
    >
      {label}
    </button>
  );
}

// ─── 预订任务分组卡片 ───

function BookingTaskGroup({ bookingId, tasks, tab, tick: _tick, onStart, onDone }: {
  bookingId: string;
  tasks: PrepTask[];
  tab: 'pending' | 'done';
  tick: number;
  onStart: (id: string) => void;
  onDone: (id: string) => void;
}) {
  const firstTask = tasks[0];
  const { text: countdown, isUrgent } = getCountdown(firstTask.dining_at);
  const allStarted = tasks.every(t => t.status === 'started' || t.status === 'done');
  const allDone = tasks.every(t => t.status === 'done');

  return (
    <div style={{
      background: '#111', borderRadius: 14,
      border: isUrgent && tab === 'pending'
        ? '2px solid #A32D2D'
        : '1px solid #222',
      overflow: 'hidden',
      animation: isUrgent && tab === 'pending' ? 'bp-urgent-flash 1.5s infinite' : undefined,
    }}>
      {/* 卡片头部 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 16px', background: '#161616', borderBottom: '1px solid #222',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 22, fontWeight: 'bold', color: '#fff' }}>
            {firstTask.table_no || bookingId.slice(-6)}
          </span>
          {firstTask.dining_at && (
            <span style={{ fontSize: 16, color: '#888' }}>
              就餐 {formatTime(firstTask.dining_at)}
            </span>
          )}
          {firstTask.booking_time && (
            <span style={{ fontSize: 16, color: '#555' }}>
              预订 {formatTime(firstTask.booking_time)}
            </span>
          )}
        </div>
        {/* 倒计时 */}
        <div style={{
          fontSize: 22, fontWeight: 'bold',
          color: isUrgent ? '#ff4d4f' : '#aaa',
          fontFamily: 'JetBrains Mono, monospace',
          animation: isUrgent ? 'bp-pulse 1s infinite' : undefined,
        }}>
          {tab === 'pending' ? countdown : '已完成'}
        </div>
      </div>

      {/* 菜品清单 */}
      <div style={{ padding: '12px 16px' }}>
        {tasks.map(task => (
          <DishRow key={task.id} task={task} />
        ))}
      </div>

      {/* 操作按钮（仅待处理 tab 显示） */}
      {tab === 'pending' && (
        <div style={{
          padding: '0 16px 14px',
          display: 'flex', gap: 10,
        }}>
          {!allStarted && (
            <ActionButton
              label="开始备餐"
              color="#1890ff"
              onClick={() => {
                tasks
                  .filter(t => t.status === 'pending')
                  .forEach(t => onStart(t.id));
              }}
            />
          )}
          {allStarted && !allDone && (
            <ActionButton
              label="完成备餐"
              color="#0F6E56"
              onClick={() => {
                tasks
                  .filter(t => t.status === 'started')
                  .forEach(t => onDone(t.id));
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}

// ─── 菜品行 ───

function DishRow({ task }: { task: PrepTask }) {
  const statusColor: Record<string, string> = {
    pending: '#BA7517',
    started: '#1890ff',
    done: '#0F6E56',
  };
  const statusLabel: Record<string, string> = {
    pending: '待备',
    started: '备餐中',
    done: '已备',
  };

  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '8px 0', borderBottom: '1px solid #1a1a1a',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          fontSize: 16, padding: '3px 10px', borderRadius: 6,
          background: statusColor[task.status] + '22',
          color: statusColor[task.status],
          fontWeight: 'bold', minWidth: 60, textAlign: 'center',
        }}>
          {statusLabel[task.status]}
        </span>
        <span style={{ fontSize: 20, color: '#ddd', fontWeight: 'bold' }}>
          {task.dish_name}
        </span>
        <span style={{ fontSize: 16, color: '#555' }}>
          {DEPT_OPTIONS.find(d => d.id === task.dept_id)?.label || task.dept_id}
        </span>
      </div>
      <span style={{
        fontSize: 22, fontWeight: 'bold', color: '#FF6B35',
        fontFamily: 'JetBrains Mono, monospace',
      }}>
        ×{task.quantity}
      </span>
    </div>
  );
}

// ─── 操作按钮 ───

function ActionButton({ label, color, onClick }: {
  label: string; color: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1, padding: '16px 0', minHeight: 56, fontSize: 20,
        fontWeight: 'bold', color: '#fff', background: color,
        border: 'none', borderRadius: 10, cursor: 'pointer',
        transition: 'transform 200ms ease',
      }}
      onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
      onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
    >
      {label}
    </button>
  );
}
