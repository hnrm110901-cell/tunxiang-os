/**
 * 订单类型 — 对应 shared/ontology/src/entities.py Order + OrderItem
 * 金额字段统一 _fen 后缀（分），ID 字段统一 string（UUID）
 */
import type { TenantEntity, PaginatedResponse, PaginationParams } from './common';
import type { OrderStatus, OrderType, PricingMode } from './enums';

// ─────────────────────────────────────────────
// 核心实体
// ─────────────────────────────────────────────

/** 订单明细 */
export interface OrderItem extends TenantEntity {
  order_id: string;
  dish_id: string | null;
  item_name: string;
  quantity: number;
  unit_price_fen: number;
  subtotal_fen: number;
  food_cost_fen: number | null;
  gross_margin: number | null;
  notes: string | null;
  customizations: Record<string, unknown> | null;

  // 扩展字段
  pricing_mode: PricingMode | null;
  weight_value: number | null;
  gift_flag: boolean;
  sent_to_kds_flag: boolean;
  kds_station: string | null;
  return_flag: boolean;
  return_reason: string | null;

  // 价格 & 折扣 & 做法
  original_price_fen: number | null;
  single_discount_fen: number | null;
  practice_names: string | null;
  is_gift: boolean;
  gift_reason: string | null;
  combo_id: string | null;
}

/** 订单主体 */
export interface Order extends TenantEntity {
  order_no: string;
  store_id: string;
  customer_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  table_number: string | null;
  waiter_id: string | null;

  // 类型 & 渠道
  order_type: OrderType;
  sales_channel_id: string | null;

  // 金额（分）
  total_amount_fen: number;
  discount_amount_fen: number;
  final_amount_fen: number | null;

  // 状态 & 时间
  status: OrderStatus;
  order_time: string;
  confirmed_at: string | null;
  completed_at: string | null;
  notes: string | null;

  // metadata
  order_metadata: Record<string, unknown> | null;

  // 扩展字段
  guest_count: number | null;
  dining_duration_min: number | null;
  abnormal_flag: boolean;
  abnormal_type: string | null;
  discount_type: string | null;
  margin_alert_flag: boolean;
  gross_margin_before: number | null;
  gross_margin_after: number | null;
  served_at: string | null;
  serve_duration_min: number | null;

  // 收银 & 来源
  cashier_id: string | null;
  service_charge_fen: number | null;
  order_source: string | null;
  table_transfer_from: string | null;

  // 关联
  items: OrderItem[];
}

// ─────────────────────────────────────────────
// 请求类型
// ─────────────────────────────────────────────

/** 创建订单请求 */
export interface CreateOrderRequest {
  store_id: string;
  order_type: OrderType;
  sales_channel_id?: string;
  customer_id?: string;
  customer_name?: string;
  customer_phone?: string;
  table_number?: string;
  waiter_id?: string;
  guest_count?: number;
  notes?: string;
  order_metadata?: Record<string, unknown>;
  items: CreateOrderItemRequest[];
}

/** 创建订单明细请求 */
export interface CreateOrderItemRequest {
  dish_id?: string;
  item_name: string;
  quantity: number;
  unit_price_fen: number;
  notes?: string;
  customizations?: Record<string, unknown>;
  pricing_mode?: PricingMode;
  weight_value?: number;
  is_gift?: boolean;
  gift_reason?: string;
  combo_id?: string;
}

/** 更新订单请求 */
export interface UpdateOrderRequest {
  status?: OrderStatus;
  notes?: string;
  guest_count?: number;
  table_number?: string;
  order_metadata?: Record<string, unknown>;
}

/** 订单列表查询参数 */
export interface OrderListParams extends PaginationParams {
  store_id?: string;
  status?: OrderStatus;
  order_type?: OrderType;
  customer_id?: string;
  start_time?: string;
  end_time?: string;
}

// ─────────────────────────────────────────────
// 响应类型
// ─────────────────────────────────────────────

export type OrderListResponse = PaginatedResponse<Order>;
