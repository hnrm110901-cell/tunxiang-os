/**
 * KitchenBoard -- 档口任务看板（核心页面）
 *
 * 布局：预警条 + 统计栏 / 水平滚动工单卡片区（240px/张，gap≥12px）
 * 使用 TXKDSTicket 组件：倒计时实时更新，超时整卡红底白字，左滑完成
 * WebSocket 实时推送：连接 Mac mini /ws/kds/{stationId}
 * 深色背景，触控优化（最小48px按钮，最小20px菜品字体）
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { TXKDSTicket, type TXKDSTicketItem } from '@tx/touch';
import { useKdsWebSocket, type KDSTicket, type RemakeAlert } from '../hooks/useKdsWebSocket';
import { warmUpAudio } from '../utils/audio';
import { pauseTicket, resumeTicket, grabTicket } from '../api/kdsOpsApi';
import { StatusBar, OrderTicketCard } from '@tx-ds/biz';
import type { OrderTicketData } from '@tx-ds/biz';
import { RemakeOverlay } from '../components/RemakeOverlay';
import { useKDSRules } from '../hooks/useKDSRules';
import { getTimeLevelFromRules, getChannelColor, type KDSRuleConfig } from '../api/kdsRulesApi';

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
  // localStorage 读取只在 mount 时执行一次
  const [config] = useState(getKdsConfig);
  const wsEnabled = !!config.host;

  // 加载门店KDS规则配置（storeId 从 localStorage 读取，或使用默认）
  const storeId = localStorage.getItem('kds_store_id') || null;
  const { rules } = useKDSRules(storeId);

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

  // 单一数据源：WS 数据或离线 mock
  const [offlineTickets, setOfflineTickets] = useState<KDSTicket[]>(
    () => wsEnabled ? [] : MOCK_TICKETS,
  );
  const tickets = wsEnabled ? wsTickets : offlineTickets;
  const setTickets = wsEnabled ? setWsTickets : setOfflineTickets;

  // 当 WS 数据更新时同步到本地
  useEffect(() => {
    if (wsEnabled && wsTickets.length > 0) {
      setTickets(wsTickets);
    }
  }, [wsEnabled, wsTickets]);

  // 注意：倒计时由 TXKDSTicket 内部每秒更新，无需外部 tick
  const [now, setNow] = useState(Date.now());
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

  // 每秒刷新倒计时（TXKDSTicket 内部也有独立更新）
  useEffect(() => {
    const timer = setInterval(() => {
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
    setTickets(prev => prev.map(t => t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t));
  }, [setTickets]);

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
      setTickets(prev => prev.map(t => t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '抢单失败';
      alert(msg);
    }
  }, [operatorId, setTickets]);

  // 完成出品
  const completeCooking = useCallback((id: string) => {
    setTickets(prev => prev.map(t => t.id === id ? { ...t, status: 'done' as const, completedAt: Date.now() } : t));
  }, [setTickets]);

  // 按档口过滤
  const filtered = selectedDept === 'all' ? tickets : tickets.filter(t => t.deptId === selectedDept);

  const pending = sortTickets(filtered.filter(t => t.status === 'pending'));
  const cooking = sortTickets(filtered.filter(t => t.status === 'cooking'));
  const done = filtered.filter(t => t.status === 'done')
    .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))
    .slice(0, 10);

  // 催单中的 ticket IDs（最近 5 分钟），rushAlerts 变化时才重建 Set
  const rushTicketIds = useMemo(
    () => new Set(rushAlerts.filter(a => Date.now() - a.timestamp < 5 * 60 * 1000).map(a => a.ticketId)),
    [rushAlerts],
  );

  // 平均出餐时间（已完成工单的总时长均值，单位：分钟）
  const avgCookMin = useMemo(() => {
    if (done.length === 0) return 0;
    const valid = done.filter(t => t.completedAt);
    if (valid.length === 0) return 0;
    return Math.round(
      valid.reduce((sum, t) => sum + (t.completedAt! - t.createdAt) / 60000, 0) / valid.length,
    );
  }, [done]);

  // 活跃工单（pending + cooking）按水平滚动排列，只在依赖变化时重算
  const activeTickets = useMemo(() => [
    ...sortTickets(pending.map(t => ({ ...t, _col: 'pending' as const }))),
    ...sortTickets(cooking.map(t => ({ ...t, _col: 'cooking' as const }))),
  ], [pending, cooking]);

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
            合并视图
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
        {/* 统计栏：待出单数 + 平均出餐时间 */}
        <div style={{ display: 'flex', gap: 32, fontSize: 18, alignItems: 'center' }}>
          <span>
            待出 <b style={{ color: '#BA7517', fontSize: 28, fontFamily: 'JetBrains Mono, monospace' }}>{pending.length + cooking.length}</b> 单
          </span>
          <span>
            平均出餐 <b style={{ color: '#0F6E56', fontSize: 28, fontFamily: 'JetBrains Mono, monospace' }}>{avgCookMin}</b> 分钟
          </span>
          <span>
            已完成 <b style={{ color: '#555', fontSize: 24, fontFamily: 'JetBrains Mono, monospace' }}>{done.length}</b>
          </span>
        </div>
      </header>

      {/* KDS 工单区：水平滚动，每张卡片 240px，gap 16px */}
      <div style={{
        flex: 1, overflowX: 'auto', overflowY: 'hidden',
        display: 'flex', flexDirection: 'row', alignItems: 'flex-start',
        gap: 16, padding: '16px 20px',
        WebkitOverflowScrolling: 'touch',
      }}>
        {activeTickets.length === 0 && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, color: '#555',
          }}>
            暂无工单
          </div>
        )}
        {activeTickets.map(t => {
          const isPending = t._col === 'pending';
          const isPaused = pausedIds.has(t.id);
          // 将 KDSTicket.items 映射为 TXKDSTicketItem
          const txItems: TXKDSTicketItem[] = t.items.map(item => ({
            name: item.name,
            qty: item.qty,
            spec: item.notes || undefined,
            priority: (rushTicketIds.has(t.id) || t.priority === 'rush') ? 'rush' : 'normal',
          }));
          return (
            <div key={t.id} style={{ display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
              {/* TXKDSTicket 卡片：倒计时、超时红底、左滑完成 */}
              <TXKDSTicket
                orderId={t.orderNo}
                tableNo={t.tableNo}
                items={txItems}
                createdAt={t.createdAt}
                timeLimit={config.timeoutMinutes}
                isVip={t.priority === 'vip'}
                onComplete={() => isPending ? startCooking(t.id) : completeCooking(t.id)}
                onRush={() => grabMode && operatorId ? handleGrab(t.id) : startCooking(t.id)}
              />
              {/* 状态标签 + 停菜/操作按钮（卡片外补充） */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: 240 }}>
                {/* 状态徽章 */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  padding: '4px 0', borderRadius: 6,
                  background: isPending ? '#1a1a00' : '#001a1a',
                  fontSize: 16, fontWeight: 'bold',
                  color: isPending ? '#BA7517' : '#4A9EFF',
                  border: `1px solid ${isPending ? '#BA7517' : '#4A9EFF'}`,
                }}>
                  {isPending ? '待制作' : '制作中'}
                </div>

                {/* 停菜标记 */}
                {isPaused && (
                  <div style={{
                    background: '#2A2A00', border: '1px solid #666600',
                    borderRadius: 6, padding: '4px 10px',
                    fontSize: 16, color: '#CCCC00', fontWeight: 600, textAlign: 'center',
                  }}>
                    已停菜
                  </div>
                )}

                {/* 操作按钮 */}
                <div style={{ display: 'flex', gap: 8 }}>
                  {isPending && grabMode && operatorId ? (
                    <button
                      onClick={() => handleGrab(t.id)}
                      style={{
                        flex: 1, padding: '14px 0', border: 'none', borderRadius: 8,
                        background: '#FF6B35', color: '#fff',
                        fontSize: 20, fontWeight: 'bold', cursor: 'pointer', minHeight: 56,
                      }}
                      onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                      onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
                    >
                      抢单
                    </button>
                  ) : (
                    <button
                      onClick={() => isPending ? startCooking(t.id) : completeCooking(t.id)}
                      disabled={isPaused}
                      style={{
                        flex: 1, padding: '14px 0', border: 'none', borderRadius: 8,
                        background: isPaused ? '#2A2A2A' : isPending ? '#4A9EFF' : '#0F6E56',
                        color: '#fff', fontSize: 20, fontWeight: 'bold',
                        cursor: isPaused ? 'not-allowed' : 'pointer',
                        opacity: isPaused ? 0.5 : 1, minHeight: 56,
                      }}
                      onTouchStart={e => !isPaused && (e.currentTarget.style.transform = 'scale(0.97)')}
                      onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
                    >
                      {isPending ? '开始制作' : '完成出品'}
                    </button>
                  )}
                  {/* 停菜/恢复（仅制作中） */}
                  {!isPending && (
                    <button
                      onClick={() => togglePause(t.id)}
                      style={{
                        padding: '14px 14px', border: `1px solid ${isPaused ? '#666600' : '#333'}`,
                        borderRadius: 8,
                        background: isPaused ? '#2A2A00' : '#1A1A1A',
                        color: isPaused ? '#CCCC00' : '#666',
                        fontSize: 20, fontWeight: 'bold',
                        cursor: 'pointer', minHeight: 56, minWidth: 56,
                      } as React.CSSProperties}
                      onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                      onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
                      title={isPaused ? '恢复出品' : '停菜'}
                    >
                      {isPaused ? '▶' : '⏸'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* 已完成区域：分隔线 + 简化卡片 */}
        {done.length > 0 && (
          <>
            <div style={{
              width: 2, alignSelf: 'stretch', background: '#222', flexShrink: 0, margin: '0 4px',
            }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 }}>
              <div style={{ fontSize: 18, color: '#555', fontWeight: 'bold', textAlign: 'center', padding: '4px 0' }}>
                已完成 ({done.length})
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                {done.map(t => <DoneCard key={t.id} ticket={t} />)}
              </div>
            </div>
          </>
        )}
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

// ─── 档口选项卡 ───
// (BoardColumn and TicketCard replaced by TXKDSTicket from @tx/touch)

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

// (BoardColumn and TicketCard replaced by TXKDSTicket horizontal layout)

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
