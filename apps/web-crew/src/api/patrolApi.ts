/**
 * 巡检整改执行 API
 * PatrolExecutionPage — 店长/岗位负责人巡检 + 整改任务跟踪
 *
 * API:
 *   GET   /api/v1/ops/inspection/today
 *   GET   /api/v1/ops/inspection/items
 *   PATCH /api/v1/ops/inspection/items/:id
 *   POST  /api/v1/ops/inspection/submit
 *   GET   /api/v1/ops/rectification/my-tasks
 *   PATCH /api/v1/ops/rectification/tasks/:id/feedback
 */
import { txFetch } from './index';

// ─── 巡检类型 ───

export type CheckStatus = 'pending' | 'pass' | 'fail' | 'na';
export type InspectionCategory = 'food_safety' | 'hygiene' | 'equipment' | 'service' | 'fire_safety';

export interface InspectionItem {
  id: string;
  category: InspectionCategory;
  name: string;
  description: string;
  status: CheckStatus;
  note?: string;
  photos?: string[];
  severity?: 'high' | 'medium' | 'low';
}

export interface InspectionSummary {
  total: number;
  completed: number;
  pass: number;
  fail: number;
  na: number;
  last_inspection_at?: string;
}

// ─── 整改任务类型 ───

export interface RectifyTask {
  id: string;
  title: string;
  source: string;
  deadline: string;
  status: 'pending' | 'in_progress' | 'completed';
  description: string;
  feedback?: string;
  photos_before?: string[];
  photos_after?: string[];
}

// ─── API 调用 ───

export async function fetchInspectionToday(): Promise<InspectionSummary> {
  return txFetch('/api/v1/ops/inspection/today');
}

export async function fetchInspectionItems(): Promise<{ items: InspectionItem[] }> {
  return txFetch('/api/v1/ops/inspection/items');
}

export async function updateInspectionItem(
  id: string,
  payload: { status: CheckStatus; note?: string; severity?: 'high' | 'medium' | 'low' },
): Promise<InspectionItem> {
  return txFetch(`/api/v1/ops/inspection/items/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function submitInspection(
  items: Array<{ id: string; status: CheckStatus; note?: string; severity?: string }>,
): Promise<{ inspection_id: string; summary: InspectionSummary }> {
  return txFetch('/api/v1/ops/inspection/submit', {
    method: 'POST',
    body: JSON.stringify({ items }),
  });
}

export async function fetchRectifyTasks(): Promise<{ items: RectifyTask[] }> {
  return txFetch('/api/v1/ops/rectification/my-tasks');
}

export async function submitRectifyFeedback(
  taskId: string,
  payload: { feedback: string; status: 'in_progress' | 'completed' },
): Promise<RectifyTask> {
  return txFetch(`/api/v1/ops/rectification/tasks/${encodeURIComponent(taskId)}/feedback`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}
