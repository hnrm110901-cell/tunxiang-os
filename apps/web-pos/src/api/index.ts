/**
 * web-pos 统一 API 客户端
 * 所有页面通过此文件调用后端，不再使用 mock 数据。
 */

// ─── 基础配置 ───

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export async function txFetch<T>(path: string, options?: RequestInit): Promise<T> {
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

// ─── 各域 API 统一导出 ───

export * from './tradeApi';
export * from './menuApi';

// ─── 排队 ───

export interface QueueItem {
  queue_id: string;
  queue_no: string;
  guest_count: number;
  status: string;
  created_at: string;
}

export async function fetchQueueList(storeId: string): Promise<{ items: QueueItem[]; total: number }> {
  return txFetch(`/api/v1/trade/queue?store_id=${encodeURIComponent(storeId)}`);
}

export async function takeQueueNumber(
  storeId: string,
  guestCount: number,
): Promise<{ queue_id: string; queue_no: string; estimated_wait_min: number }> {
  return txFetch('/api/v1/trade/queue/take', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, guest_count: guestCount }),
  });
}

// ─── 日报 ───

export interface DailyReportData {
  date: string;
  revenue_fen: number;
  order_count: number;
  avg_ticket_fen: number;
  top_dishes: Array<{ dish_id: string; dish_name: string; quantity: number }>;
}

export async function fetchDailyReport(storeId: string): Promise<DailyReportData> {
  return txFetch(`/api/v1/analytics/reports/daily?store_id=${encodeURIComponent(storeId)}`);
}

// ─── 异常事件 ───

export interface ExceptionItem {
  exception_id: string;
  type: string;
  severity: string;
  message: string;
  created_at: string;
  resolved: boolean;
}

export async function fetchExceptions(storeId: string): Promise<{ items: ExceptionItem[]; total: number }> {
  return txFetch(`/api/v1/ops/exceptions?store_id=${encodeURIComponent(storeId)}`);
}
