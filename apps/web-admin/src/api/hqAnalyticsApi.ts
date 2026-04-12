/**
 * HQ 总部管控 API — /api/v1/analytics/hq/*
 *
 * 封装多品牌总览、门店绩效矩阵、品牌对比、品牌P&L四类接口。
 * 金额字段统一使用分（整数），展示层通过 fenToYuan() 转换。
 */
import { txFetchData } from './index';

// ─── 公共参数类型 ────────────────────────────────────────────────────────────

export interface HQDateParams {
  /** 预设周期：today / week / month */
  period?: 'today' | 'week' | 'month';
  /** 自定义起始日期 YYYY-MM-DD（与 period 二选一） */
  date_from?: string;
  /** 自定义结束日期 YYYY-MM-DD */
  date_to?: string;
}

// ─── 品牌总览类型 ────────────────────────────────────────────────────────────

export interface BrandKpiCard {
  brand_id: string;
  brand_name: string;
  /** 营收（分） */
  revenue_fen: number;
  /** 环比变化率，正数为上升，-1.0 = -100% */
  revenue_ratio: number;
  order_count: number;
  /** 客单价（分） */
  avg_ticket_fen: number;
  /** 健康分 0-100 */
  health_score: number;
}

export interface BrandRevenueTrendPoint {
  date: string;
  brand_id: string;
  brand_name: string;
  /** 营收（分） */
  revenue_fen: number;
}

export interface CrossBrandStoreRankItem {
  rank: number;
  store_id: string;
  store_name: string;
  brand_id: string;
  brand_name: string;
  city: string;
  /** 今日营收（分） */
  today_revenue_fen: number;
  /** 目标达成率，0-1 */
  target_rate: number;
  /** 健康分 0-100 */
  health_score: number;
  /** 预警数量 */
  alert_count: number;
}

export interface BrandsOverviewData {
  brands: BrandKpiCard[];
  revenue_trend: BrandRevenueTrendPoint[];
  store_rank: CrossBrandStoreRankItem[];
}

// ─── 门店绩效矩阵类型 ────────────────────────────────────────────────────────

export interface StorePerformanceItem {
  rank: number;
  store_id: string;
  store_name: string;
  city: string;
  brand_id: string;
  brand_name: string;
  /** 今日营收（分） */
  today_revenue_fen: number;
  /** 目标达成率，0-1 */
  target_rate: number;
  /** 毛利率，0-1 */
  gross_margin: number;
  /** 人力成本率，0-1 */
  labor_cost_rate: number;
  /** 客流量（人次） */
  customer_count: number;
  /** 趋势方向：up / down / flat */
  trend: 'up' | 'down' | 'flat';
  /** 预警数 */
  alert_count: number;
}

export interface StorePerformanceParams extends HQDateParams {
  brand_id?: string;
  city?: string;
  sort_by?: 'revenue' | 'target_rate' | 'gross_margin' | 'health_score';
  sort_order?: 'asc' | 'desc';
  page?: number;
  size?: number;
}

export interface StorePerformanceResult {
  items: StorePerformanceItem[];
  total: number;
}

// ─── 品牌对比类型 ────────────────────────────────────────────────────────────

export interface BrandCompareItem {
  brand_id: string;
  brand_name: string;
  revenue_fen: number;
  order_count: number;
  avg_ticket_fen: number;
  gross_margin: number;
  labor_cost_rate: number;
  health_score: number;
}

export interface BrandsCompareResult {
  items: BrandCompareItem[];
}

// ─── 品牌P&L类型 ─────────────────────────────────────────────────────────────

export interface PnlLineItem {
  label: string;
  amount_fen: number;
  /** 占营收比，0-1 */
  pct_of_revenue: number;
  /** 环比变化率 */
  ratio: number;
}

export interface BrandPnlData {
  brand_id: string;
  brand_name: string;
  period_label: string;
  revenue_fen: number;
  gross_profit_fen: number;
  gross_margin: number;
  net_profit_fen: number;
  net_margin: number;
  line_items: PnlLineItem[];
}

// ─── 门店P&L概览（Drawer用） ─────────────────────────────────────────────────

export interface StorePnlOverview {
  store_id: string;
  store_name: string;
  period_label: string;
  revenue_fen: number;
  cost_of_goods_fen: number;
  gross_profit_fen: number;
  gross_margin: number;
  labor_cost_fen: number;
  labor_cost_rate: number;
  operating_expense_fen: number;
  net_profit_fen: number;
  net_margin: number;
}

// ─── API 函数 ────────────────────────────────────────────────────────────────

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const pairs: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      pairs.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
    }
  }
  return pairs.length ? `?${pairs.join('&')}` : '';
}

/** 获取多品牌总览（KPI卡 + 七日趋势 + 门店快速排名） */
export async function getBrandsOverview(params: HQDateParams = {}): Promise<BrandsOverviewData> {
  const q = buildQuery(params as Record<string, string | number | boolean | undefined>);
  return txFetchData<BrandsOverviewData>(`/api/v1/analytics/hq/brands/overview${q}`);
}

/** 获取指定品牌下门店绩效矩阵 */
export async function getBrandStorePerformance(
  brandId: string,
  params: StorePerformanceParams = {},
): Promise<StorePerformanceResult> {
  const q = buildQuery(params as Record<string, string | number | boolean | undefined>);
  return txFetchData<StorePerformanceResult>(
    `/api/v1/analytics/hq/brands/${encodeURIComponent(brandId)}/stores/performance${q}`,
  );
}

/** 获取多品牌横向对比 */
export async function getBrandsCompare(params: HQDateParams = {}): Promise<BrandsCompareResult> {
  const q = buildQuery(params as Record<string, string | number | boolean | undefined>);
  return txFetchData<BrandsCompareResult>(`/api/v1/analytics/hq/brands/compare${q}`);
}

/** 获取指定品牌P&L */
export async function getBrandPnl(
  brandId: string,
  params: HQDateParams = {},
): Promise<BrandPnlData> {
  const q = buildQuery(params as Record<string, string | number | boolean | undefined>);
  return txFetchData<BrandPnlData>(
    `/api/v1/analytics/hq/brands/${encodeURIComponent(brandId)}/pnl${q}`,
  );
}

/** 获取单门店P&L概览（Drawer展示用） */
export async function getStorePnlOverview(
  storeId: string,
  params: HQDateParams = {},
): Promise<StorePnlOverview> {
  const q = buildQuery(params as Record<string, string | number | boolean | undefined>);
  return txFetchData<StorePnlOverview>(
    `/api/v1/analytics/hq/stores/${encodeURIComponent(storeId)}/pnl${q}`,
  );
}
