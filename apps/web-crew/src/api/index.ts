/**
 * web-crew 统一 API 客户端
 * 服务员 PWA 端所有页面通过此文件调用后端。
 */

// ─── 基础配置 ───

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

async function txFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options?.headers as Record<string, string> || {}),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 桌台状态 ───

export interface TableInfo {
  table_no: string;
  status: 'idle' | 'occupied' | 'reserved' | 'cleaning';
  guest_count: number;
  order_id: string | null;
  seated_at: string | null;
}

export async function fetchTableStatus(storeId: string): Promise<{ items: TableInfo[]; total: number }> {
  return txFetch(`/api/v1/trade/tables?store_id=${encodeURIComponent(storeId)}`);
}

// ─── 下单 ───

export interface OrderItem {
  dish_id: string;
  dish_name: string;
  quantity: number;
  unit_price_fen: number;
  special_notes?: string;
}

export interface SubmitOrderResult {
  order_id: string;
  order_no: string;
  total_fen: number;
}

export async function submitOrder(
  storeId: string,
  tableNo: string,
  items: OrderItem[],
): Promise<SubmitOrderResult> {
  return txFetch('/api/v1/trade/orders', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      table_no: tableNo,
      order_type: 'dine_in',
      items,
    }),
  });
}

// ─── 活跃订单 ───

export interface ActiveOrder {
  order_id: string;
  order_no: string;
  table_no: string;
  status: string;
  total_fen: number;
  item_count: number;
  created_at: string;
}

export async function fetchActiveOrders(storeId: string): Promise<{ items: ActiveOrder[]; total: number }> {
  return txFetch(`/api/v1/trade/orders?store_id=${encodeURIComponent(storeId)}&status=active`);
}

// ─── 催单 ───

export async function rushOrder(orderId: string): Promise<{ order_id: string; rushed: boolean }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/rush`, {
    method: 'POST',
  });
}

// ─── 每日运营摘要 ───

export interface DailyOpsData {
  date: string;
  store_id: string;
  total_orders: number;
  total_revenue_fen: number;
  avg_serve_time_sec: number;
  peak_hour: string;
}

export async function fetchDailyOps(storeId: string, date?: string): Promise<DailyOpsData> {
  const query = date ? `&date=${encodeURIComponent(date)}` : '';
  return txFetch(`/api/v1/ops/daily-summary?store_id=${encodeURIComponent(storeId)}${query}`);
}

// ─── 评价数据 ───

export interface ReviewData {
  store_id: string;
  avg_rating: number;
  total_reviews: number;
  recent: Array<{
    review_id: string;
    customer_name: string;
    rating: number;
    comment: string;
    created_at: string;
  }>;
}

export async function fetchReviewData(storeId: string): Promise<ReviewData> {
  return txFetch(`/api/v1/crm/reviews?store_id=${encodeURIComponent(storeId)}`);
}

// ─── 员工个人资料 ───

export interface ProfileData {
  employee_id: string;
  name: string;
  role: string;
  phone: string;
  store_id: string;
  store_name: string;
  avatar_url: string;
  today_orders: number;
  today_revenue_fen: number;
}

export async function fetchProfile(employeeId: string): Promise<ProfileData> {
  return txFetch(`/api/v1/org/employees/${encodeURIComponent(employeeId)}/profile`);
}
