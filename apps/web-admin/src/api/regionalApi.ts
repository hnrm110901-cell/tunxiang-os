/**
 * 区域追踪 API — /api/v1/regional/*
 * 区域门店评分卡、整改任务、跨店对标
 */
import { txFetchData } from './index';

// ─── 类型 ───

export type ScoreLevel = 'green' | 'yellow' | 'red';
export type RectifyStatus = 'pending' | 'in_progress' | 'completed' | 'overdue';

export interface StoreScoreCard {
  store_id: string;
  store_name: string;
  region: string;
  score: number;
  level: ScoreLevel;
  issue_count: number;
  last_inspect: string;
}

export interface RectifyTask {
  task_id: string;
  store_id: string;
  store_name: string;
  title: string;
  status: RectifyStatus;
  priority: 'high' | 'medium' | 'low';
  deadline: string;
  assignee: string;
  created_at: string;
}

export interface RectifyTimeline {
  time: string;
  event: string;
  operator: string;
}

export interface BenchmarkItem {
  store_id: string;
  store_name: string;
  metric: string;
  value: number;
  rank: number;
  avg_value: number;
}

// ─── 接口 ───

/** 区域门店评分卡列表 */
export async function fetchStoreScoreCards(
  region?: string,
): Promise<{ items: StoreScoreCard[] }> {
  const regionParam = region ? `?region=${encodeURIComponent(region)}` : '';
  return txFetchData<{ items: StoreScoreCard[] }>(`/api/v1/regional/score-cards${regionParam}`);
}

/** 整改任务列表 */
export async function fetchRectifyTasks(
  storeId?: string,
  status?: RectifyStatus,
  page = 1,
  size = 20,
): Promise<{ items: RectifyTask[]; total: number }> {
  const params = new URLSearchParams({ page: String(page), size: String(size) });
  if (storeId) params.set('store_id', storeId);
  if (status) params.set('status', status);
  return txFetchData<{ items: RectifyTask[]; total: number }>(`/api/v1/regional/rectify-tasks?${params.toString()}`);
}

/** 获取整改详情及时间线 */
export async function fetchRectifyDetail(
  taskId: string,
): Promise<RectifyTask & { timeline: RectifyTimeline[] }> {
  return txFetchData<RectifyTask & { timeline: RectifyTimeline[] }>(`/api/v1/regional/rectify-tasks/${encodeURIComponent(taskId)}`);
}

/** 创建整改任务 */
export async function createRectifyTask(
  storeId: string,
  title: string,
  priority: 'high' | 'medium' | 'low',
  deadline: string,
  assignee: string,
): Promise<{ task_id: string }> {
  return txFetchData<{ task_id: string }>('/api/v1/regional/rectify-tasks', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, title, priority, deadline, assignee }),
  });
}

/** 更新整改任务状态 */
export async function updateRectifyStatus(
  taskId: string,
  status: RectifyStatus,
  note?: string,
): Promise<{ task_id: string; status: RectifyStatus }> {
  return txFetchData<{ task_id: string; status: RectifyStatus }>(`/api/v1/regional/rectify-tasks/${encodeURIComponent(taskId)}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status, note }),
  });
}

/** 跨店对标排行 */
export async function fetchBenchmark(
  metric: string,
  region?: string,
): Promise<{ items: BenchmarkItem[] }> {
  const regionParam = region ? `&region=${encodeURIComponent(region)}` : '';
  return txFetchData<{ items: BenchmarkItem[] }>(`/api/v1/regional/benchmark?metric=${encodeURIComponent(metric)}${regionParam}`);
}
