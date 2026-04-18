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
 *
 * KDS theme is applied via data-theme="kds" on root element.
 * Theme colors are available via CSS vars: --tx-kds-green, --tx-kds-amber, --tx-kds-red
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { fetchTicketQueue, startTicket, completeTicket } from '../api/kdsOpsApi';
import { warmUpAudio, playNewOrder, playTimeout } from '../utils/audio';
import { OrderTicketCard } from '@tx-ds/biz';
import type { OrderTicketData } from '@tx-ds/biz';
import { TXKDSTicket, type TXKDSTicketItem } from '@tx/touch/components/TXKDSTicket';
import { useKDSRules } from '../hooks/useKDSRules';
import { useOrdersCache } from '../hooks/useOrdersCache';
import { useConnection } from '../contexts/ConnectionContext';
import { installCacheDiagnostics } from '../utils/cacheStats';
import {
  getTimeLevelFromRules,
  getTimerColorFromLevel,
  getChannelColor,
  type KDSRuleConfig,
} from '../api/kdsRulesApi';


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
    --tx-kds-green: #0F6E56;
    --tx-kds-amber: #f5a623;
    --tx-kds-red: #ff4d4f;
  }
  @keyframes kds-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.65; }
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
  /** 渠道：dine_in / takeout / pickup */
  channel?: string;
  /** 是否赠菜工单 */
  isGift?: boolean;
  /** 是否退菜工单 */
  isReturn?: boolean;
  /** 客位数 */
  guestSeat?: number;
}

/** Grouped dish entry for by-dish view */
interface GroupedDish {
  name: string;
  totalQty: number;
  tables: string[];
  notes: string[];
}

type ViewMode = 'scroll' | 'paged';
type GroupMode = 'by-table' | 'by-dish';

type TimeStatus = 'normal' | 'warning' | 'overtime';

/**
 * 根据KDS规则配置计算时间状态（优先使用规则，回退到原有timeLimit逻辑）
 */
function getTimeStatusFromRules(
  createdAt: number,
  timeLimit: number,
  rules: KDSRuleConfig,
): TimeStatus {
  const elapsedMin = (Date.now() - createdAt) / 60000;
  const level = getTimeLevelFromRules(elapsedMin, rules);
  if (level === 'urgent') return 'overtime';
  if (level === 'warning') return 'warning';
  // 兜底：如果 timeLimit 到期也算超时
  if (elapsedMin >= timeLimit) return 'overtime';
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
      startedAt: Date.now() - 22 * 60 * 1000,
      channel: 'dine_in', guestSeat: 4 }), // 超时
    makeTicket({ createdAtOffsetMin: 12, status: 'cooking', priority: 'vip', tableNo: 'B01',
      items: [{ name: '口味虾', qty: 2, notes: '中辣' }, { name: '米饭', qty: 4, notes: '' }],
      startedAt: Date.now() - 10 * 60 * 1000,
      channel: 'dine_in', guestSeat: 6 }), // 即将超时
    makeTicket({ createdAtOffsetMin: 5, status: 'pending', priority: 'normal', tableNo: '外卖001',
      items: [{ name: '蒜蓉西兰花', qty: 1, notes: '' }, { name: '酸菜鱼', qty: 1, notes: '微辣' }],
      channel: 'takeout' }),
    makeTicket({ createdAtOffsetMin: 3, status: 'pending', priority: 'rush', tableNo: 'C01',
      items: [{ name: '外婆鸡', qty: 1, notes: '' }],
      channel: 'dine_in', isGift: true, guestSeat: 2 }),
    makeTicket({ createdAtOffsetMin: 1, status: 'pending', priority: 'normal', tableNo: '自取003',
      items: [{ name: '番茄炒蛋', qty: 2, notes: '' }, { name: '土豆丝', qty: 1, notes: '' }],
      channel: 'pickup' }),
  ];
}

