/**
 * 日清日结 API — /api/v1/daily-ops/*
 * E1~E8 日清流程节点状态、巡航检查项确认
 */
import { txFetch } from './index';

// ─── 类型 ───

export type NodeStatus = 'pending' | 'in_progress' | 'completed';

export interface CheckItem {
  check_id: string;
  label: string;
  done: boolean;
  completed_by: string | null;
  completed_at: string | null;
}

export interface CruiseNode {
  code: string;
  name: string;
  status: NodeStatus;
  checks: CheckItem[];
}

export interface DailyOpsFlow {
  date: string;
  store_id: string;
  nodes: CruiseNode[];
  progress_percent: number;
  open_time: string | null;
  close_time: string | null;
}

// ─── 接口 ───

/** 获取当日日清日结流程状态 */
export async function fetchDailyOpsFlow(
  storeId: string,
  date?: string,
): Promise<DailyOpsFlow> {
  const dateParam = date ? `&date=${encodeURIComponent(date)}` : '';
  return txFetch(`/api/v1/daily-ops/flow?store_id=${encodeURIComponent(storeId)}${dateParam}`);
}

/** 确认单个检查项 */
export async function confirmCheck(
  storeId: string,
  nodeCode: string,
  checkId: string,
  employeeId: string,
): Promise<{ check_id: string; done: boolean; completed_at: string }> {
  return txFetch('/api/v1/daily-ops/confirm', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      node_code: nodeCode,
      check_id: checkId,
      employee_id: employeeId,
    }),
  });
}

/** 完成当前节点，推进到下一节点 */
export async function advanceNode(
  storeId: string,
  nodeCode: string,
): Promise<{ node_code: string; status: NodeStatus; next_node: string | null }> {
  return txFetch('/api/v1/daily-ops/advance', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, node_code: nodeCode }),
  });
}

/** 查询日清日结历史 */
export async function fetchDailyOpsHistory(
  storeId: string,
  page = 1,
  size = 20,
): Promise<{ items: DailyOpsFlow[]; total: number }> {
  return txFetch(
    `/api/v1/daily-ops/history?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`,
  );
}
