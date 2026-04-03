/**
 * 门店健康 API — /api/v1/store-health/*
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface StoreHealthItem {
  store_id: string;
  store_name: string;
  /** "online" | "offline" | "warning" | "unknown" */
  status: string;
  /** 0-100，-1 表示数据降级（显示灰色） */
  health_score: number;
  /** "A" | "B" | "C" | "D" | "-" */
  health_grade: string;
  today_revenue_fen: number;
  /** 营收达成率，0-1 */
  revenue_rate: number;
  /** 成本率，0-1 */
  cost_rate: number;
  /** 日清 E1-E8 完成率，0-1 */
  daily_review_completion: number;
  alerts: string[];
}

export interface StoreHealthSummary {
  total_stores: number;
  online_stores: number;
  avg_health_score: number;
  total_revenue_fen: number;
}

export interface StoreHealthOverview {
  stores: StoreHealthItem[];
  summary: StoreHealthSummary;
  generated_at: string;
}

// ─── 接口 ───

/** 获取所有门店健康汇总列表 */
export async function fetchStoreHealthOverview(): Promise<StoreHealthOverview> {
  return txFetch<StoreHealthOverview>('/api/v1/store-health/overview');
}

/** 获取单门店详细健康报告 */
export async function fetchStoreHealthDetail(storeId: string): Promise<StoreHealthItem> {
  return txFetch<StoreHealthItem>(`/api/v1/store-health/${encodeURIComponent(storeId)}`);
}
