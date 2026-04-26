/**
 * memberApi.ts — 调用 tx-member 会员 API
 *
 * Base URL 从环境变量读取，本地开发默认走 vite proxy → localhost:8000
 */
import type { ApiResponse, CustomerProfile, Coupon, JssdkConfig } from '../types';

const BASE = import.meta.env.VITE_API_BASE_URL ?? '';

/** 从 localStorage 读取当前租户 ID（导购登录时写入） */
function getTenantId(): string {
  return localStorage.getItem('tx_tenant_id') ?? '';
}

/** 从 localStorage 读取 JWT Token */
function getToken(): string {
  return localStorage.getItem('tx_token') ?? '';
}

/** 通用 fetch 封装，自动附带认证 header */
async function txFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<ApiResponse<T>> {
  const url = `${BASE}${path}`;
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    'X-Tenant-ID': getTenantId(),
    Authorization: `Bearer ${getToken()}`,
    ...(options.headers ?? {}),
  };

  const resp = await fetch(url, { ...options, headers });

  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  }

  return resp.json() as Promise<ApiResponse<T>>;
}

// ─────────────────────────────────────────────────────────────────
// 会员查询
// ─────────────────────────────────────────────────────────────────

/**
 * 通过企微 externalUserId 查询会员档案（旧接口，保留兼容）
 * GET /api/v1/member/customers?wecom_external_userid={id}
 */
export async function fetchCustomerByWecomId(
  externalUserId: string,
): Promise<CustomerProfile | null> {
  const result = await txFetch<{ items: CustomerProfile[]; total: number }>(
    `/api/v1/member/customers?wecom_external_userid=${encodeURIComponent(externalUserId)}&size=1`,
  );
  if (!result.ok || result.data.total === 0) return null;
  return result.data.items[0] ?? null;
}

/**
 * 通过企微 externalUserId 获取360画像（新接口）
 * GET /api/v1/member/profile360/by-wecom/{externalUserId}
 */
export async function fetchProfile360(
  externalUserId: string,
): Promise<CustomerProfile | null> {
  const result = await txFetch<CustomerProfile>(
    `/api/v1/member/profile360/by-wecom/${encodeURIComponent(externalUserId)}`,
  );
  return result.ok ? result.data : null;
}

/**
 * 通过 customer_id 查询会员完整画像
 * GET /api/v1/member/customers/{customer_id}
 */
export async function fetchCustomerById(
  customerId: string,
): Promise<CustomerProfile | null> {
  const result = await txFetch<CustomerProfile>(
    `/api/v1/member/customers/${customerId}`,
  );
  return result.ok ? result.data : null;
}

// ─────────────────────────────────────────────────────────────────
// 标签操作
// ─────────────────────────────────────────────────────────────────

/**
 * 更新客户标签
 * PATCH /api/v1/member/customers/{customer_id}/tags
 */
export async function updateCustomerTags(
  customerId: string,
  tags: string[],
): Promise<void> {
  await txFetch(`/api/v1/member/customers/${customerId}/tags`, {
    method: 'PATCH',
    body: JSON.stringify({ tags }),
  });
}

// ─────────────────────────────────────────────────────────────────
// 企微备注
// ─────────────────────────────────────────────────────────────────

/**
 * 更新导购备注
 * PATCH /api/v1/member/customers/{customer_id}/wecom
 */
export async function updateWecomRemark(
  customerId: string,
  remark: string,
): Promise<void> {
  await txFetch(`/api/v1/member/customers/${customerId}/wecom`, {
    method: 'PATCH',
    body: JSON.stringify({ wecom_remark: remark }),
  });
}

// ─────────────────────────────────────────────────────────────────
// 优惠券
// ─────────────────────────────────────────────────────────────────

/**
 * 获取可发放的优惠券列表
 * GET /api/v1/member/coupons?issuable=true
 */
export async function fetchIssuableCoupons(): Promise<Coupon[]> {
  const result = await txFetch<{ items: Coupon[]; total: number }>(
    '/api/v1/member/coupons?issuable=true&size=20',
  );
  return result.ok ? result.data.items : [];
}

/**
 * 向客户发放优惠券（旧接口，保留兼容）
 * POST /api/v1/member/coupons/issue
 */
export async function issueCoupon(
  customerId: string,
  couponId: string,
): Promise<void> {
  await txFetch('/api/v1/member/coupons/issue', {
    method: 'POST',
    body: JSON.stringify({ customer_id: customerId, coupon_id: couponId }),
  });
}

/**
 * 1v1发券（带日志追踪）
 * POST /api/v1/member/profile360/{customerId}/send-coupon
 */
export async function sendCouponWithLog(
  customerId: string,
  couponId: string,
  employeeId: string,
  storeId: string,
): Promise<{ send_id: string }> {
  const result = await txFetch<{ send_id: string }>(
    `/api/v1/member/profile360/${customerId}/send-coupon`,
    {
      method: 'POST',
      body: JSON.stringify({ coupon_id: couponId, employee_id: employeeId, store_id: storeId }),
    },
  );
  if (!result.ok) throw new Error(result.error?.message ?? '发券失败');
  return result.data;
}

// ─────────────────────────────────────────────────────────────────
// 企微 JS-SDK 配置
// ─────────────────────────────────────────────────────────────────

/**
 * 获取 JS-SDK 签名配置（用于 wx.config + wx.agentConfig）
 * GET /api/v1/wecom/jssdk-config?url={当前页面URL}
 */
export async function fetchJssdkConfig(pageUrl: string): Promise<JssdkConfig> {
  const result = await txFetch<JssdkConfig>(
    `/api/v1/wecom/jssdk-config?url=${encodeURIComponent(pageUrl)}`,
  );
  if (!result.ok) {
    throw new Error('获取企微 JS-SDK 配置失败');
  }
  return result.data;
}