// ─── DemoTicket → OrderTicketData mapper ─────────────────

function toTicketData(t: DemoTicket): OrderTicketData {
  return {
    id: t.id,
    orderNo: t.orderNo,
    tableNo: t.tableNo,
    status: t.status === 'pending' ? 'pending' : t.status === 'cooking' ? 'cooking' : 'done',
    priority: t.priority,
    createdAt: new Date(t.createdAt).toISOString(),
    timeoutMinutes: t.timeLimit,
    items: t.items.map((item, i) => ({
      id: `${t.id}-${i}`,
      name: item.name,
      qty: item.qty,
      remark: item.notes || undefined,
    })),
  };
}

/** Simple overtime check for stat counting */
function isOvertime(createdAt: number, timeLimit: number): boolean {
  return (Date.now() - createdAt) / 60000 >= timeLimit;
}

// ─── Pagination helpers ──────────────────────────────────

const TICKETS_PER_PAGE = 6;

// ─── 主组件 ───────────────────────────────────────────

export function KDSBoardPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const isDemo = searchParams.get('demo') === 'true';
  const storeId = searchParams.get('store') || 'wh';
  const storeName = STORE_MAP[storeId] || '未知门店';

  // 加载门店KDS规则配置（超时颜色/渠道色/标识开关）
  const { rules } = useKDSRules(storeId);

  // C1: 本地 last-100-orders 缓存（旁路挂载，不改 WebSocket 主路径）
  const ordersCache = useOrdersCache();
  // C2: 连接健康 → 写操作 guard
  const { health } = useConnection();
  const isReadOnly = health !== 'online';
  useEffect(() => {
    installCacheDiagnostics();
  }, []);
  useEffect(() => {
    if (!ordersCache.hydrating && ordersCache.stats) {
      console.log('[KDS-Cache] stats', ordersCache.stats);
    }
  }, [ordersCache.hydrating, ordersCache.stats]);

  const [tickets, setTickets] = useState<DemoTicket[]>(() => buildMockTickets());
  const [now, setNow] = useState(() => Date.now());
  const [clock, setClock] = useState(() => formatClock());
  const [audioWarmed, setAudioWarmed] = useState(false);

  // View mode toggles
  const [viewMode, setViewMode] = useState<ViewMode>('scroll');
  const [groupMode, setGroupMode] = useState<GroupMode>('by-table');
  const [currentPage, setCurrentPage] = useState(0);

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
      setNow(Date.now());
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

  const warnReadOnly = useCallback(() => {
    console.warn('[KDS] 离线只读，网络恢复后再试');
    if (typeof window !== 'undefined' && typeof window.alert === 'function') {
      // 无 toast 组件：用 alert 兜底，C3 再引入 toast
      window.alert('离线只读，网络恢复后再试');
    }
  }, []);

  const handleStart = useCallback(async (id: string) => {
    if (isReadOnly) {
      warnReadOnly();
      return;
    }
    // 乐观更新
    setTickets((prev) =>
      prev.map((t) =>
        t.id === id ? { ...t, status: 'cooking' as const, startedAt: Date.now() } : t,
      ),
    );
    if (!isDemo) {
      try {
        await startTicket(id);
      } catch (err) {
        // 乐观更新已显示，网络失败不回滚（下一轮 poll 会覆盖）
        console.warn('[KDS] startTicket 失败，乐观保留', err);
      }
    }
  }, [isDemo, isReadOnly, warnReadOnly]);

  const completeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up animation timeout on unmount
  useEffect(() => {
    return () => {
      if (completeTimerRef.current) clearTimeout(completeTimerRef.current);
    };
  }, []);

  const handleComplete = useCallback(async (id: string) => {
    if (isReadOnly) {
      warnReadOnly();
      return;
    }
    // 先标记 done，再移除（300ms 动画）
    setTickets((prev) =>
      prev.map((t) => (t.id === id ? { ...t, status: 'done' as const } : t)),
    );
    if (completeTimerRef.current) clearTimeout(completeTimerRef.current);
    completeTimerRef.current = setTimeout(() => {
      setTickets((prev) => prev.filter((t) => t.id !== id));
      completeTimerRef.current = null;
    }, 400);

    if (!isDemo) {
      try {
        await completeTicket(id);
      } catch (err) {
        console.warn('[KDS] completeTicket 失败，乐观保留', err);
      }
    }
  }, [isDemo, isReadOnly, warnReadOnly]);

  // ─── 统计 ────────────────────────────────────────

  const activeTickets = tickets.filter((t) => t.status !== 'done');
  const pendingCount = activeTickets.filter((t) => t.status === 'pending').length;
  const cookingCount = activeTickets.filter((t) => t.status === 'cooking').length;
  const overtimeCount = activeTickets.filter(
    (t) => getTimeStatusFromRules(t.createdAt, t.timeLimit, rules) === 'overtime',
  ).length;

  // ─── Pagination (paged mode) ──────────────────────

  const totalPages = Math.max(1, Math.ceil(activeTickets.length / TICKETS_PER_PAGE));

  // Clamp current page when tickets change
  useEffect(() => {
    if (currentPage >= totalPages) {
      setCurrentPage(Math.max(0, totalPages - 1));
    }
  }, [totalPages, currentPage]);

  const pagedTickets = useMemo(() => {
    if (viewMode !== 'paged') return activeTickets;
    const start = currentPage * TICKETS_PER_PAGE;
    return activeTickets.slice(start, start + TICKETS_PER_PAGE);
  }, [viewMode, activeTickets, currentPage]);

  // ─── Group by dish ────────────────────────────────

  const groupedDishes = useMemo((): GroupedDish[] => {
    if (groupMode !== 'by-dish') return [];
    const map = new Map<string, GroupedDish>();
    for (const ticket of activeTickets) {
      for (const item of ticket.items) {
        const existing = map.get(item.name);
        if (existing) {
          existing.totalQty += item.qty;
          if (!existing.tables.includes(ticket.tableNo)) {
            existing.tables.push(ticket.tableNo);
          }
          if (item.notes && !existing.notes.includes(item.notes)) {
            existing.notes.push(item.notes);
          }
        } else {
          map.set(item.name, {
            name: item.name,
            totalQty: item.qty,
            tables: [ticket.tableNo],
            notes: item.notes ? [item.notes] : [],
          });
        }
      }
    }
    return Array.from(map.values()).sort((a, b) => b.totalQty - a.totalQty);
  }, [groupMode, activeTickets]);

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

        {/* 中：统计数字 + 视图切换 */}
        <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
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

          {/* 视图切换按钮组 */}
          <div style={{ display: 'flex', gap: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 8, padding: 2 }}>
            <ToggleButton
              active={viewMode === 'scroll'}
              label="滚动"
              onClick={() => { setViewMode('scroll'); setCurrentPage(0); }}
            />
            <ToggleButton
              active={viewMode === 'paged'}
              label="分页"
              onClick={() => { setViewMode('paged'); setCurrentPage(0); }}
            />
          </div>
          <div style={{ display: 'flex', gap: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 8, padding: 2 }}>
            <ToggleButton
              active={groupMode === 'by-table'}
              label="按桌"
              onClick={() => setGroupMode('by-table')}
            />
            <ToggleButton
              active={groupMode === 'by-dish'}
              label="按菜"
              onClick={() => setGroupMode('by-dish')}
            />
          </div>
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

      {/* ── 主内容区 ── */}
      {groupMode === 'by-dish' ? (
        /* ── 按菜品分组视图 ── */
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '20px 24px',
          }}
        >
          {groupedDishes.length === 0 ? (
            <EmptyState isDemo={isDemo} />
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 16,
            }}>
              {groupedDishes.map((dish) => (
                <DishGroupCard key={dish.name} dish={dish} />
              ))}
            </div>
          )}
        </div>
      ) : viewMode === 'paged' ? (
        /* ── 分页视图 ── */
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div
            style={{
              flex: 1,
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
              gridAutoRows: 'min-content',
              gap: 16,
              padding: '20px 20px',
              overflowY: 'auto',
              alignContent: 'start',
            }}
          >
            {pagedTickets.length === 0 ? (
              <div style={{ gridColumn: '1 / -1' }}>
                <EmptyState isDemo={isDemo} />
              </div>
            ) : (
              pagedTickets.map((ticket) => (
                <OrderTicketCard
                  key={ticket.id}
                  ticket={toTicketData(ticket)}
                  kds
                  now={now}
                  swipeable
                  onSwipeComplete={() => handleComplete(ticket.id)}
                  isFlashing={ticket.priority === 'rush'}
                  onStart={() => handleStart(ticket.id)}
                  onComplete={() => handleComplete(ticket.id)}
                />
              ))
            )}
          </div>

          {/* 分页导航 */}
          {activeTickets.length > 0 && (
            <div
              style={{
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                gap: 16,
                padding: '12px 0',
                background: '#111827',
                borderTop: '1px solid rgba(255,255,255,0.06)',
                flexShrink: 0,
              }}
            >
              <PageNavButton
                label="<"
                disabled={currentPage <= 0}
                onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
              />
              <span
                style={{
                  fontSize: 16,
                  fontWeight: 600,
                  color: 'rgba(255,255,255,0.6)',
                  fontFamily: 'JetBrains Mono, monospace',
                  minWidth: 100,
                  textAlign: 'center',
                }}
              >
                {currentPage + 1} / {totalPages}
              </span>
              <PageNavButton
                label=">"
                disabled={currentPage >= totalPages - 1}
                onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))}
              />
            </div>
          )}
        </div>
      ) : (
        /* ── 水平滚动视图（原始默认） ── */
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
            <EmptyState isDemo={isDemo} />
          ) : (
            activeTickets.map((ticket) => (
              <div key={ticket.id} style={{ width: 260, flexShrink: 0 }}>
                <OrderTicketCard
                  ticket={toTicketData(ticket)}
                  kds
                  now={now}
                  swipeable
                  onSwipeComplete={() => handleComplete(ticket.id)}
                  isFlashing={ticket.priority === 'rush'}
                  onStart={() => handleStart(ticket.id)}
                  onComplete={() => handleComplete(ticket.id)}
                />
              </div>
            ))
          )}

          {/* 末尾占位，避免最后一张卡贴边 */}
          {activeTickets.length > 0 && (
            <div style={{ flexShrink: 0, width: 4 }} />
          )}
        </div>
      )}
    </div>
  );
}

