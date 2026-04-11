/**
 * 门店健康度雷达 API — /api/v1/store-health/radar/*
 */
import { txFetchData } from './client';

// ─── 类型 ───

export interface StoreHealthRadarDimensions {
  revenue_rate: number;      // 营收达成率 0-1
  gross_margin: number;      // 毛利率 0-1
  table_turnover: number;    // 翻台率（次）
  complaint_rate: number;    // 客诉率 0-1 (越低越好)
  quality_rate: number;      // 出品合格率 0-1
  labor_efficiency: number;  // 人效（元/人/天）
}

export interface StoreHealthRadar {
  store_id: string;
  store_name: string;
  region: string;
  brand: string;
  health_score: number;       // 0-100
  health_grade: 'A' | 'B' | 'C' | 'D';
  level: 'green' | 'yellow' | 'red';
  dimensions: StoreHealthRadarDimensions;
  alerts: string[];
  trend_7d: number;  // 7天变化 正/负
}

export interface HealthSummary {
  total: number;
  green: number;
  yellow: number;
  red: number;
  avg_score: number;
}

export interface DimensionTrend {
  date: string;
  value: number;
}

export interface DimensionDetail {
  key: string;
  label: string;
  value: number;
  benchmark: number;
  unit: string;
  trend: DimensionTrend[];
}

export interface StoreHealthRadarDetail {
  store_id: string;
  store_name: string;
  region: string;
  brand: string;
  health_score: number;
  health_grade: 'A' | 'B' | 'C' | 'D';
  level: 'green' | 'yellow' | 'red';
  dimensions: StoreHealthRadarDimensions;
  dimension_details: DimensionDetail[];
  alerts: string[];
  trend_7d: number;
  trend_30d: number;
}

// ─── 接口 ───

/** 获取健康雷达汇总 */
export async function fetchHealthRadarSummary(): Promise<HealthSummary> {
  return txFetchData<HealthSummary>('/api/v1/store-health/radar/summary');
}

/** 获取健康雷达门店列表 */
export async function fetchHealthRadarList(params?: {
  region?: string;
  brand?: string;
  level?: string;
}): Promise<StoreHealthRadar[]> {
  const filtered = Object.fromEntries(
    Object.entries(params ?? {}).filter(([, v]) => v !== undefined && v !== ''),
  );
  const qs = new URLSearchParams(filtered as Record<string, string>).toString();
  return txFetchData<StoreHealthRadar[]>(
    `/api/v1/store-health/radar/list${qs ? `?${qs}` : ''}`,
  );
}

/** 获取单门店雷达详情 */
export async function fetchStoreRadarDetail(
  storeId: string,
): Promise<StoreHealthRadarDetail> {
  return txFetchData<StoreHealthRadarDetail>(
    `/api/v1/store-health/radar/${encodeURIComponent(storeId)}`,
  );
}

/** 一键创建整改任务 */
export async function createRectifyTask(storeId: string): Promise<{ task_id: string }> {
  return txFetchData<{ task_id: string }>(
    `/api/v1/store-health/radar/${encodeURIComponent(storeId)}/rectify`,
    { method: 'POST' },
  );
}
