/**
 * 员工类型 — 对应 shared/ontology/src/entities.py Employee
 * 角色, 技能, 排班, 业绩提成, 效率指标
 */
import type { TenantEntity, PaginatedResponse, PaginationParams } from './common';
import type { EmploymentStatus, EmploymentType, EmployeeRole } from './enums';

// ─────────────────────────────────────────────
// 核心实体
// ─────────────────────────────────────────────

/** 员工 */
export interface Employee extends TenantEntity {
  store_id: string;
  emp_name: string;
  phone: string | null;
  email: string | null;
  role: EmployeeRole;
  skills: string[] | null;

  // 雇佣信息
  hire_date: string | null;
  employment_status: EmploymentStatus;
  employment_type: EmploymentType;
  is_active: boolean;
  probation_end_date: string | null;
  grade_level: string | null;

  // IM 绑定
  wechat_userid: string | null;
  dingtalk_userid: string | null;

  // 个人信息
  gender: string | null;
  birth_date: string | null;
  education: string | null;

  // 证照（敏感字段前端不展示原文）
  health_cert_expiry: string | null;
  health_cert_attachment: string | null;
  id_card_expiry: string | null;
  background_check: string | null;

  // 薪酬
  daily_wage_standard_fen: number | null;
  work_hour_type: string | null;
  first_work_date: string | null;
  regular_date: string | null;
  seniority_months: number | null;

  // 紧急联系人
  emergency_contact: string | null;
  emergency_phone: string | null;
  emergency_relation: string | null;

  // 组织
  org_id: string | null;
  preferences: Record<string, unknown> | null;
  performance_score: string | null;
}

// ─────────────────────────────────────────────
// 请求类型
// ─────────────────────────────────────────────

/** 创建员工请求 */
export interface CreateEmployeeRequest {
  store_id: string;
  emp_name: string;
  phone?: string;
  email?: string;
  role: EmployeeRole;
  skills?: string[];
  hire_date?: string;
  employment_type?: EmploymentType;
  gender?: string;
  birth_date?: string;
  education?: string;
  health_cert_expiry?: string;
  health_cert_attachment?: string;
  id_card_no?: string;
  id_card_expiry?: string;
  daily_wage_standard_fen?: number;
  work_hour_type?: string;
  emergency_contact?: string;
  emergency_phone?: string;
  emergency_relation?: string;
  org_id?: string;
}

/** 更新员工请求 */
export interface UpdateEmployeeRequest {
  emp_name?: string;
  phone?: string;
  email?: string;
  role?: EmployeeRole;
  skills?: string[];
  employment_status?: EmploymentStatus;
  employment_type?: EmploymentType;
  is_active?: boolean;
  grade_level?: string;
  health_cert_expiry?: string;
  health_cert_attachment?: string;
  id_card_expiry?: string;
  background_check?: string;
  daily_wage_standard_fen?: number;
  work_hour_type?: string;
  emergency_contact?: string;
  emergency_phone?: string;
  emergency_relation?: string;
  org_id?: string;
  preferences?: Record<string, unknown>;
  performance_score?: string;
}

/** 员工列表查询参数 */
export interface EmployeeListParams extends PaginationParams {
  store_id?: string;
  role?: EmployeeRole;
  employment_status?: EmploymentStatus;
  is_active?: boolean;
  keyword?: string;
}

// ─────────────────────────────────────────────
// 响应类型
// ─────────────────────────────────────────────

export type EmployeeListResponse = PaginatedResponse<Employee>;
