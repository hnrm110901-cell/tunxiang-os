/**
 * 区域经营总览 API
 * 调用 GET /api/v1/analytics/region-overview
 */
import { txFetchData } from './client';

// ─────────────────────────────────────────────
// 类型定义
// ─────────────────────────────────────────────

export interface RegionMetrics {
  region_id: string;
  region_name: string;
  store_count: number;
  revenue_fen: number;
  revenue_change: number;
  avg_ticket_fen: number;
  avg_ticket_change: number;
  table_turnover: number;
  table_turnover_change: number;
  gross_margin: number;
  gross_margin_change: number;
  labor_efficiency_fen: number;
  labor_efficiency_change: number;
  complaint_rate: number;
  complaint_rate_change: number;
  alert_count: number;
  alert_critical: number;
  rectification_completion: number;
  weekly_trend: number[];
}

export interface RegionOverviewData {
  period: string;
  dimension: 'region' | 'brand';
  items: RegionMetrics[];
  total_revenue_fen: number;
  total_stores: number;
}

export interface StoreMetrics {
  store_id: string;
  store_name: string;
  revenue_fen: number;
  revenue_change: number;
  avg_ticket_fen: number;
  table_turnover: number;
  gross_margin: number;
  labor_efficiency_fen: number;
  complaint_rate: number;
  alert_count: number;
}

// ─────────────────────────────────────────────
// API 请求
// ─────────────────────────────────────────────

export async function fetchRegionOverview(params: {
  dimension: 'region' | 'brand';
  period: string;
}): Promise<RegionOverviewData> {
  const qs = new URLSearchParams(params).toString();
  return txFetchData<RegionOverviewData>(`/api/v1/analytics/region-overview?${qs}`);
}

export async function fetchRegionStores(regionId: string): Promise<StoreMetrics[]> {
  return txFetchData<StoreMetrics[]>(`/api/v1/analytics/region-overview/${encodeURIComponent(regionId)}/stores`);
}
