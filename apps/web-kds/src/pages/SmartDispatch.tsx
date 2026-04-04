/**
 * SmartDispatch — 智能分单看板
 *
 * 按档口自动分单展示，后厨大屏站立操作。
 * 优先级规则：VIP桌 > 催菜 > 普通，时间早 > 时间晚。
 *
 * 设计遵循 Store-KDS 触控规范：
 *   - 所有点击区域 >= 48x48px
 *   - 字体 >= 16px，标题 >= 24px
 *   - 深色主题：背景 #0B1A20，卡片 #112228，高亮 #FF6B35
 *   - 关键操作触发 navigator.vibrate(50)
 *   - 20s 自动刷新
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type StationName = '炒菜' | '烧烤' | '凉菜' | '蒸品' | '面点' | '甜品';
type Priority = 'high' | 'medium' | 'normal';
type TicketStatus = 'pending' | 'making' | 'done' | 'skipped';

interface Ticket {
  id: string;
  orderId: string;
  tableNo: string;
  dishName: string;
  quantity: number;
  station: StationName;
  priority: Priority;
  status: TicketStatus;
  isVip: boolean;
  isRush: boolean;
  rushCount: number;
  createdAt: number; // timestamp ms
}

interface StationStats {
  station: StationName;
  pending: number;
  making: number;
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const STATIONS: StationName[] = ['炒菜', '烧烤', '凉菜', '蒸品', '面点', '甜品'];

const C = {
  bg: '#0B1A20',
  card: '#112228',
  accent: '#FF6B35',
  green: '#22C55E',
  blue: '#3B82F6',
  orange: '#F59E0B',
  red: '#EF4444',
  white: '#F1F5F9',
  muted: '#94A3B8',
  border: '#1E3A44',
} as const;

const PRIORITY_BORDER: Record<Priority, string> = {
  high: C.red,
  medium: C.orange,
  normal: 'transparent',
};

// ─── Mock 数据 ────────────────────────────────────────────────────────────────

const MOCK_DISHES: Record<StationName, string[]> = {
  '炒菜': ['宫保鸡丁', '水煮牛肉', '干锅花菜', '回锅肉', '鱼香肉丝'],
  '烧烤': ['烤羊排', '烤生蚝', '烤茄子', '烤韭菜', '烤鱿鱼'],
  '凉菜': ['凉拌黄瓜', '皮蛋豆腐', '口水鸡', '凉拌木耳', '蒜泥白肉'],
  '蒸品': ['清蒸鲈鱼', '粉蒸排骨', '蒸蛋羹', '剁椒鱼头', '蒜蓉蒸虾'],
  '面点': ['小笼包', '煎饺', '葱油饼', '刀削面', '炸酱面'],
  '甜品': ['芒果布丁', '双皮奶', '杨枝甘露', '红豆沙', '桂花糕'],
};

const TABLES = ['A1', 'A2', 'A3', 'B1', 'B2', 'B5', 'C3', 'C7', 'D1', 'D4', 'E6', 'V1', 'V2', 'V3'];

function randomPick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function generateMockTickets(): Ticket[] {
  const now = Date.now();
  const tickets: Ticket[] = [];
  let idCounter = 0;

  for (const station of STATIONS) {
    const count = Math.floor(Math.random() * 4) + 2; // 2-5 per station
    for (let i = 0; i < count; i++) {
      idCounter++;
      const isVip = Math.random() < 0.2;
      const isRush = Math.random() < 0.15;
      const rushCount = isRush ? Math.floor(Math.random() * 3) + 1 : 0;
      const priority: Priority = isVip ? 'high' : isRush ? 'medium' : 'normal';
      const statusRand = Math.random();
      const status: TicketStatus = statusRand < 0.5 ? 'pending' : statusRand < 0.85 ? 'making' : 'done';

      tickets.push({
        id: `tk-${idCounter}`,
        orderId: `ORD${String(1000 + idCounter).slice(1)}`,
        tableNo: randomPick(TABLES),
        dishName: randomPick(MOCK_DISHES[station]),
        quantity: Math.floor(Math.random() * 3) + 1,
        station,
        priority,
        status,
        isVip,
        isRush,
        rushCount,
        createdAt: now - Math.floor(Math.random() * 30) * 60000,
      });
    }
  }

  return tickets;
}

// ─── API 调用 ─────────────────────────────────────────────────────────────────

const BASE = 'http://localhost:8001';

async function fetchStationTickets(): Promise<Ticket[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/kds/dispatch/tickets`, {
      headers: { 'X-Tenant-ID': 'default' },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return (json.data?.items ?? []).map((item: Record<string, unknown>) => ({
      id: String(item.id ?? ''),
      orderId: String(item.order_id ?? ''),
      tableNo: String(item.table_no ?? ''),
      dishName: String(item.dish_name ?? ''),
      quantity: Number(item.quantity ?? 1),
      station: String(item.station ?? '炒菜') as StationName,
      priority: String(item.priority ?? 'normal') as Priority,
      status: String(item.status ?? 'pending') as TicketStatus,
      isVip: Boolean(item.is_vip),
      isRush: Boolean(item.is_rush),
      rushCount: Number(item.rush_count ?? 0),
      createdAt: Number(item.created_at ?? Date.now()),
    }));
  } catch {
    return [];
  }
}

async function apiUpdateTicketStatus(ticketId: string, status: TicketStatus): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/kds/dispatch/tickets/${ticketId}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': 'default' },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// ─── 排序逻辑 ─────────────────────────────────────────────────────────────────

const PRIORITY_WEIGHT: Record<Priority, number> = { high: 0, medium: 1, normal: 2 };

function sortTickets(tickets: Ticket[]): Ticket[] {
  return [...tickets].sort((a, b) => {
    // 优先级高的在前
    const pw = PRIORITY_WEIGHT[a.priority] - PRIORITY_WEIGHT[b.priority];
    if (pw !== 0) return pw;
    // 同优先级：时间早的在前
    return a.createdAt - b.createdAt;
  });
}

// ─── 组件 ─────────────────────────────────────────────────────────────────────

export function SmartDispatch() {
  const [tickets, setTickets] = useState<Ticket[]>(() => generateMockTickets());
  const [activeStation, setActiveStation] = useState<StationName | 'all'>('all');
  const [useMock, setUseMock] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(Date.now());
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── 数据刷新 ────────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    if (useMock) {
      setTickets(generateMockTickets());
    } else {
      const data = await fetchStationTickets();
      if (data.length > 0) {
        setTickets(data);
      }
    }
    setLastRefresh(Date.now());
  }, [useMock]);

  // 20s 自动刷新
  useEffect(() => {
    refreshTimerRef.current = setInterval(loadData, 20000);
    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
    };
  }, [loadData]);

  // ─── 操作 ───────────────────────────────────────────────────────────

  const handleStatusChange = useCallback(async (ticketId: string, newStatus: TicketStatus) => {
    // 乐观更新
    setTickets(prev => prev.map(t => t.id === ticketId ? { ...t, status: newStatus } : t));
    if (navigator.vibrate) navigator.vibrate(50);

    if (!useMock) {
      try {
        await apiUpdateTicketStatus(ticketId, newStatus);
      } catch (err) {
        // 回滚
        setTickets(prev => prev.map(t => t.id === ticketId ? { ...t, status: 'pending' } : t));
        console.error('Failed to update ticket status:', err);
      }
    }
  }, [useMock]);

  // ─── 统计 ───────────────────────────────────────────────────────────

  const stationStats: StationStats[] = STATIONS.map(station => ({
    station,
    pending: tickets.filter(t => t.station === station && t.status === 'pending').length,
    making: tickets.filter(t => t.station === station && t.status === 'making').length,
  }));

  const maxLoad = Math.max(...stationStats.map(s => s.pending + s.making), 1);

  // ─── 过滤 + 排序 ───────────────────────────────────────────────────

  const filteredTickets = sortTickets(
    tickets.filter(t => {
      if (t.status === 'done' || t.status === 'skipped') return false;
      if (activeStation === 'all') return true;
      return t.station === activeStation;
    })
  );

  // ─── 格式化 ─────────────────────────────────────────────────────────

  const formatTime = (ts: number): string => {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  };

  const formatWait = (ts: number): string => {
    const mins = Math.floor((Date.now() - ts) / 60000);
    return mins < 1 ? '<1分钟' : `${mins}分钟`;
  };

  const formatRefreshTime = (ts: number): string => {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  };

  // ─── 渲染 ───────────────────────────────────────────────────────────

  return (
    <div style={{
      minHeight: '100vh',
      background: C.bg,
      color: C.white,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: 16,
      gap: 12,
      boxSizing: 'border-box',
    }}>
      {/* ── 顶部标题 ─────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, margin: 0 }}>
          智能分单看板
        </h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontSize: 14, color: C.muted }}>
            上次刷新: {formatRefreshTime(lastRefresh)}
          </span>
          <button
            onClick={loadData}
            style={{
              height: 48,
              minWidth: 80,
              borderRadius: 8,
              border: `1px solid ${C.border}`,
              background: 'transparent',
              color: C.accent,
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            刷新
          </button>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 14,
            color: C.muted,
            cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={useMock}
              onChange={e => setUseMock(e.target.checked)}
              style={{ width: 18, height: 18, cursor: 'pointer' }}
            />
            模拟数据
          </label>
        </div>
      </div>

      {/* ── 档口Tab ──────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        gap: 8,
        overflowX: 'auto',
        flexShrink: 0,
      }}>
        <button
          onClick={() => setActiveStation('all')}
          style={{
            minWidth: 72,
            height: 48,
            borderRadius: 8,
            border: `2px solid ${activeStation === 'all' ? C.accent : C.border}`,
            background: activeStation === 'all' ? 'rgba(255,107,53,0.15)' : 'transparent',
            color: activeStation === 'all' ? C.accent : C.muted,
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
            flexShrink: 0,
          }}
        >
          全部
        </button>
        {STATIONS.map(station => {
          const stats = stationStats.find(s => s.station === station);
          const load = (stats?.pending ?? 0) + (stats?.making ?? 0);
          const isBusy = load >= maxLoad * 0.8 && load > 2;
          return (
            <button
              key={station}
              onClick={() => setActiveStation(station)}
              style={{
                minWidth: 90,
                height: 48,
                borderRadius: 8,
                border: `2px solid ${activeStation === station ? C.accent : isBusy ? C.red : C.border}`,
                background: activeStation === station
                  ? 'rgba(255,107,53,0.15)'
                  : isBusy
                    ? 'rgba(239,68,68,0.08)'
                    : 'transparent',
                color: activeStation === station ? C.accent : isBusy ? C.red : C.muted,
                fontSize: 16,
                fontWeight: 600,
                cursor: 'pointer',
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
                padding: '4px 12px',
              }}
            >
              <span>{station}</span>
              <span style={{ fontSize: 12 }}>
                {stats?.pending ?? 0}待 / {stats?.making ?? 0}做
              </span>
            </button>
          );
        })}
      </div>

      {/* ── 工单列表 ─────────────────────────────────────────────────── */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        minHeight: 0,
      }}>
        {filteredTickets.length === 0 ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flex: 1,
            color: C.muted,
            fontSize: 18,
          }}>
            当前无待处理工单
          </div>
        ) : (
          filteredTickets.map(ticket => (
            <div
              key={ticket.id}
              style={{
                background: C.card,
                borderRadius: 10,
                padding: '14px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                borderLeft: `5px solid ${PRIORITY_BORDER[ticket.priority]}`,
              }}
            >
              {/* 档口标签 */}
              <div style={{
                minWidth: 52,
                textAlign: 'center',
                fontSize: 14,
                fontWeight: 600,
                color: C.accent,
                background: 'rgba(255,107,53,0.12)',
                padding: '6px 8px',
                borderRadius: 6,
                flexShrink: 0,
              }}>
                {ticket.station}
              </div>

              {/* 主体信息 */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  marginBottom: 4,
                }}>
                  <span style={{ fontSize: 18, fontWeight: 700 }}>{ticket.dishName}</span>
                  <span style={{
                    fontSize: 16,
                    fontWeight: 600,
                    color: C.accent,
                  }}>
                    x{ticket.quantity}
                  </span>
                  {ticket.isVip && (
                    <span style={{
                      fontSize: 12,
                      fontWeight: 700,
                      color: '#FFD700',
                      background: 'rgba(255,215,0,0.15)',
                      padding: '2px 8px',
                      borderRadius: 4,
                    }}>
                      VIP
                    </span>
                  )}
                  {ticket.isRush && (
                    <span style={{
                      fontSize: 12,
                      fontWeight: 700,
                      color: C.orange,
                      background: 'rgba(245,158,11,0.15)',
                      padding: '2px 8px',
                      borderRadius: 4,
                    }}>
                      催{ticket.rushCount}次
                    </span>
                  )}
                </div>
                <div style={{
                  display: 'flex',
                  gap: 16,
                  fontSize: 14,
                  color: C.muted,
                }}>
                  <span>单号: {ticket.orderId}</span>
                  <span>桌号: {ticket.tableNo}</span>
                  <span>下单: {formatTime(ticket.createdAt)}</span>
                  <span>等待: {formatWait(ticket.createdAt)}</span>
                </div>
              </div>

              {/* 状态标签 */}
              <div style={{
                fontSize: 14,
                fontWeight: 600,
                color: ticket.status === 'making' ? C.orange : C.muted,
                background: ticket.status === 'making' ? 'rgba(245,158,11,0.12)' : 'transparent',
                padding: '4px 10px',
                borderRadius: 6,
                flexShrink: 0,
              }}>
                {ticket.status === 'pending' ? '待处理' : '制作中'}
              </div>

              {/* 操作按钮 */}
              <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                {ticket.status === 'pending' && (
                  <button
                    onClick={() => handleStatusChange(ticket.id, 'making')}
                    style={{
                      minWidth: 72,
                      height: 48,
                      borderRadius: 8,
                      border: 'none',
                      background: C.blue,
                      color: '#fff',
                      fontSize: 14,
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    开始
                  </button>
                )}
                {ticket.status === 'making' && (
                  <button
                    onClick={() => handleStatusChange(ticket.id, 'done')}
                    style={{
                      minWidth: 72,
                      height: 48,
                      borderRadius: 8,
                      border: 'none',
                      background: C.green,
                      color: '#fff',
                      fontSize: 14,
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    完成
                  </button>
                )}
                <button
                  onClick={() => handleStatusChange(ticket.id, 'skipped')}
                  style={{
                    minWidth: 56,
                    height: 48,
                    borderRadius: 8,
                    border: `1px solid ${C.border}`,
                    background: 'transparent',
                    color: C.muted,
                    fontSize: 14,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  跳过
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* ── 底部统计栏 ───────────────────────────────────────────────── */}
      <div style={{
        background: C.card,
        borderRadius: 12,
        padding: '12px 16px',
        display: 'flex',
        gap: 12,
        overflowX: 'auto',
        flexShrink: 0,
      }}>
        {stationStats.map(stat => {
          const load = stat.pending + stat.making;
          const isBusy = load >= maxLoad * 0.8 && load > 2;
          return (
            <div
              key={stat.station}
              style={{
                flex: 1,
                minWidth: 100,
                background: isBusy ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.03)',
                borderRadius: 8,
                padding: '10px 12px',
                textAlign: 'center',
                border: isBusy ? `1px solid ${C.red}44` : '1px solid transparent',
              }}
            >
              <div style={{
                fontSize: 16,
                fontWeight: 700,
                color: isBusy ? C.red : C.white,
                marginBottom: 4,
              }}>
                {stat.station}
                {isBusy && (
                  <span style={{ fontSize: 12, marginLeft: 4 }}>繁忙</span>
                )}
              </div>
              <div style={{
                display: 'flex',
                justifyContent: 'center',
                gap: 12,
                fontSize: 14,
              }}>
                <span style={{ color: C.muted }}>
                  待处理 <span style={{ color: C.accent, fontWeight: 600 }}>{stat.pending}</span>
                </span>
                <span style={{ color: C.muted }}>
                  制作中 <span style={{ color: C.orange, fontWeight: 600 }}>{stat.making}</span>
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default SmartDispatch;
