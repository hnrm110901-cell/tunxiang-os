/**
 * 桌台状态视图（服务员视角）
 * - 真实 API：fetchTableStatus()
 * - WebSocket 实时推送：/api/v1/tables/ws/layout/{store_id}
 * - 移动银台Pro模块2.2：实时人均消费 + 简约模式
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { TableCard, StatusBar } from '@tx-ds/biz';
import type { TableCardData, StatusBarItem } from '@tx-ds/biz';
import { fetchTableStatus } from '../api';
import type { TableInfo } from '../api';
import { useCrewStore } from '../store/crewStore';
import { SlimModeToggle } from '../components/SlimModeToggle';

// ─── 常量 ───────────────────────────────────────────────

const STORE_ID: string = (window as any).__STORE_ID__ || 'store_001';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

/** WebSocket URL（ws:// 或 wss://，自动跟随页面协议） */
function buildWsUrl(storeId: string): string {
  const base = API_BASE.replace(/^http/, 'ws');
  return `${base}/api/v1/tables/ws/layout/${encodeURIComponent(storeId)}`;
}

// ─── 工具函数 ───────────────────────────────────────────

/** 计算在座分钟数 */
function calcMinutes(seatedAt: string | null): number {
  if (!seatedAt) return 0;
  return Math.max(0, Math.floor((Date.now() - new Date(seatedAt).getTime()) / 60000));
}

/** 将 TableInfo 状态映射到共享组件状态 */
function mapStatus(status: TableInfo['status'], diningMinutes?: number): TableCardData['status'] {
  switch (status) {
    case 'idle':
      return 'free';
    case 'occupied':
      return diningMinutes != null && diningMinutes > 45 ? 'overtime' : 'occupied';
    case 'reserved':
      return 'reserved';
    case 'cleaning':
      return 'cleaning';
    default:
      return 'free';
  }
}

/** 将 TableInfo 转换为共享 TableCardData */
function toCardData(t: TableInfo): TableCardData {
  const diningMinutes = t.seated_at ? calcMinutes(t.seated_at) : undefined;
  return {
    tableNo: t.table_no,
    seats: (t as any).capacity ?? 4, // TODO: add capacity to TableInfo (available in tablesApi.TableInfo)
    status: mapStatus(t.status, diningMinutes),
    guestCount: t.guest_count || undefined,
    diningMinutes,
  };
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

// ─── 会员 / 消费类型 ───────────────────────────────────────

interface MemberInfo {
  name: string;
  level: string;
  visit_count: number;
}

/** 桌台当前消费金额（分），从订单 API 获取后填充 */
interface TableSpend {
  total_fen: number;
}

// ─── 主视图 ─────────────────────────────────────────────

export function TablesView() {
  const navigate = useNavigate();
  const { isSlimMode } = useCrewStore();

  const [tables, setTables] = useState<TableInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [memberMap, setMemberMap] = useState<Record<string, MemberInfo | null>>({});
  const [spendMap, setSpendMap] = useState<Record<string, TableSpend | null>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 初始拉取 ──────────────────────────────────────────

  const loadTables = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchTableStatus(STORE_ID);
      setTables(result.items);

      // 并行获取所有 occupied 桌的会员信息 + 消费金额（失败时静默忽略）
      const occupiedWithOrder = result.items.filter(
        (t) => t.status === 'occupied' && t.order_id
      );
      if (occupiedWithOrder.length > 0) {
        const tenantId = (window as any).__TENANT_ID__ || '';

        // 会员信息
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

        // 消费金额（从订单摘要接口获取 total_fen）
        const spendResults = await Promise.allSettled(
          occupiedWithOrder.map((t) =>
            fetch(`/api/v1/trade/orders/${encodeURIComponent(t.order_id ?? '')}/summary`, {
              headers: { 'X-Tenant-ID': tenantId },
            })
              .then((r) => r.json())
              .then((res) => ({
                table_no: t.table_no,
                spend: res.ok && res.data ? ({ total_fen: (res.data.total_fen ?? res.data.final_amount_fen ?? 0) } as TableSpend) : null,
              }))
          )
        );
        const sm: Record<string, TableSpend | null> = {};
        spendResults.forEach((r) => {
          if (r.status === 'fulfilled' && r.value) {
            sm[r.value.table_no] = r.value.spend;
          }
        });
        setSpendMap(sm);
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
  const occupiedCount = tables.filter((t) => t.status === 'occupied').length;
  const reservedCount = tables.filter((t) => t.status === 'reserved').length;
  const total = tables.length;

  const statsItems: StatusBarItem[] = [
    { label: '空闲', value: idleCount, suffix: '台', color: '#52c41a' },
    { label: '在座', value: occupiedCount, suffix: '台', color: 'var(--tx-primary, #FF6B35)' },
    { label: '预定', value: reservedCount, suffix: '台', color: '#faad14' },
    { label: '总计', value: total, suffix: '台' },
  ];

  // ── 渲染 ─────────────────────────────────────────────

  return (
    <div style={{ padding: 16, paddingBottom: 32 }}>
      {/* shimmer 动画 + txPulse 脉冲动画 */}
      <style>{`
        @keyframes shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @keyframes txPulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(163,45,45,.4); }
          50%       { box-shadow: 0 0 0 6px rgba(163,45,45,.0); }
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
            <StatusBar size="compact" items={statsItems} />
          )}
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <SlimModeToggle compact />
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

      {/* 简约模式横幅提示 */}
      {isSlimMode && (
        <div
          style={{
            background: 'rgba(255,107,35,0.12)',
            borderBottom: '1px solid rgba(255,107,35,0.3)',
            padding: '6px 16px',
            fontSize: 13,
            color: '#FF6B35',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span>⚡</span>
          <span>简约模式已开启 — 高峰期精简视图</span>
        </div>
      )}

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
                gridTemplateColumns: isSlimMode ? 'repeat(3, 1fr)' : '1fr 1fr',
                gap: isSlimMode ? 8 : 10,
              }}
            >
              {tables.map((t) => (
                <TableCard
                  key={t.table_no}
                  table={toCardData(t)}
                  onClick={(card) => {
                    const original = tables.find((tb) => tb.table_no === card.tableNo);
                    if (original) handleTableTap(original);
                  }}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
