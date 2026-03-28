/**
 * 排队 API — /api/v1/queue/*
 * 取号、叫号、过号、排队状态
 */
import { txFetch } from './index';

// ─── 类型 ───

export type QueueStatus = 'waiting' | 'called' | 'seated' | 'skipped';
export type QueueType = 'large' | 'small';

export interface QueueItem {
  queue_id: string;
  queue_number: string;
  type: QueueType;
  guest_count: number;
  customer_name: string;
  phone: string;
  status: QueueStatus;
  taken_at: string;
  estimated_wait_min: number;
}

export interface QueueSummary {
  large_waiting: number;
  small_waiting: number;
  avg_wait_min_large: number;
  avg_wait_min_small: number;
  total_today: number;
  seated_today: number;
}

// ─── 接口 ───

/** 获取当前排队列表 */
export async function fetchQueueList(
  storeId: string,
  type?: QueueType,
): Promise<{ items: QueueItem[]; total: number }> {
  const typeParam = type ? `&type=${encodeURIComponent(type)}` : '';
  return txFetch(`/api/v1/queue?store_id=${encodeURIComponent(storeId)}${typeParam}`);
}

/** 获取排队统计摘要 */
export async function fetchQueueSummary(
  storeId: string,
): Promise<QueueSummary> {
  return txFetch(`/api/v1/queue/summary?store_id=${encodeURIComponent(storeId)}`);
}

/** 取号 */
export async function takeNumber(
  storeId: string,
  guestCount: number,
  customerName: string,
  phone: string,
): Promise<{ queue_id: string; queue_number: string; estimated_wait_min: number }> {
  return txFetch('/api/v1/queue/take', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      guest_count: guestCount,
      customer_name: customerName,
      phone,
    }),
  });
}

/** 叫号 */
export async function callNumber(
  queueId: string,
): Promise<{ queue_id: string; status: QueueStatus }> {
  return txFetch(`/api/v1/queue/${encodeURIComponent(queueId)}/call`, {
    method: 'POST',
  });
}

/** 确认入座 */
export async function seatGuest(
  queueId: string,
  tableNo: string,
): Promise<{ queue_id: string; table_no: string; status: QueueStatus }> {
  return txFetch(`/api/v1/queue/${encodeURIComponent(queueId)}/seat`, {
    method: 'POST',
    body: JSON.stringify({ table_no: tableNo }),
  });
}

/** 过号 */
export async function skipNumber(
  queueId: string,
): Promise<{ queue_id: string; status: QueueStatus }> {
  return txFetch(`/api/v1/queue/${encodeURIComponent(queueId)}/skip`, {
    method: 'POST',
  });
}

/** 重新激活过号的客人 */
export async function reactivateNumber(
  queueId: string,
): Promise<{ queue_id: string; status: QueueStatus }> {
  return txFetch(`/api/v1/queue/${encodeURIComponent(queueId)}/reactivate`, {
    method: 'POST',
  });
}
