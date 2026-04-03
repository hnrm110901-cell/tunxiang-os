/**
 * 派单 API — /api/v1/dispatch/*
 * Agent/人工派单、审批流转、执行跟踪
 */
import { txFetch } from './index';

// ─── 类型 ───

export type DispatchStatus = 'pending' | 'assigned' | 'in_progress' | 'completed' | 'cancelled';
export type DispatchSource = 'agent' | 'manual' | 'system';

export interface DispatchTicket {
  ticket_id: string;
  source: DispatchSource;
  agent_id: string | null;
  store_id: string;
  store_name: string;
  title: string;
  description: string;
  priority: 'critical' | 'high' | 'medium' | 'low';
  status: DispatchStatus;
  assignee_id: string | null;
  assignee_name: string | null;
  created_at: string;
  deadline: string | null;
  completed_at: string | null;
}

export interface DispatchComment {
  comment_id: string;
  ticket_id: string;
  author: string;
  content: string;
  created_at: string;
}

// ─── 接口 ───

/** 获取派单列表 */
export async function fetchDispatchTickets(
  status?: DispatchStatus,
  storeId?: string,
  page = 1,
  size = 20,
): Promise<{ items: DispatchTicket[]; total: number }> {
  const params = new URLSearchParams({ page: String(page), size: String(size) });
  if (status) params.set('status', status);
  if (storeId) params.set('store_id', storeId);
  return txFetch(`/api/v1/dispatch/tickets?${params.toString()}`);
}

/** 获取单个派单详情 */
export async function getDispatchDetail(
  ticketId: string,
): Promise<DispatchTicket & { comments: DispatchComment[] }> {
  return txFetch(`/api/v1/dispatch/tickets/${encodeURIComponent(ticketId)}`);
}

/** 创建派单（人工） */
export async function createDispatchTicket(
  storeId: string,
  title: string,
  description: string,
  priority: 'critical' | 'high' | 'medium' | 'low',
  assigneeId?: string,
  deadline?: string,
): Promise<{ ticket_id: string }> {
  return txFetch('/api/v1/dispatch/tickets', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      title,
      description,
      priority,
      assignee_id: assigneeId,
      deadline,
    }),
  });
}

/** 分配处理人 */
export async function assignDispatchTicket(
  ticketId: string,
  assigneeId: string,
): Promise<{ ticket_id: string; assignee_id: string }> {
  return txFetch(`/api/v1/dispatch/tickets/${encodeURIComponent(ticketId)}/assign`, {
    method: 'POST',
    body: JSON.stringify({ assignee_id: assigneeId }),
  });
}

/** 更新派单状态 */
export async function updateDispatchStatus(
  ticketId: string,
  status: DispatchStatus,
  note?: string,
): Promise<{ ticket_id: string; status: DispatchStatus }> {
  return txFetch(`/api/v1/dispatch/tickets/${encodeURIComponent(ticketId)}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status, note }),
  });
}

/** 添加评论 */
export async function addDispatchComment(
  ticketId: string,
  content: string,
): Promise<{ comment_id: string }> {
  return txFetch(`/api/v1/dispatch/tickets/${encodeURIComponent(ticketId)}/comments`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}
