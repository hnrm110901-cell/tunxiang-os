/**
 * 菜谱方案批量下发 API — 域B 菜品菜单
 *
 * 集团建立菜谱方案 → 批量下发到各门店 → 门店可微调价格/状态
 */
import { txFetchData } from './client';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

export interface MenuScheme {
  id: string;
  name: string;
  description: string | null;
  brand_id: string | null;
  /** draft | published | archived */
  status: 'draft' | 'published' | 'archived';
  published_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** 方案内菜品数量 */
  item_count: number;
  /** 已下发门店数量 */
  store_count: number;
}

export interface MenuSchemeItem {
  id: string;
  dish_id: string;
  dish_name: string;
  /** 菜品档案默认价（分） */
  default_price_fen: number;
  image_url: string | null;
  /** 方案定价（分），null = 沿用菜品默认价 */
  price_fen: number | null;
  is_available: boolean;
  sort_order: number;
  notes: string | null;
}

export interface MenuSchemeDetail extends MenuScheme {
  items: MenuSchemeItem[];
}

export interface StoreMenuStatus {
  store_id: string;
  store_name?: string;
  /** 下发时间 */
  distributed_at: string;
  distributed_by: string | null;
  /** 门店已设置覆盖的菜品数量 */
  override_count: number;
}

/** 门店菜谱视图 — 方案基础值 + 门店覆盖合并后的生效值 */
export interface StoreMenuDish {
  dish_id: string;
  dish_name: string;
  default_price_fen: number;
  image_url: string | null;
  /** 方案定价（分） */
  scheme_price_fen: number | null;
  scheme_available: boolean;
  sort_order: number;
  /** 门店覆盖价格（分），null = 无覆盖 */
  override_price_fen: number | null;
  /** 门店覆盖可售状态，null = 无覆盖 */
  override_available: boolean | null;
  /** 生效价格（分）：覆盖 > 方案 > 菜品默认 */
  effective_price_fen: number;
  /** 生效可售状态 */
  effective_available: boolean;
  /** 是否有门店覆盖 */
  has_override: boolean;
}

export interface StoreMenuView {
  store_id: string;
  scheme_id: string;
  items: StoreMenuDish[];
  total: number;
  page: number;
  size: number;
  message?: string;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

// ─── 方案管理 API ─────────────────────────────────────────────────────────────

export interface ListSchemesParams {
  brand_id?: string;
  status?: 'draft' | 'published' | 'archived';
  keyword?: string;
  page?: number;
  size?: number;
}

/** 获取菜谱方案列表 */
export async function listSchemes(
  params: ListSchemesParams = {},
): Promise<PageResult<MenuScheme>> {
  const q = new URLSearchParams();
  if (params.brand_id) q.set('brand_id', params.brand_id);
  if (params.status) q.set('status', params.status);
  if (params.keyword) q.set('keyword', params.keyword);
  if (params.page) q.set('page', String(params.page));
  if (params.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<PageResult<MenuScheme>>(`/api/v1/menu-schemes/${qs}`);
}

export interface CreateSchemeData {
  name: string;
  description?: string;
  brand_id?: string;
}

/** 新建菜谱方案 */
export async function createScheme(data: CreateSchemeData): Promise<MenuScheme> {
  return txFetchData<MenuScheme>('/api/v1/menu-schemes/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/** 获取方案详情（含菜品列表） */
export async function getSchemeDetail(schemeId: string): Promise<MenuSchemeDetail> {
  return txFetchData<MenuSchemeDetail>(`/api/v1/menu-schemes/${schemeId}`);
}

export interface UpdateSchemeData {
  name?: string;
  description?: string;
  brand_id?: string;
}

/** 更新方案基本信息 */
export async function updateScheme(
  schemeId: string,
  data: UpdateSchemeData,
): Promise<{ scheme_id: string; updated: boolean }> {
  return txFetchData(`/api/v1/menu-schemes/${schemeId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

/** 发布方案（draft → published） */
export async function publishScheme(
  schemeId: string,
): Promise<{ scheme_id: string; status: string; published_at: string }> {
  return txFetchData(`/api/v1/menu-schemes/${schemeId}/publish`, {
    method: 'POST',
  });
}

/** 将方案批量下发到门店 */
export async function distributeScheme(
  schemeId: string,
  storeIds: string[],
  operator?: string,
): Promise<{ scheme_id: string; distributed_store_count: number; total_requested: number }> {
  return txFetchData(`/api/v1/menu-schemes/${schemeId}/distribute`, {
    method: 'POST',
    body: JSON.stringify({ store_ids: storeIds, operator }),
  });
}

/** 查看已下发门店列表 */
export async function getDistributedStores(
  schemeId: string,
  page = 1,
  size = 50,
): Promise<PageResult<StoreMenuStatus>> {
  return txFetchData<PageResult<StoreMenuStatus>>(
    `/api/v1/menu-schemes/${schemeId}/stores?page=${page}&size=${size}`,
  );
}

export interface SchemeItemInput {
  dish_id: string;
  price_fen?: number | null;
  is_available?: boolean;
  sort_order?: number;
  notes?: string | null;
}

/** 批量设置方案菜品条目（UPSERT） */
export async function setSchemeItems(
  schemeId: string,
  items: SchemeItemInput[],
): Promise<{ scheme_id: string; upserted_count: number }> {
  return txFetchData(`/api/v1/menu-schemes/${schemeId}/items`, {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}

// ─── 门店菜谱 API ─────────────────────────────────────────────────────────────

/** 获取门店当前菜谱（方案基础值 + 覆盖合并后的生效值） */
export async function getStoreMenu(
  storeId: string,
  schemeId?: string,
  page = 1,
  size = 50,
): Promise<StoreMenuView> {
  const q = new URLSearchParams({ page: String(page), size: String(size) });
  if (schemeId) q.set('scheme_id', schemeId);
  return txFetchData<StoreMenuView>(`/api/v1/store-menu/${storeId}?${q.toString()}`);
}

/** 门店设置价格/状态覆盖 */
export async function setStoreOverride(
  storeId: string,
  dishId: string,
  schemeId: string,
  overridePriceFen: number | null,
  overrideAvailable: boolean | null,
): Promise<{
  store_id: string;
  dish_id: string;
  scheme_id: string;
  override_price_fen: number | null;
  override_available: boolean | null;
}> {
  return txFetchData(`/api/v1/store-menu/${storeId}/override`, {
    method: 'PUT',
    body: JSON.stringify({
      dish_id: dishId,
      scheme_id: schemeId,
      override_price_fen: overridePriceFen,
      override_available: overrideAvailable,
    }),
  });
}

/** 清除门店覆盖（还原为方案值） */
export async function clearStoreOverride(
  storeId: string,
  dishId: string,
  schemeId: string,
): Promise<{ deleted: boolean }> {
  return txFetchData(
    `/api/v1/store-menu/${storeId}/override/${dishId}?scheme_id=${schemeId}`,
    { method: 'DELETE' },
  );
}
