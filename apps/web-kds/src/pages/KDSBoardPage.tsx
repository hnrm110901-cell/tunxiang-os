/**
 * KDS 出餐看板 — 演示就绪版（Demo-Ready）
 *
 * 布局：全屏横屏，顶栏 + 水平滚动工单卡片区
 * 工单卡片：宽 240px 固定，颜色编码时间状态
 * 完成操作：左滑 72px 触发 / 点击按钮
 *
 * 数据来源：
 *   1. ?demo=true  → 演示模式，模拟数据 + 每 30 秒自动生成新工单
 *   2. 有 WS 配置  → 连接 Mac mini WebSocket 实时推送
 *   3. 兜底        → 每 3 秒轮询 /api/v1/kds/queue
 *   4. 连接失败    → 3-5 张模拟工单（1 超时、1 即将超时、其余正常）
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useSwipe } from '../hooks/useSwipe';
import { fetchTicketQueue, startTicket, completeTicket } from '../api/kdsOpsApi';
import { warmUpAudio, playNewOrder, playTimeout } from '../utils/audio';

// ─── CSS Variables ──────────────────────────────────────

const CSS_VARS = `
  :root {
    --tx-primary: #FF6B35;
    --tx-success: #0F6E56;
    --tx-warning: #BA7517;
    --tx-danger: #A32D2D;
    --tx-bg-dark: #0D1117;
    --tx-bg-card: #111827;
    --tx-border: rgba(255,255,255,0.08);
    --tx-text-1: #F0F0F0;
    --tx-text-2: rgba(255,255,255,0.55);
  }
  @keyframes kds-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.65; }
  }
  @keyframes kds-border-flash {
    0%, 100% { border-color: #A32D2D; box-shadow: 0 0 0 0 rgba(163,45,45,0); }
    50% { border-color: #ff4d4f; box-shadow: 0 0 20px 4px rgba(163,45,45,0.5); }
  }
  @keyframes kds-card-in {
    from { opacity: 0; transform: translateY(-16px) scale(0.96); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }
  @keyframes kds-warn-flash {
    0%, 100% { border-color: #BA7517; }
    50% { border-color: #f5a623; }
  }
`;

// ─── 类型 ─────────────────────────────────────────────

interface TicketItem {
  name: string;
  qty: number;
  notes: string;
}

interface DemoTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  items: TicketItem[];
  createdAt: number; // timestamp ms
  status: 'pending' | 'cooking' | 'done';
  priority: 'normal' | 'rush' | 'vip';
  timeLimit: number; // minutes
  startedAt?: number;
}

// ─── 时间状态 ──────────────────────────────────────────

type TimeStatus = 'normal' | 'warning' | 'overtime';

function getTimeStatus(createdAt: number, timeLimit: number): TimeStatus {
  const elapsedMin = (Date.now() - createdAt) / 60000;
  if (elapsedMin >= timeLimit) return 'overtime';
  if (elapsedMin >= timeLimit * 0.5) return 'warning';
  return 'normal';
}

function formatElapsed(createdAt: number): string {
  const totalSec = Math.floor((Date.now() - createdAt) / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ─── 门店配置 ─────────────────────────────────────────

const STORE_MAP: Record<string, string> = {
  wh: '文化城店',
  lx: '浏小鲜',
  ya: '永安店',
};

// ─── 模拟数据工厂 ──────────────────────────────────────

const MENU_ITEMS = [
  { name: '剁椒鱼头', notes: '少辣' },
  { name: '小炒肉', notes: '多放辣' },
  { name: '口味虾', notes: '中辣' },
  { name: '蒜蓉西兰花', notes: '' },
  { name: '酸菜鱼', notes: '微辣' },
  { name: '外婆鸡', notes: '' },
  { name: '红烧肉', notes: '' },
  { name: '蒸鲈鱼', notes: '' },
  { name: '炒青菜', notes: '' },
  { name: '凉拌黄瓜', notes: '' },
  { name: '米饭', notes: '' },
  { name: '毛血旺', notes: '加辣' },
  { name: '土豆丝', notes: '' },
  { name: '番茄炒蛋', notes: '' },
];

const TABLES = ['A01', 'A02', 'A03', 'B01', 'B02', 'B03', 'C01', 'C02', 'D01', 'D02'];
const PRIORITIES: DemoTicket['priority'][] = ['normal', 'normal', 'normal', 'vip', 'rush'];

let _ticketSeq = 10;

function makeTicket(opts: Partial<DemoTicket> & { createdAtOffsetMin: number }): DemoTicket {
  const id = `t${++_ticketSeq}`;
  const itemCount = Math.floor(Math.random() * 3) + 1;
  const picked = [...MENU_ITEMS].sort(() => Math.random() - 0.5).slice(0, itemCount);
  return {
    id,
    orderNo: String(_ticketSeq).padStart(3, '0'),
    tableNo: TABLES[Math.floor(Math.random() * TABLES.length)],
    items: picked.map((m) => ({ name: m.name, qty: Math.floor(Math.random() * 2) + 1, notes: m.notes })),
    createdAt: Date.now() - opts.createdAtOffsetMin * 60 * 1000,
    status: opts.status ?? 'pending',
    priority: opts.priority ?? PRIORITIES[Math.floor(Math.random() * PRIORITIES.length)],
    timeLimit: 20,
    startedAt: opts.startedAt,
    ...opts,
  };
}

function buildMockTickets(): DemoTicket[] {
  return [
    makeTicket({ createdAtOffsetMin: 25, status: 'cooking', priority: 'normal', tableNo: 'A01',
      items: [{ name: '剁椒鱼头', qty: 1, notes: '少辣' }, { name: '小炒肉', qty: 1, notes: '' }],
      startedAt: Date.now() - 22 * 60 * 1000 }), // 超时
    makeTicket({ createdAtOffsetMin: 12, status: 'cooking', priority: 'vip', tableNo: 'B01',
      items: [{ name: '口味虾', qty: 2, notes: '中辣' }, { name: '米饭', qty: 4, notes: '' }],
      startedAt: Date.now() - 10 * 60 * 1000 }), // 即将超时
    makeTicket({ createdAtOffsetMin: 5, status: 'pending', priority: 'normal', tableNo: 'A03',
      items: [{ name: '蒜蓉西兰花', qty: 1, notes: '' }, { name: '酸菜鱼', qty: 1, notes: '微辣' }] }),
    makeTicket({ createdAtOffsetMin: 3, status: 'pending', priority: 'rush', tableNo: 'C01',
      items: [{ name: '外婆鸡', qty: 1, notes: '' }] }),
    makeTicket({ createdAtOffsetMin: 1, status: 'pending', priority: 'normal', tableNo: 'D02',
      items: [{ name: '番茄炒蛋', qty: 2, notes: '' }, { name: '土豆丝', qty: 1, notes: '' }] }),
  ];
}

// ─── 主组件 ───────────────────────────────────────────

export function KDSBoardPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const isDemo = searchParams.get('demo') === 'true';
  const storeId = searchParams.get('store') || 'wh';
  const storeName = STORE_MAP[storeId] || '未知门店';

  const [tickets, setTickets] = useState<DemoTicket[]>(() => buildMockTickets());
  const [tick, setTick] = useState(0); // 每秒刷新倒计时
  const [clock, setClock] = useState(() => formatClock());
  const [audioWarmed, setAudioWarmed] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const demoRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  // ─── 时钟更新 ───

  function formatClock() {
    return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  }

  useEffect(() => {
    mountedRef.current = true;
    const timer = setInterval(() => {
      setTick((t) => t + 1);
      setClock(formatClock());
    }, 1000);
    return () => {
      mountedRef.current = false;
      clearInterval(timer);
    };
  }, []);

  // ─── 音频预热 ───

  const handleFirstInteraction = useCallback(() => {
    if (!audioWarmed) {
      warmUpAudio();
      setAudioWarmed(true);
    }
  }, [audioWarmed]);

  // ─── 实时数据连接 ───

  useEffect(() => {
    if (isDemo) {
      // 演示模式：已有 mock 数据，每 30 秒自动加一张新工单
      demoRef.current = setInterval(() => {
        if (!mountedRef.current) return;
        const newTicket = makeTicket({
          createdAtOffsetMin: 0,
          status: 'pending',
        });
        setTickets((prev) => [newTicket, ...prev]);
        playNewOrder();
      }, 30_000);

      return () => {
        if (demoRef.current) clearInterval(demoRef.current);
      };
    }

    // 非演示模式：尝试 WebSocket 连接
    const macHost = localStorage.getItem('kds_mac_host');
    const stationId = localStorage.getItem('kds_station_id') || 'default';

    if (macHost) {
      // WebSocket 模式
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${protocol}//${macHost}/ws/kds/${encodeURIComponent(stationId)}`;

      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log('[KDS] WS connected');
          setTickets([]); // 清空 mock，等服务端数据
        };

        ws.onmessage = (e) => {
          if (e.data === 'pong') return;
          try {
            const msg = JSON.parse(e.data);
            if (msg.type === 'new_ticket') {
              const p = msg.payload || msg;
              const t: DemoTicket = {
                id: p.ticket_id || `ws-${Date.now()}`,
                orderNo: p.order_no || p.order_number || '',
                tableNo: p.table_no || p.table_number || '',
                items: (p.items || []).map((i: Record<string, unknown>) => ({
                  name: (i.dish_name || i.name || '') as string,
                  qty: (i.quantity || i.qty || 1) as number,
                  notes: (i.special_notes || i.notes || '') as string,
                })),
                createdAt: p.created_at ? new Date(p.created_at as string).getTime() : Date.now(),
                status: 'pending',
                priority: (p.priority || 'normal') as DemoTicket['priority'],
                timeLimit: (p.time_limit_min || 20) as number,
              };
              setTickets((prev) => [t, ...prev]);
              if (audioWarmed) playNewOrder();
            } else if (msg.type === 'timeout_alert') {
              if (audioWarmed) playTimeout();
            }
          } catch {
            // ignore
          }
        };

        ws.onerror = () => {
          console.warn('[KDS] WS error, falling back to poll');
          fallbackToPoll(stationId);
        };

        ws.onclose = () => {
          if (!mountedRef.current) return;
          fallbackToPoll(stationId);
        };
      } catch {
        fallbackToPoll(stationId);
      }
    } else {
      // 没有 Mac mini 配置：3 秒轮询
      const stId = stationId;
      fallbackToPoll(stId);
    }

    function fallbackToPoll(stId: string) {
      if (pollRef.current) return; // 避免重复
      pollRef.current = setInterval(async () => {
        if (!mountedRef.current) return;
        try {
          const result = await fetchTicketQueue(stId, 'pending,cooking');
          if (result.items.length > 0) {
            const mapped: DemoTicket[] = result.items.map((t) => ({
              id: t.ticket_id,
              orderNo: t.order_no,
              tableNo: t.table_no,
              items: t.items.map((i) => ({
                name: i.dish_name,
                qty: i.quantity,
                notes: i.special_notes,
              })),
              createdAt: new Date(t.created_at).getTime(),
              status: (t.status === 'cooking' ? 'cooking' : 'pending') as DemoTicket['status'],
              priority: t.priority,
              timeLimit: t.time_limit_min || 20,
              startedAt: t.started_at ? new Date(t.started_at).getTime() : undefined,
            }));
            setTickets(mapped);
          }
        } catch {
          // 轮询失败：保留现有 mock 数据
        }
      }, 3000);
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
      }
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDemo, storeId]);

  // ─── 操作 ─────────────────────────────────────────

  const handleStart = useCallback(async (id: string) => {
    // 乐观更新
    setTickets((prev) =>
      prev.map((t) =>
        t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t,
      ),
    );
    if (!isDemo) {
      try {
        await startTicket(id);
      } catch {
        // 忽略，乐观更新已显示
      }
    }
  }, [isDemo]);

  const handleComplete = useCallback(async (id: string) => {
    // 先标记 done，再移除（300ms 动画）
    setTickets((prev) =>
      prev.map((t) => (t.id === id ? { ...t, status: 'done' as const } : t)),
    );
    setTimeout(() => {
      setTickets((prev) => prev.filter((t) => t.id !== id));
    }, 400);

    if (!isDemo) {
      try {
        await completeTicket(id);
      } catch {
        // 忽略
      }
    }
  }, [isDemo]);

  // ─── 统计 ────────────────────────────────────────

  const activeTickets = tickets.filter((t) => t.status !== 'done');
  const pendingCount = activeTickets.filter((t) => t.status === 'pending').length;
  const cookingCount = activeTickets.filter((t) => t.status === 'cooking').length;
  const overtimeCount = activeTickets.filter(
    (t) => getTimeStatus(t.createdAt, t.timeLimit) === 'overtime',
  ).length;

  return (
    <div
      style={{
        background: '#0D1117',
        color: '#F0F0F0',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      }}
      onTouchStart={handleFirstInteraction}
      onClick={handleFirstInteraction}
    >
      <style>{CSS_VARS}</style>

      {/* ── 顶栏 ── */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
          height: 64,
          background: '#111827',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          flexShrink: 0,
          gap: 20,
        }}
      >
        {/* 左：品牌 + 门店 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span
            style={{
              fontSize: 22,
              fontWeight: 800,
              color: '#FF6B35',
              letterSpacing: 1,
            }}
          >
            后厨看板
          </span>
          <span
            style={{
              padding: '4px 12px',
              borderRadius: 8,
              background: 'rgba(255,107,53,0.12)',
              border: '1px solid rgba(255,107,53,0.25)',
              color: '#FF6B35',
              fontSize: 16,
              fontWeight: 600,
            }}
          >
            {storeName}
          </span>
          {isDemo && (
            <span
              style={{
                padding: '4px 12px',
                borderRadius: 8,
                background: 'rgba(255,255,255,0.06)',
                color: 'rgba(255,255,255,0.4)',
                fontSize: 15,
                animation: 'kds-pulse 2s infinite',
              }}
            >
              DEMO
            </span>
          )}
        </div>

        {/* 中：统计数字 */}
        <div style={{ display: 'flex', gap: 32, alignItems: 'center' }}>
          <StatItem label="待制作" value={pendingCount} color="#BA7517" />
          <StatItem label="制作中" value={cookingCount} color="#185FA5" />
          <StatItem
            label="超时"
            value={overtimeCount}
            color={overtimeCount > 0 ? '#A32D2D' : '#444'}
            blink={overtimeCount > 0}
          />
        </div>

        {/* 右：时钟 + 返回 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span
            style={{
              fontSize: 20,
              fontWeight: 600,
              fontFamily: 'JetBrains Mono, "Courier New", monospace',
              color: 'rgba(255,255,255,0.6)',
              letterSpacing: 2,
            }}
          >
            {clock}
          </span>
          <button
            onClick={() => navigate('/select' + (isDemo ? '?demo=true' : ''))}
            style={{
              padding: '8px 16px',
              minHeight: 48,
              minWidth: 48,
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 10,
              color: 'rgba(255,255,255,0.5)',
              fontSize: 16,
              cursor: 'pointer',
            }}
          >
            切换
          </button>
        </div>
      </header>

      {/* ── 工单区（水平滚动） ── */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 16,
          padding: '20px 20px',
          overflowX: 'auto',
          overflowY: 'hidden',
          WebkitOverflowScrolling: 'touch',
          scrollbarWidth: 'thin',
          scrollbarColor: 'rgba(255,255,255,0.1) transparent',
        }}
      >
        {activeTickets.length === 0 ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'rgba(255,255,255,0.2)',
              fontSize: 24,
              gap: 16,
            }}
          >
            <span style={{ fontSize: 64 }}>✓</span>
            <span>暂无待出餐工单</span>
            {isDemo && (
              <span style={{ fontSize: 18, color: 'rgba(255,255,255,0.15)' }}>
                每 30 秒将自动生成新工单
              </span>
            )}
          </div>
        ) : (
          activeTickets.map((ticket) => (
            <KDSTicketCard
              key={ticket.id}
              ticket={ticket}
              tick={tick}
              onStart={() => handleStart(ticket.id)}
              onComplete={() => handleComplete(ticket.id)}
            />
          ))
        )}

        {/* 末尾占位，避免最后一张卡贴边 */}
        {activeTickets.length > 0 && (
          <div style={{ flexShrink: 0, width: 4 }} />
        )}
      </div>
    </div>
  );
}

