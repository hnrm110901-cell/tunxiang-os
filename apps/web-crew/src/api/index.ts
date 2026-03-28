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

// ─── 开台 ───

export async function openTable(
  storeId: string,
  tableNo: string,
  guestCount: number,
): Promise<{ table_no: string; order_id: string }> {
  return txFetch('/api/v1/trade/tables/open', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_no: tableNo, guest_count: guestCount }),
  });
}

export async function clearTable(
  storeId: string,
  tableNo: string,
): Promise<{ table_no: string; status: string }> {
  return txFetch('/api/v1/trade/tables/clear', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_no: tableNo }),
  });
}

// ─── 菜品列表 ───

export interface DishCategory {
  category_id: string;
  category_name: string;
}

export interface DishInfo {
  dish_id: string;
  dish_name: string;
  category_id: string;
  price_fen: number;
  image_url?: string;
  tags?: string[];
  sold_out: boolean;
  is_market_price: boolean;   // 时价菜
  is_weighed: boolean;        // 称重菜
  specs?: DishSpec[];
}

export interface DishSpec {
  spec_id: string;
  spec_name: string;       // 如"做法"
  options: string[];        // 如["红烧","清蒸","葱油"]
}

export async function fetchDishCategories(storeId: string): Promise<{ items: DishCategory[] }> {
  return txFetch(`/api/v1/menu/categories?store_id=${encodeURIComponent(storeId)}`);
}

export async function fetchDishes(storeId: string, categoryId?: string): Promise<{ items: DishInfo[]; total: number }> {
  const catParam = categoryId ? `&category_id=${encodeURIComponent(categoryId)}` : '';
  return txFetch(`/api/v1/menu/dishes?store_id=${encodeURIComponent(storeId)}${catParam}`);
}

// ─── KDS 出餐任务 ───

export interface KdsTask {
  task_id: string;
  order_id: string;
  table_no: string;
  dish_name: string;
  quantity: number;
  spec?: string;
  status: 'pending' | 'cooking' | 'done';
  created_at: string;
}

export async function fetchKdsTasks(storeId: string, orderId: string): Promise<{ items: KdsTask[] }> {
  return txFetch(`/api/v1/kds/tasks?store_id=${encodeURIComponent(storeId)}&order_id=${encodeURIComponent(orderId)}`);
}

export async function rushKdsTask(taskId: string): Promise<{ task_id: string; rushed: boolean }> {
  return txFetch(`/api/v1/kds/tasks/${encodeURIComponent(taskId)}/rush`, {
    method: 'POST',
  });
}

// ─── 转台/并台 ───

export async function transferTable(
  storeId: string,
  fromTable: string,
  toTable: string,
): Promise<{ from_table: string; to_table: string }> {
  return txFetch('/api/v1/trade/tables/transfer', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, from_table: fromTable, to_table: toTable }),
  });
}

export async function mergeTables(
  storeId: string,
  mainTable: string,
  mergeTables: string[],
): Promise<{ main_table: string; merged_tables: string[] }> {
  return txFetch('/api/v1/trade/tables/merge', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, main_table: mainTable, merge_tables: mergeTables }),
  });
}

// ─── 会员 ───

export interface MemberInfo {
  member_id: string;
  name: string;
  phone: string;
  level: string;
  points: number;
  balance_fen: number;
  preferences: string[];
  visit_count: number;
  last_visit: string;
}

export async function searchMember(keyword: string): Promise<{ items: MemberInfo[] }> {
  return txFetch(`/api/v1/member/search?keyword=${encodeURIComponent(keyword)}`);
}

export async function bindMemberToOrder(
  orderId: string,
  memberId: string,
): Promise<{ order_id: string; member_id: string }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/bind-member`, {
    method: 'POST',
    body: JSON.stringify({ member_id: memberId }),
  });
}

// ─── 客诉 ───

export interface ComplaintPayload {
  store_id: string;
  table_no?: string;
  order_id?: string;
  type: 'dish' | 'service' | 'environment' | 'wait';
  description: string;
  image_urls?: string[];
}

export async function submitComplaint(payload: ComplaintPayload): Promise<{ complaint_id: string }> {
  return txFetch('/api/v1/ops/complaints', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// ─── 服务确认 ───

export interface ServiceStatus {
  table_no: string;
  guest_count: number;
  order_status: 'ordered' | 'all_served' | 'pending_checkout';
  total_fen: number;
  elapsed_min: number;
  last_patrol: string | null;
}

export async function fetchServiceStatus(storeId: string): Promise<{ items: ServiceStatus[] }> {
  return txFetch(`/api/v1/trade/service-status?store_id=${encodeURIComponent(storeId)}`);
}

export async function recordPatrol(
  storeId: string,
  tableNo: string,
): Promise<{ table_no: string; patrol_time: string }> {
  return txFetch('/api/v1/trade/patrol', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_no: tableNo }),
  });
}
