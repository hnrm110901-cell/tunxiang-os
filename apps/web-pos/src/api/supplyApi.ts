/**
 * tx-supply API 客户端 — 收货验收模块
 *
 * 对接后端 receiving_v2_routes (POST/GET /api/v1/receiving/orders)
 * 和 inventory.py (GET /api/v1/supply/purchase-orders, /api/v1/supply/ingredients)
 */

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

async function txFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options.headers as Record<string, string> || {}),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 类型 ───

export interface PurchaseOrderItem {
  item_id: string;
  ingredient_id: string;
  ingredient_name: string;
  ordered_qty: number;
  unit: string;
  unit_price_fen: number;
}

export interface PurchaseOrder {
  po_id: string;
  po_no: string;
  supplier_id: string;
  supplier_name: string;
  store_id: string;
  status: string;
  items: PurchaseOrderItem[];
  created_at: string;
}

export interface IngredientOption {
  ingredient_id: string;
  name: string;
  unit: string;
  category: string;
}

export interface ReceivingOrderItem {
  item_id: string;
  ingredient_id: string;
  ingredient_name: string;
  expected_quantity: number;
  actual_quantity: number | null;
  accepted_quantity: number | null;
  expected_unit: string;
  unit_price_fen: number | null;
  batch_no: string | null;
  expiry_date: string | null;
  rejection_reason: string | null;
  status: string;
}

export interface ReceivingOrder {
  order_id: string;
  store_id: string;
  supplier_id: string | null;
  procurement_order_id: string | null;
  delivery_note_no: string | null;
  receiver_id: string | null;
  status: string;
  items: ReceivingOrderItem[];
  created_at: string;
  completed_at: string | null;
  total_accepted_value_fen: number;
}

// ─── 采购单查询 ───

export async function fetchPurchaseOrders(
  storeId: string,
  status = 'pending',
  keyword = '',
): Promise<{ items: PurchaseOrder[]; total: number }> {
  const params = new URLSearchParams({ store_id: storeId, status });
  if (keyword) params.set('keyword', keyword);
  return txFetch(`/api/v1/supply/purchase-orders?${params.toString()}`);
}

// ─── 食材列表（快速收货搜索用） ───

export async function searchIngredients(
  storeId: string,
  keyword = '',
): Promise<{ items: IngredientOption[] }> {
  const params = new URLSearchParams({ store_id: storeId });
  if (keyword) params.set('keyword', keyword);
  return txFetch(`/api/v1/supply/ingredients?${params.toString()}`);
}

// ─── 收货单 CRUD (V2) ───

export interface CreateReceivingItemInput {
  ingredient_id: string;
  ingredient_name: string;
  expected_quantity: number;
  expected_unit: string;
  unit_price_fen?: number;
}

export interface CreateReceivingInput {
  store_id: string;
  supplier_id?: string;
  delivery_note_no?: string;
  procurement_order_id?: string;
  receiver_id?: string;
  items: CreateReceivingItemInput[];
}

export async function createReceivingOrder(
  input: CreateReceivingInput,
): Promise<ReceivingOrder> {
  return txFetch('/api/v1/receiving/orders', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function listReceivingOrders(
  storeId: string,
  dateFrom?: string,
  dateTo?: string,
  status?: string,
  page = 1,
  size = 20,
): Promise<{ items: ReceivingOrder[]; total: number }> {
  const params = new URLSearchParams({ store_id: storeId, page: String(page), size: String(size) });
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (status) params.set('status', status);
  return txFetch(`/api/v1/receiving/orders?${params.toString()}`);
}

export async function getReceivingOrder(orderId: string): Promise<ReceivingOrder> {
  return txFetch(`/api/v1/receiving/orders/${orderId}`);
}

export interface InspectItemInput {
  actual_quantity: number;
  accepted_quantity: number;
  unit_price_fen?: number;
  batch_no?: string;
  expiry_date?: string;
  rejection_reason?: string;
}

export async function inspectReceivingItem(
  orderId: string,
  itemId: string,
  input: InspectItemInput,
): Promise<ReceivingOrderItem> {
  return txFetch(`/api/v1/receiving/orders/${orderId}/items/${itemId}/inspect`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function completeReceiving(
  orderId: string,
  storeId: string,
  signerId?: string,
): Promise<ReceivingOrder> {
  return txFetch(`/api/v1/receiving/orders/${orderId}/complete`, {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, signer_id: signerId }),
  });
}

export async function rejectAllReceiving(
  orderId: string,
  reason?: string,
): Promise<ReceivingOrder> {
  return txFetch(`/api/v1/receiving/orders/${orderId}/reject-all`, {
    method: 'POST',
    body: JSON.stringify({ rejection_reason: reason }),
  });
}
