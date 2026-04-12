/**
 * 会员分析 API — /api/v1/member/analytics/*
 * 会员增长、活跃度漏斗、复购率、流失预警
 */
import { txFetchData } from './index';

// ─── 类型 ───

export interface MemberGrowth {
  date: string;
  new_members: number;
  total_members: number;
  growth_rate: number;
}

export interface FunnelStep {
  name: string;
  value: number;
  percent: number;
}

export interface RepurchaseData {
  month: string;
  rate: number;
  repeat_orders: number;
  total_orders: number;
}

export interface ChurnRisk {
  member_id: string;
  name: string;
  phone: string;
  level: string;
  last_visit: string;
  days_since_last: number;
  total_spend_fen: number;
  visit_count: number;
  churn_probability: number;
}

export interface MemberSegment {
  segment: string;
  count: number;
  percent: number;
  avg_spend_fen: number;
  avg_visits: number;
}

// ─── 接口 ───

/** 会员增长趋势 */
export async function fetchMemberGrowth(
  period: 'day' | 'week' | 'month' = 'month',
  days = 90,
): Promise<{ items: MemberGrowth[] }> {
  return txFetchData<{ items: MemberGrowth[] }>(`/api/v1/member/analytics/growth?period=${period}&days=${days}`);
}

/** 活跃度漏斗 */
export async function fetchActivityFunnel(
  storeId?: string,
): Promise<{ items: FunnelStep[] }> {
  const storeParam = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetchData<{ items: FunnelStep[] }>(`/api/v1/member/analytics/funnel${storeParam}`);
}

/** 复购率趋势 */
export async function fetchRepurchaseTrend(
  months = 12,
): Promise<{ items: RepurchaseData[] }> {
  return txFetchData<{ items: RepurchaseData[] }>(`/api/v1/member/analytics/repurchase?months=${months}`);
}

/** 流失预警列表 */
export async function fetchChurnRiskList(
  page = 1,
  size = 20,
): Promise<{ items: ChurnRisk[]; total: number }> {
  return txFetchData<{ items: ChurnRisk[]; total: number }>(`/api/v1/member/analytics/churn-risk?page=${page}&size=${size}`);
}

/** 会员分层分析 */
export async function fetchMemberSegments(): Promise<{ items: MemberSegment[] }> {
  return txFetchData<{ items: MemberSegment[] }>('/api/v1/member/analytics/segments');
}
