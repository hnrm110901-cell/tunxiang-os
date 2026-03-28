/**
 * 驾驶舱 API — /api/v1/dashboard/*
 * 经营总览、门店排行、预警、趋势
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface OverviewKPI {
  label: string;
  value: number;
  formatted: string;
  trend_percent: number;
  trend_up: boolean;
}

export interface StoreRankItem {
  rank: number;
  store_id: string;
  store_name: string;
  revenue_fen: number;
  order_count: number;
  turnover_rate: number;
  health_score: number;
}

export interface DashboardAlert {
  alert_id: string;
  level: 'critical' | 'warning' | 'info';
  store_name: string;
  message: string;
  created_at: string;
}

export interface TrendPoint {
  date: string;
  revenue_fen: number;
  order_count: number;
  avg_ticket_fen: number;
}

// ─── 接口 ───

/** 获取经营总览 KPI */
export async function fetchDashboardOverview(
  date?: string,
): Promise<{ items: OverviewKPI[] }> {
  const dateParam = date ? `?date=${encodeURIComponent(date)}` : '';
  return txFetch(`/api/v1/dashboard/overview${dateParam}`);
}

/** 获取门店排行 */
export async function fetchStoreRanking(
  period: 'day' | 'week' | 'month' = 'day',
): Promise<{ items: StoreRankItem[] }> {
  return txFetch(`/api/v1/dashboard/store-ranking?period=${period}`);
}

/** 获取驾驶舱预警列表 */
export async function fetchDashboardAlerts(
  page = 1,
  size = 20,
): Promise<{ items: DashboardAlert[]; total: number }> {
  return txFetch(`/api/v1/dashboard/alerts?page=${page}&size=${size}`);
}

/** 获取经营趋势（日/周/月） */
export async function fetchRevenueTrend(
  storeId: string,
  period: 'day' | 'week' | 'month' = 'week',
  days = 30,
): Promise<{ items: TrendPoint[] }> {
  return txFetch(
    `/api/v1/dashboard/trend?store_id=${encodeURIComponent(storeId)}&period=${period}&days=${days}`,
  );
}

/** 获取实时数据（用于大屏刷新） */
export async function fetchRealtimeMetrics(): Promise<{
  total_revenue_fen: number;
  total_orders: number;
  active_stores: number;
  active_alerts: number;
}> {
  return txFetch('/api/v1/dashboard/realtime');
}
