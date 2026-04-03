/**
 * trade.ts — tx-trade service API (port 8001, accessed via gateway /api/v1/)
 *
 * All amounts are in fen (分).
 */
import { txRequest } from '../utils/request'

// ---------------------------------------------------------------------------
// Shared enums & types
// ---------------------------------------------------------------------------

export type OrderStatus =
  | 'pending_payment'
  | 'paid'
  | 'preparing'
  | 'ready'
  | 'completed'
  | 'cancelled'
  | 'refunded'

export type PaymentMethod = 'wechat_pay' | 'alipay' | 'stored_value' | 'points' | 'mixed'

export type TableStatus = 'available' | 'occupied' | 'reserved' | 'cleaning' | 'unavailable'

// ---------------------------------------------------------------------------
// Order types
// ---------------------------------------------------------------------------

export interface OrderItem {
  dishId: string
  dishName: string
  specId?: string
  specName?: string
  quantity: number
  /** Unit price in fen */
  unitPriceFen: number
  /** Total price for this line in fen */
  totalPriceFen: number
  remark?: string
}

export interface CouponInfo {
  couponId: string
  couponName: string
  /** Discount amount in fen */
  discountFen: number
}

export interface Order {
  orderId: string
  orderNo: string
  storeId: string
  storeName: string
  tableId?: string
  tableNo?: string
  memberId?: string
  status: OrderStatus
  items: OrderItem[]
  /** Original total in fen */
  totalFen: number
  /** Amount actually payable after discounts, in fen */
  payableFen: number
  discountFen: number
  coupon?: CouponInfo
  remark?: string
  paymentMethod?: PaymentMethod
  paidAt?: string
  createdAt: string
  updatedAt: string
}

export interface PagedResult<T> {
  items: T[]
  total: number
  page: number
  size: number
  totalPages: number
}

// ---------------------------------------------------------------------------
// Request param types
// ---------------------------------------------------------------------------

export interface CreateOrderParams {
  storeId: string
  tableId?: string
  items: Array<{
    dishId: string
    specId?: string
    quantity: number
    remark?: string
  }>
  remark?: string
  couponId?: string
}

export interface ListOrdersParams {
  page?: number
  size?: number
  status?: OrderStatus
  storeId?: string
}

export interface PayOrderParams {
  /** For wechat_pay: openid, etc. */
  [key: string]: unknown
}

export interface CartItem {
  dishId: string
  specId?: string
  quantity: number
  remark?: string
}

export interface StoredValueBalance {
  memberId: string
  balanceFen: number
  lastUpdatedAt: string
}

export interface StoredValueCard {
  cardId: string
  memberId: string
  balanceFen: number
  totalRechargeFen: number
  totalConsumedFen: number
  createdAt: string
}

export interface RechargeResult {
  transactionId: string
  memberId: string
  amountFen: number
  balanceAfterFen: number
  createdAt: string
}

export interface PayOrderResult {
  orderId: string
  paymentId: string
  status: 'success' | 'pending' | 'failed'
  /** WeChat Pay prepay_id or other gateway token, if applicable */
  gatewayData?: Record<string, unknown>
}

export interface ApplyCouponResult {
  orderId: string
  coupon: CouponInfo
  payableFen: number
  discountFen: number
}

export interface TableStatusResult {
  tableId: string
  tableNo: string
  status: TableStatus
  currentOrderId?: string
  seatedAt?: string
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const BASE = '/api/v1'

/** Create a new order */
export async function createOrder(params: CreateOrderParams): Promise<Order> {
  return txRequest<Order>(`${BASE}/orders`, 'POST', params as unknown as Record<string, unknown>)
}

/** Fetch a single order by ID */
export async function getOrder(orderId: string): Promise<Order> {
  return txRequest<Order>(`${BASE}/orders/${encodeURIComponent(orderId)}`)
}

/** List orders with optional pagination and status filter */
export async function listOrders(params: ListOrdersParams = {}): Promise<PagedResult<Order>> {
  const qs = buildQuery({
    page: params.page ?? 1,
    size: params.size ?? 20,
    ...(params.status ? { status: params.status } : {}),
    ...(params.storeId ? { store_id: params.storeId } : {}),
  })
  return txRequest<PagedResult<Order>>(`${BASE}/orders${qs}`)
}

/** Initiate payment for an order */
export async function payOrder(
  orderId: string,
  method: PaymentMethod,
  params: PayOrderParams = {},
): Promise<PayOrderResult> {
  return txRequest<PayOrderResult>(
    `${BASE}/orders/${encodeURIComponent(orderId)}/pay`,
    'POST',
    { method, ...params },
  )
}

/** Cancel an order */
export async function cancelOrder(orderId: string): Promise<Order> {
  return txRequest<Order>(`${BASE}/orders/${encodeURIComponent(orderId)}/cancel`, 'POST')
}

/** Get current status of a table */
export async function getTableStatus(tableId: string): Promise<TableStatusResult> {
  return txRequest<TableStatusResult>(`${BASE}/tables/${encodeURIComponent(tableId)}/status`)
}

/**
 * Create an order from a cart (atomic multi-item order creation).
 */
export async function createCartOrder(
  storeId: string,
  items: CartItem[],
  remark?: string,
): Promise<Order> {
  return txRequest<Order>(`${BASE}/orders/cart`, 'POST', {
    storeId,
    items,
    ...(remark ? { remark } : {}),
  })
}

/** Apply a coupon to an existing order */
export async function applyCoupon(
  orderId: string,
  couponId: string,
): Promise<ApplyCouponResult> {
  return txRequest<ApplyCouponResult>(
    `${BASE}/orders/${encodeURIComponent(orderId)}/apply-coupon`,
    'POST',
    { couponId },
  )
}

/** Get stored-value (储值) balance for a member */
export async function getStoredValueBalance(memberId: string): Promise<StoredValueBalance> {
  return txRequest<StoredValueBalance>(
    `${BASE}/stored-value/${encodeURIComponent(memberId)}/balance`,
  )
}

/** Recharge stored-value for a member */
export async function rechargeStoredValue(
  memberId: string,
  amountFen: number,
): Promise<RechargeResult> {
  return txRequest<RechargeResult>(`${BASE}/stored-value/recharge`, 'POST', {
    memberId,
    amountFen,
  })
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | boolean>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null)
  if (entries.length === 0) return ''
  return '?' + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&')
}
