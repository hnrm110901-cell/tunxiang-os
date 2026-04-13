/**
 * 菜谱方案版本管理 + 批量下发 + 门店差异化 API — 模块3.4
 *
 * 对应后端 services/tx-menu/src/api/menu_plan_routes.py
 */
import { txFetchData } from './client';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

export interface PlanVersion {
  id: string;
  version_number: number;
  change_summary: string | null;
  published_by: string | null;
  created_at: string;
  item_count: number;
}

export interface DistributeLogEntry {
  id: string;
  store_id: string;
  version_number: number | null;
  status: 'success' | 'failed' | 'pending';
  error_message: string | null;
  distributed_by: string | null;
  distributed_at: string;
}

export interface StoreOverrideItem {
  id: string;
  dish_id: string;
  dish_name: string;
  scheme_id: string;
  override_price_fen: number | null;
  override_available: boolean | null;
  scheme_price_fen: number | null;
  scheme_available: boolean | null;
  updated_at: string;
}

export interface PendingUpdateItem {
  log_id: string;
  scheme_id: string;
  scheme_name: string;
  version_number: number | null;
  distributed_at: string;
  distributed_by: string | null;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

// ─── 版本管理 API ─────────────────────────────────────────────────────────────

/** 获取方案版本历史列表 */
export async function listPlanVersions(
  planId: string,
  params: { page?: number; size?: number } = {},
): Promise<PageResult<PlanVersion>> {
  const q = new URLSearchParams();
  if (params.page) q.set('page', String(params.page));
  if (params.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<PageResult<PlanVersion>>(`/api/v1/menu/plans/${planId}/versions${qs}`);
}

/** 手动创建版本快照 */
export async function createPlanVersion(
  planId: string,
  data: { change_summary?: string },
): Promise<{ id: string; version_number: number; created_at: string }> {
  return txFetchData(`/api/v1/menu/plans/${planId}/versions`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/** 回滚到指定版本 */
export async function rollbackPlanVersion(
  planId: string,
  versionNumber: number,
): Promise<{ plan_id: string; rolled_back_to_version: number; items_restored: number }> {
  return txFetchData(`/api/v1/menu/plans/${planId}/rollback/${versionNumber}`, {
    method: 'POST',
  });
}

// ─── 下发日志 API ─────────────────────────────────────────────────────────────

/** 获取方案下发日志 */
export async function getDistributeLog(
  planId: string,
  params: { store_id?: string; status?: string; page?: number; size?: number } = {},
): Promise<PageResult<DistributeLogEntry>> {
  const q = new URLSearchParams();
  if (params.store_id) q.set('store_id', params.store_id);
  if (params.status) q.set('status', params.status);
  if (params.page) q.set('page', String(params.page));
  if (params.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<PageResult<DistributeLogEntry>>(
    `/api/v1/menu/plans/${planId}/distribute-log${qs}`,
  );
}

// ─── 门店差异化 API ───────────────────────────────────────────────────────────

/** 获取门店覆盖配置列表 */
export async function listStoreOverrides(
  storeId: string,
  params: { scheme_id?: string; page?: number; size?: number } = {},
): Promise<PageResult<StoreOverrideItem>> {
  const q = new URLSearchParams();
  if (params.scheme_id) q.set('scheme_id', params.scheme_id);
  if (params.page) q.set('page', String(params.page));
  if (params.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<PageResult<StoreOverrideItem>>(
    `/api/v1/menu/store/${storeId}/overrides${qs}`,
  );
}

export interface StoreOverrideBatchItem {
  dish_id: string;
  scheme_id: string;
  override_price_fen?: number | null;
  override_available?: boolean | null;
}

/** 批量 UPSERT 门店覆盖 */
export async function batchUpsertStoreOverrides(
  storeId: string,
  items: StoreOverrideBatchItem[],
): Promise<{ store_id: string; upserted_count: number }> {
  return txFetchData(`/api/v1/menu/store/${storeId}/overrides`, {
    method: 'PUT',
    body: JSON.stringify({ items }),
  });
}

/** 重置门店为集团方案（删除所有覆盖） */
export async function resetStoreOverrides(
  storeId: string,
  schemeId?: string,
): Promise<{ store_id: string; deleted_override_count: number }> {
  const q = new URLSearchParams();
  if (schemeId) q.set('scheme_id', schemeId);
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData(`/api/v1/menu/store/${storeId}/reset${qs}`, { method: 'POST' });
}

/** 获取门店待更新通知 */
export async function getPendingUpdates(
  storeId: string,
  params: { page?: number; size?: number } = {},
): Promise<PageResult<PendingUpdateItem>> {
  const q = new URLSearchParams();
  if (params.page) q.set('page', String(params.page));
  if (params.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<PageResult<PendingUpdateItem>>(
    `/api/v1/menu/store/${storeId}/pending-updates${qs}`,
  );
}

// ─── 批量操作 API ─────────────────────────────────────────────────────────────

/** 分类拖拽排序 */
export async function reorderCategories(
  items: Array<{ category_id: string; sort_order: number }>,
): Promise<{ updated_count: number }> {
  return txFetchData('/api/v1/menu/categories/reorder', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}

/** 批量启用/禁用菜品 */
export async function batchToggleItems(data: {
  dish_ids: string[];
  scheme_id: string;
  is_available: boolean;
}): Promise<{ updated_count: number; is_available: boolean }> {
  return txFetchData('/api/v1/menu/items/batch-toggle', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/** 批量指定分类 */
export async function batchAssignCategory(data: {
  dish_ids: string[];
  category_id: string;
}): Promise<{ updated_count: number; category_id: string }> {
  return txFetchData('/api/v1/menu/items/batch-assign', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}
