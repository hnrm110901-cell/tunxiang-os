/**
 * HR 模块 API 客户端 — 合规预警、IM 同步、绩效、积分、薪资台账
 */
import { txFetch } from './index';

// ─── A. 合规预警 ───

export interface ComplianceAlert {
  employee_id: string;
  emp_name: string;
  document_type: string;
  expiry_date: string;
  days_remaining: number;
  severity: 'critical' | 'high' | 'medium' | 'low';
  category: 'document' | 'performance' | 'attendance';
}

export interface ComplianceSummary {
  total: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface ComplianceAlertResp {
  documents: ComplianceAlert[];
  performance: ComplianceAlert[];
  attendance: ComplianceAlert[];
  summary: ComplianceSummary;
}

export async function fetchComplianceAlerts(severity?: string): Promise<ComplianceAlertResp> {
  const query = severity ? `?severity=${encodeURIComponent(severity)}` : '';
  return txFetch(`/api/v1/org/compliance/alerts${query}`);
}

export async function triggerComplianceScan(scanType: string = 'all'): Promise<ComplianceAlertResp> {
  return txFetch('/api/v1/org/compliance/scan', {
    method: 'POST',
    body: JSON.stringify({ scan_type: scanType }),
  });
}

// ─── B. IM 同步 ───

export interface IMSyncStatus {
  total_employees: number;
  wecom_bound: number;
  dingtalk_bound: number;
  unbound: number;
}

export interface IMSyncPreviewEntry {
  action: 'bind' | 'create' | 'deactivate';
  im_userid: string;
  name: string;
  phone: string;
  employee_id?: string;
}

export interface IMSyncPreview {
  to_bind: IMSyncPreviewEntry[];
  to_create: IMSyncPreviewEntry[];
  to_deactivate: IMSyncPreviewEntry[];
  unchanged: number;
}

export async function fetchIMSyncStatus(): Promise<IMSyncStatus> {
  return txFetch('/api/v1/org/im-sync/status');
}

export async function previewIMSync(
  provider: string,
  corpId: string,
  corpSecret: string,
): Promise<IMSyncPreview> {
  return txFetch('/api/v1/org/im-sync/preview', {
    method: 'POST',
    body: JSON.stringify({ provider, corp_id: corpId, corp_secret: corpSecret }),
  });
}

export async function applyIMSync(
  provider: string,
  diffId: string,
  autoCreate: boolean = false,
): Promise<{ bound: number; created: number; deactivated: number; errors: string[] }> {
  return txFetch('/api/v1/org/im-sync/apply', {
    method: 'POST',
    body: JSON.stringify({ provider, diff_id: diffId, auto_create: autoCreate }),
  });
}

// ─── C. 绩效打分 ───

export interface PerformanceScoreItem {
  employee_id: string;
  emp_name: string;
  position: string;
  store_name: string;
  score: number;
  service_score: number;
  sales_score: number;
  attendance_score: number;
  skill_score: number;
  rank: number;
  month: string;
}

export async function fetchPerformanceScores(
  storeId?: string,
  month?: string,
): Promise<{ items: PerformanceScoreItem[]; total: number }> {
  const params = new URLSearchParams();
  if (storeId) params.set('store_id', storeId);
  if (month) params.set('month', month);
  const query = params.toString() ? `?${params.toString()}` : '';
  return txFetch(`/api/v1/org/performance/scores${query}`);
}

export async function submitPerformanceScore(
  employeeId: string,
  month: string,
  scores: Record<string, number>,
): Promise<{ weighted_total: number; rank_hint: string }> {
  return txFetch('/api/v1/org/performance/scores', {
    method: 'POST',
    body: JSON.stringify({ employee_id: employeeId, month, scores }),
  });
}

// ─── D. 员工积分 ───

export interface EmployeePoints {
  employee_id: string;
  emp_name: string;
  total_points: number;
  monthly_points: number;
  rank: number;
  level: string;
  recent_actions: Array<{ action: string; points: number; date: string }>;
}

export async function fetchEmployeePoints(
  storeId?: string,
): Promise<{ items: EmployeePoints[]; total: number }> {
  const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : '';
  return txFetch(`/api/v1/org/points/leaderboard${query}`);
}

// ─── E. 薪资台账 ───

export interface PayslipDetail {
  id: string;
  employee_id: string;
  emp_name: string;
  month: string;
  items: Array<{ item_code: string; item_name: string; amount_fen: number }>;
  gross_fen: number;
  deduction_fen: number;
  social_fen: number;
  tax_fen: number;
  net_fen: number;
  status: 'draft' | 'confirmed' | 'paid';
}

export async function fetchPayslips(
  storeId: string,
  month: string,
  page?: number,
): Promise<{ items: PayslipDetail[]; total: number }> {
  return txFetch(
    `/api/v1/payroll/payslips?store_id=${encodeURIComponent(storeId)}&month=${encodeURIComponent(month)}&page=${page || 1}&size=20`,
  );
}

export async function fetchMyPayslip(month: string): Promise<PayslipDetail> {
  return txFetch(`/api/v1/payroll/my-payslip?month=${encodeURIComponent(month)}`);
}
