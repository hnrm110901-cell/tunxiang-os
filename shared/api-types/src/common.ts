/**
 * 通用响应类型 — 与 CLAUDE.md 约定一致
 * RESTful 统一响应：{ "ok": bool, "data": {}, "error": {} }
 * 分页：?page=1&size=20，返回 { items: [], total: int }
 */

/** 统一 API 响应 */
export interface ApiResponse<T> {
  ok: boolean;
  data: T;
  error?: ApiError;
}

/** API 错误体 */
export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

/** 分页请求参数 */
export interface PaginationParams {
  page?: number;
  size?: number;
}

/** 所有实体共有的基础字段（对应 TenantBase） */
export interface TenantEntity {
  id: string;
  tenant_id: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}
