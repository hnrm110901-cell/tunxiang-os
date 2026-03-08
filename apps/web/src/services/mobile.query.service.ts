import { apiClient } from './api';
import { getMockHomeSummary, getMockShiftSummary, getMockTaskDetail, getMockTaskSummary } from './mobile.mock';
import type { MobileHomeSummaryResponse, MobileTask, ShiftSummaryResponse, TaskSummaryResponse } from './mobile.types';

const STORE_ID = localStorage.getItem('store_id') || 'STORE001';

export async function queryHomeSummary(): Promise<MobileHomeSummaryResponse> {
  try {
    const resp = await apiClient.get<MobileHomeSummaryResponse>(`/api/v1/mobile/home/summary`, {
      params: { store_id: STORE_ID },
    });
    return resp;
  } catch {
    return getMockHomeSummary();
  }
}

export async function queryShiftSummary(date: string): Promise<ShiftSummaryResponse> {
  try {
    const resp = await apiClient.get<ShiftSummaryResponse>(`/api/v1/mobile/shifts/summary`, {
      params: { store_id: STORE_ID, date },
    });
    return resp;
  } catch {
    return getMockShiftSummary(date);
  }
}

export async function queryTaskSummary(): Promise<TaskSummaryResponse> {
  try {
    const resp = await apiClient.get<TaskSummaryResponse>(`/api/v1/mobile/tasks/summary`, {
      params: { store_id: STORE_ID },
    });
    return resp;
  } catch {
    return getMockTaskSummary();
  }
}

export async function queryTaskDetail(taskId: string): Promise<MobileTask> {
  try {
    const resp = await apiClient.get<MobileTask>(`/api/v1/mobile/tasks/${taskId}`);
    return resp;
  } catch {
    const task = getMockTaskDetail(taskId);
    if (!task) throw new Error('任务不存在');
    return task;
  }
}
