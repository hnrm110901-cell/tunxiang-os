/**
 * KitchenBoard -- 档口任务看板（核心页面）
 *
 * 三列布局：待制作 | 制作中 | 已完成
 * 每张卡片：桌号 + 菜名 + 数量 + 等待时间 + VIP标记 + 备注
 * 按优先级排序，催菜标红，超时闪烁
 * 深色背景，触控优化（最小48x48按钮，最小16px字体）
 *
 * WebSocket 实时推送：连接 Mac mini /ws/kds/{stationId}
 * 替代旧版 setInterval 轮询
 */
import { useState, useEffect, useCallback } from 'react';
import { useKdsWebSocket, type KDSTicket, type RemakeAlert } from '../hooks/useKdsWebSocket';
import { warmUpAudio } from '../utils/audio';
import { pauseTicket, resumeTicket, grabTicket } from '../api/kdsOpsApi';
import { StatusBar, OrderTicketCard } from '@tx-ds/biz';
import type { OrderTicketData } from '@tx-ds/biz';

// ─── KDS 配置（从 localStorage 读取） ───

function getKdsConfig() {
  try {
    return {
      host: localStorage.getItem('kds_mac_host') || '',
      stationId: localStorage.getItem('kds_station_id') || 'default',
      soundEnabled: localStorage.getItem('kds_sound') !== 'off',
      timeoutMinutes: parseInt(localStorage.getItem('kds_timeout_minutes') || '25', 10),
    };
  } catch {
    return { host: '', stationId: 'default', soundEnabled: true, timeoutMinutes: 25 };
  }
}

// ─── 超时阈值（分钟） ───

function getTimeoutThresholds() {
  const critical = parseInt(localStorage.getItem('kds_timeout_minutes') || '25', 10);
  return {
    warn: Math.max(Math.floor(critical * 0.6), 5),
    critical,
  };
}

// ─── KDSTicket → OrderTicketData 转换 ───

function toTicketData(t: KDSTicket): OrderTicketData {
  return {
    id: t.id,
    orderNo: t.orderNo,
    tableNo: t.tableNo,
    status: t.status,
    priority: t.priority,
    createdAt: new Date(t.createdAt).toISOString(),
    timeoutMinutes: getTimeoutThresholds().critical,
    items: t.items.map((item, i) => ({
      id: `${t.id}-${i}`,
      name: item.name,
      qty: item.qty,
      spec: item.spec,
      remark: item.notes || undefined,
    })),
  };
}

// ─── 优先级排序权重 ───

function priorityWeight(p: string): number {
  if (p === 'rush') return 0;
  if (p === 'vip') return 1;
  return 2;
}

function sortTickets(tickets: KDSTicket[]): KDSTicket[] {
  return [...tickets].sort((a, b) => {
    const pw = priorityWeight(a.priority) - priorityWeight(b.priority);
    if (pw !== 0) return pw;
    return a.createdAt - b.createdAt;
  });
}

// ─── Component ───

