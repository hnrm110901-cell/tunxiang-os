/**
 * 食材类型 — 对应 shared/ontology/src/entities.py
 *   IngredientMaster + Ingredient + IngredientTransaction
 * 库存量, 效期, 采购价, 批次, 供应商
 */
import type { TenantEntity, PaginatedResponse, PaginationParams } from './common';
import type { InventoryStatus, TransactionType, StorageType } from './enums';

// ─────────────────────────────────────────────
// 核心实体
// ─────────────────────────────────────────────

/** 食材主档（集团级字典表） */
export interface IngredientMaster extends TenantEntity {
  canonical_name: string;
  aliases: string[] | null;
  category: string;
  sub_category: string | null;
  base_unit: string;
  spec_desc: string | null;

  // 存储
  shelf_life_days: number | null;
  storage_type: StorageType;
  storage_temp_min: number | null;
  storage_temp_max: number | null;

  // 属性
  is_traceable: boolean;
  allergen_tags: string[] | null;
  seasonality: string[] | null;
  typical_waste_pct: number | null;
  typical_yield_rate: number | null;
  is_active: boolean;
}

/** 门店库存台账 */
export interface Ingredient extends TenantEntity {
  store_id: string;
  ingredient_name: string;
  category: string | null;
  unit: string;
  current_quantity: number;
  min_quantity: number;
  max_quantity: number | null;
  unit_price_fen: number | null;
  status: InventoryStatus;
  supplier_name: string | null;
  supplier_contact: string | null;
}

/** 库存流水 */
export interface IngredientTransaction extends TenantEntity {
  ingredient_id: string;
  store_id: string;
  transaction_type: TransactionType;
  quantity: number;
  unit_cost_fen: number | null;
  total_cost_fen: number | null;
  quantity_before: number | null;
  quantity_after: number | null;
  performed_by: string | null;
  transaction_time: string | null;
  reference_id: string | null;
  notes: string | null;
}

// ─────────────────────────────────────────────
// 请求类型
// ─────────────────────────────────────────────

/** 创建食材主档请求 */
export interface CreateIngredientMasterRequest {
  canonical_name: string;
  aliases?: string[];
  category: string;
  sub_category?: string;
  base_unit: string;
  spec_desc?: string;
  shelf_life_days?: number;
  storage_type?: StorageType;
  storage_temp_min?: number;
  storage_temp_max?: number;
  is_traceable?: boolean;
  allergen_tags?: string[];
  seasonality?: string[];
  typical_waste_pct?: number;
  typical_yield_rate?: number;
}

/** 创建门店库存台账请求 */
export interface CreateIngredientRequest {
  store_id: string;
  ingredient_name: string;
  category?: string;
  unit: string;
  current_quantity?: number;
  min_quantity: number;
  max_quantity?: number;
  unit_price_fen?: number;
  supplier_name?: string;
  supplier_contact?: string;
}

/** 更新库存台账请求 */
export interface UpdateIngredientRequest {
  ingredient_name?: string;
  category?: string;
  min_quantity?: number;
  max_quantity?: number;
  unit_price_fen?: number;
  supplier_name?: string;
  supplier_contact?: string;
}

/** 创建库存流水请求 */
export interface CreateIngredientTransactionRequest {
  ingredient_id: string;
  store_id: string;
  transaction_type: TransactionType;
  quantity: number;
  unit_cost_fen?: number;
  performed_by?: string;
  reference_id?: string;
  notes?: string;
}

/** 食材列表查询参数 */
export interface IngredientListParams extends PaginationParams {
  store_id?: string;
  category?: string;
  status?: InventoryStatus;
  keyword?: string;
}

/** 库存流水查询参数 */
export interface IngredientTransactionListParams extends PaginationParams {
  ingredient_id?: string;
  store_id?: string;
  transaction_type?: TransactionType;
  start_time?: string;
  end_time?: string;
}

// ─────────────────────────────────────────────
// 响应类型
// ─────────────────────────────────────────────

export type IngredientMasterListResponse = PaginatedResponse<IngredientMaster>;
export type IngredientListResponse = PaginatedResponse<Ingredient>;
export type IngredientTransactionListResponse = PaginatedResponse<IngredientTransaction>;
