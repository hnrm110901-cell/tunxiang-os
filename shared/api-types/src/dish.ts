/**
 * 菜品类型 — 对应 shared/ontology/src/entities.py Dish + DishCategory + DishIngredient
 * 金额字段统一 _fen 后缀（分），ID 字段统一 string（UUID）
 */
import type { TenantEntity, PaginatedResponse, PaginationParams } from './common';

// ─────────────────────────────────────────────
// 核心实体
// ─────────────────────────────────────────────

/** 菜品分类（支持多级） */
export interface DishCategory extends TenantEntity {
  store_id: string | null;
  name: string;
  code: string | null;
  parent_id: string | null;
  sort_order: number;
  description: string | null;
  is_active: boolean;
}

/** 菜品-食材关联（BOM 配方） */
export interface DishIngredient extends TenantEntity {
  dish_id: string;
  ingredient_id: string;
  quantity: number;
  unit: string;
  cost_per_serving_fen: number | null;
  is_required: boolean;
  is_substitutable: boolean;
  substitute_ids: string[] | null;
  notes: string | null;
}

/** 菜品主档 */
export interface Dish extends TenantEntity {
  store_id: string | null;
  dish_name: string;
  dish_code: string;
  category_id: string | null;
  description: string | null;
  image_url: string | null;

  // 价格（分）
  price_fen: number;
  original_price_fen: number | null;
  cost_fen: number | null;
  profit_margin: number | null;

  // 属性
  unit: string;
  serving_size: string | null;
  spicy_level: number;
  preparation_time: number | null;
  cooking_method: string | null;
  kitchen_station: string | null;
  production_dept_id: string | null;
  sell_start_date: string | null;
  sell_end_date: string | null;
  sell_time_ranges: Array<{ start: string; end: string }> | null;

  // 标签
  tags: string[] | null;
  allergens: string[] | null;
  dietary_info: string[] | null;

  // 营养
  calories: number | null;
  protein: number | null;
  fat: number | null;
  carbohydrate: number | null;

  // 状态
  is_available: boolean;
  is_recommended: boolean;
  is_seasonal: boolean;
  sort_order: number;
  season: string | null;

  // 库存关联
  requires_inventory: boolean;
  low_stock_threshold: number | null;
  dish_master_id: string | null;

  // 统计
  total_sales: number;
  total_revenue_fen: number;
  rating: number | null;
  review_count: number;

  // 备注 & 扩展
  notes: string | null;
  dish_metadata: Record<string, unknown> | null;

  // 关联
  category?: DishCategory;
  ingredients?: DishIngredient[];
}

// ─────────────────────────────────────────────
// 请求类型
// ─────────────────────────────────────────────

/** 创建菜品请求 */
export interface CreateDishRequest {
  store_id?: string;
  dish_name: string;
  dish_code: string;
  category_id?: string;
  description?: string;
  image_url?: string;
  price_fen: number;
  original_price_fen?: number;
  cost_fen?: number;
  unit?: string;
  serving_size?: string;
  spicy_level?: number;
  preparation_time?: number;
  cooking_method?: string;
  kitchen_station?: string;
  tags?: string[];
  allergens?: string[];
  dietary_info?: string[];
  calories?: number;
  protein?: number;
  fat?: number;
  carbohydrate?: number;
  is_available?: boolean;
  is_recommended?: boolean;
  is_seasonal?: boolean;
  season?: string;
  sort_order?: number;
  requires_inventory?: boolean;
  low_stock_threshold?: number;
  notes?: string;
  dish_metadata?: Record<string, unknown>;
}

/** 更新菜品请求 */
export interface UpdateDishRequest extends Partial<CreateDishRequest> {
  dish_name?: string;
  dish_code?: string;
  price_fen?: number;
}

/** 创建菜品分类请求 */
export interface CreateDishCategoryRequest {
  store_id?: string;
  name: string;
  code?: string;
  parent_id?: string;
  sort_order?: number;
  description?: string;
}

/** 菜品列表查询参数 */
export interface DishListParams extends PaginationParams {
  store_id?: string;
  category_id?: string;
  is_available?: boolean;
  is_recommended?: boolean;
  keyword?: string;
}

// ─────────────────────────────────────────────
// 响应类型
// ─────────────────────────────────────────────

export type DishListResponse = PaginatedResponse<Dish>;
export type DishCategoryListResponse = PaginatedResponse<DishCategory>;
