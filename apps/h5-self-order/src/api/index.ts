/**
 * H5 自助点餐 — fetch 封装
 * 自动携带 X-Tenant-ID / Accept-Language / Authorization
 */

const BASE_URL = import.meta.env.VITE_API_BASE ?? '';

let _tenantId = '';
let _lang = 'zh';
let _token = '';

export function setApiTenantId(id: string) { _tenantId = id; }
export function setApiLang(lang: string) { _lang = lang; }
export function setApiToken(token: string) { _token = token; }

interface ApiResponse<T> {
  ok: boolean;
  data: T;
  error?: { code: string; message: string };
}

export async function txFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept-Language': _lang,
    ...(options.headers as Record<string, string> ?? {}),
  };
  if (_tenantId) headers['X-Tenant-ID'] = _tenantId;
  if (_token) headers['Authorization'] = `Bearer ${_token}`;

  const res = await fetch(`${BASE_URL}/api/v1${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }

  const body: ApiResponse<T> = await res.json();
  if (!body.ok) {
    const err = body.error ?? { code: 'UNKNOWN', message: 'Unknown error' };
    throw new Error(`[${err.code}] ${err.message}`);
  }
  return body.data;
}
