/**
 * 桌台状态视图（服务员视角）
 * - 真实 API：fetchTableStatus()
 * - WebSocket 实时推送：/api/v1/tables/ws/layout/{store_id}
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchTableStatus } from '../api';
import type { TableInfo } from '../api';

// ─── 常量 ───────────────────────────────────────────────

const STORE_ID: string = (window as any).__STORE_ID__ || 'store_001';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

/** WebSocket URL（ws:// 或 wss://，自动跟随页面协议） */
function buildWsUrl(storeId: string): string {
  const base = API_BASE.replace(/^http/, 'ws');
  return `${base}/api/v1/tables/ws/layout/${encodeURIComponent(storeId)}`;
}

// ─── 状态颜色 & 标签 ────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  idle: '#52c41a',
  occupied: 'var(--tx-primary, #FF6B35)',
  reserved: '#faad14',
  cleaning: '#8c8c8c',
};

const STATUS_LABEL: Record<string, string> = {
  idle: '空闲',
  occupied: '在座',
  reserved: '预定',
  cleaning: '清台',
};

// ─── 工具函数 ───────────────────────────────────────────

/** 计算在座分钟数 */
function calcMinutes(seatedAt: string | null): number {
  if (!seatedAt) return 0;
  return Math.max(0, Math.floor((Date.now() - new Date(seatedAt).getTime()) / 60000));
}

/** 格式化分钟 → "35分" / "1h20分" */
function formatDuration(min: number): string {
  if (min < 60) return `${min}分`;
  return `${Math.floor(min / 60)}h${min % 60}分`;
}

// ─── Skeleton（加载占位） ───────────────────────────────

