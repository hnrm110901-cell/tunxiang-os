/**
 * P0 页面 API 层 — 6 个关键页面的后端调用封装
 *
 * 所有调用带 X-Tenant-ID header，返回统一 { ok, data, error } 格式。
 * 当前为 Mock 实现，后续对接真实 BFF。
 */
import type {
  OrchestratorTaskInput, OrchestratorStep, OrchestratorResult, ToolCallRecord,
  AlertListItem, AlertDetail,
  FrontWorkbenchStats, ReservationListItem, WaitlistItem, TableThumbnail, AgentSuggestionItem,
  ReservationFullItem, ReservationDetail, ReservationForm,
  TableFullItem, TableDetail, TableEvent,
  DayCloseRecord, DayCloseStep, RevenueCheck, PaymentCheck,
  RefundDiscountCheck, InvoiceCheck, InventorySampling, HandoverCheck, DayCloseAgentExplanation,
} from '../../../shared/api-types/p0-pages';

const API_BASE = '/api/v1';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const tenantId = localStorage.getItem('tx_tenant_id') || 'default';
  const token = localStorage.getItem('tx_token') || '';

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': tenantId,
      'Authorization': `Bearer ${token}`,
      ...options?.headers,
    },
  });

  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data as T;
}

// ═══════════════════════════════════════════════════════════
// 1. 总控 Agent 工作台
// ═══════════════════════════════════════════════════════════

export const orchestratorApi = {
  /** 提交任务 */
  submitTask: (input: OrchestratorTaskInput) =>
    request<{ task_id: string }>('/agent/orchestrator/tasks', {
      method: 'POST', body: JSON.stringify(input),
    }),

  /** 获取任务状态和步骤 */
  getTaskStatus: (taskId: string) =>
    request<{ steps: OrchestratorStep[]; current_step: number }>(`/agent/orchestrator/tasks/${taskId}/status`),

  /** 获取任务结果 */
  getTaskResult: (taskId: string) =>
    request<OrchestratorResult>(`/agent/orchestrator/tasks/${taskId}/result`),

  /** 获取工具调用记录 */
  getToolCalls: (taskId: string) =>
    request<ToolCallRecord[]>(`/agent/orchestrator/tasks/${taskId}/tool-calls`),

  /** 确认待审批步骤 */
  approveStep: (taskId: string, stepId: string, remark: string) =>
    request<void>(`/agent/orchestrator/tasks/${taskId}/steps/${stepId}/approve`, {
      method: 'POST', body: JSON.stringify({ remark }),
    }),

  /** 获取任务模板 */
  getTemplates: () =>
    request<{ template_id: string; label: string; prompt: string }[]>('/agent/orchestrator/templates'),

  /** 获取最近任务 */
  getRecentTasks: (limit?: number) =>
    request<OrchestratorTaskInput[]>(`/agent/orchestrator/tasks/recent?limit=${limit || 10}`),
};

// ═══════════════════════════════════════════════════════════
// 2. 预警中心
// ═══════════════════════════════════════════════════════════

export const alertsApi = {
  /** 预警列表（支持筛选分页） */
  list: (params: {
    alert_level?: string; alert_category?: string; alert_status?: string;
    store_id?: string; page?: number; size?: number;
  }) => request<{ items: AlertListItem[]; total: number }>(
    `/alerts?${new URLSearchParams(params as Record<string, string>).toString()}`
  ),

  /** 预警详情（含 Agent 分析） */
  getDetail: (alertId: string) =>
    request<AlertDetail>(`/alerts/${alertId}`),

  /** 触发 Agent 分析 */
  requestAnalysis: (alertId: string) =>
    request<void>(`/alerts/${alertId}/analyze`, { method: 'POST' }),

  /** 指派责任人 */
  assign: (alertIds: string[], userId: string) =>
    request<void>('/alerts/batch/assign', {
      method: 'POST', body: JSON.stringify({ alert_ids: alertIds, user_id: userId }),
    }),

  /** 批量生成任务 */
  createTasks: (alertIds: string[]) =>
    request<{ task_ids: string[] }>('/alerts/batch/create-tasks', {
      method: 'POST', body: JSON.stringify({ alert_ids: alertIds }),
    }),

  /** 忽略预警 */
  ignore: (alertIds: string[], reason: string) =>
    request<void>('/alerts/batch/ignore', {
      method: 'POST', body: JSON.stringify({ alert_ids: alertIds, reason }),
    }),
};

// ═══════════════════════════════════════════════════════════
// 3. 前厅工作台
// ═══════════════════════════════════════════════════════════

export const frontWorkbenchApi = {
  /** 顶部四卡统计 */
  getStats: (storeId: string) =>
    request<FrontWorkbenchStats>(`/front/workbench/stats?store_id=${storeId}`),

  /** 今日预订列表 */
  getReservations: (storeId: string, date?: string) =>
    request<ReservationListItem[]>(`/front/workbench/reservations?store_id=${storeId}&date=${date || 'today'}`),

  /** 当前等位列表 */
  getWaitlist: (storeId: string) =>
    request<WaitlistItem[]>(`/front/workbench/waitlist?store_id=${storeId}`),

  /** 桌态缩略 */
  getTableThumbnails: (storeId: string) =>
    request<TableThumbnail[]>(`/front/workbench/tables?store_id=${storeId}`),

  /** Agent 建议 */
  getSuggestions: (storeId: string) =>
    request<AgentSuggestionItem[]>(`/front/workbench/suggestions?store_id=${storeId}`),
};

