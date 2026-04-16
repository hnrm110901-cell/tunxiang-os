/**
 * 单店详情页（集团驾驶舱下钻）
 *
 * URL: /store-detail?store_id=xxx&store_name=xxx
 * 展示单店今日数据：营收/订单/翻台宫格、小时营收分布、桌台状态、今日告警
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import { fetchTableStatus, TableInfo } from '../api/index';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  red: '#ef4444',
  orange: '#f97316',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  yellow: '#eab308',
};

/* ---------- 类型定义 ---------- */

interface StoreStats {
  revenue_fen: number;
  order_count: number;
  table_turnover: number;
  current_diners: number;
  avg_serve_time_min: number;
  occupied_tables: number;
  total_tables: number;
}

interface HourlyRevenue {
  hour: number;
  revenue_fen: number;
}

interface StoreAlert {
  severity: 'danger' | 'warning' | 'info';
  title: string;
  body: string;
  time: string;
}

/* ---------- API 工具 ---------- */

const TENANT_ID = (): string =>
  (typeof window !== 'undefined' && (window as unknown as Record<string, string>).__TENANT_ID__) || '';

async function txFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID(),
      ...(options.headers || {}),
    },
  });
  const json = await res.json();
  if (!res.ok || json.ok === false) {
    throw new Error(json.error?.message || json.detail || `HTTP ${res.status}`);
  }
  return json.data ?? json;
}

/* ---------- 工具 ---------- */
/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function tableStatusColor(status: TableInfo['status']): string {
  switch (status) {
    case 'occupied':  return C.accent;
    case 'reserved':  return C.yellow;
    case 'cleaning':  return C.orange;
    case 'idle':
    default:          return C.muted;
  }
}

function tableStatusLabel(status: TableInfo['status']): string {
  switch (status) {
    case 'occupied':  return '用餐中';
    case 'reserved':  return '已预订';
    case 'cleaning':  return '清台中';
    case 'idle':
    default:          return '空闲';
  }
}

