/**
 * 经营简报中心 API — /api/v1/analytics/briefings/*
 * 日报/周报/门店对标/异常简报 的查询与订阅
 */
import { txFetchData } from './client';

// ─── 类型 ───

export interface BriefingKPI {
  revenue_fen: number;
  revenue_change: number;
  gross_margin: number;
  gross_margin_change: number;
  customer_count: number;
  customer_change: number;
  table_turnover: number;
  turnover_change: number;
}

export interface StoreScore {
  name: string;
  score: number;
}

export interface Briefing {
  id: string;
  type: 'daily' | 'weekly' | 'benchmark' | 'anomaly';
  title: string;
  date: string;
  summary: string;
  content: string; // markdown 格式
  kpi: BriefingKPI;
  anomaly_count: number;
  rectification_rate: number;
  top_stores: StoreScore[];
  bottom_stores: StoreScore[];
  generated_at: string;
  is_read: boolean;
}

export interface BriefingListResult {
  items: Briefing[];
  total: number;
}

export interface SubscribePayload {
  channels: ('wecom' | 'email')[];
  push_time: string; // HH:mm
  types: ('daily' | 'weekly' | 'benchmark' | 'anomaly')[];
}

export interface SubscribeResult {
  ok: boolean;
  subscription_id: string;
}

// ─── 接口 ───

/** 获取简报列表（分页 + 按类型筛选） */
export async function fetchBriefings(
  type: Briefing['type'],
  page = 1,
  size = 10,
  keyword?: string,
): Promise<BriefingListResult> {
  let url = `/api/v1/analytics/briefings?type=${type}&page=${page}&size=${size}`;
  if (keyword) {
    url += `&keyword=${encodeURIComponent(keyword)}`;
  }
  return txFetchData<BriefingListResult>(url);
}

/** 获取简报详情 */
export async function fetchBriefingDetail(id: string): Promise<Briefing> {
  return txFetchData<Briefing>(`/api/v1/analytics/briefings/${encodeURIComponent(id)}`);
}

/** 设置简报订阅推送 */
export async function subscribeBriefing(
  payload: SubscribePayload,
): Promise<SubscribeResult> {
  return txFetchData<SubscribeResult>('/api/v1/analytics/briefings/subscribe', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
