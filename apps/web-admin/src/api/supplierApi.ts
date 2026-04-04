/**
 * 供应商门户 API -- /api/v1/suppliers/*
 * 供应商档案、询价管理(RFQ)、风险评估
 *
 * txFetch 会自动注入 X-Tenant-ID header
 * 响应格式：{ ok: boolean, data: T | null, error: {...} | null }
 */
import { txFetch } from './index';

// ─── 供应商档案 ────────────────────────────────────────────────────────────────

export type SupplierCategory =
  | 'seafood'
  | 'meat'
  | 'vegetable'
  | 'seasoning'
  | 'frozen'
  | 'dry_goods'
  | 'beverage'
  | 'other';

export type SupplierStatus = 'active' | 'inactive' | 'suspended';

export type PaymentTerm = 'net30' | 'net60' | 'cod';

export interface SupplierListItem {
  id: string;
  name: string;
  category: SupplierCategory;
  contact_name?: string;
  contact_phone?: string;
  address?: string;
  status: SupplierStatus;
  rating: number;          // 综合评分 0-5
  order_count: number;
  qualifications?: string[];
  payment_term?: PaymentTerm;
  created_at: string;
  updated_at: string;
}

export interface SupplierDetail extends SupplierListItem {
  delivery_rate: number;       // 交付率 0-1
  quality_pass_rate: number;   // 质量通过率 0-1
  active_contract_count: number;
  notes?: string;
}

export interface SupplierListFilters {
  category?: string;
  status?: string;
  rating_min?: number;
  page?: number;
  size?: number;
}

export interface CreateSupplierPayload {
  name: string;
  category: SupplierCategory;
  contact_name?: string;
  contact_phone?: string;
  address?: string;
  qualifications?: string[];
  payment_term?: PaymentTerm;
}

// ─── 询价管理 (RFQ) ──────────────────────────────────────────────────────────

export type RFQStatus = 'open' | 'quoted' | 'accepted' | 'expired';

export interface RFQListItem {
  rfq_id: string;
  item_name: string;
  quantity: number;
  unit: string;
  expected_delivery_date?: string;
  supplier_ids: string[];
  status: RFQStatus;
  created_at: string;
  updated_at: string;
}

export interface RFQQuoteItem {
  supplier_id: string;
  supplier_name: string;
  supplier_rating: number;
  unit_price_fen: number;
  total_price_fen: number;
  delivery_days: number;
  is_recommended: boolean;
  recommendation_reason?: string;
}

export interface RFQCompareResult {
  rfq_id: string;
  item_name: string;
  quantity: number;
  unit: string;
  quotes: RFQQuoteItem[];
}

export interface CreateRFQPayload {
  item_name: string;
  quantity: number;
  unit: string;
  expected_delivery_date?: string;
  supplier_ids: string[];
}

// ─── 风险评估 ─────────────────────────────────────────────────────────────────

export type RiskLevel = 'low' | 'medium' | 'high';

export interface SupplierRiskItem {
  supplier_id: string;
  supplier_name: string;
  risk_level: RiskLevel;
  risk_score: number;   // 0-100
  risk_factors: string[];
  mitigation_suggestions: string[];
  last_assessed_at: string;
}

export interface RiskAssessmentResult {
  assessed_at: string;
  overall_risk_level: RiskLevel;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
  items: SupplierRiskItem[];
  global_suggestions: string[];
}

// ─── API 函数 ─────────────────────────────────────────────────────────────────

/** 获取供应商列表 */
export async function fetchSupplierList(
  filters: SupplierListFilters = {},
): Promise<{ items: SupplierListItem[]; total: number }> {
  const params = new URLSearchParams();
  if (filters.category) params.set('category', filters.category);
  if (filters.status) params.set('status', filters.status);
  if (filters.rating_min != null) params.set('rating_min', String(filters.rating_min));
  params.set('page', String(filters.page || 1));
  params.set('size', String(filters.size || 20));
  const res = await txFetch<{ items: SupplierListItem[]; total: number }>(
    `/api/v1/suppliers?${params.toString()}`,
  );
  return res.data ?? { items: [], total: 0 };
}

/** 创建供应商 */
export async function createSupplier(
  payload: CreateSupplierPayload,
): Promise<{ id: string }> {
  const res = await txFetch<{ id: string }>('/api/v1/suppliers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return res.data ?? { id: '' };
}

/** 获取供应商详情 */
export async function fetchSupplierDetail(id: string): Promise<SupplierDetail> {
  const res = await txFetch<SupplierDetail>(`/api/v1/suppliers/${encodeURIComponent(id)}`);
  if (!res.data) throw new Error('供应商详情为空');
  return res.data;
}

/** 获取询价列表 */
export async function fetchRFQList(
  params: { page?: number; size?: number } = {},
): Promise<{ items: RFQListItem[]; total: number }> {
  const qs = new URLSearchParams();
  qs.set('page', String(params.page || 1));
  qs.set('size', String(params.size || 20));
  const res = await txFetch<{ items: RFQListItem[]; total: number }>(
    `/api/v1/suppliers/rfq?${qs.toString()}`,
  );
  return res.data ?? { items: [], total: 0 };
}

/** 发起询价 */
export async function createRFQ(
  payload: CreateRFQPayload,
): Promise<{ rfq_id: string }> {
  const res = await txFetch<{ rfq_id: string }>('/api/v1/suppliers/rfq', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return res.data ?? { rfq_id: '' };
}

/** 获取比价结果 */
export async function fetchRFQCompare(rfqId: string): Promise<RFQCompareResult> {
  const res = await txFetch<RFQCompareResult>(
    `/api/v1/suppliers/rfq/${encodeURIComponent(rfqId)}/compare`,
  );
  if (!res.data) throw new Error('比价结果为空');
  return res.data;
}

/** 接受报价 */
export async function acceptRFQQuote(
  rfqId: string,
  supplierId: string,
): Promise<void> {
  await txFetch(`/api/v1/suppliers/rfq/${encodeURIComponent(rfqId)}/accept`, {
    method: 'POST',
    body: JSON.stringify({ supplier_id: supplierId }),
  });
}

/** 获取供应链风险评估 */
export async function fetchRiskAssessment(): Promise<RiskAssessmentResult> {
  const res = await txFetch<RiskAssessmentResult>('/api/v1/suppliers/risk-assessment');
  if (!res.data) throw new Error('风险评估数据为空');
  return res.data;
}
