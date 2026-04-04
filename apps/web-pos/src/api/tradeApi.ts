/**
 * tx-trade API 客户端
 * 收银全流程：开单→加菜→结算→支付→打印
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

// ─── 订单 ───

export interface CreateOrderResult {
  order_id: string;
  order_no: string;
}

export async function createOrder(storeId: string, tableNo: string): Promise<CreateOrderResult> {
  return txFetch('/api/v1/trade/orders', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_no: tableNo, order_type: 'dine_in' }),
  });
}

export interface AddItemResult {
  item_id: string;
  subtotal_fen: number;
}

export async function addItem(
  orderId: string,
  dishId: string,
  dishName: string,
  quantity: number,
  unitPriceFen: number,
): Promise<AddItemResult> {
  return txFetch(`/api/v1/trade/orders/${orderId}/items`, {
    method: 'POST',
    body: JSON.stringify({ dish_id: dishId, dish_name: dishName, quantity, unit_price_fen: unitPriceFen }),
  });
}

export async function removeItem(orderId: string, itemId: string): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${orderId}/items/${itemId}`, { method: 'DELETE' });
}

export async function settleOrder(orderId: string): Promise<{ order_no: string; final_amount_fen: number }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/settle`, { method: 'POST' });
}

export async function cancelOrder(orderId: string, reason = ''): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${orderId}/cancel?reason=${encodeURIComponent(reason)}`, { method: 'POST' });
}

export async function getOrder(orderId: string): Promise<Record<string, unknown>> {
  return txFetch(`/api/v1/trade/orders/${orderId}`);
}

// ─── 支付 ───

export async function createPayment(
  orderId: string,
  method: string,
  amountFen: number,
  tradeNo?: string,
): Promise<{ payment_id: string; payment_no: string }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/payments`, {
    method: 'POST',
    body: JSON.stringify({ method, amount_fen: amountFen, trade_no: tradeNo }),
  });
}

export async function processRefund(
  orderId: string,
  paymentId: string,
  amountFen: number,
  reason = '',
): Promise<{ refund_no: string }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/refund`, {
    method: 'POST',
    body: JSON.stringify({ payment_id: paymentId, amount_fen: amountFen, reason }),
  });
}

// ─── 打印 ───

export async function printReceipt(orderId: string): Promise<{ content_base64: string }> {
  return txFetch(`/api/v1/trade/orders/${orderId}/print/receipt`, { method: 'POST' });
}

export async function printKitchen(orderId: string, station = ''): Promise<Record<string, unknown>> {
  return txFetch(`/api/v1/trade/orders/${orderId}/print/kitchen?station=${encodeURIComponent(station)}`, { method: 'POST' });
}

// ─── 反结账 ───

export interface ReverseSettleResult {
  order_id: string;
  status: string;
  reopened_at: string;
}

export async function reverseSettle(
  orderId: string,
  reason: string,
  remark: string,
  authCode: string,
): Promise<ReverseSettleResult> {
  return txFetch(`/api/v1/trade/orders/${orderId}/reverse-settle`, {
    method: 'POST',
    body: JSON.stringify({ reason, remark, auth_code: authCode }),
  });
}

// ─── 企业挂账 ───

export interface CreditAccountItem {
  id: string;
  name: string;
  contact_person: string;
  credit_limit_fen: number;
  used_fen: number;
  status: 'active' | 'frozen';
}

export async function fetchCreditAccounts(
  storeId: string,
  keyword = '',
): Promise<{ items: CreditAccountItem[] }> {
  const params = new URLSearchParams({ store_id: storeId });
  if (keyword) params.set('keyword', keyword);
  return txFetch(`/api/v1/trade/credit-accounts?${params.toString()}`);
}

// ─── Agent ───

export async function dispatchAgent(agentId: string, action: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  return txFetch(`/api/v1/agent/dispatch?agent_id=${agentId}&action=${action}`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export async function listAgents(): Promise<Array<{ agent_id: string; agent_name: string; priority: string }>> {
  return txFetch('/api/v1/agent/agents');
}

// ─── 发票 ───

export interface SubmitInvoiceParams {
  order_id: string;
  invoice_type: string;
  title: string;
  tax_no: string;
  amount_fen: number;
  bank_name?: string;
  bank_account?: string;
  company_address?: string;
  company_phone?: string;
  receiver_email?: string;
  receiver_phone?: string;
  remark?: string;
}

export interface SubmitInvoiceResult {
  invoice_id: string;
  invoice_no: string;
  status: string;
  pdf_url?: string;
}

export async function submitInvoice(params: SubmitInvoiceParams): Promise<SubmitInvoiceResult> {
  return txFetch('/api/v1/trade/invoices', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}
