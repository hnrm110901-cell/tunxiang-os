/**
 * TableMonitorScreen — 前厅桌台监控大屏（TXTouch Store 终端）
 *
 * 功能：
 * - 全屏深色背景展示所有桌台实时状态
 * - 顶部 Tab 切换包厢/大厅区域
 * - 桌台卡片 4 列网格：状态色圈、进度条、时长、催单角标
 * - 每 30 秒轮询刷新 + WebSocket 实时推送
 * - 点击桌台卡片展开菜品明细抽屉
 *
 * 终端规范：≥48px 点击目标，≥16px 字体
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ─── Types ───

type TableZone = '包厢' | '大厅';

type TableStatusCode =
  | 'idle'
  | 'ordering'
  | 'cooking'
  | 'ready'
  | 'rush'
  | 'overtime';

interface PendingDish {
  name: string;
  status: string;
  dept: string;
}

interface TableStatus {
  table_id: string;
  table_no: string;
  zone: TableZone;
  status: TableStatusCode;
  dish_total: number;
  dish_done: number;
  elapsed_minutes: number;
  standard_minutes: number;
  is_overtime: boolean;
  rush_count: number;
  pending_dishes: PendingDish[];
}

interface StoreOverview {
  tables: TableStatus[];
  total: number;
}

// ─── 颜色常量 ───

const COLOR = {
  bg: '#0A0A0A',
  surface: '#141414',
  card: '#1C1C1C',
  border: '#2A2A2A',
  text: '#FFFFFF',
  textMuted: '#888888',
  primary: '#FF6B35',   // 催单状态主色
  overtime: '#FF3B30',  // 超时
  cooking: '#34C759',   // 用餐中/出菜中
  ready: '#30D158',     // 菜已出齐
  idle: '#636366',      // 空闲
  ordering: '#0A84FF',  // 下单中
  rush: '#FF6B35',      // 催单
  tabActive: '#FF6B35',
  tabInactive: '#3A3A3C',
};

function statusColor(status: TableStatusCode): string {
  switch (status) {
    case 'overtime': return COLOR.overtime;
    case 'rush':     return COLOR.rush;
    case 'cooking':  return COLOR.cooking;
    case 'ready':    return COLOR.ready;
    case 'ordering': return COLOR.ordering;
    default:         return COLOR.idle;
  }
}

function statusLabel(status: TableStatusCode): string {
  switch (status) {
    case 'overtime': return '超时';
    case 'rush':     return '催单';
    case 'cooking':  return '出菜中';
    case 'ready':    return '已出齐';
    case 'ordering': return '下单中';
    default:         return '空闲';
  }
}

// ─── 子组件：桌台卡片 ───

function TableCard({
  table,
  onClick,
}: {
  table: TableStatus;
  onClick: () => void;
}) {
  const color = statusColor(table.status);
  const progress =
    table.dish_total > 0
      ? Math.round((table.dish_done / table.dish_total) * 100)
      : 0;

  return (
    <button
      onClick={onClick}
      style={{
        background: COLOR.card,
        border: `1px solid ${table.is_overtime ? COLOR.overtime : table.rush_count > 0 ? COLOR.rush : COLOR.border}`,
        borderRadius: 12,
        padding: '16px',
        cursor: 'pointer',
        textAlign: 'left',
        color: COLOR.text,
        position: 'relative',
        minHeight: 148,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        // 超时时闪烁边框
        boxShadow: table.is_overtime
          ? `0 0 0 1px ${COLOR.overtime}`
          : table.rush_count > 0
          ? `0 0 0 1px ${COLOR.rush}`
          : 'none',
      }}
    >
      {/* 催单次数角标 */}
      {table.rush_count > 0 && (
        <div
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            background: COLOR.rush,
            color: '#fff',
            borderRadius: '50%',
            width: 22,
            height: 22,
            fontSize: 12,
            fontWeight: 'bold',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
          }}
        >
          {table.rush_count}
        </div>
      )}

      {/* 桌号 + 状态色圈 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div
          style={{
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: color,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 24,
            fontWeight: 'bold',
            letterSpacing: 1,
            lineHeight: 1.2,
          }}
        >
          {table.table_no}
        </span>
        <span
          style={{
            fontSize: 12,
            color,
            background: `${color}22`,
            padding: '2px 6px',
            borderRadius: 4,
            fontWeight: 600,
          }}
        >
          {statusLabel(table.status)}
        </span>
      </div>

      {/* 进度条 */}
      {table.dish_total > 0 && (
        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 12,
              color: COLOR.textMuted,
              marginBottom: 4,
            }}
          >
            <span>出菜进度</span>
            <span>
              {table.dish_done}/{table.dish_total} 道
            </span>
          </div>
          <div
            style={{
              height: 6,
              background: COLOR.border,
              borderRadius: 3,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${progress}%`,
                background: color,
                borderRadius: 3,
                transition: 'width 0.3s ease',
              }}
            />
          </div>
        </div>
      )}

      {/* 时长 */}
      {table.elapsed_minutes > 0 && (
        <div
          style={{
            fontSize: 16,
            color: table.is_overtime ? COLOR.overtime : COLOR.textMuted,
            fontWeight: table.is_overtime ? 700 : 400,
          }}
        >
          已等 {table.elapsed_minutes} 分钟
          {table.is_overtime && (
            <span
              style={{
                marginLeft: 6,
                fontSize: 12,
                color: COLOR.overtime,
                fontWeight: 'bold',
              }}
            >
              ！超时
            </span>
          )}
        </div>
      )}

      {/* 待出菜品（最多3道） */}
      {table.pending_dishes.length > 0 && (
        <div style={{ fontSize: 13, color: COLOR.textMuted, lineHeight: 1.6 }}>
          {table.pending_dishes.slice(0, 3).map((d, i) => (
            <span key={i}>
              {i > 0 && ' · '}
              <span
                style={{
                  color:
                    d.status === 'cooking' ? COLOR.cooking : COLOR.textMuted,
                }}
              >
                {d.name}
              </span>
            </span>
          ))}
          {table.pending_dishes.length > 3 && (
            <span style={{ color: COLOR.textMuted }}>
              {' '}+{table.pending_dishes.length - 3}道
            </span>
          )}
        </div>
      )}
    </button>
  );
}

// ─── 子组件：菜品明细抽屉 ───

function TableDetailDrawer({
  table,
  onClose,
}: {
  table: TableStatus;
  onClose: () => void;
}) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'flex-end',
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: COLOR.surface,
          width: '100%',
          borderRadius: '16px 16px 0 0',
          padding: 24,
          maxHeight: '70vh',
          overflowY: 'auto',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* 抽屉头部 */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 20,
          }}
        >
          <div>
            <span style={{ fontSize: 24, fontWeight: 'bold', color: COLOR.text }}>
              {table.table_no}
            </span>
            <span
              style={{
                marginLeft: 12,
                fontSize: 14,
                color: statusColor(table.status),
              }}
            >
              {statusLabel(table.status)}
            </span>
            <div style={{ fontSize: 13, color: COLOR.textMuted, marginTop: 2 }}>
              {table.zone} · 已等 {table.elapsed_minutes} 分钟 ·{' '}
              {table.dish_done}/{table.dish_total} 道已出
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: COLOR.card,
              border: 'none',
              color: COLOR.text,
              fontSize: 22,
              width: 48,
              height: 48,
              borderRadius: 12,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>

        {/* 待出菜品列表 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {table.pending_dishes.map((dish, i) => (
            <div
              key={i}
              style={{
                background: COLOR.card,
                borderRadius: 8,
                padding: '14px 16px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: 18,
                    fontWeight: 600,
                    color: COLOR.text,
                  }}
                >
                  {dish.name}
                </div>
                <div style={{ fontSize: 13, color: COLOR.textMuted, marginTop: 2 }}>
                  {dish.dept}
                </div>
              </div>
              <span
                style={{
                  fontSize: 13,
                  padding: '4px 10px',
                  borderRadius: 6,
                  background: dish.status === 'cooking' ? `${COLOR.cooking}22` : `${COLOR.ordering}22`,
                  color: dish.status === 'cooking' ? COLOR.cooking : COLOR.ordering,
                  fontWeight: 600,
                }}
              >
                {dish.status === 'cooking' ? '出菜中' : '等待中'}
              </span>
            </div>
          ))}

          {table.pending_dishes.length === 0 && (
            <div
              style={{
                textAlign: 'center',
                color: COLOR.textMuted,
                padding: 32,
                fontSize: 16,
              }}
            >
              所有菜品已出齐
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── 主组件 ───

interface TableMonitorScreenProps {
  /** Mac mini API host，如 "192.168.1.100:8000" */
  apiHost?: string;
  storeId: string;
  tenantId: string;
}

export function TableMonitorScreen({
  apiHost = 'localhost:8000',
  storeId,
  tenantId,
}: TableMonitorScreenProps) {
  const [zone, setZone] = useState<TableZone>('大厅');
  const [overview, setOverview] = useState<StoreOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedTable, setSelectedTable] = useState<TableStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCountRef = useRef(0);
  const mountedRef = useRef(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── 轮询拉取 ───

  const fetchOverview = useCallback(async () => {
    try {
      const resp = await fetch(
        `http://${apiHost}/api/v1/table-monitor/overview/${storeId}`,
        {
          headers: {
            'X-Tenant-ID': tenantId,
            'Content-Type': 'application/json',
          },
        },
      );
      if (!resp.ok) return;
      const json = await resp.json();
      if (json.ok && mountedRef.current) {
        setOverview(json.data);
        setLoading(false);
      }
    } catch {
      // 网络错误静默处理，等待下次轮询
      if (mountedRef.current) setLoading(false);
    }
  }, [apiHost, storeId, tenantId]);

  // ─── WebSocket 实时推送 ───

  const connectWs = useCallback(() => {
    if (!mountedRef.current) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${apiHost}/ws/table-monitor/${encodeURIComponent(storeId)}`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleRetry();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      retryCountRef.current = 0;
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current || event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data as string) as Record<string, unknown>;
        if (msg.type === 'table_status_update') {
          // 收到实时推送立即刷新
          fetchOverview();
        }
      } catch {
        // 解析失败忽略
      }
    };

    ws.onerror = () => {
      // 连接失败，等待重试
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      scheduleRetry();
    };

    function scheduleRetry() {
      if (!mountedRef.current) return;
      const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 30_000);
      retryCountRef.current += 1;
      retryRef.current = setTimeout(() => {
        if (mountedRef.current) connectWs();
      }, delay);
    }
  }, [apiHost, storeId, fetchOverview]);

  // ─── 生命周期 ───

  useEffect(() => {
    mountedRef.current = true;

    // 首次立即拉取
    fetchOverview();

    // 每 30 秒轮询
    pollRef.current = setInterval(fetchOverview, 30_000);

    // 建立 WebSocket
    connectWs();

    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
      if (retryRef.current) clearTimeout(retryRef.current);
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
      }
    };
  }, [fetchOverview, connectWs]);

  // ─── 衍生数据 ───

  const allTables = overview?.tables ?? [];
  const zoneTables = allTables.filter(t => t.zone === zone);

  const totalCount = allTables.length;
  const rushCount = allTables.filter(t => t.rush_count > 0 && !t.is_overtime).length;
  const overtimeCount = allTables.filter(t => t.is_overtime).length;

  const zones: TableZone[] = ['大厅', '包厢'];

  // ─── 渲染 ───

  return (
    <div
      style={{
        background: COLOR.bg,
        color: COLOR.text,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: 'Noto Sans SC, PingFang SC, system-ui, sans-serif',
      }}
    >
      {/* ── 顶部状态栏 ── */}
      <header
        style={{
          background: COLOR.surface,
          padding: '12px 20px',
          borderBottom: `1px solid ${COLOR.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 20, fontWeight: 'bold' }}>前厅监控</span>
          {/* WebSocket 连接指示 */}
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: connected ? COLOR.cooking : COLOR.idle,
              display: 'inline-block',
            }}
          />
        </div>

        {/* 汇总计数 */}
        <div style={{ display: 'flex', gap: 24, fontSize: 15 }}>
          <div>
            <span style={{ color: COLOR.textMuted }}>总桌数 </span>
            <span style={{ fontSize: 20, fontWeight: 'bold', color: COLOR.text }}>
              {totalCount}
            </span>
          </div>
          <div>
            <span style={{ color: COLOR.textMuted }}>催单 </span>
            <span
              style={{
                fontSize: 20,
                fontWeight: 'bold',
                color: rushCount > 0 ? COLOR.rush : COLOR.textMuted,
              }}
            >
              {rushCount}
            </span>
          </div>
          <div>
            <span style={{ color: COLOR.textMuted }}>超时 </span>
            <span
              style={{
                fontSize: 20,
                fontWeight: 'bold',
                color: overtimeCount > 0 ? COLOR.overtime : COLOR.textMuted,
              }}
            >
              {overtimeCount}
            </span>
          </div>
        </div>
      </header>

      {/* ── 区域 Tab ── */}
      <div
        style={{
          display: 'flex',
          background: COLOR.surface,
          borderBottom: `1px solid ${COLOR.border}`,
          padding: '0 20px',
          flexShrink: 0,
        }}
      >
        {zones.map(z => (
          <button
            key={z}
            onClick={() => setZone(z)}
            style={{
              padding: '14px 24px',
              minWidth: 80,
              minHeight: 48,
              background: 'none',
              border: 'none',
              borderBottom:
                zone === z ? `3px solid ${COLOR.tabActive}` : '3px solid transparent',
              color: zone === z ? COLOR.tabActive : COLOR.textMuted,
              fontSize: 17,
              fontWeight: zone === z ? 700 : 400,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            {z}
            <span
              style={{
                marginLeft: 6,
                fontSize: 13,
                color: zone === z ? COLOR.tabActive : COLOR.textMuted,
              }}
            >
              ({allTables.filter(t => t.zone === z).length})
            </span>
          </button>
        ))}
      </div>

      {/* ── 桌台网格 ── */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: 16,
        }}
      >
        {loading && (
          <div
            style={{
              textAlign: 'center',
              color: COLOR.textMuted,
              padding: 64,
              fontSize: 18,
            }}
          >
            加载中…
          </div>
        )}

        {!loading && zoneTables.length === 0 && (
          <div
            style={{
              textAlign: 'center',
              color: COLOR.textMuted,
              padding: 64,
              fontSize: 18,
            }}
          >
            {zone}暂无就餐桌台
          </div>
        )}

        {!loading && zoneTables.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: 12,
            }}
          >
            {zoneTables.map(table => (
              <TableCard
                key={table.table_id}
                table={table}
                onClick={() => setSelectedTable(table)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── 单桌详情抽屉 ── */}
      {selectedTable && (
        <TableDetailDrawer
          table={selectedTable}
          onClose={() => setSelectedTable(null)}
        />
      )}
    </div>
  );
}
