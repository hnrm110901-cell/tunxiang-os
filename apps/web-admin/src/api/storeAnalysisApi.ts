/**
 * 门店分析 API — /api/v1/analysis/store/*
 * 营收趋势、翻台率、客单价、高峰时段、门店对比
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface StoreKPI {
  store_id: string;
  store_name: string;
  revenue_fen: number;
  order_count: number;
  turnover_rate: number;
  avg_ticket_fen: number;
  peak_hour: string;
  guest_count: number;
}

export interface StoreRevenueTrend {
  date: string;
  revenue_fen: number;
  order_count: number;
}

export interface StoreComparison {
  store_id: string;
  store_name: string;
  revenue_fen: number;
  turnover_rate: number;
  avg_ticket_fen: number;
  peak_orders: number;
  health_score: number;
}

export interface PeakHourData {
  hour: string;
  order_count: number;
  revenue_fen: number;
  avg_wait_sec: number;
}

// ─── 接口 ───

/** 获取门店 KPI 概览 */
export async function fetchStoreKPI(
  storeId: string,
  period: 'day' | 'week' | 'month' = 'day',
): Promise<StoreKPI> {
  return txFetch(
    `/api/v1/analysis/store/kpi?store_id=${encodeURIComponent(storeId)}&period=${period}`,
  );
}

/** 获取门店营收趋势 */
export async function fetchStoreRevenueTrend(
  storeId: string,
  period: 'day' | 'week' | 'month' = 'week',
  days = 30,
): Promise<{ items: StoreRevenueTrend[] }> {
  return txFetch(
    `/api/v1/analysis/store/revenue-trend?store_id=${encodeURIComponent(storeId)}&period=${period}&days=${days}`,
  );
}

/** 门店对比分析 */
export async function fetchStoreComparison(
  storeIds: string[],
  period: 'day' | 'week' | 'month' = 'week',
): Promise<{ items: StoreComparison[] }> {
  return txFetch('/api/v1/analysis/store/compare', {
    method: 'POST',
    body: JSON.stringify({ store_ids: storeIds, period }),
  });
}

/** 高峰时段分析 */
export async function fetchPeakHourAnalysis(
  storeId: string,
  date?: string,
): Promise<{ items: PeakHourData[] }> {
  const dateParam = date ? `&date=${encodeURIComponent(date)}` : '';
  return txFetch(
    `/api/v1/analysis/store/peak-hours?store_id=${encodeURIComponent(storeId)}${dateParam}`,
  );
}
