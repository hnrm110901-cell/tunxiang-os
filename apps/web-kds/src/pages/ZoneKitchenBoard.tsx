/**
 * ZoneKitchenBoard — 包厢/大厅分区 KDS 看板
 *
 * 复用 KitchenBoard 核心逻辑，新增：
 *   - 顶部区域 Tab：全部 | 包厢 | 大厅
 *   - URL 参数 ?zone=vip|hall|all 持久化区域选择
 *   - 区域标签颜色：包厢=金色 #FFD700，大厅=蓝色 #4A9EFF
 *   - 统计栏：各区域催单数/超时数独立显示
 *
 * 深色主题，所有按钮 ≥56px，字体 ≥16px
 */
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useKdsWebSocket, type KDSTicket, type RemakeAlert } from '../hooks/useKdsWebSocket';
import { warmUpAudio } from '../utils/audio';

// ─── 区域类型 ───

type Zone = 'all' | 'vip' | 'hall';

const ZONE_CONFIG: Record<Zone, { label: string; color: string; bg: string }> = {
  all:  { label: '全部',    color: '#E0E0E0', bg: '#333' },
  vip:  { label: '包厢',    color: '#1a1a00', bg: '#FFD700' },
  hall: { label: '大厅',    color: '#fff',    bg: '#4A9EFF' },
};

// ─── 区域识别（根据桌台号前缀推断） ───

function inferZone(tableNo: string): Zone {
  const upper = tableNo.toUpperCase();
  if (
    upper.includes('包厢') || upper.includes('VIP') ||
    upper.includes('包房') || upper.startsWith('V') ||
    upper.startsWith('P')
  ) {
    return 'vip';
  }
  return 'hall';
}

// ─── KDS 配置 ───

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

// ─── 超时阈值 ───

function getTimeoutThresholds() {
  const critical = parseInt(localStorage.getItem('kds_timeout_minutes') || '25', 10);
  return { warn: Math.max(Math.floor(critical * 0.6), 5), critical };
}

// ─── 排序 ───

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

// ─── 时间格式 ───

function elapsedMin(ts: number): number {
  return Math.floor((Date.now() - ts) / 60000);
}