export function KitchenBoard() {
  const config = getKdsConfig();
  const wsEnabled = !!config.host;

  // WebSocket 数据源
  const {
    connected,
    tickets: wsTickets,
    rushAlerts,
    remakeAlerts,
    timeoutAlerts,
    setTickets: setWsTickets,
    dismissRemakeAlert,
    dismissTimeoutAlert,
  } = useKdsWebSocket(config);

  // 本地 tickets state（无 WS 时用 mock 数据，有 WS 时同步 WS 数据）
  const [tickets, setTickets] = useState<KDSTicket[]>(() =>
    wsEnabled ? [] : MOCK_TICKETS,
  );

  // 当 WS 数据更新时同步到本地
  useEffect(() => {
    if (wsEnabled && wsTickets.length > 0) {
      setTickets(wsTickets);
    }
  }, [wsEnabled, wsTickets]);

  const [tick, setTick] = useState(0);
  const [now, setNow] = useState(Date.now);
  const [selectedDept, setSelectedDept] = useState<string>('all');
  const [audioWarmed, setAudioWarmed] = useState(false);

  // ── 新功能状态 ──
  // 抢单模式：开启后每张 pending 卡片显示"抢单"按钮
  const [grabMode, setGrabMode] = useState<boolean>(
    () => localStorage.getItem('kds_grab_mode') === 'on'
  );
  // 批量合并视图：按菜品合并多桌同一菜品的数量
  const [batchView, setBatchView] = useState<boolean>(false);
  // 停菜中的 ticket IDs 本地状态（实时 UI 反馈）
  const [pausedIds, setPausedIds] = useState<Set<string>>(new Set());
  // 当前操作员ID（实际应从登录信息获取）
  const operatorId = (window as any).__OPERATOR_ID__ as string | undefined;

  // 每秒刷新倒计时
  useEffect(() => {
    const timer = setInterval(() => {
      setTick(t => t + 1);
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // 用户首次触控时预热 AudioContext
  const handleFirstTouch = useCallback(() => {
    if (!audioWarmed) {
      warmUpAudio();
      setAudioWarmed(true);
    }
  }, [audioWarmed]);

  // 开始制作
  const startCooking = useCallback((id: string) => {
    const update = (prev: KDSTicket[]) =>
      prev.map(t => t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t);
    setTickets(update);
    if (wsEnabled) setWsTickets(update);
  }, [wsEnabled, setWsTickets]);

  // 停菜/恢复
  const togglePause = useCallback(async (id: string) => {
    const isPaused = pausedIds.has(id);
    // 乐观更新
    setPausedIds(prev => {
      const next = new Set(prev);
      if (isPaused) next.delete(id); else next.add(id);
      return next;
    });
    try {
      if (isPaused) {
        await resumeTicket(id, operatorId);
      } else {
        await pauseTicket(id, operatorId);
      }
    } catch {
      // 失败回滚
      setPausedIds(prev => {
        const next = new Set(prev);
        if (isPaused) next.add(id); else next.delete(id);
        return next;
      });
    }
  }, [pausedIds, operatorId]);

  // 抢单
  const handleGrab = useCallback(async (id: string) => {
    if (!operatorId) return;
    try {
      await grabTicket(id, operatorId);
      const update = (prev: KDSTicket[]) =>
        prev.map(t => t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t);
      setTickets(update);
      if (wsEnabled) setWsTickets(update);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '抢单失败';
      alert(msg);
    }
  }, [operatorId, wsEnabled, setWsTickets]);

  // 完成出品
  const completeCooking = useCallback((id: string) => {
    const update = (prev: KDSTicket[]) =>
      prev.map(t => t.id === id ? { ...t, status: 'done' as const, completedAt: Date.now() } : t);
    setTickets(update);
    if (wsEnabled) setWsTickets(update);
  }, [wsEnabled, setWsTickets]);

  // 按档口过滤
  const filtered = selectedDept === 'all' ? tickets : tickets.filter(t => t.deptId === selectedDept);

  const pending = sortTickets(filtered.filter(t => t.status === 'pending'));
  const cooking = sortTickets(filtered.filter(t => t.status === 'cooking'));
  const done = filtered.filter(t => t.status === 'done')
    .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))
    .slice(0, 10);

  // 催单中的 ticket IDs（最近 5 分钟）
  const rushTicketIds = new Set(
    rushAlerts
      .filter(a => Date.now() - a.timestamp < 5 * 60 * 1000)
      .map(a => a.ticketId),
  );

  return (
    <div
      onTouchStart={handleFirstTouch}
      onClick={handleFirstTouch}
      style={{
        background: '#0A0A0A', color: '#E0E0E0', height: '100vh',
        display: 'flex', flexDirection: 'column',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      }}
    >
      {/* 重做弹窗 */}
      {remakeAlerts.length > 0 && (
        <RemakeOverlay
          alerts={remakeAlerts}
          onDismiss={dismissRemakeAlert}
        />
      )}

      {/* 超时告警条 */}
      {timeoutAlerts.length > 0 && (
        <div style={{
          background: '#A32D2D', padding: '10px 20px',
          display: 'flex', alignItems: 'center', gap: 12,
          animation: 'kds-pulse 1.5s infinite',
        }}>
          <span style={{ fontSize: 20, fontWeight: 'bold', color: '#fff' }}>
            超时告警
          </span>
          {timeoutAlerts.map((a, i) => (
            <span key={i} style={{ fontSize: 18, color: '#ffcccc' }}>
              {a.dish || a.ticketId || '未知菜品'} ({a.waitMinutes || '?'}分钟)
              <button
                onClick={() => dismissTimeoutAlert(i)}
                style={{
                  marginLeft: 8, padding: '4px 12px', background: 'rgba(255,255,255,0.2)',
                  color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer',
                  fontSize: 16, minHeight: 48, minWidth: 48,
                }}
              >
                知道了
              </button>
            </span>
          ))}
        </div>
      )}

      {/* 顶栏 */}
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 20px', background: '#111', borderBottom: '1px solid #222',
        minHeight: 56,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <span style={{ fontWeight: 'bold', fontSize: 24, color: '#FF6B35' }}>后厨看板</span>
          <DeptTabs selected={selectedDept} onChange={setSelectedDept} />
          {/* WebSocket 连接状态 */}
          {wsEnabled && (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontSize: 16, color: connected ? '#0F6E56' : '#A32D2D',
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: '50%',
                background: connected ? '#0F6E56' : '#A32D2D',
                display: 'inline-block',
                animation: connected ? undefined : 'kds-pulse 1.5s infinite',
              }} />
              {connected ? '已连接' : '断开'}
            </span>
          )}
          {/* 抢单模式切换 */}
          <button
            onClick={() => {
              const next = !grabMode;
              setGrabMode(next);
              localStorage.setItem('kds_grab_mode', next ? 'on' : 'off');
            }}
            style={{
              padding: '6px 14px',
              minHeight: 48,
              background: grabMode ? '#FF6B35' : '#1A1A1A',
              color: grabMode ? '#fff' : '#666',
              border: `1px solid ${grabMode ? '#FF6B35' : '#333'}`,
              borderRadius: 8,
              fontSize: 15,
              fontWeight: grabMode ? 700 : 400,
              cursor: 'pointer',
            }}
          >
            {grabMode ? '🏃 抢单中' : '抢单模式'}
          </button>

          {/* 批量合并视图切换 */}
          <button
            onClick={() => setBatchView(v => !v)}
            style={{
              padding: '6px 14px',
              minHeight: 48,
              background: batchView ? '#1A3050' : '#1A1A1A',
              color: batchView ? '#64D2FF' : '#666',
              border: `1px solid ${batchView ? '#1A6CF0' : '#333'}`,
              borderRadius: 8,
              fontSize: 15,
              fontWeight: batchView ? 700 : 400,
              cursor: 'pointer',
            }}
          >
            {batchView ? '合并视图' : '合并视图'}
          </button>

          {!wsEnabled && (
            <span style={{ fontSize: 16, color: '#BA7517' }}>
              离线模式（未配置 Mac mini 地址）
            </span>
          )}
        </div>
        <StatusBar items={[
          { label: '待制作', value: pending.length, color: '#BA7517' },
          { label: '制作中', value: cooking.length, color: '#1890ff' },
          { label: '已完成', value: done.length, color: '#0F6E56' },
        ]} />
      </header>

      {/* 三列看板 */}
      <div style={{ flex: 1, display: 'flex', gap: 2, overflow: 'hidden' }}>
        {/* 待制作 */}
        <BoardColumn title="待制作" count={pending.length} color="#BA7517" bgColor="#1a1a00">
          {pending.map(t => (
            <OrderTicketCard
              key={t.id}
              ticket={toTicketData(t)}
              kds
              now={now}
              isFlashing={rushTicketIds.has(t.id)}
              isPaused={pausedIds.has(t.id)}
              onStart={() => startCooking(t.id)}
              onGrab={grabMode && operatorId ? () => handleGrab(t.id) : undefined}
            />
          ))}
        </BoardColumn>

        {/* 制作中 */}
        <BoardColumn title="制作中" count={cooking.length} color="#1890ff" bgColor="#001a1a">
          {cooking.map(t => (
            <OrderTicketCard
              key={t.id}
              ticket={toTicketData(t)}
              kds
              now={now}
              isFlashing={rushTicketIds.has(t.id)}
              isPaused={pausedIds.has(t.id)}
              onComplete={() => completeCooking(t.id)}
              onPause={() => togglePause(t.id)}
            />
          ))}
        </BoardColumn>

        {/* 已完成 */}
        <BoardColumn title="已完成" count={done.length} color="#0F6E56" bgColor="#001a00">
          {done.map(t => (
            <DoneCard key={t.id} ticket={t} />
          ))}
        </BoardColumn>
      </div>

      {/* 动画 CSS（kds-border-flash / kds-rush-flash 已迁移到 OrderTicketCard.module.css） */}
      <style>{`
        @keyframes kds-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
        @keyframes kds-slide-in {
          from { opacity: 0; transform: translateY(-12px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

// ─── 重做弹窗 ───

function RemakeOverlay({ alerts, onDismiss }: {
  alerts: RemakeAlert[];
  onDismiss: (taskId: string) => void;
}) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: '#1a1a1a', borderRadius: 16, padding: 28,
        border: '3px solid #A32D2D', maxWidth: 480, width: '90%',
        animation: 'kds-slide-in 0.3s ease-out',
      }}>
        <div style={{
          fontSize: 28, fontWeight: 'bold', color: '#ff4d4f',
          marginBottom: 20, textAlign: 'center',
        }}>
          重做通知
        </div>
        {alerts.map(a => (
          <div key={a.taskId} style={{
            background: '#222', borderRadius: 12, padding: 16,
            marginBottom: 12, borderLeft: '6px solid #A32D2D',
          }}>
            <div style={{ fontSize: 22, fontWeight: 'bold', color: '#fff', marginBottom: 8 }}>
              {a.tableNumber && `${a.tableNumber} - `}{a.dishName}
              {a.remakeCount > 1 && (
                <span style={{ fontSize: 18, color: '#ff4d4f', marginLeft: 8 }}>
                  (第{a.remakeCount}次)
                </span>
              )}
            </div>
            <div style={{ fontSize: 18, color: '#BA7517', marginBottom: 12 }}>
              原因: {a.reason}
            </div>
            <button
              onClick={() => onDismiss(a.taskId)}
              style={{
                width: '100%', padding: '14px 0', background: '#A32D2D',
                color: '#fff', border: 'none', borderRadius: 8,
                fontSize: 20, fontWeight: 'bold', cursor: 'pointer',
                minHeight: 56,
              }}
              onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
              onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
            >
              收到，立即重做
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 档口选项卡 ───

const DEPT_OPTIONS = [
  { id: 'all', label: '全部' },
  { id: 'hot', label: '炒炉' },
  { id: 'cold', label: '凉菜' },
  { id: 'steam', label: '蒸菜' },
  { id: 'bar', label: '吧台' },
];

function DeptTabs({ selected, onChange }: { selected: string; onChange: (id: string) => void }) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      {DEPT_OPTIONS.map(d => (
        <button
          key={d.id}
          onClick={() => onChange(d.id)}
          style={{
            padding: '8px 20px',
            minHeight: 48, minWidth: 48,
            fontSize: 16,
            fontWeight: selected === d.id ? 'bold' : 'normal',
            color: selected === d.id ? '#fff' : '#888',
            background: selected === d.id ? '#FF6B35' : '#222',
            border: 'none', borderRadius: 8, cursor: 'pointer',
            transition: 'transform 200ms ease',
          }}
        >
          {d.label}
        </button>
      ))}
    </div>
  );
}

// ─── 看板列 ───

function BoardColumn({ title, count, color, bgColor, children }: {
  title: string; count: number; color: string; bgColor: string; children: React.ReactNode;
}) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      background: bgColor, overflow: 'hidden',
    }}>
      <div style={{
        textAlign: 'center', padding: '10px 0', fontSize: 20,
        fontWeight: 'bold', color, borderBottom: `3px solid ${color}`,
      }}>
        {title} ({count})
      </div>
      <div style={{
        flex: 1, overflowY: 'auto', padding: 10, display: 'flex',
        flexDirection: 'column', gap: 10,
        WebkitOverflowScrolling: 'touch',
      }}>
        {children}
      </div>
    </div>
  );
}

// (TicketCard removed — now uses shared OrderTicketCard from @tx-ds/biz)

// ─── 已完成卡片（简化） ───

function DoneCard({ ticket: t }: { ticket: KDSTicket }) {
  const totalMin = t.completedAt && t.startedAt
    ? Math.floor((t.completedAt - t.createdAt) / 60000)
    : 0;

  return (
    <div style={{
      background: '#111', borderRadius: 12, padding: 12,
      borderLeft: '6px solid #0F6E56', opacity: 0.75,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 22, fontWeight: 'bold', color: '#aaa' }}>{t.tableNo}</span>
          <span style={{ fontSize: 16, color: '#555' }}>#{t.orderNo}</span>
        </div>
        <span style={{ fontSize: 20, color: '#0F6E56', fontFamily: 'JetBrains Mono, monospace', fontWeight: 'bold' }}>
          {totalMin}'
        </span>
      </div>
      <div style={{ fontSize: 18, color: '#888' }}>
        {t.items.map(i => `${i.name}x${i.qty}`).join(' / ')}
      </div>
    </div>
  );
}

// ─── Mock Data（离线/未配置时使用） ───

const MOCK_NOW = Date.now();
const min = (m: number) => m * 60 * 1000;

const MOCK_TICKETS: KDSTicket[] = [
  { id: 't1', orderNo: '001', tableNo: 'A01', items: [{ name: '剁椒鱼头', qty: 1, notes: '少辣' }, { name: '小炒肉', qty: 1, notes: '' }], createdAt: MOCK_NOW - min(8), status: 'pending', priority: 'rush', deptId: 'hot' },
  { id: 't2', orderNo: '002', tableNo: 'A03', items: [{ name: '口味虾', qty: 2, notes: '中辣' }, { name: '炒青菜', qty: 1, notes: '' }], createdAt: MOCK_NOW - min(5), status: 'pending', priority: 'normal', deptId: 'hot' },
  { id: 't3', orderNo: '003', tableNo: 'B01', items: [{ name: '鱼头', qty: 2, notes: '' }, { name: '米饭', qty: 6, notes: '' }], createdAt: MOCK_NOW - min(18), status: 'cooking', priority: 'vip', deptId: 'hot', startedAt: MOCK_NOW - min(10) },
  { id: 't4', orderNo: '004', tableNo: 'B02', items: [{ name: '外婆鸡', qty: 1, notes: '多放辣' }], createdAt: MOCK_NOW - min(3), status: 'pending', priority: 'normal', deptId: 'steam' },
  { id: 't5', orderNo: '005', tableNo: 'A05', items: [{ name: '凉拌黄瓜', qty: 2, notes: '' }], createdAt: MOCK_NOW - min(32), status: 'cooking', priority: 'rush', deptId: 'cold', startedAt: MOCK_NOW - min(28) },
  { id: 't6', orderNo: '006', tableNo: 'C01', items: [{ name: '蒜蓉西兰花', qty: 1, notes: '' }], createdAt: MOCK_NOW - min(12), status: 'cooking', priority: 'normal', deptId: 'hot', startedAt: MOCK_NOW - min(8) },
  { id: 't7', orderNo: '007', tableNo: 'A02', items: [{ name: '酸菜鱼', qty: 1, notes: '微辣' }, { name: '辣椒炒肉', qty: 1, notes: '' }], createdAt: MOCK_NOW - min(2), status: 'pending', priority: 'vip', deptId: 'hot' },
  { id: 't8', orderNo: '008', tableNo: 'B03', items: [{ name: '红烧肉', qty: 1, notes: '' }], createdAt: MOCK_NOW - min(1), status: 'done', priority: 'normal', deptId: 'hot', startedAt: MOCK_NOW - min(15), completedAt: MOCK_NOW - min(1) },
  { id: 't9', orderNo: '009', tableNo: 'C02', items: [{ name: '蒸鲈鱼', qty: 1, notes: '' }], createdAt: MOCK_NOW - min(20), status: 'done', priority: 'normal', deptId: 'steam', startedAt: MOCK_NOW - min(18), completedAt: MOCK_NOW - min(2) },
];
