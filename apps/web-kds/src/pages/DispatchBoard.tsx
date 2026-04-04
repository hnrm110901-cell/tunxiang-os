/**
 * DispatchBoard — 出餐调度看板
 *
 * 档口负责人全屏调度面板，工作在后厨站立操作。
 * 三列布局：等待出餐 | 正在制作 | 待出餐
 *
 * 设计遵循 Store-KDS 触控规范：
 *   - 所有点击区域 ≥ 48×48px
 *   - 字体 ≥ 16px，标题 ≥ 24px
 *   - 深色主题：背景 #0B1A20，卡片 #112228，高亮 #FF6B35
 *   - 关键操作触发 navigator.vibrate(50)
 *   - 乐观更新 + 30s 自动刷新
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type Priority = 'normal' | 'vip' | 'rush' | 'banquet';
type StationLabel = '炒菜' | '烧烤' | '凉菜' | '甜品' | '海鲜' | '汤品';
type OrderStatus = 'waiting' | 'making' | 'ready';

interface DispatchOrder {
  id: string;
  tableNo: string;
  dishCount: number;
  priority: Priority;
  status: OrderStatus;
  station?: StationLabel;
  createdAt: number; // timestamp ms
}

// ─── Mock 数据 ────────────────────────────────────────────────────────────────

const STATIONS: StationLabel[] = ['炒菜', '烧烤', '凉菜', '甜品', '海鲜', '汤品'];

function makeMockOrders(): DispatchOrder[] {
  const now = Date.now();
  return [
    // 等待出餐 ×8
    { id: 'w1', tableNo: 'A3', dishCount: 4, priority: 'vip',     status: 'waiting', createdAt: now - 18 * 60000 },
    { id: 'w2', tableNo: 'B7', dishCount: 2, priority: 'rush',    status: 'waiting', createdAt: now - 12 * 60000 },
    { id: 'w3', tableNo: 'C1', dishCount: 6, priority: 'banquet', status: 'waiting', createdAt: now - 8  * 60000 },
    { id: 'w4', tableNo: 'D5', dishCount: 3, priority: 'normal',  status: 'waiting', createdAt: now - 5  * 60000 },
    { id: 'w5', tableNo: 'E2', dishCount: 5, priority: 'vip',     status: 'waiting', createdAt: now - 4  * 60000 },
    { id: 'w6', tableNo: 'F8', dishCount: 2, priority: 'normal',  status: 'waiting', createdAt: now - 3  * 60000 },
    { id: 'w7', tableNo: 'G4', dishCount: 7, priority: 'rush',    status: 'waiting', createdAt: now - 2  * 60000 },
    { id: 'w8', tableNo: 'H6', dishCount: 1, priority: 'normal',  status: 'waiting', createdAt: now - 1  * 60000 },
    // 正在制作 ×5
    { id: 'm1', tableNo: 'A1', dishCount: 3, priority: 'vip',     status: 'making', station: '炒菜',  createdAt: now - 16 * 60000 },
    { id: 'm2', tableNo: 'B3', dishCount: 4, priority: 'normal',  status: 'making', station: '烧烤',  createdAt: now - 10 * 60000 },
    { id: 'm3', tableNo: 'C6', dishCount: 2, priority: 'rush',    status: 'making', station: '凉菜',  createdAt: now - 7  * 60000 },
    { id: 'm4', tableNo: 'D2', dishCount: 5, priority: 'banquet', status: 'making', station: '海鲜',  createdAt: now - 6  * 60000 },
    { id: 'm5', tableNo: 'E9', dishCount: 3, priority: 'normal',  status: 'making', station: '甜品',  createdAt: now - 4  * 60000 },
    // 待出餐 ×3
    { id: 'r1', tableNo: 'A2', dishCount: 3, priority: 'vip',     status: 'ready',  createdAt: now - 20 * 60000 },
    { id: 'r2', tableNo: 'B4', dishCount: 5, priority: 'normal',  status: 'ready',  createdAt: now - 9  * 60000 },
    { id: 'r3', tableNo: 'C3', dishCount: 2, priority: 'banquet', status: 'ready',  createdAt: now - 6  * 60000 },
  ];
}

// ─── API 调用 ─────────────────────────────────────────────────────────────────

const BASE = 'http://localhost:8001';

async function apiServeOrder(orderId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/kds/orders/${orderId}/served`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': 'default' },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function fetchKDSOrders(): Promise<DispatchOrder[]> {
  const res = await fetch(`${BASE}/api/v1/kds/orders?status=pending`, {
    headers: { 'X-Tenant-ID': 'default' },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  // 将后端数据映射到本地格式（实际字段根据后端调整）
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (json.data?.items ?? []).map((o: any) => ({
    id: String(o.id),
    tableNo: o.table_no ?? o.tableNo ?? '?',
    dishCount: o.dish_count ?? o.dishCount ?? 0,
    priority: (o.priority ?? 'normal') as Priority,
    status: (o.status ?? 'waiting') as OrderStatus,
    station: o.station ?? undefined,
    createdAt: o.created_at ? new Date(o.created_at).getTime() : Date.now(),
  }));
}

// ─── 辅助函数 ─────────────────────────────────────────────────────────────────

function vibrate() {
  try { navigator.vibrate?.(50); } catch { /* noop */ }
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** 超时颜色判断（阈值 15 分钟） */
function timerColor(createdAt: number): { color: string; bg?: string } {
  const elapsed = Date.now() - createdAt;
  const min = elapsed / 60000;
  if (min >= 15) return { color: '#FFFFFF', bg: '#A32D2D' };
  if (min >= 10) return { color: '#FFD166' };
  return { color: '#4ADE80' };
}