// ─── 顶栏统计格 ─────────────────────────────────────

function StatItem({
  label,
  value,
  color,
  blink,
}: {
  label: string;
  value: number;
  color: string;
  blink?: boolean;
}) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        animation: blink ? 'kds-pulse 1.5s infinite' : undefined,
      }}
    >
      <span
        style={{
          fontSize: 28,
          fontWeight: 800,
          color,
          fontFamily: 'JetBrains Mono, monospace',
          lineHeight: 1,
        }}
      >
        {value}
      </span>
      <span style={{ fontSize: 14, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>{label}</span>
    </div>
  );
}

// ─── 工单卡片 ─────────────────────────────────────────

function KDSTicketCard({
  ticket,
  tick: _tick,
  onStart,
  onComplete,
}: {
  ticket: DemoTicket;
  tick: number;
  onStart: () => void;
  onComplete: () => void;
}) {
  const status = getTimeStatus(ticket.createdAt, ticket.timeLimit);
  const elapsed = formatElapsed(ticket.createdAt);
  const isVip = ticket.priority === 'vip';
  const isRush = ticket.priority === 'rush';
  const isCooking = ticket.status === 'cooking';

  // 颜色编码
  const borderColor =
    status === 'overtime'
      ? '#A32D2D'
      : status === 'warning'
        ? '#BA7517'
        : 'rgba(255,255,255,0.1)';

  const timerColor =
    status === 'overtime'
      ? '#ff4d4f'
      : status === 'warning'
        ? '#f5a623'
        : '#0F6E56';

  const cardBg =
    status === 'overtime'
      ? 'linear-gradient(160deg, #1a0505 0%, #200808 100%)'
      : '#111827';

  const cardAnimation =
    status === 'overtime'
      ? 'kds-border-flash 1.5s infinite'
      : status === 'warning'
        ? 'kds-warn-flash 2s infinite'
        : 'kds-card-in 0.3s ease-out';

  // 左滑完成手势
  const { swipeHandlers, swipeOffset, isSwiping } = useSwipe({
    onSwipeLeft: onComplete,
    threshold: 72,
  });

  return (
    <div
      style={{
        width: 240,
        flexShrink: 0,
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 16,
      }}
    >
      {/* 左滑提示底层 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: '#0F6E56',
          borderRadius: 16,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          paddingRight: 20,
          opacity: isSwiping && swipeOffset < -20 ? Math.min(1, Math.abs(swipeOffset) / 72) : 0,
          transition: isSwiping ? 'none' : 'opacity 0.2s',
        }}
      >
        <span style={{ color: '#fff', fontSize: 28, fontWeight: 700 }}>完成</span>
      </div>

      {/* 主卡片 */}
      <div
        {...swipeHandlers}
        style={{
          width: '100%',
          minHeight: 300,
          background: cardBg,
          border: `2px solid ${borderColor}`,
          borderRadius: 16,
          padding: '16px 14px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: 0,
          cursor: isSwiping ? 'grabbing' : 'grab',
          userSelect: 'none',
          transform: `translateX(${swipeOffset}px)`,
          transition: isSwiping ? 'none' : 'transform 0.25s ease, border-color 0.3s',
          animation: cardAnimation,
          position: 'relative',
        }}
      >
        {/* 卡头：桌号 + 状态标签 + 倒计时 */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: 12,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 28,
                fontWeight: 800,
                color: '#fff',
                lineHeight: 1,
                marginBottom: 4,
              }}
            >
              {ticket.tableNo}
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 14, color: 'rgba(255,255,255,0.35)' }}>
                #{ticket.orderNo}
              </span>
              {isVip && (
                <span
                  style={{
                    fontSize: 13,
                    padding: '1px 8px',
                    borderRadius: 5,
                    background: 'linear-gradient(135deg, #C5A347, #E8D48B)',
                    color: '#1a1a00',
                    fontWeight: 700,
                  }}
                >
                  VIP
                </span>
              )}
              {isRush && (
                <span
                  style={{
                    fontSize: 13,
                    padding: '1px 8px',
                    borderRadius: 5,
                    background: '#A32D2D',
                    color: '#fff',
                    fontWeight: 700,
                    animation: 'kds-pulse 1s infinite',
                  }}
                >
                  催
                </span>
              )}
            </div>
          </div>

          {/* 倒计时 */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
            }}
          >
            <div
              style={{
                fontSize: 32,
                fontWeight: 800,
                color: timerColor,
                fontFamily: 'JetBrains Mono, "Courier New", monospace',
                lineHeight: 1,
                animation:
                  status === 'warning' || status === 'overtime'
                    ? 'kds-pulse 1.5s infinite'
                    : undefined,
              }}
            >
              {elapsed}
            </div>
            <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.3)', marginTop: 3 }}>
              {status === 'overtime' ? '已超时' : status === 'warning' ? '即将超时' : '正常'}
            </div>
          </div>
        </div>

        {/* 分割线 */}
        <div
          style={{
            height: 1,
            background: 'rgba(255,255,255,0.06)',
            marginBottom: 12,
          }}
        />

        {/* 菜品列表 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {ticket.items.map((item, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
              }}
            >
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 20, fontWeight: 700, color: '#F0F0F0' }}>
                  {item.name}
                </span>
                {item.notes && (
                  <span
                    style={{
                      fontSize: 15,
                      color: '#f5a623',
                      marginLeft: 6,
                      fontWeight: 400,
                    }}
                  >
                    ({item.notes})
                  </span>
                )}
              </div>
              <span
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: '#FF6B35',
                  minWidth: 40,
                  textAlign: 'right',
                }}
              >
                ×{item.qty}
              </span>
            </div>
          ))}
        </div>

        {/* 操作按钮 */}
        <div style={{ marginTop: 16 }}>
          {ticket.status === 'pending' ? (
            <ActionButton
              label="开始制作"
              color="#185FA5"
              onClick={onStart}
            />
          ) : (
            <ActionButton
              label="出餐完成"
              color="#0F6E56"
              onClick={onComplete}
            />
          )}
        </div>

        {/* 左滑提示文字（状态为 cooking 时显示） */}
        {isCooking && (
          <div
            style={{
              textAlign: 'center',
              marginTop: 8,
              fontSize: 13,
              color: 'rgba(255,255,255,0.2)',
            }}
          >
            左滑完成出餐
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 操作按钮（触控优化） ──────────────────────────────

function ActionButton({
  label,
  color,
  onClick,
}: {
  label: string;
  color: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      onPointerDown={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
      }}
      onPointerUp={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
      }}
      onPointerLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
      }}
      style={{
        width: '100%',
        height: 56,
        border: 'none',
        borderRadius: 12,
        background: color,
        color: '#fff',
        fontSize: 20,
        fontWeight: 700,
        cursor: 'pointer',
        transition: 'transform 200ms ease',
        minHeight: 56,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {label}
    </button>
  );
}