function formatElapsed(ts: number): string {
  const total = Math.floor((Date.now() - ts) / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

type TimeLevel = 'normal' | 'warning' | 'critical';

function getTimeLevel(ts: number): TimeLevel {
  const { warn, critical } = getTimeoutThresholds();
  const m = elapsedMin(ts);
  if (m >= critical) return 'critical';
  if (m >= warn) return 'warning';
  return 'normal';
}

const TIME_COLORS: Record<TimeLevel, string> = {
  normal: '#0F6E56',
  warning: '#BA7517',
  critical: '#A32D2D',
};

// ─── Mock 数据 ───

const _now = Date.now();
const _min = (m: number) => m * 60 * 1000;

const MOCK_TICKETS: KDSTicket[] = [
  { id: 't1', orderNo: '001', tableNo: '包厢3号', items: [{ name: '烤鸭', qty: 1, notes: '' }, { name: '口味虾', qty: 2, notes: '中辣' }], createdAt: _now - _min(8), status: 'pending', priority: 'vip', deptId: 'roast' },
  { id: 't2', orderNo: '002', tableNo: '包厢1号', items: [{ name: '剁椒鱼头', qty: 1, notes: '少辣' }], createdAt: _now - _min(5), status: 'pending', priority: 'rush', deptId: 'steam' },
  { id: 't3', orderNo: '003', tableNo: '大厅A05', items: [{ name: '小炒肉', qty: 1, notes: '' }, { name: '炒青菜', qty: 1, notes: '' }], createdAt: _now - _min(12), status: 'cooking', priority: 'normal', deptId: 'wok', startedAt: _now - _min(8) },
  { id: 't4', orderNo: '004', tableNo: '大厅B02', items: [{ name: '外婆鸡', qty: 1, notes: '' }], createdAt: _now - _min(3), status: 'pending', priority: 'normal', deptId: 'steam' },
  { id: 't5', orderNo: '005', tableNo: '包厢2号', items: [{ name: '红烧肉', qty: 1, notes: '' }, { name: '蒸鲈鱼', qty: 1, notes: '' }], createdAt: _now - _min(18), status: 'cooking', priority: 'vip', deptId: 'stew', startedAt: _now - _min(12) },
  { id: 't6', orderNo: '006', tableNo: '大厅C01', items: [{ name: '凉拌黄瓜', qty: 2, notes: '' }], createdAt: _now - _min(2), status: 'pending', priority: 'normal', deptId: 'cold' },
  { id: 't7', orderNo: '007', tableNo: '大厅A03', items: [{ name: '酸菜鱼', qty: 1, notes: '微辣' }], createdAt: _now - _min(20), status: 'done', priority: 'normal', deptId: 'wok', startedAt: _now - _min(18), completedAt: _now - _min(2) },
];

// ─── 主组件 ───

export function ZoneKitchenBoard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const zoneParam = (searchParams.get('zone') as Zone) || 'all';
  const [zone, setZone] = useState<Zone>(
    ['all', 'vip', 'hall'].includes(zoneParam) ? zoneParam : 'all'
  );

  const config = getKdsConfig();
  const wsEnabled = !!config.host;

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

  const [tickets, setTickets] = useState<KDSTicket[]>(() =>
    wsEnabled ? [] : MOCK_TICKETS,
  );
  const [tick, setTick] = useState(0);
  const [audioWarmed, setAudioWarmed] = useState(false);

  useEffect(() => {
    if (wsEnabled && wsTickets.length > 0) setTickets(wsTickets);
  }, [wsEnabled, wsTickets]);

  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const handleFirstTouch = useCallback(() => {
    if (!audioWarmed) {
      warmUpAudio();
      setAudioWarmed(true);
    }
  }, [audioWarmed]);

  // 区域 Tab 切换
  const handleZoneChange = useCallback((z: Zone) => {
    setZone(z);
    setSearchParams({ zone: z });
  }, [setSearchParams]);

  // 开始/完成制作
  const startCooking = useCallback((id: string) => {
    const update = (prev: KDSTicket[]) =>
      prev.map(t => t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t);
    setTickets(update);
    if (wsEnabled) setWsTickets(update);
  }, [wsEnabled, setWsTickets]);

  const completeCooking = useCallback((id: string) => {
    const update = (prev: KDSTicket[]) =>
      prev.map(t => t.id === id ? { ...t, status: 'done' as const, completedAt: Date.now() } : t);
    setTickets(update);
    if (wsEnabled) setWsTickets(update);
  }, [wsEnabled, setWsTickets]);

  // 按区域过滤
  const filteredByZone = zone === 'all'
    ? tickets
    : tickets.filter(t => inferZone(t.tableNo) === zone);

  const pending = sortTickets(filteredByZone.filter(t => t.status === 'pending'));
  const cooking = sortTickets(filteredByZone.filter(t => t.status === 'cooking'));
  const done = filteredByZone
    .filter(t => t.status === 'done')
    .sort((a, b) => (b.completedAt || 0) - (a.completedAt || 0))
    .slice(0, 10);

  // 各区域统计
  const zoneStats = (['vip', 'hall'] as Zone[]).map(z => {
    const zTickets = tickets.filter(t => inferZone(t.tableNo) === z);
    const rushNow = rushAlerts.filter(a =>
      Date.now() - a.timestamp < 5 * 60 * 1000 &&
      zTickets.some(t => t.id === a.ticketId)
    ).length;
    const timeoutNow = timeoutAlerts.filter(a =>
      zTickets.some(t => t.id === a.ticketId)
    ).length;
    return { zone: z, rush: rushNow, timeout: timeoutNow, total: zTickets.filter(t => t.status !== 'done').length };
  });

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
        <RemakeOverlay alerts={remakeAlerts} onDismiss={dismissRemakeAlert} />
      )}

      {/* 超时告警条 */}
      {timeoutAlerts.length > 0 && (
        <div style={{
          background: '#A32D2D', padding: '10px 20px',
          display: 'flex', alignItems: 'center', gap: 12,
          animation: 'zkb-pulse 1.5s infinite',
        }}>
          <span style={{ fontSize: 20, fontWeight: 'bold', color: '#fff' }}>超时告警</span>
          {timeoutAlerts.map((a, i) => (
            <span key={i} style={{ fontSize: 18, color: '#ffcccc' }}>
              {a.dish || '未知菜品'} ({a.waitMinutes || '?'}分钟)
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
        display: 'flex', flexDirection: 'column', gap: 8,
        padding: '10px 20px', background: '#111', borderBottom: '1px solid #222',
        minHeight: 80,
      }}>
        {/* 行1: 标题 + 区域 Tab + 连接状态 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{ fontWeight: 'bold', fontSize: 24, color: '#FF6B35' }}>分区看板</span>
            {/* 区域 Tab */}
            <div style={{ display: 'flex', gap: 6 }}>
              {(['all', 'vip', 'hall'] as Zone[]).map(z => {
                const cfg = ZONE_CONFIG[z];
                const active = zone === z;
                return (
                  <button
                    key={z}
                    onClick={() => handleZoneChange(z)}
                    style={{
                      padding: '8px 20px', minHeight: 48, minWidth: 48,
                      fontSize: 17, fontWeight: active ? 'bold' : 'normal',
                      color: active ? cfg.color : '#888',
                      background: active ? cfg.bg : '#222',
                      border: 'none', borderRadius: 8, cursor: 'pointer',
                      transition: 'all 200ms ease',
                    }}
                  >
                    {cfg.label}
                  </button>
                );
              })}
            </div>

            {/* WS 状态 */}
            {wsEnabled && (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontSize: 16, color: connected ? '#0F6E56' : '#A32D2D',
              }}>
                <span style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: connected ? '#0F6E56' : '#A32D2D',
                  display: 'inline-block',
                  animation: connected ? undefined : 'zkb-pulse 1.5s infinite',
                }} />
                {connected ? '已连接' : '断开'}
              </span>
            )}
            {!wsEnabled && (
              <span style={{ fontSize: 16, color: '#BA7517' }}>离线模式</span>
            )}
          </div>

          {/* 全局统计 */}
          <div style={{ display: 'flex', gap: 28, fontSize: 18 }}>
            <span>待制作 <b style={{ color: '#BA7517', fontSize: 26, fontFamily: 'JetBrains Mono, monospace' }}>{pending.length}</b></span>
            <span>制作中 <b style={{ color: '#1890ff', fontSize: 26, fontFamily: 'JetBrains Mono, monospace' }}>{cooking.length}</b></span>
            <span>已完成 <b style={{ color: '#0F6E56', fontSize: 26, fontFamily: 'JetBrains Mono, monospace' }}>{done.length}</b></span>
          </div>
        </div>

        {/* 行2: 各区域催单/超时独立统计 */}
        <div style={{ display: 'flex', gap: 24 }}>
          {zoneStats.map(stat => (
            <div key={stat.zone} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ZoneTag zone={stat.zone as Zone} size={16} />
              <span style={{ fontSize: 16, color: '#888' }}>
                {stat.total}单
                {stat.rush > 0 && (
                  <span style={{ color: '#ff4d4f', marginLeft: 6, fontWeight: 'bold', animation: 'zkb-pulse 1s infinite' }}>
                    催{stat.rush}
                  </span>
                )}
                {stat.timeout > 0 && (
                  <span style={{ color: '#A32D2D', marginLeft: 6, fontWeight: 'bold' }}>
                    超时{stat.timeout}
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      </header>

      {/* 三列看板 */}
      <div style={{ flex: 1, display: 'flex', gap: 2, overflow: 'hidden' }}>
        <ZoneBoardColumn title="待制作" count={pending.length} color="#BA7517" bgColor="#1a1a00">
          {pending.map(t => (
            <ZoneTicketCard
              key={t.id}
              ticket={t}
              actionLabel="开始制作"
              actionColor="#1890ff"
              onAction={() => startCooking(t.id)}
              tick={tick}
              isFlashing={rushTicketIds.has(t.id)}
            />
          ))}
        </ZoneBoardColumn>

        <ZoneBoardColumn title="制作中" count={cooking.length} color="#1890ff" bgColor="#001a1a">
          {cooking.map(t => (
            <ZoneTicketCard
              key={t.id}
              ticket={t}
              actionLabel="完成出品"
              actionColor="#0F6E56"
              onAction={() => completeCooking(t.id)}
              tick={tick}
              isFlashing={rushTicketIds.has(t.id)}
            />
          ))}
        </ZoneBoardColumn>

        <ZoneBoardColumn title="已完成" count={done.length} color="#0F6E56" bgColor="#001a00">
          {done.map(t => (
            <ZoneDoneCard key={t.id} ticket={t} />
          ))}
        </ZoneBoardColumn>
      </div>

      {/* 动画 CSS */}
      <style>{`
        @keyframes zkb-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
        @keyframes zkb-border-flash {
          0%, 100% { border-color: #A32D2D; }
          50% { border-color: #ff4d4f; }
        }
        @keyframes zkb-rush-flash {
          0%, 100% { box-shadow: 0 0 0 0 rgba(255, 77, 79, 0); }
          50% { box-shadow: 0 0 16px 4px rgba(255, 77, 79, 0.6); }
        }
        @keyframes zkb-slide-in {
          from { opacity: 0; transform: translateY(-12px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

// ─── 区域标签 ───

function ZoneTag({ zone, size = 14 }: { zone: Zone; size?: number }) {
  if (zone === 'all') return null;
  const cfg = ZONE_CONFIG[zone];
  return (
    <span style={{
      fontSize: size, padding: '2px 8px', borderRadius: 5,
      background: cfg.bg, color: cfg.color,
      fontWeight: 'bold', display: 'inline-block',
    }}>
      {cfg.label}
    </span>
  );
}

// ─── 看板列 ───

function ZoneBoardColumn({ title, count, color, bgColor, children }: {
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
        flex: 1, overflowY: 'auto', padding: 10,
        display: 'flex', flexDirection: 'column', gap: 10,
        WebkitOverflowScrolling: 'touch',
      }}>
        {children}
      </div>
    </div>
  );
}

// ─── 工单卡片（带区域标签） ───

function ZoneTicketCard({ ticket: t, actionLabel, actionColor, onAction, tick: _tick, isFlashing }: {
  ticket: KDSTicket; actionLabel: string; actionColor: string;
  onAction: () => void; tick: number; isFlashing?: boolean;
}) {
  const level = getTimeLevel(t.createdAt);
  const elapsed = formatElapsed(t.createdAt);
  const isRush = t.priority === 'rush';
  const isVip = t.priority === 'vip';
  const isCritical = level === 'critical';
  const ticketZone = inferZone(t.tableNo);

  const borderColor = isCritical
    ? '#A32D2D'
    : isRush ? '#BA7517' : isVip ? '#722ed1' : '#333';

  return (
    <div style={{
      background: isCritical ? '#1a0505' : '#111',
      borderRadius: 12, padding: 14,
      borderLeft: `6px solid ${borderColor}`,
      animation: isCritical
        ? 'zkb-border-flash 1.5s infinite'
        : isFlashing || isRush
          ? 'zkb-rush-flash 1s infinite'
          : undefined,
    }}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>{t.tableNo}</span>
          {/* 区域标签 */}
          <ZoneTag zone={ticketZone} size={16} />
          <span style={{ fontSize: 16, color: '#666' }}>#{t.orderNo}</span>
          {isRush && (
            <span style={{
              fontSize: 16, padding: '2px 10px', borderRadius: 6,
              background: '#A32D2D', color: '#fff', fontWeight: 'bold',
              animation: 'zkb-pulse 1s infinite',
            }}>催</span>
          )}
          {isVip && (
            <span style={{
              fontSize: 16, padding: '2px 10px', borderRadius: 6,
              background: 'linear-gradient(135deg, #C5A347, #E8D48B)',
              color: '#1a1a00', fontWeight: 'bold',
            }}>VIP</span>
          )}
        </div>
        <div style={{
          fontSize: 28, fontWeight: 'bold',
          color: TIME_COLORS[level],
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          {elapsed}
        </div>
      </div>

      {/* 菜品列表 */}
      {t.items.map((item, i) => (
        <div key={i} style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '4px 0', fontSize: 20, fontWeight: 'bold',
        }}>
          <span style={{ flex: 1 }}>
            {item.name}
            {item.notes && (
              <span style={{ fontSize: 16, color: '#A32D2D', marginLeft: 6, fontWeight: 'normal' }}>
                ({item.notes})
              </span>
            )}
          </span>
          <span style={{ color: '#FF6B35', fontSize: 22, minWidth: 50, textAlign: 'right' }}>
            x{item.qty}
          </span>
        </div>
      ))}

      {/* 操作按钮 */}
      <button
        onClick={onAction}
        style={{
          width: '100%', marginTop: 10, padding: '14px 0',
          border: 'none', borderRadius: 8,
          background: actionColor, color: '#fff',
          fontSize: 20, fontWeight: 'bold',
          cursor: 'pointer', minHeight: 56,
          transition: 'transform 200ms ease',
        }}
        onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
        onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
      >
        {actionLabel}
      </button>
    </div>
  );
}

// ─── 已完成卡片 ───

function ZoneDoneCard({ ticket: t }: { ticket: KDSTicket }) {
  const totalMin = t.completedAt && t.startedAt
    ? Math.floor((t.completedAt - t.createdAt) / 60000)
    : 0;
  const ticketZone = inferZone(t.tableNo);

  return (
    <div style={{
      background: '#111', borderRadius: 12, padding: 12,
      borderLeft: '6px solid #0F6E56', opacity: 0.75,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 22, fontWeight: 'bold', color: '#aaa' }}>{t.tableNo}</span>
          <ZoneTag zone={ticketZone} size={14} />
          <span style={{ fontSize: 16, color: '#555' }}>#{t.orderNo}</span>
        </div>
        <span style={{
          fontSize: 20, color: '#0F6E56',
          fontFamily: 'JetBrains Mono, monospace', fontWeight: 'bold',
        }}>
          {totalMin}'
        </span>
      </div>
      <div style={{ fontSize: 18, color: '#888' }}>
        {t.items.map(i => `${i.name}x${i.qty}`).join(' / ')}
      </div>
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
        animation: 'zkb-slide-in 0.3s ease-out',
      }}>
        <div style={{
          fontSize: 28, fontWeight: 'bold', color: '#ff4d4f',
          marginBottom: 20, textAlign: 'center',
        }}>重做通知</div>
        {alerts.map(a => (
          <div key={a.taskId} style={{
            background: '#222', borderRadius: 12, padding: 16,
            marginBottom: 12, borderLeft: '6px solid #A32D2D',
          }}>
            <div style={{ fontSize: 22, fontWeight: 'bold', color: '#fff', marginBottom: 8 }}>
              {a.tableNumber && `${a.tableNumber} - `}{a.dishName}
              {a.remakeCount > 1 && (
                <span style={{ fontSize: 18, color: '#ff4d4f', marginLeft: 8 }}>(第{a.remakeCount}次)</span>
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
                fontSize: 20, fontWeight: 'bold', cursor: 'pointer', minHeight: 56,
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
