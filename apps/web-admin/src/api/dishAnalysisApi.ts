/**
 * 菜品分析 API — /api/v1/analysis/dish/*
 * 销量排行、毛利排行、退菜率、四象限、菜单优化建议
 */
import { txFetchData } from './index';

// ─── 类型 ───

export interface DishSalesRank {
  rank: number;
  dish_id: string;
  dish_name: string;
  sales_count: number;
  revenue_fen: number;
  trend_percent: number;
}

export interface DishMarginRank {
  rank: number;
  dish_id: string;
  dish_name: string;
  margin_rate: number;
  revenue_fen: number;
  sales_count: number;
}

export interface DishReturnRate {
  dish_id: string;
  dish_name: string;
  return_rate: number;
  return_count: number;
  top_reason: string;
}

export interface DishQuadrant {
  dish_id: string;
  dish_name: string;
  sales_count: number;
  margin_rate: number;
  quadrant: 'star' | 'cash_cow' | 'puzzle' | 'dog';
}

export interface MenuSuggestion {
  suggestion_id: string;
  type: 'promote' | 'optimize' | 'remove' | 'reprice';
  dish_name: string;
  reason: string;
  expected_impact: string;
  confidence: number;
}

// ─── 接口 ───

/** 菜品销量排行 */
export async function fetchDishSalesRank(
  storeId: string,
  period: 'day' | 'week' | 'month' = 'week',
  limit = 20,
): Promise<{ items: DishSalesRank[] }> {
  return txFetchData<{ items: DishSalesRank[] }>(
    `/api/v1/analysis/dish/sales-rank?store_id=${encodeURIComponent(storeId)}&period=${period}&limit=${limit}`,
  );
}

/** 菜品毛利排行 */
export async function fetchDishMarginRank(
  storeId: string,
  period: 'day' | 'week' | 'month' = 'week',
  limit = 20,
): Promise<{ items: DishMarginRank[] }> {
  return txFetchData<{ items: DishMarginRank[] }>(
    `/api/v1/analysis/dish/margin-rank?store_id=${encodeURIComponent(storeId)}&period=${period}&limit=${limit}`,
  );
}

/** 退菜率分析 */
export async function fetchDishReturnRate(
  storeId: string,
  period: 'day' | 'week' | 'month' = 'week',
): Promise<{ items: DishReturnRate[] }> {
  return txFetchData<{ items: DishReturnRate[] }>(
    `/api/v1/analysis/dish/return-rate?store_id=${encodeURIComponent(storeId)}&period=${period}`,
  );
}

/** 四象限分析 */
export async function fetchDishQuadrant(
  storeId: string,
  period: 'day' | 'week' | 'month' = 'month',
): Promise<{ items: DishQuadrant[] }> {
  return txFetchData<{ items: DishQuadrant[] }>(
    `/api/v1/analysis/dish/quadrant?store_id=${encodeURIComponent(storeId)}&period=${period}`,
  );
}

/** 菜单优化建议（AI 生成） */
export async function fetchMenuSuggestions(
  storeId: string,
): Promise<{ items: MenuSuggestion[] }> {
  return txFetchData<{ items: MenuSuggestion[] }>(
    `/api/v1/analysis/dish/suggestions?store_id=${encodeURIComponent(storeId)}`,
  );
}