// ─── 空状态 ─────────────────────────────────────────

function EmptyState({ isDemo }: { isDemo: boolean }) {
  return (
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
        minHeight: 300,
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

// ─── 切换按钮 ────────────────────────────────────────

function ToggleButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '4px 12px',
        borderRadius: 6,
        border: 'none',
        background: active ? 'rgba(255,107,53,0.2)' : 'transparent',
        color: active ? '#FF6B35' : 'rgba(255,255,255,0.4)',
        fontSize: 14,
        fontWeight: active ? 700 : 400,
        cursor: 'pointer',
        transition: 'all 0.15s',
      }}
    >
      {label}
    </button>
  );
}

// (KDSTicketCard removed — now uses shared OrderTicketCard from @tx-ds/biz)
// KDS rules utility functions (getTimeStatusFromRules, formatElapsed) are kept above for overtime counting.

// ─── 分页导航按钮 ────────────────────────────────────

function PageNavButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        width: 48,
        height: 48,
        borderRadius: 10,
        border: '1px solid rgba(255,255,255,0.1)',
        background: disabled ? 'transparent' : 'rgba(255,255,255,0.06)',
        color: disabled ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.6)',
        fontSize: 24,
        fontWeight: 700,
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {label}
    </button>
  );
}

// ─── 按菜品分组卡片 ──────────────────────────────────

