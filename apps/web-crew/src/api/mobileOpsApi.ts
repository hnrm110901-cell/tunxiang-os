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
