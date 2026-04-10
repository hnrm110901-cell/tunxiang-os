/**
 * 存酒管理 API 客户端
 * 覆盖后端 /api/v1/wine-storage/* 所有端点
 */
import { txFetchData } from './client';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

export interface WineStorageRecord {
  id: string;
  store_id: string;
  customer_id: string;
  source_order_id: string;
  wine_name: string;
  wine_category: string;
  quantity: number;
  original_qty: number;
  unit: string;
  estimated_value_fen: number | null;
  cabinet_position: string | null;
  status: WineStorageStatus;
  stored_at: string;
  expires_at: string | null;
  operator_id: string;
  photo_url: string | null;
  notes: string | null;
}

export type WineStorageStatus =
  | 'stored'
  | 'partially_retrieved'
  | 'fully_retrieved'
  | 'expired'
  | 'transferred'
  | 'written_off';

export interface WineRetrieveReq {
  quantity: number;
  related_order_id?: string;
  remark?: string;
}

export interface WineExtendReq {
  extend_days: number;
  remark?: string;
}

export interface WineStoreReq {
  store_id: string;
  customer_id: string;
  source_order_id: string;
  wine_name: string;
  wine_category: string;
  quantity: number;
  unit?: string;
  estimated_value_fen?: number;
  cabinet_position?: string;
  expires_days?: number;
  photo_url?: string;
  notes?: string;
}

export interface WineSummaryReport {
  store_id: string;
  total_count: number;
  total_quantity: number;
  total_estimated_value_fen: number;
  by_category: Array<{
    wine_category: string;
    storage_count: number;
    total_quantity: number;
    total_estimated_value_fen: number;
  }>;
}

export interface WineExpiringItem {
  id: string;
  store_id: string;
  customer_id: string;
  wine_name: string;
  wine_category: string;
  quantity: number;
  unit: string;
  cabinet_position: string | null;
  expires_at: string;
  days_remaining: number;
}

export interface WineListResponse {
  items: WineStorageRecord[];
  total: number;
  page: number;
  size: number;
}

export interface WineRetrieveResult {
  storage_id: string;
  status: WineStorageStatus;
  quantity_retrieved: number;
  quantity_remaining: number;
}

export interface WineExtendResult {
  storage_id: string;
  status: WineStorageStatus;
  old_expires_at: string | null;
  new_expires_at: string | null;
  extended_days: number;
}

// ─── API 函数 ────────────────────────────────────────────────────────────────

/** 获取门店存酒列表 */
export async function listWineByStore(
  storeId: string,
  params?: { status?: string; wine_category?: string; page?: number; size?: number },
): Promise<WineListResponse> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.wine_category) q.set('wine_category', params.wine_category);
  if (params?.page) q.set('page', String(params.page));
  if (params?.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<WineListResponse>(
    `/api/v1/wine-storage/store/${encodeURIComponent(storeId)}${qs}`,
  );
}

/** 取酒（部分或全部） */
export async function retrieveWine(
  id: string,
  quantity: number,
  remark?: string,
): Promise<WineRetrieveResult> {
  const body: WineRetrieveReq = { quantity, remark };
  return txFetchData<WineRetrieveResult>(
    `/api/v1/wine-storage/${encodeURIComponent(id)}/retrieve`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

/** 续存（延长有效期） */
export async function extendWine(
  id: string,
  extendDays: number,
  remark?: string,
): Promise<WineExtendResult> {
  const body: WineExtendReq = { extend_days: extendDays, remark };
  return txFetchData<WineExtendResult>(
    `/api/v1/wine-storage/${encodeURIComponent(id)}/extend`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

/** 获取即将到期存酒（默认7天） */
export async function getExpiringSoon(
  storeId: string,
  daysAhead = 7,
): Promise<{ days_ahead: number; total: number; items: WineExpiringItem[] }> {
  return txFetchData(
    `/api/v1/wine-storage/report/expiring?store_id=${encodeURIComponent(storeId)}&days_ahead=${daysAhead}`,
  );
}

/** 获取存酒汇总报表 */
export async function getWineSummary(storeId: string): Promise<WineSummaryReport> {
  return txFetchData<WineSummaryReport>(
    `/api/v1/wine-storage/report/summary?store_id=${encodeURIComponent(storeId)}`,
  );
}

/** 存酒（新建记录） */
export async function storeWine(
  req: WineStoreReq,
): Promise<{ storage_id: string; status: string; quantity: number; expires_at: string | null; stored_at: string | null }> {
  return txFetchData('/api/v1/wine-storage/', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/** 按客户手机号/ID查询存酒列表 */
export async function listWineByCustomer(
  customerId: string,
  params?: { status?: string; page?: number; size?: number },
): Promise<WineListResponse> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.page) q.set('page', String(params.page));
  if (params?.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<WineListResponse>(
    `/api/v1/wine-storage/customer/${encodeURIComponent(customerId)}${qs}`,
  );
}
