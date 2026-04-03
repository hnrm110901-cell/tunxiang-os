/**
 * KDS 操作 API — /api/v1/kds/*
 * 分单/队列/开始制作/完成/催菜/重做/超时
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface KDSTicketItem {
  dish_name: string;
  quantity: number;
  special_notes: string;
  spec: string;
}

export interface KDSTicket {
  ticket_id: string;
  order_id: string;
  order_no: string;
  table_no: string;
  items: KDSTicketItem[];
  status: 'pending' | 'cooking' | 'done' | 'cancelled';
  priority: 'normal' | 'rush' | 'vip';
  dept_id: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  rush_count: number;
  is_overtime: boolean;
  time_limit_min: number;
}

export interface KDSQueueInfo {
  station_id: string;
  pending_count: number;
  cooking_count: number;
  avg_wait_sec: number;
  avg_cook_sec: number;
}

export interface RemakeRequest {
  ticket_id: string;
  reason: 'complaint' | 'quality' | 'wrong_dish' | 'wrong_spec' | 'other';
  note: string;
}

// ─── 接口 ───

/** 获取当前队列中的所有票据 */
export async function fetchTicketQueue(
  stationId: string,
  status?: string,
): Promise<{ items: KDSTicket[]; total: number }> {
  const statusParam = status ? `&status=${encodeURIComponent(status)}` : '';
  return txFetch(
    `/api/v1/kds/queue?station_id=${encodeURIComponent(stationId)}${statusParam}`,
  );
}

/** 获取队列统计信息 */
export async function fetchQueueInfo(
  stationId: string,
): Promise<KDSQueueInfo> {
  return txFetch(`/api/v1/kds/queue/info?station_id=${encodeURIComponent(stationId)}`);
}

/** 开始制作（pending → cooking） */
export async function startTicket(
  ticketId: string,
): Promise<{ ticket_id: string; status: string; started_at: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/start`, {
    method: 'POST',
  });
}

/** 完成制作（cooking → done） */
export async function completeTicket(
  ticketId: string,
): Promise<{ ticket_id: string; status: string; completed_at: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/complete`, {
    method: 'POST',
  });
}

/** 催菜标记 */
export async function rushTicket(
  ticketId: string,
): Promise<{ ticket_id: string; rush_count: number }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/rush`, {
    method: 'POST',
  });
}

/** 重做 */
export async function remakeTicket(
  request: RemakeRequest,
): Promise<{ new_ticket_id: string; original_ticket_id: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(request.ticket_id)}/remake`, {
    method: 'POST',
    body: JSON.stringify({ reason: request.reason, note: request.note }),
  });
}

/** 超时票据列表 */
export async function fetchOvertimeTickets(
  stationId: string,
): Promise<{ items: KDSTicket[] }> {
  return txFetch(
    `/api/v1/kds/tickets/overtime?station_id=${encodeURIComponent(stationId)}`,
  );
}

/** 确认超时已处理 */
export async function resolveOvertimeTicket(
  ticketId: string,
  action: 'expedite' | 'cancel' | 'reassign',
): Promise<{ ticket_id: string; resolved: boolean }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/resolve-timeout`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}

/** 分单 — 按档口拆分订单到不同工作站 */
export async function splitToStations(
  orderId: string,
): Promise<{ tickets: Array<{ ticket_id: string; station_id: string; dept_id: string }> }> {
  return txFetch(`/api/v1/kds/split`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId }),
  });
}

// ─── 停菜控制 ───

/** 停菜：暂缓出品（半成品已做好但暂缓上桌） */
export async function pauseTicket(
  ticketId: string,
  operatorId?: string,
): Promise<{ task_id: string; is_paused: boolean; paused_at: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/pause`, {
    method: 'POST',
    body: JSON.stringify({ operator_id: operatorId }),
  });
}

/** 恢复停菜 */
export async function resumeTicket(
  ticketId: string,
  operatorId?: string,
): Promise<{ task_id: string; is_paused: boolean; resumed_at: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/resume`, {
    method: 'POST',
    body: JSON.stringify({ operator_id: operatorId }),
  });
}

// ─── 抢单 ───

/** 抢单：厨师主动认领 pending 任务并立即开始制作 */
export async function grabTicket(
  ticketId: string,
  operatorId: string,
): Promise<{ task_id: string; grabbed_by: string; status: string; started_at: string }> {
  return txFetch(`/api/v1/kds/tickets/${encodeURIComponent(ticketId)}/grab`, {
    method: 'POST',
    body: JSON.stringify({ operator_id: operatorId }),
  });
}

// ─── 沽清 ───

export interface SoldoutItem {
  dish_id: string;
  dish_name: string;
  soldout_at: string;
  reason: string | null;
  source: string;
}

/** 标记沽清 */
export async function markSoldout(payload: {
  store_id: string;
  dish_id: string;
  dish_name: string;
  reason?: string;
  reported_by?: string;
}): Promise<{ dish_id: string; record_id: string; soldout_at: string }> {
  return txFetch('/api/v1/kds/soldout', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 恢复沽清 */
export async function restoreSoldout(payload: {
  store_id: string;
  dish_id: string;
}): Promise<{ dish_id: string; restored_at: string }> {
  return txFetch('/api/v1/kds/soldout', {
    method: 'DELETE',
    body: JSON.stringify(payload),
  });
}

/** 查询当前门店所有沽清菜品 */
export async function fetchActiveSoldout(
  storeId: string,
): Promise<{ items: SoldoutItem[]; total: number }> {
  return txFetch(`/api/v1/kds/soldout?store_id=${encodeURIComponent(storeId)}`);
}

// ─── 同菜批量合并 ───

export interface BatchDishGroup {
  dish_id: string;
  dish_name: string;
  dept_id: string;
  total_qty: number;
  tickets: Array<{ ticket_id: string; table_no: string; qty: number; priority: string }>;
}

/** 获取批量合并视图（同档口同菜品聚合） */
export async function fetchBatchedQueue(
  deptId: string,
): Promise<{ groups: BatchDishGroup[] }> {
  return txFetch(`/api/v1/kds/queue/batched?dept_id=${encodeURIComponent(deptId)}`);
}