function SkeletonCard() {
  return (
    <div
      style={{
        height: 110,
        borderRadius: 10,
        background: '#112228',
        borderLeft: '4px solid #1e3a45',
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      {[80, 60, 40].map((w, i) => (
        <div
          key={i}
          style={{
            height: 14,
            width: `${w}%`,
            borderRadius: 4,
            background: 'linear-gradient(90deg, #1e3a45 25%, #234455 50%, #1e3a45 75%)',
            backgroundSize: '200% 100%',
            animation: 'shimmer 1.4s infinite',
          }}
        />
      ))}
    </div>
  );
}

// ─── 会员等级配置 ────────────────────────────────────────

const MEMBER_LEVEL_COLOR: Record<string, string> = {
  bronze: '#CD7F32',
  silver: '#A8A8A8',
  gold: '#FFD700',
  diamond: '#B9F2FF',
};

const MEMBER_LEVEL_LABEL: Record<string, string> = {
  bronze: '铜卡',
  silver: '银卡',
  gold: '金卡',
  diamond: '钻石卡',
};

// ─── 台位卡片 ───────────────────────────────────────────

interface MemberInfo {
  name: string;
  level: string;
  visit_count: number;
}

interface TableCardProps {
  table: TableInfo;
  onTap: (t: TableInfo) => void;
  member?: MemberInfo | null;
}

function TableCard({ table, onTap, member }: TableCardProps) {
  const [pressed, setPressed] = useState(false);
  const mins = calcMinutes(table.seated_at);
  const color = STATUS_COLOR[table.status] || '#8c8c8c';
  const label = STATUS_LABEL[table.status] || table.status;

  return (
    <div
      onClick={() => onTap(table)}
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerCancel={() => setPressed(false)}
      style={{
        borderRadius: 10,
        background: '#112228',
        borderLeft: `4px solid ${color}`,
        padding: '14px 16px',
        cursor: 'pointer',
        WebkitTapHighlightColor: 'transparent',
        transform: pressed ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 0.1s ease',
        userSelect: 'none',
        minHeight: 48,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      {/* 行1：桌号 + 状态 tag */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>{table.table_no}</span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: color,
            border: `1px solid ${color}`,
            borderRadius: 4,
            padding: '1px 6px',
          }}
        >
          {label}
        </span>
      </div>

      {/* 行2：人数 + 时长 */}
      {table.status !== 'idle' && (
        <div style={{ fontSize: 14, color: '#aaa' }}>
          {table.guest_count > 0 ? `${table.guest_count}人` : ''}
          {table.status === 'occupied' && table.seated_at
            ? `${table.guest_count > 0 ? ' · ' : ''}${formatDuration(mins)}`
            : ''}
        </div>
      )}

      {/* 行3：会员标识（occupied 且有绑定会员时显示） */}
      {table.status === 'occupied' && member && (
        <div
          style={{
            fontSize: 16,
            color: MEMBER_LEVEL_COLOR[member.level] || '#FF6B35',
            marginTop: 4,
          }}
        >
          👤 {member.name} · {MEMBER_LEVEL_LABEL[member.level] || member.level} · 第{member.visit_count}次
        </div>
      )}

      {/* 行4：空闲提示 或 占座金额占位（金额需订单详情API，此处展示在座标记） */}
      {table.status === 'idle' && (
        <div style={{ fontSize: 14, color: STATUS_COLOR.idle }}>空闲 &rsaquo;</div>
      )}
    </div>
  );
}

// ─── 主视图 ─────────────────────────────────────────────

export function TablesView() {
  const navigate = useNavigate();

  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [memberMap, setMemberMap] = useState<Record<string, MemberInfo | null>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 初始拉取 ──────────────────────────────────────────

  const loadTables = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchTableStatus(STORE_ID);
      setTables(result.items);

      // 并行获取所有 occupied 桌的会员信息（失败时静默忽略）
      const occupiedWithOrder = result.items.filter(
        (t) => t.status === 'occupied' && t.order_id
      );
      if (occupiedWithOrder.length > 0) {
        const tenantId = (window as any).__TENANT_ID__ || '';
        const memberResults = await Promise.allSettled(
          occupiedWithOrder.map((t) =>
            fetch(`/api/v1/member/by-order?order_id=${t.order_id}`, {
              headers: { 'X-Tenant-ID': tenantId },
            })
              .then((r) => r.json())
              .then((res) => ({
                table_no: t.table_no,
                member: res.ok ? (res.data as MemberInfo | null) : null,
              }))
          )
        );
        const map: Record<string, MemberInfo | null> = {};
        memberResults.forEach((r) => {
          if (r.status === 'fulfilled' && r.value) {
            map[r.value.table_no] = r.value.member;
          }
        });
        setMemberMap(map);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  // ── WebSocket ─────────────────────────────────────────

  const connectWs = () => {
    if (wsRef.current) {
      wsRef.current.close();
    }

    const url = buildWsUrl(STORE_ID);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string);
        if (msg.type !== 'table_status_update') return;

        setTables((prev) =>
          prev.map((t) =>
            t.table_no === msg.table_number
              ? {
                  ...t,
                  status: msg.new_status,
                  guest_count: msg.guest_count ?? t.guest_count,
                  order_id: msg.order_no ?? t.order_id,
                  seated_at:
                    msg.new_status === 'occupied'
                      ? (msg.timestamp ?? t.seated_at)
                      : msg.new_status === 'idle'
                      ? null
                      : t.seated_at,
                }
              : t
          )
        );
      } catch {
        // 忽略解析错误
      }
    };

    ws.onclose = () => {
      // 5 秒后自动重连
      retryTimerRef.current = setTimeout(connectWs, 5000);
    };

    ws.onerror = () => {
      ws.close();
    };
  };

  // ── 生命周期 ──────────────────────────────────────────

  useEffect(() => {
    loadTables();
    connectWs();

    return () => {
      wsRef.current?.close();
      wsRef.current = null;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 台位点击 ──────────────────────────────────────────

  const handleTableTap = (t: TableInfo) => {
    if (t.status === 'occupied') {
      navigate(`/table-detail?table=${encodeURIComponent(t.table_no)}&order_id=${encodeURIComponent(t.order_id ?? '')}`);
    } else {
      navigate(`/open-table?table=${encodeURIComponent(t.table_no)}`);
    }
  };

  // ── 扫码 ─────────────────────────────────────────────

  const parseScanResult = (raw: string) => {
    let tableNo = '';
    if (raw.startsWith('txos://table/')) {
      const parts = raw.split('/');
      tableNo = parts[parts.length - 1];
    } else if (/^[A-Za-z0-9]{2,6}$/.test(raw.trim())) {
      tableNo = raw.trim().toUpperCase();
    }

    if (!tableNo) {
      return;
    }

    navigate(`/open-table?table=${encodeURIComponent(tableNo)}&prefilled=true`);
  };

  const handleScanQR = () => {
    if ((window as any).TXBridge) {
      (window as any).TXBridge.scan();
      (window as any).TXBridge.onScanResult = (result: string) => {
        parseScanResult(result);
      };
    } else {
      const mock = prompt('开发模式 - 输入桌台号（如 A01）:');
      if (mock) parseScanResult(`txos://table/store_001/${mock.trim().toUpperCase()}`);
    }
  };

  // ── 汇总统计 ──────────────────────────────────────────

  const idleCount = tables.filter((t) => t.status === 'idle').length;
  const total = tables.length;

  // ── 渲染 ─────────────────────────────────────────────

  return (
    <div style={{ padding: 16, paddingBottom: 32 }}>
      {/* shimmer 动画 */}
      <style>{`
        @keyframes shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>

      {/* 顶部栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <div>
          <h3 style={{ margin: 0, fontSize: 18, color: '#fff' }}>桌台状态</h3>
          {!loading && !error && total > 0 && (
            <div style={{ fontSize: 13, color: '#aaa', marginTop: 2 }}>
              空闲{' '}
              <span style={{ color: STATUS_COLOR.idle, fontWeight: 700 }}>{idleCount}</span>
              {' / '}总{' '}
              <span style={{ color: '#fff', fontWeight: 700 }}>{total}</span> 台
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => navigate('/table-map')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              minHeight: 48,
              padding: '0 16px',
              background: 'transparent',
              border: '1.5px solid var(--tx-primary, #FF6B35)',
              borderRadius: 8,
              color: 'var(--tx-primary, #FF6B35)',
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            🗺️ 地图视图
          </button>
          <button
            onClick={handleScanQR}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              minHeight: 48,
              padding: '0 16px',
              background: 'var(--tx-primary, #FF6B35)',
              border: 'none',
              borderRadius: 8,
              color: '#ffffff',
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            📷 扫码开台
          </button>
        </div>
      </div>

      {/* 加载 Skeleton */}
      {loading && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 10,
          }}
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {/* 网络错误 */}
      {!loading && error && (
        <div
          style={{
            textAlign: 'center',
            padding: '40px 16px',
            color: '#aaa',
          }}
        >
          <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
          <div style={{ fontSize: 16, marginBottom: 20 }}>{error}</div>
          <button
            onClick={loadTables}
            style={{
              minHeight: 48,
              padding: '0 32px',
              background: 'var(--tx-primary, #FF6B35)',
              border: 'none',
              borderRadius: 8,
              color: '#fff',
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            重试
          </button>
        </div>
      )}

      {/* 台位列表（2列网格） */}
      {!loading && !error && (
        <>
          {tables.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#aaa', padding: '40px 0', fontSize: 16 }}>
              暂无桌台数据
            </div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 10,
              }}
            >
              {tables.map((t) => (
                <TableCard
                  key={t.table_no}
                  table={t}
                  onTap={handleTableTap}
                  member={memberMap[t.table_no]}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