/* ---------- 子组件：3宫格指标 ---------- */
function StatsGrid({ stats }: { stats: StoreStats | null }) {
  const items = stats ? [
    { label: '今日营收', value: `¥${fenToYuan(stats.revenue_fen)}`, color: C.accent },
    { label: '订单数',   value: `${stats.order_count}单`,          color: C.white },
    { label: '翻台率',   value: `${stats.table_turnover}次`,       color: C.white },
    { label: '在餐人数', value: `${stats.current_diners}人`,       color: C.white },
    { label: '平均服务', value: `${stats.avg_serve_time_min}分钟`, color: C.white },
    { label: '桌台占用', value: `${stats.occupied_tables}/${stats.total_tables}`, color: C.white },
  ] : [
    { label: '今日营收', value: '-', color: C.muted },
    { label: '订单数',   value: '-', color: C.muted },
    { label: '翻台率',   value: '-', color: C.muted },
    { label: '在餐人数', value: '-', color: C.muted },
    { label: '平均服务', value: '-', color: C.muted },
    { label: '桌台占用', value: '-', color: C.muted },
  ];

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr 1fr 1fr',
      gap: 8, marginBottom: 14,
    }}>
      {items.map(({ label, value, color }) => (
        <div key={label} style={{
          background: C.card, borderRadius: 10,
          padding: '12px 10px', textAlign: 'center',
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 3 }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

/* ---------- 子组件：小时营收 CSS Bar ---------- */
function HourlyChart({ data }: { data: HourlyRevenue[] }) {
  if (data.length === 0) {
    return (
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: C.muted, marginBottom: 8 }}>
          今日小时营收分布
        </div>
        <div style={{
          background: C.card, borderRadius: 12,
          padding: '20px 10px', border: `1px solid ${C.border}`,
          textAlign: 'center', color: C.muted, fontSize: 14,
        }}>
          暂无数据
        </div>
      </div>
    );
  }
  const maxRev = Math.max(...data.map(d => d.revenue_fen));
  const currentHour = new Date().getHours();

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: C.muted, marginBottom: 8 }}>
        今日小时营收分布
      </div>
      <div style={{
        background: C.card, borderRadius: 12,
        padding: '14px 10px', border: `1px solid ${C.border}`,
      }}>
        {/* 柱图 */}
        <div style={{
          display: 'flex', alignItems: 'flex-end', gap: 3,
          height: 60, marginBottom: 6,
        }}>
          {data.map(({ hour, revenue_fen }) => {
            const heightPct = maxRev > 0 ? (revenue_fen / maxRev) * 100 : 0;
            const isCurrent = hour === currentHour;
            const isPeak = revenue_fen === maxRev;
            return (
              <div key={hour} style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'flex-end', height: '100%',
                position: 'relative',
              }}>
                {isPeak && (
                  <div style={{
                    position: 'absolute', top: -14,
                    fontSize: 9, color: C.accent, whiteSpace: 'nowrap',
                  }}>
                    高峰
                  </div>
                )}
                <div style={{
                  width: '100%', borderRadius: '2px 2px 0 0',
                  height: `${Math.max(heightPct, 3)}%`,
                  background: isCurrent ? C.green : isPeak ? C.accent : '#1e3a46',
                }} />
              </div>
            );
          })}
        </div>

        {/* 小时标注（只显示偶数小时避免拥挤） */}
        <div style={{ display: 'flex', gap: 3 }}>
          {data.map(({ hour }) => (
            <div key={hour} style={{
              flex: 1, textAlign: 'center', fontSize: 9, color: C.muted,
            }}>
              {hour % 2 === 0 ? `${hour}` : ''}
            </div>
          ))}
        </div>

        {/* 说明 */}
        <div style={{
          display: 'flex', gap: 12, marginTop: 8, paddingTop: 8,
          borderTop: `1px solid ${C.border}`, fontSize: 12, color: C.muted,
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: C.accent, display: 'inline-block' }} />
            高峰时段
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: C.green, display: 'inline-block' }} />
            当前时段
          </span>
        </div>
      </div>
    </div>
  );
}

