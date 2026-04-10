/**
 * 押金管理 API 客户端
 * 覆盖后端 /api/v1/deposits/* 所有端点
 */
import { txFetchData } from './client';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

export type DepositStatus =
  | 'collected'
  | 'partially_applied'
  | 'fully_applied'
  | 'refunded'
  | 'converted'
  | 'written_off';

export interface DepositRecord {
  id: string;
  store_id: string;
  customer_id: string | null;
  reservation_id: string | null;
  order_id: string | null;
  amount_fen: number;
  applied_amount_fen: number;
  refunded_amount_fen: number;
  remaining_fen: number;
  status: DepositStatus;
  payment_method: string;
  payment_ref: string | null;
  collected_at: string;
  expires_at: string | null;
  operator_id: string;
  remark: string | null;
}

export interface DepositLedgerItem {
  store_id: string;
  start_date: string;
  end_date: string;
  total_count: number;
  total_collected_fen: number;
  total_applied_fen: number;
  total_refunded_fen: number;
  total_converted_fen: number;
  total_outstanding_fen: number;
}

export interface DepositAgingBucket {
  count: number;
  amount_fen: number;
}

export interface DepositAgingItem {
  store_id: string;
  aging: {
    '0_7_days': DepositAgingBucket;
    '8_30_days': DepositAgingBucket;
    '31_90_days': DepositAgingBucket;
    'over_90_days': DepositAgingBucket;
  };
}

export interface DepositListResponse {
  items: DepositRecord[];
  total: number;
  page: number;
  size: number;
}

export interface DepositCreateReq {
  store_id: string;
  customer_id?: string;
  reservation_id?: string;
  order_id?: string;
  amount_fen: number;
  payment_method: string;
  payment_ref?: string;
  expires_days?: number;
  remark?: string;
}

export interface DepositActionResult {
  deposit_id: string;
  status: DepositStatus;
  amount_fen: number;
  applied_amount_fen: number;
  refunded_amount_fen: number;
  remaining_fen: number;
}

// ─── API 函数 ────────────────────────────────────────────────────────────────

/** 获取门店押金列表 */
export async function listDepositsByStore(
  storeId: string,
  params?: { status?: string; page?: number; size?: number },
): Promise<DepositListResponse> {
  const q = new URLSearchParams();
  if (params?.status) q.set('status', params.status);
  if (params?.page) q.set('page', String(params.page));
  if (params?.size) q.set('size', String(params.size));
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData<DepositListResponse>(
    `/api/v1/deposits/store/${encodeURIComponent(storeId)}${qs}`,
  );
}

/** 退还押金 */
export async function refundDeposit(
  id: string,
  refundAmountFen: number,
  remark?: string,
): Promise<DepositActionResult> {
  return txFetchData<DepositActionResult>(
    `/api/v1/deposits/${encodeURIComponent(id)}/refund`,
    {
      method: 'POST',
      body: JSON.stringify({ refund_amount_fen: refundAmountFen, remark }),
    },
  );
}

/** 押金转收入 */
export async function convertDeposit(
  id: string,
  remark?: string,
): Promise<{ deposit_id: string; status: DepositStatus; converted_amount_fen: number }> {
  return txFetchData(
    `/api/v1/deposits/${encodeURIComponent(id)}/convert`,
    {
      method: 'POST',
      body: JSON.stringify({ remark }),
    },
  );
}

/** 押金抵扣消费 */
export async function applyDeposit(
  id: string,
  orderId: string,
  applyAmountFen: number,
  remark?: string,
): Promise<DepositActionResult> {
  return txFetchData<DepositActionResult>(
    `/api/v1/deposits/${encodeURIComponent(id)}/apply`,
    {
      method: 'POST',
      body: JSON.stringify({ order_id: orderId, apply_amount_fen: applyAmountFen, remark }),
    },
  );
}

/** 收取押金（新建记录） */
export async function collectDeposit(
  req: DepositCreateReq,
): Promise<{ deposit_id: string; status: string; amount_fen: number; expires_at: string | null; collected_at: string | null }> {
  return txFetchData('/api/v1/deposits/', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/** 获取押金台账报表 */
export async function getDepositLedger(
  storeId: string,
  startDate: string,
  endDate: string,
): Promise<DepositLedgerItem> {
  return txFetchData<DepositLedgerItem>(
    `/api/v1/deposits/report/ledger?store_id=${encodeURIComponent(storeId)}&start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`,
  );
}

/** 获取押金账龄分析 */
export async function getDepositAging(storeId: string): Promise<DepositAgingItem> {
  return txFetchData<DepositAgingItem>(
    `/api/v1/deposits/report/aging?store_id=${encodeURIComponent(storeId)}`,
  );
}
