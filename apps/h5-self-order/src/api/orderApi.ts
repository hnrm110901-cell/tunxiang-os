import { txFetch } from './index';

/* ---- 类型定义 ---- */

export interface CartItemPayload {
  dishId: string;
  quantity: number;
  customSelections: Record<string, string[]>; // groupName -> selected item ids
  remark?: string;
}

export interface CreateOrderPayload {
  storeId: string;
  tableNo: string;
  items: CartItemPayload[];
  remark?: string;
  phone?: string;
  couponId?: string;
}

export type OrderStatus = 'received' | 'cooking' | 'ready' | 'pickup' | 'completed';

export interface OrderStatusInfo {
  orderId: string;
  status: OrderStatus;
  steps: {
    key: OrderStatus;
    label: string;
    estimatedMinutes: number;
    completedAt?: string;
  }[];
  currentDishName?: string;
  createdAt: string;
}

export interface OrderSummary {
  orderId: string;
  totalAmount: number;
  discountAmount: number;
  payableAmount: number;
  itemCount: number;
  items: {
    dishId: string;
    dishName: string;
    dishImage: string;
    quantity: number;
    price: number;
    subtotal: number;
  }[];
}

export interface FeedbackPayload {
  orderId: string;
  dishRatings: { dishId: string; rating: number }[];
  serviceRating: number;
  environmentRating: number;
  comment?: string;
  photoUrls?: string[];
}

/* ---- API 函数 ---- */

export function createOrder(payload: CreateOrderPayload) {
  return txFetch<{ orderId: string }>('/orders', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getOrderStatus(orderId: string) {
  return txFetch<OrderStatusInfo>(`/orders/${orderId}/status`);
}

export function getOrderSummary(orderId: string) {
  return txFetch<OrderSummary>(`/orders/${orderId}/summary`);
}

export function rushOrder(orderId: string) {
  return txFetch<{ success: boolean }>(`/orders/${orderId}/rush`, {
    method: 'POST',
  });
}

export function submitFeedback(payload: FeedbackPayload) {
  return txFetch<{ pointsEarned: number }>('/feedback', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function resolveTableQR(code: string) {
  return txFetch<{ storeId: string; storeName: string; tableNo: string; tenantId: string }>(
    `/scan/resolve?code=${encodeURIComponent(code)}`,
  );
}
