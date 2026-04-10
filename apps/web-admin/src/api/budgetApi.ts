/**
 * 预算管理 API — 对接 tx-finance budget_v2_routes.py + budget_routes.py
 *
 * budget_v2_routes.py 提供前端友好的快捷接口（prefix=/api/v1/finance/budget）：
 *   GET  /api/v1/finance/budget              — 年度月度预算列表
 *   POST /api/v1/finance/budget              — 创建/更新月度预算
 *   GET  /api/v1/finance/budget/execution    — 月度预算执行情况
 *
 * budget_routes.py 提供完整 CRUD（prefix=/api/v1/finance/budgets）：
 *   POST /api/v1/finance/budgets             — 创建/更新预算计划（UPSERT）
 *   GET  /api/v1/finance/budgets             — 预算计划列表
 *   GET  /api/v1/finance/budgets/{id}        — 预算计划详情
 *   POST /api/v1/finance/budgets/{id}/approve — 审批预算计划
 */
import { txFetchData } from './client';

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

/** 月度预算计划 */
export interface MonthlyBudget {
  period: string;                    // YYYY-MM
  revenue_target_fen: number | null;
  cost_budget_fen: number | null;
  labor_budget_fen: number | null;
  status: string | null;
}

/** 预算执行情况响应 */
export interface BudgetExecution {
  store_id: string;
  period: string;
  has_budget: boolean;
  budget: {
    revenue_target_fen: number;
    cost_budget_fen: number;
    labor_budget_fen: number;
  };
  actual: {
    revenue_fen: number;
    food_cost_fen: number;
    labor_cost_fen: number;
  };
  variance: {
    revenue_fen: number;
    cost_fen: number;
    labor_fen: number;
    revenue_over_budget: boolean;
    cost_over_budget: boolean;
    labor_over_budget: boolean;
  };
  execution_rate: number;
  execution_status: 'on_track' | 'below_target' | 'critical';
  _is_mock?: boolean;
}

/** 创建月度预算请求体 */
export interface CreateMonthlyBudgetBody {
  store_id: string;
  year: number;
  month: number;
  revenue_target_fen: number;
  cost_budget_fen: number;
  labor_budget_fen: number;
  note?: string;
}

/** budget_routes.py UPSERT 请求体 */
export interface UpsertBudgetBody {
  store_id: string;
  period_type: 'monthly' | 'quarterly' | 'yearly';
  period: string;
  category: 'revenue' | 'ingredient_cost' | 'labor_cost' | 'fixed_cost' | 'marketing_cost' | 'total';
  budget_fen: number;
  note?: string;
  created_by?: string;
}

/** 预算计划列表项 */
export interface BudgetPlanItem {
  id: string;
  store_id: string;
  store_name?: string;
  period_type: string;
  period: string;
  category: string;
  budget_fen: number;
  note: string | null;
  status: string;
  created_at: string;
}

// ─── API 函数 ──────────────────────────────────────────────────────────────────

/**
 * 获取门店年度月度预算列表（12 个月）
 * GET /api/v1/finance/budget?store_id=&year=
 */
export async function listAnnualBudgets(params: {
  storeId: string;
  year: number;
}): Promise<{ store_id: string; year: number; items: MonthlyBudget[]; total: number }> {
  const { storeId, year } = params;
  return txFetchData(
    `/api/v1/finance/budget?store_id=${encodeURIComponent(storeId)}&year=${year}`,
  );
}

/**
 * 创建或更新月度预算（三科目：营收目标/食材成本/人力成本）
 * POST /api/v1/finance/budget
 */
export async function createOrUpdateMonthlyBudget(body: CreateMonthlyBudgetBody): Promise<{
  store_id: string;
  period: string;
  revenue_target_fen: number;
  cost_budget_fen: number;
  labor_budget_fen: number;
}> {
  return txFetchData('/api/v1/finance/budget', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * 查询月度预算执行情况（预算 vs 实际）
 * GET /api/v1/finance/budget/execution?store_id=&year=&month=
 */
export async function getBudgetExecution(params: {
  storeId: string;
  year: number;
  month: number;
}): Promise<BudgetExecution> {
  const { storeId, year, month } = params;
  return txFetchData(
    `/api/v1/finance/budget/execution?store_id=${encodeURIComponent(storeId)}&year=${year}&month=${month}`,
  );
}

/**
 * 创建/更新预算计划（完整 CRUD，支持多科目）
 * POST /api/v1/finance/budgets
 */
export async function upsertBudgetPlan(body: UpsertBudgetBody): Promise<BudgetPlanItem> {
  return txFetchData('/api/v1/finance/budgets', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * 获取预算计划列表
 * GET /api/v1/finance/budgets?store_id=&period_type=&period=
 */
export async function listBudgetPlans(params: {
  storeId: string;
  periodType?: string;
  period?: string;
  page?: number;
  size?: number;
}): Promise<{ items: BudgetPlanItem[]; total: number }> {
  const { storeId, periodType, period, page = 1, size = 50 } = params;
  let url = `/api/v1/finance/budgets?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`;
  if (periodType) url += `&period_type=${encodeURIComponent(periodType)}`;
  if (period) url += `&period=${encodeURIComponent(period)}`;
  return txFetchData(url);
}

/**
 * 审批预算计划
 * POST /api/v1/finance/budgets/{id}/approve
 */
export async function approveBudgetPlan(id: string, approvedBy: string): Promise<{ ok: boolean }> {
  return txFetchData(`/api/v1/finance/budgets/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

// ─── 工具：执行状态标签 ────────────────────────────────────────────────────────

export const EXECUTION_STATUS_LABEL: Record<string, string> = {
  on_track: '正常执行',
  below_target: '低于目标',
  critical: '严重偏差',
};

export const EXECUTION_STATUS_COLOR: Record<string, string> = {
  on_track: 'success',
  below_target: 'warning',
  critical: 'error',
};