/* ---------- 子组件：桌台状态 ---------- */
function TablesSection({ tables, loading }: { tables: TableInfo[]; loading: boolean }) {
  if (loading) {
    return (
      <div style={{
        background: C.card, borderRadius: 12, padding: 16,
        border: `1px solid ${C.border}`, marginBottom: 14,
        color: C.muted, fontSize: 14, textAlign: 'center',
      }}>
        加载桌台数据...
      </div>
    );
  }

  // 按状态排序：occupied > reserved > cleaning > idle
  const statusOrder: Record<TableInfo['status'], number> = { occupied: 0, reserved: 1, cleaning: 2, idle: 3 };
  const sorted = [...tables].sort((a, b) => statusOrder[a.status] - statusOrder[b.status]);

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: C.muted, marginBottom: 8 }}>
        桌台实时状态（{tables.length}桌）
      </div>
      <div style={{
        background: C.card, borderRadius: 12,
        padding: '12px 10px', border: `1px solid ${C.border}`,
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8,
      }}>
        {sorted.slice(0, 24).map(t => (
          <div key={t.table_no} style={{
            borderRadius: 8, padding: '8px 4px', textAlign: 'center',
            background: `${tableStatusColor(t.status)}22`,
            border: `1px solid ${tableStatusColor(t.status)}44`,
          }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.white }}>
              {t.table_no}
            </div>
            <div style={{ fontSize: 10, color: tableStatusColor(t.status), marginTop: 2 }}>
              {tableStatusLabel(t.status)}
            </div>
            {t.guest_count > 0 && (
              <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>
                {t.guest_count}人
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- 子组件：今日告警 ---------- */
function AlertsSection({ alerts }: { alerts: StoreAlert[] }) {
  function severityColor(s: 'danger' | 'warning' | 'info'): string {
    if (s === 'danger')  return C.red;
    if (s === 'warning') return C.orange;
    return C.muted;
  }

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: C.muted, marginBottom: 8 }}>
        今日告警
      </div>
      {alerts.length === 0 ? (
        <div style={{
          background: C.card, borderRadius: 10, padding: '14px 12px',
          border: `1px solid ${C.border}`, textAlign: 'center',
          fontSize: 14, color: C.muted,
        }}>
          暂无告警
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {alerts.map((a, i) => (
            <div key={i} style={{
              background: C.card, borderRadius: 10,
              padding: '10px 12px',
              border: `1px solid ${C.border}`,
              borderLeftWidth: 4,
              borderLeftColor: severityColor(a.severity),
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 14, fontWeight: 700, color: C.white }}>{a.title}</span>
                <span style={{ fontSize: 12, color: C.muted }}>{a.time}</span>
              </div>
              <div style={{ fontSize: 13, color: C.muted }}>{a.body}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- 主页面 ---------- */
export function StoreDetailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const storeId = searchParams.get('store_id') || '';
  const storeName = searchParams.get('store_name') || '门店详情';

  const [tables, setTables] = useState<TableInfo[]>([]);
  const [tablesLoading, setTablesLoading] = useState(true);
  const [tablesError, setTablesError] = useState<string | null>(null);

  // ── 门店综合数据 state ──
  const [stats, setStats] = useState<StoreStats | null>(null);
  const [hourlyRevenue, setHourlyRevenue] = useState<HourlyRevenue[]>([]);
  const [alerts, setAlerts] = useState<StoreAlert[]>([]);

  const loadTables = useCallback(async () => {
    if (!storeId) return;
    setTablesLoading(true);
    setTablesError(null);
    try {
      const result = await fetchTableStatus(storeId);
      setTables(result.items);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '桌台加载失败';
      setTablesError(msg);
    } finally {
      setTablesLoading(false);
    }
  }, [storeId]);

  // ── 加载门店今日综合数据 ──
  const loadStoreInfo = useCallback(async () => {
    if (!storeId) return;
    try {
      const res = await txFetch<Record<string, unknown>>(
        `/api/v1/trade/store/info?store_id=${encodeURIComponent(storeId)}&date=today`,
      );
      setStats((res.stats ?? null) as StoreStats | null);
      setHourlyRevenue((res.hourly_revenue ?? []) as HourlyRevenue[]);
      setAlerts((res.alerts ?? []) as StoreAlert[]);
    } catch {
      setStats(null);
      setHourlyRevenue([]);
      setAlerts([]);
    }
  }, [storeId]);

  useEffect(() => {
    loadTables();
    loadStoreInfo();
  }, [loadTables, loadStoreInfo]);

  return (
    <div style={{
      background: C.bg, minHeight: '100vh',
      padding: '0 12px 80px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif',
    }}>
      {/* 顶部导航 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 40,
        background: C.bg, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '12px 0', marginBottom: 14,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: C.muted, fontSize: 24, padding: '0 4px',
            minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          ‹
        </button>
        <div>
          <div style={{ fontSize: 17, fontWeight: 700, color: C.white }}>{storeName}</div>
          <div style={{ fontSize: 12, color: C.muted }}>今日经营数据</div>
        </div>
      </div>

      {/* Section 1: 3宫格 */}
      <StatsGrid stats={stats} />

      {/* Section 2: 小时营收 */}
      <HourlyChart data={hourlyRevenue} />

      {/* Section 3: 桌台状态 */}
      {tablesError ? (
        <div style={{
          background: `${C.red}22`, border: `1px solid ${C.red}55`,
          borderRadius: 10, padding: '12px 14px', marginBottom: 14,
          fontSize: 14, color: C.red,
        }}>
          桌台加载失败：{tablesError}
        </div>
      ) : (
        <TablesSection tables={tables} loading={tablesLoading} />
      )}

      {/* Section 4: 今日告警 */}
      <AlertsSection alerts={alerts} />
    </div>
  );
}
