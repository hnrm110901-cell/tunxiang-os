/**
 * 储值充值 API — /api/v1/members/{member_id}/stored-value
 * 充值 / 消费 / 退款 / 交易明细
 */
import { txFetch } from './index';

// ─── 类型 ───

export type StoredValueTxnType = 'recharge' | 'consume' | 'refund' | 'adjustment' | 'expire';

export interface StoredValueTransaction {
  id: string;
  type: StoredValueTxnType;
  amount_fen: number;
  balance_before_fen: number | null;
  balance_after_fen: number | null;
  operator_id: string | null;
  note: string | null;
  payment_method: string | null;
  order_id: string | null;
  created_at: string;
}

export interface StoredValueAccount {
  account_id: string;
  member_id: string;
  balance_fen: number;
  frozen_fen: number;
  total_recharged_fen: number;
  total_consumed_fen: number;
  transactions: StoredValueTransaction[];
}

export interface RechargeResult {
  transaction_id: string;
  amount_fen: number;
  bonus_fen: number;
  total_credited_fen: number;
  balance_after_fen: number;
}

export interface ConsumeResult {
  success: boolean;
  transaction_id?: string;
  balance_after_fen: number;
  insufficient_fen: number;
}

export interface RefundResult {
  transaction_id: string;
  refunded_fen: number;
  balance_after_fen: number;
}

// ─── 接口 ───

/** 获取储值账户余额及最近20条交易 */
export async function getStoredValue(memberId: string): Promise<StoredValueAccount> {
  return txFetch(`/api/v1/members/${encodeURIComponent(memberId)}/stored-value`);
}

/** 充值 */
export async function rechargeStoredValue(
  memberId: string,
  payload: {
    amount_fen: number;
    payment_method: 'cash' | 'wechat' | 'alipay' | 'card';
    operator_id: string;
    note?: string;
    external_payment_id?: string;
  },
): Promise<RechargeResult> {
  return txFetch(`/api/v1/members/${encodeURIComponent(memberId)}/stored-value/recharge`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 消费扣款 */
export async function consumeStoredValue(
  memberId: string,
  payload: {
    amount_fen: number;
    order_id: string;
    operator_id: string;
  },
): Promise<ConsumeResult> {
  return txFetch(`/api/v1/members/${encodeURIComponent(memberId)}/stored-value/consume`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 退款回储值账户 */
export async function refundToStoredValue(
  memberId: string,
  payload: {
    transaction_id: string;
    amount_fen: number;
    reason: string;
    operator_id: string;
  },
): Promise<RefundResult> {
  return txFetch(`/api/v1/members/${encodeURIComponent(memberId)}/stored-value/refund`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 根据充值金额计算赠送金额（前端预览，与后端规则同步） */
export function calcBonus(amountFen: number): number {
  if (amountFen >= 300_000) return 50_000;
  if (amountFen >= 200_000) return 30_000;
  if (amountFen >= 100_000) return 15_000;
  if (amountFen >= 50_000) return 5_000;
  return 0;
}
