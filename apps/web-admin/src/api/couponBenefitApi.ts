/**
 * 券权益中心 + 客户旅程编排 API
 * 数据来源: tx-member (:8003) / tx-growth (:8004)
 */
import { txFetchData } from './client';

// ============================================================
// 类型定义 — 券权益
// ============================================================

export type CouponType = 'discount' | 'cash_off' | 'gift' | 'free';
export type CouponStatus = 'draft' | 'active' | 'paused' | 'expired';

export interface Coupon {
  id: string;
  name: string;
  type: CouponType;
  value_fen: number;
  min_order_fen: number;
  discount_rate?: number;
  valid_from: string;
  valid_to: string;
  total_issued: number;
  used_count: number;
  expired_count: number;
  status: CouponStatus;
  applicable_stores: string[];
  created_at: string;
}

export interface CreateCouponPayload {
  name: string;
  type: CouponType;
  value_fen: number;
  min_order_fen: number;
  discount_rate?: number;
  valid_from: string;
  valid_to: string;
  total_limit: number;
  applicable_stores: string[];
}

export interface CouponStats {
  total_issued: number;
  total_used: number;
  redemption_rate: number;
  driven_revenue_fen: number;
}

export interface PointsRule {
  id: string;
  spend_fen_per_point: number;
  checkin_points: number;
  birthday_points: number;
  expiry_days: number;
}

export interface PointsProduct {
  id: string;
  name: string;
  points_cost: number;
  stock: number;
  exchanged_count: number;
  image_url?: string;
  is_active: boolean;
}

export interface StoredValuePlan {
  id: string;
  name: string;
  charge_fen: number;
  bonus_fen: number;
  total_sold: number;
  total_charged_fen: number;
  total_balance_fen: number;
  is_active: boolean;
}

export interface StoredValueStats {
  total_charged_fen: number;
  total_balance_fen: number;
  consumption_rate: number;
}

export interface GiftCardTemplate {
  id: string;
  name: string;
  face_value_fen: number;
  design_url?: string;
  total_sold: number;
  total_activated: number;
  total_balance_fen: number;
  is_active: boolean;
}

// ============================================================
// 类型定义 — 客户旅程
// ============================================================

export type JourneyStatus = 'draft' | 'running' | 'paused' | 'ended';
export type NodeType = 'trigger' | 'wait' | 'condition' | 'action' | 'end';

export interface JourneyNode {
  id: string;
  type: NodeType;
  label: string;
  config: Record<string, unknown>;
  next_ids: string[];
  stats?: { entered: number; completed: number };
}

export interface Journey {
  id: string;
  name: string;
  status: JourneyStatus;
  trigger_count: number;
  conversion_rate: number;
  nodes: JourneyNode[];
  created_at: string;
  updated_at: string;
}

export interface CreateJourneyPayload {
  name: string;
  nodes: Omit<JourneyNode, 'stats'>[];
}

// ============================================================
// 分页响应
// ============================================================

interface PaginatedResponse<T> {
  items: T[];
  total: number;
}

// ============================================================
// 券权益 API
// ============================================================

/** 优惠券列表 */
export function fetchCoupons(page = 1, size = 20) {
  return txFetchData<PaginatedResponse<Coupon>>(
    `/api/v1/member/coupons?page=${page}&size=${size}`,
  );
}

/** 创建优惠券 */
export function createCoupon(payload: CreateCouponPayload) {
  return txFetchData<Coupon>('/api/v1/member/coupons', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 更新优惠券状态 */
export function updateCouponStatus(id: string, status: CouponStatus) {
  return txFetchData<Coupon>(`/api/v1/member/coupons/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

/** 优惠券统计 */
export function fetchCouponStats() {
  return txFetchData<CouponStats>('/api/v1/member/coupons/stats');
}

/** 积分规则 */
export function fetchPointsRules() {
  return txFetchData<PointsRule>('/api/v1/member/points/rules');
}

/** 更新积分规则 */
export function updatePointsRules(payload: Partial<PointsRule>) {
  return txFetchData<PointsRule>('/api/v1/member/points/rules', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

/** 积分商品列表 */
export function fetchPointsProducts(page = 1, size = 20) {
  return txFetchData<PaginatedResponse<PointsProduct>>(
    `/api/v1/member/points/products?page=${page}&size=${size}`,
  );
}

/** 储值方案列表 */
export function fetchStoredValuePlans() {
  return txFetchData<PaginatedResponse<StoredValuePlan>>(
    '/api/v1/member/stored-value/plans',
  );
}

/** 储值统计 */
export function fetchStoredValueStats() {
  return txFetchData<StoredValueStats>('/api/v1/member/stored-value/stats');
}

/** 礼品卡模板列表 */
export function fetchGiftCardTemplates() {
  return txFetchData<PaginatedResponse<GiftCardTemplate>>(
    '/api/v1/member/gift-cards/templates',
  );
}

// ============================================================
// 客户旅程 API
// ============================================================

/** 旅程列表 */
export function fetchJourneys(page = 1, size = 20) {
  return txFetchData<PaginatedResponse<Journey>>(
    `/api/v1/growth/journeys?page=${page}&size=${size}`,
  );
}

/** 旅程详情 */
export function fetchJourney(id: string) {
  return txFetchData<Journey>(`/api/v1/growth/journeys/${id}`);
}

/** 创建旅程 */
export function createJourney(payload: CreateJourneyPayload) {
  return txFetchData<Journey>('/api/v1/growth/journeys', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 更新旅程 */
export function updateJourney(id: string, payload: Partial<CreateJourneyPayload>) {
  return txFetchData<Journey>(`/api/v1/growth/journeys/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

/** 更新旅程状态 */
export function updateJourneyStatus(id: string, status: JourneyStatus) {
  return txFetchData<Journey>(`/api/v1/growth/journeys/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

/** 删除旅程 */
export function deleteJourney(id: string) {
  return txFetchData<void>(`/api/v1/growth/journeys/${id}`, {
    method: 'DELETE',
  });
}
