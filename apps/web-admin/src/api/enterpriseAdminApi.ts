/**
 * 企业挂账管理后台 API 客户端
 * 对应后端: services/tx-trade/src/api/enterprise_routes.py
 * 注意: 这是后台管理版，与 web-pos/src/api/enterpriseApi.ts 职责不同
 */
import { txFetchData } from './client';

// ─── 类型定义 ───

export interface EnterpriseAccount {
  id: string;
  name: string;
  contact: string;
  phone: string;
  credit_limit_fen: number;
  used_credit_fen: number;
  status: 'active' | 'disabled';
  billing_cycle: 'monthly' | 'bi_monthly' | 'quarterly';
  created_at: string;
}

export interface EnterpriseSigner {
  id: string;
  enterprise_id: string;
  name: string;
  employee_no: string;
  max_sign_amount_fen: number;
}

export interface EnterpriseSignRecord {
  id: string;
  enterprise_id: string;
  enterprise_name?: string;
  signer_name: string;
  amount_fen: number;
  order_id: string;
  table_no: string;
  biz_date: string;
  status: 'unpaid' | 'paid';
  notes?: string;
}

export interface EnterpriseBill {
  id: string;
  enterprise_id: string;
  enterprise_name?: string;
  month: string;
  total_fen: number;
  paid_fen: number;
  status: 'pending' | 'partial' | 'settled';
  created_at: string;
  items?: EnterpriseSignRecord[];
}

export interface EnterpriseStatement {
  enterprise_id: string;
  enterprise_name: string;
  month: string;
  total_fen: number;
  sign_records: EnterpriseSignRecord[];
  bill?: EnterpriseBill;
}

// ─── 请求参数类型 ───

export interface ListEnterprisesParams {
  page?: number;
  size?: number;
  name?: string;
  status?: string;
}

export interface CreateEnterpriseData {
  name: string;
  contact: string;
  credit_limit_fen: number;
  billing_cycle?: string;
}

export interface UpdateEnterpriseData {
  name?: string;
  contact?: string;
  credit_limit_fen?: number;
  billing_cycle?: string;
  status?: string;
}

export interface ListSignRecordsParams {
  page?: number;
  size?: number;
  status?: string;
  start_date?: string;
  end_date?: string;
}

// ─── API 函数 ───

/** 查询企业客户列表 GET /api/v1/enterprise/accounts */
export async function listEnterprises(
  params?: ListEnterprisesParams,
): Promise<{ items: EnterpriseAccount[]; total: number }> {
  const q = new URLSearchParams();
  if (params?.page) q.set('page', String(params.page));
  if (params?.size) q.set('size', String(params.size));
  if (params?.name) q.set('name', params.name);
  if (params?.status) q.set('status', params.status);
  const qs = q.toString() ? `?${q.toString()}` : '';
  return txFetchData(`/api/v1/enterprise/accounts${qs}`);
}

/** 创建企业客户 POST /api/v1/enterprise/accounts */
export async function createEnterprise(
  data: CreateEnterpriseData,
): Promise<EnterpriseAccount> {
  return txFetchData('/api/v1/enterprise/accounts', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/** 更新企业信息 PUT /api/v1/enterprise/accounts/{id} */
export async function updateEnterprise(
  id: string,
  data: UpdateEnterpriseData,
): Promise<EnterpriseAccount> {
  return txFetchData(`/api/v1/enterprise/accounts/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

/** 调整信用额度（通过 updateEnterprise）PUT /api/v1/enterprise/accounts/{id} */
export async function updateEnterpriseCreditLimit(
  id: string,
  limitFen: number,
): Promise<EnterpriseAccount> {
  return txFetchData(`/api/v1/enterprise/accounts/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ credit_limit_fen: limitFen }),
  });
}

/** 停用企业 PUT /api/v1/enterprise/accounts/{id} */
export async function disableEnterprise(id: string): Promise<EnterpriseAccount> {
  return txFetchData(`/api/v1/enterprise/accounts/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ status: 'disabled' }),
  });
}

/** 获取企业签单记录（通过对账单接口）GET /api/v1/enterprise/accounts/{id}/statement */
export async function listSignRecords(
  enterpriseId: string,
  params?: ListSignRecordsParams,
): Promise<EnterpriseStatement> {
  const month = params?.start_date?.slice(0, 7) || new Date().toISOString().slice(0, 7);
  return txFetchData(
    `/api/v1/enterprise/accounts/${enterpriseId}/statement?month=${month}`,
  );
}

/** 生成月结账单 POST /api/v1/enterprise/accounts/{id}/bills?month=YYYY-MM */
export async function monthlySettlement(
  enterpriseId: string,
  month: string,
): Promise<EnterpriseBill> {
  return txFetchData(
    `/api/v1/enterprise/accounts/${enterpriseId}/bills?month=${month}`,
    { method: 'POST' },
  );
}

/** 获取对账明细 GET /api/v1/enterprise/accounts/{id}/statement?month=YYYY-MM */
export async function getAuditTrail(
  enterpriseId: string,
  month?: string,
): Promise<EnterpriseStatement> {
  const m = month || new Date().toISOString().slice(0, 7);
  return txFetchData(
    `/api/v1/enterprise/accounts/${enterpriseId}/statement?month=${m}`,
  );
}

/** 查询企业详情 GET /api/v1/enterprise/accounts/{id} */
export async function getEnterprise(id: string): Promise<EnterpriseAccount> {
  return txFetchData(`/api/v1/enterprise/accounts/${id}`);
}
