/**
 * 实时营业巡航页 -- E2 店长/总部
 * 功能: 实时KPI卡片 + 桌台巡航状态 + 出餐巡航 + 沽清巡航 + 巡台记录列表
 * API: GET /api/v1/ops/daily-review?date={date}&store_id={storeId}
 * 30秒自动刷新
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { ChartPlaceholder } from '../../../components/ChartPlaceholder';
import { txFetchData } from '../../../api';

// ---------- 类型 ----------
type TableAlertType = 'overtime-bill' | 'uncleared' | 'normal';
type DishAlertType = 'overtime' | 'pile-up' | 'normal';
type SoldOutLevel = 'sold-out' | 'soon' | 'ok';

interface KPICard {
  label: string;
  value: string;
  sub: string;
  trend?: string;
  up?: boolean;
}

interface TableStatus {
  id: string;
  name: string;
  zone: string;
  status: TableAlertType;
  occupiedMin: number;
  guestCount: number;
  alert?: string;
}

interface DishQueue {
  id: string;
  dish: string;
  table: string;
  waitMin: number;
  alert: DishAlertType;
  qty: number;
}

interface SoldOutItem {
  id: string;
  dish: string;
  remaining: number;
  level: SoldOutLevel;
  estimateRunOut?: string;
}

interface PatrolRecord {
  id: string;
  time: string;
  zone: string;
  inspector: string;
  type: string;
  result: 'normal' | 'issue';
  note: string;
}

interface CruiseDashboard {
  kpi: KPICard[];
  tables: TableStatus[];
  dish_queue: DishQueue[];
  sold_out: SoldOutItem[];
  patrol_records: PatrolRecord[];
}

// ---------- 配色 ----------
const TABLE_ALERT_CONFIG: Record<TableAlertType, { label: string; color: string; bg: string }> = {
  'overtime-bill': { label: '超时未结', color: '#A32D2D', bg: '#A32D2D30' },
  'uncleared':     { label: '空桌未清', color: '#BA7517', bg: '#BA751730' },
  'normal':        { label: '正常', color: '#0F6E56', bg: '#0F6E5630' },
};

const DISH_ALERT_CONFIG: Record<DishAlertType, { label: string; color: string }> = {
  'overtime':  { label: '超时', color: '#A32D2D' },
  'pile-up':   { label: '堆积', color: '#BA7517' },
  'normal':    { label: '正常', color: '#0F6E56' },
};

const SOLD_OUT_CONFIG: Record<SoldOutLevel, { label: string; color: string; bg: string }> = {
  'sold-out': { label: '已沽清', color: '#A32D2D', bg: '#A32D2D20' },
  'soon':     { label: '即将沽清', color: '#BA7517', bg: '#BA751720' },
  'ok':       { label: '充足', color: '#0F6E56', bg: '#0F6E5620' },
};

const POLL_INTERVAL = 30_000;

// ---------- 组件 ----------
export function CruiseMonitorPage() {
  const [tableFilter, setTableFilter] = useState<'all' | TableAlertType>('all');
  const [dashboard, setDashboard] = useState<CruiseDashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  const todayDate = new Date().toISOString().slice(0, 10);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await txFetchData<CruiseDashboard>(
        `/api/v1/ops/daily-review?date=${todayDate}`,
      );
      if (res) setDashboard(res);
    } catch {
      // 加载失败保持当前数据
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, [todayDate]);

  useEffect(() => {
    loadData();
    timerRef.current = setInterval(loadData, POLL_INTERVAL);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loadData]);

  const kpiList: KPICard[] = dashboard?.kpi ?? [];
  const tables: TableStatus[] = dashboard?.tables ?? [];
  const dishQueue: DishQueue[] = dashboard?.dish_queue ?? [];
  const soldOut: SoldOutItem[] = dashboard?.sold_out ?? [];
  const patrol: PatrolRecord[] = dashboard?.patrol_records ?? [];

  const filteredTables = tableFilter === 'all'
    ? tables
    : tables.filter((t) => t.status === tableFilter);

  const alertTableCount = tables.filter((t) => t.status !== 'normal').length;

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>营业巡航</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#999' }}>
            {lastRefresh.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })} 更新
          </span>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: loading ? '#BA7517' : '#0F6E56',
            display: 'inline-block', animation: 'cruise-pulse 2s infinite',
          }} />
          <span style={{ fontSize: 12, color: '#999' }}>30s自动刷新</span>
        </div>
      </div>

      {/* 加载提示 */}
      {loading && !dashboard && (
        <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>加载中...</div>
      )}

      {/* 实时KPI卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {kpiList.length === 0
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} style={{ background: '#112228', borderRadius: 8, padding: 16, borderLeft: '3px solid #1a2a33', minHeight: 80 }} />
            ))
          : kpiList.map((kpi) => (
              <div key={kpi.label} style={{
                background: '#112228', borderRadius: 8, padding: 16,
                borderLeft: '3px solid #FF6B2C',
              }}>
                <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                  <span style={{ fontSize: 26, fontWeight: 'bold', color: '#fff' }}>{kpi.value}</span>
                  <span style={{ fontSize: 12, color: '#999' }}>{kpi.sub}</span>
                </div>
                {kpi.trend && (
                  <div style={{ fontSize: 11, marginTop: 4, color: kpi.up ? '#0F6E56' : '#A32D2D' }}>
                    {kpi.up ? '\u2191' : '\u2193'} {kpi.trend} 较昨日同期
                  </div>
                )}
              </div>
            ))
        }
      </div>

      {/* 桌台巡航状态 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>
            桌台巡航
            {alertTableCount > 0 && (
              <span style={{
                fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
                background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
              }}>
                {alertTableCount} 桌异常
              </span>
            )}
          </h3>
          <div style={{ display: 'flex', gap: 6 }}>
            {[
              { key: 'all' as const, label: '全部' },
              { key: 'overtime-bill' as const, label: '超时未结' },
              { key: 'uncleared' as const, label: '空桌未清' },
              { key: 'normal' as const, label: '正常' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTableFilter(key)}
                style={{
                  padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  fontSize: 11, fontWeight: 600,
                  background: tableFilter === key ? '#FF6B2C' : '#0B1A20',
                  color: tableFilter === key ? '#fff' : '#999',
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {filteredTables.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无桌台数据</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
            {filteredTables.map((table) => {
              const cfg = TABLE_ALERT_CONFIG[table.status];
              return (
                <div
                  key={table.id}
                  style={{
                    padding: 12, borderRadius: 8,
                    background: table.status !== 'normal' ? cfg.bg : '#0B1A20',
                    border: `1px solid ${table.status !== 'normal' ? cfg.color + '60' : '#1a2a33'}`,
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 15, fontWeight: 'bold', color: '#fff' }}>{table.name}</span>
                    <span style={{
                      fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                      color: cfg.color,
                      background: table.status === 'normal' ? cfg.bg : 'transparent',
                    }}>
                      {cfg.label}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: '#999', marginBottom: 2 }}>{table.zone}</div>
                  {table.status === 'normal' && table.occupiedMin > 0 && (
                    <div style={{ fontSize: 11, color: '#ccc' }}>
                      {table.guestCount}人 | {table.occupiedMin}分钟
                    </div>
                  )}
                  {table.alert && (
                    <div style={{ fontSize: 11, color: cfg.color, marginTop: 4, fontWeight: 600 }}>
                      {table.alert}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 出餐巡航 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            出餐巡航
            {dishQueue.filter((d) => d.alert !== 'normal').length > 0 && (
              <span style={{
                fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
                background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
              }}>
                {dishQueue.filter((d) => d.alert !== 'normal').length} 项异常
              </span>
            )}
          </h3>
          {dishQueue.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无出餐数据</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {dishQueue.map((item) => {
                const cfg = DISH_ALERT_CONFIG[item.alert];
                return (
                  <div key={item.id} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: 10, borderRadius: 8, background: '#0B1A20',
                    borderLeft: `3px solid ${cfg.color}`,
                  }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{
                          fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
                          background: cfg.color + '20', color: cfg.color,
                        }}>
                          {cfg.label}
                        </span>
                        <span style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{item.dish}</span>
                        <span style={{ fontSize: 11, color: '#999' }}>x{item.qty}</span>
                      </div>
                      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                        {item.table} | 等待 {item.waitMin} 分钟
                      </div>
                    </div>
                    {item.alert !== 'normal' && (
                      <button style={{
                        padding: '4px 12px', borderRadius: 6, border: 'none',
                        background: cfg.color + '20', color: cfg.color,
                        cursor: 'pointer', fontWeight: 600, fontSize: 11,
                      }}>
                        催菜
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 沽清巡航 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            沽清巡航
            {soldOut.filter((s) => s.level === 'sold-out').length > 0 && (
              <span style={{
                fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
                background: '#A32D2D20', color: '#A32D2D', fontWeight: 600,
              }}>
                {soldOut.filter((s) => s.level === 'sold-out').length} 项已沽清
              </span>
            )}
          </h3>
          {soldOut.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无沽清数据</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {soldOut.map((item) => {
                const cfg = SOLD_OUT_CONFIG[item.level];
                return (
                  <div key={item.id} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: 12, borderRadius: 8, background: '#0B1A20',
                    borderLeft: `3px solid ${cfg.color}`,
                    opacity: item.level === 'sold-out' ? 0.7 : 1,
                  }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{
                          fontSize: 13, fontWeight: 600,
                          color: item.level === 'sold-out' ? '#999' : '#fff',
                          textDecoration: item.level === 'sold-out' ? 'line-through' : 'none',
                        }}>
                          {item.dish}
                        </span>
                        <span style={{
                          fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                          background: cfg.bg, color: cfg.color,
                        }}>
                          {cfg.label}
                        </span>
                      </div>
                      {item.level !== 'sold-out' && (
                        <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                          剩余 {item.remaining} 份 | {item.estimateRunOut}后售罄
                        </div>
                      )}
                    </div>
                    <span style={{
                      fontSize: 22, fontWeight: 'bold',
                      color: item.level === 'sold-out' ? '#A32D2D' : cfg.color,
                    }}>
                      {item.remaining}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* 巡台记录列表 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>巡台记录</h3>
          {patrol.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '20px 0' }}>暂无巡台记录</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                  <th style={{ padding: '8px 4px' }}>时间</th>
                  <th style={{ padding: '8px 4px' }}>区域</th>
                  <th style={{ padding: '8px 4px' }}>巡检人</th>
                  <th style={{ padding: '8px 4px' }}>类型</th>
                  <th style={{ padding: '8px 4px' }}>结果</th>
                  <th style={{ padding: '8px 4px' }}>备注</th>
                </tr>
              </thead>
              <tbody>
                {patrol.map((r) => (
                  <tr key={r.id} style={{ borderTop: '1px solid #1a2a33' }}>
                    <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.time}</td>
                    <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.zone}</td>
                    <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.inspector}</td>
                    <td style={{ padding: '10px 4px', color: '#ccc' }}>{r.type}</td>
                    <td style={{ padding: '10px 4px' }}>
                      <span style={{
                        fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                        background: r.result === 'issue' ? '#A32D2D20' : '#0F6E5620',
                        color: r.result === 'issue' ? '#A32D2D' : '#0F6E56',
                      }}>
                        {r.result === 'issue' ? '异常' : '正常'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 4px', color: '#999', maxWidth: 200 }}>{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* 图表占位 */}
        <ChartPlaceholder
          title="营业时段客流热力图"
          chartType="Heatmap"
          apiEndpoint="GET /api/v1/ops/daily-review"
          height={320}
        />
      </div>

      {/* 动画 */}
      <style>{`
        @keyframes cruise-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}
