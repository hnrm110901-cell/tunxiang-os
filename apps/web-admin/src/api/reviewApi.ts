/**
 * 复盘 API — /api/v1/review/*
 * 日/周/月复盘、门店问题看板、经营案例库
 */
import { txFetch } from './index';

// ─── 类型 ───

export type ReviewPeriod = 'day' | 'week' | 'month';
export type HealthLevel = 'green' | 'yellow' | 'red';

export interface ReviewSummary {
  period: ReviewPeriod;
  date_range: string;
  total_revenue_fen: number;
  revenue_trend: number;
  total_orders: number;
  avg_ticket_fen: number;
  highlights: string[];
  concerns: string[];
}

export interface StoreIssue {
  store_id: string;
  store_name: string;
  level: HealthLevel;
  score: number;
  issues: string[];
  actions: string[];
}

export interface ReviewCase {
  case_id: string;
  title: string;
  store_name: string;
  period: string;
  category: string;
  summary: string;
  outcome: string;
  tags: string[];
}

// ─── 接口 ───

/** 获取复盘总结 */
export async function fetchReviewSummary(
  period: ReviewPeriod = 'week',
  date?: string,
): Promise<ReviewSummary> {
  const dateParam = date ? `&date=${encodeURIComponent(date)}` : '';
  return txFetch(`/api/v1/review/summary?period=${period}${dateParam}`);
}

/** 门店问题看板 */
export async function fetchStoreIssues(
  period: ReviewPeriod = 'week',
): Promise<{ items: StoreIssue[] }> {
  return txFetch(`/api/v1/review/store-issues?period=${period}`);
}

/** 获取单门店整改详情 */
export async function fetchStoreIssueDetail(
  storeId: string,
  period: ReviewPeriod = 'week',
): Promise<StoreIssue & { timeline: Array<{ time: string; event: string }> }> {
  return txFetch(
    `/api/v1/review/store-issues/${encodeURIComponent(storeId)}?period=${period}`,
  );
}

/** 经营案例库列表 */
export async function fetchReviewCases(
  category?: string,
  page = 1,
  size = 20,
): Promise<{ items: ReviewCase[]; total: number }> {
  const catParam = category ? `&category=${encodeURIComponent(category)}` : '';
  return txFetch(`/api/v1/review/cases?page=${page}&size=${size}${catParam}`);
}
