/**
 * 借调管理 API 客户端
 * 域F · 组织人事 · 借调+工时拆分+成本分摊
 */
import { txFetchData } from './index';

// ─── Types ──────────────────────────────────────────────

export interface TransferOrder {
  id: string;
  employee_id: string;
  employee_name: string;
  from_store_id: string;
  from_store_name: string;
  to_store_id: string;
  to_store_name: string;
  transfer_type: string;
  start_date: string;
  end_date: string;
  status: 'pending' | 'approved' | 'active' | 'completed' | 'cancelled';
  reason: string;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
}

export interface TransferListResult {
  items: TransferOrder[];
  total: number;
}

export interface CostAllocationDetail {
  store_id: string;
  hours: number;
  ratio: number;
  wage_fen: number;
  social_fen: number;
  bonus_fen: number;
  total_fen: number;
}

export interface DetailReport {
  employee_id: string;
  employee_name?: string;
  total_hours: number;
  total_cost_fen: number;
  stores: CostAllocationDetail[];
}

export interface StoreSummary {
  employee_count: number;
  total_wage_fen: number;
  total_social_fen: number;
  total_bonus_fen: number;
  grand_total_fen: number;
}

export interface SummaryReport {
  stores: Record<string, StoreSummary>;
  grand_total_fen: number;
}

export interface StoreAnalysis {
  actual_fen: number;
  budget_fen: number;
  variance_fen: number;
  variance_rate: number;
  last_period_fen: number;
  mom_change_fen: number;
  mom_rate: number;
}

export interface AnalysisReport {
  stores: Record<string, StoreAnalysis>;
  total_actual_fen: number;
  total_budget_fen: number;
  total_variance_fen: number;
}

export interface CostReportResult {
  month: string;
  store_id: string;
  detail: DetailReport[];
  summary: SummaryReport;
  analysis: AnalysisReport;
}

// ─── API Calls ──────────────────────────────────────────

export async function fetchTransfers(params: {
  store_id?: string;
  employee_id?: string;
  status?: string;
  page?: number;
  size?: number;
}): Promise<TransferListResult> {
  const query = new URLSearchParams();
  if (params.store_id) query.set('store_id', params.store_id);
  if (params.employee_id) query.set('employee_id', params.employee_id);
  if (params.status) query.set('status', params.status);
  if (params.page) query.set('page', String(params.page));
  if (params.size) query.set('size', String(params.size));
  return txFetchData<TransferListResult>(`/api/v1/transfers?${query.toString()}`);
}

export async function fetchTransferDetail(id: string): Promise<TransferOrder> {
  return txFetchData<TransferOrder>(`/api/v1/transfers/${id}`);
}

export async function createTransfer(data: {
  employee_id: string;
  employee_name: string;
  from_store_id: string;
  from_store_name: string;
  to_store_id: string;
  to_store_name: string;
  start_date: string;
  end_date: string;
  transfer_type?: string;
  reason?: string;
}): Promise<TransferOrder> {
  return txFetchData<TransferOrder>('/api/v1/transfers', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function approveTransfer(id: string, approverId: string): Promise<TransferOrder> {
  return txFetchData<TransferOrder>(`/api/v1/transfers/${id}/approve`, {
    method: 'PUT',
    body: JSON.stringify({ approver_id: approverId }),
  });
}

export async function completeTransfer(id: string): Promise<TransferOrder> {
  return txFetchData<TransferOrder>(`/api/v1/transfers/${id}/complete`, {
    method: 'PUT',
  });
}

export async function cancelTransfer(id: string): Promise<TransferOrder> {
  return txFetchData<TransferOrder>(`/api/v1/transfers/${id}/cancel`, {
    method: 'PUT',
  });
}

export async function computeAllocation(data: {
  employee_id: string;
  month: string;
  salary_data: {
    base_fen: number;
    overtime_fen: number;
    social_fen: number;
    bonus_fen: number;
  };
}): Promise<{ time_split: Record<string, Record<string, number>>; cost_split: Record<string, unknown>; allocations_saved: number }> {
  return txFetchData(`/api/v1/transfers/compute-allocation`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function fetchCostReport(
  storeId: string,
  month: string,
): Promise<CostReportResult> {
  return txFetchData<CostReportResult>(
    `/api/v1/transfers/cost-report?store_id=${encodeURIComponent(storeId)}&month=${encodeURIComponent(month)}`,
  );
}
