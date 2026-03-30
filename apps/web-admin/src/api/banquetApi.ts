/**
 * 宴会管理 API -- /api/v1/banquet/*
 * 销售漏斗、宴会列表、宴会详情
 */
import { txFetch } from './index';

// ─── 类型 ───

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

export interface BanquetListItem {
  contract_id: string;
  customer_name: string;
  customer_phone: string;
  banquet_date: string;
  table_count: number;
  total_amount_fen: number;
  stage: 'lead' | 'quote' | 'signed' | 'executing' | 'completed' | 'cancelled';
  store_name: string;
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
  banquet_date: string;
  banquet_type: string; // 婚宴/寿宴/商务宴/其他
  table_count: number;
  guests_per_table: number;
  menu_name: string;
  per_table_price_fen: number;
  total_amount_fen: number;
  deposit_fen: number;
  paid_fen: number;
  stage: string;
  store_id: string;
  store_name: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface BanquetKPIs {
  month_banquet_count: number;
  sign_rate: number; // 签约率 0-1
  avg_per_table_fen: number;
  month_revenue_fen: number;
}

// ─── 接口 ───

/** 获取宴会销售漏斗 */
export async function fetchBanquetFunnel(
  storeId?: string,
): Promise<BanquetFunnelData> {
  const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetch(`/api/v1/banquet/funnel${query}`);
}

/** 获取宴会列表 */
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

/** 获取宴会详情 */
export async function fetchBanquetDetail(
  contractId: string,
): Promise<BanquetDetail> {
  return txFetch(`/api/v1/banquet/detail?contract_id=${encodeURIComponent(contractId)}`);
}

/** 获取宴会关键 KPI */
export async function fetchBanquetKPIs(
  storeId?: string,
): Promise<BanquetKPIs> {
  const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetch(`/api/v1/banquet/kpis${query}`);
}
