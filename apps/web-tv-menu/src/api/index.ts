/**
 * 电视点菜墙 — API 请求封装
 * 所有请求统一带 X-Tenant-ID header
 */

const BASE_URL = '/api/v1/tv-menu';

/** 从URL参数或localStorage获取租户ID */
function getTenantId(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get('tenantId') || localStorage.getItem('tx-tenant-id') || 'default';
}

/** 从URL参数或localStorage获取门店ID */
export function getStoreId(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get('storeId') || localStorage.getItem('tx-store-id') || 'store-001';
}

interface TvApiResponse<T = unknown> {
  ok: boolean;
  data: T;
  error?: { code: string; message: string };
}

export async function tvFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const tenantId = getTenantId();

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': tenantId,
      ...options.headers,
    },
  });

  if (!res.ok) {
    throw new Error(`API Error: ${res.status} ${res.statusText}`);
  }

  const json: TvApiResponse<T> = await res.json();

  if (!json.ok) {
    throw new Error(json.error?.message || 'Unknown API error');
  }

  return json.data;
}
