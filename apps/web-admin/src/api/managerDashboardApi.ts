/**
 * 管理直通车 API — Manager Dashboard
 * 后端路由: /api/v1/manager/* (tx-trade/manager_app_routes.py)
 * 补充路由: /api/v1/analytics/* (tx-analytics)
 */
import { txFetchData } from './client';

// ─── 接口类型定义 ───

export interface StoreDailyStats {
  store_id: string;
  store_name: string;
  biz_date: string;
  revenue_fen: number;
  order_count: number;
  guest_count: number;
  avg_per_guest_fen: number;
  turnover_rate: number;
  target_fen: number;
  completion_pct: number;
}

export interface RealTimeStatus {
  active_tables: number;
  idle_tables: number;
  today_revenue_fen: number;
  peak_hour: string;
  alerts: ManagerAlert[];
}

export interface ManagerAlert {
  id: string;
  type: string;
  severity: 'critical' | 'warning' | 'info';
  message: string;
  created_at: string;
  is_read: boolean;
}

export interface StoreComparison {
  store_id: string;
  store_name: string;
  today_revenue_fen: number;
  target_fen: number;
  completion_pct: number;
  order_count: number;
  turnover_rate: number;
}

export interface DailyTrendItem {
  date: string;
  revenue_fen: number;
  order_count: number;
  /** 同比变化百分比，正数为增长 */
  yoy_pct: number | null;
}

export interface GoalProgress {
  store_id: string;
  month: string;
  target_fen: number;
  achieved_fen: number;
  completion_pct: number;
  remaining_days: number;
  daily_needed_fen: number;
}

// ─── API 函数 ───

/**
 * 今日实时 KPI 数据（来自 /api/v1/manager/realtime-kpi）
 */
export async function getTodayStats(storeId: string): Promise<StoreDailyStats> {
  const data = await txFetchData<{
    revenue: number;
    revenue_vs_yesterday: number;
    order_count: number;
    avg_check: number;
    table_turns: number;
    guest_count: number;
    on_table_count: number;
    free_table_count: number;
  }>(`/api/v1/manager/realtime-kpi?store_id=${encodeURIComponent(storeId)}&period=today`);

  const today = new Date().toISOString().slice(0, 10);
  return {
    store_id: storeId,
    store_name: '',
    biz_date: today,
    revenue_fen: data.revenue,
    order_count: data.order_count,
    guest_count: data.guest_count,
    avg_per_guest_fen: data.avg_check,
    turnover_rate: data.table_turns,
    target_fen: 0,       // 由 getGoalProgress 补充
    completion_pct: 0,
  };
}

/**
 * 多门店今日汇总对比
 */
export async function getMultiStoreOverview(storeIds: string[]): Promise<StoreComparison[]> {
  const qs = storeIds.map((id) => `store_ids=${encodeURIComponent(id)}`).join('&');
  return txFetchData<StoreComparison[]>(
    `/api/v1/analytics/store-comparison?${qs}&period=today`,
  );
}

/**
 * 近 N 天趋势
 */
export async function getDailyTrend(storeId: string, days = 7): Promise<DailyTrendItem[]> {
  return txFetchData<DailyTrendItem[]>(
    `/api/v1/analytics/daily-trend?store_id=${encodeURIComponent(storeId)}&days=${days}`,
  );
}

/**
 * 本月目标完成进度
 */
export async function getGoalProgress(storeId: string, month: string): Promise<GoalProgress> {
  return txFetchData<GoalProgress>(
    `/api/v1/analytics/goal-progress?store_id=${encodeURIComponent(storeId)}&month=${encodeURIComponent(month)}`,
  );
}

/**
 * 实时告警（来自 /api/v1/manager/alerts）
 */
export async function getManagerAlerts(storeId: string): Promise<ManagerAlert[]> {
  const data = await txFetchData<ManagerAlert[]>(
    `/api/v1/manager/alerts?store_id=${encodeURIComponent(storeId)}`,
  );
  return data;
}

/**
 * 标记告警已读（来自 /api/v1/manager/alerts/{id}/read）
 */
export async function markAlertRead(alertId: string): Promise<void> {
  await txFetchData(`/api/v1/manager/alerts/${encodeURIComponent(alertId)}/read`, {
    method: 'POST',
  });
}
