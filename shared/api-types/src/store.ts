/**
 * 门店类型 — 对应 shared/ontology/src/entities.py Store
 * 桌台拓扑, 档口配置, 人效模型, 经营指标
 */
import type { TenantEntity, PaginatedResponse, PaginationParams } from './common';
import type { StoreStatus, StoreType } from './enums';

// ─────────────────────────────────────────────
// 核心实体
// ─────────────────────────────────────────────

/** 门店 */
export interface Store extends TenantEntity {
  store_name: string;
  store_code: string;
  email: string | null;
  manager_id: string | null;
  is_active: boolean;

  // 门店类型
  store_type: StoreType;
  has_physical_seats: boolean;

  // 地址
  address: string | null;
  city: string | null;
  district: string | null;
  phone: string | null;
  latitude: number | null;
  longitude: number | null;
  brand_id: string | null;
  region: string | null;
  status: StoreStatus;

  // 物理属性
  area: number | null;
  seats: number | null;
  floors: number;
  opening_date: string | null;
  business_hours: Record<string, unknown> | null;
  config: Record<string, unknown> | null;

  // 经营目标
  monthly_revenue_target_fen: number | null;
  daily_customer_target: number | null;
  cost_ratio_target: number | null;
  labor_cost_ratio_target: number | null;

  // 蓝图扩展
  turnover_rate_target: number | null;
  serve_time_limit_min: number | null;
  waste_rate_target: number | null;
  rectification_close_rate: number | null;
  meal_periods: Array<{ name: string; start: string; end: string }> | null;
  business_type: string | null;

  // 分类标签
  store_category: string | null;
  store_tags: Array<{ category: string; tags: string[] }> | null;
  operation_mode: string | null;
  store_level: string | null;
  last_online_at: string | null;
  license_expiry: string | null;

  // 日结/班别
  settlement_mode: string | null;
  shift_type: string | null;

  // 扩展
  store_metadata: Record<string, unknown> | null;
}

// ─────────────────────────────────────────────
// 请求类型
// ─────────────────────────────────────────────

/** 创建门店请求 */
export interface CreateStoreRequest {
  store_name: string;
  store_code: string;
  store_type?: StoreType;
  email?: string;
  address?: string;
  city?: string;
  district?: string;
  phone?: string;
  latitude?: number;
  longitude?: number;
  brand_id?: string;
  region?: string;
  area?: number;
  seats?: number;
  floors?: number;
  opening_date?: string;
  business_hours?: Record<string, unknown>;
  business_type?: string;
  store_category?: string;
  operation_mode?: string;
  store_level?: string;
  settlement_mode?: string;
  shift_type?: string;
  config?: Record<string, unknown>;
  store_metadata?: Record<string, unknown>;
}

/** 更新门店请求 */
export interface UpdateStoreRequest {
  store_name?: string;
  email?: string;
  address?: string;
  city?: string;
  district?: string;
  phone?: string;
  latitude?: number;
  longitude?: number;
  status?: StoreStatus;
  is_active?: boolean;
  area?: number;
  seats?: number;
  business_hours?: Record<string, unknown>;
  monthly_revenue_target_fen?: number;
  daily_customer_target?: number;
  cost_ratio_target?: number;
  labor_cost_ratio_target?: number;
  turnover_rate_target?: number;
  serve_time_limit_min?: number;
  waste_rate_target?: number;
  business_type?: string;
  store_category?: string;
  store_tags?: Array<{ category: string; tags: string[] }>;
  operation_mode?: string;
  store_level?: string;
  settlement_mode?: string;
  shift_type?: string;
  config?: Record<string, unknown>;
  store_metadata?: Record<string, unknown>;
}

/** 门店列表查询参数 */
export interface StoreListParams extends PaginationParams {
  city?: string;
  region?: string;
  brand_id?: string;
  status?: StoreStatus;
  store_type?: StoreType;
  is_active?: boolean;
  keyword?: string;
}

// ─────────────────────────────────────────────
// 响应类型
// ─────────────────────────────────────────────

export type StoreListResponse = PaginatedResponse<Store>;
