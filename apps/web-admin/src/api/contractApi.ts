/**
 * 电子签约 API 客户端
 * 域F - 组织人事 - 合同模板管理 + 签署流程
 *
 * API 前缀: /api/v1/e-signature
 */
import { txFetchData } from './index';

// ─── Types ──────────────────────────────────────────────

export interface ContractTemplate {
  id: string;
  template_name: string;
  contract_type: string;
  contract_type_label: string;
  content_html: string;
  variables: Array<{ key: string; label: string; required?: boolean }>;
  is_active: boolean;
  version: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SigningRecord {
  id: string;
  template_id: string;
  employee_id: string;
  employee_name: string;
  store_id: string | null;
  contract_no: string;
  contract_type: string;
  contract_type_label: string;
  status: 'draft' | 'pending_sign' | 'employee_signed' | 'completed' | 'expired' | 'terminated';
  status_label: string;
  signed_at: string | null;
  company_signed_at: string | null;
  company_signer_id: string | null;
  start_date: string | null;
  end_date: string | null;
  expire_remind_days: number;
  created_at: string;
  updated_at: string;
}

export interface SigningRecordDetail extends SigningRecord {
  content_snapshot: string | null;
  variables_filled: Record<string, unknown>;
  e_sign_doc_id: string | null;
  metadata: Record<string, unknown>;
}

export interface ExpiringContract {
  id: string;
  employee_id: string;
  employee_name: string;
  contract_no: string;
  contract_type: string;
  contract_type_label: string;
  store_id: string | null;
  start_date: string;
  end_date: string;
  days_remaining: number;
}

export interface ContractStats {
  total: number;
  completed: number;
  pending: number;
  terminated: number;
  expired: number;
  expiring_30d: number;
}

// ─── 模板 API ───────────────────────────────────────────

export async function createContractTemplate(data: {
  template_name: string;
  contract_type: string;
  content_html?: string;
  variables?: Array<{ key: string; label: string; required?: boolean }>;
  created_by?: string;
}): Promise<ContractTemplate> {
  return txFetchData('/api/v1/e-signature/templates', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function fetchContractTemplates(params?: {
  contract_type?: string;
  page?: number;
  size?: number;
}): Promise<{ items: ContractTemplate[]; total: number }> {
  const qs = new URLSearchParams();
  if (params?.contract_type) qs.set('contract_type', params.contract_type);
  if (params?.page) qs.set('page', String(params.page));
  if (params?.size) qs.set('size', String(params.size));
  const q = qs.toString() ? `?${qs}` : '';
  return txFetchData(`/api/v1/e-signature/templates${q}`);
}

export async function fetchContractTemplate(id: string): Promise<ContractTemplate> {
  return txFetchData(`/api/v1/e-signature/templates/${encodeURIComponent(id)}`);
}

export async function updateContractTemplate(
  id: string,
  data: Partial<{
    template_name: string;
    contract_type: string;
    content_html: string;
    variables: Array<{ key: string; label: string; required?: boolean }>;
    is_active: boolean;
  }>,
): Promise<ContractTemplate> {
  return txFetchData(`/api/v1/e-signature/templates/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

// ─── 签署 API ───────────────────────────────────────────

export async function initiateContractSigning(data: {
  template_id: string;
  employee_id: string;
  start_date: string;
  end_date: string;
  variables_filled?: Record<string, unknown>;
  store_id?: string;
}): Promise<{ id: string; contract_no: string; status: string; employee_name: string }> {
  return txFetchData('/api/v1/e-signature/signing/initiate', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function employeeSignContract(id: string): Promise<SigningRecord> {
  return txFetchData(`/api/v1/e-signature/signing/${encodeURIComponent(id)}/employee-sign`, {
    method: 'PUT',
  });
}

export async function companySignContract(
  id: string,
  signerId: string,
): Promise<SigningRecord> {
  return txFetchData(`/api/v1/e-signature/signing/${encodeURIComponent(id)}/company-sign`, {
    method: 'PUT',
    body: JSON.stringify({ signer_id: signerId }),
  });
}

export async function terminateContract(
  id: string,
  reason: string,
): Promise<SigningRecord> {
  return txFetchData(`/api/v1/e-signature/signing/${encodeURIComponent(id)}/terminate`, {
    method: 'PUT',
    body: JSON.stringify({ reason }),
  });
}

export async function fetchSigningRecords(params?: {
  employee_id?: string;
  status?: string;
  contract_type?: string;
  page?: number;
  size?: number;
}): Promise<{ items: SigningRecord[]; total: number }> {
  const qs = new URLSearchParams();
  if (params?.employee_id) qs.set('employee_id', params.employee_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.contract_type) qs.set('contract_type', params.contract_type);
  if (params?.page) qs.set('page', String(params.page));
  if (params?.size) qs.set('size', String(params.size));
  const q = qs.toString() ? `?${qs}` : '';
  return txFetchData(`/api/v1/e-signature/signing${q}`);
}

export async function fetchSigningDetail(id: string): Promise<SigningRecordDetail> {
  return txFetchData(`/api/v1/e-signature/signing/${encodeURIComponent(id)}`);
}

// ─── 到期提醒 + 统计 ────────────────────────────────────

export async function fetchExpiringContracts(days = 30): Promise<ExpiringContract[]> {
  return txFetchData(`/api/v1/e-signature/expiring?days=${days}`);
}

export async function fetchContractStats(): Promise<ContractStats> {
  return txFetchData('/api/v1/e-signature/stats');
}