const PRIORITY_LABELS: Record<Priority, { label: string; color: string; bg: string }> = {
  normal:  { label: '',    color: 'transparent', bg: 'transparent' },
  vip:     { label: 'VIP',  color: '#1A1A00', bg: '#FFD166' },
  rush:    { label: '催菜', color: '#FFFFFF', bg: '#FF6B35' },
  banquet: { label: '宴席', color: '#FFFFFF', bg: '#9B59B6' },
};

const STATION_COLORS: Record<StationLabel, string> = {
  炒菜: '#FF6B35',
  烧烤: '#E67E22',
  凉菜: '#2ECC71',
  甜品: '#E91E63',
  海鲜: '#3498DB',
  汤品: '#16A085',
};

// ─── 子组件：倒计时 Hook ───────────────────────────────────────────────────────

function useTick(intervalMs = 1000) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return tick;
}

// ─── 子组件：订单卡片 ─────────────────────────────────────────────────────────

interface OrderCardProps {
  order: DispatchOrder;
  onAction: (order: DispatchOrder) => void;
  actionLabel: string;
  actionColor: string;
  /** ready 列显示传菜大按钮 */
  largeAction?: boolean;
}

function OrderCard({ order, onAction, actionLabel, actionColor, largeAction }: OrderCardProps) {
  useTick(); // 1s 重渲染刷新倒计时
  const elapsed = Date.now() - order.createdAt;
  const tc = timerColor(order.createdAt);
  const pTag = PRIORITY_LABELS[order.priority];
  const isOvertime = elapsed >= 15 * 60000;

  const cardStyle: React.CSSProperties = {
    background: isOvertime ? '#2A0A0A' : '#112228',
    border: `2px solid ${isOvertime ? '#A32D2D' : order.status === 'ready' ? '#0F6E56' : '#1D3540'}`,
    borderRadius: 12,
    padding: '16px',
    marginBottom: 12,
    position: 'relative',
    boxShadow: isOvertime ? '0 0 12px rgba(163,45,45,0.4)' : '0 2px 8px rgba(0,0,0,0.3)',
  };

  const tableStyle: React.CSSProperties = {
    fontSize: 32,
    fontWeight: 800,
    color: '#FFFFFF',
    lineHeight: 1,
    marginBottom: 8,
  };

  const timerStyle: React.CSSProperties = {
    fontSize: 22,
    fontWeight: 700,
    color: tc.color,
    background: tc.bg ?? 'transparent',
    padding: tc.bg ? '2px 8px' : 0,
    borderRadius: 6,
    display: 'inline-block',
    marginBottom: 8,
  };

  const btnStyle: React.CSSProperties = {
    width: '100%',
    height: largeAction ? 88 : 56,
    background: actionColor,
    border: 'none',
    borderRadius: 10,
    color: '#FFFFFF',
    fontSize: largeAction ? 22 : 17,
    fontWeight: 700,
    cursor: 'pointer',
    marginTop: 12,
    transition: 'transform 200ms ease, filter 200ms ease',
    touchAction: 'manipulation',
  };

  function handleClick() {
    vibrate();
    onAction(order);
  }

  return (
    <div style={cardStyle}>
      {/* 优先级标签 */}
      {order.priority !== 'normal' && (
        <span style={{
          position: 'absolute', top: 12, right: 12,
          background: pTag.bg, color: pTag.color,
          fontSize: 13, fontWeight: 700, padding: '3px 8px', borderRadius: 6,
        }}>
          {pTag.label}
        </span>
      )}

      {/* 档口标签（制作中列） */}
      {order.station && (
        <span style={{
          display: 'inline-block',
          background: STATION_COLORS[order.station],
          color: '#FFFFFF',
          fontSize: 13, fontWeight: 600,
          padding: '2px 8px', borderRadius: 6, marginBottom: 8,
        }}>
          {order.station}
        </span>
      )}

      <div style={tableStyle}>{order.tableNo}桌</div>
      <div style={timerStyle}>{formatElapsed(elapsed)}</div>
      {isOvertime && (
        <div style={{ fontSize: 16, color: '#FF6B6B', fontWeight: 700, marginBottom: 4 }}>
          ⚠ 已超时
        </div>
      )}
      <div style={{ fontSize: 16, color: '#8AABB8' }}>{order.dishCount} 道菜</div>

      <button
        style={btnStyle}
        onPointerDown={e => {
          (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
          (e.currentTarget as HTMLButtonElement).style.filter = 'brightness(0.85)';
        }}
        onPointerUp={e => {
          (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
          (e.currentTarget as HTMLButtonElement).style.filter = 'brightness(1)';
        }}
        onPointerLeave={e => {
          (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
          (e.currentTarget as HTMLButtonElement).style.filter = 'brightness(1)';
        }}
        onClick={handleClick}
      >
        {largeAction ? `🍽 ${actionLabel}` : actionLabel}
      </button>
    </div>
  );
}

// ─── 子组件：列标题 ───────────────────────────────────────────────────────────

function ColumnHeader({ title, count, accent }: { title: string; count: number; accent: string }) {
  return (
    <div style={{
      padding: '12px 16px',
      borderBottom: `3px solid ${accent}`,
      marginBottom: 16,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
    }}>
      <span style={{ fontSize: 22, fontWeight: 800, color: '#FFFFFF' }}>{title}</span>
      <span style={{
        background: accent,
        color: accent === '#FFD166' ? '#1A1A00' : '#FFFFFF',
        fontSize: 18, fontWeight: 700,
        padding: '4px 14px', borderRadius: 20,
      }}>{count}</span>
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function DispatchBoard() {
  const [orders, setOrders] = useState<DispatchOrder[]>(() => makeMockOrders());
  const [staffCount] = useState(8);
  const [servedToday, setServedToday] = useState(47);
  const [avgMinutes] = useState(14);
  const [refreshCountdown, setRefreshCountdown] = useState(30);
  const [now, setNow] = useState(() => new Date());
  const pendingServe = useRef<Set<string>>(new Set());

  // 时钟
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // 30s 自动刷新 + 进度条倒计时
  useEffect(() => {
    const tick = setInterval(() => {
      setRefreshCountdown(c => {
        if (c <= 1) {
          doRefresh();
          return 30;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(tick);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doRefresh = useCallback(async () => {
    try {
      const fresh = await fetchKDSOrders();
      setOrders(fresh);
    } catch {
      // 降级保留 mock 数据，不中断展示
    }
  }, []);

  // 过滤列表
  const waiting = orders.filter(o => o.status === 'waiting');
  const making  = orders.filter(o => o.status === 'making');
  const ready   = orders.filter(o => o.status === 'ready');

  // 乐观更新：等待 → 制作
  function handleStartMaking(order: DispatchOrder) {
    const stationIdx = Math.floor(Math.random() * STATIONS.length);
    setOrders(prev => prev.map(o =>
      o.id === order.id
        ? { ...o, status: 'making', station: STATIONS[stationIdx] }
        : o
    ));
  }

  // 乐观更新：制作 → 待出餐
  function handleFinish(order: DispatchOrder) {
    setOrders(prev => prev.map(o =>
      o.id === order.id ? { ...o, status: 'ready' } : o
    ));
  }

  // 乐观更新：传菜 → 移除；调用 API
  function handleServe(order: DispatchOrder) {
    if (pendingServe.current.has(order.id)) return;
    pendingServe.current.add(order.id);

    setOrders(prev => prev.filter(o => o.id !== order.id));
    setServedToday(c => c + 1);

    apiServeOrder(order.id)
      .catch(() => {
        // API 失败时恢复到 ready 列（可选，这里静默忽略以免扰操作流）
      })
      .finally(() => {
        pendingServe.current.delete(order.id);
      });
  }

  // 样式常量
  const timeStr = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const progressPct = ((30 - refreshCountdown) / 30) * 100;

  const containerStyle: React.CSSProperties = {
    minWidth: 1280,
    minHeight: 800,
    height: '100vh',
    background: '#0B1A20',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
    overflow: 'hidden',
  };

  const topBarStyle: React.CSSProperties = {
    height: 60,
    background: '#0D2030',
    display: 'flex',
    alignItems: 'center',
    padding: '0 24px',
    gap: 32,
    flexShrink: 0,
    borderBottom: '1px solid #1D3540',
  };

  const statStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  };

  const mainStyle: React.CSSProperties = {
    flex: 1,
    display: 'flex',
    gap: 0,
    overflow: 'hidden',
    padding: '0 0 0 0',
  };

  const colStyle = (flex: number): React.CSSProperties => ({
    flex,
    display: 'flex',
    flexDirection: 'column',
    padding: '16px 12px',
    overflow: 'hidden',
    borderRight: '1px solid #1D3540',
  });

  const scrollStyle: React.CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'],
    paddingRight: 4,
  };

  const bottomBarStyle: React.CSSProperties = {
    height: 64,
    background: '#0D2030',
    display: 'flex',
    alignItems: 'center',
    padding: '0 24px',
    gap: 16,
    flexShrink: 0,
    borderTop: '1px solid #1D3540',
  };

  const bigBtnStyle: React.CSSProperties = {
    height: 48,
    minWidth: 80,
    padding: '0 20px',
    background: '#1D3540',
    border: '1px solid #2A4D5E',
    borderRadius: 10,
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    transition: 'transform 200ms ease, filter 200ms ease',
    touchAction: 'manipulation',
  };

  const bellBtnStyle: React.CSSProperties = {
    width: 80,
    height: 48,
    background: '#FF6B35',
    border: 'none',
    borderRadius: 12,
    color: '#FFFFFF',
    fontSize: 22,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'transform 200ms ease',
    touchAction: 'manipulation',
  };

  return (
    <div style={containerStyle}>
      {/* 刷新进度条 */}
      <div style={{
        height: 3, background: '#0D2030', position: 'relative', flexShrink: 0,
      }}>
        <div style={{
          height: '100%',
          width: `${progressPct}%`,
          background: '#FF6B35',
          transition: 'width 1s linear',
          borderRadius: 2,
        }} />
      </div>

      {/* 顶部状态栏 */}
      <div style={topBarStyle}>
        {/* 时钟 */}
        <div style={{ fontSize: 28, fontWeight: 800, color: '#FFFFFF', letterSpacing: 2, minWidth: 110 }}>
          {timeStr}
        </div>

        <div style={{ width: 1, height: 36, background: '#1D3540' }} />

        {/* 统计项 */}
        {[
          { label: '今日出餐', value: servedToday, unit: '单', color: '#4ADE80' },
          { label: '平均时长', value: avgMinutes,  unit: '分', color: '#FFD166' },
          { label: '队列中',   value: waiting.length + making.length, unit: '单', color: '#FF6B35' },
          { label: '在岗员工', value: staffCount,  unit: '人', color: '#60D4FA' },
        ].map(stat => (
          <div key={stat.label} style={{ ...statStyle, minWidth: 80 }}>
            <span style={{ fontSize: 26, fontWeight: 800, color: stat.color, lineHeight: 1 }}>
              {stat.value}<span style={{ fontSize: 14, marginLeft: 2 }}>{stat.unit}</span>
            </span>
            <span style={{ fontSize: 13, color: '#8AABB8', marginTop: 2 }}>{stat.label}</span>
          </div>
        ))}

        <div style={{ flex: 1 }} />

        <span style={{ fontSize: 14, color: '#8AABB8' }}>
          {refreshCountdown}s 后刷新
        </span>
      </div>

      {/* 主区域三列 */}
      <div style={mainStyle}>
        {/* 左列：等待出餐 35% */}
        <div style={colStyle(35)}>
          <ColumnHeader title="等待出餐" count={waiting.length} accent="#FF6B35" />
          <div style={scrollStyle}>
            {waiting.length === 0 && (
              <div style={{ textAlign: 'center', color: '#4A6A7A', fontSize: 18, paddingTop: 40 }}>
                暂无等待订单
              </div>
            )}
            {waiting.map(order => (
              <OrderCard
                key={order.id}
                order={order}
                onAction={handleStartMaking}
                actionLabel="开始制作"
                actionColor="#FF6B35"
              />
            ))}
          </div>
        </div>

        {/* 中列：正在制作 35% */}
        <div style={colStyle(35)}>
          <ColumnHeader title="正在制作" count={making.length} accent="#FFD166" />
          <div style={scrollStyle}>
            {making.length === 0 && (
              <div style={{ textAlign: 'center', color: '#4A6A7A', fontSize: 18, paddingTop: 40 }}>
                暂无制作中订单
              </div>
            )}
            {making.map(order => (
              <OrderCard
                key={order.id}
                order={order}
                onAction={handleFinish}
                actionLabel="完成出餐"
                actionColor="#0F6E56"
              />
            ))}
          </div>
        </div>

        {/* 右列：待出餐 30% */}
        <div style={{ ...colStyle(30), borderRight: 'none' }}>
          <ColumnHeader title="待出餐" count={ready.length} accent="#4ADE80" />
          <div style={scrollStyle}>
            {ready.length === 0 && (
              <div style={{ textAlign: 'center', color: '#4A6A7A', fontSize: 18, paddingTop: 40 }}>
                暂无待传菜订单
              </div>
            )}
            {ready.map(order => (
              <OrderCard
                key={order.id}
                order={order}
                onAction={handleServe}
                actionLabel="传菜"
                actionColor="#FF6B35"
                largeAction
              />
            ))}
          </div>
        </div>
      </div>

      {/* 底部工具栏 */}
      <div style={bottomBarStyle}>
        {/* 呼叫传菜员 —— 80px 大按钮 */}
        <button
          style={bellBtnStyle}
          onPointerDown={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.93)'; }}
          onPointerUp={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          onPointerLeave={e => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          onClick={() => {
            vibrate();
            // 触发广播或推送
          }}
          title="呼叫传菜员"
        >
          🔔
        </button>

        {[
          { icon: '🏭', label: '备料站', path: '/prep-station' },
          { icon: '👥', label: '排班信息', path: '/chef-stats' },
          { icon: '📊', label: '档口绩效', path: '/station' },
        ].map(item => (
          <button
            key={item.label}
            style={bigBtnStyle}
            onPointerDown={e => {
              (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
              (e.currentTarget as HTMLButtonElement).style.filter = 'brightness(0.85)';
            }}
            onPointerUp={e => {
              (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
              (e.currentTarget as HTMLButtonElement).style.filter = 'brightness(1)';
            }}
            onPointerLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
              (e.currentTarget as HTMLButtonElement).style.filter = 'brightness(1)';
            }}
            onClick={() => {
              vibrate();
              window.location.href = item.path;
            }}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}

        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 14, color: '#4A6A7A' }}>出餐调度 v2</span>
      </div>
    </div>
  );
}

export default DispatchBoard;
