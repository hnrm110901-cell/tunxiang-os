/**
 * 整改指挥中心 API — /api/v1/ops/rectification/*
 */
import { txFetchData } from './client';

// ─── 类型 ───

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'overdue' | 'escalated';
export type Severity = 'critical' | 'warning' | 'info';

export interface TimelineEntry {
  time: string;
  action: string;
  operator: string;
  note?: string;
}

export interface RectificationTask {
  id: string;
  alert_id: string;
  alert_title: string;
  alert_category: string;
  store_id: string;
  store_name: string;
  region: string;
  assignee: string;
  severity: Severity;
  status: TaskStatus;
  description: string;
  requirement: string;
  deadline: string;
  created_at: string;
  updated_at: string;
  escalation_level: number; // 0=门店, 1=区域, 2=总部
  timeline: TimelineEntry[];
  photos_before?: string[];
  photos_after?: string[];
  completion_rate?: number;
}

export interface RectificationSummary {
  pending: number;
  in_progress: number;
  completed: number;
  overdue: number;
  avg_resolve_hours: number;
  completion_rate: number;
  by_region: { region: string; count: number; completed: number }[];
}

export interface CreateTaskPayload {
  alert_id: string;
  store_id: string;
  assignee: string;
  severity: Severity;
  description: string;
  requirement: string;
  deadline: string;
}

export interface UpdateStatusPayload {
  status: TaskStatus;
  note?: string;
}

// ─── 接口 ───

/** 获取整改任务汇总统计 */
export async function fetchRectificationSummary(): Promise<RectificationSummary> {
  return txFetchData<RectificationSummary>('/api/v1/ops/rectification/summary');
}

/** 获取整改任务列表（支持筛选） */
export async function fetchRectificationTasks(params?: {
  status?: TaskStatus;
  severity?: Severity;
  region?: string;
  store_id?: string;
  q?: string;
}): Promise<RectificationTask[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set('status', params.status);
  if (params?.severity) query.set('severity', params.severity);
  if (params?.region) query.set('region', params.region);
  if (params?.store_id) query.set('store_id', params.store_id);
  if (params?.q) query.set('q', params.q);
  const qs = query.toString();
  return txFetchData<RectificationTask[]>(`/api/v1/ops/rectification/tasks${qs ? `?${qs}` : ''}`);
}

/** 获取单个整改任务详情 */
export async function fetchRectificationTask(taskId: string): Promise<RectificationTask> {
  return txFetchData<RectificationTask>(
    `/api/v1/ops/rectification/tasks/${encodeURIComponent(taskId)}`
  );
}

/** 从预警创建整改任务 */
export async function createRectificationTask(payload: CreateTaskPayload): Promise<RectificationTask> {
  return txFetchData<RectificationTask>('/api/v1/ops/rectification/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 变更整改任务状态 */
export async function updateRectificationStatus(
  taskId: string,
  payload: UpdateStatusPayload
): Promise<RectificationTask> {
  return txFetchData<RectificationTask>(
    `/api/v1/ops/rectification/tasks/${encodeURIComponent(taskId)}/status`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }
  );
}
