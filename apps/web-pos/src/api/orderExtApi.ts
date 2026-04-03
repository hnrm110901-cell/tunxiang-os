/**
 * 点单扩展 API — /api/v1/trade/orders/* (扩展)
 * 拆单、合并支付、反结算、发票开具
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface SplitOrderResult {
  new_order_ids: string[];
  original_order_id: string;
}

export interface ReverseSettleResult {
  order_id: string;
  status: string;
  reversed_at: string;
}

export interface TaxInvoice {
  invoice_id: string;
  order_id: string;
  invoice_no: string;
  buyer_name: string;
  buyer_tax_no: string;
  amount_fen: number;
  status: 'pending' | 'issued' | 'failed';
  issued_at: string;
}

// ─── 接口 ───

/** 拆单结账 — 将部分菜品拆为新订单 */
export async function splitOrder(
  orderId: string,
  itemIds: string[],
): Promise<SplitOrderResult> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/split`, {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds }),
  });
}

/** 合并支付 — 多个订单合并结账 */
export async function mergePayment(
  orderIds: string[],
  method: string,
  amountFen: number,
): Promise<{ payment_id: string; merged_order_ids: string[] }> {
  return txFetch('/api/v1/trade/orders/merge-payment', {
    method: 'POST',
    body: JSON.stringify({ order_ids: orderIds, method, amount_fen: amountFen }),
  });
}

/** 反结算 — 撤销已结算订单 */
export async function reverseSettle(
  orderId: string,
  reason: string,
): Promise<ReverseSettleResult> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/reverse-settle`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

/** 申请开具发票 */
export async function requestInvoice(
  orderId: string,
  buyerName: string,
  buyerTaxNo: string,
  email?: string,
): Promise<TaxInvoice> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/invoice`, {
    method: 'POST',
    body: JSON.stringify({ buyer_name: buyerName, buyer_tax_no: buyerTaxNo, email }),
  });
}

/** 查询发票状态 */
export async function getInvoiceStatus(
  invoiceId: string,
): Promise<TaxInvoice> {
  return txFetch(`/api/v1/trade/orders/invoice/${encodeURIComponent(invoiceId)}`);
}
