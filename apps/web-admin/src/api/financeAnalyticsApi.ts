/**
 * 财务分析 API — /api/v1/finance/analytics/*
 * 收入构成、支付渠道、折扣结构、门店利润排行
 */
import { txFetchData } from './index';

// ─── 类型 ───

export interface RevenueChannel {
  name: string;
  amount_fen: number;
  percent: number;
}

export interface PaymentMethodStats {
  method: string;
  amount_fen: number;
  percent: number;
  tx_count: number;
}

export interface DiscountStructure {
  type: string;
  amount_fen: number;
  percent: number;
  order_count: number;
  avg_discount_fen: number;
}

export interface StoreProfitRank {
  rank: number;
  store_id: string;
  store_name: string;
  revenue_fen: number;
  cost_fen: number;
  profit_fen: number;
  margin_rate: number;
}

export interface FinanceTrend {
  date: string;
  revenue_fen: number;
  cost_fen: number;
  profit_fen: number;
  margin_rate: number;
}

// ─── 接口 ───

/** 收入构成 */
export async function fetchRevenueComposition(
  storeId?: string,
  period: 'day' | 'week' | 'month' = 'month',
): Promise<{ items: RevenueChannel[] }> {
  const storeParam = storeId ? `&store_id=${encodeURIComponent(storeId)}` : '';
  return txFetchData<{ items: RevenueChannel[] }>(`/api/v1/finance/analytics/revenue-composition?period=${period}${storeParam}`);
}

/** 支付渠道分布 */
export async function fetchPaymentMethodStats(
  storeId?: string,
  period: 'day' | 'week' | 'month' = 'month',
): Promise<{ items: PaymentMethodStats[] }> {
  const storeParam = storeId ? `&store_id=${encodeURIComponent(storeId)}` : '';
  return txFetchData<{ items: PaymentMethodStats[] }>(`/api/v1/finance/analytics/payment-methods?period=${period}${storeParam}`);
}

/** 折扣结构分析 */
export async function fetchDiscountStructure(
  storeId?: string,
  period: 'day' | 'week' | 'month' = 'month',
): Promise<{ items: DiscountStructure[] }> {
  const storeParam = storeId ? `&store_id=${encodeURIComponent(storeId)}` : '';
  return txFetchData<{ items: DiscountStructure[] }>(`/api/v1/finance/analytics/discount-structure?period=${period}${storeParam}`);
}

/** 门店利润排行 */
export async function fetchStoreProfitRank(
  period: 'day' | 'week' | 'month' = 'month',
): Promise<{ items: StoreProfitRank[] }> {
  return txFetchData<{ items: StoreProfitRank[] }>(`/api/v1/finance/analytics/store-profit-rank?period=${period}`);
}

/** 财务趋势 */
export async function fetchFinanceTrend(
  storeId?: string,
  period: 'day' | 'week' | 'month' = 'month',
  days = 30,
): Promise<{ items: FinanceTrend[] }> {
  const storeParam = storeId ? `&store_id=${encodeURIComponent(storeId)}` : '';
  return txFetchData<{ items: FinanceTrend[] }>(`/api/v1/finance/analytics/trend?period=${period}&days=${days}${storeParam}`);
}
