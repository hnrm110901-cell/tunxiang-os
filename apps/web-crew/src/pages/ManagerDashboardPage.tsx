/**
 * 店长实时经营看板
 * 路由：/manager-dashboard
 * 15秒自动刷新，Promise.allSettled 并行加载，API失败降级Mock
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

/* ---------- Design Token ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  cardHover: '#152d38',
  border: '#1a2a33',
  text: '#E0E0E0',
  textSub: '#8FA3AA',
  muted: '#64748b',
  primary: '#FF6B35',
  primaryActive: '#E55A28',
  primaryLight: 'rgba(255,107,53,0.15)',
  success: '#0F6E56',
  successBg: 'rgba(15,110,86,0.14)',
  successText: '#2de8aa',
  warning: '#BA7517',
  warningBg: 'rgba(186,117,23,0.14)',
  warningText: '#FFB938',
  danger: '#A32D2D',
  dangerBg: 'rgba(163,45,45,0.14)',
  dangerText: '#FF6060',
  info: '#185FA5',
  infoBg: 'rgba(24,95,165,0.14)',
  infoText: '#60AAFF',
  divider: '#1a2a33',
  // table status colors
  tableEmpty: '#2a3a44',
  tableDining: '#FF6B35',
  tableDirty: '#BA7517',
  tableReserved: '#185FA5',
};

/* ---------- 类型定义 ---------- */
interface DailySummary {
  date: string;
  revenue: number;           // 元
  order_count: number;
  table_turn_rate: number;   // 翻台率 0-1
  avg_check: number;         // 客单价 元
  guest_count: number;
  gross_margin?: number;     // 毛利率 0-1
}

interface PnlData {
  revenue: number;
  food_cost: number;
  labor_cost: number;
  gross_profit: number;
  gross_margin: number;      // 0-1
  net_profit?: number;
}

type TableStatus = 'empty' | 'dining' | 'dirty' | 'reserved';

interface TableInfo {
  table_id: string;
  table_no: string;
  status: TableStatus;
  pax?: number;
  elapsed_min?: number;
}

interface ChecklistItem {
  id: string;
  code: string;  // E1~E8
  name: string;
  status: 'pending' | 'in_progress' | 'completed';
}

interface SupplyAlert {
  ingredient_id: string;
  name: string;
  days_remaining: number;
  suggested_purchase?: number;
  unit?: string;
  risk_level: 'low' | 'medium' | 'high';
}

interface InventoryAnalysis {
  high_risk_count: number;
  alerts: SupplyAlert[];
  summary?: string;
}

interface StaffMember {
  id: string;
  name: string;
  role: string;
  status: 'on_duty' | 'break' | 'off';
}

interface DashboardData {
  summary: DailySummary | null;
  pnl: PnlData | null;
  tables: TableInfo[];
  checklist: ChecklistItem[];
  inventory: InventoryAnalysis | null;
  staff: StaffMember[];
}

/* ---------- 工具函数 ---------- */
function getTenantId(): string {
  return localStorage.getItem('tenant_id') ?? '';
}

function getStoreId(): string {
  return (window as any).__STORE_ID__ || localStorage.getItem('store_id') || '1';
}

function getHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Tenant-ID': getTenantId(),
  };
}

function getToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function getBusinessPeriod(): string {
  const h = new Date().getHours();
  if (h >= 7 && h < 11) return '早市';
  if (h >= 11 && h < 14) return '午市';
  if (h >= 17 && h < 22) return '晚市';
  return '营业中';
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

function formatRevenue(yuan: number): string {
  if (yuan >= 10000) return (yuan / 10000).toFixed(2) + '万';
  return yuan.toFixed(0) + '元';
}

// Mock 数据已全部移除，API 失败时降级为空数据

/* ---------- API 调用函数（使用 txFetch，自动携带 X-Tenant-ID）---------- */

async function fetchKpi(): Promise<DailySummary> {
  return txFetch<DailySummary>('/api/v1/trade/store/kpi?date=today');
}

async function fetchAlerts(): Promise<InventoryAnalysis> {
  return txFetch<InventoryAnalysis>('/api/v1/analytics/alerts?status=active');
}

async function fetchStaffOnDuty(): Promise<StaffMember[]> {
  const res = await txFetch<{ items: StaffMember[] }>('/api/v1/org/employees/on-duty');
  return res.items ?? [];
}

async function fetchTables(): Promise<TableInfo[]> {
  const res = await txFetch<{ items: TableInfo[] }>('/api/v1/trade/tables?store_id=' + getStoreId());
  return res.items ?? [];
}

async function fetchChecklist(): Promise<ChecklistItem[]> {
  const res = await txFetch<{ checklist: ChecklistItem[] }>(
    `/api/v1/ops/settlement/checklist?store_id=${getStoreId()}`
  );
  return res.checklist ?? [];
}


/* ---------- 子组件 ---------- */

/** KPI 指标卡 */
function KpiCard({
  label, value, unit, sub, highlight,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  highlight?: 'danger' | 'warning' | 'success';
}) {
  const valueColor =
    highlight === 'danger' ? C.dangerText :
    highlight === 'warning' ? C.warningText :
    highlight === 'success' ? C.successText :
    '#FFFFFF';

  return (
    <div style={{
      minWidth: 140,
      height: 80,
      background: C.card,
      borderRadius: 12,
      padding: '12px 16px',
      flexShrink: 0,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
      border: `1px solid ${C.border}`,
    }}>
      <span style={{ fontSize: 14, color: C.textSub, whiteSpace: 'nowrap' }}>{label}</span>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span style={{ fontSize: 28, fontWeight: 700, color: valueColor, lineHeight: 1 }}>{value}</span>
        {unit && <span style={{ fontSize: 14, color: C.textSub }}>{unit}</span>}
      </div>
      {sub && <span style={{ fontSize: 13, color: C.muted }}>{sub}</span>}
    </div>
  );
}

/** 桌台小格子 */
function TableDot({ table }: { table: TableInfo }) {
  const statusColor: Record<TableStatus, string> = {
    empty: C.tableEmpty,
    dining: C.tableDining,
    dirty: C.tableDirty,
    reserved: C.tableReserved,
  };
  return (
    <div
      title={`${table.table_no} · ${table.status}${table.elapsed_min ? ` · ${table.elapsed_min}分` : ''}`}
      style={{
        width: 40,
        height: 40,
        borderRadius: 8,
        background: statusColor[table.status],
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 13,
        fontWeight: 600,
        color: table.status === 'empty' ? C.muted : '#fff',
        flexShrink: 0,
        cursor: 'default',
      }}
    >
      {table.table_no.replace(/[A-Z]/, '')}
    </div>
  );
}

/** E1-E8 单项 */
function ChecklistRow({ item }: { item: ChecklistItem }) {
  const isComplete = item.status === 'completed';
  const isInProgress = item.status === 'in_progress';
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '8px 0',
      borderBottom: `1px solid ${C.divider}`,
    }}>
      <span style={{
        width: 32,
        height: 32,
        borderRadius: 8,
        background: isComplete ? C.successBg : isInProgress ? C.warningBg : C.card,
        border: `1px solid ${isComplete ? C.success : isInProgress ? C.warning : C.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 13,
        fontWeight: 700,
        color: isComplete ? C.successText : isInProgress ? C.warningText : C.muted,
        flexShrink: 0,
      }}>
        {isComplete ? '✓' : item.code}
      </span>
      <span style={{ fontSize: 16, color: isComplete ? C.muted : C.text, flex: 1 }}>{item.name}</span>
      {!isComplete && (
        <span style={{
          fontSize: 13,
          padding: '3px 10px',
          borderRadius: 6,
          background: isInProgress ? C.warningBg : C.dangerBg,
          color: isInProgress ? C.warningText : C.dangerText,
          fontWeight: 600,
        }}>
          {isInProgress ? '进行中' : '待完成'}
        </span>
      )}
    </div>
  );
}

/** 库存预警行 */
function InventoryRow({ alert }: { alert: SupplyAlert }) {
  const isCritical = alert.days_remaining <= 3;
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '10px 0',
      borderBottom: `1px solid ${C.divider}`,
    }}>
      <div style={{
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: isCritical ? C.dangerText : C.warningText,
        flexShrink: 0,
        marginTop: 2,
      }} />
      <span style={{
        fontSize: 16,
        fontWeight: 600,
        color: isCritical ? C.dangerText : C.text,
        minWidth: 60,
      }}>
        {alert.name}
      </span>
      <span style={{
        fontSize: 14,
        color: isCritical ? C.dangerText : C.warningText,
        flex: 1,
      }}>
        剩{alert.days_remaining}天
      </span>
      {alert.suggested_purchase != null && (
        <span style={{ fontSize: 14, color: C.textSub }}>
          建采 {alert.suggested_purchase}{alert.unit ?? ''}
        </span>
      )}
    </div>
  );
}

/* ---------- 主页面 ---------- */
export function ManagerDashboardPage() {
  const navigate = useNavigate();

  const [data, setData] = useState<DashboardData>({
    summary: null,
    pnl: null,
    tables: [],
    checklist: [],
    inventory: null,
    staff: [],
  });
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async (isManual = false) => {
    if (isManual) setRefreshing(true);

    const [
      kpiResult,
      alertsResult,
      staffResult,
      tablesResult,
      checklistResult,
    ] = await Promise.allSettled([
      fetchKpi(),
      fetchAlerts(),
      fetchStaffOnDuty(),
      fetchTables(),
      fetchChecklist(),
    ]);

    const newData: DashboardData = {
      summary: kpiResult.status === 'fulfilled' ? kpiResult.value : null,
      pnl: null,  // 由 KPI 接口覆盖，暂不单独请求
      tables: tablesResult.status === 'fulfilled' ? tablesResult.value : [],
      checklist: checklistResult.status === 'fulfilled' ? checklistResult.value : [],
      inventory: alertsResult.status === 'fulfilled' ? alertsResult.value : null,
      staff: staffResult.status === 'fulfilled' ? staffResult.value : [],
    };

    setData(newData);
    setLastUpdated(new Date());
    setLoading(false);
    setRefreshing(false);
  }, []);

  // 首次加载
  useEffect(() => {
    loadData();
  }, [loadData]);

  // 15秒自动刷新
  useEffect(() => {
    intervalRef.current = setInterval(() => {
      loadData();
    }, 15000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [loadData]);

  /* ---------- 派生数据 ---------- */
  const summary = data.summary;
  const pnl = data.pnl;
  const tables = data.tables;
  const checklist = data.checklist;
  const inventory = data.inventory;
  const staff = data.staff;

  const totalTables = tables.length;
  const diningTables = tables.filter(t => t.status === 'dining').length;
  const dirtyTables = tables.filter(t => t.status === 'dirty').length;

  const completedCount = checklist.filter(i => i.status === 'completed').length;
  const pendingItems = checklist.filter(i => i.status !== 'completed');

  const onDutyStaff = staff.filter(s => s.status === 'on_duty');
  const breakStaff = staff.filter(s => s.status === 'break');

  // Group staff by role
  const roleGroups: Record<string, StaffMember[]> = {};
  onDutyStaff.forEach(s => {
    if (!roleGroups[s.role]) roleGroups[s.role] = [];
    roleGroups[s.role].push(s);
  });

  const grossMargin = pnl?.gross_margin ?? summary?.gross_margin ?? null;
  const grossMarginHighlight: 'danger' | 'warning' | 'success' | undefined =
    grossMargin == null ? undefined :
    grossMargin < 0.35 ? 'danger' :
    grossMargin < 0.45 ? 'warning' :
    'success';

  /* ---------- 渲染 ---------- */
  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        background: C.bg,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        gap: 16,
        color: C.muted,
        fontSize: 16,
      }}>
        <div style={{
          width: 40,
          height: 40,
          border: `3px solid ${C.border}`,
          borderTopColor: C.primary,
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        加载经营数据...
      </div>
    );
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: C.bg,
      color: C.text,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      paddingBottom: 32,
    }}>

      {/* ===== 顶部导航栏 ===== */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        background: C.card,
        borderBottom: `1px solid ${C.border}`,
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        minHeight: 56,
      }}>
        {/* 左：日期 + 营业时段 */}
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: C.text }}>
            {new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', weekday: 'short' })}
          </div>
          <div style={{
            display: 'inline-block',
            fontSize: 13,
            color: C.primary,
            background: C.primaryLight,
            borderRadius: 6,
            padding: '1px 8px',
            marginTop: 2,
          }}>
            {getBusinessPeriod()}
          </div>
        </div>

        {/* 中：门店名 */}
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text, textAlign: 'center', flex: 1 }}>
          店长看板
        </div>

        {/* 右：刷新按钮 + 最后更新时间 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            style={{
              minWidth: 48,
              minHeight: 48,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: refreshing ? C.border : C.primaryLight,
              border: 'none',
              borderRadius: 10,
              color: refreshing ? C.muted : C.primary,
              fontSize: 20,
              cursor: refreshing ? 'not-allowed' : 'pointer',
              transition: 'transform 0.2s, background 0.2s',
              transform: refreshing ? 'rotate(360deg)' : 'none',
            }}
            aria-label="刷新数据"
          >
            ↻
          </button>
          {lastUpdated && (
            <span style={{ fontSize: 12, color: C.muted }}>
              {formatTime(lastUpdated)}
            </span>
          )}
        </div>
      </header>

      <div style={{ padding: '0 16px' }}>

        {/* ===== 2. 今日关键指标卡片行（横向滚动） ===== */}
        <section style={{ marginTop: 20 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: C.textSub, margin: '0 0 12px' }}>
            今日关键指标
          </h2>
          <div style={{
            display: 'flex',
            gap: 12,
            overflowX: 'auto',
            paddingBottom: 8,
            WebkitOverflowScrolling: 'touch',
            scrollbarWidth: 'none',
            msOverflowStyle: 'none',
          }}>
            <style>{`.no-scrollbar::-webkit-scrollbar { display: none; }`}</style>

            <KpiCard
              label="今日营收"
              value={summary ? formatRevenue(summary.revenue) : '--'}
              highlight="success"
            />
            <KpiCard
              label="翻台率"
              value={summary ? summary.table_turn_rate.toFixed(1) : '--'}
              unit="次"
            />
            <KpiCard
              label="订单数"
              value={summary ? String(summary.order_count) : '--'}
              unit="单"
            />
            <KpiCard
              label="毛利率"
              value={grossMargin != null ? (grossMargin * 100).toFixed(1) : '--'}
              unit="%"
              highlight={grossMarginHighlight}
              sub={grossMargin != null && grossMargin < 0.35 ? '低于阈值' : undefined}
            />
            <KpiCard
              label="客单价"
              value={summary ? `¥${summary.avg_check.toFixed(0)}` : '--'}
            />
          </div>
        </section>

        {/* ===== 3. 桌台实时状态（网格图） ===== */}
        <section style={{ marginTop: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: C.textSub, margin: 0 }}>
              桌台实时状态
            </h2>
            <span style={{ fontSize: 14, color: C.muted }}>
              共{totalTables}桌，使用中{diningTables}桌
            </span>
          </div>

          {/* 图例 */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
            {([
              { color: C.tableEmpty, label: '空桌' },
              { color: C.tableDining, label: '用餐中' },
              { color: C.tableDirty, label: '待清洁' },
              { color: C.tableReserved, label: '已预订' },
            ] as const).map(({ color, label }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 12, height: 12, borderRadius: 3, background: color }} />
                <span style={{ fontSize: 14, color: C.textSub }}>{label}</span>
              </div>
            ))}
          </div>

          {/* 网格 */}
          <div style={{
            background: C.card,
            borderRadius: 12,
            padding: 16,
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            border: `1px solid ${C.border}`,
          }}>
            <div style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 10,
            }}>
              {tables.map(t => <TableDot key={t.table_id} table={t} />)}
            </div>

            {/* 摘要行 */}
            {dirtyTables > 0 && (
              <div style={{
                marginTop: 12,
                padding: '8px 12px',
                borderRadius: 8,
                background: C.warningBg,
                color: C.warningText,
                fontSize: 14,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}>
                ⚠ {dirtyTables}张桌台待清洁
              </div>
            )}
          </div>
        </section>

        {/* ===== 4. E1-E8清单状态 ===== */}
        <section style={{ marginTop: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: C.textSub, margin: 0 }}>
              日清日结
            </h2>
            {pendingItems.length > 0 && (
              <span style={{
                fontSize: 13,
                padding: '3px 10px',
                borderRadius: 6,
                background: C.warningBg,
                color: C.warningText,
                fontWeight: 600,
              }}>
                {pendingItems.length}项未完成
              </span>
            )}
          </div>

          <div
            role="button"
            tabIndex={0}
            onClick={() => navigate('/daily-settlement')}
            onKeyDown={e => e.key === 'Enter' && navigate('/daily-settlement')}
            style={{
              background: C.card,
              borderRadius: 12,
              padding: '0 16px',
              boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
              border: `1px solid ${C.border}`,
              cursor: 'pointer',
              minHeight: 48,
            }}
          >
            {/* 进度条 */}
            <div style={{ padding: '14px 0 10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 14, color: C.textSub }}>完成进度</span>
                <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>
                  {completedCount} / 8
                </span>
              </div>
              <div style={{
                height: 8,
                background: C.border,
                borderRadius: 4,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${(completedCount / 8) * 100}%`,
                  background: completedCount === 8 ? C.success : C.primary,
                  borderRadius: 4,
                  transition: 'width 0.4s ease',
                }} />
              </div>
            </div>

            {/* 每项清单 */}
            {checklist.map(item => (
              <ChecklistRow key={item.id} item={item} />
            ))}

            {/* 跳转提示 */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              padding: '14px 0',
              color: C.primary,
              fontSize: 16,
              fontWeight: 600,
            }}>
              查看详情 →
            </div>
          </div>
        </section>

        {/* ===== 5. 库存预警卡片 ===== */}
        <section style={{ marginTop: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: C.textSub, margin: 0 }}>
              库存预警
            </h2>
            {inventory && inventory.high_risk_count > 0 && (
              <span style={{
                fontSize: 13,
                padding: '3px 10px',
                borderRadius: 6,
                background: C.dangerBg,
                color: C.dangerText,
                fontWeight: 600,
              }}>
                {inventory.high_risk_count}种高风险
              </span>
            )}
          </div>

          <div style={{
            background: C.card,
            borderRadius: 12,
            padding: '0 16px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            border: `1px solid ${C.border}`,
          }}>
            {/* AI分析摘要 */}
            {inventory?.summary && (
              <div style={{
                padding: '12px 0 10px',
                borderBottom: `1px solid ${C.divider}`,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  borderRadius: 5,
                  background: C.infoBg,
                  color: C.infoText,
                  fontWeight: 600,
                  flexShrink: 0,
                }}>
                  AI
                </span>
                <span style={{ fontSize: 14, color: C.textSub }}>{inventory.summary}</span>
              </div>
            )}

            {/* 预警列表 */}
            {(inventory?.alerts ?? []).map(alert => (
              <InventoryRow key={alert.ingredient_id} alert={alert} />
            ))}

            {(!inventory || inventory.alerts.length === 0) && (
              <div style={{
                padding: '20px 0',
                textAlign: 'center',
                color: C.muted,
                fontSize: 16,
              }}>
                暂无库存预警
              </div>
            )}
          </div>
        </section>

        {/* ===== 6. 员工实时状态 ===== */}
        <section style={{ marginTop: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: C.textSub, margin: 0 }}>
              员工状态
            </h2>
            <div style={{ display: 'flex', gap: 12 }}>
              <span style={{ fontSize: 14, color: C.successText }}>
                在岗 {onDutyStaff.length}
              </span>
              <span style={{ fontSize: 14, color: C.warningText }}>
                休息 {breakStaff.length}
              </span>
            </div>
          </div>

          <div style={{
            background: C.card,
            borderRadius: 12,
            padding: '12px 16px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            border: `1px solid ${C.border}`,
          }}>
            {/* 统计概览 */}
            <div style={{
              display: 'flex',
              gap: 16,
              marginBottom: 14,
              paddingBottom: 14,
              borderBottom: `1px solid ${C.divider}`,
            }}>
              <div style={{
                flex: 1,
                background: C.successBg,
                borderRadius: 10,
                padding: '12px',
                textAlign: 'center',
              }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: C.successText }}>{onDutyStaff.length}</div>
                <div style={{ fontSize: 14, color: C.textSub, marginTop: 4 }}>在岗人数</div>
              </div>
              <div style={{
                flex: 1,
                background: C.warningBg,
                borderRadius: 10,
                padding: '12px',
                textAlign: 'center',
              }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: C.warningText }}>{breakStaff.length}</div>
                <div style={{ fontSize: 14, color: C.textSub, marginTop: 4 }}>休息人数</div>
              </div>
            </div>

            {/* 岗位分组 */}
            {Object.entries(roleGroups).map(([role, members]) => (
              <div key={role} style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 0',
                borderBottom: `1px solid ${C.divider}`,
              }}>
                <span style={{
                  fontSize: 14,
                  color: C.textSub,
                  minWidth: 48,
                  flexShrink: 0,
                }}>
                  {role}
                </span>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', flex: 1 }}>
                  {members.map(m => (
                    <span key={m.id} style={{
                      fontSize: 14,
                      padding: '4px 10px',
                      borderRadius: 6,
                      background: C.successBg,
                      color: C.successText,
                      border: `1px solid ${C.success}44`,
                    }}>
                      {m.name}
                    </span>
                  ))}
                </div>
                <span style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: C.text,
                  flexShrink: 0,
                }}>
                  {members.length}
                </span>
              </div>
            ))}

            {/* 休息人员 */}
            {breakStaff.length > 0 && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 0',
              }}>
                <span style={{
                  fontSize: 14,
                  color: C.warningText,
                  minWidth: 48,
                  flexShrink: 0,
                }}>
                  休息
                </span>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {breakStaff.map(m => (
                    <span key={m.id} style={{
                      fontSize: 14,
                      padding: '4px 10px',
                      borderRadius: 6,
                      background: C.warningBg,
                      color: C.warningText,
                      border: `1px solid ${C.warning}44`,
                    }}>
                      {m.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>

      </div>
    </div>
  );
}
