/**
 * 企业挂账 API — /api/v1/enterprise/*
 * 搜索企业客户、查额度、挂账签单、挂账记录查询
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface EnterpriseCustomer {
  enterprise_id: string;
  name: string;
  contact_person: string;
  credit_limit_fen: number;
  used_fen: number;
  status: 'active' | 'frozen';
}

export interface CreditRecord {
  record_id: string;
  enterprise_id: string;
  enterprise_name: string;
  order_id: string;
  order_no: string;
  amount_fen: number;
  signer_name: string;
  created_at: string;
  settled: boolean;
}

// ─── 接口 ───

/** 搜索企业客户（按名称或ID关键字） */
export async function searchEnterprise(
  keyword: string,
): Promise<{ items: EnterpriseCustomer[] }> {
  return txFetch(`/api/v1/enterprise/search?keyword=${encodeURIComponent(keyword)}`);
}

/** 获取企业客户详情（含额度） */
export async function getEnterpriseDetail(
  enterpriseId: string,
): Promise<EnterpriseCustomer> {
  return txFetch(`/api/v1/enterprise/${encodeURIComponent(enterpriseId)}`);
}

/** 企业挂账签单 */
export async function createCreditCharge(
  orderId: string,
  enterpriseId: string,
  amountFen: number,
  signerName: string,
): Promise<{ record_id: string; remaining_credit_fen: number }> {
  return txFetch('/api/v1/enterprise/charge', {
    method: 'POST',
    body: JSON.stringify({
      order_id: orderId,
      enterprise_id: enterpriseId,
      amount_fen: amountFen,
      signer_name: signerName,
    }),
  });
}

/** 查询企业挂账记录 */
export async function fetchCreditRecords(
  enterpriseId: string,
  page = 1,
  size = 20,
): Promise<{ items: CreditRecord[]; total: number }> {
  return txFetch(
    `/api/v1/enterprise/${encodeURIComponent(enterpriseId)}/records?page=${page}&size=${size}`,
  );
}

/** 企业挂账结算（批量核销） */
export async function settleCredit(
  enterpriseId: string,
  recordIds: string[],
): Promise<{ settled_count: number; total_fen: number }> {
  return txFetch(`/api/v1/enterprise/${encodeURIComponent(enterpriseId)}/settle`, {
    method: 'POST',
    body: JSON.stringify({ record_ids: recordIds }),
  });
}
