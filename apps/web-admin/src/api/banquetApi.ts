/**
 * 宴会管理 API -- /api/v1/banquets/*
 * 销售漏斗、宴会列表、宴会详情、线索创建、阶段推进
 *
 * 后端路由前缀：/api/v1/banquets（banquet_routes.py）
 * txFetch 会自动注入 X-Tenant-ID header
 */
import { txFetch } from './index';

// ─── 类型定义 ───

export interface BanquetFunnelStage {
  stage: 'lead' | 'quote' | 'signed' | 'executing' | 'completed';
  label: string;
  count: number;
  conversion_rate: number; // 相对上一阶段的转化率（首阶段为100%）
}

export interface BanquetFunnelData {
  stages: BanquetFunnelStage[];
  total_leads: number;
  overall_conversion: number; // 线索→完成 总转化率
}

export type BanquetStage =
  | 'lead'
  | 'quote'
  | 'signed'
  | 'executing'
  | 'completed'
  | 'cancelled';

export interface BanquetListItem {
  contract_id: string;
  customer_name: string;
  customer_phone: string;
  company_name?: string;
  banquet_date: string;
  event_type?: string;        // 婚宴/寿宴/商务宴/生日宴/其他
  table_count: number;
  guest_count?: number;
  total_amount_fen: number;
  budget_fen?: number;
  stage: BanquetStage;
  store_id?: string;
  store_name?: string;
  source?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface BanquetListFilters {
  store_id?: string;
  stage?: string;
  date_from?: string;
  date_to?: string;
  keyword?: string;
  page?: number;
  size?: number;
}

export interface BanquetDetail {
  contract_id: string;
  customer_name: string;
  customer_phone: string;
  company_name?: string;
  banquet_date: string;
  event_type: string;
  table_count: number;
  guest_count?: number;
  guests_per_table?: number;
  menu_name?: string;
  per_table_price_fen?: number;
  total_amount_fen: number;
  budget_fen?: number;
  deposit_fen?: number;
  paid_fen?: number;
  stage: BanquetStage;
  store_id: string;
  store_name?: string;
  source?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
  timeline?: Array<{
    time: string;
    stage: string;
    label: string;
    operator?: string;
    note?: string;
  }>;
}

export interface BanquetKPIs {
  month_banquet_count: number;
  sign_rate: number;           // 签约率 0~1
  avg_per_table_fen: number;
  month_revenue_fen: number;
}

export interface CreateLeadPayload {
  customer_name: string;
  company_name?: string;
  phone: string;
  event_type: string;
  event_date: string;
  guest_count: number;
  estimated_budget_fen: number;
  source: string;
  notes?: string;
}

// ─── API 函数 ───

/** 获取宴会销售漏斗 */
export async function fetchBanquetFunnel(
  storeId?: string,
): Promise<BanquetFunnelData> {
  const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetch(`/api/v1/banquet/funnel${query}`);
}

/** 获取宴会列表（分页 + 筛选） */
export async function fetchBanquetList(
  filters: BanquetListFilters = {},
): Promise<{ items: BanquetListItem[]; total: number }> {
  const params = new URLSearchParams();
  if (filters.store_id) params.set('store_id', filters.store_id);
  if (filters.stage) params.set('stage', filters.stage);
  if (filters.date_from) params.set('date_from', filters.date_from);
  if (filters.date_to) params.set('date_to', filters.date_to);
  if (filters.keyword) params.set('keyword', filters.keyword);
  params.set('page', String(filters.page || 1));
  params.set('size', String(filters.size || 20));
  return txFetch(`/api/v1/banquet/list?${params.toString()}`);
}

/** 获取宴会详情（含时间轴） */
export async function fetchBanquetDetail(
  contractId: string,
): Promise<BanquetDetail> {
  return txFetch(
    `/api/v1/banquets/contracts/${encodeURIComponent(contractId)}`,
  );
}

/** 获取宴会关键 KPI（本月） */
export async function fetchBanquetKPIs(
  storeId?: string,
): Promise<BanquetKPIs> {
  const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetch(`/api/v1/banquet/kpis${query}`);
}

/** 创建新宴会线索 — POST /api/v1/banquets/leads */
export async function createBanquetLead(
  payload: CreateLeadPayload,
): Promise<{ lead_id: string; contract_id: string }> {
  return txFetch('/api/v1/banquets/leads', {
    method: 'POST',
    body: JSON.stringify({
      customer_name: payload.customer_name,
      company_name: payload.company_name || '',
      phone: payload.phone,
      event_type: payload.event_type,
      event_date: payload.event_date,
      guest_count: payload.guest_count,
      estimated_budget_fen: payload.estimated_budget_fen,
      source: payload.source,
      notes: payload.notes || '',
    }),
  });
}

/** 推进宴会阶段 — PUT /api/v1/banquets/leads/{lead_id}/stage */
export async function advanceBanquetStage(
  leadId: string,
  targetStage: string,
): Promise<{ lead_id: string; stage: string }> {
  return txFetch(
    `/api/v1/banquets/leads/${encodeURIComponent(leadId)}/stage?target_stage=${encodeURIComponent(targetStage)}`,
    { method: 'PUT' },
  );
}
