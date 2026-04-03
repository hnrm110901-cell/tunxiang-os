/**
 * KDS 催菜 API — /api/v1/kds/*
 * 服务员端查看出餐状态、催菜
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface KdsTask {
  task_id: string;
  order_id: string;
  table_no: string;
  dish_name: string;
  quantity: number;
  spec: string;
  status: 'pending' | 'cooking' | 'done';
  created_at: string;
  started_at: string | null;
  rush_count: number;
  is_overtime: boolean;
}

// ─── 接口 ───

/** 查询指定订单的 KDS 任务列表 */
export async function fetchKdsTasks(
  storeId: string,
  orderId: string,
): Promise<{ items: KdsTask[] }> {
  return txFetch(
    `/api/v1/kds/tasks?store_id=${encodeURIComponent(storeId)}&order_id=${encodeURIComponent(orderId)}`,
  );
}

/** 催菜 */
export async function rushKdsTask(
  taskId: string,
): Promise<{ task_id: string; rushed: boolean }> {
  return txFetch(`/api/v1/kds/tasks/${encodeURIComponent(taskId)}/rush`, {
    method: 'POST',
  });
}

/** 查询指定桌台所有出餐进度 */
export async function fetchTableCookProgress(
  storeId: string,
  tableNo: string,
): Promise<{ items: KdsTask[]; total_dishes: number; completed_dishes: number }> {
  return txFetch(
    `/api/v1/kds/progress?store_id=${encodeURIComponent(storeId)}&table_no=${encodeURIComponent(tableNo)}`,
  );
}
