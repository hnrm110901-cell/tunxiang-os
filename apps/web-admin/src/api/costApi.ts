/**
 * 成本管理 API — 对接 tx-finance cost_routes_v2.py
 *
 * 实际端点（prefix=/api/v1/finance）：
 *   POST /api/v1/finance/costs              — 录入成本记录
 *   GET  /api/v1/finance/costs              — 查询成本明细（?store_id=&date=）
 *   GET  /api/v1/finance/costs/summary      — 成本结构汇总（饼图数据）
 *   POST /api/v1/finance/configs            — 设置财务配置
 *   GET  /api/v1/finance/configs/{store_id} — 查询门店财务配置
 */
import { txFetchData } from './client';

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

/** 成本类型枚举 */
export type CostType =
  | 'purchase'
  | 'wastage'
  | 'live_seafood_death'
  | 'labor'
  | 'rent'
  | 'utilities'
  | 'other';

/** 单条成本明细 */
export interface CostItem {
  id: string;
  cost_date: string;
  cost_type: CostType;
  description: string | null;
  amount_fen: number;
  quantity: number | null;
  unit: string | null;
  unit_cost_fen: number | null;
  reference_id: string | null;
  created_at: string;
}

/** 成本结构汇总（饼图数据）中的单个分类 */
export interface CostBreakdownItem {
  cost_type: CostType;
  amount_fen: number;
  ratio: number;
}

/** 成本结构汇总响应 */
export interface CostSummary {
  store_id: string;
  start_date: string;
  end_date: string;
  total_cost_fen: number;
  breakdown: CostBreakdownItem[];
}

/** 财务配置项 */
export interface FinanceConfigItem {
  id: string;
  config_type: string;
  value_fen: number | null;
  value_pct: number | null;
  effective_from: string | null;
  effective_until: string | null;
  scope: 'store' | 'tenant';
}

/** 门店财务配置响应 */
export interface StoreFinanceConfigs {
  store_id: string;
  as_of_date: string;
  configs: FinanceConfigItem[];
}

/** 录入成本记录请求体 */
export interface CreateCostItemBody {
  store_id: string;
  cost_date: string;
  cost_type: CostType;
  description?: string;
  amount_fen: number;
  quantity?: number;
  unit?: string;
  unit_cost_fen?: number;
  reference_id?: string;
}

/** 设置财务配置请求体 */
export interface SetFinanceConfigBody {
  store_id?: string;
  config_type: string;
  value_fen?: number;
  value_pct?: number;
  effective_from?: string;
  effective_until?: string;
}

// ─── API 函数 ──────────────────────────────────────────────────────────────────

/**
 * 录入成本记录（手工录入房租/水电/损耗等）
 * POST /api/v1/finance/costs
 */
export async function createCostItem(body: CreateCostItemBody): Promise<{ id: string }> {
  const res = await txFetchData<{ id: string }>('/api/v1/finance/costs', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return res;
}

/**
 * 查询成本明细列表
 * GET /api/v1/finance/costs?store_id=&date=&cost_type=&page=&size=
 */
export async function getCostItems(params: {
  storeId: string;
  date?: string;
  costType?: CostType;
  page?: number;
  size?: number;
}): Promise<{ items: CostItem[]; total: number; page: number; size: number }> {
  const { storeId, date = 'today', costType, page = 1, size = 20 } = params;
  let url = `/api/v1/finance/costs?store_id=${encodeURIComponent(storeId)}&date=${encodeURIComponent(date)}&page=${page}&size=${size}`;
  if (costType) url += `&cost_type=${encodeURIComponent(costType)}`;
  return txFetchData(url);
}

/**
 * 成本结构汇总（用于饼图/成本占比分析）
 * GET /api/v1/finance/costs/summary?store_id=&start_date=&end_date=
 */
export async function getCostSummary(params: {
  storeId: string;
  startDate: string;
  endDate: string;
}): Promise<CostSummary> {
  const { storeId, startDate, endDate } = params;
  const url = `/api/v1/finance/costs/summary?store_id=${encodeURIComponent(storeId)}&start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;
  return txFetchData(url);
}

/**
 * 设置门店财务配置（成本比例/月租/水电等）
 * POST /api/v1/finance/configs
 */
export async function setFinanceConfig(body: SetFinanceConfigBody): Promise<{ id: string }> {
  return txFetchData('/api/v1/finance/configs', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * 查询门店财务配置
 * GET /api/v1/finance/configs/{store_id}?date=
 */
export async function getStoreFinanceConfigs(
  storeId: string,
  date?: string,
): Promise<StoreFinanceConfigs> {
  let url = `/api/v1/finance/configs/${encodeURIComponent(storeId)}`;
  if (date) url += `?date=${encodeURIComponent(date)}`;
  return txFetchData(url);
}

// ─── 工具：成本类型标签 ────────────────────────────────────────────────────────

export const COST_TYPE_LABEL: Record<CostType, string> = {
  purchase: '食材采购',
  wastage: '食材损耗',
  live_seafood_death: '活鲜死亡',
  labor: '人力成本',
  rent: '房租',
  utilities: '水电费',
  other: '其他',
};

export const COST_TYPE_COLOR: Record<CostType, string> = {
  purchase: '#FF6B35',
  wastage: '#BA7517',
  live_seafood_death: '#A32D2D',
  labor: '#185FA5',
  rent: '#0F6E56',
  utilities: '#9B8000',
  other: '#5F5E5A',
};