// ═══════════════════════════════════════════════════════════
// 4. 预订台账
// ═══════════════════════════════════════════════════════════

export const reservationApi = {
  /** 预订列表 */
  list: (params: {
    store_id: string; date?: string; status?: string;
    table_type?: string; source?: string; page?: number; size?: number;
  }) => request<{ items: ReservationFullItem[]; total: number }>(
    `/reservations?${new URLSearchParams(params as Record<string, string>).toString()}`
  ),

  /** 预订详情 */
  getDetail: (reservationId: string) =>
    request<ReservationDetail>(`/reservations/${reservationId}`),

  /** 新建预订 */
  create: (form: ReservationForm) =>
    request<{ reservation_id: string }>('/reservations', {
      method: 'POST', body: JSON.stringify(form),
    }),

  /** 确认预订 */
  confirm: (reservationId: string) =>
    request<void>(`/reservations/${reservationId}/confirm`, { method: 'POST' }),

  /** 改约 */
  reschedule: (reservationId: string, changes: Partial<ReservationForm>) =>
    request<void>(`/reservations/${reservationId}/reschedule`, {
      method: 'PUT', body: JSON.stringify(changes),
    }),

  /** 取消 */
  cancel: (reservationId: string, reason?: string) =>
    request<void>(`/reservations/${reservationId}/cancel`, {
      method: 'POST', body: JSON.stringify({ reason }),
    }),

  /** 安排入座 */
  seat: (reservationId: string, tableId: string) =>
    request<void>(`/reservations/${reservationId}/seat`, {
      method: 'POST', body: JSON.stringify({ table_id: tableId }),
    }),
};

// ═══════════════════════════════════════════════════════════
// 5. 桌态总览
// ═══════════════════════════════════════════════════════════

export const tableBoardApi = {
  /** 全部桌台 */
  list: (storeId: string) =>
    request<TableFullItem[]>(`/tables?store_id=${storeId}`),

  /** 桌台详情 */
  getDetail: (tableId: string) =>
    request<TableDetail>(`/tables/${tableId}`),

  /** 开台 */
  openTable: (tableId: string, partySize: number, customerId?: string) =>
    request<void>(`/tables/${tableId}/open`, {
      method: 'POST', body: JSON.stringify({ party_size: partySize, customer_id: customerId }),
    }),

  /** 并台 */
  mergeTables: (tableIds: string[]) =>
    request<void>('/tables/merge', {
      method: 'POST', body: JSON.stringify({ table_ids: tableIds }),
    }),

  /** 拆台 */
  splitTable: (tableId: string) =>
    request<void>(`/tables/${tableId}/split`, { method: 'POST' }),

  /** 最近事件 */
  getEvents: (storeId: string, limit?: number) =>
    request<TableEvent[]>(`/tables/events?store_id=${storeId}&limit=${limit || 20}`),
};

// ═══════════════════════════════════════════════════════════
// 6. 日清日结
// ═══════════════════════════════════════════════════════════

export const dayCloseApi = {
  /** 获取日结记录 */
  get: (storeId: string, businessDate: string) =>
    request<DayCloseRecord>(`/day-close?store_id=${storeId}&date=${businessDate}`),

  /** 获取步骤列表 */
  getSteps: (closeId: string) =>
    request<DayCloseStep[]>(`/day-close/${closeId}/steps`),

  /** 获取营收核对数据 */
  getRevenueCheck: (closeId: string) =>
    request<RevenueCheck>(`/day-close/${closeId}/revenue`),

  /** 获取支付核对数据 */
  getPaymentCheck: (closeId: string) =>
    request<PaymentCheck>(`/day-close/${closeId}/payment`),

  /** 获取退款核对数据 */
  getRefundCheck: (closeId: string) =>
    request<RefundDiscountCheck>(`/day-close/${closeId}/refund`),

  /** 获取发票核对数据 */
  getInvoiceCheck: (closeId: string) =>
    request<InvoiceCheck>(`/day-close/${closeId}/invoice`),

  /** 获取库存抽检数据 */
  getInventorySampling: (closeId: string) =>
    request<InventorySampling>(`/day-close/${closeId}/inventory`),

  /** 获取交班数据 */
  getHandoverCheck: (closeId: string) =>
    request<HandoverCheck>(`/day-close/${closeId}/handover`),

  /** 保存步骤 */
  saveStep: (closeId: string, stepCode: string, data: Record<string, any>) =>
    request<void>(`/day-close/${closeId}/steps/${stepCode}`, {
      method: 'PUT', body: JSON.stringify(data),
    }),

  /** 完成步骤 */
  completeStep: (closeId: string, stepCode: string) =>
    request<void>(`/day-close/${closeId}/steps/${stepCode}/complete`, { method: 'POST' }),

  /** 店长签核 */
  signoff: (closeId: string, remark?: string) =>
    request<void>(`/day-close/${closeId}/signoff`, {
      method: 'POST', body: JSON.stringify({ remark }),
    }),

  /** Agent 解释 */
  getAgentExplanation: (closeId: string) =>
    request<DayCloseAgentExplanation>(`/day-close/${closeId}/agent-explanation`),

  /** 生成整改任务 */
  createRectification: (closeId: string) =>
    request<{ task_id: string }>(`/day-close/${closeId}/create-rectification`, { method: 'POST' }),
};
