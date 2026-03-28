/**
 * 高峰 API — /api/v1/peak/*
 * 高峰状态监控、催菜列表、加派响应
 */
import { txFetch } from './index';

// ─── 类型 ───

export type PeakLevel = 'normal' | 'busy' | 'peak' | 'extreme';

export interface PeakStatus {
  store_id: string;
  level: PeakLevel;
  current_guests: number;
  waiting_count: number;
  avg_serve_time_sec: number;
  occupied_tables: number;
  total_tables: number;
}

export interface RushDish {
  rush_id: string;
  table_no: string;
  dish_name: string;
  quantity: number;
  elapsed_min: number;
  rush_count: number;
  is_overtime: boolean;
  order_id: string;
}

export interface DispatchRequest {
  dispatch_id: string;
  area: string;
  reason: string;
  urgency: 'normal' | 'urgent' | 'critical';
  suggested_staff: string;
  status: 'pending' | 'accepted' | 'completed';
}

// ─── 接口 ───

/** 获取当前高峰状态 */
export async function fetchPeakStatus(
  storeId: string,
): Promise<PeakStatus> {
  return txFetch(`/api/v1/peak/status?store_id=${encodeURIComponent(storeId)}`);
}

/** 获取待催菜列表 */
export async function fetchRushDishes(
  storeId: string,
): Promise<{ items: RushDish[] }> {
  return txFetch(`/api/v1/peak/rush-list?store_id=${encodeURIComponent(storeId)}`);
}

/** 获取加派建议 */
export async function fetchDispatchSuggestions(
  storeId: string,
): Promise<{ items: DispatchRequest[] }> {
  return txFetch(`/api/v1/peak/dispatch-suggestions?store_id=${encodeURIComponent(storeId)}`);
}

/** 响应加派请求 */
export async function respondDispatch(
  dispatchId: string,
  action: 'accept' | 'decline',
  employeeId: string,
): Promise<{ dispatch_id: string; status: string }> {
  return txFetch(`/api/v1/peak/dispatch/${encodeURIComponent(dispatchId)}/respond`, {
    method: 'POST',
    body: JSON.stringify({ action, employee_id: employeeId }),
  });
}
