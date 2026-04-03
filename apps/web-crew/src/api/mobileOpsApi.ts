/**
 * 移动收银台扩展 API — 服务员端更多操作
 * 对标: 天财商龙移动收银台 + Toast Go 2
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface UpdateTableInfoParams {
  guest_count?: number;
  waiter_id?: string;
}

export interface DishStatusItem {
  dish_id: string;
  sold_out: boolean;
  daily_limit: number;
  daily_sold_count: number;
}

export interface AIRecommendation {
  dish_id: string;
  dish_name: string;
  price_fen: number;
  reason: string;
  tags: string[];
  image_url?: string;
}

export interface OrderKdsItem {
  task_id: string;
  dish_name: string;
  quantity: number;
  spec?: string;
  status: 'pending' | 'cooking' | 'done';
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  rush_count: number;
  is_overtime: boolean;
}

export interface PlatformCouponResult {
  coupon_code: string;
  platform: string;
  discount_fen: number;
  verified: boolean;
}

// ─── 1. 修改开台信息 ───

export async function updateTableInfo(
  orderId: string,
  params: UpdateTableInfoParams,
): Promise<{ order_id: string; guest_count?: number; waiter_id?: string }> {
  return txFetch(`/api/v1/mobile/orders/${encodeURIComponent(orderId)}/table-info`, {
    method: 'PUT',
    body: JSON.stringify(params),
  });
}

// ─── 2. 聚合验券 ───

export async function verifyPlatformCoupon(
  code: string,
  orderId: string,
): Promise<PlatformCouponResult> {
  return txFetch('/api/v1/trade/coupons/platform/verify', {
    method: 'POST',
    body: JSON.stringify({ code, order_id: orderId }),
  });
}

// ─── 3. 复制菜品 ───

export async function copyDishesFromOrder(
  sourceOrderId: string,
  targetOrderId: string,
): Promise<{ order_id: string; copied_count: number }> {
  return txFetch(`/api/v1/mobile/orders/${encodeURIComponent(targetOrderId)}/copy-dishes`, {
    method: 'POST',
    body: JSON.stringify({ source_order_id: sourceOrderId }),
  });
}

// ─── 4. 沽清管理 ───

export async function setDishAvailability(
  dishId: string,
  available: boolean,
): Promise<{ dish_id: string; available: boolean }> {
  return txFetch(`/api/v1/mobile/dishes/${encodeURIComponent(dishId)}/availability`, {
    method: 'PUT',
    body: JSON.stringify({ available }),
  });
}

// ─── 5. 限量设置 ───

export async function setDishDailyLimit(
  dishId: string,
  limit: number,
): Promise<{ dish_id: string; daily_limit: number }> {
  return txFetch(`/api/v1/mobile/dishes/${encodeURIComponent(dishId)}/daily-limit`, {
    method: 'PUT',
    body: JSON.stringify({ limit }),
  });
}

// ─── 6. 修改点菜员 ───

export async function updateOrderWaiter(
  orderId: string,
  newWaiterId: string,
): Promise<{ order_id: string; waiter_id: string }> {
  return txFetch(`/api/v1/mobile/orders/${encodeURIComponent(orderId)}/waiter`, {
    method: 'PUT',
    body: JSON.stringify({ new_waiter_id: newWaiterId }),
  });
}

// ─── 7. 刷新菜品状态 ───

export async function refreshDishStatus(
  storeId: string,
): Promise<{ items: DishStatusItem[]; total: number }> {
  return txFetch(`/api/v1/mobile/dishes/status?store_id=${encodeURIComponent(storeId)}`);
}

// ─── 8. AI 智能推荐 ───

export async function getAIRecommendations(
  storeId: string,
  orderId?: string,
): Promise<{ items: AIRecommendation[] }> {
  const orderParam = orderId ? `&order_id=${encodeURIComponent(orderId)}` : '';
  return txFetch(`/api/v1/scan-order/init?store_id=${encodeURIComponent(storeId)}${orderParam}&include_recommendations=true`);
}

// ─── 9. 出餐进度(KDS 状态) ───

export async function getOrderKdsStatus(
  orderId: string,
): Promise<{ items: OrderKdsItem[] }> {
  return txFetch(`/api/v1/scan-order/status/${encodeURIComponent(orderId)}`);
}

// ═══════════════════════════════════════════════
// 以下 9 个 API：补齐天财商龙移动收银台缺失功能
// ═══════════════════════════════════════════════

// ─── 类型（新增） ───

export interface PreBillItem {
  item_name: string;
  quantity: number;
  unit_price_fen: number;
  subtotal_fen: number;
  notes: string | null;
  is_gift: boolean;
}

export interface PreBillResult {
  order_id: string;
  order_no: string;
  table_no: string | null;
  items: PreBillItem[];
  subtotal_fen: number;
  discount_fen: number;
  service_charge_fen: number;
  total_fen: number;
  guest_count: number | null;
}

export interface FireResult {
  order_id: string;
  fired_count: number;
  items: string[];
}

export interface MarkServedResult {
  order_id: string;
  item_id: string;
  item_name: string;
  served_at: string;
}

export interface PriceOverrideResult {
  order_id: string;
  item_id: string;
  item_name: string;
  old_price_fen: number;
  new_price_fen: number;
  new_subtotal_fen: number;
  new_order_total_fen: number;
}

export interface TransferItemResult {
  order_id: string;
  item_id: string;
  item_name: string;
  target_table_no: string;
  target_order_id: string;
}

export interface PrintResult {
  order_id: string;
  order_no: string;
  printed: boolean;
  receipt_size_bytes: number;
}

export interface KitchenMessageResult {
  message_id: string;
  message: string;
  table_no: string;
  sent_at: string;
}

export interface TransferPaymentResult {
  payment_id: string;
  source_order_id: string;
  target_order_id: string;
  transferred: boolean;
}

// ─── 10. 埋单(Pre-bill) ───

export async function preBill(orderId: string): Promise<PreBillResult> {
  return txFetch(`/api/v1/mobile/orders/${encodeURIComponent(orderId)}/pre-bill`, {
    method: 'POST',
  });
}

// ─── 11. 起菜(Fire to Kitchen) ───

export async function fireToKitchen(orderId: string): Promise<FireResult> {
  return txFetch(`/api/v1/mobile/orders/${encodeURIComponent(orderId)}/fire`, {
    method: 'POST',
  });
}

// ─── 12. 上菜/划菜(Mark Served) ───

export async function markItemServed(
  orderId: string,
  itemId: string,
): Promise<MarkServedResult> {
  return txFetch(
    `/api/v1/mobile/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/served`,
    { method: 'PUT' },
  );
}

// ─── 13. 菜品变价(Price Override) ───

export async function overrideItemPrice(
  orderId: string,
  itemId: string,
  newPriceFen: number,
  reason?: string,
): Promise<PriceOverrideResult> {
  return txFetch(
    `/api/v1/mobile/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/price`,
    {
      method: 'PUT',
      body: JSON.stringify({ new_price_fen: newPriceFen, reason: reason || '' }),
    },
  );
}

// ─── 14. 单品转台(Transfer Single Item) ───

export async function transferSingleItem(
  orderId: string,
  itemId: string,
  targetTableNo: string,
): Promise<TransferItemResult> {
  return txFetch(
    `/api/v1/mobile/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/transfer`,
    {
      method: 'POST',
      body: JSON.stringify({ target_table_no: targetTableNo }),
    },
  );
}

// ─── 15. 打印客单(Print Receipt from Mobile) ───

export async function printOrderReceipt(orderId: string): Promise<PrintResult> {
  return txFetch(`/api/v1/mobile/orders/${encodeURIComponent(orderId)}/print`, {
    method: 'POST',
  });
}

// ─── 16. 后厨通知(Kitchen Message) ───

export async function sendKitchenMessage(
  message: string,
  tableNo?: string,
): Promise<KitchenMessageResult> {
  return txFetch('/api/v1/mobile/kds/message', {
    method: 'POST',
    body: JSON.stringify({ message, table_no: tableNo || '' }),
  });
}

// ─── 17. 转账(Transfer Payment) ───

export async function transferPayment(
  sourceOrderId: string,
  targetOrderId: string,
  paymentId: string,
): Promise<TransferPaymentResult> {
  return txFetch('/api/v1/mobile/payments/transfer', {
    method: 'POST',
    body: JSON.stringify({
      source_order_id: sourceOrderId,
      target_order_id: targetOrderId,
      payment_id: paymentId,
    }),
  });
}
