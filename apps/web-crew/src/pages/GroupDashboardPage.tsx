/**
 * 集团跨店数据驾驶舱
 *
 * URL: /group-dashboard
 * 从 ProfilePage 的管理者区域进入，无底部 Tab。
 * 手机端查看多门店今日实时经营数据、异常告警和7日趋势。
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import {
  fetchGroupToday,
  fetchGroupTrend,
  fetchGroupAlerts,
  GroupTodayResponse,
  GroupTrendResponse,
  GroupAlertItem,
  GroupStoreTodayData,
} from '../api/index';

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

/* ---------- 工具函数 ---------- */
/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function pctColor(pct: number): string {
  return pct >= 0 ? C.green : C.red;
}

function pctArrow(pct: number): string {
  return pct >= 0 ? '↑' : '↓';
}

function statusDot(status: GroupStoreTodayData['status']): string {
  switch (status) {
    case 'open':   return C.green;
    case 'prep':   return C.yellow;
    case 'closed': return C.muted;
    case 'error':  return C.red;
    default:       return C.muted;
  }
}

function statusLabel(status: GroupStoreTodayData['status']): string {
  switch (status) {
    case 'open':   return '营业中';
    case 'prep':   return '备餐中';
    case 'closed': return '休息中';
    case 'error':  return '异常';
    default:       return '未知';
  }
}