function DishGroupCard({ dish }: { dish: GroupedDish }) {
  return (
    <div
      style={{
        background: '#111827',
        border: '2px solid rgba(255,255,255,0.08)',
        borderRadius: 16,
        padding: '16px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      {/* 菜名 + 总数 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 22, fontWeight: 800, color: '#F0F0F0' }}>
          {dish.name}
        </span>
        <span
          style={{
            fontSize: 28,
            fontWeight: 800,
            color: '#FF6B35',
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          x{dish.totalQty}
        </span>
      </div>

      {/* 桌号列表 */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {dish.tables.map((table) => (
          <span
            key={table}
            style={{
              padding: '2px 10px',
              borderRadius: 6,
              background: 'rgba(255,255,255,0.06)',
              color: 'rgba(255,255,255,0.6)',
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {table}
          </span>
        ))}
      </div>

      {/* 备注 */}
      {dish.notes.length > 0 && (
        <div style={{ fontSize: 14, color: 'var(--tx-kds-amber)' }}>
          {dish.notes.join(' / ')}
        </div>
      )}
    </div>
  );
}

// ─── 旧版看板（兼容 /board-legacy 路由） ───

// KDS_TIMEOUT_MINUTES：旧版看板固定 25 分钟上限
const KDS_TIMEOUT_MINUTES = 25;
const _legacyNow = Date.now();
const _legacyMin = (m: number) => m * 60 * 1000;

interface LegacyTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  items: TXKDSTicketItem[];
  createdAt: Date;
  status: 'pending' | 'preparing' | 'abnormal';
  isVip: boolean;
}

const LEGACY_MOCK: LegacyTicket[] = [
  {
    id: '1', orderNo: '001', tableNo: 'A01', status: 'pending', isVip: false,
    createdAt: new Date(_legacyNow - _legacyMin(8)),
    items: [{ name: '剁椒鱼头', qty: 1, spec: '少辣', priority: 'normal' }, { name: '小炒肉', qty: 1, priority: 'normal' }],
  },
  {
    id: '2', orderNo: '002', tableNo: 'A03', status: 'preparing', isVip: false,
    createdAt: new Date(_legacyNow - _legacyMin(11)),
    items: [{ name: '口味虾', qty: 1, spec: '中辣', priority: 'rush' }],
  },
  {
    id: '3', orderNo: '003', tableNo: 'B01', status: 'preparing', isVip: true,
    createdAt: new Date(_legacyNow - _legacyMin(18)),
    items: [{ name: '鱼头', qty: 2, priority: 'normal' }, { name: '米饭', qty: 6, priority: 'normal' }],
  },
  {
    id: '4', orderNo: '004', tableNo: 'B02', status: 'pending', isVip: false,
    createdAt: new Date(_legacyNow - _legacyMin(5)),
    items: [{ name: '外婆鸡', qty: 1, spec: '多放辣', priority: 'normal' }],
  },
  {
    id: '5', orderNo: '005', tableNo: 'A05', status: 'abnormal', isVip: false,
    createdAt: new Date(_legacyNow - _legacyMin(38)),
    items: [{ name: '凉拌黄瓜', qty: 2, priority: 'normal' }],
  },
];

const COL_STYLE = {
  flex: 1, display: 'flex' as const, flexDirection: 'column' as const,
  gap: 12, overflowY: 'auto' as const, padding: 12,
  WebkitOverflowScrolling: 'touch' as const,
};

export function KDSBoardPageLegacy() {
  const [tickets, setTickets] = useState<LegacyTicket[]>(LEGACY_MOCK);

  const move = (id: string, to: LegacyTicket['status']) => {
    setTickets(prev =>
      prev.map(t => t.id === id ? { ...t, status: to } : t)
    );
  };

  const complete = (id: string) => setTickets(prev => prev.filter(t => t.id !== id));

  const pending = tickets.filter(t => t.status === 'pending');
  const preparing = tickets.filter(t => t.status === 'preparing');
  const abnormal = tickets.filter(t => t.status === 'abnormal');

  return (
    <div style={{
      background: '#0A0A0A', color: '#E0E0E0', height: '100vh',
      display: 'flex', flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
    }}>
      {/* 顶栏 — KDS标题>=24px，计数>=28px */}
      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '10px 20px', background: '#111', borderBottom: '1px solid #222', minHeight: 56,
      }}>
        <span style={{ fontWeight: 'bold', fontSize: 24, color: '#FF6B35' }}>后厨看板（旧版）</span>
        <div style={{ display: 'flex', gap: 32, fontSize: 18 }}>
          <span>待制作 <b style={{ color: '#BA7517', fontSize: 28 }}>{pending.length}</b></span>
          <span>制作中 <b style={{ color: '#4A9EFF', fontSize: 28 }}>{preparing.length}</b></span>
          <span style={{ color: abnormal.length > 0 ? '#A32D2D' : '#555' }}>
            异常 <b style={{ fontSize: 28 }}>{abnormal.length}</b>
          </span>
        </div>
      </header>

      {/* 三列看板 */}
      <div style={{ flex: 1, display: 'flex', gap: 2, overflow: 'hidden' }}>
        {/* 待制作列 */}
        <div style={{ ...COL_STYLE, background: '#111500' }}>
          <div style={{
            textAlign: 'center', padding: '8px 0', fontSize: 20,
            fontWeight: 'bold', color: '#BA7517', borderBottom: '3px solid #BA7517',
          }}>
            待制作 ({pending.length})
          </div>
          {pending.map(t => (
            <TXKDSTicket
              key={t.id}
              orderId={t.orderNo}
              tableNo={t.tableNo}
              items={t.items}
              createdAt={t.createdAt}
              timeLimit={KDS_TIMEOUT_MINUTES}
              isVip={t.isVip}
              onComplete={() => move(t.id, 'preparing')}
              onRush={() => move(t.id, 'preparing')}
            />
          ))}
        </div>

        {/* 制作中列 */}
        <div style={{ ...COL_STYLE, background: '#001515' }}>
          <div style={{
            textAlign: 'center', padding: '8px 0', fontSize: 20,
            fontWeight: 'bold', color: '#4A9EFF', borderBottom: '3px solid #4A9EFF',
          }}>
            制作中 ({preparing.length})
          </div>
          {preparing.map(t => (
            <TXKDSTicket
              key={t.id}
              orderId={t.orderNo}
              tableNo={t.tableNo}
              items={t.items}
              createdAt={t.createdAt}
              timeLimit={KDS_TIMEOUT_MINUTES}
              isVip={t.isVip}
              onComplete={() => complete(t.id)}
              onRush={() => {/* 已在制作中，加急通知已处理 */}}
            />
          ))}
        </div>

        {/* 异常列 */}
        <div style={{ ...COL_STYLE, background: '#150000' }}>
          <div style={{
            textAlign: 'center', padding: '8px 0', fontSize: 20,
            fontWeight: 'bold', color: '#A32D2D', borderBottom: '3px solid #A32D2D',
          }}>
            异常 ({abnormal.length})
          </div>
          {abnormal.map(t => (
            <TXKDSTicket
              key={t.id}
              orderId={t.orderNo}
              tableNo={t.tableNo}
              items={t.items}
              createdAt={t.createdAt}
              timeLimit={KDS_TIMEOUT_MINUTES}
              isVip={t.isVip}
              onComplete={() => complete(t.id)}
              onRush={() => complete(t.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
