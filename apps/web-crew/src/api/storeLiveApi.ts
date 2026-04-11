/**
 * 营业中控台 + 门店异常事件中心 API
 * StoreLivePage / StoreIncidentsCenterPage
 */
import { txFetch } from './index';

// ─── 营业中控台 类型 ───

export interface SlowDish {
  dish_name: string;
  table_no: string;
  wait_minutes: number;
  order_item_id: string;
}

export interface RecentReturn {
  time: string;
  dish_name: string;
  table_no: string;
  reason: string;
}

export interface RecentComplaint {
  time: string;
  type: string;
  content: string;
}

export interface WaitingQueueItem {
  party_size: number;
  wait_minutes: number;
  queue_no: string;
}

export interface StoreLiveData {
  revenue_fen: number;
  revenue_target_fen: number;
  order_count: number;
  table_utilization: number;
  waiting_count: number;
  avg_dining_minutes: number;
  table_turnover: number;
  table_turnover_yesterday: number;
  slow_dishes: SlowDish[];
  recent_returns: RecentReturn[];
  recent_complaints: RecentComplaint[];
  waiting_queue: WaitingQueueItem[];
}

// ─── 异常事件中心 类型 ───

export type IncidentCategory = 'shortage' | 'complaint' | 'slow_dish' | 'return' | 'equipment' | 'staff';
export type IncidentStatus = 'open' | 'processing' | 'closed';

export interface IncidentTimelineItem {
  time: string;
  action: string;
  operator: string;
}

export interface Incident {
  id: string;
  category: IncidentCategory;
  title: string;
  description: string;
  severity: 'high' | 'medium' | 'low';
  status: IncidentStatus;
  created_at: string;
  updated_at: string;
  reporter: string;
  handler?: string;
  photos?: string[];
  timeline: IncidentTimelineItem[];
  rectification_task_id?: string;
}

export interface IncidentSummary {
  today_new: number;
  today_open: number;
  today_closed: number;
}

export interface CreateIncidentPayload {
  category: IncidentCategory;
  title: string;
  description: string;
  severity: 'high' | 'medium' | 'low';
  photos?: string[];
}

// ─── 营业中控台 API ───

export async function fetchStoreLive(): Promise<StoreLiveData> {
  return txFetch('/api/v1/ops/store/live-dashboard');
}

export async function rushDish(orderItemId: string): Promise<{ order_item_id: string; rushed: boolean }> {
  return txFetch(`/api/v1/ops/store/rush-dish`, {
    method: 'POST',
    body: JSON.stringify({ order_item_id: orderItemId }),
  });
}

// ─── 异常事件中心 API ───

export async function fetchIncidents(
  category?: IncidentCategory,
  status?: IncidentStatus,
): Promise<{ items: Incident[]; total: number }> {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (status) params.set('status', status);
  const qs = params.toString();
  return txFetch(`/api/v1/ops/incidents${qs ? `?${qs}` : ''}`);
}

export async function fetchIncidentSummary(): Promise<IncidentSummary> {
  return txFetch('/api/v1/ops/incidents/summary');
}

export async function createIncident(payload: CreateIncidentPayload): Promise<{ id: string }> {
  return txFetch('/api/v1/ops/incidents', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateIncidentStatus(
  id: string,
  status: IncidentStatus,
): Promise<{ id: string; status: IncidentStatus }> {
  return txFetch(`/api/v1/ops/incidents/${encodeURIComponent(id)}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}