function nowTimeStr(): string {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

/* ---------- 子组件：顶部汇总卡 ---------- */
function SummaryCard({ data }: { data: GroupTodayResponse['summary'] }) {
  const vs = data.revenue_vs_yesterday_pct;
  return (
    <div style={{
      background: C.card, borderRadius: 14, padding: '20px 16px 16px',
      marginBottom: 14, border: `1px solid ${C.border}`,
    }}>
      <div style={{ fontSize: 14, color: C.muted, marginBottom: 6 }}>今日集团营收</div>

      {/* 大字营收 */}
      <div style={{ fontSize: 32, fontWeight: 800, color: C.accent, letterSpacing: -1 }}>
        ¥{fenToYuan(data.total_revenue_fen)}
      </div>

      {/* 环比 + 门店数 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginTop: 6, marginBottom: 14,
        fontSize: 15, fontWeight: 600,
      }}>
        <span style={{ color: pctColor(vs) }}>
          {pctArrow(vs)} {Math.abs(vs).toFixed(1)}% vs 昨日
        </span>
        <span style={{ color: C.muted }}>|</span>
        <span style={{ color: C.text }}>
          {data.active_stores}/{data.total_stores} 门店营业中
        </span>
      </div>

      {/* 分割线 */}
      <div style={{ height: 1, background: C.border, marginBottom: 14 }} />

      {/* 3 指标 */}
      <div style={{ display: 'flex', justifyContent: 'space-around' }}>
        {[
          { label: '订单', value: `${data.total_orders}单` },
          { label: '翻台', value: `${data.avg_table_turnover}次` },
          { label: '在餐', value: `${data.current_diners}人` },
        ].map(({ label, value }) => (
          <div key={label} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.white }}>{value}</div>
            <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- 子组件：告警横滑条 ---------- */
function AlertsStrip({ alerts }: { alerts: GroupAlertItem[] }) {
  if (alerts.length === 0) return null;

  function alertBorderColor(severity: GroupAlertItem['severity']): string {
    if (severity === 'danger')  return C.red;
    if (severity === 'warning') return C.orange;
    return C.muted;
  }

  function alertIcon(type: string): string {
    switch (type) {
      case 'revenue_drop':   return '📉';
      case 'discount_abuse': return '💸';
      case 'slow_serve':     return '⏱';
      case 'peak_incoming':  return '📈';
      default:               return '⚠️';
    }
  }

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, color: C.muted, marginBottom: 8, fontWeight: 600 }}>
        异常告警 {alerts.length} 条
      </div>
      <div style={{
        display: 'flex', gap: 10, overflowX: 'auto',
        paddingBottom: 6,
        scrollbarWidth: 'none',
      }}>
        {alerts.map((a, i) => (
          <div key={i} style={{
            flexShrink: 0, width: 220,
            background: C.card, borderRadius: 10,
            borderLeft: `4px solid ${alertBorderColor(a.severity)}`,
            padding: '10px 12px',
            border: `1px solid ${C.border}`,
            borderLeftWidth: 4,
            borderLeftColor: alertBorderColor(a.severity),
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 16 }}>{alertIcon(a.type)}</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: C.white }}>{a.store_name}</span>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 3 }}>
              {a.title}
            </div>
            <div style={{ fontSize: 12, color: C.muted, lineHeight: 1.4 }}>
              {a.body}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- 子组件：门店卡片 ---------- */
function StoreCard({ store, onClick }: { store: GroupStoreTodayData; onClick: () => void }) {
  const occupancyPct = store.total_tables > 0
    ? Math.round((store.occupied_tables / store.total_tables) * 100)
    : 0;
  const vs = store.revenue_vs_yesterday_pct;
  const isClosed = store.status === 'closed';

  return (
    <div
      onClick={onClick}
      style={{
        background: C.card, borderRadius: 12, padding: '14px 14px 12px',
        marginBottom: 10, border: `1px solid ${C.border}`,
        cursor: 'pointer', position: 'relative',
        opacity: isClosed ? 0.6 : 1,
      }}
    >
      {/* 第一行：门店名 + 状态 + 环比 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* 状态灯 */}
          <div style={{
            width: 10, height: 10, borderRadius: '50%',
            background: statusDot(store.status), flexShrink: 0,
            boxShadow: store.status === 'open' ? `0 0 6px ${C.green}` : 'none',
          }} />
          <span style={{ fontSize: 16, fontWeight: 700, color: C.white }}>
            {store.store_name}
          </span>
          <span style={{ fontSize: 12, color: C.muted }}>{statusLabel(store.status)}</span>
        </div>
        {!isClosed && (
          <span style={{ fontSize: 14, fontWeight: 600, color: pctColor(vs) }}>
            {pctArrow(vs)}{Math.abs(vs).toFixed(1)}%
          </span>
        )}
      </div>

      {/* 第二行：核心指标 */}
      {!isClosed && (
        <div style={{
          display: 'flex', gap: 16, fontSize: 14, color: C.text,
          fontWeight: 600, marginBottom: 10,
        }}>
          <span style={{ color: C.accent }}>¥{fenToYuan(store.revenue_fen)}</span>
          <span>{store.order_count}单</span>
          <span>在餐{store.current_diners}人</span>
          <span>满座{occupancyPct}%</span>
        </div>
      )}

      {/* 桌台占用进度条 */}
      {!isClosed && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: C.muted }}>桌台占用</span>
            <span style={{ fontSize: 12, color: C.text }}>
              {store.occupied_tables}/{store.total_tables}
            </span>
          </div>
          <div style={{
            height: 6, borderRadius: 3,
            background: C.border, overflow: 'hidden',
          }}>
            <div style={{
              height: '100%', borderRadius: 3,
              width: `${occupancyPct}%`,
              background: occupancyPct >= 90 ? C.red : occupancyPct >= 70 ? C.accent : C.green,
              transition: 'width 0.3s ease',
            }} />
          </div>
        </div>
      )}

      {/* 平均服务时长 + 告警标签 */}
      {!isClosed && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 12, color: C.muted }}>
            平均服务 {store.avg_serve_time_min} 分钟 · 翻台 {store.table_turnover} 次
          </span>
          {store.alerts.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {store.alerts.map((a, i) => (
                <span key={i} style={{
                  fontSize: 11, background: `${C.red}22`, color: C.red,
                  borderRadius: 4, padding: '2px 6px', border: `1px solid ${C.red}44`,
                }}>
                  ⚠ {a}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 休息状态提示 */}
      {isClosed && (
        <div style={{ fontSize: 14, color: C.muted, textAlign: 'center', padding: '8px 0' }}>
          今日休息
        </div>
      )}

      {/* 右箭头 */}
      <div style={{
        position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
        fontSize: 16, color: C.muted,
      }}>›</div>
    </div>
  );
}

/* ---------- 子组件：7日趋势 CSS Bar Chart ---------- */
function TrendChart({ trend }: { trend: GroupTrendResponse }) {
  const { dates, total_revenue } = trend;
  if (dates.length === 0) return null;

  const maxRev = Math.max(...total_revenue);
  const todayIdx = dates.length - 1;

  const weekLabels = ['日', '一', '二', '三', '四', '五', '六'];

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: C.muted, marginBottom: 10 }}>
        {dates.length}日营收趋势
      </div>
      <div style={{
        background: C.card, borderRadius: 12, padding: '14px 12px',
        border: `1px solid ${C.border}`,
      }}>
        {/* 柱图区域 */}
        <div style={{
          display: 'flex', alignItems: 'flex-end', gap: 4,
          height: 80, marginBottom: 8,
        }}>
          {total_revenue.map((rev, i) => {
            const heightPct = maxRev > 0 ? (rev / maxRev) * 100 : 0;
            const isToday = i === todayIdx;
            const isMax = rev === maxRev;
            return (
              <div key={i} style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'flex-end', height: '100%',
                position: 'relative',
              }}>
                {/* "最高"标注 */}
                {isMax && (
                  <div style={{
                    position: 'absolute', top: -2,
                    fontSize: 10, color: C.accent,
                    whiteSpace: 'nowrap',
                  }}>
                    最高
                  </div>
                )}
                <div style={{
                  width: '100%', borderRadius: '3px 3px 0 0',
                  height: `${Math.max(heightPct, 4)}%`,
                  background: isToday ? C.accent : '#1e3a46',
                  transition: 'height 0.4s ease',
                }} />
              </div>
            );
          })}
        </div>

        {/* 底部日期标注 */}
        <div style={{ display: 'flex', gap: 4 }}>
          {dates.map((d, i) => {
            const dayOfWeek = new Date(d).getDay();
            const isToday = i === dates.length - 1;
            return (
              <div key={i} style={{
                flex: 1, textAlign: 'center',
                fontSize: 11,
                color: isToday ? C.accent : C.muted,
                fontWeight: isToday ? 700 : 400,
              }}>
                {weekLabels[dayOfWeek]}
              </div>
            );
          })}
        </div>

        {/* 营收区间说明 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between',
          marginTop: 8, paddingTop: 8, borderTop: `1px solid ${C.border}`,
          fontSize: 12, color: C.muted,
        }}>
          <span>最高 ¥{fenToYuan(maxRev)}</span>
          <span>今日 ¥{fenToYuan(total_revenue[todayIdx] ?? 0)}</span>
        </div>
      </div>
    </div>
  );
}

/* ---------- 主页面组件 ---------- */
export function GroupDashboardPage() {
  const navigate = useNavigate();

  // 暂时 mock brand_id；实际应从 window.__BRAND_ID__ 或 auth context 读取
  // TODO: 替换为真实 brand_id
  const brandId = (window as any).__BRAND_ID__ || 'brand-001';

  const [todayData, setTodayData] = useState<GroupTodayResponse | null>(null);
  const [trendData, setTrendData] = useState<GroupTrendResponse | null>(null);
  const [alerts, setAlerts] = useState<GroupAlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState('--:--:--');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [today, trend, alertsResp] = await Promise.all([
        fetchGroupToday(brandId),
        fetchGroupTrend(brandId, 7),
        fetchGroupAlerts(brandId),
      ]);
      setTodayData(today);
      setTrendData(trend);
      setAlerts(alertsResp.alerts);
      setLastUpdated(nowTimeStr());
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  // 首次加载
  useEffect(() => {
    load();
  }, [load]);

  // 每60秒自动刷新
  useEffect(() => {
    const timer = setInterval(() => {
      load();
    }, 60_000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div style={{
      background: C.bg, minHeight: '100vh',
      padding: '0 12px 80px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif',
    }}>
      {/* 顶部导航栏 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 40,
        background: C.bg, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
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

        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 17, fontWeight: 700, color: C.white }}>集团数据驾驶舱</div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
            最后更新: {lastUpdated}
          </div>
        </div>

        <button
          onClick={load}
          disabled={loading}
          style={{
            background: loading ? C.border : `${C.accent}22`,
            border: `1px solid ${loading ? C.border : C.accent}`,
            borderRadius: 8, cursor: loading ? 'default' : 'pointer',
            color: loading ? C.muted : C.accent,
            fontSize: 13, fontWeight: 600,
            padding: '6px 12px', minHeight: 36,
          }}
        >
          {loading ? '刷新中' : '刷新'}
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          background: `${C.red}22`, border: `1px solid ${C.red}55`,
          borderRadius: 10, padding: '12px 14px', marginBottom: 14,
          fontSize: 14, color: C.red,
        }}>
          加载失败：{error}
        </div>
      )}

      {/* 骨架屏 / 数据区 */}
      {loading && !todayData ? (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: 300, gap: 12,
          color: C.muted, fontSize: 15,
        }}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            border: `3px solid ${C.border}`,
            borderTopColor: C.accent,
            animation: 'spin 0.8s linear infinite',
          }} />
          加载中...
        </div>
      ) : todayData ? (
        <>
          {/* Section 1: 汇总卡 */}
          <SummaryCard data={todayData.summary} />

          {/* Section 2: 告警横滑 */}
          <AlertsStrip alerts={alerts} />

          {/* Section 3: 门店列表 */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.muted, marginBottom: 8 }}>
              门店列表（{todayData.stores.length}家）
            </div>
            {todayData.stores.map(store => (
              <StoreCard
                key={store.store_id}
                store={store}
                onClick={() => navigate(`/store-detail?store_id=${store.store_id}&store_name=${encodeURIComponent(store.store_name)}`)}
              />
            ))}
          </div>

          {/* Section 4: 趋势图 */}
          {trendData && <TrendChart trend={trendData} />}
        </>
      ) : null}

      {/* 旋转动画全局样式 */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
